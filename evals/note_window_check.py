"""Checks the real window with a pretend phone: a bright window behind it to prove it's see-through, and real mouse input for
every button and for hovering. The pointer moves by itself for about half a minute, so leave the mouse alone.
Pictures go to the folder given. Run: .venv\\Scripts\\python.exe evals\\note_window_check.py <folder for pictures>"""
import ctypes
import ctypes.wintypes
import json
import tempfile
import time
import types
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.argv, FOLDER = [sys.argv[0]], sys.argv[1]
os.environ["PAT_NOTE_COPY"] = "PatNoteCheck"  # so this can run beside a real note
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.join(FOLDER, "shotlibs"))
from PIL import ImageGrab
from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QApplication, QWidget

import note
import note_window
from private_numbers import PrivateNumbers

user32 = ctypes.windll.user32
results = []


class Desk:
    def __init__(self):
        self.screen = "idle"
        self.route = "iphone"
        self.calls = []
        self.level = 0

    def state(self):
        facts = [{"label": "Person", "value": "Alex"}, {"label": "Time", "value": None}] if self.screen == "ai" else []
        if self.screen == "done":
            return {"screen": "done", "number": "+998 90 000 00 01", "name": "Alex", "level": 0, "notice": "", "route": "iphone",
                    "facts": [{"label": "Time and place", "value": "11:00 AM, the Los Angeles office, fifth floor, room 12, ask for the front desk"}],
                    "summary": LONG_SUMMARY, "next_step": "Bring a suit, and reply to Alex by Friday if anything changes."}
        return {"screen": self.screen, "level": self.level, "number": "+998 90 000 00 01", "name": "Alex", "route": self.route, "always": False, "notice": "",
                "listening": False, "talking": self.screen == "ai", "summary": "Confirming the meeting" if self.screen == "ai" else "", "facts": facts}

    def answer_ai(self, always=False):
        self.calls.append("always" if always else "once")
        self.screen = "ai"

    def dismiss(self):
        self.calls.append("dismiss")
        self.screen = "idle"

    def choose_route(self, route):
        self.calls.append(f"choose {route}")

    def answer_me(self, route="iphone"):
        self.calls.append(f"me {route}")
        self.route = route
        self.screen = "me"

    def set_route(self, route):
        self.calls.append(f"route {route}")
        self.route = route

    def listen(self, on):
        self.calls.append(f"listen {on}")

    def take_over(self):
        self.calls.append("take over")
        self.screen = "me"

    def end_call(self):
        self.calls.append("end")
        self.screen = "idle"

    def submit(self, text):
        self.calls.append(f"submit {text}")


desk = Desk()
LONG_SUMMARY = "Alex confirmed tomorrow's meeting at 11:00 AM in Los Angeles, and asked Aziz to come ten minutes early, bring a suit and a printed copy of the contract, and to reply by Friday if the plan changes."


def check(name, passed, detail=""):
    results.append(passed)
    print(("PASS " if passed else "FAIL ") + name + (f"  {detail}" if detail else ""), flush=True)


