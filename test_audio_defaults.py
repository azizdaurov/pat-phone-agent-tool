"""Switching and restoring default devices, with a pretend Windows, so nothing changes on the laptop.
Run: .venv\\Scripts\\python.exe -m unittest test_audio_defaults -v"""
import os
import tempfile
import unittest
from unittest import mock

from audio_defaults import CAPTURE, RENDER, CallDevices, WindowsAudio, chosen_devices, repair_defaults


class PretendWindows:
    def __init__(self):
        self.names = {RENDER: {"Speakers (Realtek(R) Audio)": "real", "Speakers (Boom Audio)": "silent", "CABLE Input (VB-Audio Virtual Cable)": "cable-in"},
                      CAPTURE: {"Microphone Array (Realtek(R) Audio)": "real-mic", "CABLE Output (VB-Audio Virtual Cable)": "cable-out"}}
        self.current = {RENDER: ["real", "real", "cable-in"], CAPTURE: ["real-mic", "real-mic", "real-mic"]}
        self.broken = set()

    def endpoints(self, kind):
        return self.names[kind]

    def defaults(self, kind):
        return list(self.current[kind])

    def set_default(self, device_id, role):
        if device_id in self.broken:
            raise OSError("device is gone")
        kind = RENDER if device_id in self.names[RENDER].values() else CAPTURE
        self.current[kind][role] = device_id


