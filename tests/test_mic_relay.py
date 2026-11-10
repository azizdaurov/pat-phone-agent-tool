"""Microphone forwarding tests use generated arrays and fake devices, never a real microphone."""
import itertools
import queue
import threading
import types
import unittest
from unittest import mock

import numpy as np

from mic_relay import MicRelay


class Relay(unittest.TestCase):
    def test_signal_on_second_microphone_channel_reaches_both_cable_channels(self):
        relay = MicRelay(48000, 48000)
        captured = np.column_stack((np.zeros(128), np.full(128, 0.4))).astype(np.float32)
        relay.capture(captured, 128, None, None)
        output = np.empty((128, 2), dtype=np.float32)
        relay.render(output, 128, None, None)
        np.testing.assert_allclose(output, 0.2)
        self.assertEqual(relay.forwarded_frames, 128)

    def test_no_input_produces_silence_instead_of_stale_or_uninitialized_audio(self):
        relay = MicRelay(48000, 48000)
        output = np.ones((128, 2), dtype=np.float32)
        relay.render(output, 128, None, None)
        np.testing.assert_array_equal(output, np.zeros_like(output))

    def test_different_callback_sizes_keep_sample_order(self):
        relay = MicRelay(48000, 48000)
        relay.capture(np.arange(9, dtype=np.float32)[:, None], 9, None, None)
        outputs = []
        for count in (4, 5):
            out = np.empty((count, 1), dtype=np.float32)
            relay.render(out, count, None, None)
            outputs.append(out[:, 0])
        np.testing.assert_array_equal(np.concatenate(outputs), np.arange(9))

    def test_native_rate_conversion_is_continuous_across_input_blocks(self):
        relay = MicRelay(44100, 48000, max_blocks=20)
        audio = np.sin(2 * np.pi * 220 * np.arange(4410) / 44100).astype(np.float32)
        for chunk in np.array_split(audio, 7):
            relay.capture(chunk[:, None], len(chunk), None, None)
        out = np.zeros((4800, 1), dtype=np.float32)
        relay.render(out, 4800, None, None)
        self.assertGreaterEqual(relay.forwarded_frames, 4798)
        expected = np.sin(2 * np.pi * 220 * np.arange(relay.forwarded_frames) / 48000)
        np.testing.assert_allclose(out[:relay.forwarded_frames, 0], expected, atol=0.001)

    def test_backlog_is_bounded_and_old_audio_is_dropped(self):
        relay = MicRelay(48000, 48000, max_blocks=2)
        for value in range(10):
            relay.capture(np.full((10, 1), value, dtype=np.float32), 10, None, None)
        self.assertEqual(relay.blocks.qsize(), 2)
        self.assertEqual(relay.dropped_blocks, 8)


def no_echo_cancellation(*args):
    raise OSError("Windows' echo cancellation couldn't open: not here")


