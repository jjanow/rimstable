"""Main window: sidebar navigation, a status banner, and the pages."""
import time
from pathlib import Path

from PySide6.QtCore import QStandardPaths, Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (QButtonGroup, QFrame, QHBoxLayout, QLabel, QMainWindow, QPushButton,
                               QStackedWidget, QVBoxLayout, QWidget)

from .. import core, dds
from . import dialogs, theme
from .pages import ActivityPage, ModsPage, OverviewPage, SnapshotsPage, snap_time, when
from .tasks import CommandRunner, error_text, launch_detached, run_async
from .widgets import Banner, Pill, button, label, refresh_icons

NAV = [("overview", "Overview"), ("mods", "Mods"), ("snapshots", "Snapshots"), ("activity", "Activity")]
TITLES = {"freeze": "Freezing", "pull": "Pulling", "snap": "Taking a snapshot", "restore": "Restoring",
          "prune": "Pruning snapshots", "shortcut": "Creating a shortcut", "dds": "Encoding textures"}


def steam_problem():
    """A short explanation when the Steam side is missing (the Locations card has the paths)."""
    if not core.GAME_SRC.is_dir():
        return "RimWorld isn't installed in the Steam library"
    if not (core.CFG_SRC / "Config/ModsConfig.xml").is_file():
        return "Steam's RimWorld config wasn't found"
    return None


def load_state():
    """Everything the pages show except the (slower) Steam diff. Never writes anything."""
    st = {"manifest": None, "snapshots": [], "snap_error": None, "steam_game": None,
          "steam_error": steam_problem()}
    if core.MANIFEST.exists():
        st["manifest"] = core.load_manifest()
    try:
        st["snapshots"] = core.snapshots(init=False)
    except Exception as e:
        st["snap_error"] = error_text(e)
    if not st["steam_error"]:
        try:
            st["steam_game"] = core.game_info(core.GAME_SRC, core.CFG_SRC)
        except Exception as e:
            st["steam_error"] = error_text(e)
    return st


def load_dds():
    """DDS counts for both targets; a missing Steam side only blanks the Steam row."""
    out = {"stable": dds.summary(dds.STABLE)}
    if not steam_problem():
        out["steam"] = dds.summary(dds.STEAM)
    return out


def load_diff():
    problem = steam_problem()
    if problem:
        raise core.RimstableError(problem)
    return core.diff_report()


