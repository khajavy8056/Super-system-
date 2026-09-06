<#
================================================================================
 builder-lib.ps1 - ONE shared build engine for the Supermarket System installer.
================================================================================
 Dot-sourced by BOTH builder-gui.ps1 (graphical window) and build.ps1
 (command line / CI). This is deliberate: v0.3.x kept two copies of the build
 logic (a standalone build.ps1 and this library) and they drifted apart within
 a single release. There is exactly one implementation now.

 Contains no UI calls of its own. Progress is reported through a $Report
 scriptblock supplied by the caller, so the same code drives the WPF window,
 the console, and the CI runner.

 Consolidated from two parallel development lines:
   * v0.3.1 line : shared library, self-containment size checks, DPI awareness
   * v0.4.0 line : 10-file repository preflight, exit-code checks on every
                   external step, portable exe ALWAYS produced, no forced
                   auto-download chain (that chain was the single most
                   reported cause of failed user builds)
================================================================================
#>
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# ---------------------------------------------------------------------------
# Paths and logging
# ---------------------------------------------------------------------------
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$RepoRoot  = Resolve-Path (Join-Path $ScriptDir '..\..')
$WorkDir   = Join-Path $env:USERPROFILE 'SupermarketSystem-build'
$LogFile   = Join-Path $WorkDir 'build.log'
# A second copy next to the script: users send us "the build log" and they look
# in the folder they double-clicked, not in their profile.
$RepoLogFile = Join-Path $ScriptDir 'build.log'
$OutputDir = Join-Path $RepoRoot 'installer\output'

New-Item -ItemType Directory -Force -Path $WorkDir   | Out-Null
New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
"=== Supermarket System setup build @ $(Get-Date -Format s) ===" |
    Out-File -FilePath $LogFile -Encoding utf8

function Write-Log {
    param([string]$Message, [string]$Level = 'INFO')
    $line = "[{0}] [{1}] {2}" -f (Get-Date -Format 'HH:mm:ss'), $Level, $Message
    $line | Out-File -FilePath $LogFile -Append -Encoding utf8
    try { $line | Out-File -FilePath $RepoLogFile -Append -Encoding utf8 } catch {}
}

# ---------------------------------------------------------------------------
# Build options (set by the caller BEFORE the steps run)
# ---------------------------------------------------------------------------
# AllowDownloads: when $false the builder NEVER fetches Python or Inno Setup
# from the internet. It reports what is missing and still produces the portable
# exe. The auto-download chain is what produced most user build failures, so it
# is opt-in from the command line and consent-gated in the GUI.
# NOTE: scope-qualified reads. The variable provider exposes scopes as child
# drives (Variable:\Script\Foo), so "Variable:\Script:Foo" would silently
# mis-resolve; Get-Variable -Scope Script is unambiguous.
if ($null -eq (Get-Variable -Name AllowDownloads -Scope Script -ErrorAction SilentlyContinue)) {
    $Script:AllowDownloads = $true
}
if ($null -eq (Get-Variable -Name RequireSetup -Scope Script -ErrorAction SilentlyContinue)) {
    $Script:RequireSetup = $true
}

# Read the version from the single source of truth, so the Setup filename can
# never drift from what the application actually reports.
$Version = '0.0.0'
try {
    $initPy = Join-Path $RepoRoot 'backend\app\__init__.py'
    $m = Select-String -Path $initPy -Pattern '__version__\s*=\s*"([^"]+)"'
    if ($m) { $Version = $m.Matches[0].Groups[1].Value }
} catch { Write-Log "Could not read version, defaulting to $Version : $_" 'WARN' }
Write-Log "Repository: $RepoRoot"
Write-Log "Version:    $Version"
Write-Log "AllowDownloads: $Script:AllowDownloads   RequireSetup: $Script:RequireSetup"

# ---------------------------------------------------------------------------
# Per-monitor DPI awareness  (must be set before any window is created)
# ---------------------------------------------------------------------------
function Enable-DpiAwareness {
    try {
        Add-Type -ErrorAction Stop -Namespace Win32 -Name DpiApi -MemberDefinition @'
[DllImport("user32.dll")]
public static extern bool SetProcessDpiAwarenessContext(IntPtr value);
[DllImport("shcore.dll")]
public static extern int SetProcessDpiAwareness(int value);
[DllImport("user32.dll")]
public static extern bool SetProcessDPIAware();
'@
        # -4 = PerMonitorV2: correct rendering when moved between monitors with
        # different scaling. Fall back through the older APIs on Windows 8.1/7.
        if ([Win32.DpiApi]::SetProcessDpiAwarenessContext([IntPtr](-4))) { return 'PerMonitorV2' }
        try { [void][Win32.DpiApi]::SetProcessDpiAwareness(2); return 'PerMonitor' } catch {}
        [void][Win32.DpiApi]::SetProcessDPIAware(); return 'System'
    } catch {
        Write-Log "DPI awareness could not be set: $_" 'WARN'
        return 'Default'
    }
}

