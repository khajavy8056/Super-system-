@echo off
setlocal
chcp 65001 >nul
title Rasa System - Fresh Install Cleanup

set "SCRIPT=%~dp0RESET-TO-FRESH-INSTALL.ps1"
if not exist "%SCRIPT%" (
  echo ERROR: The matching PowerShell file was not found:
  echo   %SCRIPT%
  echo Keep RESET-TO-FRESH-INSTALL.bat and RESET-TO-FRESH-INSTALL.ps1 in the same folder.
  pause
  exit /b 2
)

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT%"
set "RC=%ERRORLEVEL%"
echo.
if not "%RC%"=="0" echo Cleanup did not finish successfully. Review the PowerShell messages above.
pause
exit /b %RC%
