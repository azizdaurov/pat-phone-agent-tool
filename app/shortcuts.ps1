# Used by setup.ps1. Loading this file only defines functions; it changes nothing.
function Get-PatShortcutFolders {
    return @{
        Desktop = [Environment]::GetFolderPath('DesktopDirectory')
        Programs = [Environment]::GetFolderPath('Programs')
        Startup = [Environment]::GetFolderPath('Startup')
    }
}

function Initialize-PatShortcutWriter {
    if ('Pat.Setup.Shortcut' -as [type]) { return }
    # WScript.Shell can replace non-English letters with '?'. Use Windows' Unicode shortcut interface instead.
    Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
using System.Runtime.InteropServices.ComTypes;

namespace Pat.Setup {
    [ComImport, Guid("00021401-0000-0000-C000-000000000046")]
    internal class ShellLink { }

    [ComImport, Guid("000214F9-0000-0000-C000-000000000046"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    internal interface IShellLinkW {
        void GetPath(IntPtr path, int count, IntPtr findData, uint flags);
        void GetIDList(out IntPtr pidl);
        void SetIDList(IntPtr pidl);
        void GetDescription(IntPtr text, int count);
        void SetDescription([MarshalAs(UnmanagedType.LPWStr)] string text);
        void GetWorkingDirectory(IntPtr path, int count);
        void SetWorkingDirectory([MarshalAs(UnmanagedType.LPWStr)] string path);
        void GetArguments(IntPtr text, int count);
        void SetArguments([MarshalAs(UnmanagedType.LPWStr)] string text);
        void GetHotkey(out short hotkey);
        void SetHotkey(short hotkey);
        void GetShowCmd(out int command);
        void SetShowCmd(int command);
        void GetIconLocation(IntPtr path, int count, out int index);
        void SetIconLocation([MarshalAs(UnmanagedType.LPWStr)] string path, int index);
        void SetRelativePath([MarshalAs(UnmanagedType.LPWStr)] string path, uint reserved);
        void Resolve(IntPtr window, uint flags);
        void SetPath([MarshalAs(UnmanagedType.LPWStr)] string path);
    }

    public static class Shortcut {
        public static void Save(string path, string target, string arguments, string directory, string icon) {
            var link = (IShellLinkW)new ShellLink();
            try {
                link.SetPath(target);
                link.SetArguments(arguments);
                link.SetWorkingDirectory(directory);
                link.SetIconLocation(icon, 0);
                link.SetDescription("Pat, the Phone Agent Tool");
                link.SetShowCmd(1); // Show the note normally. pythonw opens no console.
                ((IPersistFile)link).Save(path, true);
            } finally {
                Marshal.FinalReleaseComObject(link);
            }
        }
    }
}
'@
}

function Write-PatShortcut {
    param([string]$Path, [string]$Root)

    [Pat.Setup.Shortcut]::Save(
        $Path,
        (Join-Path $Root '.venv\Scripts\pythonw.exe'),
        ('"' + (Join-Path $Root 'note.py') + '"'),
        $Root,
        (Join-Path $Root 'note\icons\pat.ico')
    )
}

function Set-PatShortcuts {
    param(
        [Parameter(Mandatory)][string]$Root,
        [ValidateSet('Ask', 'On', 'Off', 'Keep')][string]$Startup = 'Ask',
        [switch]$Rehearse
    )

    if ($Rehearse) {
        Write-Host '   Would: create or update Pat in your Start menu and on your Desktop, with its icon and no console.'
        switch ($Startup) {
            'Ask' { Write-Host '   Would: ask whether to start Pat at sign-in (off by default; keep the current choice on a repeat run).' }
            'On' { Write-Host '   Would: create or update Pat in your Startup folder.' }
            'Off' { Write-Host '   Would: remove Pat from your Startup folder if present.' }
            'Keep' { Write-Host '   Would: keep the current startup choice and update its shortcut if present.' }
        }
        return
    }

    $Root = (Get-Item -LiteralPath $Root -ErrorAction Stop).FullName
    foreach ($file in '.venv\Scripts\pythonw.exe', 'note.py', 'note\icons\pat.ico') {
        if (-not (Test-Path -LiteralPath (Join-Path $Root $file) -PathType Leaf)) {
            throw "Pat needs $file. Run the full setup.ps1 first."
        }
    }
    $folders = Get-PatShortcutFolders
    foreach ($name in 'Desktop', 'Programs', 'Startup') {
        if (-not $folders[$name]) { throw "Windows could not find your $name folder." }
    }
    $startupPath = Join-Path $folders.Startup 'Pat.lnk'
    $startAtSignIn = Test-Path -LiteralPath $startupPath -PathType Leaf
    switch ($Startup) {
        'On' { $startAtSignIn = $true }
        'Off' { $startAtSignIn = $false }
        'Ask' {
            $hint = if ($startAtSignIn) { '[Y/n]' } else { '[y/N]' }
            while ($true) {
                try { $answer = (Read-Host "   Start Pat when you sign in? $hint").Trim() }
                catch { break }  # No input available: keep the current choice.
                if (-not $answer) { break }
                if ($answer -match '^(y|yes)$') { $startAtSignIn = $true; break }
                if ($answer -match '^(n|no)$') { $startAtSignIn = $false; break }
                Write-Host '   Type y or n, or press Enter to keep the current choice.'
            }
        }
    }

    Initialize-PatShortcutWriter
    foreach ($name in 'Programs', 'Desktop') {
        New-Item -ItemType Directory -Path $folders[$name] -Force | Out-Null
        Write-PatShortcut -Path (Join-Path $folders[$name] 'Pat.lnk') -Root $Root
    }
    if ($startAtSignIn) {
        New-Item -ItemType Directory -Path $folders.Startup -Force | Out-Null
        Write-PatShortcut -Path $startupPath -Root $Root
    } elseif (Test-Path -LiteralPath $startupPath -PathType Leaf) {
        Remove-Item -LiteralPath $startupPath -Force
    }
    Write-Host '   Pat is in your Start menu and on your Desktop. Open either shortcut to show the note.'
    if ($startAtSignIn) { Write-Host '   Pat will start when you sign in. It loads speech in the background.' }
    else { Write-Host '   Start with Windows is off.' }
}
