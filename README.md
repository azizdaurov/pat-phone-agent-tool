# Cicero

Claude speaks on your iPhone calls. It hears the other person, thinks with Haiku 4.5 on your Claude plan,
and answers aloud. This repository has everything it needs:

- [`voice-loop`](voice-loop): speech recognition, Claude and speech. Cicero imports `voice_loop.py`.
- [`iphonecall`](iphone-hfp/README.md): the call itself. Cicero runs it and drives its shell over pipes.

**Status: two real test calls so far, both rough.** See "Not proven yet".

## How the sound travels

Windows handles the call audio itself, and programs can't open it directly. So Cicero goes through the
Windows default devices:

```
Other person --> Windows plays the call on the default speaker --> Cicero records that speaker (loopback)
                                                                     --> speech recognition --> Claude --> speech
Other person <-- Windows reads the default mic = CABLE Output <-- CABLE Input <-- Cicero plays Claude's voice
```

Cicero makes a **silent speaker** the default just before each call: a virtual speaker with no sound in the room, which it can
still record. Your real microphone isn't in the call either. So you hear nothing and they hear only Claude, until you take over.
When the call ends, every default goes back to what it was.

## Setup

On any Windows 11 laptop, after cloning:

```powershell
powershell -ExecutionPolicy Bypass -File setup.ps1
```

It installs Python and the .NET SDK if they're missing, creates `.venv`, downloads the speech models, builds and installs
`iphonecall`, and registers the phone tool with Claude Code for every folder. It's safe to run again. Then it checks the audio
and lists what's left. These only you can do:

