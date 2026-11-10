# Gets Pat, the Phone Agent Tool, ready on this laptop. Safe to run again: it skips what is already done, and picks up by itself after a restart.
#
#   powershell -ExecutionPolicy Bypass -File setup.ps1
#
# Windows asks you to approve anything that needs an administrator: turning on Developer Mode and installing drivers.
# It only makes a call if you ask it to, later. -Rehearse shows what it would do on a new laptop, and changes nothing.
# -ShortcutsOnly updates Pat's shortcuts without running the rest of setup. -Startup accepts Ask, On, Off or Keep.
param(
    [switch]$SkipModels,
    [switch]$Rehearse,
    [switch]$ShortcutsOnly,
    [ValidateSet('Ask', 'On', 'Off', 'Keep')][string]$Startup = 'Ask'
)
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$venv = "$root\.venv"
$python = "$venv\Scripts\python.exe"
. "$root\app\shortcuts.ps1"
if ($ShortcutsOnly) {
    Set-PatShortcuts -Root $root -Startup $Startup -Rehearse:$Rehearse
    return
}
$pythonVersion = '3.13'
$dotnetMajor = '10'
$vbcableZip = 'https://download.vb-audio.com/Download_CABLE/VBCABLE_Driver_Pack45.zip'
$vbcablePage = 'https://vb-audio.com/Cable/'
$todo = New-Object System.Collections.ArrayList
$needsRestart = $false

# Everything this prints also goes to a file, so a setup that fails on someone else's laptop can be sent for help.
# report.py adds the newest one to its bug report, with names and numbers taken out.
$setupLog = Join-Path $root "setup-logs\setup-$(Get-Date -Format 'yyyyMMdd-HHmmss').txt"
if ($Rehearse) {
    $setupLog = $null
} else {
    New-Item -ItemType Directory -Force (Split-Path $setupLog) | Out-Null
    try { Start-Transcript -Path $setupLog | Out-Null } catch { $setupLog = $null }
}
trap {
    Write-Host "`nSetup stopped: $_" -ForegroundColor Red
    if ($setupLog) { Write-Host "Everything it printed is in $setupLog. Send that file if you need help." -ForegroundColor Yellow }
    try { Stop-Transcript | Out-Null } catch { }
    break
}

function Step($text) { Write-Host "`n== $text" -ForegroundColor Cyan }
function Todo($text) { [void]$todo.Add($text); Write-Host "   Left for you: $text" -ForegroundColor Yellow }
function Check($what) { if ($LASTEXITCODE -ne 0) { throw "$what failed." } }
function Would($text) { Write-Host "   Would: $text" -ForegroundColor DarkGray }

function Refresh-Path {
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User')
}

function Install-WithWinget($id) {
    if ($Rehearse) { Would "install $id with winget"; return }
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) { throw "winget is missing, so install $id by hand and run this again." }
    winget install --id $id --exact --silent --accept-package-agreements --accept-source-agreements
    Check "Installing $id"
    Refresh-Path
}

function Has-Command($name) {
    return [bool](Get-Command $name -ErrorAction SilentlyContinue)
}

# With errors set to stop, a tool that's missing or says no would end this script, so ask quietly.
function Asks-Quietly($command, $arguments) {
    if (-not (Has-Command $command)) { return $null }
    $saved = $ErrorActionPreference
    $ErrorActionPreference = 'SilentlyContinue'
    try {
        $answer = & $command @arguments 2>$null
        if ($LASTEXITCODE -ne 0) { return $null }
        return @($answer) -join "`n"
    } catch { return $null } finally { $ErrorActionPreference = $saved }
}

function Find-Python {
    if ($null -ne (Asks-Quietly 'py' @("-$pythonVersion", '--version'))) { return @('py', "-$pythonVersion") }
    $installed = "$env:LOCALAPPDATA\Programs\Python\Python$($pythonVersion -replace '\.', '')\python.exe"
    if (Test-Path $installed) { return @($installed) }
    return $null
}

