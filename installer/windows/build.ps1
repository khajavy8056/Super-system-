# Command-line build of the Windows installer (Windows 10/11).
#
#   powershell -ExecutionPolicy Bypass -File .\build.ps1
#
# Produces:
#   installer\windows\dist\SupermarketSystem.exe        (PyInstaller onefile)
#   installer\output\SupermarketSystem-Setup-<ver>.exe  (Inno Setup)
#
# This is a thin wrapper: the actual steps live in builder-lib.ps1 and are
# shared with the graphical builder (BUILD-SETUP.bat). Keeping one
# implementation means the CLI and the GUI can never drift apart — previously
# this file had its own copy of the logic and its own hardcoded version.
#
# For the graphical version with a progress bar, double-click BUILD-SETUP.bat.
$ErrorActionPreference = 'Stop'
& (Join-Path $PSScriptRoot 'builder-gui.ps1') -Silent
