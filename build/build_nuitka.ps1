param(
    [string]$Python = "python",
    [string]$OutputDir = "dist",
    [string]$AppName = "GGUF-Code-Agent",
    [string]$LogoPngPath = "D:\AI-Agent-GGUF\ChatGPT Image Jul 15, 2026, 11_59_51 AM.png"
)

$ErrorActionPreference = "Stop"

Set-Location (Split-Path -Parent $PSScriptRoot)
Set-Location ..

Write-Host "Installing build dependencies..."
& $Python -m pip install --upgrade pip
& $Python -m pip install --upgrade nuitka ordered-set zstandard pillow

$LogoResolved = (Resolve-Path $LogoPngPath).Path
if (-not (Test-Path $LogoResolved)) {
    throw "Logo file not found: $LogoPngPath"
}

$IconIcoPath = Join-Path $PSScriptRoot "app_icon.ico"
$convertScript = @"
from PIL import Image
img = Image.open(r'''$LogoResolved''').convert("RGBA")
img.save(r'''$IconIcoPath''', format="ICO", sizes=[(256,256),(128,128),(64,64),(48,48),(32,32),(16,16)])
print("icon_ok")
"@
& $Python -c $convertScript

if (-not (Test-Path $IconIcoPath)) {
    throw "Icon generation failed: $IconIcoPath"
}

Write-Host "Building onefile executable with Nuitka..."
& $Python -m nuitka app.py `
    --onefile `
    --standalone `
    --enable-plugin=pyside6 `
    --assume-yes-for-downloads `
    --windows-console-mode=disable `
    --windows-icon-from-ico="$IconIcoPath" `
    --include-data-file="$LogoResolved=ChatGPT Image Jul 15, 2026, 11_59_51 AM.png" `
    --include-data-dir=workspace=workspace `
    --output-dir=$OutputDir `
    --output-filename="$AppName.exe"

if ($LASTEXITCODE -ne 0) {
    throw "Nuitka build failed with exit code $LASTEXITCODE"
}

Write-Host "Build complete: $OutputDir\\$AppName.exe"
