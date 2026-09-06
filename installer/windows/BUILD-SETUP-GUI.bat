@echo off
REM ============================================================================
REM  Supermarket System - GRAPHICAL Setup Builder (optional)
REM ----------------------------------------------------------------------------
REM  Same build engine as BUILD-SETUP.bat (builder-lib.ps1), wrapped in a WPF
REM  window with a progress bar. Use this if you prefer a graphical build.
REM
REM  If the window does not appear, or you are on Windows 7 / Server Core
REM  without WPF, use BUILD-SETUP.bat instead - it does exactly the same job
REM  in the console and prints the real error.
REM
REM  Deliberately ASCII-only: a .bat file is read by the legacy console code
REM  page (cp437/cp720), so Persian text here would render as mojibake.
REM  All user-facing Persian lives in the GUI, which is real Unicode WPF.
REM ============================================================================
setlocal EnableExtensions EnableDelayedExpansion
title Supermarket System - Setup Builder (GUI)

set "SCRIPT_DIR=%~dp0"
set "GUI=%SCRIPT_DIR%builder-gui.ps1"

if not exist "%GUI%" (
  echo.
  echo  [ERROR] builder-gui.ps1 was not found next to this file.
  echo          Expected: "%GUI%"
  echo.
  echo  Keep this file inside installer\windows\ together with the
  echo  rest of the repository files.
  echo.
  pause
  exit /b 1
)

REM --- Locate PowerShell -----------------------------------------------------
REM Windows 7+ always ships Windows PowerShell 5.x at this fixed path. We prefer
REM the absolute path over a bare "powershell" because a broken/hijacked PATH is
REM one of the most common causes of a silent no-op on user machines.
set "PS=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
if not exist "%PS%" set "PS=powershell.exe"

REM --- Hand off to the GUI ---------------------------------------------------
REM -STA          : required by WPF (the GUI toolkit we use).
REM -ExecutionPolicy Bypass : applies to THIS process only; it does not weaken
REM                 the machine policy and needs no administrator rights.
REM -WindowStyle Hidden : hides the console so only the graphical window shows.
"%PS%" -NoProfile -STA -ExecutionPolicy Bypass -WindowStyle Hidden -File "%GUI%" %*
set "RC=%ERRORLEVEL%"

REM Exit code 0 = success, 2 = user closed/cancelled the window on purpose.
if "%RC%"=="0" goto :eof
if "%RC%"=="2" goto :eof

echo.
echo  [ERROR] The graphical builder exited with code %RC%.
echo.
echo  Easiest fix: run the console builder in this same folder instead --
echo      BUILD-SETUP.bat
echo  It uses the identical build engine and prints the underlying error.
echo.
echo  A detailed log is written to:
echo      %%USERPROFILE%%\SupermarketSystem-build\build.log
echo      installer\windows\build.log
echo.
pause
exit /b %RC%
