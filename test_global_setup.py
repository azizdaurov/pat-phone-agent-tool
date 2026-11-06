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
        (self.folder / "025550100.md").write_text("calls: 1\nlast_call: old\n\n## Pinned (yours; Pat never changes this)\nKeep this.\n\n## Summary (rewritten after each call)\nWHO: private\n", encoding="utf-8")

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

    def test_a_copy_started_as_administrator_stops_a_second_one_and_says_why(self):
        """Windows answers "access denied", not "already exists", when that copy owns the marker: two notes would both hold the phone."""
        import note_window
        import pat
        windows = mock.Mock()
        windows.CreateMutexW.return_value = None
        with mock.patch.object(note_window.ctypes, "WinDLL", return_value=windows), mock.patch.object(note_window.ctypes, "get_last_error", return_value=5), \
                mock.patch.object(note_window, "tell_about_admin_copy") as told, mock.patch.object(note_window, "_copy_mutex", None):
            self.assertFalse(note_window.claim_single_copy())
            told.assert_called_once()
            with self.assertRaises(SystemExit) as error:
                pat.only_one_copy()
        self.assertIn("administrator", str(error.exception))

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
        import pat
        with mock.patch.object(pat.sys, "argv", ["pat.py", "answer"]), mock.patch.object(pat, "only_one_copy", side_effect=AssertionError("must not touch audio")):
            with self.assertRaises(SystemExit) as error:
                pat.main()
        self.assertIn("Terms of Use", str(error.exception))

    def test_saved_phone_id_is_used_by_the_note_and_call_command(self):
        import pat
        self.ready(phone_device="paired-phone-id")
        self.assertEqual(pat.phone_command(True), ["iphonecall", "--device-id", "paired-phone-id", "--stay-on-phone"])

    def test_the_cli_uses_the_saved_owner_and_explicit_call_timezone(self):
        import pat
        from call_brief import CallBrief
        self.ready()
        captured = []
        brief = CallBrief.from_dict({"goal": "Take a message", "time_zone": "UTC"})
        def load(args):
            captured.append(args)
            return brief
        class BeforeHardware(Exception):
            pass
        with mock.patch.object(pat.sys, "argv", ["pat.py", "answer", "--time-zone", "Asia/Tokyo", "--date-format", "mdy"]), mock.patch.object(pat, "load_brief", side_effect=load), mock.patch.object(pat, "only_one_copy", side_effect=BeforeHardware):
            with self.assertRaises(BeforeHardware):
                pat.main()
        self.assertEqual((captured[0].owner, captured[0].owner_ru), ("Maya", "Maya"))
        self.assertEqual((brief.time_zone, brief.date_format), ("Asia/Tokyo", "mdy"))
        self.assertIn("Time zone: Asia/Tokyo", brief.date_table())

    def test_each_call_uses_the_name_written_for_its_language(self):
        import pat
        from call_brief import CallBrief
        self.ready()
        self.profile.save(name_language="en", names={"ru": "Майя"})
        self.assertEqual(UserProfile().names, {"en": "Maya", "ru": "Майя"})
        captured = []
        class BeforeHardware(Exception):
            pass
        for argv, language, expected in ((["pat.py", "answer"], "en", ("Maya", "Майя")), (["pat.py", "answer"], "ru", ("Майя", "Майя")),
                                         (["pat.py", "answer", "--owner", "Sam"], "ru", ("Sam", "Sam"))):
            load = lambda args, language=language: (captured.append(args), CallBrief.from_dict({"goal": "Take a message", "language": language}))[1]
            with mock.patch.object(pat.sys, "argv", argv), mock.patch.object(pat, "load_brief", side_effect=load), mock.patch.object(pat, "only_one_copy", side_effect=BeforeHardware):
                with self.assertRaises(BeforeHardware):
                    pat.main()
            self.assertEqual((captured[-1].owner, captured[-1].owner_ru), expected)
        self.assertIn("Майя", pat.OPENINGS["answer"]["ru"].format(owner="Maya", owner_ru=captured[0].owner_ru))

    def test_names_per_language_are_checked_and_old_profiles_still_work(self):
        with self.assertRaises(ValueError):
            self.profile.save(name="Maya", names={"ru": "М" * 101})
        with self.assertRaises(ValueError):
            self.profile.save(name="Maya", names={"xx": "Maya"})  # not a language Pat calls in
        self.profile.save(name="Майя")
        self.assertEqual(UserProfile().name_language, "ru")  # saved before languages were: guessed from its letters
        self.assertEqual(UserProfile().name_in("en"), "Майя")  # nothing written for English yet
        values = dict(UserProfile().values, name="Maya", name_ru="Майя")
        values.pop("name_language", None)
        values.pop("names", None)
        with open(self.profile.path, "w", encoding="utf-8") as f:
            json.dump(values, f, ensure_ascii=False)
        self.assertEqual(UserProfile().names, {"en": "Maya", "ru": "Майя"})  # the test build's Russian field carries over

    def test_bug_reports_hide_every_spelling_of_the_owners_name(self):
        import report
        self.profile.save(name="Maya Stone", name_language="en", names={"ru": "Майя Стоун"})
        for word in ("Maya Stone", "Майя Стоун", "Майя", "Стоун"):
            self.assertIn(word, report.private_names())


