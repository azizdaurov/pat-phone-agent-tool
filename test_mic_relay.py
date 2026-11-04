"""Microphone forwarding tests use generated arrays and fake devices, never a real microphone."""
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


class DeviceSetup(unittest.TestCase):
    def test_takeover_opens_native_capture_and_separate_call_output(self):
        import cicero
        caller = types.SimpleNamespace(rate=48000, channels=2, blocks=queue.Queue(), drop_waiting=lambda: None)
        mic = {"name": "Mic", "default_samplerate": 44100, "max_input_channels": 2}
        cable = {"name": "Cable", "default_samplerate": 48000, "max_output_channels": 2}
        with mock.patch.object(cicero.sd, "query_devices", side_effect=lambda index: mic if index == 2 else cable), mock.patch.object(cicero.sd, "InputStream") as capture, mock.patch.object(cicero.sd, "OutputStream") as playback, mock.patch.object(cicero.sd, "Stream", side_effect=AssertionError("do not use a combined duplex stream")):
            takeover = cicero.LaptopTakeover(caller, 1, 2, 3)
            self.assertEqual(capture.call_args.kwargs["samplerate"], 44100)
            self.assertEqual(capture.call_args.kwargs["channels"], 2)
            self.assertEqual(playback.call_args.kwargs["device"], 3)
            self.assertEqual(playback.call_args.kwargs["channels"], 2)
            takeover.start()
            takeover.stop()


from test_support import setup_profile as setUpModule, teardown_profile as tearDownModule

if __name__ == "__main__":
    unittest.main()
