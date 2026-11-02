"""Claude speaks on your iPhone calls: Haiku hears the other person and answers aloud, Sonnet reads along and rarely steps in.

Joins voice-loop (speech recognition, Claude, speech) to iphonecall (the call itself).
Agents place calls through phone_mcp.py. By hand, run from this folder, in voice-loop's environment:
  .venv\\Scripts\\python.exe cicero.py dial +998XXXXXXXXX --lang ru --brief "Ask if they open on Sunday"
  .venv\\Scripts\\python.exe cicero.py answer --lang ru
While a call runs, type h to hang up or p to move the call to the iPhone and take over. Setup: README.md
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

from audio_defaults import CallDevices
from call_brief import ASK_MARK, DEFAULT_ENGLISH_VOICE, END_MARK, ENGLISH_VOICES, REACHED_MARKS, CallBrief
from observer import OBSERVER_MODEL, Observer
from phone_memory import ContactNotes, SUMMARY_LIMIT, SUMMARY_PROMPT, attempt_text, merge_call, number_key, summary_may_change

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # calls are in Russian, whatever the terminal is set to
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "voice-loop"))
from voice_loop import (BatchEar, Brain, Ear, MIC_RATE, Mouth, PiperVoice, PocketVoice, RU_STT_MODEL, RU_TTS_VOICE,  # noqa: E402
                        SYSTEM_PROMPTS, STT_ARCH, Splitter, TTS_LANGUAGE, TTS_VOICE)

CABLE_PLAY = "CABLE Input"  # Cicero speaks into this end of the virtual cable...
CABLE_HEAR = "CABLE Output"  # ...and Windows reads this end as the call's microphone
# As the default speaker, one of these plays the call with no sound in the room, and it can still be recorded. The first one
# installed is used. Another can be named in CICERO_SILENT_SPEAKER; check it first with evals\silent_output_probe.py.
SILENT_SPEAKERS = ("Voicemeeter Input", "CABLE-A Input", "CABLE-B Input", "Steam Streaming Speakers", "Boom Audio")
TAKE_OVER_KEY = 0x78  # F9, anywhere in Windows
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

# Says it isn't a person, and whose it is, in every call. No option removes it. Chosen by Aziz over "ИИ", which Piper says unclearly.
OPENINGS = {
    "dial": {"en": "Hello, this is {owner}'s AI assistant.", "ru": "Здравствуйте, это виртуальный ассистент {owner_ru}."},
    "answer": {"en": "Hello, this is {owner}'s AI assistant.", "ru": "Здравствуйте, это виртуальный ассистент {owner_ru}."},
}
# Said before Aziz comes on the line, so the other person knows a person has joined.
TAKING_OVER = {"en": "One moment, I'm passing you to {owner}.", "ru": "Одну секунду, передаю трубку {owner_ru}."}
# When nobody comes to the phone during the identity check.
NOBODY_CAME = {"en": "I couldn't reach them. We will call again. Goodbye.", "ru": "Не дождался ответа. Мы перезвоним. До свидания."}
DEFAULT_ANSWER_GOAL = "Find out who is calling and why, and offer to pass on a message."
WARM_UP = {"en": "The call is about to connect. Reply with just the word ready.",
           "ru": "Звонок сейчас начнётся. Ответь одним словом: готов."}
# Said when Sonnet changes what Haiku will say. Varied, so it doesn't sound like a machine stalling.
STALLS = {"en": ["One moment.", "Just a moment, please.", "One second.", "Sorry, one moment.", "Hold on a second, please."],
          "ru": ["Одну секунду.", "Секундочку.", "Минутку, пожалуйста.", "Одну минуту.", "Извините, одну секунду."]}


class PhoneLine:
    """Drives iphonecall's shell over pipes, and turns what it prints into call events."""

    CALL = re.compile(r"-- (\w+) (.*): (\w+), audio=(\w+), muted=")
    CALL_ENDED = re.compile(r"-- call ended \((\d+) active\)")
    READY = "commands:"
    END_GRACE_SECONDS = 5  # a call that comes back within this long never ended

    def __init__(self, command=("iphonecall",), log_path=None, end_grace=END_GRACE_SECONDS):
        self.proc = subprocess.Popen(list(command), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.STDOUT, text=True, errors="replace", bufsize=1)
        self.events = queue.Queue()
        self.started = []
        self.ready = threading.Event()
        self.ended = threading.Event()
        self.in_call = False
        self.audio = None
        self.log_path = log_path
        self.end_grace = end_grace
        self.end_timer = None
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
                self.audio = match.group(4)
                if self.end_timer:
                    self.end_timer.cancel()
                    self.end_timer = None
                self.ended.clear()
                self.in_call = True
                self.events.put((status, who, direction))
            elif ended and int(ended.group(1)) == 0:
                self.end_timer = threading.Timer(self.end_grace, self._call_is_over)
                self.end_timer.daemon = True
                self.end_timer.start()
            elif line.startswith(("error:", "stuck:", "dial ")):
                print(f"[phone: {line}]", flush=True)
        self._log("(iphonecall stopped)")
        if self.end_timer:
            self.end_timer.cancel()
        self.ended.set()
        self.events.put(("Closed", "", ""))

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
        """False if the call is still on the iPhone after this long. Then Cicero can neither hear nor be heard."""
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
        self.stream = self.pa.open(format=pyaudiowpatch.paFloat32, channels=self.channels, rate=self.rate,
                                   input=True, input_device_index=device["index"], frames_per_buffer=1024,
                                   stream_callback=self._on_audio)

    def _on_audio(self, data, count, when, status):
        self.blocks.put(np.frombuffer(data, dtype=np.float32).copy())
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
    """Puts Aziz on the call: the other person's voice on the real speaker, his real microphone into the cable."""

    def __init__(self, caller, speaker, microphone, cable):
        self.caller = caller
        self.closed = threading.Event()
        rate = caller.rate
        self.speaker = sd.OutputStream(samplerate=rate, channels=caller.channels, dtype="float32", device=speaker,
                                       extra_settings=sd.WasapiSettings(auto_convert=True))
        self.microphone = sd.Stream(samplerate=48000, channels=(1, 1), dtype="float32", device=(microphone, cable),
                                    callback=self._pass_voice_on,
                                    extra_settings=(sd.WasapiSettings(auto_convert=True), sd.WasapiSettings(auto_convert=True)))
        self.forwarding = threading.Thread(target=self._play_caller, daemon=True)

    def _pass_voice_on(self, indata, outdata, frames, when, status):
        outdata[:] = indata

    def _play_caller(self):
        while not self.closed.is_set():
            try:
                block = self.caller.blocks.get(timeout=0.1)
            except queue.Empty:
                continue
            self.speaker.write(block.reshape(-1, self.caller.channels))

    def start(self):
        self.caller.drop_waiting()
        self.speaker.start()
        self.microphone.start()
        self.forwarding.start()

    def stop(self):
        self.closed.set()
        self.forwarding.join(1)
        self.microphone.stop()
        self.microphone.close()
        self.speaker.stop()
        self.speaker.close()


