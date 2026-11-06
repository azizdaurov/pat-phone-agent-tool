"""Relative dates become real ones in what's kept. Run: .venv\\Scripts\\python.exe -m unittest test_real_dates -v"""
import datetime
import tempfile
import unittest

from live_notes import LiveNotes
from observer import Observer
from phone_memory import ContactNotes, merge_call
from call_brief import CallBrief
from real_dates import SAY_DATES, date_lines, day_of, real_dates

TODAY = datetime.date(2026, 11, 3)


class Swapping(unittest.TestCase):
    def test_english_and_russian(self):
        for text, expected in (("Meeting tomorrow at 11", "Meeting 4-11-2026 at 11"), ("Встреча завтра в 11", "Встреча 4-11-2026 в 11"),
                               ("called today", "called 3-11-2026"), ("приходил вчера", "приходил 2-11-2026"), ("Yesterday he left", "2-11-2026 he left"),
                               ("the day after tomorrow", "5-11-2026"), ("послезавтра", "5-11-2026"), ("the day before yesterday", "1-11-2026"), ("позавчера", "1-11-2026"),
                               ("TOMORROW", "4-11-2026"), ("tomorrow's meeting", "4-11-2026 meeting"), ("завтрашняя встреча", "4-11-2026 встреча"),
                               ("насчёт завтрашней встречи", "насчёт 4-11-2026 встречи"), ("tonight", "3-11-2026"), ("сегодняшний разговор", "3-11-2026 разговор")):
            self.assertEqual(real_dates(text, TODAY), expected, text)

    def test_across_month_and_year_ends(self):
        self.assertEqual(real_dates("tomorrow", datetime.date(2026, 11, 30)), "1-12-2026")
        self.assertEqual(real_dates("tomorrow", datetime.date(2026, 12, 31)), "1-1-2027")
        self.assertEqual(real_dates("yesterday", datetime.date(2027, 1, 1)), "31-12-2026")

    def test_a_tomorrow_from_yesterday_keeps_yesterdays_tomorrow(self):
        written_then = real_dates("Meeting tomorrow", datetime.date(2026, 11, 2))
        self.assertEqual(real_dates(written_then, TODAY), "Meeting 3-11-2026")

    def test_dates_are_written_one_way(self):
        self.assertEqual(real_dates("Meeting 2026-11-04 at 11:00, 2026-01-09", TODAY), "Meeting 4-11-2026 at 11:00, 9-1-2026")

    def test_other_words_and_numbers_stay(self):
        for text in ("Todayville", "the tomorrowland park", "at 11:00", "room 2026", "Monday", "", "сегодняшнийдень-x"[:0]):
            self.assertEqual(real_dates(text, TODAY), text)

    def test_reports_are_swapped_all_the_way_down(self):
        report = {"summary": "Meeting tomorrow", "answers": [{"label": "When", "answer": "завтра", "confirmed": True}, {"answer": None}], "seconds": 5}
        self.assertEqual(real_dates(report, TODAY), {"summary": "Meeting 4-11-2026", "answers": [{"label": "When", "answer": "4-11-2026", "confirmed": True}, {"answer": None}], "seconds": 5})

    def test_what_a_model_is_told(self):
        lines = date_lines(TODAY)
        for part in ("Tuesday, 3-11-2026", "Tomorrow is 4-11-2026", "Yesterday was 2-11-2026", "Friday 6-11-2026", "Tuesday 10-11-2026", "Next week starts on 9-11-2026"):
            self.assertIn(part, lines)

    def test_reading_a_timestamp(self):
        self.assertEqual(day_of("2026-11-03 13:42"), TODAY)
        self.assertEqual(day_of("nonsense"), datetime.date.today())


class WhereTheyAreKept(unittest.TestCase):
    def notes(self):
        return ContactNotes("900000001", tempfile.mkdtemp())

    def test_notes_use_the_date_of_the_call_even_if_written_later(self):
        notes = self.notes()
        prompts = []

        def model(text):
            prompts.append(text)
            return "OPEN: Meeting tomorrow at 11.\nLAST: 2026-11-03 Alex confirmed."
        merge_call(notes, [("Them", "Да, встреча завтра в одиннадцать")], model, "2026-11-03 13:42")
        self.assertEqual(notes.summary, "OPEN: Meeting 4-11-2026 at 11.\nLAST: 3-11-2026 Alex confirmed.")
        self.assertIn("Tomorrow is 4-11-2026", prompts[0])

    def test_report_gets_real_dates(self):
        asked = []

        def model(text):
            asked.append(text)
            return '{"outcome":"done","summary":"Meeting tomorrow","answers":[{"label":"When","answer":"завтра в 11"}]}'
        report = Observer(model, [], "Aziz").final_report("goodbye", seconds=5)
        day = real_dates("tomorrow")
        self.assertEqual(report["summary"], f"Meeting {day}")
        self.assertEqual(report["answers"][0]["answer"], f"{day} в 11")
        self.assertIn("Tomorrow is", asked[0])

    def test_live_note_gets_real_dates(self):
        import time
        notes = LiveNotes(lambda text: '{"facts":[{"label":"Time","value":"завтра в 11"}],"summary":"Meeting tomorrow"}', ["When?"], today=TODAY)
        notes.request([("Them", "Завтра в одиннадцать")])
        deadline = time.time() + 2
        while not notes.summary and time.time() < deadline:
            time.sleep(0.01)
        self.assertEqual(notes.facts[0]["value"], "4-11-2026 в 11")
        self.assertEqual(notes.summary, "Meeting 4-11-2026")
        notes.close()

    def test_model_gets_the_date_table_on_the_live_note(self):
        notes = LiveNotes(lambda text: "", ["When?"], today=TODAY)
        self.assertIn("Tomorrow is 4-11-2026", notes._prompt([]))
        notes.close()

    def test_only_haiku_is_told_how_to_say_dates(self):
        brief = CallBrief.from_dict({"goal": "Book a table.", "need_from_them": ["Is it free?"]})
        target = CallBrief.from_dict({"goal": "Book a table.", "name": "Alex", "confidence": "confirmed"})
        for prompt in (brief.haiku_prompt("Speak.", "Hello.", "Aziz", "n"), target.haiku_prompt("Speak.", "Hello.", "Aziz", "n")):
            self.assertIn(SAY_DATES["en"], prompt)
            self.assertNotIn("шестого ноября", prompt)  # only the call's own language
        self.assertNotIn(SAY_DATES["en"], brief.observer_prompt("Aziz"))

    def test_the_date_table_is_sent_once_on_calls_that_check_who_answered(self):
        target = CallBrief.from_dict({"goal": "Book a table.", "name": "Alex", "confidence": "confirmed", "language": "ru"})
        self.assertIn(SAY_DATES["ru"], target.haiku_prompt("Speak.", "Hello.", "Aziz", "n"))
        self.assertNotIn("Friday, the sixth", target.haiku_prompt("Speak.", "Hello.", "Aziz", "n"))
        task = target.task_message("Aziz")
        self.assertNotIn(SAY_DATES["ru"], task)
        self.assertIn("including the date table", task)


from tests.test_support import setup_profile as setUpModule, teardown_profile as tearDownModule

if __name__ == "__main__":
    unittest.main()
