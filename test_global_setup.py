"""Regression cases for global phone identities, dates, setup consent and owner preferences."""
import datetime
import json
import os
import pathlib
import tempfile
import types
import unittest
from unittest import mock

from phone_numbers import international_number
from phone_memory import ContactNotes, number_key
from private_numbers import PrivateNumbers
from user_profile import TERMS_TEXT, TERMS_VERSION, UserProfile
import real_dates


class ProfileCase(unittest.TestCase):
    def setUp(self):
        self.folder = pathlib.Path(tempfile.mkdtemp())
        self.environment = mock.patch.dict(os.environ, {"PAT_PROFILE_PATH": str(self.folder / "profile.json")})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.original_dates = real_dates._time_zone, real_dates._date_format
        real_dates._time_zone = real_dates._date_format = None
        self.addCleanup(self.restore_dates)
        self.profile = UserProfile()

    def restore_dates(self):
        real_dates._time_zone, real_dates._date_format = self.original_dates

    def ready(self, **values):
        self.profile.save(name="Maya", time_zone="UTC", date_format="iso", **values)
        self.profile.accept_terms()


class GlobalNumbers(ProfileCase):
    def test_full_us_numbers_never_share_the_old_nine_digit_identity(self):
        private = PrivateNumbers(str(self.folder))
        private.add_contact("First", "+12025550100")
        self.assertNotEqual(number_key("+12025550100"), number_key("+13025550100"))
        self.assertEqual(private.name_for("+13025550100"), "")

    def test_area_code_parentheses_are_not_the_whole_number(self):
        self.assertEqual(number_key("Alex (+1 (415) 555-0101)"), "14155550101")
        self.assertNotEqual(number_key("+1 (415) 555-0101"), number_key("+1 (415) 555-0102"))

    def test_formats_and_unicode_digits_have_one_dialable_form(self):
        for value in ("+1 (415) 555-0101", "+1-415-555-0101", "+١٤١٥٥٥٥٠١٠١"):
            self.assertEqual(international_number(value), "+14155550101")

    def test_short_international_number_is_saved_hidden_and_dialable(self):
        private = PrivateNumbers(str(self.folder))
        private.add_contact("Short", "+29022023")
        self.assertEqual(private.resolve("Short")[0], "+29022023")
        protected = private.protect("Call:+29022023")
        self.assertEqual(protected, "Call:Short")

    def test_short_number_is_passed_to_the_call_process(self):
        import phone_mcp
        from easter_eggs import EasterEggs
        self.ready()
        with mock.patch.multiple(phone_mcp, CALLS=str(self.folder), private=PrivateNumbers(str(self.folder)),
                                 eggs=EasterEggs(str(self.folder), str(self.folder)), running={}):
            with mock.patch.object(phone_mcp.subprocess, "Popen") as launch:
                result = phone_mcp.start_call("+29022023", {"goal": "Ask when they open", "name": "Alex", "confidence": "guess"}, 5)
            self.assertEqual(result["status"], "running")
            self.assertIn("+29022023", launch.call_args.args[0])

    def test_colon_does_not_bypass_unknown_number_privacy(self):
        private = PrivateNumbers(str(self.folder))
        for text in ("Call:14155550101", "Phone:+29022023"):
            self.assertNotIn("5550101", private.protect(text))
            self.assertNotIn("29022023", private.protect(text))

    def test_local_number_requires_a_selected_country(self):
        self.assertEqual(international_number("020 7946 0000", country="GB"), "+442079460000")
        with self.assertRaises(ValueError):
            international_number("020 7946 0000", country="")

    def test_bare_number_is_private_but_never_given_a_guessed_country(self):
        private = PrivateNumbers(str(self.folder))
        protected = private.protect("2025550100")
        self.assertRegex(protected, r"^#\d+$")
        with self.assertRaises(LookupError):
            private.resolve(protected)
        self.profile.save(name="Maya", country="US", time_zone="UTC")
        self.assertEqual(private.resolve(protected)[0], "+12025550100")

    def legacy_book(self, values):
        (self.folder / "book.json").write_text(json.dumps(values), encoding="utf-8")
        (self.folder / "025550100.md").write_text("calls: 1\nlast_call: old\n\n## Pinned (yours; Cicero never changes this)\nKeep this.\n\n## Summary (rewritten after each call)\nWHO: private\n", encoding="utf-8")

    def test_unique_old_notes_are_copied_without_deleting_original(self):
        self.legacy_book({"First": "+12025550100"})
        notes = ContactNotes("12025550100", str(self.folder))
        self.assertEqual(notes.pinned, "Keep this.")
        notes.save()
        self.assertTrue((self.folder / "025550100.md").exists())
        self.assertTrue((self.folder / "12025550100.md").exists())

    def test_ambiguous_old_notes_and_answer_rules_are_not_given_to_either_person(self):
        from note import CallRules
        self.legacy_book({"First": "+12025550100", "Second": "+13025550100"})
        rules_path = self.folder / "rules.json"
        rules_path.write_text('{"025550100":"ai"}', encoding="utf-8")
        rules = CallRules(str(rules_path))
        for key in ("12025550100", "13025550100"):
            self.assertEqual(ContactNotes(key, str(self.folder)).summary, "")
            self.assertIsNone(rules.rule("+" + key))

    def test_setting_ask_clears_a_uniquely_migrated_always_ai_rule(self):
        from note import CallRules
        self.legacy_book({"First": "+12025550100"})
        rules_path = self.folder / "rules.json"
        rules_path.write_text('{"025550100":"ai"}', encoding="utf-8")
        rules = CallRules(str(rules_path))
        self.assertEqual(rules.rule("+12025550100"), "ai")
        rules.set("+12025550100", "ask")
        self.assertIsNone(CallRules(str(rules_path)).rule("+12025550100"))


