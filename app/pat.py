"""Claude speaks on your phone calls: Haiku hears the other person and answers aloud, Sonnet reads along and rarely steps in.

Joins voice-loop (speech recognition, Claude, speech) to iphonecall (the call itself).
Agents place calls through phone_mcp.py. By hand, run from this folder, in voice-loop's environment:
  .venv\\Scripts\\python.exe pat.py dial "+COUNTRY_CODE_NUMBER" --brief "Ask if they open on Sunday"
  .venv\\Scripts\\python.exe pat.py answer
Replace +COUNTRY_CODE_NUMBER with a full international number. English is the default; use --lang ru for Russian.
While a call runs, type h to hang up or p to move the call to the phone and take over. Setup: README.md
"""
import argparse
import collections
import ctypes
import datetime
import json
import logging
import os
import queue
import random
import re
import secrets
import subprocess
import sys
import threading
import time
import wave

import numpy as np
import sounddevice as sd

from audio_defaults import CallDevices, chosen_devices, headset_problem, repair_defaults
from call_brief import (ASK_MARK, DEFAULT_ENGLISH_VOICE, END_MARK, ENGLISH_VOICES, HEARD_NOTHING, REACHED_MARKS, CallBrief,
                        caller_id_message, is_bare_answer)
from caller_names import CallerNames
import claude_errors
from easter_eggs import EasterEggs, POEM_PROMPTS, WATSON, write_poem
from live_call import LiveCall, SoundMeter, final_note, write_last_call
from live_notes import INCOMING_LABELS, LiveNotes, NOTES_PROMPT
from note_settings import NoteSettings
from observer import OBSERVER_MODEL, Observer
from phone_memory import ContactNotes, SUMMARY_LIMIT, SUMMARY_PROMPT, attempt_text, merge_call, number_key, summary_may_change
from phone_numbers import international_number
from private_numbers import PrivateNumbers
from user_profile import UserProfile, setup_refusal
from real_dates import configure as configure_dates, current_time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # Names and calls may contain any Unicode characters.
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # the repository: this file is in app/
sys.path.insert(0, os.path.join(HERE, "voice-loop"))
from voice_loop import (BatchEar, Brain, MIC_RATE, Mouth, PiperVoice, PocketVoice, RU_TTS_VOICE,  # noqa: E402
                        SYSTEM_PROMPTS, Splitter, TTS_LANGUAGE, TTS_VOICE)

# The fewest word errors on phone audio that still answer in about 0.2 s on a CPU.
RU_STT_MODEL = "gigaam-v3-rnnt"
EN_STT_MODEL = "nemo-parakeet-tdt-0.6b-v2"

CABLE_PLAY = "CABLE Input"  # Pat speaks into this end of the virtual cable...
CABLE_HEAR = "CABLE Output"  # ...and Windows reads this end as the call's microphone
# As the default speaker, one of these plays the call with no sound in the room, and it can still be recorded. The first one
# installed is used. Another can be named in PAT_SILENT_SPEAKER; check it first with evals\silent_output_probe.py.
SILENT_SPEAKERS = ("Voicemeeter Input", "CABLE-A Input", "CABLE-B Input", "Steam Streaming Speakers", "Boom Audio")
TAKE_OVER_KEY = 0x78  # F9, anywhere in Windows
MIC_GONE_SECONDS = 2
QUIET_MIC = 0.01  # loudest sound while someone talks, below which the other person would barely hear them
FRAME = 512  # Silero's frame at 16 kHz: 32 ms
SILENT_GAP = 0.1  # Windows sends no loopback audio during silence, so a gap this long counts as silence
START_FRAMES = 5  # 0.16 s of speech starts a turn
END_FRAMES = 22  # 0.7 s of silence ends it
MAX_TURN_FRAMES = 940  # 30 s
PREROLL_FRAMES = 16
START_PROB = 0.5
END_PROB = 0.35
AFTER_PICKUP_SECONDS = 1.0  # lets the audio move to the laptop before the opening line
AUDIO_MOVE_SECONDS = 6  # after pickup; longer than this, hanging up is kinder than a silent line
# How much of what was played counts as not heard when someone interrupts: 0.16 s to detect them, plus the
# audio buffer and the phone network's delay (not measured). Too much only makes Claude repeat a few words.
CUT_MARGIN_SECONDS = 0.5
# English speech is made while it plays, so a piece's length is a guess until it ends. A low guess pushes the
# cut earlier. This is for a voice with no rate of its own in ENGLISH_VOICES.
SLOW_CHARS_PER_SECOND = 13
NOBODY_THERE_SECONDS = 60
NUDGE_SECONDS = 8  # dead air this long during the task, and Claude checks the person is still there
MAX_NUDGES = 2  # in a row, after which NOBODY_THERE_SECONDS decides
MAX_WORDLESS_REPLIES = 2  # in a row, so line noise can't keep Claude talking
CONFIRMATION_END = re.compile(r"\b(?:is that (?:right|correct|okay)|right|correct|(?:это |вс[её] )?(?:верно|правильно)|так)\s*\?\s*$", re.I)
CONFIRMATION_CUES = set("right correct correctly okay ok confirm верно правильно так подтвердите подтверждаете".split())
CONFIRMATION_WORDS = CONFIRMATION_CUES | set(
    "can could would you please did i hear get got have is this that it does sound understand understood heard do so am understanding everything "
    "я вас вы меня ли услышал услышала понял поняла понимаю это всё все да мне пожалуйста".split())

# Says it isn't a person, and whose it is, in every call. No option removes it. The Russian wording uses words the voice reads clearly.
OPENINGS = {
    "dial": {"en": "Hello, this is {owner}'s AI assistant. {owner} might hear this conversation.",
             "ru": "Здравствуйте, я виртуальный ассистент. Мой пользователь — {owner_ru}. {owner_ru} может слышать этот разговор."},
    "answer": {"en": "Hello, this is {owner}'s AI assistant. {owner} might hear this conversation. How can I help you?",
               "ru": "Здравствуйте, я виртуальный ассистент. Мой пользователь — {owner_ru}. {owner_ru} может слышать этот разговор."},
}
# Said before the owner comes on the line, so the other person knows a person has joined.
TAKING_OVER = {"en": "One moment, I'm passing you to {owner}.", "ru": "Одну секунду, передаю трубку. С вами будет говорить {owner_ru}."}
# When nobody comes to the phone during the identity check.
NOBODY_CAME = {"en": "I couldn't reach them. We will call again. Goodbye.", "ru": "Не дождался ответа. Мы перезвоним. До свидания."}
DEFAULT_ANSWER_GOAL = "Find out who is calling and why, and offer to pass on a message."
# Told to Haiku on a call Pat answered, once Pat knows who called.
KNOWN_CALLER = ("You now know who they are. Don't ask their name again, and don't ask for their full name, surname or phone number "
                "unless your task asks for it.")
WARM_UP = {"en": "The call is about to connect. Reply with just the word ready.",
           "ru": "Звонок сейчас начнётся. Ответь одним словом: готов."}
# Said when Sonnet changes what Haiku will say. Varied, so it doesn't sound like a machine stalling.
STALLS = {"en": ["One moment.", "Just a moment, please.", "One second.", "Sorry, one moment.", "Hold on a second, please."],
          "ru": ["Одну секунду.", "Секундочку.", "Минутку, пожалуйста.", "Одну минуту.", "Извините, одну секунду."]}


