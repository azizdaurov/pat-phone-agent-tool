# The note

A small paper note that stays on top, watches the phone line, and decides who takes each incoming call.

Double-click **Pat** on your Desktop, or type **Pat** in the Start menu. It opens without a console window. If it is already
running, the shortcut brings the same note back. Setup can also start Pat when you sign in to Windows; this is off by default.
To change that choice or repair the shortcuts, run `powershell -ExecutionPolicy Bypass -File setup.ps1 -ShortcutsOnly`.

For a manual start or a demo:

```powershell
.venv\Scripts\pythonw.exe note.py           # the real note
.venv\Scripts\python.exe evals\note_demo.py  # a pretend phone: nothing rings or dials
```

## Screens

| Screen | What's on it |
|---|---|
| No call | A prompt bar. Type what you want, and an agent places the call through the phone tool |
| Ringing | The caller, then `AI once`, `Always AI` and `Me`. The arrow chooses phone or laptop for `Me`. Claude gets ready as soon as it rings, in about 10 s |
| Claude on the call | A mixer following both voices, bullet points that fill in during the call, `Listen` and `Take over` |
| You on the call | A phone/laptop switch and `End call` |
| After the call | Bullet points, the summary and what to do next, until `Done` |

- **`Always AI`** applies to that number. Undo it in Contacts.
- **AI** answers by itself. **Me** never does, since you may be away: the phone rings as usual and the note keeps its buttons.
- **`Listen`** plays both sides on your speaker; your microphone stays out of the call.
- **`Take over`** and **F9** put you on the call on the laptop after Claude says it's passing them to you. Noise and echo
  cancellation is optional and off by default. Choose **With** or **Without (default)** on the tray menu, including during take-over
  ([details](audio.md#taking-over-on-the-laptop)).
- **`Me`** answers on the phone the first time, then wherever the arrow last pointed.
- **Bullet points** come from a separate Claude that only reads the transcript. Values pass through speech recognition,
  so they can be wrong.
- **Hiding:** with no call, the note slides to the nearest screen edge; point at the sliver to bring it back. A ringing
  call always brings it out. The cross hides it to the tray, where it keeps watching. Quit is on the tray icon's menu.
- **One copy** runs at a time. Opening it again brings the open one forward.

The caller's name comes from Pat's contacts, or else from the phone. A separate AI check keeps only a first name and
surname clearly in the phone's label ("Rustam work" gives Rustam; "Mom" or "Restaurant" give nothing), and Pat may
greet the caller by it. It shares nothing more because of it, since caller ID doesn't prove who is speaking.

## Settings

Right-click the note's icon in the hidden icons:

| Item | What it sets |
|---|---|
| Zoom in, Zoom out | The note's size |
| Your name, region and phone... | Your name in each call language, how Pat refers to you, the country for local numbers, time zone, date format, the phone to use |
| Set up the phone for Pat's calls... | [Pairing](phone.md#set-up-the-phone-for-pats-calls) |
| Incoming calls speak | The language Claude answers in. English by default |
| Unknown numbers | The note's options (default), Always AI, or Always me |
| English voice, Russian voice | Who Claude sounds like, for agents' calls too unless they name another |
| Noise cancellation | With or Without (default), for laptop take-over. The choice stays saved and can be changed during take-over |
| Contacts... | Add, edit and remove contacts, and choose Ask, AI or Me for each |
| Stats, Facts found, Pat facts | See [easter eggs](#easter-eggs) |

**Your name** is one row: a language on the left, your name in it on the right. Type it once and AI writes it for the
other call languages; a spelling you type yourself is never overwritten. **Pronouns** are they/them (default), he/him or
she/her. Russian has no neutral pronoun, so they/them there means Pat uses your name.

**Country for local numbers:** with none, enter full international numbers starting with `+`.

**Contacts** live in `contacts\book.json`. Besides the Contacts window:

```powershell
.venv\Scripts\python.exe private_numbers.py add "Alex" "+COUNTRY_CODE_NUMBER"
.venv\Scripts\python.exe private_numbers.py list
```

## First run

Pat asks what to call you and how to refer to you, then shows the [Terms of Use](../TERMS.md). **Agree and open Pat**
stays off until you tick the box. The note, command-line calls and MCP tools need this; hanging up or taking over a call
doesn't. Your name and acceptance are saved in `contacts\user-profile.json`. Changing `TERMS.md` asks everyone to accept
again.

## Speech stays loaded

The note starts a local speech process that loads recognition, voices and speech detection once and keeps them in memory,
so calls don't wait for them. It opens no microphone or speaker. The prompt bar says **Speech is getting ready…** until
it's done, which can take a couple of minutes; you can answer on your phone meanwhile. Hiding the note keeps the models
loaded; Quit releases them after any AI call has finished. Loading errors go to `calls\speech-service.log`.

## Easter eggs

Type these in the prompt bar, or try them with `.venv\Scripts\python.exe easter_eggs.py "pat pat"`:

| Type | What happens |
|---|---|
| A request ending in `--haiku`, `--sonnet` or `--cicero` | That poem appears under the call's summary |
| `stats` | Calls, time on the phone and badges |
| `predict tea or coffee` | Pat the Octopus, heir to Paul, eats from one box |
| `pat pat` | A pat on the back |
| `facts` | The Pat facts you've found |
| A few famous phone numbers, and a few words | Find out. Each joke plays once |

They show only on your screen; the person on a call never hears one. A joke number can't ring anyone, and emergency and
crisis numbers always get a plain refusal: dial those yourself. Poems can get details wrong, so the summary above each is
the record. **Pat facts** appear under some summaries and stop at 24; turn them off on the tray menu. Delete
`contacts\easter_eggs.json` to see everything again. Files whose last line is `#fisheggs` are easter eggs too: start with
[fisheggs/READ_ME_FIRST.md](../fisheggs/READ_ME_FIRST.md).
