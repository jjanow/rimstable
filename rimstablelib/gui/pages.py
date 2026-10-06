"""The four pages of the main window. Pages only display state and call back into the window for actions."""
import datetime as dt

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt
from PySide6.QtGui import QColor, QFontDatabase
from PySide6.QtWidgets import (QAbstractItemView, QGridLayout, QHBoxLayout, QHeaderView, QLineEdit, QMenu,
                               QPlainTextEdit, QScrollArea, QStackedLayout, QTableView, QVBoxLayout, QWidget)

from .. import core
from . import theme
from .widgets import Card, ElidedLabel, EmptyState, Pill, PillDelegate, Segmented, StatCard, button, label

SORT_ROLE = Qt.UserRole
TONE_ROLE = Qt.UserRole + 1


def when(t):
    """Friendly local time: 'today 08:30', 'yesterday 08:30', '5 Oct 08:30', '5 Oct 2025'."""
    if t is None:
        return "—"
    now = dt.datetime.now()
    if t.date() == now.date():
        return f"today {t:%H:%M}"
    if t.date() == now.date() - dt.timedelta(days=1):
        return f"yesterday {t:%H:%M}"
    if t.year == now.year:
        return f"{t.day} {t:%b %H:%M}"
    return f"{t.day} {t:%b %Y}"


def parse_time(s):
    try:
        return dt.datetime.fromisoformat(s[:19])
    except (TypeError, ValueError):
        return None


def snap_time(s):
    return parse_time(s["time"])


class Page(QWidget):
    """Title row with actions on the right, then the page body."""
    def __init__(self, win, title, subtitle=""):
        super().__init__()
        self.win = win
        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 24, 28, 24)
        outer.setSpacing(18)
        head = QHBoxLayout()
        head.setSpacing(8)
        col = QVBoxLayout()
        col.setSpacing(2)
        self.title = label(title, "h1")
        self.subtitle = label(subtitle, "muted")
        col.addWidget(self.title)
        col.addWidget(self.subtitle)
        head.addLayout(col, 1)
        self.actions = QHBoxLayout()
        self.actions.setSpacing(8)
        head.addLayout(self.actions)
        outer.addLayout(head)
        self.body = QVBoxLayout()
        self.body.setSpacing(16)
        outer.addLayout(self.body, 1)

    def retheme(self):
        for e in self.findChildren(EmptyState):
            e.retheme()


# ---------------------------------------------------------------- overview

