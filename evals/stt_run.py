"""Runs one recognizer over the test set and saves its text and timings. Resumes if stopped.
Usage: stt_run.py <engine> [language] [conditions, comma separated]
Engines: an onnx-asr name such as gigaam-v3-ctc, whisper:<model folder name> (run in the whisper test environment), moonshine."""
import json
import os
import sys
import time

import numpy as np
import soundfile as sf

DATA = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "stt-test-data"))
ONE_LANGUAGE = {"gigaam": "ru", "t-one": "ru", "alphacep": "ru", "parakeet-tdt-0.6b-v2": "en", "moonshine": "en"}
HF_HUB = os.path.expanduser("~/.cache/huggingface/hub")


def peak_memory_mb():
    import ctypes
    from ctypes import wintypes

    class Counters(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD), ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t), ("a", ctypes.c_size_t), ("b", ctypes.c_size_t),
                    ("c", ctypes.c_size_t), ("d", ctypes.c_size_t), ("e", ctypes.c_size_t), ("f", ctypes.c_size_t)]
    counters = Counters()
    counters.cb = ctypes.sizeof(counters)
    get_memory = ctypes.WinDLL("psapi").GetProcessMemoryInfo
    get_memory.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
    kernel = ctypes.WinDLL("kernel32")
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    get_memory(kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb)
    return round(counters.PeakWorkingSetSize / 1e6)


def onnx_engine(name):
    import onnx_asr
    try:
        model = onnx_asr.load_model(name, quantization="int8")
    except Exception:
        model = onnx_asr.load_model(name)

    def recognize(audio, language):
        return model.recognize(audio, sample_rate=16000)
    return recognize


def whisper_engine(name):
    from faster_whisper import WhisperModel
    snapshots = os.path.join(HF_HUB, name, "snapshots")
    model = WhisperModel(os.path.join(snapshots, os.listdir(snapshots)[0]), device="cpu", compute_type="int8", cpu_threads=8)

    def recognize(audio, language):
        segments, _ = model.transcribe(audio, language=language, beam_size=1, condition_on_previous_text=False)
        return " ".join(segment.text.strip() for segment in segments)
    return recognize


def moonshine_engine():
    """The same streaming path Cicero uses, fed in 32 ms blocks as fast as it will take them."""
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "voice-loop"))
    from voice_loop import Ear, STT_ARCH
    ear = Ear(STT_ARCH, mic=False)

    def recognize(audio, language):
        ear.prepare()
        for start in range(0, len(audio), 512):
            ear.take(audio[start:start + 512])
        return ear.end(tail=0)
    return recognize


def main():
    engine = sys.argv[1]
    wanted_language = sys.argv[2] or None if len(sys.argv) > 2 else None
    conditions = set(sys.argv[3].split(",")) if len(sys.argv) > 3 else None
    clip_limit = int(sys.argv[4]) if len(sys.argv) > 4 else None
    only = next((language for mark, language in ONE_LANGUAGE.items() if mark in engine), None)
    with open(os.path.join(DATA, "set", "manifest.json"), encoding="utf-8") as f:
        entries = json.load(f)
    entries = [e for e in entries if (only is None or e["language"] == only)
               and (wanted_language is None or e["language"] == wanted_language)
               and (conditions is None or e["condition"] in conditions)
               and (clip_limit is None or e["condition"] == "real_call" or int(e["id"][2:]) < clip_limit)]
    os.makedirs(os.path.join(DATA, "results"), exist_ok=True)
    out = os.path.join(DATA, "results", engine.replace("/", "_").replace(":", "_") + ".jsonl")
    done = set()
    if os.path.exists(out):
        with open(out, encoding="utf-8") as f:
            done = {(row["language"], row["condition"], row["id"]) for row in map(json.loads, f)}
    started = time.perf_counter()
    if engine == "moonshine":
        recognize = moonshine_engine()
    elif engine.startswith("whisper:"):
        recognize = whisper_engine(engine.split(":", 1)[1])
    else:
        recognize = onnx_engine(engine)
    loaded = time.perf_counter() - started
    recognize(np.zeros(16000, dtype=np.float32), only or "ru")
    print(engine, "loaded in", round(loaded, 1), "s, memory", peak_memory_mb(), "MB", flush=True)
    with open(out, "a", encoding="utf-8") as f:
        for number, entry in enumerate(entries):
            if (entry["language"], entry["condition"], entry["id"]) in done:
                continue
            audio, _ = sf.read(entry["path"], dtype="float32")
            started = time.perf_counter()
            try:
                text = recognize(audio, entry["language"]).strip()
            except Exception as error:
                text = ""
                print("failed", entry["id"], repr(error)[:200], flush=True)
            row = {key: entry[key] for key in ("id", "language", "condition", "seconds")}
            row.update(text=text, took=round(time.perf_counter() - started, 3))
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            f.flush()
            if number % 100 == 0:
                print(number, "of", len(entries), flush=True)
    print(engine, "done, peak memory", peak_memory_mb(), "MB", flush=True)


if __name__ == "__main__":
    main()
