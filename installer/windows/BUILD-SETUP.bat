@echo off
REM ============================================================================
REM  Supermarket System - ONE-CLICK SETUP BUILDER (double-click me)
REM ----------------------------------------------------------------------------
REM  Keeps the whole repository intact: this file must stay inside
REM  installer\windows\ of the FULL repository (build.ps1 checks that for you).
REM
REM  What it does: runs build.ps1 which
REM    1. verifies the repository is complete (11 critical files),
REM    2. finds Python 3.11+ (or tells you exactly how to install it),
REM    3. builds dist\SupermarketSystem.exe with PyInstaller,
REM    4. always publishes installer\output\SupermarketSystem-<ver>-portable.exe,
REM    5. builds installer\output\SupermarketSystem-Setup-<ver>.exe with Inno
REM       Setup 6 when it is installed.
REM
REM  This is the RECOMMENDED entry point. It is deliberately console-only: no
REM  WPF dependency and no hidden window, so when something fails you can read
REM  the reason on the screen instead of watching nothing happen. If you prefer
REM  a progress bar, run BUILD-SETUP-GUI.bat in this same folder.
REM
REM  This file is ASCII-only on purpose (the legacy console code page cannot
REM  render Persian). All Persian documentation: installer\windows\README.md
REM ============================================================================
setlocal EnableExtensions
title Supermarket System - Setup Builder

set "HERE=%~dp0"
set "PS=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
if not exist "%PS%" set "PS=powershell.exe"

if not exist "%HERE%build.ps1" (
  echo.
  echo  [ERROR] build.ps1 was not found next to this file:
  echo          "%HERE%build.ps1"
  echo          Keep the repository folder complete.
  echo.
  pause
  exit /b 1
)

REM --- Syntax self-check (a real fix for the 1.2.0 "Missing closing '}'" report) ----
REM The scripts contain Persian text; without a UTF-8 BOM the legacy ANSI parser
REM read some bytes as quote marks and reported bogus "missing }" errors. The
REM files now carry a BOM, and this pre-parse proves they load on THIS machine
REM before anything is built.
"%PS%" -NoProfile -ExecutionPolicy Bypass -Command "$e=$null; $t=$null; foreach($f in @('%HERE%builder-lib.ps1','%HERE%build.ps1','%HERE%builder-gui.ps1')){ [void][System.Management.Automation.Language.Parser]::ParseFile($f,[ref]$t,[ref]$e); if($e){ Write-Host ('[ERROR] PowerShell cannot parse ' + $f); $e | ForEach-Object { Write-Host ('   ' + $_.Extent.StartLineNumber + ': ' + $_.Message) }; exit 3 } }; exit 0"
if errorlevel 3 (
  echo.
  echo  The build scripts could not be parsed. Re-download the repository ZIP;
  echo  do not open/save the .ps1 files with an editor that strips the UTF-8 BOM.
  echo.
  pause
  exit /b 3
)

"%PS%" -NoProfile -ExecutionPolicy Bypass -File "%HERE%build.ps1" %*
set "RC=%ERRORLEVEL%"

echo.
if "%RC%"=="0" (
  echo  Build finished. Check the messages above for output paths.
) else (
  echo  Build FAILED with exit code %RC%.
  echo  Read installer\windows\build.log and README.md ^(troubleshooting^).
)
echo.
pause
exit /b %RC%
