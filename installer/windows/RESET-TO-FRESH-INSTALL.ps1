# Requires Windows PowerShell 5.1 or PowerShell 7.
# Removes registered Rasa System / Supermarket System installs and the app's
# known per-user data locations. It never searches/deletes arbitrary user files.
[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'High')]
param(
    [Parameter()]
    [string]$TargetUserProfile = $env:USERPROFILE
)

$ErrorActionPreference = 'Stop'
$script:Failures = New-Object 'System.Collections.Generic.List[string]'
$script:Warnings = New-Object 'System.Collections.Generic.List[string]'
$script:DryRun = [bool]$WhatIfPreference
$script:KnownFolderNames = @('RasaSystem', 'Rasa System', 'SupermarketSystem', 'Supermarket System')
$script:AppId = 'B1969066-0725-5BAD-AC99-E4201ADBDE6B'

function Add-WarningMessage {
    param([Parameter(Mandatory)][string]$Message)
    $script:Warnings.Add($Message)
    Write-Warning $Message
}

function Add-FailureMessage {
    param([Parameter(Mandatory)][string]$Message)
    $script:Failures.Add($Message)
    Write-Error -Message $Message -ErrorAction Continue
}

function Test-TargetProductEntry {
    param([Parameter(Mandatory)]$Entry)

    if ([string]$Entry.KeyName -like "*$script:AppId*") {
        return $true
    }
    $displayName = [string]$Entry.DisplayName
    return $displayName -match '^\s*(?:Rasa\s*System|Supermarket\s*System)(?:\s|v?\d|\(|$)'
}

function Get-RegisteredInstalls {
    $roots = @(
        'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall',
        'HKCU:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall',
        'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall',
        'HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall'
    )
    $found = @()

    foreach ($root in $roots) {
        if (-not (Test-Path -LiteralPath $root)) {
            continue
        }
        try {
            $keys = Get-ChildItem -LiteralPath $root -ErrorAction Stop
        }
        catch {
            Add-WarningMessage "نخواندن کلیدهای نصب از $root: $($_.Exception.Message)"
            continue
        }
        foreach ($key in $keys) {
            try {
                $properties = Get-ItemProperty -LiteralPath $key.PSPath -ErrorAction Stop
            }
            catch {
                Add-WarningMessage "نخواندن اطلاعات نصب از $($key.PSPath): $($_.Exception.Message)"
                continue
            }
            $entry = [PSCustomObject]@{
                KeyPath             = $key.PSPath
                KeyName             = $key.PSChildName
                DisplayName         = [string]$properties.DisplayName
                InstallLocation     = [string]$properties.InstallLocation
                UninstallString     = [string]$properties.UninstallString
                QuietUninstallString = [string]$properties.QuietUninstallString
            }
            if (Test-TargetProductEntry -Entry $entry) {
                $found += $entry
            }
        }
    }
    return $found
}