# ---------------------------------------------------------------------------
# UI updater (no-op when $Refs is $null, e.g. in -Silent mode)
# ---------------------------------------------------------------------------
function Update-Ui {
    param(
        [hashtable]$Refs, [string]$Step, [string]$Detail,
        $Percent, [string]$LogLine
    )
    if ($null -eq $Refs) { return }
    $Refs.Dispatcher.Invoke([action]{
        if ($Step)   { $Refs.Step.Text = $Step }
        if ($Detail) { $Refs.Detail.Text = $Detail }
        if ($null -ne $Percent -and "$Percent" -ne '') {
            $Refs.Bar.Value = [double]$Percent
            # Persian digits, to match the rest of the application's UI.
            $t = ([int][double]$Percent).ToString()
            for ($d = 0; $d -lt 10; $d++) {
                $t = $t.Replace([string]$d, [string][char](0x06F0 + $d))
            }
            $Refs.Pct.Text = "$t٪"
        }
        if ($LogLine) {
            $Refs.Log.Text += ($LogLine + "`r`n")
            $Refs.Scroll.ScrollToEnd()
        }
    }, [Windows.Threading.DispatcherPriority]::Background)
}

# ---------------------------------------------------------------------------
# Build steps
# ---------------------------------------------------------------------------
function Invoke-Native {
    <#
      Run an external program, capture BOTH streams, and throw a readable
      error when it fails. The exit code is the only verdict that counts:
      pip and PyInstaller write ordinary progress to stderr, so treating
      stderr as failure produces constant false alarms.
    #>
    param(
        [Parameter(Mandatory)][string]$FilePath,
        [string[]]$Arguments = @(),
        [string]$WorkingDirectory,
        [scriptblock]$Report
    )
    $prev = $null
    if ($WorkingDirectory) { $prev = Get-Location; Set-Location $WorkingDirectory }
    try {
        Write-Log "RUN: `"$FilePath`" $($Arguments -join ' ')"
        if ($Report) { & $Report ("‌» " + (Split-Path -Leaf $FilePath) + ' ' + ($Arguments -join ' ')) }

        # ROOT CAUSE of the v1.2.3 "step 5/6 fails at '596 INFO: PyInstaller:
        # 6.22.2'" report: this library runs under $ErrorActionPreference =
        # 'Stop'. In Windows PowerShell 5.1, "2>&1" wraps every stderr line of
        # a native program in a NativeCommandError, and under 'Stop' the FIRST
        # such line becomes a terminating exception. PyInstaller writes ALL of
        # its ordinary progress ("596 INFO: PyInstaller: 6.22.2", ...) to
        # stderr, so the build was aborted on its very first log line even
        # though nothing had failed. pip's warnings can trigger the same.
        # The native call therefore runs with 'Continue'; the exit code below
        # remains the only verdict.
        $prevEap = $ErrorActionPreference
        $ErrorActionPreference = 'Continue'
        $global:LASTEXITCODE = 0
        try {
            $output = @(& $FilePath @Arguments 2>&1 | ForEach-Object {
                $line = if ($_ -is [System.Management.Automation.ErrorRecord]) { $_.Exception.Message } else { "$_" }
                Write-Log "    $line"
                $line
            })
            $code = $LASTEXITCODE
        } finally {
            $ErrorActionPreference = $prevEap
        }
        if ($null -eq $code) { $code = 0 }
        if ($code -ne 0) {
            $tail = ($output | Select-Object -Last 15) -join "`n"
            throw ("خطا در اجرای {0} (کد خروج {1}).`n--- آخرین خروجی ---`n{2}" -f `
                   (Split-Path -Leaf $FilePath), $code, $tail)
        }
        return $output
    } finally {
        if ($prev) { Set-Location $prev }
    }
}

function Test-PythonExe {
    <#
      Return "<major>.<minor>.<micro>" when $Exe is a real CPython >= 3.11
      that actually starts, otherwise $null. Never throws.

      ROOT CAUSE of the v1.2.2 "installed but not found" report: this probe
      used  -c 'import sys;print("%d.%d.%d"%sys.version_info[:3])'.
      Windows PowerShell 5.1 hands native programs their arguments WITHOUT
      re-escaping embedded double quotes, so python received
          import sys;print(%d.%d.%d%sys.version_info[:3])
      -> SyntaxError -> exit 1 -> EVERY candidate was rejected, including the
      perfectly good Python that was already installed and even the one we had
      just installed ourselves. The probe now uses arguments that contain no
      quote characters at all (python -V prints "Python 3.11.9"), and a second,
      quote-free -c probe as fallback. Every rejection is logged WITH the raw
      output so the reason is never a mystery again.
    #>
    param([string]$Exe)
    if (-not $Exe -or -not (Test-Path -LiteralPath $Exe)) { return $null }
    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $raw = @()
        try { $raw = @(& $Exe -V 2>&1 | ForEach-Object { "$_" }) } catch { $raw = @("$_") }
        $code = $LASTEXITCODE
        $ver = $null
        foreach ($l in $raw) {
            $m = [regex]::Match($l, 'Python\s+(\d+)\.(\d+)\.(\d+)')
            if ($m.Success) { $ver = ('{0}.{1}.{2}' -f $m.Groups[1].Value, $m.Groups[2].Value, $m.Groups[3].Value); break }
        }
        if (-not $ver) {
            # Fallback probe: no quote characters in the argument.
            try { $raw2 = @(& $Exe -c 'import sys;print(sys.version_info[0],sys.version_info[1],sys.version_info[2])' 2>&1 | ForEach-Object { "$_" }) } catch { $raw2 = @("$_") }
            $code = $LASTEXITCODE
            foreach ($l in $raw2) {
                $m = [regex]::Match($l, '^\s*(\d+)\s+(\d+)\s+(\d+)\s*$')
                if ($m.Success) { $ver = ('{0}.{1}.{2}' -f $m.Groups[1].Value, $m.Groups[2].Value, $m.Groups[3].Value); break }
            }
            $raw += $raw2
        }
        if (-not $ver) {
            Write-Log ("Candidate rejected (no version, exit {0}): {1}`n      output: {2}" -f $code, $Exe, (($raw | Select-Object -First 5) -join ' | '))
            return $null
        }
        $parts = $ver.Split('.')
        if ([int]$parts[0] -eq 3 -and [int]$parts[1] -ge 11) { return $ver }
        Write-Log "Ignoring Python $ver at $Exe (need >= 3.11)"
        return $null
    } catch {
        Write-Log "Candidate rejected (exception): $Exe -> $_"
        return $null
    } finally { $ErrorActionPreference = $prevEap }
}

