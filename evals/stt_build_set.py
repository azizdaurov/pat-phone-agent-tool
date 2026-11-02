"""Builds the speech recognition test set in stt-test-data/set. Needs the Open STT archive already downloaded.
Same clips in every condition: as recorded, through a simulated phone line, and with background voices on top.
Usage: stt_build_set.py [clips per language]"""
import csv
import json
import os
import random
import sys
import tarfile
import time
import urllib.error
import urllib.request

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly, sosfilt, butter

DATA = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "stt-test-data"))
RATE = 16000
SEED = 20261102
MIN_SECONDS, MAX_SECONDS = 1.0, 15.0
BABBLE_VOICES = 6
EARNINGS_ROWS = "https://datasets-server.huggingface.co/rows?dataset=distil-whisper/earnings22&config=chunked&split=test&offset={}&length=1"
EARNINGS_TOTAL = 57391


def phone_line(audio):
    """What a narrowband call does: 8 kHz and mu-law, then back to 16 kHz. The band matches the saved real calls,
    which had 24-38% of their energy at 100-300 Hz, at most 0.22% at 3400-4000 Hz and none above 4000 Hz."""
    narrow = sosfilt(butter(6, [100, 3400], "bandpass", fs=RATE, output="sos"), audio)
    low = resample_poly(narrow, 1, 2)
    mu = 255.0
    coded = np.sign(low) * np.log1p(mu * np.minimum(np.abs(low), 1.0)) / np.log1p(mu)
    coded = np.round(coded * 127) / 127
    decoded = np.sign(coded) * ((1 + mu) ** np.abs(coded) - 1) / mu
    return resample_poly(decoded, 2, 1)[:len(audio)].astype(np.float32)


def babble_for(length, others, rng):
    voices = np.zeros(length)
    for _ in range(BABBLE_VOICES):
        layer = np.zeros(0)
        while len(layer) < length:
            layer = np.concatenate([layer, others[rng.randrange(len(others))]])
        voices += layer[:length] / max(float(np.std(layer[:length])), 1e-4)
    return voices


def with_noise(audio, noise, snr_db):
    speech = max(float(np.std(audio)), 1e-4)
    noise = noise * speech / max(float(np.std(noise)), 1e-4) / 10 ** (snr_db / 20)
    mixed = audio + noise
    return (mixed / max(1.0, float(np.abs(mixed).max()) / 0.98)).astype(np.float32)


def load(path):
    audio, rate = sf.read(path, dtype="float32", always_2d=True)
    audio = audio[:, 0]
    return resample_poly(audio, RATE, rate).astype(np.float32) if rate != RATE else audio


def russian_clips(count, rng):
    """Real phone calls with hand-written transcripts."""
    folder = os.path.join(DATA, "open_stt")
    with open(os.path.join(folder, "asr_calls_2_val.csv"), encoding="utf-8") as f:
        rows = [row for row in csv.reader(f) if len(row) >= 3]
    fitting = [row for row in rows if MIN_SECONDS <= float(row[2]) <= MAX_SECONDS]
    rng.shuffle(fitting)
    wanted = {}
    for row in fitting[:count * 2]:
        wanted[row[0].replace("\\", "/")] = row[1].replace("\\", "/")
    found = {}
    # Reads only the wanted members and writes them under flat new names, so archive paths can't choose where files land.
    out = os.path.join(folder, "picked")
    os.makedirs(out, exist_ok=True)
    wanted_names = set(wanted) | set(wanted.values())
    with tarfile.open(os.path.join(folder, "asr_calls_2_val.tar.gz")) as tar:
        for member in tar:
            name = member.name.lstrip("./")
            if name not in wanted_names or not member.isfile():
                continue
            found[name] = tar.extractfile(member).read()
    clips = []
    for audio_name, text_name in wanted.items():
        if audio_name not in found or text_name not in found or len(clips) == count or not found[text_name].strip():
            continue
        path = os.path.join(out, f"ru{len(clips):04d}.wav")
        with open(path, "wb") as f:
            f.write(found[audio_name])
        clips.append({"id": f"ru{len(clips):04d}", "path": path, "text": found[text_name].decode("utf-8").strip()})
    return clips


def fetch(url):
    for attempt in range(6):
        try:
            with urllib.request.urlopen(url, timeout=60) as response:
                return response.read()
        except (urllib.error.URLError, TimeoutError):
            if attempt == 5:
                raise
            time.sleep(5 * (attempt + 1))


def english_clips(count, rng):
    """Real conference calls with hand-written transcripts. One row per request, so only these clips are fetched.
    Each fetched row is kept, so a rerun picks up where it stopped."""
    folder = os.path.join(DATA, "earnings22")
    clips = []
    for offset in rng.sample(range(EARNINGS_TOTAL), count * 2):
        if len(clips) == count:
            break
        path = os.path.join(folder, f"offset{offset}.wav")
        saved = path[:-4] + ".json"
        if not os.path.exists(saved):
            row = json.loads(fetch(EARNINGS_ROWS.format(offset)))["rows"][0]["row"]
            with open(path, "wb") as f:
                f.write(fetch(row["audio"][0]["src"]))
            with open(saved, "w", encoding="utf-8") as f:
                json.dump({"text": row["transcription"], "file": row["file_id"]}, f)
        with open(saved, encoding="utf-8") as f:
            row = json.load(f)
        if MIN_SECONDS <= sf.info(path).duration <= MAX_SECONDS and len(row["text"].split()) >= 2:
            clips.append({"id": f"en{len(clips):04d}", "path": path, "text": row["text"], "file": row["file"]})
    return clips


def build(language, clips, rng):
    audio = {clip["id"]: load(clip["path"]) for clip in clips}
    entries = []
    for clip in clips:
        pure = audio[clip["id"]]
        line = phone_line(pure)
        others = [a for name, a in audio.items() if name != clip["id"]]
        babble = phone_line(babble_for(len(pure), others, rng) / 40)
        for condition, sound in (("recorded", pure), ("phone", line),
                                 ("phone_babble10", with_noise(line, babble, 10)),
                                 ("phone_babble5", with_noise(line, babble, 5)),
                                 ("babble_only", (babble * 0.03 / max(float(np.std(babble)), 1e-4)).astype(np.float32))):
            folder = os.path.join(DATA, "set", language, condition)
            os.makedirs(folder, exist_ok=True)
            path = os.path.join(folder, clip["id"] + ".wav")
            sf.write(path, sound, RATE, subtype="PCM_16")
            entries.append({"id": clip["id"], "language": language, "condition": condition, "path": path,
                            "text": clip["text"], "seconds": round(len(pure) / RATE, 2)})
    return entries


def main():
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 200
    rng = random.Random(SEED)
    entries = build("ru", russian_clips(count, rng), rng) + build("en", english_clips(count, rng), rng)
    with open(os.path.join(DATA, "set", "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=0)
    print(len(entries), "files")


if __name__ == "__main__":
    main()
