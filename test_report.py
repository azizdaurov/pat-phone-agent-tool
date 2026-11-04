"""The bug report, made from pretend logs, so no real call is read.
Run: .venv\\Scripts\\python.exe -m unittest test_report -v"""
import os
import tempfile
import unittest
from unittest import mock

import report
from report import Redactor, without_conversation


class Numbers(unittest.TestCase):
    def setUp(self):
        self.redact = Redactor(["Рустам", "Aziz"], home=r"C:\Users\Aziz")

    def test_phone_numbers_in_every_form_are_hidden_and_the_same_one_keeps_its_stand_in(self):
        text = self.redact.clean("-- Incoming +998 90 123 45 67 (+998901234567): Talking; dial 212-867-5309: Succeeded")
        self.assertEqual(text, "-- Incoming <number 1> (<number 1>): Talking; dial <number 2>: Succeeded")

    def test_times_dates_counts_and_measurements_stay(self):
        for line in ("21:59:38.783689 call>", "last 2026-11-04T21:44+05:00", "mic input frames=1829440, peak=0.1840",
                     "first audio 4.45 s after their speech ended", "Notes updated: 303 old + 526 transcript -> 479 characters."):
            self.assertEqual(self.redact.clean(line), line)

    def test_a_call_file_keeps_its_date_and_time_but_not_the_number(self):
        self.assertEqual(self.redact.clean(r"Transcript: C:\Users\Aziz\calls\20261104-215947-998907432299.txt"),
                         r"Transcript: %USERPROFILE%\calls\20261104-215947-<number 1>.txt")
        self.assertEqual(self.redact.clean("Call 20261104-205048-7b60f7.log"), "Call 20261104-205048-7b60f7.log")

    def test_names_are_hidden_whatever_their_case_but_not_inside_other_words(self):
        self.assertEqual(self.redact.clean("phone : iPhone AZIZ; Incoming Рустам"), "phone : iPhone <name 2>; Incoming <name 1>")
        self.assertEqual(self.redact.clean("Azizbek"), "Azizbek")

    def test_versions_can_be_kept(self):
        self.assertEqual(self.redact.clean("Windows: Windows-10-10.0.26200-SP0", numbers=False), "Windows: Windows-10-10.0.26200-SP0")


class Conversation(unittest.TestCase):
    LOG = ["Dialing +998901234567. Claude's task: Find out if a table for 4 is free",
           "Pat: task: goal: Find out if a table for 4 is free",
           "need_from_them: ['Is a table free?']",
           "context: The owner asked to book.",
           "  and a second line of context",
           "language: en",
           "name: Alex",
           "time_zone: Asia/Tashkent",
           "Pat: hearing through: Voicemeeter Input [Loopback]; call audio: LocalDevice",
           "Claude: Hello, this is Aziz's AI assistant.",
           "Pat: speech started, 7.8 s into the call",
           "Them: Yes, we have amazing grilled chicken.",
           "Cicero: Haiku asks Sonnet: may I agree to 9pm?",
           "Cicero: Sonnet answers: yes",
           "Pat: Sonnet correct (off topic): Ask about the table again",
           "Pat: not spoken: some words",
           "Pat: call over: goodbye, loudest sound heard 0.720 of 1",
           "Traceback (most recent call last):"]

    def test_what_was_said_and_the_brief_are_left_out_and_the_rest_stays(self):
        out = without_conversation(self.LOG)
        self.assertEqual(out, [
            "Dialing +998901234567. <task left out>",
            "Pat: task: <left out>",
            "language: en",
            "time_zone: Asia/Tashkent",
            "Pat: hearing through: Voicemeeter Input [Loopback]; call audio: LocalDevice",
            "Claude: <said 7 words>",
            "Pat: speech started, 7.8 s into the call",
            "Them: <said 6 words>",
            "Cicero: Haiku asks Sonnet: <left out>",
            "Cicero: Sonnet answers: <left out>",
            "Pat: Sonnet correct: <left out>",
            "Pat: not spoken: <left out>",
            "Pat: call over: goodbye, loudest sound heard 0.720 of 1",
            "Traceback (most recent call last):"])
        joined = "\n".join(out)
        for private in ("table", "chicken", "Alex", "book", "9pm", "Aziz"):
            self.assertNotIn(private, joined)


class WholeReport(unittest.TestCase):
    def test_a_report_from_pretend_logs_has_no_number_name_or_words(self):
        folder = tempfile.mkdtemp()
        with open(os.path.join(folder, "20261104-215931-54ae54.log"), "w", encoding="utf-8") as f:
            f.write("\n".join(Conversation.LOG))
        with open(os.path.join(folder, "20261104-215931-54ae54.result.json"), "w", encoding="utf-8") as f:
            f.write('{"status": "done", "reason": "goodbye", "seconds": 54, "summary": "Table booked for Alex"}')
        with open(os.path.join(folder, "phone-20261104-215938.log"), "w", encoding="utf-8") as f:
            f.write("21:59:38.783689 phone    : iPhone Aziz\n21:59:39.386270 -- Outgoing Рустам (+998901234567): Dialing\n")
        with mock.patch.object(report, "CALLS", folder), mock.patch.object(report, "environment", return_value=["Python: 3.13"]):
            text = report.build(3, Redactor(["Рустам", "Aziz"]))
        self.assertIn("Result: {\"status\": \"done\", \"reason\": \"goodbye\", \"seconds\": 54}", text)
        self.assertIn("21:59:38.783689 phone    : iPhone <name 2>", text)
        for private in ("998901234567", "+998", "Рустам", "Aziz", "Alex", "chicken", "Table booked"):
            self.assertNotIn(private, text)


if __name__ == "__main__":
    unittest.main()
