"""Pre-encoded DDS textures (todds) for the stable copy and/or the Steam install.

RimWorld loads Foo.dds instead of Foo.png when both sit next to each other, which skips PNG decoding and
runtime DXT compression (measured: texture loading 63s -> 9s with ~250 mods). Every DDS rimstable creates is
recorded in a ledger together with the PNG it came from, so rimstable can tell its files from DDS a mod ships,
regenerate stale ones after a mod update, keep them through freeze/pull, and remove only its own on --clean.

Ledgers: stable -> game/Mods/.rimstable-dds.json (inside snapshots, survives refreeze since Mods/ is not
mirrored as a whole); steam -> <root>/dds-steam.json (never written inside Steam's folders).
"""
import json
import os
import shutil
import struct
import subprocess
import tempfile
from pathlib import Path

from .core import (
    APP_DIR, CFG_SRC, GAME_SRC, MARKER, MODS, ROOT, STEAMAPPS, WINDOWS, WS_SRC, assert_dest, die, read_about,
    read_modsconfig, remove_path, resolve_active,
)

# BC1 for opaque textures, BC7 where there's alpha; Unity reads DDS bottom-up, hence the vertical flip
TODDS_ARGS = ["-f", "BC1", "-af", "BC7", "-vf", "-t"]
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


class Target:
    def __init__(self, name, base, ledger, roots):
        self.name, self.base, self.ledger, self.roots = name, base, ledger, roots

    def key(self, p):
        return Path(p).relative_to(self.base).as_posix()


STABLE = Target("stable", MODS, MODS / ".rimstable-dds.json", [MODS])
STEAM = Target("steam", STEAMAPPS, ROOT / "dds-steam.json", [WS_SRC, GAME_SRC / "Mods"])
TARGETS = {"stable": [STABLE], "steam": [STEAM], "both": [STABLE, STEAM]}

_cache = {}


def todds_exe():
    exe = "todds.exe" if WINDOWS else "todds"
    for c in (os.environ.get("RIMSTABLE_TODDS"), shutil.which("todds"), APP_DIR / "tools" / exe):
        if c and Path(c).is_file():
            return str(c)
    die(f"todds not found. Download it from https://github.com/todds-encoder/todds/releases and put the "
        f"binary at {APP_DIR / 'tools' / exe} (or on PATH, or point RIMSTABLE_TODDS at it)")


def sig(p):
    st = os.stat(p)
    return [st.st_size, int(st.st_mtime)]


def load(t):
    """{key: {"png": sig, "dds": sig}}, or None when DDS was never enabled for this target."""
    if not t.ledger.is_file():
        return None
    stamp = t.ledger.stat().st_mtime_ns
    hit = _cache.get(t.name)
    if hit and hit[0] == stamp:
        return hit[1]
    files = json.loads(t.ledger.read_text(encoding="utf-8"))["files"]
    _cache[t.name] = (stamp, files)
    return files


def save(t, files):
    assert_dest(t.ledger)  # both ledgers live inside the stable root
    tmp = t.ledger.with_suffix(".tmp")
    tmp.write_text(json.dumps({"version": 1, "files": files}, separators=(",", ":")), encoding="utf-8")
    tmp.replace(t.ledger)
    _cache.pop(t.name, None)


def enabled(t):
    return t.ledger.is_file()


def check_write(t, p):
    """stable: the usual stable-root guard. steam: only .dds files inside the Workshop/local Mods folders."""
    if t is STABLE:
        return assert_dest(p)
    rp = Path(p).resolve()
    if rp.suffix.lower() != ".dds" or not any(r.resolve() in rp.parents for r in t.roots):
        die(f"refusing to modify {p}: the Steam DDS target only touches .dds files in Workshop/Mods folders")


def ours(t, files, moddir):
    """Relative paths (to moddir) of DDS files in moddir that rimstable generated and that are unchanged."""
    if not files:
        return set()
    prefix = t.key(moddir) + "/"
    out = set()
    for k, e in files.items():
        if k.startswith(prefix):
            p = t.base / k
            try:
                if sig(p) == e["dds"]:
                    out.add(k[len(prefix):])
            except FileNotFoundError:
                pass
    return out


