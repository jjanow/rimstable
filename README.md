# rimstable

Keeps a frozen, Steam-independent RimWorld install that only changes when you say so.
The Steam install (game + Workshop mods) becomes a test bed that updates freely; the
stable copy is never touched by Steam.

Runs on Linux and Windows. The command line needs Python 3 (stdlib only) and `restic` (>= 0.17) on PATH.
It is not installed on PATH; run it as `~/repos/rimstable/rimstable <command>` on Linux, or
`python path\to\rimstable <command>` on Windows. With no arguments it prints help and the launch command.

## Manager window

`rimstable gui` opens a window that does everything the commands do: an overview of the stable copy
against Steam, a searchable mod list with "Update all", per-mod pull and Hold/Unhold, snapshots with restore and
prune, a Textures (DDS) card showing what is encoded or waiting for each install with an
"Encode textures…" dialog, a Play button, and a log of every command it ran. It follows the system light/dark setting
(`RIMSTABLE_THEME=light` or `dark` overrides it).

The window needs [PySide6](https://pypi.org/project/PySide6/) (Qt). Install it in a venv
next to the script, and `rimstable gui` picks it up without needing to be activated:

```sh
python3 -m venv ~/repos/rimstable/.venv                 # Windows: py -m venv path\to\rimstable\.venv
~/repos/rimstable/.venv/bin/pip install PySide6          # Windows: path\to\rimstable\.venv\Scripts\pip install PySide6
~/repos/rimstable/rimstable gui
~/repos/rimstable/rimstable shortcut gui                 # optional: a "Rimstable" desktop launcher
```

The window only reads files itself. Every change runs the matching command (`rimstable freeze`, `pull`,
`hold`, `unhold`, `snap`, `restore`, `prune`, `shortcut`, `dds`) as a child process, so the checks below apply unchanged, and
the window asks before anything destructive (restore, prune, replacing saves with `userdata`, removing DDS). Play starts
`rimstable launch` detached, so closing the window doesn't close the game.

The code is in `rimstablelib/`: `core.py` (detection, copying, restic, safety checks), `dds.py` (todds
and the DDS ledgers), `cli.py` (the commands) and `gui/` (the window). The `rimstable` script is a thin entry point.

## Where it looks

The Steam library is found automatically: the Steam install (Linux: flatpak, `~/.local/share/Steam`,
`~/.steam/steam`; Windows: the `SteamPath` registry value, then Program Files), then whichever
library in `libraryfolders.vdf` has RimWorld. The game config comes from the matching place:

| | config/saves source |
|---|---|
| Linux, flatpak Steam | `~/.var/app/com.valvesoftware.Steam/.config/unity3d/Ludeon Studios/RimWorld by Ludeon Studios` |
| Linux, native Steam | `~/.config/unity3d/Ludeon Studios/RimWorld by Ludeon Studios` |
| Windows | `%USERPROFILE%\AppData\LocalLow\Ludeon Studios\RimWorld by Ludeon Studios` |

Override with `RIMSTABLE_STEAMAPPS` (the `steamapps` dir) and `RIMSTABLE_CONFIG_SRC`.

## Layout

`~/Games/RimWorld-stable/` (Windows: `%USERPROFILE%\Games\RimWorld-stable`; override with `RIMSTABLE_ROOT`):

| path | contents |
|---|---|
| `game/` | copy of the Steam game dir, `steam_appid.txt` removed |
| `game/Mods/<workshopId>/` | every active Workshop mod. Folder names stay the Workshop id so `Mod_<id>_*.xml` settings still match |
| `game/Mods/rimstable_nosteamnag/` | the bundled helper mod that closes the Steam API dialog (see Notes) |
| `userdata/` | config and saves, passed via `-savedatafolder` |
| `manifest.json` | game build and a fingerprint per mod at freeze time |
| `snapshots/` | restic repo (no password) of `game/`, `userdata/` and `manifest.json` |
| `.rimstable` | marker; rimstable refuses to write or delete outside a marked root |

## Commands

Run with no arguments, or `-h` after any command (`rimstable prune -h`), for built-in help.

| command | what it does |
|---|---|
| `freeze` | build or refresh the stable copy from the Steam install |
| `userdata` | replace the stable config and saves with Steam's |
| `diff [-held]` | show what changed on Steam since the last freeze |
| `pull [mod]` | update every changed mod from Steam, or just the named one |
| `hold <mod> [reason]` / `unhold <mod>` | keep a stable mod as it is, or release it |
| `remove <mod>` | delete a mod from the stable copy |
| `snap` | take a snapshot |
| `list` | list snapshots |
| `restore <id>` | roll the stable copy back to a snapshot |
| `prune` | delete all but the newest snapshots |
| `status` | summary of the stable copy |
| `dds` | pre-encode mod textures as DDS for a faster start (stable and/or Steam) |
| `launch` | run the stable copy |
| `shortcut` | create a desktop launcher |
| `gui` | open the manager window (see above) |

### `freeze [LABEL] [-force]`

The first run copies the game, every active Workshop mod, and your config and saves into the
stable root. Later runs ("refreezes") take a snapshot, then bring the game and mods up to
date with Steam, remove mods that are no longer active, and copy Steam's `ModsConfig.xml`
(load order). They add settings files only for mods that are new to the stable copy.
Stable saves and existing mod settings are left alone. Steam's Missile Girl/Gagarin XML cache
(`MissileGirl/Cache`) is never copied: it records Steam paths and would force a rebuild.
`LABEL` names the snapshot taken after the freeze (default `first freeze` / `refreeze`), and can be
several words, quoted or not. `-force` skips the "Steam is mid-update" check.

Active mods that aren't on disk (unsubscribed, still downloading) don't stop the freeze. They're
listed as a warning. On a refreeze, a stable copy of such a mod is kept as it is; on the first
freeze, it's skipped.

A refreeze keeps held mods (see `hold`) as they are: their stable copy and manifest record stay, even
when Steam has a newer version or no longer has the mod active. A held mod that isn't active in Steam
is inactive in the stable copy afterwards, because the refreeze takes Steam's load order.

A refreeze refuses when Steam's game is a different major.minor version (e.g. 1.7) than the stable
copy (e.g. 1.6). Moving the stable copy to a new version isn't supported yet: RimWorld resets a mod
list saved by another major.minor, and `launch` only knows the stable version's executable
(`RimWorldLinux`; 1.7 runs as `RimWorld`). `pull` still works across versions, but it refuses mod
updates that won't work on the stable copy's version (see `pull`).

### `userdata`

Takes a `pre-userdata` snapshot, then replaces all stable config **and saves** with Steam's. The
old ones stay in that snapshot if you need them back. To refreeze and take Steam's saves, run
`freeze` and then `userdata`. Like a refreeze, it refuses when Steam's game is a different
major.minor version than the stable copy: the stable game would reset Steam's mod list.

### `diff [-held]`

Read-only. Compares the stable copy with the Steam install and shows:

- the game build, and whether it changed
- mods updated on Steam since the freeze, each marked `1.6 changes` (files the stable copy's game
  version loads changed), `other` (only other versions' folders or metadata changed, e.g. a new `1.7/`
  folder), or `CAN'T PULL` with the reason (see `pull`). Held mods aren't counted here.
- held mods with their reason, and whether Steam's copy changed, is the same, or is gone. Mods held
  with the same reason (e.g. by `hold -all`) show as one line with those counts; `-held` lists each.
- mods that are no longer in the Workshop folder or the Steam game's local `Mods/` folder
- differences in the active mod list
- how many stable mods support the Steam game's version (e.g. 1.7)

### `pull [mod] [-force] [-anyversion] [-held]`

Takes a snapshot, then copies one mod from the Workshop folder, or the Steam game's local `Mods/`
folder, into the stable copy.
`<mod>` can be an exact packageId or Workshop id, or part of the mod's name or packageId.
It has to match exactly one mod, or pull lists the candidates and stops. Pull doesn't change the
load order. If the mod isn't active in the stable copy, enable it in the in-game mod manager.
`-force` skips the "Steam is mid-update" check.

Pull refuses a mod whose Steam version won't work on the stable copy's game version: its About.xml
doesn't list that version (e.g. 1.6), or a DLL that version would load is built for .NET (RimWorld 1.7
and later) while the stable game runs .NET Framework. Which folders count as loaded follows RimWorld's
own rules: `LoadFolders.xml`, else the version folder, `Common/` and the mod root. Note that RimWorld
falls back to the oldest version folder above its own when no older one exists, so a mod with only a
`1.7/` folder loads it on 1.6. `-anyversion` pulls anyway.

