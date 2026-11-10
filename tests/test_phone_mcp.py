"""The phone tool, through a real MCP connection and with a fake pat.py, so nothing dials.
Run: .venv\\Scripts\\python.exe -m unittest test_phone_mcp -v"""
import json
import os
import sys
import tempfile
import unittest

import anyio

import phone_mcp
from call_card import TEXT_WIDTH, display_width, render_card
from private_numbers import PrivateNumbers

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # the repository
FAKE_PAT = r"""
import json, sys
args = sys.argv[1:]
result = args[args.index("--result-file") + 1]
print("ARGS", args, flush=True)
print("Claude: Hello", flush=True)
print("Them: Yes, open on Sunday", flush=True)
line = sys.stdin.readline()
with open(result, "w", encoding="utf-8") as f:
    json.dump({"status": "done", "reason": "hung up on request" if line.strip() == "h" else "goodbye",
               "report": {"outcome": "done"}}, f)
"""
NUMBER = "+998 90 000 00 01"
BRIEF = {"goal": "Find out the Sunday hours.", "name": "Рустам", "confidence": "guess", "language": "ru"}


FULL_REPORT = {
    "status": "done", "number": "+998 90 000 00 01", "seconds": 72,
    "report": {
        "outcome": "done",
        "answers": [{"label": "Place", "answer": "Los Angeles", "confirmed": True},
                    {"label": "Time", "answer": "11:00", "confirmed": False},
                    {"need": "How much does the check-up cost?", "answer": None, "confirmed": False}],
        "summary": "They confirmed the meeting and asked Aziz to come early.",
        "important_details": ["Bring a suit"],
        "follow_up": "Reply by Friday",
    },
}


class Card(unittest.TestCase):
    def assert_frame_lines_up(self, card):
        widths = {display_width(line) for line in card.splitlines()}
        self.assertEqual(widths, {TEXT_WIDTH + 6}, card)

    def test_full_card_has_everything_and_lines_up(self):
        card = render_card(FULL_REPORT)
        self.assert_frame_lines_up(card)
        for part in ("Call Summary", "Done", "+998 90 000 00 01", "1 min 12 s", "Place", "Los Angeles", "Bring a suit",
                     "Reply by Friday", "come early"):
            self.assertIn(part, card)

    def test_a_contact_question_gets_its_own_section(self):
        card = render_card({"status": "done", "report": {"outcome": "done", "summary": "ok", "contact": "Says they are Sam: add to contacts?"}})
        self.assert_frame_lines_up(card)
        self.assertIn("CONTACT", card)
        self.assertIn("add to contacts?", card)

    def test_long_labels_wrap_instead_of_being_cut(self):
        card = render_card({"status": "done", "report": {"outcome": "done", "answers": [{"label": "Time and place of the meeting", "answer": "11:00", "confirmed": True}]}})
        self.assert_frame_lines_up(card)
        self.assertNotIn("…", card)
        for word in ("Time", "place", "meeting", "11:00"):
            self.assertIn(word, card)

    def test_unconfirmed_and_missing_answers_are_marked(self):
        card = render_card(FULL_REPORT)
        self.assertRegex(card, r"11:00 \(not confirmed\)")
        self.assertIn("not obtained", card)
        self.assertNotIn("Los Angeles (not confirmed)", card)

    def test_russian_long_text_wide_characters_and_long_words_line_up(self):
        report = {"outcome": "partial", "summary": "Встреча перенесена на следующую неделю, " * 4,
                  "answers": [{"label": "Очень длинное название поля ответа", "answer": "Москва, улица Тверская " * 4, "confirmed": True},
                              {"label": "地点", "answer": "東京都渋谷区" * 8, "confirmed": True},
                              {"label": "Link", "answer": "https://example.com/" + "a" * 90, "confirmed": True}],
                  "important_details": ["Обязательно " * 12]}
        card = render_card({"status": "done", "report": report})
        self.assert_frame_lines_up(card)
        self.assertIn("Partly done", card)

    def test_calls_with_no_report_still_get_a_card(self):
        for status, expected in (("no_answer", "No answer"), ("failed", "Failed"), ("crashed", "Failed"), ("done", "no report")):
            card = render_card({"status": status, "reason": "the call ended before anyone picked up"})
            self.assert_frame_lines_up(card)
            self.assertIn(expected, card)
            self.assertIn("picked up", card)

    def test_odd_reports_cannot_break_it(self):
        for report in (None, "nonsense", {}, {"answers": ["x", None]}, {"answers": None, "important_details": None},
                       {"summary": "a\nb\n\n```\nc"}):
            card = render_card({"status": "done", "report": report})
            self.assert_frame_lines_up(card)
            self.assertNotIn("```", card)


