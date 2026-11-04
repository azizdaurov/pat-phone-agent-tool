"""Resident, local-only speech models. Audio goes over authenticated pipes, never pickle or a network service."""
import argparse
import hashlib
import json
import os
import secrets
import struct
import subprocess
import sys
import threading
import time
import uuid
from multiprocessing.connection import Client, Listener

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DESCRIPTOR_NAME = "speech-service.json"
MAX_PACKET = 8 * 1024 * 1024
IO_TIMEOUT = 30
PROTOCOL_VERSION = 1


def descriptor_path(folder=None):
    return os.environ.get("PAT_SPEECH_DESCRIPTOR") or os.path.join(folder or os.path.join(HERE, "calls"), DESCRIPTOR_NAME)


def read_status(path=None):
    try:
        with open(path or descriptor_path(), encoding="utf-8") as stream:
            value = json.load(stream)
        return value if isinstance(value, dict) else None
    except (OSError, ValueError):
        return None


def write_status(path, value):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    temporary = path + f".{os.getpid()}.{uuid.uuid4().hex}.tmp"
    try:
        with open(temporary, "w", encoding="utf-8") as stream:
            json.dump(value, stream)
        for attempt in range(30):
            try:
                os.replace(temporary, path)
                break
            except PermissionError:
                if attempt == 29:
                    raise
                time.sleep(0.01)  # Windows can hold a reader open during the atomic replacement.
    finally:
        try:
            os.remove(temporary)
        except OSError:
            pass


def send_json(connection, value):
    connection.send_bytes(json.dumps(value).encode("utf-8"))


