"""Command-line interface. Every command that changes files runs here; the GUI runs these as a subprocess."""
import argparse
import datetime as dt
import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path

from . import core
from .core import (
    APP_DIR, CFG_SRC, EXE_NAME, GAME, GAME_SRC, HELPER_FOLDER, MANIFEST, MARKER, MODS, ROOT, SCRIPT,
    RimstableError, USERDATA, USERDATA_SKIP, WINDOWS, WS_SRC, assert_dest, changed_mods, desktop_dir, die,
    diff_report, ensure_repo, game_info, index_mods, install_helper, label_of, launch_hint, load_manifest, mod_record,
    read_modsconfig, remove_mod_dir, require_not_running, require_steam_idle, resolve_active, restic,
    rimworld_pids, save_manifest, shortcut_name, snap_path, snapshot, snapshots, sync_into,
    workshop_times, write_shortcut,
)


def cmd_freeze(a):
    require_not_running()
    require_steam_idle(a.force)
    first = not MANIFEST.exists()
    if first and ROOT.exists() and any(ROOT.iterdir()) and not MARKER.exists():
        die(f"{ROOT} exists, is not empty and has no {MARKER.name} marker; refusing to use it")

    cfg = read_modsconfig(CFG_SRC)
    mods, missing = resolve_active(cfg["active"])
    if missing and not a.allow_missing:
        die("active mods not found on disk (unsubscribed? still downloading?):\n  "
            + "\n  ".join(missing) + "\npass --allow-missing to freeze without them")

    ROOT.mkdir(parents=True, exist_ok=True)
    MARKER.touch()
    if not first:
        snapshot("pre-refreeze")

    print(f"[game] {GAME_SRC} -> {GAME}")
    sync_into(GAME_SRC, GAME, exclude={"steam_appid.txt", "Mods"})
    MODS.mkdir(exist_ok=True)

    print(f"[mods] {len(mods)} mods -> {MODS}")
    keep = {HELPER_FOLDER}
    for mod in mods:
        folder = Path(mod["dir"]).name
        keep.add(folder)
        sync_into(mod["dir"], MODS / folder)
    for d in MODS.iterdir():
        if d.is_dir() and d.name not in keep:
            print(f"[mods] removing no-longer-active {d.name}")
            remove_mod_dir(d)

    if first or a.userdata:
        print(f"[userdata] {CFG_SRC} -> {USERDATA}" + (" (replacing, saves included)" if not first else ""))
        sync_into(CFG_SRC, USERDATA, delete=not first, exclude=USERDATA_SKIP)
    else:
        # keep stable saves/settings; take Steam's load order and settings for mods new to stable
        assert_dest(USERDATA / "Config")
        shutil.copy2(CFG_SRC / "Config/ModsConfig.xml", USERDATA / "Config/ModsConfig.xml")
        added = 0
        for f in (CFG_SRC / "Config").glob("Mod_*.xml"):
            if not (USERDATA / "Config" / f.name).exists():
                shutil.copy2(f, USERDATA / "Config" / f.name)
                added += 1
        print(f"[userdata] ModsConfig.xml updated, {added} new mod settings files; saves untouched")

    install_helper()
    times = workshop_times()
    save_manifest({
        "frozen_at": dt.datetime.now().isoformat(timespec="seconds"),
        "game": game_info(GAME_SRC, CFG_SRC),
        "active": cfg["active"],
        "mods": [mod_record(m, times) for m in mods],
    })
    snapshot(a.label or ("first freeze" if first else "refreeze"))
    print(f"frozen: {len(mods)} mods, game {game_info(GAME_SRC, CFG_SRC)['revision']}")
    print(launch_hint())


def find_mod(query, records):
    q = query.lower()
    exact = [r for r in records if q in (r["packageId"], r["folder"])]
    if exact:
        return exact
    return [r for r in records if q in r["name"].lower() or q in r["packageId"]]


