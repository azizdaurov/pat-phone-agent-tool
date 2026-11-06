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
        self.assertEqual(self.redact.clean(r"Transcript: C:\Users\Aziz\calls\20261104-215947-12025550143.txt"),  # 555-01xx: reserved for fiction
                         r"Transcript: %USERPROFILE%\calls\20261104-215947-<number 1>.txt")
        self.assertEqual(self.redact.clean("Call 20261104-205048-7b60f7.log"), "Call 20261104-205048-7b60f7.log")

    def test_names_are_hidden_whatever_their_case_but_not_inside_other_words(self):
        self.assertEqual(self.redact.clean("phone : iPhone AZIZ; Incoming Рустам"), "phone : iPhone <name 2>; Incoming <name 1>")
        self.assertEqual(self.redact.clean("Azizbek"), "Azizbek")

    def test_a_name_the_phone_shows_for_a_caller_is_hidden_even_if_pat_never_saved_it(self):
        redact = Redactor(["Aziz"])
        lines = ["21:59:39.386270 -- Incoming Dr Zelinsky Clinic (+14155550101): Incoming, audio=RemoteDevice, muted=False",
                 "call     : Incoming Dr Zelinsky Clinic (+14155550101): Talking, audio=LocalDevice, muted=False",
                 "Incoming: Dr Zelinsky Clinic (+14155550101)",
                 "21:59:40.1 -- Outgoing Мама: Dialing, audio=RemoteDevice, muted=False"]
        self.assertEqual([redact.clean(line) for line in lines], [
            "21:59:39.386270 -- Incoming <caller 1> (<number 1>): Incoming, audio=RemoteDevice, muted=False",
            "call     : Incoming <caller 1> (<number 1>): Talking, audio=LocalDevice, muted=False",
            "Incoming: <caller 1> (<number 1>)",
            "21:59:40.1 -- Outgoing <caller 2>: Dialing, audio=RemoteDevice, muted=False"])

    def test_a_saved_contact_calling_keeps_its_name_stand_in_and_other_lines_stay(self):
        self.assertEqual(self.redact.clean("-- Incoming Рустам (+998901234567): Talking, audio=LocalDevice, muted=False"),
                         "-- Incoming <name 1> (<number 1>): Talking, audio=LocalDevice, muted=False")
        for line in ("-- call ended (0 active)", "-- audio -> laptop, try 1: Succeeded", "Incoming: <number 1>",
                     "-- Incoming +998901234567: Incoming, audio=RemoteDevice, muted=False"):
            cleaned = self.redact.clean(line)
            self.assertNotIn("<caller", cleaned, line)

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
        logs = tempfile.mkdtemp()
        with open(os.path.join(logs, "setup-20261105-170000.txt"), "w", encoding="utf-8") as f:
            f.write("Username: LAPTOP7\\Aziz\n== Phone\n   Phone ready: iPhone Aziz\n")
        with open(os.path.join(folder, "pair-20261106-222017.log"), "w", encoding="utf-8") as f:
            f.write('{"event":"log","text":"(also written to C:\\\\Users\\\\Aziz\\\\calls\\\\pair.log)"}\n'
                    '{"event":"found","text":"  1. iPhone Aziz","number":1,"name":"iPhone Aziz"}\n'
                    'access   : Allowed\n'
                    '{"event":"done","text":"Done: Pat can take calls on iPhone Aziz.","name":"iPhone Aziz",'
                    '"id":"\\\\?\\\\BTHENUM#{0000111e}_LOCALMFG&0002#7&1A&0&30D7A1A4FC0B_C00000000"}\n')
        settings = ["Developer Mode: on", "Paired phones:", "  iPhone Aziz   yes   yes"]
        pairings = ["2026-11-06 17:50:04  pairing removed: device 1 (not paired now)", "2026-11-06 19:39:51  paired: iPhone Aziz"]
        with mock.patch.object(report, "CALLS", folder), mock.patch.object(report, "SETUP_LOGS", logs), \
                mock.patch.object(report, "environment", return_value=["Python: 3.13"]), mock.patch.object(report, "laptop_state", return_value=settings), \
                mock.patch.object(report, "bluetooth_events", return_value=pairings):
            text = report.build(3, Redactor(["Рустам", "Aziz", "LAPTOP7"]))
        self.assertIn("Result: {\"status\": \"done\", \"reason\": \"goodbye\", \"seconds\": 54}", text)
        self.assertRegex(text, r"21:59:38\.783689 phone    : iPhone <name \d>")
        self.assertIn("Developer Mode: on", text)
        self.assertIn("===== Setup log setup-20261105-170000.txt", text)
        self.assertIn("2026-11-06 17:50:04  pairing removed: device 1 (not paired now)", text)  # dates and times kept whole
        self.assertIn("found: 1. iPhone <name", text)
        self.assertIn("access   : Allowed", text)
        self.assertNotIn("30D7A1A4FC0B", text.upper())
        for private in ("998901234567", "+998", "Рустам", "Aziz", "Alex", "chicken", "Table booked", "LAPTOP7"):
            self.assertNotIn(private, text)


