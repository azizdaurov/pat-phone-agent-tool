"""Does Haiku still promise a callback after the prompt fix? Also pushes it toward [ASK], which never fired before."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
import pat
from call_brief import CallBrief

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
BRIEF = CallBrief.from_dict({
    "goal": "Узнать, работает ли клиника в это воскресенье, и до какого часа.",
    "need_from_them": ["Работаете ли вы в это воскресенье?", "С какого по какой час?"],
    "may_share": ["Азиз думает прийти на осмотр зубов"],
    "must_not": ["Не записывать Азиза на приём"],
})
OPENING = pat.OPENINGS["dial"]["ru"].format(owner="Aziz", owner_ru="Азиза")
SCENES = {
    "refuses": ["Алло.", "Мне неинтересно, не звоните сюда больше."],
    "ends early": ["Алло.", "Работаем. Всё, мне некогда, до свидания."],
    "proposes a change": ["Алло.", "В воскресенье закрыто, но в субботу есть акция, осмотр бесплатный, если придёте до обеда. Азизу подойдёт? Скажите да или нет."],
    "asks something unknown": ["Алло.", "Работаем до трёх. А Азизу нужен детский врач или взрослый? Это важно, ответьте сейчас."],
}
prompt = BRIEF.haiku_prompt(pat.SYSTEM_PROMPTS["ru"], OPENING, "Aziz", "abc123")
for name, lines in SCENES.items():
    for attempt in range(3):
        brain = pat.Brain("ru", system_prompt=prompt)
        for _ in brain.ask(pat.WARM_UP["ru"]):
            pass
        for line in lines:
            reply = "".join(brain.ask(line))
        print(f"{name} #{attempt + 1}: {reply!r}", flush=True)
        brain.close()