def cmd_pull(a):
    if a.all == bool(a.mod):
        die("name one mod to pull, or pass --all (not both)")
    require_not_running()
    require_steam_idle(a.force)
    man = load_manifest()
    ws = index_mods(WS_SRC)
    if a.all:
        return pull_all(man, ws)
    candidates = [{"packageId": pid, "folder": m["dir"].name, "name": m["name"]} for pid, m in ws.items()]
    hits = find_mod(a.mod, candidates)
    if len(hits) != 1:
        die(f"'{a.mod}' matches {len(hits)} Workshop mods" +
            ("".join(f"\n  {h['folder']}  {h['packageId']}  {h['name']}" for h in hits[:20])))
    pid = hits[0]["packageId"]
    src = dict(ws[pid], packageId=pid)
    snapshot(f"pre-pull {src['name']}")
    sync_into(src["dir"], MODS / src["dir"].name)
    rec = mod_record(src, workshop_times())
    man["mods"] = [r for r in man["mods"] if r["packageId"] != pid] + [rec]
    save_manifest(man)
    print(f"pulled {src['name']} ({pid})")
    active = read_modsconfig(USERDATA)["active"]
    if pid not in active:
        print("note: this mod is not active in the stable install; enable it in the in-game mod manager")


def pull_all(man, ws):
    """Update every stable mod that changed on Steam, after one snapshot. Mods new to Steam aren't added."""
    changed = sorted(changed_mods(man, ws), key=lambda x: x[1]["name"].lower())
    if not changed:
        print("all stable mods match Steam; nothing to pull")
        return
    snapshot(f"pre-pull all ({len(changed)} mods)")
    times = workshop_times()
    for i, (r, cur) in enumerate(changed, 1):
        print(f"[pull {i}/{len(changed)}] {cur['name']}")
        src = dict(cur, packageId=r["packageId"])
        sync_into(src["dir"], MODS / src["dir"].name)
        rec = mod_record(src, times)
        man["mods"] = [m for m in man["mods"] if m["packageId"] != r["packageId"]] + [rec]
        save_manifest(man)  # after each mod, so an interrupted run leaves an accurate manifest
    print(f"pulled {len(changed)} mods")


def cmd_diff(a):
    d = diff_report()
    stable, steam = d["stable_game"], d["steam_game"]
    print(f"game   stable {stable['revision']} build {stable['buildid']}"
          f"   steam {steam['revision']} build {steam['buildid']}"
          + ("   (same)" if stable["buildid"] == steam["buildid"] else "   ** CHANGED **"))

    def when(folder):
        t = d["times"].get(folder)
        return dt.datetime.fromtimestamp(t).strftime("%Y-%m-%d") if t else "?"

    print(f"\nmods updated on Steam since freeze: {len(d['changed'])}")
    for r, cur in sorted(d["changed"], key=lambda x: x[0]["name"].lower()):
        print(f"  {r['folder']:>11}  {when(r['folder'])}  [{','.join(cur['supportedVersions'])}]  {r['name']}")
    if d["gone"]:
        print(f"\nmods no longer in the Workshop folder (unsubscribed/removed): {len(d['gone'])}")
        for r in d["gone"]:
            print(f"  {r['folder']:>11}  {r['name']}")

    if d["added"] or d["removed"]:
        print("\nload-order differences (Steam test bed vs stable):")
        for p in d["added"]:
            print(f"  + {p}  (active in Steam only)")
        for p in d["removed"]:
            print(f"  - {p}  (active in stable only)")
    print(f"\n{d['ready']}/{len(d['manifest']['mods'])} stable mods list support for {d['target']}"
          " in their current Steam version")


def cmd_snap(a):
    load_manifest()
    require_not_running()
    snapshot(a.label or "manual")


def cmd_list(a):
    for s in snapshots():
        t = s["time"][:19].replace("T", " ")
        print(f"{s['short_id']}  {t}  {label_of(s)}")