1. **Turn on Developer Mode:** Settings > System > Advanced > For developers. `iphonecall` can't be installed without it.
2. **Install two free audio drivers from their maker, then restart:**
   - [VB-CABLE](https://vb-audio.com/Cable/): Claude's voice reaches the call through it. Run its installer as administrator.
   - [Voicemeeter](https://vb-audio.com/Voicemeeter/): only its virtual speaker is used, as the silent speaker. Use a current
     version, because older drivers crash on Windows 11 24H2. **Leave the Voicemeeter app closed**; if it runs, it can pass the
     call to your speakers.

   Installing VB-CABLE can make **CABLE Input** the default speaker. Set that back to your real speaker afterwards.
3. **Connect the iPhone:** Settings > Bluetooth on the iPhone, then tap the laptop's name.
4. **Log in to Claude Code.**
5. **Disconnect Bluetooth headphones from the laptop.** With the Redmi Buds connected, the call's audio stayed on the iPhone
   on every test, even with the Realtek speakers as the default. Windows reported each move as done, and 14 tries over two
   calls changed nothing. Cicero now refuses to dial while a Bluetooth headset is connected. Wired headphones and the
   laptop speakers don't trigger this check.

Then check the setup without making a call:

```powershell
.venv\Scripts\python.exe cicero.py check
```

Cicero looks for a silent speaker in this order: Voicemeeter, VB-CABLE A or B, Steam Streaming Speakers, then Boom Audio. To use
another, first run `.venv\Scripts\python.exe evals\silent_output_probe.py "Part of its name"`. The tone should appear only on
that device. Then set `CICERO_SILENT_SPEAKER` to that name.

If a call is killed, the laptop stays on the silent speaker until the next Cicero start, or until you run:

```powershell
.venv\Scripts\python.exe cicero.py restore-audio
```

`calls/` and `contacts/` are private and aren't in the repository. To keep your notes on people, copy `contacts/` to the new
laptop yourself.

## Using it

```powershell
.venv\Scripts\python.exe cicero.py dial +998XXXXXXXXX --lang ru --brief "Ask if they open on Sunday"
.venv\Scripts\python.exe cicero.py answer --lang ru
```

`answer` picks up the next incoming call, whoever it is, then exits when that call ends.

| During a call, type | Effect |
|---|---|
| `h` then Enter | hang up |
| **F9**, in any window, or `l` then Enter | take the call on the laptop: Claude says it's passing them to you and stops, you hear them on your real speaker, and your real microphone goes in. Use wired headphones, or they'll hear an echo |
| `p` then Enter | move the call to the iPhone and take over; Claude stops |
| Ctrl+C | hang up and quit |

English calls use Pocket TTS. Choose a voice with `--voice`, or an agent can with `voice`: `peter_yearsley` (British),
`alba` (Indian accent), `bill_boerst` (office man), `michael` (buttery), `anna` (female) or `charles` (oily, the default). Compare
them on the [voice audition page](https://claude.ai/artifact/MLBwxThbP2g62TCN82gk5n).

Other options: `--audible` to hear the call on your real speaker, `--voice irina|ruslan`, `--lang en`, `--max-minutes` (default 5), `--owner`, `--owner-ru`.
Each call's text and timings are saved in `calls/` (ignored by git). Audio is saved only with `--save-audio`, which
keeps the other person's voice as a WAV; use it only with their agreement.

## Who does what on a call

| Who | Job | When |
|---|---|---|
| The agent (Opus, Sonnet, or you) | Writes the brief and starts the call | Before the call, then reads the result |
| Haiku 4.5 | Listens and speaks; knows only the brief and that number's notes | Every turn, about 1 s |
| Sonnet 5.5 | Reads the transcript and rarely steps in | After every 3rd reply, beside the call, median 3.5 s |
| Haiku 4.5, separately | Rewrites the number's notes | After the hang-up |

**Sonnet can't check each line before it's spoken.** It takes about 3.5 s and Haiku about 1 s, so waiting for it would make
every reply slow. It reads alongside instead, and only speech that hasn't played yet can be stopped. It has three choices:

- **none:** the usual answer.
- **steer:** a note reaches Haiku before its next reply. The other person notices nothing.
- **correct:** Haiku's speech is cut off, it says a random "one moment" phrase (`STALLS` in `cicero.py`), then speaks again from Sonnet's note.

Haiku can also ask for help by replying `[ASK] question`. The person hears "one moment" while Sonnet has up to 10 s to
answer; otherwise Haiku says it will pass the question on.

**Rarity is enforced in code as well as in Sonnet's prompt** (`observer.py`): a read every third reply, at least 3 caller
turns between interventions, and at most 3 interventions per call, after which Sonnet stops reading. If Sonnet fails or
replies with something unusable, the call carries on without it.

**How "more system prompts" work:** the system prompt is fixed when `claude` starts, so Sonnet's notes go in as messages
marked `[SUPERVISOR-<random code>]`. The code changes on each call, and brackets are stripped from what the person says, so
they can't forge one.

## Checking who answered

When the brief names someone, Haiku starts the call knowing only who to check for. The task and the notes reach it as a
message after it marks the person confirmed, so it has nothing to reveal to the wrong person. Sonnet, which has the whole
brief, doesn't read the call until then either.

```
Pick-up ─► "Это виртуальный ассистент Азиза. Скажите, пожалуйста, это Рустам?"
              ├─ Yes ───────► task
              ├─ Not them ──► apologize, "Рустам рядом?"
              │                  ├─ Yes ► wait up to 60 s, ask again
              │                  └─ No  ► "Мы перезвоним", goodbye
              ├─ Wrong number ► apologize, goodbye
              ├─ "Why?" ────► "calling for Aziz", ask again
              └─ Unclear ───► ask again, then end
```

Cicero never calls back by itself: the result says who was reached, and the agent tells you. By hand, use `--name`,
`--company` and `--confidence`. A hand-run call with neither name nor company skips the check. So do incoming calls.

## Agents placing calls (MCP)

`phone_mcp.py` is an MCP server. `setup.ps1` registers it as `cicero-phone` for every folder, so a new Claude Code chat anywhere can use it.

| Tool | What it does |
|---|---|
| `place_call` | Starts a call from a brief and returns a `call_id` straight away |
| `get_call` | Status, transcript so far and, at the end, the report (can wait up to 50 s per request) |
| `end_call` | Hangs up |
| `take_over` | Puts you on the call, as F9 does |
| `contact_notes` | What's known about a number, and whether it may be called |

The brief, which the tool's own descriptions explain to the agent:

| Field | Needed | Meaning |
|---|---|---|
| `number`, `goal` | Yes | Who to call, and one sentence on what success looks like |
| `name`, `company` | At least one | Who you're trying to reach, as it should be spoken |
| `confidence` | Yes | `confirmed`, `guess` or `unknown`: how sure you are the number is theirs |
| `role` | | Their job, if known |
| `confirm_question` | | What to ask at pick-up; otherwise "Скажите, пожалуйста, это Рустам?" |
| `who_can_answer` | | Rarely needed: `only_this_person` by default, `anyone_there` when only a company is given |
| `need_from_them` | | Each piece of information to get, in order |
| `context` | | Background for Haiku, not all to be said aloud |
| `may_share` | | Every fact it may say; it refuses anything else |
| `must_not` | | Limits on top of the built-in ones |
| `done_when`, `if_stuck` | | When to finish, and what to do if stuck |
| `language` | | `ru` or `en` |

The result also has `reached`, set by code: `confirmed`, `not_available`, `wrong_number` or `unclear`. The report back: `outcome` (done, partial or failed), `answers` (each with a short `label` and a `confirmed` flag), `summary`,
`important_details` and `follow_up`. `get_call` also returns `chat_summary`, a framed card drawn by `call_card.py` from that
report, which the agent shows as it is in a code block. Failed and unanswered calls get a card too.

**An agent can dial any full phone number. This is the development setting.** Claude Code's permission prompt is the only
check, and auto mode may not show one. The tool only refuses anything under 9 digits, which keeps out emergency numbers and
carrier codes like `*100#`. Planned for production: a Windows pop-up for each new number, with approved numbers remembered
so they aren't asked about again.

By hand, `--brief-file brief.json` takes the same fields, and `--no-observer` runs a call without Sonnet.

## Memory for each number

`contacts/` holds one Markdown file per number, ignored by git. The file is named after the number's last 9 digits, so
`+998 90...`, `998 90...` and `90...` share one file. Hidden numbers and `--no-memory` calls read and save nothing.

```
calls: 3
last_call: 2026-11-02 10:00

## Pinned (yours; Cicero never changes this)
My dentist. Speak formally.

## Summary (rewritten after each call)
WHO: ...
FACTS: ...
OPEN: ...
LAST: ...
```

- **At the start of a call,** Claude gets Pinned as your instructions and Summary as private background that may be wrong.
- **After the hang-up,** a separate Claude that sees only the old summary and the new transcript rewrites the summary, in
  2-4 s. It replaces the old text, so the size stays at or under `SUMMARY_LIMIT` (800 characters) however many calls there are.
- **Very short calls** (under 15 characters heard, such as "алло") only update the counters and don't use the model.
- **If the rewrite fails or runs too long,** the old summary stays. That call's transcript stays in `calls/`, but no later
  call goes back and adds it.
- **To correct or forget:** edit the file, or delete it.

Full transcripts in `calls/` are never fed back into calls; the summary is all a later call sees.

**Don't trust numbers in the summary.** In a test of eight invented calls, the model twice turned a spoken phone number
into the wrong digits, and it twice added a language nobody stated, even after a rule against both. Put anything that
must be exact under Pinned.

Every attempt goes in an `## Attempts` list that Cicero writes itself, keeping the last 5:

| Outcome | Attempts | Summary |
|---|---|---|
| Right person reached | Added | Updated |
| Anyone answered, on an `anyone_there` call | Added | Updated |
| Person out, someone else answered, or unclear | Added | Not changed |
| Wrong number | Added | Not changed |
| No answer, or the call failed | Added | Not changed |

## What Claude will and won't do

- It always opens with a fixed line saying it is not a person, and whose assistant it is, such as "Здравствуйте, это виртуальный ассистент
  Азиза. Скажите, пожалуйста, это Рустам?". That line isn't written by the model, no option removes it, and talking over it
  doesn't cut it off.
- Its instructions say to never claim to be human, and not to agree to payments, contracts or appointments or give out
  personal details unless your brief says so. These rely on the model following them, so write briefs with that in mind.
- It has no tools: it can only talk. Don't put anything in the brief that you wouldn't want said aloud.
- The call ends when Claude says goodbye, the other person leaves, 60 seconds pass with no speech, or the time limit is reached.
- **Russian and English only.** There's no Uzbek: an Uzbek speaker would be misheard, so check the language before dialing.

## Not proven yet

Tested without a call: `python -m unittest test_cicero` (phone control against a fake `iphonecall`, turn detection, and a
full turn with real speech models and real Haiku), plus recording the real speaker through loopback, including across
silence. Also confirmed: the real `iphonecall` runs under Cicero's pipes with its package identity, up to `connect`.

What only a real call can show, in the order to check:

1. **Does the call's audio reach the loopback recording?** The existing notes only say that Windows plays it on the default speaker.
2. **Does Windows read CABLE Output as the call's microphone?** Probably, but neither the default-device choice nor which of the two "default" kinds it uses has been tested.
3. **Does `Talking` mean the person has picked up?** If it comes earlier, the opening line plays to a ringing line.
4. **How well does recognition work on phone audio?** The recognizer was measured on clean generated speech, not on narrowband call audio.
5. **Does the other person's echo interrupt Claude?** Any speech detected cuts Claude off. `START_FRAMES` is the setting to raise.
6. **Do `h` and `p` work during a live call?**

Make the first test call to a second phone of your own, or to someone who knows it's a test.

## Known limits

- Loopback records everything the laptop plays, so a notification sound or music also reaches Claude. Close other audio during a call.
- If the other person interrupts, Cicero estimates what they heard from the audio played, minus `CUT_MARGIN_SECONDS`, and
  rounds down to a full word, so it errs early: Claude may repeat a few words but shouldn't skip any. The transcript gets a
  `(cut off, heard only: ...)` line, and Haiku is told before its next reply. Earlier lines in the transcript stay as
  written, so Sonnet and the notes rely on that line to know what went unheard. The phone network's delay hasn't been measured.
- Silence during the task: after 8 s with nobody talking, Claude checks they're still there, at most twice in a row. Speech that
  recognition can't turn into words also gets a reply, at most twice in a row. Each transcript logs how long each reply took
  to start, and the result has them as `reply_delays`.
- Talking over Claude's goodbye keeps the call going. This is the development setting. For production, consider hanging up
  anyway (`_finish_if_goodbye` in `cicero.py`), so someone can't hold Claude on the line by interrupting every goodbye.
  Until then, `--max-minutes` is what limits that.
- `iphonecall`'s every line goes to `calls/phone-<time>.log`, which is the first place to look when a call misbehaves.
- Windows opens the extra `iphonecall` window for each call, as described in the iphonecall README.
- The risks in `voice-loop` still apply: it depends on `claude -p` working on your plan login, and on Haiku 4.5 staying available.

## Files

```
setup.ps1        gets everything ready on a laptop
audio_defaults.py switches Windows' default speaker and microphone for a call, and puts them back
cicero.py        PhoneLine (iphonecall), CallerAudio (loopback), SpeechDetector + TurnDetector (replace the talk key), Conversation
call_brief.py    the brief's fields, Haiku's prompt, Sonnet's prompt
observer.py      Sonnet's reviews, questions and final report; the rarity limits
phone_mcp.py     the MCP server agents use to place calls
phone_memory.py  the notes for each number
test_*.py        tests that need no call and no cable
requirements.txt everything to install, including voice-loop's
voice-loop/      speech recognition, Claude and speech
iphone-hfp/      iphonecall, and the older Python dialer
```