def receive_json(connection, timeout=IO_TIMEOUT):
    if not connection.poll(timeout):
        raise TimeoutError("Pat's speech service did not respond.")
    value = json.loads(connection.recv_bytes(MAX_PACKET).decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Invalid speech message.")
    if value.get("error"):
        raise RuntimeError(value["error"])
    return value


def connect(status):
    address = status["address"]
    if status["family"] == "AF_INET":
        address = tuple(address)
    return Client(address, family=status["family"], authkey=bytes.fromhex(status["key"]))


def public_notice(status):
    if not status:
        return "Speech is getting ready…"
    if status.get("state") == "ready":
        return ""
    if status.get("state") == "error":
        return "Speech could not load. Run setup, then reopen Pat."
    return "Speech is getting ready…"


class SpeechEngine:
    """The weights live here for the whole Pat session. There are no audio-device handles."""
    def __init__(self, progress):
        import cicero
        from voice_loop import PocketVoice, PiperVoice, TTS_LANGUAGE
        self.cicero = cicero
        self.ears = {}
        self.voices = {}
        self.asr_locks = {language: threading.Lock() for language in ("en", "ru")}
        self.tts_lock = threading.Lock()
        for language, model in (("en", cicero.EN_STT_MODEL), ("ru", cicero.RU_STT_MODEL)):
            progress(f"Loading {language} recognition")
            self.ears[language] = cicero.BatchEar(model, mic=False)
        english_model = None
        for voice in cicero.ENGLISH_VOICES:
            progress(f"Preparing English voice {voice}")
            speaker = PocketVoice(TTS_LANGUAGE, voice, model=english_model)
            english_model = speaker.model
            self.voices[("en", voice)] = speaker
            for _ in speaker.stream(speaker.warm_text, threading.Event()):
                pass
        for voice in ("irina", "ruslan"):
            progress(f"Preparing Russian voice {voice}")
            speaker = PiperVoice(voice)
            self.voices[("ru", voice)] = speaker
            for _ in speaker.stream(speaker.warm_text, threading.Event()):
                pass
        progress("Loading speech detection")
        self.vad_session = cicero.SpeechDetector(use_service=False).session

    def recognize(self, language, audio, rate):
        with self.asr_locks[language]:
            return self.ears[language].model.recognize(audio, sample_rate=rate).strip()

    def speaker(self, language, voice):
        return self.voices[(language, voice)]

    def detector(self):
        return self.cicero.SpeechDetector(session=self.vad_session, use_service=False)


class SpeechServer:
    def __init__(self, path, engine_factory=SpeechEngine, parent_alive=lambda: True):
        self.path = path
        self.status = read_status(path)
        if not self.status:
            raise RuntimeError("Speech service launch information is missing.")
        self.engine_factory = engine_factory
        self.parent_alive = parent_alive
        self.ready = threading.Event()
        self.draining = threading.Event()
        self.lock = threading.RLock()
        self.active = 0
        self.engine = None
        self.listener = None

    def update(self, **fields):
        with self.lock:
            self.status.update(fields, updated=time.time())
            write_status(self.path, self.status)

    def load(self):
        try:
            self.engine = self.engine_factory(lambda phase: self.update(phase=phase))
            self.ready.set()
            self.update(state="ready", phase="Speech ready")
        except Exception as error:
            try:
                self.update(state="error", error=str(error))
            finally:
                print(f"Speech model load failed: {error}", flush=True)
                self.draining.set()

    def serve(self):
        address = self.status["address"]
        if self.status["family"] == "AF_INET":
            address = tuple(address)
        self.listener = Listener(address, family=self.status["family"], authkey=bytes.fromhex(self.status["key"]))
        self.update(address=self.listener.address, pid=os.getpid())
        threading.Thread(target=self.load, daemon=True).start()
        threading.Thread(target=self.accept, daemon=True).start()
        try:
            while True:
                if not self.parent_alive():
                    self.draining.set()
                if self.draining.is_set():
                    with self.lock:
                        if self.active == 0:
                            break
                time.sleep(0.1)
        finally:
            self.listener.close()
            current = read_status(self.path)
            if current and current.get("instance") == self.status["instance"] and self.status.get("state") != "error":
                try:
                    os.remove(self.path)
                except OSError:
                    pass

    def accept(self):
        while not (self.draining.is_set() and not self.active):
            try:
                connection = self.listener.accept()
            except (OSError, EOFError):
                return
            except Exception:  # An unauthenticated client must not stop the service.
                continue
            threading.Thread(target=self.handle, args=(connection,), daemon=True).start()

    def handle(self, connection):
        counted = False
        try:
            request = receive_json(connection)
            kind = request.get("kind")
            if kind == "shutdown":
                self.draining.set()
                self.update(state="draining")
                send_json(connection, {"ok": True})
                return
            if kind == "status":
                send_json(connection, {"state": self.status["state"], "instance": self.status["instance"]})
                return
            if not self.ready.is_set():
                send_json(connection, {"error": "Speech is still getting ready. Wait until the loading message disappears."})
                return
            if kind not in ("asr", "voice", "vad"):
                raise ValueError("Unknown speech resource.")
            language = request.get("language", "en")
            if language not in ("en", "ru"):
                raise ValueError("Unsupported speech language.")
            speaker = self.engine.speaker(language, request["voice"]) if kind == "voice" else None
            detector = self.engine.detector() if kind == "vad" else None
            with self.lock:
                self.active += 1
                counted = True
            hello = {"instance": self.status["instance"]}
            if speaker:
                hello.update(sample_rate=speaker.sample_rate, clause_chars=speaker.clause_chars)
            send_json(connection, hello)
            while True:
                if kind == "asr":
                    task = receive_json(connection, timeout=3600)
                    audio = np.frombuffer(connection.recv_bytes(MAX_PACKET), dtype="<f4")
                    if task.get("rate") != 16000 or len(audio) > 16000 * 120:
                        raise ValueError("Invalid recognition audio.")
                    send_json(connection, {"text": self.engine.recognize(language, audio, task["rate"])})
                elif kind == "vad":
                    packet = connection.recv_bytes(MAX_PACKET)
                    if len(packet) != 512 * 4:
                        raise ValueError("Invalid speech-detection frame.")
                    probability = detector(np.frombuffer(packet, dtype="<f4"))
                    connection.send_bytes(struct.pack("<f", probability))
                else:
                    task = receive_json(connection, timeout=3600)
                    if task.get("cancel"):
                        continue  # A cancellation can arrive just after the previous sentence finished.
                    text = task.get("text", "")
                    if not isinstance(text, str) or len(text) > 10000:
                        raise ValueError("Invalid speech text.")
                    stop = threading.Event()
                    try:
                        with self.engine.tts_lock:
                            for chunk in speaker.stream(text, stop):
                                if connection.poll():
                                    control = receive_json(connection)
                                    if control.get("cancel"):
                                        stop.set()
                                if stop.is_set():
                                    break
                                connection.send_bytes(b"A" + np.asarray(chunk, dtype="<f4").tobytes())
                        connection.send_bytes(b"D")
                    finally:
                        stop.set()
        except (EOFError, BrokenPipeError, OSError):
            pass
        except Exception as error:
            try:
                send_json(connection, {"error": str(error)})
            except (OSError, EOFError):
                pass
        finally:
            connection.close()
            if counted:
                with self.lock:
                    self.active -= 1


class Resource:
    def __init__(self, status, kind, **fields):
        self.status = status
        self.kind = kind
        self.fields = fields
        self.connection = None
        self.lock = threading.RLock()
        self.hello = self.open()

    def open(self):
        self.connection = connect(self.status)
        send_json(self.connection, {"kind": self.kind, **self.fields})
        return receive_json(self.connection)

    def close(self):
        if self.connection is not None:
            self.connection.close()
            self.connection = None

    def __del__(self):
        self.close()


class RemoteEar(Resource):
    def __init__(self, status, language):
        super().__init__(status, "asr", language=language)
        self.rate = 16000
        self.audio = []

    def prepare(self):
        self.audio = []

    def feed_block(self, block, rate):
        if rate != 16000:
            raise ValueError("Recognition expects 16 kHz audio.")
        self.audio.append(block)

    def end(self, tail=0):
        if not self.audio:
            return ""
        audio = np.concatenate(self.audio).astype("<f4")
        self.audio = []
        with self.lock:
            send_json(self.connection, {"rate": self.rate})
            self.connection.send_bytes(audio.tobytes())
            return receive_json(self.connection)["text"]


class RemoteVoice(Resource):
    already_warm = True

    def __init__(self, status, language, voice):
        super().__init__(status, "voice", language=language, voice=voice)
        self.sample_rate = self.hello["sample_rate"]
        self.clause_chars = self.hello["clause_chars"]
        self.length_known = language == "ru"
        self.warm_text = "Ready."

    def stream(self, text, stop):
        with self.lock:
            if self.connection is None:
                self.open()
            finished = False
            cancelled = False
            try:
                send_json(self.connection, {"text": text})
                while True:
                    if stop.is_set() and not cancelled:
                        send_json(self.connection, {"cancel": True})
                        cancelled = True
                    if not self.connection.poll(IO_TIMEOUT):
                        raise TimeoutError("Speech generation did not respond.")
                    packet = self.connection.recv_bytes(MAX_PACKET)
                    if packet == b"D":
                        finished = True
                        return
                    if packet.startswith(b"A"):
                        if not stop.is_set():
                            yield np.frombuffer(packet[1:], dtype="<f4")
                    else:
                        raise RuntimeError(json.loads(packet.decode("utf-8")).get("error", "Invalid voice response."))
            finally:
                if not finished or cancelled:
                    self.close()  # The server cancels this stream; the next sentence opens a fresh, warm session.


class RemoteDetector(Resource):
    def __init__(self, status):
        super().__init__(status, "vad")

    def __call__(self, frame):
        with self.lock:
            self.connection.send_bytes(np.asarray(frame, dtype="<f4").tobytes())
            if not self.connection.poll(IO_TIMEOUT):
                raise TimeoutError("Speech detection did not respond.")
            packet = self.connection.recv_bytes(MAX_PACKET)
            if len(packet) != 4:
                raise RuntimeError("Invalid speech-detection response.")
            return struct.unpack("<f", packet)[0]


def available():
    status = read_status()
    if status and status.get("protocol") != PROTOCOL_VERSION:
        raise RuntimeError("Restart Pat to refresh its speech service.")
    if status and status.get("state") not in ("ready", "draining"):
        raise RuntimeError(public_notice(status))
    return status


class ResidentSpeech:
    """Owned by the note. Closing the note drains an active call before unloading the models."""
    def __init__(self, folder=None, command=None):
        self.path = descriptor_path(folder)
        self.command = command
        self.process = None
        self.closed = threading.Event()
        self.thread = None

    def start(self):
        self.thread = threading.Thread(target=self.watch, daemon=True)
        self.thread.start()

    def launch(self):
        identity = hashlib.sha256(os.path.abspath(self.path).encode()).hexdigest()[:12]
        family = "AF_PIPE" if os.name == "nt" else "AF_INET"
        address = rf"\\.\pipe\PatSpeech-{identity}-{uuid.uuid4().hex[:12]}" if family == "AF_PIPE" else ("127.0.0.1", 0)
        write_status(self.path, {"state": "starting", "phase": "Loading speech", "family": family, "address": address, "protocol": PROTOCOL_VERSION,
                                 "key": secrets.token_hex(32), "instance": uuid.uuid4().hex, "owner_pid": os.getpid()})
        python = os.path.join(os.path.dirname(sys.executable), "python.exe") if os.name == "nt" else sys.executable
        command = self.command or [python, os.path.abspath(__file__), "--descriptor", self.path]
        with open(os.path.join(os.path.dirname(self.path), "speech-service.log"), "a", encoding="utf-8") as log:
            self.process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                            cwd=HERE, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                                            env={**os.environ, "PYTHONUNBUFFERED": "1"})

    def watch(self):
        while not self.closed.is_set():
            if self.process is None or self.process.poll() is not None:
                try:
                    self.launch()
                except OSError as error:
                    status = read_status(self.path) or {}
                    write_status(self.path, {**status, "state": "error", "error": str(error)})
                if self.closed.wait(5):
                    break
            self.closed.wait(1)

    def status(self):
        status = read_status(self.path)
        if status and self.process is not None and self.process.poll() is not None:
            status = {**status, "state": "error"}
        return status

    def is_ready(self):
        return bool(self.process and self.process.poll() is None and (self.status() or {}).get("state") == "ready")

    def close(self):
        self.closed.set()
        if self.thread:
            self.thread.join(2)
        status = self.status()
        if self.process is None:
            if status and status.get("owner_pid") == os.getpid():
                try:
                    os.remove(self.path)
                except OSError:
                    pass
            return
        if self.process is not None and self.process.poll() is not None:
            try:
                os.remove(self.path)
            except OSError:
                pass
            return
        if self.process is not None and self.process.poll() is None and (not status or status.get("state") not in ("ready", "draining")):
            # No call can own a model session before readiness; startup can be stopped immediately.
            self.process.terminate()
            self.process.wait(timeout=5)
            try:
                os.remove(self.path)
            except OSError:
                pass
            return
        if status:
            try:
                connection = connect(status)
                try:
                    send_json(connection, {"kind": "shutdown"})
                    receive_json(connection, timeout=2)
                finally:
                    connection.close()
            except (OSError, EOFError, ValueError, TimeoutError):
                pass


def parent_monitor(pid):
    if os.name != "nt":
        return lambda: os.getppid() == pid
    import ctypes
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
    handle = kernel32.OpenProcess(0x1000, False, pid)
    def alive():
        result = ctypes.c_ulong()
        return bool(handle and kernel32.GetExitCodeProcess(handle, ctypes.byref(result)) and result.value == 259)
    return alive


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--descriptor", required=True)
    args = parser.parse_args()
    from user_profile import UserProfile
    if not UserProfile().ready:
        raise SystemExit("Finish Pat's first-run setup before starting speech.")
    status = read_status(args.descriptor)
    SpeechServer(args.descriptor, parent_alive=parent_monitor(status["owner_pid"])).serve()


if __name__ == "__main__":
    main()
