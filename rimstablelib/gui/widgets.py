"""Small building blocks shared by the pages."""
from PySide6.QtCore import QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter
from PySide6.QtWidgets import (QButtonGroup, QFrame, QHBoxLayout, QLabel, QProgressBar, QPushButton,
                               QSizePolicy, QStyle, QStyledItemDelegate, QVBoxLayout, QWidget)

from . import icons, theme


def label(text="", role=None, wrap=False, select=False):
    w = QLabel(text)
    if role:
        w.setProperty("role", role)
    if wrap:
        w.setWordWrap(True)
    if select:
        w.setTextInteractionFlags(Qt.TextSelectableByMouse)
    return w


def set_prop(w, name, value):
    if w.property(name) != value:
        w.setProperty(name, value)
        theme.repolish(w)


def button(text, kind=None, icon=None, tooltip=None):
    b = QPushButton(text)
    if kind:
        b.setProperty("kind", kind)
    if icon:
        b.setProperty("icon_name", icon)
    if tooltip:
        b.setToolTip(tooltip)
    b.setCursor(Qt.PointingHandCursor)
    return b


def refresh_icons(root):
    """(Re)draw the icon of every button under root that names one, in colors that suit its kind."""
    t = theme.current
    for b in root.findChildren(QPushButton):
        name = b.property("icon_name")
        if not name:
            continue
        kind = b.property("kind")
        if kind in ("primary", "play"):
            color = t["on_accent"]
        elif kind == "danger":
            color = "#ffffff"
        elif b.property("nav"):
            color = t["muted"]
        else:
            color = t["text"]
        size = 20 if kind == "play" else 16 if not b.property("nav") else 18
        b.setIcon(icons.icon(name, color, size, on_color=t["accent"] if b.property("nav") else None,
                             disabled_color=t["faint"]))
        b.setIconSize(QSize(size, size))


def divider():
    f = QFrame()
    f.setObjectName("Divider")
    return f


class Card(QFrame):
    def __init__(self, title=None, parent=None, margins=18, spacing=10):
        super().__init__(parent)
        self.setObjectName("Card")
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(margins, margins - 2, margins, margins)
        self.body.setSpacing(spacing)
        self.header = None
        if title:
            self.header = QHBoxLayout()
            self.header.setSpacing(8)
            self.title = label(title, "h2")
            self.header.addWidget(self.title)
            self.header.addStretch(1)
            self.body.addLayout(self.header)


class Pill(QLabel):
    def __init__(self, text="", tone="neutral"):
        super().__init__(text)
        self.setProperty("pill", tone)
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)

    def set(self, text, tone):
        self.setText(text)
        set_prop(self, "pill", tone)


class StatCard(Card):
    """Eyebrow title, a big value, a caption, and optionally a progress bar or link button."""
    def __init__(self, eyebrow, progress=False):
        super().__init__(margins=16, spacing=4)
        self.setMinimumWidth(170)
        self.eyebrow = label(eyebrow.upper(), "eyebrow")
        self.value = label("—", "stat")
        self.caption = label("", "muted", wrap=True)
        self.body.addWidget(self.eyebrow)
        self.body.addWidget(self.value)
        self.bar = None
        if progress:
            self.bar = QProgressBar()
            self.bar.setTextVisible(False)
            self.body.addSpacing(4)
            self.body.addWidget(self.bar)
        self.body.addWidget(self.caption)
        self.body.addStretch(1)

    def set(self, value, caption="", tone=None, progress=None):
        self.value.setText(value)
        set_prop(self.value, "tone", tone or "")
        self.caption.setText(caption)
        if self.bar is not None and progress is not None:
            done, total = progress
            self.bar.setRange(0, max(total, 1))
            self.bar.setValue(done)
            set_prop(self.bar, "tone", "ok" if done == total else "warn")


class ElidedLabel(QLabel):
    """One-line label that shortens its text with an ellipsis to fit, showing the full text as a tooltip."""
    def __init__(self, mode=Qt.ElideMiddle):
        super().__init__()
        self._full, self._mode = "", mode
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.setMinimumWidth(60)

    def set_full_text(self, text):
        self._full = text
        self.setToolTip(text)
        self._elide()

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._elide()

    def _elide(self):
        self.setText(self.fontMetrics().elidedText(self._full, self._mode, max(self.width(), 10)))