class OverviewPage(Page):
    def __init__(self, win):
        super().__init__(win, "Overview")
        self.refresh_btn = button("Refresh", None, "refresh", "Re-read the stable copy and the Steam install")
        self.refresh_btn.clicked.connect(win.refresh)
        self.actions.addWidget(self.refresh_btn)

        self.stack = QStackedLayout()
        self.body.addLayout(self.stack, 1)

        # first run: nothing frozen yet
        self.freeze_first = button("Freeze from Steam…", "primary", "snow")
        self.freeze_first.clicked.connect(win.freeze)
        empty = EmptyState(
            "snow", "No stable copy yet",
            "Freezing copies the Steam game, every active Workshop mod, and your config and saves into the "
            "stable folder listed below. Steam can then update freely; the stable copy only changes when you "
            "say so.",
            self.freeze_first)
        first = QWidget()
        fl = QVBoxLayout(first)
        fl.setContentsMargins(0, 0, 0, 0)
        empty_card = Card()
        empty_card.body.addWidget(empty)
        fl.addWidget(empty_card, 1)
        self.first_locations = self._locations_card()
        fl.addWidget(self.first_locations)
        self.stack.addWidget(first)

        # normal: dashboard
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        dash = QWidget()
        scroll.setWidget(dash)
        dl = QVBoxLayout(dash)
        dl.setContentsMargins(0, 0, 4, 0)
        dl.setSpacing(16)

        self.stats = QGridLayout()
        self.stats.setSpacing(14)
        self.s_game = StatCard("Game build")
        self.s_updates = StatCard("Mod updates on Steam")
        self.s_support = StatCard("Version support", progress=True)
        self.s_snaps = StatCard("Snapshots")
        self.stat_cols = 0
        self._layout_stats(4)
        self.review_btn = button("Review →", "link")
        self.review_btn.clicked.connect(lambda: win.show_mods("update"))
        self.update_all_btn = button("Update all", "link", tooltip="Pull every changed mod from Steam")
        self.update_all_btn.clicked.connect(win.update_all)
        links = QHBoxLayout()
        links.setSpacing(18)
        links.addWidget(self.update_all_btn)
        links.addWidget(self.review_btn)
        links.addStretch(1)
        self.s_updates.body.addLayout(links)
        self.snaps_btn = button("Manage snapshots →", "link")
        self.snaps_btn.clicked.connect(lambda: win.go("snapshots"))
        self.s_snaps.body.addWidget(self.snaps_btn, 0, Qt.AlignLeft)
        dl.addLayout(self.stats)

        row = QHBoxLayout()
        row.setSpacing(14)
        self.load_card = Card("Load order")
        self.load_pill = Pill()
        self.load_card.header.addWidget(self.load_pill)
        self.load_text = label("", "muted", wrap=True)
        self.load_list = label("", wrap=True, select=True)
        self.load_list.setTextFormat(Qt.RichText)
        self.load_card.body.addWidget(self.load_text)
        self.load_card.body.addWidget(self.load_list)
        self.load_card.body.addStretch(1)
        row.addWidget(self.load_card, 3)

        act = Card("Actions")
        self.refreeze_btn = button("Refreeze from Steam…", "primary", "snow",
                                   "Bring the stable copy up to date with the Steam install (snapshots first)")
        self.refreeze_btn.clicked.connect(win.freeze)
        self.snap_btn = button("Take snapshot…", None, "camera")
        self.snap_btn.clicked.connect(win.take_snapshot)
        self.shortcut_btn = button("Desktop shortcut", None, "shortcut")
        menu = QMenu(self.shortcut_btn)
        menu.addAction("Play RimWorld (Stable)", lambda: win.make_shortcut(False))
        menu.addAction("Open Rimstable", lambda: win.make_shortcut(True))
        self.shortcut_btn.setMenu(menu)
        self.folder_btn = button("Open stable folder", None, "folder")
        self.folder_btn.clicked.connect(lambda: win.open_path(core.ROOT))
        for b in (self.refreeze_btn, self.snap_btn, self.shortcut_btn, self.folder_btn):
            b.setStyleSheet("text-align: left; padding-left: 12px;")
            act.body.addWidget(b)
        act.body.addStretch(1)
        row.addWidget(act, 2)
        dl.addLayout(row)

        self.locations = self._locations_card()
        dl.addWidget(self.locations)
        dl.addStretch(1)
        self.stack.addWidget(scroll)

    def _layout_stats(self, cols):
        """Four stat cards in one row, or 2x2 when the window is narrow."""
        if cols == self.stat_cols:
            return
        self.stat_cols = cols
        for i, c in enumerate((self.s_game, self.s_updates, self.s_support, self.s_snaps)):
            self.stats.removeWidget(c)
            self.stats.addWidget(c, i // cols, i % cols)
        for i in range(4):
            self.stats.setColumnStretch(i, 1 if i < cols else 0)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._layout_stats(4 if self.width() >= 960 else 2)

    def _locations_card(self):
        c = Card("Locations")
        grid = QGridLayout()
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(8)
        c.rows = {}
        for i, (key, name) in enumerate([("steam", "Steam game"), ("workshop", "Workshop mods"),
                                         ("config", "Steam config & saves"), ("root", "Stable copy")]):
            grid.addWidget(label(name, "muted"), i, 0, Qt.AlignTop)
            val = ElidedLabel()
            val.setProperty("role", "mono")
            val.setTextInteractionFlags(Qt.TextSelectableByMouse)
            val.setFont(QFontDatabase.systemFont(QFontDatabase.FixedFont))
            pill = Pill()
            grid.addWidget(val, i, 1)
            grid.addWidget(pill, i, 2, Qt.AlignRight)
            c.rows[key] = (val, pill)
        grid.setColumnStretch(1, 1)
        c.body.addLayout(grid)
        return c

    def _fill_locations(self, card):
        paths = {"steam": core.GAME_SRC, "workshop": core.WS_SRC, "config": core.CFG_SRC, "root": core.ROOT}
        for key, (val, pill) in card.rows.items():
            p = paths[key]
            val.set_full_text(str(p))
            if key == "root":
                pill.set("frozen", "ok") if core.MANIFEST.exists() else pill.set("not created", "neutral")
            else:
                pill.set("found", "ok") if p.is_dir() else pill.set("missing", "danger")

    def update_state(self, st, diff, diff_error):
        man = st.get("manifest")
        self._fill_locations(self.first_locations if not man else self.locations)
        if not man:
            self.stack.setCurrentIndex(0)
            self.subtitle.setText("Set up a stable copy of your Steam RimWorld")
            return
        self.stack.setCurrentIndex(1)
        g = man["game"]
        frozen = parse_time(man.get("frozen_at"))
        self.subtitle.setText(f"RimWorld {g.get('revision') or g.get('version_txt')}  ·  "
                              f"{len(man['mods'])} mods  ·  frozen {when(frozen)}")

        steam = st.get("steam_game")
        if steam is None:
            self.s_game.set("Steam missing", st.get("steam_error") or "", "danger")
        elif steam.get("buildid") == g.get("buildid"):
            self.s_game.set("Same as Steam", f"{g.get('revision') or g.get('version_txt')} · build {g.get('buildid')}", "ok")
        else:
            self.s_game.set("Steam updated", f"stable build {g.get('buildid')}, Steam build {steam.get('buildid')} "
                            f"({steam.get('revision') or steam.get('version_txt')})", "warn")

        if diff is not None:
            n = len(diff["changed"])
            gone = len(diff["gone"])
            cap = "updated on Steam since the freeze" + (f"; {gone} no longer on Steam" if gone else "")
            self.s_updates.set(str(n), cap, "warn" if n else "ok")
            self.review_btn.setVisible(bool(n))
            self.update_all_btn.setVisible(bool(n))
            total = len(man["mods"])
            self.s_support.set(f"{diff['ready']}/{total}", f"mods list support for {diff['target']} in their "
                               "current Steam version", None, (diff["ready"], total))
            added, removed = diff["added"], diff["removed"]
            if added or removed:
                self.load_pill.set(f"{len(added) + len(removed)} differences", "warn")
                self.load_text.setText("The active mod lists of the Steam install and the stable copy differ. "
                                       "A refreeze takes Steam's load order.")
                t = theme.current
                items = [f"<span style='color:{t['success']}'>+</span> {p} "
                         f"<span style='color:{t['muted']}'>active in Steam only</span>" for p in added[:12]]
                items += [f"<span style='color:{t['danger']}'>−</span> {p} "
                          f"<span style='color:{t['muted']}'>active in stable only</span>" for p in removed[:12]]
                more = len(added) + len(removed) - len(items)
                self.load_list.setText("<br>".join(items) + (f"<br>…and {more} more" if more > 0 else ""))
                self.load_list.show()
            else:
                self.load_pill.set("in sync", "ok")
                self.load_text.setText("Steam and the stable copy have the same active mods.")
                self.load_list.hide()
        elif diff_error:
            for c in (self.s_updates, self.s_support):
                c.set("?", diff_error, "danger")
            self.review_btn.hide()
            self.update_all_btn.hide()
            self.load_pill.set("unknown", "neutral")
            self.load_text.setText(diff_error)
            self.load_list.hide()
        else:
            for c in (self.s_updates, self.s_support):
                c.set("…", "comparing with Steam")
            self.review_btn.hide()
            self.update_all_btn.hide()
            self.load_pill.set("checking", "neutral")
            self.load_text.setText("Comparing with the Steam install…")
            self.load_list.hide()

        snaps = st.get("snapshots") or []
        if st.get("snap_error"):
            self.s_snaps.set("?", st["snap_error"], "danger")
        elif snaps:
            last = snaps[-1]
            self.s_snaps.set(str(len(snaps)), f"Latest: {core.label_of(last) or 'unlabelled'}, {when(snap_time(last))}")
        else:
            self.s_snaps.set("0", "none yet")

    def set_enabled(self, can_modify, reason):
        for b in (self.refreeze_btn, self.snap_btn, self.freeze_first, self.update_all_btn):
            b.setEnabled(can_modify)
            b.setToolTip(reason if not can_modify else "")


# ---------------------------------------------------------------- mods

STATUS = {
    "update": ("Update on Steam", "warn", 0),
    "new": ("Not in stable", "accent", 1),
    "gone": ("Not on Steam", "danger", 2),
    "current": ("Up to date", "ok", 3),
    "checking": ("Checking…", "neutral", 4),
    "unknown": ("Unknown", "neutral", 4),
}


def mod_rows(man, diff, failed=False):
    """Table rows: every frozen mod, plus Workshop mods the stable copy doesn't have.
    Without a diff the status is "checking", or "unknown" if comparing with Steam failed."""
    changed = {r["packageId"] for r, _ in diff["changed"]} if diff else set()
    gone = {r["packageId"] for r in diff["gone"]} if diff else set()
    ws = diff["workshop"] if diff else {}
    times = diff["times"] if diff else {}
    rows = []
    for r in man["mods"]:
        pid = r["packageId"]
        cur = ws.get(pid)
        if diff:
            status = "update" if pid in changed else "gone" if pid in gone else "current"
        else:
            status = "unknown" if failed else "checking"
        rows.append({"name": r["name"] or pid, "packageId": pid, "folder": r["folder"], "status": status,
                     "versions": (cur or r)["supportedVersions"], "updated": times.get(r["folder"]) or r.get("timeupdated")})
    stable = {r["packageId"] for r in man["mods"]}
    for pid, m in ws.items():
        if pid not in stable and pid != core.HELPER_ID:
            rows.append({"name": m["name"] or pid, "packageId": pid, "folder": m["dir"].name, "status": "new",
                         "versions": m["supportedVersions"], "updated": times.get(m["dir"].name)})
    return rows


class ModsModel(QAbstractTableModel):
    COLS = ["Name", "Status", "Supports", "Steam updated", "Folder"]

    def __init__(self):
        super().__init__()
        self.rows, self.target = [], None

    def set_rows(self, rows, target):
        self.beginResetModel()
        self.rows, self.target = rows, target
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.COLS)

    def headerData(self, section, orient, role=Qt.DisplayRole):
        if orient == Qt.Horizontal and role == Qt.DisplayRole:
            return self.COLS[section]
        if orient == Qt.Horizontal and role == Qt.TextAlignmentRole:
            return int(Qt.AlignLeft | Qt.AlignVCenter)
        return None

    def data(self, idx, role=Qt.DisplayRole):
        r = self.rows[idx.row()]
        c = idx.column()
        unsupported = self.target and r["versions"] and self.target not in r["versions"]
        if role == Qt.DisplayRole:
            if c == 0:
                return r["name"]
            if c == 1:
                return STATUS[r["status"]][0]
            if c == 2:
                return ", ".join(r["versions"])
            if c == 3:
                return dt.datetime.fromtimestamp(r["updated"]).strftime("%Y-%m-%d") if r["updated"] else "—"
            return r["folder"]
        if role == TONE_ROLE and c == 1:
            return STATUS[r["status"]][1]
        if role == SORT_ROLE:
            return [r["name"].lower(), STATUS[r["status"]][2], ",".join(r["versions"]), r["updated"] or 0,
                    r["folder"]][c]
        if role == Qt.ToolTipRole:
            if c == 0:
                return f"{r['name']}\n{r['packageId']}"
            if c == 2 and unsupported:
                return f"Doesn't list {self.target}"
        if role == Qt.ForegroundRole:
            if c == 2 and unsupported:
                return QColor(theme.current["warning"])
            if c in (3, 4):
                return QColor(theme.current["muted"])
        return None


