"""Name first, then a required Terms of Use checkbox. No phone or model starts here."""
import json
from zoneinfo import available_timezones

import threading

from PySide6.QtCore import QLocale, QObject, QProcess, Qt, QTimer, Signal
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog,
                              QHBoxLayout, QLineEdit, QPushButton,
                              QSizePolicy, QStackedWidget, QTextEdit, QVBoxLayout, QWidget)

from languages import LANGUAGES
from owner_names import ask_haiku, localize
from note_dialog import Disclosure, PADDING, PAPER_WIDTH, PaperDialog, StepDots, field, label, rule
from user_profile import DATE_FORMATS, PRONOUNS, TERMS_TEXT, UserProfile

PRONOUNS_QUESTION = "How should I refer to you?"
FILL_DELAY_MS = 1200  # after the last key in the first row, so a name being typed isn't sent letter by letter


class _Filled(QObject):
    done = Signal(int, object)


class NameTable(QWidget):
    """The owner's name per language, in one row: a language dropdown on the left, that language's name on the right.
    It opens on the language the name is typed in, the system's. Typing the name there has AI write it for the other
    languages, which the dropdown then shows; a language whose name the owner types themselves is never overwritten."""

    def __init__(self, profile, ask=None, parent=None):
        super().__init__(parent)
        self.ask = ask or ask_haiku
        self.source = profile.name_language
        self.order = [self.source] + [code for code in LANGUAGES if code != self.source]
        self.names = dict(profile.names)
        self.by_hand = set()
        self.request = 0
        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.language = QComboBox()
        self.language.setObjectName("owner-name-language")
        for code in self.order:
            self.language.addItem(LANGUAGES[code]["native"], code)
        self.language.setFixedWidth(116)
        self.edit = QLineEdit(self.names.get(self.source, ""))
        self.edit.setObjectName("owner-name")
        self.edit.setMaxLength(100)
        self.edit.setPlaceholderText("Your name")
        row.addWidget(self.language)
        row.addWidget(self.edit, 1)
        column.addLayout(row)
        self.status = label("", "status")
        self.status.hide()
        column.addWidget(self.status)
        self.language.currentIndexChanged.connect(self._show_language)
        self.edit.textChanged.connect(lambda text: self.names.__setitem__(self.current, text.strip()))
        self.edit.textEdited.connect(self._typed)
        self.edit.editingFinished.connect(lambda: self.timer.isActive() and (self.timer.stop(), self.fill()))
        self.timer = QTimer(self, singleShot=True, interval=FILL_DELAY_MS)
        self.timer.timeout.connect(self.fill)
        self._filled = _Filled(self)
        self._filled.done.connect(self._show_filled)

    @property
    def current(self):
        return self.language.currentData()

    def default_name(self):
        return self.names.get(self.source, "")

    def _typed(self, _text):
        if self.current == self.source:
            self.timer.start()
        else:
            self.by_hand.add(self.current)

    def _show_language(self):
        self.edit.setText(self.names.get(self.current, ""))
        self.edit.setPlaceholderText("Your name" if self.current == self.source else "Filled in when you type your name in your language")

    def fill(self):
        name = self.default_name()
        targets = [code for code in self.order[1:] if code not in self.by_hand]
        if not name or not targets:
            return
        self.request += 1
        number = self.request
        self.set_status("Writing your name in the other languages…")

        def work():
            try:
                names = localize(name, self.source, self.ask, targets)
            except Exception:  # no login, no network or a timeout: the rows stay as they are
                names = None
            self._filled.done.emit(number, names)
        threading.Thread(target=work, daemon=True).start()

    def _show_filled(self, number, names):
        if number != self.request:  # the name changed again since this was asked
            return
        if not names:
            self.set_status("Couldn't fill them in. Type them yourself, or calls will use your name as written.")
            return
        filled = [code for code in names if code not in self.by_hand]
        for code in filled:
            self.names[code] = names[code]
            if code == self.current:
                self.edit.setText(names[code])
        titles = ", ".join(LANGUAGES[code]["native"] for code in filled)
        self.set_status(f"Filled in by AI: {titles}. Pick it in the list to check or change it." if filled else "")

    def set_status(self, text):
        self.status.setText(text)
        self.status.setVisible(bool(text))
        if hasattr(self.window(), "fit_contents"):
            QTimer.singleShot(0, self.window().fit_contents)

    def values(self):
        """(name, its language, {other language: name}) to save."""
        return self.default_name(), self.source, {code: self.names[code] for code in self.order[1:] if self.names.get(code)}


