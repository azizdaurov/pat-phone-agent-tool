"""Tests taking over, with no phone. A tone played on the silent speaker stands in for the other person.
Before: is it off the real speaker? During: does it reach the real speaker, and does the real microphone reach the cable?
You'll hear a short beep. Nothing is saved."""
import os
import sys
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
import numpy as np
import pyaudiowpatch
import sounddevice as sd
import pat

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
pa = pyaudiowpatch.PyAudio()
loopbacks = {d["name"]: d for d in pa.get_loopback_device_info_generator()}
silent_speaker = pat.find_silent_speaker()
boom = next(d for name, d in loopbacks.items() if silent_speaker in name)
speaker_index, mic_index = pat.real_devices()
print("real speaker:", sd.query_devices(speaker_index)["name"], "| real microphone:", sd.query_devices(mic_index)["name"], flush=True)
real_name = sd.query_devices(speaker_index)["name"]
real_loop = next(d for name, d in loopbacks.items() if name.startswith(real_name))
cable_in = next(i for i, d in enumerate(sd.query_devices()) if "WASAPI" in sd.query_hostapis(d["hostapi"])["name"] and pat.CABLE_HEAR in d["name"] and d["max_input_channels"] > 0)
boom_out = pat.find_output(silent_speaker)
rate = int(sd.query_devices(boom_out)["default_samplerate"])
tone = (0.1 * np.sin(2 * np.pi * 440 * np.arange(int(rate * 1.2)) / rate)).astype(np.float32)


def play_on_silent_speaker():
    sd.play(tone, rate, device=boom_out, blocking=True, extra_settings=sd.WasapiSettings(auto_convert=True))


def measure_while(action):
    peaks = {"real speaker": 0.0, "call's microphone": 0.0}

    def on_real(data, count, when, status):
        peaks["real speaker"] = max(peaks["real speaker"], float(np.abs(np.frombuffer(data, dtype=np.float32)).max()))
        return None, pyaudiowpatch.paContinue

    def on_cable(data, frames, when, status):
        peaks["call's microphone"] = max(peaks["call's microphone"], float(np.abs(data).max()))

    stream = pa.open(format=pyaudiowpatch.paFloat32, channels=real_loop["maxInputChannels"], rate=int(real_loop["defaultSampleRate"]), input=True,
                     input_device_index=real_loop["index"], frames_per_buffer=1024, stream_callback=on_real)
    cable = sd.InputStream(samplerate=48000, channels=2, dtype="float32", device=cable_in, callback=on_cable)
    cable.start()
    time.sleep(0.3)
    action()
    time.sleep(0.5)
    cable.stop()
    cable.close()
    stream.stop_stream()
    stream.close()
    return {name: round(value, 4) for name, value in peaks.items()}


caller = pat.CallerAudio(device=boom)
print("before taking over:", measure_while(play_on_silent_speaker), flush=True)
takeover = pat.LaptopTakeover(caller, speaker_index, mic_index, pat.find_output(pat.CABLE_PLAY))
takeover.start()
started = time.perf_counter()
print("after taking over :", measure_while(play_on_silent_speaker), flush=True)
takeover.stop()
print("after stopping    :", measure_while(play_on_silent_speaker), flush=True)
caller.close()
pa.terminate()
