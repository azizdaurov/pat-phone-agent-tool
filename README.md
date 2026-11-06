<p align="center">
  <img src="docs/banner.jpg" alt="Pat: an octopus tentacle holding a vintage telephone handset" width="100%">
</p>

<p align="center"><b>Pat, the Phone Agent Tool.</b> Claude talks on your phone calls, from a Windows laptop.</p>

Pat places and answers calls through your own iPhone or Android phone, over Bluetooth. It hears the other person, thinks
with Claude Haiku 4.5 on your Claude plan, and answers aloud in English or Russian. A sticky note on your desktop shows
each call, and you can take over at any moment.

- **Free, on your own SIM.** Your number, your phone plan. No calling service, no per-minute fees.
- **Calls for you.** Type "call the dentist and ask if they open on Sunday" into the note, or let an agent place the call.
- **Answers for you.** For each contact: show the note's options, let the AI answer, or let your phone ring.
- **Supervised.** Sonnet 5.5 reads the call alongside Haiku and steps in only when it goes off track.
- **Private numbers.** Real numbers stay on the laptop. The AI sees a contact's name or a placeholder such as `#1`.
- **Honest.** Every call opens with a fixed line saying it's an AI assistant and whose. No option removes it.

Tested on real calls with an iPhone and an Android phone, November 2026.

## How it works

```
Them ─► phone ─► Bluetooth ─► Windows plays the call on a silent virtual speaker ─► Pat records it ─► speech recognition
                                                                                                         │
Them ◄─ phone ◄─ Bluetooth ◄─ Windows takes the call's mic from CABLE Output ◄─ Pat's voice ◄─ Claude Haiku ◄─┘
```

| Part | What it does |
|---|---|
| [`iphonecall`](iphone-hfp/README.md) | A small Windows app (C#) that holds the phone's hands-free line: dial, answer, hang up, move audio |
| [`voice-loop`](voice-loop) | Speech recognition, Claude and speech |
| `pat.py` | One call: hearing, turn-taking, the brief, Sonnet's supervision, the report |
| `note.py` | The sticky note: watches the line, decides who takes each call |
| `phone_mcp.py` | The `pat-phone` MCP server, so Claude Code agents can place calls |

## Requirements

- Windows 11 on an Intel or AMD (x64) processor. Not Windows on ARM, not macOS.
- [Claude Code](https://claude.com/claude-code), installed and logged in.
- An iPhone or Android phone with Bluetooth. Android makers handle Bluetooth calls differently.
- About 4 GB of disk, mostly speech models.

## Install

```powershell
git clone https://github.com/azizdaurov/pat-phone-agent-tool.git
cd pat-phone-agent-tool
powershell -ExecutionPolicy Bypass -File setup.ps1
```

Setup installs Python, the .NET SDK, the packages, the speech models, the phone helper and two free audio drivers
([VB-CABLE](https://vb-audio.com/Cable/) and [Voicemeeter](https://vb-audio.com/Voicemeeter/)). It turns on Developer
Mode, ends Phone Link, and sets up your phone for calls. Approve what Windows asks, and restart when it offers: setup
carries on by itself. It's safe to run again, and `-Rehearse` shows what it would do without changing anything.

Check everything without making a call:

```powershell
.venv\Scripts\python.exe pat.py check
```

Before calls, keep the Voicemeeter app closed, and disconnect Bluetooth headphones from the laptop
([why, and how to keep them](docs/audio.md#bluetooth-headphones)).

## Use

**The note.** Setup opens it; afterwards run `.venv\Scripts\pythonw.exe note.py`. Type what you want in its bar. When a
call rings, choose `AI once`, `Always AI` or `Me`. During a call, press **F9** anywhere to take over on the laptop.
[More](docs/note.md)

**The command line.**

```powershell
.venv\Scripts\python.exe pat.py dial "+COUNTRY_CODE_NUMBER" --brief "Ask if they open on Sunday"
.venv\Scripts\python.exe pat.py answer
```

Type `h` to hang up, `l` or F9 to take over on the laptop, `p` to move the call to your phone. [More](docs/calls.md)

**Agents.** Setup registers the `pat-phone` MCP server for every folder, so any new Claude Code chat can place a call with
`place_call`, follow it with `get_call`, and end it with `end_call`. [The brief](docs/calls.md#agents-placing-calls)

Make your first test call to a second phone of your own, or to someone who knows it's a test.

## Phone Link

Windows lets one app use a phone for calls: the one that registered on the phone's Bluetooth pairing first, even after
it's closed. Phone Link can hold your phone this way, and its setup screen can delete the pairing. Setup ends Phone Link
and turns off its start at sign-in. When the note says "Phone Link has your phone", press **Set up the phone for Pat's
calls**: Pat pairs the phone again and registers first. [Details](docs/phone.md)

## Privacy

- `calls/` and `contacts/` hold transcripts, notes and real numbers. They're ignored by git and never leave the laptop.
- Numbers typed into the note are swapped for a contact's name or `#1` before Claude sees them. Numbers typed into a
  Claude Code chat reach Claude, so use names there.
- Names, the task and everything said on a call do go to Claude.

## Something wrong?

```powershell
.venv\Scripts\python.exe report.py
```

It writes a report to `reports\` with numbers, names and what was said replaced by stand-ins. It includes the laptop
settings behind most problems and Windows' record of Bluetooth pairings. Read it before you post it. If setup itself
failed, send its log from `setup-logs\` (not cleaned: it shows your Windows user name).

## Documentation

| | |
|---|---|
| [Phone](docs/phone.md) | Pairing, Phone Link, choosing between phones, a second laptop |
| [The note](docs/note.md) | Screens, settings, first run, contacts, easter eggs |
| [Calls](docs/calls.md) | Briefs, who does what, checking who answered, memory, limits |
| [Audio](docs/audio.md) | How sound travels, headphones, speech recognition |
| [Development](docs/development.md) | Files, tests, bug reports |
| [Phone helper](iphone-hfp/README.md) | `iphonecall` and how Windows' calling APIs behave |

## Roadmap

- Sync the phone's contacts with Pat's. Until then, Pat's contacts win on the note, on the call and in what Haiku is told.
- Give the name-check prompt a "What you may tell them" section, which its never-share rule already points at.

## Legal notice

Pat places phone calls with an AI voice. **You are the caller.** You alone are responsible for following the laws that apply to
your calls, including, where they apply, the US Telephone Consumer Protection Act and the FCC's ruling that AI-generated voices
are artificial voices, Do Not Call lists, and the call-recording and consent laws of every country and state involved. Get the
consent the law requires before you call. Never use Pat to deceive anyone about who is calling, and do not use it for sales,
bulk calls, harassment or emergencies. Pat's built-in limits reduce misuse but do not make a call lawful or consented. AI and
speech recognition make mistakes. Pat is provided "as is", without warranty and without liability, as the Apache License says.
[TERMS.md](TERMS.md) is the agreement for using Pat as Oasis Team provides it.

## License

[Apache License 2.0](LICENSE); see also [NOTICE](NOTICE). The names "Pat" and "Oasis Team" are not licensed: see
[TRADEMARK.md](TRADEMARK.md). A modified version or fork is its maker's work, not Oasis Team's. The speech models, voices
and audio drivers that Pat downloads or installs each have their own licenses.