Pull also refuses a held mod (see `hold`). `-held` pulls it once and keeps the hold.

With no `<mod>`, pull updates every stable mod that `diff` lists as updated on Steam, after a single snapshot.
It doesn't add Workshop mods the stable copy doesn't have, leaves mods that are no longer on Steam
alone, and skips (and lists) held mods and updates that won't work on the stable copy's game version.
The manager window's "Update all" button runs this.

### `hold <mod> [REASON]`, `hold -all [REASON]`, `unhold <mod>`, `unhold -all`

`hold` keeps a stable mod as it is: `pull` with no mod named, "Update all" and `freeze` leave its
stable copy and manifest record alone, and `pull <mod>` refuses it unless given `-held`. Use it for mods
whose stable copy differs from Steam's on purpose, e.g. your own mods, where Steam has the 1.7 build
and the stable copy keeps the 1.6 one. `<mod>` matches mods in the stable copy the same way `pull`
matches Steam mods. `REASON` is optional, can be several words, and is shown by `diff`, `status` and
the manager window; holding a held mod again without a reason keeps the old one. `unhold` releases it.

`hold -all` holds every mod in the stable copy, freezing the whole known-working set; mods that were
already held keep their reason. A single mod can still be updated on purpose with `pull <mod> -held`.
`unhold -all` releases every held mod.

