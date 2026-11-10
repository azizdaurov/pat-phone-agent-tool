"""Render Pat's real windows with fictional data, without phones, audio or AI services.

Run: .venv/Scripts/python.exe evals/pat_demo_shots.py <output-folder>
Windows are rendered natively at 4x scale. Paper windows have transparent backgrounds;
the tray submenu keeps its normal white background.
"""
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
import traceback
import types

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["QT_SCALE_FACTOR"] = "4"
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu")
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "app"), str(ROOT / "voice-loop")]

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("output", type=Path)
args = parser.parse_args()
out = args.output.resolve()
out.mkdir(parents=True, exist_ok=True)
scratch = tempfile.TemporaryDirectory(prefix="pat-demo-", dir=out)
os.environ["PAT_PROFILE_PATH"] = str(Path(scratch.name) / "profile.json")

from PySide6.QtCore import QPoint, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QFontDatabase, QImage, QPainter, QPen
from PySide6.QtWidgets import QApplication, QMenu

from note import CallRules
from note_settings import NoteSettings
from note_window import ContactsWindow, NoteWindow, _settings_menu
from onboarding import OnboardingDialog, ProfileDialog
from private_numbers import PrivateNumbers
from user_profile import UserProfile


def facts(*items):
    return [{"label": label, "value": value} for label, value in items]


AIRLINE = {"name": "Northstar Air", "number": "+1 202 555 0124"}
DELIVERY = {"name": "Aster Delivery", "number": "+1 202 555 0146"}
INTERVIEW = {"name": "Horizon Research", "number": "+1 202 555 0168"}
FLIGHT_FACTS = facts(("Flight", "NS 204 to London"), ("Departure", "18:45, Terminal 2"),
                     ("Baggage", "One checked bag included"), ("Seat", None))
NOTE_SHOTS = [
    ("01-ready-to-work", "Ready to work", {"screen": "idle"},
     "document.getElementById('prompt').value = 'Call Northstar Air for me.';"),
    ("02-incoming-airline", "An important call", {"screen": "ringing", **AIRLINE}, ""),
    ("03-choose-phone-or-laptop", "Choose where to answer", {"screen": "ringing", **AIRLINE}, "setMenu(true);"),
    ("04-ai-flight-change", "Pat checks the new flight", {"screen": "ai", **AIRLINE, "talking": True, "level": .74,
     "facts": FLIGHT_FACTS, "summary": "Checking a later flight that still makes your connection."}, ""),
    ("05-listening-to-delivery", "Listen while Pat talks", {"screen": "ai", **DELIVERY, "listening": True,
     "talking": True, "level": .58, "facts": facts(("Delivery", "Studio equipment"), ("Arrival", "14:00–15:00"),
     ("Drop-off", "Front desk"), ("Contact", None)), "summary": "Confirming the delivery while you work."}, ""),
    ("06-take-over-on-laptop", "Take over on the laptop", {"screen": "me", **DELIVERY, "route": "laptop",
     "talking": True, "level": .67}, ""),
    ("07-move-to-phone", "Move the call to your phone", {"screen": "me", **INTERVIEW, "route": "iphone"}, ""),
    ("08-flight-change-summary", "A clear plan after the call", {"screen": "done", **AIRLINE,
     "facts": facts(("Flight", "NS 204 · 18:45"), ("Check-in", "Terminal 2 · by 17:15"),
                    ("Baggage", "One checked bag included"), ("Reference", "DEMO-7Q2")),
     "summary": "The earlier flight was cancelled. Northstar Air confirmed the 18:45 alternative and kept your checked bag.",
     "next_step": "Leave for the airport by 16:00. Keep reference DEMO-7Q2."}, ""),
    ("09-interview-confirmed", "The interview is confirmed", {"screen": "done", **INTERVIEW,
     "facts": facts(("Interview", "Tuesday · 10:30 Tashkent"), ("Format", "Video call"), ("Interviewer", "Dr. Maya Chen")),
     "summary": "Maya confirmed a 30-minute research interview. The video link will arrive by email.",
     "next_step": "Send your project link before Monday. Prepare a five-minute project overview."}, ""),
    ("10-dentist-booked", "An appointment, sorted", {"screen": "done", "name": "Willow Dental",
     "number": "+1 202 555 0182", "facts": facts(("Appointment", "Wednesday · 09:00"),
     ("Dentist", "Dr. Reed"), ("Place", "12 Willow Street")),
     "summary": "Your check-up is booked. The clinic asked you to arrive ten minutes early.",
     "next_step": "Bring your ID and your previous dental records."}, ""),
]


