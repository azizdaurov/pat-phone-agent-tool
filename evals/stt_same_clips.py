"""Compares every recognizer on the clips Whisper also got (the first 60 per language), so the numbers are like for like,
then shows what each one wrote for the turns of the real calls."""
import glob
import json
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from stt_score import DATA, difference_range, edits, percent_range, wer, words

BEST = {"ru": "gigaam-v3-rnnt", "en": "nemo-parakeet-tdt-0.6b-v2"}
CONDITIONS = ["phone", "phone_babble10"]


def main():
    with open(os.path.join(DATA, "set", "manifest.json"), encoding="utf-8") as f:
        manifest = json.load(f)
    references = {(e["language"], e["condition"], e["id"]): words(e["text"], e["language"]) for e in manifest}
    results = {}
    for path in glob.glob(os.path.join(DATA, "results", "*.jsonl")):
        with open(path, encoding="utf-8") as f:
            results[os.path.basename(path)[:-6]] = [json.loads(line) for line in f]
    for language in ("ru", "en"):
        print(f"\n=== {language}, first 60 clips ===")
        scores = {}
        for engine, rows in results.items():
            for condition in CONDITIONS:
                pairs = {}
                for r in rows:
                    if r["language"] == language and r["condition"] == condition and int(r["id"][2:]) < 60:
                        reference = references[(language, condition, r["id"])]
                        pairs[r["id"]] = (edits(reference, words(r["text"], language)), len(reference))
                if len(pairs) == 60:
                    scores[(engine, condition)] = pairs
        engines = sorted({e for e, _ in scores}, key=lambda e: wer(list(scores[(e, "phone_babble10")].values())))
        for engine in engines:
            cells = []
            for condition in CONDITIONS:
                pairs = scores[(engine, condition)]
                low, high = percent_range(list(pairs.values()))
                cells.append(f"{condition} {wer(list(pairs.values())) * 100:.1f} ({low * 100:.1f}-{high * 100:.1f})")
            taken = [r["took"] for r in results[engine] if r["language"] == language and 2 <= r["seconds"] <= 4
                     and r["condition"] in CONDITIONS]
            against = ""
            if engine != BEST[language] and (BEST[language], "phone") in scores:
                low, high = difference_range(scores[(engine, "phone_babble10")], scores[(BEST[language], "phone_babble10")])
                against = f"; noisy vs {BEST[language]} {low * 100:+.1f} to {high * 100:+.1f}"
            print(f"{engine[:44]:44} {' | '.join(cells)}; 2-4 s clip {statistics.median(taken):.2f} s{against}")
    print("\n=== real call turns ===")
    for entry in manifest:
        if entry["condition"] == "real_call":
            print(entry["id"], "| on the call:", entry.get("heard_on_the_call"))
            for engine, rows in results.items():
                if "whisper" in engine:
                    text = next((r["text"] for r in rows if r["id"] == entry["id"] and r["condition"] == "real_call"), None)
                    print("    ", engine[-22:], "|", text)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
