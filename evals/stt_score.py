"""Scores saved recognizer output against the hand-written transcripts. Word error rate, with a 95% range from resampling clips.
Usage: stt_score.py [baseline engine for ru] [baseline engine for en]"""
import glob
import json
import os
import random
import re
import statistics
import sys

DATA = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "stt-test-data"))
CONDITIONS = ["recorded", "phone", "phone_babble10", "phone_babble5"]
RESAMPLES = 2000
FILLERS = {"uh", "um", "hmm", "mm", "mhm", "эм", "ээ", "мм", "э", "м"}
sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def _english_number(n):
    ones = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split()
    tens = "x x twenty thirty forty fifty sixty seventy eighty ninety".split()
    if n < 20:
        return ones[n]
    if n < 100:
        return tens[n // 10] + (" " + ones[n % 10] if n % 10 else "")
    if n < 1000:
        return ones[n // 100] + " hundred" + (" " + _english_number(n % 100) if n % 100 else "")
    for size, name in ((10 ** 9, "billion"), (10 ** 6, "million"), (1000, "thousand")):
        if n >= size:
            return _english_number(n // size) + " " + name + (" " + _english_number(n % size) if n % size else "")


def _russian_number(n):
    ones = "ноль один два три четыре пять шесть семь восемь девять десять одиннадцать двенадцать тринадцать четырнадцать пятнадцать шестнадцать семнадцать восемнадцать девятнадцать".split()
    tens = "x x двадцать тридцать сорок пятьдесят шестьдесят семьдесят восемьдесят девяносто".split()
    hundreds = "x сто двести триста четыреста пятьсот шестьсот семьсот восемьсот девятьсот".split()
    if n < 20:
        return ones[n]
    if n < 100:
        return tens[n // 10] + (" " + ones[n % 10] if n % 10 else "")
    if n < 1000:
        return hundreds[n // 100] + (" " + _russian_number(n % 100) if n % 100 else "")
    if n < 10 ** 6:
        return _russian_number(n // 1000) + " тысяч" + (" " + _russian_number(n % 1000) if n % 1000 else "")
    return " ".join(_russian_number(int(digit)) for digit in str(n))


def words(text, language):
    """Same treatment for transcript and output: digits become words, so writing 15 or fifteen isn't an error, and fillers go."""
    say = _english_number if language == "en" else _russian_number
    text = text.lower().replace("ё", "е").replace("<unk>", " ")
    text = re.sub(r"(?<=\d),(?=\d)", "", text)
    text = re.sub(r"(\d+)\.(\d+)", lambda m: f"{m[1]} {'point' if language == 'en' else 'и'} " + " ".join(m[2]), text)
    text = text.replace("%", " percent " if language == "en" else " процентов ")
    text = re.sub(r"\d+", lambda m: " " + say(int(m[0])) + " ", text)
    tokens = re.sub(r"[^\w\s']", " ", text).replace("_", " ").split()
    return [word for word in tokens if word not in FILLERS]


def edits(reference, heard):
    previous = list(range(len(heard) + 1))
    for i, word in enumerate(reference, 1):
        current = [i]
        for j, other in enumerate(heard, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (word != other)))
        previous = current
    return previous[-1]


def wer(pairs):
    return sum(e for e, _ in pairs) / max(1, sum(n for _, n in pairs))


def percent_range(pairs, seed=1):
    rng = random.Random(seed)
    rates = sorted(wer(rng.choices(pairs, k=len(pairs))) for _ in range(RESAMPLES))
    return rates[int(RESAMPLES * 0.025)], rates[int(RESAMPLES * 0.975)]


def difference_range(a, b, seed=2):
    rng = random.Random(seed)
    ids = sorted(set(a) & set(b))
    rates = []
    for _ in range(RESAMPLES):
        chosen = rng.choices(ids, k=len(ids))
        rates.append(wer([a[i] for i in chosen]) - wer([b[i] for i in chosen]))
    rates.sort()
    return rates[int(RESAMPLES * 0.025)], rates[int(RESAMPLES * 0.975)]


def main():
    baselines = {"ru": sys.argv[1] if len(sys.argv) > 1 else "gigaam-v3-ctc", "en": sys.argv[2] if len(sys.argv) > 2 else "moonshine"}
    with open(os.path.join(DATA, "set", "manifest.json"), encoding="utf-8") as f:
        references = {(e["language"], e["condition"], e["id"]): words(e["text"], e["language"]) for e in json.load(f)}
    results = {}
    for path in glob.glob(os.path.join(DATA, "results", "*.jsonl")):
        with open(path, encoding="utf-8") as f:
            results[os.path.basename(path)[:-6]] = [json.loads(line) for line in f]
    for language in ("ru", "en"):
        print(f"\n=== {language}: word errors, percent (95% range) ===")
        table = {}
        for engine, rows in results.items():
            for condition in CONDITIONS:
                pairs = {r["id"]: (edits(references[(language, condition, r["id"])], words(r["text"], language)),
                                   len(references[(language, condition, r["id"])]))
                         for r in rows if r["language"] == language and r["condition"] == condition}
                if pairs:
                    table[(engine, condition)] = pairs
        engines = sorted({e for e, _ in table}, key=lambda e: wer(list(table.get((e, "phone_babble10"), {"x": (1, 0)}).values())))
        for engine in engines:
            cells = []
            for condition in CONDITIONS:
                pairs = table.get((engine, condition))
                if not pairs:
                    cells.append(f"{condition}: -")
                    continue
                low, high = percent_range(list(pairs.values()))
                cells.append(f"{condition}: {wer(list(pairs.values())) * 100:.1f} ({low * 100:.1f}-{high * 100:.1f}) n={len(pairs)}")
            rows = [r for r in results[engine] if r["language"] == language]
            short = sorted(r["took"] for r in rows if 2 <= r["seconds"] <= 4 and r["condition"] != "babble_only")
            speed = sum(r["took"] for r in rows) / max(1e-9, sum(r["seconds"] for r in rows))
            invented = [len(words(r["text"], language)) for r in rows if r["condition"] == "babble_only"]
            print(f"{engine:34} " + " | ".join(cells))
            print(f"{'':34} 2-4 s clip: median {statistics.median(short) if short else 0:.2f} s; time/audio {speed:.3f}; "
                  f"words invented from babble alone: {sum(invented) / max(1, len(invented)):.1f} per clip")
        base = baselines[language]
        if any(e == base for e, _ in table):
            print(f"\nCompared with {base} (minus = fewer errors; a range that includes 0 is not a clear difference):")
            for engine in engines:
                if engine == base:
                    continue
                parts = []
                for condition in CONDITIONS:
                    a, b = table.get((engine, condition)), table.get((base, condition))
                    if a and b:
                        low, high = difference_range(a, b)
                        parts.append(f"{condition} {low * 100:+.1f} to {high * 100:+.1f}")
                print(f"  {engine:32} " + "; ".join(parts))


if __name__ == "__main__":
    main()