function Get-SafeInnoUninstaller {
    param([Parameter(Mandatory)]$Entry)

    $commands = @($Entry.QuietUninstallString, $Entry.UninstallString) |
        Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
    foreach ($command in $commands) {
        $expanded = [Environment]::ExpandEnvironmentVariables([string]$command)
        $match = [regex]::Match($expanded, '^\s*"(?<exe>[^"]+\.exe)"', [System.Text.RegularExpressions.RegexOptions]::IgnoreCase)
        if (-not $match.Success) {
            $match = [regex]::Match($expanded, '^\s*(?<exe>.+?\.exe)(?:\s|$)', [System.Text.RegularExpressions.RegexOptions]::IgnoreCase)
        }
        if (-not $match.Success) {
            continue
        }

        $candidate = $match.Groups['exe'].Value.Trim('"')
        if ([IO.Path]::GetFileName($candidate) -notmatch '^unins\d+\.exe$') {
            continue
        }
        if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) {
            continue
        }

        $parent = [IO.Path]::GetDirectoryName([IO.Path]::GetFullPath($candidate)).TrimEnd('\')
        $parentName = Split-Path -Path $parent -Leaf
        if ($script:KnownFolderNames -notcontains $parentName) {
            continue
        }
        if (-not [string]::IsNullOrWhiteSpace($Entry.InstallLocation)) {
            $installLocation = [Environment]::ExpandEnvironmentVariables($Entry.InstallLocation.Trim().Trim('"'))
            if (Test-Path -LiteralPath $installLocation -PathType Container) {
                $expectedParent = [IO.Path]::GetFullPath($installLocation).TrimEnd('\')
                if (-not $parent.Equals($expectedParent, [StringComparison]::OrdinalIgnoreCase)) {
                    continue
                }
            }
        }
        return [IO.Path]::GetFullPath($candidate)
    }
    return $null
}

function Add-InstallTarget {
    param([Parameter(Mandatory)][string]$Path)

    $expanded = [Environment]::ExpandEnvironmentVariables($Path.Trim().Trim('"'))
    if ([string]::IsNullOrWhiteSpace($expanded)) {
        return
    }
    try {
        $fullPath = [IO.Path]::GetFullPath($expanded).TrimEnd('\')
    }
    catch {
        Add-WarningMessage "مسیر نصب نامعتبر است و حذف نمی‌شود: $Path"
        return
    }
    $leaf = Split-Path -Path $fullPath -Leaf
    if ($script:KnownFolderNames -notcontains $leaf) {
        return
    }
    $dataPaths = @(
        [IO.Path]::GetFullPath((Join-Path $TargetUserProfile 'RasaSystem')).TrimEnd('\'),
        [IO.Path]::GetFullPath((Join-Path $TargetUserProfile 'SupermarketSystem')).TrimEnd('\')
    )
    if ($dataPaths -contains $fullPath) {
        return
    }
    if ($script:InstallTargets -notcontains $fullPath) {
        $script:InstallTargets += $fullPath
    }
}

function Remove-ExactTarget {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$Label
    )

    if (-not (Test-Path -LiteralPath $Path)) {
        return
    }
    if ($script:DryRun) {
        Write-Host "WHATIF: would remove $Label : $Path" -ForegroundColor Yellow
        return
    }
    try {
        Remove-Item -LiteralPath $Path -Recurse -Force -ErrorAction Stop
        Write-Host "Removed $Label : $Path" -ForegroundColor Green
    }
    catch {
        Add-FailureMessage "حذف نشد ($Label): $Path — $($_.Exception.Message)"
    }
}

$TargetUserProfile = [IO.Path]::GetFullPath($TargetUserProfile.Trim().Trim('"'))
if (-not (Test-Path -LiteralPath $TargetUserProfile -PathType Container)) {
    throw "پوشهٔ پروفایل ویندوز پیدا نشد: $TargetUserProfile"
}

Write-Host ''
Write-Host 'Rasa System / Supermarket System — destructive fresh-install reset' -ForegroundColor Cyan
Write-Host "User profile to clean: $TargetUserProfile"
Write-Host 'This removes the local store database, backups inside the app folder, logs, local secrets, WebView profile, and known installed app folders.' -ForegroundColor Yellow
Write-Host 'It does not remove backups or portable EXEs stored elsewhere (for example Downloads), nor data on other PCs/phones/cloud accounts.'
Write-Host 'Custom DATABASE_URL or SUPERMARKET_DATA_DIR locations are outside scope and are not deleted.' -ForegroundColor Yellow
Write-Host ''

$registeredInstalls = @(Get-RegisteredInstalls)
if ($registeredInstalls.Count -gt 0) {
    Write-Host 'Registered app installations found:' -ForegroundColor Cyan
    foreach ($entry in $registeredInstalls) {
        $display = if ([string]::IsNullOrWhiteSpace($entry.DisplayName)) { $entry.KeyName } else { $entry.DisplayName }
        Write-Host "  - $display"
        if (-not [string]::IsNullOrWhiteSpace($entry.InstallLocation)) {
            Write-Host "    location: $($entry.InstallLocation)"
        }
    }
}
else {
    Write-Host 'No matching Add/Remove Programs entries were found.'
}

$dataTargets = @(
    (Join-Path $TargetUserProfile 'RasaSystem'),
    (Join-Path $TargetUserProfile 'SupermarketSystem')
)
$script:InstallTargets = @()
foreach ($entry in $registeredInstalls) {
    if (-not [string]::IsNullOrWhiteSpace($entry.InstallLocation)) {
        Add-InstallTarget -Path $entry.InstallLocation
    }
    $uninstaller = Get-SafeInnoUninstaller -Entry $entry
    if ($uninstaller) {
        Add-InstallTarget -Path (Split-Path -Path $uninstaller -Parent)
    }
}
$programRoots = @(
    $env:ProgramFiles,
    ${env:ProgramFiles(x86)},
    $(if ($env:LOCALAPPDATA) { Join-Path $env:LOCALAPPDATA 'Programs' })
) | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
foreach ($root in $programRoots) {
    foreach ($folderName in $script:KnownFolderNames) {
        Add-InstallTarget -Path (Join-Path $root $folderName)
    }
}

Write-Host 'Existing application/data folders in scope:' -ForegroundColor Cyan
$shownTargets = @()
$candidatePaths = @($script:InstallTargets) + @($dataTargets)
foreach ($path in $candidatePaths) {
    if ((Test-Path -LiteralPath $path) -and ($shownTargets -notcontains $path)) {
        $shownTargets += $path
        Write-Host "  - $path"
    }
}
if ($shownTargets.Count -eq 0) {
    Write-Host '  (none of the known folders currently exist)'
}

if ($script:DryRun) {
    Write-Host ''
    Write-Host 'Matching uninstall registry entries (review only; none will be changed):' -ForegroundColor Cyan
    foreach ($entry in $registeredInstalls) {
        Write-Host "  - $($entry.DisplayName) [$($entry.KeyPath)]"
    }
    if ($registeredInstalls.Count -eq 0) {
        Write-Host '  (none)'
    }
    Write-Host 'Dry run only: no process will be stopped, no uninstaller will run, and no files or registry entries will be removed.' -ForegroundColor Yellow
}
else {
    Write-Host ''
    Write-Host 'WARNING: this operation is irreversible. It is not a normal update.' -ForegroundColor Red
    $confirmation = Read-Host 'To continue, type exactly: RESET RASA SYSTEM'
    if ($confirmation -cne 'RESET RASA SYSTEM') {
        Write-Host 'Cancelled; nothing was deleted.' -ForegroundColor Yellow
        exit 2
    }

    $processNames = @('RasaSystem', 'Rasa System', 'SupermarketSystem', 'Supermarket System')
    $runningProcesses = @(Get-Process | Where-Object { $processNames -contains $_.ProcessName })
    foreach ($process in $runningProcesses) {
        Write-Host "Closing process $($process.ProcessName) (PID $($process.Id))..."
        $closed = $false
        try {
            $closed = $process.CloseMainWindow()
        }
        catch {
            Add-WarningMessage "پنجرهٔ فرایند بسته نشد؛ تلاش برای توقف امن: $($_.Exception.Message)"
        }
        if ($closed) {
            $null = $process.WaitForExit(12000)
        }
        else {
            Start-Sleep -Seconds 3
        }
        $process.Refresh()
        if (-not $process.HasExited) {
            try {
                Stop-Process -Id $process.Id -Force -ErrorAction Stop
                Write-Host "Stopped process $($process.ProcessName) (PID $($process.Id))."
            }
            catch {
                Add-FailureMessage "فرایند $($process.ProcessName) بسته نشد: $($_.Exception.Message)"
            }
        }
    }

    $completedUninstallers = @()
    foreach ($entry in $registeredInstalls) {
        $uninstaller = Get-SafeInnoUninstaller -Entry $entry
        if (-not $uninstaller) {
            Add-WarningMessage "حذف‌کنندهٔ امنِ Inno برای '$($entry.DisplayName)' پیدا نشد؛ مسیرهای شناخته‌شده پاک‌سازی می‌شوند."
            continue
        }
        if ($completedUninstallers -contains $uninstaller) {
            continue
        }
        $completedUninstallers += $uninstaller
        Write-Host "Uninstalling $($entry.DisplayName) with its registered Inno Setup uninstaller..."
        try {
            $uninstallProcess = Start-Process -FilePath $uninstaller `
                -ArgumentList @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART') `
                -Wait -PassThru -ErrorAction Stop
            if ($uninstallProcess.ExitCode -eq 0) {
                Write-Host "Uninstaller completed: $($entry.DisplayName)" -ForegroundColor Green
            }
            else {
                Add-WarningMessage "حذف‌کنندهٔ '$($entry.DisplayName)' با کد $($uninstallProcess.ExitCode) تمام شد."
            }
        }
        catch {
            Add-FailureMessage "اجرای حذف‌کنندهٔ '$($entry.DisplayName)' ناموفق بود: $($_.Exception.Message)"
        }
    }
}

# The installer directories are restricted to exact product folder names, either
# recorded by the matching uninstall entry or in standard Windows install roots.
foreach ($path in $script:InstallTargets) {
    Remove-ExactTarget -Path $path -Label 'application install folder'
}
foreach ($path in $dataTargets) {
    Remove-ExactTarget -Path $path -Label 'all local app data'
}

$userStartMenu = Join-Path $TargetUserProfile 'AppData\Roaming\Microsoft\Windows\Start Menu\Programs'
$commonStartMenu = Join-Path $env:ProgramData 'Microsoft\Windows\Start Menu\Programs'
$shortcutRoots = @(
    (Join-Path $TargetUserProfile 'Desktop'),
    $userStartMenu,
    $commonStartMenu,
    (Join-Path $env:PUBLIC 'Desktop')
) | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
$shortcutNames = @('Rasa System.lnk', 'RasaSystem.lnk', 'Supermarket System.lnk', 'SupermarketSystem.lnk')
foreach ($root in $shortcutRoots) {
    foreach ($name in $shortcutNames) {
        Remove-ExactTarget -Path (Join-Path $root $name) -Label 'app shortcut'
    }
}
$shortcutFolderNames = @('Rasa System', 'RasaSystem', 'Supermarket System', 'SupermarketSystem')
foreach ($root in @($userStartMenu, $commonStartMenu)) {
    foreach ($name in $shortcutFolderNames) {
        Remove-ExactTarget -Path (Join-Path $root $name) -Label 'app Start Menu folder'
    }
}

if (-not $script:DryRun) {
    # Remove only exact app uninstall records, and only after their install folder is gone.
    $remainingEntries = @(Get-RegisteredInstalls)
    foreach ($entry in $remainingEntries) {
        $installStillExists = $false
        if (-not [string]::IsNullOrWhiteSpace($entry.InstallLocation)) {
            $installPath = [Environment]::ExpandEnvironmentVariables($entry.InstallLocation.Trim().Trim('"'))
            $installStillExists = Test-Path -LiteralPath $installPath
        }
        if ($installStillExists) {
            Add-WarningMessage "ورودی حذف برنامه باقی ماند چون مسیر نصب هنوز وجود دارد: $($entry.KeyPath)"
            continue
        }
        try {
            Remove-Item -LiteralPath $entry.KeyPath -Recurse -Force -ErrorAction Stop
            Write-Host "Removed stale uninstall record: $($entry.DisplayName)" -ForegroundColor Green
        }
        catch {
            Add-FailureMessage "پاک‌کردن ورودی رجیستری ناموفق بود ($($entry.KeyPath)): $($_.Exception.Message)"
        }
    }
}

Write-Host ''
if ($script:DryRun) {
    Write-Host 'Dry run finished. Run the BAT file normally (not with -WhatIf) to perform the reset.' -ForegroundColor Yellow
    exit 0
}
if ($script:Failures.Count -gt 0) {
    Write-Host 'Reset was incomplete. Review the errors above; if a Program Files/HKLM item failed, rerun the BAT as Administrator under the same Windows account.' -ForegroundColor Red
    exit 1
}
Write-Host 'Fresh-install cleanup finished.' -ForegroundColor Green
Write-Host 'Now run the new Rasa System setup. Its first launch will create a new, empty local database.' -ForegroundColor Cyan
Write-Host 'Downloaded backups or data on another device/cloud are separate and are not restored/deleted by this tool.'
exit 0
