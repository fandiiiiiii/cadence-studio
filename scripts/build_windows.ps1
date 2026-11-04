$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $Root

if (-not (Test-Path -LiteralPath ".venv\Scripts\python.exe")) {
  throw "Run scripts\setup.ps1 first."
}

& ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q pyinstaller
if ($LASTEXITCODE -ne 0) { throw "Could not install PyInstaller." }

& ".venv\Scripts\pyinstaller.exe" `
  --noconfirm --clean --onefile --windowed `
  --name CadenceStudio `
  --icon "assets\cadence.ico" `
  --paths "src" `
  --add-data "src\cadence_studio\web;cadence_studio\web" `
  --add-data "src\cadence_studio\resources;cadence_studio\resources" `
  --collect-all openpyxl `
  --collect-submodules uvicorn `
  --collect-submodules fastapi `
  --collect-submodules starlette `
  --collect-submodules pydantic `
  --collect-submodules cadence_studio `
  --hidden-import=multipart `
  --hidden-import=mutagen `
  --hidden-import=cadence_studio.app `
  --hidden-import=cadence_studio.desktop `
  "launcher.py"

if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed." }

Write-Host ""
Write-Host "Built: $Root\dist\CadenceStudio.exe" -ForegroundColor Green
Write-Host "Double-click the EXE, or keep using 启动 Cadence.cmd." -ForegroundColor DarkGray