class ModsFilter(QSortFilterProxyModel):
    def __init__(self):
        super().__init__()
        self.status, self.text = "stable", ""
        self.setSortRole(SORT_ROLE)

    def set_filter(self, status=None, text=None):
        if status is not None:
            self.status = status
        if text is not None:
            self.text = text.lower().strip()
        self.invalidateFilter()

    def filterAcceptsRow(self, row, parent):
        r = self.sourceModel().rows[row]
        if self.status == "stable" and r["status"] == "new":
            return False
        if self.status not in ("stable", "all") and r["status"] != self.status:
            return False
        t = self.text
        return not t or t in r["name"].lower() or t in r["packageId"] or t in r["folder"].lower()


def make_table(model):
    v = QTableView()
    v.setModel(model)
    v.setSelectionBehavior(QAbstractItemView.SelectRows)
    v.setSelectionMode(QAbstractItemView.SingleSelection)
    v.setShowGrid(False)
    v.setWordWrap(False)
    v.setSortingEnabled(True)
    v.setFocusPolicy(Qt.StrongFocus)
    v.verticalHeader().hide()
    v.verticalHeader().setDefaultSectionSize(40)
    h = v.horizontalHeader()
    h.setHighlightSections(False)
    h.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    h.setStretchLastSection(False)
    return v