Holds live in `manifest.json` and take no snapshot. `restore` puts back the holds the snapshot had.

### `remove <mod>`

Deletes a mod from the stable copy, after a snapshot: its folder in `Mods/`, its manifest record and its
line in the stable `ModsConfig.xml` active list. This is how a held mod leaves the stable copy (e.g. after
unsubscribing on Steam), since `freeze` keeps held mods and mods missing from Steam. `<mod>` matches like
`hold`. A mod that wasn't held comes back on the next `freeze` while Steam still has it active.

### `snap [LABEL]`

Takes a snapshot of `game/`, `userdata/` and `manifest.json`. The label defaults to `manual`.
It can be several words, quoted or not: `rimstable snap before big update`.

### `list`

Shows snapshots oldest first: short id, time, label.

### `restore <id>`

Takes a snapshot of the current state (`pre-restore <id>`), then rolls `game/`, `userdata/`
and `manifest.json` back to snapshot `<id>`. Files that aren't in that snapshot are deleted.
`<id>` is any unique prefix of an id from `rimstable list`. If the restore was a mistake,
restore the `pre-restore` snapshot.

### `prune [N]`

Deletes all snapshots except the newest `N` (default **20**), counted by time and ignoring
labels. The data they used is then freed on disk. Prune never runs by itself;
snapshots pile up until you run it.

Snapshots are taken automatically, so they count toward `N`:

| command | snapshot(s) taken |
|---|---|
| `freeze` (first run) | `first freeze` after copying |
| `freeze` (refreeze) | `pre-refreeze` before, then `refreeze` (or your label) after |
| `userdata` | `pre-userdata` before |
| `pull` | `pre-pull <mod name>` before (`pre-pull all (N mods)` with no mod named) |
| `restore` | `pre-restore <id>` before |
| `snap` | `manual` (or your label) |

For example, with 25 snapshots, `rimstable prune 5` deletes the oldest 20 and keeps
the newest 5. The snapshot you care about can be pushed out by later automatic ones, so check
`rimstable list` first. Prune can't be undone. `N` must be at least 1; `prune 0` is refused and
deletes nothing.

### `status`

Shows the stable root, freeze time, game version, mod count, held mods with their reason (mods held with the same reason, e.g. by `hold -all`, as one line), snapshot count with the latest
snapshot, how many generated DDS each target has (or `off`), and whether RimWorld is running.

### `dds [check] [clean] [stable|steam|both] [MOD ...] [-force]`

Encodes each mod's `Textures/**/*.png` as DDS with [todds](https://github.com/todds-encoder/todds).
RimWorld loads `Foo.dds` instead of `Foo.png` when both exist, which skips PNG decoding and
compression at startup. With ~250 mods this cut texture loading from 63s to 9s, about 60s off
the startup. The first full run takes a few minutes and roughly doubles the size of the mods
folder (2 GB to 4 GB here).

- `stable` (default) is the stable copy, `steam` is the Steam install's active mods
  (Workshop and local `Mods/`), and `both` is both.
- `MOD ...` limits the run to some mod folders (Workshop id) or packageIds.
- Re-runs only encode new PNGs and PNGs that changed since their DDS was made.
- PNGs whose width or height isn't a multiple of 4 are skipped. Unity refuses block-compressed
  DDS of that size and the texture would go missing, so those keep loading as PNG.
