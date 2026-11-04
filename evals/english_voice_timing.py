"""What an English reply feels like with each voice, on the real path: real Haiku, the real mouth, playing silently into the cable.
Measures time from "they stopped talking" to first audio, and silence between the phrases of a reply. No phone."""
import logging
import os
import sys
import tempfile
import threading
import time
import types

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import numpy as np
import pat
from call_brief import CallBrief

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
logging.disable(logging.INFO)
BRIEF = CallBrief.from_dict({"goal": "Find out what time tomorrow's meeting starts and where it is.", "language": "en",
                             "need_from_them": ["What time does it start?", "Where is it?", "Is there anything else important?"]})
OPENING = "Hello, this is Aziz's AI assistant."
LINES = ["Hello, yes, who is this?", "Oh, the meeting starts at eleven in the morning.", "Yes, that's right, eleven.",
         "It's at the office on Navoi street, on the third floor.", "Yes, the third floor.", "Please tell him to bring a suit, it's a formal meeting."]


class TimedOut:
    """Passes audio to the cable and records when each block was written."""

    def __init__(self, real):
        self.real = real
        self.times = []

    def write(self, chunk):
        self.times.append(time.perf_counter())
        return self.real.write(chunk)

    def abort(self):
        self.real.abort()

    def start(self):
        self.real.start()


def run(label, voice_name):
    started = time.perf_counter()
    _, mouth = pat.load_speech("en", voice_name)
    print(f"\n=== {label}: loaded in {time.perf_counter() - started:.1f} s", flush=True)
    real = pat.open_cable(mouth.sample_rate)
    real.start()
    mouth.out = TimedOut(real)
    brain = pat.Brain("en", system_prompt=BRIEF.haiku_prompt(pat.SYSTEM_PROMPTS["en"], OPENING, "Aziz", "abc123"))
    for _ in brain.ask(pat.WARM_UP["en"]):
        pass
    call = pat.Conversation(types.SimpleNamespace(ended=threading.Event()), iter(()), None, mouth, brain,
                               pat.Transcript(tempfile.mkdtemp()), OPENING, language="en", nonce="abc123")
    first, gaps, longest = [], [], []
    for line in LINES:
        mouth.out.times = []
        start = time.perf_counter()
        call._turn(line, call.epoch)
        times = mouth.out.times
        if not times:
            continue
        first.append(times[0] - start)
        steps = np.diff(times)
        # Writes come about every 50 ms while playing, so a longer step is silence the listener can hear.
        silences = steps[steps > 0.15] - 0.05
        gaps.append(float(silences.sum()))
        longest.append(float(silences.max()) if len(silences) else 0.0)
        print(f"  first audio {first[-1]:.2f} s, silence inside reply {gaps[-1]:.2f} s", flush=True)
        if call.finished.is_set():
            break
    brain.close()
    real.stop()
    real.close()
    print(f"  == {label}: first audio median {np.median(first):.2f} s, slowest {max(first):.2f} s | "
          f"silence inside a reply median {np.median(gaps):.2f} s, longest pause {max(longest):.2f} s | audio gaps reported {mouth.underruns}", flush=True)


for name in sys.argv[1:] or pat.ENGLISH_VOICES:
    run(f"Pocket TTS {name}", name)
