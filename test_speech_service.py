"""Resident model reuse and cancellation over real local IPC, with fake models and no audio devices."""
import json
import os
import pathlib
import queue
import tempfile
import threading
import time
import types
import unittest
from unittest import mock

import numpy as np

from speech_service import (RemoteDetector, RemoteEar, RemoteVoice, ResidentSpeech, SpeechServer,
                            descriptor_path, read_status)
from test_note import DeskCase


class FakeVoice:
    sample_rate = 16000
    clause_chars = None
    def stream(self, text, stop):
        for value in ((0.7, 0.8, 0.9) if text == "Next sentence" else (0.1, 0.2, 0.3)):
            if stop.is_set():
                return
            yield np.full(80, value, dtype=np.float32)


class FakeDetector:
    def __init__(self):
        self.frames = 0

    def __call__(self, frame):
        self.frames += 1
        return self.frames / 10


class FakeEngine:
    def __init__(self, progress):
        self.tts_lock = threading.Lock()
        self.voice = FakeVoice()
        count_path = os.environ.get("PAT_FAKE_MODEL_LOADS")
        if count_path:
            with open(count_path, "a", encoding="utf-8") as stream:
                stream.write("loaded\n")
        time.sleep(float(os.environ.get("PAT_FAKE_MODEL_DELAY", "0")))
        progress("Fake models ready")

    def recognize(self, language, audio, rate):
        return f"{language}:{len(audio)}:{rate}"

    def speaker(self, language, voice):
        return self.voice

    def detector(self):
        return FakeDetector()


def wait_until(function, seconds=20):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if function():
            return
        time.sleep(0.05)
    raise AssertionError("Timed out waiting for test speech service.")


def fake_service(folder):
    import sys
    path = os.path.join(folder, "speech-service.json")
    code = ("import sys; from test_speech_service import FakeEngine; "
            "from speech_service import SpeechServer; SpeechServer(sys.argv[1], engine_factory=FakeEngine).serve()")
    return ResidentSpeech(folder, command=[sys.executable, "-B", "-u", "-c", code, path])


