"""Can Voicemeeter alone carry Claude's voice into the call's microphone, with its app closed? Plays a tone into each of its virtual
speakers and listens on each of its virtual microphones. VB-CABLE is the control, since that one is known to pass sound. Nothing reaches a real speaker."""
import sys
import time

import numpy as np
import sounddevice as sd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
RATE = 48000
wasapi = [i for i, api in enumerate(sd.query_hostapis()) if "WASAPI" in api["name"]][0]
devices = [(i, d) for i, d in enumerate(sd.query_devices()) if d["hostapi"] == wasapi]
outputs = [(i, d["name"]) for i, d in devices if d["max_output_channels"] > 0 and ("Voicemeeter" in d["name"] or d["name"].startswith("CABLE Input"))]
inputs = [(i, d["name"]) for i, d in devices if d["max_input_channels"] > 0 and ("Voicemeeter" in d["name"] or d["name"].startswith("CABLE Output"))]
settings = sd.WasapiSettings(auto_convert=True)
tone = (0.1 * np.sin(2 * np.pi * 440 * np.arange(RATE) / RATE)).astype(np.float32)
print("microphones listened to:", [name.split(" (")[0] for _, name in inputs], flush=True)


def short(name):
    return name.split(" (")[0]


for out_index, out_name in outputs:
    peaks = {}
    streams = []
    for in_index, in_name in inputs:
        def on_audio(data, frames, when, status, name=in_name):
            peaks[name] = max(peaks.get(name, 0.0), float(np.abs(data).max()))
        try:
            stream = sd.InputStream(samplerate=RATE, channels=1, dtype="float32", device=in_index, callback=on_audio, extra_settings=settings)
            stream.start()
            streams.append(stream)
        except sd.PortAudioError as error:
            print(f"   can't listen on {short(in_name)}: {error}", flush=True)
    time.sleep(0.3)
    try:
        sd.play(tone, RATE, device=out_index, blocking=True, extra_settings=settings)
    except sd.PortAudioError as error:
        print(f"{short(out_name)}: can't play: {error}", flush=True)
    time.sleep(0.3)
    for stream in streams:
        stream.stop()
        stream.close()
    heard = {short(name): round(peak, 3) for name, peak in peaks.items() if peak > 0.001}
    print(f"played into {short(out_name)}: heard on {heard or 'nothing'}", flush=True)
