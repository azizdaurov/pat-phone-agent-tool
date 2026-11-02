"""Does Haiku keep asking until it has the answer? Real Haiku, scripted evasive callers, text only."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import cicero
from call_brief import CallBrief

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
BRIEF = CallBrief.from_dict({
    "goal": "Узнать, во сколько завтра начинается встреча и где она будет.",
    "need_from_them": ["Во сколько начинается встреча?", "Где она будет?"],
    "may_share": ["Азиз хочет прийти на встречу вовремя"],
})
OPENING = cicero.OPENINGS["dial"]["ru"].format(owner="Aziz", owner_ru="Азиза")
SCENES = {
    "vague, then answers": ["Алло.", "Ну, как обычно.", "Ну утром где-то.", "В десять.", "В офисе на Навои.", "Да, верно."],
    "changes the subject": ["Алло.", "А погода сегодня хорошая, правда?", "Я вчера был на рыбалке.", "В два часа.", "Не знаю где, это не я решаю.", "Да, всё."],
    "refuses": ["Алло.", "Не скажу, это не ваше дело."],
}
prompt = BRIEF.haiku_prompt(cicero.SYSTEM_PROMPTS["ru"], OPENING, "Aziz", "abc123")
for name, lines in SCENES.items():
    for attempt in range(1, 3):
        brain = cicero.Brain("ru", system_prompt=prompt)
        for _ in brain.ask(cicero.WARM_UP["ru"]):
            pass
        print(f"=== {name} #{attempt}", flush=True)
        for line in lines:
            reply = "".join(brain.ask(line)).replace("\n", " ")
            print(f"  Them : {line}\n  Haiku: {reply}", flush=True)
            if "[END]" in reply:
                break
        brain.close()