def country_choices():
    """(English name, region code) for every country the number library knows, by name. The name comes from the code
    itself: a locale such as "English in Uzbekistan" doesn't exist, and Qt fell back to the United States for 133 of them."""
    from phonenumbers import SUPPORTED_REGIONS
    named = [(QLocale.territoryToString(QLocale.codeToTerritory(region)), region) for region in SUPPORTED_REGIONS]
    return sorted(named, key=lambda pair: (pair[0].casefold(), pair[1]))


def pronoun_choice(current):
    box = QComboBox()
    box.setObjectName("owner-pronouns")
    for value, title in PRONOUNS.items():
        box.addItem(title, value)
    box.setCurrentIndex(max(0, box.findData(current)))
    return box

class OnboardingDialog(PaperDialog):
    def __init__(self, profile, parent=None):
        super().__init__(parent)
        self.profile = profile
        self.setWindowTitle("Welcome to Pat")
        layout = self.paper_layout
        steps = QHBoxLayout()
        self.step = label("1 of 2 · Your name", "step")
        self.dots = StepDots()
        self.step.setWordWrap(False)
        steps.addWidget(self.step, 1)
        steps.addWidget(self.dots)
        layout.addLayout(steps)
        layout.addSpacing(16)
        self.pages = QStackedWidget()
        layout.addWidget(self.pages)
        name_page = QWidget()
        name_layout = QVBoxLayout(name_page)
        name_layout.setContentsMargins(0, 0, 0, 0)
        name_layout.setSpacing(0)
        name_layout.addWidget(label("What should I call you?", "heading"))
        name_layout.addSpacing(4)
        name_layout.addWidget(label("I’ll use your name when I introduce myself on calls.", "hint"))
        name_layout.addSpacing(20)
        self.names = NameTable(profile)
        self.name = self.names.edit
        field(name_layout, "Your name", self.names)
        name_layout.addSpacing(8)
        name_layout.addWidget(label("Your name in each call language.", "hint"))
        name_layout.addSpacing(24)
        self.pronouns = pronoun_choice(profile.pronouns)
        field(name_layout, PRONOUNS_QUESTION, self.pronouns)
        name_layout.addSpacing(20)
        name_layout.addWidget(label("You can change these later in Settings.", "hint"))
        name_layout.addSpacing(20)
        self.pages.addWidget(name_page)
        terms_page = QWidget()
        terms_layout = QVBoxLayout(terms_page)
        terms_layout.setContentsMargins(0, 0, 0, 0)
        terms_layout.setSpacing(0)
        terms_layout.addWidget(label("Before we begin", "heading"))
        terms_layout.addSpacing(4)
        terms_layout.addWidget(label("Read the Terms of Use before continuing.", "hint"))
        terms_layout.addSpacing(20)
        self.terms = QTextEdit()
        self.terms.setObjectName("terms-text")
        self.terms.setReadOnly(True)
        self.terms.setMarkdown(TERMS_TEXT)
        self.terms.setFixedHeight(220)
        terms_layout.addWidget(self.terms)
        terms_layout.addSpacing(20)
        self.agree = QCheckBox("I have read and agree to the Terms of Use.")
        self.agree.setObjectName("agree-to-terms")
        terms_layout.addWidget(self.agree)
        self.pages.addWidget(terms_page)
        self.problem = label("", "problem")
        self.problem.hide()
        layout.addWidget(self.problem)
        layout.addSpacing(16)
        rule(layout)
        layout.addSpacing(12)
        self.buttons = QWidget()
        actions = QHBoxLayout(self.buttons)
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(8)
        actions.addStretch()
        self.next = QPushButton("Continue")
        self.next.setObjectName("setup-continue")
        self.next.setProperty("tone", "primary")
        self.next.setDefault(True)
        self.back = QPushButton("Cancel")
        self.back.setProperty("tone", "quiet")
        self.back.setAutoDefault(False)
        self.back.clicked.connect(self.go_back)
        self.next.clicked.connect(self.advance)
        actions.addWidget(self.back)
        actions.addWidget(self.next)
        layout.addWidget(self.buttons)
        layout.addSpacing(16)
        self.name.textChanged.connect(self.refresh)
        self.agree.toggled.connect(self.refresh)
        self.refresh()

    def refresh(self):
        self.next.setEnabled(bool(self.names.default_name()) if self.pages.currentIndex() == 0 else self.agree.isChecked())
        self.fit_contents()

    def fit_contents(self):
        if hasattr(self, "pages") and self.pages.currentWidget():
            page_layout = self.pages.currentWidget().layout()
            page_layout.invalidate()
            height = page_layout.totalHeightForWidth(PAPER_WIDTH - PADDING * 2)
            self.pages.setFixedHeight(height if height >= 0 else page_layout.sizeHint().height())
        super().fit_contents()

    def go_back(self):
        if self.pages.currentIndex() == 0:
            self.reject()
            return
        self.pages.setCurrentIndex(0)
        self.next.setText("Continue")
        self.back.setText("Cancel")
        self.step.setText("1 of 2 · Your name")
        self.dots.current = 0
        self.dots.update()
        self.refresh()

    def advance(self):
        if not self.names.default_name():
            return
        if self.pages.currentIndex() == 0:
            self.pages.setCurrentIndex(1)
            self.next.setText("Agree and open Pat")
            self.back.setText("Back")
            self.step.setText("2 of 2 · Terms of Use")
            self.dots.current = 1
            self.dots.update()
            self.refresh()
            return
        self.accept()

    def accept(self):
        if self.pages.currentIndex() != 1 or not self.agree.isChecked() or not self.names.default_name():
            return
        try:
            name, language, others = self.names.values()
            self.profile.save(name=name, name_language=language, names=others, pronouns=self.pronouns.currentData())
            self.profile.accept_terms()
        except (ValueError, OSError) as error:
            self.problem.setText(str(error))
            self.problem.show()
            self.fit_contents()
            return
        super().accept()


