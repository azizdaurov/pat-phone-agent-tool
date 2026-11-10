"""Does a laptop take-over send the speaker's sound back down the line? No phone or call needed.

A recorded voice stands in for the other person. It plays on the real speaker through Pat's own take-over code, while
this records CABLE Output: exactly what the other phone would receive. Then Pat's own speech detector counts how many
times it would think someone started talking, which is what made an AI on the other end cut itself off. It runs twice,
with Windows' echo cancellation and with the plain microphone. Stay quiet while it runs; you'll hear the voice twice.
Nothing is saved unless --talk is used with --save-dir.

Run: .venv\\Scripts\\python.exe evals\\echo_cancel_probe.py
     .venv\\Scripts\\python.exe evals\\echo_cancel_probe.py --talk   (your own voice, both ways: it must still get through)
     .venv\\Scripts\\python.exe evals\\echo_cancel_probe.py --talk --save-dir evals/results/echo_talk
"""
import argparse
import os
import queue
import sys
import threading
import time
import types
import wave

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
import numpy as np
import sounddevice as sd
import pat

VOICE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results", "english_voice_samples", "pocket_anna.wav")
CALL_RATE = 48000
SECONDS = 6


def load_voice():
    with wave.open(VOICE) as recording:
        rate = recording.getframerate()
        sound = np.frombuffer(recording.readframes(recording.getnframes()), dtype=np.int16).astype(np.float32) / 32768
        if recording.getnchannels() > 1:
            sound = sound.reshape(-1, recording.getnchannels()).mean(axis=1)
    sound = sound[: rate * SECONDS]
    positions = np.arange(0, len(sound) - 1, rate / CALL_RATE)
    return (np.interp(positions, np.arange(len(sound)), sound) * 0.5).astype(np.float32)


def cable_input():
    return next(i for i, d in enumerate(sd.query_devices()) if "WASAPI" in sd.query_hostapis(d["hostapi"])["name"]
                and pat.CABLE_HEAR in d["name"] and d["max_input_channels"] > 0)


def turns_heard(sound_16k):
    """How many times Pat's speech detector would say the other side started talking."""
    turns = pat.TurnDetector(pat.SpeechDetector(use_service=False))
    starts = 0
    for i in range(0, len(sound_16k) - pat.FRAME, pat.FRAME):
        if turns.feed(sound_16k[i:i + pat.FRAME]) == "start":
            starts += 1
    return starts


def run(voice, speaker, microphone, cable, echo_cancel):
    caller = types.SimpleNamespace(rate=CALL_RATE, channels=1, blocks=queue.Queue(), drop_waiting=lambda: None)
    takeover = pat.LaptopTakeover(caller, speaker, microphone, cable, echo_cancel=echo_cancel)
    heard = []
    device = cable_input()
    channels = min(2, int(sd.query_devices(device)["max_input_channels"]))
    recording = sd.InputStream(samplerate=CALL_RATE, channels=channels, dtype="float32", device=device,
                               callback=lambda data, *rest: heard.append(data.mean(axis=1).copy()))
    takeover.start()
    recording.start()
    time.sleep(1.5)  # the canceller's first moments, before the other person speaks
    for start in range(0, len(voice), 960):
        caller.blocks.put(voice[start:start + 960])
    time.sleep(len(voice) / CALL_RATE + 1.0)
    recording.stop()
    recording.close()
    takeover.stop()
    sound = np.concatenate(heard) if heard else np.zeros(0, np.float32)
    sound_16k = sound[: len(sound) // 3 * 3].reshape(-1, 3).mean(axis=1)
    loudness = float(np.sqrt(np.mean(sound ** 2))) if len(sound) else 0.0
    return takeover.echo_cancelled, loudness, turns_heard(sound_16k)


def plain(*args, **kwargs):
    raise OSError("turned off for this comparison")


def talk(speaker, microphone, cable, save_dir=None):
    """Your own voice must still get through: you talk for 5 s each way, and nothing plays."""
    for label, opener in (("plain microphone", plain), ("echo cancellation", None)):
        input(f"Press Enter, then talk for 5 seconds ({label})... ")
        caller = types.SimpleNamespace(rate=CALL_RATE, channels=1, blocks=queue.Queue(), drop_waiting=lambda: None)
        takeover = pat.LaptopTakeover(caller, speaker, microphone, cable, echo_cancel=opener)
        heard = []
        device = cable_input()
        recording = sd.InputStream(samplerate=CALL_RATE, channels=min(2, int(sd.query_devices(device)["max_input_channels"])),
                                   dtype="float32", device=device, callback=lambda data, *rest: heard.append(data.mean(axis=1).copy()))
        takeover.start()
        recording.start()
        time.sleep(5)
        recording.stop()
        recording.close()
        takeover.stop()
        sound = np.concatenate(heard) if heard else np.zeros(0, np.float32)
        if save_dir is not None:
            os.makedirs(save_dir, exist_ok=True)
            if opener is plain:
                filename = "plain_microphone.wav"
            elif takeover.echo_cancelled:
                filename = "echo_cancelled.wav"
            else:
                filename = "echo_unavailable_plain.wav"
            path = os.path.abspath(os.path.join(save_dir, filename))
            pcm = (np.clip(sound, -1, 1) * 32767).astype("<i2")
            with wave.open(path, "wb") as output:
                output.setnchannels(1)
                output.setsampwidth(2)
                output.setframerate(CALL_RATE)
                output.writeframes(pcm.tobytes())
            print(f"Saved: {path}", flush=True)
        if opener is None and not takeover.echo_cancelled:
            print("Echo cancellation was unavailable; this round used the plain microphone.", flush=True)
        sound_16k = sound[: len(sound) // 3 * 3].reshape(-1, 3).mean(axis=1)
        print(f"{label}: your voice reaches the call at loudness {float(np.sqrt(np.mean(sound ** 2))):.4f}, "
              f"loudest {float(np.max(np.abs(sound))) if len(sound) else 0:.3f}; speech detector starts {turns_heard(sound_16k)} turn(s)", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--talk", action="store_true", help="Compare your voice with and without echo cancellation.")
    parser.add_argument("--save-dir", help="Save each --talk recording as a WAV in this folder, at its original volume.")
    args = parser.parse_args()
    if args.save_dir and not args.talk:
        parser.error("--save-dir needs --talk")
    speaker, microphone = pat.real_devices()
    if speaker is None or microphone is None:
        raise SystemExit("No real speaker or microphone found.")
    cable = pat.find_output(pat.CABLE_PLAY)
    print(f"speaker: {sd.query_devices(speaker)['name']} | microphone: {sd.query_devices(microphone)['name']}", flush=True)
    if args.talk:
        talk(speaker, microphone, cable, args.save_dir)
        return
    voice = load_voice()
    for label, opener in (("echo cancellation", None), ("plain microphone", plain)):
        cancelled, loudness, starts = run(voice, speaker, microphone, cable, opener)
        if opener is None and not cancelled:
            label = "echo cancellation (unavailable here, so this is the plain microphone)"
        print(f"{label}: the other phone gets loudness {loudness:.4f}; their speech detector would start {starts} turn(s)", flush=True)


main()
