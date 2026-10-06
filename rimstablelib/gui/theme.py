"""Colors and the Qt stylesheet. Follows the OS light/dark setting; RIMSTABLE_THEME=dark|light overrides it."""
import os
from string import Template

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QGuiApplication, QPalette

DARK = {
    "bg": "#111318", "sidebar": "#0c0e12", "surface": "#171a20", "raised": "#1f232b", "hover": "#272c36",
    "border": "#262b34", "border_strong": "#353b47", "divider": "#1f232a",
    "text": "#e8eaef", "muted": "#939cab", "faint": "#5f6776",
    "accent": "#6ea8ff", "accent_hover": "#8bbaff", "on_accent": "#08111f", "accent_soft": "rgba(110,168,255,0.14)",
    "success": "#4cc495", "success_soft": "rgba(76,196,149,0.14)",
    "warning": "#eab55a", "warning_soft": "rgba(234,181,90,0.14)",
    "danger": "#f27066", "danger_soft": "rgba(242,112,102,0.14)",
    "neutral_soft": "rgba(147,156,171,0.14)", "scroll": "#2e3440",
}
LIGHT = {
    "bg": "#f4f5f7", "sidebar": "#eceef2", "surface": "#ffffff", "raised": "#ffffff", "hover": "#e6e9ee",
    "border": "#dde1e7", "border_strong": "#c7cdd6", "divider": "#eef0f3",
    "text": "#1a1e24", "muted": "#5b6574", "faint": "#9aa2ae",
    "accent": "#2d6be0", "accent_hover": "#245bc4", "on_accent": "#ffffff", "accent_soft": "rgba(45,107,224,0.10)",
    "success": "#1d8a5f", "success_soft": "rgba(29,138,95,0.10)",
    "warning": "#a86b12", "warning_soft": "rgba(200,130,20,0.12)",
    "danger": "#cc3b31", "danger_soft": "rgba(204,59,49,0.10)",
    "neutral_soft": "rgba(91,101,116,0.10)", "scroll": "#cfd4db",
}

current = dict(DARK)

