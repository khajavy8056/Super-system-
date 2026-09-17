@echo off
setlocal EnableExtensions DisableDelayedExpansion
chcp 65001 >nul
REM Standalone annual synthetic store generator, Windows 10/11 x64.
REM Optional: -Root "D:\StoreDemo" -Days 365 -PerDay 1100 -PauseAfterDays 7
REM Downloads are verified BEFORE execution. No Git, winget or admin required.
set "DEMO_BOOT_DIR=%LOCALAPPDATA%\SupermarketDemoLauncher\3.6.4"
echo Downloading and verifying the 3.6.4 launcher...
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; [Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; $d=$env:DEMO_BOOT_DIR; New-Item -ItemType Directory -Force -Path $d | Out-Null; $p=Join-Path $d 'bootstrap.ps1'; Invoke-WebRequest -UseBasicParsing -Uri 'https://raw.githubusercontent.com/khajavy8056/Super-system-/v3.6.4/tools/bootstrap-year.ps1' -OutFile $p -TimeoutSec 180; if ((Get-FileHash -LiteralPath $p -Algorithm SHA256).Hash -ne 'cf86b7ab9be3eac8022c7327f229a1c58b18962beb283a45687c464fb55c9be8') { throw 'Launcher checksum mismatch. Nothing was executed.' }"
if errorlevel 1 goto download_failed
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%DEMO_BOOT_DIR%\bootstrap.ps1" %*
set "RC=%ERRORLEVEL%"
echo.
echo Exit code: %RC%   ^(0=validated backup, 75=paused, other=failed^)
pause
exit /b %RC%
:download_failed
echo FAILED: Check internet access to GitHub and retry. No simulation was started.
pause
exit /b 1