class SetupGate(ProfileCase):
    def test_cancelled_first_run_does_not_start_the_phone_watcher(self):
        import note
        with mock.patch.object(note.sys, "argv", ["note.py"]), mock.patch("note_window.claim_single_copy", return_value=True), mock.patch("onboarding.ensure_onboarding", return_value=False):
            with mock.patch.object(note.threading, "Thread", side_effect=AssertionError("watcher must not start")):
                note.main()

    def test_name_and_current_terms_are_both_required(self):
        self.assertFalse(self.profile.ready)
        self.profile.save(name="Maya", time_zone="UTC")
        self.assertFalse(UserProfile().ready)
        self.profile.accept_terms()
        self.assertTrue(UserProfile().ready)
        self.profile.save(accepted_terms="older terms")
        self.assertFalse(UserProfile().ready)

    def test_unaccepted_terms_block_the_phone_tool_before_starting_a_process(self):
        import phone_mcp
        with mock.patch.object(phone_mcp.subprocess, "Popen", side_effect=AssertionError("must not start")):
            self.assertEqual(phone_mcp.start_call("+29022023", {}, 5)["status"], "setup_required")
        self.assertEqual(phone_mcp.list_contacts()["status"], "setup_required")

    def test_unaccepted_terms_block_cli_before_touching_audio_or_phone(self):
        import cicero
        with mock.patch.object(cicero.sys, "argv", ["cicero.py", "answer"]), mock.patch.object(cicero, "only_one_copy", side_effect=AssertionError("must not touch audio")):
            with self.assertRaises(SystemExit) as error:
                cicero.main()
        self.assertIn("Terms of Use", str(error.exception))

    def test_saved_phone_id_is_used_by_the_note_and_call_command(self):
        import cicero
        self.ready(phone_device="paired-phone-id")
        self.assertEqual(cicero.phone_command(True), ["iphonecall", "--device-id", "paired-phone-id", "--stay-on-phone"])

    def test_the_cli_uses_the_saved_owner_and_explicit_call_timezone(self):
        import cicero
        from call_brief import CallBrief
        self.ready()
        captured = []
        brief = CallBrief.from_dict({"goal": "Take a message", "time_zone": "UTC"})
        def load(args):
            captured.append(args)
            return brief
        class BeforeHardware(Exception):
            pass
        with mock.patch.object(cicero.sys, "argv", ["cicero.py", "answer", "--time-zone", "Asia/Tokyo", "--date-format", "mdy"]), mock.patch.object(cicero, "load_brief", side_effect=load), mock.patch.object(cicero, "only_one_copy", side_effect=BeforeHardware):
            with self.assertRaises(BeforeHardware):
                cicero.main()
        self.assertEqual((captured[0].owner, captured[0].owner_ru), ("Maya", "Maya"))
        self.assertEqual((brief.time_zone, brief.date_format), ("Asia/Tokyo", "mdy"))
        self.assertIn("Time zone: Asia/Tokyo", brief.date_table())


