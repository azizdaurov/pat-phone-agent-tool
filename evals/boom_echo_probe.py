"""Would sound on Boom Audio leak into the cable, which is the call's microphone? That would echo callers back to themselves.
Records CABLE Output and three outputs with nothing playing, then while playing to Boom Audio, three times each."""
import sys
import time

import numpy as np
import pyaudiowpatch
import sounddevice as sd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
pa = pyaudiowpatch.PyAudio()
loopbacks = [d for d in pa.get_loopback_device_info_generator() if "CABLE Input" not in d["name"]]
peaks = {}


def peak_callback(name):
    def on_audio(data, count, when, status):
        peaks[name] = max(peaks.get(name, 0.0), float(np.abs(np.frombuffer(data, dtype=np.float32)).max()))
        return None, pyaudiowpatch.paContinue
    return on_audio


def index_of(name, direction):
    for index, device in enumerate(sd.query_devices()):
        if "WASAPI" in sd.query_hostapis(device["hostapi"])["name"] and name in device["name"] and device[direction] > 0:
            return index


def trial(label, play):
    peaks.clear()
    streams = [pa.open(format=pyaudiowpatch.paFloat32, channels=d["maxInputChannels"], rate=int(d["defaultSampleRate"]), input=True,
                       input_device_index=d["index"], frames_per_buffer=1024, stream_callback=peak_callback(d["name"])) for d in loopbacks]

    def on_mic(data, frames, when, status):
        peaks["CABLE Output, the call's microphone"] = max(peaks.get("CABLE Output, the call's microphone", 0.0), float(np.abs(data).max()))

    mic = sd.InputStream(samplerate=48000, channels=2, dtype="float32", device=index_of("CABLE Output", "max_input_channels"), callback=on_mic)
    mic.start()
    time.sleep(0.4)
    if play:
        index = index_of("Boom Audio", "max_output_channels")
        rate = int(sd.query_devices(index)["default_samplerate"])
        tone = (0.1 * np.sin(2 * np.pi * 440 * np.arange(int(rate * 1.5)) / rate)).astype(np.float32)
        sd.play(tone, rate, device=index, blocking=True, extra_settings=sd.WasapiSettings(auto_convert=True))
    else:
        time.sleep(1.5)
    time.sleep(0.4)
    mic.stop()
    mic.close()
    for stream in streams:
        stream.stop_stream()
        stream.close()
    print(label, {name.split(" (")[0] + (" 16ch" if "16ch" in name else ""): round(value, 3) for name, value in peaks.items()}, flush=True)


for round_number in range(3):
    trial("nothing playing :", False)
    trial("playing to Boom :", True)
pa.terminate()
