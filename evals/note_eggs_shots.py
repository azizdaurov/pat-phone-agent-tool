"""Pictures of the real sticky note page showing each easter egg, with no window on screen, no phone and no Claude.
Usage: note_eggs_shots.py <folder for the pictures>"""
import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
import note_window
from easter_eggs import FACTS, EasterEggs
from private_numbers import PrivateNumbers
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

out = sys.argv[1]
os.makedirs(out, exist_ok=True)
folder = tempfile.mkdtemp()
private = PrivateNumbers(folder)
private.add_contact("Mom", "+998900000001")
eggs = EasterEggs(folder, folder)
AFTER = dict(screen="done", name="Dentist", number="", facts=[{"label": "Time", "value": "11:00"}, {"label": "Place", "value": "Main Street clinic"}], summary="They open at 11:00.", next_step="")
SONNET = "\n".join(f"Line {n} of a very dramatic sonnet about the dentist" for n in range(1, 15))
SHOTS = [
    ("mom-joke", dict(screen="idle", panel=eggs.respond("Mom", private))),
    ("good-kid", dict(screen="idle", panel=eggs.press("fine")[0])),
    ("jenny", dict(screen="idle", panel=eggs.respond("867-5309", private))),
    ("stats", dict(screen="idle", panel=eggs.stats_panel() | {"rows": [["Calls Pat took for you", "41"], ["Time on the phone", "1 h 38 min"], ["Longest call", "12 min"], ["Times they hung up on Pat", "3"], ["Badges", "Good Kid"]], "lines": ["You have avoided 41 awkward conversations."]})),
    ("predict", dict(screen="idle", panel=eggs.respond("predict Call today or Call tomorrow", private))),
    ("pat-pat", dict(screen="idle", panel=eggs.respond("pat pat", private))),
    ("poem-writing", dict(AFTER, poem_pending=True, poem_style="haiku")),
    ("haiku", dict(AFTER, poem="Eleven o'clock,\nLos Angeles waits for you.\nBring a suit, my friend.", poem_style="haiku")),
    ("sonnet-scrolls", dict(AFTER, poem=SONNET, poem_style="sonnet")),
    ("flair", dict(AFTER, flair=[{"text": "Happy birthday, telephone! First call: 1876."}], pat_facts=["Pat fact #9: A new contact has appeared: Octo. It can't call anyone. Pat doesn't talk about it."])),
    ("calling-octo", dict(screen="idle", panel=dict(eggs.respond("555-0108", private), delay=60))),
    ("mom", dict(screen="idle", panel={"lines": ["Mom?"], "buttons": [{"id": "ok", "label": "OK"}], "attempt": 1})),
    ("found", dict(screen="idle", panel=eggs.found_panel() | {"lines": [f"#{n}: {t}" for n, t in sorted(FACTS.items())][:14]})),
]


class Desk:
    current = {"screen": "idle"}

    def state(self):
        return {"notice": "", "level": 0, "route": "iphone", "me_route": "iphone", "always": False, "talking": False, "listening": False, **self.current}


app = QApplication([])
desk = Desk()
window = note_window.NoteWindow(desk)
window.show()
queue = list(SHOTS)


def next_shot():
    if not queue:
        app.quit()
        return
    name, state = queue.pop(0)
    desk.current = state
    QTimer.singleShot(900, lambda: save(name))


def save(name):
    window.grab().save(os.path.join(out, f"{name}.png"))
    print(name, window.width(), window.height(), flush=True)
    next_shot()


QTimer.singleShot(2500, next_shot)
QTimer.singleShot(60000, app.quit)
app.exec()