function Find-Claude {
    if ($env:VOICE_LOOP_CLAUDE) { return $env:VOICE_LOOP_CLAUDE }
    $onPath = Get-Command claude -ErrorAction SilentlyContinue
    if ($onPath) { return $onPath.Source }
    $found = Get-ChildItem "$env:LOCALAPPDATA\Claude-Data\*\claude-code\*\*\claude.exe" -ErrorAction SilentlyContinue |
        Sort-Object { try { [version]$_.Directory.Parent.Name } catch { [version]'0.0' } } | Select-Object -Last 1
    if ($found) { return $found.FullName }
    return $null
}

function Developer-Mode-Is-On {
    if ($Rehearse) { return $false }
    return (Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\AppModelUnlock' -ErrorAction SilentlyContinue).AllowDevelopmentWithoutDevLicense -eq 1
}

function Has-Driver($name) {
    if ($Rehearse) { return $false }
    return [bool](Get-CimInstance Win32_PnPSignedDriver -Filter "DeviceClass='MEDIA'" | Where-Object { $_.DeviceName -like "*$name*" })
}

# Runs something as administrator, after Windows asks you. False if you said no, or it wouldn't start.
function As-Admin($file, $arguments) {
    if ($Rehearse) { Would "ask Windows to run as administrator: $file $arguments"; return $true }
    try {
        Start-Process $file -ArgumentList $arguments -Verb RunAs -Wait
        return $true
    } catch {
        Write-Host "   Windows didn't run it: $($_.Exception.Message)" -ForegroundColor Yellow
        return $false
    }
}

function Install-VbCable {
    if ($Rehearse) { Would "download $vbcableZip"; Would 'run its setup silently, then with its window if that did not work'; return }
    $folder = Join-Path $env:TEMP 'pat-vbcable'
    Remove-Item $folder -Recurse -Force -ErrorAction SilentlyContinue
    New-Item -ItemType Directory $folder | Out-Null
    try {
        Invoke-WebRequest $vbcableZip -OutFile "$folder\vbcable.zip" -UseBasicParsing
        Expand-Archive "$folder\vbcable.zip" $folder
    } catch {
        Start-Process $vbcablePage
        Todo "VB-CABLE didn't download. Its page is open: download it, run VBCABLE_Setup_x64.exe as administrator, restart, and run this again."
        return
    }
    $installer = "$folder\VBCABLE_Setup_x64.exe"
    # The maker doesn't document a silent install, so if this doesn't take, its own window does it.
    [void](As-Admin $installer '-i -h')
    if (-not (Has-Driver 'VB-Audio Virtual Cable')) {
        Write-Host '   Click Install Driver in the window that opens.'
        [void](As-Admin $installer '')
    }
}

function Mobile-Access {
    # Settings > Bluetooth & devices > Mobile devices > 'Allow this PC to access your mobile devices'.
    # With it off, Windows connects the phone over Bluetooth but never makes the phone line Pat dials on.
    # Windows doesn't document this value; it was checked to follow the switch both ways (1 on, 0 off).
    # Returns 'on', 'off', or 'unknown' when Windows doesn't have the value.
    $mobility = Get-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Mobility' -ErrorAction SilentlyContinue
    if (-not $mobility -or $null -eq $mobility.CrossDeviceEnabled) { return 'unknown' }
    if ($mobility.CrossDeviceEnabled -eq 1) { return 'on' }
    return 'off'
}

function Wait-For-Mobile-Access {
    $state = Mobile-Access
    if ($state -eq 'on') { Write-Host "   'Allow this PC to access your mobile devices' is on."; return }
    Start-Process 'ms-settings:mobile-devices'
    if ($state -eq 'unknown') {
        Write-Host "   Pat couldn't read 'Allow this PC to access your mobile devices'. Its settings page is open: make sure it's on."
        return
    }
    # Required: without it Pat can't make or take a single call, so setup waits here rather than finish half-working.
    Write-Host "   'Allow this PC to access your mobile devices' is off. Without it, Windows won't make a phone line, so Pat can't work."
    Write-Host "   Its settings page is open: turn it on. Setup waits here until it's on (Ctrl+C stops setup)."
    $waited = 0
    while ((Mobile-Access) -ne 'on') {
        Start-Sleep -Seconds 2
        $waited += 2
        if ($waited % 60 -eq 0) {
            Write-Host "   Still off. Settings > Bluetooth & devices > Mobile devices > 'Allow this PC to access your mobile devices'."
            Start-Process 'ms-settings:mobile-devices'
        }
    }
    Write-Host "   It's on."
}

function Pick-Phone {
    Push-Location $root
    try { $said = & $python pat.py pick-phone 2>$null; $ok = $LASTEXITCODE -eq 0 } finally { Pop-Location }
    $global:LASTEXITCODE = 0
    if ($ok) { Write-Host "   $said" }
    return $ok
}

# Phone Link takes a phone's calls away from Pat: once it registers on the phone's pairing, Windows refuses Pat until the
# pairing is made again, and its setup screen can delete the pairing. Seen 5-6 Nov 2026. So it is ended if it runs, and its
# start at sign-in is turned off, each said in one line. "Mobile devices" didn't get in the way, so it is left alone.
$phoneLinkStart = 'HKCU:\Software\Classes\Local Settings\Software\Microsoft\Windows\CurrentVersion\AppModel\SystemAppData\Microsoft.YourPhone_8wekyb3d8bbwe\YourPhone.Start'

function Quiet-Phone-Link {
    if ($Rehearse) {
        Would 'end Phone Link if it is running, and turn off its start at sign-in if it is on'
        return
    }
    if (Get-Process PhoneExperienceHost -ErrorAction SilentlyContinue) {
        Get-Process PhoneExperienceHost -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
        Write-Host '   Ended Phone Link: while it runs, it can take your phone''s calls away from Pat.'
    }
    # State 2 means on; 0 and 1 are off (1 is "turned off by you"), and 3 and 4 are set by an administrator.
    $start = Get-ItemProperty $phoneLinkStart -ErrorAction SilentlyContinue
    if ($start -and $start.State -eq 2) {
        Set-ItemProperty $phoneLinkStart -Name State -Value 1
        Write-Host '   Turned off Phone Link''s start at sign-in, for the same reason. To undo: Settings > Apps > Startup.'
    }
}

function Set-Up-Phone {
    if ($Rehearse) {
        Would "check 'Allow this PC to access your mobile devices', and open its page if it is off"
        Would 'check for a phone that works for calls; if there is none, offer to set one up with iphonecall pair'
        return $true
    }
    Wait-For-Mobile-Access
    if (Pick-Phone) { return $true }
    Write-Host '   No phone works for Pat''s calls yet. Pat can set one up: it pairs the phone itself, so no other app can hold'
    Write-Host '   its calls. A window opens and walks you through it; keep Settings > Bluetooth open on your phone.'
    try { $answer = Read-Host '   Set up your phone for Pat''s calls now? [Y/n]' } catch { $answer = 'n' }
    if ($answer -match '^[Nn]') { return $false }
    $helper = (Get-Command iphonecall -ErrorAction SilentlyContinue).Source
    if (-not $helper) { return $false }
    Start-Process $helper -ArgumentList 'pair' -Wait
    # Right after pairing, a phone can take a minute before it accepts the call link.
    $deadline = (Get-Date).AddSeconds(60)
    while ((Get-Date) -lt $deadline) {
        if (Pick-Phone) { return $true }
        Start-Sleep -Seconds 5
    }
    return $false
}

function Ask-To-Restart {
    if ($Rehearse) { Would 'offer to restart, and carry on by itself afterwards'; return }
    $again = "powershell -NoExit -ExecutionPolicy Bypass -File `"$PSCommandPath`""
    Set-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\RunOnce' 'PatSetup' $again
    try { $answer = Read-Host 'The audio drivers need a restart. This carries on by itself afterwards. Restart now? [Y/n]' } catch { $answer = 'n' }
    if ($answer -notmatch '^[Nn]') { try { Stop-Transcript | Out-Null } catch { }; Restart-Computer -Force; exit }
    Todo 'Restart the laptop. This setup carries on by itself afterwards.'
}

Step 'Windows'
$build = [Environment]::OSVersion.Version.Build
# Windows 10 can pair the phone and dial, but has no PhoneCall API (build 20348+) for answering, hanging up or moving a
# call's audio from an app: tried 10 Nov on build 19045, iphonecall crashed on GetAllActivePhoneCalls. See branch windows-10-trial.
if ($build -lt 22000) { throw "Pat needs Windows 11 (this is build $build). Windows 10 can pair your phone, but it doesn't let apps answer, hang up or move a call's audio." }
"Windows build $build"
# Run as administrator, setup still works, but everything per-user (Python, the Claude login, the phone tool, the
# mobile-devices switch) lands in the account that opened the window. Another account's password puts it in the wrong one.
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if ($isAdmin) {
    Write-Host "   This window runs as administrator, as $env:USERNAME. That's fine if this is the account that will use Pat." -ForegroundColor Yellow
    Write-Host '   If you typed another account''s password to open it, close it and run setup in a normal window instead:' -ForegroundColor Yellow
    Write-Host '   setup asks for administrator itself where it needs it.' -ForegroundColor Yellow
}

Step "Python $pythonVersion"
if ($Rehearse) {
    Would 'install Python if it is missing, create .venv and install the packages'
} else {
    if (-not (Test-Path $python)) {
        $base = Find-Python
        if (-not $base) {
            Install-WithWinget "Python.Python.$pythonVersion"
            $base = Find-Python
            if (-not $base) { throw "Python $pythonVersion was installed, but this window can't find it. Close it, open a new one, and run this again." }
        }
        # Split into the program and a LIST of its options. "$command, $options = $base" made $options a plain string
        # ('-3.13'), and PowerShell 5 splatting a string dropped the rest of the line, so py opened Python's >>> prompt
        # and setup waited there forever on laptops without Python.
        $command = @($base)[0]
        $options = @(@($base) | Select-Object -Skip 1)
        & $command @options -m venv $venv
        Check 'Creating the Python environment'
        if (-not (Test-Path $python)) { throw "Python didn't create the environment in $venv." }
    }
    # About 1.6 GB the first time. Its progress shows, so a long download doesn't look like a stuck setup.
    Write-Host '   Installing Pat''s Python packages: about 1.6 GB the first time, often 10-30 minutes. Leave this window open.'
    & $python -m pip install --disable-pip-version-check -r "$root\requirements.txt"
    Check 'Installing Python packages'
    & $python --version
}

Step 'Pat shortcuts'
Set-PatShortcuts -Root $root -Startup $Startup -Rehearse:$Rehearse

if ($SkipModels) {
    Step 'Speech models: skipped'
} elseif ($Rehearse) {
    Step 'Speech models'
    Would 'download the speech models, about 2 GB'
} else {
    Step 'Speech models (about 2 GB the first time)'
    Push-Location $root
    try { & $python pat.py prepare; Check 'Downloading speech models' } finally { Pop-Location }
}

Step 'Developer Mode'
if (Developer-Mode-Is-On) {
    'Already on.'
} else {
    if ($isAdmin) { 'iphonecall needs it. This window already runs as administrator, so it is turned on without asking.' }
    else { 'iphonecall needs it. Windows will ask you to approve.' }
    $key = 'HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\AppModelUnlock'
    [void](As-Admin 'reg.exe' "add `"$key`" /t REG_DWORD /f /v AllowDevelopmentWithoutDevLicense /d 1")
    if (Developer-Mode-Is-On) { 'It is on now.' }
}

Step 'iphonecall'
if ($Rehearse) {
    Install-WithWinget "Microsoft.DotNet.SDK.$dotnetMajor"
    Would 'build and install iphonecall'
} elseif (-not (Developer-Mode-Is-On)) {
    Start-Process 'ms-settings:developers'
    Todo 'Turn on Developer Mode in the page that just opened, then run this again.'
} else {
    $sdks = Asks-Quietly 'dotnet' @('--list-sdks')
    if (-not ($sdks -match "(?m)^$dotnetMajor\.")) { Install-WithWinget "Microsoft.DotNet.SDK.$dotnetMajor" }
    & "$root\iphone-hfp\iphonecall\build.ps1"
}

Step 'Claude Code'
$claude = Find-Claude
if ($Rehearse) {
    Would 'check Claude Code is logged in, and register the phone tool for every folder'
} elseif (-not $claude) {
    Todo 'Install the Claude Code app and log in, then run this again.'
} else {
    if ((Asks-Quietly $claude @('auth', 'status')) -notmatch '"loggedIn":\s*true') { Todo 'Open the Claude Code app and log in.' } else { 'Logged in.' }
    $saved = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    foreach ($name in 'pat-phone', 'cicero-phone') {  # its old name too. On a first run there's nothing to remove
        & $claude mcp remove --scope user $name *> $null
    }
    $ErrorActionPreference = $saved
    $global:LASTEXITCODE = 0
    & $claude mcp add --scope user pat-phone -- $python "$root\phone_mcp.py"
    Check 'Registering the phone tool'
    'Phone tool registered for every folder. Chats open before now keep using the old one until restarted.'
}

Step 'Audio drivers'
if (-not (Has-Driver 'VB-Audio Virtual Cable') -or -not ((Has-Driver 'Voicemeeter') -or (Has-Driver 'CABLE-A') -or (Has-Driver 'Boom Audio'))) {
    # Windows often makes a newly added audio device the default, and both of Pat's are silent. Setup moves the defaults
    # back right after installing, but a call or video already running on this laptop can go quiet until then.
    Write-Host '   Installing audio drivers. Your sound can cut out for a moment, and a call on this laptop may go quiet' -ForegroundColor Yellow
    Write-Host '   until setup puts your speaker and microphone back, right after.' -ForegroundColor Yellow
}
if (Has-Driver 'VB-Audio Virtual Cable') {
    'VB-CABLE is installed.'
} else {
    'Installing VB-CABLE. Windows will ask you to approve, and may ask whether to trust the driver.'
    Install-VbCable
    $needsRestart = $true
}
if ((Has-Driver 'Voicemeeter') -or (Has-Driver 'CABLE-A') -or (Has-Driver 'Boom Audio')) {
    'A silent speaker is installed.'
} else {
    'Installing Voicemeeter. Only its virtual speaker is used.'
    try {
        Install-WithWinget 'VB-Audio.Voicemeeter'
        if (-not $Rehearse) { Get-Process voicemeeter* -ErrorAction SilentlyContinue | Stop-Process -Force }  # if it runs, the call could reach the speakers
    } catch {
        Start-Process 'https://vb-audio.com/Voicemeeter/'
        Todo "Voicemeeter didn't install. Its page is open: install it, restart, leave the app closed, and run this again."
    }
    $needsRestart = $true
}
# Straight after the drivers too, not only after the restart: until then the new silent devices can be the defaults.
if ($Rehearse) {
    Would 'put the default speaker and microphone back on the real ones'
} else {
    Step 'Default speaker and microphone'
    Push-Location $root
    try { & $python pat.py fix-audio } finally { Pop-Location }
    $global:LASTEXITCODE = 0
}
if ($needsRestart) { Ask-To-Restart }

if ($Rehearse) {
    Would 'record 3 seconds from the microphone, to check it sends sound when you take over a call'
} elseif (-not $needsRestart) {
    Step 'Microphone'
    Write-Host '   Say something for 3 seconds...'
    Push-Location $root
    try { & $python pat.py check-mic } finally { Pop-Location }
    if ($LASTEXITCODE -ne 0) { Todo 'Fix the microphone as above, then check it again: .venv\Scripts\python.exe pat.py check-mic' }
    $global:LASTEXITCODE = 0
}

if (-not $needsRestart -or $Rehearse) {
    Step 'Phone'
    Quiet-Phone-Link
    if (Set-Up-Phone) {
        'Connected.'
    } else {
        Todo ("No phone works for Pat's calls yet. Open Pat's note and choose 'Set up the phone for Pat's calls' from its " +
              "right-click menu. Keep Settings > Bluetooth open on your phone while it pairs.")
    }
}

Step 'Done'
if ($todo.Count) {
    'Still to do:'
    $todo | ForEach-Object { "  - $_" }
} elseif ($Rehearse) {
    Would 'open the sticky note'
} elseif ($isAdmin) {
    # Opened from here it would run as administrator too, and a second, normal copy couldn't tell it was there.
    'All ready. Close this administrator window, then double-click Pat on your Desktop or find Pat in the Start menu.'
} else {
    'All ready. Opening the sticky note: its icon is in the hidden icons, and its settings are on its right-click menu.'
    Start-Process "$venv\Scripts\pythonw.exe" -ArgumentList "`"$root\note.py`"" -WorkingDirectory $root
}
if ($setupLog) {
    "Setup log: $setupLog"
    try { Stop-Transcript | Out-Null } catch { }
}
