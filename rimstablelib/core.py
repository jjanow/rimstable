"""rimstable - keep a frozen, Steam-independent RimWorld install that only changes when you say so.

The Steam install (game + Workshop mods) is treated as a read-only source / test bed.
The stable install lives under RIMSTABLE_ROOT (default ~/Games/RimWorld-stable):

    game/          full copy of the game, steam_appid.txt removed, active mods in game/Mods/<workshopId>/
    userdata/      config + saves, used via -savedatafolder
    manifest.json  what was frozen (game build, every mod's fingerprint)
    snapshots/     restic repository of game/ + userdata/ + manifest.json
    .rimstable     marker file; nothing is ever deleted outside a root that carries it
"""
import csv
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path, PureWindowsPath

WINDOWS = os.name == "nt"
HOME = Path.home()
APPID = "294100"
CFG_REL = Path("Ludeon Studios/RimWorld by Ludeon Studios")
FLATPAK = HOME / ".var/app/com.valvesoftware.Steam"
# the repo checkout: the `rimstable` entry script and the NoSteamNag mod live here
APP_DIR = Path(__file__).resolve().parent.parent
SCRIPT = APP_DIR / "rimstable"


def steam_roots():
    """Candidate Steam install dirs for this platform, most likely first."""
    if WINDOWS:
        roots = []
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as k:
                roots.append(Path(winreg.QueryValueEx(k, "SteamPath")[0]))
        except OSError:
            pass
        for env in ("ProgramFiles(x86)", "ProgramFiles"):
            if os.environ.get(env):
                roots.append(Path(os.environ[env]) / "Steam")
        return roots
    return [FLATPAK / ".local/share/Steam", HOME / ".local/share/Steam", HOME / ".steam/steam"]


def library_paths(vdf_text):
    """Library folders listed in Steam's libraryfolders.vdf."""
    return [Path(m.group(1).replace("\\\\", "\\")) for m in re.finditer(r'"path"\s+"([^"]+)"', vdf_text)]


def find_steamapps():
    """The steamapps dir of the Steam library that has RimWorld installed."""
    seen, fallback = set(), None
    for root in steam_roots():
        try:
            root = root.resolve()
        except OSError:
            continue
        if root in seen or not (root / "steamapps").is_dir():
            continue
        seen.add(root)
        fallback = fallback or root / "steamapps"
        libs = [root]
        vdf = root / "steamapps/libraryfolders.vdf"
        if vdf.exists():
            libs += library_paths(vdf.read_text(encoding="utf-8", errors="replace"))
        for lib in libs:
            if (lib / f"steamapps/appmanifest_{APPID}.acf").exists():
                return lib / "steamapps"
    return fallback or steam_roots()[0] / "steamapps"


def find_config(steamapps):
    """RimWorld's config dir for the Steam flavor that owns steamapps (flatpak Steam keeps its own)."""
    if WINDOWS:
        return Path(os.environ.get("USERPROFILE", HOME)) / "AppData/LocalLow" / CFG_REL
    if FLATPAK.resolve() in Path(steamapps).resolve().parents:
        return FLATPAK / ".config/unity3d" / CFG_REL
    return Path(os.environ.get("XDG_CONFIG_HOME", HOME / ".config")) / "unity3d" / CFG_REL


STEAMAPPS = Path(os.environ.get("RIMSTABLE_STEAMAPPS") or find_steamapps())
GAME_SRC = STEAMAPPS / "common/RimWorld"
WS_SRC = STEAMAPPS / f"workshop/content/{APPID}"
WS_ACF = STEAMAPPS / f"workshop/appworkshop_{APPID}.acf"
APP_ACF = STEAMAPPS / f"appmanifest_{APPID}.acf"
CFG_SRC = Path(os.environ.get("RIMSTABLE_CONFIG_SRC") or find_config(STEAMAPPS))
EXE_NAME = "RimWorldWin64.exe" if WINDOWS else "RimWorldLinux"

ROOT = Path(os.environ.get("RIMSTABLE_ROOT", HOME / "Games/RimWorld-stable")).resolve()
GAME = ROOT / "game"
MODS = GAME / "Mods"
USERDATA = ROOT / "userdata"
MANIFEST = ROOT / "manifest.json"
REPO = ROOT / "snapshots"
MARKER = ROOT / ".rimstable"

