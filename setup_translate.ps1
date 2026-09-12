<#
.SYNOPSIS
    Sets up everything needed to translate the book on another Windows machine.

.DESCRIPTION
    Installs Ollama, picks a translation model that fits the GPU, creates a Python
    virtual environment with the project's dependencies, and checks that all of it
    actually works. Safe to run more than once - every step is skipped if already done.

.PARAMETER PagesSource
    Folder or .zip holding the OCR'd pages (pNNNN.md). Defaults to ocr_out\pages if it
    is already next to this script.

.PARAMETER Model
    Force a specific Ollama model instead of choosing one by GPU memory.

.EXAMPLE
    .\setup_translate.ps1
    .\setup_translate.ps1 -PagesSource D:\downloads\book_pages.zip
    .\setup_translate.ps1 -Model gemma3:27b
#>
[CmdletBinding()]
param(
    [string]$PagesSource,
    [string]$Model,
    [switch]$SkipModelPull,
    # Share of VRAM the translator may take. The rest is left for the desktop, so the
    # machine stays usable and nothing gets pushed out of memory mid-run.
    [ValidateRange(0.3, 1.0)]
    [double]$GpuUtilization = 0.8,
    # Where model blobs live. Ollama defaults to the system drive, which is usually the
    # one without room for several gigabytes of weights.
    [string]$ModelsDir
)

# Deliberately NOT 'Stop': under Windows PowerShell 5.1 anything a native program writes
# to stderr becomes a terminating error, so winget, ollama or python printing a harmless
# notice would kill the script. Failures are checked explicitly instead.
$ErrorActionPreference = 'Continue'
$root = $PSScriptRoot
if (-not $root) { $root = (Get-Location).Path }

function Find-Python {
    <#
      Returns a usable Python 3.10+ interpreter, or $null.
      The `python` on a clean Windows is usually the Microsoft Store alias: a stub that
      prints a notice and exits, so it has to be skipped rather than probed.
    #>
    $candidates = @()
    $launcher = Get-Command py -ErrorAction SilentlyContinue
    if ($launcher) { $candidates += $launcher.Source }
    foreach ($name in @('python', 'python3')) {
        foreach ($cmd in (Get-Command $name -All -ErrorAction SilentlyContinue)) {
            if ($cmd.Source -and $cmd.Source -notlike '*\WindowsApps\*') {
                $candidates += $cmd.Source
            }
        }
    }
    foreach ($exe in ($candidates | Select-Object -Unique)) {
        $ver = $null
        try { $ver = & $exe -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null }
        catch { continue }
        if ($ver -and ($ver -match '^\d+\.\d+$') -and [version]$ver -ge [version]'3.10') {
            return $exe
        }
    }
    return $null
}

function Step($text) { Write-Host "`n=== $text ===" -ForegroundColor Cyan }
function Good($text) { Write-Host "  [ok] $text" -ForegroundColor Green }
function Warn($text) { Write-Host "  [!] $text" -ForegroundColor Yellow }
function Die($text)  { Write-Host "  [x] $text" -ForegroundColor Red; exit 1 }

# ---------------------------------------------------------------- prerequisites
Step "Checking prerequisites"

if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
    Die "winget not found. Install 'App Installer' from the Microsoft Store, then re-run."
}
Good "winget present"

