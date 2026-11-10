"""The laptop microphone with Windows' own echo cancellation, for taking over a call on the laptop.

Without it, the laptop's speakers play the other person's voice, the microphone picks it up, and it goes back down the
line: they hear themselves a moment later, and an AI on their end hears speech and stops talking. Windows' Voice Capture
DSP (mfwmaaec.dll, part of every Windows 10 and 11 except the N editions without the Media Feature Pack) records the
microphone and, at the same time, what the speaker is playing, and subtracts that sound from the microphone. It runs in
software, so it doesn't depend on the sound driver.

It's driven through COM with ctypes, like audio_defaults.py, so it needs no extra package. Microsoft documents it as the
"Voice Capture DSP" (CLSID_CWMAudioAEC); the property numbers below are the MFPKEY_WMAAECMA_* ones in wmcodecdsp.h.
Run this file to try it: it plays nothing and records 5 seconds through the canceller.
"""
import ctypes
import threading
import time
import uuid
from ctypes import POINTER, WINFUNCTYPE, byref, c_int, c_long, c_longlong, c_ubyte, c_ulong, c_ushort, c_void_p

import numpy as np

from audio_defaults import CAPTURE, RENDER, WindowsAudio, _create, _method, _release

RATE = 16000  # the canceller's output: 16 kHz mono, which is what a wideband phone call carries anyway
CHANNELS = 1
OPEN_SECONDS = 10  # opening the canceller takes well under a second; this only stops a hung driver from hanging Pat
POLL_SECONDS = 0.01  # the canceller hands out 10 ms of sound at a time

CANCELLER = "745057c7-f353-4f2d-a7ee-58434477730e"  # CLSID_CWMAudioAEC
MEDIA_OBJECT = "d8ad0f58-5494-4102-97c5-ec798e59bcf4"  # IID_IMediaObject
PROPERTY_STORE = "886d8eeb-8cf2-4446-8d02-cdba1dbdcf99"
MEDIA_BUFFER = "59eff8b9-938c-4a26-82f2-95cb84cdc837"
UNKNOWN = "00000000-0000-0000-c000-000000000046"
DEVICE_ENUMERATOR = ("BCDE0395-E52F-467C-8E3D-C4579291692E", "A95664D2-9614-4F35-A746-DE8DB63617E6")
SETTINGS = "6f52c567-0360-4bd2-9617-ccbf1421c939"  # the property set of all MFPKEY_WMAAECMA_* settings
SYSTEM_MODE, SOURCE_MODE, DEVICE_INDEXES, FEATURE_MODE, AUTO_GAIN, GAIN_BOUNDER = 2, 3, 4, 5, 9, 21
SINGLE_CHANNEL_ECHO_CANCELLATION = 0
VT_I4, VT_BOOL = 3, 11
TRUE, FALSE = 0xFFFF, 0  # VARIANT_BOOL
MORE_TO_COME = 0x01000000  # DMO_OUTPUT_DATA_BUFFERF_INCOMPLETE
AUDIO, PCM, WAVE_FORMAT = ("73647561-0000-0010-8000-00aa00389b71", "00000001-0000-0010-8000-00aa00389b71",
                           "05589f81-c356-11ce-bf01-00aa0055595a")
# Methods by their place in each interface, after IUnknown's three.
SET_OUTPUT_TYPE, ALLOCATE, FREE, PROCESS_OUTPUT = 9, 18, 19, 22  # IMediaObject
SET_VALUE = 6  # IPropertyStore
GUID = c_ubyte * 16


def _guid(text):
    return GUID(*uuid.UUID(text).bytes_le)


class _PropertyKey(ctypes.Structure):
    _fields_ = [("set", GUID), ("number", c_ulong)]


class _Value(ctypes.Structure):
    """PROPVARIANT holding a number or a yes/no: type, three reserved words, the value, then room for the rest of the union."""
    _fields_ = [("vt", c_ushort), ("reserved", c_ushort * 3), ("value", c_longlong), ("rest", c_void_p)]


class _MediaType(ctypes.Structure):
    _fields_ = [("major", GUID), ("sub", GUID), ("fixed_size", c_int), ("compressed", c_int), ("sample_size", c_ulong),
                ("format_type", GUID), ("unknown", c_void_p), ("format_size", c_ulong), ("format", c_void_p)]


class _WaveFormat(ctypes.Structure):
    _pack_ = 1  # WAVEFORMATEX is packed: 18 bytes
    _fields_ = [("tag", c_ushort), ("channels", c_ushort), ("rate", c_ulong), ("bytes_per_second", c_ulong),
                ("block", c_ushort), ("bits", c_ushort), ("extra", c_ushort)]


