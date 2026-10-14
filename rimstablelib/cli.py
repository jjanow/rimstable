"""Command-line interface. Every command that changes files runs here; the GUI runs these as a subprocess."""
import argparse
import datetime as dt
import importlib.util
import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

from . import core, dds, modver
from .core import (
    APP_DIR, CFG_SRC, EXE_NAME, GAME, GAME_SRC, HELPER_FOLDER, MANIFEST, MARKER, MODS, ROOT, SCRIPT,
    RimstableError, USERDATA, USERDATA_SKIP, WINDOWS, assert_dest, changed_mods, desktop_dir, die,
    deactivate, diff_report, ensure_repo, game_info, held_mods, install_helper, keep_hold, label_of, launch_hint, load_manifest,
    mod_record,
    read_modsconfig, remove_mod_dir, require_not_running, require_same_version, require_steam_idle, resolve_active,
    restic, rimworld_pids, save_manifest, shortcut_name, snap_path, snapshot, snapshots, steam_mods, sync_into,
    workshop_times, write_shortcut,
)


def cmd_freeze(a):
    require_not_running()
    require_steam_idle(a.force)
    first = not MANIFEST.exists()
    if first and ROOT.exists() and any(ROOT.iterdir()) and not MARKER.exists():
        die(f"{ROOT} exists, is not empty and has no {MARKER.name} marker; refusing to use it")
    if not first:
        require_same_version(load_manifest()["game"])

    cfg = read_modsconfig(CFG_SRC)
    mods, missing = resolve_active(cfg["active"])
    old = {} if first else {r["packageId"]: r for r in load_manifest()["mods"]}
    # a held mod keeps its stable copy and manifest record, whether Steam has it active or not
    held = [r for r in old.values() if r.get("hold") and (MODS / r["folder"]).is_dir()]
    held_ids = {r["packageId"] for r in held}
    mods = [m for m in mods if m["packageId"] not in held_ids]
    # a mod missing from Steam keeps its stable copy (and manifest record) instead of being removed
    kept = [old[p] for p in missing if p in old and p not in held_ids and (MODS / old[p]["folder"]).is_dir()]
    if missing:
        kept_ids = {r["packageId"] for r in kept} | held_ids
        print("warning: active mods not found on disk (unsubscribed? still downloading?):")
        for p in missing:
            print(f"  {p}  ({'keeping the stable copy' if p in kept_ids else 'skipped'})")
    if held:
        print(f"keeping {len(held)} held mods as they are:")
        for r in sorted(held, key=lambda r: r["name"].lower()):
            note = "" if r["packageId"] in cfg["active"] else "  (not active in Steam, so inactive after the freeze)"
            print(f"  {r['folder']}  {r['name']}{note}")

    ROOT.mkdir(parents=True, exist_ok=True)
    MARKER.touch()
    if not first:
        snapshot("pre-refreeze")

    print(f"[game] {GAME_SRC} -> {GAME}")
    sync_into(GAME_SRC, GAME, exclude={"steam_appid.txt", "Mods"})
    MODS.mkdir(exist_ok=True)

    print(f"[mods] {len(mods)} mods -> {MODS}")
    keep = {HELPER_FOLDER} | {r["folder"] for r in kept + held}
    for mod in mods:
        folder = Path(mod["dir"]).name
        keep.add(folder)
        sync_into(mod["dir"], MODS / folder, exclude=dds.sync_exclude(mod["dir"], MODS / folder))
    for d in MODS.iterdir():
        if d.is_dir() and d.name not in keep:
            print(f"[mods] removing no-longer-active {d.name}")
            remove_mod_dir(d)
    if dds.enabled(dds.STABLE):
        dds.convert(dds.STABLE)

    if first:
        print(f"[userdata] {CFG_SRC} -> {USERDATA}")
        sync_into(CFG_SRC, USERDATA, delete=False, exclude=USERDATA_SKIP)
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
        "mods": [keep_hold(mod_record(m, times), old.get(m["packageId"])) for m in mods] + kept + held,
    })
    snapshot(" ".join(a.label) or ("first freeze" if first else "refreeze"))
    print(f"frozen: {len(mods)} mods, game {game_info(GAME_SRC, CFG_SRC)['revision']}")
    print(launch_hint())