class MainWindow(QMainWindow):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.setWindowTitle("Rimstable")
        self.setWindowIcon(QIcon(str(core.ICON)))
        self.resize(1200, 780)
        self.setMinimumSize(980, 640)
        self.state, self.diff, self.diff_error = {}, None, None
        self.dds_info, self.dds_error = None, None
        self.pids, self.loading, self.reload_pending, self.polling = [], False, False, False
        self.generation = 0
        self.cmd_started = 0.0

        self.runner = CommandRunner(self)
        root = QWidget()
        self.setCentralWidget(root)
        lay = QHBoxLayout(root)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self._sidebar())

        content = QWidget(objectName="Content")
        cl = QVBoxLayout(content)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)
        bw = QWidget()
        bl = QVBoxLayout(bw)
        bl.setContentsMargins(28, 18, 28, 0)
        self.banner = Banner()
        self.banner.action_clicked.connect(lambda: self.go("activity"))
        bl.addWidget(self.banner)
        cl.addWidget(bw)
        self.banner_wrap = bw
        bw.hide()
        self.banner.visibility_changed.connect(bw.setVisible)

        self.pages = {"overview": OverviewPage(self), "mods": ModsPage(self),
                      "snapshots": SnapshotsPage(self), "activity": ActivityPage(self)}
        self.stack = QStackedWidget()
        for p in self.pages.values():
            self.stack.addWidget(p)
        cl.addWidget(self.stack, 1)
        lay.addWidget(content, 1)

        self.runner.started.connect(self._cmd_started)
        self.runner.output.connect(self._cmd_output)
        self.runner.finished.connect(self._cmd_finished)
        for i, (key, _) in enumerate(NAV):
            QShortcut(QKeySequence(f"Ctrl+{i + 1}"), self, activated=lambda k=key: self.go(k))
        QShortcut(QKeySequence.Refresh, self, activated=self.refresh)

        if hasattr(self.app.styleHints(), "colorSchemeChanged"):  # Qt >= 6.5; older Qt keeps the start theme
            self.app.styleHints().colorSchemeChanged.connect(self.retheme)
        self.poll_timer = QTimer(self, interval=3000, timeout=self.poll)
        self.poll_timer.start()
        refresh_icons(self)
        self.go("overview")
        self._update_controls()
        self.refresh()
        self.poll()

    # ------------------------------------------------------------ layout

    def _sidebar(self):
        side = QFrame(objectName="Sidebar")
        side.setFixedWidth(232)
        sl = QVBoxLayout(side)
        sl.setContentsMargins(16, 20, 16, 18)
        sl.setSpacing(4)
        brand = QHBoxLayout()
        brand.setSpacing(10)
        logo = QLabel()
        logo.setPixmap(QIcon(str(core.ICON)).pixmap(34, 34))
        names = QVBoxLayout()
        names.setSpacing(0)
        names.addWidget(QLabel("Rimstable", objectName="Brand"))
        names.addWidget(QLabel("Frozen RimWorld manager", objectName="BrandSub"))
        brand.addWidget(logo)
        brand.addLayout(names, 1)
        sl.addLayout(brand)
        sl.addSpacing(22)

        self.nav = QButtonGroup(self)
        self.nav_buttons = {}
        for i, (key, text) in enumerate(NAV):
            b = QPushButton(f"  {text}")
            b.setProperty("nav", True)
            b.setProperty("icon_name", key)
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setToolTip(f"{text}  (Ctrl+{i + 1})")
            b.clicked.connect(lambda _=False, k=key: self.go(k))
            self.nav.addButton(b)
            self.nav_buttons[key] = b
            sl.addWidget(b)
        bl = QHBoxLayout(self.nav_buttons["mods"])
        bl.setContentsMargins(0, 0, 10, 0)
        bl.addStretch(1)
        self.mods_badge = QLabel(objectName="Badge")
        self.mods_badge.setToolTip("Mods updated on Steam since the freeze")
        self.mods_badge.setFixedHeight(18)
        self.mods_badge.hide()
        bl.addWidget(self.mods_badge, 0, Qt.AlignVCenter)
        sl.addStretch(1)

        self.run_pill = Pill("checking…", "neutral")
        sl.addWidget(self.run_pill, 0, Qt.AlignLeft)
        sl.addSpacing(8)
        self.play_btn = button("Play", "play", "play", "Start the stable copy (rimstable launch)")
        self.play_btn.clicked.connect(self.play)
        sl.addWidget(self.play_btn)
        sl.addSpacing(6)
        self.version_lbl = label("", "faint", wrap=True)
        self.version_lbl.setAlignment(Qt.AlignCenter)
        sl.addWidget(self.version_lbl)
        return side

    def go(self, key):
        self.nav_buttons[key].setChecked(True)
        self.stack.setCurrentWidget(self.pages[key])

    def show_mods(self, status):
        self.go("mods")
        self.pages["mods"].show_filter(status)

    def retheme(self, *_):
        theme.apply(self.app)
        refresh_icons(self)
        for p in self.pages.values():
            p.retheme()
            for v in p.findChildren(QWidget):
                v.update()
        self._render()

    # ------------------------------------------------------------ data

    def refresh(self):
        if self.loading:
            self.reload_pending = True
            return
        self.loading = True
        self.generation += 1
        gen = self.generation
        self._update_controls()
        run_async(load_state, lambda st: self._state_loaded(gen, st), lambda e: self._state_failed(gen, e))

    def _state_loaded(self, gen, st):
        self.state = st
        self._render()
        if st.get("manifest"):
            run_async(load_dds, lambda d: self._dds_loaded(gen, d, None),
                      lambda e: self._dds_loaded(gen, None, e))
            run_async(load_diff, lambda d: self._diff_loaded(gen, d, None),
                      lambda e: self._diff_loaded(gen, None, e))
        else:
            self._diff_loaded(gen, None, None)

    def _state_failed(self, gen, msg):
        self.state = {"manifest": None, "snapshots": [], "snap_error": msg, "steam_game": None, "steam_error": msg}
        self.banner.show_state("error", "Couldn't read the stable copy", msg)
        self._diff_loaded(gen, None, msg)

    def _diff_loaded(self, gen, diff, err):
        if gen != self.generation:
            return
        self.diff, self.diff_error = diff, err
        self.loading = False
        self._render()
        if self.reload_pending:
            self.reload_pending = False
            self.refresh()

    def _dds_loaded(self, gen, info, err):
        if gen != self.generation:
            return
        self.dds_info, self.dds_error = info, err
        self.pages["overview"].update_dds(info, err)

    def _render(self):
        if not self.state:
            return
        for p in ("overview", "mods", "snapshots"):
            self.pages[p].update_state(self.state, self.diff, self.diff_error)
        n = len(self.diff["changed"]) if self.diff else 0
        self.mods_badge.setText(str(n))
        self.mods_badge.setVisible(n > 0)
        man = self.state.get("manifest")
        if man:
            g = man["game"]
            self.version_lbl.setText(f"RimWorld {g.get('revision') or g.get('version_txt')}")
        else:
            self.version_lbl.setText("Not frozen yet")
        self._update_controls()

    def poll(self):
        if self.polling:
            return
        self.polling = True
        run_async(core.rimworld_pids, self._pids, lambda _: self._pids([]))

    def _pids(self, pids):
        self.polling = False
        if pids != self.pids or self.run_pill.text() == "checking…":
            self.pids = pids
            if pids:
                self.run_pill.set("● RimWorld running", "ok")
                self.run_pill.setToolTip(f"pid {' '.join(pids)}")
            else:
                self.run_pill.set("● RimWorld not running", "neutral")
                self.run_pill.setToolTip("")
            self._update_controls()

    def _update_controls(self):
        busy = self.runner.busy
        running = bool(self.pids)
        can = not busy and not running
        reason = ("Wait for the current command to finish" if busy
                  else "Quit RimWorld first" if running else "")
        for p in ("overview", "mods", "snapshots"):
            self.pages[p].set_enabled(can, reason)
        # a diff taken while a command copies files would show a half-updated tree
        self.pages["overview"].refresh_btn.setEnabled(not busy and not self.loading)
        has_man = bool(self.state.get("manifest"))
        self.play_btn.setEnabled(can and has_man)
        self.play_btn.setText("Running" if running else "Play")
        self.play_btn.setToolTip(reason or ("" if has_man else "Freeze first") or
                                 "Start the stable copy (rimstable launch)")

    # ------------------------------------------------------------ commands

    def run(self, args):
        if not self.runner.run(args):
            self.banner.show_state("error", "Another command is still running")

    def _cmd_started(self, args):
        self.cmd_started = time.monotonic()
        self.cmd_args = args
        self.banner.show_state("busy", self._title(args) + "…", "Starting…")
        self.pages["activity"].started(args)
        self._update_controls()

    def _cmd_output(self, line):
        self.pages["activity"].line(line)
        if line.strip():
            self.banner.set_text(line.strip())

    def _cmd_finished(self, ok, msg):
        secs = time.monotonic() - self.cmd_started
        self.pages["activity"].finished(ok, secs)
        name = self._title(self.cmd_args)
        if ok:
            self.banner.show_state("ok", f"{name} finished", f"Took {secs:.0f}s.")
        else:
            self.banner.show_state("error", f"{name} failed", msg)
        self._update_controls()
        self.refresh()
        self.poll()

    def _title(self, args):
        if args[:2] == ["pull", "--all"]:
            return "Updating mods"
        if args[0] == "dds" and "--clean" in args:
            return "Removing generated DDS"
        return TITLES.get(args[0], args[0])

    def freeze(self):
        first = not self.state.get("manifest")
        d = dialogs.FreezeDialog(self, first)
        if d.exec():
            self.run(d.args())

    def encode_textures(self):
        d = dialogs.DdsDialog(self, self.dds_info)
        if d.exec():
            self.run(d.args())

    def take_snapshot(self):
        d = dialogs.SnapshotDialog(self)
        if d.exec():
            self.run(d.args())

    def pull(self, row):
        verb = "Update" if row["status"] == "update" else "Add"
        details = None
        if row["status"] == "new":
            details = "It isn't in the stable copy's mod list yet; enable it in the in-game mod manager afterwards."
        if dialogs.confirm(self, f"{verb} {row['name']}?",
                           f"Copies the current Steam version of {row['name']} into the stable copy. "
                           f"A “pre-pull” snapshot is taken first.",
                           f"Pull {row['name'][:40]}", icon_name="download", details=details):
            self.run(["pull", row["packageId"]])

    def update_all(self):
        changed = sorted((cur["name"] for _, cur in (self.diff or {}).get("changed", [])), key=str.lower)
        if not changed or self.runner.busy:
            return
        shown = changed[:10]
        more = f"\n…and {len(changed) - len(shown)} more" if len(changed) > len(shown) else ""
        if dialogs.confirm(self, f"Update {len(changed)} mod{'s' if len(changed) != 1 else ''}?",
                           "Copies the current Steam version of every stable mod that changed since the freeze. "
                           "One \u201cpre-pull all\u201d snapshot is taken first. The load order isn't changed, "
                           "and Workshop mods that aren't in the stable copy aren't added.",
                           f"Update {len(changed)}", icon_name="download", details="\n".join(shown) + more):
            self.run(["pull", "--all"])

    def restore(self, s):
        lbl = core.label_of(s) or "unlabelled"
        if dialogs.confirm(self, f"Restore snapshot {s['short_id']}?",
                           f"Rolls game/, userdata/ and manifest.json back to “{lbl}” from "
                           f"{when(snap_time(s))}. Files that aren't in that snapshot are deleted, including saves "
                           "made since.",
                           "Restore", tone="danger", icon_name="undo",
                           details=f"A “pre-restore {s['short_id']}” snapshot of the current state is "
                                   "taken first, so you can undo this."):
            self.run(["restore", s["id"]])

    def prune(self):
        d = dialogs.PruneDialog(self, self.state.get("snapshots") or [], core.label_of,
                                lambda s: when(snap_time(s)))
        if d.exec():
            self.run(d.args())

    def make_shortcut(self, gui):
        dest = core.desktop_dir() / core.shortcut_name(gui)
        args = ["shortcut"] + (["--gui"] if gui else [])
        if dest.exists():
            if not dialogs.confirm(self, "Replace the shortcut?", f"{dest} already exists.", "Replace",
                                   icon_name="shortcut"):
                return
            args.append("--force")
        self.run(args)

    def open_path(self, p):
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(p)))

    def play(self):
        if self.pids or self.runner.busy or not self.state.get("manifest"):
            return
        log_dir = Path(QStandardPaths.writableLocation(QStandardPaths.TempLocation)) / "rimstable"
        ok, err = launch_detached(log_dir)
        if not ok:
            self.banner.show_state("error", "Couldn't start RimWorld", "The launcher process failed to start.")
            return
        self.banner.show_state("ok", "Starting RimWorld…", "The stable copy is launching.")
        self.play_btn.setEnabled(False)
        QTimer.singleShot(3000, lambda: self._check_launch(err))
        for ms in (1500, 4000, 8000):
            QTimer.singleShot(ms, self.poll)

    def _check_launch(self, err):
        try:
            text = err.read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
        msg = [line[len("rimstable: "):] for line in text.splitlines() if line.startswith("rimstable: ")]
        if msg:
            self.banner.show_state("error", "Couldn't start RimWorld", "\n".join(msg))
        self._update_controls()

    def closeEvent(self, ev):
        if self.runner.busy and not dialogs.confirm(
                self, "A command is still running",
                f"{self._title(self.cmd_args)} hasn't finished. Closing now stops it partway "
                "through.", "Close anyway", tone="danger"):
            ev.ignore()
            return
        if self.runner.proc:
            self.runner.proc.kill()
            self.runner.proc.waitForFinished(3000)
        ev.accept()