class ResidentIPC(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.counts = pathlib.Path(self.folder, "loads.txt")
        self.env = mock.patch.dict(os.environ, {"PAT_SPEECH_DESCRIPTOR": os.path.join(self.folder, "speech-service.json"),
                                               "PAT_FAKE_MODEL_LOADS": str(self.counts)})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.resident = fake_service(self.folder)
        self.resident.start()
        self.addCleanup(self.shutdown)
        wait_until(self.resident.is_ready)

    def shutdown(self):
        self.resident.close()
        wait_until(lambda: self.resident.process.poll() is not None)

    def test_two_calls_reuse_one_model_process_and_binary_audio_round_trips(self):
        instances = []
        for _ in range(2):
            ear = RemoteEar(self.resident.status(), "en")
            voice = RemoteVoice(self.resident.status(), "en", "charles")
            try:
                ear.prepare()
                ear.feed_block(np.zeros(512, dtype=np.float32), 16000)
                self.assertEqual(ear.end(), "en:512:16000")
                chunks = list(voice.stream("Hello", threading.Event()))
                self.assertEqual(sum(len(chunk) for chunk in chunks), 240)
                self.assertAlmostEqual(float(chunks[0][0]), 0.1, places=5)
                instances.append(ear.hello["instance"])
            finally:
                ear.close()
                voice.close()
        self.assertEqual(instances[0], instances[1])
        self.assertEqual(self.counts.read_text().splitlines(), ["loaded"])

    def test_vad_state_is_fresh_for_every_call_while_weights_stay_resident(self):
        for _ in range(2):
            detector = RemoteDetector(self.resident.status())
            try:
                self.assertAlmostEqual(detector(np.zeros(512, dtype=np.float32)), 0.1, places=5)
                self.assertAlmostEqual(detector(np.zeros(512, dtype=np.float32)), 0.2, places=5)
            finally:
                detector.close()
        self.assertEqual(self.counts.read_text().splitlines(), ["loaded"])

    def test_closing_pat_drains_a_live_speech_session_before_unloading(self):
        voice = RemoteVoice(self.resident.status(), "en", "charles")
        try:
            self.resident.close()
            self.assertIsNone(self.resident.process.poll())
            self.assertEqual(sum(len(x) for x in voice.stream("Finish the call", threading.Event())), 240)
        finally:
            voice.close()
        wait_until(lambda: self.resident.process.poll() is not None)
        self.assertIsNone(read_status(self.resident.path))

    def test_an_interrupted_sentence_does_not_poison_the_next_sentence(self):
        voice = RemoteVoice(self.resident.status(), "en", "charles")
        try:
            stream = voice.stream("Interrupted", threading.Event())
            next(stream)
            stream.close()
            self.assertEqual(sum(len(x) for x in voice.stream("Next sentence", threading.Event())), 240)
        finally:
            voice.close()

    def test_late_cancellation_does_not_consume_the_next_sentences_audio(self):
        voice = RemoteVoice(self.resident.status(), "en", "charles")
        try:
            stop = threading.Event()
            first = voice.stream("First sentence", stop)
            next(first)
            stop.set()
            list(first)
            chunks = list(voice.stream("Next sentence", threading.Event()))
            self.assertEqual(sum(len(x) for x in chunks), 240)
            self.assertAlmostEqual(float(chunks[0][0]), 0.7, places=5)
        finally:
            voice.close()

    def test_call_load_speech_uses_the_service_without_loading_local_models(self):
        import pat
        with mock.patch.object(pat, "BatchEar", side_effect=AssertionError("must reuse resident weights")), mock.patch.object(pat, "PocketVoice", side_effect=AssertionError("must reuse resident weights")):
            ear, mouth = pat.load_speech("en", "charles")
        try:
            self.assertTrue(mouth.voice.already_warm)
            self.assertEqual(mouth.voice.sample_rate, 16000)
            detector = pat.SpeechDetector()
            try:
                self.assertAlmostEqual(detector(np.zeros(512, dtype=np.float32)), 0.1, places=5)
            finally:
                detector.close()
        finally:
            ear.close()
            mouth.voice.close()


class WaitingForSpeech(DeskCase):
    def setUp(self):
        super().setUp()
        self.loaded = False
        self.desk.speech_ready = lambda: self.loaded

    def test_no_call_process_is_started_while_speech_is_loading(self):
        self.ring()
        self.desk.answer_ai()
        self.assertEqual(self.calls, [])
        self.assertEqual(self.commands(), [])
        self.assertEqual(self.desk.state()["screen"], "ringing")
        self.assertTrue(self.desk.ai_requested)

    def test_a_still_ringing_call_uses_models_when_warmup_finishes(self):
        self.ring()
        self.desk.answer_ai()
        self.loaded = True
        self.assertEqual(self.desk.state()["screen"], "ai")
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.commands(), ["go"])

    def test_an_expired_call_is_not_answered_when_warmup_finishes(self):
        self.ring()
        self.desk.answer_ai()
        self.desk.on_event(("RingingStopped", "", ""))
        self.loaded = True
        self.assertEqual(self.desk.state()["screen"], "idle")
        self.assertFalse(self.desk.ai_requested)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.commands(), [])

    def test_me_cancels_the_queued_ai_request_during_warmup(self):
        self.ring()
        self.desk.answer_ai()
        self.desk.answer_me()
        self.loaded = True
        self.assertEqual(self.desk.state()["screen"], "me")
        self.assertEqual(self.calls, [])


class PreparingCallCancellation(DeskCase):
    def test_chosen_ai_request_is_cancelled_if_ringing_stops_before_it_connects(self):
        self.ring()
        self.desk.answer_ai()
        self.commands()
        self.set_live(stage="starting")
        self.desk.on_event(("RingingStopped", "", ""))
        self.assertEqual(self.commands(), ["cancel"])
        self.assertEqual(self.desk.screen, "idle")
        self.assertIsNotNone(self.calls[0].poll())