class SpeechDetector:
    """Silero, one frame at a time. Works on speech itself, so call volume and line hiss matter little."""

    CONTEXT = 64  # samples of the previous frame that Silero expects in front of each new one

    def __init__(self):
        import onnx_asr
        self.session = onnx_asr.load_vad("silero")._model
        self.state = np.zeros((2, 1, 128), dtype=np.float32)
        self.context = np.zeros(self.CONTEXT, dtype=np.float32)

    def __call__(self, frame):
        joined = np.concatenate((self.context, frame)).astype(np.float32)[None, :]
        output, self.state = self.session.run(
            None, {"input": joined, "state": self.state, "sr": np.array(MIC_RATE, dtype=np.int64)})
        self.context = frame[-self.CONTEXT:]
        return float(output[0][0])


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
        self.length_known = isinstance(voice, PiperVoice)
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

    def add(self, who, text):
        print(f"{who}: {text}", flush=True)
        if who != "Cicero":
            self.spoken.append((who, text))
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(f"{datetime.datetime.now():%H:%M:%S} {who}: {text}\n")


def saved_frames(frames, path):
    """Passes the frames on, and keeps what Cicero hears as a WAV. Only with --save-audio."""
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
                 nobody_seconds=NOBODY_THERE_SECONDS, observer=None, nonce="", owner="Aziz", language="en",
                 task_message=None):
        self.task_message = task_message  # None when there's nobody to check for, and Haiku already has the task
        self.confirmed = task_message is None
        self.reached = "not_checked" if task_message is None else "unclear"
        self.observer = observer
        self.nonce = nonce
        self.owner = owner
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
        self.turn_lock = threading.Lock()
        self.opening_done = threading.Event()

    def _say_opening(self):
        with self.turn_lock:
            self.transcript.add("Claude", self.opening)
            self.mouth.say(self.opening, self.mouth.token)
            self.mouth.drain()
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
            if piece and heard:
                self.transcript.add("Claude", piece)
                self.mouth.say(piece, token, self._note_first_audio)
            elif piece:
                self.transcript.add("Cicero", f"not spoken: {piece}")

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
        """How long the person waited, to measure on real calls. Counted from when Cicero decided they had stopped."""
        ended, self.speech_ended_at = self.speech_ended_at, None
        if ended is not None:
            delay = time.monotonic() - ended
            self.reply_delays.append(round(delay, 2))
            self.transcript.add("Cicero", f"first audio {delay:.2f} s after their speech ended, plus {END_FRAMES * FRAME / MIC_RATE:.1f} s of waiting to be sure they had")

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
            self.transcript.add("Claude", f"(cut off, heard only: {heard})" if heard else "(cut off, heard nothing of this reply)")
        self.mouth.cancel()

    def _cut_note(self):
        """A note for Haiku about its last reply, or "" if it was heard in full."""
        heard, self.pending_cut = self.pending_cut, None
        if heard is None:
            return ""
        said = f'They heard only: "{heard}".' if heard else "They heard none of it."
        return self._supervisor(f"You were cut off during your last reply. {said} Say the rest again only if it still matters.")

    def _say_stall(self, token):
        phrase = random.choice(STALLS[self.language])
        self.transcript.add("Claude", phrase)
        self.mouth.say(phrase, token)
        return phrase

    def _consult(self, question, token):
        """Haiku asked for help: the person hears "one moment" while Sonnet decides."""
        self.transcript.add("Cicero", f"Haiku asks Sonnet: {question}")
        phrase = self._say_stall(token)
        note = self.observer.consult(question) if self.observer and self.confirmed else None
        fallback = f"Tell them you can't decide this and will pass it on to {self.owner}."
        note = note or (fallback if self.confirmed else "Ask them again whether you've reached the right person.")
        self.transcript.add("Cicero", f"Sonnet answers: {note}")
        message = self._supervisor(f'You just said "{phrase}" to them. {note} Say your next line now, with no {ASK_MARK}.')
        if self._speak_reply(message, token):
            self._speak_reply(self._supervisor(f"No more questions. Tell them you will pass it on to {self.owner}."), token)

    def _turn(self, text, epoch, prompt=None):
        with self.turn_lock:
            # A reply to words they have since talked over still goes into Haiku's memory, but isn't spoken.
            live = epoch == self.epoch
            token = self.mouth.token if live else self.mouth.token - 1
            self.mouth.start_reply()
            if text:
                self.caller_turns += 1
                message = re.sub(r"[\[\]]", " ", text)  # only Cicero can write a supervisor mark
            else:
                message = self._supervisor(prompt or "They made a short sound, but speech recognition got no words. "
                                           "They may have answered you. Ask them briefly to repeat it, or say your next line if you weren't waiting for an answer.")
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
        self.transcript.add("Cicero", f"Sonnet {advice['action']} ({advice['reason']}): {advice['note']}")
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
        started = last_heard = turn_started = last_busy = time.monotonic()
        turns = TurnDetector(SpeechDetector())
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
                self.transcript.add("Cicero", f"call over: {reason}, loudest sound heard {loudest:.3f} of 1")
                return reason

            loudest = max(loudest, float(np.abs(frame).max()))
            # Silence only counts from when Claude has finished talking.
            if self.generating or self.turn_lock.locked() or not self.mouth.idle():
                last_busy = now
            if self.confirmed and not turns.speaking and self.nudges < MAX_NUDGES and now - max(last_heard, last_busy) > NUDGE_SECONDS:
                self.nudges += 1
                last_busy = now
                self.transcript.add("Cicero", f"no speech for {NUDGE_SECONDS} s, checking they're still there")
                prompt = "They have said nothing for a while, so they may not have heard you. Check briefly that they're still there, and repeat your last question."
                threading.Thread(target=self._turn, args=("", self.epoch, prompt), daemon=True).start()

            event = turns.feed(frame)
            if event == "start":
                self.nudges = 0
                turn_started = now
                self.transcript.add("Cicero", f"speech started, {now - started:.1f} s into the call")
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
                self.transcript.add("Cicero", f"speech ended after {now - turn_started:.1f} s")
                text = self.ear.end(tail=0)
                if text:
                    self.wordless_replies = 0
                    self.transcript.add("Them", text)
                else:
                    self.wordless_replies += 1
                    self.transcript.add("Cicero", "speech detected, but recognition got no words")
                # Speech with no words may still have been their answer, so it gets a reply too, or the line goes quiet.
                if text or self.wordless_replies <= MAX_WORDLESS_REPLIES:
                    threading.Thread(target=self._turn, args=(text, self.epoch), daemon=True).start()
            elif turns.speaking:
                self.ear.feed_block(frame, MIC_RATE)
                last_heard = now
        return "caller left"


