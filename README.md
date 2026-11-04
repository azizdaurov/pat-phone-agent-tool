# Pat, the Phone Agent Tool

Claude speaks on your iPhone calls. It hears the other person, thinks with Haiku 4.5 on your Claude plan,
and answers aloud. This repository has everything it needs:

- [`voice-loop`](voice-loop): speech recognition, Claude and speech. Pat imports `voice_loop.py`.
- [`iphonecall`](iphone-hfp/README.md): the call itself. Pat runs it and drives its shell over pipes.

**Status: two real test calls so far, both rough.** See "Not proven yet".

## Legal notice

Pat places phone calls with an AI voice. **You are the caller.** You alone are responsible for following the laws that apply to
your calls, including, where they apply, the US Telephone Consumer Protection Act and the FCC's ruling that AI-generated voices
are artificial voices, Do Not Call lists, and the call-recording and consent laws of every country and state involved. Get the
consent the law requires before you call. Never use Pat to deceive anyone about who is calling, and do not use it for sales,
bulk calls, harassment or emergencies. Pat's built-in limits reduce misuse but do not make a call lawful or consented. AI and
speech recognition make mistakes. Pat is provided "as is", without warranty and without liability, as the Apache License says.
[TERMS.md](TERMS.md) is the agreement for using Pat as Oasis Team provides it.

## License

Pat's source code is licensed under the [Apache License 2.0](LICENSE); see also [NOTICE](NOTICE). The names "Pat" and
"Oasis Team" are not licensed: see [TRADEMARK.md](TRADEMARK.md). A modified version or fork is its maker's work, not Oasis Team's.
The speech models, voices and audio drivers that Pat downloads or installs each have their own licenses.

## First run and personal settings

Pat first asks what it should call you. It then shows a Terms of Use window. The checkbox starts unchecked and
**Agree and open Pat** stays disabled until you check it. Cancel closes setup before any phone watcher or call starts.
The note, command-line calling and MCP phone tools require this setup. Hanging up or taking over an existing call stays available.

`TERMS.md` contains the supplied Terms of Use, shown as formatted text in that window. Replacing its contents requires
users to accept the new text on their next launch. This checkbox records acceptance; it does not claim to verify that someone read it.
Your name and acceptance record are saved locally in `contacts/user-profile.json`, which is ignored by Git. No email or Git identity is changed.

Right-click the tray icon and choose **Your name, region and phone...** to change:

- Your name, used by outgoing and incoming AI calls. There is no default owner name.
- The country for local numbers. With none selected, enter full international numbers beginning with `+` and the country code.
- Your IANA time zone and the date format for reports. ISO `YYYY-MM-DD` is the default; `DD-MM-YYYY` and `MM/DD/YYYY` are available.
- Which paired phone to use. **Find paired phones** lists device names and saves the selected device's ID, so renaming it does not break selection.

Automatic phone selection works only when one hands-free phone is paired, regardless of its name. With several phones,
choose one explicitly rather than letting Pat guess. After updating this version, rebuild the phone helper with `setup.ps1`.

## Speech stays ready while Pat is open

After first-run setup, the note starts a separate local speech process. It loads English and Russian recognition,
the supported voices and speech detection once, then keeps their weights in memory. English voices share one TTS model.
Call processes reuse these models through authenticated local Windows pipes; they do not load another copy for each call.
The resident process opens no microphone or speaker and makes no phone calls.

The prompt bar shows **Speech is getting ready…** during the one-time startup. The message disappears when speech is ready.
Start Pat before you need it and wait for the message to disappear. Warmup depends on the computer and can take a couple of minutes.
While it loads, you can answer on the iPhone. An AI request is kept only while that same call is still ringing;
expired or cancelled requests cannot wait for and pick up a later call.

Hiding the note or closing it to the tray keeps the models loaded. **Quit** releases them once an active AI call has
finished, so closing the note does not cut off its speech. Direct command-line calls without the note keep the standalone
loading behavior. More RAM is used while the note is running, in exchange for avoiding model startup on every call.