class OwnerNameLanguages(ProfileCase):
    def test_the_ai_reply_is_checked_before_it_is_used(self):
        from owner_names import checked, localize
        self.assertEqual(checked('{"ru": "Азиз"}', ["ru"]), {"ru": "Азиз"})
        self.assertEqual(checked('Sure! {"ru": "Aziz"}', ["ru"]), {})  # not in Russian letters
        self.assertEqual(checked('{"ru": "Азиз\\"}<b>"}', ["ru"]), {})
        self.assertEqual(checked("I can't help with that.", ["ru"]), {})
        self.assertEqual(checked('{"ru": "' + "А" * 101 + '"}', ["ru"]), {})
        asked = []
        names = localize("Aziz", "en", lambda text: (asked.append(text), '{"ru": "Азиз", "en": "Ignored"}')[1])
        self.assertEqual(names, {"ru": "Азиз"})  # never rewrites the language it was typed in
        self.assertIn("<name>Aziz</name>", asked[0])

    def test_the_table_fills_rows_with_ai_but_never_overwrites_one_typed_by_hand(self):
        import time
        from PySide6.QtWidgets import QApplication
        import onboarding
        app = QApplication.instance() or QApplication([])
        self.profile.save(name="Maya", name_language="en")
        replies = iter(['{"ru": "Майя"}', '{"ru": "Майя Стоун"}'])
        table = onboarding.NameTable(UserProfile(), ask=lambda text: next(replies))

        def settle():
            deadline = time.time() + 5
            while "Writing" in table.status.text() and time.time() < deadline:
                app.processEvents()
                time.sleep(0.01)
        self.assertEqual([table.current, table.edit.text(), table.language.count()], ["en", "Maya", 2])  # one row, a dropdown
        table.fill()
        settle()
        self.assertEqual(table.edit.text(), "Maya")  # still showing the owner's own language
        self.assertIn("Русский", table.status.text())
        table.language.setCurrentIndex(table.language.findData("ru"))
        self.assertEqual(table.edit.text(), "Майя")
        table.edit.setText("Мая")
        table.edit.textEdited.emit("Мая")  # the owner corrects it
        table.language.setCurrentIndex(table.language.findData("en"))
        table.edit.setText("Maya Stone")
        table.fill()
        settle()
        self.assertEqual(table.values(), ("Maya Stone", "en", {"ru": "Мая"}))
        failing = onboarding.NameTable(UserProfile(), ask=lambda text: 1 / 0)
        failing.edit.setText("Sam")
        failing.names.pop("ru", None)
        failing.fill()
        deadline = time.time() + 5
        while "Writing" in failing.status.text() and time.time() < deadline:
            app.processEvents()
            time.sleep(0.01)
        self.assertIn("Couldn't fill them in", failing.status.text())
        table.deleteLater()
        failing.deleteLater()
        app.processEvents()


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


class OwnerPronouns(ProfileCase):
    def test_haiku_and_sonnet_are_told_how_to_speak_about_the_owner(self):
        from call_brief import CallBrief
        brief = CallBrief.from_dict({"goal": "Check hours"})
        target = CallBrief.from_dict({"goal": "Check hours", "name": "Alex", "confidence": "confirmed"})
        for pronouns, english, russian in (("he", "say he and him", "masculine"), ("she", "say she and her", "feminine"),
                                           ("they", "use the name Maya or they", "avoid word forms that show gender")):
            self.profile.save(name="Maya", pronouns=pronouns)
            for prompt in (brief.haiku_prompt("", "Hello.", "Maya", "n"), target.haiku_prompt("", "Hello.", "Maya", "n"),
                           brief.observer_prompt("Maya")):
                self.assertIn(english, prompt)
                self.assertIn(russian, prompt)

    def test_old_profiles_and_bad_values(self):
        self.profile.save(name="Maya")
        self.assertEqual(UserProfile().pronouns, "they")
        with self.assertRaises(ValueError):
            self.profile.save(name="Maya", pronouns="it")


