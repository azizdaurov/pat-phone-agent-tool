# Gets Cicero ready on this laptop. Safe to run again: it skips what is already done.
#
#   powershell -ExecutionPolicy Bypass -File setup.ps1
#
# It installs Python and the .NET SDK if they're missing, and sets up everything inside this folder.
# It never installs an audio driver, changes a Windows setting or makes a call: what only you can do is listed at the end.
param([switch]$SkipModels)
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$venv = "$root\.venv"
$python = "$venv\Scripts\python.exe"
$pythonVersion = '3.13'
$dotnetMajor = '10'
$todo = New-Object System.Collections.ArrayList

function Step($text) { Write-Host "`n== $text" -ForegroundColor Cyan }
function Todo($text) { [void]$todo.Add($text); Write-Host "   Left for you: $text" -ForegroundColor Yellow }
function Check($what) { if ($LASTEXITCODE -ne 0) { throw "$what failed." } }

function Refresh-Path {
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User')
}

function Install-WithWinget($id) {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) { throw "winget is missing, so install $id by hand and run this again." }
    winget install --id $id --exact --silent --accept-package-agreements --accept-source-agreements
    Check "Installing $id"
    Refresh-Path
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

Step 'Windows'
$build = [Environment]::OSVersion.Version.Build
if ($build -lt 22000) { throw "Cicero needs Windows 11; this is build $build." }
"Windows build $build"

Step "Python $pythonVersion"
if (-not (Test-Path $python)) {
    $null = & py "-$pythonVersion" --version 2>$null
    if ($LASTEXITCODE -ne 0) { Install-WithWinget "Python.Python.$pythonVersion" }
    & py "-$pythonVersion" -m venv $venv
    Check 'Creating the Python environment'
}
& $python -m pip install --disable-pip-version-check --quiet -r "$root\requirements.txt"
Check 'Installing Python packages'
& $python --version

if ($SkipModels) {
    Step 'Speech models: skipped'
} else {
    Step 'Speech models (a large download the first time)'
    Push-Location $root
    try { & $python cicero.py prepare; Check 'Downloading speech models' } finally { Pop-Location }
}

Step 'iphonecall'
$devMode = (Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\AppModelUnlock' -ErrorAction SilentlyContinue).AllowDevelopmentWithoutDevLicense
if ($devMode -ne 1) {
    Todo 'Turn on Developer Mode (Settings > System > Advanced > For developers), then run this again to build iphonecall.'
} else {
    $sdks = & dotnet --list-sdks 2>$null
    if (-not ($sdks -match "^$dotnetMajor\.")) { Install-WithWinget "Microsoft.DotNet.SDK.$dotnetMajor" }
    & "$root\iphone-hfp\iphonecall\build.ps1"
}

Step 'Phone tool for Claude Code'
$claude = Find-Claude
if (-not $claude) {
    Todo 'Install Claude Code and log in, then run this again to register the phone tool.'
} else {
    $saved = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    & $claude mcp remove --scope user cicero-phone *> $null  # there's nothing to remove on a first run
    $ErrorActionPreference = $saved
    & $claude mcp add --scope user cicero-phone -- $python "$root\phone_mcp.py"
    Check 'Registering the phone tool'
    'Registered for every folder. Chats open before now keep using the old one until restarted.'
}

Step 'Audio devices'
Push-Location $root
try {
    $saved = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    & $python cicero.py check
    $audioOk = $LASTEXITCODE -eq 0
    $ErrorActionPreference = $saved
} finally { Pop-Location }
if (-not $audioOk) {
    Todo 'Install both free audio drivers, then restart: VB-CABLE (https://vb-audio.com/Cable/) and Voicemeeter (https://vb-audio.com/Voicemeeter/). Leave the Voicemeeter app closed.'
}

Step 'Done'
if ($todo.Count) {
    'Still to do:'
    $todo | ForEach-Object { "  - $_" }
}
'Do these once, if you have not already:'
'  - Pair the iPhone with this laptop in Bluetooth settings and allow calls.'
'  - Close Phone Link, or remove the iPhone from it, so it does not hold the phone line.'
'  - Log in to Claude Code.'
"Then check everything: $python `"$root\cicero.py`" check"