`calls/speech-service.log` records loading failures; the private service descriptor in `calls/` is ignored by Git.
The offline regression suite in `test_speech_service.py` uses fake models and cannot open audio devices or place calls.

## How the sound travels

Windows handles the call audio itself, and programs can't open it directly. So Pat goes through the
Windows default devices:

```
Other person --> Windows plays the call on the default speaker --> Pat records that speaker (loopback)
                                                                     --> speech recognition --> Claude --> speech
Other person <-- Windows reads the default mic = CABLE Output <-- CABLE Input <-- Pat plays Claude's voice
```

Pat makes a **silent speaker** the default just before each call: a virtual speaker with no sound in the room, which it can
still record. Your real microphone isn't in the call either. So you hear nothing and they hear only Claude, until you take over.
When the call ends, every default goes back to what it was.

## Setup

On any Windows 11 laptop, including a second one for the same iPhone, after cloning:

```powershell
powershell -ExecutionPolicy Bypass -File setup.ps1
```

It installs what's missing: Python, the .NET SDK, the packages, about 2 GB of speech models, `iphonecall`, and the two free audio
drivers ([VB-CABLE](https://vb-audio.com/Cable/) and [Voicemeeter](https://vb-audio.com/Voicemeeter/)). It turns on Developer Mode,
registers the phone tool, and puts your default speaker and microphone back on the real ones. It's safe to run again. Then:

1. **Approve** what Windows asks: Developer Mode, and each driver. A driver may also ask whether you trust it.
2. **Restart** when it offers. Setup carries on by itself afterwards.
3. **Connect the iPhone:** setup opens Bluetooth settings and waits. Pair it if needed, then on the iPhone go to Settings > Bluetooth and tap the laptop's name.
4. **Keep the Voicemeeter app closed.** Only its virtual speaker is used; if the app runs, it can pass the call to your speakers.
5. **Disconnect Bluetooth headphones from the laptop** before calls. With the Redmi Buds connected, the call's audio stayed on the iPhone
   on every test, even with the Realtek speakers as the default. Windows reported each move as done, and 14 tries over two
   calls changed nothing. Pat now refuses to dial while a Bluetooth headset is connected. Wired headphones and the
   laptop speakers don't trigger this check.

When it's all ready, setup opens the sticky note. To see what it would do, changing nothing, add `-Rehearse`. The Claude Code app must already
be installed and logged in; setup checks.

Then check the setup without making a call:

```powershell
.venv\Scripts\python.exe pat.py check
```

Pat looks for a silent speaker in this order: Voicemeeter, VB-CABLE A or B, Steam Streaming Speakers, then Boom Audio. To use
another, first run `.venv\Scripts\python.exe evals\silent_output_probe.py "Part of its name"`. The tone should appear only on
that device. Then set `PAT_SILENT_SPEAKER` to that name.

If a call is killed, the laptop stays on the silent speaker until the next Pat start, or until you run:

```powershell
.venv\Scripts\python.exe pat.py restore-audio
```

`calls/` and `contacts/` are private and aren't in the repository. To keep your notes, contacts and who-picks-up choices, copy
`contacts/` to the new laptop yourself, and `calls/note-settings.json` for the menu's settings.

An iPhone talks hands-free to one laptop at a time. Before using a laptop, tap its name in the iPhone's Bluetooth settings.

## Using it

```powershell
.venv\Scripts\python.exe pat.py dial "+COUNTRY_CODE_NUMBER" --brief "Ask if they open on Sunday"
.venv\Scripts\python.exe pat.py answer
```

Replace `+COUNTRY_CODE_NUMBER` with a full international number. New desktop settings, command-line calls and MCP calls
default to English. Use `--lang ru` or `language="ru"` for Russian; saved desktop language choices stay in effect.
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

## The sticky note

A small window that stays on top, watches the phone line, and decides who takes each incoming call:

```powershell
.venv\Scripts\pythonw.exe note.py
```

To try the window with a pretend phone, so nothing
rings or dials: `.venv\Scripts\python.exe evals\note_demo.py`.

| Screen | What's on it |
|---|---|
| No call | Just a prompt bar. Type what you want and an agent places the call through the phone tool |
| Incoming | The caller, then `AI once`, `Always AI` and `Me (iPhone)`. The arrow chooses iPhone or Laptop for `Me`. Claude gets ready as soon as it rings, about 10 s, so the choice is quick |
| After the call | The bullet points, the full summary and what to do next, for as long as you want. `Done` goes back to the bar |
| Claude on the call | A mixer that follows the sound of both voices, bullet points that fill in during the call (dots until then), a few words on what it's about, `Listen` and `Take over`. Calls placed by agents show here too |
| You on the call | iPhone/Laptop switch and `End call`. The mixer only appears on the laptop: on the iPhone, the laptop can't hear the call |

- **`Always AI`** is for that number only. To undo it, set it back in Contacts.
- **Settings** are on the right-click menu of the note's icon, in the hidden icons:
  - **Zoom in, Zoom out:** the size of the note.
  - **Incoming calls speak:** the language Claude answers in. English by default.
  - **Unknown numbers:** show the note's options (the default), Always AI, or Always me.
  - **English voice, Russian voice:** who Claude sounds like. Agents' calls use this too, unless the agent names another voice.
  - **Contacts...:** see, add and remove contacts, and choose for each one: Ask, AI or Me.
- **AI** answers by itself. **Me** never answers by itself, since you may be away: Claude stays out and the iPhone rings as usual, and the note still offers its buttons.
- **`Listen`** plays both sides on your real speaker, and your microphone stays out of the call.
- **`Take over`** puts you on the call on the laptop, after Claude says it's passing them to you, the same as F9. The switch moves it to the iPhone.
- **`Me`** answers on the iPhone the first time, then wherever the arrow last pointed, even after a restart. The switch during a call doesn't change that choice.
- **Only one copy** can run. Opening it again brings the open one to the front.
- **Bullet points** come from a small Claude beside the call, which only reads the transcript and can't affect the call. Values come through speech recognition, so they can be wrong.
- **Hiding:** with no call, the note slides to the nearest screen edge and leaves a sliver; move the pointer onto it to bring it back. During a call the arrow does the same. A ringing call always brings it back.
- **The small buttons:** the dash minimizes to the taskbar. The cross closes it to the hidden icons, where it keeps watching for calls and comes back when one rings. To stop it, right-click its icon there and choose Quit.
- Drag it by any blank part of the paper.

## Real dates

Notes, reports and the sticky note use complete dates in your chosen format, never "tomorrow", so older notes stay clear.
The calendar uses the saved IANA time zone, including daylight-saving changes. For someone in another zone, supply
`time_zone` in the phone tool or brief, or use `--time-zone America/New_York` on the command line. Use `date_format`
or `--date-format iso|dmy|mdy` to override report formatting for that call. The models receive the local date, time,
UTC offset and coming days in the chosen zone, and are told to clarify a different zone if the other person means one.
`real_dates.py` replaces leftover relative dates. A transcript stays word for word.

## Keeping numbers private

Real numbers stay on this laptop. The AI only sees a contact's name or a placeholder such as `#1`, and the phone tool swaps it back
when dialing. Results, summary cards and call ids show the name or placeholder too.

- **Contacts** live in `contacts/book.json`, which isn't in the repository. Then you can say "call Рустам", in the note or in a chat:

  ```powershell
  .venv\Scripts\python.exe private_numbers.py add "Alex" "+COUNTRY_CODE_NUMBER"
  .venv\Scripts\python.exe private_numbers.py list
  ```

Use your contact's name and full international number in that example.

- **A number typed into the note** is swapped for its contact's name or a placeholder before anything leaves the laptop. The note shows you the real number.
- **A number typed into a Claude Code chat** reaches Claude before any of this can act, so use a contact's name in chats. It still dials if you do type one.
- **What still goes to Claude:** names, the task, and everything said on the call, including any number someone says aloud. To keep a call's content private as well, the AI would have to run on this laptop.

## Easter eggs

Type these in the sticky note's prompt bar, or try them with `.venv\Scripts\python.exe easter_eggs.py "pat pat"`:

| Type | What happens |
|---|---|
| A request ending in `--haiku`, `--sonnet` or `--cicero` | That piece appears under the call's summary, with a Copy button. A chat agent passes it as `summary_style` |
| `stats` | Calls, time on the phone and badges. Also on the tray icon's menu |
| `predict tea or coffee` | Pat the Octopus, heir to Paul, eats from one box. It's random |
| `pat pat` | A pat on the back |
| `facts` | The Pat facts you've found. Also on the tray icon's menu, as `Facts found` |
| A few famous phone numbers, and a few words | Find out. Each joke plays once |

The rules behind them, in `easter_eggs.py`:

- **They only show on your screen.** The person on a call never hears a joke, and the opening line doesn't change.
- **A joke number can't ring anyone.** After its joke it gets a plain refusal, here and in the phone tool, unless it's one of your contacts.
- **Emergency and crisis numbers are never jokes.** They always get a plain refusal, even though the list can't be complete: dial those yourself.
- **Only short requests can trigger a joke.** `Mom` does, once, and offers `Proceed` if she's a contact. `call Mom and ask about dinner` goes straight through.
- **The poems are for fun.** They can get details wrong, so the summary above each one is the record. They also cost a little of your Claude plan, and only run when asked for.

**Pat facts** are small lines under the summary after some calls, and they stop at 24. Turn them off on the tray icon's menu, under `Pat facts`. That also hides the rest of their story, and the jokes stay. Pat picks up where it left off if you turn them back on, one fact per call.

What has played is in `contacts/easter_eggs.json`. Delete the file to see them all again.

Any file whose last line is `#fisheggs` is an easter egg too, not part of how Pat works. Start with [fisheggs/READ_ME_FIRST.md](fisheggs/READ_ME_FIRST.md).

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
- **correct:** Haiku's speech is cut off, it says a random "one moment" phrase (`STALLS` in `pat.py`), then speaks again from Sonnet's note.

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

Pat passes the opening it actually spoke to Haiku with the first caller response. A clear yes to that opening's identity
question moves straight to the task. Confirmed details are kept without another confirmation at the end.

```
Pick-up ─► "Я виртуальный ассистент. Мой пользователь — [имя]. Скажите, пожалуйста, это Рустам?"
              ├─ Yes ───────► task
              ├─ Not them ──► apologize, "Рустам рядом?"
              │                  ├─ Yes ► wait up to 60 s, ask again
              │                  └─ No  ► "Мы перезвоним", goodbye
              ├─ Wrong number ► apologize, goodbye
              ├─ "Why?" ────► "calling for [your name]", ask again
              └─ Unclear ───► ask again, then end
```

Pat never calls back by itself: the result says who was reached, and the agent tells you. By hand, use `--name`,
`--company` and `--confidence`. A hand-run call with neither name nor company skips the check. So do incoming calls.

## Agents placing calls (MCP)

`phone_mcp.py` is an MCP server. `setup.ps1` registers it as `pat-phone` for every folder, so a new Claude Code chat anywhere can use it.

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
| `time_zone` | | Optional IANA zone for the person being called; otherwise your saved zone |
| `date_format` | | Optional `iso`, `dmy` or `mdy`; otherwise your saved report format |

The result also has `reached`, set by code: `confirmed`, `not_available`, `wrong_number` or `unclear`. The report back: `outcome` (done, partial or failed), `answers` (each with a short `label` and a `confirmed` flag), `summary`,
`important_details` and `follow_up`. `get_call` also returns `chat_summary`, a framed card drawn by `call_card.py` from that
report, which the agent shows as it is in a code block. Failed and unanswered calls get a card too.

**After first-run setup, an agent can dial full phone numbers.** Terms acceptance is a setup gate, not approval of each call.
Claude Code's permission prompt may ask about a call; auto mode may not. Phone numbers are parsed with country numbering
metadata and passed to the dialer as `+` followed by digits. Valid short international numbers are supported. Emergency
and service-code restrictions remain. The privacy filter also covers short numbers and text such as `Call:+29022023`.

By hand, `--brief-file brief.json` takes the same fields, and `--no-observer` runs a call without Sonnet.

## Memory for each number

`contacts/` holds one Markdown file per full international number, ignored by git. The filename includes the country code,
so different countries or area codes never share notes merely because their last nine digits match. Formatting differences
such as spaces or parentheses are normalized. Local numbers require the appropriate country in settings.
Hidden numbers and `--no-memory` calls read and save nothing.

Old nine-digit notes and answer rules are carried over only when the saved contact/placeholder book identifies a single
full number for that old key. The original notes file is kept. Ambiguous old records remain untouched and are not assigned
to either person; inspect them before moving them to full-number filenames. Notes store their date format so older dates
are not silently reinterpreted after a preference change.

```
calls: 3
last_call: 2026-11-02 10:00

## Pinned (yours; Pat never changes this)
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

Every attempt goes in an `## Attempts` list that Pat writes itself, keeping the last 5:

| Outcome | Attempts | Summary |
|---|---|---|
| Right person reached | Added | Updated |
| Anyone answered, on an `anyone_there` call | Added | Updated |
| Person out, someone else answered, or unclear | Added | Not changed |
| Wrong number | Added | Not changed |
| No answer, or the call failed | Added | Not changed |

## What Claude will and won't do

- It always opens with a fixed line saying it is not a person, and whose assistant it is, such as "Hello, this is [your name]'s AI assistant.". That line isn't written by the model, no option removes it, and talking over it
  doesn't cut it off.
- Its instructions say to never claim to be human, and not to agree to payments, contracts or appointments or give out
  personal details unless your brief says so. These rely on the model following them, so write briefs with that in mind.
- It has no tools: it can only talk. Don't put anything in the brief that you wouldn't want said aloud.
- The call ends when Claude says goodbye, the other person leaves, 60 seconds pass with no speech, or the time limit is reached.
- **Russian and English only.** There's no Uzbek: an Uzbek speaker would be misheard, so check the language before dialing.

## How Pat hears

Russian uses GigaAM v3 RNN-T and English uses Parakeet TDT v2, both on the CPU through onnx-asr. They transcribe when the person stops
talking, in about 0.2 s for a short turn. Parakeet needs about 1.1 GB of memory, GigaAM about 0.4 GB.

Word errors on the same 60 clips per language, compared with the models Pat used before (full run of 200 clips in brackets):

| | Simulated phone line | Plus background voices |
|---|---|---|
| Russian, GigaAM RNN-T | 18.9% (16.0%) | 25.9% (23.9%) |
| Russian, GigaAM CTC, before | 20.6% (19.2%) | 31.2% (28.8%) |
| English, Parakeet v2 | 19.2% (16.2%) | 26.5% (23.5%) |
| English, Moonshine, before | 29.9% (25.8%) | 59.0% (51.1%) |

The Russian clips are real phone calls (Open STT), the English ones are conference calls (Earnings22), and the background voices
were mixed in by the test. Loading Parakeet adds about 6 s before an English call dials. On seven real English turns from one of our calls, Parakeet was no better than Moonshine and sometimes repeated words, so
the gain may be smaller on a real call. Whisper turbo tied Parakeet on English but took 8.5 s per turn. Saved calls have nothing above 4 kHz.

The scripts are `evals/stt_*.py`. They need `soundfile`, `scipy` and a `stt-test-data` folder beside this one, and aren't part of the setup.

## Not proven yet

Tested without a call: `python -m unittest test_pat` (phone control against a fake `iphonecall`, turn detection, and a
full turn with real speech models and real Haiku), plus recording the real speaker through loopback, including across
silence. Also confirmed: the real `iphonecall` runs under Pat's pipes with its package identity, up to `connect`.

What only a real call can show, in the order to check:

1. **Does the call's audio reach the loopback recording?** The existing notes only say that Windows plays it on the default speaker.
2. **Does Windows read CABLE Output as the call's microphone?** Probably, but neither the default-device choice nor which of the two "default" kinds it uses has been tested.
3. **Does `Talking` mean the person has picked up?** If it comes earlier, the opening line plays to a ringing line.
4. **Do the new recognizers help on real calls?** See "How Pat hears": they were chosen on recorded calls, and neither has been on a live call yet.
5. **Does the other person's echo interrupt Claude?** Any speech detected cuts Claude off. `START_FRAMES` is the setting to raise.
6. **Do `h` and `p` work during a live call?**

Make the first test call to a second phone of your own, or to someone who knows it's a test.

## Known limits

- Loopback records everything the laptop plays, so a notification sound or music also reaches Claude. Close other audio during a call.
- If the other person interrupts, Pat estimates what they heard from the audio played, minus `CUT_MARGIN_SECONDS`, and
  rounds down to a full word, so it errs early: Claude may repeat a few words but shouldn't skip any. The transcript gets a
  `(cut off, heard only: ...)` line, and Haiku is told before its next reply. Earlier lines in the transcript stay as
  written, so Sonnet and the notes rely on that line to know what went unheard. The phone network's delay hasn't been measured.
  If a complete detail was heard and only a short confirmation tag was cut off, a clear answer counts and Pat moves on.
  If the read-back itself was not heard in full, a bare yes/no cannot confirm it; Pat repeats the missing part.
- Silence during the task: after 8 s with nobody talking, Claude checks they're still there, at most twice in a row. Speech that
  recognition can't turn into words also gets a reply, at most twice in a row. Each transcript logs how long each reply took
  to start, and the result has them as `reply_delays`.
- Talking over Claude's goodbye keeps the call going. This is the development setting. For production, consider hanging up
  anyway (`_finish_if_goodbye` in `pat.py`), so someone can't hold Claude on the line by interrupting every goodbye.
  Until then, `--max-minutes` is what limits that.
- `iphonecall`'s every line goes to `calls/phone-<time>.log`, which is the first place to look when a call misbehaves.
- The risks in `voice-loop` still apply: it depends on `claude -p` working on your plan login, and on Haiku 4.5 staying available.

## Reporting a problem

Don't post files from `calls\` as they are: they hold real phone numbers, names, the call's brief and everything said.
Make a report instead:

```
.venv\Scripts\python.exe report.py
```

It writes one text file in `reports\` (ignored by git) from the last 3 calls; `--calls 10` takes more. Numbers become
`<number 1>`, `<number 2>` and so on, the same number always the same one, and saved contacts, your name and your Windows user
name become `<name 1>` and so on. What anyone said is replaced by a word count, and the brief and the AIs' notes to each other
are left out. Timings, devices, versions and errors stay. Read it before you post it: a private word in an error message can
still get through.

## Files

```
setup.ps1        gets everything ready on a laptop
audio_defaults.py switches Windows' default speaker and microphone for a call, and puts them back
real_dates.py    turns "tomorrow" into a real date in what's kept
private_numbers.py the contact list, and the placeholders that keep numbers off the AI
note.py          the sticky note: watches the line, and decides who takes each call
note_settings.py what the tray menu sets
note_window.py   its window: see-through, slides to an edge, lives in the tray
note/            what the note looks like
live_call.py     the state and commands passed between a running call and the note
live_notes.py    the note's bullet points and summary
pat.py           PhoneLine (iphonecall), CallerAudio (loopback), SpeechDetector + TurnDetector (replace the talk key), Conversation
call_brief.py    the brief's fields, Haiku's prompt, Sonnet's prompt
observer.py      Sonnet's reviews, questions and final report; the rarity limits
phone_mcp.py     the MCP server agents use to place calls
phone_memory.py  the notes for each number
report.py        a bug report you can post, with numbers, names and what was said left out
test_*.py        tests that need no call and no cable
requirements.txt everything to install, including voice-loop's
voice-loop/      speech recognition, Claude and speech
iphone-hfp/      iphonecall, and the older Python dialer
LICENSE, NOTICE  Apache License 2.0 for the code
TERMS.md         the Terms of Use shown at first run
TRADEMARK.md     what the names Pat and Oasis Team may be used for
```

Offline phone-selection checks: `dotnet run --project evals/phone-selection/phone-selection.csproj`. These checks use fake device names and never connect to a phone.
