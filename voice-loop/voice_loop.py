"""Push-to-talk voice chat with Claude Haiku 4.5 on your Claude plan, in English or Russian.

English uses Parakeet and Pocket TTS. Russian uses GigaAM and Piper, voice irina or ruslan. Both recognizers run through onnx-asr.
Hold the talk key, speak, release. Hold it again to stop a reply. Ctrl+C quits.
Run from this folder: .venv/Scripts/python.exe voice_loop.py --lang ru --voice ruslan
"""
import argparse
import collections
import csv
import ctypes
import datetime
import glob
import json
import logging
import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time

import numpy as np
import sounddevice as sd

# Haiku 5.5 started its replies about 0.7 s later and said dates the way they're written, so calls use 4.5.
# To go back to 5.5, swap these two lines.
MODEL = "claude-haiku-4-5"
FALLBACK_MODEL = "claude-haiku-5-5"
SYSTEM_PROMPTS = {
    "en": "You are a voice assistant. Reply in one or two short spoken sentences. No lists, no markdown - "
    "your answer will be read aloud.",
    "ru": "Ты голосовой ассистент. Отвечай по-русски одним-двумя короткими предложениями, в каждом не больше "
          "двенадцати слов: твой ответ будут читать вслух. Без списков и разметки. Числа, сокращения и "
          "иностранные названия пиши словами кириллицей.",
}
ERROR_PHRASES = {"en": "Sorry, I could not reach Claude.", "ru": "Извините, не могу связаться с Клодом."}
TTS_LANGUAGE = "english_18m_2026-10"
TTS_VOICE = "alba"
EN_STT_MODEL = "nemo-parakeet-tdt-0.6b-v2"
RU_VOICES = {"irina": "ru_RU-irina-medium", "ruslan": "ru_RU-ruslan-medium"}
RU_TTS_VOICE = "irina"
RU_STT_MODEL = "gigaam-v3-rnnt"  # same as Pat's
KEYS = {"rctrl": 0xA3, "lctrl": 0xA2, "f8": 0x77, "f9": 0x78, "f10": 0x79}

HERE = os.path.dirname(os.path.abspath(__file__))
MIC_RATE = 16000
MIC_BLOCK = 1024
PREROLL_SECONDS = 0.2  # keeps the first syllable if the key goes down slightly late
TAIL_SECONDS = 0.1  # keeps the last syllable if the key comes up slightly early
# A sentence can end at the edge of the text so far, unless it might be the "3." of a coming "3.5".
SENTENCE_END = re.compile(r"""[.!?]["')\]»]*\s|(?:[!?]|(?<!\d)\.)["')\]»]*$""")
CLAUSE_END = re.compile(r"[,;:—–]\s")
MARKDOWN = re.compile(r"[*_#`]")
TIMINGS_FILE = os.path.join(HERE, "timings.csv")


def only_one_copy():
    """Two copies would both hear the talk key and answer at once, in two voices.

    Windows releases the mutex when this process exits, however it exits.
    """
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    kernel32.CreateMutexW(None, False, "Local\\VoiceLoopSingleCopy")
    if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
        sys.exit("The voice loop is already running in another window. Press Ctrl+C there first.")


def find_claude():
    override = os.environ.get("VOICE_LOOP_CLAUDE")
    if override:
        return override
    on_path = shutil.which("claude")
    if on_path:
        return on_path
    pattern = os.path.expandvars(r"%LOCALAPPDATA%\Claude-Data\*\claude-code\*\*\claude.exe")

    def version(path):
        parts = path.split(os.sep)[-3].split(".")
        return [int(p) for p in parts if p.isdigit()]

    found = sorted(glob.glob(pattern), key=version)
    if not found:
        sys.exit("Could not find claude.exe. Set VOICE_LOOP_CLAUDE to its full path.")
    return found[-1]


