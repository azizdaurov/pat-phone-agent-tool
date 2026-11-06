# iphonecall

Dial and answer calls on your phone (its SIM, its number) from a Windows laptop, with the voice on the laptop, through
Windows' own Bluetooth hands-free calling. Pat runs it and drives its shell over pipes. Tested with an iPhone and a
Galaxy A13.

`hfp_call.py` is an older fallback that needs only Python, but keeps the voice on the phone. Use one at a time: only one
program can hold the hands-free link.

## Install

`setup.ps1` does this. By hand:

1. Turn on **Developer Mode**: Settings > System > Advanced > For developers.
2. Turn on Settings > Bluetooth & devices > Mobile devices > **Allow this PC to access your mobile devices**. Without
   it, Windows connects the phone but never makes its phone line.
3. Build and install:
   ```powershell
   powershell -ExecutionPolicy Bypass -File iphonecall\build.ps1
   ```
4. Set up the phone: `iphonecall pair`. It removes the chosen phone's old pairing, ends Phone Link, finds the phone while
   its Bluetooth screen is open, pairs with a code, and registers before any other app can.

To remove it: `powershell -ExecutionPolicy Bypass -File iphonecall\uninstall.ps1`.

## Use

```powershell
iphonecall
```

| Key | |
|---|---|
| `d +COUNTRY_CODE_NUMBER` | Dial |
| `a` | Answer (incoming calls are announced) |
| `h` | Hang up, or reject |
| `m` | Mute or unmute |
| `l` / `p` | Move the call's audio to the laptop / the phone |
| `s` | Status |
| `q` | Quit; a call carries on on the phone |

| Command | |
|---|---|
| `dial <number>`, `status` | One call, or connect and print the line without calling |
| `pair [--json]` | Set up a phone; `--json` reports each step as a JSON line, for Pat's note |
| `phones` | Each paired phone: connected, has a line, and the order Pat would try them in |
| `list`, `list-json`, `lines` | Paired phones and their IDs; Windows' phone lines. Never dials |
| `audio-devices-json` | The selected phone's audio endpoints, to tell them from a headset's |
| `self-test` | The phone-choosing order, on made-up phones |
| `unregister` | Drop this app's registration on the phone |

`--device <name>` or `--device-id <id>` picks a phone. Without one, it starts from Windows' default phone line or a
connected phone, then tries the others. `--stay-on-phone` leaves the call's audio where it is; otherwise each call moves
to the laptop and plays on the **default** speaker and microphone.

It has no console of its own, so the copy Windows starts for each call stays out of sight; it closes 3 s after the call.

## When something goes wrong

| You see | Fix |
|---|---|
| `access : DeniedBySystem` | Another app, usually Phone Link, registered on the pairing first. Run `iphonecall pair` |
| `register : registered=False` | Windows ignored the registration: check the manifest (1 and 2 below) |
| `connect : False` | The phone isn't connected. Tap the laptop's name in the phone's Bluetooth settings |
| `Access denied by Windows` | You ran `pkg\iphonecall.exe` directly. Run `iphonecall` |
| `stuck: ... did not answer` | A Windows call service hung. Run it again |
| `'iphonecall' is not recognized` | Not installed: run `build.ps1` |

## How Windows' calling APIs behave

Each was found the hard way.

1. **Only packaged apps get access.** Windows refuses `PhoneLineTransportDevice` and `PhoneLine` to plain programs, so
   this is a Developer Mode package launched through the `iphonecall` alias. No unlock token is needed on Windows 11.
2. **The manifest entries are load-bearing.** Without `windows.phoneCallActivation` and the `bluetooth` and `radios`
   capabilities, `RegisterApp()` does nothing and `IsRegistered()` stays false. They match Phone Link's and Sefirah's.
3. **Open the call store before connecting.** `PhoneCallManager.RequestStoreAsync()` never returns if first called after
   `ConnectAsync()` in the same process.
4. **The call's audio needs a switch.** A call starts with `audio=RemoteDevice`, silent everywhere, until
   `ChangeAudioDeviceAsync(LocalDevice)`. The phone's call endpoints are invisible to WASAPI, so an app can't route them.
5. **`ChangeAudioDeviceAsync` can say `Succeeded` and change nothing.** It did on every call with Bluetooth headphones
   connected. Trust the call's `AudioDevice`, not the result. `AudioRoutingStatus` is wrong too.
6. **The first app to register on a pairing keeps the phone.** The registration belongs to the Bluetooth pairing and
   outlives the app. A second app gets `DeniedBySystem`; only a new pairing clears it, as
   [MyPhone #26](https://github.com/BestOwl/MyPhone/issues/26) also found. `pair` removes the old pairing, pairs with
   `PairAsync()` and calls `RegisterApp()` at once. Phone Link's `PhoneExperienceHost` blocks an iPhone's pairing while
   it runs, so `pair` ends it.
7. **Listing paired devices is slow.** Windows' "paired Bluetooth devices" query waits out a 30-second search, so `pair`
   reads calls entries from the phone-line devices and notifications entries from the `BTHLE\Dev_<address>` nodes. An
   iPhone's LE address is random-type.
8. **Windows starts the app for every call.** `phoneCallActivation` launches `pkg\iphonecall.exe` with no arguments;
   `Program.cs` tells that apart with `PhoneCallActivatedEventArgs`, and those copies exit after the call.
9. **Finished calls stay "active".** `GetAllActivePhoneCalls()` returns calls with status `Ended` for minutes, so
   `CallSession.ActiveCalls` filters them out.

## Working on it

| File | |
|---|---|
| `Program.cs` | Command line and the interactive shell |
| `HandsFree.cs` | Find the phone, register, connect, find its line |
| `PhoneSelection.cs` | The order phones are tried in |
| `Pairing.cs` | `pair` |
| `CallSession.cs` | Dial, answer, hang up, mute, audio, and the call monitor |
| `AppxManifest.xml` | Package identity and capabilities |
| `pkg/` | Build output, and the installed package itself: don't move or delete it |

A code change needs only `build.ps1` (quit `iphonecall` first), because Windows runs the files straight from `pkg\`. A
manifest change reinstalls the package, which also drops its registration on the phone. It targets .NET 10.

## `hfp_call.py`

```powershell
python hfp_call.py shell     # d <number>, a, h, r (redial), s, v <0-15>, raw AT commands, q
python hfp_call.py status
```

Error 10051 or 10060 means the phone isn't accepting the laptop: tap the laptop's name on it. Give the phone's address
with `--addr` or `IPHONE_BT_ADDR`; `--channel 8` skips the service lookup on an iPhone.

## References

- [MyPhone issue #26](https://github.com/BestOwl/MyPhone/issues/26): Windows 11 blocking this API, and unpairing to free a phone.
- [Sefirah](https://github.com/shrimqy/Sefirah) (GPL-3.0): its working manifest and connect order showed the fix; read, not copied.
- [Windows.ApplicationModel.Calls](https://learn.microsoft.com/uwp/api/windows.applicationmodel.calls): `PhoneLineTransportDevice`, `PhoneLine`, `PhoneCall`.
