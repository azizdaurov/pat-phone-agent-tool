"""How fast do the chosen English voices speak? The cut-off estimate needs a rate no faster than the real one,
or it would claim more was heard than was. Also compares the estimate with a transcription of the audio up to each cut."""
import logging
import os
import sys
import threading

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import numpy as np
import cicero

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
logging.disable(logging.INFO)
VOICES = sys.argv[1:] or ["peter_yearsley", "alba", "bill_boerst", "michael"]
TEXTS = ["Hello, I am calling to find out whether your clinic is open this Sunday and until what time.",
         "Thank you, the check up costs one hundred thousand, and I will pass that on to Aziz this evening.",
         "Could you tell me whether it is possible to come in without making an appointment first?",
         "I understand, you are open from nine in the morning until three in the afternoon, is that right?",
         "Great. And where is the meeting taking place?", "I'm sorry, I didn't catch that. Could you repeat it?"]
CUTS = (0.25, 0.5, 0.75)
ear = cicero.Ear(cicero.STT_ARCH, mic=False)


def transcribe(audio):
    ear.prepare()
    for start in range(0, len(audio), 1024):
        ear.feed_block(audio[start:start + 1024], cicero.MIC_RATE)
    return ear.end(tail=0)


for name in VOICES:
    voice = cicero.PocketVoice(cicero.TTS_LANGUAGE, name)
    rate_guess = cicero.ENGLISH_VOICES[name]["chars_per_second"] if hasattr(cicero, "ENGLISH_VOICES") and name in cicero.ENGLISH_VOICES else None
    rates = []
    ahead = total = 0
    for text in TEXTS * 2:
        audio = np.concatenate(list(voice.stream(text, threading.Event())))
        seconds = len(audio) / voice.sample_rate
        rates.append(len(text) / seconds)
        if rate_guess is None:
            continue
        for cut in CUTS:
            played = seconds * cut
            heard = cicero.heard_text([[text, played, len(text) / rate_guess]])
            actual = transcribe(cicero.to_16k(audio[:int(played * voice.sample_rate)], 1, voice.sample_rate))
            total += 1
            ahead += len(heard.split()) > len(actual.split())
    line = f"{name:16s} {min(rates):.1f}-{max(rates):.1f} characters per second, median {np.median(rates):.1f}"
    if rate_guess:
        line += f" | guess {rate_guess} | estimate ahead of the audio on {ahead}/{total} cuts"
    print(line, flush=True)