class DemoDesk:
    current = {}

    def state(self):
        return {"screen": "idle", "notice": "", "level": 0, "route": "iphone", "me_route": "iphone",
                "number": "", "name": "", "always": False, "talking": False, "listening": False,
                "facts": [], "summary": "", "next_step": "", **self.current}

    def show_stats(self):
        pass


app = QApplication([])
app.setQuitOnLastWindowClosed(False)
# The offscreen Qt platform has no system font database on Windows. Load the same
# installed fonts the real app uses; this changes only this renderer's process.
font_folder = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
for filename in ("georgia.ttf", "georgiab.ttf", "georgiai.ttf", "georgiaz.ttf",
                 "segoeui.ttf", "segoeuib.ttf", "segoeuii.ttf", "segoeuiz.ttf", "seguisym.ttf"):
    font_path = font_folder / filename
    if font_path.exists():
        QFontDatabase.addApplicationFont(str(font_path))
if "Georgia" not in QFontDatabase.families():
    raise RuntimeError("The app's Georgia font could not be loaded")
app.setFont(QFont("Segoe UI", 9))
profile = UserProfile()
profile.save(name="Sam Morgan", name_language="en", names={"ru": "Сэм Морган"}, pronouns="they",
             country="UZ", time_zone="Asia/Tashkent", date_format="dmy", phone_name="Sam's iPhone",
             phone_device="DEMO-PHONE-001")
private = PrivateNumbers(scratch.name)
rules = CallRules(str(Path(scratch.name) / "rules.json"))
for name, number, rule in (("Aster Delivery", "+12025550146", "ai"), ("Horizon Research", "+12025550168", "ask"),
                           ("Maya Chen", "+12025550173", "me"), ("Northstar Air", "+12025550124", "ask"),
                           ("Willow Dental", "+12025550182", "ai")):
    private.add_contact(name, number)
    rules.set(number, rule)

desk = DemoDesk()
window = NoteWindow(desk)
for timer in (window.state_timer, window.hover_timer, window.drag_timer):
    timer.stop()
window.show()
contacts = ContactsWindow(private, rules)
contacts.show()
settings = ProfileDialog()
settings.show()
onboarding = OnboardingDialog(profile)
onboarding.show()
tray_menu = QMenu()
_settings_menu(tray_menu, window, types.SimpleNamespace(settings=NoteSettings(scratch.name), private=private, rules=rules))
records = []
tasks = []


def save_image(image, slug, title, kind="window"):
    image.setDevicePixelRatio(1)
    image.setDotsPerMeterX(round(384 / .0254))
    image.setDotsPerMeterY(round(384 / .0254))
    image.setText("Description", "Pat's real UI with fictional demo data. No calls were made.")
    filename = slug + ".png"
    if image.isNull() or not image.save(str(out / filename), "PNG"):
        raise RuntimeError("Could not save " + filename)
    records.append({"file": filename, "title": title, "width": image.width(), "height": image.height(), "kind": kind})
    print(f"Saved {filename}: {image.width()} x {image.height()}", flush=True)


def save_widget(widget, slug, title):
    if widget.devicePixelRatioF() < 3.9:
        raise RuntimeError("Native 4x rendering was not enabled")
    save_image(widget.grab().toImage(), slug, title)


