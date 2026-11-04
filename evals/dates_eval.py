"""What real Claude writes about dates, in the notes, the report and the live note, before and after the code's catch. Text only, no phone."""
import datetime
import json
import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import cicero
from call_brief import CallBrief
from observer import OBSERVER_MODEL, Observer
from phone_memory import ContactNotes, SUMMARY_LIMIT, SUMMARY_PROMPT, merge_call
from real_dates import RELATIVE

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
SPOKEN = [("Claude", "Здравствуйте, это виртуальный ассистент Азиза. Скажите, пожалуйста, это Алекс?"), ("Them", "Да, это я."),
          ("Claude", "Встреча завтра в силе?"), ("Them", "Да, завтра в одиннадцать, в Трамп Тауэр."),
          ("Claude", "Что-нибудь ещё передать?"), ("Them", "Пусть позвонит послезавтра, а документы я отправил вчера. В пятницу приеду сам.")]
STILL_RELATIVE = re.compile("|".join(words for words, _ in RELATIVE), re.IGNORECASE)
BRIEF = CallBrief.from_dict({"goal": "Find out if tomorrow's meeting is still on.", "language": "ru", "name": "Алекс", "confidence": "confirmed", "need_from_them": ["Is the meeting still on?"]})
today = datetime.date.today()
when = f"{today} 13:42"
results = []


def report(name, text):
    leftover = STILL_RELATIVE.findall(text)
    results.append(not leftover)
    print(f"--- {name}\n{text}\n{'STILL RELATIVE: ' + str(leftover) if leftover else 'all real dates'}", flush=True)


for run in range(2):
    brain = cicero.Brain("en", system_prompt=SUMMARY_PROMPT.format(owner="Aziz", limit=SUMMARY_LIMIT))
    raw = []

    def ask(text):
        raw.append("".join(brain.ask(text)))
        return raw[-1]
    notes = ContactNotes("900000099", tempfile.mkdtemp())
    merge_call(notes, SPOKEN, ask, when)
    brain.close()
    print(f"=== run {run + 1}. Model alone left relative words: {STILL_RELATIVE.findall(raw[0])}", flush=True)
    report("notes, as kept", notes.summary)

    sonnet = cicero.Brain("en", system_prompt=BRIEF.observer_prompt("Aziz"), model=OBSERVER_MODEL)
    observer = Observer(lambda text: "".join(sonnet.ask(text)), SPOKEN, "Aziz")
    final = observer.final_report("goodbye", seconds=90)
    sonnet.close()
    results.append(bool(final))
    report("report, as kept", json.dumps(final, ensure_ascii=False) if final else "NO REPORT")
print(f"{sum(results)} of {len(results)} free of relative dates", flush=True)
