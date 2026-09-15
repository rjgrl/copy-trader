#Requires -Version 5.1
<#
.SYNOPSIS
  Build the production ONEDIR windowed TelegramMT5Copier.exe

.EXAMPLE
  .\scripts\build_exe.ps1
  .\scripts\build_exe.ps1 -Clean
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
    Write-Host "==> Cleaning previous dist/build outputs"
    $paths = @(
        (Join-Path $Root "dist\TelegramMT5Copier"),
        (Join-Path $Root "build\TelegramMT5Copier"),
        (Join-Path $Root "build\TelegramMT5Copier_debug")
    )
    foreach ($p in $paths) {
        if (Test-Path $p) { Remove-Item -Recurse -Force $p }
    }
}

$env:TELEGRAM_MT5_CONSOLE = "0"
Write-Host "==> Running PyInstaller (windowed ONEDIR)"
& $Python -m PyInstaller --noconfirm --clean --distpath (Join-Path $Root "dist") --workpath (Join-Path $Root "build\pyinstaller") $Spec

$Exe = Join-Path $Root "dist\TelegramMT5Copier\TelegramMT5Copier.exe"
if (-not (Test-Path $Exe)) {
    throw "Build finished but executable missing: $Exe"
}

Write-Host ""
Write-Host "Build succeeded."
Write-Host "Executable: $Exe"
Write-Host "Persistent data will be stored under:"
Write-Host "  $env:LOCALAPPDATA\TelegramMT5Copier\"
Write-Host ""