def render_note(state, js=""):
    desk.current = state
    # A static capture needs the finished layout, rather than a paused offscreen
    # height transition. Keep the app's fonts, layout, colours and contents intact.
    prepare = """if (!document.getElementById('demo-still')) {
        const style = document.createElement('style'); style.id = 'demo-still';
        style.textContent = '#note { transition: none !important; }'; document.head.appendChild(style);
    } document.getElementById('prompt').value = ''; """
    window.page().runJavaScript(prepare + "render(" + json.dumps(desk.state(), ensure_ascii=False) + ");" + js)


for slug, title, state, js in NOTE_SHOTS:
    tasks.append((lambda state=state, js=js: render_note(state, js), 800))
    tasks.append((lambda slug=slug, title=title: save_widget(window, slug, title), 0))

tasks.extend([
    (lambda: save_widget(contacts, "11-contacts", "Your people and who answers"), 0),
    (lambda: contacts.page().runJavaScript("openEditor({name:'Aster Delivery', number:'+12025550146', rule:'ai', named:true});"), 600),
    (lambda: save_widget(contacts, "12-edit-contact", "Choose how a contact is answered"), 0),
    (lambda: save_widget(settings, "13-settings-your-name", "Your name, in each language"), 0),
    (lambda: settings.region_section.set_open(True), 400),
    (lambda: save_widget(settings, "14-settings-region-and-time", "Your country, time and dates"), 0),
    (lambda: settings.phone_section.set_open(True), 400),
    (lambda: save_widget(settings, "15-settings-your-phone", "Choose the phone Pat uses"), 0),
])


def save_noise_menu():
    submenu = window.submenus["Noise cancellation"]
    submenu.ensurePolished()
    submenu.resize(submenu.sizeHint())
    save_widget(submenu, "16-noise-cancellation-choice", "Noise cancellation: Without by default")


tasks.append((save_noise_menu, 0))
PAIRING = {"screen": "idle", "pairing": {"title": "Check the code",
    "text": "Your phone should show this code too. Tap Pair there, then confirm here.", "code": "482 916",
    "hint": "Keep Settings > Bluetooth open on your phone: the Pair request appears there.",
    "actions": [{"label": "No code, or a different one", "answer": "n", "tone": "quiet"},
                {"label": "Codes match", "answer": "y", "tone": "primary"}]}}
tasks.extend([
    (lambda: render_note(PAIRING), 800),
    (lambda: save_widget(window, "17-pair-phone-code", "Pair a phone with a matching code"), 0),
    (onboarding.advance, 400),
    (lambda: save_widget(onboarding, "18-first-run-terms", "First run: review the terms"), 0),
])


def text(painter, x, y, value, size, color="#3B2A1A", bold=False):
    font = QFont("Georgia")
    font.setPixelSize(size)
    font.setBold(bold)
    painter.setFont(font)
    painter.setPen(QColor(color))
    painter.drawText(QPoint(x, y), value)


def draw_fit(painter, image, area):
    scale = min(area.width() / image.width(), area.height() / image.height())
    width, height = image.width() * scale, image.height() * scale
    painter.drawImage(QRectF(area.x() + (area.width() - width) / 2, area.y() + (area.height() - height) / 2,
                            width, height), image)


