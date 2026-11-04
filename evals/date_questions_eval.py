"""Does real Claude pin down vague dates and times on a call, lightly, and leave alone the ones that don't need it? Text only, no phone.
Usage: date_questions_eval.py [runs]   The dates in the checks assume it's run on 3-11-2026."""
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import cicero
from call_brief import CallBrief
from observer import OBSERVER_MODEL, Observer, parse_advice

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
RUNS = int(sys.argv[1]) if len(sys.argv) > 1 else 3
ASKS_MORE = r"какого числа|как(ой|ого|ая|ую) (день|числ|дат)|утра или|вечера или|дня или|уточни|which day|what day|what date|morning or|evening or|am or|pm or|which monday"
ASKS_WHICH = r"утра или|вечера или|дня или|или утр|или вечер|или дн|morning or|evening or|afternoon or|am or|a\.m\. or|pm or|p\.m\. or|or in the (morning|evening|afternoon)|or (morning|evening|afternoon)"
MEETING = {"ru": {"goal": "Узнать, когда встреча.", "need_from_them": ["Когда встреча?"]}, "en": {"goal": "Find out when the meeting is.", "need_from_them": ["When is the meeting?"]}}
PRICE = {"ru": {"goal": "Узнать цену осмотра.", "need_from_them": ["Сколько стоит осмотр?", "Нужна ли запись?"]}, "en": {"goal": "Find out the price of a check-up.", "need_from_them": ["How much is a check-up?", "Do I need to book?"]}}
HOURS = {"ru": {"goal": "Узнать, работают ли они в это воскресенье, 8 ноября.", "need_from_them": ["Вы работаете в это воскресенье?"]}, "en": {"goal": "Find out if they're open this Sunday, 8 November.", "need_from_them": ["Are you open this Sunday?"]}}

# name, brief, language, what they say in turn, kind, what the last reply must show
SHOULD_PIN = "should pin down"
SHOULD_LEAVE = "should leave alone"
CASES = [
    ("a weekday: says the real date back", MEETING, "ru", ["Да, слушаю.", "В пятницу."], SHOULD_PIN, r"шест|\b6\b"),
    ("a weekday, English", MEETING, "en", ["Yes, hello.", "On Friday."], SHOULD_PIN, r"\b6(th)?\b|sixth"),
    ("an hour with no morning or evening", MEETING, "ru", ["Да, слушаю.", "В пятницу в пять."], SHOULD_PIN, ASKS_WHICH),
    ("an hour with no morning or evening, English", MEETING, "en", ["Yes, hello.", "Friday at five."], SHOULD_PIN, ASKS_WHICH),
    ("only next week", MEETING, "ru", ["Да, слушаю.", "На следующей неделе."], SHOULD_PIN, r"\?|уточни"),
    ("only next week, English", MEETING, "en", ["Yes, hello.", "Sometime next week."], SHOULD_PIN, r"\?"),
    ("already clear", MEETING, "ru", ["Да, слушаю.", "Завтра в одиннадцать утра."], SHOULD_LEAVE, ASKS_MORE),
    ("already clear, English", MEETING, "en", ["Yes, hello.", "Tomorrow at eleven in the morning."], SHOULD_LEAVE, ASKS_MORE),
    ("the hour settles it", MEETING, "ru", ["Да, слушаю.", "В пятницу в семнадцать ноль-ноль."], SHOULD_LEAVE, ASKS_MORE + "|" + ASKS_WHICH),
    ("the hour settles it, English", MEETING, "en", ["Yes, hello.", "Friday at 9 p.m."], SHOULD_LEAVE, ASKS_MORE + "|" + ASKS_WHICH),
    ("mentioned in passing", PRICE, "ru", ["Да, слушаю.", "В прошлый понедельник было дороже, а сейчас сто тысяч."], SHOULD_LEAVE, r"понедельник.*\?|" + ASKS_MORE),
    ("mentioned in passing, English", PRICE, "en", ["Yes, hello.", "It was more last Monday, but now it's a hundred dollars."], SHOULD_LEAVE, r"monday.*\?|" + ASKS_MORE),
    ("a date the brief already names", HOURS, "ru", ["Да, слушаю.", "Да, в воскресенье работаем."], SHOULD_LEAVE, ASKS_MORE),
    ("they don't know, and say so", MEETING, "ru", ["Да, слушаю.", "На следующей неделе.", "Пока не знаю, ещё не решили."], SHOULD_LEAVE, ASKS_MORE),
    ("they don't know, English", MEETING, "en", ["Yes, hello.", "Sometime next week.", "I don't know yet, it isn't decided."], SHOULD_LEAVE, ASKS_MORE),
]
OWNER_NAMES = {"ru": "Aziz"}


