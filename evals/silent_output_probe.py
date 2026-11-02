"""Plays a tone to each output device, and records every output at once. Sound reaching only the device it was played to means
that device can be recorded without being passed on. Boom Audio and the cable have no speaker of their own, unless software forwards them."""
import sys
import time

import numpy as np
import pyaudiowpatch
import sounddevice as sd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
TARGETS = sys.argv[1:] or ["Boom Audio"]
pa = pyaudiowpatch.PyAudio()
loopbacks = list(pa.get_loopback_device_info_generator())
print("outputs that can be recorded:", [d["name"] for d in loopbacks], flush=True)
peaks = {}


def start_recording(device):
    """Opens one output for recording, or reports why it can't be."""
    name = device["name"]

    def on_audio(data, count, when, status):
        peaks[name] = max(peaks.get(name, 0.0), float(np.abs(np.frombuffer(data, dtype=np.float32)).max()))
        return None, pyaudiowpatch.paContinue

    try:
        return pa.open(format=pyaudiowpatch.paFloat32, channels=device["maxInputChannels"], rate=int(device["defaultSampleRate"]), input=True,
                       input_device_index=device["index"], frames_per_buffer=1024, stream_callback=on_audio)
    except OSError as error:
        print(f"can't record {name}: {error}", flush=True)
        return None


def output_index(name):
    for index, device in enumerate(sd.query_devices()):
        if "WASAPI" in sd.query_hostapis(device["hostapi"])["name"] and name in device["name"] and device["max_output_channels"] > 0:
            return index


for target in TARGETS:
    index = output_index(target)
    if index is None:
        print(f"{target}: not found")
        continue
    peaks.clear()
    streams = [stream for stream in map(start_recording, loopbacks) if stream]
    time.sleep(0.4)
    rate = int(sd.query_devices(index)["default_samplerate"])
    tone = (0.1 * np.sin(2 * np.pi * 440 * np.arange(int(rate * 1.5)) / rate)).astype(np.float32)
    sd.play(tone, rate, device=index, blocking=True, extra_settings=sd.WasapiSettings(auto_convert=True))
    time.sleep(0.4)
    for stream in streams:
        stream.stop_stream()
        stream.close()
    print(f"played to {target}:", {name: round(value, 3) for name, value in peaks.items()}, flush=True)
pa.terminate()