class DeviceSetup(unittest.TestCase):
    def devices(self):
        import pat
        mic = {"name": "Mic", "default_samplerate": 44100, "max_input_channels": 2}
        speaker = {"name": "Speakers", "default_samplerate": 48000, "max_output_channels": 2}
        cable = {"name": "Cable", "default_samplerate": 48000, "max_output_channels": 2}
        return mock.patch.object(pat.sd, "query_devices", side_effect=lambda index: {1: speaker, 2: mic}.get(index, cable))

    def test_takeover_defaults_to_the_plain_microphone_without_opening_the_canceller(self):
        import pat
        caller = types.SimpleNamespace(rate=48000, channels=2, blocks=queue.Queue(), drop_waiting=lambda: None)
        with self.devices(), mock.patch.object(pat.sd, "InputStream") as capture, mock.patch.object(pat.sd, "OutputStream"), \
                mock.patch("echo_cancel.EchoCancelledMic", side_effect=AssertionError("cancellation is off by default")):
            takeover = pat.LaptopTakeover(caller, 1, 2, 3)
            self.assertFalse(takeover.echo_cancelled)
            self.assertEqual(capture.call_args.kwargs["samplerate"], 44100)
            self.assertEqual(capture.call_args.kwargs["channels"], 2)
            takeover.start()
            takeover.stop()

    def test_takeover_opens_native_capture_and_separate_call_output(self):
        import pat
        caller = types.SimpleNamespace(rate=48000, channels=2, blocks=queue.Queue(), drop_waiting=lambda: None)
        with self.devices(), mock.patch.object(pat.sd, "InputStream") as capture, mock.patch.object(pat.sd, "OutputStream") as playback, mock.patch.object(pat.sd, "Stream", side_effect=AssertionError("do not use a combined duplex stream")):
            takeover = pat.LaptopTakeover(caller, 1, 2, 3, echo_cancel=no_echo_cancellation)
            self.assertFalse(takeover.echo_cancelled)
            self.assertEqual(capture.call_args.kwargs["samplerate"], 44100)
            self.assertEqual(capture.call_args.kwargs["channels"], 2)
            self.assertEqual(playback.call_args.kwargs["device"], 3)
            self.assertEqual(playback.call_args.kwargs["channels"], 2)
            takeover.start()
            takeover.stop()

    def test_takeover_uses_windows_echo_cancellation_when_it_opens(self):
        import pat
        caller = types.SimpleNamespace(rate=48000, channels=2, blocks=queue.Queue(), drop_waiting=lambda: None)
        opened = []

        def echo_cancelled(microphone, speaker, callback):
            stream = mock.Mock(active=True)
            opened.append((microphone, speaker, callback, stream))
            return stream

        with self.devices(), mock.patch.object(pat.sd, "InputStream", side_effect=AssertionError("the plain microphone isn't needed")), \
                mock.patch.object(pat.sd, "OutputStream"), mock.patch("echo_cancel.EchoCancelledMic", side_effect=echo_cancelled):
            takeover = pat.LaptopTakeover(caller, 1, 2, 3, echo_cancel=True)
        microphone, speaker, callback, stream = opened[0]
        self.assertEqual((microphone, speaker), ("Mic", "Speakers"))  # the canceller removes what this speaker plays
        self.assertTrue(takeover.echo_cancelled)
        self.assertIs(takeover.microphone, stream)
        self.assertEqual(takeover.relay.input_rate, 16000)  # the canceller's 16 kHz mono, raised to the cable's rate
        callback(np.full((160, 1), 0.25, dtype=np.float32), 160, None, None)
        self.assertEqual(takeover.relay.input_frames, 160)
        self.assertAlmostEqual(takeover.relay.peak, 0.25)

    def test_the_message_says_whether_headphones_are_needed(self):
        import pat
        for cancelled, expected in ((True, "speakers are fine"), (False, "Use wired headphones")):
            printed = []
            line = types.SimpleNamespace(ended=threading.Event(), to_phone=lambda: None)
            conversation = types.SimpleNamespace(stopped=threading.Event(), hand_over=threading.Event())
            mouth = types.SimpleNamespace(say=lambda *a: None, drain=lambda: None, token=None)
            fake = mock.Mock(echo_cancelled=cancelled)
            fake.problem.side_effect = lambda: line.ended.set()  # the call ends right away
            with mock.patch.object(pat, "real_devices", return_value=(1, 2)), mock.patch.object(pat, "LaptopTakeover", return_value=fake) as open_audio, \
                    mock.patch("builtins.print", side_effect=lambda *a, **k: printed.append(" ".join(map(str, a)))):
                pat.stay_on_laptop(conversation, line, None, mouth, types.SimpleNamespace(owner="Aziz", owner_ru="Азиз"),
                                   types.SimpleNamespace(language="en"), 3, headsets=lambda: [], noise_preference=lambda: cancelled)
            self.assertIs(open_audio.call_args.kwargs["echo_cancel"], cancelled)
            self.assertIn(expected, " ".join(printed))


class NoiseChoice(unittest.TestCase):
    def run_takeover(self, streams, preference, end_after=1):
        import pat
        line = types.SimpleNamespace(ended=threading.Event(), to_phone=mock.Mock())
        conversation = types.SimpleNamespace(stopped=threading.Event(), hand_over=threading.Event())
        mouth = types.SimpleNamespace(say=lambda *a: None, drain=lambda: None, token=None)
        args = types.SimpleNamespace(owner="Aziz", owner_ru="Азиз")
        remaining = [end_after]

        def finish():
            remaining[0] -= 1
            if remaining[0] == 0:
                line.ended.set()

        streams[-1].problem.side_effect = finish
        with mock.patch.object(pat, "real_devices", return_value=(1, 2)), \
                mock.patch.object(pat, "LaptopTakeover", side_effect=streams) as open_audio, \
                mock.patch.object(pat.time, "monotonic", side_effect=itertools.count()), \
                mock.patch.object(pat.time, "sleep"):
            pat.stay_on_laptop(conversation, line, None, mouth, args, types.SimpleNamespace(language="en"), 3,
                               headsets=lambda: [], noise_preference=preference)
        self.assertFalse(conversation.hand_over.is_set())
        line.to_phone.assert_not_called()
        for stream in streams:
            stream.start.assert_called_once()
            stream.stop.assert_called_once()
        return open_audio

    def test_cancellation_can_be_paused_and_resumed_during_takeover(self):
        selected = [True]
        streams = [mock.Mock(echo_cancelled=value) for value in (True, False, True)]
        for stream, next_choice in zip(streams, (False, True)):
            stream.problem.side_effect = lambda value=next_choice: selected.__setitem__(0, value)
        open_audio = self.run_takeover(streams, lambda: selected[0])
        self.assertEqual([call.kwargs["echo_cancel"] for call in open_audio.call_args_list], [True, False, True])

    def test_unavailable_cancellation_is_not_reopened_on_every_settings_check(self):
        stream = mock.Mock(echo_cancelled=False)
        preference = mock.Mock(return_value=True)
        open_audio = self.run_takeover([stream], preference, end_after=3)
        open_audio.assert_called_once()
        self.assertEqual(preference.call_count, 3)


