# Phone

Pat calls through your phone's Bluetooth hands-free link, the one a car uses. The phone keeps its SIM and its number.

## Connecting a phone

Setup does this once. It checks Settings > Bluetooth & devices > Mobile devices > **Allow this PC to access your mobile
devices**, and opens that page if it's off: without it, Windows connects the phone but never makes the phone line Pat
dials on. Then, if no phone works for calls, it offers the set-up steps below.

On Android, also tap the gear next to the laptop in the phone's Bluetooth settings and turn on **Calls**.

## Phone Link

Windows lets one app use a phone for calls: the one that registered on the phone's Bluetooth pairing first. The
registration belongs to the pairing, so it stays after the app is closed. While Phone Link holds the phone, Windows
refuses Pat. Phone Link's setup screen can also delete the phone's pairing, and an iPhone won't pair while Phone Link
runs.

Setup ends Phone Link if it's running and turns off its start at sign-in, saying each in one line. To undo the second,
use Settings > Apps > Startup. "Mobile devices" in Task Manager is a different program and doesn't get in the way.

If Phone Link keeps coming back, uninstall it for your Windows user; the Microsoft Store installs it again:

```powershell
Get-AppxPackage Microsoft.YourPhone | Remove-AppxPackage
```

Don't use the "Phone-PC linking" policy instead: it also turns off "Allow this PC to access your mobile devices".

## Set up the phone for Pat's calls

The note shows this button under its message when the pairing itself is the problem:

| The note says | Why |
|---|---|
| Phone Link has your phone. | Phone Link registered on the pairing first. |
| The phone Pat used isn't paired any more. | The pairing was removed, for example by Phone Link's setup screen. |
| Your phone is paired for notifications only, not calls. | Only Phone Link's notifications pairing is left. |
| No phone is set up for Pat's calls. | No phone is paired for calls. |

"Your phone isn't connected" gets no button: the phone is off, away or has Bluetooth off, and Pat connects by itself once
it's back. The steps are also on the note's right-click menu, for switching phones.

1. **Which is your phone?** Pat removes its old pairing, calls and notifications entries both. "My phone isn't here"
   removes nothing.
2. Pat ends Phone Link if it's running.
3. **Find your phone.** Open Settings > Bluetooth on the phone and keep it open: the phone is visible to the laptop only
   then. Phones appear as they're found.
4. **Check the code.** Tap Pair on the phone, then **Codes match**. A phone that still holds an old pairing can show no
   code the first time; Pat tries again by itself, and only after a second refusal asks you to choose Forget This Device
   on the phone.
5. Pat registers on the new pairing before any other app can, and saves it as the phone it uses. A phone can take a few
   seconds to accept calls after pairing, so Pat tries for about 20 seconds; the note connects later by itself if needed.

`iphonecall pair` runs the same steps in a terminal. Each run is logged in `calls\pair-<date and time>.log`.

## Several phones

With no phone chosen, Pat tries a phone connected to the laptop first, then the one chosen in Settings > Your phone, then
one that already has a Windows phone line. A connected phone is tried even when Pat can't see its line, which is how
Phone Link leaves a phone, so the note can say why it's refused. A phone that is neither connected nor has a line is never
tried. `iphonecall phones` shows each paired phone and the order Pat would try them in.

To fix the choice, pick a phone in Settings > Your phone. **Find paired phones** saves the device's Windows ID, so
renaming the phone doesn't break it.

## A second laptop

A phone talks hands-free to one laptop at a time: connect to the laptop in the phone's Bluetooth settings before using
it. Run setup there too. To bring your contacts, notes and answer rules, copy `contacts\` yourself, and
`calls\note-settings.json` for the menu's settings.

If the phone the note is using disconnects, the note keeps looking and takes whichever phone connects next. A chosen
phone that comes back takes over again.
