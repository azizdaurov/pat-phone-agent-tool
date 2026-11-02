"""Cuts each heard turn out of the saved real calls, adds them to the test manifest as condition real_call, and prints
what share of each call's sound energy lies above 3400 Hz, to check the phone line simulation against the real thing."""
import json
import os
import re

import numpy as np
import soundfile as sf

HERE = os.path.dirname(os.path.abspath(__file__))
CALLS = os.path.join(HERE, "..", "calls")
DATA = os.path.abspath(os.path.join(HERE, "..", "..", "stt-test-data"))
RATE = 16000
PAD_BEFORE, PAD_AFTER = 0.4, 0.3


def band_shares(audio):
    spectrum = np.abs(np.fft.rfft(audio)) ** 2
    freqs = np.fft.rfftfreq(len(audio), 1 / RATE)
    total = spectrum.sum() or 1
    return {band: round(float(spectrum[(freqs >= band[0]) & (freqs < band[1])].sum() / total) * 100, 2)
            for band in ((0, 300), (300, 3400), (3400, 4000), (4000, 8000))}


def main():
    entries = []
    for name in sorted(os.listdir(CALLS)):
        if not name.endswith(".wav"):
            continue
        audio, _ = sf.read(os.path.join(CALLS, name), dtype="float32")
        if not np.any(audio):
            print(name, "silent, skipped")
            continue
        with open(os.path.join(CALLS, name[:-4] + ".txt"), encoding="utf-8") as f:
            text = f.read()
        language = "en" if re.search(r"^language: en", text, re.M) else "ru"
        print(name, language, "share of energy by band (Hz):", band_shares(audio))
        turns = re.findall(r"speech started, ([\d.]+) s into the call\n(?:.*\n)*?.*speech ended after ([\d.]+) s\n(?:\S+ Them: (.*))?", text)
        folder = os.path.join(DATA, "set", "real", name[:-4])
        os.makedirs(folder, exist_ok=True)
        for number, (start, length, heard) in enumerate(turns):
            first = max(0, int((float(start) - PAD_BEFORE) * RATE))
            last = int((float(start) + float(length) + PAD_AFTER) * RATE)
            clip = audio[first:last]
            if len(clip) < RATE // 4:
                continue
            path = os.path.join(folder, f"{number:02d}.wav")
            sf.write(path, clip, RATE, subtype="PCM_16")
            entries.append({"id": f"{name[:-4]}-{number:02d}", "language": language, "condition": "real_call", "path": path,
                            "text": "", "heard_on_the_call": heard, "seconds": round(len(clip) / RATE, 2)})
    manifest = os.path.join(DATA, "set", "manifest.json")
    with open(manifest, encoding="utf-8") as f:
        kept = [e for e in json.load(f) if e["condition"] != "real_call"]
    with open(manifest, "w", encoding="utf-8") as f:
        json.dump(kept + entries, f, ensure_ascii=False, indent=0)
    print(len(entries), "real turns")


if __name__ == "__main__":
    main()