class IncomingCancellation(unittest.TestCase):
    def test_cancel_wins_even_if_a_go_message_also_arrived(self):
        import pat
        go, cancel, ended, ringing = (threading.Event() for _ in range(4))
        go.set(); cancel.set(); ringing.set()
        self.assertFalse(pat.wait_for_go(go, cancel, types.SimpleNamespace(ended=ended, ringing=ringing)))

    def test_an_incoming_request_does_not_wait_for_a_future_call_after_cancellation(self):
        import pat
        cancel = threading.Event(); cancel.set()
        line = types.SimpleNamespace(ended=threading.Event(), events=queue.Queue())
        self.assertIsNone(pat.wait_for_current_incoming(line, cancel))

    def test_a_call_already_picked_up_on_the_phone_is_not_answered_by_ai(self):
        import pat
        go = threading.Event(); go.set()
        line = types.SimpleNamespace(ended=threading.Event(), ringing=threading.Event())
        self.assertFalse(pat.wait_for_go(go, threading.Event(), line))

    def test_stale_incoming_event_is_not_used_after_ringing_stopped(self):
        import pat
        line = types.SimpleNamespace(ended=threading.Event(), ringing=threading.Event(), events=queue.Queue())
        line.events.put(("Incoming", "Caller", "Incoming"))
        self.assertIsNone(pat.wait_for_current_incoming(line, threading.Event(), seconds=0.1))


class StatusFiles(unittest.TestCase):
    def test_closing_after_launch_failure_does_not_wait_on_a_missing_pipe(self):
        import speech_service
        folder = tempfile.mkdtemp()
        service = ResidentSpeech(folder)
        with mock.patch.dict(os.environ, {"PAT_SPEECH_DESCRIPTOR": os.path.join(folder, "speech-service.json")}):
            service.path = descriptor_path(folder)
            speech_service.write_status(service.path, {"state": "error", "owner_pid": os.getpid()})
            with mock.patch.object(speech_service, "connect", side_effect=AssertionError("no process to connect to")):
                service.close()
            self.assertIsNone(read_status(service.path))

    def test_a_temporary_windows_reader_lock_does_not_lose_readiness(self):
        import speech_service
        folder = tempfile.mkdtemp()
        path = os.path.join(folder, "speech-service.json")
        original = os.replace
        attempts = []
        def replace(source, target):
            attempts.append(1)
            if len(attempts) == 1:
                raise PermissionError("simulated Windows reader lock")
            return original(source, target)
        with mock.patch.object(speech_service.os, "replace", side_effect=replace):
            speech_service.write_status(path, {"state": "ready"})
        self.assertEqual(read_status(path)["state"], "ready")
        self.assertEqual(len(attempts), 2)


class ModelConstruction(unittest.TestCase):
    def test_all_english_voices_share_one_loaded_model_and_no_microphone_is_opened(self):
        import pat
        from speech_service import SpeechEngine
        class Model:
            sample_rate = 16000
            loads = 0
            @classmethod
            def load_model(cls, **_):
                cls.loads += 1
                return cls()
            def get_state_for_audio_prompt(self, voice):
                return voice
            def generate_audio_stream(self, state, text, stop):
                yield types.SimpleNamespace(numpy=lambda: np.zeros(80, dtype=np.float32))
        russian = types.SimpleNamespace(warm_text="Ready", stream=lambda *_: iter([np.zeros(80)]))
        with mock.patch.dict("sys.modules", {"pocket_tts": types.SimpleNamespace(TTSModel=Model)}), mock.patch.object(pat, "BatchEar") as ears, mock.patch("voice_loop.PiperVoice", return_value=russian), mock.patch.object(pat, "SpeechDetector", return_value=types.SimpleNamespace(session=object())):
            engine = SpeechEngine(lambda _: None)
        self.assertEqual(Model.loads, 1)
        self.assertEqual(len(engine.voices), len(pat.ENGLISH_VOICES) + 2)
        self.assertEqual(ears.call_count, 2)
        self.assertTrue(all(call.kwargs["mic"] is False for call in ears.call_args_list))
        self.assertEqual(len({id(voice.model) for (lang, _), voice in engine.voices.items() if lang == "en"}), 1)


from test_support import setup_profile as setUpModule, teardown_profile as tearDownModule

if __name__ == "__main__":
    unittest.main()