class ModsPage(Page):
    def __init__(self, win):
        super().__init__(win, "Mods", "Frozen mods compared with the Steam Workshop folder")
        self.pull_btn = button("Pull selected…", None, "download",
                               "Copy the selected mod's current Steam version into the stable copy")
        self.pull_btn.clicked.connect(self._pull)
        self.update_all_btn = button("Update all", "primary", "refresh",
                                     "Pull every stable mod that changed on Steam, after one snapshot")
        self.update_all_btn.clicked.connect(win.update_all)
        self.updates = 0
        self.actions.addWidget(self.update_all_btn)
        self.actions.addWidget(self.pull_btn)

        bar = QHBoxLayout()
        bar.setSpacing(10)
        self.seg = Segmented([("stable", "In stable"), ("update", "Updates"), ("new", "Not in stable"),
                              ("gone", "Not on Steam"), ("all", "All")])
        self.seg.changed.connect(lambda k: (self.proxy.set_filter(status=k), self._selection_changed()))
        bar.addWidget(self.seg)
        bar.addStretch(1)
        self.search = QLineEdit(placeholderText="Search name, packageId or Workshop id")
        self.search.setClearButtonEnabled(True)
        self.search.setMinimumWidth(280)
        self.search.textChanged.connect(lambda t: self.proxy.set_filter(text=t))
        bar.addWidget(self.search)

        self.model = ModsModel()
        self.proxy = ModsFilter()
        self.proxy.setSourceModel(self.model)
        self.table = make_table(self.proxy)
        self.table.setItemDelegateForColumn(1, PillDelegate(self.table))
        h = self.table.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.Stretch)
        for c, w in ((1, 170), (2, 170), (3, 130), (4, 130)):
            h.setSectionResizeMode(c, QHeaderView.Interactive)
            h.resizeSection(c, w)
        self.table.sortByColumn(0, Qt.AscendingOrder)
        self.table.selectionModel().selectionChanged.connect(self._selection_changed)
        self.table.doubleClicked.connect(self._pull)

        self.stack = QStackedLayout()
        content = QWidget()
        cl = QVBoxLayout(content)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(12)
        cl.addLayout(bar)
        cl.addWidget(self.table, 1)
        self.hint = label("", "faint")
        cl.addWidget(self.hint)
        self.stack.addWidget(content)
        empty = Card()
        empty.body.addWidget(EmptyState("mods", "No stable copy yet", "Freeze from Steam on the Overview page first."))
        self.stack.addWidget(empty)
        self.body.addLayout(self.stack, 1)
        self.can_modify, self.reason = True, ""
        self._selection_changed()

    def show_filter(self, key):
        self.search.clear()
        self.seg.select(key)

    def update_state(self, st, diff, diff_error):
        man = st.get("manifest")
        self.stack.setCurrentIndex(0 if man else 1)
        if not man:
            return
        rows = mod_rows(man, diff, failed=bool(diff_error))
        sel = self.selected()
        self.model.set_rows(rows, diff["target"] if diff else None)
        counts = {k: sum(r["status"] == k for r in rows) for k in STATUS}
        self.updates = counts["update"]
        self.update_all_btn.setText(f"Update all  {self.updates}" if self.updates else "Update all")
        self.seg.set_text("stable", f"In stable  {len(man['mods'])}")
        self.seg.set_text("update", f"Updates  {counts['update']}" if diff else "Updates")
        self.seg.set_text("new", f"Not in stable  {counts['new']}" if diff else "Not in stable")
        self.seg.set_text("gone", f"Not on Steam  {counts['gone']}" if diff else "Not on Steam")
        self.seg.set_text("all", f"All  {len(rows)}")
        if diff_error:
            self.hint.setText(f"Couldn't compare with Steam: {diff_error}")
        elif not diff:
            self.hint.setText("Comparing with the Steam install…")
        else:
            self.hint.setText("Update all copies the Steam version of every changed mod after one snapshot; "
                              "Pull selected does the same for one mod. Neither changes the load order.")
        if sel:
            for i in range(self.proxy.rowCount()):
                if self.model.rows[self.proxy.mapToSource(self.proxy.index(i, 0)).row()]["packageId"] == sel["packageId"]:
                    self.table.selectRow(i)
                    break
        self._selection_changed()

    def selected(self):
        idx = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        if not idx:
            return None
        return self.model.rows[self.proxy.mapToSource(idx[0]).row()]

    def _selection_changed(self, *_):
        r = self.selected()
        ok = bool(r and r["status"] in ("update", "new")) and self.can_modify
        self.pull_btn.setEnabled(ok)
        self.update_all_btn.setEnabled(self.can_modify and self.updates > 0)
        self.update_all_btn.setToolTip(self.reason if not self.can_modify else
                                       "Pull every stable mod that changed on Steam, after one snapshot"
                                       if self.updates else "Every stable mod matches Steam")
        if not self.can_modify:
            self.pull_btn.setToolTip(self.reason)
        elif r and r["status"] not in ("update", "new"):
            self.pull_btn.setToolTip(f"{r['name']} is {STATUS[r['status']][0].lower()}")
        else:
            self.pull_btn.setToolTip("Copy the selected mod's current Steam version into the stable copy")

    def _pull(self, *_):
        r = self.selected()
        if r and r["status"] in ("update", "new") and self.can_modify:
            self.win.pull(r)

    def set_enabled(self, can_modify, reason):
        self.can_modify, self.reason = can_modify, reason
        self._selection_changed()


