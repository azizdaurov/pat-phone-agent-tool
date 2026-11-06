"""The sticky note's window: truly see-through, always on top, slides to a screen edge, and lives in the tray.
What it shows and does comes from a desk (see note.py); what it looks like is in note/index.html."""
import ctypes
import json
import os
import threading

from call_brief import ENGLISH_VOICES
from phone_memory import number_key
from phone_numbers import unambiguous_legacy_keys
from PySide6.QtCore import QEasingCurve, QObject, QPoint, QPropertyAnimation, QSize, Qt, QTimer, QUrl, Slot
from PySide6.QtGui import QAction, QActionGroup, QColor, QCursor, QIcon
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

HERE = os.path.dirname(os.path.abspath(__file__))
ICON_SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)
ICON_AGAIN_MS = 2000
NOTE_WIDTH = 304
SIDE_ROOM = 12  # see-through room for the note's shadow; must match the page's body padding
TOP_ROOM = 8
BOTTOM_ROOM = 22
WIDTH = NOTE_WIDTH + 2 * SIDE_ROOM
START_HEIGHT = 84
SHOWN_WHEN_HIDDEN = 14  # how much of the note stays on screen at the edge
SCREEN_MARGIN = 8
SLIDE_MS = 220
STATE_MS = 50  # often enough for the mixer to follow speech
HOVER_MS = 100
LEAVE_MS = 700  # the pointer can stray this long before the note slides away
HOVER_GRACE_MS = 2000
DRAG_MS = 10
LEFT_BUTTON = 0x01
ZOOMS = (0.8, 0.9, 1.0, 1.1, 1.25, 1.5, 1.75, 2.0)
LANGUAGES = (("English", "en"), ("Russian", "ru"))
FOR_UNKNOWN = (("Show the note's options", "ask"), ("Always AI", "ai"), ("Always me", "me"))
RUSSIAN_VOICES = (("Irina (female)", "irina"), ("Ruslan (male)", "ruslan"))
CONTACTS_SIZE = (484, 530)  # 460 × 500 paper, plus room for its shadow
SHOWN_ON_REQUEST_MS = 3000  # asked for by hand, the prompt bar stays out this long before it can slide away
COPY_NAME = os.environ.get("PAT_NOTE_COPY", "PatNote")  # tests set their own, so they can run beside a real note
_copy_mutex = None


def claim_single_copy():
    """True if this is the only copy running. If one is already open, asks it to show itself and returns False.
    Windows releases the mutex when this process exits, however it exits."""
    global _copy_mutex
    if _copy_mutex is not None:
        return True
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    handle = kernel32.CreateMutexW(None, False, f"Local\\{COPY_NAME}")
    error = ctypes.get_last_error()
    if error == 183:  # ERROR_ALREADY_EXISTS
        QApplication.instance() or QApplication([])
        socket = QLocalSocket()
        socket.connectToServer(COPY_NAME)
        socket.waitForConnected(1000)
        return False
    if not handle and error == 5:  # ERROR_ACCESS_DENIED: a copy started as administrator owns it, and can't be asked to show itself
        QApplication.instance() or QApplication([])
        tell_about_admin_copy()
        return False
    _copy_mutex = handle
    return True


def tell_about_admin_copy():
    """Two notes would both hold the phone, and one of them would say it isn't connected."""
    from PySide6.QtWidgets import QMessageBox
    QMessageBox.information(None, "Pat is already open",
                            "Pat is already running as administrator, probably opened by setup. Right-click its icon "
                            "in the hidden icons and choose Quit, then open Pat again normally.")


def nearest_side(window_left, window_width, screen_left, screen_width):
    """"left" or "right", whichever edge the window's middle is nearer to. Right if it's exactly in the middle."""
    middle = window_left + window_width / 2
    return "left" if middle - screen_left < screen_left + screen_width - middle else "right"


def hidden_left(side, width, screen_left, screen_width, zoom=1.0):
    """Where the window's left goes so only a sliver of the note shows at that edge."""
    room = int(SIDE_ROOM * zoom)
    if side == "left":
        return screen_left - width + room + SHOWN_WHEN_HIDDEN
    return screen_left + screen_width - room - SHOWN_WHEN_HIDDEN


def english_voices():
    return [(f"{name.replace('_', ' ').title()} ({voice['sounds']})", name) for name, voice in ENGLISH_VOICES.items()]


def next_zoom(zoom, step):
    """The next zoom up (step 1) or down (step -1), staying in range."""
    nearest = min(range(len(ZOOMS)), key=lambda i: abs(ZOOMS[i] - zoom))
    return ZOOMS[max(0, min(len(ZOOMS) - 1, nearest + step))]