QSS = Template("""
QMainWindow, QDialog { background: $bg; }
QWidget { color: $text; }
QWidget#Content, QStackedWidget, QScrollArea, QScrollArea > QWidget > QWidget { background: $bg; }
QFrame#Sidebar { background: $sidebar; border-right: 1px solid $border; }
QLabel#Brand { font-size: 16px; font-weight: 700; }
QLabel#BrandSub { color: $faint; font-size: 11px; }

QPushButton { background: $raised; border: 1px solid $border; border-radius: 8px; padding: 7px 14px; }
QPushButton:hover { background: $hover; border-color: $border_strong; }
QPushButton:pressed { background: $border; }
QPushButton:disabled { color: $faint; background: transparent; border-color: $border; }
QPushButton::menu-indicator { image: none; width: 0; }
QPushButton[kind="primary"] { background: $accent; color: $on_accent; border: 1px solid $accent; font-weight: 600; }
QPushButton[kind="primary"]:hover { background: $accent_hover; border-color: $accent_hover; }
QPushButton[kind="primary"]:disabled { background: $raised; color: $faint; border-color: $border; }
QPushButton[kind="danger"] { background: $danger; color: #ffffff; border: 1px solid $danger; font-weight: 600; }
QPushButton[kind="danger"]:disabled { background: $raised; color: $faint; border-color: $border; }
QPushButton[kind="ghost"] { background: transparent; border: 1px solid transparent; color: $muted; }
QPushButton[kind="ghost"]:hover { background: $hover; color: $text; }
QPushButton[kind="link"] { background: transparent; border: none; padding: 2px 0; color: $accent; font-weight: 600;
                          text-align: left; }
QPushButton[kind="link"]:hover { color: $accent_hover; text-decoration: underline; }
QPushButton[kind="play"] { background: $accent; color: $on_accent; border: none; border-radius: 10px;
                           padding: 12px 16px; font-size: 15px; font-weight: 700; }
QPushButton[kind="play"]:hover { background: $accent_hover; }
QPushButton[kind="play"]:disabled { background: $raised; color: $faint; }
QPushButton[nav="true"] { text-align: left; padding: 9px 12px; border: none; border-radius: 8px;
                          background: transparent; color: $muted; font-weight: 500; }
QPushButton[nav="true"]:hover { background: $hover; color: $text; }
QPushButton[nav="true"]:checked { background: $accent_soft; color: $text; font-weight: 600; }
QPushButton[seg="true"] { background: transparent; border: 1px solid transparent; border-radius: 7px;
                          padding: 5px 12px; color: $muted; }
QPushButton[seg="true"]:hover { color: $text; }
QPushButton[seg="true"]:checked { background: $raised; border-color: $border_strong; color: $text; font-weight: 600; }
QFrame#Segmented { background: $surface; border: 1px solid $border; border-radius: 9px; }

QFrame#Card { background: $surface; border: 1px solid $border; border-radius: 12px; }
QFrame#Divider { background: $divider; max-height: 1px; min-height: 1px; border: none; }
QLabel[role="h1"] { font-size: 22px; font-weight: 700; }
QLabel[role="h2"] { font-size: 14px; font-weight: 600; }
QLabel[role="muted"] { color: $muted; }
QLabel[role="faint"] { color: $faint; }
QLabel[role="eyebrow"] { color: $muted; font-size: 11px; font-weight: 600; }
QLabel[role="stat"] { font-size: 26px; font-weight: 700; }
QLabel[role="mono"] { color: $muted; }
QLabel[tone="ok"] { color: $success; }
QLabel[tone="warn"] { color: $warning; }
QLabel[tone="danger"] { color: $danger; }
QLabel[pill] { border-radius: 10px; padding: 3px 10px; font-size: 12px; font-weight: 600; }
QLabel[pill="ok"] { background: $success_soft; color: $success; }
QLabel[pill="warn"] { background: $warning_soft; color: $warning; }
QLabel[pill="danger"] { background: $danger_soft; color: $danger; }
QLabel[pill="neutral"] { background: $neutral_soft; color: $muted; }
QLabel[pill="accent"] { background: $accent_soft; color: $accent; }
QLabel#Badge { background: $accent; color: $on_accent; border-radius: 9px; padding: 1px 7px; font-size: 11px; font-weight: 700; }

QFrame#Banner { border-radius: 10px; border: 1px solid $border; background: $surface; }
QFrame#Banner[kind="busy"] { background: $accent_soft; border-color: transparent; }
QFrame#Banner[kind="ok"] { background: $success_soft; border-color: transparent; }
QFrame#Banner[kind="error"] { background: $danger_soft; border-color: transparent; }

QLineEdit, QPlainTextEdit { background: $raised; border: 1px solid $border; border-radius: 8px; padding: 7px 10px;
                            selection-background-color: $accent; selection-color: $on_accent; }
QLineEdit:focus { border-color: $accent; }
QPlainTextEdit#Log { background: $surface; border-radius: 12px; padding: 10px; }

QTableView { background: $surface; border: 1px solid $border; border-radius: 12px; gridline-color: transparent;
             selection-background-color: $accent_soft; selection-color: $text; }
QTableView::item { padding: 0 10px; border-bottom: 1px solid $divider; }
QTableView::item:selected { background: $accent_soft; color: $text; }
QHeaderView { background: transparent; }
QHeaderView::section { background: $surface; color: $muted; border: none; border-bottom: 1px solid $border;
                       padding: 9px 10px; font-weight: 600; font-size: 12px; }
QHeaderView::section:first { border-top-left-radius: 12px; }
QHeaderView::section:last { border-top-right-radius: 12px; }
QTableCornerButton::section { background: $surface; border: none; }

QScrollBar:vertical { background: transparent; width: 11px; margin: 3px; }
QScrollBar:horizontal { background: transparent; height: 11px; margin: 3px; }
QScrollBar::handle { background: $scroll; border-radius: 4px; min-height: 28px; min-width: 28px; }
QScrollBar::handle:hover { background: $faint; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: none; }

QProgressBar { background: $raised; border: none; border-radius: 3px; max-height: 6px; min-height: 6px; }
QProgressBar::chunk { background: $accent; border-radius: 3px; }
QProgressBar[tone="ok"]::chunk { background: $success; }
QProgressBar[tone="warn"]::chunk { background: $warning; }

QCheckBox { spacing: 9px; }
QToolTip { background: $raised; color: $text; border: 1px solid $border_strong; padding: 6px 8px; }
QMenu { background: $raised; border: 1px solid $border_strong; padding: 6px; }
QMenu::item { padding: 7px 18px 7px 10px; border-radius: 6px; }
QMenu::item:selected { background: $hover; }
QMenu::icon { padding-left: 8px; }
""")


def is_dark():
    forced = os.environ.get("RIMSTABLE_THEME", "").lower()
    if forced in ("dark", "light"):
        return forced == "dark"
    hints = QGuiApplication.styleHints()
    if hasattr(hints, "colorScheme"):  # Qt >= 6.5
        scheme = hints.colorScheme()
        if scheme != Qt.ColorScheme.Unknown:
            return scheme == Qt.ColorScheme.Dark
    return QGuiApplication.palette().color(QPalette.Window).lightness() < 128


def apply(app):
    """Apply the light or dark theme to the whole app; returns the tokens now in use."""
    current.clear()
    current.update(DARK if is_dark() else LIGHT)
    c = {k: QColor(v) for k, v in current.items() if v.startswith("#")}
    pal = QPalette()
    for role, key in [(QPalette.Window, "bg"), (QPalette.WindowText, "text"), (QPalette.Base, "raised"),
                      (QPalette.AlternateBase, "surface"), (QPalette.Text, "text"), (QPalette.Button, "raised"),
                      (QPalette.ButtonText, "text"), (QPalette.Highlight, "accent"),
                      (QPalette.HighlightedText, "on_accent"), (QPalette.ToolTipBase, "raised"),
                      (QPalette.ToolTipText, "text"), (QPalette.PlaceholderText, "faint"), (QPalette.Link, "accent"),
                      (QPalette.Mid, "border_strong"), (QPalette.Dark, "border_strong"), (QPalette.Light, "hover"),
                      (QPalette.Midlight, "border")]:
        pal.setColor(role, c[key])
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        pal.setColor(QPalette.Disabled, role, c["faint"])
    app.setPalette(pal)
    app.setStyleSheet(QSS.substitute(current))
    return current


def repolish(w):
    """Re-evaluate the stylesheet after changing a dynamic property used in a selector."""
    w.style().unpolish(w)
    w.style().polish(w)
