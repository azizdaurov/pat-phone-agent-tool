"""Paper windows shared by first setup and the owner's settings."""
import os

from PySide6.QtCore import QEvent, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (QDialog, QFrame, QGraphicsDropShadowEffect, QHBoxLayout,
                              QLabel, QLayout, QPushButton, QVBoxLayout, QWidget)

HERE = os.path.dirname(os.path.abspath(__file__))
PAPER_WIDTH = 460
SHADOW = 12
PADDING = 20


def icon(name):
    return QIcon(os.path.join(HERE, "note", "icons", name + ".svg"))


_arrow = os.path.join(HERE, "note", "icons", "chevron-down.svg").replace("\\", "/")
_check = os.path.join(HERE, "note", "icons", "check.svg").replace("\\", "/")
STYLE = """
QDialog, QWidget { color: #3B2A1A; font-family: Georgia; font-size: 14px; background: transparent; }
QLabel#heading { font-size: 21px; font-weight: bold; }
QLabel#hint, QLabel#brand, QLabel#step, QLabel#status { color: #6B5238; font-size: 12px; }
QLabel#hint, QLabel#status { font-style: italic; }
QLabel#problem { color: #944A3F; font-size: 12px; }
QLabel#field-label { font-size: 13px; }
QFrame#separator { background: rgba(107,82,56,61); }
QLineEdit, QTextEdit, QComboBox { background: #F3E9D3; color: #3B2A1A; border: 1px solid #A98E67;
    border-radius: 11px; padding: 8px 10px; min-height: 20px; }
QLineEdit:focus, QTextEdit:focus, QComboBox:focus { border-color: #3B2A1A; }
QComboBox { padding-right: 30px; }
QComboBox QLineEdit { padding: 0; margin: 0; border: 0; border-radius: 0; background: transparent; min-height: 0; }
QComboBox:editable { padding-left: 5px; }  /* its typing field adds its own inset; this lines its text up with the other boxes */
QComboBox::drop-down { border: 0; width: 28px; }
QComboBox::down-arrow { image: url('__ARROW__'); width: 10px; height: 10px; }
QComboBox QAbstractItemView { background: #F3E9D3; color: #3B2A1A; border: 1px solid #A98E67;
    selection-background-color: #3B2A1A; selection-color: #F5ECD9; padding: 4px; }
QTextEdit { font-size: 12px; }
QCheckBox { font-size: 13px; spacing: 10px; }
QCheckBox::indicator { width: 16px; height: 16px; border: 1px solid #A98E67; border-radius: 3px; background: #F3E9D3; }
QCheckBox::indicator:checked { background: #3B2A1A; border-color: #3B2A1A; image: url('__CHECK__'); }
QPushButton { background: #F3E9D3; color: #3B2A1A; font-size: 13px; border: 1px solid #A98E67;
    border-radius: 17px; padding: 7px 14px; min-height: 18px; }
QPushButton:hover { background: #FBF4E4; }
QPushButton[tone='primary'] { background: #3B2A1A; color: #F5ECD9; border-color: #3B2A1A; }
QPushButton[tone='primary']:hover { background: #54402C; }
QPushButton[tone='quiet'] { background: transparent; border-color: transparent; }
QPushButton:disabled { background: #B9A27A; color: #F3E9D3; border-color: #B9A27A; }
QPushButton:focus { border-color: #3B2A1A; }
QPushButton#close-paper { padding: 0; min-height: 0; border: 0; border-radius: 12px;
    background: transparent; color: #6B5238; font-size: 20px; }
QPushButton#close-paper:hover { background: rgba(107,82,56,35); }
QPushButton#disclosure { font-size: 12px; border-radius: 16px; padding: 6px 12px; min-height: 18px; }
QScrollBar:vertical { background: transparent; width: 4px; margin: 2px 0; }
QScrollBar::handle:vertical { background: #B9A27A; border-radius: 2px; min-height: 24px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
""".replace("__ARROW__", _arrow).replace("__CHECK__", _check)


def label(text="", kind="field-label"):
    result = QLabel(text)
    result.setObjectName(kind)
    result.setTextFormat(Qt.PlainText)
    result.setWordWrap(True)
    return result


def rule(layout):
    line = QFrame()
    line.setObjectName("separator")
    line.setFixedHeight(1)
    layout.addWidget(line)


def field(layout, title, widget):
    layout.addWidget(label(title))
    layout.addSpacing(8)
    layout.addWidget(widget)


class PaperSurface(QWidget):
    def __init__(self):
        super().__init__()
        self.grain = QPixmap(os.path.join(HERE, "note", "paper-grain.png"))

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        area = QRectF(self.rect()).adjusted(.5, .5, -.5, -.5)
        path = QPainterPath()
        path.addRoundedRect(area, 20, 20)
        painter.fillPath(path, QColor("#E6D6B8"))
        painter.save()
        painter.setClipPath(path)
        painter.setOpacity(.26)
        painter.drawTiledPixmap(self.rect(), self.grain)
        painter.restore()
        painter.setPen(QPen(QColor("#CDB995"), 1))
        painter.drawPath(path)


class PaperDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowIcon(QIcon(os.path.join(HERE, "note", "icons", "pat-64.png")))
        self.setStyleSheet(STYLE)
        self.setFixedWidth(PAPER_WIDTH + SHADOW * 2)
        outer = QVBoxLayout(self)
        outer.setSizeConstraint(QLayout.SetNoConstraint)
        outer.setContentsMargins(SHADOW, SHADOW, SHADOW, 20)
        self.paper = PaperSurface()
        shadow = QGraphicsDropShadowEffect(self.paper)
        shadow.setBlurRadius(18)
        shadow.setOffset(0, 5)
        shadow.setColor(QColor(44, 30, 14, 75))
        self.paper.setGraphicsEffect(shadow)
        outer.addWidget(self.paper)
        self.paper_layout = QVBoxLayout(self.paper)
        self.paper_layout.setSizeConstraint(QLayout.SetNoConstraint)
        self.paper_layout.setContentsMargins(PADDING, 12, PADDING, 0)
        self.paper_layout.setSpacing(0)
        self.chrome = QWidget()
        chrome = QHBoxLayout(self.chrome)
        chrome.setContentsMargins(0, 0, 0, 0)
        self.brand = label("Pat", "brand")
        chrome.addWidget(self.brand)
        chrome.addStretch()
        self.close_button = QPushButton("×")
        self.close_button.setObjectName("close-paper")
        self.close_button.setAccessibleName("Close")
        self.close_button.setAutoDefault(False)
        self.close_button.setFixedSize(24, 24)
        self.close_button.clicked.connect(self.reject)
        chrome.addWidget(self.close_button)
        self.chrome.installEventFilter(self)
        self.brand.installEventFilter(self)
        self.paper_layout.addWidget(self.chrome)
        self.paper_layout.addSpacing(12)

    def eventFilter(self, watched, event):
        if watched in (self.chrome, self.brand) and event.type() == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            if self.windowHandle():
                self.windowHandle().startSystemMove()
            return True
        return super().eventFilter(watched, event)

    def fit_contents(self):
        self.paper_layout.invalidate()
        height = self.paper_layout.totalHeightForWidth(PAPER_WIDTH)
        if height < 0:
            height = self.paper_layout.sizeHint().height()
        self.paper.setFixedHeight(height)
        self.setFixedHeight(height + SHADOW + 20)

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(0, self.fit_contents)


class StepDots(QWidget):
    def __init__(self):
        super().__init__()
        self.current = 0
        self.setFixedSize(18, 8)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        for index in range(2):
            painter.setBrush(QColor("#3B2A1A" if index == self.current else "#B9A27A"))
            painter.drawEllipse(QRectF(index * 12, 1, 6, 6))


class Disclosure(QWidget):
    """A labeled, keyboard-accessible section that changes the paper window's height."""
    def __init__(self, title, description, dialog, opened=False, group=None):
        """group: a list shared by sections of which only one may be open, so the window stays short enough for a
        laptop screen (all three Settings sections open made it 850 pixels tall on an 816-pixel screen)."""
        super().__init__()
        self.dialog = dialog
        self.group = group
        if group is not None:
            group.append(self)
        column = QVBoxLayout(self)
        column.setSizeConstraint(QLayout.SetNoConstraint)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        rule(column)
        self.header = QWidget()
        row = QHBoxLayout(self.header)
        row.setContentsMargins(0, 8, 0, 8)
        row.setSpacing(12)
        words = QVBoxLayout()
        words.setSpacing(3)
        self.title = label(title)
        self.meta = label(description, "brand")
        words.addWidget(self.title)
        words.addWidget(self.meta)
        row.addLayout(words, 1)
        self.toggle_button = QPushButton()
        self.toggle_button.setObjectName("disclosure")
        self.toggle_button.setAutoDefault(False)
        self.toggle_button.setLayoutDirection(Qt.RightToLeft)
        self.toggle_button.setMinimumWidth(76)
        self.toggle_button.clicked.connect(lambda: self.set_open(not self.opened))
        row.addWidget(self.toggle_button)
        for widget in (self.header, self.title, self.meta):
            widget.installEventFilter(self)
        column.addWidget(self.header)
        self.content = QWidget()
        self.fields = QVBoxLayout(self.content)
        self.fields.setContentsMargins(0, 0, 0, 16)
        self.fields.setSpacing(0)
        column.addWidget(self.content)
        self.set_open(opened)

    def eventFilter(self, watched, event):
        if watched in (self.header, self.title, self.meta) and event.type() == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
            self.set_open(not self.opened)
            return True
        return super().eventFilter(watched, event)

    def set_open(self, opened):
        if opened and self.group:
            for other in self.group:
                if other is not self and other.opened:
                    other.set_open(False)
        self.opened = opened
        self.content.setVisible(opened)
        self.toggle_button.setText("Hide" if opened else "Edit")
        self.toggle_button.setIcon(icon("chevron-up" if opened else "chevron-down"))
        self.toggle_button.setAccessibleName(("Hide " if opened else "Edit ") + self.title.text())
        self.toggle_button.setProperty("expanded", opened)
        self.layout().invalidate()
        self.updateGeometry()
        QTimer.singleShot(0, self.dialog.fit_contents)
