"""Which files of a mod a given RimWorld version loads, and whether a mod update still works on the stable
copy's version.

load_folders() follows RimWorld 1.6's ModContentPack.InitLoadFolders: LoadFolders.xml's exact version key,
else its newest key at or below the game version, else its "default" key; without a usable LoadFolders.xml,
the version folder (exact, else the newest below, else the oldest above), Common/ and the mod root.
"""
import hashlib
import os
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from .core import GAME

# folders RimWorld reads inside each load folder
CONTENT_DIRS = {"assemblies", "defs", "patches", "languages", "textures", "sounds", "assetbundles"}


def parse_version(s):
    """'1.6', 'v1.6' or '1.6.4871 rev598' -> (1, 6, 4871, -1), padded like System.Version; None if not one."""
    m = re.match(r"v?(\d+)\.(\d+)(?:\.(\d+))?(?:\.(\d+))?(?=$|\s)", (s or "").strip().lower())
    if not m:
        return None
    return tuple(int(g) if g is not None else -1 for g in m.groups())


def short(ver):
    return f"{ver[0]}.{ver[1]}"


def find_ci(d, name):
    """The entry of d named `name`, ignoring case."""
    return next((p for p in Path(d).iterdir() if p.name.lower() == name.lower()), None)


def read_loadfolders(f):
    """{version key: [folder, ...]} from LoadFolders.xml ("" = mod root). IfModActive conditions are ignored:
    every listed folder counts as loaded."""
    try:
        root = ET.parse(f).getroot()
    except ET.ParseError:
        return {}
    out = {}
    for v in root:
        if not isinstance(v.tag, str):
            continue
        key = v.tag.lower()
        key = key[1:] if key.startswith("v") else key
        folders = out.setdefault(key, [])
        for li in v:
            if not isinstance(li.tag, str):
                continue
            t = (li.text or "").strip()
            folders.append("" if t in ("/", "\\") else t.replace("\\", "/").strip("/"))
    return out


def load_folders(moddir, ver):
    """Folders (relative to moddir, "" = root) that RimWorld `ver` loads from moddir, highest priority first."""
    moddir = Path(moddir)
    lf = find_ci(moddir, "LoadFolders.xml")
    keys = read_loadfolders(lf) if lf and lf.is_file() else {}
    if keys:
        exact = keys.get(".".join(str(x) for x in ver if x >= 0))
        if exact:
            return exact[::-1]
        older = [k for k in keys if k != "default" and "." in k and (parse_version(k) or (99999,)) <= ver]
        if older:
            return keys[max(older)][::-1]
        if "default" in keys:
            return keys["default"][::-1]
    folders = []
    if (moddir / short(ver)).is_dir():
        folders.append(short(ver))
    else:
        found = sorted((v, d.name) for d in moddir.iterdir()
                       if d.is_dir() and re.fullmatch(r"\d+\.\d+", d.name) and (v := parse_version(d.name)))
        below = [n for v, n in found if v <= ver]
        if below:
            folders.append(below[-1])
        elif found:
            folders.append(found[0][1])
    if (moddir / "Common").is_dir():
        folders.append("Common")
    return folders + [""]


def loaded_files(moddir, ver, skip=()):
    """{content path ('Assemblies/X.dll', 'Defs/...'): [file, ...] in load-folder priority order} for the files
    RimWorld `ver` reads from moddir. `skip` holds moddir-relative posix paths to leave out."""
    moddir = Path(moddir)
    out = {}
    for folder in load_folders(moddir, ver):
        base = moddir / folder
        if not base.is_dir():
            continue
        for sub in base.iterdir():
            if not sub.is_dir() or sub.name.lower() not in CONTENT_DIRS:
                continue
            for dirpath, dirnames, filenames in os.walk(sub):
                dirnames.sort()
                for fn in sorted(filenames):
                    p = Path(dirpath) / fn
                    if p.relative_to(moddir).as_posix() in skip:
                        continue
                    rel = p.relative_to(sub).as_posix()
                    out.setdefault(f"{sub.name.lower()}/{rel}", []).append(p)
    return out


