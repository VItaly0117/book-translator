<#
.SYNOPSIS
    Removes everything the translation setup put on this machine.

.DESCRIPTION
    Undoes setup_translate.ps1: the pulled models and their blobs, the Ollama install,
    the environment variables, and the virtual environment. Shows exactly what it is
    about to delete and how much space that frees, then asks before doing it.

    The translated pages are NOT deleted unless you ask for it with -IncludeResults -
    send them off the machine first.

.PARAMETER Force
    Skip the confirmation prompt.

.PARAMETER KeepOllama
    Remove the models but leave Ollama itself installed.

.PARAMETER IncludeResults
    Also delete translated_uk (the translation output). Off by default on purpose.

.PARAMETER RemovePython
    Also uninstall Python. Off by default - it may have been there before, or be in use
    by something else.

.EXAMPLE
    .\cleanup_translate.ps1
    .\cleanup_translate.ps1 -Force -IncludeResults
#>
[CmdletBinding()]
param(
    [switch]$Force,
    [switch]$KeepOllama,
    [switch]$IncludeResults,
    [switch]$RemovePython
)

$ErrorActionPreference = 'Continue'
$root = $PSScriptRoot
if (-not $root) { $root = (Get-Location).Path }

function Step($t) { Write-Host "`n=== $t ===" -ForegroundColor Cyan }
function Good($t) { Write-Host "  [ok] $t" -ForegroundColor Green }
function Warn($t) { Write-Host "  [!] $t" -ForegroundColor Yellow }

function Get-SizeGb($path) {
    if (-not (Test-Path $path)) { return 0 }
    try {
        $bytes = (Get-ChildItem $path -Recurse -File -ErrorAction SilentlyContinue |
                  Measure-Object -Property Length -Sum).Sum
        return [math]::Round(($bytes / 1GB), 2)
    } catch { return 0 }
}

# ------------------------------------------------------------------ what is here
Step "What is on this machine"

$venv       = Join-Path $root '.venv-translate'
$ollamaHome = Join-Path $env:USERPROFILE '.ollama'
$ollamaProg = Join-Path $env:LOCALAPPDATA 'Programs\Ollama'
$results    = Join-Path $root 'translated_uk'

$plan = @()
foreach ($item in @(
    @{ Path = $venv;       Label = 'Python virtual environment' },
    @{ Path = $ollamaHome; Label = 'Ollama models and blobs' },
    @{ Path = $ollamaProg; Label = 'Ollama program files' }
)) {
    if (Test-Path $item.Path) {
        $gb = Get-SizeGb $item.Path
        $plan += [pscustomobject]@{ Path = $item.Path; Label = $item.Label; Gb = $gb }
    }
}
if ($IncludeResults -and (Test-Path $results)) {
    $plan += [pscustomobject]@{ Path = $results; Label = 'TRANSLATED PAGES'; Gb = (Get-SizeGb $results) }
}

if ($plan.Count -eq 0) {
    Good "nothing left to remove"
} else {
    foreach ($p in $plan) {
        Write-Host ("  {0,-30} {1,6} GB  {2}" -f $p.Label, $p.Gb, $p.Path)
    }
    Write-Host ("  total: {0} GB" -f [math]::Round(($plan | Measure-Object -Property Gb -Sum).Sum, 2))
}

# the results are easy to lose and impossible to get back without another full run
if ((Test-Path $results) -and -not $IncludeResults) {
    $pages = (Get-ChildItem (Join-Path $results 'pages') -Filter 'p*.md' -ErrorAction SilentlyContinue).Count
    Warn "keeping $results ($pages translated pages) - copy it off this machine first"
    Warn "pass -IncludeResults if you really want it gone too"
}

if (-not $Force -and $plan.Count -gt 0) {
    $answer = Read-Host "`nRemove all of the above? (y/N)"
    if ($answer -notmatch '^(y|yes)$') { Write-Host "cancelled - nothing was touched"; exit 0 }
}

# ---------------------------------------------------------------------- models
Step "Models"

$ollamaExe = Join-Path $env:LOCALAPPDATA 'Programs\Ollama\ollama.exe'
if (-not (Test-Path $ollamaExe)) {
    $onPath = Get-Command ollama -ErrorAction SilentlyContinue
    if ($onPath) { $ollamaExe = $onPath.Source }
}
if (Test-Path $ollamaExe) {
    $list = & $ollamaExe list 2>$null
    foreach ($line in ($list | Select-Object -Skip 1)) {
        $name = ($line -split '\s+')[0]
        if ($name) {
            & $ollamaExe rm $name 2>$null | Out-Null
            Good "removed model $name"
        }
    }
} else {
    Warn "ollama not found - skipping model removal"
}

# --------------------------------------------------------------------- processes
Step "Stopping Ollama"
Get-Process -Name 'ollama', 'ollama app' -ErrorAction SilentlyContinue |
    Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2
Good "stopped"

# --------------------------------------------------------------------- uninstall
if (-not $KeepOllama) {
    Step "Uninstalling Ollama"
    winget uninstall --id Ollama.Ollama --disable-interactivity 2>$null | Out-Null
    foreach ($path in @($ollamaProg, $ollamaHome)) {
        if (Test-Path $path) {
            Remove-Item $path -Recurse -Force -ErrorAction SilentlyContinue
            if (Test-Path $path) { Warn "could not fully remove $path" } else { Good "removed $path" }
        }
    }
} else {
    Step "Keeping Ollama installed (models were still removed)"
}

# ------------------------------------------------------------- environment vars
Step "Environment variables"
foreach ($name in @('OLLAMA_NUM_PARALLEL', 'OLLAMA_KEEP_ALIVE', 'OLLAMA_GPU_OVERHEAD')) {
    if ([Environment]::GetEnvironmentVariable($name, 'User')) {
        [Environment]::SetEnvironmentVariable($name, $null, 'User')
        Good "cleared $name"
    }
}

# ---------------------------------------------------------------------- the venv
Step "Python virtual environment"
if (Test-Path $venv) {
    Remove-Item $venv -Recurse -Force -ErrorAction SilentlyContinue
    if (Test-Path $venv) { Warn "could not remove $venv - close any terminal using it and re-run" }
    else { Good "removed $venv" }
} else {
    Good "already gone"
}

# --------------------------------------------------------------------- results
if ($IncludeResults -and (Test-Path $results)) {
    Step "Translated pages"
    Remove-Item $results -Recurse -Force -ErrorAction SilentlyContinue
    Good "removed $results"
}

# ---------------------------------------------------------------------- python
if ($RemovePython) {
    Step "Python"
    winget uninstall --id Python.Python.3.12 --disable-interactivity 2>$null | Out-Null
    Good "uninstall requested"
}

# ------------------------------------------------------------------------ done
Step "Done"
Write-Host @"
  What is left, to delete by hand if you want the machine completely clean:

    $root

  That folder holds this script and the project itself, so it cannot delete itself
  while running. Close this window, then remove it from Explorer or with:

    Remove-Item -Recurse -Force "$root"
"@ -ForegroundColor Cyan