# ---------------------------------------------------------------- snapshots

class SnapsModel(QAbstractTableModel):
    COLS = ["Taken", "Label", "ID"]

    def __init__(self):
        super().__init__()
        self.rows = []

    def set_rows(self, snaps):
        self.beginResetModel()
        self.rows = list(reversed(snaps))
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.COLS)

    def headerData(self, section, orient, role=Qt.DisplayRole):
        if orient == Qt.Horizontal and role == Qt.DisplayRole:
            return self.COLS[section]
        return None

    def data(self, idx, role=Qt.DisplayRole):
        s = self.rows[idx.row()]
        c = idx.column()
        t = snap_time(s)
        lbl = core.label_of(s)
        if role == Qt.DisplayRole:
            return [when(t), lbl or "—", s["short_id"]][c]
        if role == SORT_ROLE:
            return [s["time"], lbl.lower(), s["short_id"]][c]
        if role == Qt.ToolTipRole:
            return f"{s['id']}\n{t:%Y-%m-%d %H:%M:%S}" if t else s["id"]
        if role == Qt.ForegroundRole and c == 2:
            return QColor(theme.current["muted"])
        if role == Qt.FontRole and c == 2:
            return QFontDatabase.systemFont(QFontDatabase.FixedFont)
        return None



class SnapshotsPage(Page):
    def __init__(self, win):
        super().__init__(win, "Snapshots", "Restic snapshots of game/, userdata/ and manifest.json")
        self.snap_btn = button("Take snapshot…", "primary", "camera")
        self.snap_btn.clicked.connect(win.take_snapshot)
        self.restore_btn = button("Restore…", None, "undo", "Roll the stable copy back to the selected snapshot")
        self.restore_btn.clicked.connect(self._restore)
        self.prune_btn = button("Prune…", None, "trash", "Delete all but the newest snapshots")
        self.prune_btn.clicked.connect(win.prune)
        for b in (self.prune_btn, self.restore_btn, self.snap_btn):
            self.actions.addWidget(b)

        self.model = SnapsModel()
        self.proxy = QSortFilterProxyModel()
        self.proxy.setSortRole(SORT_ROLE)
        self.proxy.setSourceModel(self.model)
        self.table = make_table(self.proxy)
        h = self.table.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.Interactive)
        h.resizeSection(0, 190)
        h.setSectionResizeMode(1, QHeaderView.Stretch)
        h.setSectionResizeMode(2, QHeaderView.Interactive)
        h.resizeSection(2, 130)
        self.table.sortByColumn(0, Qt.DescendingOrder)
        self.table.selectionModel().selectionChanged.connect(self._update_buttons)
        self.table.doubleClicked.connect(self._restore)

        self.stack = QStackedLayout()
        content = QWidget()
        cl = QVBoxLayout(content)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(12)
        cl.addWidget(self.table, 1)
        self.hint = label("Freeze, pull and restore take a snapshot automatically before they change anything. "
                          "Snapshots pile up until you prune them.", "faint", wrap=True)
        cl.addWidget(self.hint)
        self.stack.addWidget(content)
        empty = Card()
        self.empty = EmptyState("snapshots", "No snapshots", "Snapshots appear here once the stable copy is frozen.")
        empty.body.addWidget(self.empty)
        self.stack.addWidget(empty)
        self.body.addLayout(self.stack, 1)
        self.can_modify, self.reason, self.has_manifest = True, "", False
        self._update_buttons()

    def update_state(self, st, diff, diff_error):
        snaps = st.get("snapshots") or []
        self.has_manifest = bool(st.get("manifest"))
        self.model.set_rows(snaps)
        self.stack.setCurrentIndex(0 if snaps else 1)
        if st.get("snap_error"):
            self.empty.set_text("Couldn't read snapshots", st["snap_error"])
        n = len(snaps)
        self.subtitle.setText(f"{n} snapshot{'s' if n != 1 else ''} of game/, userdata/ and manifest.json"
                              if n else "Restic snapshots of game/, userdata/ and manifest.json")
        self._update_buttons()

    def selected(self):
        idx = self.table.selectionModel().selectedRows()
        return self.model.rows[self.proxy.mapToSource(idx[0]).row()] if idx else None

    def _update_buttons(self, *_):
        ok = self.can_modify and self.has_manifest
        tip = self.reason if not self.can_modify else "" if self.has_manifest else "Freeze first"
        self.snap_btn.setEnabled(ok)
        self.prune_btn.setEnabled(ok and self.model.rowCount() > 1)
        self.restore_btn.setEnabled(ok and self.selected() is not None)
        for b in (self.snap_btn, self.prune_btn):
            b.setToolTip(tip)
        self.restore_btn.setToolTip(tip or ("" if self.selected() else "Select a snapshot to restore"))

    def _restore(self, *_):
        s = self.selected()
        if s and self.restore_btn.isEnabled():
            self.win.restore(s)

    def set_enabled(self, can_modify, reason):
        self.can_modify, self.reason = can_modify, reason
        self._update_buttons()


