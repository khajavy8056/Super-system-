param(
    [string]$Root = "",
    [ValidateRange(1,3660)][int]$Days = 365,
    [ValidateRange(1,10000)][int]$PerDay = 1100,
    [ValidateRange(0,3660)][int]$PauseAfterDays = 0
)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding
$ProgressPreference = 'Continue'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$Version = '3.6.4'
$BundleHash = 'c8d0e36f00d19d41ef6d18bba9f172d3a2d9246be58249891b53f63386514a4f'
$Base = "https://raw.githubusercontent.com/khajavy8056/Super-system-/v$Version"
function Download($Url, $Path) {
    for ($attempt = 1; $attempt -le 3; $attempt++) {
        try {
            Invoke-WebRequest -UseBasicParsing -Uri $Url -OutFile "$Path.partial" -TimeoutSec 180
            Move-Item -LiteralPath "$Path.partial" -Destination $Path -Force
            return
        } catch {
            if ($attempt -eq 3) { throw }
            Write-Host "Download failed; retry $attempt/3 ..."
            Start-Sleep -Seconds 3
        }
    }
}
function Run($Exe, [string[]]$Arguments) {
    & $Exe @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Command failed (exit $LASTEXITCODE): $Exe $Arguments" }
}
$transcript = $false
$lock = $null
$rc = 1
try {
    if (-not [Environment]::Is64BitOperatingSystem) { throw 'Windows 10/11 64-bit is required.' }
    if (-not $Root) {
        $default = Join-Path $env:USERPROFILE "SupermarketDemo\$Version"
        $Root = Read-Host "Output/work folder (use an NTFS disk with ample free space). Enter = $default"
        if (-not $Root) { $Root = $default }
    }
    $Root = [IO.Path]::GetFullPath($Root)
    New-Item -ItemType Directory -Force -Path $Root | Out-Null
    # Protect installation as well as simulation from simultaneous double-clicks.
    $lock = [IO.File]::Open((Join-Path $Root 'launcher.lock'), 'OpenOrCreate', 'ReadWrite', 'None')
    Start-Transcript -Path (Join-Path $Root ("run-" + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.log')) | Out-Null
    $transcript = $true
    Write-Host 'SYNTHETIC STORE. This does not modify your installed shop database.'
    Write-Host 'Internet is needed for initial setup. Do not let this computer sleep during generation.'
    $kit = Join-Path $Root 'kit'
    $marker = Join-Path $kit 'bundle.sha256'
    if (Test-Path $kit) {
        if (-not (Test-Path $marker) -or (Get-Content $marker -Raw).Trim() -ne $BundleHash) {
            throw 'Incomplete/different kit. Choose a NEW Root folder; existing simulation has not been deleted.'
        }
    } else {
        $zip = Join-Path $Root 'generator.zip'
        Download "$Base/releases/generator/SupermarketDemo-$Version.zip" $zip
        if ((Get-FileHash $zip -Algorithm SHA256).Hash -ne $BundleHash) { throw 'Generator checksum mismatch; nothing was executed.' }
        $staging = Join-Path $Root 'kit-staging'
        if (Test-Path $staging) { Remove-Item -LiteralPath $staging -Recurse -Force }
        Expand-Archive -LiteralPath $zip -DestinationPath $staging
        Set-Content -LiteralPath (Join-Path $staging 'bundle.sha256') -Value $BundleHash -Encoding ASCII
        Move-Item -LiteralPath $staging -Destination $kit
    }
    $venv = Join-Path $Root 'venv'
    $python = Join-Path $venv 'Scripts\python.exe'
    if (-not (Test-Path $python)) {
        $runtime = Join-Path $Root 'python-runtime'
        $basePython = Join-Path $runtime 'python.exe'
        if (-not (Test-Path $basePython)) {
            # Prefer an existing compatible interpreter; do not modify its packages.
            foreach ($command in @('py','python')) {
                $exe = Get-Command $command -ErrorAction SilentlyContinue
                if (-not $exe -or $exe.Source -like '*WindowsApps*') { continue }
                $probeArgs = @('-c','import sys; assert sys.version_info >= (3,11); print(sys.executable)')
                if ($command -eq 'py') { $probeArgs = @('-3') + $probeArgs }
                $probe = & $exe.Source @probeArgs
                if ($LASTEXITCODE -eq 0 -and $probe -and (Test-Path ([string]$probe))) {
                    $basePython = [string]$probe
                    break
                }
            }
        }
        if (-not (Test-Path $basePython)) {
            Write-Host 'Finding the latest available official Python 3.13 Windows installer ...'
            $index = Invoke-WebRequest -UseBasicParsing -Uri 'https://www.python.org/ftp/python/' -TimeoutSec 90
            $versions = [regex]::Matches($index.Content, 'href="(3\.13\.\d+)/"') | ForEach-Object { [version]$_.Groups[1].Value } | Sort-Object -Unique -Descending
            $installer = Join-Path $Root 'python-installer.exe'
            $found = $false
            foreach ($v in ($versions | Select-Object -First 8)) {
                try {
                    Download "https://www.python.org/ftp/python/$v/python-$v-amd64.exe" $installer
                    $found = $true
                    break
                } catch { Write-Host "No downloadable installer for $v; checking the next version." }
            }
            if (-not $found) { throw 'Cannot download Python. Check access to python.org and retry.' }
            $signature = Get-AuthenticodeSignature -LiteralPath $installer
            if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'O=Python Software Foundation(?:,|$)') {
                throw 'Python installer signature/publisher verification failed. Installer was NOT executed.'
            }
            $installArgs = "/quiet InstallAllUsers=0 Include_launcher=0 Include_test=0 PrependPath=0 TargetDir=`"$runtime`" /log `"$Root\python-install.log`""
            $p = Start-Process -FilePath $installer -ArgumentList $installArgs -Wait -PassThru
            if ($p.ExitCode -notin @(0,3010)) { throw "Python installation failed ($($p.ExitCode)); see python-install.log" }
        }
        Run $basePython @('-m','venv',$venv)
    }
    Run $python @('-c','import sys; assert sys.version_info >= (3,11), "Python 3.11+ required"')
    $req = Join-Path $kit 'backend\requirements.txt'
    $frozen = Join-Path $Root 'requirements.installed.txt'
    # Reuse EXACT dependency versions across resumes, not the newest releases.
    if (Test-Path $frozen) { $req = $frozen }
    Run $python @('-m','pip','install','--disable-pip-version-check','--require-virtualenv','-r',$req)
    Run $python @('-m','pip','check')
    if (-not (Test-Path $frozen)) {
        $freeze = & $python -m pip freeze
        if ($LASTEXITCODE -ne 0) { throw 'Cannot record installed dependency versions.' }
        $freeze | Set-Content -LiteralPath $frozen -Encoding ASCII
    }
    $env:PYTHONUTF8 = '1'
    $out = Join-Path $Root 'store-year.db.gz'
    $work = "$out.work"
    $argsList = @((Join-Path $kit 'tools\make_stress_backup.py'),'--no-bootstrap','--days',"$Days",'--per-day',"$PerDay",'--out',$out,'--work-dir',$work)
    if (Test-Path (Join-Path $work 'demo.db')) {
        Write-Host 'Resuming from last committed day (same parameters/code required).'
        $argsList += '--resume'
    }
    if ($PauseAfterDays -gt 0) { $argsList += @('--pause-after-days',"$PauseAfterDays") }
    & $python @argsList
    $rc = $LASTEXITCODE
    if ($rc -eq 0) { Write-Host "SUCCESS: validated backup: $out" }
    elseif ($rc -eq 75) { Write-Host 'PAUSED safely. Run this BAT again with the same parameters to continue. No final backup yet.' }
    else { Write-Host "FAILED ($rc). Do NOT restore an unvalidated file. See the log in $Root." }
} catch {
    Write-Host "FAILED: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host 'Retry with the same folder/parameters. Never delete your working database to fix a download problem.'
    $rc = 1
} finally {
    if ($transcript) { Stop-Transcript | Out-Null }
    if ($lock) { $lock.Dispose() }
}
exit $rc
