"""The same words in every English voice, to compare by ear. Saves WAVs and times each voice's first audio. No phone."""
import logging
import os
import sys
import threading
import time
import wave

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "app"))
import numpy as np
import pat

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
logging.disable(logging.INFO)
TEXT = ["Hello, this is Aziz's AI assistant.", "Could you tell me, please, is this Rustam?",
        "Thank you. I'm calling to find out what time tomorrow's meeting starts, and where it is."]
# Pocket TTS's built-in voices recorded in English; it also has Italian, Spanish, German, Portuguese and Dutch ones.
pocket_names = ["alba", "anna", "azelma", "bill_boerst", "caro_davy", "charles", "cosette", "eponine", "eve", "fantine", "george",
                "jane", "javert", "jean", "marius", "mary", "michael", "paul", "peter_yearsley", "stuart_bell", "vera"]
folder = os.path.join(HERE, "results", "english_voice_samples")
os.makedirs(folder, exist_ok=True)


def save(name, voice):
    audio = []
    first = None
    for piece in TEXT:
        started = time.perf_counter()
        for chunk in voice.stream(piece, threading.Event()):
            if first is None:
                first = time.perf_counter() - started
            audio.append(chunk)
    joined = np.concatenate(audio)
    with wave.open(os.path.join(folder, f"{name}.wav"), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(voice.sample_rate)
        f.writeframes((np.clip(joined, -1, 1) * 32767).astype(np.int16).tobytes())
    print(f"{name:22s} first audio {first:.2f} s | length {len(joined) / voice.sample_rate:.1f} s", flush=True)


pocket = pat.PocketVoice(pat.TTS_LANGUAGE, pat.TTS_VOICE)
list(pocket.stream("Ready.", threading.Event()))
for name in pocket_names:
    try:
        pocket.voice = pocket.model.get_state_for_audio_prompt(name)
        save(f"pocket_{name}", pocket)
    except Exception as error:
        print(f"pocket_{name}: skipped, {str(error)[:110]}", flush=True)
