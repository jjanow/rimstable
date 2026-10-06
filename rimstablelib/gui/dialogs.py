"""Modal dialogs. The CLI never asks before acting, so every destructive step is confirmed here."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QDialog, QHBoxLayout, QLabel, QLineEdit, QSpinBox, QVBoxLayout

from . import icons, theme
from .widgets import button, label, refresh_icons, set_prop


class Dialog(QDialog):
    def __init__(self, parent, title, icon_name=None, tone="accent", width=480):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(width)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 22, 24, 20)
        outer.setSpacing(14)
        head = QHBoxLayout()
        head.setSpacing(12)
        if icon_name:
            ic = QLabel()
            color = {"accent": "accent", "danger": "danger", "warn": "warning"}[tone]
            ic.setPixmap(icons.pixmap(icon_name, theme.current[color], 22))
            head.addWidget(ic, 0, Qt.AlignVCenter)
        self.heading = label(title, "h2")
        self.heading.setStyleSheet("font-size: 17px;")
        head.addWidget(self.heading, 1)
        outer.addLayout(head)
        self.body = QVBoxLayout()
        self.body.setSpacing(10)
        outer.addLayout(self.body)
        outer.addSpacing(6)
        self.buttons = QHBoxLayout()
        self.buttons.addStretch(1)
        self.cancel = button("Cancel")
        self.cancel.clicked.connect(self.reject)
        self.buttons.addWidget(self.cancel)
        outer.addLayout(self.buttons)

    def add_ok(self, text, kind="primary", icon=None):
        self.ok = button(text, kind, icon)
        self.ok.setDefault(True)
        self.ok.clicked.connect(self.accept)
        self.buttons.addWidget(self.ok)
        refresh_icons(self)
        return self.ok


def confirm(parent, title, text, ok_text, tone="accent", icon_name="alert", details=None):
    d = Dialog(parent, title, icon_name, tone)
    d.body.addWidget(label(text, wrap=True))
    if details:
        d.body.addWidget(label(details, "muted", wrap=True))
    d.add_ok(ok_text, "danger" if tone == "danger" else "primary")
    return d.exec() == QDialog.Accepted


class FreezeDialog(Dialog):
    def __init__(self, parent, first):
        super().__init__(parent, "Freeze from Steam" if first else "Refreeze from Steam", "snow", width=540)
        if first:
            text = ("Copies the Steam game, every active Workshop mod, and your config and saves into the "
                    "stable folder, then takes a snapshot.")
        else:
            text = ("Takes a snapshot, then brings the game and mods up to date with Steam, removes mods that are "
                    "no longer active and takes Steam's load order. Stable saves and existing mod settings are kept.")
        self.body.addWidget(label(text, "muted", wrap=True))
        self.body.addSpacing(4)
        self.body.addWidget(label("Snapshot label", "eyebrow"))
        self.label = QLineEdit(placeholderText="first freeze" if first else "refreeze")
        self.body.addWidget(self.label)
        self.body.addSpacing(4)
        self.userdata = QCheckBox("Replace stable config and saves with Steam's")
        self.warn = label("Your stable saves and settings will be overwritten. They stay in the "
                          "pre-refreeze snapshot if you need them back.", wrap=True)
        set_prop(self.warn, "tone", "danger")
        self.warn.hide()
        self.userdata.toggled.connect(self._userdata_toggled)
        if not first:
            self.body.addWidget(self.userdata)
            self.body.addWidget(self.warn)
        self.allow_missing = QCheckBox("Freeze even if some active mods aren't on disk")
        self.allow_missing.setToolTip("Unsubscribed or still downloading. Without this, freeze stops and lists them.")
        self.force = QCheckBox("Skip the “Steam is mid-update” check")
        self.body.addWidget(self.allow_missing)
        self.body.addWidget(self.force)
        self.add_ok("Freeze" if first else "Refreeze", icon="snow")

    def _userdata_toggled(self, on):
        self.warn.setVisible(on)
        set_prop(self.ok, "kind", "danger" if on else "primary")
        self.ok.setText("Refreeze and replace saves" if on else "Refreeze")
        refresh_icons(self)
        self.adjustSize()

    def args(self):
        a = ["freeze"]
        if self.userdata.isChecked():
            a.append("--userdata")
        if self.allow_missing.isChecked():
            a.append("--allow-missing")
        if self.force.isChecked():
            a.append("--force")
        if self.label.text().strip():
            a += ["--label", self.label.text().strip()]
        return a


class SnapshotDialog(Dialog):
    def __init__(self, parent):
        super().__init__(parent, "Take a snapshot", "camera")
        self.body.addWidget(label("Saves the current game/, userdata/ and manifest.json so you can roll back to "
                                  "this point later.", "muted", wrap=True))
        self.body.addWidget(label("Label", "eyebrow"))
        self.label = QLineEdit(placeholderText="manual")
        self.body.addWidget(self.label)
        self.add_ok("Take snapshot", icon="camera")

    def args(self):
        t = self.label.text().strip()
        return ["snap"] + (["--label", t] if t else [])


class PruneDialog(Dialog):
    def __init__(self, parent, snaps, label_of, when):
        super().__init__(parent, "Prune snapshots", "trash", "danger")
        self.snaps, self.label_of, self.when = snaps, label_of, when
        self.body.addWidget(label("Deletes every snapshot except the newest ones, by time and whatever their "
                                  "label, and frees their disk space. This can't be undone.", "muted", wrap=True))
        row = QHBoxLayout()
        row.addWidget(label("Keep the newest"))
        self.keep = QSpinBox()
        self.keep.setRange(1, max(1, len(snaps)))
        self.keep.setValue(min(20, len(snaps)) if len(snaps) > 20 else max(1, len(snaps) - 1))
        self.keep.setMinimumWidth(80)
        row.addWidget(self.keep)
        row.addWidget(label("snapshots"))
        row.addStretch(1)
        self.body.addLayout(row)
        self.summary = label("", wrap=True)
        self.summary.setTextFormat(Qt.RichText)
        self.body.addWidget(self.summary)
        self.add_ok("Delete snapshots", "danger", "trash")
        self.keep.valueChanged.connect(self._update)
        self._update()

    def _update(self):
        doomed = self.snaps[:max(0, len(self.snaps) - self.keep.value())]
        self.ok.setEnabled(bool(doomed))
        if not doomed:
            self.summary.setText("Nothing to delete.")
            return
        t = theme.current
        names = [f"{self.when(s)} · {self.label_of(s) or '—'}" for s in doomed[:6]]
        more = len(doomed) - len(names)
        self.summary.setText(
            f"<b style='color:{t['danger']}'>Deletes {len(doomed)} of {len(self.snaps)}</b>, oldest first:<br>"
            f"<span style='color:{t['muted']}'>" + "<br>".join(names) + (f"<br>…and {more} more" if more else "")
            + "</span>")

    def args(self):
        return ["prune", "--keep", str(self.keep.value())]