class GlobalDates(ProfileCase):
    def test_same_instant_has_the_correct_local_day(self):
        instant = datetime.datetime(2026, 11, 4, 1, tzinfo=datetime.timezone.utc)
        new_york = real_dates.date_lines(time_zone="America/New_York", date_format="iso", now=instant)
        tokyo = real_dates.date_lines(time_zone="Asia/Tokyo", date_format="iso", now=instant)
        self.assertIn("Tuesday, 2026-11-03", new_york)
        self.assertIn("Wednesday, 2026-11-04", tokyo)
        self.assertIn("Tomorrow is 2026-11-04", new_york)

    def test_dst_uses_the_offset_for_that_instant(self):
        before = datetime.datetime(2026, 3, 8, 6, 59, tzinfo=datetime.timezone.utc)
        after = before + datetime.timedelta(minutes=1)
        self.assertIn("01:59 -0500", real_dates.date_lines(time_zone="America/New_York", now=before))
        self.assertIn("03:00 -0400", real_dates.date_lines(time_zone="America/New_York", now=after))

    def test_reports_use_the_selected_format_and_never_rewrite_bad_dates(self):
        day = datetime.date(2026, 11, 3)
        for form, expected in (("iso", "2026-11-04"), ("dmy", "4-11-2026"), ("mdy", "11/04/2026")):
            real_dates.configure("UTC", form)
            self.assertEqual(real_dates.real_dates("tomorrow", day), expected)
            self.assertEqual(real_dates.real_dates("2026-11-04", day), expected)
        self.assertEqual(real_dates.real_dates("2026-99-99", day), "2026-99-99")

    def test_call_timezone_can_override_owner_timezone(self):
        from call_brief import CallBrief
        self.ready()
        brief = CallBrief.from_dict({"goal": "Check hours", "time_zone": "Asia/Tokyo", "date_format": "mdy"})
        self.assertIn("Time zone: Asia/Tokyo", brief.date_table())
        self.assertIn("Date format: MM/DD/YYYY", brief.date_table())
        with self.assertRaises(ValueError):
            CallBrief.from_dict({"goal": "Check hours", "time_zone": "not/a-zone"})


class FirstRunScreen(ProfileCase):
    def test_name_is_first_and_acceptance_is_disabled_until_checked(self):
        from PySide6.QtWidgets import QApplication, QDialog
        from onboarding import OnboardingDialog
        app = QApplication.instance() or QApplication([])
        dialog = OnboardingDialog(self.profile)
        self.assertEqual(dialog.pages.currentIndex(), 0)
        self.assertFalse(dialog.next.isEnabled())
        dialog.name.setText("Maya")
        dialog.advance()
        self.assertEqual(dialog.pages.currentIndex(), 1)
        title = next(line.strip().lstrip("#").strip() for line in TERMS_TEXT.splitlines() if line.strip())
        self.assertIn(title, dialog.terms.toPlainText())
        self.assertNotIn("##", dialog.terms.toPlainText())
        self.assertFalse(dialog.agree.isChecked())
        self.assertFalse(dialog.next.isEnabled())
        dialog.accept()
        self.assertFalse(UserProfile().ready)
        dialog.agree.setChecked(True)
        self.assertTrue(dialog.next.isEnabled())
        dialog.advance()
        self.assertEqual(dialog.result(), QDialog.Accepted)
        self.assertEqual(UserProfile().name, "Maya")
        self.assertEqual(UserProfile().values["accepted_terms"], TERMS_VERSION)
        dialog.deleteLater()
        app.processEvents()

    def test_cancel_does_not_grant_access(self):
        from PySide6.QtWidgets import QApplication
        from onboarding import OnboardingDialog
        app = QApplication.instance() or QApplication([])
        dialog = OnboardingDialog(self.profile)
        dialog.name.setText("Maya")
        dialog.advance()
        dialog.reject()
        self.assertFalse(UserProfile().ready)
        dialog.deleteLater()
        app.processEvents()