def cmd_userdata(a):
    require_same_version(load_manifest()["game"])
    require_not_running()
    snapshot("pre-userdata")
    print(f"[userdata] {CFG_SRC} -> {USERDATA} (replacing, saves included)")
    sync_into(CFG_SRC, USERDATA, delete=True, exclude=USERDATA_SKIP)
    print("stable config and saves replaced with Steam's; the pre-userdata snapshot has the old ones")


def find_mod(query, records):
    q = query.lower()
    exact = [r for r in records if q in (r["packageId"], r["folder"])]
    if exact:
        return exact
    return [r for r in records if q in r["name"].lower() or q in r["packageId"]]


def stable_mod(query, man):
    """The one stable mod (manifest record) that query names."""
    hits = find_mod(query, man["mods"])
    if len(hits) != 1:
        die(f"'{query}' matches {len(hits)} mods in the stable copy" +
            ("".join(f"\n  {h['folder']}  {h['packageId']}  {h['name']}" for h in hits[:20])))
    return hits[0]


def hold_text(r):
    h = r["hold"]
    return f"held since {h['at'][:10]}" + (f": {h['reason']}" if h.get("reason") else "")


def cmd_hold(a):
    man = load_manifest()
    if a.all:
        # with -all the first word lands in `mod`; it's part of the reason
        reason = " ".join(([a.mod] if a.mod else []) + a.reason).strip()
        at = dt.datetime.now().isoformat(timespec="seconds")
        new = [r for r in man["mods"] if not r.get("hold")]
        for r in new:
            r["hold"] = {"reason": reason, "at": at}
        save_manifest(man)
        print(f"holding {len(new)} mods ({len(man['mods']) - len(new)} were already held and keep their reason): "
              "pull, Update all and freeze leave the stable copies alone" + (f"\nreason: {reason}" if reason and new else ""))
        return
    if not a.mod:
        die("name a mod to hold, or use -all")
    r = stable_mod(a.mod, man)
    reason = " ".join(a.reason).strip() or (r.get("hold") or {}).get("reason", "")
    r["hold"] = {"reason": reason, "at": dt.datetime.now().isoformat(timespec="seconds")}
    save_manifest(man)
    print(f"holding {r['name']} ({r['packageId']}): pull, Update all and freeze leave its stable copy alone"
          + (f"\nreason: {reason}" if reason else ""))


def cmd_unhold(a):
    man = load_manifest()
    if a.all:
        held = [r for r in man["mods"] if r.get("hold")]
        for r in held:
            del r["hold"]
        save_manifest(man)
        print(f"released {len(held)} mods; pull and freeze update them from Steam again")
        return
    if not a.mod:
        die("name a mod to release, or use -all")
    r = stable_mod(a.mod, man)
    if not r.get("hold"):
        print(f"{r['name']} ({r['packageId']}) isn't held")
        return
    del r["hold"]
    save_manifest(man)
    print(f"released {r['name']} ({r['packageId']}); pull and freeze update it from Steam again")



def cmd_remove(a):
    require_not_running()
    man = load_manifest()
    r = stable_mod(a.mod, man)
    pid = r["packageId"]
    snapshot(f"pre-remove {r['name']}")
    d = MODS / r["folder"]
    if d.is_dir():
        remove_mod_dir(d)
    man["mods"] = [m for m in man["mods"] if m["packageId"] != pid]
    man["active"] = [p for p in man["active"] if p.lower() != pid.lower()]
    save_manifest(man)
    off = deactivate(pid)
    print(f"removed {r['name']} ({pid}) from the stable copy" + (" and its active mods" if off else ""))
    if not r.get("hold"):
        print("note: it wasn't held, so freeze puts it back while Steam has it active")


