"""Windows' echo canceller wrapper, tested without opening it: device positions, the buffer it writes into, and how
opening, failing and stopping behave."""
import ctypes
import threading
import time
import unittest
import uuid
from ctypes import POINTER, WINFUNCTYPE, byref, c_long, c_ulong, c_void_p
from unittest import mock

import numpy as np

import echo_cancel
from echo_cancel import EchoCancelledMic, _MediaBuffer, endpoint_position


class Positions(unittest.TestCase):
    def test_a_device_is_found_by_its_place_in_windows_list(self):
        names = ["Microphone Array (Realtek(R) Audio)", None, "CABLE Output (VB-Audio Virtual Cable)"]
        self.assertEqual(endpoint_position(1, "CABLE Output (VB-Audio Virtual Cable)", names), 2)  # the unnamed one keeps its place

    def test_a_missing_device_is_an_error_the_takeover_can_fall_back_from(self):
        with self.assertRaises(OSError):
            endpoint_position(1, "USB Microphone", ["Microphone Array (Realtek(R) Audio)"])


class Buffer(unittest.TestCase):
    """Calls the buffer through its COM table, the way the canceller does."""

    def method(self, buffer, index, restype, *arguments):
        table = ctypes.cast(buffer.pointer, POINTER(POINTER(c_void_p))).contents
        return WINFUNCTYPE(restype, c_void_p, *arguments)(table[index])

    def test_the_canceller_can_write_into_it_and_the_sound_comes_out(self):
        buffer = _MediaBuffer(64)
        size = c_ulong()
        self.assertEqual(self.method(buffer, 4, c_long, POINTER(c_ulong))(buffer.pointer, byref(size)), 0)
        self.assertEqual(size.value, 64)
        memory, length = c_void_p(), c_ulong()
        self.method(buffer, 5, c_long, POINTER(c_void_p), POINTER(c_ulong))(buffer.pointer, byref(memory), byref(length))
        self.assertEqual(length.value, 0)
        samples = np.array([16384, -16384, 0, 32767], dtype=np.int16)
        ctypes.memmove(memory.value, samples.tobytes(), samples.nbytes)
        self.assertEqual(self.method(buffer, 3, c_long, c_ulong)(buffer.pointer, samples.nbytes), 0)
        np.testing.assert_allclose(buffer.take(), [0.5, -0.5, 0.0, 32767 / 32768])
        self.assertEqual(buffer.length, 0)

    def test_it_refuses_more_than_it_holds_and_answers_only_for_its_own_interfaces(self):
        buffer = _MediaBuffer(8)
        self.assertNotEqual(self.method(buffer, 3, c_long, c_ulong)(buffer.pointer, 9), 0)
        out = c_void_p()
        own = ctypes.create_string_buffer(uuid.UUID(echo_cancel.MEDIA_BUFFER).bytes_le)
        other = ctypes.create_string_buffer(uuid.UUID(echo_cancel.PROPERTY_STORE).bytes_le)
        query = self.method(buffer, 0, c_long, c_void_p, POINTER(c_void_p))
        self.assertEqual(query(buffer.pointer, ctypes.addressof(own), byref(out)), 0)
        self.assertEqual(out.value, buffer.pointer)
        self.assertNotEqual(query(buffer.pointer, ctypes.addressof(other), byref(out)), 0)
        self.assertIsNone(out.value)


class Opening(unittest.TestCase):
    def setUp(self):
        # Nothing real is opened: the COM calls around the canceller do nothing.
        for name in ("_method", "_release"):
            patcher = mock.patch.object(echo_cancel, name, return_value=lambda *a: 0)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_a_canceller_that_cant_open_raises_so_the_takeover_uses_the_plain_microphone(self):
        with mock.patch.object(EchoCancelledMic, "_open", side_effect=OSError("class not registered")):
            with self.assertRaises(OSError) as raised:
                EchoCancelledMic("Mic", "Speakers", lambda *a: None, positions=(0, 2))
        self.assertIn("class not registered", str(raised.exception))

    def test_sound_flows_only_after_start_and_stops_with_stop(self):
        blocks, pumping = [], threading.Event()

        def pump(this, canceller):
            pumping.set()
            while not this._stop.is_set():
                this.callback(np.zeros((160, 1), np.float32), 160, None, None)
                time.sleep(0.01)

        with mock.patch.object(EchoCancelledMic, "_open", return_value=(c_void_p(1), c_void_p(2))), \
                mock.patch.object(EchoCancelledMic, "_pump", pump):
            mic = EchoCancelledMic("Mic", "Speakers", lambda data, *rest: blocks.append(data.shape), positions=(0, 2))
            time.sleep(0.05)
            self.assertEqual(blocks, [])
            self.assertFalse(mic.active)
            mic.start()
            self.assertTrue(pumping.wait(2))
            time.sleep(0.05)
            self.assertTrue(mic.active)
            mic.stop()
            self.assertFalse(mic.active)
            count = len(blocks)
            time.sleep(0.05)
        self.assertGreater(count, 0)
        self.assertEqual(len(blocks), count)
        self.assertEqual(blocks[0], (160, 1))

    def test_a_failure_while_running_is_reported_as_a_problem(self):
        def pump(this, canceller):
            raise OSError("device removed")

        with mock.patch.object(EchoCancelledMic, "_open", return_value=(c_void_p(1), c_void_p(2))), \
                mock.patch.object(EchoCancelledMic, "_pump", pump):
            mic = EchoCancelledMic("Mic", "Speakers", lambda *a: None, positions=(0, 2))
            mic.start()
            mic._thread.join(2)
        self.assertIn("device removed", mic.error)
        self.assertFalse(mic.active)


if __name__ == "__main__":
    unittest.main()