class Banner(QFrame):
    """Inline status strip: busy (with progress), ok (auto-hides) or error (stays until closed)."""
    action_clicked = Signal()
    visibility_changed = Signal(bool)

    def __init__(self):
        super().__init__()
        self.setObjectName("Banner")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 10, 10, 10)
        lay.setSpacing(12)
        self.icon = QLabel()
        self.icon.setFixedSize(18, 18)
        col = QVBoxLayout()
        col.setSpacing(4)
        self.title = label("", "h2")
        self.text = label("", "muted", wrap=True, select=True)
        self.bar = QProgressBar()
        self.bar.setRange(0, 0)
        self.bar.setTextVisible(False)
        col.addWidget(self.title)
        col.addWidget(self.text)
        col.addWidget(self.bar)
        self.action = button("View log", "ghost")
        self.action.clicked.connect(self.action_clicked)
        self.close_btn = button("", "ghost", "x", "Dismiss")
        self.close_btn.setFixedWidth(34)
        self.close_btn.clicked.connect(self.hide)
        lay.addWidget(self.icon, 0, Qt.AlignTop)
        lay.addLayout(col, 1)
        lay.addWidget(self.action, 0, Qt.AlignTop)
        lay.addWidget(self.close_btn, 0, Qt.AlignTop)
        self._timer = QTimer(self, singleShot=True, interval=7000, timeout=self.hide)
        self.hide()

    def setVisible(self, visible):
        super().setVisible(visible)
        self.visibility_changed.emit(visible)

    def show_state(self, kind, title, text=""):
        self._timer.stop()
        set_prop(self, "kind", kind)
        t = theme.current
        name, color = {"busy": ("refresh", t["accent"]), "ok": ("check", t["success"]),
                       "error": ("alert", t["danger"])}[kind]
        self.icon.setPixmap(icons.pixmap(name, color, 18))
        self.title.setText(title)
        self.set_text(text)
        self.bar.setVisible(kind == "busy")
        self.close_btn.setVisible(kind != "busy")
        refresh_icons(self)
        self.show()
        if kind == "ok":
            self._timer.start()

    def set_text(self, text):
        self.text.setText(text)
        self.text.setVisible(bool(text))


class EmptyState(QWidget):
    def __init__(self, icon_name, title, text, action=None):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 48, 24, 48)
        lay.setSpacing(10)
        lay.addStretch(1)
        self.icon_name = icon_name
        self.icon = QLabel(alignment=Qt.AlignCenter)
        self.title = label(title, "h2")
        self.title.setAlignment(Qt.AlignCenter)
        self.text = label(text, "muted", wrap=True)
        self.text.setAlignment(Qt.AlignCenter)
        self.text.setFixedWidth(520)
        lay.addWidget(self.icon)
        lay.addWidget(self.title)
        lay.addWidget(self.text, 0, Qt.AlignHCenter)
        if action:
            lay.addSpacing(8)
            lay.addWidget(action, 0, Qt.AlignHCenter)
        lay.addStretch(1)
        self.retheme()

    def set_text(self, title, text):
        self.title.setText(title)
        self.text.setText(text)
        self._fit()

    def _fit(self):
        # stacked layouts don't pass height-for-width down, so size the wrapped text explicitly
        self.text.ensurePolished()
        self.text.setMinimumHeight(self.text.heightForWidth(self.text.width()))

    def retheme(self):
        self.icon.setPixmap(icons.pixmap(self.icon_name, theme.current["faint"], 40, stroke=1.6))
        self._fit()


class Segmented(QFrame):
    """A row of mutually exclusive filter buttons."""
    changed = Signal(str)

    def __init__(self, options):
        super().__init__()
        self.setObjectName("Segmented")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(3, 3, 3, 3)
        lay.setSpacing(2)
        self.group = QButtonGroup(self)
        self.buttons = {}
        for key, text in options:
            b = QPushButton(text)
            b.setProperty("seg", True)
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, k=key: self.changed.emit(k))
            self.group.addButton(b)
            self.buttons[key] = b
            lay.addWidget(b)
        next(iter(self.buttons.values())).setChecked(True)

    def set_text(self, key, text):
        self.buttons[key].setText(text)

    def select(self, key):
        self.buttons[key].setChecked(True)
        self.changed.emit(key)


class PillDelegate(QStyledItemDelegate):
    """Draws a cell as a small rounded pill; the model gives the tone via Qt.UserRole + 1."""
    TONES = {"ok": ("success", "success_soft"), "warn": ("warning", "warning_soft"),
             "danger": ("danger", "danger_soft"), "accent": ("accent", "accent_soft"),
             "neutral": ("muted", "neutral_soft")}

    def paint(self, p, opt, idx):
        self.initStyleOption(opt, idx)
        text = opt.text
        opt.text = ""
        opt.widget.style().drawControl(QStyle.CE_ItemViewItem, opt, p, opt.widget)
        if not text:
            return
        fg_key, bg_key = self.TONES.get(idx.data(Qt.UserRole + 1) or "neutral", self.TONES["neutral"])
        fg, bg = QColor(theme.current[fg_key]), qcolor(theme.current[bg_key])
        f = QFont(opt.font)
        f.setPointSizeF(f.pointSizeF() * 0.9)
        f.setWeight(QFont.DemiBold)
        fm = QFontMetrics(f)
        w, h = fm.horizontalAdvance(text) + 18, fm.height() + 6
        r = QRectF(opt.rect.x() + 10, opt.rect.center().y() - h / 2 + 0.5, w, h)
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(bg)
        p.drawRoundedRect(r, h / 2, h / 2)
        p.setPen(fg)
        p.setFont(f)
        p.drawText(r, Qt.AlignCenter, text)
        p.restore()


def qcolor(css):
    """QColor from '#rrggbb' or 'rgba(r,g,b,a)' with a 0..1 alpha."""
    if css.startswith("rgba"):
        r, g, b, a = (float(x) for x in css[5:-1].split(","))
        return QColor(int(r), int(g), int(b), int(a * 255))
    return QColor(css)
