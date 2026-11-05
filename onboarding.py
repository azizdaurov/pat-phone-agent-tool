"""Name first, then a required Terms of Use checkbox. No phone or model starts here."""
import json
from zoneinfo import available_timezones

import threading

from PySide6.QtCore import QLocale, QObject, QProcess, QTimer, Signal
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                              QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                              QStackedWidget, QTextEdit, QVBoxLayout, QWidget)

from languages import LANGUAGES
from owner_names import ask_haiku, localize
from user_profile import DATE_FORMATS, PRONOUNS, TERMS_TEXT, UserProfile

PRONOUNS_QUESTION = "How should Pat refer to you on calls?"
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
        self.language = QComboBox()
        self.language.setObjectName("owner-name-language")
        for code in self.order:
            self.language.addItem(LANGUAGES[code]["native"] + (" (your language)" if code == self.source else ""), code)
        self.edit = QLineEdit(self.names.get(self.source, ""))
        self.edit.setObjectName("owner-name")
        self.edit.setMaxLength(100)
        self.edit.setPlaceholderText("Your name")
        row.addWidget(self.language)
        row.addWidget(self.edit, 1)
        column.addLayout(row)
        self.status = QLabel("")
        self.status.setWordWrap(True)
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
        self.status.setText("Writing your name in the other languages…")

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
            self.status.setText("Couldn't fill them in. Type them yourself, or calls will use your name as written.")
            return
        filled = [code for code in names if code not in self.by_hand]
        for code in filled:
            self.names[code] = names[code]
            if code == self.current:
                self.edit.setText(names[code])
        titles = ", ".join(LANGUAGES[code]["native"] for code in filled)
        self.status.setText(f"Filled in by AI: {titles}. Pick it in the list to check or change it." if filled else "")

    def values(self):
        """(name, its language, {other language: name}) to save."""
        return self.default_name(), self.source, {code: self.names[code] for code in self.order[1:] if self.names.get(code)}


def pronoun_choice(current):
    box = QComboBox()
    box.setObjectName("owner-pronouns")
    for value, title in PRONOUNS.items():
        box.addItem(title, value)
    box.setCurrentIndex(max(0, box.findData(current)))
    return box

STYLE = """
QDialog { background: #E6D6B8; color: #3B2A1A; font-family: Georgia; }
QLabel, QCheckBox { color: #3B2A1A; font-size: 14px; }
QLineEdit, QTextEdit, QComboBox { background: #F3E9D3; color: #3B2A1A; padding: 8px; border: 1px solid #A98E67; border-radius: 8px; }
QPushButton { background: #3B2A1A; color: #F5ECD9; padding: 9px 16px; border: 0; border-radius: 12px; }
QPushButton:disabled { background: #B9A27A; color: #F3E9D3; }
"""


class OnboardingDialog(QDialog):
    def __init__(self, profile, parent=None):
        super().__init__(parent)
        self.profile = profile
        self.setWindowTitle("Welcome to Pat")
        self.setStyleSheet(STYLE)
        self.resize(560, 520)
        layout = QVBoxLayout(self)
        self.pages = QStackedWidget()
        layout.addWidget(self.pages)
        name_page = QWidget()
        name_layout = QVBoxLayout(name_page)
        name_layout.addWidget(QLabel("What should Pat call you?"))
        self.names = NameTable(profile)
        self.name = self.names.edit
        name_layout.addWidget(self.names)
        name_layout.addWidget(QLabel("Pat will use this name when introducing your assistant, written for the call's language."))
        name_layout.addWidget(QLabel(PRONOUNS_QUESTION))
        self.pronouns = pronoun_choice(profile.pronouns)
        name_layout.addWidget(self.pronouns)
        name_layout.addStretch()
        self.pages.addWidget(name_page)
        terms_page = QWidget()
        terms_layout = QVBoxLayout(terms_page)
        terms_layout.addWidget(QLabel("Read the Terms of Use before continuing."))
        self.terms = QTextEdit()
        self.terms.setObjectName("terms-text")
        self.terms.setReadOnly(True)
        self.terms.setMarkdown(TERMS_TEXT)
        terms_layout.addWidget(self.terms)
        self.agree = QCheckBox("I have read and agree to the Terms of Use.")
        self.agree.setObjectName("agree-to-terms")
        terms_layout.addWidget(self.agree)
        self.pages.addWidget(terms_page)
        self.problem = QLabel()
        self.problem.setWordWrap(True)
        layout.addWidget(self.problem)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
        self.next = self.buttons.addButton("Continue", QDialogButtonBox.AcceptRole)
        self.next.setObjectName("setup-continue")
        self.buttons.rejected.connect(self.reject)
        self.next.clicked.connect(self.advance)
        layout.addWidget(self.buttons)
        self.name.textChanged.connect(self.refresh)
        self.agree.toggled.connect(self.refresh)
        self.refresh()

    def refresh(self):
        self.next.setEnabled(bool(self.names.default_name()) if self.pages.currentIndex() == 0 else self.agree.isChecked())

    def advance(self):
        if not self.names.default_name():
            return
        if self.pages.currentIndex() == 0:
            self.pages.setCurrentIndex(1)
            self.next.setText("Agree and open Pat")
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
            return
        super().accept()