class Brain:
    """One claude process kept open, because starting a new one costs about a second per turn."""

    def __init__(self, language="en", cli=None, system_prompt=None, model=MODEL):
        self.cli = cli or find_claude()
        self.model = model
        self.system_prompt = system_prompt or SYSTEM_PROMPTS[language]
        self.workdir = os.path.join(tempfile.gettempdir(), "voice_loop")
        os.makedirs(self.workdir, exist_ok=True)
        self.proc = None
        self.lines = None
        self.noise = collections.deque(maxlen=5)
        self.start()

    def start(self):
        # Dropping CLAUDE*/ANTHROPIC* keeps this on your plan login, even if an API key is set somewhere.
        env = {k: v for k, v in os.environ.items() if not k.upper().startswith(("CLAUDE", "ANTHROPIC"))}
        env["MAX_THINKING_TOKENS"] = "0"
        env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] = "1"
        args = [
            self.cli, "-p", "--input-format", "stream-json", "--output-format", "stream-json", "--verbose",
            "--include-partial-messages", "--model", self.model, "--fallback-model",
            "claude-haiku-4-5" if self.model == FALLBACK_MODEL else FALLBACK_MODEL,
            "--tools", "", "--system-prompt", self.system_prompt, "--no-session-persistence",
            "--strict-mcp-config", "--setting-sources", "", "--disable-slash-commands",
        ]
        if self.model == "claude-haiku-5-5":
            args += ["--effort", "low"]
        self.proc = subprocess.Popen(
            args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            env=env, cwd=self.workdir, text=True, encoding="utf-8", errors="replace", bufsize=1,
        )
        self.lines = queue.Queue()
        threading.Thread(target=self._read, args=(self.proc.stdout, self.lines), daemon=True).start()

    def _read(self, stream, lines):
        for raw in stream:
            lines.put(raw)
        lines.put(None)

    def ask(self, text):
        """Yield the reply's text as it arrives."""
        if self.proc.poll() is not None:
            self.start()
        message = {"type": "user", "session_id": "", "parent_tool_use_id": None,
                   "message": {"role": "user", "content": text}}
        self.proc.stdin.write(json.dumps(message) + "\n")
        self.proc.stdin.flush()
        while True:
            raw = self.lines.get()
            if raw is None:
                raise RuntimeError("claude stopped: " + " ".join(self.noise))
            try:
                event = json.loads(raw)
            except ValueError:
                self.noise.append(raw.strip())
                continue
            if event.get("type") == "stream_event":
                delta = event.get("event", {}).get("delta", {})
                if delta.get("type") == "text_delta":
                    yield delta.get("text", "")
            elif event.get("type") == "result":
                if event.get("is_error"):
                    raise RuntimeError(str(event.get("result")))
                return

    def warm_up(self):
        for _ in self.ask("Reply with just the word ready."):
            pass

    def close(self):
        if self.proc and self.proc.poll() is None:
            self.proc.stdin.close()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()


def open_speaker(rate):
    """Prefer WASAPI: it buffered 26 ms on this laptop, against 182 ms for the default route."""
    for api in sd.query_hostapis():
        if "WASAPI" in api["name"] and api["default_output_device"] >= 0:
            try:
                return sd.OutputStream(samplerate=rate, channels=1, dtype="float32", latency="low",
                                       device=api["default_output_device"],
                                       extra_settings=sd.WasapiSettings(auto_convert=True))
            except sd.PortAudioError:
                break
    return sd.OutputStream(samplerate=rate, channels=1, dtype="float32", latency="low")


class PocketVoice:
    """English: streams audio while it generates."""

    warm_text = "Ready."
    clause_chars = None

    def __init__(self, language=TTS_LANGUAGE, voice=TTS_VOICE, model=None):
        from pocket_tts import TTSModel
        self.model = model if model is not None else TTSModel.load_model(language=language)
        self.voice = self.model.get_state_for_audio_prompt(voice)
        self.sample_rate = self.model.sample_rate

    def stream(self, text, stop):
        for chunk in self.model.generate_audio_stream(self.voice, text, stop=stop):
            yield chunk.numpy().astype(np.float32)


class PiperVoice:
    """Russian: makes each piece of text in one go, at about 25x real time on this laptop."""

    warm_text = "Готово."
    clause_chars = 30  # shorter pieces mean first audio sooner, since nothing plays until a piece is done

    def __init__(self, voice=RU_TTS_VOICE):
        import piper
        voice = RU_VOICES.get(voice, voice)
        folder = os.path.join(HERE, "models", "piper")
        path = os.path.join(folder, f"{voice}.onnx")
        if not os.path.exists(path):
            os.makedirs(folder, exist_ok=True)
            subprocess.run([sys.executable, "-m", "piper.download_voices", voice, "--data-dir", folder], check=True)
        self.model = piper.PiperVoice.load(path)
        self.sample_rate = self.model.config.sample_rate

    def stream(self, text, stop):
        for chunk in self.model.synthesize(text):
            if stop.is_set():
                return
            yield chunk.audio_float_array.astype(np.float32)