def find_output(name):
    for index, device in enumerate(sd.query_devices()):
        api = sd.query_hostapis(device["hostapi"])["name"]
        if "WASAPI" in api and name in device["name"] and device["max_output_channels"] > 0:
            return index
    return None


def silent_speakers():
    chosen = os.environ.get("CICERO_SILENT_SPEAKER")
    return (chosen, *SILENT_SPEAKERS) if chosen else SILENT_SPEAKERS


def find_silent_speaker(find=None):
    """The first silent speaker on this laptop, or None."""
    find = find or find_output
    return next((name for name in silent_speakers() if find(name) is not None), None)


def pick_real_device(devices):
    """The first (index, name) that's a real speaker or microphone, not the cable or the silent speaker."""
    for index, name in devices:
        if not any(virtual in name for virtual in ("CABLE", *silent_speakers())):
            return index
    return None


def real_devices():
    """Returns (speaker, microphone) to use when Aziz takes over. Either can be None if there's none."""
    wasapi = [(index, device) for index, device in enumerate(sd.query_devices())
              if "WASAPI" in sd.query_hostapis(device["hostapi"])["name"]]
    return (pick_real_device([(i, d["name"]) for i, d in wasapi if d["max_output_channels"] > 0]),
            pick_real_device([(i, d["name"]) for i, d in wasapi if d["max_input_channels"] > 0]))