def contact_rows(private, rules, eggs=None):
    """Everyone the contact list shows: contacts, then numbers with a rule but no name, such as from Always AI on a ringing call."""
    book = private.contacts()
    rows = [{"name": name, "number": number, "rule": rules.rule(number) or "ask", "named": True}
            for name, number in sorted(book.items(), key=lambda item: item[0].casefold())]
    named = {number_key(number) for number in book.values()}
    rows += [{"name": "No name", "number": "+" + key, "rule": rule, "named": False} for key, rule in rules.rules.items() if key not in named]
    octo = eggs.octo_contact() if eggs else None
    return rows + [octo] if octo else rows


def open_left(side, width, screen_left, screen_width):
    """The default place for the open note, at that edge."""
    if side == "left":
        return screen_left + SCREEN_MARGIN
    return screen_left + screen_width - width - SCREEN_MARGIN


def should_hide(screen, asked_to_hide, typing):
    """A ringing call always stays out. The prompt bar hides by itself unless it's being typed in. Calls hide only if asked."""
    if screen == "ringing":
        return False
    if screen == "idle":
        return not typing
    return asked_to_hide


def tray_icon():
    """The plain P up to 64 pixels, where the pencil drawing would turn to a smudge, and the drawing above that."""
    icon = QIcon()
    for size in ICON_SIZES:
        icon.addFile(os.path.join(HERE, "note", "icons", f"pat-{size}.png"), QSize(size, size))
    return icon


class Bridge(QObject):
    """What the page can call. Anything that may wait on the phone runs off the window's thread."""

    def __init__(self, window):
        super().__init__()
        self.window = window

    def _soon(self, name, *args):
        threading.Thread(target=lambda: getattr(self.window.desk, name)(*args), daemon=True).start()

    @Slot(bool)
    def answer_ai(self, always):
        self._soon("answer_ai", always)

    @Slot(str)
    def answer_me(self, route):
        self._soon("answer_me", route)

    @Slot(str)
    def set_route(self, route):
        self._soon("set_route", route)

    @Slot(bool)
    def listen(self, on):
        self._soon("listen", on)

    @Slot()
    def dismiss(self):
        self.window.desk.dismiss()

    @Slot(str)
    def choose_route(self, route):
        self.window.desk.choose_route(route)

    @Slot()
    def take_over(self):
        self._soon("take_over")

    @Slot()
    def end_call(self):
        self._soon("end_call")

    @Slot(str)
    def submit(self, text):
        self._soon("submit", text)

    @Slot(str)
    def press(self, button):
        self._soon("press", button)

    @Slot(str)
    def copy(self, text):
        QApplication.clipboard().setText(text)

    @Slot(int)
    def fit(self, note_height):
        self.window.fit_note(note_height)

    @Slot()
    def start_drag(self):
        self.window.start_drag()

    @Slot()
    def hide_to_edge(self):
        self.window.ask_to_hide()

    @Slot()
    def minimize(self):
        self.window.showMinimized()

    @Slot()
    def close_note(self):
        self.window.hide()

    @Slot(bool)
    def set_typing(self, typing):
        self.window.typing = typing

    @Slot()
    def setup_phone(self):
        self.window.open_pairing()

    @Slot(str, str)
    def pairing_answer(self, answer, chosen):
        self._soon("pairing_answer", answer, chosen)


class ContactsBridge(QObject):
    """What the contact list can call."""

    def __init__(self, private, rules, eggs=None, window=None):
        super().__init__()
        self.private = private
        self.rules = rules
        self.eggs = eggs
        self.window = window

    @Slot()
    def close_window(self):
        if self.window:
            self.window.hide()

    @Slot()
    def start_drag(self):
        if self.window and self.window.windowHandle():
            self.window.windowHandle().startSystemMove()

    @Slot(result=str)
    def rows(self):
        return json.dumps(contact_rows(self.private, self.rules, self.eggs), ensure_ascii=False)

    @Slot(str, str)
    def set_rule(self, number, rule):
        self.rules.set(number, rule)

    @Slot(str, str, result=str)
    def add(self, name, number):
        """The problem with what was typed, or "" if it's been added."""
        if not name.strip():
            return "Give them a name."
        if any(key.casefold() == name.strip().casefold() for key in self.private.contacts()):
            return "There is already a contact with that name."
        try:
            self.private.add_contact(name, number)
        except (ValueError, OSError) as error:
            return str(error)
        return ""

    @Slot(str, str, str, str, str, result=str)
    def update(self, old_name, old_number, name, number, rule):
        if rule not in ("ask", "ai", "me"):
            return "Choose Ask, AI, or Me."
        old_key = number_key(old_number)
        aliases = unambiguous_legacy_keys(old_key, os.path.dirname(self.private.book_path))
        try:
            number = self.private.edit_contact(old_name, old_number, name, number)
            if old_key != number_key(number) and not any(number_key(value) == old_key for value in self.private.contacts().values()):
                for key in [old_key, *aliases]:
                    self.rules.rules.pop(key, None)
            self.rules.set(number, rule)
        except (ValueError, OSError) as error:
            return str(error)
        return ""

    @Slot(str, str, result=str)
    def remove(self, name, number):
        try:
            saved = self.private.contacts().get(name)
            if saved and number_key(saved) == number_key(number):
                self.private.remove_contact(name)
            self.rules.set(number, "ask")
        except OSError as error:
            return str(error)
        return ""