def cmd_pull(a):
    require_not_running()
    require_steam_idle(a.force)
    man = load_manifest()
    ws = steam_mods()
    if not a.mod:
        return pull_all(man, ws, a.anyversion)
    candidates = [{"packageId": pid, "folder": m["dir"].name, "name": m["name"]} for pid, m in ws.items()]
    hits = find_mod(a.mod, candidates)
    if len(hits) != 1:
        die(f"'{a.mod}' matches {len(hits)} Steam mods (Workshop and local Mods/)" +
            ("".join(f"\n  {h['folder']}  {h['packageId']}  {h['name']}" for h in hits[:20])))
    pid = hits[0]["packageId"]
    src = dict(ws[pid], packageId=pid)
    old = next((r for r in man["mods"] if r["packageId"] == pid), None)
    if old and old.get("hold") and not a.held:
        die(f"{src['name']} ({pid}) is {hold_text(old)}\n"
            f"'rimstable unhold {old['folder']}' releases it; add -held to pull it once and keep the hold")
    probs = modver.pull_problems(src, man)
    if probs and not a.anyversion:
        die(f"{src['name']} ({pid}) won't work on the stable copy's RimWorld {man['game']['version_txt']}:\n  "
            + "\n  ".join(probs) + "\nadd -anyversion to pull it anyway")
    snapshot(f"pre-pull {src['name']}")
    dst = MODS / src["dir"].name
    sync_into(src["dir"], dst, exclude=dds.sync_exclude(src["dir"], dst))
    if dds.enabled(dds.STABLE):
        dds.convert(dds.STABLE, [dst])
    rec = keep_hold(mod_record(src, workshop_times()), old)
    man["mods"] = [r for r in man["mods"] if r["packageId"] != pid] + [rec]
    save_manifest(man)
    print(f"pulled {src['name']} ({pid})" + (", still held" if rec.get("hold") else ""))
    active = read_modsconfig(USERDATA)["active"]
    if pid not in active:
        print("note: this mod is not active in the stable install; enable it in the in-game mod manager")


