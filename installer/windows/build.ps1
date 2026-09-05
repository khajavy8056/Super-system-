# Build the Windows installer for Supermarket System  (version 0.4.0)
# ----------------------------------------------------------------------------
# Run directly:  powershell -NoProfile -ExecutionPolicy Bypass -File build.ps1
# Or simply double-click BUILD-SETUP.bat (same folder) - recommended.
#
# Design goals (root causes of earlier failed builds are handled here):
#   * verifies the repository is COMPLETE before doing anything (the #1 cause
#     of "compile errors" was building from a partial copy of the project),
#   * every external step is checked (python found, pip ok, PyInstaller exit
#     code checked, dist exe really exists, ISCC present),
#   * without Inno Setup you still get a working portable exe - the build
#     never "fails silently",
#   * full log written to build.log next to this script.
#
# Requirements: Windows 10/11 + Python 3.9+ on PATH or the py launcher
# (3.11+ recommended). Optional: Inno Setup 6 for the Setup.exe.

$ErrorActionPreference = "Stop"
$Version = "0.4.0"

# Unicode-safe console so the Persian summary below prints correctly.
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}

$Here  = $PSScriptRoot
$Root  = Resolve-Path (Join-Path $Here "..\..")   # repo root: installer/windows -> repo
$Venv  = Join-Path $Root "backend\.venv"
$VenvPy = Join-Path $Venv "Scripts\python.exe"
$Dist  = Join-Path $Here "dist\SupermarketSystem.exe"
$OutDir = Join-Path $Root "installer\output"

try { Start-Transcript -Path (Join-Path $Here "build.log") -Append | Out-Null } catch {}
# (transcripts must never break the build)

function Fail($msg) {
    Write-Host ""
    Write-Host "ERROR: $msg" -ForegroundColor Red
    Write-Host "FAIL - see installer\windows\build.log and README.md" -ForegroundColor Red
    try { Stop-Transcript | Out-Null } catch {}
    exit 1
}

Write-Host "== Supermarket System $Version - build started ==" -ForegroundColor Cyan
Write-Host "Repo root: $Root"

# --- 0) repository completeness preflight ------------------------------------
$Required = @(
    "backend\requirements.txt",
    "backend\app\main.py",
    "backend\app\database.py",
    "frontend\index.html",
    "frontend\mobile\index.html",
    "frontend\app.js",
    "installer\windows\app.spec",
    "installer\windows\setup.iss",
    "installer\windows\icon.ico",
    "installer\windows\run_supermarket.py"
)
$Missing = @()
foreach ($f in $Required) {
    if (-not (Test-Path (Join-Path $Root $f))) { $Missing += $f }
}
if ($Missing.Count -gt 0) {
    Write-Host "ERROR: project files are missing (incomplete repository copy):" -ForegroundColor Red
    foreach ($f in $Missing) { Write-Host "   - $f" -ForegroundColor Yellow }
    Fail "Repository incomplete. Clone/download the WHOLE repository and keep BUILD-SETUP.bat inside installer\windows\."
}

# --- 1) locate Python ---------------------------------------------------------
$PythonExe = $null
$PythonArgs = @()
$cmd = Get-Command python -ErrorAction SilentlyContinue
if ($cmd) { $PythonExe = $cmd.Source }
if (-not $PythonExe) {
    $cmd = Get-Command py -ErrorAction SilentlyContinue
    if ($cmd) { $PythonExe = $cmd.Source; $PythonArgs = @("-3") }
}
if (-not $PythonExe) {
    Fail "Python not found. Install Python 3.11+ from https://www.python.org/downloads/ and tick 'Add python.exe to PATH' during setup, then run this again."
}
$ver = & $PythonExe @PythonArgs -c "import sys; print('%d.%d' % sys.version_info[:2])"
Write-Host "Python found: $PythonExe (v$ver)"
$verNum = & $PythonExe @PythonArgs -c "import sys; print(sys.version_info[0]*100 + sys.version_info[1])"
if ([int]$verNum -lt 309) {
    Fail "Python 3.9+ is required (found $ver). Install 3.11+ from python.org."
}

# --- 2) venv + dependencies ---------------------------------------------------
if (-not (Test-Path $VenvPy)) {
    Write-Host "Creating virtual environment (backend\.venv) ..."
    & $PythonExe @PythonArgs -m venv $Venv
    if ($LASTEXITCODE -ne 0) { Fail "Could not create the virtual environment." }
}
Write-Host "Installing dependencies (may take a few minutes the first time) ..."
& $VenvPy -m pip install --disable-pip-version-check --upgrade pip | Out-Null
& $VenvPy -m pip install --disable-pip-version-check -r (Join-Path $Root "backend\requirements.txt") pyinstaller
if ($LASTEXITCODE -ne 0) { Fail "pip could not install the dependencies. Check the internet connection and build.log." }

# --- 3) PyInstaller ------------------------------------------------------------
Write-Host "Building SupermarketSystem.exe with PyInstaller ..."
Push-Location $Here
try {
    & $VenvPy -m PyInstaller --clean --noconfirm app.spec
    $rc = $LASTEXITCODE
} finally { Pop-Location }
if ($rc -ne 0) { Fail "PyInstaller exited with code $rc." }
if (-not (Test-Path $Dist)) { Fail "PyInstaller reported success but $Dist was not created." }
Write-Host "Portable executable ready: $Dist" -ForegroundColor Green

# --- 4) copy portable exe to output -------------------------------------------
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$Portable = Join-Path $OutDir "SupermarketSystem-$Version-portable.exe"
Copy-Item $Dist $Portable -Force
Write-Host "Portable copy: $Portable" -ForegroundColor Green

# --- 5) Inno Setup (optional) --------------------------------------------------
$Iscc = $null
foreach ($p in @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe")) {
    if (Test-Path $p) { $Iscc = $p; break }
}
if (-not $Iscc) {
    Write-Host ""
    Write-Host "NOTE: Inno Setup 6 not found - the Setup.exe was NOT built." -ForegroundColor Yellow
    Write-Host "      The portable exe above already runs on its own (no setup needed)." -ForegroundColor Yellow
    Write-Host "      To get the classic Setup.exe: install Inno Setup 6 from" -ForegroundColor Yellow
    Write-Host "      https://jrsoftware.org/isdl.php  then run BUILD-SETUP.bat again." -ForegroundColor Yellow
} else {
    Write-Host "Building Setup.exe with Inno Setup ..."
    & $Iscc (Join-Path $Here "setup.iss")
    if ($LASTEXITCODE -ne 0) { Fail "Inno Setup exited with code $LASTEXITCODE." }
    $Setup = Join-Path $OutDir "SupermarketSystem-Setup-$Version.exe"
    if (Test-Path $Setup) {
        Write-Host "Installer ready: $Setup" -ForegroundColor Green
    } else {
        Fail "Inno Setup finished but $Setup was not found."
    }
}

# --- summary -------------------------------------------------------------------
Write-Host ""
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "BUILD OK / ساخت با موفقیت انجام شد" -ForegroundColor Green
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host " Portable  : $Portable"
if ($Iscc) { Write-Host " Installer : installer\output\SupermarketSystem-Setup-$Version.exe" }
Write-Host " Data dir  : %USERPROFILE%\SupermarketSystem  (created on first run)"
try { Stop-Transcript | Out-Null } catch {}
exit 0
