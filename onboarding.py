"""Name first, then a required Terms of Use checkbox. No phone or model starts here."""
import json
from zoneinfo import available_timezones

from PySide6.QtCore import QLocale, QProcess, QTimer
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                              QFormLayout, QLabel, QLineEdit, QPushButton,
                              QStackedWidget, QTextEdit, QVBoxLayout, QWidget)

from user_profile import DATE_FORMATS, TERMS_TEXT, UserProfile

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
        self.name = QLineEdit(profile.name)
        self.name.setObjectName("owner-name")
        self.name.setPlaceholderText("Your name")
        self.name.setMaxLength(100)
        name_layout.addWidget(self.name)
        name_layout.addWidget(QLabel("Pat will use this name when introducing your assistant."))
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
        self.next.setEnabled(bool(self.name.text().strip()) if self.pages.currentIndex() == 0 else self.agree.isChecked())

    def advance(self):
        if not self.name.text().strip():
            return
        if self.pages.currentIndex() == 0:
            self.pages.setCurrentIndex(1)
            self.next.setText("Agree and open Pat")
            self.refresh()
            return
        self.accept()

    def accept(self):
        if self.pages.currentIndex() != 1 or not self.agree.isChecked() or not self.name.text().strip():
            return
        try:
            self.profile.save(name=self.name.text())
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
        self.resize(500, 400)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.name = QLineEdit(self.profile.name)
        self.name.setMaxLength(100)
        form.addRow("Your name", self.name)
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
        self.phone.addItem("Automatic (only when one phone is paired)", "")
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
            self.phone.addItem("Automatic (only when one phone is paired)", "")
            for phone in choices:
                self.phone.addItem(phone["name"], phone["id"])
            self.phone.setCurrentIndex(max(0, self.phone.findData(selected)))
            self.problem.setText("Choose the phone to use. Its Bluetooth name may be anything.")
        except (ValueError, KeyError, TypeError):
            self.find_failed()

    def save(self):
        try:
            self.profile.save(name=self.name.text(), country=self.country.currentData(), time_zone=self.zone.currentText(),
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
