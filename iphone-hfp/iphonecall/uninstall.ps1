# Removes the iphonecall package. The iPhone pairing and Developer Mode are left as they are.
#
#   powershell -ExecutionPolicy Bypass -File uninstall.ps1
$ErrorActionPreference = 'Stop'
if (Get-Process iphonecall -ErrorAction SilentlyContinue) { throw 'iphonecall is running. Quit it (q) and run this again.' }
Get-AppxPackage AzizDaurov.iPhoneCall | Remove-AppxPackage
Remove-Item "$PSScriptRoot\obj\installed-manifest.sha256" -ErrorAction SilentlyContinue
'Removed iphonecall.'
