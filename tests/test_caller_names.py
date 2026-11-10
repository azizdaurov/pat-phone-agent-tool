"""Which part of a caller's label Pat may greet them with. Pretend AI replies only; no real Claude.
Run: .venv\\Scripts\\python.exe -m unittest test_caller_names -v"""
import os
import tempfile
import threading
import unittest

from caller_names import CallerNames, checked


class Checked(unittest.TestCase):
    def test_a_name_must_come_from_the_label(self):
        self.assertEqual(checked('{"name": "Rustam"}', "Rustam work"), "Rustam")
        self.assertEqual(checked('{"name": "Азиз"}', "Азиз брат"), "Азиз")
        self.assertEqual(checked('{"name": "Bob Smith"}', "Uncle Bob"), "")  # Smith was made up
        self.assertEqual(checked('{"name": "Mister Idiot"}', "Idiot"), "")

    def test_anything_odd_means_no_name(self):
        for reply in ("", "Rustam", "{not json}", '{"name": 5}', '["Rustam"]', '{"name": "Rustam Rustam Rustam Rustam Rustam"}'):
            self.assertEqual(checked(reply, "Rustam Rustam Rustam Rustam Rustam"), "", reply)
        self.assertEqual(checked('{"name": ""}', "Restaurant"), "")


class Saved(unittest.TestCase):
    def setUp(self):
        self.path = os.path.join(tempfile.mkdtemp(), "caller-names.json")

    def test_each_label_is_asked_once_including_ones_that_are_not_names(self):
        asked = []
        names = CallerNames(ask=lambda text: (asked.append(text), '{"name": ""}' if "Carwash" in text else '{"name": "Rustam"}')[1], path=self.path)
        self.assertEqual([names.name_for("Rustam work"), names.name_for("Carwash"), names.name_for("Rustam work"), names.name_for("Carwash")],
                         ["Rustam", "", "Rustam", ""])
        self.assertEqual(asked, ["<label>Rustam work</label>", "<label>Carwash</label>"])
        self.assertEqual(names.name_for(""), "")  # an unknown caller has no label to ask about
        self.assertEqual(len(asked), 2)

    def test_a_slow_or_failing_check_gives_no_name_and_the_ring_goes_on(self):
        release = threading.Event()
        slow = CallerNames(ask=lambda text: (release.wait(5), '{"name": "Rustam"}')[1], path=self.path)
        self.assertEqual(slow.start("Rustam")(0.05), "")
        release.set()
        self.assertEqual(CallerNames(ask=lambda text: 1 / 0, path=self.path).start("Timur")(1), "")

    def test_contacts_are_checked_ahead_and_a_ring_then_waits_for_nothing(self):
        asked = []
        names = CallerNames(ask=lambda text: (asked.append(text), '{"name": "Rustam"}')[1], path=self.path)
        names.name_for("Rustam work")
        names.check_ahead(["Rustam work", "Rustam", "Carwash"]).join(5)
        self.assertEqual(len(asked), 3)  # the one already saved isn't asked again
        never = CallerNames(ask=lambda text: 1 / 0, path=self.path)
        self.assertEqual(never.name_for("Rustam"), "Rustam")  # saved, so the ring asks no AI

    def test_a_failed_check_ahead_saves_nothing_so_it_is_tried_again(self):
        CallerNames(ask=lambda text: 1 / 0, path=self.path).check_ahead(["Timur"]).join(5)
        asked = []
        CallerNames(ask=lambda text: (asked.append(text), '{"name": "Timur"}')[1], path=self.path).name_for("Timur")
        self.assertEqual(asked, ["<label>Timur</label>"])


if __name__ == "__main__":
    unittest.main()
