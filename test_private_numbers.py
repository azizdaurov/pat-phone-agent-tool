"""Real numbers stay on the laptop. Run: .venv\\Scripts\\python.exe -m unittest test_private_numbers -v"""
import json
import os
import tempfile
import unittest

from private_numbers import PrivateNumbers

NUMBER = "+998 90 000 00 01"
DIGITS = "900000001"


class Contacts(unittest.TestCase):
    def test_display_name_uses_the_saved_name_even_if_the_phone_supplies_an_alias(self):
        self.assertEqual(self.private.display_name("Different label (+998900000001)"), "Рустам")

    def test_caller_labels_do_not_break_parenthesized_area_codes(self):
        from private_numbers import split_caller
        self.assertEqual(split_caller("Alex (+1 (415) 555-0101)"), ("Alex", "+1 (415) 555-0101"))

    def setUp(self):
        self.private = PrivateNumbers(tempfile.mkdtemp())
        self.private.add_contact("Рустам", NUMBER)
        self.private.add_contact("Rustam Karimov", "+998 90 000 00 02")
        self.private.add_contact("Rustam Aliyev", "+998 90 000 00 03")

    def test_name_gives_the_number_in_any_case(self):
        self.assertEqual(self.private.resolve("рустам"), ("+998900000001", "Рустам"))

    def test_part_of_a_name_works_if_only_one_fits(self):
        self.assertEqual(self.private.resolve("Karimov")[1], "Rustam Karimov")

    def test_part_of_a_name_that_fits_two_asks_which(self):
        with self.assertRaisesRegex(LookupError, "More than one"):
            self.private.resolve("Rustam")

    def test_unknown_name_is_refused(self):
        with self.assertRaisesRegex(LookupError, "No contact"):
            self.private.resolve("Mom")

    def test_too_short_to_be_a_contact_number(self):
        with self.assertRaises(ValueError):
            self.private.add_contact("Short", "112")

    def test_removed_contact_is_gone(self):
        self.assertTrue(self.private.remove_contact("Рустам"))
        self.assertFalse(self.private.remove_contact("Рустам"))
        with self.assertRaises(LookupError):
            self.private.resolve("Рустам")


class TypedNumbers(unittest.TestCase):
    def setUp(self):
        self.private = PrivateNumbers(tempfile.mkdtemp())

    def test_every_way_of_writing_a_number_is_swapped(self):
        for written in ("+998 90 123 45 67", "+998901234567", "998901234567", "90 123 45 67", "+998 (90) 123-45-67", "901234567", "+1 415 555 0100"):
            text = self.private.protect(f"call {written} please")
            self.assertRegex(text, r"^call #\d+ please$", written)

    def test_same_number_keeps_its_placeholder_however_it_is_written(self):
        first = self.private.protect("+998 90 123 45 67")
        self.assertEqual(self.private.protect("998901234567"), first)
        self.assertEqual(self.private.protect("90 123 45 67"), first)
        self.assertNotEqual(self.private.protect("+998 90 123 45 68"), first)

    def test_a_contact_number_becomes_the_name(self):
        self.private.add_contact("Рустам", NUMBER)
        self.assertEqual(self.private.protect("call +998900000001 now"), "call Рустам now")

    def test_a_placeholder_gives_the_number_back(self):
        label = self.private.protect("+998 90 123 45 67")
        self.assertEqual(self.private.resolve(label), ("+998901234567", ""))
        self.assertEqual(self.private.reveal(f"Calling {label} now"), "Calling +998 90 123 45 67 now")

    def test_two_numbers_in_one_message(self):
        text = self.private.protect("+998901234567 or +998901234568")
        self.assertEqual(text, "#1 or #2")

    def test_things_that_arent_phone_numbers_stay(self):
        for text in ("meet at 11:00", "on 2026-11-03", "on 2026-11-03 at 10:30", "room 12", "costs 500 000 sum", "call Rustam", "#1", "version 1.2.3"):
            self.assertEqual(self.private.protect(text), text)

    def test_unknown_placeholder_is_refused(self):
        with self.assertRaisesRegex(LookupError, "#9"):
            self.private.resolve("#9")

    def test_placeholder_stays_after_a_restart(self):
        label = self.private.protect("+998901234567")
        again = PrivateNumbers(os.path.dirname(self.private.book_path))
        self.assertEqual(again.resolve(label)[0], "+998901234567")

    def test_damaged_files_count_as_empty(self):
        with open(self.private.placeholders_path, "w", encoding="utf-8") as f:
            f.write("{not json")
        self.assertEqual(self.private.protect("+998901234567"), "#1")


class Results(unittest.TestCase):
    def setUp(self):
        self.private = PrivateNumbers(tempfile.mkdtemp())
        self.label = self.private.label_for(NUMBER)

    def test_number_is_gone_in_every_form_and_every_field(self):
        result = {"number": NUMBER, "reason": f"called 998900000001 and {NUMBER}", "list": ["+998900000001"], "deep": {"x": DIGITS},
                  "transcript_file": rf"C:\calls\20261103-120000-{DIGITS}.txt", "seconds": 72, "nothing": None}
        hidden = self.private.hide(result)
        self.assertNotIn(DIGITS, json.dumps(hidden))
        self.assertNotIn("900 00 01", json.dumps(hidden, ensure_ascii=False))
        self.assertNotIn("000 00 01", json.dumps(hidden, ensure_ascii=False))
        self.assertEqual(hidden["number"], self.label)
        self.assertEqual(hidden["seconds"], 72)
        self.assertIsNone(hidden["nothing"])

    def test_other_numbers_said_on_the_call_stay(self):
        self.assertEqual(self.private.hide("Their office is +998 71 123 45 67"), "Their office is +998 71 123 45 67")

    def test_contacts_are_hidden_too(self):
        self.private.add_contact("Рустам", "+998 90 000 00 02")
        self.assertEqual(self.private.hide("Dialing +998900000002"), "Dialing Рустам")


from test_support import setup_profile as setUpModule, teardown_profile as tearDownModule

if __name__ == "__main__":
    unittest.main()
