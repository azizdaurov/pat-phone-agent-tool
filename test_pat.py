"""Tests with no call and no virtual cable. Run: .venv\\Scripts\\python.exe -m unittest test_pat -v
Rehearsal uses the real speech models and a real Haiku turn, on your plan login. No sound is played."""
import os
import sys
import tempfile
import threading
import types
import time
import unittest
from unittest import mock
import wave

import numpy as np

import pat
from pat import FRAME, MIC_RATE

HERE = os.path.dirname(os.path.abspath(__file__))
SAMPLE = os.path.join(HERE, "voice-loop", "samples", "ru_piper_irina.wav")
FAKE_PHONE = r"""
import sys
print("phone    : iPhone Aziz"); print("connect  : True"); print("commands: d <number> dial")
print("call> ", end="", flush=True)
for raw in sys.stdin:
    word = raw.strip()
    if word.startswith("d "):
        print(f"dial {word[2:]}: Success")
        print("\n-- Outgoing +998: Dialing, audio=RemoteDevice, muted=False")
        print("\n-- Outgoing +998: Talking, audio=LocalDevice, muted=False", flush=True)
    elif word == "a":
        print("answer: Success")
        print("\n-- Incoming Mom (+998): Talking, audio=LocalDevice, muted=False", flush=True)
    elif word == "h":
        print("hang up: Success")
        print("\n-- call ended (0 active)", flush=True)
    elif word == "blip":
        print("\n-- call ended (0 active)", flush=True)
        print("\n-- Outgoing +998: Talking, audio=LocalDevice, muted=False", flush=True)
    elif word == "second":
        print("\n-- call ended (1 active)", flush=True)
    elif word == "stuck":
        print("\n-- Outgoing +998: Talking, audio=RemoteDevice, muted=False", flush=True)
    elif word == "moved":
        print("\n-- Outgoing +998: Talking, audio=LocalDevice, muted=False", flush=True)
    elif word == "die":
        sys.exit(0)
    elif word == "ring":
        print("\n-- Incoming Mom (+998): Incoming, audio=RemoteDevice, muted=False   (type 'a' to answer, 'h' to reject)", flush=True)
    elif word == "q":
        break
    print("call> ", end="", flush=True)
"""


def load_sample():
    with wave.open(SAMPLE) as f:
        rate, audio = f.getframerate(), np.frombuffer(f.readframes(f.getnframes()), dtype=np.int16)
    # The file is several sentences with short pauses; the opening seconds are one turn.
    return pat.to_16k(audio.astype(np.float32) / 32768, 1, rate)[:MIC_RATE * 4]


def framed(audio, realtime=False):
    for start in range(0, len(audio) - FRAME + 1, FRAME):
        if realtime:
            time.sleep(FRAME / MIC_RATE)
        yield audio[start:start + FRAME]


class Resample(unittest.TestCase):
    def test_stereo_48k(self):
        tone = np.sin(2 * np.pi * 440 * np.arange(4800) / 48000).astype(np.float32)
        out = pat.to_16k(np.repeat(tone, 2), 2, 48000)
        self.assertEqual(len(out), 1600)
        self.assertAlmostEqual(float(np.abs(out).max()), 1.0, delta=0.05)

    def test_44k(self):
        self.assertAlmostEqual(len(pat.to_16k(np.zeros(4410, dtype=np.float32), 1, 44100)), 1600, delta=1)


