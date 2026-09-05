<#
================================================================================
 builder-lib.ps1 - shared logic for the Supermarket System setup builder.
================================================================================
 Dot-sourced by BOTH builder-gui.ps1 (UI thread) and the background runspace
 that actually performs the build. Keeping it in its own file is what makes
 that safe: the worker can load every function and the $Steps list WITHOUT
 re-executing the window code, which would otherwise spawn a second GUI.

 Contains no UI calls. Progress is reported through a $Report scriptblock the
 caller supplies, so the same code drives the WPF window and -Silent/CI mode.
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
$OutputDir = Join-Path $RepoRoot 'installer\output'

New-Item -ItemType Directory -Force -Path $WorkDir   | Out-Null
New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
"=== Supermarket System setup build @ $(Get-Date -Format s) ===" |
    Out-File -FilePath $LogFile -Encoding utf8

function Write-Log {
    param([string]$Message, [string]$Level = 'INFO')
    "[{0}] [{1}] {2}" -f (Get-Date -Format 'HH:mm:ss'), $Level, $Message |
        Out-File -FilePath $LogFile -Append -Encoding utf8
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
# Lives here, not in the GUI file, so the background runspace and the UI
# thread share ONE definition. Takes explicit control references because a
# closure's variable scope does not survive being marshalled across runspaces.
function Update-Ui {
    param(
        [hashtable]$Refs, [string]$Step, [string]$Detail,
        $Percent, [string]$LogLine
    )
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
# Each step: Name (Persian, shown in the UI) + Action (scriptblock).
# $Report is a scriptblock the action calls to push detail lines to the UI.

function Invoke-Native {
    <#
      Run an external program, capture BOTH streams, and throw a readable
      error when it fails. Using the call operator with a redirect (rather
      than Start-Process) keeps output ordered and avoids a stray console.
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

        # 2>&1 merges stderr into the pipeline; many tools (pip, PyInstaller)
        # write ordinary progress to stderr, so treating it as failure would
        # produce constant false alarms. The exit code is the real verdict.
        $output = & $FilePath @Arguments 2>&1 | ForEach-Object {
            $line = $_.ToString()
            Write-Log "    $line"
            $line
        }
        if ($LASTEXITCODE -ne 0) {
            $tail = ($output | Select-Object -Last 15) -join "`n"
            throw ("خطا در اجرای {0} (کد خروج {1}).`n--- آخرین خروجی ---`n{2}" -f `
                   (Split-Path -Leaf $FilePath), $LASTEXITCODE, $tail)
        }
        return $output
    } finally {
        if ($prev) { Set-Location $prev }
    }
}

function Find-Python {
    <#
      Locate a usable Python >= 3.11. Order matters: the py launcher is the
      most reliable on Windows, then PATH, then the standard per-user install
      location that our own bootstrap uses.
    #>
    $candidates = @()
    $py = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($py) { $candidates += ,@($py.Source, @('-3', '-c', 'import sys;print(sys.executable)')) }
    foreach ($n in 'python.exe', 'python3.exe') {
        $c = Get-Command $n -ErrorAction SilentlyContinue
        if ($c) { $candidates += ,@($c.Source, @('-c', 'import sys;print(sys.executable)')) }
    }
    $local = Join-Path $env:LOCALAPPDATA 'Programs\Python'
    if (Test-Path $local) {
        Get-ChildItem $local -Directory -ErrorAction SilentlyContinue |
            Sort-Object Name -Descending | ForEach-Object {
                $exe = Join-Path $_.FullName 'python.exe'
                if (Test-Path $exe) { $candidates += ,@($exe, @('-c', 'import sys;print(sys.executable)')) }
            }
    }

    foreach ($cand in $candidates) {
        try {
            $exe = & $cand[0] @($cand[1]) 2>$null
            if ($LASTEXITCODE -ne 0 -or -not $exe) { continue }
            $exe = ($exe | Select-Object -First 1).ToString().Trim()
            $ver = & $exe -c 'import sys;print("%d.%d"%sys.version_info[:2])' 2>$null
            if ($LASTEXITCODE -ne 0) { continue }
            $parts = $ver.Trim().Split('.')
            if ([int]$parts[0] -eq 3 -and [int]$parts[1] -ge 11) {
                Write-Log "Found Python $ver at $exe"
                return $exe
            }
            Write-Log "Ignoring Python $ver at $exe (need >= 3.11)"
        } catch { continue }
    }
    return $null
}

function Install-Python {
    param([scriptblock]$Report)
    $arch = if ([Environment]::Is64BitOperatingSystem) { 'amd64' } else { 'win32' }
    $pyVer = '3.11.9'
    $url = "https://www.python.org/ftp/python/$pyVer/python-$pyVer-$arch.exe"
    $dst = Join-Path $WorkDir "python-$pyVer-$arch.exe"

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

    & $Report 'نصب پایتون (بدون نیاز به دسترسی مدیر) ...'
    # InstallAllUsers=0 keeps this a per-user install => no UAC prompt.
    Invoke-Native -FilePath $dst -Report $Report -Arguments @(
        '/quiet', 'InstallAllUsers=0', 'PrependPath=1',
        'Include_pip=1', 'Include_launcher=1', 'AssociateFiles=0'
    )

    # The installer updates PATH for FUTURE processes only; refresh ours so the
    # very next step can find python without asking the user to reboot.
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' +
                [Environment]::GetEnvironmentVariable('Path', 'User')

    $exe = Find-Python
    if (-not $exe) { throw 'پایتون نصب شد اما پیدا نشد. لطفاً یک‌بار ویندوز را restart کنید و دوباره تلاش کنید.' }
    return $exe
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
    $url = 'https://files.jrsoftware.org/is/6/innosetup-6.2.2.exe'
    $dst = Join-Path $WorkDir 'innosetup-6.2.2.exe'
    & $Report 'دانلود Inno Setup ...'
    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        $ProgressPreference = 'SilentlyContinue'
        Invoke-WebRequest -Uri $url -OutFile $dst -UseBasicParsing
    } catch {
        throw "دانلود Inno Setup ناموفق بود. اتصال اینترنت را بررسی کنید.`nجزئیات: $_"
    }
    & $Report 'نصب Inno Setup ...'
    Invoke-Native -FilePath $dst -Report $Report -Arguments @(
        '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/SP-'
    )
    $iscc = Find-InnoSetup
    if (-not $iscc) { throw 'Inno Setup نصب شد اما ISCC.exe پیدا نشد.' }
    return $iscc
}

# --- the ordered step list --------------------------------------------------
# Declared up-front: Set-StrictMode makes reading an undefined variable a
# terminating error, so every cross-step variable must exist before use.
$Script:PythonExe  = $null
$Script:VenvPy     = $null
$Script:Iscc       = $null
$Script:FinalSetup = $null

$Steps = @(
    @{ Name = 'بررسی سیستم و پیش‌نیازها'; Action = {
        param($Report)
        & $Report "ویندوز: $([Environment]::OSVersion.VersionString)"
        & $Report ("معماری: " + $(if ([Environment]::Is64BitOperatingSystem) { '64-bit' } else { '32-bit' }))
        & $Report "پوشهٔ پروژه: $RepoRoot"
        if (-not (Test-Path (Join-Path $RepoRoot 'backend\requirements.txt'))) {
            throw "پوشهٔ پروژه ناقص است: backend\requirements.txt پیدا نشد.`nBUILD-SETUP.bat باید داخل installer\windows\ همان مخزن باقی بماند."
        }
        & $Report 'ساختار پروژه سالم است.'
    }}

    @{ Name = 'یافتن یا نصب پایتون ۳٫۱۱+'; Action = {
        param($Report)
        $exe = Find-Python
        if ($exe) {
            $v = & $exe -c 'import sys;print("%d.%d.%d"%sys.version_info[:3])'
            & $Report "پایتون $($v.Trim()) پیدا شد."
        } else {
            & $Report 'پایتون مناسبی یافت نشد؛ نصب خودکار آغاز می‌شود.'
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
        & $Report 'همهٔ وابستگی‌ها نصب شدند.'
    }}

    @{ Name = 'یافتن یا نصب Inno Setup'; Action = {
        param($Report)
        $iscc = Find-InnoSetup
        if ($iscc) { & $Report "Inno Setup پیدا شد: $iscc" }
        else {
            & $Report 'Inno Setup یافت نشد؛ نصب خودکار آغاز می‌شود.'
            $iscc = Install-InnoSetup -Report $Report
            & $Report 'Inno Setup نصب شد.'
        }
        $Script:Iscc = $iscc
    }}

    @{ Name = 'ساخت فایل اجرایی برنامه'; Action = {
        param($Report)
        & $Report 'اجرای PyInstaller (طولانی‌ترین مرحله) ...'
        Invoke-Native -FilePath $Script:VenvPy -WorkingDirectory $ScriptDir -Report $Report `
            -Arguments @('-m', 'PyInstaller', '--clean', '--noconfirm', 'app.spec')

        $exe = Join-Path $ScriptDir 'dist\SupermarketSystem.exe'
        if (-not (Test-Path $exe)) {
            throw "PyInstaller بدون خطا تمام شد اما فایل خروجی ساخته نشد:`n$exe"
        }
        $mb = [math]::Round((Get-Item $exe).Length / 1MB, 1)
        & $Report "فایل اجرایی ساخته شد ($mb مگابایت)."
    }}

    @{ Name = 'ساخت فایل نصب نهایی (Setup.exe)'; Action = {
        param($Report)
        & $Report 'اجرای Inno Setup ...'
        Invoke-Native -FilePath $Script:Iscc -WorkingDirectory $ScriptDir -Report $Report `
            -Arguments @("/DMyAppVersion=$Version", 'setup.iss')

        $setup = Join-Path $OutputDir "SupermarketSystem-Setup-$Version.exe"
        if (-not (Test-Path $setup)) {
            throw "Inno Setup بدون خطا تمام شد اما فایل نصب ساخته نشد:`n$setup"
        }
        $mb = [math]::Round((Get-Item $setup).Length / 1MB, 1)
        & $Report "فایل نصب آمادهٔ توزیع است ($mb مگابایت)."
        $Script:FinalSetup = $setup
    }}
)