def cmd_restore(a):
    require_not_running()
    load_manifest()
    ids = {s["short_id"]: s for s in snapshots()}
    match = [s for sid, s in ids.items() if sid.startswith(a.id) or s["id"].startswith(a.id)]
    if len(match) != 1:
        die(f"snapshot '{a.id}' not found (see 'rimstable list')")
    s = match[0]
    snapshot(f"pre-restore {s['short_id']}")
    for sub in (GAME, USERDATA):
        assert_dest(sub)
        print(f"[restore] {sub}")
        restic("restore", "-q", f"{s['id']}:{snap_path(sub)}", "--target", str(sub),
               "--delete", "--overwrite", "if-changed")
    data = restic("dump", s["id"], snap_path(MANIFEST), capture=True)
    assert_dest(MANIFEST)
    MANIFEST.write_bytes(data)
    print(f"restored {s['short_id']} ({label_of(s)})")


def cmd_prune(a):
    if a.keep < 1:
        die("--keep must be at least 1")
    require_not_running()
    ensure_repo()
    restic("forget", "--tag", "rimstable", "--keep-last", str(a.keep), "--prune")


def cmd_status(a):
    man = load_manifest()
    g = man["game"]
    print(f"root     {ROOT}")
    print(f"frozen   {man['frozen_at']}")
    print(f"game     {g['revision'] or g['version_txt']} (Steam build {g['buildid']})")
    print(f"mods     {len(man['mods'])} + core/DLC, {len(man['active'])} active at freeze")
    snaps = snapshots()
    if snaps:
        print(f"snaps    {len(snaps)}, latest {snaps[-1]['short_id']} {label_of(snaps[-1])}")
    pids = rimworld_pids()
    print(f"running  {'yes (pid ' + ' '.join(pids) + ')' if pids else 'no'}")
    print()
    print(launch_hint())


def cmd_launch(a):
    load_manifest()
    require_not_running()
    install_helper()
    log = USERDATA / "Player.log"
    if log.exists():
        log.replace(USERDATA / "Player-prev.log")
    exe = GAME / EXE_NAME
    extra = a.args[1:] if a.args[:1] == ["--"] else a.args
    argv = [str(exe), f"-savedatafolder={USERDATA}", "-logFile", str(log), *extra]
    if WINDOWS:
        # os.exec* on Windows spawns a child and exits anyway; just start the game detached
        subprocess.Popen(argv, cwd=GAME, creationflags=subprocess.DETACHED_PROCESS)
        return
    os.chdir(GAME)
    os.execve(str(exe), argv, dict(os.environ, LC_ALL="C"))


def cmd_shortcut(a):
    load_manifest()
    dest = Path(a.path) if a.path else desktop_dir() / shortcut_name(a.gui)
    if dest.exists() and not a.force:
        die(f"{dest} already exists (pass --force to overwrite)")
    write_shortcut(dest, gui=a.gui)
    print(f"wrote {dest}")


def venv_python():
    """The interpreter of a .venv next to the entry script (where the README puts PySide6), if any."""
    venv = APP_DIR / ".venv"
    for p in (["Scripts/pythonw.exe", "Scripts/python.exe"] if WINDOWS else ["bin/python3", "bin/python"]):
        if (venv / p).exists():
            return venv / p
    return None


def cmd_gui(a):
    if importlib.util.find_spec("PySide6") is None:
        py = venv_python()
        if py and not os.environ.get("RIMSTABLE_REEXEC"):
            env = dict(os.environ, RIMSTABLE_REEXEC="1")
            argv = [str(py), str(SCRIPT), "gui"]
            if WINDOWS:
                subprocess.Popen(argv, env=env)
                return
            os.execve(argv[0], argv, env)
        die("the GUI needs PySide6, which this Python doesn't have. Install it into a venv next to rimstable:\n"
            f"  {'py' if WINDOWS else 'python3'} -m venv {APP_DIR / '.venv'}\n"
            f"  {venv_pip()} install PySide6\n"
            "then run 'rimstable gui' again (it picks up the venv by itself)")
    from .gui import main as gui_main
    sys.exit(gui_main())


