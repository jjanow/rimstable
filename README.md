# rimstable

Keeps a frozen, Steam-independent RimWorld install that only changes when you say so.
The Steam install (game + Workshop mods) becomes a test bed that updates freely; the
stable copy is never touched by Steam.

Runs on Linux and Windows. The command line needs Python 3 (stdlib only) and `restic` (>= 0.17) on PATH.
It is not installed on PATH; run it as `~/repos/rimstable/rimstable <command>` on Linux, or
`python path\to\rimstable <command>` on Windows. With no arguments it prints help and the launch command.

## Manager window

`rimstable gui` opens a window that does everything the commands do: an overview of the stable copy
against Steam, a searchable mod list with one-click pull, snapshots with restore and prune, a Play
button, and a log of every command it ran. It follows the system light/dark setting
(`RIMSTABLE_THEME=light` or `dark` overrides it).

The window needs [PySide6](https://pypi.org/project/PySide6/) (Qt). Install it in a venv
next to the script, and `rimstable gui` picks it up without needing to be activated:

```sh
python3 -m venv ~/repos/rimstable/.venv                 # Windows: py -m venv path\to\rimstable\.venv
~/repos/rimstable/.venv/bin/pip install PySide6          # Windows: path\to\rimstable\.venv\Scripts\pip install PySide6
~/repos/rimstable/rimstable gui
~/repos/rimstable/rimstable shortcut --gui               # optional: a "Rimstable" desktop launcher
```

The window only reads files itself. Every change runs the matching command (`rimstable freeze`, `pull`,
`snap`, `restore`, `prune`, `shortcut`) as a child process, so the checks below apply unchanged, and
the window asks before anything destructive (restore, prune, refreeze with `--userdata`). Play starts
`rimstable launch` detached, so closing the window doesn't close the game.

The code is in `rimstablelib/`: `core.py` (detection, copying, restic, safety checks), `cli.py` (the
commands) and `gui/` (the window). The `rimstable` script is a thin entry point.

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
| `diff` | show what changed on Steam since the last freeze |
| `pull <mod>` | update a single mod from Steam |
| `snap` | take a snapshot |
| `list` | list snapshots |
| `restore <id>` | roll the stable copy back to a snapshot |
| `prune` | delete all but the newest snapshots |
| `status` | summary of the stable copy |
| `launch` | run the stable copy |
| `shortcut` | create a desktop launcher |
| `gui` | open the manager window (see above) |

### `freeze [--userdata] [--allow-missing] [--force] [-m LABEL]`

The first run copies the game, every active Workshop mod, and your config and saves into the
stable root. Later runs ("refreezes") take a snapshot, then bring the game and mods up to
date with Steam, remove mods that are no longer active, and copy Steam's `ModsConfig.xml`
(load order). They add settings files only for mods that are new to the stable copy.
Stable saves and existing mod settings are left alone. Steam's Missile Girl/Gagarin XML cache
(`MissileGirl/Cache`) is never copied: it records Steam paths and would force a rebuild.

| option | effect |
|---|---|
| `--userdata` | on a refreeze, replace all stable config **and saves** with Steam's (they're in the pre-refreeze snapshot if you need them back) |
| `--allow-missing` | freeze even if some active mods aren't on disk (unsubscribed, still downloading). Without it, freeze stops and lists them |
| `--force` | skip the "Steam is mid-update" check |
| `-m`, `--label LABEL` | label for the snapshot taken after the freeze (default `first freeze` / `refreeze`) |

### `diff`

Read-only. Compares the stable copy with the Steam install and shows:

- the game build, and whether it changed
- mods updated on Steam since the freeze
- mods that are no longer in the Workshop folder
- differences in the active mod list
- how many stable mods support the Steam game's version (e.g. 1.7)

### `pull <mod> [--force]`

Takes a snapshot, then copies one mod from the Workshop folder into the stable copy.
`<mod>` can be an exact packageId or Workshop id, or part of the mod's name or packageId.
It has to match exactly one mod, or pull lists the candidates and stops. Pull doesn't change the
load order. If the mod isn't active in the stable copy, enable it in the in-game mod manager.
`--force` skips the "Steam is mid-update" check.

### `snap [-m LABEL]`

Takes a snapshot of `game/`, `userdata/` and `manifest.json`. The label defaults to `manual`.

### `list`

Shows snapshots oldest first: short id, time, label.

### `restore <id>`

Takes a snapshot of the current state (`pre-restore <id>`), then rolls `game/`, `userdata/`
and `manifest.json` back to snapshot `<id>`. Files that aren't in that snapshot are deleted.
`<id>` is any unique prefix of an id from `rimstable list`. If the restore was a mistake,
restore the `pre-restore` snapshot.

### `prune [--keep N]`

Deletes all snapshots except the newest `N` (default **20**), counted by time and ignoring
labels. The data they used is then freed on disk. Prune never runs by itself;
snapshots pile up until you run it.

Snapshots are taken automatically, so they count toward `N`:

| command | snapshot(s) taken |
|---|---|
| `freeze` (first run) | `first freeze` after copying |
| `freeze` (refreeze) | `pre-refreeze` before, then `refreeze` (or your `-m` label) after |
| `pull` | `pre-pull <mod name>` before |
| `restore` | `pre-restore <id>` before |
| `snap` | `manual` (or your `-m` label) |

For example, with 25 snapshots, `rimstable prune --keep 5` deletes the oldest 20 and keeps
the newest 5. The snapshot you care about can be pushed out by later automatic ones, so check
`rimstable list` first. Prune can't be undone. `N` must be at least 1; `--keep 0` is refused and
deletes nothing.

### `status`

Shows the stable root, freeze time, game version, mod count, snapshot count with the latest
snapshot, and whether RimWorld is running.

### `launch [-- ARGS]`

Runs the stable copy with `-savedatafolder` pointing at `userdata/`. Anything after `--` is
passed to RimWorld, e.g. `rimstable launch -- -popupwindow`. The previous `Player.log` is
kept as `Player-prev.log`. Before starting, it installs the NoSteamNag helper mod and activates
it after Harmony if it isn't already active.

### `shortcut [--path FILE] [--force] [--gui]`

Creates a "RimWorld (Stable)" launcher on the Desktop: a `.desktop` file on Linux, a `.lnk` on
Windows.

| option | effect |
|---|---|
| `--path FILE` | write the shortcut to `FILE` instead of the Desktop |
| `--force` | overwrite an existing shortcut |
| `--gui` | create a "Rimstable" launcher for the manager window instead |

### `gui`

Opens the manager window. If the running Python has no PySide6 it uses `.venv/` next to the script,
or prints how to create it.

### Safety checks

`freeze`, `pull`, `restore`, `snap`, `prune` and `launch` won't run while RimWorld is running.
`freeze` and `pull` also won't run while Steam is updating RimWorld or a mod; `--force` skips
that check.

## DLC workflow

1. Play the stable copy (`rimstable launch`, or the desktop shortcut from `rimstable shortcut`). Let Steam update the regular install.
2. Try the DLC in the Steam install. Run `rimstable diff` now and then to see how many
   of your mods support the new version.
3. Once the Steam setup works for you, `rimstable freeze`. If it goes wrong,
   `rimstable restore <id>`.
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