class Phone(unittest.TestCase):
    def setUp(self):
        script = os.path.join(tempfile.mkdtemp(), "fake_phone.py")
        with open(script, "w", encoding="utf-8") as f:
            f.write(FAKE_PHONE)
        self.log = os.path.join(os.path.dirname(script), "phone.log")
        self.line = pat.PhoneLine((sys.executable, "-u", script), log_path=self.log, end_grace=0.3)
        self.assertTrue(self.line.wait_ready(20))

    def tearDown(self):
        self.line.close()

    def test_dial_then_hang_up(self):
        self.line.dial("+998")
        self.assertEqual(self.line.wait_for(["Talking"], 5)[0], "Talking")
        self.assertTrue(self.line.in_call)
        self.line.hang_up()
        self.assertEqual(self.line.wait_for(["Never"], 5)[0], "Ended")
        self.assertFalse(self.line.in_call)

    def test_incoming_name_and_answer(self):
        self.line._send("ring")
        self.assertEqual(self.line.wait_for(["Incoming"], 5), ("Incoming", "Mom (+998)"))
        self.line.answer()
        self.assertEqual(self.line.wait_for(["Talking"], 5)[0], "Talking")

    def test_timeout(self):
        self.assertIsNone(self.line.wait_for(["Talking"], 0.2))

    def test_call_that_blips_during_dialing_is_not_given_up_on(self):
        self.line._send("blip")
        self.assertEqual(self.line.wait_for(["Talking"], 5)[0], "Talking")
        time.sleep(0.6)
        self.assertFalse(self.line.ended.is_set())
        self.assertTrue(self.line.in_call)

    def test_other_call_ending_does_not_end_this_one(self):
        self.line.dial("+998")
        self.line.wait_for(["Talking"], 5)
        self.line._send("second")
        time.sleep(0.6)
        self.assertFalse(self.line.ended.is_set())
        self.assertTrue(self.line.in_call)

    def test_call_stuck_on_the_iphone_is_noticed(self):
        self.line._send("stuck")
        self.assertEqual(self.line.wait_for(["Talking"], 5)[0], "Talking")
        self.assertFalse(self.line.wait_for_laptop_audio(0.3))

    def test_call_that_moves_to_the_laptop_late_is_accepted(self):
        self.line._send("stuck")
        self.line.wait_for(["Talking"], 5)
        self.line._send("moved")
        self.assertTrue(self.line.wait_for_laptop_audio(5))

    def test_iphonecall_dying_is_reported_as_closed(self):
        self.line._send("die")
        self.assertEqual(self.line.wait_for(["Talking"], 5)[0], "Closed")

    def test_everything_iphonecall_says_is_logged(self):
        self.line.dial("+998")
        self.line.wait_for(["Talking"], 5)
        with open(self.log, encoding="utf-8") as f:
            log = f.read()
        self.assertIn("connect  : True", log)
        self.assertIn("Dialing", log)


class Headsets(unittest.TestCase):
    def test_finds_buds_but_not_the_phone_or_plain_devices(self):
        endpoints = ["CABLE Output (VB-Audio Virtual Cable)", "Speakers (iPhone Aziz Hands-Free HF Audio)",
                     "Headset (Redmi Buds 6 Lite)", "Headphones (Redmi Buds 6 Lite)",
                     "Headset (Redmi Buds 6 Lite Hands-Free)", "Microphone (iPhone Aziz Hands-Free HF Audio)"]
        self.assertEqual(pat.connected_headsets(endpoints), ["Headset (Redmi Buds 6 Lite Hands-Free)"])

    def test_no_headset(self):
        self.assertEqual(pat.connected_headsets(["Speakers (Realtek(R) Audio)"]), [])


class EnglishVoices(unittest.TestCase):
    def test_voice_choice_sets_its_own_rate(self):
        made = []
        real = (pat.BatchEar, pat.PocketVoice, pat.TrackingMouth)
        pat.BatchEar = lambda *a, **k: "ear"
        pat.PocketVoice = lambda language, voice: made.append(voice) or "voice"
        pat.TrackingMouth = lambda *a, **k: types.SimpleNamespace()
        try:
            default = pat.load_speech("en", None)[1]
            chosen = pat.load_speech("en", "michael")[1]
            unknown = pat.load_speech("en", "somebody")[1]
        finally:
            pat.BatchEar, pat.PocketVoice, pat.TrackingMouth = real
        self.assertEqual(made, [pat.DEFAULT_ENGLISH_VOICE, "michael", "somebody"])
        self.assertEqual(default.slow_rate, pat.ENGLISH_VOICES[pat.DEFAULT_ENGLISH_VOICE]["chars_per_second"])
        self.assertEqual(chosen.slow_rate, pat.ENGLISH_VOICES["michael"]["chars_per_second"])
        self.assertEqual(unknown.slow_rate, pat.SLOW_CHARS_PER_SECOND)

    def test_chosen_voices_and_their_default(self):
        self.assertEqual(set(pat.ENGLISH_VOICES), {"peter_yearsley", "alba", "bill_boerst", "michael", "anna", "charles"})
        self.assertIn(pat.DEFAULT_ENGLISH_VOICE, pat.ENGLISH_VOICES)

    def test_tool_offers_the_same_voices(self):
        import typing
        import phone_mcp
        hints = typing.get_type_hints(phone_mcp.place_call, include_extras=True)
        offered = set(typing.get_args(typing.get_args(hints["voice"])[0])) - {""}
        self.assertEqual(offered, set(pat.ENGLISH_VOICES))