class ContactsWindow(QWebEngineView):
    def __init__(self, private, rules, eggs=None):
        super().__init__()
        self.setWindowTitle("Pat contacts")
        self.setWindowIcon(tray_icon())
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowMinimizeButtonHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.bridge = ContactsBridge(private, rules, eggs, self)
        self.channel = QWebChannel()
        self.channel.registerObject("bridge", self.bridge)
        self.page().setWebChannel(self.channel)
        self.page().setBackgroundColor(QColor(Qt.transparent))
        self.setContextMenuPolicy(Qt.NoContextMenu)
        self.setFixedSize(*CONTACTS_SIZE)
        self.load(QUrl.fromLocalFile(os.path.join(HERE, "note", "contacts.html")))

    def bring_up(self):
        self.page().runJavaScript("if (bridge) refresh()")
        self.showNormal()
        self.raise_()
        self.activateWindow()


class NoteWindow(QWebEngineView):
    def __init__(self, desk, zoom=1.0):
        super().__init__()
        self.desk = desk
        self.zoom = zoom
        self.note_height = START_HEIGHT - TOP_ROOM - BOTTOM_ROOM
        self.typing = False
        self.asked_to_hide = False
        self.is_hidden_at_edge = False
        self.side = "right"
        self.left_when_open = None
        self.pointer_left_for = 0
        self.last_screen = None
        self.last_sent = None
        self.quitting = False
        self.ready = False
        self.drag_offset = None

        self.setWindowTitle("Pat")
        self.setWindowIcon(tray_icon())
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.WindowMinimizeButtonHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setStyleSheet("background: transparent")
        self.page().setBackgroundColor(QColor(0, 0, 0, 0))
        self.setContextMenuPolicy(Qt.NoContextMenu)

        self.bridge = Bridge(self)
        self.channel = QWebChannel()
        self.channel.registerObject("bridge", self.bridge)
        self.page().setWebChannel(self.channel)
        self.setZoomFactor(self.zoom)
        self.loadFinished.connect(lambda ok: self._on_loaded())
        self.load(QUrl.fromLocalFile(os.path.join(HERE, "note", "index.html")))

        self.slide = QPropertyAnimation(self, b"pos")
        self.slide.setDuration(SLIDE_MS)
        self.slide.setEasingCurve(QEasingCurve.OutCubic)

        self.wanted_height = self._scaled(START_HEIGHT)
        self.resize(self._scaled(WIDTH), self.wanted_height)
        area = self.screen().availableGeometry()
        self.move(open_left("right", self.width(), area.left(), area.width()), area.top() + SCREEN_MARGIN)

        self.state_timer = QTimer(self, interval=STATE_MS)
        self.state_timer.timeout.connect(lambda: self._send_state())
        self.hover_timer = QTimer(self, interval=HOVER_MS)
        self.hover_timer.timeout.connect(lambda: self._follow_pointer())
        self.drag_timer = QTimer(self, interval=DRAG_MS)
        self.drag_timer.timeout.connect(lambda: self._follow_drag())
        self.state_timer.start()
        self.hover_timer.start()

    def _on_loaded(self):
        self.ready = True
        self.setZoomFactor(self.zoom)  # a page load can reset it

    def _scaled(self, size):
        return round(size * self.zoom)

    def fit_note(self, note_height):
        self.note_height = note_height
        self.wanted_height = self._scaled(note_height + TOP_ROOM + BOTTOM_ROOM)
        self.resize(self._scaled(WIDTH), self.wanted_height)

    def set_zoom(self, zoom):
        """Bigger or smaller, keeping the edge it's nearest to where it is."""
        area = self._area()
        old_width = self.width()
        right_edge = self.x() + old_width
        near_right = nearest_side(self.x(), old_width, area.left(), area.width()) == "right"
        self.slide.stop()
        self.zoom = zoom
        self.setZoomFactor(zoom)
        self.fit_note(self.note_height)
        if self.is_hidden_at_edge:
            self.move(hidden_left(self.side, self.width(), area.left(), area.width(), zoom), self.y())
            if self.side == "right" and self.left_when_open is not None:  # or it would come back past the screen's edge
                self.left_when_open += old_width - self.width()
        elif near_right:
            self.move(right_edge - self.width(), self.y())
        self.last_sent = None

    def _send_state(self):
        if self.height() != self.wanted_height and not self.isMinimized():
            self.resize(WIDTH, self.wanted_height)  # a screen cut short would hide its buttons
        state = self.desk.state()
        screen = state["screen"]
        if screen != self.last_screen:
            self._on_screen_changed(screen)
        self.last_screen = screen
        state["side"] = self.side
        text = json.dumps(state, ensure_ascii=False)
        if self.ready and text != self.last_sent:
            self.last_sent = text
            self.page().runJavaScript(f"render({text})")

    def _on_screen_changed(self, screen):
        self.asked_to_hide = False  # hiding was for that screen: after Take over, say, End call has to stay in reach
        if screen in ("ringing", "done"):
            self.bring_back()

    def bring_back(self):
        """A call is ringing: out of the tray, the taskbar and the edge."""
        if self.isMinimized():
            self.showNormal()
        self.show()
        self.raise_()
        self.slide_out()
        self.pointer_left_for = LEAVE_MS - SHOWN_ON_REQUEST_MS

    def _area(self):
        return self.screen().availableGeometry()

    def _slide_to(self, left):
        self.slide.stop()
        self.slide.setStartValue(self.pos())
        self.slide.setEndValue(QPoint(left, self.y()))
        self.slide.start()

    def slide_in(self):
        if self.is_hidden_at_edge:
            return
        area = self._area()
        self.left_when_open = self.x()
        self.side = nearest_side(self.x(), self.width(), area.left(), area.width())
        self.is_hidden_at_edge = True
        self._slide_to(hidden_left(self.side, self.width(), area.left(), area.width(), self.zoom))

    def slide_out(self):
        if not self.is_hidden_at_edge:
            return
        self.is_hidden_at_edge = False
        area = self._area()
        left = self.left_when_open if self.left_when_open is not None else open_left(self.side, self.width(), area.left(), area.width())
        self._slide_to(left)

    def ask_to_hide(self):
        self.asked_to_hide = True
        self.pointer_left_for = LEAVE_MS  # no waiting: the pointer is on the button, so it hides until touched
        self.slide_in()

    def open_pairing(self):
        """The "Set up the phone for Pat's calls" steps, inside the note, so they sit under it and zoom with it."""
        self.desk.start_pairing()
        self.bring_back()

    def start_drag(self):
        """Follows the pointer itself. Windows' own window-move left the window unable to resize afterwards."""
        if self.is_hidden_at_edge:
            return
        self.slide.stop()
        self.drag_offset = QCursor.pos() - self.pos()
        self.drag_timer.start()

    def _follow_drag(self):
        if not ctypes.windll.user32.GetAsyncKeyState(LEFT_BUTTON) & 0x8000:
            self.drag_timer.stop()
            self.drag_offset = None
            self.pointer_left_for = 0
            return
        self.move(QCursor.pos() - self.drag_offset)

    def _pointer_on_note(self):
        return self.frameGeometry().contains(QCursor.pos())

    def _follow_pointer(self):
        if self.drag_offset is not None or not self.isVisible() or self.isMinimized() or self.slide.state() == QPropertyAnimation.Running:
            return
        hide_me = should_hide(self.last_screen or "idle", self.asked_to_hide, self.typing)
        if self._pointer_on_note():
            # Right after the arrow, the pointer is still where the note was; it isn't asking for it back until it has left.
            if self.is_hidden_at_edge and self.pointer_left_for < LEAVE_MS:
                self.slide_out()
                # At the very edge, the note slides out from under the pointer, so give it time to reach the note.
                self.pointer_left_for = LEAVE_MS - HOVER_GRACE_MS
            elif not self.is_hidden_at_edge:
                self.pointer_left_for = 0
            return
        self.pointer_left_for = LEAVE_MS if self.is_hidden_at_edge else self.pointer_left_for + HOVER_MS
        if self.is_hidden_at_edge:
            self.pointer_left_for = 0
        elif hide_me and self.pointer_left_for >= LEAVE_MS:
            self.pointer_left_for = 0
            self.slide_in()

    def showEvent(self, event):
        super().showEvent(event)
        # A new taskbar button can come up with a blank icon, and Windows only looks again when the icon changes.
        QTimer.singleShot(ICON_AGAIN_MS, lambda: self.setWindowIcon(tray_icon()))

    def closeEvent(self, event):
        if self.quitting:
            event.accept()
        else:  # keeps watching the line from the tray
            event.ignore()
            self.hide()