class FirstRunScreen(ProfileCase):
    def test_enter_moves_to_terms_instead_of_closing_the_window(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QApplication
        from onboarding import OnboardingDialog
        app = QApplication.instance() or QApplication([])
        dialog = OnboardingDialog(self.profile)
        dialog.name.setText("Maya")
        dialog.show()
        dialog.name.setFocus()
        app.processEvents()
        QTest.keyClick(dialog.name, Qt.Key_Return)
        self.assertEqual(dialog.pages.currentIndex(), 1)
        self.assertFalse(UserProfile().ready)
        dialog.reject()
        dialog.deleteLater()
        app.processEvents()

    def test_back_keeps_the_name_but_does_not_accept_the_terms(self):
        from PySide6.QtWidgets import QApplication
        from onboarding import OnboardingDialog
        app = QApplication.instance() or QApplication([])
        dialog = OnboardingDialog(self.profile)
        dialog.name.setText("Maya")
        dialog.advance()
        dialog.go_back()
        self.assertEqual(dialog.pages.currentIndex(), 0)
        self.assertEqual(dialog.name.text(), "Maya")
        dialog.advance()
        self.assertFalse(dialog.next.isEnabled())
        dialog.reject()
        self.assertFalse(UserProfile().ready)
        dialog.deleteLater()
        app.processEvents()

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

    def test_pronouns_are_asked_with_the_name_and_saved(self):
        from PySide6.QtWidgets import QApplication
        from onboarding import OnboardingDialog
        app = QApplication.instance() or QApplication([])
        dialog = OnboardingDialog(self.profile)
        self.assertEqual(dialog.pronouns.currentData(), "they")  # nobody is assumed to be he or she
        dialog.name.setText("Maya")
        dialog.pronouns.setCurrentIndex(dialog.pronouns.findData("she"))
        dialog.advance()
        dialog.agree.setChecked(True)
        dialog.advance()
        self.assertEqual(UserProfile().pronouns, "she")
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


class ProfileScreen(ProfileCase):
    def test_sections_resize_the_window_and_changes_are_saved(self):
        from PySide6.QtWidgets import QApplication
        from onboarding import ProfileDialog
        app = QApplication.instance() or QApplication([])
        self.ready(country="UZ")
        with mock.patch("onboarding.UserProfile", return_value=self.profile):
            dialog = ProfileDialog()
        dialog.show()
        app.processEvents()
        dialog.fit_contents()
        sections = (dialog.name_section, dialog.region_section, dialog.phone_section)
        self.assertEqual([s.opened for s in sections], [True, False, False])
        dialog.region_section.set_open(True)  # one open at a time, so the window fits a laptop screen
        self.assertEqual([s.opened for s in sections], [False, True, False])
        dialog.region_section.set_open(False)
        app.processEvents()
        dialog.fit_contents()
        small = dialog.height()
        dialog.phone_section.set_open(True)
        app.processEvents()
        dialog.fit_contents()
        self.assertGreater(dialog.height(), small)
        self.assertEqual([s.opened for s in sections], [False, False, True])
        dialog.name.setText("Maya Stone")
        dialog.pronouns.setCurrentIndex(dialog.pronouns.findData("she"))
        dialog.country.setCurrentIndex(dialog.country.findData("GB"))
        dialog.zone.setCurrentText("Europe/London")
        dialog.dates.setCurrentIndex(dialog.dates.findData("dmy"))
        dialog.phone.addItem("My phone", "test-phone-id")
        dialog.phone.setCurrentIndex(1)
        dialog.save()
        saved = UserProfile()
        self.assertEqual((saved.name, saved.pronouns, saved.country, saved.time_zone, saved.date_format, saved.phone_device),
                         ("Maya Stone", "she", "GB", "Europe/London", "dmy", "test-phone-id"))
        dialog.deleteLater()
        app.processEvents()