def venv_pip():
    return APP_DIR / ".venv" / ("Scripts/pip.exe" if WINDOWS else "bin/pip")


def main():
    p = argparse.ArgumentParser(prog="rimstable", description=core.__doc__.splitlines()[0],
                                epilog=launch_hint(), formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("freeze", help="build/refresh the stable install from the Steam install")
    s.add_argument("--userdata", action="store_true", help="on refreeze, also replace config AND saves from Steam")
    s.add_argument("--allow-missing", action="store_true", help="freeze even if some active mods are not on disk")
    s.add_argument("--force", action="store_true", help="ignore the Steam-is-updating check")
    s.add_argument("-m", "--label", help="snapshot label")
    s.set_defaults(fn=cmd_freeze)

    s = sub.add_parser("diff", help="what changed on Steam since the freeze")
    s.set_defaults(fn=cmd_diff)

    s = sub.add_parser("pull", help="update one mod, or all changed mods, from Steam (snapshots first)")
    s.add_argument("mod", nargs="?", help="packageId, Workshop id, or part of the name")
    s.add_argument("--all", action="store_true",
                   help="update every stable mod that changed on Steam since the freeze, after one snapshot")
    s.add_argument("--force", action="store_true", help="ignore the Steam-is-updating check")
    s.set_defaults(fn=cmd_pull)

    s = sub.add_parser("snap", help="take a snapshot")
    s.add_argument("-m", "--label", help="snapshot label (default: manual)")
    s.set_defaults(fn=cmd_snap)

    sub.add_parser("list", help="list snapshots").set_defaults(fn=cmd_list)

    s = sub.add_parser("restore", help="roll the stable install back to a snapshot")
    s.add_argument("id", help="snapshot id or unique prefix, from 'rimstable list'")
    s.set_defaults(fn=cmd_restore)

    s = sub.add_parser("prune", help="delete all but the newest snapshots",
                       description="Delete every snapshot except the newest N (by time, any label) and free "
                                   "their disk space. Automatic pre-pull/pre-restore/pre-refreeze snapshots "
                                   "count toward N. Cannot be undone; check 'rimstable list' first.")
    s.add_argument("--keep", type=int, default=20, metavar="N",
                   help="how many of the newest snapshots to keep (default: 20, minimum 1)")
    s.set_defaults(fn=cmd_prune)

    sub.add_parser("status", help="summary of the stable install").set_defaults(fn=cmd_status)

    s = sub.add_parser("launch", help="run the stable install")
    s.add_argument("args", nargs=argparse.REMAINDER)
    s.set_defaults(fn=cmd_launch)

    s = sub.add_parser("shortcut", help="put a 'RimWorld (Stable)' launcher on your desktop")
    s.add_argument("--path", help="write the shortcut (.desktop, or .lnk on Windows) here instead of the Desktop")
    s.add_argument("--force", action="store_true", help="overwrite an existing shortcut")
    s.add_argument("--gui", action="store_true", help="make a 'Rimstable' launcher for the manager window instead")
    s.set_defaults(fn=cmd_shortcut)

    s = sub.add_parser("gui", help="open the manager window (needs PySide6)")
    s.set_defaults(fn=cmd_gui)

    if sys.stdout:  # None under pythonw (Windows shortcut)
        sys.stdout.reconfigure(line_buffering=True, errors="replace")
    if sys.stderr:
        sys.stderr.reconfigure(errors="replace")
    if len(sys.argv) == 1:
        p.print_help()
        return
    a = p.parse_args()
    try:
        a.fn(a)
    except RimstableError as e:
        print(f"rimstable: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
