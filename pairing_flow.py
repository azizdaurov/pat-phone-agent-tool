"""The note's "Set up the phone for Pat's calls" steps, shown inside the note under its message.

It drives `iphonecall pair --json` (phone_pairing.py) and turns each step into one small screen for the note page: a
title, a line of text, maybe a code or a drop-down, and buttons. While it runs, the note's own phone line steps aside, so
two programs never reach for the phone at once. When it's done, the new pairing becomes the phone Pat uses.

A screen is a dict: title, text, status, code, choose ({options: [{label, value}], value, placeholder}) and actions
([{label, answer, tone}]). An action's answer is what the helper gets; "chosen" means the drop-down's value, and
"close" ends the steps.
"""
import threading

from phone_pairing import PairingRun
from user_profile import UserProfile

TITLE = "Set up the phone for Pat's calls"
NOT_HERE = "My phone isn't here"
CLOSE = {"label": "Close", "answer": "close", "tone": "primary"}
CANCEL = {"label": "Cancel", "answer": "close", "tone": "quiet"}


def save_phone(name, device_id, profile=None):
    """The new pairing becomes the phone Pat uses, so the note doesn't go looking for the old one."""
    profile = profile or UserProfile()
    try:
        profile.save(phone_device=device_id, phone_name=name)
        return True
    except (OSError, ValueError):
        return False


OPEN_BLUETOOTH = "On your phone, open Settings > Bluetooth and keep that screen open."
PAIR_THERE = "Keep Settings > Bluetooth open on your phone: the Pair request appears there."


def screen(title, text="", **parts):
    """hint is the one thing to do on the phone, shown boxed so it stands out."""
    return {"title": title, "text": text, "hint": parts.get("hint", ""), "status": parts.get("status", ""),
            "code": parts.get("code", ""), "choose": parts.get("choose"), "actions": parts.get("actions", [])}


