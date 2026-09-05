@echo off
REM ============================================================================
REM  Supermarket System - Setup Builder  (START HERE / از اینجا شروع کنید)
REM ----------------------------------------------------------------------------
REM  This file sits in the project ROOT so it is impossible to miss. It simply
REM  forwards to installer\windows\BUILD-SETUP.bat, which opens the graphical
REM  builder window.
REM
REM  Double-click this file on Windows. A window with a progress bar opens,
REM  downloads and installs every prerequisite, and produces one distributable
REM  SupermarketSystem-Setup-<version>.exe.
REM
REM  ASCII-only on purpose: .bat files are read using the legacy console code
REM  page, where Persian text would appear as mojibake. The GUI is real Unicode.
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