# MissileGirl/Cache is Gagarin's XML cache; Steam's copy hashes Steam paths and would force a rebuild
USERDATA_SKIP = {"Player.log", "Player-prev.log", "steam_autocloud.vdf", "MissileGirl/Cache"}
# helper mod that closes the "Could not initialize Steam API" dialog (no steam_appid.txt on purpose)
HELPER_SRC = APP_DIR / "NoSteamNag"
HELPER_ID = "rimstable.nosteamnag"
HELPER_FOLDER = "rimstable_nosteamnag"


class RimstableError(Exception):
    """A refusal or failure with a message for the user; the CLI prints it and exits 1."""


def die(msg):
    raise RimstableError(msg)


def run(cmd, **kw):
    return subprocess.run(cmd, check=True, **kw)


def read_text(p):
    return Path(p).read_text(encoding="utf-8", errors="replace")


def install_helper():
    """Copy the NoSteamNag mod into the stable Mods folder and activate it right after Harmony."""
    if not (HELPER_SRC / "Assemblies/RimstableNoSteamNag.dll").exists():
        print(f"[helper] {HELPER_SRC} not built; the Steam API dialog will still appear", file=sys.stderr)
        return
    sync_into(HELPER_SRC, MODS / HELPER_FOLDER, exclude={"Source"})
    cfg = USERDATA / "Config/ModsConfig.xml"
    if HELPER_ID in read_modsconfig(USERDATA)["active"]:
        return
    raw = cfg.read_bytes()
    bom = raw.startswith(b"\xef\xbb\xbf")
    text = raw.decode("utf-8-sig")
    m = re.search(r"^([ \t]*)<li>brrainz\.harmony</li>[ \t]*\r?\n", text, re.M | re.I)
    if not m:
        print("[helper] Harmony is not active; not activating the Steam API dialog helper", file=sys.stderr)
        return
    assert_dest(cfg)
    text = text[:m.end()] + f"{m.group(1)}<li>{HELPER_ID}</li>\n" + text[m.end():]
    cfg.write_bytes((b"\xef\xbb\xbf" if bom else b"") + text.encode("utf-8"))
    print(f"[helper] activated {HELPER_ID}")


# ---------- safety ----------

def inside_root(p):
    p = Path(p).resolve()
    return p != ROOT and ROOT in p.parents


def assert_dest(p):
    """Every write/delete target must be inside a marked stable root."""
    if not MARKER.is_file():
        die(f"refusing to modify {p}: {MARKER} missing")
    if not inside_root(p):
        die(f"refusing to modify {p}: not inside {ROOT}")
    for src in (GAME_SRC, WS_SRC, CFG_SRC):
        s = src.resolve()
        rp = Path(p).resolve()
        if rp == s or s in rp.parents or rp in s.parents:
            die(f"refusing to modify {p}: overlaps Steam source {src}")


def rimworld_pids():
    if WINDOWS:
        r = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {EXE_NAME}", "/FO", "CSV", "/NH"],
                           capture_output=True, text=True, errors="replace",
                           creationflags=subprocess.CREATE_NO_WINDOW)
        return tasklist_pids(r.stdout, EXE_NAME)
    r = subprocess.run(["pgrep", "-x", EXE_NAME], capture_output=True, text=True)
    return r.stdout.split()


def tasklist_pids(out, image):
    """PIDs from `tasklist /FO CSV /NH` output (the no-match message is localized, so match the image name)."""
    return [row[1] for row in csv.reader(out.splitlines()) if len(row) > 1 and row[0].lower() == image.lower()]


def require_not_running():
    pids = rimworld_pids()
    if pids:
        die(f"RimWorld is running (pid {' '.join(pids)}); quit it first")


def require_steam_idle(force):
    busy = []
    acf = read_text(APP_ACF) if APP_ACF.exists() else ""
    m = re.search(r'"StateFlags"\s+"(\d+)"', acf)
    if m and m.group(1) != "4":
        busy.append(f"game StateFlags={m.group(1)} (4 = fully installed)")
    ws = read_text(WS_ACF) if WS_ACF.exists() else ""
    for key in ("NeedsUpdate", "NeedsDownload"):
        m = re.search(rf'"{key}"\s+"(\d+)"', ws)
        if m and m.group(1) != "0":
            busy.append(f"workshop {key}={m.group(1)}")
    if busy and not force:
        die("Steam looks mid-update: " + "; ".join(busy) + " (wait, or pass --force)")


def make_writable(p):
    """Windows won't overwrite or delete read-only files (e.g. a mod's .git objects)."""
    try:
        st = os.lstat(p)
        if not stat.S_ISLNK(st.st_mode) and not st.st_mode & stat.S_IWRITE:
            os.chmod(p, st.st_mode | stat.S_IWRITE)
    except FileNotFoundError:
        pass