def connected_headsets(endpoints=None):
    """Bluetooth headsets connected to the laptop, other than the phone itself.

    With one connected, Windows reports moving the call's audio to the laptop as done, but it stays on the iPhone.
    """
    if endpoints is None:
        try:
            endpoints = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "Get-PnpDevice -Class AudioEndpoint -Status OK | Select-Object -ExpandProperty FriendlyName"],
                capture_output=True, text=True, errors="replace", timeout=20).stdout.splitlines()
        except (OSError, subprocess.TimeoutExpired):
            return []
    return [name.strip() for name in endpoints if "Hands-Free" in name and "iPhone" not in name]


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
    """The things Cicero can't fix itself. Stops before any call rather than on a silent line."""
    problems = []
    for headset in connected_headsets():
        problems.append(f"'{headset}' is connected. Disconnect it from the laptop, or the call's audio stays on the "
                        "iPhone and the other person hears nothing (see README.md).")
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
    kernel32.CreateMutexW(None, False, "Local\\CiceroSingleCopy")
    if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
        sys.exit("Cicero is already running in another window.")


def load_speech(language, voice):
    """Returns (ear, mouth), with the mouth not yet connected to any speaker."""
    if language == "ru":
        return BatchEar(RU_STT_MODEL, mic=False), TrackingMouth(PiperVoice(voice or RU_TTS_VOICE), play=False)
    voice = voice or DEFAULT_ENGLISH_VOICE
    mouth = TrackingMouth(PocketVoice(TTS_LANGUAGE, voice), play=False)
    mouth.slow_rate = ENGLISH_VOICES.get(voice, {}).get("chars_per_second", SLOW_CHARS_PER_SECOND)
    return Ear(STT_ARCH, mic=False), mouth


def prepare_models():
    """Downloads now what a first call would otherwise stop to download."""
    SpeechDetector()
    for language, voice in (("ru", "irina"), ("ru", "ruslan"), ("en", None)):
        print(f"Loading {language} speech{f' ({voice})' if voice else ''}...", flush=True)
        load_speech(language, voice)
    print("Speech models are ready.")


def use_call_devices(devices, audible):
    """Just before the call, so the laptop keeps its sound while Cicero loads."""
    devices.use(speaker=None if audible else find_silent_speaker(), mic=CABLE_HEAR)


def load_brief(args):
    if args.brief_file:
        with open(args.brief_file, encoding="utf-8") as f:
            return CallBrief.from_dict(json.load(f))
    return CallBrief.from_dict({"goal": args.brief or DEFAULT_ANSWER_GOAL, "language": args.lang, "name": args.name,
                                "company": args.company, "confidence": args.confidence if (args.name or args.company) else ""})


