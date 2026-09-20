@echo off
setlocal EnableExtensions DisableDelayedExpansion
REM Optional: drag your installed SupermarketSystem.exe onto this BAT.
REM UI override only; no database, executable, registry or installed files are changed.
if not exist "%~dp0frontend\index.html" goto missing
set "FRONTEND_DIR=%~dp0frontend"
set "SHOP_EXE=%~1"
if not defined SHOP_EXE set "SHOP_EXE=%ProgramFiles%\SupermarketSystem\SupermarketSystem.exe"
if not exist "%SHOP_EXE%" set "SHOP_EXE=%ProgramFiles(x86)%\SupermarketSystem\SupermarketSystem.exe"
if not exist "%SHOP_EXE%" (
 echo Existing SupermarketSystem.exe not found. This is NOT a full installer.
 echo Drag your installed SupermarketSystem.exe onto this BAT, or run:
 echo START-WINDOWS-UI.bat "C:\your-install-folder\SupermarketSystem.exe"
 pause
 exit /b 1
)
tasklist /FI "IMAGENAME eq SupermarketSystem.exe" /NH 2>nul | find /I "SupermarketSystem.exe" >nul
if not errorlevel 1 (
 echo Close the running shop application using its Exit command, then retry.
 echo No running process was stopped and no files were changed.
 pause
 exit /b 2
)
echo Starting the installed shop app with Desktop UI 3.6.6 ...
start "" "%SHOP_EXE%"
exit /b 0
:missing
echo Extract the WHOLE ZIP before running. The frontend folder is missing.
pause
exit /b 1
