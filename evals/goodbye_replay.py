"""Replays the 2026-11-02 20:09 ending with real Haiku: its goodbye is cut off and the person asks "а что?"."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
import pat
from call_brief import CallBrief

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
BRIEF = CallBrief.from_dict({"goal": "Узнать, как у человека дела, что он делал сегодня и какие у него планы на завтра, потом попрощаться."})
OPENING = pat.OPENINGS["dial"]["ru"].format(owner="Aziz", owner_ru="Азиза")
TURNS = ["привет привет", "все нормально", "я программировал", "завтра планирую тоже программировать"]
CUT = '[SUPERVISOR-abc123] You were cut off during your last reply. They heard none of it. Say the rest again only if it still matters.'
prompt = BRIEF.haiku_prompt(pat.SYSTEM_PROMPTS["ru"], OPENING, "Aziz", "abc123")
for attempt in range(1, 6):
    brain = pat.Brain("ru", system_prompt=prompt)
    for _ in brain.ask(pat.WARM_UP["ru"]):
        pass
    for line in TURNS:
        last = "".join(brain.ask(line))
    after = "".join(brain.ask(f"{CUT}\nа что?"))
    print(f"#{attempt} before the cut: {last!r}\n   after 'а что?': {after!r}", flush=True)
    brain.close()
