"""Windows' default speaker and microphone: sets them for a call, and puts back what was there before.

Setting a default uses IPolicyConfig, the interface behind Windows' own Sound settings. Microsoft doesn't document it, but
it has kept the same shape since Windows 7. What was there before is saved to a file first, so if a call is killed the next
start of Pat can still put it back. Run this file to list the devices; it changes nothing.
"""
import ctypes
import json
import os
import re
import uuid
import winreg
from ctypes import POINTER, WINFUNCTYPE, byref, c_int, c_void_p, c_wchar_p

STATE_NAME = "audio-defaults.json"
RENDER, CAPTURE = 0, 1
ROLES = (0, 1, 2)  # games and system sounds, music and video, calls: Windows keeps a default for each
ENDPOINTS_KEY = r"SOFTWARE\Microsoft\Windows\CurrentVersion\MMDevices\Audio"
FRIENDLY_NAME = "{a45c254e-df1c-4efd-8020-67d146a850e0},2"  # "Speakers"
ADAPTER_NAME = "{b3f8fa53-0004-438e-9003-51a46e139bfc},6"  # "Boom Audio"
ACTIVE = 1


def _guid(text):
    return ctypes.create_string_buffer(uuid.UUID(text).bytes_le)


def _method(pointer, index, *arguments):
    """Method number `index` of a COM object. A failed call raises OSError, because of the HRESULT."""
    table = ctypes.cast(pointer, POINTER(POINTER(c_void_p))).contents
    return WINFUNCTYPE(ctypes.HRESULT, c_void_p, *arguments)(table[index])


def _create(class_id, interface_id):
    ole = ctypes.windll.ole32
    ole.CoInitialize(None)  # fails harmlessly if this thread already did it
    pointer = c_void_p()
    ctypes.OleDLL("ole32").CoCreateInstance(_guid(class_id), None, 1, _guid(interface_id), byref(pointer))
    return pointer


def _release(pointer):
    table = ctypes.cast(pointer, POINTER(POINTER(c_void_p))).contents
    WINFUNCTYPE(ctypes.c_ulong, c_void_p)(table[2])(pointer)


class WindowsAudio:
    def endpoints(self, kind):
        """{name: id} of the working devices, with names as sounddevice shows them: "Speakers (Boom Audio)"."""
        flow = "Render" if kind == RENDER else "Capture"
        found = {}
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, rf"{ENDPOINTS_KEY}\{flow}") as devices:
            for number in range(winreg.QueryInfoKey(devices)[0]):
                guid = winreg.EnumKey(devices, number)
                with winreg.OpenKey(devices, guid) as device:
                    if winreg.QueryValueEx(device, "DeviceState")[0] != ACTIVE:
                        continue
                    with winreg.OpenKey(device, "Properties") as properties:
                        friendly = winreg.QueryValueEx(properties, FRIENDLY_NAME)[0]
                        adapter = winreg.QueryValueEx(properties, ADAPTER_NAME)[0]
                found[f"{friendly} ({adapter})"] = f"{{0.0.{kind}.00000000}}.{guid}"
        return found

    def defaults(self, kind):
        """The id of the default device for each role, or None where there is none."""
        enumerator = _create("BCDE0395-E52F-467C-8E3D-C4579291692E", "A95664D2-9614-4F35-A746-DE8DB63617E6")
        ids = []
        try:
            for role in ROLES:
                device = c_void_p()
                try:
                    _method(enumerator, 4, c_int, c_int, POINTER(c_void_p))(enumerator, kind, role, byref(device))
                except OSError:
                    ids.append(None)
                    continue
                text = c_wchar_p()
                _method(device, 5, POINTER(c_wchar_p))(device, byref(text))
                ids.append(text.value)
                ctypes.windll.ole32.CoTaskMemFree(text)
                _release(device)
        finally:
            _release(enumerator)
        return ids

    def set_default(self, device_id, role):
        policy = _create("870AF99C-171D-4F9E-AF0D-E63DF40C2BC9", "F8679F50-850A-41CF-9C72-430F290290C8")
        try:
            _method(policy, 13, c_wchar_p, c_int)(policy, device_id, role)
        finally:
            _release(policy)


