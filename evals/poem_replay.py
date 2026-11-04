"""Real Haiku and Sonnet write all three summary styles from a saved call's report, and the card is drawn with each. No phone.
Usage: poem_replay.py <call id, or nothing for the newest call with a report>"""
import glob
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import cicero
from call_card import render_card
from easter_eggs import POEM_PROMPTS, write_poem

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
calls = os.path.join(HERE, "..", "calls")
paths = [os.path.join(calls, f"{sys.argv[1]}.result.json")] if len(sys.argv) > 1 else sorted(glob.glob(os.path.join(calls, "*.result.json")), reverse=True)
for path in paths:
    with open(path, encoding="utf-8") as f:
        saved = json.load(f)
    if isinstance(saved.get("report"), dict) and saved["report"].get("answers"):
        break
print("Report:", json.dumps(saved["report"], ensure_ascii=False), "\n", flush=True)
for style in POEM_PROMPTS:
    started = time.perf_counter()
    poem = write_poem(style, saved["report"], lambda model: cicero.Brain("en", system_prompt="You write short, funny pieces about phone calls, for the person who asked for the call.", model=model))
    print(f"--- {style}, {time.perf_counter() - started:.1f} s", flush=True)
    print(poem or "(nothing written)", "\n", flush=True)
    if style == "haiku":
        print(render_card({"status": saved["status"], "report": saved["report"], "seconds": saved.get("seconds"), "number": "#1", "poem": poem}), "\n", flush=True)