class CardReached(unittest.TestCase):
    def test_who_was_reached_is_shown_and_lines_up(self):
        for reached, expected in (("confirmed", "Reached Рустам"), ("not_available", "Not available: Рустам"),
                                  ("wrong_number", "Wrong number, not Рустам"), ("unclear", "Couldn't confirm it was Рустам")):
            card = render_card({"status": "done", "reached": reached, "target": "Рустам"})
            self.assertIn(expected, card)
            self.assertEqual({display_width(line) for line in card.splitlines()}, {TEXT_WIDTH + 6})

    def test_not_checked_shows_nothing_extra(self):
        self.assertNotIn("Reached", render_card({"status": "done", "reached": "not_checked"}))


class Calls(unittest.TestCase):
    def setUp(self):
        folder = tempfile.mkdtemp()
        self.fake = os.path.join(folder, "fake_pat.py")
        with open(self.fake, "w", encoding="utf-8") as f:
            f.write(FAKE_PAT)
        phone_mcp.CALLS = folder
        phone_mcp.private = PrivateNumbers(folder)
        phone_mcp.running.clear()

    def start(self, number=NUMBER, brief=BRIEF, voice="", save_audio=False):
        return phone_mcp.start_call(number, brief, 5, command=[sys.executable, self.fake], voice=voice, save_audio=save_audio)

    def args_used(self, call_id):
        phone_mcp.end_call(call_id)
        phone_mcp.running[call_id].wait(10)
        with open(phone_mcp._path(call_id, "log"), encoding="utf-8") as f:
            return f.read()

    def tearDown(self):
        for proc in phone_mcp.running.values():
            if proc.poll() is None:
                proc.stdin.close()
                proc.wait(5)
            proc.stdin.close()

    def test_any_full_number_starts_with_no_approval_step(self):
        self.assertEqual(self.start(number="+1 (415) 000-0000")["status"], "running")

    def test_emergency_numbers_and_carrier_codes_are_refused_and_nothing_starts(self):
        for number in ("112", "101", "*100#", "*#06#", "+998", "", "Mom"):
            self.assertEqual(self.start(number=number)["status"], "refused", number)
        self.assertEqual(phone_mcp.running, {})

    def test_voice_reaches_an_english_call(self):
        call_id = self.start(brief={**BRIEF, "language": "en"}, voice="michael")["call_id"]
        self.assertIn("'--voice', 'michael'", self.args_used(call_id))

    def test_audio_is_saved_only_when_asked(self):
        self.assertIn("--save-audio", self.args_used(self.start(save_audio=True)["call_id"]))
        phone_mcp.running.clear()
        self.assertNotIn("--save-audio", self.args_used(self.start()["call_id"]))

    def test_no_voice_means_no_option(self):
        call_id = self.start(brief={**BRIEF, "language": "en"})["call_id"]
        self.assertNotIn("--voice", self.args_used(call_id))

    def test_english_voice_is_refused_on_a_russian_call(self):
        result = self.start(voice="michael")
        self.assertEqual(result["status"], "refused")
        self.assertIn("English calls only", result["reason"])
        self.assertEqual(phone_mcp.running, {})

    def test_take_over_reaches_a_running_call(self):
        call_id = self.start()["call_id"]
        self.assertEqual(phone_mcp.take_over(call_id), {"status": "taking over"})
        phone_mcp.running[call_id].wait(10)
        self.assertEqual(phone_mcp.take_over(call_id), {"status": "not running"})

    def test_tool_must_say_who_it_calls(self):
        result = self.start(brief={"goal": "Find out the Sunday hours."})
        self.assertEqual(result["status"], "refused")
        self.assertIn("who you are calling", result["reason"])
        self.assertEqual(phone_mcp.running, {})

    def test_confidence_is_needed_with_a_name(self):
        result = self.start(brief={"goal": "x", "name": "Рустам"})
        self.assertEqual(result["status"], "refused")
        self.assertIn("confidence", result["reason"])

    def test_bad_brief_is_refused_with_the_reason(self):
        result = self.start(brief={"goal": ""})
        self.assertEqual(result["status"], "refused")
        self.assertIn("goal", result["reason"])

    def test_not_a_number(self):
        self.assertEqual(self.start(number="Mom")["status"], "refused")

    def test_one_call_at_a_time(self):
        self.assertEqual(self.start()["status"], "running")
        self.assertEqual(self.start()["status"], "refused")

    def test_running_then_finished_with_transcript_and_report(self):
        call_id = self.start()["call_id"]
        self.assertEqual(phone_mcp.read_call(call_id)["status"], "running")
        self.assertEqual(phone_mcp.end_call(call_id), {"status": "hanging up"})
        phone_mcp.running[call_id].wait(10)
        state = phone_mcp.read_call(call_id)
        self.assertEqual((state["status"], state["reason"]), ("done", "hung up on request"))
        self.assertEqual(state["transcript"], ["Claude: Hello", "Them: Yes, open on Sunday"])
        self.assertEqual(state["report"], {"outcome": "done"})
        self.assertIn("Call Summary", state["chat_summary"])

    def test_sonnets_corrections_stay_out_of_get_call(self):
        call_id = "20261109-120000-abcdef"
        with open(phone_mcp._path(call_id, "log"), "w", encoding="utf-8") as f:
            f.write("Claude: Hello\n")
        with open(phone_mcp._path(call_id, "result.json"), "w", encoding="utf-8") as f:
            json.dump({"status": "done", "report": {"outcome": "done"},
                       "corrections": [{"action": "correct", "note": "Ask who is calling."}]}, f)
        state = phone_mcp.read_call(call_id)
        self.assertEqual(state["status"], "done")
        self.assertNotIn("corrections", state)

    def test_each_get_call_has_only_the_lines_since_the_last_one(self):
        call_id = "20261110-120000-abcdef"
        log = phone_mcp._path(call_id, "log")
        with open(log, "w", encoding="utf-8") as f:
            f.write("Claude: Hello\nThem: Hi\n")
        get = lambda full_transcript=False: phone_mcp.only_new_lines(phone_mcp.read_call(call_id), call_id, full_transcript)
        first = get()
        self.assertEqual(first["transcript"], ["Claude: Hello", "Them: Hi"])
        self.assertNotIn("earlier_lines", first)
        self.assertEqual(get()["transcript"], [])  # nothing new
        with open(log, "a", encoding="utf-8") as f:
            f.write("Pat: Sonnet steer\nClaude: Is this Alex?\nThem: Yes\n")
        later = get()
        self.assertEqual(later["transcript"], ["Claude: Is this Alex?", "Them: Yes"])
        self.assertIn("2 earlier lines", later["earlier_lines"])
        self.assertEqual(get(full_transcript=True)["transcript"], ["Claude: Hello", "Them: Hi", "Claude: Is this Alex?", "Them: Yes"])
        with open(phone_mcp._path(call_id, "result.json"), "w", encoding="utf-8") as f:
            json.dump({"status": "done", "report": {"outcome": "done"}}, f)
        final = get()
        self.assertEqual((final["status"], final["transcript"]), ("done", []))  # the report and card still come in full
        self.assertIn("chat_summary", final)

    def test_process_dying_without_a_result_is_reported(self):
        call_id = self.start()["call_id"]
        phone_mcp.running[call_id].kill()
        phone_mcp.running[call_id].wait(5)
        state = phone_mcp.read_call(call_id)
        self.assertEqual(state["status"], "crashed")
        self.assertIn("Failed", state["chat_summary"])

    def test_a_contact_can_be_called_by_name_and_is_who_is_asked_for(self):
        phone_mcp.private.add_contact("Рустам", "+998 90 000 00 05")
        result = self.start(number="Рустам", brief={"goal": "Find out the hours.", "confidence": "confirmed"})
        self.assertEqual((result["status"], result["calling"]), ("running", "Рустам"))
        used = self.args_used(result["call_id"])
        self.assertIn("+998900000005", used)
        with open(phone_mcp._path(result["call_id"], "brief.json"), encoding="utf-8") as f:
            self.assertIn("Рустам", f.read())

    def test_a_placeholder_dials_the_real_number(self):
        label = phone_mcp.private.protect("+998 90 000 00 06")
        result = self.start(number=label)
        self.assertEqual(result["calling"], label)
        self.assertIn("+998900000006", self.args_used(result["call_id"]))

    def test_an_unknown_contact_or_placeholder_is_refused_and_nothing_starts(self):
        for target in ("Nobody", "#7"):
            self.assertEqual(self.start(number=target)["status"], "refused", target)
        self.assertEqual(phone_mcp.running, {})

    def test_call_ids_have_no_digits_of_the_number(self):
        call_id = self.start(number="+998 90 000 00 07")["call_id"]
        self.assertNotIn("900000007", call_id)
        self.assertNotIn("0000007", call_id)

    def test_nothing_handed_back_has_the_number(self):
        call_id = self.start(number="+998 90 000 00 08")["call_id"]
        phone_mcp.end_call(call_id)
        phone_mcp.running[call_id].wait(10)
        with open(phone_mcp._path(call_id, "result.json"), "w", encoding="utf-8") as f:
            json.dump({"status": "done", "number": "+998 90 000 00 08", "reason": "called 998900000008", "seconds": 5, "notes": "see contacts\\900000008.md",
                       "transcript_file": "calls\\20261103-120000-900000008.txt", "report": {"outcome": "done", "summary": "Reached +998900000008."}}, f)
        everything = json.dumps(phone_mcp.read_call(call_id), ensure_ascii=False)
        self.assertNotIn("900000008", everything)
        self.assertNotIn("000 00 08", everything)
        self.assertIn("#1", phone_mcp.read_call(call_id)["chat_summary"])

    def test_a_crashed_call_hands_back_no_number_either(self):
        call_id = self.start(number="+998 90 000 00 08")["call_id"]
        phone_mcp.running[call_id].kill()
        phone_mcp.running[call_id].wait(5)
        with open(phone_mcp._path(call_id, "log"), "w", encoding="utf-8") as f:
            f.write("Dialing +998 90 000 00 08. Claude's task\nNotes in contacts\\900000008.md\n")
        self.assertNotIn("900000008", json.dumps(phone_mcp.read_call(call_id), ensure_ascii=False))
        self.assertNotIn("000 00 08", json.dumps(phone_mcp.read_call(call_id), ensure_ascii=False))

    def test_list_contacts_has_names_only(self):
        phone_mcp.private.add_contact("Рустам", "+998 90 000 00 09")
        listed = phone_mcp.list_contacts()
        self.assertEqual(listed, {"contacts": ["Рустам"]})

    def test_contact_notes_by_name_placeholder_or_unknown(self):
        phone_mcp.private.add_contact("Рустам", "+998 90 000 00 09")
        self.assertIn("known", phone_mcp.contact_notes("Рустам"))
        self.assertEqual(phone_mcp.contact_notes("Nobody"), {"known": False})
        self.assertEqual(phone_mcp.contact_notes("#99"), {"known": False})

    def test_unknown_call_and_path_tricks(self):
        self.assertEqual(phone_mcp.read_call("..\\..\\secret")["status"], "unknown")


