"""After Claude is cut off, how long until its next reply is actually audible? Real Pocket TTS, real cable, silent, no phone.
Records CABLE Output and times from "say" to the first sound coming out, in the pattern seen on the 23:39 call."""
import logging
import os
import sys
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import numpy as np
import sounddevice as sd
import pat

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
logging.disable(logging.INFO)
VOICE = sys.argv[1] if len(sys.argv) > 1 else "anna"
SHORT = "Is this Alex?"
REPLY = ["Aziz asked me to find out the time and place of tomorrow's meeting.", "What time does it start?"]
PLAIN = "Can you hear me okay?"


def find_input(name):
    for index, device in enumerate(sd.query_devices()):
        if "WASAPI" in sd.query_hostapis(device["hostapi"])["name"] and name in device["name"] and device["max_input_channels"] > 0:
            return index


_, mouth = pat.load_speech("en", VOICE)
mouth.out = pat.open_cable(mouth.sample_rate)
mouth.out.start()
sound_at = []


def on_audio(data, frames, when, status):
    if np.abs(data).max() > 0.003:
        sound_at.append(time.perf_counter())


record = sd.InputStream(samplerate=48000, channels=2, dtype="float32", device=find_input(pat.CABLE_HEAR), blocksize=480, callback=on_audio)
record.start()


def speak_and_time(label, pieces, cut_after=None):
    """Says the pieces, optionally cuts them off, and reports how soon sound came out and for how long."""
    sound_at.clear()
    mouth.start_reply()
    started = time.perf_counter()
    for piece in pieces:
        mouth.say(piece, mouth.token)
    if cut_after is not None:
        time.sleep(cut_after)
        mouth.cancel()
        mouth.drain()
        print(f"{label}: cut after {cut_after:.1f} s, sound {'after ' + format(sound_at[0] - started, '.2f') + ' s' if sound_at else 'never came out'}", flush=True)
        return
    mouth.drain()
    time.sleep(0.4)
    if sound_at:
        print(f"{label}: sound after {sound_at[0] - started:.2f} s, lasting {sound_at[-1] - sound_at[0]:.1f} s; call took {time.perf_counter() - started:.1f} s", flush=True)
    else:
        print(f"{label}: NO SOUND came out, call took {time.perf_counter() - started:.1f} s", flush=True)


speak_and_time("first line", [SHORT])
for round_number in range(1, 5):
    print(f"--- round {round_number}", flush=True)
    speak_and_time("reply to cut", [SHORT], cut_after=0.05 * round_number)
    time.sleep(1.0)
    speak_and_time("next reply", REPLY)
    time.sleep(2.0)
    speak_and_time("reply after a wait", [PLAIN])
    speak_and_time("long reply to cut", REPLY, cut_after=2.5)
    speak_and_time("straight after a cut", [PLAIN])
print("underruns", mouth.underruns)
record.stop()