def make_boards():
    gallery = list(records)
    board = QImage(6000, 3600, QImage.Format_ARGB32_Premultiplied)
    board.fill(QColor("#F1EEE7"))
    painter = QPainter(board)
    painter.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing | QPainter.SmoothPixmapTransform)
    text(painter, 120, 150, "Pat, at work.", 104, bold=True)
    text(painter, 124, 215, "18 real app views. Calls, clear notes, contacts and setup.", 36, "#6B5238")
    text(painter, 4710, 145, "FICTIONAL DEMO DATA", 34, "#6B5238")
    cols, rows, margin, gap = 6, 3, 120, 44
    card_w = (board.width() - margin * 2 - gap * (cols - 1)) / cols
    card_h = (board.height() - 340 - gap * (rows - 1) - 100) / rows
    for index, record in enumerate(gallery):
        x = margin + (index % cols) * (card_w + gap)
        y = 290 + (index // cols) * (card_h + gap)
        painter.setPen(QPen(QColor("#DFD7C9"), 2))
        painter.setBrush(QColor("#FAF8F3"))
        painter.drawRoundedRect(QRectF(x, y, card_w, card_h), 28, 28)
        image = QImage(str(out / record["file"]))
        draw_fit(painter, image, QRectF(x + 28, y + 30, card_w - 56, card_h - 150))
        text(painter, round(x + 30), round(y + card_h - 62), f"{index + 1:02d}  {record['title']}", 29)
    text(painter, 124, 3540, "Native 4x window PNGs are included separately, with transparent backgrounds.", 30, "#6B5238")
    painter.end()
    save_image(board, "00-all-windows-overview", "All 18 Pat demo windows", "overview")

    story = QImage(3840, 2160, QImage.Format_ARGB32_Premultiplied)
    story.fill(QColor("#F1EEE7"))
    painter = QPainter(story)
    painter.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing | QPainter.SmoothPixmapTransform)
    text(painter, 120, 160, "A flight change. A clear plan.", 110, bold=True)
    text(painter, 124, 235, "Pat takes the call, checks the details, and leaves the next step.", 38, "#6B5238")
    names = (("02-incoming-airline.png", "01   An important call"),
             ("04-ai-flight-change.png", "02   Pat checks the details"),
             ("08-flight-change-summary.png", "03   The plan is ready"))
    for index, (filename, caption) in enumerate(names):
        x, y, width, height = 120 + index * 1220, 330, 1160, 1670
        painter.setPen(QPen(QColor("#DFD7C9"), 2))
        painter.setBrush(QColor("#FAF8F3"))
        painter.drawRoundedRect(QRectF(x, y, width, height), 36, 36)
        text(painter, x + 45, y + 90, caption, 42)
        draw_fit(painter, QImage(str(out / filename)), QRectF(x + 24, y + 145, width - 48, height - 205))
    text(painter, 124, 2090, "REAL APP UI  /  FICTIONAL DEMO DATA", 30, "#6B5238")
    painter.end()
    save_image(story, "00-flight-change-story", "A flight change, from call to clear plan", "overview")

    (out / "manifest.json").write_text(json.dumps({"fictional_data": True, "native_window_scale": 4, "images": records},
                                                   indent=2, ensure_ascii=False), encoding="utf-8")
    lines = ["# Pat demo PNGs", "", "These are captures of the real app UI with fictional demo data.",
             "No calls, microphone recording, Bluetooth changes or AI services were used.", "",
             "- `00-flight-change-story.png`: a 3840 × 2160 demo story.",
             "- `00-all-windows-overview.png`: a 6000 × 3600 overview of all 18 views.",
             "- `01`–`18`: native 4× captures, ready for slides or editing. Paper windows are transparent; the tray submenu keeps its normal white background.",
             "- `manifest.json`: image titles and exact pixel sizes.", "",
             "All scenario names, phone numbers, bookings, times and outcomes are sample data. These are not records of real calls.",
             "The noise-choice image captures the real tray submenu, with Without selected.", "",
             "## Images", ""]
    lines.extend(f"- [{record['title']}]({record['file']}) — {record['width']} × {record['height']}" for record in records)
    lines.extend(["", "## Re-create", "", "```powershell",
                  ".venv/Scripts/python.exe evals/pat_demo_shots.py demo/pat-windows-2026-11-07", "```", ""])
    (out / "README.md").write_text("\n".join(lines), encoding="utf-8")
    app.exit(0)


tasks.append((make_boards, 0))


def step():
    if not tasks:
        return
    action, wait = tasks.pop(0)
    try:
        action()
        QTimer.singleShot(wait, step)
    except Exception:
        traceback.print_exc()
        app.exit(1)


def timeout():
    print("Rendering timed out", file=sys.stderr, flush=True)
    app.exit(1)


QTimer.singleShot(3000, step)
QTimer.singleShot(60000, timeout)
result = app.exec()
window.quitting = True
for widget in (window, contacts, settings, onboarding, tray_menu, window.contacts):
    widget.close()
scratch.cleanup()
raise SystemExit(result)
