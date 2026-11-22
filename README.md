# Firetier 0.1.0

A FastFlag profile manager for Roblox, set up for Rivals FPS. It edits
`ClientAppSettings.json`, the local config file Roblox reads at startup. Bloxstrap
and Fishstrap use the same mechanism.

It does **not** replace assets, touch the Roblox executable or cache, inject
anything, or interact with anti-cheat.

## Run

**Easiest:** double-click `dist/Firetier.exe`. It's one file, so you can put it
anywhere: on the desktop, in Downloads, on a USB stick. It contains the whole
portable build. The first launch unpacks it to `%LOCALAPPDATA%\Firetier\app\`,
which takes a few seconds. Later launches start straight away. `Firetier.exe classic`
opens the classic window. A newer `Firetier.exe` unpacks its own copy and removes
older ones that aren't running.

The exe isn't code-signed, so the first time Windows SmartScreen may say "Windows
protected your PC". Choose *More info → Run anyway*.

**Or the folder:** extract the entire `dist/Firetier-Windows.zip` and double-click
`Firetier.bat` inside it. The archive includes its own Python runtime, so nothing
needs installing.

Both open the interface in a Microsoft Edge app window, which comes with
Windows 11. The page is served by a small local server on `127.0.0.1` that only
accepts requests carrying a random token made for that launch. Close the window and
the server exits about 30 seconds later. Without Edge, it opens in your default browser.

`Firetier.bat classic` opens the older Tk window instead. It uses the same
profiles and backups.

From the source folder, the same `Firetier.bat` works if Python 3.10 or newer is
installed. You can also run `python server.py` for the web UI or `python firetier.py`
for the classic window. There are no other dependencies.

## How to use it

1. **Target** (Settings → Target, or the Dashboard). If Fishstrap or Bloxstrap is
   installed, Firetier picks *its* FastFlags file, because the bootstrapper copies
   that file into Roblox on every launch. Otherwise it picks the newest Roblox
   version folder. If you start Roblox through Fishstrap, keep the Fishstrap target.
2. **Pick a profile** on the Dashboard or under **Presets**. The built-in
   *Rivals: No Textures (max allowed)* sets the low-detail flags on Roblox's allowlist and
   the Direct3D 11 renderer. It leaves lighting updating (`DFFlagDebugPauseVoxelizer` off),
   because paused lighting goes stale between rounds and looks glitchy.
3. **Apply.**
   - *Merge* sets this profile's flags and keeps everything else in the file.
   - *Replace* leaves only this profile's flags in the file.

   Either way, Firetier backs up the current file, writes the new one, reads it
   back to check it, and restores the backup if anything fails.
4. **Restart Roblox** (through Fishstrap if that's the target). Roblox reads flags only at startup.

### Loading screen

Each launch opens on a short fire splash. Its rows are the real start-up steps (local engine,
profiles, flags file, Roblox account, health checks) with what each one found. Click it or press
Esc, Enter or Space to skip. Buttons ripple when clicked, primary buttons throw sparks, and a
verified apply ends in a burst. Motion defaults to **Full** even when Windows' *Animation effects*
is off. **Settings → Appearance → Motion** switches it to *System* (follow Windows) or *Reduced*
(a still splash and no effects).

### Roblox account (optional)

**Settings → Roblox account** (or the chip at the bottom of the sidebar) shows your name and
avatar in Firetier. The field is prefilled with the user ID found in your local Roblox Player
logs, if any. Nothing is sent until you click **Connect**. It is cosmetic: it doesn't change
which flags apply.

### Screens

- **Dashboard**: the active target, the selected profile, its status labels and the apply button.
- **Games**: profiles grouped by game (Rivals, and general presets that apply to every game).
  You can search by game name, place ID or profile, and star games to show only
  favourites. Each card spells out what's supported: FastFlags yes, asset swaps no,
  in-game effect not verified.
- **Presets**: the built-in presets and your own profiles. You can duplicate, import or export them.
- **Editor**: edit a profile's flags. Each flag is marked *active*, *ignored* (not on
  the allowlist) or *invalid*. Built-in presets are read-only, so duplicate one to change it.
- **Asset Studio**: drop local images or audio to inspect them. For images, a slider
  shows what each texture-quality level does: Roblox drops mip levels, so each step
  halves the resolution. *Save level N as PNG* downloads that approximation. It is a
  local drawing, not a Roblox render, and nothing is uploaded. Imported Fleasion
  asset lists show here locked: stored for reference, never applied.
- **Diagnostics**: read-only checks (installs, permissions, ignored and invalid flags,
  conflicts, whether Roblox is running), the activity log, backups with restore,
  *Remove all flags from target*, and a copyable report.
- **Settings**: Appearance, Target, Applying (write mode, backups), Performance,
  Storage (folder sizes, open folder), Privacy, Updates & about, and Advanced (classic
  interface, reset preferences).

### Cleaning up an existing flags file

Click **Load target as profile**. Every flag in the file shows up, marked
*active*, *ignored* (not on Roblox's allowlist) or *invalid*. Apply that profile in
**Replace** mode and the file is left with only the flags Roblox actually honors.
A backup is made first.

## What the status labels mean

| Label | Meaning |
|---|---|
| Configuration: valid | Values are the right type, with no conflicts. |
| Honored by Roblox: N of M | N of the flags are on Roblox's allowlist. The rest are ignored. |
| In <target>: all N present on disk | The file contains these exact values (read back from disk). |
| In-game effect: not verified | Always shown. Firetier can't see inside Roblox. |
| Live asset replacement: unsupported | Fleasion-style imports are stored unchanged but never applied. |

Every preview in Firetier is an offline drawing made by Firetier: the Editor's
preview, Asset Studio and the classic window's Preview tab. They are approximations,
not Roblox screenshots.

Firetier has no telemetry. It makes two kinds of network calls, both over HTTPS with certificate
checks on, and neither sends a cookie, password or token:

- **Roblox account**, only when you click **Connect** (or **Refresh**): one public lookup to
  `users.roblox.com` and the avatar headshot from `thumbnails.roblox.com`. **Disconnect** deletes
  the saved name and avatar.
- **Updates**: the latest-release lookup on `api.github.com` for the repo in Settings › Updates &
  about (default `eyomybro/Firetier`), and, when you click **Update & restart**, the release files
  from `github.com`. Requests identify themselves only as `Firetier-updater`.

## Updates

Firetier checks the repo's latest GitHub release when it opens (at most every 6 hours; turn
**Check automatically** off to stop that, or clear the repo to turn updates off). A newer version
shows a toast and a **New** badge on Settings. Nothing installs until you click **Update & restart**:

1. Firetier downloads `Firetier.exe` from that release and checks it against the release's
   `firetier-update.json`: same version, same size, same SHA-256, and a Windows program header.
   Files that download from anywhere other than the repo's own release page are refused.
2. The running `Firetier.exe` is renamed to `Firetier.old.exe` and the new one takes its name. If
   that or the restart fails, the old build is put back.
3. The new version starts and opens its window; the old one exits. Profiles, backups, settings and
   the account stay where they are (see Files).

To roll back by hand, close Firetier, delete `Firetier.exe` and rename `Firetier.old.exe` to
`Firetier.exe`. A copy run from the source files (`Firetier.bat`) can check for updates but can't
replace itself; it links to the release page instead.

### Publishing a release

1. Raise `APP_VERSION` in `engine.py` (installs only move to a higher version).
2. Run `python packaging/make_release.py`. It builds `Firetier.exe` and writes it to
   `dist/release/v<version>/` with `firetier-update.json` and `Firetier-v<version>-Windows.zip`
   (the download for people: it unzips to just `Firetier.exe`, which needs nothing else installed).
3. On GitHub: Releases › Draft a new release › tag `v<version>` › attach all three files › Publish.
   A release without `Firetier.exe` and `firetier-update.json` is shown but can't be installed
   from inside Firetier.

## Limits

- **Allowlist.** Since late 2025, Roblox only honors 18 FastFlags set locally
  ([announcement](https://devforum.roblox.com/t/allowlist-for-local-client-configuration-via-fast-flags/3966569)).
  Everything else is silently ignored, including `DFIntTaskSchedulerTargetFps`
  (the FPS unlocker), `FFlagDisablePostFx` and the shadow flags. Firetier has an
  embedded copy of the list, checked 2026-11-21. If Roblox changes the list,
  Firetier won't know until the list is updated.
- **No true "no textures".** The lowest you can go is
  `DFIntTextureQualityOverride = 0`, which gives very low-resolution textures, not
  none. Removing textures entirely would mean modifying Roblox's asset delivery
  or cache, and Firetier doesn't do that.
- **Vulkan on 2 GB cards.** On a GeForce GT 1030, Roblox's Vulkan renderer budgeted
  64 MB of video memory (Direct3D 11: 2 GB), so textures were evicted and reloaded constantly.
  That shows as flickering textures and stutter. Diagnostics reads the newest Roblox log and
  warns when this happens.
- **FFA lag is mostly CPU.** With many players, the cost is character
  animation, effects and scripts. FastFlags barely touch that. Lowering
  resolution or using Roblox's own graphics-quality slider can still help.
- **Game profiles are labels.** FastFlags apply to every Roblox game. They can't
  be limited to Rivals.
- **Roblox updates** wipe the version folder's `ClientSettings`. Re-apply after an
  update if you target Roblox directly. Fishstrap re-copies its file automatically.

## Files

- `%LOCALAPPDATA%\Firetier\profiles\`: your profiles (JSON)
- `%LOCALAPPDATA%\Firetier\backups\`: one folder per backup (`meta.json` + the file)
- `%LOCALAPPDATA%\Firetier\trash\`: deleted profiles
- `%LOCALAPPDATA%\Firetier\firetier.log`: apply and restore history
- `%LOCALAPPDATA%\Firetier\account\`: the connected Roblox account's name and avatar (only after Connect)
- `%LOCALAPPDATA%\Firetier\webview\`: the Edge app window's private browser profile
- `Firetier.old.exe`, next to `Firetier.exe`: the build before the last update (safe to delete)
- `%LOCALAPPDATA%\Firetier\app\`: the copy `Firetier.exe` unpacks itself to (safe to delete; it unpacks again)

Set `FIRETIER_HOME` to use a different folder.

## Recovery and verification

Diagnostics includes Restore preferences. Resetting archives the prior preferences in `settings.before-reset.json`. Startup can recover damaged settings from `settings.previous.json` and keeps the damaged bytes under a unique filename. Diagnostics lists unreadable profiles and backup manifests. Review `docs/DEBUGGING_GUIDE.md`, `docs/ENGINEERING_LESSONS.md` and `docs/REGRESSION_HISTORY.md` before changing these paths.

## Tests

```
python -m unittest discover -s tests -v
```

## Build

```
python packaging/build_windows.py dist/Firetier-Windows.zip --exe dist/Firetier.exe
```

This builds the portable zip from the local CPython install. With `--exe`, it also wraps
the zip in `Firetier.exe` (`packaging/launcher.cs`), using the C# compiler that ships
with Windows.