def workshop_generated(moddir):
    """DDS files rimstable added to a Steam mod folder; fingerprints ignore them so diff/pull stay accurate."""
    moddir = Path(moddir)
    if not any(r == moddir.parent for r in STEAM.roots):
        return set()
    return ours(STEAM, load(STEAM), moddir)


def sync_exclude(src, dst):
    """mirror() exclusions for copying a Steam mod into the stable copy: skip Steam's generated DDS, and keep
    stable's generated DDS unless the mod now ships a real file at that path."""
    src, dst = Path(src), Path(dst)
    steam_gen = workshop_generated(src)
    keep = {r for r in ours(STABLE, load(STABLE), dst) if r in steam_gen or not (src / r).exists()}
    return steam_gen | keep


def png_of(dds):
    """The PNG a DDS was made from; mods use both .png and .PNG (RimWorld pairs them either way)."""
    for ext in (".png", ".PNG", ".Png"):
        p = dds.with_suffix(ext)
        if p.is_file():
            return p
    return dds.with_suffix(".png")


def png_size(p):
    try:
        with open(p, "rb") as f:
            h = f.read(24)
    except OSError:
        return None
    if len(h) < 24 or h[:8] != PNG_MAGIC or h[12:16] != b"IHDR":
        return None
    return struct.unpack(">II", h[16:24])


def mod_dirs(t, queries=()):
    if t is STABLE:
        dirs = sorted(d for d in MODS.iterdir() if d.is_dir())
    else:
        mods, _ = resolve_active(read_modsconfig(CFG_SRC)["active"])
        dirs = sorted({Path(m["dir"]) for m in mods})
    if not queries:
        return dirs
    out = []
    for q in queries:
        q = q.lower()
        hit = [d for d in dirs if d.name.lower() == q or ((read_about(d) or {}).get("packageId") == q)]
        if not hit:
            die(f"'{q}': no {t.name} mod folder or packageId matches")
        out += hit
    return sorted(set(out))


def adopt(moddirs, quiet=False):
    """First run on the stable copy: claim DDS that a previous todds run made. A DDS counts as generated when a
    PNG sits next to it and the Steam copy of the mod has no file at that path."""
    files, n = {}, 0
    for d in moddirs:
        src = next((r / d.name for r in STEAM.roots if (r / d.name).is_dir()), None)
        if src is None:
            continue
        steam_gen = workshop_generated(src)
        for dp, _, fns in os.walk(d):
            for fn in fns:
                if not fn.endswith(".dds"):
                    continue
                p = Path(dp, fn)
                png, rel = png_of(p), p.relative_to(d).as_posix()
                if png.is_file() and (rel in steam_gen or not (src / rel).exists()):
                    files[STABLE.key(p)] = {"png": sig(png), "dds": sig(p)}
                    n += 1
    if n and not quiet:
        print(f"[dds stable] adopted {n} DDS files from an earlier todds run")
    return files


def plan(t, files, moddirs):
    """(stale keys, gone keys, PNGs to encode, skipped-size count)."""
    stale, gone = [], []
    for d in moddirs:
        prefix = t.key(d) + "/"
        for k, e in files.items():
            if not k.startswith(prefix):
                continue
            p = t.base / k
            png = png_of(p)
            try:
                if sig(p) != e["dds"]:
                    gone.append(k)  # replaced by a file the mod ships; not ours any more
                elif not png.is_file() or sig(png) != e["png"]:
                    stale.append(k)
            except FileNotFoundError:
                gone.append(k)
    stale_paths = {t.base / k for k in stale}
    todo, badsize = [], 0
    for d in moddirs:
        for dp, _, fns in os.walk(d):
            if "Textures" not in Path(dp).relative_to(d).parts:
                continue
            for fn in fns:
                if not fn.lower().endswith(".png"):
                    continue
                png = Path(dp, fn)
                dds = png.with_suffix(".dds")
                if dds.exists() and dds not in stale_paths:
                    continue
                size = png_size(png)
                if not size or size[0] % 4 or size[1] % 4:
                    badsize += 1  # block compression needs multiples of 4; Unity refuses such DDS
                    continue
                todo.append(png)
    return stale, gone, todo, badsize