class Chosen(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.system = PretendWindows()
        self.system.names[RENDER]["Headphones (USB Audio)"] = "usb"

    def test_windows_default_for_calls_comes_first(self):
        self.system.current[RENDER] = ["real", "real", "usb"]
        self.assertEqual(chosen_devices(self.folder, self.system),
                         (("Headphones (USB Audio)", "Speakers (Realtek(R) Audio)"), ("Microphone Array (Realtek(R) Audio)",)))

    def test_during_a_call_it_is_what_was_picked_before_the_call(self):
        self.system.current[RENDER] = ["usb", "usb", "usb"]
        CallDevices(self.folder, self.system).use(speaker="Boom Audio", mic="CABLE Output")
        self.assertEqual(self.system.current[RENDER], ["silent"] * 3)
        self.assertEqual(chosen_devices(self.folder, self.system), (("Headphones (USB Audio)",), ("Microphone Array (Realtek(R) Audio)",)))

    def test_unknown_or_broken_gives_none(self):
        self.system.current[CAPTURE] = [None, None, None]
        self.assertEqual(chosen_devices(self.folder, self.system)[1], ())
        with open(os.path.join(self.folder, "audio-defaults.json"), "w", encoding="utf-8") as f:
            f.write("not json")
        self.assertEqual(chosen_devices(self.folder, self.system)[0], ("CABLE Input (VB-Audio Virtual Cable)", "Speakers (Realtek(R) Audio)"))


class Switching(unittest.TestCase):
    def test_other_process_can_remove_saved_defaults_before_they_are_opened(self):
        with mock.patch("audio_defaults.os.path.exists", return_value=True), mock.patch("builtins.open", side_effect=FileNotFoundError):
            self.assertEqual(self.devices.restore(), [])

    def test_other_process_can_remove_saved_defaults_during_restore(self):
        self.devices.use(speaker="Boom Audio")
        with mock.patch("audio_defaults.os.remove", side_effect=FileNotFoundError):
            self.assertEqual(self.devices.restore(), [])

    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.system = PretendWindows()
        self.before = {kind: list(ids) for kind, ids in self.system.current.items()}
        self.devices = CallDevices(self.folder, self.system)

    def test_every_role_switches_and_comes_back_as_each_one_was(self):
        self.devices.use(speaker="Boom Audio", mic="CABLE Output")
        self.assertEqual(self.system.current, {RENDER: ["silent"] * 3, CAPTURE: ["cable-out"] * 3})
        self.assertEqual(self.devices.restore(), [])
        self.assertEqual(self.system.current, self.before)

    def test_a_killed_call_is_put_right_by_the_next_start(self):
        self.devices.use(speaker="Boom Audio", mic="CABLE Output")
        self.assertEqual(CallDevices(self.folder, self.system).restore(), [])
        self.assertEqual(self.system.current, self.before)

    def test_a_second_call_after_a_crash_doesnt_save_the_switched_devices_as_normal(self):
        self.devices.use(speaker="Boom Audio", mic="CABLE Output")
        self.devices.use(speaker="Boom Audio", mic="CABLE Output")
        self.devices.restore()
        self.assertEqual(self.system.current, self.before)

    def test_restoring_twice_or_with_nothing_saved_changes_nothing(self):
        self.assertEqual(self.devices.restore(), [])
        self.system.current[RENDER][0] = "silent"  # chosen by hand, after the last call
        self.assertEqual(self.devices.restore(), [])
        self.assertEqual(self.system.current[RENDER][0], "silent")

    def test_audible_call_leaves_the_speaker_alone(self):
        self.devices.use(mic="CABLE Output")
        self.assertEqual(self.system.current[RENDER], self.before[RENDER])
        self.assertEqual(self.system.current[CAPTURE], ["cable-out"] * 3)
        self.devices.restore()
        self.assertEqual(self.system.current, self.before)

    def test_missing_device_stops_before_anything_changes(self):
        with self.assertRaisesRegex(LookupError, "Voicemeeter"):
            self.devices.use(speaker="Voicemeeter Input", mic="CABLE Output")
        self.assertEqual(self.system.current, self.before)
        self.assertFalse(os.path.exists(self.devices.path))

    def test_device_gone_by_the_end_is_reported_and_the_rest_still_restored(self):
        self.devices.use(speaker="Boom Audio", mic="CABLE Output")
        self.system.broken.add("real")
        problems = self.devices.restore()
        self.assertEqual(len(problems), 2)
        self.assertEqual(self.system.current[RENDER], ["silent", "silent", "cable-in"])
        self.assertEqual(self.system.current[CAPTURE], self.before[CAPTURE])
        self.assertFalse(os.path.exists(self.devices.path))

    def test_damaged_save_file_is_reported_not_fatal(self):
        with open(self.devices.path, "w", encoding="utf-8") as f:
            f.write("{not json")
        self.assertIn("Couldn't read", self.devices.restore()[0])
        self.assertFalse(os.path.exists(self.devices.path))


class Repairing(unittest.TestCase):
    REAL = ("Speakers (Realtek(R) Audio)", "Microphone Array (Realtek(R) Audio)")

    @staticmethod
    def virtual(name):
        return "CABLE" in name or "Boom" in name

    def test_only_the_virtual_roles_move(self):
        system = PretendWindows()  # the calls role on the cable, the others on the real speaker
        changed = repair_defaults(*self.REAL, self.virtual, system)
        self.assertEqual(system.current[RENDER], ["real", "real", "real"])
        self.assertEqual(system.current[CAPTURE], ["real-mic", "real-mic", "real-mic"])
        self.assertEqual(changed, ["CABLE Input (VB-Audio Virtual Cable) -> Speakers (Realtek(R) Audio)"])

    def test_nothing_to_do_changes_nothing(self):
        system = PretendWindows()
        system.current[RENDER] = ["real", "real", "real"]
        self.assertEqual(repair_defaults(*self.REAL, self.virtual, system), [])

    def test_no_default_at_all_gets_the_real_device(self):
        system = PretendWindows()
        system.current[CAPTURE] = [None, None, None]
        repair_defaults(*self.REAL, self.virtual, system)
        self.assertEqual(system.current[CAPTURE], ["real-mic"] * 3)

    def test_with_no_real_device_it_leaves_things_alone(self):
        system = PretendWindows()
        system.current[RENDER] = ["cable-in"] * 3
        self.assertEqual(repair_defaults(None, None, self.virtual, system), [])
        self.assertEqual(system.current[RENDER], ["cable-in"] * 3)


class RealWindows(unittest.TestCase):
    """Reads only: nothing here sets a device."""

    def test_defaults_are_among_the_devices_listed(self):
        audio = WindowsAudio()
        for kind in (RENDER, CAPTURE):
            listed = set(audio.endpoints(kind).values())
            ids = audio.defaults(kind)
            self.assertEqual(len(ids), 3)
            for device_id in ids:
                if device_id:
                    self.assertIn(device_id, listed)

    def test_names_match_what_the_audio_library_lists(self):
        import sounddevice as sd
        wasapi = {d["name"] for d in sd.query_devices() if "WASAPI" in sd.query_hostapis(d["hostapi"])["name"]}
        for kind in (RENDER, CAPTURE):
            for name in WindowsAudio().endpoints(kind):
                self.assertIn(name, wasapi)


class OtherLaptops(unittest.TestCase):
    """Devices this laptop doesn't have: one Windows can't describe must not hide the rest."""

    def test_a_device_that_cannot_be_described_is_skipped(self):
        audio = WindowsAudio()
        real = audio._describe
        calls = []

        def flaky(collection, index):
            calls.append(index)
            if index == 0:
                raise OSError("pretend: this device has no name")
            return real(collection, index)
        with mock.patch.object(audio, "_describe", side_effect=flaky):
            found = audio._endpoints_from_api(RENDER)
        self.assertGreater(len(calls), 1, "needs at least two speakers on this laptop")
        self.assertEqual(len(found), len(audio._endpoints_from_api(RENDER)) - 1)

    def test_if_the_audio_api_fails_the_registry_list_is_used(self):
        audio = WindowsAudio()
        with mock.patch.object(audio, "_endpoints_from_api", side_effect=OSError("pretend")), \
                mock.patch.object(audio, "_endpoints_from_registry", return_value={"Speakers (Pretend)": "id"}):
            self.assertEqual(audio.endpoints(RENDER), {"Speakers (Pretend)": "id"})


if __name__ == "__main__":
    unittest.main()
