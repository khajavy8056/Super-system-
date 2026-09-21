@echo off
REM ============================================================================
REM  Supermarket System - Setup Builder  (START HERE / از اینجا شروع کنید)
REM ----------------------------------------------------------------------------
REM  This file sits in the project ROOT so it is impossible to miss. It simply
REM  forwards to installer\windows\BUILD-SETUP.bat, the console builder.
REM
REM  Double-click this file on Windows. It checks the project is complete,
REM  builds the application, and produces:
REM      installer\output\SupermarketSystem-<version>-portable.exe
REM      installer\output\SupermarketSystem-Setup-<version>.exe
REM
REM  Prefer a progress bar instead of console text? Run
REM      installer\windows\BUILD-SETUP-GUI.bat
REM
REM  ASCII-only on purpose: .bat files are read using the legacy console code
REM  page, where Persian text would appear as mojibake.
REM ============================================================================
setlocal EnableExtensions

set "TARGET=%~dp0installer\windows\BUILD-SETUP.bat"

if not exist "%TARGET%" (
  echo.
  echo  [ERROR] Could not find:
  echo          "%TARGET%"
  echo.
  echo  Keep this file in the project root, next to the "installer" folder.
  echo.
  pause
  exit /b 1
)

call "%TARGET%" %*
exit /b %ERRORLEVEL%