class Mouth:
    """Speaks sentences one at a time on its own thread."""

    def __init__(self, voice, play=True):
        self.voice = voice
        self.sample_rate = voice.sample_rate
        self.out = None
        if play:
            self.out = open_speaker(self.sample_rate)
            self.out.start()
        self.queue = queue.Queue()
        self.token = 0
        self.stop = threading.Event()
        self.underruns = 0
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        if not getattr(voice, "already_warm", False):
            for _ in voice.stream(voice.warm_text, threading.Event()):
                pass

    def say(self, text, token, on_first_audio=None):
        self.queue.put((text, token, on_first_audio))

    def cancel(self):
        self.token += 1
        self.stop.set()

    def drain(self):
        self.queue.join()

    def _run(self):
        while True:
            text, token, on_first_audio = self.queue.get()
            try:
                if token == self.token:
                    self._speak(text, on_first_audio)
            except Exception as error:
                print(f"[speech error: {error}]", flush=True)
            finally:
                self.queue.task_done()

    def _speak(self, text, on_first_audio):
        self.stop = threading.Event()
        for audio in self.voice.stream(text, self.stop):
            if self.stop.is_set():
                break
            if on_first_audio:
                on_first_audio()
                on_first_audio = None
            if self.out is None:
                continue
            step = int(self.sample_rate * 0.05)
            for start in range(0, len(audio), step):
                if self.stop.is_set():
                    break
                if self.out.write(audio[start:start + step]):
                    self.underruns += 1
        if self.stop.is_set() and self.out is not None:
            self.out.abort()
            self.out.start()


class Mic:
    """Keeps the microphone open and passes audio on only while the talk key is held."""

    def __init__(self, mic=True):
        self.rate = MIC_RATE
        self.recording = False
        self.preroll = collections.deque(maxlen=max(1, int(PREROLL_SECONDS * MIC_RATE / MIC_BLOCK)))
        self.mic = None
        if mic:
            self._open_mic()

    def _open_mic(self):
        try:
            self.mic = sd.InputStream(samplerate=self.rate, channels=1, dtype="float32",
                                      blocksize=MIC_BLOCK, callback=self._on_audio)
        except sd.PortAudioError:
            self.rate = int(sd.query_devices(kind="input")["default_samplerate"])
            self.mic = sd.InputStream(samplerate=self.rate, channels=1, dtype="float32",
                                      blocksize=MIC_BLOCK, callback=self._on_audio)
        self.mic.start()

    def _on_audio(self, data, frames, when, status):
        block = data[:, 0].copy()
        if self.recording:
            self.take(block)
        else:
            self.preroll.append(block)

    def begin(self):
        self.prepare()
        for block in self.preroll:
            self.take(block)
        self.preroll.clear()
        self.recording = True

    def feed_block(self, block, rate):
        """Bench entry point: stands in for the microphone."""
        self.rate = rate
        self.take(block)

    def prepare(self):
        raise NotImplementedError

    def take(self, block):
        raise NotImplementedError


class BatchEar(Mic):
    """onnx-asr models (Parakeet, GigaAM) don't stream: it transcribes everything at release."""

    def __init__(self, model=RU_STT_MODEL, mic=True):
        import onnx_asr
        self.model = onnx_asr.load_model(model, quantization="int8")
        self.model.recognize(np.zeros(MIC_RATE, dtype=np.float32), sample_rate=MIC_RATE)
        self.audio = []
        super().__init__(mic)

    def prepare(self):
        self.audio = []

    def take(self, block):
        self.audio.append(block)

    def end(self, tail=TAIL_SECONDS):
        if tail:
            time.sleep(tail)
        self.recording = False
        if not self.audio:
            return ""
        return self.model.recognize(np.concatenate(self.audio), sample_rate=self.rate).strip()