function Get-PythonDiagnostics {
    <#
      Self-diagnosis used when no Python is accepted: lists every candidate
      with its raw probe output. Shown to the user and written to the log so a
      failure report contains the cause, not just the symptom.
    #>
    $lines = @()
    foreach ($c in (Get-PythonCandidates)) {
        $exists = Test-Path -LiteralPath $c
        $out = '(missing)'
        if ($exists) {
            $prevEap = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
            try { $out = ((& $c -V 2>&1 | ForEach-Object { "$_" }) -join ' ') + " [exit $LASTEXITCODE]" } catch { $out = "exception: $_" }
            finally { $ErrorActionPreference = $prevEap }
        }
        $lines += ("  {0}  ->  {1}" -f $c, $out)
    }
    if ($lines.Count -eq 0) { $lines = @('  (هیچ کاندیدایی پیدا نشد)') }
    return ($lines -join "`n")
}

function Get-PythonCandidates {
    <#
      Every place a CPython can legitimately live on Windows, most reliable
      first. v1.2.1 only looked at PATH + the per-user folder, so a Python
      installed "for all users" (C:\Program Files\Python311) or one whose
      PATH entry was not ticked at install time was reported as "not found"
      even though it was there -- and then the auto-download could not make
      it visible either. All of these are now checked:
        1. explicit override  ($env:SUPERMARKET_PYTHON)
        2. PEP 514 registry   (HKCU + HKLM, 64 and 32 bit views) - this is
           how the official installer registers itself, PATH or not
        3. the py launcher    (py -0p lists every registered interpreter)
        4. PATH               (python.exe / python3.exe)
        5. well-known folders (%LOCALAPPDATA%\Programs\Python, Program Files,
           C:\PythonXY, and the launcher's own %LOCALAPPDATA%\Programs\Python\Launcher)
    #>
    $list = New-Object System.Collections.Generic.List[string]
    $add = { param($p) if ($p) { $p = "$p".Trim().Trim('"'); if ($p -and -not $list.Contains($p)) { $list.Add($p) } } }

    if ($env:SUPERMARKET_PYTHON) { & $add $env:SUPERMARKET_PYTHON }

    foreach ($root in @('HKCU:\Software\Python\PythonCore',
                        'HKLM:\Software\Python\PythonCore',
                        'HKLM:\Software\WOW6432Node\Python\PythonCore')) {
        if (Test-Path $root) {
            Get-ChildItem $root -ErrorAction SilentlyContinue | Sort-Object Name -Descending | ForEach-Object {
                $ip = Join-Path $_.PSPath 'InstallPath'
                if (Test-Path $ip) {
                    $props = Get-ItemProperty $ip -ErrorAction SilentlyContinue
                    if ($props) {
                        if ($props.PSObject.Properties['ExecutablePath']) { & $add $props.ExecutablePath }
                        if ($props.PSObject.Properties['(default)'])      { & $add (Join-Path $props.'(default)' 'python.exe') }
                    }
                }
            }
        }
    }

    $py = Get-Command py.exe -ErrorAction SilentlyContinue
    if (-not $py) {
        foreach ($lp in @((Join-Path $env:LOCALAPPDATA 'Programs\Python\Launcher\py.exe'),
                          (Join-Path $env:WINDIR 'py.exe'))) {
            if (Test-Path $lp) { $py = @{ Source = $lp }; break }
        }
    }
    if ($py) {
        $prevEap = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
        try {
            (& $py.Source -0p 2>&1) | ForEach-Object {
                $m = [regex]::Match("$_", '([A-Za-z]:\\[^\r\n]*python\.exe)', 'IgnoreCase')
                if ($m.Success) { & $add $m.Groups[1].Value }
            }
            $one = (& $py.Source -3 -c 'import sys;print(sys.executable)' 2>&1 | Select-Object -First 1)
            if ($LASTEXITCODE -eq 0 -and "$one" -match 'python\.exe$') { & $add "$one" }
        } catch {} finally { $ErrorActionPreference = $prevEap }
    }

    foreach ($n in 'python.exe', 'python3.exe') {
        Get-Command $n -All -ErrorAction SilentlyContinue | ForEach-Object {
            # The Store stub lives in ...\WindowsApps\ and is not a real Python.
            if ($_.Source -notmatch '\\WindowsApps\\') { & $add $_.Source }
        }
    }

    $roots = @()
    if ($env:LOCALAPPDATA)          { $roots += (Join-Path $env:LOCALAPPDATA 'Programs\Python') }
    if ($env:ProgramFiles)          { $roots += $env:ProgramFiles }
    if (${env:ProgramFiles(x86)})   { $roots += ${env:ProgramFiles(x86)} }
    $roots += $env:SystemDrive + '\'
    foreach ($r in $roots) {
        if (-not (Test-Path $r)) { continue }
        Get-ChildItem $r -Directory -Filter 'Python3*' -ErrorAction SilentlyContinue |
            Sort-Object Name -Descending | ForEach-Object { & $add (Join-Path $_.FullName 'python.exe') }
    }
    return $list
}

function Find-Python {
    param([scriptblock]$Report)
    $cands = @(Get-PythonCandidates)
    Write-Log ("Python candidates ({0}): {1}" -f $cands.Count, ($cands -join ' ; '))
    foreach ($exe in $cands) {
        $ver = Test-PythonExe $exe
        if ($ver) {
            Write-Log "Found Python $ver at $exe"
            $Script:PythonVersionFound = $ver
            return $exe
        }
    }
    return $null
}

function Install-Python {
    param([scriptblock]$Report)
    if (-not $Script:AllowDownloads) {
        throw ("پایتون ۳٫۱۱ یا جدیدتر روی این سیستم پیدا نشد.`n" +
               "آن را از https://www.python.org/downloads/ نصب کنید و در مراحل نصب " +
               "گزینه «Add python.exe to PATH» را بزنید، سپس دوباره تلاش کنید.")
    }
    $arch = if ([Environment]::Is64BitOperatingSystem) { 'amd64' } else { 'win32' }
    $pyVer = '3.11.9'
    $url = "https://www.python.org/ftp/python/$pyVer/python-$pyVer-$arch.exe"
    $dst = Join-Path $WorkDir "python-$pyVer-$arch.exe"

    # Re-use a previous download (a failed run must not download twice).
    if ((Test-Path $dst) -and (Get-Item $dst).Length -gt 20MB) {
        & $Report "فایل نصب پایتون از اجرای قبلی موجود است؛ دانلود مجدد انجام نمی‌شود."
    } else {
        & $Report "دانلود پایتون $pyVer ..."
        Write-Log "Downloading $url"
        try {
            # TLS 1.2 is not the default on stock Windows PowerShell 5.1 and
            # python.org refuses anything older.
            [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
            $ProgressPreference = 'SilentlyContinue'   # the CLI bar is very slow
            Invoke-WebRequest -Uri $url -OutFile $dst -UseBasicParsing
        } catch {
            throw "دانلود پایتون ناموفق بود. اتصال اینترنت را بررسی کنید.`nجزئیات: $_"
        }
    }

    # Install into a FIXED, KNOWN directory. v1.2.1 relied on PATH being
    # refreshed after a silent install, which does not happen when the same
    # version was already present (the installer then runs a silent "modify"
    # that changes nothing) -- the exact "installed but not found, please
    # restart" dead end users hit. With TargetDir we know where python.exe is
    # and verify it directly instead of hoping PATH changed.
    $target = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python311'
    & $Report 'نصب پایتون (بدون نیاز به دسترسی مدیر) ...'
    $prevEap = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
    try {
        $proc = Start-Process -FilePath $dst -Wait -PassThru -ArgumentList @(
            '/quiet', 'InstallAllUsers=0', 'PrependPath=1', "TargetDir=`"$target`"",
            'Include_pip=1', 'Include_launcher=1', 'AssociateFiles=0', 'Include_test=0'
        )
        Write-Log "python installer exit code: $($proc.ExitCode)"
    } finally { $ErrorActionPreference = $prevEap }

    # Refresh PATH for THIS process (installer only updates future processes).
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' +
                [Environment]::GetEnvironmentVariable('Path', 'User') + ';' + $env:Path

    $direct = Join-Path $target 'python.exe'
    if (Test-PythonExe $direct) { return $direct }
    $exe = Find-Python
    if ($exe) { return $exe }

    $log = Join-Path $env:TEMP 'Python 3.11.9 (64-bit)_*.log'
    $diag = Get-PythonDiagnostics
    Write-Log "Python diagnostics:`n$diag"
    throw ("نتیجهٔ بررسی همهٔ مسیرهای پایتون:`n$diag`n`n" +
           "نصب‌کنندهٔ پایتون اجرا شد (کد خروج $($proc.ExitCode)) اما هیچ python.exe سالمی پیدا نشد.`n" +
           "مسیر انتظار: $direct`n" +
           "اگر پایتون از قبل در جای دیگری نصب است، مسیر کامل python.exe را در متغیر " +
           "SUPERMARKET_PYTHON قرار دهید و دوباره اجرا کنید، مثلاً:`n" +
           "  set SUPERMARKET_PYTHON=C:\Python311\python.exe`n" +
           "گزارش نصب‌کنندهٔ پایتون: $log")
}

function Find-InnoSetup {
    foreach ($p in @(
        'C:\Program Files (x86)\Inno Setup 6\ISCC.exe',
        'C:\Program Files\Inno Setup 6\ISCC.exe'
    )) { if (Test-Path $p) { return $p } }
    $c = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    if ($c) { return $c.Source }
    return $null
}

function Install-InnoSetup {
    param([scriptblock]$Report)
    if (-not $Script:AllowDownloads) { return $null }
    $url = 'https://files.jrsoftware.org/is/6/innosetup-6.2.2.exe'
    $dst = Join-Path $WorkDir 'innosetup-6.2.2.exe'
    & $Report 'دانلود Inno Setup ...'
    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        $ProgressPreference = 'SilentlyContinue'
        Invoke-WebRequest -Uri $url -OutFile $dst -UseBasicParsing
    } catch {
        Write-Log "Inno Setup download failed: $_" 'WARN'
        return $null
    }
    & $Report 'نصب Inno Setup ...'
    Invoke-Native -FilePath $dst -Report $Report -Arguments @(
        '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/SP-'
    )
    return Find-InnoSetup
}

# --- the ordered step list --------------------------------------------------
# Declared up-front: Set-StrictMode makes reading an undefined variable a
# terminating error, so every cross-step variable must exist before use.
$Script:PythonExe  = $null
$Script:VenvPy     = $null
$Script:Iscc       = $null
$Script:Portable   = $null
$Script:PythonVersionFound = $null
$Script:FinalSetup = $null

$Steps = @(
    @{ Name = 'بررسی سیستم و پیش‌نیازها'; Action = {
        param($Report)
        & $Report "ویندوز: $([Environment]::OSVersion.VersionString)"
        & $Report ("معماری: " + $(if ([Environment]::Is64BitOperatingSystem) { '64-bit' } else { '32-bit' }))
        & $Report "پوشه پروژه: $RepoRoot"

        # Full repository preflight. The #1 cause of "compiler errors / exit
        # code 1" was building from a partial copy of the project, so every
        # file the build really needs is verified up front and by name.
        $required = @(
            'backend\requirements.txt', 'backend\app\main.py', 'backend\app\database.py',
            'backend\app\__init__.py', 'frontend\index.html', 'frontend\app.js',
            'frontend\mobile\index.html', 'installer\windows\app.spec',
            'installer\windows\setup.iss', 'installer\windows\icon.ico',
            'installer\windows\run_supermarket.py'
        )
        $missing = @()
        foreach ($f in $required) {
            if (-not (Test-Path (Join-Path $RepoRoot $f))) { $missing += $f }
        }
        if ($missing.Count -gt 0) {
            throw ("پوشه پروژه ناقص است. این فایل‌ها پیدا نشدند:`n  " +
                   ($missing -join "`n  ") +
                   "`n`nکل مخزن را دانلود کنید و BUILD-SETUP.bat را داخل installer\windows\ نگه دارید.")
        }
        & $Report 'ساختار پروژه سالم است (۱۱ فایل حیاتی بررسی شد).'
    }}

    @{ Name = 'یافتن یا نصب پایتون ۳٫۱۱+'; Action = {
        param($Report)
        & $Report 'جست‌وجوی پایتون نصب‌شده (رجیستری، py launcher، PATH، پوشه‌های استاندارد) ...'
        $exe = Find-Python
        if ($exe) {
            & $Report "پایتون $($Script:PythonVersionFound) پیدا شد: $exe"
            & $Report 'پایتون از قبل نصب است؛ چیزی دانلود نمی‌شود.'
        } else {
            & $Report 'پایتون مناسبی یافت نشد. نتیجهٔ بررسی مسیرها:'
            foreach ($l in (Get-PythonDiagnostics).Split("`n")) { & $Report $l }
            $exe = Install-Python -Report $Report
            & $Report 'پایتون با موفقیت نصب شد.'
        }
        $Script:PythonExe = $exe
    }}

    @{ Name = 'ساخت محیط مجازی و نصب وابستگی‌ها'; Action = {
        param($Report)
        $venv = Join-Path $WorkDir 'venv'
        if (-not (Test-Path (Join-Path $venv 'Scripts\python.exe'))) {
            & $Report 'ساخت محیط مجازی ...'
            Invoke-Native -FilePath $Script:PythonExe -Arguments @('-m', 'venv', $venv) -Report $Report
        } else {
            & $Report 'محیط مجازی موجود بازاستفاده شد.'
        }
        $Script:VenvPy = Join-Path $venv 'Scripts\python.exe'

        & $Report 'به‌روزرسانی pip ...'
        Invoke-Native -FilePath $Script:VenvPy -Report $Report `
            -Arguments @('-m', 'pip', 'install', '--upgrade', 'pip', '--disable-pip-version-check')

        & $Report 'نصب وابستگی‌های برنامه (ممکن است چند دقیقه طول بکشد) ...'
        Invoke-Native -FilePath $Script:VenvPy -Report $Report -Arguments @(
            '-m', 'pip', 'install', '--disable-pip-version-check',
            '-r', (Join-Path $RepoRoot 'backend\requirements.txt'), 'pyinstaller'
        )
        & $Report 'همه وابستگی‌ها نصب شدند.'
    }}

    @{ Name = 'یافتن یا نصب Inno Setup'; Action = {
        param($Report)
        $iscc = Find-InnoSetup
        if ($iscc) {
            & $Report "Inno Setup پیدا شد: $iscc"
        } else {
            & $Report 'Inno Setup یافت نشد.'
            $iscc = Install-InnoSetup -Report $Report
            if ($iscc) { & $Report 'Inno Setup نصب شد.' }
        }
        $Script:Iscc = $iscc
        if (-not $iscc) {
            Write-Log 'Inno Setup unavailable - only the portable exe will be produced.' 'WARN'
        }
    }}

    @{ Name = 'ساخت فایل اجرایی خودکفا'; Action = {
        param($Report)
        & $Report 'اجرای PyInstaller (طولانی‌ترین مرحله) ...'
        Invoke-Native -FilePath $Script:VenvPy -WorkingDirectory $ScriptDir -Report $Report `
            -Arguments @('-m', 'PyInstaller', '--clean', '--noconfirm', 'app.spec')

        $exe = Join-Path $ScriptDir 'dist\SupermarketSystem.exe'
        if (-not (Test-Path $exe)) {
            throw "PyInstaller بدون خطا تمام شد اما فایل خروجی ساخته نشد:`n$exe"
        }
        $mb = [math]::Round((Get-Item $exe).Length / 1MB, 1)

        # Self-containment check. PyInstaller embeds CPython plus every
        # dependency, so the result must be tens of megabytes. A suspiciously
        # small file means the interpreter was NOT bundled and the installer
        # would fail on any machine without Python -- exactly the failure this
        # deliverable exists to prevent. Better to fail here than on a
        # customer's counter.
        if ($mb -lt 15) {
            throw ("فایل اجرایی تنها $mb مگابایت است؛ به‌نظر می‌رسد مفسر پایتون " +
                   "و وابستگی‌ها داخل آن جاسازی نشده‌اند. فایل نصب روی سیستمی " +
                   "که پایتون ندارد کار نخواهد کرد. مرحله نصب وابستگی‌ها را بررسی کنید.")
        }
        & $Report "فایل اجرایی خودکفا ساخته شد ($mb مگابایت)."

        # ALWAYS publish a portable copy. Even when Inno Setup is missing the
        # user walks away with something that runs (from v0.4.0).
        $portable = Join-Path $OutputDir "SupermarketSystem-$Version-portable.exe"
        Copy-Item $exe $portable -Force
        $Script:Portable = $portable
        & $Report "نسخه قابل‌حمل (بدون نیاز به نصب): $portable"
    }}

    @{ Name = 'ساخت فایل نصب نهایی (Setup.exe)'; Action = {
        param($Report)
        if (-not $Script:Iscc) {
            if ($Script:RequireSetup) {
                throw ("Inno Setup 6 روی این سیستم نصب نیست و دانلود خودکار غیرفعال است.`n" +
                       "نسخه قابل‌حمل ساخته شد و به‌تنهایی کار می‌کند:`n  $Script:Portable`n" +
                       "برای ساخت Setup.exe کلاسیک، Inno Setup 6 را از " +
                       "https://jrsoftware.org/isdl.php نصب کنید و دوباره اجرا کنید.")
            }
            & $Report 'Inno Setup نصب نیست؛ فقط نسخه قابل‌حمل ساخته شد (خطا نیست).'
            return
        }
        & $Report 'اجرای Inno Setup ...'
        Invoke-Native -FilePath $Script:Iscc -WorkingDirectory $ScriptDir -Report $Report `
            -Arguments @("/DMyAppVersion=$Version", 'setup.iss')

        $setup = Join-Path $OutputDir "SupermarketSystem-Setup-$Version.exe"
        if (-not (Test-Path $setup)) {
            throw "Inno Setup بدون خطا تمام شد اما فایل نصب ساخته نشد:`n$setup"
        }
        $mb = [math]::Round((Get-Item $setup).Length / 1MB, 1)
        if ($mb -lt 10) {
            throw "فایل نصب تنها $mb مگابایت است؛ احتمالاً فایل اجرایی داخل آن قرار نگرفته."
        }
        & $Report "فایل نصب آماده توزیع است ($mb مگابایت)."
        & $Report 'این فایل کاملاً خودکفاست: روی سیستم مقصد نه پایتون لازم است نه هیچ پیش‌نیاز دیگری.'
        & $Report "مسیر: $setup"
        $Script:FinalSetup = $setup
    }}
)
