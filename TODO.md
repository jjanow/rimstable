# TODO: a stable copy per RimWorld version

## What rimstable is for

**Point-in-time copies of mods that are known to work, attached to the game version they work on.**

The problem it solves: Steam updates Workshop mods whenever their authors do. Those updates
frequently break the 1.6 game, and mods whose authors never update break 1.7 (both the Steam install
and anything frozen from it). So rimstable freezes a working game + mod set and keeps it apart from
Steam:

1. **The 1.6 stable copy** (`~/Games/RimWorld-stable`, 1.6.4871) holds the mods as they were when
   1.6 worked. It stays exactly as it is; this is the user's only fully working install right now.
2. **A 1.7 stable copy, later.** Over the coming weeks the user gets Steam's 1.7 install working
   (dropping or replacing mods that broke). Once it works, rimstable freezes it into a separate
   copy (e.g. `~/Games/RimWorld-stable-1.7`) the same way the 1.6 copy was made.
3. **Repeat for every future version or DLC:** get Steam working, freeze a new copy. Older copies
   are left alone.
4. **The copies never interact.** Each has its own game, mods, manifest, userdata, snapshots and
   shortcut. No migration, nothing copied from one to another.
5. **Mod updates are only ever on demand.** In a copy, one mod or all of them can be updated from
   Steam's Workshop when the user asks; nothing updates on its own, and by default a copy's mods
   don't change at all.

Status as of 2026-10-13: Steam is 1.7.4977. The 1.6 copy cannot be refrozen any more (Steam's game is
1.7; `freeze` refuses), so from now on it only changes through `pull` (and `restore`).

## Done (already supports the above)

- [x] One copy per root: `RIMSTABLE_ROOT` picks the copy (default `~/Games/RimWorld-stable`).
- [x] `freeze` / `userdata` refuse when Steam's major.minor differs from the copy's (ce69492), so the
      1.6 copy can't be overwritten by 1.7.
- [x] `pull MOD` / `pull` (all) / GUI "Update all": on demand only; read Steam's Workshop and Steam's
      local `RimWorld/Mods/` (ce69492).
