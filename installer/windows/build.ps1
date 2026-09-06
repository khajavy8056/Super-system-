# ============================================================================
#  Command-line build of the Windows installer for Supermarket System.
#
#    powershell -NoProfile -ExecutionPolicy Bypass -File build.ps1
#    powershell -NoProfile -ExecutionPolicy Bypass -File build.ps1 -NoDownload
#
#  Produces:
#    installer\windows\dist\SupermarketSystem.exe            (PyInstaller)
#    installer\output\SupermarketSystem-<ver>-portable.exe   (ALWAYS)
#    installer\output\SupermarketSystem-Setup-<ver>.exe      (needs Inno Setup)
#
#  This file is a thin driver: every real step lives in builder-lib.ps1 and is
#  shared with the graphical builder (BUILD-SETUP-GUI.bat). One implementation
#  means the console, the GUI and CI can never drift apart.
#
#  v0.3.1 had a bug here that made BOTH entry points die instantly:
#  builder-gui.ps1 read $ScriptDir before anything had assigned it, and
#  Set-StrictMode -Version Latest turns that into a terminating error.
#  $ScriptDir is now defined here (and in the GUI) before the dot-source.
# ============================================================================
[CmdletBinding()]
param(
    # Never fetch Python or Inno Setup from the internet. The build then
    # reports what is missing and still produces the portable exe. This is the
    # mode CI uses and the mode to pick when the auto-download chain fails.
    [switch]$NoDownload,

    # Do not fail the build when Inno Setup is absent; the portable exe is
    # enough. Implied by -NoDownload.
    [switch]$PortableOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# Must be assigned BEFORE dot-sourcing: builder-lib.ps1 derives every path
# from it, and StrictMode makes an unassigned variable a hard error.
$ScriptDir = $PSScriptRoot
if (-not $ScriptDir) { $ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition }

try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}

. (Join-Path $ScriptDir 'builder-lib.ps1')

if ($NoDownload)    { $Script:AllowDownloads = $false }
if ($PortableOnly)  { $Script:RequireSetup   = $false }
if ($NoDownload)    { $Script:RequireSetup   = $false }

Write-Host "== Supermarket System $Version - build started ==" -ForegroundColor Cyan
Write-Host "Repo root : $RepoRoot"
Write-Host "Log file  : $LogFile"
Write-Host "Downloads : $(if ($Script:AllowDownloads) { 'allowed' } else { 'DISABLED (-NoDownload)' })"
Write-Host ""

$i = 0
try {
    foreach ($s in $Steps) {
        $i++
        Write-Host ("[{0}/{1}] {2}" -f $i, $Steps.Count, $s.Name) -ForegroundColor Cyan
        & $s.Action ([scriptblock]::Create('param($m) Write-Host ("      " + $m)'))
    }
} catch {
    Write-Host ""
    Write-Host "ERROR: $_" -ForegroundColor Red
    Write-Host "FAIL - see $RepoLogFile and installer\windows\README.md" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "BUILD OK / ساخت با موفقیت انجام شد" -ForegroundColor Green
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host " Portable : $Script:Portable"
if ($Script:FinalSetup) { Write-Host " Installer: $Script:FinalSetup" }
Write-Host " Data dir : %USERPROFILE%\SupermarketSystem  (created on first run)"
exit 0
