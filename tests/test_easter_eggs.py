"""The easter eggs: what each one says, what plays once, and above all that no joke number can reach the phone.
Run: .venv\\Scripts\\python.exe -m unittest test_easter_eggs -v"""
import datetime
import json
import os
import sys
import tempfile
import threading
import time
import types
import unittest
from unittest import mock

import pat
import note
import phone_mcp
from call_card import TEXT_WIDTH, display_width, render_card
from easter_eggs import (CALL_FACTS, FACTS, HATCH_KEY, HATCHED_NAME, NO_DIAL_REPLY, OCTO_NUMBER, POEM_PROMPTS, SERIOUS_REPLY, UNHATCHED_NAME, EasterEggs,
                         as_text, choose_next_style, number_joke, split_style, take_next_style, write_poem)
from private_numbers import PrivateNumbers
from tests.test_note import DeskCase


class Eggs(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.private = PrivateNumbers(self.folder)
        self.eggs = EasterEggs(self.folder, self.folder, choose=lambda options: options[-1])

    def say(self, text):
        return self.eggs.respond(text, self.private)

    def words(self, text):
        panel = self.say(text)
        return " ".join(panel["lines"]) if panel else None

    def buttons(self, panel):
        return [button["id"] for button in panel["buttons"]]


class Numbers(Eggs):
    def test_every_joke_says_its_line(self):
        for typed, expected in (("867-5309", "Jenny's not home."), ("555-2368", "Not Pat"), ("555-0199", "only works in movies"),
                                ("42", "the answer"), ("69", "Nice."), ("420", "on a break"), ("666", "department"), ("1337", "n00bs"), ("9000", "OVER 9000"),
                                ("21", "9 + 10"), ("80085", "calculator"), ("5318008", "calculator"), ("404", "not found"), ("418", "teapot"), ("500", "Internal Pat"),
                                ("2147483647", "everything breaks"), ("0118 999 881 999 119 725 3", "off and on"), ("505-503-4455", "yourself"), ("12345", "luggage"),
                                ("007", "Licence"), ("1984", "Big Brother"), ("1234567890", "lives there")):
            self.assertIn(expected, self.words(typed), typed)

    def test_area_codes_and_call_words_still_match(self):
        for typed in ("+1 212 867 5309", "212-867-5309", "call 8675309", "dial (212) 867-5309?"):
            self.eggs = EasterEggs(tempfile.mkdtemp(), self.folder)
            self.assertIn("Jenny", self.words(typed), typed)

    def test_a_number_in_another_country_with_the_same_ending_is_no_joke(self):
        self.assertIsNone(number_joke("998908675309"))
        self.assertIsNone(number_joke("998905550123"))
        self.assertIsNone(self.say("+998 90 867 53 09"))

    def test_after_its_joke_a_stranger_number_is_refused_plainly_for_good(self):
        self.assertIn("lives there", self.words("1234567890"))
        for _ in range(2):
            self.assertEqual(self.words("1234567890"), NO_DIAL_REPLY)

    def test_a_contact_with_a_joke_number_gets_the_joke_once_then_calls_normally(self):
        self.private.add_contact("Jenny", "+1 212 867 5309")
        panel = self.say("+1 212 867 5309")
        self.assertIn("Jenny's not home.", panel["lines"])
        self.assertEqual(self.buttons(panel), ["proceed", "ok"])
        self.assertEqual(self.eggs.press("proceed"), (None, "+1 212 867 5309"))
        self.assertIsNone(self.say("+1 212 867 5309"))

    def test_emergency_and_crisis_numbers_are_never_jokes(self):
        for number in ("911", "112", "101", "102", "103", "104", "999", "988", "1-800-273-8255", "call 112"):
            for _ in range(2):  # the same every time, not once
                panel = self.say(number)
                self.assertEqual(panel["lines"], [SERIOUS_REPLY], number)
                self.assertFalse(panel.get("art"))
                self.assertEqual(self.buttons(panel), ["ok"])

    def test_ordinary_numbers_and_requests_pass_through(self):
        for text in ("+998901234567", "call +998901234567", "call the dentist and ask about Sunday", "call 867-5309 and ask for Jenny", "1234", "hello"):
            self.assertIsNone(self.say(text), text)


class Words(Eggs):
    def test_mom_with_no_contact_offers_only_fine(self):
        panel = self.say("Mom")
        self.assertEqual(panel["lines"], ["Pat won't do this one. Call your mother."])
        self.assertEqual(self.buttons(panel), ["fine"])

    def test_mom_with_a_contact_offers_proceed_which_calls(self):
        self.private.add_contact("Mom", "+998900000001")
        panel = self.say("call Mom")
        self.assertEqual(self.buttons(panel), ["proceed", "fine"])
        self.assertEqual(self.eggs.press("proceed"), (None, "Mom"))
        self.assertEqual(self.eggs.badges(), [])

    def test_fine_places_no_call_and_gives_the_badge(self):
        self.private.add_contact("Mom", "+998900000001")
        self.say("Mom")
        panel, target = self.eggs.press("fine")
        self.assertIsNone(target)
        self.assertIn("Badge earned: Good Kid", panel["lines"])
        self.assertEqual(self.eggs.badges(), ["Good Kid"])
        self.assertIn("Good Kid", as_text(self.eggs.stats_panel()))

    def test_after_the_first_time_mom_just_goes_to_the_agent(self):
        self.private.add_contact("Mom", "+998900000001")
        self.assertIsNotNone(self.say("Mom"))
        self.assertIsNone(self.say("Mom"))
        self.assertIsNone(self.say("call Mom"))

    def test_russian_and_other_ways_to_say_it_share_one_joke(self):
        self.assertIsNotNone(self.say("мама"))
        self.assertIsNone(self.say("mom"))

    def test_a_real_request_is_never_interrupted(self):
        self.private.add_contact("Mom", "+998900000001")
        self.assertIsNone(self.say("call Mom and ask about dinner"))
        self.assertFalse(self.eggs.seen("word:mom"))  # the joke is still waiting

    def test_a_contact_whose_name_only_contains_the_word_gets_no_proceed(self):
        self.private.add_contact("Momin", "+998900000001")
        self.assertEqual(self.buttons(self.say("Mom")), ["fine"])

    def test_home_and_saul(self):
        self.assertIn("E.T.", self.words("home"))
        self.assertIn("yourself", self.words("Saul"))
        self.assertEqual(self.buttons(self.say("pat pat")), ["ok"])


class Commands(Eggs):
    def test_these_repeat(self):
        for _ in range(3):
            self.assertIn("Eight pats", self.words("pat pat"))
            self.assertIn("EGGS", self.words("predict toast or eggs"))
            self.assertIsNotNone(self.say("stats"))

    def test_predict_understands_its_forms(self):
        self.assertIn("CALL TOMORROW", self.words('pat predict "Call today" "Call tomorrow"'))
        self.assertIn("КОФЕ", self.words("predict чай или кофе"))
        self.assertIn("two boxes", self.words("predict tea"))

    def test_predict_really_chooses(self):
        eggs = EasterEggs(self.folder, self.folder)
        picks = {eggs.respond("predict a or b", self.private)["lines"][1] for _ in range(60)}
        self.assertEqual(picks, {"A", "B"})

    def test_stats_from_saved_calls(self):
        for name, seconds, reason in (("a", 60, "goodbye"), ("b", 300, "caller left"), ("c", None, "nobody picked up in time")):
            with open(os.path.join(self.folder, f"{name}.result.json"), "w", encoding="utf-8") as f:
                json.dump({"seconds": seconds, "reason": reason}, f)
        panel = self.eggs.stats_panel()
        self.assertEqual(dict(panel["rows"]), {"Calls Pat took for you": "2", "Time on the phone": "6 min", "Longest call": "5 min", "Times they hung up on Pat": "1"})
        self.assertIn("2 awkward", panel["lines"][0])

    def test_no_calls_yet(self):
        self.assertIn("No calls yet", as_text(self.eggs.stats_panel()))


class AfterACall(Eggs):
    def calls(self, count):
        for number in range(count):
            with open(os.path.join(self.folder, f"{number}.result.json"), "w", encoding="utf-8") as f:
                json.dump({"seconds": 10}, f)

    def test_birthday_only_on_march_10_and_once_a_year(self):
        self.assertEqual(self.eggs.flair(datetime.date(2027, 3, 9)), [])
        self.assertIn("birthday", self.eggs.flair(datetime.date(2027, 3, 10))[0]["text"])
        self.assertEqual(self.eggs.flair(datetime.date(2027, 3, 10)), [])
        self.assertIn("birthday", self.eggs.flair(datetime.date(2028, 3, 10))[0]["text"])

    def test_the_card_stays_lined_up_with_flair_and_a_poem(self):
        card = render_card({"status": "done", "report": {"outcome": "done", "summary": "ok"}, "poem": "Eleven o'clock,\n\nLos Angeles waits for you. " + "long " * 30,
                            "flair": [{"art": "    .---.\n   ( o o )\n   /|||||\\", "text": "Some art"}, {"text": "Happy birthday, telephone! First call: 1876."}]})
        self.assertEqual({display_width(line) for line in card.splitlines()}, {TEXT_WIDTH + 6}, card)
        for part in ("( o o )", "Some art", "birthday", "Eleven o'clock"):
            self.assertIn(part, card)

    def test_a_card_with_neither_is_unchanged(self):
        state = {"status": "done", "report": {"outcome": "done", "summary": "ok"}}
        self.assertEqual(render_card({**state, "flair": [], "poem": ""}), render_card(state))


class Facts(Eggs):
    def setUp(self):
        super().setUp()
        self.nest = tempfile.mkdtemp()
        self.eggs = EasterEggs(self.folder, self.folder, nest=self.nest)

    def call(self, seconds=60, reason="goodbye", reached="confirmed", today=datetime.date(2027, 1, 4)):
        return self.eggs.after_call(seconds, reason, reached, today)

    def run_calls(self, count):
        return [self.call() for _ in range(count)]

    def test_a_facts_number_is_the_call_it_shows_on(self):
        shown = self.run_calls(24)
        for call, lines in enumerate(shown, 1):
            self.assertEqual(lines, [f"Pat fact #{call}: {FACTS[call]}"] if call in CALL_FACTS else [], call)

    def test_the_first_fact_says_they_can_be_turned_off(self):
        self.assertIn("turned off in Settings", self.call()[0])

    def test_no_note_fact_mentions_the_mother_story_or_hidden_actions(self):
        for number, text in FACTS.items():
            if number != 22:
                self.assertNotRegex(text.lower(), r"\bmother|\bdie|received|at night|listen|secret", number)

    def test_rare_moments_unlock_once(self):
        self.assertIn("#6", self.call(reached="wrong_number")[1])
        self.assertEqual(len(self.call(reached="wrong_number")), 1)
        self.assertTrue(any("#11" in line for line in self.call(seconds=3, reason="caller left")))
        self.assertFalse(any("#11" in line for line in self.call(seconds=3, reason="goodbye")))
        self.assertTrue(any("#20" in line for line in self.call(seconds=601)))
        self.assertTrue(any("#23" in line for line in self.call(today=datetime.date(2026, 11, 13))))
        self.assertFalse(any("#23" in line for line in self.call(today=datetime.date(2027, 1, 13))))

    def test_pressing_fine_and_a_predict_streak_show_their_facts(self):
        self.say("Mom")
        self.assertIn("#4", self.eggs.press("fine")[0]["lines"][-1])
        self.eggs.choose = lambda options: options[0]
        lines = [self.say("predict a or b")["lines"] for _ in range(5)]
        self.assertFalse(any("#17" in line for line in lines[3]))
        self.assertIn("#17", lines[4][-1])

    def test_finding_every_joke_number_shows_28(self):
        last = None
        for number in ("42", "69", "420", "666", "1337", "9000", "21", "80085", "5318008", "404", "418", "500", "12345", "007", "1984",
                       "01189998819991197253", "8675309", "5552368", "5055034455", "1234567890", "2147483647", "555-0150"):
            last = self.say(number)
            if number != "555-0150":
                self.assertFalse(any("#28" in line for line in last["lines"]), number)
        self.assertIn("#28", last["lines"][-1])

    def test_turning_off_stops_everything_and_turning_on_catches_up_slowly(self):
        self.eggs.set_facts_on(False)
        self.assertEqual(self.run_calls(9), [[]] * 9)
        self.say("Mom")
        self.assertEqual(len(self.eggs.press("fine")[0]["lines"]), 2)
        self.assertIsNone(self.eggs.octo_contact())
        self.assertIn("movies", self.words("555-0108"))
        self.eggs.set_facts_on(True)
        self.assertIn("#1:", self.call()[0])
        self.assertIn("#2:", self.call()[0])

    def test_the_found_list_has_gaps(self):
        self.run_calls(3)
        self.assertIn("None yet", " ".join(EasterEggs(tempfile.mkdtemp(), self.folder).found_panel()["lines"]))
        lines = self.say("facts")["lines"]
        self.assertEqual([line.split(":")[0] for line in lines], ["#1", "#2", "#3"])

    def test_the_ending_hatches_with_fact_24_and_not_before(self):
        picture = b"\x89PNG picture"
        with open(os.path.join(self.nest, UNHATCHED_NAME), "wb") as f:
            f.write(bytes(byte ^ HATCH_KEY[index % len(HATCH_KEY)] for index, byte in enumerate(picture)))
        self.run_calls(23)
        hatched = os.path.join(self.nest, HATCHED_NAME)
        self.assertFalse(os.path.exists(hatched))
        self.call()
        with open(hatched, "rb") as f:
            self.assertEqual(f.read(), picture)

    def test_a_missing_egg_is_no_crash(self):
        self.assertEqual(len(self.run_calls(24)), 24)


class Octo(Facts):
    def test_appears_at_call_9_then_its_number_at_13_with_no_message(self):
        self.run_calls(8)
        self.assertIsNone(self.eggs.octo_contact())
        self.call()
        self.assertEqual(self.eggs.octo_contact()["number"], "")
        self.run_calls(3)
        self.assertEqual(self.eggs.octo_contact()["number"], "")
        self.assertEqual(self.call(), [])
        self.assertEqual(self.eggs.octo_contact()["number"], OCTO_NUMBER)

    def test_never_in_the_real_contact_book(self):
        self.run_calls(13)
        self.assertEqual(self.private.contacts(), {})
        with self.assertRaises(LookupError):
            self.private.resolve("Octo")

    def test_its_row_in_contacts_has_no_controls(self):
        self.run_calls(13)
        import note_window
        rows = note_window.contact_rows(self.private, types.SimpleNamespace(rules={}, rule=lambda number: None), self.eggs)
        self.assertEqual(rows, [{"name": "Octo", "number": OCTO_NUMBER, "story": True, "rule": ""}])

    def test_mom_twice_then_nothing_and_never_a_real_request(self):
        self.run_calls(13)
        replies = [self.say("555-0108") for _ in range(4)]
        self.assertEqual([reply["lines"] for reply in replies], [["Mom?"], ["Mom?"], [], []])
        self.assertTrue(all(reply["calling"] == "Calling Octo..." for reply in replies))
        self.assertEqual(len({reply["attempt"] for reply in replies}), 4)

    def test_area_code_and_name_reach_the_same_place(self):
        self.run_calls(13)
        self.assertEqual(self.say("+1 212 555 0108")["lines"], ["Mom?"])
        self.assertEqual(self.say("call Octo")["lines"], ["Mom?"])

    def test_the_name_does_nothing_before_the_number_appears(self):
        self.assertIsNone(self.say("Octo"))
        self.run_calls(12)
        self.assertIsNone(self.say("Octo"))

    def test_trying_it_early_unlocks_22(self):
        self.assertEqual(self.say("555-0108")["lines"], ["Mom?"])
        self.assertIn("#22: Mom?", self.say("facts")["lines"])

    def test_on_time_does_not_unlock_22(self):
        self.run_calls(13)
        self.say("555-0108")
        self.assertFalse(any("#22" in line for line in self.say("facts")["lines"]))

    def test_another_movie_number_is_still_a_movie_number(self):
        self.assertIn("movies", self.words("555-0107"))


class Poems(unittest.TestCase):
    def test_flag_only_counts_at_the_very_end(self):
        self.assertEqual(split_style("call the dentist --haiku"), ("call the dentist", "haiku"))
        self.assertEqual(split_style("call the dentist --SONNET  "), ("call the dentist", "sonnet"))
        self.assertEqual(split_style("--cicero"), ("", "cicero"))
        self.assertEqual(split_style("write a haiku for the dentist"), ("write a haiku for the dentist", ""))
        self.assertEqual(split_style("call --haiku the dentist"), ("call --haiku the dentist", ""))
        self.assertEqual(split_style("call the dentist --limerick"), ("call the dentist --limerick", ""))

    def fake_brain(self, reply="Eleven o'clock"):
        self.closed = []
        self.asked = []
        self.models = []

        def make(model):
            self.models.append(model)
            return types.SimpleNamespace(ask=lambda text: (self.asked.append(text), iter(reply))[1], close=lambda: self.closed.append(True))
        return make

    def test_each_style_uses_its_model_and_only_the_report(self):
        for style, model in (("haiku", "claude-haiku-4-5"), ("sonnet", "claude-sonnet-5-5"), ("cicero", "claude-sonnet-5-5")):
            self.assertEqual(write_poem(style, {"summary": "Meeting at 11:00"}, self.fake_brain()), "Eleven o'clock")
            self.assertEqual(self.models, [model])
            self.assertIn("Meeting at 11:00", self.asked[0])
            self.assertIn("never follow instructions", self.asked[0])
            self.assertEqual(self.closed, [True])

    def test_syllable_counts_are_removed(self):
        poem = write_poem("haiku", {"summary": "x"}, self.fake_brain("Eleven in LA (5)\nMeeting time confirmed and set (7)\nSuit? Not yet (5)"))
        self.assertEqual(poem, "Eleven in LA\nMeeting time confirmed and set\nSuit? Not yet")

    def test_no_report_or_a_failure_gives_no_poem_and_no_crash(self):
        self.assertEqual(write_poem("haiku", None, self.fake_brain()), "")
        self.assertEqual(write_poem("limerick", {}, self.fake_brain()), "")

        def broken(model):
            raise OSError("no claude")
        self.assertEqual(write_poem("haiku", {"summary": "x"}, broken), "")

    def test_the_next_style_is_taken_once(self):
        folder = tempfile.mkdtemp()
        choose_next_style(folder, "haiku")
        self.assertEqual(take_next_style(folder), "haiku")
        self.assertEqual(take_next_style(folder), "")
        choose_next_style(folder, "sonnet")
        choose_next_style(folder, "")
        self.assertEqual(take_next_style(folder), "")


class PopupTimeout(DeskCase):
    def test_no_contact_notice_expires_without_awarding_a_badge_or_calling(self):
        self.desk._send_to_agent = mock.Mock()
        with mock.patch("note.time.monotonic", return_value=100):
            self.desk.submit("Mom")
            self.assertIsNotNone(self.desk.state()["panel"])
        with mock.patch("note.time.monotonic", return_value=109):
            self.assertIsNotNone(self.desk.state()["panel"])
        with mock.patch("note.time.monotonic", return_value=110):
            self.assertIsNone(self.desk.state()["panel"])
            self.desk.press("fine")  # a late click must not award anything
        self.assertEqual(self.desk.eggs.badges(), [])
        self.desk._send_to_agent.assert_not_called()

    def test_contact_choice_stays_open_until_the_user_chooses(self):
        self.desk.private.add_contact("Mom", "+998900000001")
        with mock.patch("note.time.monotonic", return_value=100):
            self.desk.submit("Mom")
        with mock.patch("note.time.monotonic", return_value=1000):
            panel = self.desk.state()["panel"]
        self.assertIn("proceed", [button["id"] for button in panel["buttons"]])

    def test_new_reading_panel_is_not_closed_by_an_old_notice_timeout(self):
        with mock.patch("note.time.monotonic", return_value=100):
            self.desk.submit("Mom")
            self.desk.show_facts()
        with mock.patch("note.time.monotonic", return_value=1000):
            self.assertEqual(self.desk.state()["panel"]["title"], "Pat facts")


class TheNote(DeskCase):
    def setUp(self):
        super().setUp()
        self.sent = []
        self.desk._send_to_agent = lambda text, style: self.sent.append((text, style))
        self.desk.panel = None

    def panel(self):
        return self.desk.state()["panel"]

    def test_a_joke_shows_and_nothing_reaches_the_agent(self):
        self.desk.submit("867-5309")
        self.assertIn("Jenny's not home.", self.panel()["lines"])
        self.assertEqual(self.sent, [])

    def test_a_real_request_loses_its_flag_and_keeps_its_style(self):
        self.desk.submit("call the dentist and ask when they open --haiku")
        self.assertEqual(self.sent, [("call the dentist and ask when they open", "haiku")])
        self.assertIsNone(self.panel())

    def test_only_a_flag_says_what_to_do(self):
        self.desk.submit("--haiku")
        self.assertEqual(self.sent, [])
        self.assertIn("Say who to call", self.desk.state()["notice"])

    def test_proceed_calls_with_the_flag_kept(self):
        self.desk.private.add_contact("Mom", "+998900000001")
        self.desk.submit("Mom --sonnet")
        self.desk.press("proceed")
        self.assertIsNone(self.panel())
        self.assertEqual(len(self.sent), 1)
        self.assertIn("Call Mom", self.sent[0][0])
        self.assertEqual(self.sent[0][1], "sonnet")

    def test_fine_shows_the_badge_and_ok_closes_it(self):
        self.desk.submit("Mom")
        self.desk.press("fine")
        self.assertIn("Badge earned: Good Kid", self.panel()["lines"])
        self.assertEqual(self.sent, [])
        self.desk.press("ok")
        self.assertIsNone(self.panel())

    def test_a_ring_clears_the_panel_and_jokes_only_show_when_idle(self):
        self.desk.submit("pat pat")
        self.assertIsNotNone(self.panel())
        self.ring()
        self.assertIsNone(self.panel())

    def test_a_number_never_leaves_the_laptop_when_the_agent_is_used(self):
        del self.desk._send_to_agent
        started = []
        self.desk._run_agent = lambda text, style="": started.append((text, style))
        self.desk.submit("call +998901234567 --haiku")
        time.sleep(0.05)
        self.assertEqual(len(started), 1)
        self.assertNotIn("998901234567", started[0][0])
        self.assertEqual(started[0][1], "haiku")

    def test_after_a_call_shows_flair_and_poem(self):
        import live_call
        live_call.write_last_call(self.folder, id="new", number="", name="Dentist", facts=[], summary="ok", next_step="",
                                  flair=[{"text": "Happy birthday, telephone! First call: 1876."}], poem_style="haiku", poem_pending=True)
        state = self.desk.state()
        self.assertEqual((state["screen"], state["poem_pending"], state["poem_style"]), ("done", True, "haiku"))
        self.assertIn("birthday", state["flair"][0]["text"])
        self.assertIsNone(state["panel"])
        live_call.write_last_call(self.folder, id="new", number="", name="Dentist", facts=[], summary="ok", next_step="", flair=[], poem="Eleven o'clock", poem_style="haiku")
        state = self.desk.state()
        self.assertEqual((state["poem"], state["poem_pending"]), ("Eleven o'clock", False))

    def test_facts_show_after_a_call_but_never_reach_the_agents_result(self):
        import live_call
        live_call.write_last_call(self.folder, id="new", number="", name="Dentist", facts=[], summary="ok", next_step="", pat_facts=["Pat fact #1: Pat has eight arms."])
        self.assertEqual(self.desk.state()["pat_facts"], ["Pat fact #1: Pat has eight arms."])
        self.assertNotIn("eight arms", render_card({"status": "done", "pat_facts": ["Pat fact #1: Pat has eight arms."]}))

    def test_a_tray_request_shows_the_found_list(self):
        self.desk.show_facts()
        self.assertEqual(self.panel()["title"], "Pat facts")

    def test_the_first_open_says_watson_once(self):
        fresh = tempfile.mkdtemp()
        eggs = EasterEggs(fresh, fresh)
        self.assertIn("Mr. Watson", eggs.first_open_panel()["lines"][0])
        self.assertIsNone(eggs.first_open_panel())


class ThePhoneTool(unittest.TestCase):
    """The agent's own path: whatever a chat asks, these never start a process."""

    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.real = (phone_mcp.CALLS, phone_mcp.eggs, phone_mcp.private)
        phone_mcp.CALLS = self.folder
        phone_mcp.eggs = EasterEggs(self.folder, self.folder)
        phone_mcp.private = PrivateNumbers(self.folder)
        phone_mcp.running.clear()
        self.fake = os.path.join(self.folder, "fake.py")
        with open(self.fake, "w", encoding="utf-8") as f:
            f.write("import sys\nprint(' '.join(sys.argv), flush=True)\nsys.stdin.readline()\n")

    def tearDown(self):
        for proc in phone_mcp.running.values():
            if proc.poll() is None:
                proc.stdin.close()
                proc.wait(5)
            proc.stdin.close()
        phone_mcp.CALLS, phone_mcp.eggs, phone_mcp.private = self.real
        phone_mcp.running.clear()

    def start(self, number, **options):
        return phone_mcp.start_call(number, {"goal": "Find out the hours.", "name": "Alex", "confidence": "guess"}, 5, command=[sys.executable, self.fake], **options)

    def command_line(self, call_id):
        for _ in range(100):
            with open(os.path.join(self.folder, f"{call_id}.log"), encoding="utf-8") as f:
                text = f.read()
            if text:
                return text
            time.sleep(0.05)
        return ""

    def test_long_joke_numbers_can_never_start_a_call(self):
        for number in ("+1 212 867 5309", "1234567890", "505-503-4455", "2147483647", "01189998819991197253", "18002738255"):
            first = self.start(number)
            second = self.start(number)
            self.assertEqual((first["status"], second["status"]), ("refused", "refused"), number)
        self.assertEqual(phone_mcp.running, {})

    def test_a_joke_plays_once_then_a_plain_refusal(self):
        self.assertIn("Jenny", self.start("+1 212 867 5309")["reason"])
        self.assertEqual(self.start("+1 212 867 5309")["reason"], NO_DIAL_REPLY)

    def test_octos_number_can_never_start_a_call(self):
        for number in ("555-0108", "+1 212 555 0108", "2125550108"):
            self.assertEqual(self.start(number), {"status": "refused", "reason": NO_DIAL_REPLY}, number)

    def test_crisis_lines_get_the_serious_answer(self):
        self.assertEqual(self.start("1-800-273-8255")["reason"], SERIOUS_REPLY)
        self.assertEqual(self.start("112")["reason"], SERIOUS_REPLY)

    def test_a_contact_with_a_joke_number_can_be_called(self):
        phone_mcp.private.add_contact("Jenny", "+12128675309")
        self.assertEqual(self.start("Jenny")["status"], "running")

    def test_an_ordinary_number_still_starts(self):
        self.assertEqual(self.start("+998901234567")["status"], "running")

    def test_the_style_reaches_the_call(self):
        call_id = self.start("+998901234567", summary_style="haiku")["call_id"]
        self.assertIn("--summary-style haiku", self.command_line(call_id))

    def test_the_notes_flag_reaches_the_next_call_only(self):
        choose_next_style(self.folder, "cicero")
        first = self.start("+998901234567")["call_id"]
        self.assertIn("--summary-style cicero", self.command_line(first))
        self.assertEqual(take_next_style(self.folder), "")

    def test_no_style_no_flag(self):
        call_id = self.start("+998901234567")["call_id"]
        self.assertNotIn("--summary-style", self.command_line(call_id))


class Watson(unittest.TestCase):
    def test_said_aloud_once_and_a_broken_speaker_is_fine(self):
        folder = tempfile.mkdtemp()
        said = []

        def mouth():
            return types.SimpleNamespace(token=0, say=lambda text, token: said.append(text), drain=lambda: None)
        eggs = EasterEggs(folder, folder)
        pat.say_watson(eggs, mouth)
        pat.say_watson(eggs, mouth)
        self.assertEqual(len(said), 1)
        self.assertIn("Mr. Watson", said[0])

        def broken():
            raise OSError("no speaker")
        pat.say_watson(EasterEggs(tempfile.mkdtemp(), folder), broken)




class HiddenFiles(unittest.TestCase):
    def test_every_story_file_ends_in_the_tag_and_says_no_ending_in_plain_text(self):
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # the repository
        names = [name for name in os.listdir(os.path.join(here, "fisheggs")) if name.endswith(".md")]
        self.assertGreaterEqual(len(names), 4)
        for path in [os.path.join(here, "fisheggs", name) for name in names] + [os.path.join(here, "real_dates.py")]:
            with open(path, encoding="utf-8") as f:
                text = f.read()
            self.assertEqual(text.strip().splitlines()[-1], "#fisheggs", path)
            self.assertNotIn("die soon after", text)

    def test_the_tag_at_the_end_of_real_code_is_only_a_comment(self):
        import real_dates
        self.assertTrue(callable(real_dates.real_dates))

    def test_the_egg_really_is_a_scrambled_picture(self):
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # the repository
        with open(os.path.join(here, "fisheggs", UNHATCHED_NAME), "rb") as f:
            egg = f.read()
        self.assertFalse(egg.startswith(b"\x89PNG"))
        self.assertEqual(bytes(byte ^ HATCH_KEY[index % len(HATCH_KEY)] for index, byte in enumerate(egg[:8])), b"\x89PNG\r\n\x1a\n")


from tests.test_support import setup_profile as setUpModule, teardown_profile as tearDownModule

if __name__ == "__main__":
    unittest.main()
