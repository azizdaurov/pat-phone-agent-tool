"""Call ending UI regressions with fake phones only."""
import live_call
import queue
import types
from unittest import mock
from test_note import DeskCase


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
        with mock.patch.object(note.time, "sleep"):
            with self.assertRaises(FinishedTest):
                note.watch_line(mock.Mock(side_effect=[line, FinishedTest()]), lambda _: desk, problems)
        self.assertEqual(desk.on_event.call_count, 2)

    def test_when_phone_link_has_the_phone_the_note_says_to_close_it(self):
        import note
        import pat
        class FinishedTest(Exception):
            pass
        refused = types.SimpleNamespace(started=["phone    : iPhone", "access   : DeniedBySystem"], wait_ready=lambda: False, close=lambda: None,
                                        TAKEN=pat.PhoneLine.TAKEN)
        refused.taken_by_another_app = lambda: pat.PhoneLine.taken_by_another_app(refused)
        absent = types.SimpleNamespace(wait_ready=lambda: False, close=lambda: None)  # a pretend line without the check
        problems = mock.Mock()
        with mock.patch.object(note.time, "sleep"):
            with self.assertRaises(FinishedTest):
                note.watch_line(mock.Mock(side_effect=[refused, absent, FinishedTest()]), lambda _: None, problems)
        self.assertEqual([call.args[0] for call in problems.call_args_list],
                         ["Phone Link has your phone. Close Phone Link, then re-pair the phone in Bluetooth settings.", "Your phone isn't connected."])

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