class Splitter:
    """Cuts streamed text at sentence ends, so speech starts before the whole reply exists.

    With clause_chars set, also cuts at the first comma or dash past that many characters.
    """

    def __init__(self, clause_chars=None):
        self.buffer = ""
        self.clause_chars = clause_chars

    def feed(self, text):
        self.buffer += MARKDOWN.sub("", text)
        pieces = []
        while True:
            match = SENTENCE_END.search(self.buffer)
            if not match and self.clause_chars:
                match = CLAUSE_END.search(self.buffer, self.clause_chars)
            if not match:
                return pieces
            pieces.append(self.buffer[:match.end()].strip())
            self.buffer = self.buffer[match.end():]

    def flush(self):
        rest, self.buffer = self.buffer.strip(), ""
        return [rest] if rest else []


def run_turn(brain, mouth, text, marks, token, show=True):
    """Stream one reply from Claude into the mouth, recording when each stage is reached."""
    splitter = Splitter(mouth.voice.clause_chars)

    def first_audio():
        marks["audio"] = time.perf_counter()

    def speak(sentence):
        nonlocal first_audio
        marks.setdefault("sentence", time.perf_counter())
        if show:
            print(sentence, flush=True)
        mouth.say(sentence, token, first_audio)
        first_audio = None

    for delta in brain.ask(text):
        marks.setdefault("word", time.perf_counter())
        for sentence in splitter.feed(delta):
            speak(sentence)
    for sentence in splitter.flush():
        speak(sentence)
    mouth.drain()


def report(marks, underruns):
    start = marks["release"]
    seconds = {k: round(marks[k] - start, 3) for k in ("transcript", "word", "sentence", "audio") if k in marks}
    print("  [from key release: " + ", ".join(f"{k} {v:.2f}s" for k, v in seconds.items())
          + (f", {underruns} audio gaps" if underruns else "") + "]", flush=True)
    new_file = not os.path.exists(TIMINGS_FILE)
    with open(TIMINGS_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if new_file:
            writer.writerow(["time", "transcript_s", "word_s", "sentence_s", "audio_s", "audio_gaps"])
        writer.writerow([datetime.datetime.now().isoformat(timespec="seconds"), seconds.get("transcript"),
                         seconds.get("word"), seconds.get("sentence"), seconds.get("audio"), underruns])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lang", choices=sorted(SYSTEM_PROMPTS), default="en", help="language you speak and hear")
    parser.add_argument("--key", choices=sorted(KEYS), default="rctrl", help="talk key to hold")
    parser.add_argument("--voice", default=None, help="English: a Pocket TTS voice name. Russian: irina or ruslan")
    parser.add_argument("--tts", default=TTS_LANGUAGE, help="Pocket TTS model (English only)")
    parser.add_argument("--stt", default=None, help="speech-to-text model name")
    args = parser.parse_args()

    only_one_copy()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    logging.disable(logging.INFO)
    print("Loading speech models...", flush=True)
    if args.lang == "ru":
        mouth = Mouth(PiperVoice(args.voice or RU_TTS_VOICE))
        ear = BatchEar(args.stt or RU_STT_MODEL)
    else:
        mouth = Mouth(PocketVoice(args.tts, args.voice or TTS_VOICE))
        ear = BatchEar(args.stt or EN_STT_MODEL)
    print("Starting Claude...", flush=True)
    brain = Brain(args.lang)
    brain.warm_up()

    key = KEYS[args.key]
    user32 = ctypes.windll.user32
    turn_lock = threading.Lock()

    def turn(text, marks, token):
        with turn_lock:
            gaps = mouth.underruns
            try:
                run_turn(brain, mouth, text, marks, token)
            except Exception as error:
                print(f"[Claude error: {error}]", flush=True)
                mouth.say(ERROR_PHRASES[args.lang], mouth.token)
                return
            report(marks, mouth.underruns - gaps)

    print(f"Ready. Hold {args.key}, talk, release. Ctrl+C quits.", flush=True)
    try:
        while True:
            if not user32.GetAsyncKeyState(key) & 0x8000:
                time.sleep(0.01)
                continue
            mouth.cancel()
            ear.begin()
            while user32.GetAsyncKeyState(key) & 0x8000:
                time.sleep(0.01)
            marks = {"release": time.perf_counter()}
            text = ear.end()
            marks["transcript"] = time.perf_counter()
            if not text:
                print("[heard nothing]", flush=True)
                continue
            print(f"You: {text}", flush=True)
            threading.Thread(target=turn, args=(text, marks, mouth.token), daemon=True).start()
    except KeyboardInterrupt:
        print("Bye.")
    finally:
        brain.close()


if __name__ == "__main__":
    main()
