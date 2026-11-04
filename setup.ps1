# Gets Pat, the Phone Agent Tool, ready on this laptop. Safe to run again: it skips what is already done, and picks up by itself after a restart.
#
#   powershell -ExecutionPolicy Bypass -File setup.ps1
#
# Windows asks you to approve anything that needs an administrator: turning on Developer Mode and installing drivers.
# It only makes a call if you ask it to, later. -Rehearse shows what it would do on a new laptop, and changes nothing.
param([switch]$SkipModels, [switch]$Rehearse)
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$venv = "$root\.venv"
$python = "$venv\Scripts\python.exe"
$pythonVersion = '3.13'
$dotnetMajor = '10'
$vbcableZip = 'https://download.vb-audio.com/Download_CABLE/VBCABLE_Driver_Pack45.zip'
$vbcablePage = 'https://vb-audio.com/Cable/'
$phoneWaitSeconds = 300
$todo = New-Object System.Collections.ArrayList
$needsRestart = $false

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

function Mobile-Access-Is-On {
    # Settings > Bluetooth & devices > Mobile devices > 'Allow this PC to access your mobile devices'.
    # With it off, Windows connects the phone over Bluetooth but never makes the phone line Pat dials on.
    $mobility = Get-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Mobility' -ErrorAction SilentlyContinue
    return ($mobility -and $mobility.CrossDeviceEnabled -eq 1)
}

function Pick-Phone {
    Push-Location $root
    try { $said = & $python pat.py pick-phone 2>$null; $ok = $LASTEXITCODE -eq 0 } finally { Pop-Location }
    $global:LASTEXITCODE = 0
    if ($ok) { Write-Host "   $said" }
    return $ok
}

function Wait-For-Phone {
    if ($Rehearse) {
        Would "check 'Allow this PC to access your mobile devices', and open its page if it is off"
        Would 'open Bluetooth settings, wait for an iPhone or Android phone to connect, and save it as your phone'
        return $true
    }
    if (-not (Mobile-Access-Is-On)) {
        Start-Process 'ms-settings:mobile-devices'
        Write-Host "   Mobile devices settings are open. Turn on 'Allow this PC to access your mobile devices'."
    }
    if (Pick-Phone) { return $true }
    Start-Process 'ms-settings:bluetooth'
    Write-Host '   Bluetooth settings are open. Add your phone there if it is not paired, and accept on both.'
    Write-Host "   Then on the phone, open Bluetooth settings and connect to $env:COMPUTERNAME, allowing calls when asked."
    Write-Host "   On Android, also tap the gear next to $env:COMPUTERNAME and turn on Calls. Waiting for it..."
    $deadline = (Get-Date).AddSeconds($phoneWaitSeconds)
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Seconds 5
        if (Pick-Phone) { return $true }
    }
    return $false
}

function Ask-To-Restart {
    if ($Rehearse) { Would 'offer to restart, and carry on by itself afterwards'; return }
    $again = "powershell -NoExit -ExecutionPolicy Bypass -File `"$PSCommandPath`""
    Set-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\RunOnce' 'PatSetup' $again
    try { $answer = Read-Host 'The audio drivers need a restart. This carries on by itself afterwards. Restart now? [Y/n]' } catch { $answer = 'n' }
    if ($answer -notmatch '^[Nn]') { Restart-Computer -Force; exit }
    Todo 'Restart the laptop. This setup carries on by itself afterwards.'
}

Step 'Windows'
$build = [Environment]::OSVersion.Version.Build
if ($build -lt 22000) { throw "Pat needs Windows 11; this is build $build." }
"Windows build $build"

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
        $command, $options = $base
        & $command @options -m venv $venv
        Check 'Creating the Python environment'
    }
    & $python -m pip install --disable-pip-version-check --quiet -r "$root\requirements.txt"
    Check 'Installing Python packages'
    & $python --version
}

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
    'iphonecall needs it. Windows will ask you to approve.'
    $key = 'HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\AppModelUnlock'
    [void](As-Admin 'reg.exe' "add `"$key`" /t REG_DWORD /f /v AllowDevelopmentWithoutDevLicense /d 1")
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
if ($needsRestart) {
    Ask-To-Restart
} elseif ($Rehearse) {
    Would 'put the default speaker and microphone back on the real ones'
} else {
    Step 'Default speaker and microphone'
    Push-Location $root
    try { & $python pat.py fix-audio } finally { Pop-Location }
    $global:LASTEXITCODE = 0
}

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
    if (Wait-For-Phone) {
        'Connected.'
    } else {
        Todo ("No phone connected for calls. On the phone, connect to $env:COMPUTERNAME in its Bluetooth settings and allow calls " +
              "(on Android, tap the gear next to it and turn on Calls). Check 'Allow this PC to access your mobile devices' in " +
              "Settings > Bluetooth & devices > Mobile devices. Then run: .venv\Scripts\python.exe pat.py pick-phone")
    }
}

Step 'Done'
if ($todo.Count) {
    'Still to do:'
    $todo | ForEach-Object { "  - $_" }
} elseif ($Rehearse) {
    Would 'open the sticky note'
} else {
    'All ready. Opening the sticky note: its icon is in the hidden icons, and its settings are on its right-click menu.'
    Start-Process "$venv\Scripts\pythonw.exe" -ArgumentList "`"$root\note.py`"" -WorkingDirectory $root
}
