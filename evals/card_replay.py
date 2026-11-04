"""Real Sonnet writes the final report for a saved call, using today's prompt, and the card is drawn from it. No phone.
Usage: card_replay.py <call id, such as 20261102-203109-900000001> [runs]"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import pat
from call_brief import CallBrief
from call_card import render_card
from observer import OBSERVER_MODEL, Observer

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
call_id = sys.argv[1]
runs = int(sys.argv[2]) if len(sys.argv) > 2 else 3
calls = os.path.join(HERE, "..", "calls")
with open(os.path.join(calls, f"{call_id}.brief.json"), encoding="utf-8") as f:
    brief = CallBrief.from_dict(json.load(f))
with open(os.path.join(calls, f"{call_id}.result.json"), encoding="utf-8") as f:
    saved = json.load(f)
with open(saved["transcript_file"], encoding="utf-8") as f:
    spoken = [(m[1], m[2]) for m in (re.match(r"\S+ (Claude|Them): (.*)", line) for line in f) if m]
for run in range(runs):
    sonnet = pat.Brain("en", system_prompt=brief.observer_prompt("Aziz"), model=OBSERVER_MODEL)
    report = Observer(lambda text: "".join(sonnet.ask(text)), spoken, "Aziz").final_report(saved["reason"])
    sonnet.close()
    print(render_card({"status": saved["status"], "reason": saved["reason"], "report": report, "seconds": saved.get("seconds"),
                       "number": "+998 90 123 45 67"}), flush=True)
