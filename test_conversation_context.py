"""Opening context and interrupted confirmations, with fake speech and models only."""
import types
import unittest
from unittest import mock

import pat
from call_brief import CallBrief
from test_supervision import FakeBrain, checked_call, conversation


class OpeningContext(unittest.TestCase):
    def test_bare_yes_answers_the_actual_opening_and_context_is_sent_once(self):
        brain = FakeBrain("[CONFIRMED]", "Are you open on Sunday?", "Thank you.")
        call, _ = checked_call(brain)
        call.opening = "Hello, this is Maya's AI assistant. Is this Alex?"
        call._say_opening()
        call._turn("Yes.", call.epoch)
        self.assertTrue(call.confirmed)
        self.assertTrue(brain.messages[0].startswith("[SUPERVISOR-abc123]"))
        self.assertIn(call.opening, brain.messages[0])
        self.assertTrue(brain.messages[0].endswith("\nYes."))
        self.assertEqual(call.mouth.spoken.count(call.opening), 1)
        call._turn("Yes.", call.epoch)
        self.assertEqual(brain.messages[-1], "Yes.")
        self.assertEqual(sum("SECRETGOAL" in message for message in brain.messages), 1)

    def test_unclear_answer_does_not_release_the_task(self):
        brain = FakeBrain("Is Alex nearby?")
        call, _ = checked_call(brain)
        call._say_opening()
        call._turn("Who are you calling?", call.epoch)
        self.assertFalse(call.confirmed)
        self.assertFalse(any("SECRET" in message for message in brain.messages))

    def test_warmup_is_marked_as_system_control_not_caller_speech(self):
        brief = CallBrief.from_dict({"goal": "Check opening hours", "language": "en"})
        fake = FakeBrain("ready")
        with mock.patch.object(pat, "Brain", return_value=fake):
            result = pat.start_brain(types.SimpleNamespace(owner="Maya"), brief, "Hello", "warmup-test", "")
        self.assertIs(result, fake)
        self.assertEqual(fake.messages, ["[SUPERVISOR-warmup-test] " + pat.WARM_UP["en"]])


class InterruptedConfirmation(unittest.TestCase):
    def test_yes_before_main_detail_is_heard_repeats_only_missing_part(self):
        for reply, heard in (("Thanks. The meeting is at forty-two Example Street. Is that right?", "Thanks."),
                             ("The meeting is at forty-two Example Street. Did I get that right?", "The"),
                             ("Спасибо. Встреча на Примерной улице, дом сорок два. Всё верно?", "Спасибо."),
                             ("Улица Примерная, дом сорок два. Правильно ли я услышал?", "Улица")):
            with self.subTest(reply=reply):
                call, _ = conversation(FakeBrain(reply))
                call._turn("What is the address?", call.epoch)
                call.brain.messages.clear()
                call.mouth.spoken.clear()
                call.mouth.busy = True
                call.mouth.heard = heard
                call._cut_speech()
                call.mouth.busy = False
                call._turn("Yes.", call.epoch)
                self.assertEqual(call.brain.messages, [])
                self.assertFalse(call.finished.is_set())
                self.assertEqual(" ".join(call.mouth.spoken), reply[len(heard):].strip())

    def test_partly_heard_value_is_not_counted_as_confirmed(self):
        call, _ = conversation(FakeBrain("The meeting is at forty-two Example Street. Is that right?"))
        call._turn("What is the address?", call.epoch)
        call.brain.messages.clear()
        call.mouth.spoken.clear()
        call.mouth.busy = True
        call.mouth.heard = "The meeting is at forty-two"
        call._cut_speech()
        call.mouth.busy = False
        call._turn("Yes.", call.epoch)
        self.assertEqual(call.brain.messages, [])
        self.assertEqual(" ".join(call.mouth.spoken), "Example Street. Is that right?")

    def test_playback_estimate_keeps_the_detail_when_only_closing_tag_is_cut(self):
        detail = "A table for four on Friday at eight pm."
        pieces = [[detail, 5.0, 5.0], ["Is that right?", 0.8, 2.0]]
        heard = pat.heard_text(pieces, margin=0.5)
        self.assertTrue(heard.startswith(detail))
        self.assertNotIn("right?", heard)

    def test_yes_after_heard_detail_reaches_model_without_forced_replay(self):
        for tag in ("Is that right?", "Did I get that right?", "Правильно ли я услышал?"):
            with self.subTest(tag=tag):
                detail = "A table for four on Friday at eight pm."
                call, _ = conversation(FakeBrain(f"{detail} {tag}", "Thank you. Goodbye. [END]"))
                call._turn(detail, call.epoch)
                call.brain.messages.clear()
                call.mouth.spoken.clear()
                call.mouth.busy = True
                call.mouth.heard = detail + " " + tag.rsplit(" ", 1)[0]
                call._cut_speech()
                call.mouth.busy = False
                call._turn("Yes.", call.epoch)
                self.assertEqual(len(call.brain.messages), 1)
                self.assertIn(call.mouth.heard, call.brain.messages[0])
                self.assertIn("even if only a short closing question", call.brain.messages[0])
                self.assertTrue(call.brain.messages[0].endswith("\nYes."))
                self.assertTrue(call.finished.is_set())
                self.assertEqual(call.mouth.spoken, ["Thank you.", "Goodbye."])


from test_support import setup_profile as setUpModule, teardown_profile as tearDownModule

if __name__ == "__main__":
    unittest.main()