def convert(t, moddirs=None, dry_run=False):
    files = load(t)
    if moddirs is None:
        moddirs = mod_dirs(t)
    if files is None:
        files = adopt(moddirs) if t is STABLE else {}
    else:
        files = dict(files)
    stale, gone, todo, badsize = plan(t, files, moddirs)
    print(f"[dds {t.name}] {len(moddirs)} mods: {len(todo)} PNGs to encode ({len(stale)} of them stale), "
          f"{badsize} skipped (size not a multiple of 4), {len(files) - len(stale) - len(gone)} already done")
    if dry_run:
        return
    for k in gone:
        files.pop(k)
    for k in stale:
        p = t.base / k
        check_write(t, p)
        remove_path(p)
        files.pop(k)
    failed = 0
    if todo:
        for png in todo:
            check_write(t, png.with_suffix(".dds"))
        fd, lst = tempfile.mkstemp(suffix=".txt", prefix="rimstable-todds-")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write("\n".join(str(p) for p in todo) + "\n")
            subprocess.run([todds_exe(), *TODDS_ARGS, lst], check=False)
        finally:
            os.remove(lst)
        for png in todo:
            dds = png.with_suffix(".dds")
            if dds.is_file():
                files[t.key(dds)] = {"png": sig(png), "dds": sig(dds)}  # todds always writes lowercase .dds
            else:
                failed += 1
    save(t, files)
    print(f"[dds {t.name}] encoded {len(todo) - failed}" + (f", {failed} failed" if failed else "")
          + f"; {len(files)} generated DDS recorded")


def clean(t, moddirs=None, dry_run=False):
    """Delete the DDS rimstable generated (all of them, or in some mods). Cleaning everything also turns off
    automatic re-encoding after freeze/pull."""
    files = load(t)
    if files is None:
        print(f"[dds {t.name}] nothing to clean")
        return
    files = dict(files)
    prefixes = None if moddirs is None else tuple(t.key(d) + "/" for d in moddirs)
    n = 0
    for k, e in list(files.items()):
        if prefixes and not k.startswith(prefixes):
            continue
        p = t.base / k
        try:
            mine = sig(p) == e["dds"]
        except FileNotFoundError:
            mine = False
        if mine:
            n += 1
            if not dry_run:
                check_write(t, p)
                remove_path(p)
        if not dry_run:
            files.pop(k)
    if dry_run:
        print(f"[dds {t.name}] would delete {n} generated DDS files")
        return
    if prefixes is None:
        assert_dest(t.ledger)
        t.ledger.unlink()
        _cache.pop(t.name, None)
    else:
        save(t, files)
    print(f"[dds {t.name}] deleted {n} generated DDS files")


def summary(t):
    """Read-only counts for the GUI: is DDS on for this target, how many are recorded, how many PNGs wait."""
    files = load(t)
    on = files is not None
    if not on:
        files = adopt(mod_dirs(t), quiet=True) if t is STABLE else {}
    stale, gone, todo, badsize = plan(t, files, mod_dirs(t))
    return {"enabled": on, "recorded": len(files) - len(gone), "todo": len(todo), "stale": len(stale),
            "badsize": badsize}


def status_line():
    parts = []
    for t in (STABLE, STEAM):
        files = load(t)
        parts.append(f"{t.name} {'off' if files is None else str(len(files)) + ' files'}")
    return ", ".join(parts)


def require_root():
    if not MARKER.is_file():
        die(f"no stable install at {ROOT}; the DDS ledgers live there ('rimstable freeze' first)")
