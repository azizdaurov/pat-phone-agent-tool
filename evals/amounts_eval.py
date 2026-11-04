"""Does real Claude keep amounts as said, with no currency added and none asked about? On the call, in the report, in the notes and on the sticky note. Text only, no phone.
Usage: amounts_eval.py [runs]"""
import os
import re
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import cicero
import live_notes
from call_brief import CallBrief
from observer import OBSERVER_MODEL, Observer
from phone_memory import ContactNotes, SUMMARY_LIMIT, SUMMARY_PROMPT, merge_call

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
RUNS = int(sys.argv[1]) if len(sys.argv) > 1 else 3
CURRENCY = r"рубл|руб\b|сум|доллар|тенге|евро|dollar|ruble|rouble|\bsum\b|\bsom\b|euro|tenge|\$|usd|uzs"
ASKED = r"валют|currency"
BRIEFS = {"ru": {"goal": "Узнать цену осмотра.", "need_from_them": ["Сколько стоит осмотр?", "Нужна ли запись?"]},
          "en": {"goal": "Find out the price of a check-up.", "need_from_them": ["How much is a check-up?", "Do I need to book?"]}}
CALLS = {"ru": [("Claude", "Сколько стоит осмотр?"), ("Them", "Сто тысяч."), ("Claude", "Сто тысяч, верно? Нужна ли запись?"), ("Them", "Да, сто тысяч. Запись не нужна."), ("Claude", "Спасибо, до свидания.")],
         "en": [("Claude", "How much is a check-up?"), ("Them", "A hundred."), ("Claude", "A hundred, is that right? Do I need to book?"), ("Them", "Yes, a hundred. No booking needed."), ("Claude", "Thank you, goodbye.")]}
score = {}


def mark(name, passed, text):
    done, total = score.get(name, (0, 0))
    score[name] = (done + passed, total + 1)
    print(f"   {'ok ' if passed else 'NO '} {name}: {text[:210]}", flush=True)


for language, lines in (("ru", ["Да, слушаю.", "Сто тысяч."]), ("en", ["Yes, hello.", "A hundred."])):
    brief = CallBrief.from_dict({**BRIEFS[language], "language": language})
    opening = cicero.OPENINGS["dial"][language].format(owner="Aziz", owner_ru="Азиза")
    for run in range(RUNS):
        brain = cicero.Brain(language, system_prompt=brief.haiku_prompt(cicero.SYSTEM_PROMPTS[language], opening, "Aziz", "abc123"))
        replies = ["".join(brain.ask(line)) for line in lines]
        brain.close()
        reply = replies[-1].lower()
        mark(f"on the call, {language}: no currency added or asked", not re.search(CURRENCY + "|" + ASKED, reply), replies[-1])

    for run in range(RUNS):
        sonnet = cicero.Brain("en", system_prompt=brief.observer_prompt("Aziz"), model=OBSERVER_MODEL)
        report = Observer(lambda text: "".join(sonnet.ask(text)), CALLS[language], "Aziz").final_report("goodbye", seconds=90)
        sonnet.close()
        text = str(report)
        mark(f"report, {language}: just the number", bool(report) and not re.search(CURRENCY, text.lower()), text)

    for run in range(RUNS):
        brain = cicero.Brain("en", system_prompt=SUMMARY_PROMPT.format(owner="Aziz", limit=SUMMARY_LIMIT))
        notes = ContactNotes("900000098", tempfile.mkdtemp())
        merge_call(notes, CALLS[language], lambda text: "".join(brain.ask(text)), "2026-11-03 13:42")
        brain.close()
        mark(f"notes, {language}: just the number", bool(notes.summary) and not re.search(CURRENCY, notes.summary.lower()), notes.summary)

    for run in range(RUNS):
        brain = cicero.Brain("en", system_prompt=live_notes.NOTES_PROMPT)
        note = live_notes.LiveNotes(lambda text: "".join(brain.ask(text)), BRIEFS[language]["need_from_them"])
        note.request(CALLS[language])
        deadline = time.time() + 30
        while not note.facts and time.time() < deadline:
            time.sleep(0.05)
        note.close()
        brain.close()
        text = str(note.facts)
        mark(f"sticky note, {language}: just the number", bool(note.facts) and not re.search(CURRENCY, text.lower()), text)
for name, (done, total) in score.items():
    print(f"{name}: {done} of {total}", flush=True)
