# TODO: RimWorld 1.6 + 1.7 support with per-mod version management

Goal: rimstable handles a stable copy on 1.6 while Steam runs 1.7, lets each mod be kept at a chosen
version, and can later move the stable copy to 1.7 (or keep a copy per version) without losing the
mod list, saves or helpers.

Status as of 2026-10-13: the stable copy is 1.6.4871, Steam is 1.7.4977. Freeze and userdata refuse
across versions; pull works across versions.

## Done

- [x] `freeze` / `userdata` refuse when Steam's major.minor differs from the stable copy's (ce69492)
- [x] Running check matches 1.7's `RimWorld` process (ce69492)
- [x] `pull` / `diff` read Steam's local `RimWorld/Mods/` as well as the Workshop (ce69492)
- [x] `rimstablelib/modver.py`: which folders and files a RimWorld version loads, following 1.6's
      `ModContentPack.InitLoadFolders` (checked against the decompiled 1.6 `Assembly-CSharp.dll`)
- [x] `pull` refuses mod updates that won't work on the stable version (About.xml doesn't list it, or
      a loaded DLL targets .NET while the game is .NET Framework); pull-all / Update all skip them;
      `-anyversion` overrides
- [x] `diff` marks each changed mod `1.6 changes` / `other` / `CAN'T PULL`; local mods get a date
- [x] GUI: "Can't pull" rows, Update all count and dialog exclude blocked mods
- [x] README: `pull` and `diff` sections

## 1. Per-mod version management (next)

The stable copies of the user's own mods (`jjanow_*`, `rimstable_*`) differ from Steam's on purpose.
Right now one Update all click overwrites them.

- [ ] **Hold a mod at its stable version.** Add a `held` flag to the mod's manifest record (survives
      refreeze; `freeze` must keep held mods' stable copies the way it keeps missing mods).
      - [ ] CLI: `rimstable hold MOD [reason]`, `rimstable unhold MOD`, and holds listed in `status`
      - [ ] `diff` shows held mods as `held` (with the reason) instead of as an update; they don't
            count toward "updated on Steam"
      - [ ] `pull` with no mod named and Update all skip held mods; `pull MOD` on a held mod refuses
            unless given its own override flag (not `-force`, which means "ignore Steam updating")
      - [ ] GUI: Hold / Unhold in the mods table (context menu + button), a "Held" filter, held tone
      - [ ] Hold the user's 20 own mods once this lands (ask first; that's their call)
- [ ] **Refreeze must respect holds.** `cmd_freeze` re-mirrors every active mod from Steam; held mods
      must be skipped there too, or a refreeze undoes them.
- [ ] **Record which game version each stable mod copy was checked on** (`checked_on: "1.6"` in the
      manifest record), so a version move can list mods that were never checked on the new version.
- [ ] **Optional: pin a held mod to a source.** E.g. "take this mod from ~/repos/rimworld-mods at
      commit X" instead of from Steam, so the stable copy of an own mod can be updated deliberately
      without going through Steam's 1.7 copy. Decide whether this is worth it vs `install.sh --dest`.
- [ ] Fix the stale header in `~/repos/rimworld-mods/install.sh`: "rimstable pull only reads Workshop
      mods" has been wrong since ce69492. Say that pull reads local mods too and that held mods are
      skipped (once holds exist).

## 2. Readiness reporting for a move to 1.7

- [ ] `diff`'s "N/269 list support for 1.7" only reads About.xml. Run `modver.problems()` for 1.7
      with the `netcore` runtime instead. That catches mods that list 1.7 but would load nothing
      usable, though a .NET Framework DLL may still load on 1.7. Verify what 1.7 actually does with a
      net472 DLL before reporting those as OK or broken.
- [ ] GUI: the "Supports" column warns against Steam's version only; also show whether the mod
      supports the stable version.
- [ ] Verify `load_folders()` against 1.7's own load-folder code (decompile the 1.7 assembly the
      same way; 1.6's rules were checked, 1.7's weren't).