def pull_all(man, ws, anyversion=False):
    """Update every stable mod that changed on Steam, after one snapshot. Mods new to Steam aren't added, and
    updates that won't work on the stable copy's game version are skipped unless anyversion. Held mods are
    never pulled here."""
    held = sorted(r["name"] for r, _, ch in held_mods(man, ws) if ch)
    if held:
        print(f"skipping {len(held)} held mods that changed on Steam: " + ", ".join(held))
    changed = sorted(changed_mods(man, ws), key=lambda x: x[1]["name"].lower())
    if not changed:
        print("all stable mods match Steam; nothing to pull")
        return
    if not anyversion:
        blocked = [(cur, probs) for _, cur in changed if (probs := modver.pull_problems(cur, man))]
        if blocked:
            print(f"skipping {len(blocked)} updates that won't work on the stable copy's RimWorld "
                  f"{man['game']['version_txt']} (add -anyversion to pull them anyway):")
            for cur, probs in blocked:
                print(f"  {cur['name']}: " + "; ".join(probs))
            skip = {id(cur) for cur, _ in blocked}
            changed = [(r, cur) for r, cur in changed if id(cur) not in skip]
            if not changed:
                print("nothing else to pull")
                return
    snapshot(f"pre-pull all ({len(changed)} mods)")
    times = workshop_times()
    pulled = []
    for i, (r, cur) in enumerate(changed, 1):
        print(f"[pull {i}/{len(changed)}] {cur['name']}")
        src = dict(cur, packageId=r["packageId"])
        dst = MODS / src["dir"].name
        sync_into(src["dir"], dst, exclude=dds.sync_exclude(src["dir"], dst))
        pulled.append(dst)
        rec = mod_record(src, times)
        man["mods"] = [m for m in man["mods"] if m["packageId"] != r["packageId"]] + [rec]
        save_manifest(man)  # after each mod, so an interrupted run leaves an accurate manifest
    if dds.enabled(dds.STABLE):
        dds.convert(dds.STABLE, pulled)  # one todds run; if interrupted, 'rimstable dds' finishes the job
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

    v = d["stable_target"] or "?"
    print(f"\nmods updated on Steam since freeze: {len(d['changed'])}")
    if d["changed"]:
        print(f"  ({v} changes = files the stable copy's RimWorld {v} loads; other = only other versions' "
              "files or metadata)")
    counts = {"blocked": 0, "loads": 0, "other": 0}
    for r, cur in sorted(d["changed"], key=lambda x: x[0]["name"].lower()):
        rv = d["review"].get(r["packageId"], {"problems": [], "loaded": ["?"]})
        kind = "blocked" if rv["problems"] else "loads" if rv["loaded"] else "other"
        counts[kind] += 1
        tag = {"blocked": "CAN'T PULL", "loads": f"{v} changes", "other": "other"}[kind]
        print(f"  {r['folder']:>11}  {when(r['folder'])}  {tag:<11} [{','.join(cur['supportedVersions'])}]  "
              f"{r['name']}")
        for p in rv["problems"]:
            print(f"  {'':>11}    {p}")
    if d["changed"]:
        print(f"  {counts['loads']} change what {v} loads, {counts['other']} only other versions or metadata"
              + (f", {counts['blocked']} won't work on {v} (pull skips them; -anyversion overrides)"
                 if counts["blocked"] else ""))
    if d["held"]:
        print(f"\nheld mods (pull and freeze leave them alone; 'rimstable unhold MOD' releases one): "
              f"{len(d['held'])}")
        rows = [(r, "Steam changed" if ch else "same as Steam" if cur else "not on Steam")
                for r, cur, ch in sorted(d["held"], key=lambda x: x[0]["name"].lower())]
        groups = {}
        for r, state in rows:
            groups.setdefault(r["hold"].get("reason", ""), []).append(state)
        if a.held or len(groups) == len(rows):
            for r, state in rows:
                reason = r["hold"].get("reason")
                print(f"  {r['folder']:>11}  {state:<13}  {r['name']}" + (f"  ({reason})" if reason else ""))
        else:
            # mods held with the same reason (e.g. by hold -all) collapse into one line; -held lists each
            for reason, states in sorted(groups.items(), key=lambda g: -len(g[1])):
                counts = ", ".join(f"{states.count(k)} {k}" for k in ("Steam changed", "same as Steam", "not on Steam")
                                   if states.count(k))
                print(f"  {len(states)} mods{f' ({reason})' if reason else ''}: {counts}")
            print("  ('rimstable diff -held' lists each one)")
    if d["gone"]:
        print(f"\nmods no longer in Steam's Workshop or local Mods/ folder (unsubscribed/removed): {len(d['gone'])}")
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
    snapshot(" ".join(a.label) or "manual")


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
        die("N must be at least 1")
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
    held = sorted((r for r in man["mods"] if r.get("hold")), key=lambda r: r["name"].lower())
    if held:
        print(f"held     {len(held)}")
        # mods held with the same reason (e.g. by hold -all) collapse into one line; lone holds are listed
        groups = {}
        for r in held:
            groups.setdefault(r["hold"].get("reason", ""), []).append(r)
        for reason, rs in sorted(groups.items(), key=lambda g: -len(g[1])):
            if len(rs) == 1:
                print(f"           {rs[0]['name']} ({rs[0]['folder']}), {hold_text(rs[0])}")
            else:
                since = min(r["hold"]["at"] for r in rs)[:10]
                print(f"           {len(rs)} mods held since {since}" + (f": {reason}" if reason else ", no reason")
                      + " ('rimstable diff -held' lists them)")
    snaps = snapshots()
    if snaps:
        print(f"snaps    {len(snaps)}, latest {snaps[-1]['short_id']} {label_of(snaps[-1])}")
    print(f"dds      {dds.status_line()}")
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


