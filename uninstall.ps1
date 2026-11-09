# Takes Pat, the Phone Agent Tool, off this laptop and puts back what setup.ps1 changed.
#
#   powershell -ExecutionPolicy Bypass -File uninstall.ps1
#
# It always puts the default speaker and microphone back on real devices and removes Pat's phone tool, shortcuts and
# phone helper. It asks before touching what other apps may use too: the audio drivers, Developer Mode and Phone Link.
# Your calls, contacts and settings stay in this folder until you delete it. -Rehearse shows the steps and changes nothing.
param([switch]$Rehearse)
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$python = "$root\.venv\Scripts\python.exe"
$vbcableZip = 'https://download.vb-audio.com/Download_CABLE/VBCABLE_Driver_Pack45.zip'
$developerKey = 'HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\AppModelUnlock'
$phoneLinkStart = 'HKCU:\Software\Classes\Local Settings\Software\Microsoft\Windows\CurrentVersion\AppModel\SystemAppData\Microsoft.YourPhone_8wekyb3d8bbwe\YourPhone.Start'
$todo = New-Object System.Collections.ArrayList
$needsRestart = $false

function Step($text) { Write-Host "`n== $text" -ForegroundColor Cyan }
function Would($text) { Write-Host "   Would: $text" -ForegroundColor DarkGray }
function Todo($text) { [void]$todo.Add($text); Write-Host "   Left for you: $text" -ForegroundColor Yellow }

# The same checks as setup.ps1's, so both agree on what is installed.
function Find-Claude {
    if ($env:VOICE_LOOP_CLAUDE) { return $env:VOICE_LOOP_CLAUDE }
    $onPath = Get-Command claude -ErrorAction SilentlyContinue
    if ($onPath) { return $onPath.Source }
    $found = Get-ChildItem "$env:LOCALAPPDATA\Claude-Data\*\claude-code\*\*\claude.exe" -ErrorAction SilentlyContinue |
        Sort-Object { try { [version]$_.Directory.Parent.Name } catch { [version]'0.0' } } | Select-Object -Last 1
    if ($found) { return $found.FullName }
    return $null
}

function Has-Driver($name) {
    return [bool](Get-CimInstance Win32_PnPSignedDriver -Filter "DeviceClass='MEDIA'" | Where-Object { $_.DeviceName -like "*$name*" })
}

function As-Admin($file, $arguments) {
    try {
        Start-Process $file -ArgumentList $arguments -Verb RunAs -Wait
        return $true
    } catch {
        Write-Host "   Windows didn't run it: $($_.Exception.Message)" -ForegroundColor Yellow
        return $false
    }
}

# Yes only when you type y. In -Rehearse, or with no one to answer, it's no.
function Ask-Yes($question) {
    if ($Rehearse) { Would "ask: $question [y/N]"; return $false }
    try { $answer = Read-Host "   $question [y/N]" } catch { return $false }
    return $answer -match '^(y|yes)$'
}

Step 'Pat is closed'
# Ending Pat from here could leave someone on a silent call, so it's left to you. The phone tool each open Claude Code
# chat runs (phone_mcp.py) doesn't count: it only starts Pat when asked, and its registration goes below.
$running = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
    ($_.Name -in 'python.exe', 'pythonw.exe' -and $_.CommandLine -like "*$root*" -and $_.CommandLine -notlike '*phone_mcp.py*') -or
    $_.Name -eq 'iphonecall.exe' })
if ($running.Count) {
    $names = ($running | ForEach-Object { $_.Name } | Sort-Object -Unique) -join ', '
    if ($Rehearse) { Would "stop here, because Pat is running ($names)" }
    else { throw "Pat is still running ($names). Right-click its icon in the tray, choose Quit, and run this again." }
} else {
    'Pat is closed.'
}

Step 'Default speaker and microphone'
if ($Rehearse) {
    Would 'put back the defaults saved before any call that was cut off, then move every default off the virtual devices'
} elseif (Test-Path $python) {
    Push-Location $root
    try {
        & $python pat.py restore-audio
        & $python pat.py fix-audio
    } finally { Pop-Location }
    $global:LASTEXITCODE = 0
} else {
    Todo 'Check the default speaker and microphone in Settings > System > Sound: Pat''s Python is gone, so it could not.'
}

Step 'Phone tool for Claude Code'
$claude = Find-Claude
if ($Rehearse) {
    Would 'remove the pat-phone tool from Claude Code'
} elseif (-not $claude) {
    'Claude Code is not installed, so there is no phone tool to remove.'
} else {
    $saved = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    foreach ($name in 'pat-phone', 'cicero-phone') { & $claude mcp remove --scope user $name *> $null }
    $ErrorActionPreference = $saved
    $global:LASTEXITCODE = 0
    'Removed. Chats open now keep it until they are restarted.'
}

