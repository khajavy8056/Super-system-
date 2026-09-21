<#
================================================================================
 Supermarket System - graphical Setup builder
================================================================================
 Shows a WPF window with a progress bar, checks/installs every prerequisite,
 and produces one distributable file:

     installer\output\SupermarketSystem-Setup-<version>.exe

 Design notes that matter:

 * DPI / monitor scaling. A WPF window is laid out in device-independent
   units (1/96 inch), so it is correctly sized on 4K, 125%/150%/200% scaling
   and on an old 1366x768 laptop WITHOUT us hardcoding pixels. We additionally
   declare PerMonitorV2 awareness so the window re-renders crisply when dragged
   between monitors of different scaling, instead of being bitmap-stretched
   and blurry. Size is clamped to the WORK AREA (not the raw screen) so the
   window never hides behind the taskbar on a small display.

 * Errors. Every external command is run through Invoke-Step, which captures
   stdout+stderr, checks the exit code, writes a transcript, and turns any
   failure into a readable Persian message plus the real underlying error.
   $ErrorActionPreference = 'Stop' makes non-terminating errors fatal too, so
   nothing fails silently half-way and leaves a broken Setup.exe behind.

 * The build runs on a BACKGROUND runspace. If it ran on the UI thread the
   window would freeze ("Not Responding") for the several minutes the build
   takes, which users reasonably read as a crash.