def leading(words, choices):
    """Pop words[0] if it is one of choices (the keyword part of `dds` and `shortcut` arguments)."""
    return words.pop(0) if words and words[0] in choices else None


def cmd_dds(a):
    words = list(a.words)
    dry_run = bool(leading(words, ["check"]))
    clean = bool(leading(words, ["clean"]))
    targets = dds.TARGETS[leading(words, dds.TARGETS) or "stable"]
    dds.require_root()
    if not dry_run:
        require_not_running()
    if dds.STEAM in targets and not dry_run:
        require_steam_idle(a.force)
    for t in targets:
        dirs = dds.mod_dirs(t, words) if words else None
        if clean:
            dds.clean(t, dirs, dry_run)
        else:
            dds.convert(t, dirs, dry_run)


def cmd_shortcut(a):
    words = list(a.words)
    gui = bool(leading(words, ["gui"]))
    if len(words) > 1:
        die("give at most one FILE")
    load_manifest()
    dest = Path(words[0]) if words else desktop_dir() / shortcut_name(gui)
    if dest.exists() and not a.force:
        die(f"{dest} already exists (add -force to overwrite)")
    write_shortcut(dest, gui=gui)
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


class Parser(argparse.ArgumentParser):
    """Help is -h or -help; rimstable has no double-dash options."""
    def __init__(self, *args, **kw):
        super().__init__(*args, add_help=False, **kw)
        self.add_argument("-h", "-help", action="help", help="show this help and exit")


