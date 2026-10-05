# rimstable

Keeps a frozen, Steam-independent RimWorld install that only changes when you say so.
The Steam install (game + Workshop mods) becomes a test bed that updates freely; the
stable copy is never touched by Steam.

Python 3 stdlib, plus `rsync` and `restic` (>= 0.17).

## Layout

`~/Games/RimWorld-stable/` (override with `RIMSTABLE_ROOT`):

| path | contents |
|---|---|
| `game/` | copy of the Steam game dir, `steam_appid.txt` removed |
| `game/Mods/<workshopId>/` | every active Workshop mod. Folder names stay the Workshop id so `Mod_<id>_*.xml` settings still match |
| `userdata/` | config and saves, passed via `-savedatafolder` |
| `manifest.json` | game build and a fingerprint per mod at freeze time |
| `snapshots/` | restic repo (no password) of `game/`, `userdata/` and `manifest.json` |
| `.rimstable` | marker; rimstable refuses to write or delete outside a marked root |

## Commands

```
rimstable freeze [-m label]   first run: copy game, active mods, config+saves
                              later runs: snapshot, update game+mods+ModsConfig.xml,
                              add settings for new mods; stable saves are NOT touched
             --userdata       also replace stable config+saves with Steam's
rimstable diff                game build, mods updated on Steam since freeze,
                              load-order differences, how many mods support the
                              current Steam game version (e.g. 1.7)
rimstable pull <mod>          snapshot, then update one mod (packageId, Workshop id, or name)
rimstable snap [-m label]     snapshot
rimstable list                list snapshots
rimstable restore <id>        snapshot, then roll game/ and userdata/ back to <id>
rimstable prune [--keep 20]   forget old snapshots
rimstable status
rimstable launch [-- args]    run the stable copy
rimstable install             "RimWorld (Stable)" desktop entry (not added to PATH)
```

Freeze and pull refuse to run while RimWorld is running or Steam is mid-update
(`--force` overrides the Steam check).

## DLC workflow

1. Play the stable copy ("RimWorld (Stable)"). Let Steam update the regular install.
2. Try the DLC in the Steam install. Run `rimstable diff` now and then to see how many
   of your mods support the new version.
3. Once the Steam setup works for you, `rimstable freeze`. If it goes wrong,
   `rimstable restore <id>`.
4. Saves made on a newer game version won't load in an older frozen copy.

## Notes

- Launched outside Steam, SteamAPI init fails on purpose. That prevents a Workshop scan
  and duplicate mods. DLCs load from `game/Data/`; this was verified on 1.6.4871 rev600
  with all 6 DLCs and 253 active mods, and `activeMods` was unchanged after launch.
- Unity's own PlayerPrefs (window size and similar) are still written to
  `~/.config/unity3d/Ludeon Studios/RimWorld by Ludeon Studios/prefs`.
  Game config is not.
- `Version.txt` can be stale. The real revision comes from the game's ModsConfig.xml `<version>`.