def _choices(menu, title, choices, current, on_choose):
    """A submenu with one choice ticked."""
    submenu = menu.addMenu(title)
    group = QActionGroup(submenu)
    for label, value in choices:
        action = QAction(label, submenu, checkable=True, checked=value == current)
        action.setData(value)
        action.triggered.connect(lambda checked=False, value=value: on_choose(value))
        group.addAction(action)
        submenu.addAction(action)
    return submenu


def _settings_menu(menu, window, options):
    settings = options.settings

    def zoom_by(step):
        zoom = next_zoom(window.zoom, step)
        settings.change("zoom", zoom)
        window.set_zoom(zoom)
        window.bring_back()

    eggs = getattr(options, "eggs", None)
    contacts = ContactsWindow(options.private, options.rules, eggs)
    window.contacts = contacts
    menu.addAction(QAction("Zoom in", menu, triggered=lambda: zoom_by(1)))
    menu.addAction(QAction("Zoom out", menu, triggered=lambda: zoom_by(-1)))
    menu.addSeparator()
    window.submenus = {}
    from onboarding import ProfileDialog
    menu.addAction(QAction("Your name, region and phone...", menu, triggered=lambda: ProfileDialog(window).exec()))
    menu.addAction(QAction("Set up the phone for Pat's calls...", menu, triggered=window.open_pairing))
    for title, choices, name in (("Incoming calls speak", LANGUAGES, "language"), ("Unknown numbers", FOR_UNKNOWN, "unknown"),
                                 ("English voice", english_voices(), "voice_en"), ("Russian voice", RUSSIAN_VOICES, "voice_ru")):
        window.submenus[title] = _choices(menu, title, choices, getattr(settings, name), lambda value, name=name: settings.change(name, value))
    menu.addAction(QAction("Contacts...", menu, triggered=contacts.bring_up))

    def show_stats():
        window.desk.show_stats()
        window.bring_back()

    menu.addAction(QAction("Stats", menu, triggered=show_stats))
    if eggs:
        def show_facts():
            window.desk.show_facts()
            window.bring_back()

        window.submenus["Pat facts"] = _choices(menu, "Pat facts", (("On", True), ("Off", False)), eggs.facts_on(), eggs.set_facts_on)
        menu.addAction(QAction("Facts found", menu, triggered=show_facts))
    menu.addSeparator()


