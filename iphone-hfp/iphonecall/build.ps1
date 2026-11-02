# Builds iphonecall into pkg\ and installs pkg\ as a Developer Mode package. The package is
# (re)installed only on the first run, when AppxManifest.xml changed, or with -Reinstall;
# code-only changes just need the rebuild, because Windows runs the files straight from pkg\.
#
#   powershell -ExecutionPolicy Bypass -File build.ps1 [-Reinstall]
param([switch]$Reinstall)
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$packageName = 'AzizDaurov.iPhoneCall'

$devMode = (Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\AppModelUnlock' -ErrorAction SilentlyContinue).AllowDevelopmentWithoutDevLicense
if ($devMode -ne 1) { throw 'Developer Mode is off. Turn it on: Settings > System > Advanced > For developers.' }

# A running iphonecall locks pkg\iphonecall.exe; don't kill it, it may be in a call.
if (Get-Process iphonecall -ErrorAction SilentlyContinue) { throw 'iphonecall is running. Quit it (q) and run this again.' }

dotnet build "$root\iphonecall.csproj" -c Release -nologo -v q
if ($LASTEXITCODE -ne 0) { throw 'Build failed.' }

$stamp = "$root\obj\installed-manifest.sha256"
$hash = (Get-FileHash "$root\AppxManifest.xml" -Algorithm SHA256).Hash
$installed = Get-AppxPackage $packageName
$current = $installed -and (Test-Path $stamp) -and ((Get-Content $stamp) -eq $hash)
if ($current -and -not $Reinstall) {
    'Built. Package already installed with this manifest.'
    return
}

# Reinstalling drops the app's registration with the phone; iphonecall registers again on its next run.
if ($installed) { $installed | Remove-AppxPackage }
Add-AppxPackage -Register "$root\pkg\AppxManifest.xml"
Set-Content $stamp $hash
'Built and installed. Run: iphonecall'