def build_parser():
    p = Parser(prog="rimstable", description=core.__doc__.splitlines()[0],
                                epilog=launch_hint(), formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("freeze", help="build/refresh the stable install from the Steam install")
    s.add_argument("label", nargs="*", metavar="LABEL",
                   help="label for the snapshot taken after the freeze (default: first freeze / refreeze)")
    s.add_argument("-force", action="store_true", help="ignore the Steam-is-updating check")
    s.set_defaults(fn=cmd_freeze)

    s = sub.add_parser("userdata", help="replace the stable config AND saves with Steam's (snapshots first)")
    s.set_defaults(fn=cmd_userdata)

    s = sub.add_parser("diff", help="what changed on Steam since the freeze")
    s.add_argument("-held", action="store_true",
                   help="list every held mod instead of one line per hold reason")
    s.set_defaults(fn=cmd_diff)

    s = sub.add_parser("pull", help="update all changed mods, or one named mod, from Steam (snapshots first)")
    s.add_argument("mod", nargs="?",
                   help="packageId, Workshop id, or part of the name; omit to update every stable mod "
                        "that changed on Steam since the freeze, after one snapshot")
    s.add_argument("-force", action="store_true", help="ignore the Steam-is-updating check")
    s.add_argument("-anyversion", action="store_true",
                   help="pull even mods whose Steam version won't work on the stable copy's game version "
                        "(About.xml doesn't list it, or a DLL is built for a newer .NET)")
    s.add_argument("-held", action="store_true",
                   help="pull the named mod even though it's held (it stays held)")
    s.set_defaults(fn=cmd_pull)

    s = sub.add_parser("hold", help="keep a stable mod as it is: pull, Update all and freeze skip it")
    s.add_argument("mod", nargs="?", help="packageId, Workshop id/folder, or part of the name of a mod in the stable copy")
    s.add_argument("reason", nargs="*", metavar="REASON",
                   help="why it's held, quoted or not (shown by diff, status and the GUI)")
    s.add_argument("-all", action="store_true",
                   help="hold every mod in the stable copy (already-held mods keep their reason); "
                        "then everything after -all is the reason")
    s.set_defaults(fn=cmd_hold)

    s = sub.add_parser("unhold", help="release a held mod, so pull and freeze update it from Steam again")
    s.add_argument("mod", nargs="?", help="packageId, Workshop id/folder, or part of the name of a held mod")
    s.add_argument("-all", action="store_true", help="release every held mod")
    s.set_defaults(fn=cmd_unhold)

    s = sub.add_parser("remove", help="delete a mod from the stable copy: its folder, manifest record and "
                                      "activation (snapshots first)")
    s.add_argument("mod", help="packageId, Workshop id/folder, or part of the name of a mod in the stable copy")
    s.set_defaults(fn=cmd_remove)

    s = sub.add_parser("snap", help="take a snapshot")
    s.add_argument("label", nargs="*", metavar="LABEL", help="snapshot label, quoted or not (default: manual)")
    s.set_defaults(fn=cmd_snap)

    sub.add_parser("list", help="list snapshots").set_defaults(fn=cmd_list)

    s = sub.add_parser("restore", help="roll the stable install back to a snapshot")
    s.add_argument("id", help="snapshot id or unique prefix, from 'rimstable list'")
    s.set_defaults(fn=cmd_restore)

    s = sub.add_parser("prune", help="delete all but the newest snapshots",
                       description="Delete every snapshot except the newest N (by time, any label) and free "
                                   "their disk space. Automatic pre-pull/pre-restore/pre-refreeze snapshots "
                                   "count toward N. Cannot be undone; check 'rimstable list' first.")
    s.add_argument("keep", type=int, nargs="?", default=20, metavar="N",
                   help="how many of the newest snapshots to keep (default: 20, minimum 1)")
    s.set_defaults(fn=cmd_prune)

    sub.add_parser("status", help="summary of the stable install").set_defaults(fn=cmd_status)

    s = sub.add_parser("launch", help="run the stable install")
    s.add_argument("args", nargs=argparse.REMAINDER)
    s.set_defaults(fn=cmd_launch)

    s = sub.add_parser("dds", help="pre-encode mod textures as DDS with todds (much faster startup)",
                       usage="rimstable dds [check] [clean] [stable|steam|both] [MOD ...] [-force]",
                       formatter_class=argparse.RawDescriptionHelpFormatter,
                       epilog="  check                 only report what would happen\n"
                              "  clean                 delete the generated DDS instead (for all mods this also "
                              "turns\n                        automatic re-encoding off)\n"
                              "  stable|steam|both     the stable copy (default), the Steam install's active mods, "
                              "or both\n"
                              "  MOD                   limit to these mod folders (Workshop id) or packageIds",
                       description=textwrap.fill(
                                   "Encode each mod's Textures/*.png as DDS with todds, which RimWorld loads "
                                   "instead of the PNG. Only DDS that rimstable generated are ever replaced or "
                                   "deleted; DDS that mods ship are left alone. Once enabled for the stable copy, "
                                   "freeze and pull re-encode changed mods automatically; for Steam, run this again "
                                   "after Workshop updates. Re-runs only encode what is new or changed.", 79))
    s.add_argument("words", nargs="*", help=argparse.SUPPRESS)
    s.add_argument("-force", action="store_true", help="ignore the Steam-is-updating check")
    s.set_defaults(fn=cmd_dds)

    s = sub.add_parser("shortcut", help="put a 'RimWorld (Stable)' launcher on your desktop",
                       usage="rimstable shortcut [gui] [FILE] [-force]",
                       formatter_class=argparse.RawDescriptionHelpFormatter,
                       epilog="  gui                   make a 'Rimstable' launcher for the manager window instead\n"
                              "  FILE                  write the shortcut (.desktop, or .lnk on Windows) here "
                              "instead of the Desktop")
    s.add_argument("words", nargs="*", help=argparse.SUPPRESS)
    s.add_argument("-force", action="store_true", help="overwrite an existing shortcut")
    s.set_defaults(fn=cmd_shortcut)

    s = sub.add_parser("gui", help="open the manager window (needs PySide6)")
    s.set_defaults(fn=cmd_gui)

    return p


def main():
    p = build_parser()
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
