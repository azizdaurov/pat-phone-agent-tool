# Development

## Tests

```powershell
.venv\Scripts\python.exe -m unittest            # tests/: needs no phone, no call and no audio driver
iphonecall self-test                            # the phone-choosing order, on made-up phones
dotnet run --project evals\phone-selection\phone-selection.csproj
```

After changing the phone helper, rebuild it with `iphone-hfp\iphonecall\build.ps1` (quit the note first: it holds the
helper), or run `setup.ps1` again.

## Files

| File | |
|---|---|
| `setup.ps1` | Gets a laptop ready; `-Rehearse` changes nothing |
| `pat.py` | One call: `PhoneLine` drives `iphonecall`, `CallerAudio` records the loopback, `SpeechDetector` and `TurnDetector` take turns, `Conversation` runs Claude |
| `call_brief.py`, `observer.py` | The brief and Haiku's prompts; Sonnet's reviews, questions, report and rarity limits |
| `call_card.py` | The framed summary card agents show |
| `phone_mcp.py` | The `pat-phone` MCP server |
| `phone_memory.py`, `private_numbers.py`, `phone_numbers.py` | Notes per number; contacts and `#1` placeholders; number parsing |
| `caller_names.py`, `owner_names.py` | The caller's name from caller ID; your name in each call language |
| `audio_defaults.py`, `bluetooth_audio.py`, `mic_relay.py` | Default devices for a call; telling the phone's audio from a headset's; your microphone into the call on take-over |
| `languages.py` | The call languages. Adding one also takes its recognition, voice, rules and openings |
| `speech_service.py` | The speech models the note keeps loaded |
| `note.py`, `note_window.py`, `note/` | The sticky note: line watcher, window, page |
| `note_dialog.py`, `onboarding.py`, `note_settings.py` | Paper windows; first run and settings; the tray menu's settings |
| `pairing_flow.py`, `phone_pairing.py` | The note's phone set-up steps, driving `iphonecall pair --json` |
| `live_call.py`, `live_notes.py` | State passed between a running call and the note; its bullet points |
| `real_dates.py`, `easter_eggs.py` | Real dates in what's kept; the jokes |
| `report.py` | The bug report |
| `tests/` | The tests |
| `voice-loop/` | Speech recognition, Claude and speech |
| `iphone-hfp/` | `iphonecall` and the older Python dialer |

## Bug reports

`report.py` writes one file to `reports\` from the last 3 calls (`--calls 10` for more):

- Numbers become `<number 1>`, `<number 2>`, the same number always the same one. Contacts, your name and your Windows
  user name become `<name 1>`; a caller's name from the phone's own contacts becomes `<caller 1>`. Bluetooth addresses and
  the laptop's name are removed.
- What anyone said becomes a word count. The brief and the AIs' notes to each other are left out.
- It lists the laptop settings behind most problems: Developer Mode, mobile-device access, the phone helper, Phone Link
  (installed, running, start at sign-in, its Mobile devices option), headsets with calls on, paired phones, Claude Code
  login.
- It adds Windows' Bluetooth events from the last day (paired, pairing removed, authentication failed, connection
  refused) by device name, the two newest phone set-ups, the newest setup log, and the note's logs.

A private word inside an error message can still get through, so read a report before posting it.

Every setup run writes `setup-logs\setup-<date and time>.txt`. It isn't cleaned: it shows your Windows user name and the
laptop's name.
