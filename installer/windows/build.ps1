# Build the Windows installer (run on Windows with Python 3.11+).
#   ./build.ps1
$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..\..")

Write-Host "[1/3] Installing backend dependencies..."
Push-Location (Join-Path $Root "backend")
python -m venv .venv
.\.venv\Scripts\python -m pip install --upgrade pip
.\.venv\Scripts\pip install -r requirements.txt pyinstaller
Pop-Location

Write-Host "[2/3] Building executable with PyInstaller..."
Push-Location $PSScriptRoot
$env:PYINSTALLER = Join-Path $Root "backend\.venv\Scripts\pyinstaller.exe"
& $env:PYINSTALLER --clean --noconfirm app.spec
Pop-Location

Write-Host "[3/3] Building installer with Inno Setup..."
$iscc = "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if (-not (Test-Path $iscc)) { $iscc = "C:\Program Files\Inno Setup 6\ISCC.exe" }
if (-not (Test-Path $iscc)) {
    Write-Warning "Inno Setup not found. The exe is ready in installer\windows\dist\."
    Write-Warning "Install Inno Setup 6 to produce the Setup.exe."
    exit 0
}
& $iscc setup.iss
Write-Host "Done! Installer at installer\output\"