class Connection(unittest.TestCase):
    """What an agent actually sees."""

    def test_tools_and_refusal_over_a_real_connection(self):
        from mcp import ClientSession
        from mcp.client.stdio import StdioServerParameters, stdio_client

        async def session_results():
            # An integration test must never rely on a real contact being absent to avoid dialing.
            folder = tempfile.mkdtemp()
            bootstrap = (f"import sys; sys.path.insert(0, {os.path.join(HERE, 'app')!r}); import phone_mcp; from private_numbers import PrivateNumbers; "
                         "from easter_eggs import EasterEggs; "
                         "phone_mcp.CALLS=sys.argv[1]; phone_mcp.private=PrivateNumbers(sys.argv[1]); "
                         "phone_mcp.eggs=EasterEggs(sys.argv[1],sys.argv[1]); "
                         "phone_mcp.COMMAND=[sys.executable,'-c','raise SystemExit(0)']; phone_mcp.mcp.run()")
            params = StdioServerParameters(command=sys.executable, args=["-c", bootstrap, folder], cwd=HERE,
                                           env={"PAT_PROFILE_PATH": os.environ["PAT_PROFILE_PATH"],
                                                "PAT_SPEECH_DESCRIPTOR": os.environ.get("PAT_SPEECH_DESCRIPTOR", os.path.join(folder, "speech-service.json")),
                                                "PYTHONDONTWRITEBYTECODE": "1", "TEMP": tempfile.gettempdir(), "TMP": tempfile.gettempdir()})
            with anyio.fail_after(30):
                async with stdio_client(params) as (read, write):
                    async with ClientSession(read, write) as session:
                        init = await session.initialize()
                        tools = await session.list_tools()
                        # This contact is absent from the test book, and even valid input uses a fake worker.
                        refused = await session.call_tool("place_call", {"number": "Mom", "goal": "test", "confidence": "guess", "name": "Рустам"})
                        from user_profile import UserProfile
                        profile = UserProfile()
                        profile.save(accepted_terms="old-test-terms")
                        gated = await session.call_tool("list_contacts", {})
                        self.assertIn("setup_required", gated.content[0].text)
                        profile.accept_terms()
                        ready = await session.call_tool("list_contacts", {})
                        self.assertNotIn("setup_required", ready.content[0].text)
                        return init, tools, refused

        init, listed, refused = anyio.run(session_results)
        self.assertIn("real phone calls", init.instructions)
        tools = {tool.name: tool for tool in listed.tools}
        self.assertEqual(set(tools), {"place_call", "get_call", "end_call", "take_over", "contact_notes", "list_contacts"})
        schema = tools["place_call"].input_schema
        self.assertEqual(schema["properties"]["language"]["default"], "en")
        self.assertEqual(set(schema["required"]), {"number", "goal", "confidence"})
        for name in ("voice", "name", "company", "role", "confidence", "confirm_question", "who_can_answer", "need_from_them", "context", "may_share", "must_not", "done_when", "if_stuck", "language", "time_zone", "date_format", "may_say_before_confirmed"):
            self.assertTrue(schema["properties"][name].get("description"), name)
        self.assertIn("refused", refused.content[0].text)
        self.assertIn("full phone number", refused.content[0].text)


from tests.test_support import setup_profile as setUpModule, teardown_profile as tearDownModule

if __name__ == "__main__":
    unittest.main()
