"""How clearly does each wording say it's an AI? Speaks each with Piper, times it, runs it through the recognizer, and saves a WAV to listen to."""
import logging
import os
import sys
import threading
import wave

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import numpy as np
import cicero

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
logging.disable(logging.INFO)
ASK = "Скажите, пожалуйста, это Рустам?"
OPENINGS = {
    "ii_hyphen": f"Здравствуйте, это ИИ-ассистент Азиза. {ASK}",
    "ii_spaced": f"Здравствуйте, это И И ассистент Азиза. {ASK}",
    "ii_words": f"Здравствуйте, это и-и ассистент Азиза. {ASK}",
    "ai_latin": f"Здравствуйте, это эй-ай ассистент Азиза. {ASK}",
    "virtual": f"Здравствуйте, это виртуальный ассистент Азиза. {ASK}",
    "robot": f"Здравствуйте, это робот-ассистент Азиза. {ASK}",
    "full": f"Здравствуйте, это ассистент Азиза, искусственный интеллект. {ASK}",
}
folder = os.path.join(HERE, "results", "opening_samples")
os.makedirs(folder, exist_ok=True)
ear = cicero.BatchEar(cicero.RU_STT_MODEL, mic=False)
for voice_name in ("irina", "ruslan"):
    voice = cicero.PiperVoice(voice_name)
    print(f"--- {voice_name}")
    for name, text in OPENINGS.items():
        audio = np.concatenate(list(voice.stream(text, threading.Event())))
        heard = ear.model.recognize(cicero.to_16k(audio, 1, voice.sample_rate), sample_rate=cicero.MIC_RATE)
        print(f"{name:10s} {len(audio) / voice.sample_rate:.1f} s | {heard}", flush=True)
        with wave.open(os.path.join(folder, f"{voice_name}_{name}.wav"), "wb") as f:
            f.setnchannels(1)
            f.setsampwidth(2)
            f.setframerate(voice.sample_rate)
            f.writeframes((np.clip(audio, -1, 1) * 32767).astype(np.int16).tobytes())