class QuietCalls(unittest.TestCase):
    def test_audible_call_needs_a_speaker_that_isnt_the_cable(self):
        self.assertIsNone(pat.speaker_problem("Speakers (Realtek(R) Audio)"))
        self.assertIn("hear itself", pat.speaker_problem("CABLE Input (VB-Audio Virtual Cable)"))

    def test_silent_speaker_is_the_first_one_installed(self):
        for installed, expected in (({"Boom Audio"}, "Boom Audio"), ({"Boom Audio", "Voicemeeter Input"}, "Voicemeeter Input"),
                                    ({"CABLE-A Input", "Boom Audio"}, "CABLE-A Input"), (set(), None)):
            self.assertEqual(pat.find_silent_speaker(lambda name: 1 if name in installed else None), expected)

    def test_silent_speaker_can_be_named(self):
        with mock.patch.dict(os.environ, {"PAT_SILENT_SPEAKER": "Line 1"}):
            self.assertEqual(pat.find_silent_speaker(lambda name: 1 if name in ("Line 1", "Boom Audio") else None), "Line 1")
            self.assertIsNone(pat.pick_real_device([(1, "Line 1 (Virtual Audio Cable)")]))

    def test_take_over_never_picks_a_virtual_device(self):
        devices = [(1, "CABLE In 16ch (VB-Audio Virtual Cable)"), (2, "Speakers (Boom Audio)"), (3, "CABLE Input (VB-Audio Virtual Cable)"),
                   (5, "Voicemeeter Input (VB-Audio Voicemeeter VAIO)"), (6, "CABLE-A Input (VB-Audio Cable A)"), (4, "Speakers (Realtek(R) Audio)")]
        self.assertEqual(pat.pick_real_device(devices), 4)
        self.assertIsNone(pat.pick_real_device(devices[:5]))

    def test_take_over_uses_the_device_picked_in_windows(self):
        devices = [(1, "CABLE Input (VB-Audio Virtual Cable)"), (2, "Speakers (Realtek(R) Audio)"), (3, "Headphones (USB Audio)")]
        self.assertEqual(pat.preferred_device(devices, ("Headphones (USB Audio)", "Speakers (Realtek(R) Audio)")), 3)
        self.assertEqual(pat.preferred_device(devices, ("CABLE Input (VB-Audio Virtual Cable)", "Headphones (USB Audio)")), 3)
        self.assertEqual(pat.preferred_device(devices, ("Unplugged (Gone)",)), 2)
        self.assertEqual(pat.preferred_device(devices, ()), 2)

    def test_microphone_check_tells_silence_quiet_and_working_apart(self):
        info = {"name": "Microphone Array (Realtek(R) Audio)", "default_samplerate": 48000, "max_input_channels": 2}
        with mock.patch.object(pat, "real_devices", return_value=(1, 7)), mock.patch.object(pat.sd, "query_devices", return_value=info):
            fine, message = pat.check_microphone(record=lambda: np.zeros((100, 2), dtype=np.float32))
            self.assertFalse(fine)
            self.assertIn("Privacy", message)
            fine, message = pat.check_microphone(record=lambda: np.full((100, 2), 0.002, dtype=np.float32))
            self.assertFalse(fine)
            self.assertIn("quiet", message)
            self.assertEqual(pat.check_microphone(record=lambda: np.full((100, 2), 0.2, dtype=np.float32))[0], True)
            fine, message = pat.check_microphone(record=mock.Mock(side_effect=OSError("in use")))
            self.assertIn("in use", message)
        with mock.patch.object(pat, "real_devices", return_value=(1, None)):
            self.assertFalse(pat.check_microphone()[0])

    def test_take_over_never_picks_voicemeeters_other_devices_or_the_phone(self):
        devices = [(1, "Voicemeeter In 3 (VB-Audio Voicemeeter VAIO)"), (2, "Voicemeeter Out A3 (VB-Audio Voicemeeter VAIO)"),
                   (3, "Voicemeeter VAIO3 Input (VB-Audio Voicemeeter VAIO)"), (4, "Speakers (iPhone Aziz Hands-Free HF Audio)"),
                   (5, "Microphone Array (Realtek(R) Audio)")]
        self.assertEqual(pat.pick_real_device(devices), 5)

    def test_key_sets_take_over_only_when_pressed(self):
        pressed = []
        conversation = types.SimpleNamespace(take_over=threading.Event())
        pat.watch_take_over_key(conversation, is_down=lambda: bool(pressed))
        time.sleep(0.15)
        self.assertFalse(conversation.take_over.is_set())
        pressed.append(True)
        self.assertTrue(conversation.take_over.wait(1))

    def test_typing_l_takes_over_and_h_hangs_up(self):
        conversation = types.SimpleNamespace(take_over=threading.Event(), stopped=threading.Event(), hand_over=threading.Event())
        line = types.SimpleNamespace(to_phone=lambda: None)
        real = sys.stdin
        sys.stdin = iter(["l\n", "h\n"])
        try:
            pat.listen_for_keys(line, conversation)
            self.assertTrue(conversation.take_over.wait(1))
            self.assertTrue(conversation.stopped.wait(1))
            self.assertFalse(conversation.hand_over.is_set())
        finally:
            sys.stdin = real

    def test_audio_queued_before_taking_over_is_dropped(self):
        caller = pat.CallerAudio.__new__(pat.CallerAudio)
        caller.blocks = pat.queue.Queue()
        for _ in range(50):
            caller.blocks.put(np.zeros(4, dtype=np.float32))
        caller.drop_waiting()
        self.assertTrue(caller.blocks.empty())

    def test_take_over_stops_claude_with_its_own_reason(self):
        call, _ = pat_call()
        call.take_over.set()
        now = time.monotonic()
        self.assertEqual(call._stop_reason(now, now, now, False), "taken over on the laptop")