def ensure_onboarding(profile=None):
    profile = profile or UserProfile()
    if profile.ready:
        return True
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    return OnboardingDialog(profile).exec() == QDialog.Accepted


class ProfileDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.profile = UserProfile()
        self.setWindowTitle("Pat settings")
        self.setStyleSheet(STYLE)
        self.resize(560, 420)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.names = NameTable(self.profile)
        self.name = self.names.edit
        form.addRow("Your name", self.names)
        self.pronouns = pronoun_choice(self.profile.pronouns)
        form.addRow("Pat refers to you as", self.pronouns)
        self.country = QComboBox()
        self.country.addItem("Use full international numbers (+country code)", "")
        from phonenumbers import SUPPORTED_REGIONS
        for region in sorted(SUPPORTED_REGIONS):
            locale = QLocale("en_" + region)
            self.country.addItem(f"{QLocale.territoryToString(locale.territory())} ({region})", region)
        self.country.setCurrentIndex(max(0, self.country.findData(self.profile.country)))
        form.addRow("Country for local numbers", self.country)
        self.zone = QComboBox()
        self.zone.setEditable(True)
        self.zone.addItems(sorted(available_timezones()))
        self.zone.setCurrentText(self.profile.time_zone)
        form.addRow("Time zone", self.zone)
        self.dates = QComboBox()
        for value, title in DATE_FORMATS.items():
            self.dates.addItem(title, value)
        self.dates.setCurrentIndex(self.dates.findData(self.profile.date_format))
        form.addRow("Dates in reports", self.dates)
        self.phone = QComboBox()
        self.phone.addItem("Automatic (the phone connected last)", "")
        if self.profile.phone_device:
            self.phone.addItem(self.profile.values.get("phone_name") or "Selected phone", self.profile.phone_device)
            self.phone.setCurrentIndex(1)
        form.addRow("Phone", self.phone)
        self.find = QPushButton("Find paired phones")
        self.find.clicked.connect(self.find_phones)
        form.addRow("", self.find)
        layout.addLayout(form)
        self.problem = QLabel("The time zone is used unless a call names a different one.")
        self.problem.setWordWrap(True)
        layout.addWidget(self.problem)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.process = QProcess(self)
        self.process.finished.connect(self.phones_found)
        self.process.errorOccurred.connect(lambda _: self.find_failed())
        self.phone_timeout = QTimer(self, singleShot=True, interval=15000)
        self.phone_timeout.timeout.connect(lambda: (self.process.kill(), self.find_failed()))

    def find_phones(self):
        self.find.setEnabled(False)
        self.problem.setText("Looking for paired phones…")
        self.process.start("iphonecall", ["list-json"])
        self.phone_timeout.start()

    def find_failed(self):
        self.phone_timeout.stop()
        self.find.setEnabled(True)
        self.problem.setText("Could not list phones. Run setup.ps1 to build the updated phone tool.")

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
            self.problem.setText("Choose the phone to use. Its Bluetooth name may be anything.")
        except (ValueError, KeyError, TypeError):
            self.find_failed()

    def save(self):
        try:
            name, language, others = self.names.values()
            self.profile.save(name=name, name_language=language, names=others, pronouns=self.pronouns.currentData(), country=self.country.currentData(), time_zone=self.zone.currentText(),
                              date_format=self.dates.currentData(), phone_device=self.phone.currentData(), phone_name=self.phone.currentText())
        except (ValueError, KeyError, OSError) as error:
            self.problem.setText(str(error))
            return
        self.accept()

    def done(self, result):
        self.phone_timeout.stop()
        if hasattr(self, "process") and self.process.state() != QProcess.NotRunning:
            self.process.kill()
            self.process.waitForFinished(1000)
        super().done(result)
