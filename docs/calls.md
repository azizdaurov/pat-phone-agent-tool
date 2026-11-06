# Calls

## From the command line

```powershell
.venv\Scripts\python.exe pat.py dial "+COUNTRY_CODE_NUMBER" --brief "Ask if they open on Sunday"
.venv\Scripts\python.exe pat.py answer    # picks up the next incoming call, then exits when it ends
```

| During a call | Effect |
|---|---|
| `h` | Hang up |
| `l`, or **F9** in any window | Take over on the laptop: Claude says it's passing them to you and stops |
| `p` | Move the call to your phone and take over |
| Ctrl+C | Hang up and quit |

| Option | |
|---|---|
| `--lang ru` | Russian. English is the default |
| `--voice` | English: `charles` (default), `peter_yearsley`, `alba`, `bill_boerst`, `michael`, `anna`. Russian: `irina`, `ruslan`. Hear them with `evals\english_voice_samples.py` |
| `--name`, `--company`, `--confidence` | Who you're trying to reach; see [checking who answered](#checking-who-answered) |
| `--brief-file brief.json` | A full brief, with the fields below |
| `--time-zone`, `--date-format` | For someone in another zone, or another date style in the report |
| `--max-minutes` | Call length limit, default 5 |
| `--audible` | Hear the call on your real speaker |
| `--no-observer` | No Sonnet on this call |
| `--save-audio` | Keep the other person's voice as a WAV. Only with their agreement |

Each call's text and timings go to `calls\` (ignored by git).

## Who does what

| Who | Job | When |
|---|---|---|
| The agent (Opus, Sonnet, or you) | Writes the brief and starts the call | Before, then reads the result |
| Haiku 4.5 | Listens and speaks; knows only the brief and the number's notes | Every turn, about 1 s |
| Sonnet 5.5 | Reads the transcript and rarely steps in | After every 3rd reply, beside the call, about 3.5 s |
| Haiku 4.5, separately | Rewrites the number's notes | After the hang-up |

Sonnet is too slow to check each line before it's spoken, so it reads alongside and chooses one of three:

- **none:** the usual answer.
- **steer:** a quiet note reaches Haiku before its next reply.
- **correct:** Haiku's speech is cut off, it says a "one moment" phrase, then speaks again from Sonnet's note.

Haiku can also reply `[ASK] question`: the person hears "one moment" while Sonnet has up to 10 s to answer. Code keeps
Sonnet rare: at least 3 caller turns between interventions and at most 3 per call (`observer.py`). Its notes reach Haiku
marked with a code that changes every call, and brackets are stripped from what the person says, so they can't forge one.

## Checking who answered

When the brief names someone, Haiku starts the call knowing only who to check for. The task and notes reach it after it
marks the person confirmed, so there's nothing to reveal to the wrong person, and Sonnet stays out until then.

```
Pick-up ─► "This is [your name]'s AI assistant. Am I speaking with Rustam?"
              ├─ Yes ─────────► the task
              ├─ Not them ────► "Is Rustam nearby?" ─► yes: wait up to 60 s ─► ask again
              │                                       └► no: "We'll call back", goodbye
              ├─ Wrong number ► apologize, goodbye
              ├─ "Why?" ──────► "calling for [your name]", ask again
              └─ Unclear ─────► ask again, then end
```

Pat never calls back by itself: the result says who was reached. Calls with neither name nor company skip the check, and
so do incoming calls.

## Agents placing calls

`phone_mcp.py` is registered by setup as `pat-phone` for every folder.

| Tool | |
|---|---|
| `place_call` | Starts a call from a brief and returns a `call_id` at once |
| `get_call` | Status, transcript so far and, at the end, the report. Waits up to 50 s per request |
| `end_call` | Hangs up |
| `take_over` | Puts you on the call, as F9 does |
| `contact_notes` | What's known about a number, and whether it may be called |
| `list_contacts` | Contact names and placeholders, never numbers |

| Brief field | |
|---|---|
| `number`, `goal` | **Required.** Who to call, a contact's name or `#1`, and one sentence on what success looks like |
| `name`, `company` | **At least one.** Who to reach, written as it should be spoken |
| `confidence` | **Required.** `confirmed`, `guess` or `unknown`: how sure the number is theirs |
| `role`, `confirm_question` | Their job; what to ask at pick-up |
| `who_can_answer` | `only_this_person` (default), or `anyone_there` when only a company is given |
| `need_from_them` | Each piece of information to get, in order |
| `context` | Background for Haiku, not all to be said aloud |
| `may_share` | Every fact it may say. It refuses anything else |
| `must_not` | Limits on top of the built-in ones |
| `done_when`, `if_stuck` | When to finish, and what to do if stuck |
| `language`, `time_zone`, `date_format` | `ru` or `en`; the other person's IANA zone; `iso`, `dmy` or `mdy` |

The result has `reached` (`confirmed`, `not_available`, `wrong_number` or `unclear`, set by code), `outcome`, `answers`
with `confirmed` flags, `summary`, `important_details`, `follow_up`, and `chat_summary`: a framed card the agent shows as
is. After first-run setup an agent can dial full numbers; Claude Code's permission prompt is the per-call check, and in
auto mode it may not appear. Emergency and service codes stay refused.

## Memory for each number

`contacts\` keeps one Markdown file per full international number, ignored by git:

```
calls: 3
last_call: 2026-11-02 10:00

## Pinned (yours; Pat never changes this)
My dentist. Speak formally.

## Summary (rewritten after each call)
WHO: ...  FACTS: ...  OPEN: ...  LAST: ...
```

Claude gets Pinned as your instructions and Summary as background that may be wrong. After the hang-up a separate Claude,
seeing only the old summary and the new transcript, rewrites the summary in 2-4 s, capped at 800 characters. Calls under
15 heard characters only update the counters. Every attempt is listed under `## Attempts` (last 5); the summary changes
only when the right person, or anyone on an `anyone_there` call, was reached. Edit or delete the file to correct or
forget. Full transcripts never feed later calls.

**Put anything exact under Pinned.** In tests the summary model twice wrote a spoken phone number with wrong digits.

Hidden numbers and `--no-memory` calls read and save nothing. Old nine-digit notes carry over only when your contacts give
them a single owner.

## Dates

Notes, reports and the note write complete dates in your chosen format, never "tomorrow", using your saved IANA time
zone. The models get the local date, time and coming days, and `real_dates.py` replaces any relative date left over.
Transcripts stay word for word.

## What Claude will and won't do

- It always opens with a fixed line saying it's an AI assistant and whose. The model doesn't write it, and talking over
  it doesn't cut it off.
- It never claims to be human, and doesn't agree to payments, contracts or appointments, or give out personal details,
  unless the brief allows it. These rules rely on the model, so write briefs with that in mind.
- It has no tools: it can only talk. Don't put anything in a brief you wouldn't want said aloud.
- A call ends when Claude says goodbye, the other person leaves, 60 seconds pass without speech, or the time limit hits.
- Russian and English only.

## Known limits

- Pat records everything the laptop plays, so notifications and music reach Claude too. Close other audio.
- When interrupted, Pat estimates what was heard from the audio played and rounds down to a whole word, so Claude may
  repeat a few words but shouldn't skip any. The transcript marks it `(cut off, heard only: ...)`.
- After 8 s of silence Claude checks they're still there, at most twice in a row.
- Talking over Claude's goodbye keeps the call going (`_finish_if_goodbye` in `pat.py`); `--max-minutes` limits that.
- It depends on `claude -p` working on your plan login, and on Haiku 4.5 staying available.