def start_brain(args, brief, opening, nonce, notes):
    print("Starting Claude...", flush=True)
    prompt = brief.haiku_prompt(SYSTEM_PROMPTS[brief.language], opening, args.owner, nonce, notes)
    brain = Brain(brief.language, system_prompt=prompt)
    for _ in brain.ask(WARM_UP[brief.language]):
        pass
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
    when = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
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


def stay_on_laptop(conversation, line, caller, mouth, args, brief, cable):
    """Aziz talks from here on, until the call ends or he hangs up or moves it to the iPhone. Claude says nothing more."""
    speaker, microphone = real_devices()
    if speaker is None or microphone is None:
        print("Can't take over: no real speaker or microphone found. Moving the call to the iPhone instead.", flush=True)
        line.to_phone()
        conversation.hand_over.set()
        return
    phrase = TAKING_OVER[brief.language].format(owner=args.owner, owner_ru=args.owner_ru)
    mouth.say(phrase, mouth.token)
    mouth.drain()
    takeover = LaptopTakeover(caller, speaker, microphone, cable)
    takeover.start()
    print("You're on the call. Use wired headphones, or they'll hear an echo. Type h to hang up, p to move it to the iPhone.", flush=True)
    while not (line.ended.is_set() or conversation.stopped.is_set() or conversation.hand_over.is_set()):
        time.sleep(0.1)
    takeover.stop()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("action", choices=["dial", "answer", "check", "prepare", "restore-audio"],
                        help="check tests the setup. prepare downloads the speech models. restore-audio puts back the default "
                             "speaker and microphone after a call that was killed. None of these makes a call")
    parser.add_argument("number", nargs="?", help="number to dial, in international format")
    parser.add_argument("--brief", help="what Claude should do on this call, in one sentence")
    parser.add_argument("--brief-file", help="a full call brief as JSON; see call_brief.py")
    parser.add_argument("--result-file", help="write the outcome here as JSON when the call is over")
    parser.add_argument("--no-observer", action="store_true", help="no Sonnet on this call")
    parser.add_argument("--name", default="", help="who you're calling; Claude checks it reached them before the task")
    parser.add_argument("--company", default="", help="their company; with no --name, anyone there can help")
    parser.add_argument("--confidence", choices=["confirmed", "guess", "unknown"], default="guess",
                        help="how sure you are the number is theirs")
    parser.add_argument("--lang", choices=sorted(SYSTEM_PROMPTS), default="ru")
    parser.add_argument("--voice", default=None, help=f"Russian: irina or ruslan. English: {', '.join(ENGLISH_VOICES)}")
    parser.add_argument("--owner", default="Aziz", help="whose behalf Claude speaks on")
    parser.add_argument("--owner-ru", default="Азиза", help="the same name in Russian, genitive case")
    parser.add_argument("--max-minutes", type=float, default=5, help="hang up after this long")
    parser.add_argument("--audible", action="store_true", help="play the call on your real speaker instead of silently")
    parser.add_argument("--no-memory", action="store_true", help="don't read or update this number's notes")
    parser.add_argument("--save-audio", action="store_true",
                        help="keep the other person's audio in calls/. Only with their agreement")
    args = parser.parse_args()
    if args.action == "dial" and not (args.number and (args.brief or args.brief_file)):
        parser.error("dial needs a number and --brief or --brief-file")

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
    brief = load_brief(args)
    opening = OPENINGS[args.action][brief.language].format(owner=args.owner, owner_ru=args.owner_ru)
    if brief.has_target():
        opening = f"{opening} {brief.check_question()}"
    nonce = secrets.token_hex(4)  # the person can't say this, so they can't pose as the supervisor
    print("Loading speech models...", flush=True)
    ear, mouth = load_speech(brief.language, args.voice)
    mouth.out = open_cable(mouth.sample_rate)
    mouth.out.start()
    brain = None
    notes = None
    key = None
    known = ""
    if args.action == "dial":
        # Started before dialing, so a Claude failure can't leave someone on a silent call.
        key = number_key(args.number)
        notes, known = load_notes(key, args)
        brain = start_brain(args, brief, opening, nonce, known)

    print("Connecting to the iPhone...", flush=True)
    os.makedirs(os.path.join(HERE, "calls"), exist_ok=True)
    phone_log = os.path.join(HERE, "calls", f"phone-{datetime.datetime.now():%Y%m%d-%H%M%S}.log")
    line = PhoneLine(log_path=phone_log)
    if not line.wait_ready():
        print("\n".join(line.started))
        write_result(args, status="failed", reason="iphonecall did not start: " + " | ".join(line.started))
        if brain:
            brain.close()
        sys.exit("iphonecall did not start. Its lines above say which step failed.")

    caller = None
    conversation = None
    frames = None
    transcript = None
    observer = None
    sonnet = None
    status = "no_answer"
    reason = "the call was not answered"
    picked_up = None
    try:
        if args.action == "dial":
            print(f"Dialing {args.number}. Claude's task: {brief.goal}", flush=True)
            use_call_devices(devices, args.audible)
            line.dial(args.number)
            answered = line.wait_for(["Talking"], seconds=90)
        else:
            print("Waiting for a call. Claude will answer the next one. Ctrl+C quits.", flush=True)
            answered = None
            incoming = line.wait_for(["Incoming"])
            if incoming and incoming[0] == "Incoming":
                print(f"Incoming: {incoming[1]}", flush=True)
                # Only now is the number known, so Claude starts with the right notes while it rings.
                key = number_key(incoming[1])
                notes, known = load_notes(key, args)
                brain = start_brain(args, brief, opening, nonce, known)
                use_call_devices(devices, args.audible)
                line.answer()
                answered = line.wait_for(["Talking"], seconds=30)
        if not answered or answered[0] != "Talking":
            if not answered:
                reason = "nobody picked up in time"
            elif answered[0] == "Closed":
                reason = "iphonecall stopped during dialing; the call may still be live on the iPhone"
            else:
                reason = "the call ended before anyone picked up"
            print(f"No conversation: {reason}. Details: {phone_log}")
            return

        if not line.wait_for_laptop_audio(AUDIO_MOVE_SECONDS):
            status = "failed"
            reason = "the call audio stayed on the iPhone, so Claude could not hear or speak; hung up"
            print(f"No conversation: {reason}. Details: {phone_log}")
            return
        picked_up = time.monotonic()
        time.sleep(AFTER_PICKUP_SECONDS)
        caller = CallerAudio()
        print(f"Connected. Hearing through: {caller.name}. Press F9 or type l to take the call on the laptop, p to move it to the iPhone, h to hang up.", flush=True)
        transcript = Transcript(key=key)
        transcript.add("Cicero", f"task: {brief.text()}")
        transcript.add("Cicero", f"hearing through: {caller.name}; call audio: {line.audio}")
        observer, sonnet = start_observer(args, brief, transcript)
        frames = caller.frames()
        if args.save_audio:
            frames = saved_frames(frames, transcript.path.replace(".txt", ".wav"))
        conversation = Conversation(line, frames, ear, mouth, brain, transcript, opening,
                                    max_seconds=args.max_minutes * 60, observer=observer, nonce=nonce,
                                    owner=args.owner, language=brief.language,
                                    task_message=brief.task_message(args.owner, known) if brief.has_target() else None)
        listen_for_keys(line, conversation)
        watch_take_over_key(conversation)
        status = "done"
        reason = conversation.run()
        if conversation.take_over.is_set() and not line.ended.is_set():
            stay_on_laptop(conversation, line, caller, mouth, args, brief, find_output(CABLE_PLAY))
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
        handed_over = conversation is not None and conversation.hand_over.is_set()
        if not handed_over:
            # Always, even if no call seems active: leaving would strand a real person on a silent line.
            line.hang_up()
            time.sleep(1)
        line.close()
        for problem in devices.restore():
            print(f"Setup: {problem}")
        if brain:
            brain.close()
        reached = conversation.reached if conversation else None
        report = observer.final_report(f"{reason} (who was reached: {reached})") if observer else None
        if sonnet:
            sonnet.close()
        notes_report = None
        if notes and transcript:
            notes_report = remember_call(notes, transcript, args.owner, brief, reached)
        elif notes:
            notes.add_attempt(datetime.datetime.now().strftime("%Y-%m-%d %H:%M"), reason)
            notes.save()
        write_result(args, status=status, reason=reason, report=report, notes=notes_report,
                     number=args.number, seconds=seconds, reached=reached, target=brief.target(),
                     reply_delays=conversation.reply_delays if conversation else [],
                     transcript_file=transcript.path if transcript else None,
                     interventions=observer.interventions if observer else 0,
                     reviews=observer.reviews if observer else 0)


if __name__ == "__main__":
    main()
