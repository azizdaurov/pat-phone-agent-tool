"""After Sonnet corrects Haiku, does the call carry on smoothly, with no sorry and no explaining? Text only, no phone.

Part 1: Sonnet reads three made-up calls where Haiku went wrong, with the supervisor prompt before and after the change, and
writes its note. Part 2: Haiku gets that note the way Pat sends it after a correction (cut off, a stall phrase, then the note),
with the wording before and after the change, and says its next line.
Before = old prompt, old wording, old stall phrases (two of them said sorry). After = what Pat has now.
Haiku can't be given its earlier lines word for word, so it reaches the moment by talking through the same caller lines; its
own lines may differ from the ones Sonnet read.

Usage: .venv\\Scripts\\python.exe evals\\correction_steer_eval.py [runs per call, default 3] [after]"""
import os
import random
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
import pat  # noqa: E402
from call_brief import ASK_MARK, CONFIRMED_MARK, OBSERVER_PROMPT, CallBrief, caller_id_message  # noqa: E402
from observer import OBSERVER_MODEL, parse_advice  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
RUNS = int(sys.argv[1]) if len(sys.argv) > 1 else 3
OWNER, NONCE = "Aziz", "abc123"
NEW_RULE = OBSERVER_PROMPT.split("in English, one or two sentences, ", 1)[1].split(" To end the call", 1)[0]
OLD_RULE = "saying what to do next."
AFTER_ONLY = "after" in sys.argv[2:]  # the before side doesn't change, so it needn't be run again
OLD_STALLS = {"en": pat.STALLS["en"] + ["Sorry, one moment."], "ru": pat.STALLS["ru"] + ["Извините, одну секунду."]}
SORRY = re.compile(r"sorry|apolog|mistake|my bad|i was wrong|misspoke|correct myself|let me correct|"
                   r"извин|прост(и|ите)|прошу прощ|ошиб|виноват|поправлю", re.I)
NOTE_ASKS_SORRY = re.compile(r"apolog|sorry|admit|you were wrong|were wrong|mistake|retract|извин|прост(и|ите)\b|прошу прощ", re.I)


def opening(kind, language):
    return pat.OPENINGS[kind][language].format(owner=OWNER, owner_ru="Азиза")


CALLS = [
    dict(name="invented name (Pat answered, Russian)", language="ru",
         brief=CallBrief.from_dict({"goal": pat.DEFAULT_ANSWER_GOAL, "language": "ru", "incoming": True}),
         caller_id="Алекс",  # so Haiku really says the name it is then corrected on
         seen=[("Claude", opening("answer", "ru")),
               ("Them", "Алло, привет. Слушай, Азиз сегодня вечером свободен?"),
               ("Claude", "Здравствуйте, Алекс! Азиз сейчас не может подойти. Передать ему, что вы звонили насчёт вечера?"),
               ("Them", "Да, передай."),
               ("Claude", "Спасибо за звонок, Алекс! Азиз услышит твой вопрос.")],
         lines=["Алло, привет. Слушай, Азиз сегодня вечером свободен?", "Да, передай."]),
    dict(name="booked against a limit (outgoing, English)", language="en",
         brief=CallBrief.from_dict({"goal": "Find out whether Example Dental is open this Sunday and until what time.",
                                    "need_from_them": ["Are you open this Sunday?", "Until what time?"],
                                    "may_share": ["Aziz is thinking of coming in for a check-up"],
                                    "must_not": ["Don't book an appointment"],
                                    "company": "Example Dental", "confidence": "confirmed"}),
         seen=[("Claude", opening("dial", "en") + " Could you tell me, please, is this Example Dental?"),
               ("Them", "Yes, Example Dental, how can I help?"),
               ("Status", "person confirmed; the task starts now"),
               ("Claude", "Great. I'm calling to ask whether you're open this Sunday, and until what time?"),
               ("Them", "We're open Sunday ten to two. Shall I put him down for eleven?"),
               ("Claude", "Yes, please book him for eleven, he'll be there.")],
         lines=["Yes, Example Dental, how can I help?", "We're open Sunday ten to two. Shall I put him down for eleven?"]),
    dict(name="shared a private detail (outgoing, English)", language="en",
         brief=CallBrief.from_dict({"goal": "Find out whether Example Pharmacy has ibuprofen in stock today.",
                                    "need_from_them": ["Do you have ibuprofen in stock today?"],
                                    "may_share": ["Aziz wants to pick it up today"],
                                    "company": "Example Pharmacy", "confidence": "confirmed"}),
         seen=[("Claude", opening("dial", "en") + " Could you tell me, please, is this Example Pharmacy?"),
               ("Them", "Yes, Example Pharmacy."),
               ("Status", "person confirmed; the task starts now"),
               ("Claude", "Thanks. Do you have ibuprofen in stock today?"),
               ("Them", "We should. What's it for, if you don't mind me asking?"),
               ("Claude", "It's for Aziz, he's had a bad toothache since Monday and needs a root canal.")],
         lines=["Yes, Example Pharmacy.", "We should. What's it for, if you don't mind me asking?"]),
]