- `clean` deletes the generated DDS. For all mods it also turns DDS off for that target.
- `check` only reports counts (`dds check clean steam` reports what `dds clean steam` would delete).
- Encoding only runs for a 1.6 game; for any other version (e.g. Steam's 1.7) `dds` and `dds check`
  refuse and the GUI's Encode button is disabled. `clean` still works. 1.7 also prefers `Foo.dds`,
  but it compresses PNGs itself (BC1/BC7, BC4/BC5) and caches the result on disk, so pre-encoding
  saves little there, and whether todds' vertical flip is still right on 1.7 is untested.
- `-force` skips the "Steam is mid-update" check.
- The words go in that order, before any `MOD`. A mod folder literally named `check`, `clean`,
  `stable`, `steam` or `both` can't be given as a `MOD`; use its packageId.

Every DDS rimstable makes is recorded with the PNG it came from, in
`game/Mods/.rimstable-dds.json` (stable, part of snapshots) and `dds-steam.json` in the stable
root (Steam). Only recorded files are ever replaced or deleted, so DDS that mods ship are left alone.
`diff` and `pull` ignore generated DDS in Steam mod folders, so converting the Steam install doesn't
make mods look updated.

Once enabled for the stable copy, `freeze` and `pull` keep the existing DDS and re-encode only
what changed. The Steam install has no hook. Run `rimstable dds steam` again after
Workshop updates.

The todds binary is looked up via `RIMSTABLE_TODDS`, then `PATH`, then `tools/todds`
(`tools/todds.exe` on Windows) next to the script. `tools/` is gitignored; download a release
from GitHub into it.

### `launch [-- ARGS]`

Runs the stable copy with `-savedatafolder` pointing at `userdata/`. Anything after `--` is
passed to RimWorld, e.g. `rimstable launch -- -popupwindow`. The previous `Player.log` is
kept as `Player-prev.log`. Before starting, it installs the NoSteamNag helper mod and activates
it after Harmony if it isn't already active.

### `shortcut [gui] [FILE] [-force]`

Creates a "RimWorld (Stable)" launcher on the Desktop: a `.desktop` file on Linux, a `.lnk` on
Windows. `shortcut gui` creates a "Rimstable" launcher for the manager window instead. Give a
`FILE` to write it there instead of the Desktop. An existing shortcut is only replaced with `-force`.

### `gui`

Opens the manager window. If the running Python has no PySide6 it uses `.venv/` next to the script,
or prints how to create it.

### Safety checks

`freeze`, `pull`, `restore`, `snap`, `prune`, `launch` and `dds` (except `dds check`) won't run while
RimWorld is running (`RimWorldLinux`, or `RimWorld` for 1.7, on Linux). `freeze`, `pull` and `dds steam` also won't run while Steam is updating
RimWorld or a mod; `-force` skips that check. A refreeze and `userdata` won't run while Steam's game
is a different major.minor version than the stable copy. In Steam's folders, `dds` only creates `.dds` files
next to PNGs and only deletes ones it recorded; nothing else there is ever written.

## DLC workflow

1. Play the stable copy (`rimstable launch`, or the desktop shortcut from `rimstable shortcut`). Let Steam update the regular install.
2. Try the DLC in the Steam install. Run `rimstable diff` now and then to see how many
   of your mods support the new version.
3. Once the Steam setup works for you, `rimstable freeze`. If it goes wrong,
   `rimstable restore <id>`. This works within one major.minor version. A refreeze onto a new one
   (1.6 to 1.7) is refused for now; meanwhile `rimstable pull` keeps the stable copy's mods current.
4. Saves made on a newer game version won't load in an older frozen copy.

## Notes

- Launched outside Steam, SteamAPI init fails on purpose. That prevents a Workshop scan
  and duplicate mods. DLCs load from `game/Data/`; this was verified on 1.6.4871 rev600
  with all 6 DLCs and 253 active mods, and `activeMods` was unchanged after launch.
- Because SteamAPI init fails, RimWorld shows a "Could not initialize Steam API" dialog at the
  main menu. The bundled `NoSteamNag/` mod (packageId `rimstable.nosteamnag`, needs Harmony)
  closes it with a postfix on `UIRoot_Entry.Init`; Steam stays disconnected. `freeze` and
  `launch` copy it to `game/Mods/rimstable_nosteamnag/` and activate it after
  `brrainz.harmony`, and `diff` doesn't report it. The prebuilt DLL is committed. If a game
  update breaks it, rebuild with `dotnet build -c Release` in `NoSteamNag/Source`
  (`-p:GameDir=<game dir>` if the stable root isn't the default).
- Unity's own PlayerPrefs (window size and similar) are still written to
  `~/.config/unity3d/Ludeon Studios/RimWorld by Ludeon Studios/prefs` on Linux, or to the
  registry on Windows. Game config is not.
- The Windows code paths have not been tested on Windows yet. In particular, check that
  `rimstable launch` starts the frozen copy and doesn't hand off to the Steam one. The manager
  window hasn't been run on Windows either: check that commands run without a console window popping
  up, that Play starts the game, and that shortcuts made from the window work (they point at the
  `.venv`'s `pythonw.exe` when the window runs from there).
- The manager window follows light/dark changes while it's open only with PySide6 6.5 or newer;
  older versions pick the theme at startup.
- `Version.txt` can be stale. The real revision comes from the game's ModsConfig.xml `<version>`.
