"""Phone/headset identity checks use fake metadata only; no Bluetooth or phone calls."""
import copy
import json
import types
import unittest
from unittest import mock

from bluetooth_audio import blocking_devices
import pat

PHONE = "12345678-1111-2222-3333-123456789abc"
BUDS = "12345678-1111-2222-3333-123456789abd"


def inventory(name="Renamed Android", container=PHONE, instance="phone-node"):
    return {"schema_version": 1, "phone": {"id": "selected-phone", "container_id": PHONE, "instance_id": "phone-node"},
            "endpoints": [{"id": "audio-node", "name": name, "container_id": container,
                           "instance_ids": [instance], "services": ["BthHfAud"]}]}


class PhoneIdentity(unittest.TestCase):
    def test_android_and_renamed_iphone_are_excluded_by_identity(self):
        for name in ("Samsung", "Pixel", "My work phone", "Мой телефон", "iPhone"):
            self.assertEqual(blocking_devices(inventory(name)), [], name)

    def test_same_container_matches_without_an_instance_id(self):
        self.assertEqual(blocking_devices(inventory(instance="unrelated-node")), [])

    def test_container_format_is_normalized_and_zero_is_not_an_identity(self):
        data = inventory(container="{" + PHONE.upper() + "}", instance="unrelated-node")
        self.assertEqual(blocking_devices(data), [])
        data["phone"]["container_id"] = "00000000-0000-0000-0000-000000000000"
        data["endpoints"][0]["container_id"] = "00000000-0000-0000-0000-000000000000"
        self.assertEqual(blocking_devices(data), ["Renamed Android"])

    def test_parent_identity_works_when_container_is_missing(self):
        data = inventory(container=None)
        data["phone"]["container_id"] = None
        data["endpoints"][0]["instance_ids"] = ["audio-node", "PHONE-NODE"]
        self.assertEqual(blocking_devices(data), [])

    def test_unrelated_headset_named_iphone_is_not_exempt(self):
        self.assertEqual(blocking_devices(inventory("iPhone Hands-Free", BUDS, "headset-node")), ["iPhone Hands-Free"])

    def test_no_missing_identity_values_can_match(self):
        data = inventory(container=None, instance="")
        data["phone"] = {"id": "selected-phone", "container_id": None, "instance_id": None}
        self.assertEqual(blocking_devices(data), ["Renamed Android"])

    def test_other_phone_is_not_mistaken_for_the_selected_phone(self):
        self.assertEqual(blocking_devices(inventory("Other phone", BUDS, "other-phone")), ["Other phone"])

    def test_input_and_output_of_one_headset_are_reported_once(self):
        data = inventory("Headset", BUDS, "buds")
        data["endpoints"].append({**copy.deepcopy(data["endpoints"][0]), "id": "other-audio-node", "name": "Headset microphone"})
        self.assertEqual(blocking_devices(data), ["Headset"])

    def test_driver_metadata_detects_localized_headsets(self):
        self.assertEqual(blocking_devices(inventory("Гарнитура", BUDS, "buds")), ["Гарнитура"])

    def test_stereo_and_wired_devices_are_not_blocked(self):
        data = inventory("Headphones", BUDS, "buds")
        data["endpoints"][0]["services"] = ["BthA2dp"]
        self.assertEqual(blocking_devices(data), [])

    def test_legacy_hfp_label_can_detect_but_cannot_exempt_a_phone(self):
        data = inventory("iPhone Hands-Free", None, "other-node")
        data["endpoints"][0]["services"] = []
        self.assertEqual(blocking_devices(data), ["iPhone Hands-Free"])

    def test_invalid_or_old_inventory_is_rejected(self):
        for data in (None, [], {}, {"schema_version": 0}, {"schema_version": 1, "endpoints": "bad"},
                     {"schema_version": 1, "endpoints": [{"name": "Headset", "services": "BthHfAud"}]}):
            with self.subTest(data=data), self.assertRaises(OSError):
                blocking_devices(data)

    def test_helper_uses_the_selected_phone_command_without_connecting(self):
        fake = types.SimpleNamespace(returncode=0, stdout=json.dumps(inventory()))
        with mock.patch.object(pat, "phone_command", return_value=["fake-helper", "--device-id", "selected-phone"]), mock.patch.object(pat.subprocess, "run", return_value=fake) as run:
            self.assertEqual(pat.connected_headsets(), [])
        self.assertEqual(run.call_args.args[0], ["fake-helper", "--device-id", "selected-phone", "audio-devices-json"])

    def test_helper_failures_are_visible_instead_of_skipping_the_guard(self):
        fake = types.SimpleNamespace(returncode=1, stdout="old helper")
        with mock.patch.object(pat, "phone_command", return_value=["fake-helper"]), mock.patch.object(pat.subprocess, "run", return_value=fake):
            with self.assertRaisesRegex(OSError, "Could not check Bluetooth"):
                pat.connected_headsets()

    def test_helper_cannot_exempt_a_different_selected_phone(self):
        fake = types.SimpleNamespace(returncode=0, stdout=json.dumps(inventory()))
        with mock.patch.object(pat, "phone_command", return_value=["fake-helper", "--device-id", "different-phone"]), mock.patch.object(pat.subprocess, "run", return_value=fake):
            with self.assertRaisesRegex(OSError, "Could not check Bluetooth"):
                pat.connected_headsets()

    def test_takeover_inventory_failure_keeps_microphone_closed_and_uses_phone(self):
        import threading
        line = types.SimpleNamespace(ended=threading.Event(), to_phone=mock.Mock())
        conversation = types.SimpleNamespace(stopped=threading.Event(), hand_over=threading.Event())
        mouth = types.SimpleNamespace(say=mock.Mock(), drain=lambda: None, token=0)
        args = types.SimpleNamespace(owner="Maya", owner_ru="Майя")
        with mock.patch.object(pat, "LaptopTakeover") as capture:
            pat.stay_on_laptop(conversation, line, None, mouth, args, types.SimpleNamespace(language="en"), 0,
                               headsets=mock.Mock(side_effect=OSError("Identity check failed")))
        capture.assert_not_called()
        line.to_phone.assert_called_once()
        self.assertTrue(conversation.hand_over.is_set())


if __name__ == "__main__":
    unittest.main()
