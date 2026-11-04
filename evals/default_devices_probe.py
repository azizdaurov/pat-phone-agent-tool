"""Switches Windows' default speaker and microphone for a few seconds, as a call would, then puts them back.
Nothing plays and nothing is saved. If it's stopped halfway: .venv\\Scripts\\python.exe pat.py restore-audio"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import pat
from audio_defaults import CAPTURE, RENDER, CallDevices, WindowsAudio

audio = WindowsAudio()


def show(label):
    for kind, names in ((RENDER, audio.endpoints(RENDER)), (CAPTURE, audio.endpoints(CAPTURE))):
        by_id = {device_id: name for name, device_id in names.items()}
        print(label, [by_id.get(device_id, device_id) for device_id in audio.defaults(kind)], flush=True)


speaker = pat.find_silent_speaker()
print("silent speaker found:", speaker, flush=True)
show("before:")
devices = CallDevices(os.path.join(pat.HERE, "calls"))
devices.use(speaker=speaker, mic=pat.CABLE_HEAR)
show("during:")
time.sleep(3)
print("problems restoring:", devices.restore(), flush=True)
show("after: ")