def pick_phone(run=subprocess.run, profile=None):
    """For setup: the name of a paired phone with a working call line, the chosen one first, or None while none is ready.
    Nothing is saved: with no phone chosen, Pat uses whichever phone connected last."""
    profile = profile or UserProfile()
    listed = run(["iphonecall", "list-json"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
    try:
        phones = [phone for phone in json.loads(listed.stdout) if isinstance(phone, dict) and phone.get("id")]
    except ValueError:
        return None
    phones.sort(key=lambda phone: phone["id"] != profile.phone_device)
    for phone in phones:
        try:
            status = run(["iphonecall", "status", "--device-id", phone["id"]], capture_output=True, text=True,
                         encoding="utf-8", errors="replace", timeout=90)
        except subprocess.TimeoutExpired:
            continue
        if "canDial=True" in status.stdout:
            return phone.get("name") or "your phone"
    return None


def phone_command(stay_on_phone=False, follow_phone=False):
    """follow_phone: for a line kept open for hours, such as the note's. It closes when its phone disconnects or the chosen
    phone comes back, and its owner starts a new one, which lands on whichever phone is here."""
    command = ["iphonecall"]
    selected = UserProfile().phone_device
    if selected:
        command += ["--device-id", selected]
    if stay_on_phone:
        command.append("--stay-on-phone")
    if follow_phone:
        command.append("--follow-phone")
    return command


class PhoneLine:
    """Drives iphonecall's shell over pipes, and turns what it prints into call events."""

    CALL = re.compile(r"-- (\w+) (.*): (\w+), audio=(\w+), muted=")
    CALL_ENDED = re.compile(r"-- call ended \((\d+) active\)")
    READY = "commands:"
    END_GRACE_SECONDS = 5  # a call that comes back within this long never ended
    # Windows lets one app at a time use the phone for calls. Whichever has it keeps it: with Pat's note open, Phone
    # Link can't dial (seen 5 Nov 2026), and while Phone Link has it, Windows refuses Pat with this word (31 Oct).
    TAKEN = "DeniedBySystem"
    TAKEN_MESSAGE = ("Phone Link has your phone. Close Phone Link, then re-pair on both devices: remove the phone in the laptop's "
                     "Bluetooth settings, forget the laptop in the phone's Bluetooth settings, and pair them again. "
                     "Pat and Phone Link can't use the phone at the same time.")

    def __init__(self, command=None, log_path=None, end_grace=END_GRACE_SECONDS):
        self.proc = subprocess.Popen(list(command) if command is not None else phone_command(), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.STDOUT, text=True, errors="replace", bufsize=1,
                                     creationflags=subprocess.CREATE_NO_WINDOW)
        self.events = queue.Queue()
        self.started = []
        self.ready = threading.Event()
        self.ended = threading.Event()
        self.ringing = threading.Event()
        self.in_call = False
        self.audio = None
        self.log_path = log_path
        self.end_grace = end_grace
        self.end_timer = None
        self.last_status = None
        threading.Thread(target=self._read, daemon=True).start()

    def _log(self, line):
        if self.log_path and line:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(f"{datetime.datetime.now():%H:%M:%S.%f} {line}\n")

    def _call_is_over(self):
        self.in_call = False
        self.ended.set()
        self.events.put(("Ended", "", ""))

    def _read(self):
        for line in self.proc.stdout:
            line = line.strip()
            self._log(line)
            if not self.ready.is_set():
                self.started.append(line)
            if line.startswith(self.READY):
                self.ready.set()
            match = self.CALL.search(line)
            ended = self.CALL_ENDED.search(line)
            if match:
                direction, who, status = match.group(1, 2, 3)
                self.last_status = status
                if status == "Incoming":
                    self.ringing.set()
                else:
                    self.ringing.clear()
                self.audio = match.group(4)
                if self.end_timer:
                    self.end_timer.cancel()
                    self.end_timer = None
                self.ended.clear()
                self.in_call = True
                self.events.put((status, who, direction))
            elif ended and int(ended.group(1)) == 0:
                if self.ringing.is_set():
                    self.ringing.clear()
                    self.events.put(("RingingStopped", "", ""))
                # Dialing can disappear briefly while Windows switches call objects. A connected call's end should be prompt.
                delay = self.end_grace if self.last_status == "Dialing" else min(self.end_grace, 0.5)
                self.end_timer = threading.Timer(delay, self._call_is_over)
                self.end_timer.daemon = True
                self.end_timer.start()
            elif line.startswith(("error:", "stuck:", "dial ")):
                print(f"[phone: {line}]", flush=True)
        self._log("(iphonecall stopped)")
        if self.end_timer:
            self.end_timer.cancel()
        self.ended.set()
        self.ringing.clear()
        self.events.put(("Closed", "", ""))

    def taken_by_another_app(self):
        return any(self.TAKEN in line for line in self.started)

    def wait_ready(self, seconds=60):
        """True once the shell is up. On failure, iphonecall's own lines say which step failed."""
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline and self.proc.poll() is None:
            if self.ready.wait(0.2):
                return True
        return self.ready.is_set()

    def wait_for(self, statuses, seconds=None):
        """Wait for one of the given call states. Returns (status, who), or None on timeout."""
        deadline = time.monotonic() + seconds if seconds else None
        while True:
            left = deadline - time.monotonic() if deadline else None
            if left is not None and left <= 0:
                return None
            try:
                status, who, _ = self.events.get(timeout=left)
            except queue.Empty:
                return None
            if status in statuses or status in ("Ended", "Closed"):
                return status, who

    def wait_for_laptop_audio(self, seconds):
        """False if the call is still on the phone after this long. Then Pat can neither hear nor be heard."""
        deadline = time.monotonic() + seconds
        while self.audio != "LocalDevice":
            if time.monotonic() >= deadline or self.ended.is_set():
                return False
            time.sleep(0.1)
        return True

    def _send(self, command):
        if self.proc.poll() is None:
            self.proc.stdin.write(command + "\n")
            self.proc.stdin.flush()

    def dial(self, number):
        self._send(f"d {number}")

    def answer(self):
        self._send("a")

    def hang_up(self):
        self._send("h")

    def to_phone(self):
        self._send("p")

    def to_laptop(self):
        self._send("l")

    def close(self):
        """Leaves iphonecall. A call still running would carry on, so hang up first if that's not wanted."""
        if self.proc.poll() is None:
            try:
                self._send("q")
                self.proc.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                self.proc.kill()


def to_16k(raw, channels, rate):
    mono = raw.reshape(-1, channels).mean(axis=1)
    if rate == MIC_RATE:
        return mono
    if rate % MIC_RATE == 0:
        factor = rate // MIC_RATE
        return mono[:len(mono) // factor * factor].reshape(-1, factor).mean(axis=1)
    return np.interp(np.arange(0, len(mono), rate / MIC_RATE), np.arange(len(mono)), mono).astype(np.float32)


class CallerAudio:
    """Hears the other person by recording what Windows sends to the default speaker (WASAPI loopback)."""

    def __init__(self, device=None):
        import pyaudiowpatch
        self.pa = pyaudiowpatch.PyAudio()
        device = device or self.pa.get_default_wasapi_loopback()
        self.name = device["name"]
        self.rate = int(device["defaultSampleRate"])
        self.channels = device["maxInputChannels"]
        self.blocks = queue.Queue()
        self.closed = False
        self.continue_flag = pyaudiowpatch.paContinue
        self.tap = None  # also gets every block, for listening in
        self.stream = self.pa.open(format=pyaudiowpatch.paFloat32, channels=self.channels, rate=self.rate,
                                   input=True, input_device_index=device["index"], frames_per_buffer=1024,
                                   stream_callback=self._on_audio)

    def _on_audio(self, data, count, when, status):
        block = np.frombuffer(data, dtype=np.float32).copy()
        self.blocks.put(block)
        tap = self.tap
        if tap:
            tap(block)
        return None, self.continue_flag

    def drop_waiting(self):
        """Throws away audio not read yet, so what's played next is live and not seconds old."""
        while not self.blocks.empty():
            try:
                self.blocks.get_nowait()
            except queue.Empty:
                return

    def frames(self):
        pending = np.zeros(0, dtype=np.float32)
        while not self.closed:
            try:
                block = to_16k(self.blocks.get(timeout=SILENT_GAP), self.channels, self.rate)
            except queue.Empty:
                block = np.zeros(int(SILENT_GAP * MIC_RATE), dtype=np.float32)
            pending = np.concatenate((pending, block))
            while len(pending) >= FRAME:
                yield pending[:FRAME]
                pending = pending[FRAME:]

    def close(self):
        self.closed = True
        self.stream.stop_stream()
        self.stream.close()
        self.pa.terminate()


class LaptopTakeover:
    """Puts the owner on the call: the other person's voice on the real speaker, their real microphone into the cable."""

    def __init__(self, caller, speaker, microphone, cable):
        self.caller = caller
        self.closed = threading.Event()
        from mic_relay import MicRelay
        mic_info = sd.query_devices(microphone)
        cable_info = sd.query_devices(cable)
        input_rate = int(mic_info["default_samplerate"])
        output_rate = int(cable_info["default_samplerate"])
        input_channels = int(mic_info["max_input_channels"])
        output_channels = min(2, int(cable_info["max_output_channels"]))
        if not input_channels or not output_channels:
            raise RuntimeError("The selected microphone or call output has no audio channels.")
        self.relay = MicRelay(input_rate, output_rate)
        self.streams = []
        try:
            self.speaker = sd.OutputStream(samplerate=caller.rate, channels=caller.channels, dtype="float32", device=speaker,
                                           extra_settings=sd.WasapiSettings(auto_convert=True))
            self.streams.append(self.speaker)
            self.microphone = sd.InputStream(samplerate=input_rate, channels=input_channels, dtype="float32", device=microphone,
                                             callback=self.relay.capture, latency="low")
            self.streams.append(self.microphone)
            self.cable = sd.OutputStream(samplerate=output_rate, channels=output_channels, dtype="float32", device=cable,
                                         callback=self.relay.render, latency="low", extra_settings=sd.WasapiSettings(auto_convert=True))
            self.streams.append(self.cable)
        except Exception:
            for stream in reversed(self.streams):
                stream.close()
            raise
        self.forwarding = threading.Thread(target=self._play_caller, daemon=True)
        self.error = None
        self.started = None
        print(f"Takeover microphone: {mic_info['name']} ({input_rate} Hz, {input_channels} channels); "
              f"call output: {cable_info['name']} ({output_rate} Hz, {output_channels} channels); "
              f"their voice on: {sd.query_devices(speaker)['name']}", flush=True)

    def _play_caller(self):
        while not self.closed.is_set():
            try:
                block = self.caller.blocks.get(timeout=0.1)
            except queue.Empty:
                continue
            try:
                self.speaker.write(block.reshape(-1, self.caller.channels))
            except Exception as error:  # such as headphones unplugged
                self.error = f"the speaker stopped: {error}"
                return

    def problem(self, now=None):
        """Why the laptop's audio stopped working, or None. A microphone keeps sending audio even in silence, so a stall
        means it's gone."""
        if self.error:
            return self.error
        if not all(stream.active for stream in self.streams):
            return "an audio device stopped"
        now = time.monotonic() if now is None else now
        last = self.relay.last_capture or self.started
        if last is not None and now - last > MIC_GONE_SECONDS:
            return "the microphone stopped sending audio"
        return None

    def start(self):
        self.caller.drop_waiting()
        try:
            self.speaker.start()
            self.microphone.start()
            self.cable.start()
            self.forwarding.start()
        except Exception:
            self.stop()
            raise
        self.started = time.monotonic()

    def stop(self):
        if self.closed.is_set():
            return
        self.closed.set()
        if self.forwarding.is_alive():
            self.forwarding.join(1)
        for stream in reversed(self.streams):
            try:
                stream.stop()
            except (OSError, RuntimeError) as error:
                print(f"[takeover audio stop: {error}]", flush=True)
            finally:
                stream.close()
        print("Takeover audio: " + self.relay.summary(), flush=True)


class CableOutput:
    """The stream into the cable, which can also hand each piece of Claude's voice to someone listening in."""

    def __init__(self, stream):
        self.stream = stream
        self.listener = None
        self.sound = SoundMeter()

    def write(self, chunk):
        self.sound.feed(chunk)
        listener = self.listener
        if listener:
            listener(chunk.copy())
        return self.stream.write(chunk)

    def __getattr__(self, name):
        return getattr(self.stream, name)


class Listening:
    """Plays both sides of the call on the real speaker, with the owner's microphone staying out of it."""

    def __init__(self, caller, cable, voice_rate, speaker):
        settings = sd.WasapiSettings(auto_convert=True)
        self.caller = caller
        self.cable = cable
        self.feeds = []
        for rate, channels, attach in ((caller.rate, caller.channels, self._attach_caller), (voice_rate, 1, self._attach_voice)):
            stream = sd.OutputStream(samplerate=rate, channels=channels, dtype="float32", device=speaker, extra_settings=settings)
            waiting = queue.Queue()
            thread = threading.Thread(target=self._play, args=(stream, waiting, channels), daemon=True)
            self.feeds.append((stream, waiting, thread))
            attach(waiting.put)
        for stream, _, thread in self.feeds:
            stream.start()
            thread.start()

    def _attach_caller(self, put):
        self.caller.tap = put

    def _attach_voice(self, put):
        self.cable.listener = put

    def _play(self, stream, waiting, channels):
        while True:
            block = waiting.get()
            if block is None:
                return
            stream.write(block.reshape(-1, channels))

    def stop(self):
        self.caller.tap = None
        self.cable.listener = None
        for stream, waiting, thread in self.feeds:
            waiting.put(None)
            thread.join(1)
            stream.stop()
            stream.close()


class SpeechDetector:
    """Silero, one frame at a time. Works on speech itself, so call volume and line hiss matter little."""

    CONTEXT = 64  # samples of the previous frame that Silero expects in front of each new one

    def __init__(self, session=None, use_service=True):
        self.remote = None
        if session is None and use_service:
            from speech_service import available, RemoteDetector
            status = available()
            if status:
                self.remote = RemoteDetector(status)
                return
        if session is None:
            import onnx_asr
            session = onnx_asr.load_vad("silero")._model
        self.session = session
        self.state = np.zeros((2, 1, 128), dtype=np.float32)
        self.context = np.zeros(self.CONTEXT, dtype=np.float32)

    def __call__(self, frame):
        if self.remote:
            return self.remote(frame)
        joined = np.concatenate((self.context, frame)).astype(np.float32)[None, :]
        output, self.state = self.session.run(
            None, {"input": joined, "state": self.state, "sr": np.array(MIC_RATE, dtype=np.int64)})
        self.context = frame[-self.CONTEXT:]
        return float(output[0][0])

    def close(self):
        if self.remote:
            self.remote.close()


class TurnDetector:
    """Replaces the talk key: says when the other person starts and stops speaking."""

    def __init__(self, detector):
        self.detector = detector
        self.preroll = collections.deque(maxlen=PREROLL_FRAMES)
        self.speaking = False
        self.voiced = 0
        self.silent = 0
        self.length = 0

    def feed(self, frame):
        """Returns "start" (preroll holds the audio so far), "end", or None."""
        prob = self.detector(frame)
        if not self.speaking:
            self.preroll.append(frame)
            self.voiced = self.voiced + 1 if prob >= START_PROB else 0
            if self.voiced < START_FRAMES:
                return None
            self.speaking = True
            self.silent = self.length = 0
            return "start"
        self.length += 1
        self.silent = self.silent + 1 if prob < END_PROB else 0
        if self.silent >= END_FRAMES or self.length >= MAX_TURN_FRAMES:
            self.speaking = False
            self.voiced = 0
            self.preroll.clear()
            return "end"
        return None


def whole_words(text, fraction):
    """The part of text within this fraction of it, ending on a full word. A partly heard word doesn't count."""
    if fraction >= 1:
        return text
    position = int(len(text) * fraction)
    return text[:max(0, text.rfind(" ", 0, position + 1))].rstrip(" ,;:—–")


def heard_text(pieces, margin=CUT_MARGIN_SECONDS):
    """What the person probably heard, erring early. pieces are [text, seconds played, seconds long], oldest first."""
    heard = []
    for text, played, length in reversed(pieces):
        kept = max(0.0, played - margin)
        margin = max(0.0, margin - played)
        if kept > 0:
            heard.insert(0, whole_words(text, kept / max(length, played)))
    return " ".join(part for part in heard if part)


class TrackingMouth(Mouth):
    """voice_loop's Mouth, which also keeps track of how much of the current reply has been played."""

    def __init__(self, voice, play=True):
        self.reply_pieces = []
        self.slow_rate = SLOW_CHARS_PER_SECOND
        self.length_known = isinstance(voice, PiperVoice) or getattr(voice, "length_known", False)
        super().__init__(voice, play)

    def start_reply(self):
        self.reply_pieces = []

    def idle(self):
        return self.queue.unfinished_tasks == 0

    def heard_so_far(self):
        return heard_text(self.reply_pieces)

    def _speak(self, text, on_first_audio):
        self.stop = threading.Event()
        piece = [text, 0.0, len(text) / self.slow_rate]
        self.reply_pieces.append(piece)
        chunks = self.voice.stream(text, self.stop)
        if self.length_known:
            chunks = list(chunks)  # Piper makes a piece far faster than it plays, so this costs almost nothing
            piece[2] = sum(len(audio) for audio in chunks) / self.sample_rate
        step = int(self.sample_rate * 0.05)
        for audio in chunks:
            if self.stop.is_set():
                break
            if on_first_audio:
                on_first_audio()
                on_first_audio = None
            for start in range(0, len(audio), step):
                if self.stop.is_set():
                    break
                chunk = audio[start:start + step]
                if self.out is not None and self.out.write(chunk):
                    self.underruns += 1
                piece[1] += len(chunk) / self.sample_rate
        if self.stop.is_set():
            if self.out is not None:
                self.out.abort()
                self.out.start()
        else:
            piece[2] = piece[1]


class Transcript:
    def __init__(self, folder=os.path.join(HERE, "calls"), key=None):
        os.makedirs(folder, exist_ok=True)
        name = datetime.datetime.now().strftime("%Y%m%d-%H%M%S") + (f"-{key}" if key else "")
        self.path = os.path.join(folder, name + ".txt")
        self.spoken = []
        self.on_them = None  # called after each thing the other person says

    def add(self, who, text):
        print(f"{who}: {text}", flush=True)
        if who != "Pat":
            self.spoken.append((who, text))
        if who == "Them" and self.on_them:
            self.on_them(self.spoken)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(f"{datetime.datetime.now():%H:%M:%S} {who}: {text}\n")


def saved_frames(frames, path):
    """Passes the frames on, and keeps what Pat hears as a WAV. Only with --save-audio."""
    with wave.open(path, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(MIC_RATE)
        for frame in frames:
            f.writeframes((np.clip(frame, -1, 1) * 32767).astype(np.int16).tobytes())
            yield frame


class Conversation:
    """One call: the voice-loop turn cycle, with speech detection in place of the talk key, and Sonnet beside it."""

    def __init__(self, line, frames, ear, mouth, brain, transcript, opening, max_seconds=300,
                 nobody_seconds=NOBODY_THERE_SECONDS, observer=None, nonce="", owner=None, language="en",
                 task_message=None, caller_id_name=""):
        self.task_message = task_message  # None when there's nobody to check for, and Haiku already has the task
        # On a call Pat answered: the name Haiku greets them by, from caller ID. Their reply to that greeting settles who they are.
        self.caller_id_name = caller_id_name
        self.confirmed = task_message is None
        self.reached = "not_checked" if task_message is None else "unclear"
        self.observer = observer
        self.nonce = nonce
        self.owner = owner or UserProfile().name or "the owner"
        self.language = language
        self.epoch = 0  # goes up each time the other person talks over Claude
        self.caller_turns = 0
        self.pending_note = None
        self.pending_cut = None
        self.generating = False
        self.nudges = 0
        self.wordless_replies = 0
        self.speech_ended_at = None
        self.reply_delays = []
        self.goodbye = False
        self.stopped = threading.Event()
        self.line = line
        self.frames = frames
        self.ear = ear
        self.mouth = mouth
        self.brain = brain
        self.transcript = transcript
        self.opening = opening
        self.max_seconds = max_seconds
        self.nobody_seconds = nobody_seconds
        self.finished = threading.Event()
        self.hand_over = threading.Event()
        self.take_over = threading.Event()
        self.caller_speaking = False
        self.sound = SoundMeter()
        self.turn_lock = threading.Lock()
        self.opening_done = threading.Event()
        self.opening_pending = False
        self.last_reply = []  # the pieces of Haiku's last reply, whether or not they were played

    def someone_talking(self):
        return self.caller_speaking or not self.mouth.idle()

    def _say_opening(self):
        with self.turn_lock:
            self.transcript.add("Claude", self.opening)
            self.mouth.say(self.opening, self.mouth.token)
            self.mouth.drain()
            self.opening_pending = True
            self.opening_done.set()

    def _supervisor(self, note):
        return f"[SUPERVISOR-{self.nonce}] {note}"

    def _speak_reply(self, message, token):
        """Streams one Haiku reply into the mouth. Returns its question, if it asked the supervisor instead."""
        splitter = Splitter(self.mouth.voice.clause_chars)
        question = []

        def speak(piece):
            for mark, reached in REACHED_MARKS.items():
                if mark in piece:
                    if self.task_message is not None:  # on a call Pat answered, code decides when they're known: _caller_known
                        self.reached = reached
                    piece = piece.replace(mark, "").strip()
            if question or ASK_MARK in piece:
                question.append(piece.replace(ASK_MARK, "").strip())
                return
            # After a cut, a reply still arriving from Haiku is never heard: not said, and not a goodbye.
            heard = token == self.mouth.token
            if END_MARK in piece:
                self.goodbye = heard
                piece = piece.replace(END_MARK, "").strip()
            if piece:
                self.last_reply.append(piece)
            if piece and heard:
                self.transcript.add("Claude", piece)
                self.mouth.say(piece, token, self._note_first_audio)
            elif piece:
                self.transcript.add("Pat", f"not spoken: {piece}")

        self.generating = True
        try:
            for delta in self.brain.ask(message):
                for piece in splitter.feed(delta):
                    speak(piece)
            for piece in splitter.flush():
                speak(piece)
        finally:
            self.generating = False
        return " ".join(question)

    def _note_first_audio(self):
        """How long the person waited, to measure on real calls. Counted from when Pat decided they had stopped."""
        ended, self.speech_ended_at = self.speech_ended_at, None
        if ended is not None:
            delay = time.monotonic() - ended
            self.reply_delays.append(round(delay, 2))
            self.transcript.add("Pat", f"first audio {delay:.2f} s after their speech ended, plus {END_FRAMES * FRAME / MIC_RATE:.1f} s of waiting to be sure they had")

    def _caller_known(self):
        """On a call Pat answered: from here on, Pat knows who called. From their reply to the caller ID name, or else from
        the sticky note's Person line, which a separate Claude fills in only from what they said."""
        if self.reached != "confirmed":
            self.reached = "confirmed"
            self.transcript.add("Status", "person confirmed")
            # Without this, Haiku asked again for a full name or contact details they had already given.
            self.pending_note = f"{self.pending_note} {KNOWN_CALLER}" if self.pending_note else KNOWN_CALLER

    def caller_named(self, facts):
        """The sticky note's facts changed. Its Person line is filled in only once they've said who they are."""
        if any(fact["label"] == "Person" and fact["value"] for fact in facts):
            self._caller_known()

    def _start_task(self, token):
        """Hands Haiku the task once it has marked the person confirmed. Until then it has nothing to reveal."""
        if self.confirmed or self.reached != "confirmed":
            return ""
        self.confirmed = True
        self.transcript.add("Status", "person confirmed; the task starts now")
        return self._speak_reply(self._supervisor(self.task_message), token)

    def _cut_speech(self):
        """Stops Claude, noting how much of a reply still under way the person probably heard."""
        if self.generating or not self.mouth.idle():
            heard = self.mouth.heard_so_far()
            self.pending_cut = heard
            self.transcript.add("Claude", f"(cut off, heard only: {heard})" if heard else HEARD_NOTHING)
        self.mouth.cancel()

    def _cut_note(self):
        """A note for Haiku about its last reply, or "" if it was heard in full."""
        heard, self.pending_cut = self.pending_cut, None
        return "" if heard is None else self._supervisor(cut_message(heard))

    def _repeat_unheard_question(self, text, live, token):
        """A bare yes/no cannot answer an unheard question or an unfinished read-back."""
        reply = " ".join(self.last_reply)
        heard = self.pending_cut
        if not live or heard is None or "?" not in reply or not is_bare_answer(text):
            return False
        if heard:
            main = confirmation_detail(reply)
            main_words = word_tokens(main or "")
            # Only the short closing tag may be missing. All substantive words must have played.
            if main is None or word_tokens(heard)[:len(main_words)] == main_words:
                return False
            if reply.startswith(heard):
                missing = reply[len(heard):].lstrip(" ,;:—–")
                splitter = Splitter(self.mouth.voice.clause_chars)
                self.last_reply = splitter.feed(missing) + splitter.flush()
        self.pending_cut = None
        repeated = " ".join(self.last_reply)
        note = (f'They said "{text}" over your last reply before hearing the full question or detail, so do not count that as its answer. '
                f'You then repeated the missing part: "{repeated}". Their new words below respond to that repetition.')
        self.pending_note = f"{self.pending_note} {note}" if self.pending_note else note
        self.transcript.add("Pat", "a bare answer before they could have heard the question, so it's said again")
        for piece in self.last_reply:
            self.transcript.add("Claude", piece)
            self.mouth.say(piece, token, self._note_first_audio)
        self.mouth.drain()
        return True

    def _say_stall(self, token):
        phrase = random.choice(STALLS[self.language])
        self.transcript.add("Claude", phrase)
        self.mouth.say(phrase, token)
        return phrase

    def _consult(self, question, token):
        """Haiku asked for help: the person hears "one moment" while Sonnet decides."""
        self.transcript.add("Pat", f"Haiku asks Sonnet: {question}")
        phrase = self._say_stall(token)
        note = self.observer.consult(question) if self.observer and self.confirmed else None
        fallback = f"Tell them you can't decide this and will pass it on to {self.owner}."
        note = note or (fallback if self.confirmed else "Ask them again whether you've reached the right person.")
        self.transcript.add("Pat", f"Sonnet answers: {note}")
        message = self._supervisor(f'You just said "{phrase}" to them. {note} Say your next line now, with no {ASK_MARK}.')
        if self._speak_reply(message, token):
            self._speak_reply(self._supervisor(f"No more questions. Tell them you will pass it on to {self.owner}."), token)

    def _turn(self, text, epoch, prompt=None):
        with self.turn_lock:
            # A reply to words they have since talked over still goes into Haiku's memory, but isn't spoken.
            live = epoch == self.epoch
            token = self.mouth.token if live else self.mouth.token - 1
            self.mouth.start_reply()
            if text and self._repeat_unheard_question(text, live, token):
                return
            self.last_reply = []
            if text:
                self.caller_turns += 1
                # Haiku greets them by the caller ID name in its first reply. Their next words accept that name or correct it.
                if self.task_message is None and self.caller_id_name and self.caller_turns == 2:
                    self._caller_known()
                message = re.sub(r"[\[\]]", " ", text)  # only Pat can write a supervisor mark
            else:
                message = self._supervisor(prompt or "They made a short sound, but speech recognition got no words. "
                                           "They may have answered you. Ask them briefly to repeat it, or say your next line if you weren't waiting for an answer.")
            if self.opening_pending:
                self.opening_pending = False
                opening_note = (f'The call is connected. The person has just heard this opening in full: "{self.opening}" '
                                "Their words below respond to that opening. Do not say the greeting again.")
                if self.task_message is not None:  # only the identity check's opening asks who they are
                    opening_note += (" If they clearly answer its identity question with yes, mark them confirmed now; "
                                     "do not ask the same identity question again. If their answer is unclear, clarify it.")
                message = f"{self._supervisor(opening_note)}\n{message}"
            if self.pending_note:
                message = f"{self._supervisor(self.pending_note)}\n{message}"
                self.pending_note = None
            cut_note = self._cut_note()
            if cut_note:
                message = f"{cut_note}\n{message}"
            try:
                question = self._speak_reply(message, token)
                question = self._start_task(token) or question
                if question and live:
                    self._consult(question, token)
                # Before the reply finishes playing, so a correction can still cut it off.
                self._maybe_review()
                self.mouth.drain()
                self._finish_if_goodbye(token)
            except Exception as error:
                print(f"[Claude error: {error}]", flush=True)
                self.finished.set()

    def _finish_if_goodbye(self, token):
        """Hangs up only if the goodbye was played to the end; if they talked over it, the call goes on."""
        if self.goodbye and token == self.mouth.token:
            self.finished.set()
        self.goodbye = False

    def _maybe_review(self):
        # Sonnet has the whole brief, so nothing from it can reach Haiku before the person is confirmed.
        if self.observer and self.confirmed and self.observer.due(self.caller_turns):
            threading.Thread(target=self._review, args=(self.caller_turns,), daemon=True).start()

    def _review(self, turn):
        advice = self.observer.review(turn)
        if advice["action"] == "none":
            return
        self.transcript.add("Pat", f"Sonnet {advice['action']} ({advice['reason']}): {advice['note']}")
        if advice["action"] == "steer":
            self.pending_note = advice["note"]
        else:
            self._correct(advice["note"])

    def _correct(self, note):
        """Sonnet changes what Haiku says: cut off the speech, say "one moment", speak again from the note."""
        self._cut_speech()
        with self.turn_lock:
            if self.finished.is_set():
                return
            token = self.mouth.token
            cut_note = self._cut_note()
            self.mouth.start_reply()
            self.last_reply = []
            phrase = self._say_stall(token)
            message = self._supervisor(f'You just said "{phrase}" to them. {note} Say your next line now, with no {ASK_MARK}.')
            if cut_note:
                message = f"{cut_note}\n{message}"
            try:
                self._speak_reply(message, token)
                self.mouth.drain()
                self._finish_if_goodbye(token)
            except Exception as error:
                print(f"[Claude error: {error}]", flush=True)
                self.finished.set()

    def _stop_reason(self, now, started, last_heard, speaking):
        if self.line.ended.is_set():
            return "caller left"
        if self.stopped.is_set():
            return "hung up on request"
        if self.hand_over.is_set():
            return "handed over"
        if self.take_over.is_set():
            return "taken over on the laptop"
        if self.finished.is_set():
            return "goodbye"
        if now - started > self.max_seconds:
            return "time limit"
        if now - last_heard > self.nobody_seconds and not speaking:
            return "nobody there"
        return None

    def run(self):
        """Returns why the call stopped: "goodbye", "caller left", "time limit", "nobody there" or "handed over"."""
        detector = SpeechDetector()
        try:
            return self._run(detector)
        finally:
            close = getattr(detector, "close", None)
            if close:
                close()

    def _run(self, detector):
        started = last_heard = turn_started = last_busy = time.monotonic()
        turns = TurnDetector(detector)
        loudest = 0.0
        threading.Thread(target=self._say_opening, daemon=True).start()
        for frame in self.frames:
            now = time.monotonic()
            reason = self._stop_reason(now, started, last_heard, turns.speaking)
            if reason:
                self.mouth.cancel()
                if reason == "nobody there" and not self.confirmed:
                    self.transcript.add("Claude", NOBODY_CAME[self.language])
                    self.mouth.say(NOBODY_CAME[self.language], self.mouth.token)
                    self.mouth.drain()
                self.transcript.add("Pat", f"call over: {reason}, loudest sound heard {loudest:.3f} of 1")
                return reason

            loudest = max(loudest, float(np.abs(frame).max()))
            self.sound.feed(frame)
            # Silence only counts from when Claude has finished talking.
            if self.generating or self.turn_lock.locked() or not self.mouth.idle():
                last_busy = now
            if self.confirmed and not turns.speaking and self.nudges < MAX_NUDGES and now - max(last_heard, last_busy) > NUDGE_SECONDS:
                self.nudges += 1
                last_busy = now
                self.transcript.add("Pat", f"no speech for {NUDGE_SECONDS} s, checking they're still there")
                prompt = "They have said nothing for a while, so they may not have heard you. Check briefly that they're still there, and repeat your last question."
                threading.Thread(target=self._turn, args=("", self.epoch, prompt), daemon=True).start()

            event = turns.feed(frame)
            self.caller_speaking = turns.speaking
            if event == "start":
                self.nudges = 0
                turn_started = now
                self.transcript.add("Pat", f"speech started, {now - started:.1f} s into the call")
                # The opening says this is an AI, so talking over it must not cut it off.
                if self.opening_done.is_set():
                    self._cut_speech()
                    self.epoch += 1
                self.ear.prepare()
                for block in turns.preroll:
                    self.ear.feed_block(block, MIC_RATE)
            elif event == "end":
                last_heard = now
                self.speech_ended_at = now
                self.transcript.add("Pat", f"speech ended after {now - turn_started:.1f} s")
                text = self.ear.end(tail=0)
                if text:
                    self.wordless_replies = 0
                    self.transcript.add("Them", text)
                else:
                    self.wordless_replies += 1
                    self.transcript.add("Pat", "speech detected, but recognition got no words")
                # Speech with no words may still have been their answer, so it gets a reply too, or the line goes quiet.
                if text or self.wordless_replies <= MAX_WORDLESS_REPLIES:
                    threading.Thread(target=self._turn, args=(text, self.epoch), daemon=True).start()
            elif turns.speaking:
                self.ear.feed_block(frame, MIC_RATE)
                last_heard = now
        return "caller left"


def word_tokens(text):
    return re.findall(r"\w+", text.casefold())


def confirmation_detail(reply):
    """The substantive text before a short final confirmation tag, if there is one."""
    clause = re.search(r"[^.!?;,]*\?\s*$", reply)
    if clause:
        words = set(word_tokens(clause.group()))
        main = reply[:clause.start()].rstrip(" ,;:.!?—–")
        if main and words & CONFIRMATION_CUES and words <= CONFIRMATION_WORDS:
            return main
    ending = CONFIRMATION_END.search(reply)
    if ending:
        return reply[:ending.start()].rstrip(" ,;:.!?—–") or None
    return None


def cut_message(heard):
    """What Haiku is told about a reply they talked over. Someone saying yes before the question reached them hasn't answered it."""
    if heard:
        return (f'You were cut off during your last reply. They heard only: "{heard}". '
                "A plain yes or no can answer a complete question or confirm a complete statement or value in those heard words, "
                "even if only a short closing question such as 'Is that right?' was clipped. Use that answer: agreement confirms it; "
                "disagreement rejects it, so ask for the correction if needed. Move on from an accepted detail; "
                "do not ask them to confirm the same unchanged details again. "
                "Every substantive value needed by that question or read-back must be in the heard words; a greeting, thanks or setup alone is not enough. "
                "If the actual question or a needed value was not heard, ask it again, and don't count it as answered. "
                "Repeat only the missing question or detail, not the greeting or setup they already heard. "
                "If their words answer it by themselves, go by those. Say the rest again only if it still matters.")
    return ("You were cut off during your last reply. They heard none of it. So a plain yes or no now can't answer anything they didn't hear: "
            "if you asked something they didn't hear, ask it again now, and don't count it as answered. If their words answer it by themselves, go by those. "
            "Say the rest again only if it still matters.")


def find_output(name):
    for index, device in enumerate(sd.query_devices()):
        api = sd.query_hostapis(device["hostapi"])["name"]
        if "WASAPI" in api and name in device["name"] and device["max_output_channels"] > 0:
            return index
    return None


def silent_speakers():
    chosen = os.environ.get("PAT_SILENT_SPEAKER") or os.environ.get("CICERO_SILENT_SPEAKER")  # its old name too
    return (chosen, *SILENT_SPEAKERS) if chosen else SILENT_SPEAKERS


def find_silent_speaker(find=None):
    """The first silent speaker on this laptop, or None."""
    find = find or find_output
    return next((name for name in silent_speakers() if find(name) is not None), None)


_software_devices = {"names": None, "at": 0.0}
SOFTWARE_DEVICES_FOR = 60  # seconds before the list of software devices is read again, for a driver installed meanwhile


def software_devices():
    """Speakers and microphones that belong to a software driver, read from Windows at most once a minute."""
    if _software_devices["names"] is None or time.monotonic() - _software_devices["at"] > SOFTWARE_DEVICES_FOR:
        try:
            from audio_defaults import WindowsAudio
            names = WindowsAudio().software_devices()
        except Exception:  # no registry to read: the name checks still apply
            names = set()
        _software_devices.update(names=names, at=time.monotonic())
    return _software_devices["names"]


def is_pats_virtual_device(name):
    """The cable, the silent speaker or a phone's call audio: the virtual devices Pat itself uses."""
    return any(virtual in name for virtual in ("CABLE", "Hands-Free", "Voicemeeter", *silent_speakers()))


def is_virtual_device(name):
    """Not a real speaker or microphone: one of Pat's own virtual devices, or any other software device, such as a
    screen-sharing app's speaker, which plays nowhere. One was a tester's default for calls, so Listen and take-over
    played into it and he heard nothing (7 Nov 2026)."""
    return is_pats_virtual_device(name) or name in software_devices()


def pick_real_device(devices):
    """The first (index, name) that's a real speaker or microphone, not the cable or the silent speaker. If every device
    looks like software, as on a laptop whose own speakers come through a software driver, only Pat's own count as virtual."""
    for check in (is_virtual_device, is_pats_virtual_device):
        for index, name in devices:
            if not check(name):
                return index
    return None


def real_defaults():
    """Moves any default (everyday, media or calls) that points at a virtual device to the real speaker and microphone.
    A virtual default is silent while Voicemeeter is closed, so Zoom or WhatsApp would neither hear nor be heard.
    With Voicemeeter running, they carry sound and were probably chosen on purpose, so nothing changes.
    Returns what changed. Real defaults are left alone."""
    from audio_defaults import mixer_running
    if mixer_running():
        return []
    speaker, microphone = real_devices()
    names = [sd.query_devices(device)["name"] if device is not None else None for device in (speaker, microphone)]
    # Only Pat's own drivers: another app's virtual default, such as a screen-sharing speaker, may be there on purpose.
    return repair_defaults(*names, is_pats_virtual_device)


def preferred_device(devices, chosen):
    """The first real device among those the owner picked in Windows, or else the first real one."""
    for wanted in chosen:
        for index, name in devices:
            if name == wanted and not is_virtual_device(name):
                return index
    return pick_real_device(devices)


def real_devices(chosen=None):
    """Returns (speaker, microphone) to use when the owner takes over: the ones picked in Windows, as they were before the
    call switched them. Either can be None if there's none."""
    wasapi = [(index, device) for index, device in enumerate(sd.query_devices())
              if "WASAPI" in sd.query_hostapis(device["hostapi"])["name"]]
    if chosen is None:
        try:
            chosen = chosen_devices(os.path.join(HERE, "calls"))
        except OSError:
            chosen = ((), ())
    return (preferred_device([(i, d["name"]) for i, d in wasapi if d["max_output_channels"] > 0], chosen[0]),
            preferred_device([(i, d["name"]) for i, d in wasapi if d["max_input_channels"] > 0], chosen[1]))


def check_microphone(seconds=3, record=None):
    """For setup: records a few seconds from the microphone Pat uses when you take over. Returns (fine, what to say)."""
    microphone = real_devices()[1]
    if microphone is None:
        return False, "No microphone found, so you can't take over calls on the laptop."
    info = sd.query_devices(microphone)
    rate, channels = int(info["default_samplerate"]), int(info["max_input_channels"])
    if record is None:
        def record():
            audio = sd.rec(int(seconds * rate), samplerate=rate, channels=channels, dtype="float32", device=microphone)
            sd.wait()
            return audio
    try:
        peak = float(np.max(np.abs(record())))
    except Exception as error:
        return False, f"Couldn't open '{info['name']}': {error}"
    if peak == 0:
        return False, (f"'{info['name']}' sent only silence. It's muted, or Windows doesn't let apps use it: Settings > "
                       "Privacy & security > Microphone, turn on 'Let desktop apps access your microphone'.")
    if peak < QUIET_MIC:
        return False, f"'{info['name']}' works but is very quiet ({peak:.3f}). Raise its level in Windows' sound settings."
    return True, f"'{info['name']}' works (loudest {peak:.2f})."


def connected_headsets(endpoints=None):
    """Other hands-free devices, excluding the selected phone by Windows identity rather than its name."""
    from bluetooth_audio import blocking_devices
    if endpoints is None:
        try:
            command = phone_command()
            result = subprocess.run(command + ["audio-devices-json"], capture_output=True,
                                    text=True, encoding="utf-8", errors="replace", timeout=20)
            if result.returncode or len(result.stdout) > 1024 * 1024:
                raise ValueError("phone helper inventory failed")
            endpoints = json.loads(result.stdout)
            if "--device-id" in command:
                selected = command[command.index("--device-id") + 1]
                actual = (endpoints.get("phone") or {}).get("id") if isinstance(endpoints, dict) else None
                if not isinstance(actual, str) or actual.casefold() != selected.casefold():
                    raise ValueError("selected phone was not found")
        except (OSError, ValueError, subprocess.TimeoutExpired) as error:
            raise OSError("Could not check Bluetooth audio devices. Choose your phone in Pat's settings; "
                          "if the helper is outdated, quit Pat and run setup.ps1.") from error
    return blocking_devices(endpoints)


def speaker_problem(speaker):
    """Why this default speaker won't do for --audible, or None."""
    if CABLE_PLAY in speaker:
        return (f"Default speaker is '{speaker}'. It must not be the cable, "
                "or Claude would hear itself instead of the other person.")
    return None


def find_input(name):
    for index, device in enumerate(sd.query_devices()):
        api = sd.query_hostapis(device["hostapi"])["name"]
        if "WASAPI" in api and name in device["name"] and device["max_input_channels"] > 0:
            return index
    return None


def check_audio_setup(audible=False):
    """The things Pat can't fix itself. Stops before any call rather than on a silent line."""
    problems = []
    try:
        headsets = connected_headsets()
    except OSError as error:
        problems.append(str(error))
        headsets = []
    for headset in headsets:
        problems.append(f"'{headset}' is connected. Disconnect it from the laptop, or the call's audio stays on the "
                        "phone and the other person hears nothing. To keep listening to the laptop on it, untick Handsfree "
                        "Telephony in its Bluetooth Services instead (see README.md).")
    if find_output(CABLE_PLAY) is None or find_input(CABLE_HEAR) is None:
        problems.append(f"'{CABLE_PLAY}' or '{CABLE_HEAR}' not found. Install VB-CABLE (see README.md) and restart.")
    if audible:
        wasapi = next((a for a in sd.query_hostapis() if "WASAPI" in a["name"]), None)
        speaker = sd.query_devices(wasapi["default_output_device"])["name"] if wasapi["default_output_device"] >= 0 else ""
        problem = speaker_problem(speaker)
        if problem:
            problems.append(problem)
    elif find_silent_speaker() is None:
        problems.append("No silent speaker found, so you would hear the call. Install Voicemeeter (free, see README.md) "
                        "and restart, or use --audible to hear it.")
    return problems


def open_cable(rate):
    return sd.OutputStream(samplerate=rate, channels=1, dtype="float32", latency="low", device=find_output(CABLE_PLAY),
                           extra_settings=sd.WasapiSettings(auto_convert=True))


def only_one_copy():
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    handle = kernel32.CreateMutexW(None, False, "Local\\PatSingleCopy")
    error = ctypes.get_last_error()
    if error == 183:  # ERROR_ALREADY_EXISTS
        sys.exit("Pat is already on a call in another window.")
    if not handle and error == 5:  # ERROR_ACCESS_DENIED: the other copy was started as administrator
        sys.exit("Pat is already on a call in a window started as administrator.")


def load_speech(language, voice):
    """Returns (ear, mouth), with the mouth not yet connected to any speaker."""
    from speech_service import available, RemoteEar, RemoteVoice
    status = available()
    if status:
        selected = voice or (RU_TTS_VOICE if language == "ru" else DEFAULT_ENGLISH_VOICE)
        ear = RemoteEar(status, language)
        try:
            speaker = RemoteVoice(status, language, selected)
            mouth = TrackingMouth(speaker, play=False)
        except Exception:
            ear.close()
            raise
        if language == "en":
            mouth.slow_rate = ENGLISH_VOICES.get(selected, {}).get("chars_per_second", SLOW_CHARS_PER_SECOND)
        return ear, mouth
    if language == "ru":
        return BatchEar(RU_STT_MODEL, mic=False), TrackingMouth(PiperVoice(voice or RU_TTS_VOICE), play=False)
    voice = voice or DEFAULT_ENGLISH_VOICE
    mouth = TrackingMouth(PocketVoice(TTS_LANGUAGE, voice), play=False)
    mouth.slow_rate = ENGLISH_VOICES.get(voice, {}).get("chars_per_second", SLOW_CHARS_PER_SECOND)
    return BatchEar(EN_STT_MODEL, mic=False), mouth


def prepare_models():
    """Downloads now what a first call would otherwise stop to download."""
    SpeechDetector()
    for language, voices in (("ru", ("irina", "ruslan")), ("en", tuple(ENGLISH_VOICES))):
        for voice in voices:  # any of them can be chosen from the note's menu, and a call shouldn't stop to download one
            print(f"Loading {language} speech ({voice})...", flush=True)
            load_speech(language, voice)
    print("Speech models are ready.")
    say_watson()


def say_watson(eggs=None, make_mouth=None):
    """Once, at the end of setup, aloud: the first words ever said on a telephone. Nothing depends on this working."""
    eggs = eggs or EasterEggs()
    if eggs.seen("watson_spoken"):
        return
    eggs.mark("watson_spoken")
    print(WATSON, flush=True)
    try:
        mouth = (make_mouth or (lambda: Mouth(PocketVoice(TTS_LANGUAGE, DEFAULT_ENGLISH_VOICE))))()
        mouth.say(WATSON, mouth.token)
        mouth.drain()
    except Exception as error:
        print(f"Setup: couldn't say that aloud: {error}", flush=True)


def use_call_devices(devices, audible):
    """Just before the call, so the laptop keeps its sound while Pat loads."""
    devices.use(speaker=None if audible else find_silent_speaker(), mic=CABLE_HEAR)


def load_brief(args):
    if args.brief_file:
        with open(args.brief_file, encoding="utf-8") as f:
            brief = CallBrief.from_dict({"language": args.lang, **json.load(f)})
    else:
        brief = CallBrief.from_dict({"goal": args.brief or DEFAULT_ANSWER_GOAL, "language": args.lang, "name": args.name,
                                     "company": args.company, "confidence": args.confidence if (args.name or args.company) else ""})
    brief.incoming = args.action == "answer"
    return brief


def tell_caller_name(brain, name, nonce):
    """A name caller_names.py found in the caller's label, so Haiku can greet them by it. Nothing when there's none."""
    if name:
        for _ in brain.ask(caller_id_message(name, nonce)):
            pass


def start_brain(args, brief, opening, nonce, notes):
    print("Starting Claude...", flush=True)
    prompt = brief.haiku_prompt(SYSTEM_PROMPTS[brief.language], opening, args.owner, nonce, notes)
    try:
        brain = Brain(brief.language, system_prompt=prompt)
        for _ in brain.ask(f"[SUPERVISOR-{nonce}] {WARM_UP[brief.language]}"):
            pass
    except Exception as error:  # marked as Claude's, so the note can say it in plain words (claude_errors)
        raise RuntimeError(f"{claude_errors.STARTING}{error}") from error
    return brain


def start_observer(args, brief, transcript):
    """Returns (observer, its Claude). A call can go on without Sonnet if Sonnet won't start."""
    if args.no_observer:
        return None, None
    try:
        sonnet = Brain("en", system_prompt=brief.observer_prompt(args.owner), model=OBSERVER_MODEL)
    except Exception as error:
        print(f"[Sonnet won't be watching this call: {error}]", flush=True)
        return None, None
    return Observer(lambda text: "".join(sonnet.ask(text)), transcript.spoken, args.owner), sonnet


def write_result(args, **result):
    """What phone_mcp.py hands back to the agent that asked for the call."""
    if args.result_file:
        temporary = args.result_file + ".tmp"
        with open(temporary, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=1)
        os.replace(temporary, args.result_file)


def load_notes(key, args):
    """Returns (notes, what to tell Claude). No notes for a hidden number, or with --no-memory."""
    if args.no_memory or not key:
        return None, ""
    notes = ContactNotes(key)
    if notes.calls:
        print(f"Known number: {notes.calls} earlier calls, last {notes.last_call}. {notes.path}", flush=True)
    return notes, notes.for_prompt(args.owner)


def remember_call(notes, transcript, owner, brief, reached):
    """Runs after the hang-up. The summary, if it may change, comes from a separate Claude that sees only the notes and the transcript."""
    print("Updating notes for this number...", flush=True)
    when = current_time().isoformat(timespec="minutes")
    attempt = attempt_text(reached, brief.name.strip() or brief.company.strip())
    if not summary_may_change(reached, brief.who_answers()):
        report = merge_call(notes, transcript.spoken, None, when, attempt=attempt, update_summary=False)
        print(report, notes.path)
        return report
    brain = None
    try:
        brain = Brain("en", system_prompt=SUMMARY_PROMPT.format(owner=owner, limit=SUMMARY_LIMIT))
        report = merge_call(notes, transcript.spoken, lambda text: "".join(brain.ask(text)), when, attempt=attempt)
        print(report, notes.path)
        return report
    except Exception as error:
        report = f"Notes not updated: {error}. The transcript is still in {transcript.path}"
        print(report)
        return report
    finally:
        if brain:
            brain.close()


def listen_for_keys(line, conversation):
    def run():
        for typed in sys.stdin:
            typed = typed.strip().lower()
            if typed == "h":
                conversation.stopped.set()
            elif typed == "p":
                line.to_phone()
                conversation.hand_over.set()
            elif typed == "l":
                conversation.take_over.set()
    threading.Thread(target=run, daemon=True).start()


def watch_take_over_key(conversation, is_down=None):
    """F9 works whichever window is in front, including when an agent placed the call and there's no terminal to type in."""
    is_down = is_down or (lambda: ctypes.windll.user32.GetAsyncKeyState(TAKE_OVER_KEY) & 0x8000)

    def run():
        while not conversation.take_over.is_set():
            if is_down():
                conversation.take_over.set()
                return
            time.sleep(0.05)
    threading.Thread(target=run, daemon=True).start()


def wait_for_go(go, cancelled, line):
    """True once told to pick up. False if told not to, or the call stopped ringing. The models are ready either way."""
    while not (go.is_set() or cancelled.is_set() or line.ended.is_set()):
        if getattr(line, "ringing", None) is not None and not line.ringing.is_set():
            return False
        time.sleep(0.05)
    still_ringing = getattr(line, "ringing", None) is None or line.ringing.is_set()
    return go.is_set() and not cancelled.is_set() and not line.ended.is_set() and still_ringing


def wait_for_current_incoming(line, cancelled, seconds=15):
    """A note request belongs to the call that is ringing now, not a later call."""
    deadline = time.monotonic() + seconds
    while not cancelled.is_set() and not line.ended.is_set():
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None
        try:
            status, who, _ = line.events.get(timeout=min(0.1, remaining))
        except queue.Empty:
            continue
        if status == "Incoming":
            return (status, who) if getattr(line, "ringing", None) is None or line.ringing.is_set() else None
        if status in ("Talking", "Ended", "Closed"):
            return None
    return None


def start_live_notes(brief, spoken_so_far):
    """Returns (notes, its Claude). Its own Claude, started beside the call, so a failure here costs only the bullet points."""
    wanted = list(brief.need_from_them) or ["Who is calling", "Why they are calling", "Any message for the owner"]
    labels = ["Person"] if brief.name.strip() else []
    brain = Brain("en", system_prompt=NOTES_PROMPT)
    notes = LiveNotes(lambda text: "".join(brain.ask(text)), wanted, labels if brief.need_from_them else INCOMING_LABELS)
    notes.request(spoken_so_far)
    return notes, brain


def stay_on_laptop(conversation, line, caller, mouth, args, brief, cable, tell=None, headsets=None):
    """The owner talks from here on, until the call ends or they hang up or move it to the phone. Claude says nothing more."""
    tell = tell or (lambda text: print(text, flush=True))
    found, check_errors = [], []
    def check_headsets():
        try:
            found.extend((headsets or connected_headsets)())
        except OSError as error:
            check_errors.append(str(error))
    checking = threading.Thread(target=check_headsets, daemon=True)
    checking.start()
    phrase = TAKING_OVER[brief.language].format(owner=args.owner, owner_ru=args.owner_ru)
    mouth.say(phrase, mouth.token)
    mouth.drain()
    checking.join(25)
    blocked = ("Bluetooth audio check timed out. Use your phone." if checking.is_alive() else
               check_errors[0] if check_errors else headset_problem(found))
    if blocked:  # a headset that connected during the call: Windows would say the audio moved, but it stays on the phone
        tell(blocked)
        line.to_phone()
        conversation.hand_over.set()
        return
    speaker, microphone = real_devices()
    if speaker is None or microphone is None:
        print("Can't take over: no real speaker or microphone found. Moving the call to your phone instead.", flush=True)
        line.to_phone()
        conversation.hand_over.set()
        return
    takeover = None
    try:
        takeover = LaptopTakeover(caller, speaker, microphone, cable)
        takeover.start()
        print("You're on the call. Use wired headphones, or they'll hear an echo. Type h to hang up, p to move it to your phone.", flush=True)
        while not (line.ended.is_set() or conversation.stopped.is_set() or conversation.hand_over.is_set()):
            problem = takeover.problem()
            if problem:
                raise RuntimeError(problem)
            time.sleep(0.1)
    except Exception as error:
        print(f"Laptop audio failed: {error}. Moving the call to your phone.", flush=True)
        line.to_phone()
        conversation.hand_over.set()
    finally:
        if takeover:
            takeover.stop()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("action", choices=["dial", "answer", "check", "prepare", "restore-audio", "fix-audio", "check-mic", "pick-phone"],
                        help="check tests the setup. prepare downloads the speech models. restore-audio puts back the default "
                             "speaker and microphone after a call that was killed. fix-audio moves them off any virtual device. "
                             "check-mic records 3 seconds to see that your microphone sends sound. pick-phone checks that a phone is connected "
                             "for calls. "
                             "None of these makes a call")
    parser.add_argument("number", nargs="?", help="number to dial, in international format")
    parser.add_argument("--brief", help="what Claude should do on this call, in one sentence")
    parser.add_argument("--brief-file", help="a full call brief as JSON; see call_brief.py")
    parser.add_argument("--result-file", help="write the outcome here as JSON when the call is over")
    parser.add_argument("--no-observer", action="store_true", help="no Sonnet on this call")
    parser.add_argument("--summary-style", choices=sorted(POEM_PROMPTS), help="add this poem under the call's summary")
    parser.add_argument("--wait-for-go", action="store_true", help="answer: get ready when it rings, and pick up only when the sticky note says so")
    parser.add_argument("--name", default="", help="who you're calling; Claude checks it reached them before the task")
    parser.add_argument("--company", default="", help="their company; with no --name, anyone there can help")
    parser.add_argument("--confidence", choices=["confirmed", "guess", "unknown"], default="guess",
                        help="how sure you are the number is theirs")
    parser.add_argument("--lang", choices=sorted(SYSTEM_PROMPTS), default="en", help="call language (default: English)")
    parser.add_argument("--voice", default=None, help=f"Russian: irina or ruslan. English: {', '.join(ENGLISH_VOICES)}")
    parser.add_argument("--owner", default=None, help="override the name saved in Pat's settings for this call")
    parser.add_argument("--owner-ru", default=None, help="optional spoken Russian version of the owner's name")
    parser.add_argument("--time-zone", help="IANA time zone for this call, such as Europe/London")
    parser.add_argument("--date-format", choices=["iso", "dmy", "mdy"], help="date format for this call's reports")
    parser.add_argument("--max-minutes", type=float, default=5, help="hang up after this long")
    parser.add_argument("--audible", action="store_true", help="play the call on your real speaker instead of silently")
    parser.add_argument("--no-memory", action="store_true", help="don't read or update this number's notes")
    parser.add_argument("--save-audio", action="store_true",
                        help="keep the other person's audio in calls/. Only with their agreement")
    args = parser.parse_args()
    if args.action == "dial" and not (args.number and (args.brief or args.brief_file)):
        parser.error("dial needs a number and --brief or --brief-file")
    if args.action in ("dial", "answer"):
        refusal = setup_refusal()
        if refusal:
            write_result(args, **refusal)
            sys.exit(refusal["reason"])
        profile = UserProfile()
        owner_names = profile.names if args.owner in (None, profile.name) else {}  # a different --owner has no saved spellings
        if args.owner_ru:
            owner_names = {**owner_names, "ru": args.owner_ru}
        args.owner = args.owner or profile.name
        args.owner_ru = owner_names.get("ru") or args.owner
        if args.action == "dial":
            try:
                args.number = international_number(args.number)
            except ValueError as error:
                write_result(args, status="failed", reason=str(error))
                parser.error(str(error))
        try:
            brief = load_brief(args)
            args.owner = owner_names.get(brief.language) or args.owner  # the name as this call's language writes it
            configure_dates(args.time_zone or brief.time_zone or None, args.date_format or brief.date_format or None)
            from real_dates import preferences
            brief.time_zone, brief.date_format = preferences()
        except (ValueError, KeyError, TypeError) as error:
            write_result(args, status="failed", reason=str(error))
            parser.error(str(error))

    only_one_copy()
    if args.action == "prepare":
        prepare_models()
        return
    devices = CallDevices(os.path.join(HERE, "calls"))
    for problem in devices.restore():  # a call that was killed can leave them switched
        print(f"Setup: {problem}")
    if args.action == "restore-audio":
        print("Default speaker and microphone are back as they were.")
        return
    if args.action == "fix-audio":  # setup runs this after the drivers go in
        changed = real_defaults()
        print("\n".join(changed) if changed else "Default speaker and microphone are already the real ones.")
        return
    if args.action == "pick-phone":
        name = pick_phone()
        print(f"Phone ready: {name}" if name else "No phone has a working call line yet.")
        sys.exit(0 if name else 1)
    if args.action == "check-mic":
        fine, message = check_microphone()
        print(message)
        sys.exit(0 if fine else 1)
    problems = check_audio_setup(args.audible)
    for problem in problems:
        print(f"Setup: {problem}")
    if problems:
        write_result(args, status="failed", reason=" ".join(problems))
        sys.exit(1)
    if args.action == "check":
        print(f"Audio setup is fine. Calls will use: {find_silent_speaker() or 'your default speaker'}.")
        return

    logging.disable(logging.INFO)
    calls_folder = os.path.join(HERE, "calls")
    # The note can say "go" before this process has finished starting. It clears old commands itself.
    display_book = PrivateNumbers()
    live = LiveCall(calls_folder, keep_commands=args.wait_for_go, stage="starting", number=args.number or "", name=brief.target() or display_book.display_name(args.number or ""), facts=[], summary="",
                    talking=False, listening=False)
    go = threading.Event()
    cancelled = threading.Event()
    live.handlers.update({"go": go.set, "cancel": cancelled.set})
    opening = OPENINGS[args.action][brief.language].format(owner=args.owner, owner_ru=args.owner_ru)
    if brief.has_target():
        opening = f"{opening} {brief.check_question()}"
    nonce = secrets.token_hex(4)  # the person can't say this, so they can't pose as the supervisor
    print("Loading speech models...", flush=True)
    ear, mouth = load_speech(brief.language, args.voice or NoteSettings(calls_folder).voice_for(brief.language))
    mouth.out = CableOutput(open_cable(mouth.sample_rate))
    mouth.out.start()
    brain = None
    notes = None
    key = None
    known = ""
    if args.action == "dial":
        # Started before dialing, so a Claude failure can't leave someone on a silent call.
        key = number_key(args.number)
        notes, known = load_notes(key, args)
        try:
            brain = start_brain(args, brief, opening, nonce, known)
        except RuntimeError as error:
            write_result(args, status="failed", reason=claude_errors.plain_reason(error))
            live.close()
            sys.exit(str(error))

    print("Connecting to your phone...", flush=True)
    os.makedirs(os.path.join(HERE, "calls"), exist_ok=True)
    phone_log = os.path.join(HERE, "calls", f"phone-{datetime.datetime.now():%Y%m%d-%H%M%S}.log")
    line = PhoneLine(log_path=phone_log)
    if not line.wait_ready():
        print("\n".join(line.started))
        taken = f"{PhoneLine.TAKEN_MESSAGE} " if line.taken_by_another_app() else ""
        write_result(args, status="failed", reason=f"{taken}iphonecall did not start: " + " | ".join(line.started))
        live.close()
        if brain:
            brain.close()
        sys.exit("iphonecall did not start. Its lines above say which step failed.")

    caller = None
    conversation = None
    frames = None
    transcript = None
    observer = None
    sonnet = None
    notes_brain = None
    live_notes = None
    listening = None
    left_ringing = False
    status = "no_answer"
    reason = "the call was not answered"
    picked_up = None
    caller_name = caller_id = ""
    try:
        if args.action == "dial":
            print(f"Dialing {args.number}. Claude's task: {brief.goal}", flush=True)
            use_call_devices(devices, args.audible)
            line.dial(args.number)
            answered = line.wait_for(["Talking"], seconds=90)
        else:
            print("Waiting for a call. Claude will answer the next one. Ctrl+C quits.", flush=True)
            answered = None
            incoming = wait_for_current_incoming(line, cancelled) if args.wait_for_go else line.wait_for(["Incoming"])
            if args.wait_for_go and not incoming:
                left_ringing = True
                reason = "the requested incoming call stopped ringing"
                return
            if incoming and incoming[0] == "Incoming":
                print(f"Incoming: {incoming[1]}", flush=True)
                # Only now is the number known, so Claude starts with the right notes while it rings.
                key = number_key(incoming[1])
                notes, known = load_notes(key, args)
                caller_id = display_book.display_name(incoming[1])
                spoken_name = CallerNames().start(caller_id)  # checked while Claude starts; never the number
                brain = start_brain(args, brief, opening, nonce, known)
                live.update(stage="ringing", number=incoming[1], name=caller_id)
                caller_name = spoken_name()
                tell_caller_name(brain, caller_name, nonce)
                if args.wait_for_go and not wait_for_go(go, cancelled, line):
                    left_ringing = True
                    reason = "the sticky note took this call, or it stopped ringing"
                    return
                use_call_devices(devices, args.audible)
                line.answer()
                answered = line.wait_for(["Talking"], seconds=30)
        if not answered or answered[0] != "Talking":
            if not answered:
                reason = "nobody picked up in time"
            elif answered[0] == "Closed":
                reason = "iphonecall stopped during dialing; the call may still be live on the phone"
            else:
                reason = "the call ended before anyone picked up"
            print(f"No conversation: {reason}. Details: {phone_log}")
            return

        if not line.wait_for_laptop_audio(AUDIO_MOVE_SECONDS):
            status = "failed"
            reason = "the call audio stayed on the phone, so Claude could not hear or speak; hung up"
            print(f"No conversation: {reason}. Details: {phone_log}")
            return
        picked_up = time.monotonic()
        time.sleep(AFTER_PICKUP_SECONDS)
        caller = CallerAudio()
        print(f"Connected. Hearing through: {caller.name}. Press F9 or type l to take the call on the laptop, p to move it to your phone, h to hang up.", flush=True)
        transcript = Transcript(key=key)
        transcript.add("Pat", f"task: {brief.text()}")
        transcript.add("Pat", f"hearing through: {caller.name}; call audio: {line.audio}")
        observer, sonnet = start_observer(args, brief, transcript)
        if caller_name:
            transcript.add("Status", f"caller ID name: {caller_name}")
        if observer and brief.incoming:
            observer.caller_id = (caller_name, caller_id)
        live.update(stage="talking")
        frames = caller.frames()
        if args.save_audio:
            frames = saved_frames(frames, transcript.path.replace(".txt", ".wav"))
        conversation = Conversation(line, frames, ear, mouth, brain, transcript, opening,
                                    max_seconds=args.max_minutes * 60, observer=observer, nonce=nonce,
                                    owner=args.owner, language=brief.language,
                                    task_message=brief.task_message(args.owner, known) if brief.has_target() else None,
                                    caller_id_name=caller_name)
        listen_for_keys(line, conversation)
        watch_take_over_key(conversation)

        def start_notes():
            nonlocal live_notes, notes_brain
            try:
                live_notes, notes_brain = start_live_notes(brief, transcript.spoken)
            except Exception as error:
                print(f"[no bullet points on the sticky note: {error}]", flush=True)
                return
            transcript.on_them = live_notes.request
            if brief.incoming and not caller_name:
                live_notes.on_facts = lambda facts: conversation.caller_named(facts)

        def set_listening(on):
            nonlocal listening
            if on and listening is None:
                speaker = real_devices()[0]
                print(f"Pat: listening on {sd.query_devices(speaker)['name'] if speaker is not None else 'no speaker found'}", flush=True)
                listening = Listening(caller, mouth.out, mouth.sample_rate, speaker)
            elif not on and listening is not None:
                listening.stop()
                listening = None

        def move_to_phone():
            line.to_phone()
            conversation.hand_over.set()

        threading.Thread(target=start_notes, daemon=True).start()
        live.sources.update({"talking": conversation.someone_talking, "level": lambda: max(conversation.sound.take(), mouth.out.sound.take()), "listening": lambda: listening is not None,
                             "facts": lambda: live_notes.facts if live_notes else [],
                             "summary": lambda: live_notes.summary if live_notes else ""})
        live.handlers.update({"listen on": lambda: set_listening(True), "listen off": lambda: set_listening(False),
                              "take-over": conversation.take_over.set, "to-phone": move_to_phone, "hang-up": conversation.stopped.set})
        status = "done"
        reason = conversation.run()
        set_listening(False)
        if conversation.take_over.is_set() and not line.ended.is_set():
            live.update(stage="handed")
            stay_on_laptop(conversation, line, caller, mouth, args, brief, find_output(CABLE_PLAY),
                           tell=lambda text: (print(text, flush=True), live.update(notice=text)))
        print(f"Call over: {reason}. Transcript: {transcript.path}")
    except KeyboardInterrupt:
        print("Stopping.")
        reason = "stopped by hand"
    except Exception as error:
        status = "failed"
        reason = str(error)
        raise
    finally:
        seconds = round(time.monotonic() - picked_up) if picked_up else None
        if frames:
            frames.close()  # finishes the WAV, if one is being saved
        if caller:
            caller.close()
        if listening:
            listening.stop()
        handed_over = conversation is not None and conversation.hand_over.is_set()
        if not (handed_over or left_ringing):
            # Always, even if no call seems active: leaving would strand a real person on a silent line.
            line.hang_up()
            time.sleep(1)
        line.close()
        switched = os.path.exists(devices.path)  # only a call Pat switched the defaults for
        for problem in devices.restore():
            print(f"Setup: {problem}")
        try:  # what was there before can itself be virtual, such as Voicemeeter as the device for calls
            for change in real_defaults() if switched else []:
                print(f"Audio: {change}")
        except (OSError, LookupError, sd.PortAudioError) as error:
            print(f"[couldn't check the default audio devices: {error}]", flush=True)
        if not handed_over:
            live.update(stage="wrapping")
        if live_notes:
            live_notes.close()
        if notes_brain:
            notes_brain.close()
        if brain:
            brain.close()
        for resource in (ear, getattr(mouth, "voice", None)):
            close = getattr(resource, "close", None)
            if close:
                close()
        reached = conversation.reached if conversation else None
        report = observer.final_report(f"{reason} (who was reached: {reached})") if observer else None
        if sonnet:
            sonnet.close()
        notes_report = None
        if notes and transcript:
            notes_report = remember_call(notes, transcript, args.owner, brief, reached)
        elif notes:
            notes.add_attempt(current_time().isoformat(timespec="minutes"), reason)  # same zone and form as remember_call's
            notes.save()
        eggs = EasterEggs()
        flair = eggs.flair() if seconds else []
        pat_facts = eggs.after_call(seconds, reason, reached) if seconds and transcript else []  # for the note only, never in the agent's result
        last_call = None
        if transcript:
            facts, summary, contact_question = final_note(report, live_notes.facts if live_notes else [], live_notes.summary if live_notes else "")
            last_call = dict(id=os.path.basename(transcript.path), number=live.fields.get("number", ""), name=live.fields.get("name") or brief.target() or display_book.display_name(live.fields.get("number", "")),
                             facts=facts, summary=summary, contact_question=contact_question, flair=flair, pat_facts=pat_facts)
        poem = ""
        if args.summary_style and report:
            if last_call:  # the summary shows at once, and the poem joins it
                write_last_call(calls_folder, **last_call, poem_style=args.summary_style, poem_pending=True)
            poem = write_poem(args.summary_style, report, lambda model: Brain("en", system_prompt="You write short, funny pieces about phone calls, for the person who asked for the call.", model=model))
        write_result(args, status=status, reason=reason, report=report, notes=notes_report, flair=flair, poem=poem,
                     number=args.number, seconds=seconds, reached=reached, target=brief.target(),
                     time_zone=brief.time_zone, date_format=brief.date_format,
                     reply_delays=conversation.reply_delays if conversation else [],
                     transcript_file=transcript.path if transcript else None,
                     interventions=observer.interventions if observer else 0,
                     reviews=observer.reviews if observer else 0)
        if last_call:
            write_last_call(calls_folder, **last_call, poem=poem, poem_style=args.summary_style if poem else "")
        live.close()


if __name__ == "__main__":
    main()
