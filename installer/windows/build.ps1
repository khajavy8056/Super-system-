# Build the Windows installer (run on Windows 10/11 with Python 3.11+).
#   powershell -ExecutionPolicy Bypass -File .\build.ps1
#
# Produces:
#   installer\windows\dist\SupermarketSystem.exe        (PyInstaller onefile)
#   installer\output\SupermarketSystem-Setup-0.1.0.exe  (Inno Setup, if installed)
$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..\..")

Write-Host "[1/3] Installing backend dependencies..."
Push-Location (Join-Path $Root "backend")
if (-not (Test-Path ".venv")) { python -m venv .venv }
.\.venv\Scripts\python -m pip install --upgrade pip
.\.venv\Scripts\pip install -r requirements.txt pyinstaller
Pop-Location

Write-Host "[2/3] Building executable with PyInstaller..."
Push-Location $PSScriptRoot
& (Join-Path $Root "backend\.venv\Scripts\pyinstaller.exe") --clean --noconfirm app.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed" }
Pop-Location

Write-Host "[3/3] Building installer with Inno Setup..."
$iscc = "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if (-not (Test-Path $iscc)) { $iscc = "C:\Program Files\Inno Setup 6\ISCC.exe" }
if (-not (Test-Path $iscc)) {
  Write-Warning "Inno Setup not found. The exe is ready at installer\windows\dist\SupermarketSystem.exe."
  Write-Warning "Install Inno Setup 6 (https://jrsoftware.org/isdl.php) to produce the Setup.exe."
  exit 0
}
& $iscc (Join-Path $PSScriptRoot "setup.iss")
if ($LASTEXITCODE -ne 0) { throw "Inno Setup build failed" }
Write-Host "Done! Installer at installer\output\"