def run_case(brief_fields, language, lines):
    brief = CallBrief.from_dict({**brief_fields[language], "language": language})
    opening = cicero.OPENINGS["dial"][language].format(owner="Aziz", owner_ru="Азиза")
    brain = cicero.Brain(language, system_prompt=brief.haiku_prompt(cicero.SYSTEM_PROMPTS[language], opening, "Aziz", "abc123"))
    replies = []
    for line in lines:
        replies.append("".join(brain.ask(line)).replace(cicero.END_MARK, "").strip())
    brain.close()
    return replies


score = {SHOULD_PIN: [0, 0], SHOULD_LEAVE: [0, 0]}
for name, brief, language, lines, kind, pattern in CASES:
    print(f"=== {name} ({kind})", flush=True)
    for run in range(RUNS):
        reply = run_case(brief, language, lines)[-1]
        found = bool(re.search(pattern, reply.lower(), re.S))
        passed = found if kind == SHOULD_PIN else not found
        score[kind][0] += passed
        score[kind][1] += 1
        print(f"   {'ok ' if passed else 'NO '} {lines[-1]} -> {reply}", flush=True)
for kind, (passed, total) in score.items():
    print(f"{kind}: {passed} of {total}", flush=True)

# Sonnet: steps in only when something that matters was left vague.
BRIEF = CallBrief.from_dict({**MEETING["en"], "language": "en"})
SONNET_CASES = [
    ("left vague and about to finish", True, [("Claude", "When is the meeting?"), ("Them", "Sometime next week."), ("Claude", "Thank you, I'll pass that on. Goodbye.")]),
    ("Haiku is already asking", False, [("Claude", "When is the meeting?"), ("Them", "Next week."), ("Claude", "Which day next week?")]),
    ("clear date", False, [("Claude", "When is the meeting?"), ("Them", "Friday at eleven in the morning."), ("Claude", "Friday the 6th at 11 in the morning?"), ("Them", "Yes.")]),
    ("hour left open and about to finish", True, [("Claude", "When is the meeting?"), ("Them", "Friday at five."), ("Claude", "Thank you, I'll pass that on. Goodbye.")]),
    ("they said they don't know", False, [("Claude", "When is the meeting?"), ("Them", "Next week."), ("Claude", "Which day?"), ("Them", "I don't know yet."), ("Claude", "All right, thank you.")]),
]
right = 0
for name, should_act, lines in SONNET_CASES:
    for run in range(RUNS):
        sonnet = cicero.Brain("en", system_prompt=BRIEF.observer_prompt("Aziz"), model=OBSERVER_MODEL)
        advice = parse_advice("".join(sonnet.ask("\n".join(f"{who}: {text}" for who, text in lines))))
        sonnet.close()
        acted = advice["action"] != "none"
        right += acted == should_act
        print(f"   {'ok ' if acted == should_act else 'NO '} Sonnet, {name}: {advice['action']} {advice['note'][:110]}", flush=True)
print(f"Sonnet right: {right} of {RUNS * len(SONNET_CASES)}", flush=True)

# The report: what stayed vague must stay vague, and not be marked confirmed.
vague = [("Claude", "When is the meeting?"), ("Them", "Sometime next week."), ("Claude", "Which day?"), ("Them", "I don't know yet."), ("Claude", "All right, thank you. Goodbye.")]
for run in range(RUNS):
    sonnet = cicero.Brain("en", system_prompt=BRIEF.observer_prompt("Aziz"), model=OBSERVER_MODEL)
    report = Observer(lambda text: "".join(sonnet.ask(text)), vague, "Aziz").final_report("goodbye", seconds=90)
    sonnet.close()
    print("   report:", json.dumps(report, ensure_ascii=False)[:360], flush=True)
