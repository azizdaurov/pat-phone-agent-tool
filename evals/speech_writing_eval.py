"""How does Haiku write its lines for speech? The same calls on two models, scored for what reads badly aloud. Text only, no phone.
Usage: speech_writing_eval.py [runs] [model ...]   Defaults: 2 runs, claude-haiku-4-5 and claude-haiku-5-5."""
import os
import re
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
import pat
from call_brief import END_MARK, REACHED_MARKS, CallBrief

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
RUNS = int(sys.argv[1]) if len(sys.argv) > 1 else 2
MODELS = sys.argv[2:] or ["claude-haiku-4-5", "claude-haiku-5-5"]
TABLE = {"en": {"goal": "Book a table for four at 8 pm on Friday, 6-11-2026, under the name Aziz, and ask what they recommend.",
                "need_from_them": ["Is a table for four free at 8 pm on Friday?", "What do they recommend?"]},
         "ru": {"goal": "Забронировать столик на четверых на пятницу, 6-11-2026, в 20:00 на имя Азиз, и узнать, что они советуют.",
                "need_from_them": ["Есть ли столик на четверых в пятницу в 20:00?", "Что они советуют?"]}}
PRICE = {"ru": {"goal": "Узнать цену чистки зубов и есть ли свободное время на этой неделе.",
                "need_from_them": ["Сколько стоит чистка?", "Когда есть свободное время?"]},
         "en": {"goal": "Find out the price of a dental cleaning and whether they have a free slot this week.",
                "need_from_them": ["How much is a cleaning?", "When is a free slot?"]}}
CASES = [
    ("table", TABLE, "en", ["Hello, Bella Cucina, how can I help?", "Yes, we have a table for four on Friday at eight.",
                            "Done, it's booked under Aziz. We recommend the grilled sea bass.", "You're welcome, bye!"]),
    ("table", TABLE, "ru", ["Алло, ресторан Белла, слушаю.", "Да, на пятницу в восемь вечера столик на четверых есть.",
                            "Записала на Азиза. Советую сибаса на гриле.", "Пожалуйста, до свидания!"]),
    ("price", PRICE, "ru", ["Да, клиника, слушаю.", "Чистка стоит 350 тысяч сумов.", "В четверг в 14:30 есть окно.", "Хорошо, всего доброго."]),
    ("price", PRICE, "en", ["Yes, dental clinic.", "A cleaning is $120.", "Thursday at 2:30 pm is free.", "Okay, take care."]),
]
CHECKS = {
    "a year said": lambda s, ru: bool(re.search(r"\b20\d\d\b|две тысячи", s, re.I)),
    "raw date format": lambda s, ru: bool(re.search(r"\b\d{1,4}[-/.]\d{1,2}[-/.]\d{2,4}\b", s)),
    "markdown or list": lambda s, ru: bool(re.search(r"[*_#`]|^\s*[-•]\s|\n", s)),
    "brackets or marks left": lambda s, ru: bool(re.search(r"[\[\]{}<>]", s)),
    "parentheses, slash, &": lambda s, ru: bool(re.search(r"[()/&]", s)),
    "emoji": lambda s, ru: bool(re.search(r"[\U0001F300-\U0001FAFF☀-➿]", s)),
    "digits in Russian": lambda s, ru: ru and bool(re.search(r"\d", s)),
    "Latin in Russian": lambda s, ru: ru and bool(re.search(r"[A-Za-z]{2,}", s)),
    "long sentence": lambda s, ru: any(len(part.split()) > (14 if ru else 22) for part in re.split(r"(?<=[.!?])\s+", s)),
}


def run(model, brief_fields, language, lines):
    brief = CallBrief.from_dict({**brief_fields[language], "language": language})
    opening = pat.OPENINGS["dial"][language].format(owner="Aziz", owner_ru="Азиза")
    brain = pat.Brain(language, system_prompt=brief.haiku_prompt(pat.SYSTEM_PROMPTS[language], opening, "Aziz", "abc123"), model=model)
    turns = []
    for line in lines:
        started = time.monotonic()
        first = None
        text = ""
        for delta in brain.ask(line):
            if first is None and delta.strip():
                first = time.monotonic() - started
            text += delta
        turns.append((line, text, first))
    brain.close()
    return turns


found = {model: {label: 0 for label in CHECKS} for model in MODELS}
ended = {model: [0, 0] for model in MODELS}
waits = {model: [] for model in MODELS}
replies = {model: 0 for model in MODELS}
for name, brief, language, lines in CASES:
    for model in MODELS:
        for attempt in range(RUNS):
            print(f"=== {name} {language} {model} run {attempt + 1}", flush=True)
            turns = run(model, brief, language, lines)
            for line, text, first in turns:
                said = text
                for mark in (*REACHED_MARKS, END_MARK):
                    said = said.replace(mark, " ")
                said = re.sub(r"\s+", " ", said).strip()
                hits = [label for label, check in CHECKS.items() if check(text if label == "markdown or list" else said, language == "ru")]
                for label in hits:
                    found[model][label] += 1
                replies[model] += 1
                if first is not None:
                    waits[model].append(first)
                print(f"   them: {line}\n   pat:  {text.strip()}" + (f"\n         ^ {', '.join(hits)}" if hits else ""), flush=True)
            ended[model][0] += END_MARK in turns[-1][1]
            ended[model][1] += 1

print("\n=== totals, replies with each problem")
for model in MODELS:
    middle = sorted(waits[model])[len(waits[model]) // 2] if waits[model] else 0
    print(f"{model}: {replies[model]} replies, median first text {middle:.2f} s, ended with {END_MARK} on the goodbye {ended[model][0]} of {ended[model][1]}")
    for label, count in found[model].items():
        print(f"   {label}: {count}")