def show(desk, on_start=None, on_quit=None, options=None):
    """Opens the window and the tray icon. Blocks until Quit is chosen from the tray."""
    if not claim_single_copy():
        print("Pat is already open, so it was brought to the front.", flush=True)
        return
    # Or Windows files its windows under Python on the taskbar, with Python's icon.
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("PhoneAgentTool.Pat")
    app = QApplication.instance() or QApplication([])
    app.setWindowIcon(tray_icon())
    app.setQuitOnLastWindowClosed(False)
    window = NoteWindow(desk, options.settings.zoom if options else 1.0)
    QLocalServer.removeServer(COPY_NAME)
    server = QLocalServer(app)
    server.listen(COPY_NAME)
    server.newConnection.connect(lambda: (server.nextPendingConnection(), window.bring_back()))

    tray = QSystemTrayIcon(tray_icon(), app)
    tray.setToolTip("Pat: watching for calls")
    menu = QMenu()
    show_action = QAction("Show", menu, triggered=window.bring_back)
    quit_action = QAction("Quit", menu)

    def quit_all():
        window.quitting = True
        tray.hide()
        if on_quit:
            on_quit()
        app.quit()

    quit_action.triggered.connect(quit_all)
    menu.addAction(show_action)
    menu.addSeparator()
    if options:
        _settings_menu(menu, window, options)
    menu.addAction(quit_action)
    tray.setContextMenu(menu)
    tray.activated.connect(lambda reason: window.bring_back() if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick) else None)
    tray.show()

    window.show()
    if on_start:
        on_start(window, tray)
    app.exec()
