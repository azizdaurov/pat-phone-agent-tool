# Pat phone helper for Windows

Dial and answer calls on the iPhone (its SIM, its number) from this laptop's terminal, with the
voice on the laptop. No Phone Link needed.

The `iphonecall` helper also supports Android; calls have been tested on a Galaxy A13.

| Tool | What it does | Voice |
|---|---|---|
| `iphonecall` (main) | Dial, answer, reject, hang up, mute, move audio between laptop and phone | **on the laptop** |
| `hfp_call.py` (fallback) | Dial, answer, hang up, redial, status | stays on the iPhone |

Both talk to the iPhone over Bluetooth hands-free. Use one at a time: only one program can hold the link.

---

## Using `iphonecall`

`iphonecall audio-devices-json --device-id <id>` reads the selected phone's identity and audio-endpoint metadata without
connecting or placing a call. Pat uses it to distinguish the selected phone from other hands-free devices. Names are
display labels, so renaming a phone does not make it a headset.

### Before the first run (once)

1. **Pair the iPhone** with this laptop (Settings > Bluetooth & devices). On the iPhone, choose **your laptop's name**.
2. **Turn on mobile-device access:** Settings > Bluetooth & devices > Mobile devices >
   "Allow this PC to access your mobile devices" = **On**. Without it, Windows connects the phone but never creates its phone line.
   **Close Phone Link** and turn off its start with Windows: only one app at a time can use the phone for calls. If Phone Link
   had the phone, also remove the phone in Bluetooth settings and pair it again.
3. **Turn on Developer Mode:** Settings > System > Advanced > For developers.
4. **Build and install:**
   ```powershell
   powershell -ExecutionPolicy Bypass -File iphonecall\build.ps1
   ```

### Every time

If the iPhone isn't connected to the laptop, open **Settings > Bluetooth** on the iPhone and tap your laptop's name. Then:

```powershell
iphonecall
```

| Command | Action |
|---|---|
| `d +COUNTRY_CODE_NUMBER` | dial (replace the placeholder with a full international number) |
| `a` | answer an incoming call (incoming calls are announced in the terminal) |
| `h` | hang up, or reject an incoming call |
| `m` | mute / unmute |
| `l` / `p` | move the call audio to the laptop / to the phone |
| `s` | status |
| `q` | quit (a call in progress continues on the phone) |

Other forms: `iphonecall dial +COUNTRY_CODE_NUMBER`, `iphonecall status`, `iphonecall list`,
`iphonecall unregister`, and `--device <name>` or `--device-id <id>` to pick a paired phone.
Without a selection, the helper uses Windows' default phone line to find a phone when several are paired,
then tries connected phones first. If no default line matches, choose a phone explicitly.
Its name does not need to contain "iPhone". `iphonecall list-json` returns names and stable
device IDs for Pat's phone settings; listing never dials or changes audio routing.

**No terminal by itself:** it has no console, so the window Windows starts for each call stays out of sight. Running `iphonecall` by hand opens a terminal for it.

**Where the voice goes:** with `--stay-on-phone`, and in the window Windows opens by itself for a call, audio stays where it is unless you type `l` or `p`. Otherwise each call's audio is moved to the laptop automatically, and Windows plays it on
the current **default** speaker and microphone (Settings > System > Sound). If you hear nothing, check
which device is the default; it may be your headphones. Use headphones to stop the caller hearing an echo.

**Extra copy during calls:** when a call starts, Windows also starts a copy of `iphonecall` by itself (a side
effect of the manifest entry that makes registration work). It has no window, since `iphonecall` is built without
one, and it closes by itself 3 seconds after the call ends.

### When something goes wrong

The startup lines show which step failed:

| You see | Meaning / fix |
|---|---|
| `access : DeniedBySystem` | Another app holds the phone, usually Phone Link. Keep mobile-device access **On** (step 2), close Phone Link, then remove the phone in Bluetooth settings and pair it again. |
| `register : registered=False` | Windows ignored the registration. Check the manifest; see "Things that matter". |
| `held : HeldByAnotherApp` | Windows has the phone's call line, but another app took it and keeps it, usually Phone Link, even after it quits. Close Phone Link and stop it running in the background, then remove the phone in Bluetooth settings and pair it again. |
| `connect : False` | The iPhone isn't connected. Tap **your laptop's name** in the iPhone's Bluetooth settings and retry. |
| `Access denied by Windows` | You ran `pkg\iphonecall.exe` directly. Run `iphonecall` (the installed package). |
| `stuck: ... did not answer` | A Windows call service hung. Quit, then run again. |
| `'iphonecall' is not recognized` | Not installed, or the package was removed: run `build.ps1`. |

To remove it: `powershell -ExecutionPolicy Bypass -File iphonecall\uninstall.ps1`.

---

## Using `hfp_call.py` (fallback)

Needs only Python 3. It sends the hands-free commands itself, so Windows' calling stack (and the
package above) isn't involved, but the call voice stays on the iPhone.

```powershell
python hfp_call.py shell     # d <number>, a, h, r (redial), s, v <0-15>, raw AT commands, q
python hfp_call.py status
```

If it fails with error 10051 or 10060, the iPhone isn't accepting the laptop: tap **your laptop's name** on the iPhone.
The iPhone's hands-free service is on Bluetooth channel 8 (`--channel 8` skips the service lookup).
Give the phone address with `--addr`, or set `IPHONE_BT_ADDR`.