================================================================================
#>
[CmdletBinding()]
param(
    # Build without showing the window (for CI). Progress goes to stdout.
    [switch]$Silent
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# ---------------------------------------------------------------------------
# Shared build logic (functions + the $Steps list).
# Kept in a separate file so the background runspace can load it without
# re-executing the window code below.
#
# $ScriptDir MUST be assigned before the dot-source. builder-lib.ps1 derives
# the repository root, the log path and the output path from it, and
# Set-StrictMode -Version Latest turns an unassigned variable read into a
# terminating error -- which is exactly what v0.3.1 did here, so the window
# never appeared and build.ps1 exited with code 1 before printing anything.
# ---------------------------------------------------------------------------
$ScriptDir = $PSScriptRoot
if (-not $ScriptDir) { $ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition }

. (Join-Path $ScriptDir 'builder-lib.ps1')

# ---------------------------------------------------------------------------
# Silent / CI mode
# ---------------------------------------------------------------------------
if ($Silent) {
    $i = 0
    foreach ($s in $Steps) {
        $i++
        Write-Host ("[{0}/{1}] {2}" -f $i, $Steps.Count, $s.Name)
        & $s.Action ([scriptblock]::Create('param($m) Write-Host "      $m"'))
    }
    if (-not $Script:FinalSetup) { throw 'ساخت تمام شد اما مسیر فایل نصب ثبت نشد.' }
    Write-Host "OK: $Script:FinalSetup"
    exit 0
}

# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------
$dpiMode = Enable-DpiAwareness
Write-Log "DPI awareness: $dpiMode"

try {
    Add-Type -AssemblyName PresentationFramework, PresentationCore, WindowsBase
} catch {
    # Without WPF we cannot show anything graphical; tell the user plainly
    # instead of dying with a raw .NET stack trace.
    $msg = "این سیستم از رابط گرافیکی WPF پشتیبانی نمی‌کند.`n`n" +
           "لطفاً نسخه متنی را اجرا کنید:`n" +
           "powershell -ExecutionPolicy Bypass -File builder-gui.ps1 -Silent`n`nجزئیات: $_"
    try { [void][System.Reflection.Assembly]::LoadWithPartialName('System.Windows.Forms')
          [System.Windows.Forms.MessageBox]::Show($msg) } catch { Write-Host $msg }
    exit 1
}

# NOTE: xmlns:x must be declared; SizeToContent + MinWidth/MinHeight in
# device-independent units is what makes this correct at any DPI.
[xml]$xaml = @'
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="سازنده فایل نصب - سیستم مدیریت فروشگاه"
        Width="760" Height="560" MinWidth="640" MinHeight="480"
        WindowStartupLocation="CenterScreen"
        FlowDirection="RightToLeft"
        Background="#0F172A"
        TextOptions.TextFormattingMode="Ideal"
        TextOptions.TextRenderingMode="ClearType"
        UseLayoutRounding="True" SnapsToDevicePixels="True">
  <Window.Resources>
    <FontFamily x:Key="UiFont">Segoe UI, Tahoma, Iran Sans, Arial</FontFamily>
    <Style TargetType="TextBlock">
      <Setter Property="FontFamily" Value="{StaticResource UiFont}"/>
      <Setter Property="Foreground" Value="#E2E8F0"/>
    </Style>
    <Style TargetType="Button">
      <Setter Property="FontFamily" Value="{StaticResource UiFont}"/>
      <Setter Property="Padding" Value="18,9"/>
      <Setter Property="MinWidth" Value="120"/>
      <Setter Property="FontSize" Value="14"/>
      <Setter Property="Cursor" Value="Hand"/>
      <Setter Property="Background" Value="#2563EB"/>
      <Setter Property="Foreground" Value="White"/>
      <Setter Property="BorderThickness" Value="0"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="Button">
            <Border x:Name="b" CornerRadius="8" Background="{TemplateBinding Background}"
                    Padding="{TemplateBinding Padding}">
              <ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsMouseOver" Value="True">
                <Setter TargetName="b" Property="Opacity" Value="0.88"/>
              </Trigger>
              <Trigger Property="IsEnabled" Value="False">
                <Setter TargetName="b" Property="Background" Value="#334155"/>
                <Setter Property="Foreground" Value="#94A3B8"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>
  </Window.Resources>

  <Grid Margin="22">
    <Grid.RowDefinitions>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="*"/>
      <RowDefinition Height="Auto"/>
    </Grid.RowDefinitions>

    <StackPanel Grid.Row="0">
      <TextBlock Text="ساخت فایل نصب سیستم مدیریت فروشگاه"
                 FontSize="21" FontWeight="Bold" Foreground="White"/>
      <TextBlock x:Name="TxtSubtitle" FontSize="13" Foreground="#94A3B8" Margin="0,6,0,0"
                 TextWrapping="Wrap"
                 Text="این ابزار همه پیش‌نیازها را بررسی و در صورت نیاز نصب می‌کند، سپس یک فایل Setup.exe کامل و قابل توزیع می‌سازد."/>
    </StackPanel>

    <Border Grid.Row="1" Background="#1E293B" CornerRadius="10" Padding="16,13" Margin="0,18,0,0">
      <StackPanel>
        <TextBlock x:Name="TxtStep" Text="آماده شروع" FontSize="15" FontWeight="SemiBold"/>
        <TextBlock x:Name="TxtDetail" Text="برای شروع، دکمه «شروع ساخت» را بزنید."
                   FontSize="12" Foreground="#94A3B8" Margin="0,5,0,0" TextWrapping="Wrap"/>
      </StackPanel>
    </Border>

    <Grid Grid.Row="2" Margin="0,14,0,0">
      <Grid.ColumnDefinitions>
        <ColumnDefinition Width="*"/>
        <ColumnDefinition Width="Auto"/>
      </Grid.ColumnDefinitions>
      <ProgressBar x:Name="Bar" Grid.Column="0" Height="22" Minimum="0" Maximum="100" Value="0"
                   Background="#0B1220" Foreground="#22C55E" BorderThickness="0"/>
      <TextBlock x:Name="TxtPct" Grid.Column="1" Text="۰٪" Margin="12,0,0,0"
                 VerticalAlignment="Center" FontSize="14" FontWeight="Bold"/>
    </Grid>

    <Border Grid.Row="3" Background="#0B1220" CornerRadius="10" Margin="0,14,0,0">
      <ScrollViewer x:Name="LogScroll" VerticalScrollBarVisibility="Auto" Padding="12">
        <!-- RightToLeft: the log is mostly Persian sentences, which read
             wrongly under LTR. Windows' bidi algorithm still renders the
             embedded LTR runs (paths, versions, pip output) correctly. -->
        <TextBlock x:Name="TxtLog" FontFamily="Consolas, Courier New" FontSize="12"
                   Foreground="#CBD5E1" TextWrapping="Wrap" FlowDirection="RightToLeft"/>
      </ScrollViewer>
    </Border>

    <StackPanel Grid.Row="4" Orientation="Horizontal" HorizontalAlignment="Left" Margin="0,16,0,0">
      <Button x:Name="BtnStart" Content="شروع ساخت"/>
      <Button x:Name="BtnFolder" Content="بازکردن پوشه خروجی" Margin="10,0,0,0"
              Background="#334155" IsEnabled="False"/>
      <Button x:Name="BtnLog" Content="نمایش گزارش" Margin="10,0,0,0" Background="#334155"/>
      <Button x:Name="BtnClose" Content="بستن" Margin="10,0,0,0" Background="#334155"/>
    </StackPanel>
  </Grid>
</Window>
'@

$reader = New-Object System.Xml.XmlNodeReader $xaml
$Win = [Windows.Markup.XamlReader]::Load($reader)

$TxtStep   = $Win.FindName('TxtStep')
$TxtDetail = $Win.FindName('TxtDetail')
$TxtLog    = $Win.FindName('TxtLog')
$TxtPct    = $Win.FindName('TxtPct')
$Bar       = $Win.FindName('Bar')
$BtnStart  = $Win.FindName('BtnStart')
$BtnFolder = $Win.FindName('BtnFolder')
$BtnLog    = $Win.FindName('BtnLog')
$BtnClose  = $Win.FindName('BtnClose')
$LogScroll = $Win.FindName('LogScroll')

# Never open larger than the WORK AREA: on a 1366x768 laptop a 760x560 window
# fits, but with a taskbar and 150% scaling it would otherwise overflow.
$wa = [System.Windows.SystemParameters]::WorkArea
if ($Win.Width  -gt $wa.Width)  { $Win.Width  = [Math]::Max(560, $wa.Width  - 40) }
if ($Win.Height -gt $wa.Height) { $Win.Height = [Math]::Max(440, $wa.Height - 40) }

# --- thread-safe UI helpers -------------------------------------------------
$Sync = [hashtable]::Synchronized(@{ Cancelled = $false })

# Marshalling a closure into another runspace does not carry its variable
# scope, so the worker gets a Dispatcher-based updater built from explicit
# references rather than a closure over $Win.
$UiRefs = @{
    Dispatcher = $Win.Dispatcher
    Step = $TxtStep; Detail = $TxtDetail; Log = $TxtLog
    Pct = $TxtPct;   Bar = $Bar;          Scroll = $LogScroll
}

function Set-Ui {
    param([string]$Step, [string]$Detail, $Percent, [string]$LogLine)
    Update-Ui -Refs $UiRefs -Step $Step -Detail $Detail -Percent $Percent -LogLine $LogLine
}

# --- run the build on a background runspace ---------------------------------
$BtnStart.Add_Click({
    $BtnStart.IsEnabled = $false
    $TxtLog.Text = ''
    Set-Ui -Step 'در حال شروع ...' -Detail '' -Percent 0

    # A runspace (not a Job) keeps the work in-process, so the steps can use
    # the functions and variables already defined here without re-importing.
    $ps = [powershell]::Create()
    $ps.Runspace = [runspacefactory]::CreateRunspace()
    $ps.Runspace.ApartmentState = 'STA'
    $ps.Runspace.ThreadOptions  = 'ReuseThread'
    $ps.Runspace.Open()

    # Marshal everything the worker needs into the new runspace.
    $ps.Runspace.SessionStateProxy.SetVariable('UiRefs',     $UiRefs)
    $ps.Runspace.SessionStateProxy.SetVariable('LogFile',    $LogFile)
    $ps.Runspace.SessionStateProxy.SetVariable('OutputDir',  $OutputDir)
    $ps.Runspace.SessionStateProxy.SetVariable('RepoRoot',   $RepoRoot)
    $ps.Runspace.SessionStateProxy.SetVariable('WorkDir',    $WorkDir)
    $ps.Runspace.SessionStateProxy.SetVariable('ScriptDir',  $ScriptDir)
    $ps.Runspace.SessionStateProxy.SetVariable('Version',    $Version)
    $ps.Runspace.SessionStateProxy.SetVariable('ScriptPath', $MyInvocation.MyCommand.Definition)
    # Build options must travel too, or the worker silently falls back to the
    # library defaults and downloads prerequisites the user declined.
    $ps.Runspace.SessionStateProxy.SetVariable('Script:AllowDownloads', $Script:AllowDownloads)
    $ps.Runspace.SessionStateProxy.SetVariable('Script:RequireSetup',   $Script:RequireSetup)

    [void]$ps.AddScript({
        param()
        Set-StrictMode -Version Latest
        $ErrorActionPreference = 'Stop'
        # Load the shared logic. This file contains no UI code, so importing
        # it here cannot spawn a second window.
        . (Join-Path $ScriptDir 'builder-lib.ps1')

        # Rebuild the reporter from the marshalled Dispatcher references.
        $SetUiFn = {
            param($Step, $Detail, $Percent, $LogLine)
            Update-Ui -Refs $UiRefs -Step $Step -Detail $Detail -Percent $Percent -LogLine $LogLine
        }

        $total = $Steps.Count
        $i = 0
        try {
            foreach ($s in $Steps) {
                $i++
                $base = [double](($i - 1) * 100 / $total)
                & $SetUiFn -Step ("مرحله $i از $total - " + $s.Name) -Percent $base -LogLine ("== " + $s.Name)
                $report = { param($m) & $SetUiFn -Detail $m -LogLine ("   " + $m) }.GetNewClosure()
                & $s.Action $report
                & $SetUiFn -Percent ([double]($i * 100 / $total))
            }
            & $SetUiFn -Step '✅ ساخت با موفقیت به پایان رسید' `
                       -Detail "فایل نصب در پوشه installer\output آماده توزیع است." `
                       -Percent 100 -LogLine '== DONE'
            return @{ ok = $true }
        } catch {
            $msg = $_.Exception.Message
            "[FATAL] $msg"          | Out-File -FilePath $LogFile -Append -Encoding utf8
            $_.ScriptStackTrace     | Out-File -FilePath $LogFile -Append -Encoding utf8
            & $SetUiFn -Step '❌ ساخت ناموفق بود' -Detail $msg -LogLine ("!! " + $msg)
            return @{ ok = $false; error = $msg }
        }
    })

    # EndInvoke on completion keeps the UI responsive throughout.
    $handle = $ps.BeginInvoke()
    $timer = New-Object System.Windows.Threading.DispatcherTimer
    $timer.Interval = [TimeSpan]::FromMilliseconds(300)
    $timer.Add_Tick({
        if (-not $handle.IsCompleted) { return }
        $timer.Stop()
        $res = $null
        try { $res = $ps.EndInvoke($handle) } catch {
            Set-Ui -Step '❌ خطای غیرمنتظره' -Detail $_.Exception.Message -LogLine ("!! " + $_)
        }
        $ps.Runspace.Close(); $ps.Dispose()
        $BtnStart.IsEnabled = $true
        $ok = $false
        if ($res -and $res.Count -gt 0 -and $res[0].ok) { $ok = $true }
        if ($ok) { $BtnFolder.IsEnabled = $true }
    })
    $timer.Start()
})

$BtnFolder.Add_Click({ Start-Process explorer.exe $OutputDir })
$BtnLog.Add_Click({ Start-Process notepad.exe $LogFile })
$BtnClose.Add_Click({ $Win.Close() })

# --- GUI-ONLY BELOW ---
[void]$Win.ShowDialog()
exit 0
