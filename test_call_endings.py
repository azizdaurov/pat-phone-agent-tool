"""Call ending UI regressions with fake phones only."""
import live_call
import queue
import threading
import time
import types
from unittest import mock
from test_note import DeskCase


def quick_control(note):
    """The note's line control without its 15-second waits between tries."""
    control = note.LineControl()
    control.rest = lambda seconds: None
    return control


class Endings(DeskCase):
    def test_bad_screen_event_does_not_kill_the_phone_watcher(self):
        import note
        class FinishedTest(Exception):
            pass
        events = queue.Queue()
        events.put(("Talking", "", "Incoming")); events.put(("Closed", "", ""))
        line = types.SimpleNamespace(events=events, wait_ready=lambda: True, close=lambda: None)
        desk = types.SimpleNamespace(on_event=mock.Mock(side_effect=[ValueError("test event error"), None]))
        problems = mock.Mock()
        with self.assertRaises(FinishedTest):
            note.watch_line(mock.Mock(side_effect=[line, FinishedTest()]), lambda _: desk, problems, quick_control(note))
        self.assertEqual(desk.on_event.call_count, 2)

    def test_the_note_offers_set_up_only_when_the_pairing_is_the_problem(self):
        import note
        class FinishedTest(Exception):
            pass
        def failed(*started):
            return types.SimpleNamespace(started=list(started), wait_ready=lambda: False, close=lambda: None)
        lines = [failed("phone    : iPhone", "access   : DeniedBySystem"),
                 failed("phone    : the phone chosen in Pat's settings isn't paired any more; choosing automatically",
                        "error: Several phones are paired and none has a phone line yet."),
                 failed("No paired hands-free phone matches the selection."),
                 failed("phone    : iPhone is paired for notifications only, not calls",
                        "error: Several phones are paired and none has a phone line yet."),
                 failed("phone    : iPhone", "connect  : False"),  # off or away: Pat waits it out
                 types.SimpleNamespace(wait_ready=lambda: False, close=lambda: None)]  # a pretend line that reports nothing
        problems = mock.Mock()
        with self.assertRaises(FinishedTest):
            note.watch_line(mock.Mock(side_effect=lines + [FinishedTest()]), lambda _: None, problems, quick_control(note))
        self.assertEqual([call.args for call in problems.call_args_list],
                         [("Phone Link has your phone.", True), ("The phone Pat used isn't paired any more.", True),
                          ("No phone is set up for Pat's calls.", True),
                          ("Your phone is paired for notifications only, not calls.", True),
                          (note.NOT_CONNECTED, False), (note.NOT_CONNECTED, False)])

    def test_set_up_window_takes_the_line_without_a_problem_showing(self):
        import note
        class FinishedTest(Exception):
            pass
        control = quick_control(note)
        problems = mock.Mock()

        def make_line():
            if make_line.calls:
                raise FinishedTest()
            make_line.calls += 1
            line = types.SimpleNamespace(started=["access   : DeniedBySystem"], close=mock.Mock())
            def wait_ready():  # the set-up window opens while the line is starting
                control.pause()
                threading.Timer(0.05, control.resume).start()
                return False
            line.wait_ready = wait_ready
            return line
        make_line.calls = 0
        with self.assertRaises(FinishedTest):
            note.watch_line(make_line, lambda _: None, problems, control)
        problems.assert_not_called()

    def test_note_state_offers_set_up_only_on_the_idle_screen(self):
        import note
        late = note.LateDesk()
        late.on_problem("Phone Link has your phone.", True)
        self.assertTrue(late.state()["setup_phone"])
        late.desk = types.SimpleNamespace(state=lambda: {"screen": "ringing", "notice": ""})
        self.assertFalse(late.state()["setup_phone"])
        late.desk = None
        late.on_problem("", False)
        self.assertFalse(late.state()["setup_phone"])

    def test_pausing_closes_the_open_line_and_resuming_retries_at_once(self):
        import note
        control = note.LineControl()
        line = types.SimpleNamespace(close=mock.Mock())
        control.hold(line)
        control.pause()
        line.close.assert_called_once()
        self.assertFalse(control.running.is_set())
        control.resume()
        self.assertTrue(control.running.is_set())
        started = time.monotonic()
        control.rest(5)
        self.assertLess(time.monotonic() - started, 1)

    def test_remote_hangup_cannot_be_undone_by_the_old_live_publisher(self):
        self.ring()
        self.desk.answer_ai()
        self.set_live(session_id="first", stage="talking", number="+998900000001")
        self.desk.on_event(("Ended", "", ""))
        for _ in range(3):
            self.set_live(session_id="first", stage="talking", number="+998900000001")
            self.assertEqual(self.desk.state()["screen"], "idle")

    def test_end_button_stops_phone_and_worker_and_shows_ending_immediately(self):
        self.line.in_call = True
        self.set_live(session_id="first", stage="handed", number="+998900000001")
        self.desk.end_call()
        self.assertEqual(self.line.sent, ["hang up"])
        self.assertEqual(self.commands(), ["hang-up", "cancel"])
        self.assertEqual(self.desk.state()["screen"], "ending")
        self.assertEqual(self.desk.state()["notice"], "Ending call…")
        self.line.in_call = False
        self.desk.on_event(("Ended", "", ""))
        self.assertEqual(self.desk.state()["screen"], "idle")

    def test_summary_generation_is_not_shown_as_an_active_call(self):
        self.ring()
        self.desk.answer_ai()
        self.set_live(session_id="first", stage="wrapping", number="+998900000001")
        self.assertEqual(self.desk.state()["screen"], "idle")
        live_call.write_last_call(self.folder, id="summary-first", name="Alex", number="+998900000001", summary="Finished")
        self.assertEqual(self.desk.state()["screen"], "done")

    def test_new_call_from_same_number_is_not_hidden(self):
        self.set_live(session_id="first", stage="talking", number="+998900000001")
        self.desk.on_event(("Ended", "", ""))
        self.set_live(session_id="second", stage="talking", number="+998900000001")
        self.assertEqual(self.desk.state()["screen"], "ai")

    def test_a_new_incoming_call_can_replace_the_ending_screen(self):
        self.line.in_call = True
        self.desk.end_call()
        self.ring()
        self.assertEqual(self.desk.state()["screen"], "ringing")


from test_support import setup_profile as setUpModule, teardown_profile as tearDownModule