- [x] `pull` refuses updates that won't work on the copy's version (About.xml doesn't list it, or a
      DLL it loads targets .NET while the game is .NET Framework); pull-all skips them;
      `-anyversion` overrides. `diff` marks each update `1.6 changes` / `other` / `CAN'T PULL`
      (cb1730b, `rimstablelib/modver.py`, checked against 1.6's load-folder code).
- [x] Holds: `hold MOD [reason]` / `unhold MOD` keep a mod as it is through pull-all, Update all and
      refreeze; `pull MOD` needs `-held` (54e5425).

## 1. Make a 1.7 stable copy possible

Everything rimstable does today assumes Unity-era 1.6. The 1.7 copy would live at e.g.
`~/Games/RimWorld-stable-1.7` and be made with `freeze` from Steam's 1.7.

- [ ] **Executable per copy.** `EXE_NAME` is hardcoded to `RimWorldLinux`; 1.7's is `RimWorld`.
      Detect it from the copy's `game/` folder for `launch`, `shortcut` and the Windows `.lnk` icon.
      Find 1.7's Windows executable name.
- [ ] **Launch arguments on 1.7.** 1.7 still has `-savedatafolder` (string in `RimWorld.dll`);
      verify it works. `-logFile` is a Unity option; 1.7 writes `Logs/Player.log` inside the save
      data folder. Drop `-logFile` and the `Player.log` -> `Player-prev.log` rotation for 1.7.
      Check whether `LC_ALL=C` is still needed.
- [ ] **Where Steam's 1.7 keeps its data.** Find 1.7's save-data path (decompile) and check
      `find_config()` finds it. If 1.7 shares the 1.6 folder, freezing 1.7 copies the 1.6 saves into
      the 1.7 copy too (a copy, harmless to the 1.6 copy, but worth saying in the freeze output).
- [ ] **USERDATA_SKIP for 1.7:** add `Logs/`; check whether `MissileGirl/Cache` (Gagarin) still
      applies.
- [ ] **NoSteamNag on 1.7.** First check 1.7 still shows the "Could not initialize Steam API"
      dialog without Steam. If it does: ship `1.6/Assemblies` (net472, Harmony 2) and `1.7/Assemblies`
      (net10, Harmony 3), list 1.7 in About.xml, and update the path `install_helper()` checks.
      Confirm 1.7 Harmony's packageId is still `brrainz.harmony`.
- [ ] **ModsConfig on freeze.** Check 1.7's ModsConfig loading (decompile) so a frozen 1.7 copy keeps
      Steam's mod list rather than resetting it.
- [ ] **Pull checks for a 1.7 copy.** `modver` follows 1.6's load-folder rules; verify them against
      1.7's code. Find out what 1.7 does with a net472 DLL (loads it, or not) so pull blocks the
      right mods on a 1.7 copy.
- [x] **DDS on 1.7: off.** Decompiled 1.7.4977: `ModContentLoader.ShadowedByDds` still loads `Foo.dds`
      instead of `Foo.png`, but 1.7 encodes PNGs itself (BC1/BC7, BC4 for single-channel, BC5 normals) into
      a disk texture cache (`GpuTextureService`, `TextureCache/v23`), so pre-encoding saves little after the
      first start. DDS-loaded textures are cached and evictable too, so the forum claim that DDS raise VRAM
      on 1.7 isn't obvious from the code (not measured). `dds` refuses to encode for any game that isn't
      1.6 (`dds.DDS_VERSIONS`); `clean` still works. Revisit only with a measured start-time or VRAM win,
      and check todds' `-vf` flip on one mod first.
- [ ] **Choosing the copy.** CLI: a `-root DIR` option (or keep `RIMSTABLE_ROOT`); GUI: show which
      copy is open and switch between known copies. Shortcuts need distinct names per copy, e.g.
      "RimWorld 1.6 (Stable)" / "RimWorld 1.7 (Stable)".
- [ ] **Help get Steam's 1.7 working before freezing it:** a report of the mods active in Steam's
      1.7 list that don't support 1.7 (`modver.problems()` for 1.7 instead of only About.xml), so
      broken or abandoned mods can be dropped first.
- [ ] **Freeze the 1.7 copy** once Steam's 1.7 works (the user's call; weeks away), into its own root,
      and check launch, mod list, saves and a pull.

## 2. Small follow-ups for the 1.6 copy

- [x] **Held every mod in the 1.6 copy** (269, reason "1.6 known-working set; Steam is on 1.7") with the
      new `hold -all [reason]` / `unhold -all`. One mod can still be updated on purpose: `pull MOD -held`.
- [ ] GUI "Supports" column warns against Steam's version only; show whether the mod supports the
      copy's own version, which is what matters for a pull.

## 3. Tests and docs

- [ ] Unit tests for `modver.py`: load-folder resolution (exact, older key, default key, only-newer
      fallback), loaded-file diffs (moves, `LoadFolders` gaining a `v1.7` block, deleted files), DLL
      runtime detection, `problems()`.
- [ ] Tests for pull refuse/skip paths and holds (pull, pull-all, refreeze), writes stubbed (scratch
      `RIMSTABLE_ROOT`; patch `cli.sync_into` / `snapshot` / `remove_mod_dir` / `install_helper` /
      `require_*`, `dds.enabled`).
- [ ] README: one copy per version, how to make and pick the 1.7 copy.

## Dropped (overcomplicated; not needed when the copies never interact)

- Moving the stable copy to 1.7 / a `migrate` command / restoring a pre-migration snapshot.
- Carrying mods, holds or saves from the 1.6 copy to the 1.7 copy.
- Readiness reporting for "is the 1.6 copy's mod list ready for 1.7" (the 1.7 copy comes from Steam's
  1.7 list, not from the 1.6 copy).
- `checked_on` per mod record.
- Pinning a held mod to a git source; `~/repos/rimworld-mods/install.sh --dest` already covers it.
