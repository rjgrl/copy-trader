#Requires -Version 5.1
<#
.SYNOPSIS
  Build a console-enabled ONEDIR debug EXE for troubleshooting / Telegram auth.

.EXAMPLE
  .\scripts\build_debug.ps1
  .\scripts\build_debug.ps1 -Clean

  First-time Telegram auth (packaged):
    .\dist\TelegramMT5Copier_debug\TelegramMT5Copier_debug.exe auth
#>
param(
    [switch]$Clean
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

Write-Host "==> Project root: $Root"

$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $VenvPython)) {
    Write-Host "==> Creating virtual environment (.venv)"
    python -m venv .venv
}
$Python = $VenvPython

Write-Host "==> Installing runtime + build requirements"
& $Python -m pip install --upgrade pip
& $Python -m pip install -r requirements.txt
& $Python -m pip install -r requirements-dev.txt

$Spec = Join-Path $Root "build\TelegramMT5Copier.spec"
if (-not (Test-Path $Spec)) {
    throw "Spec not found: $Spec"
}

if ($Clean) {
    Write-Host "==> Cleaning previous debug dist/build outputs"
    $paths = @(
        (Join-Path $Root "dist\TelegramMT5Copier_debug"),
        (Join-Path $Root "build\TelegramMT5Copier_debug")
    )
    foreach ($p in $paths) {
        if (Test-Path $p) { Remove-Item -Recurse -Force $p }
    }
}

$env:TELEGRAM_MT5_CONSOLE = "1"
Write-Host "==> Running PyInstaller (console ONEDIR debug)"
& $Python -m PyInstaller --noconfirm --clean --distpath (Join-Path $Root "dist") --workpath (Join-Path $Root "build\pyinstaller_debug") $Spec

$Exe = Join-Path $Root "dist\TelegramMT5Copier_debug\TelegramMT5Copier_debug.exe"
if (-not (Test-Path $Exe)) {
    throw "Build finished but executable missing: $Exe"
}

Write-Host ""
Write-Host "Debug build succeeded."
Write-Host "Executable: $Exe"
Write-Host "Auth example:  $Exe auth"
Write-Host ""