def ensure_onboarding(profile=None):
    profile = profile or UserProfile()
    if profile.ready:
        return True
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    return OnboardingDialog(profile).exec() == QDialog.Accepted


class ProfileDialog(PaperDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.profile = UserProfile()
        self.setWindowTitle("Pat settings")
        layout = self.paper_layout
        layout.addWidget(label("Your settings", "heading"))
        layout.addSpacing(4)
        layout.addWidget(label("Your name, phone, and call options.", "hint"))
        layout.addSpacing(16)
        sections = []  # one open at a time
        self.name_section = Disclosure("Your name", self.profile.name, self, opened=True, group=sections)
        self.region_section = Disclosure("Calls & reports", "Country, time & dates", self, group=sections)
        self.phone_section = Disclosure("Your phone", "Automatic", self, group=sections)
        for section in (self.name_section, self.region_section, self.phone_section):
            layout.addWidget(section)
        self.names = NameTable(self.profile)
        self.name = self.names.edit
        self.name_section.fields.addWidget(self.names)
        self.name_section.fields.addSpacing(12)
        self.pronouns = pronoun_choice(self.profile.pronouns)
        field(self.name_section.fields, "Pat refers to you as", self.pronouns)
        self.name.textChanged.connect(lambda _: self.name_section.meta.setText(self.names.default_name()))
        self.country = QComboBox()
        self.country.addItem("Use full international numbers (+country code)", "")
        for name, region in country_choices():
            self.country.addItem(f"{name} ({region})", region)
        self.country.setCurrentIndex(max(0, self.country.findData(self.profile.country)))
        field(self.region_section.fields, "Country for local numbers", self.country)
        self.region_section.fields.addSpacing(12)
        self.zone = QComboBox()
        self.zone.setEditable(True)
        self.zone.addItems(sorted(available_timezones()))
        self.zone.setCurrentText(self.profile.time_zone)
        field(self.region_section.fields, "Time zone", self.zone)
        self.region_section.fields.addSpacing(12)
        self.dates = QComboBox()
        for value, title in DATE_FORMATS.items():
            self.dates.addItem(title, value)
        self.dates.setCurrentIndex(self.dates.findData(self.profile.date_format))
        field(self.region_section.fields, "Dates in reports", self.dates)
        self.region_section.fields.addSpacing(8)
        self.region_section.fields.addWidget(label("Calls can use a different time zone when you name one.", "hint"))
        self.phone = QComboBox()
        self.phone.addItem("Automatic (the phone connected last)", "")
        if self.profile.phone_device:
            self.phone.addItem(self.profile.values.get("phone_name") or "Selected phone", self.profile.phone_device)
            self.phone.setCurrentIndex(1)
        field(self.phone_section.fields, "Phone to use", self.phone)
        self.phone.currentIndexChanged.connect(self.update_phone_summary)
        self.update_phone_summary()
        self.phone_section.fields.addSpacing(12)
        self.find = QPushButton("Find paired phones")
        self.find.setAutoDefault(False)
        self.find.clicked.connect(self.find_phones)
        self.find.setProperty("tone", "primary")
        self.phone_section.fields.addWidget(self.find, 0, Qt.AlignLeft)
        self.phone_status = label("", "status")
        self.phone_status.hide()
        self.phone_section.fields.addSpacing(8)
        self.phone_section.fields.addWidget(self.phone_status)
        for box in (self.country, self.zone, self.dates, self.phone):
            box.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
            box.setMinimumContentsLength(10)
            box.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.problem = label("", "problem")
        self.problem.hide()
        layout.addWidget(self.problem)
        rule(layout)
        layout.addSpacing(12)
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        buttons.addStretch()
        cancel = QPushButton("Cancel")
        cancel.setProperty("tone", "quiet")
        cancel.setAutoDefault(False)
        cancel.clicked.connect(self.reject)
        save = QPushButton("Save changes")
        save.setProperty("tone", "primary")
        save.setDefault(True)
        save.clicked.connect(self.save)
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        layout.addLayout(buttons)
        layout.addSpacing(16)
        self.process = QProcess(self)
        self.process.finished.connect(self.phones_found)
        self.process.errorOccurred.connect(lambda _: self.find_failed())
        self.phone_timeout = QTimer(self, singleShot=True, interval=15000)
        self.phone_timeout.timeout.connect(lambda: (self.process.kill(), self.find_failed()))
        self.fit_contents()

    def update_phone_summary(self):
        self.phone_section.meta.setText(self.phone.currentText() if self.phone.currentData() else "Automatic")

    def show_phone_status(self, text):
        self.phone_status.setText(text)
        self.phone_status.setVisible(bool(text))
        self.fit_contents()

    def find_phones(self):
        self.find.setEnabled(False)
        self.show_phone_status("Looking for paired phones…")
        self.process.start("iphonecall", ["list-json"])
        self.phone_timeout.start()

    def find_failed(self):
        self.phone_timeout.stop()
        self.find.setEnabled(True)
        self.show_phone_status("Could not list phones. Run setup.ps1 to build the updated phone tool.")

    def phones_found(self, code, _status):
        self.phone_timeout.stop()
        self.find.setEnabled(True)
        try:
            if code:
                raise ValueError("phone tool failed")
            choices = json.loads(bytes(self.process.readAllStandardOutput()).decode("utf-8"))
            if not isinstance(choices, list):
                raise ValueError("unexpected phone list")
            selected = self.phone.currentData()
            self.phone.clear()
            self.phone.addItem("Automatic (the phone connected last)", "")
            for phone in choices:
                self.phone.addItem(phone["name"], phone["id"])
            self.phone.setCurrentIndex(max(0, self.phone.findData(selected)))
            count = len(choices)
            message = ("One paired phone found. Choose it above, or keep Automatic." if count == 1 else
                       f"{count} paired phones found. Choose one above, or keep Automatic." if count else
                       "No paired phones found. Pair your phone in Bluetooth settings first.")
            self.show_phone_status(message)
        except (ValueError, KeyError, TypeError):
            self.find_failed()

    def save(self):
        try:
            name, language, others = self.names.values()
            self.profile.save(name=name, name_language=language, names=others, pronouns=self.pronouns.currentData(), country=self.country.currentData(), time_zone=self.zone.currentText(),
                              date_format=self.dates.currentData(), phone_device=self.phone.currentData(), phone_name=self.phone.currentText())
        except (ValueError, KeyError, OSError) as error:
            self.problem.setText(str(error))
            self.problem.show()
            self.fit_contents()
            return
        self.accept()

    def done(self, result):
        self.phone_timeout.stop()
        if hasattr(self, "process") and self.process.state() != QProcess.NotRunning:
            self.process.kill()
            self.process.waitForFinished(1000)
        super().done(result)