class CallDevices:
    def __init__(self, folder, system=None):
        self.path = os.path.join(folder, STATE_NAME)
        self.system = system or WindowsAudio()

    def use(self, speaker=None, mic=None):
        """`speaker` and `mic` are parts of device names. None leaves that one as it is. Raises LookupError if one isn't there."""
        self.restore()
        targets = []
        for kind, part in ((RENDER, speaker), (CAPTURE, mic)):
            if part:
                match = next((device_id for name, device_id in self.system.endpoints(kind).items() if part in name), None)
                if match is None:
                    raise LookupError(f"No working audio device called '{part}'.")
                targets.append((kind, match))
        saved = {str(kind): self.system.defaults(kind) for kind, _ in targets}
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path + ".tmp", "w", encoding="utf-8") as f:
            json.dump(saved, f)
        os.replace(self.path + ".tmp", self.path)
        for _, device_id in targets:
            for role in ROLES:
                self.system.set_default(device_id, role)

    def restore(self):
        """Puts back what use() saved. Returns the problems, if any. Safe to call at any time: with nothing saved it does nothing."""
        if not os.path.exists(self.path):
            return []
        try:
            with open(self.path, encoding="utf-8") as f:
                saved = json.load(f)
        except FileNotFoundError:
            return []  # The call process or note already restored these defaults.
        except ValueError as error:
            try:
                os.remove(self.path)
            except FileNotFoundError:
                pass
            return [f"Couldn't read the saved audio defaults: {error}"]
        problems = []
        for ids in saved.values():
            for role, device_id in zip(ROLES, ids):
                if device_id:
                    try:
                        self.system.set_default(device_id, role)
                    except OSError as error:  # such as a headset that has since been unplugged
                        problems.append(f"Couldn't restore a default audio device: {error}")
        try:
            os.remove(self.path)
        except FileNotFoundError:
            pass
        return problems


def headset_problem(headsets):
    """What to tell the owner when a Bluetooth headset on the laptop keeps a call's audio on the phone, or None."""
    if not headsets:
        return None
    names = [re.sub(r"^[^(]*\((.*?)(?: Hands-Free[^)]*)?\)$", r"\1", name) for name in headsets]
    them = "it" if len(names) == 1 else "them"
    return (f"{' and '.join(names)} {'is' if len(names) == 1 else 'are'} connected to the laptop, so the call can't come here "
            f"and is on your phone. Disconnect {them} to take calls on the laptop.")


def chosen_devices(folder, system=None):
    """(speakers, microphones): for each, the names the owner picked in Windows, the default for calls first, then the
    everyday one. Empty where none is known. While a call has switched the defaults, it's what was saved before the call."""
    system = system or WindowsAudio()
    saved = {}
    try:
        with open(os.path.join(folder, STATE_NAME), encoding="utf-8") as f:
            saved = json.load(f)
    except (FileNotFoundError, ValueError):
        pass
    names = []
    for kind in (RENDER, CAPTURE):
        try:
            ids = saved.get(str(kind)) or system.defaults(kind)
            by_id = {device_id: name for name, device_id in system.endpoints(kind).items()}
        except OSError:
            names.append(())
            continue
        picked = [by_id[device_id] for device_id in (ids[2], ids[0]) if device_id in by_id]
        names.append(tuple(dict.fromkeys(picked)))
    return tuple(names)


def repair_defaults(real_speaker, real_mic, is_virtual, system=None):
    """Installing a virtual audio driver can make it the default, which silences other programs. Puts any such default back on the real
    device, one role at a time, and leaves a real default alone. Returns what changed."""
    system = system or WindowsAudio()
    changed = []
    for kind, real in ((RENDER, real_speaker), (CAPTURE, real_mic)):
        names = system.endpoints(kind)
        real_id = next((device_id for name, device_id in names.items() if real and real in name), None)
        by_id = {device_id: name for name, device_id in names.items()}
        if real_id is None:
            continue
        for role, device_id in zip(ROLES, system.defaults(kind)):
            name = by_id.get(device_id)
            if name is None or is_virtual(name):
                system.set_default(real_id, role)
                changed.append(f"{name or 'nothing'} -> {by_id[real_id]}")
    return changed


if __name__ == "__main__":
    audio = WindowsAudio()
    for label, kind in (("Speakers", RENDER), ("Microphones", CAPTURE)):
        names = {device_id: name for name, device_id in audio.endpoints(kind).items()}
        print(f"{label}:", *(f"  {name}" for name in names.values()), sep="\n")
        print("Default for each role:", [names.get(device_id, device_id) for device_id in audio.defaults(kind)])