def sonnet_note(call, rule):
    prompt = call["brief"].observer_prompt(OWNER)
    assert NEW_RULE in prompt, "the supervisor prompt changed: update NEW_RULE"
    prompt = prompt.replace(NEW_RULE, rule)
    sonnet = pat.Brain("en", system_prompt=prompt, model=OBSERVER_MODEL)
    try:
        return parse_advice("".join(sonnet.ask("\n".join(f"{who}: {text}" for who, text in call["seen"]))))
    finally:
        sonnet.close()


def haiku_next_line(call, note, after):
    brief, language = call["brief"], call["language"]
    kind = "answer" if brief.incoming else "dial"
    brain = pat.Brain(language, system_prompt=brief.haiku_prompt(pat.SYSTEM_PROMPTS[language], opening(kind, language), OWNER, NONCE))
    try:
        "".join(brain.ask(f"[SUPERVISOR-{NONCE}] {pat.WARM_UP[language]}"))
        if call.get("caller_id"):
            "".join(brain.ask(caller_id_message(call["caller_id"], NONCE)))
        reply = ""
        for line in call["lines"]:
            reply = "".join(brain.ask(line))
            if CONFIRMED_MARK in reply:
                reply = "".join(brain.ask(f"[SUPERVISOR-{NONCE}] {brief.task_message(OWNER)}"))
        said = re.sub(r"\[[A-Z]+\]", "", reply).strip()
        heard = re.split(r"(?<=[.!?])\s", said)[0]  # they talked over it, or Sonnet cut it, after the first sentence
        phrase = random.choice(pat.STALLS[language] if after else OLD_STALLS[language])
        message = f'[SUPERVISOR-{NONCE}] You just said "{phrase}" to them. {note} Say your next line now, with no {ASK_MARK}.'
        if after:
            message += f" {pat.CARRY_ON}"
        cut = f"[SUPERVISOR-{NONCE}] {pat.cut_message(heard)}"
        return said, phrase, re.sub(r"\[[A-Z]+\]", "", "".join(brain.ask(f"{cut}\n{message}"))).strip()
    finally:
        brain.close()


tally = {}
for call in CALLS:
    for run in range(RUNS):
        for label, rule, after in (("after", NEW_RULE, True),) if AFTER_ONLY else (("before", OLD_RULE, False), ("after", NEW_RULE, True)):
            advice = sonnet_note(call, rule)
            s = tally.setdefault(label, {"notes": 0, "note_asks_sorry": 0, "lines": 0, "stall_sorry": 0, "line_sorry": 0, "not_correct": 0})
            print(f"\n=== {call['name']} | run {run + 1} | {label}", flush=True)
            print(f"  Sonnet {advice['action']} ({advice['reason']}): {advice['note']}", flush=True)
            if advice["action"] != "correct":
                s["not_correct"] += 1
                if advice["action"] == "none":
                    continue
            s["notes"] += 1
            s["note_asks_sorry"] += bool(NOTE_ASKS_SORRY.search(advice["note"]))
            said, phrase, line = haiku_next_line(call, advice["note"], after)
            s["lines"] += 1
            s["stall_sorry"] += bool(SORRY.search(phrase))
            s["line_sorry"] += bool(SORRY.search(line))
            print(f"  Haiku had said: {said}\n  stall: {phrase}\n  next line: {line}{'   <- SORRY / EXPLAINS' if SORRY.search(line) else ''}", flush=True)

print("\n=== totals")
for label, s in tally.items():
    print(f"{label}: {s['notes']} notes, {s['not_correct']} not 'correct'; {s['note_asks_sorry']} notes ask for a sorry or an admission; "
          f"{s['lines']} Haiku lines: {s['stall_sorry']} stalls with sorry, {s['line_sorry']} next lines that say sorry or mention a mistake")
