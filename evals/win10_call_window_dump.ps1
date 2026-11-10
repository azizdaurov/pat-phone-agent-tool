# Windows 10 only: what Windows' own Call window offers to code (buttons, text), through UI Automation, the interface
# screen readers use. Pat would press Answer and End there, since Windows 10 has no PhoneCall API for apps.
# Every digit is printed as #, so phone numbers never appear in the output. Reads only; it presses nothing.
#
#   powershell -ExecutionPolicy Bypass -File evals\win10_call_window_dump.ps1 [-Seconds 90]
#
# Run it, then make or take a call: it prints the window's contents each time they change.
param([int]$Seconds = 90)
Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes
$ua = [System.Windows.Automation.AutomationElement]
$root = $ua::RootElement
$hide = { param($text) if ($text) { $text -replace '\d', '#' } else { '' } }

function Dump($window) {
    $lines = @("window: '$(& $hide $window.Current.Name)' class=$($window.Current.ClassName) pid=$($window.Current.ProcessId) " +
               "process=$((Get-Process -Id $window.Current.ProcessId -ErrorAction SilentlyContinue).ProcessName)")
    $all = $window.FindAll([System.Windows.Automation.TreeScope]::Descendants, [System.Windows.Automation.Condition]::TrueCondition)
    foreach ($e in $all) {
        $c = $e.Current
        $patterns = ($e.GetSupportedPatterns() | ForEach-Object { $_.ProgrammaticName -replace 'PatternIdentifiers.Pattern', '' }) -join ','
        $lines += "  $($c.ControlType.ProgrammaticName -replace 'ControlType.', '') name='$(& $hide $c.Name)' id='$(& $hide $c.AutomationId)' " +
                  "class='$($c.ClassName)' enabled=$($c.IsEnabled) [$patterns]"
    }
    $lines -join "`n"
}

$last = ''
$end = (Get-Date).AddSeconds($Seconds)
"Watching for Windows' Call window for $Seconds s. Make or take a call now."
while ((Get-Date) -lt $end) {
    $windows = $root.FindAll([System.Windows.Automation.TreeScope]::Children, [System.Windows.Automation.Condition]::TrueCondition) |
        Where-Object { $_.Current.Name -match '^(Call|Calls|Phone)' -or $_.Current.ClassName -match 'Call' }
    $now = ($windows | ForEach-Object { Dump $_ }) -join "`n"
    if (-not $now) {
        # Not found by name: list every top-level window, so the Call window can be recognised by its class or process.
        $now = "(no window named Call; all top-level windows:)`n" + (($root.FindAll([System.Windows.Automation.TreeScope]::Children,
            [System.Windows.Automation.Condition]::TrueCondition) | ForEach-Object {
                "  '$(& $hide $_.Current.Name)' class=$($_.Current.ClassName) process=$((Get-Process -Id $_.Current.ProcessId -ErrorAction SilentlyContinue).ProcessName)"
            }) -join "`n")
    }
    if ($now -ne $last) { "`n--- $(Get-Date -Format HH:mm:ss)`n$now"; $last = $now }
    Start-Sleep -Milliseconds 700
}
