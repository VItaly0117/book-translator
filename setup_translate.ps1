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
    [switch]$SkipModelPull
)

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
if (-not $root) { $root = (Get-Location).Path }

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

$python = $null
foreach ($candidate in @('python', 'py')) {
    $cmd = Get-Command $candidate -ErrorAction SilentlyContinue
    if ($cmd) {
        $ver = & $cmd.Source -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
        if ($ver -and [version]$ver -ge [version]'3.10') { $python = $cmd.Source; break }
    }
}
if (-not $python) {
    Warn "Python 3.10+ not found - installing Python 3.12"
    winget install --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements --disable-interactivity
    $env:Path = [System.Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' +
                [System.Environment]::GetEnvironmentVariable('Path', 'User')
    $python = (Get-Command python -ErrorAction SilentlyContinue).Source
    if (-not $python) { Die "Python still not on PATH. Open a new terminal and re-run." }
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

# Model choice follows VRAM: the whole model must fit or generation falls back to CPU
# and slows down by roughly an order of magnitude.
if (-not $Model) {
    if     ($vramGb -ge 20) { $Model = 'gemma3:27b' }
    elseif ($vramGb -ge 11) { $Model = 'gemma3:12b' }
    elseif ($vramGb -ge 6)  { $Model = 'gemma3:12b' }
    else                    { $Model = 'gemma3:4b'  }
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

$up = $false
for ($i = 0; $i -lt 3; $i++) {
    try { Invoke-RestMethod http://127.0.0.1:11434/api/version -TimeoutSec 4 | Out-Null; $up = $true; break }
    catch { Start-Sleep -Seconds 2 }
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