---

## Working on `iphonecall`

```
iphonecall/
  Program.cs         command line and the interactive shell
  HandsFree.cs       find the phone, register, connect, find its phone line
  CallSession.cs     dial / answer / hang up / mute / audio, plus the call monitor
  AppxManifest.xml   package identity and permissions (read "Things that matter" first)
  build.ps1          build, and install the package when needed
  uninstall.ps1      remove the package
  pkg/               build output; this folder IS the installed package (don't move or delete it)
```

Edit, build, test:

```powershell
powershell -ExecutionPolicy Bypass -File iphonecall\build.ps1   # quit iphonecall first
iphonecall status                                               # connects, prints the line, no call
```

A code change only needs the rebuild, because Windows runs the files straight from `pkg\`. A change to
`AppxManifest.xml` needs the package reinstalled; `build.ps1` does that automatically when the manifest changed.
It targets .NET 10 (long-term support, to November 2028) with the Windows 11 SDK projection
`net10.0-windows10.0.22621.0`. To move to a newer .NET, install its SDK and change `TargetFramework`.

### Things that matter (each one was found the hard way)

1. **Only packaged apps get access.** Windows refuses the hands-free calling APIs (`PhoneLineTransportDevice`,
   `PhoneLine`) to plain programs and scripts. That's why this is a Developer Mode package, launched through the
   `iphonecall` alias.
2. **The manifest entries are load-bearing.** Without `<uap13:Extension Category="windows.phoneCallActivation"/>`
   (plus the `bluetooth` and `radios` device capabilities), `RegisterApp()` silently does nothing and
   `IsRegistered()` stays false. These entries were copied from the manifests of Phone Link and Sefirah, which both
   work. `microphone` is declared too, for the laptop voice.
3. **Open the call store before connecting.** `PhoneCallManager.RequestStoreAsync()` never returns if it's first
   called after `PhoneLineTransportDevice.ConnectAsync()` in the same process. `HandsFree.ConnectAsync` opens it first.
4. **Windows plays the call audio, but only after the switch.** A call starts with `audio=RemoteDevice` and is
   silent everywhere. `PhoneCall.ChangeAudioDeviceAsync(LocalDevice)` makes Windows play it on the default
   devices. `CallSession` does this for every new call. The iPhone's call-audio endpoints use private device
   classes that ordinary audio APIs (WASAPI/NAudio) can't see, so an app can't route the audio itself.
5. **Only one app can use the phone for calls, so close Phone Link and re-pair the phone.** Whichever app has the phone
   keeps it. While Phone Link holds it, `RequestAccessAsync()` returns `DeniedBySystem`; with Pat's note holding it, Phone
   Link can't dial. The fix is to close Phone Link, then remove the phone in Bluetooth settings and pair it again. Pat shows
   "Phone Link has your phone" when the helper is refused this way.
   Windows can also refuse more quietly: `RequestAccessAsync()` says `Allowed` and `ConnectAsync()` returns false, while
   Windows still lists a working line for the phone. Phone Link took the phone's call link and kept it, even after it quit.
   This happened after Windows woke Phone Link in the background for an incoming call, and Phone Link took the link
   when Pat's note briefly let go of it. `HandsFree.ConnectAsync` reports it as `held : HeldByAnotherApp`. The fix is
   the same, and stopping Phone Link from running in the background keeps Windows from waking it again.
   No Microsoft unlock token is needed on Windows 11 (build 22000 and later).
6. **Ignore `AudioRoutingStatus`.** It reports `CannotRouteToLocalDevice` even when the laptop voice works.
7. **Re-pairing the iPhone** drops the registration. The next `iphonecall` run registers again by itself.
8. **`phoneCallActivation` launches the app.** Windows starts `pkg\iphonecall.exe` with no arguments when a
   call begins, so a no-argument run may be you or Windows. `Program.cs` tells them apart with
   `AppInstance.GetActivatedEventArgs() is PhoneCallActivatedEventArgs`, and `CallSession.CloseAfterCalls`
   makes those windows exit after the call. Before that, they stayed open and blocked `build.ps1`.

9. **Finished calls stay in the "active" list.** `GetAllActivePhoneCalls()` kept returning a call with status `Ended`
   minutes after it finished, so `CallSession.ActiveCalls` filters those out. Without that, a new run reports the old
   call as if it had just ended, which made Pat give up on the next call.

10. **`ChangeAudioDeviceAsync` can report `Succeeded` and change nothing.** On 3 of the 4 logged calls on 2026-11-02 it
    did, and the call stayed `audio=RemoteDevice`, with no sound reaching the laptop. Trust the call's `AudioDevice`, not
    the result. In tests on 2026-11-02 this happened whenever Bluetooth headphones were connected to the laptop, even when
    they weren't the default speaker. Without them the first try worked. `CallSession` retries every 2 s, but 14 retries
    over two calls with headphones connected didn't help: the fix is to disconnect them.

### References

- MyPhone, an earlier open-source attempt, and its issue thread on Windows 11 blocking this API:
  https://github.com/BestOwl/MyPhone/issues/26
- Sefirah (GPL-3.0), whose working manifest and connect order showed the fix; read, not copied:
  https://github.com/shrimqy/Sefirah
- Microsoft API docs: `PhoneLineTransportDevice`, `PhoneLine`, `PhoneCall` under
  https://learn.microsoft.com/uwp/api/windows.applicationmodel.calls