Step 'Shortcuts'
$shell = New-Object -ComObject WScript.Shell
foreach ($folder in 'DesktopDirectory', 'Programs', 'Startup') {
    $link = Join-Path ([Environment]::GetFolderPath($folder)) 'Pat.lnk'
    if (-not (Test-Path -LiteralPath $link)) { continue }
    # Only a shortcut that opens this folder's Pat: another Pat.lnk isn't ours to delete.
    $ours = $shell.CreateShortcut($link).WorkingDirectory -eq $root
    if (-not $ours) { Todo "Remove $link by hand if it is Pat's: it doesn't point to this folder, so it was left."; continue }
    if ($Rehearse) { Would "delete $link" } else { Remove-Item -LiteralPath $link -Force; "Deleted $link" }
}

Step 'Phone helper'
$packages = @(Get-AppxPackage 'OasisTeam.PatPhone') + @(Get-AppxPackage 'AzizDaurov.iPhoneCall') | Where-Object { $_ }
if (-not $packages.Count) {
    'Not installed.'
} elseif ($Rehearse) {
    Would 'remove the phone helper package (iphonecall)'
} else {
    $packages | Remove-AppxPackage
    'Removed.'
}
'The phone stays paired with the laptop. To unpair it: Settings > Bluetooth & devices.'

Step 'Audio drivers'
$hasCable = Has-Driver 'VB-Audio Virtual Cable'
$winget = Get-Command winget -ErrorAction SilentlyContinue
if (-not $hasCable -and -not (Has-Driver 'Voicemeeter')) {
    'VB-CABLE and Voicemeeter are not installed.'
} elseif (Ask-Yes 'Remove the VB-CABLE and Voicemeeter audio drivers too? Say no if other apps use them.') {
    if (Has-Driver 'Voicemeeter') {
        if ($winget) {
            winget uninstall --id VB-Audio.Voicemeeter --exact --silent
            $global:LASTEXITCODE = 0
        } else {
            Todo 'Remove Voicemeeter in Settings > Apps > Installed apps.'
        }
    }
    if ($hasCable) {
        $folder = Join-Path $env:TEMP 'pat-vbcable'
        Remove-Item $folder -Recurse -Force -ErrorAction SilentlyContinue
        New-Item -ItemType Directory $folder | Out-Null
        try {
            Invoke-WebRequest $vbcableZip -OutFile "$folder\vbcable.zip" -UseBasicParsing
            Expand-Archive "$folder\vbcable.zip" $folder
            $installer = "$folder\VBCABLE_Setup_x64.exe"
            # As with setup, the maker doesn't document a silent removal, so if this doesn't take, its own window does it.
            [void](As-Admin $installer '-u -h')
            if (Has-Driver 'VB-Audio Virtual Cable') {
                Write-Host '   Click Remove Driver in the window that opens.'
                [void](As-Admin $installer '')
            }
        } catch {
            Todo 'VB-CABLE did not download. Get it from https://vb-audio.com/Cable/, run VBCABLE_Setup_x64.exe as administrator, and click Remove Driver.'
        }
    }
    $needsRestart = $true
} elseif (-not $Rehearse) {
    'Kept.'
}

Step 'Developer Mode'
$developerOn = (Get-ItemProperty "HKLM:\$($developerKey.Substring(5))" -ErrorAction SilentlyContinue).AllowDevelopmentWithoutDevLicense -eq 1
if (-not $developerOn) {
    'Already off.'
} elseif (Ask-Yes 'Setup turned on Developer Mode for the phone helper. Turn it off? Say no if you use it for anything else.') {
    [void](As-Admin 'reg.exe' "add `"$developerKey`" /t REG_DWORD /f /v AllowDevelopmentWithoutDevLicense /d 0")
} elseif (-not $Rehearse) {
    'Kept on.'
}

Step 'Phone Link'
# 1 means "turned off by you", which is how setup turns it off. Whether setup or you did it isn't recorded, so ask.
$start = Get-ItemProperty $phoneLinkStart -ErrorAction SilentlyContinue
if (-not ($start -and $start.State -eq 1)) {
    'Nothing to put back.'
} elseif (Ask-Yes 'Phone Link''s start at sign-in is off. Setup may have turned it off. Turn it back on?') {
    Set-ItemProperty $phoneLinkStart -Name State -Value 2
    'On again. It starts next time you sign in.'
} elseif (-not $Rehearse) {
    'Left off.'
}

Step 'Done'
'Python and the .NET SDK stay installed, since other programs may use them. Remove them in Settings > Apps if you like.'
"Your calls, contacts and settings are in $root\calls and $root\contacts. Copy what you want to keep, then delete the folder $root to finish."
if ($needsRestart) { Todo 'Restart the laptop to finish removing the audio drivers.' }
if ($todo.Count) {
    'Still to do:'
    $todo | ForEach-Object { "  - $_" }
}
