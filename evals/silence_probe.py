"""What real Haiku actually says when nudged after silence, or when speech had no words. Text only, no phone."""
import os
import sys
import tempfile
import threading
import types

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
import pat
from call_brief import CallBrief

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
BRIEF = CallBrief.from_dict({"goal": "Find out what time tomorrow's meeting starts and where it is.", "language": "en", "name": "Alex",
                             "confidence": "confirmed", "need_from_them": ["What time does it start?", "Where is it?"]})
OPENING = "Hello, this is Aziz's AI assistant. Could you tell me, please, is this Alex?"
NUDGE = "They have said nothing for a while, so they may not have heard you. Check briefly that they're still there, and repeat your last question."


class Mouth:
    voice = types.SimpleNamespace(clause_chars=None)
    token = 0

    def __init__(self):
        self.spoken = []

    def say(self, text, token, on_first_audio=None):
        self.spoken.append(text)

    def start_reply(self):
        pass

    def idle(self):
        return True

    def heard_so_far(self):
        return ""

    def cancel(self):
        pass

    def drain(self):
        pass


for run in range(3):
    brain = pat.Brain("en", system_prompt=BRIEF.haiku_prompt(pat.SYSTEM_PROMPTS["en"], OPENING, "Aziz", "abc123"))
    for _ in brain.ask(pat.WARM_UP["en"]):
        pass
    mouth = Mouth()
    call = pat.Conversation(types.SimpleNamespace(ended=threading.Event()), iter(()), None, mouth, brain, pat.Transcript(tempfile.mkdtemp()),
                               OPENING, nonce="abc123", language="en", task_message=BRIEF.task_message("Aziz"))
    call._turn("Yes, it is.", call.epoch)
    print(f"#{run + 1} after confirming: {' '.join(mouth.spoken)}", flush=True)
    for label, args in (("nudge", ("", call.epoch, NUDGE)), ("wordless", ("", call.epoch)), ("second nudge", ("", call.epoch, NUDGE))):
        before = len(mouth.spoken)
        call._turn(*args)
        print(f"   {label}: {' '.join(mouth.spoken[before:])}", flush=True)
    brain.close()