def same_file(a, b):
    sa, sb = os.stat(a), os.stat(b)
    if sa.st_size != sb.st_size:
        return False
    if int(sa.st_mtime) == int(sb.st_mtime):
        return True
    return digest(a) == digest(b)


def digest(p):
    h = hashlib.sha1()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.digest()


def loaded_changes(new_dir, old_dir, ver, new_skip=(), old_skip=()):
    """Content paths whose loaded files differ between two copies of a mod for RimWorld `ver` (added, removed
    or changed). Each copy is resolved with its own LoadFolders.xml, so moving a file between load folders
    unchanged is no change."""
    new, old = loaded_files(new_dir, ver, new_skip), loaded_files(old_dir, ver, old_skip)
    return sorted(k for k in new.keys() | old.keys()
                  if len(new.get(k, [])) != len(old.get(k, []))
                  or not all(same_file(a, b) for a, b in zip(new[k], old[k])))


def dll_runtime(p):
    """'netcore' (.NET 5+, RimWorld 1.7 on), 'netfx' (.NET Framework) or None, from the TargetFramework
    attribute's string in the assembly."""
    try:
        data = Path(p).read_bytes()
    except OSError:
        return None
    if b".NETCoreApp,Version=v" in data:
        return "netcore"
    if b".NETFramework,Version=v" in data:
        return "netfx"
    return None


def game_runtime(gamedir):
    """'netcore' for a game running on .NET (1.7 ships RimWorld.runtimeconfig.json), else 'netfx' (Unity Mono)."""
    return "netcore" if any(Path(gamedir).glob("*.runtimeconfig.json")) else "netfx"


def problems(moddir, ver, runtime, supported):
    """Reasons a mod won't work on RimWorld `ver` with the given runtime: its About.xml doesn't list the
    version, or a DLL it would load is built for .NET while the game runs .NET Framework."""
    out = []
    if supported and short(ver) not in supported:
        out.append(f"doesn't list {short(ver)} in supportedVersions ({', '.join(supported)})")
    if runtime == "netfx":
        for k, files in loaded_files(moddir, ver).items():
            if k.startswith("assemblies/") and k.endswith(".dll"):
                for p in files:
                    if dll_runtime(p) == "netcore":
                        out.append(f"{p.relative_to(moddir).as_posix()} is built for .NET (RimWorld 1.7+), "
                                   "not the .NET Framework this game runs")
    return out


def stable_version(man):
    return parse_version(man["game"]["version_txt"])


def pull_problems(mod, man):
    """problems() for copying a Steam mod into the stable copy; [] when the stable version is unknown."""
    ver = stable_version(man)
    if not ver:
        return []
    return problems(mod["dir"], ver, game_runtime(GAME), mod["supportedVersions"])


def review(man, changed, stable_mods):
    """packageId -> {"problems": [...], "loaded": [content paths that change for the stable version]} for
    every (manifest record, Steam mod) in `changed`. `stable_mods` is the stable copy's Mods/ folder."""
    from . import dds
    ver = stable_version(man)
    if not ver:
        return {}
    runtime = game_runtime(GAME)
    ledger = dds.load(dds.STABLE)
    out = {}
    for r, cur in changed:
        src, dst = Path(cur["dir"]), Path(stable_mods) / r["folder"]
        loaded = loaded_changes(src, dst, ver, dds.workshop_generated(src),
                                dds.ours(dds.STABLE, ledger, dst)) if dst.is_dir() else ["(not in the stable copy)"]
        out[r["packageId"]] = {"problems": problems(src, ver, runtime, cur["supportedVersions"]), "loaded": loaded}
    return out


def newest_mtime(d):
    """Newest file mtime under d (the 'updated' date for mods Steam's workshop manifest doesn't list)."""
    best = 0
    for dirpath, _, filenames in os.walk(d):
        for fn in filenames:
            try:
                best = max(best, int(os.lstat(os.path.join(dirpath, fn)).st_mtime))
            except OSError:
                pass
    return best or None
