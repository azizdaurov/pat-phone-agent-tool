"""The real sticky note window with a pretend phone, so nothing rings, dials or changes audio devices.
A call rings in after 4 s, and every button works. Run: .venv\\Scripts\\python.exe evals\\note_demo.py
With --screen idle|ringing|menu|ai|iphone|laptop it just holds that screen. Quit it from its tray icon, in the hidden icons."""
import argparse
import math
import os
import sys
import tempfile
import time
import types

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
import note
import note_window
from easter_eggs import EasterEggs, split_style
from private_numbers import PrivateNumbers

FOLDER = tempfile.mkdtemp()
CALLER = {"number": "+998 90 000 00 01", "name": "Alex"}
FACTS = (("Person", "Alex"), ("Location", "Los Angeles"), ("Time", "11:00"))


class PretendDesk:
    def __init__(self, screen):
        self.screen = "idle" if screen in (None, "idle") else {"menu": "ringing", "iphone": "me", "laptop": "me"}.get(screen, screen)
        self.route = "laptop" if screen == "laptop" else "iphone"
        self.me_route = "iphone"
        self.held = screen is not None
        self.always = False
        self.listening = False
        self.notice = ""
        self.changed = time.monotonic()
        self.private = PrivateNumbers(FOLDER)
        self.eggs = EasterEggs(FOLDER, FOLDER)
        self.panel = None

    def _go(self, screen):
        self.screen = screen
        self.changed = time.monotonic()

    def state(self):
        since = time.monotonic() - self.changed
        if not self.held and self.screen == "idle" and since > 4:
            self._go("ringing")
        known = 2 if self.held else min(3, 1 + int(since / 5))
        talking = self.held or int(since) % 4 != 3
        if not self.held and self.screen == "ai" and since > 18:
            self.screen = "done"
        # Syllables and pauses, like speech.
        level = max(0.0, 0.55 + 0.45 * math.sin(since * 11) * math.sin(since * 2.3)) if talking and (self.screen == "ai" or self.route == "laptop") else 0
        if self.screen == "done":
            return {"screen": "done", **CALLER, "level": 0, "notice": "", "route": self.route, "me_route": self.me_route,
                    "facts": [{"label": label, "value": value} for label, value in FACTS],
                    "summary": "Alex confirmed tomorrow's meeting at 11:00 at the Los Angeles office, and asked Aziz to come ten minutes early and bring a printed copy of the contract.",
                    "next_step": "Bring the contract. Reply to Alex by Friday if anything changes."}
        return {"screen": self.screen, **CALLER, "level": round(level, 2), "route": self.route, "me_route": self.me_route, "always": self.always, "notice": self.notice, "listening": self.listening,
                "talking": talking and (self.screen == "ai" or self.route == "laptop"), "summary": "Confirming the meeting" if self.screen == "ai" else "",
                "facts": [{"label": label, "value": value if i < known else None} for i, (label, value) in enumerate(FACTS)] if self.screen == "ai" else []}

    def answer_ai(self, always=False):
        self.always = always
        self._go("ai")

    def dismiss(self):
        self.held = False
        self._go("idle")

    def choose_route(self, route):
        self.me_route = route

    def answer_me(self, route="iphone"):
        self.route = route
        self._go("me")

    def set_route(self, route):
        self.route = route

    def listen(self, on):
        self.listening = on

    def take_over(self):
        self.route = "laptop"
        self.listening = False
        self._go("me")

    def end_call(self):
        self.always = False
        self._go("idle")

    def submit(self, text):
        text, _ = split_style(text)
        self.panel = self.eggs.respond(text, self.private)
        if not self.panel:
            self.answer_ai()

    def press(self, button):
        self.panel, target = self.eggs.press(button)
        if target:
            self.answer_ai()

    def show_stats(self):
        self.panel = self.eggs.stats_panel()

    def show_facts(self):
        self.panel = self.eggs.found_panel()


parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument("--screen", choices=["idle", "ringing", "menu", "ai", "iphone", "laptop", "done"])
parser.add_argument("--seconds", type=float, help="close by itself after this long")
args = parser.parse_args()


def on_start(window, tray):
    if args.screen == "menu":
        note_window.QTimer.singleShot(2500, lambda: window.page().runJavaScript("document.getElementById('arrow').click()"))
    if args.seconds:
        note_window.QTimer.singleShot(int(args.seconds * 1000), note_window.QApplication.instance().quit)


# Its settings and contacts are thrown away with it, so the real ones stay as they are.
folder = FOLDER
note_window.show(PretendDesk(args.screen), on_start, options=types.SimpleNamespace(
    settings=note.NoteSettings(folder), rules=note.CallRules(os.path.join(folder, "rules.json")), private=PrivateNumbers(folder), eggs=EasterEggs(FOLDER, FOLDER)))