- [ ] Report the 7 mods active in stable but not in Steam's 1.7 list (Vehicle Framework, Prepatcher,
      XML Extensions, VPE Psycasts, MGW, Gravship 1/2) as "not tested on 1.7" in the readiness view.

## 3. Moving the stable copy to 1.7 (or keeping one per version)

**Decision needed first:** move the one stable copy from 1.6 to 1.7, or keep two stable copies side
by side (e.g. `~/Games/RimWorld-stable` for 1.6 and `~/Games/RimWorld-stable-1.7`), with the GUI
switching between roots. Everything below depends on that choice.

- [ ] **Executable per version.** `EXE_NAME` is hardcoded to `RimWorldLinux`; 1.7's executable is
      `RimWorld`. Detect the executable from the stable `game/` folder for `launch`, `shortcut` and
      the Windows `.lnk` icon. Find out 1.7's Windows executable name (unknown).
- [ ] **Launch arguments on 1.7.** 1.7 still accepts `-savedatafolder` (string in `RimWorld.dll`).
      `-logFile` is a Unity option; 1.7 writes `Logs/Player.log` inside the save data folder instead.
      Verify, then drop `-logFile` and the `Player.log` -> `Player-prev.log` rotation for 1.7.
      Check whether `LC_ALL=C` is still needed.
- [ ] **USERDATA_SKIP for 1.7:** add `Logs/` (1.7's log folder); check whether `MissileGirl/Cache`
      (Gagarin) still applies on 1.7.
- [ ] **NoSteamNag for 1.7.** It ships only a root `Assemblies/` DLL (net472, Harmony 2) and lists
      only 1.6. Move it to `1.6/Assemblies` + `1.7/Assemblies` (net10, Harmony 3), list 1.7, and check
      that 1.7 still shows the "Could not initialize Steam API" dialog at all. `install_helper()`
      checks for `NoSteamNag/Assemblies/RimstableNoSteamNag.dll`; update that path. Check the 1.7
      Harmony packageId is still `brrainz.harmony` (Steam's 1.7 list says yes).
- [ ] **Mod list across versions.** RimWorld resets a ModsConfig.xml saved by another major.minor.
      Decompile 1.7's ModsConfig loading to see exactly when it resets, then decide: write the new
      version into the stable ModsConfig on migration, or take Steam's 1.7 list.
- [ ] **A `migrate` command** (or `freeze -version`): snapshot, copy the new game, carry over held
      mods, run the readiness check and refuse or warn on blocked mods, fix ModsConfig, reinstall
      NoSteamNag, record the move in the manifest. `require_same_version` stays for plain refreezes.
- [ ] **Saves:** decide what to do with 1.6 saves on a 1.7 copy (keep them in the snapshot; warn).
- [ ] **DDS on 1.7.** 1.7 (Waylith, not Unity) references `.dds` in `Waylith.dll` /
      `Brutal.Texture.dll`, but whether it prefers a `.dds` next to the `.png`, and whether todds'
      `-vf` vertical flip (a Unity quirk) is still right, is unverified. Test on one mod before
      enabling DDS for a 1.7 stable copy; make the flip depend on the game version if needed.
- [ ] `restore` of a pre-migration snapshot puts back the 1.6 game too. Check that the manifest,
      DDS ledger and shortcut all agree afterwards.

## 4. Tests and housekeeping

- [ ] Unit tests for `modver.py` (pure functions over directories): load-folder resolution (exact,
      older key, default key, only-newer folder fallback), loaded-file diffs (moves, `LoadFolders`
      gaining a `v1.7` block, deleted files), DLL runtime detection, `problems()`. The scratchpad
      cases from 2026-10-13 are the starting set.
- [ ] Tests for the pull skip/refuse paths with writes stubbed (as done by hand on 2026-10-13).
- [ ] README: document holds, the readiness view and the migration command as they land.