def remove_path(p):
    if os.path.isdir(p) and not os.path.islink(p):
        def retry(fn, path, _):
            make_writable(path)
            fn(path)
        if sys.version_info >= (3, 12):
            shutil.rmtree(p, onexc=retry)
        else:
            shutil.rmtree(p, onerror=retry)
    else:
        make_writable(p)
        os.remove(p)


def mirror(src, dst, delete=True, exclude=()):
    """rsync -a [--delete] src/ dst/ in pure Python. `exclude` holds src-relative posix paths
    ("Player.log", "MissileGirl/Cache") that are neither copied nor deleted. Files whose size
    and mtime already match are skipped."""
    src, dst = Path(src), Path(dst)
    for dirpath, dirnames, filenames in os.walk(src):
        rel = Path(dirpath).relative_to(src)
        dirnames[:] = [d for d in dirnames if (rel / d).as_posix() not in exclude]
        filenames = [f for f in filenames if (rel / f).as_posix() not in exclude]
        out = dst / rel
        if out.is_symlink() or (out.exists() and not out.is_dir()):
            remove_path(out)
        out.mkdir(exist_ok=True)
        links = [d for d in dirnames if os.path.islink(os.path.join(dirpath, d))]
        dirnames[:] = [d for d in dirnames if d not in links]
        names = {os.path.normcase(n) for n in dirnames + filenames + links}  # NTFS is case-insensitive
        for name in filenames + links:
            s, d = os.path.join(dirpath, name), out / name
            sst = os.lstat(s)
            if os.path.islink(s):
                if d.is_symlink() and os.readlink(d) == os.readlink(s):
                    continue
                if d.exists() or d.is_symlink():
                    remove_path(d)
                os.symlink(os.readlink(s), d)
                continue
            if d.is_dir() and not d.is_symlink():
                remove_path(d)
            elif d.exists() or d.is_symlink():
                dst_st = os.lstat(d)
                if (stat.S_ISREG(dst_st.st_mode) and dst_st.st_size == sst.st_size
                        and int(dst_st.st_mtime) == int(sst.st_mtime)):
                    continue
                remove_path(d)
            shutil.copy2(s, d)
        if delete:
            for e in os.listdir(out):
                if os.path.normcase(e) not in names and (rel / e).as_posix() not in exclude:
                    remove_path(out / e)


def sync_into(src, dst, delete=True, exclude=()):
    assert_dest(dst)
    Path(dst).mkdir(parents=True, exist_ok=True)
    mirror(src, dst, delete, exclude)


def remove_mod_dir(path):
    path = Path(path)
    assert_dest(path)
    if path.parent.resolve() != MODS.resolve():
        die(f"refusing to remove {path}: not directly under {MODS}")
    remove_path(path)


# ---------- reading game / mod metadata ----------

def find_about(moddir):
    about = next((p for p in Path(moddir).iterdir() if p.is_dir() and p.name.lower() == "about"), None)
    if not about:
        return None
    return next((p for p in about.iterdir() if p.name.lower() == "about.xml"), None)


def read_about(moddir):
    f = find_about(moddir)
    if not f:
        return None
    try:
        r = ET.parse(f).getroot()
        pid = (r.findtext("packageId") or "").strip()
        name = (r.findtext("name") or "").strip()
        sv = [li.text.strip() for li in r.findall("supportedVersions/li") if li.text]
    except ET.ParseError:
        t = read_text(f)
        m = re.search(r"<packageId>\s*(.*?)\s*</packageId>", t, re.I)
        pid = m.group(1) if m else ""
        m = re.search(r"<name>\s*(.*?)\s*</name>", t, re.I)
        name = m.group(1) if m else ""
        sv = re.findall(r"<li>\s*(\d+\.\d+)\s*</li>", t)
    if not pid:
        return None
    return {"packageId": pid.lower(), "name": name, "supportedVersions": sv}


def index_mods(root):
    """packageId -> {dir, name, supportedVersions} for every mod folder under root."""
    out = {}
    if not root.is_dir():
        return out
    for d in sorted(root.iterdir()):
        if not d.is_dir():
            continue
        a = read_about(d)
        if a:
            out.setdefault(a["packageId"], dict(a, dir=d))
    return out


def read_modsconfig(cfgdir):
    r = ET.parse(Path(cfgdir) / "Config/ModsConfig.xml").getroot()
    return {
        "version": (r.findtext("version") or "").strip(),
        "active": [li.text.strip().lower() for li in r.find("activeMods") if li.text],
    }