class _OutputBuffer(ctypes.Structure):
    _fields_ = [("buffer", c_void_p), ("status", c_ulong), ("time", c_longlong), ("length", c_longlong)]


class _MediaBuffer:
    """IMediaBuffer, the one COM object the canceller needs from its caller: memory it writes its output into."""

    def __init__(self, size):
        self.data = (c_ubyte * size)()
        self.size, self.length = size, 0
        known = (uuid.UUID(UNKNOWN).bytes_le, uuid.UUID(MEDIA_BUFFER).bytes_le)

        def query(this, asked, out):
            found = ctypes.string_at(asked, 16) in known
            ctypes.cast(out, POINTER(c_void_p))[0] = this if found else None
            return 0 if found else -2147467262  # E_NOINTERFACE

        def set_length(this, length):
            if length > self.size:
                return -2147024809  # E_INVALIDARG
            self.length = length
            return 0

        def max_length(this, out):
            ctypes.cast(out, POINTER(c_ulong))[0] = self.size
            return 0

        def buffer_and_length(this, data, length):
            if data:
                ctypes.cast(data, POINTER(c_void_p))[0] = ctypes.addressof(self.data)
            if length:
                ctypes.cast(length, POINTER(c_ulong))[0] = self.length
            return 0

        # The object lives as long as this Python object, so counting references isn't needed.
        self._functions = [WINFUNCTYPE(c_long, c_void_p, c_void_p, c_void_p)(query),
                           WINFUNCTYPE(c_ulong, c_void_p)(lambda this: 1),
                           WINFUNCTYPE(c_ulong, c_void_p)(lambda this: 1),
                           WINFUNCTYPE(c_long, c_void_p, c_ulong)(set_length),
                           WINFUNCTYPE(c_long, c_void_p, c_void_p)(max_length),
                           WINFUNCTYPE(c_long, c_void_p, c_void_p, c_void_p)(buffer_and_length)]
        self._table = (c_void_p * len(self._functions))(*[ctypes.cast(f, c_void_p).value for f in self._functions])
        self._object = (c_void_p * 1)(ctypes.addressof(self._table))
        self.pointer = ctypes.addressof(self._object)

    def take(self):
        sound = np.frombuffer(bytes(self.data[:self.length]), dtype=np.int16).astype(np.float32) / 32768
        self.length = 0
        return sound


def endpoint_position(kind, name, names=None):
    """Where a device sits in Windows' list of working devices, which is how the canceller is told which to use."""
    names = _ordered_names(kind) if names is None else names
    if name not in names:
        raise OSError(f"Windows doesn't list '{name}' as a working device")
    return names.index(name)


def _ordered_names(kind):
    enumerator = _create(*DEVICE_ENUMERATOR)
    names = []
    try:
        collection = c_void_p()
        _method(enumerator, 3, c_int, c_ulong, POINTER(c_void_p))(enumerator, kind, 1, byref(collection))
        try:
            count = ctypes.c_uint()
            _method(collection, 3, POINTER(ctypes.c_uint))(collection, byref(count))
            for index in range(count.value):
                try:
                    names.append(WindowsAudio()._describe(collection, index)[0])
                except OSError:
                    names.append(None)  # keeps the positions right
        finally:
            _release(collection)
    finally:
        _release(enumerator)
    return names


def _set(store, number, kind, value):
    key, setting = _PropertyKey(_guid(SETTINGS), number), _Value(vt=kind, value=value)
    _method(store, SET_VALUE, POINTER(_PropertyKey), POINTER(_Value))(store, byref(key), byref(setting))


