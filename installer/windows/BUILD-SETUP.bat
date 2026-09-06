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