def workshop_times():
    """workshopId -> timeupdated (epoch) from Steam's workshop manifest."""
    if not WS_ACF.exists():
        return {}
    return {m.group(1): int(m.group(2)) for m in
            re.finditer(r'"(\d+)"\s*\{\s*"size"\s*"\d+"\s*"timeupdated"\s*"(\d+)"', read_text(WS_ACF))}


def game_info(gamedir, cfgdir=None):
    info = {"version_txt": read_text(Path(gamedir) / "Version.txt").strip()}
    m = re.search(r'"buildid"\s+"(\d+)"', read_text(APP_ACF)) if APP_ACF.exists() else None
    info["buildid"] = m.group(1) if m else None
    if cfgdir:
        info["revision"] = read_modsconfig(cfgdir)["version"]
    return info


def fingerprint(d):
    """Cheap tree fingerprint: relpath, size and mtime of every file (copy2 preserves mtime)."""
    h = hashlib.sha1()
    for dirpath, dirnames, filenames in os.walk(d):
        dirnames.sort()
        for fn in sorted(filenames):
            p = os.path.join(dirpath, fn)
            st = os.lstat(p)
            h.update(f"{os.path.relpath(p, d).replace(os.sep, '/')}\0{st.st_size}\0{int(st.st_mtime)}\n".encode())
    return h.hexdigest()


def major_minor(v):
    m = re.match(r"(\d+\.\d+)", v or "")
    return m.group(1) if m else None


def resolve_active(active):
    """Map Steam's active list to sources. Returns (mods, missing); DLC/core come with the game."""
    ws = index_mods(WS_SRC)
    data = index_mods(GAME_SRC / "Data")
    local = index_mods(GAME_SRC / "Mods")
    mods, missing = [], []
    for pid in active:
        if pid in data:
            continue
        src = ws.get(pid) or local.get(pid)
        if not src:
            missing.append(pid)
            continue
        mods.append(dict(src, packageId=pid))
    return mods, missing


def load_manifest():
    if not MANIFEST.exists():
        die(f"no stable install at {ROOT}; run 'rimstable freeze' first")
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def save_manifest(m):
    assert_dest(MANIFEST)
    tmp = MANIFEST.with_suffix(".tmp")
    tmp.write_text(json.dumps(m, indent=1), encoding="utf-8")
    tmp.replace(MANIFEST)


def mod_record(mod, times):
    d = Path(mod["dir"])
    return {
        "packageId": mod["packageId"],
        "folder": d.name,
        "name": mod["name"],
        "supportedVersions": mod["supportedVersions"],
        "timeupdated": times.get(d.name),
        "fingerprint": fingerprint(d),
    }


# ---------- snapshots (restic) ----------

def restic(*args, capture=False):
    """capture=True returns stdout as bytes."""
    env = dict(os.environ, RESTIC_REPOSITORY=str(REPO))
    cmd = ["restic", "--insecure-no-password", *args]
    if capture:
        return subprocess.run(cmd, check=True, env=env, capture_output=True).stdout
    return run(cmd, env=env)


def snap_path(p, windows=WINDOWS):
    """Where an absolute local path lives inside a restic snapshot; restic stores C:\\x\\y as /C/x/y."""
    if not windows:
        return str(p)
    p = PureWindowsPath(p)
    return "/".join(["", p.drive.rstrip(":"), *p.parts[1:]])


def ensure_repo():
    if not (REPO / "config").exists():
        assert_dest(REPO)
        restic("init")


def snapshot(label):
    ensure_repo()
    label = re.sub(r"[,\n]", " ", label).strip() or "manual"
    print(f"[snapshot] {label}")
    restic("backup", "-q", "--tag", "rimstable", "--tag", f"label={label}",
           str(GAME), str(USERDATA), str(MANIFEST))


def snapshots(init=True):
    """Snapshots oldest first. With init=False a missing repo means none, instead of creating it."""
    if init:
        ensure_repo()
    elif not (REPO / "config").exists():
        return []
    return json.loads(restic("snapshots", "--json", "--tag", "rimstable", capture=True) or b"[]")


def label_of(s):
    return next((t[6:] for t in s.get("tags", []) if t.startswith("label=")), "")


# ---------- reports ----------