class Steps:
    def __init__(self, window, back):
        self.window = window
        self.back = back
        self.ratio = window.devicePixelRatioF()
        pointer = ctypes.wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(pointer))
        self.pointer_was = (pointer.x, pointer.y)
        self.steps = iter(self.script())
        self.gaps = []
        self.last_tick = time.perf_counter()
        self.ticker = QTimer(interval=10)
        self.ticker.timeout.connect(self.tick)
        self.ticker.start()

    def tick(self):
        now = time.perf_counter()
        self.gaps.append((now - self.last_tick) * 1000)
        self.last_tick = now

    def real(self, x, y):
        return int(x * self.ratio), int(y * self.ratio)

    def point_at(self, x, y):
        user32.SetCursorPos(*self.real(x, y))

    def press(self):
        user32.mouse_event(2, 0, 0, 0, 0)
        user32.mouse_event(4, 0, 0, 0, 0)

    def box(self):
        geometry = self.window.frameGeometry()
        return (*self.real(geometry.left(), geometry.top()), *self.real(geometry.right() + 1, geometry.bottom() + 1))

    def picture(self, name):
        shot = ImageGrab.grab(bbox=self.box(), all_screens=True)
        shot.save(os.path.join(FOLDER, f"check-{name}.png"))
        return shot

    def run(self):
        try:
            wait = next(self.steps)
        except StopIteration:
            user32.SetCursorPos(*self.pointer_was)
            print(f"{sum(results)} of {len(results)} passed", flush=True)
            QApplication.instance().quit()
            return
        QTimer.singleShot(int(wait * 1000), self.run)

    def read_bars(self, name):
        self.bars = getattr(self, "bars", {})
        self.window.page().runJavaScript("JSON.stringify(Array.from(document.getElementById('mixer').children).map(b => b.getBoundingClientRect().height))", 0,
                                         lambda text: self.bars.__setitem__(name, json.loads(text)))

    def click(self, element):
        """Finds the element on the page and really clicks it."""
        self.window.page().runJavaScript(f"(function(){{const r=document.getElementById('{element}').getBoundingClientRect();return JSON.stringify([r.left+r.width/2,r.top+r.height/2])}})()", 0, self._click_at)

    def _click_at(self, text):
        place = json.loads(text)
        self.point_at(self.window.x() + place[0], self.window.y() + place[1])
        QTimer.singleShot(350, self.press)

    def tray_action(self, title):
        return next(action for action in self.tray.contextMenu().actions() if action.text() == title)

    def script(self):
        window = self.window
        area = window.screen().availableGeometry()
        yield 3
        width = window.width()
        right_edge = window.x() + window.width() if not window.is_hidden_at_edge else None
        self.tray_action("Zoom in").trigger()
        yield 1
        zoomed = window.width()
        check("Zoom in makes the window bigger", zoomed > width, f"{width} -> {zoomed}")
        check("zoomed, it's still fully on screen", window.x() + zoomed <= area.right() + 1, f"right edge {window.x() + zoomed}, screen {area.right() + 1}")
        check("Zoom is remembered", window.options.settings.zoom > 1.0, str(window.options.settings.zoom))
        desk.screen = "ai"
        yield 1
        self.picture("zoomed")
        self.tray_action("Zoom out").trigger()
        yield 0.5
        check("Zoom out brings it back", window.width() == width, f"{window.width()} vs {width}")
        check("zoomed out, it's still fully on screen", window.x() + window.width() <= area.right() + 1, f"right edge {window.x() + window.width()}")
        desk.screen = "idle"

        voices = window.submenus["English voice"].actions()
        check("every English voice is offered, with the default ticked", len(voices) == 6 and [a.data() for a in voices if a.isChecked()] == ["charles"], str([a.text() for a in voices]))
        next(a for a in voices if a.data() == "anna").trigger()
        check("choosing a voice saves it", window.options.settings.voice_for("en") == "anna" and [a.data() for a in voices if a.isChecked()] == ["anna"])
        russian = window.submenus["Russian voice"].actions()
        next(a for a in russian if a.data() == "ruslan").trigger()
        check("choosing a Russian voice saves it", window.options.settings.voice_for("ru") == "ruslan")

        contacts = window.contacts
        self.tray_action("Contacts...").trigger()
        yield 2
        check("Contacts opens its own window", contacts.isVisible())
        results_box = {}
        contacts.page().runJavaScript("""
          document.getElementById('name').value='Рустам'; document.getElementById('number').value='+998 90 000 00 05';
          document.getElementById('add').click();""")
        yield 0.6
        contacts.page().runJavaScript("""
          document.getElementById('name').value='Alex'; document.getElementById('number').value='+998 90 000 00 06';
          document.getElementById('add').click();""")
        yield 0.6
        check("Add puts a contact in the list", set(window.options.private.contacts()) == {"Рустам", "Alex"}, str(window.options.private.contacts()))
        contacts.page().runJavaScript("""document.querySelector('li[data-name="Alex"] button[data-rule="ai"]').click();""")
        yield 0.5
        contacts.page().runJavaScript("""document.querySelector('li[data-name="Рустам"] button[data-rule="me"]').click();""")
        yield 0.6
        check("each contact's choice is saved", window.options.rules.rule("+998900000006") == "ai" and window.options.rules.rule("+998900000005") == "me", str(window.options.rules.rules))
        geometry = contacts.frameGeometry()
        ImageGrab.grab(bbox=(*self.real(geometry.left(), geometry.top()), *self.real(geometry.right() + 1, geometry.bottom() + 1)), all_screens=True).save(os.path.join(FOLDER, "check-contacts.png"))
        contacts.page().runJavaScript("""document.getElementById('name').value='Short'; document.getElementById('number').value='112'; document.getElementById('add').click();""")
        yield 0.6
        contacts.page().runJavaScript("document.getElementById('problem').textContent", 0, lambda text: results_box.update(problem=text))
        yield 0.3
        check("a bad number is explained", "country code" in results_box.get("problem", ""), results_box.get("problem", ""))
        contacts.page().runJavaScript("""document.querySelector('li[data-name="Alex"] .remove').click();""")
        yield 0.6
        check("Remove takes them out", set(window.options.private.contacts()) == {"Рустам"} and window.options.rules.rule("+998900000006") is None)
        contacts.close()
        yield 0.5
        check("closing Contacts leaves the note running", window.isVisible() and not contacts.isVisible())
        away = (area.left() + 200, area.top() + area.height() // 2)
        self.point_at(*away)
        yield 4
        hidden_at = note_window.hidden_left("right", window.width(), area.left(), area.width())
        check("no call: slides to the right edge by itself", window.x() == hidden_at, f"x={window.x()} expected {hidden_at}")
        self.point_at(area.right() - 3, window.y() + 25)
        yield 1
        check("hovering the sliver brings it back", not window.is_hidden_at_edge and window.x() + window.width() <= area.right() + 1, f"x={window.x()}")
        yield 0.8
        check("it stays out long enough to reach it, though the pointer is left at the edge", not window.is_hidden_at_edge, f"x={window.x()}")
        self.back.raise_()  # other windows may have come over it; the note, being always on top, stays above it
        yield 0.2
        shot = self.picture("idle")
        width, height = shot.size
        check("see-through outside the note", shot.getpixel((1, 1))[:3] == (255, 0, 255) and shot.getpixel((width - 2, 1))[:3] == (255, 0, 255), str(shot.getpixel((1, 1))))
        corner = shot.getpixel((int(14 * self.ratio), int(10 * self.ratio)))
        check("note's corner isn't black", sum(corner[:3]) > 300, str(corner))
        self.point_at(window.x() + 100, window.y() + 25)
        yield 0.3
        self.point_at(*away)
        yield 1.6
        check("leaving hides it again", window.is_hidden_at_edge)

        self.point_at(area.right() - 3, window.y() + 25)
        yield 1
        before = window.pos()
        self.point_at(window.x() + 16, window.y() + 34)  # the straight part of the left edge: a rounded corner lets a click through
        yield 0.4
        user32.mouse_event(2, 0, 0, 0, 0)
        yield 0.2
        for _ in range(20):
            user32.mouse_event(1, -int(10 * self.ratio), int(3 * self.ratio), 0, 0)
            yield 0.02
        yield 0.2
        moved = before.x() - window.x()
        check("dragging moves it", 150 < moved < 250, f"moved {moved}")
        user32.mouse_event(4, 0, 0, 0, 0)
        yield 0.3
        check("it stays where it was dropped, under the pointer", not window.is_hidden_at_edge)
        dropped = window.pos()
        self.point_at(*away)
        yield 1.6
        check("after a drag it still hides", window.is_hidden_at_edge)
        desk.screen = "ringing"
        yield 1
        check("a ringing call brings it out by itself", not window.is_hidden_at_edge)
        check("back where it was dropped", window.pos() == dropped, f"{window.pos().toTuple()} vs {dropped.toTuple()}")
        check("after a drag the window still fits the bigger screen", window.height() > 150, f"height {window.height()}")
        self.picture("ringing-after-drag")
        self.point_at(*away)
        yield 1.6
        check("a ringing call doesn't hide when the pointer leaves", not window.is_hidden_at_edge)
        self.picture("ringing")
        self.click("arrow")
        yield 1
        shot = self.picture("menu")
        check("arrow opens the list, on top of the window", window.height() > 200, f"window height {window.height()}")
        self.click("once")
        yield 1
        check("AI once is clickable", desk.calls[-1:] == ["once"], str(desk.calls))
        self.picture("ai")
        self.click("listen")
        yield 0.7
        check("Listen is clickable", desk.calls[-1:] == ["listen True"], str(desk.calls))
        desk.level = 0
        yield 1.5
        self.read_bars("silent")
        desk.level = 0.3
        yield 1.2
        self.read_bars("quiet")
        desk.level = 1.0
        yield 1.2
        self.read_bars("loud")
        yield 0.05
        self.read_bars("loud, a moment later")
        yield 0.1
        desk.level = 0
        yield 1.5
        self.read_bars("silent again")
        yield 0.3
        bars = self.bars
        check("mixer is flat in silence", max(bars["silent"]) <= 7, str(max(bars["silent"])))
        check("mixer rises with the sound", max(bars["silent"]) < max(bars["quiet"]) < max(bars["loud"]), f"{max(bars['silent'])} < {max(bars['quiet'])} < {max(bars['loud'])}")
        loud, later = bars["loud"], bars["loud, a moment later"]
        steps = [abs(a - b) for a, b in zip(loud, loud[1:])]
        check("mixer is a smooth wave: neighbouring bars are close", max(steps) <= 5, f"biggest step {max(steps):.1f} px")
        check("the wave has a shape, not one height", max(loud) - min(loud) > 8, f"{min(loud):.0f} to {max(loud):.0f} px")
        changes = [abs(a - b) for a, b in zip(loud, later)]
        check("mixer doesn't jump between moments", max(changes) <= 8, f"biggest change {max(changes):.1f} px")
        check("mixer settles when the sound stops", max(bars["silent again"]) <= 7, str(max(bars["silent again"])))
        self.point_at(*away)
        yield 1.6
        check("a call doesn't hide until asked", not window.is_hidden_at_edge)
        self.click("edge")
        self.gaps.clear()
        yield 1.5
        check("the arrow slides it to the nearest edge", window.is_hidden_at_edge and window.x() == hidden_at, f"x={window.x()}")
        self.point_at(area.right() - 3, window.y() + 60)
        yield 1.5
        print(f"   slowest moment for the window during this: {max(self.gaps or [0]):.0f} ms", flush=True)
        check("hovering brings the call back", not window.is_hidden_at_edge, f"x={window.x()} y={window.y()} h={window.height()} pointer={note_window.QCursor.pos().toTuple()} left_for={window.pointer_left_for} slide={window.slide.state()}")
        yield 0.5
        self.click("take-over")
        yield 1
        check("Take over is clickable", desk.calls[-1:] == ["take over"], str(desk.calls))
        self.point_at(*away)
        yield 1.6
        check("after Take over it stays out, though it was hidden before", not window.is_hidden_at_edge, f"x={window.x()}")
        self.picture("me")
        self.click("minimize")
        yield 1
        check("the dash minimizes to the taskbar", window.isMinimized())
        window.bring_back()
        yield 1
        check("comes back from the taskbar", not window.isMinimized())
        self.click("close")
        yield 1
        check("the cross hides it and it keeps running", not window.isVisible() and QApplication.instance() is not None)
        desk.screen = "ringing"
        yield 1
        check("a ring brings it back from the hidden icons", window.isVisible() and not window.isMinimized())
        self.click("always")
        yield 1
        check("Always AI is clickable", desk.calls[-1:] == ["always"], str(desk.calls))

        desk.screen = "idle"
        self.point_at(*away)
        yield 1.6
        check("hidden again before the call ends", window.is_hidden_at_edge)
        desk.screen = "done"
        yield 1
        check("the end of a call brings it out", not window.is_hidden_at_edge)
        self.point_at(*away)
        yield 2
        check("the summary doesn't slide away", not window.is_hidden_at_edge)
        self.picture("done")
        inside = {}
        window.page().runJavaScript("JSON.stringify({text:document.getElementById('done-summary').textContent,bottom:document.getElementById('done').getBoundingClientRect().bottom,height:innerHeight})", 0, lambda text: inside.update(json.loads(text)))
        yield 0.3
        check("the whole summary is there", inside.get("text") == LONG_SUMMARY)
        check("the window is tall enough for all of it", inside.get("bottom", 9999) <= inside.get("height", 0), str(inside))
        self.click("done")
        yield 1
        check("Done is clickable and it goes back to the bar", desk.calls[-1:] == ["dismiss"], str(desk.calls))
        self.point_at(*away)
        yield 1.6
        window.move(area.left() + 100, window.y())
        window.is_hidden_at_edge = False
        window.left_when_open = None
        self.point_at(area.left() + 150, window.y() + 25)
        yield 0.5
        self.point_at(area.left() + 800, window.y() + 25)  # well clear of where it now sits
        yield 1.6
        check("near the left it hides to the left", window.is_hidden_at_edge and window.x() < area.left(), f"x={window.x()}")
        shot = self.picture("left")
        check("left sliver is on screen", window.x() + window.width() > area.left())


def menu_titles(menu):
    return [action.text() for action in menu.actions() if action.text()]


def start(window, tray):
    window.options = options
    titles = menu_titles(tray.contextMenu())
    check("tray menu has every option", all(item in titles for item in ("Show", "Zoom in", "Zoom out", "Incoming calls speak", "Unknown numbers", "English voice", "Russian voice", "Contacts...", "Quit")), str(titles))
    check("tray icon is showing", tray.isVisible() and note_window.QSystemTrayIcon.isSystemTrayAvailable())
    back = QWidget()
    back.setWindowFlags(Qt.FramelessWindowHint)
    back.setStyleSheet("background:#FF00FF")
    area = window.screen().availableGeometry()
    back.setGeometry(area.right() - 500, area.top(), 500, 620)
    back.show()
    window.move(window.x(), area.top() + 300)  # clear of a real note, which sits at the top
    window.raise_()
    window.check_back = back
    window.steps = Steps(window, back)
    window.steps.tray = tray
    QTimer.singleShot(1000, window.steps.run)


folder = tempfile.mkdtemp()
options = types.SimpleNamespace(settings=note.NoteSettings(folder), rules=note.CallRules(os.path.join(folder, "rules.json")), private=PrivateNumbers(folder))
note_window.show(desk, start, options=options)
