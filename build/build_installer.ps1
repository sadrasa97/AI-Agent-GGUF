param(
    [string]$InnoSetupCompiler = "iscc",
    [string]$Python = "python",
    [string]$LogoPngPath = "D:\AI-Agent-GGUF\ChatGPT Image Jul 15, 2026, 11_59_51 AM.png"
)

$ErrorActionPreference = "Stop"

Set-Location (Split-Path -Parent $PSScriptRoot)

$IconIcoPath = Join-Path $PSScriptRoot "app_icon.ico"
if (-not (Test-Path $IconIcoPath)) {
    $LogoResolved = (Resolve-Path $LogoPngPath).Path
    if (-not (Test-Path $LogoResolved)) {
        throw "Logo file not found: $LogoPngPath"
    }
    & $Python -m pip install --upgrade pillow
    $convertScript = @"
from PIL import Image
img = Image.open(r'''$LogoResolved''').convert("RGBA")
img.save(r'''$IconIcoPath''', format="ICO", sizes=[(256,256),(128,128),(64,64),(48,48),(32,32),(16,16)])
print("icon_ok")
"@
    & $Python -c $convertScript
}

Write-Host "Compiling installer with Inno Setup..."
& $InnoSetupCompiler ".\\GGUFCodeAgent.iss"

if ($LASTEXITCODE -ne 0) {
    throw "Installer build failed with exit code $LASTEXITCODE"
}

Write-Host "Installer created at dist\\GGUF-Code-Agent-Setup.exe"