$python = Find-Python
if (-not $python) {
    Warn "Python 3.10+ not found - installing Python 3.12"
    winget install --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements --disable-interactivity
    $env:Path = [System.Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' +
                [System.Environment]::GetEnvironmentVariable('Path', 'User')
    $python = Find-Python
    if (-not $python) {
        Die "Python installed but not visible yet. Close this window, open a new PowerShell and re-run."
    }
}
Good "Python: $python"

# ---------------------------------------------------------------------- the GPU
Step "Looking at the GPU"

$vramGb = 0
$gpuName = 'none detected'
$smi = Get-Command nvidia-smi -ErrorAction SilentlyContinue
if ($smi) {
    $line = & nvidia-smi --query-gpu=name,memory.total --format=csv,noheader,nounits 2>$null | Select-Object -First 1
    if ($line) {
        $parts = $line -split ',\s*'
        $gpuName = $parts[0]
        $vramGb = [math]::Round([double]$parts[1] / 1024, 1)
    }
} else {
    $video = Get-CimInstance Win32_VideoController | Select-Object -First 1
    if ($video) { $gpuName = $video.Name }
}
Write-Host "  GPU: $gpuName, VRAM: $vramGb GB"

# Budget, not the whole card: the reserved slice keeps the desktop responsive and stops
# the model being evicted halfway through a long run.
$usableGb = [math]::Round($vramGb * $GpuUtilization, 1)
$reserveBytes = [int64](($vramGb - $usableGb) * 1GB)
if ($vramGb -gt 0) {
    Write-Host ("  budget: {0} GB for the model, {1} GB left free ({2:P0} cap)" -f `
                $usableGb, [math]::Round($vramGb - $usableGb, 1), $GpuUtilization)
}

# The model must fit the budget. If it does not, Ollama spills layers onto the CPU and
# generation slows by roughly an order of magnitude.
if (-not $Model) {
    if     ($usableGb -ge 18) { $Model = 'gemma3:27b' }   # ~17 GB on disk
    elseif ($usableGb -ge 9)  { $Model = 'gemma3:12b' }   # ~8.1 GB
    elseif ($usableGb -ge 4)  { $Model = 'gemma3:4b'  }   # ~3.3 GB
    else                      { $Model = 'gemma3:4b'  }
}
Good "translation model: $Model"
if (-not $smi) {
    Warn "No NVIDIA GPU detected - VRAM could not be read, defaulting to a small model."
} elseif ($vramGb -lt 6) {
    Warn "Under 6 GB of VRAM - expect roughly 30s per page; a bigger card is much faster."
}

# ------------------------------------------------------------------------ ollama
Step "Ollama"

$ollamaExe = "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe"
if (-not (Test-Path $ollamaExe)) {
    $onPath = Get-Command ollama -ErrorAction SilentlyContinue
    if ($onPath) { $ollamaExe = $onPath.Source }
}
if (-not (Test-Path $ollamaExe)) {
    Warn "installing Ollama"
    winget install --id Ollama.Ollama --accept-source-agreements --accept-package-agreements --disable-interactivity
    $ollamaExe = "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe"
}
if (-not (Test-Path $ollamaExe)) { Die "Ollama did not install. Get it from https://ollama.com/download" }
Good "ollama: $ollamaExe"

# one model at a time: parallel slots split VRAM and make everything slower
[Environment]::SetEnvironmentVariable('OLLAMA_NUM_PARALLEL', '1', 'User')
[Environment]::SetEnvironmentVariable('OLLAMA_KEEP_ALIVE', '30m', 'User')
$env:OLLAMA_NUM_PARALLEL = '1'
$env:OLLAMA_KEEP_ALIVE = '30m'

$overheadChanged = $false

# Models are gigabytes each and Ollama puts them on the system drive by default. Moving
# the store is a matter of one variable plus relocating whatever is already there.
if ($ModelsDir) {
    New-Item -ItemType Directory -Force -Path $ModelsDir | Out-Null
    $defaultStore = Join-Path $env:USERPROFILE '.ollama\models'
    if ((Test-Path $defaultStore) -and -not (Get-ChildItem $ModelsDir -ErrorAction SilentlyContinue)) {
        $gb = [math]::Round(((Get-ChildItem $defaultStore -Recurse -File -ErrorAction SilentlyContinue |
                              Measure-Object -Property Length -Sum).Sum / 1GB), 2)
        Warn "moving $gb GB of existing models to $ModelsDir"
        Get-Process -Name 'ollama', 'ollama app' -ErrorAction SilentlyContinue |
            Stop-Process -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 2
        Move-Item (Join-Path $defaultStore '*') $ModelsDir -Force -ErrorAction SilentlyContinue
        $overheadChanged = $true
    }
    $previousDir = [Environment]::GetEnvironmentVariable('OLLAMA_MODELS', 'User')
    if ("$previousDir" -ne "$ModelsDir") { $overheadChanged = $true }
    [Environment]::SetEnvironmentVariable('OLLAMA_MODELS', $ModelsDir, 'User')
    $env:OLLAMA_MODELS = $ModelsDir
    Good "model store: $ModelsDir"
}

# Hold back the rest of the card. OLLAMA_GPU_OVERHEAD is read when the server starts,
# so a server already running with a different value has to be restarted.
if ($reserveBytes -gt 0) {
    $previous = [Environment]::GetEnvironmentVariable('OLLAMA_GPU_OVERHEAD', 'User')
    if ("$previous" -ne "$reserveBytes") { $overheadChanged = $true }
    [Environment]::SetEnvironmentVariable('OLLAMA_GPU_OVERHEAD', "$reserveBytes", 'User')
    $env:OLLAMA_GPU_OVERHEAD = "$reserveBytes"
    Good ("reserving {0} GB of VRAM for everything else" -f [math]::Round($reserveBytes / 1GB, 1))
}

$up = $false
for ($i = 0; $i -lt 3; $i++) {
    try { Invoke-RestMethod http://127.0.0.1:11434/api/version -TimeoutSec 4 | Out-Null; $up = $true; break }
    catch { Start-Sleep -Seconds 2 }
}

if ($up -and $overheadChanged) {
    Warn "restarting the Ollama server so the VRAM reservation takes effect"
    Get-Process -Name 'ollama' -ErrorAction SilentlyContinue | Stop-Process -Force
    Start-Sleep -Seconds 3
    $up = $false
}
if (-not $up) {
    Warn "starting the Ollama server"
    Start-Process -FilePath $ollamaExe -ArgumentList 'serve' -WindowStyle Hidden `
        -RedirectStandardOutput "$root\ollama_serve.log" -RedirectStandardError "$root\ollama_serve.err"
    for ($i = 0; $i -lt 20; $i++) {
        try { Invoke-RestMethod http://127.0.0.1:11434/api/version -TimeoutSec 4 | Out-Null; $up = $true; break }
        catch { Start-Sleep -Seconds 3 }
    }
}
if (-not $up) { Die "Ollama server is not answering on port 11434." }
Good "server is up"

if (-not $SkipModelPull) {
    $have = (& $ollamaExe list) -join "`n"
    if ($have -notmatch [regex]::Escape($Model)) {
        Write-Host "  pulling $Model (this is a few GB, one time)..."
        & $ollamaExe pull $Model
        if ($LASTEXITCODE -ne 0) { Die "could not pull $Model" }
    }
    Good "$Model ready"
}

# ------------------------------------------------------------- python environment
Step "Python environment"

$venv = Join-Path $root '.venv-translate'
$venvPy = Join-Path $venv 'Scripts\python.exe'
if (-not (Test-Path $venvPy)) {
    & $python -m venv $venv
}
if (-not (Test-Path $venvPy)) { Die "could not create the virtual environment at $venv" }

& $venvPy -m pip install --quiet --upgrade pip
# exactly what the translator imports - nothing for PDF building, which is not
# needed here: the job is to produce translated markdown, not a rendered book
& $venvPy -m pip install --quiet requests python-dotenv pypdf tqdm
if ($LASTEXITCODE -ne 0) { Die "dependency installation failed" }
Good "venv ready: $venv"

# -------------------------------------------------------------------- book pages
Step "Book pages"

$pagesDir = Join-Path $root 'ocr_out\pages'
if ($PagesSource) {
    if ($PagesSource -like '*.zip') {
        Warn "unpacking $PagesSource"
        $target = Join-Path $root 'ocr_out'
        New-Item -ItemType Directory -Force -Path $target | Out-Null
        Expand-Archive -Path $PagesSource -DestinationPath $target -Force
    } elseif (Test-Path $PagesSource) {
        New-Item -ItemType Directory -Force -Path $pagesDir | Out-Null
        Copy-Item (Join-Path $PagesSource '*.md') $pagesDir -Force
    } else {
        Die "PagesSource not found: $PagesSource"
    }
}

if (Test-Path $pagesDir) {
    $count = (Get-ChildItem $pagesDir -Filter 'p*.md' -ErrorAction SilentlyContinue).Count
    if ($count -gt 0) { Good "$count pages found in $pagesDir" }
    else { Warn "no pNNNN.md files in $pagesDir - pass -PagesSource with the pages" }
} else {
    Warn "no $pagesDir yet - pass -PagesSource with the folder or zip of pages"
}

# -------------------------------------------------------------------- smoke test
Step "Smoke test"

$probe = @'
import json, sys, urllib.request
body = json.dumps({"model": sys.argv[1],
                   "prompt": "Translate into Ukrainian, output only the translation: The heat equation describes diffusion.",
                   "stream": False,
                   "options": {"temperature": 0.1}}).encode()
req = urllib.request.Request("http://127.0.0.1:11434/api/generate", body,
                             {"Content-Type": "application/json"})
out = json.loads(urllib.request.urlopen(req, timeout=300).read())["response"].strip()
print(out[:160])
uk = sum(ch in "\u0456\u0457\u0454\u0491" for ch in out.lower())
ru = sum(ch in "\u044b\u044d\u044a\u0451" for ch in out.lower())
print(f"ukrainian-only letters: {uk}, russian-only letters: {ru}")
sys.exit(0 if uk > 0 and ru == 0 else 1)
'@
$probePath = Join-Path $env:TEMP 'translate_probe.py'
Set-Content -Path $probePath -Value $probe -Encoding utf8
& $venvPy $probePath $Model
if ($LASTEXITCODE -eq 0) { Good "the model translates into Ukrainian" }
else { Warn "the smoke test did not look like clean Ukrainian - check the model choice" }

# ------------------------------------------------------------------------- done
Step "Ready"
Write-Host @"
  Translate a few pages first:

    $venvPy ocr\translate_book.py --backend ollama --model $Model --pages 30,41,51,105,190

  Then the whole book (resumable - re-run the same line after any interruption):

    $venvPy ocr\translate_book.py --backend ollama --model $Model

  Results land in translated_uk\pages, anything that failed verification in
  translated_uk\rejected.
"@ -ForegroundColor Cyan