class LaptopSettings(unittest.TestCase):
    """The read-only checks, with pretend answers: no registry, helper or Claude is asked."""

    def run_with(self, answers, registry=lambda hive, path, name: 1):
        def run(command, **_):
            key = next((k for k in answers if k in " ".join(map(str, command))), None)
            if key is None or isinstance(answers[key], Exception):
                raise answers.get(key, OSError("not found"))
            return mock.Mock(stdout=answers[key])
        with mock.patch.object(report, "_claude_path", return_value="claude"):
            return report.laptop_state(run=run, headsets=lambda: ["Headphones (Wireless Buds Hands-Free)"], registry=registry)

    def test_each_setting_is_reported_and_the_claude_email_never_is(self):
        lines = self.run_with({"Get-AppxPackage": "1.0.0.0", "tasklist": "PhoneExperienceHost.exe  4242 Console",
                               "phones": "phone   connected\niPhone   yes", "auth": '{"loggedIn": true, "email": "someone@example.com"}'})
        text = "\n".join(lines)
        for expected in ("Developer Mode: on", "Allow this PC to access your mobile devices: on", "Phone helper: installed, version 1.0.0.0",
                         "Phone Link running: yes", "Wireless Buds", "  iPhone   yes", "Claude Code: logged in"):
            self.assertIn(expected, text)
        self.assertNotIn("someone@example.com", text)

    def test_a_check_that_cannot_tell_says_so_instead_of_failing(self):
        lines = self.run_with({"Get-AppxPackage": "", "tasklist": OSError("no tasklist"), "auth": '{"loggedIn": false}'},
                              registry=lambda hive, path, name: None)
        text = "\n".join(lines)
        for expected in ("Developer Mode: unknown", "Phone helper: not installed", "Phone Link running: unknown",
                         "Paired phones: the phone helper didn't answer", "Claude Code: not logged in"):
            self.assertIn(expected, text)

    def test_phone_link_details_are_reported(self):
        def registry(hive, path, name):
            return {"State": 2, "PhoneLinkEnabled": 0}.get(name, 1)
        text = "\n".join(self.run_with({"Get-AppxPackage": "1.26092.119.0", "tasklist": "INFO: No tasks", "auth": "{}"}, registry=registry))
        for expected in ("Phone Link running: no", "Phone Link installed: yes, version 1.26092.119.0",
                         "Phone Link starts at sign-in: on", "Phone Link option on the Mobile devices page: off"):
            self.assertIn(expected, text)
        text = "\n".join(self.run_with({"Get-AppxPackage": "", "auth": "{}"}, registry=lambda hive, path, name: None))
        self.assertIn("Phone Link installed: no", text)
        self.assertIn("Phone Link starts at sign-in: unknown", text)

    def test_bluetooth_events_are_named_and_addresses_never_leave(self):
        answer = ('[{"time":"2026-11-06 17:50:04","id":10,"name":null,"device":"30d7a1a4fc0b"},'
                  '{"time":"2026-11-06 19:26:30","id":16,"name":null,"device":"30d7a1a4fc0b"},'
                  '{"time":"2026-11-06 19:27:20","id":8,"name":"iPhone Aziz","device":"aabbccddeeff"},'
                  '{"time":"2026-11-06 19:30:00","id":10,"name":null,"device":"112233445566"}]')
        lines = report.bluetooth_events(run=lambda command, **_: mock.Mock(stdout=answer))
        self.assertEqual(lines, ["2026-11-06 17:50:04  pairing removed: device 1 (not paired now)",
                                 "2026-11-06 19:26:30  authentication failed (it may hold an old pairing): device 1 (not paired now)",
                                 "2026-11-06 19:27:20  paired: iPhone Aziz",
                                 "2026-11-06 19:30:00  pairing removed: device 2 (not paired now)"])
        single = report.bluetooth_events(run=lambda command, **_: mock.Mock(stdout='{"time":"t","id":8,"name":"Android phone","device":"x"}'))
        self.assertEqual(single, ["t  paired: Android phone"])  # PowerShell writes one event as an object
        self.assertEqual(report.bluetooth_events(run=lambda command, **_: mock.Mock(stdout="")), ["None in the last day."])

        def broken(command, **_):
            raise OSError("no powershell")
        self.assertEqual(report.bluetooth_events(run=broken), ["Couldn't read Windows' Bluetooth events."])

    def test_bluetooth_addresses_are_hidden_in_every_form_and_other_ids_stay(self):
        redact = Redactor()
        for line in ("phone id Bluetooth#Bluetooth38:00:25:aa:bb:cc-30:d7:a1:a4:fc:0b", r"BTHENUM\{0000111e}_LOCALMFG&0002\7&1A&0&30D7A1A4FC0B_C00000000",
                     "The remote adapter (30:d7:a1:a4:fc:0b) successfully paired", "address 30-D7-A1-A4-FC-0B"):
            cleaned = redact.clean(line)
            self.assertNotRegex(cleaned.lower(), r"30[:-]?d7[:-]?a1", line)
            self.assertIn("<bluetooth address>", cleaned)
        for kept in ("Call 20261104-205048-7b60f7.log", "Pat: 913e354"):
            self.assertEqual(redact.clean(kept), kept)
        audio_id = redact.clean("{0.0.0.00000000}.{355a6371-4236-4038-95bf-a1ad32d2649a}")
        self.assertIn("a1ad32d2649a}", audio_id)  # its digit runs are the number rule's business, its end isn't an address
        self.assertNotIn("<bluetooth address>", audio_id)


if __name__ == "__main__":
    unittest.main()