def pat_call():
    transcript = pat.Transcript(tempfile.mkdtemp())
    line = types.SimpleNamespace(ended=threading.Event())
    mouth = types.SimpleNamespace(voice=types.SimpleNamespace(clause_chars=None), token=0)
    return pat.Conversation(line, iter(()), None, mouth, None, transcript, "x"), transcript


class Turns(unittest.TestCase):
    def test_silence_then_speech_then_silence(self):
        silence = np.zeros(MIC_RATE, dtype=np.float32)
        audio = np.concatenate((silence, load_sample(), silence, silence))
        turns = pat.TurnDetector(pat.SpeechDetector())
        events = [(i, e) for i, e in ((i, turns.feed(f)) for i, f in enumerate(framed(audio))) if e]
        self.assertEqual(events[0][1], "start")
        self.assertEqual(events[-1][1], "end")
        self.assertGreater(events[0][0] * FRAME / MIC_RATE, 0.9)

    def test_silence_and_hiss_are_not_speech(self):
        rng = np.random.default_rng(0)
        for audio in (np.zeros(MIC_RATE * 3, dtype=np.float32),
                      rng.normal(0, 0.01, MIC_RATE * 3).astype(np.float32)):
            turns = pat.TurnDetector(pat.SpeechDetector())
            self.assertEqual([e for e in map(turns.feed, framed(audio)) if e], [])


class SavedAudio(unittest.TestCase):
    def test_wav_is_complete_after_close(self):
        path = os.path.join(tempfile.mkdtemp(), "call.wav")
        frames = pat.saved_frames(framed(np.zeros(FRAME * 3, dtype=np.float32)), path)
        self.assertEqual(len(list(zip(range(2), frames))), 2)
        frames.close()
        with wave.open(path) as f:
            self.assertEqual((f.getframerate(), f.getnframes()), (MIC_RATE, FRAME * 2))


class FakeLine:
    def __init__(self):
        self.ended = threading.Event()


class Rehearsal(unittest.TestCase):
    """A whole conversation, with a recording as the caller and no sound played."""

    def test_rehearsal(self):
        ear, mouth = pat.load_speech("ru", None)
        said = []
        original = mouth.say
        mouth.say = lambda text, token, on_first_audio=None: (said.append(text), original(text, token, on_first_audio))
        opening = "Здравствуйте, это Клод."
        brief = pat.CallBrief.from_dict({"goal": "Узнайте, как у человека дела.", "language": "ru"})
        brain = pat.Brain("ru", system_prompt=brief.haiku_prompt(pat.SYSTEM_PROMPTS["ru"], opening, "Aziz", "test"))
        silence = np.zeros(MIC_RATE, dtype=np.float32)
        tail = np.zeros(MIC_RATE * 20, dtype=np.float32)
        frames = framed(np.concatenate((silence, load_sample(), tail)), realtime=True)
        transcript = pat.Transcript(tempfile.mkdtemp())
        call = pat.Conversation(FakeLine(), frames, ear, mouth, brain, transcript, opening, max_seconds=40)
        reason = call.run()
        brain.close()
        with open(transcript.path, encoding="utf-8") as f:
            log = f.read()
        self.assertIn(reason, ("time limit", "goodbye"))  # real Haiku sometimes ends this odd call itself
        self.assertEqual(said[0], opening)
        self.assertIn("Them:", log)
        self.assertIn("speech started", log)
        self.assertIn(f"call over: {reason}", log)
        self.assertGreater(len(said), 1, "Claude never answered")
        self.assertFalse(any(pat.END_MARK in s for s in said))


from test_support import setup_profile as setUpModule, teardown_profile as tearDownModule

if __name__ == "__main__":
    unittest.main()