class PairingFlow:
    """One set-up, from the button to Done. start() runs off the window's thread; the page calls answer()."""

    def __init__(self, pause=None, resume=None, run_factory=PairingRun, save=save_phone):
        self.pause = pause
        self.resume = resume
        self.run_factory = run_factory
        self.save = save
        self.lock = threading.Lock()
        self.run = None
        self.closed = False
        self.found = []
        self.slow = False
        self.current = screen(TITLE, "Getting your phones…", actions=[CANCEL])

    @property
    def active(self):
        return not self.closed

    def screen(self):
        with self.lock:
            return None if self.closed else self.current

    def start(self):
        if self.pause:
            self.pause()  # the note's line lets go of the phone first; that can take a few seconds
        with self.lock:
            if self.closed:  # closed while the note was letting go
                return
            try:
                self.run = self.run_factory(self.on_event)
            except OSError as error:
                self.current = screen("That didn't work", f"Pat's phone helper won't start, so run setup.ps1: {error}", actions=[CLOSE])

    def answer(self, answer, chosen=""):
        """A button on the page. "close" ends the steps; "chosen" sends the drop-down's value."""
        if answer == "close":
            self.close()
            return
        text = chosen if answer == "chosen" else answer
        with self.lock:
            run = self.run
            waiting = {"y": "Pairing…", "n": "Trying again…", "": "Trying again…"}.get(text, "One moment…")
            self.current = screen(self.current["title"], waiting, hint=PAIR_THERE if self.found else "", actions=[CANCEL])
        if run:
            run.answer(text)

    def close(self):
        """At any point: the helper stops first, then the note takes the phone line back."""
        with self.lock:
            if self.closed:
                return
            self.closed = True
            run = self.run

        def let_go():
            if run:
                run.stop()
            if self.resume:
                self.resume()

        threading.Thread(target=let_go, daemon=True).start()

    def on_event(self, event):
        """What the helper says, from its reader thread."""
        kind, text = event.get("event"), event.get("text", "")
        with self.lock:
            if self.closed:
                return
            new = self._screen_for(kind, text, event)
            if new == "close":
                pass
            elif new is not None:
                self.current = new
        if new == "close":
            self.close()

    def _screen_for(self, kind, text, event):
        if kind == "phones":
            phones = event.get("phones", [])
            options = [{"label": f"{p.get('name', 'Phone')} · {'connected' if p.get('connected') else 'not connected'}",
                        "value": str(number)} for number, p in enumerate(phones, start=1)]
            options.append({"label": NOT_HERE, "value": "0"})
            first = next((str(n) for n, p in enumerate(phones, start=1) if p.get("connected")), "1" if phones else "0")
            return screen("Which is your phone?", "Pat makes a fresh pairing with it, so no other app can hold its calls.",
                          choose={"options": options, "value": first},
                          actions=[CANCEL, {"label": "Continue", "answer": "chosen", "tone": "primary"}])
        if kind == "same_name":
            options = [{"label": f"{p.get('name', 'Phone')} · {'connected now' if p.get('connected') else 'not connected'}",
                        "value": str(number)} for number, p in enumerate(event.get("phones", []), start=1)]
            return screen("Which one is yours?", "Several paired phones have this name.",
                          choose={"options": options, "value": "1"},
                          actions=[CANCEL, {"label": "Continue", "answer": "chosen", "tone": "primary"}])
        if kind in ("searching", "found", "not_found_yet"):
            if kind == "searching":
                self.found, self.slow = [], False
            if kind == "found":
                self.found.append({"label": event.get("name", "Phone"), "value": str(event.get("number"))})
            if kind == "not_found_yet":
                self.slow = True
            status = ("Still looking. Choose your phone when it's there." if self.found else
                      "Can't find it? Check that Bluetooth is on and that screen is open. Still looking…" if self.slow else "Looking…")
            return screen("Find your phone", "", hint=OPEN_BLUETOOTH, status=status,
                          choose={"options": list(self.found), "value": self.found[0]["value"] if self.found else "",
                                  "placeholder": "Phones appear here as they're found"},
                          actions=[CANCEL, {"label": "Pair", "answer": "chosen", "tone": "primary"}])
        if kind == "pairing":
            return screen("Pairing", f"Asking {event.get('name', 'your phone')}…", hint=PAIR_THERE, actions=[CANCEL])
        if kind == "code":
            return screen("Check the code", "Your phone should show this code too. Tap Pair there, then confirm here.",
                          code=str(event.get("code", "")), hint=PAIR_THERE,
                          actions=[{"label": "No code, or a different one", "answer": "n", "tone": "quiet"},
                                   {"label": "Codes match", "answer": "y", "tone": "primary"}])
        if kind == "type_code":
            return screen("Type this code on your phone", code=str(event.get("code", "")), actions=[CANCEL])
        if kind == "retrying":
            return screen("Pairing", "The phone may have tried an old pairing first. Trying again…", hint=PAIR_THERE, actions=[CANCEL])
        if kind == "refused":
            laptop = event.get("laptop", "this laptop")
            return screen("One step on the phone", "The phone still remembers an old pairing.",
                          hint=f"On your phone, open Settings > Bluetooth, tap ⓘ next to {laptop}, then Forget This Device. "
                               "Keep that screen open.",
                          actions=[CANCEL, {"label": "Try again", "answer": "", "tone": "primary"}])
        if kind == "connecting":
            return screen("Connecting", text or "Connecting Pat to the phone…", hint=PAIR_THERE if "isn't ready" in text else "")
        if kind == "done":
            self.save(event.get("name", ""), event.get("id", ""))
            return screen("Done", text, actions=[CLOSE])
        if kind in ("failed", "unsupported"):
            return screen("That didn't work", text, actions=[CLOSE])
        if kind == "stopped":
            return "close"
        if kind == "closed" and self.current.get("title") not in ("Done", "That didn't work"):
            return screen("That didn't work", "Pat's phone helper stopped before the phone was set up.", actions=[CLOSE])
        return None
