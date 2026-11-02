"""Real interruptions through the real cable, silently. Speaks into CABLE Input and cuts it off at set moments.
Compares the estimate with a transcription of what actually came out of CABLE Output. No phone, so no network delay."""
import logging
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import numpy as np
import sounddevice as sd
import cicero

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
logging.disable(logging.INFO)
PIECES = ["Здравствуйте, звоню узнать, работает ли ваша клиника в это воскресенье.",
          "Подскажите, пожалуйста, можно ли прийти на приём без предварительной записи."]
CUT_AFTER = [1.0, 2.0, 3.5, 5.0, 7.0, 9.0]


def find_input(name):
    for index, device in enumerate(sd.query_devices()):
        if "WASAPI" in sd.query_hostapis(device["hostapi"])["name"] and name in device["name"] and device["max_input_channels"] > 0:
            return index


ear, mouth = cicero.load_speech("ru", None)
mouth.out = cicero.open_cable(mouth.sample_rate)
mouth.out.start()
ahead = 0
for seconds in CUT_AFTER:
    blocks = []
    record = sd.InputStream(samplerate=48000, channels=2, dtype="float32", device=find_input(cicero.CABLE_HEAR),
                            callback=lambda data, frames, when, status: blocks.append(data.copy()))
    record.start()
    mouth.start_reply()
    for piece in PIECES:
        mouth.say(piece, mouth.token)
    time.sleep(seconds)
    heard = mouth.heard_so_far()
    started = time.perf_counter()
    mouth.cancel()
    mouth.drain()
    stopped = time.perf_counter() - started
    time.sleep(0.5)
    record.stop()
    record.close()
    came_out = ear.model.recognize(cicero.to_16k(np.concatenate(blocks).reshape(-1), 2, 48000), sample_rate=cicero.MIC_RATE).strip()
    ahead += len(heard.split()) > len(came_out.split())
    print(f"cut at {seconds:.1f} s, stopped in {stopped * 1000:.0f} ms, gaps {mouth.underruns}\n  came out ({len(came_out.split())}): {came_out}\n  estimate ({len(heard.split())}): {heard}", flush=True)
print(f"estimate ahead of what came out: {ahead}/{len(CUT_AFTER)}")