class EchoCancelledMic:
    """A microphone stream, shaped like sounddevice's InputStream for LaptopTakeover: start(), stop(), close(), active.
    `callback(data, frames, time, status)` gets 16 kHz mono float32 blocks of shape (frames, 1).

    Opening raises OSError when Windows can't give echo cancellation for this pair of devices, so the caller can fall back
    to the plain microphone. All COM calls happen on one thread of its own, which Windows requires of this object."""

    def __init__(self, microphone, speaker, callback, positions=None):
        self.callback = callback
        self.error = None
        self._go, self._stop, self._ready = threading.Event(), threading.Event(), threading.Event()
        self._failure = None
        if positions is None:
            positions = (endpoint_position(CAPTURE, microphone), endpoint_position(RENDER, speaker))
        self._thread = threading.Thread(target=self._run, args=positions, daemon=True, name="echo-cancel")
        self._thread.start()
        if not self._ready.wait(OPEN_SECONDS):
            self._stop.set()
            raise OSError("Windows' echo cancellation didn't open in time")
        if self._failure:
            raise OSError(f"Windows' echo cancellation couldn't open: {self._failure}")

    @property
    def active(self):
        return self._thread.is_alive() and self.error is None and self._go.is_set() and not self._stop.is_set()

    def start(self):
        self._go.set()

    def stop(self):
        self._stop.set()
        self._go.set()
        if self._thread is not threading.current_thread():
            self._thread.join(2)

    def close(self):
        self.stop()

    def _open(self, microphone, speaker):
        canceller = _create(CANCELLER, MEDIA_OBJECT)
        store = c_void_p()
        try:
            asked = _guid(PROPERTY_STORE)
            _method(canceller, 0, POINTER(GUID), POINTER(c_void_p))(canceller, byref(asked), byref(store))
            _set(store, SYSTEM_MODE, VT_I4, SINGLE_CHANNEL_ECHO_CANCELLATION)
            _set(store, SOURCE_MODE, VT_BOOL, TRUE)  # it records the devices itself
            _set(store, DEVICE_INDEXES, VT_I4, (speaker << 16) | microphone)
            # Its own settings, with two changes: no automatic gain, and it never moves the microphone level in
            # Windows' sound settings. Echo cancellation and noise suppression stay on.
            _set(store, FEATURE_MODE, VT_BOOL, TRUE)
            _set(store, AUTO_GAIN, VT_BOOL, FALSE)
            _set(store, GAIN_BOUNDER, VT_BOOL, FALSE)
            shape = _WaveFormat(1, CHANNELS, RATE, RATE * 2 * CHANNELS, 2 * CHANNELS, 16, 0)
            media = _MediaType(_guid(AUDIO), _guid(PCM), 1, 0, shape.block, _guid(WAVE_FORMAT), None,
                               ctypes.sizeof(shape), ctypes.addressof(shape))
            _method(canceller, SET_OUTPUT_TYPE, c_ulong, POINTER(_MediaType), c_ulong)(canceller, 0, byref(media), 0)
            _method(canceller, ALLOCATE)(canceller)
        except OSError:
            if store:
                _release(store)
            _release(canceller)
            raise
        return canceller, store

    def _run(self, microphone, speaker):
        ctypes.windll.ole32.CoInitialize(None)
        try:
            canceller, store = self._open(microphone, speaker)
        except OSError as error:
            self._failure = str(error) or type(error).__name__
            self._ready.set()
            return
        self._ready.set()
        try:
            self._go.wait()
            if not self._stop.is_set():
                self._pump(canceller)
        except OSError as error:
            self.error = f"echo cancellation stopped: {error}"
        finally:
            try:
                _method(canceller, FREE)(canceller)
            except OSError:
                pass
            _release(store)
            _release(canceller)
            ctypes.windll.ole32.CoUninitialize()

    def _pump(self, canceller):
        buffer = _MediaBuffer(RATE * 2 * CHANNELS)  # room for a second, far more than one 10 ms piece
        out = _OutputBuffer(buffer=buffer.pointer)
        status = c_ulong()
        process = _method(canceller, PROCESS_OUTPUT, c_ulong, c_ulong, POINTER(_OutputBuffer), POINTER(c_ulong))
        while not self._stop.is_set():
            while True:
                out.status = 0
                process(canceller, 0, 1, byref(out), byref(status))
                if buffer.length:
                    sound = buffer.take()
                    self.callback(sound.reshape(-1, CHANNELS), len(sound), None, None)
                if not out.status & MORE_TO_COME:
                    break
            time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    import sounddevice as sd
    from pat import real_devices

    speaker, microphone = real_devices()
    if speaker is None or microphone is None:
        raise SystemExit("No real speaker or microphone found.")
    names = sd.query_devices(microphone)["name"], sd.query_devices(speaker)["name"]
    pieces = []
    mic = EchoCancelledMic(*names, lambda data, *rest: pieces.append(data[:, 0].copy()))
    print(f"Recording 5 s from '{names[0]}', cancelling the echo of '{names[1]}'. Say something.")
    mic.start()
    time.sleep(5)
    mic.stop()
    sound = np.concatenate(pieces) if pieces else np.zeros(0)
    print(f"Got {len(sound) / RATE:.1f} s, loudest {np.max(np.abs(sound)) if len(sound) else 0:.3f}.")