# ---------------------------------------------------------------- activity

class ActivityPage(Page):
    def __init__(self, win):
        super().__init__(win, "Activity", "Output of the commands run from this window")
        self.copy_btn = button("Copy", None, "copy")
        self.clear_btn = button("Clear", "ghost")
        self.actions.addWidget(self.clear_btn)
        self.actions.addWidget(self.copy_btn)
        self.log = QPlainTextEdit(readOnly=True)
        self.log.setObjectName("Log")
        self.log.setFont(QFontDatabase.systemFont(QFontDatabase.FixedFont))
        self.log.setMaximumBlockCount(20000)
        self.log.setLineWrapMode(QPlainTextEdit.NoWrap)  # restic prints wide tables
        self.log.setPlaceholderText("Nothing has run yet. Freeze, pull, snapshot, restore and prune "
                                    "show their output here.")
        self.copy_btn.clicked.connect(lambda: (self.log.selectAll(), self.log.copy(),
                                               self.log.moveCursor(self.log.textCursor().MoveOperation.End)))
        self.clear_btn.clicked.connect(self.log.clear)
        self.body.addWidget(self.log, 1)

    def _append_html(self, html):
        self.log.appendHtml(html)
        self.log.verticalScrollBar().setValue(self.log.verticalScrollBar().maximum())

    def started(self, args):
        t = theme.current
        cmd = "rimstable " + " ".join(a if " " not in a else repr(a) for a in args)
        if self.log.blockCount() > 1 or self.log.toPlainText():
            self.log.appendPlainText("")
        self._append_html(f"<span style='color:{t['faint']}'>{dt.datetime.now():%H:%M:%S}</span> "
                          f"<b style='color:{t['accent']}'>$ {esc(cmd)}</b>")

    def line(self, text):
        t = theme.current
        if text.startswith("rimstable: "):
            self._append_html(f"<span style='color:{t['danger']}'>{esc(text)}</span>")
        elif text.startswith("["):
            tag, _, rest = text.partition("]")
            self._append_html(f"<span style='color:{t['muted']}'>{esc(tag)}]</span>{esc(rest)}")
        else:
            self.log.appendPlainText(text)

    def finished(self, ok, seconds):
        t = theme.current
        if ok:
            self._append_html(f"<span style='color:{t['success']}'>✓ done in {seconds:.0f}s</span>")
        else:
            self._append_html(f"<span style='color:{t['danger']}'>✗ failed after {seconds:.0f}s</span>")


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("  ", "&nbsp; ")