def diff_report():
    """What changed on Steam since the freeze, as data (the CLI's `diff` and the GUI format it)."""
    man = load_manifest()
    steam_game = game_info(GAME_SRC, CFG_SRC)
    target = major_minor(steam_game["version_txt"])
    ws = index_mods(WS_SRC)
    changed, gone, ready = [], [], 0
    for r in man["mods"]:
        cur = ws.get(r["packageId"])
        if not cur:
            gone.append(r)
            continue
        if target in cur["supportedVersions"]:
            ready += 1
        if fingerprint(cur["dir"]) != r["fingerprint"]:
            changed.append((r, cur))
    steam_active = read_modsconfig(CFG_SRC)["active"]
    stable_active = read_modsconfig(USERDATA)["active"]
    return {
        "manifest": man,
        "stable_game": man["game"],
        "steam_game": steam_game,
        "target": target,
        "workshop": ws,
        "times": workshop_times(),
        "changed": changed,
        "gone": gone,
        "ready": ready,
        "added": [p for p in steam_active if p not in stable_active],
        "removed": [p for p in stable_active if p not in steam_active and p != HELPER_ID],
    }


# ---------- launchers ----------

ICON = APP_DIR / "rimstablelib/gui/rimstable.svg"


def self_cmd():
    """argv that runs the entry script; on Windows the extensionless file needs the interpreter."""
    return [sys.executable, str(SCRIPT)] if WINDOWS else [str(SCRIPT)]


def launch_hint():
    cmd = subprocess.list2cmdline(self_cmd()) if WINDOWS else str(self_cmd()[0])
    return (f"launch the stable copy with:\n"
            f"  {cmd} launch\n"
            f"or create a desktop shortcut for it with:\n"
            f"  {cmd} shortcut\n"
            f"or manage it in a window with:\n"
            f"  {cmd} gui")


def desktop_dir():
    if WINDOWS:
        # honours OneDrive / folder redirection, unlike %USERPROFILE%\Desktop
        r = subprocess.run(["powershell", "-NoProfile", "-Command", "[Environment]::GetFolderPath('Desktop')"],
                           capture_output=True, text=True, errors="replace",
                           creationflags=subprocess.CREATE_NO_WINDOW)
        d = r.stdout.strip()
        return Path(d) if d else HOME / "Desktop"
    try:
        d = subprocess.run(["xdg-user-dir", "DESKTOP"], capture_output=True, text=True).stdout.strip()
    except FileNotFoundError:
        d = ""
    return Path(d) if d and d != str(HOME) else HOME / "Desktop"


def shortcut_name(gui=False):
    return ("Rimstable" if gui else "RimWorld (Stable)") + (".lnk" if WINDOWS else ".desktop")


def ps_quote(s):
    return "'" + str(s).replace("'", "''") + "'"


def write_lnk(dest, command, icon, description):
    """Windows .lnk running a rimstable command without a console window (pythonw)."""
    py = Path(sys.executable)
    pyw = py.with_name("pythonw.exe")
    target = pyw if pyw.exists() else py
    args = subprocess.list2cmdline([str(SCRIPT), command])
    script = "; ".join([
        f"$s = (New-Object -ComObject WScript.Shell).CreateShortcut({ps_quote(dest)})",
        f"$s.TargetPath = {ps_quote(target)}",
        f"$s.Arguments = {ps_quote(args)}",
        f"$s.WorkingDirectory = {ps_quote(GAME)}",
        f"$s.IconLocation = {ps_quote(icon)}",
        f"$s.Description = {ps_quote(description)}",
        "$s.Save()",
    ])
    run(["powershell", "-NoProfile", "-Command", script], creationflags=subprocess.CREATE_NO_WINDOW)


def write_shortcut(dest, gui=False):
    """A desktop launcher for `rimstable launch`, or with gui=True for `rimstable gui`."""
    dest = Path(dest)
    command = "gui" if gui else "launch"
    name = "Rimstable" if gui else "RimWorld (Stable)"
    desc = "Manage the frozen RimWorld install" if gui else "Frozen RimWorld install managed by rimstable"
    dest.parent.mkdir(parents=True, exist_ok=True)
    if WINDOWS:
        write_lnk(dest.resolve(), command, GAME / EXE_NAME, desc)
        return
    dest.write_text(
        f"[Desktop Entry]\nType=Application\nVersion=1.0\nName={name}\n"
        f"Comment={desc}\n"
        f"Exec=\"{SCRIPT}\" {command}\nPath={GAME}\nIcon={ICON if gui else 'steam_icon_294100'}\n"
        "Categories=Game;\nTerminal=false\nStartupNotify=true\n", encoding="utf-8")
    dest.chmod(0o755)  # KDE/GNOME only run executable .desktop files without a trust prompt