class LostDevice(unittest.TestCase):
    def takeover(self):
        import pat
        takeover = pat.LaptopTakeover.__new__(pat.LaptopTakeover)
        takeover.error, takeover.started = None, 100.0
        takeover.streams = [types.SimpleNamespace(active=True), types.SimpleNamespace(active=True)]
        takeover.relay = MicRelay(48000, 48000)
        return takeover

    def test_working_audio_is_no_problem(self):
        takeover = self.takeover()
        self.assertIsNone(takeover.problem(now=101.0))
        takeover.relay.last_capture = 105.0
        self.assertIsNone(takeover.problem(now=106.5))

    def test_a_microphone_that_stops_sending_is_noticed(self):
        takeover = self.takeover()
        self.assertIn("microphone", takeover.problem(now=103.0))
        takeover.relay.last_capture = 105.0
        self.assertIn("microphone", takeover.problem(now=107.5))

    def test_a_stopped_stream_or_speaker_error_is_noticed(self):
        takeover = self.takeover()
        takeover.streams[1].active = False
        self.assertIn("stopped", takeover.problem(now=100.5))
        takeover = self.takeover()
        takeover.error = "the speaker stopped: unplugged"
        self.assertEqual(takeover.problem(now=100.5), "the speaker stopped: unplugged")

    def test_lost_device_moves_the_call_to_the_iphone(self):
        import pat
        moved = []
        line = types.SimpleNamespace(ended=threading.Event(), to_phone=lambda: moved.append(True))
        conversation = types.SimpleNamespace(stopped=threading.Event(), hand_over=threading.Event())
        mouth = types.SimpleNamespace(say=lambda *a: None, drain=lambda: None, token=None)
        args = types.SimpleNamespace(owner="Aziz", owner_ru="Азиз")
        brief = types.SimpleNamespace(language="en")
        fake = mock.Mock()
        fake.problem.return_value = "the microphone stopped sending audio"
        with mock.patch.object(pat, "real_devices", return_value=(1, 2)), mock.patch.object(pat, "LaptopTakeover", return_value=fake):
            pat.stay_on_laptop(conversation, line, None, mouth, args, brief, 3, headsets=lambda: [])
        self.assertEqual(moved, [True])
        self.assertTrue(conversation.hand_over.is_set())
        fake.stop.assert_called_once()

    def test_a_headset_that_connected_during_the_call_sends_it_to_the_iphone(self):
        import pat
        moved, told, said = [], [], []
        line = types.SimpleNamespace(ended=threading.Event(), to_phone=lambda: moved.append(True))
        conversation = types.SimpleNamespace(stopped=threading.Event(), hand_over=threading.Event())
        mouth = types.SimpleNamespace(say=lambda text, token: said.append(text), drain=lambda: None, token=None)
        args = types.SimpleNamespace(owner="Aziz", owner_ru="Азиз")
        with mock.patch.object(pat, "LaptopTakeover", side_effect=AssertionError("must not open laptop audio")):
            pat.stay_on_laptop(conversation, line, None, mouth, args, types.SimpleNamespace(language="en"), 3,
                                  tell=told.append, headsets=lambda: ["Headset (AirPods Pro Hands-Free AG Audio)"])
        self.assertEqual(moved, [True])
        self.assertTrue(conversation.hand_over.is_set())
        self.assertIn("passing you to Aziz", said[0])
        self.assertIn("AirPods Pro is connected", told[0])


from tests.test_support import setup_profile as setUpModule, teardown_profile as tearDownModule

if __name__ == "__main__":
    unittest.main()
