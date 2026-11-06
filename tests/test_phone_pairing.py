"""The note's "Set up the phone for Pat's calls" window, with a pretend phone helper only. Nothing touches Bluetooth."""
import sys
import threading
import time
import types
import unittest
from unittest import mock

from phone_pairing import PairingRun, parse_event


class Driver(unittest.TestCase):
    def test_only_json_objects_with_an_event_count(self):
        self.assertEqual(parse_event('{"event": "found", "number": 1, "name": "iPhone"}')["name"], "iPhone")
        for line in ("phone    : iPhone", "access   : Allowed", "[1, 2]", '{"text": "no event"}', ""):
            self.assertIsNone(parse_event(line))

    def test_a_run_passes_on_events_and_answers_then_says_it_closed(self):
        helper = ("import json, sys\n"
                  "print('phone    : not json, only logged', flush=True)\n"
                  "print(json.dumps({'event': 'phones', 'text': 'Which?', 'phones': [{'name': 'Тест'}]}), flush=True)\n"
                  "answer = sys.stdin.readline().strip()\n"
                  "print(json.dumps({'event': 'done', 'text': 'got ' + answer}), flush=True)\n")
        events = []
        closed = threading.Event()

        def on_event(event):
            events.append(event)
            if event["event"] == "phones":
                run.answer("1")
            if event["event"] == "closed":
                closed.set()
        run = PairingRun(on_event, command=(sys.executable, "-c", helper))
        self.assertTrue(closed.wait(10))
        self.assertEqual([e["event"] for e in events], ["phones", "done", "closed"])
        self.assertEqual(events[0]["phones"][0]["name"], "Тест")  # names in any language arrive whole
        self.assertEqual(events[1]["text"], "got 1")
        run.stop()  # already finished: nothing to do


class FakeRun:
    def __init__(self, on_event):
        self.on_event = on_event
        self.answers = []
        self.stopped = False

    def answer(self, text):
        self.answers.append(text)

    def stop(self):
        self.stopped = True


class Flow(unittest.TestCase):
    """The set-up steps inside the note, with a pretend helper."""

    def open(self):
        from pairing_flow import PairingFlow
        self.order = []
        self.saved = []
        made = []

        def factory(on_event):
            self.order.append("helper")
            made.append(FakeRun(on_event))
            return made[0]
        flow = PairingFlow(pause=lambda: self.order.append("pause"), resume=lambda: self.order.append("resume"),
                           run_factory=factory, save=lambda name, device: self.saved.append((name, device)))
        flow.start()
        return flow, made[0]

    def wait_for(self, condition):
        deadline = time.time() + 5
        while not condition() and time.time() < deadline:
            time.sleep(0.01)

    def test_the_note_lets_go_of_the_phone_before_the_helper_starts_and_takes_it_back_after(self):
        flow, run = self.open()
        self.assertEqual(self.order, ["pause", "helper"])
        flow.answer("close")
        self.wait_for(lambda: "resume" in self.order)
        self.assertTrue(run.stopped)
        self.assertEqual(self.order, ["pause", "helper", "resume"])  # stopped first, then the note takes the line back
        self.assertIsNone(flow.screen())

    def test_phones_come_as_a_drop_down_with_the_connected_one_chosen(self):
        flow, run = self.open()
        run.on_event({"event": "phones", "phones": [{"name": "Android phone"}, {"name": "iPhone Aziz", "connected": True}]})
        steps = flow.screen()
        self.assertEqual([o["label"] for o in steps["choose"]["options"]],
                         ["Android phone · not connected", "iPhone Aziz · connected", "My phone isn't here"])
        self.assertEqual(steps["choose"]["value"], "2")
        flow.answer("chosen", "2")
        self.assertEqual(run.answers, ["2"])

    def test_a_whole_set_up_answers_each_step_and_saves_the_new_phone(self):
        flow, run = self.open()
        run.on_event({"event": "phones", "phones": [{"name": "iPhone Aziz", "connected": True}]})
        flow.answer("chosen", "1")
        run.on_event({"event": "searching"})
        self.assertEqual(flow.screen()["status"], "Looking…")
        self.assertEqual(flow.screen()["choose"]["options"], [])  # Pair stays off until a phone is found
        run.on_event({"event": "not_found_yet"})
        self.assertIn("Can't find it?", flow.screen()["status"])
        run.on_event({"event": "found", "number": 1, "name": "iPhone Aziz"})
        self.assertEqual(flow.screen()["choose"]["options"], [{"label": "iPhone Aziz", "value": "1"}])
        flow.answer("chosen", "1")
        self.assertIn("Settings > Bluetooth", flow.screen()["hint"])  # while Windows asks the phone, say where to look
        run.on_event({"event": "code", "code": "497821"})
        self.assertEqual(flow.screen()["code"], "497821")
        self.assertIn("Settings > Bluetooth", flow.screen()["hint"])
        flow.answer("y")
        run.on_event({"event": "done", "text": "Done: Pat can take calls on iPhone Aziz.", "name": "iPhone Aziz", "id": "phone-id"})
        self.assertEqual(flow.screen()["title"], "Done")
        self.assertEqual(self.saved, [("iPhone Aziz", "phone-id")])
        self.assertEqual(run.answers, ["1", "1", "y"])
        run.on_event({"event": "closed", "code": 0})
        self.assertEqual(flow.screen()["title"], "Done")  # the helper finishing after Done changes nothing

    def test_no_code_tries_again_and_a_refusal_asks_for_forget_on_the_phone(self):
        flow, run = self.open()
        run.on_event({"event": "code", "code": "311546"})
        flow.answer("n")
        run.on_event({"event": "refused", "laptop": "XITS"})
        self.assertIn("next to XITS, then Forget This Device", flow.screen()["hint"])
        flow.answer("")
        self.assertEqual(run.answers, ["n", ""])

    def test_the_helper_stopping_early_is_said_plainly_and_stopping_on_purpose_closes(self):
        flow, run = self.open()
        run.on_event({"event": "closed", "code": 1})
        self.assertIn("stopped before the phone was set up", flow.screen()["text"])
        flow, run = self.open()
        run.on_event({"event": "stopped", "text": "Stopped. Nothing else was changed."})
        self.assertIsNone(flow.screen())

    def test_the_new_pairing_becomes_the_phone_pat_uses(self):
        import pairing_flow
        profile = mock.Mock()
        self.assertTrue(pairing_flow.save_phone("iPhone Aziz", "phone-id", profile))
        profile.save.assert_called_once_with(phone_device="phone-id", phone_name="iPhone Aziz")
        profile.save.side_effect = ValueError("no name yet")
        self.assertFalse(pairing_flow.save_phone("iPhone Aziz", "phone-id", profile))

    def test_the_note_shows_the_steps_only_on_its_idle_screen_and_one_set_up_at_a_time(self):
        import note
        late = note.LateDesk()
        late.on_problem("Phone Link has your phone.", True)
        made = []

        def factory(pause, resume):
            flow = types.SimpleNamespace(active=True, start=lambda: None, screen=lambda: {"title": "Which is your phone?"})
            made.append(flow)
            return flow
        late.start_pairing(factory)
        late.start_pairing(factory)
        self.assertEqual(len(made), 1)
        state = late.state()
        self.assertEqual(state["pairing"]["title"], "Which is your phone?")
        self.assertFalse(state["setup_phone"])  # the button hides while its steps are showing
        late.desk = types.SimpleNamespace(state=lambda: {"screen": "ringing", "notice": ""})
        self.assertIsNone(late.state()["pairing"])  # a ringing call takes the note


if __name__ == "__main__":
    unittest.main()
