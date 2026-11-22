# Firetier design milestone

Everything in this folder is design work. The working app is `web/` + `server.py`.

## Research notes (what the concepts draw from)

- **Windows 11 / Fluent**: Segoe UI Variable, 4 px grid, 4–8 px corner radii, a quiet surface ladder
  instead of drop shadows, a visible focus ring, and system "reduce animation" respected.
- **Launcher-style apps** (Steam, Battle.net, Bloxstrap/Fishstrap settings): a fixed left nav, the
  selected game shown as a wide image, and a single obvious primary action.
- **Creative tools** (Blender, Figma, Substance): docked three-panel editors, a property inspector,
  before/after compare sliders and a status bar for state that has to be visible all the time.
- **Honesty constraint**: every screen must be able to say "configuration written" and
  "in-game effect not verified" as separate states. Each concept had to fit that wording.

## The three concepts

Screenshots: `design/screenshots/concept-a.png`, `concept-b.png`, `concept-c.png` (1440×900 app plus
a spec strip below it). Sources: `design/concepts/*.html`.

| | A · Ember (minimal premium gaming) | B · Workstation (creative tool) | C · Vector (dark futuristic) |
|---|---|---|---|
| Layout | 232 px labelled sidebar, card dashboard | Menubar, icon rail, dock tree, inspector, status bar | 84 px labelled rail, angled "HUD" cards |
| Palette | Graphite #0C0D10 → #22262C, ember #FF6A3D, amber #FFB547 | Neutral greys #18191C → #26282D, blue #4C8DFF | Navy #070A12, cyan #38E1FF, violet #8B5CFF |
| Type | Segoe UI Variable Display/Text, Bahnschrift numerals | Segoe UI Variable, dense 12–13 px | Bahnschrift uppercase display, letter-spaced |
| Strength | Calm, readable, clearly "gaming", the brand flame earns the accent | Best for editing many flags; the inspector and status bar always show state | Most striking at first glance |
| Weakness | Cards need balancing so none look empty | Too dense and "tool-like" for the dashboard and library pages | Glow, grid backdrop and gradients run into "excessive neon"; clipped corners hurt text layout; sparse lower half |
| Fits honesty labels | Yes, as quiet badges | Yes, in the status bar | Awkward: "SYNC OK" style copy invites over-claiming |

## Recommendation

**Concept A (Ember) as the base design system**, with **B's docked three-panel layout and status
strip used only for the Customization Editor**. C is dropped: it breaks the "no excessive neon / no
random gradients" rule, and its HUD voice pushes copy toward claims the app can't verify.

Fixes carried from the concept review into the real app:
- Concept A's "Recent presets" card left empty space: the real dashboard balances row heights and
  fills cards from real data or shows a designed empty state.
- Concept B's inspector clipped long flag names: inspector fields ellipsize, with a tooltip for the full name.

## Screenshots of the real app

`design/screenshots/app/` holds 53 captures of the running app (`server.py` serving `web/`), not mock-ups.
They were taken in headless Edge through the DevTools protocol, which sets an exact viewport and DPI.
The data is a sandbox seeded through the app's own HTTP API: a fake LocalAppData with a Fishstrap and
a Roblox folder, two real applies (so backups and verification exist), and one imported Fleasion list.
Nothing in the user's real Roblox or Fishstrap folders was touched.

- `WxH-<screen>.png`: the seven screens at 1280×720, 1440×900, 1920×1080 and 2560×1440.
- `WxH@125/150-<screen>.png`: Windows display scaling. The file is named by its physical size, and the CSS
  viewport is that size divided by the scale: 1920×1080 at 125 % and 150 %, and 2560×1440 at 150 %.
- 1440×900 states: `assets-image` (texture level 1 with the compare slider), `assets-audio` (waveform,
  seeked), `editor-unsupported` (imported asset list, read-only), `modal-apply`, `modal-import`,
  `onboarding`, `settings-target`, `diagnostics-log`.
- Added after design approval (1440×900): `games-search` (query "textures"), `games-nomatch` (empty
  state), `games-fav-empty` (Favorites filter; Rivals is starred by default, so it shows alone), and
  `settings-performance`, `-storage`, `-privacy`, `-about`, `-advanced`. The Dashboard, Games, Asset Studio
  and Settings captures at every size were retaken after these changes.
- `overview-1440.png`: a contact sheet of the main screens.

No page errors were logged in any capture.

## Fidelity review

Fixed in this pass, found in the screenshots:
- **Dashboard quick actions** cut labels off at 1280×720 ("Apply last prof…"). Labels now wrap onto two lines.
- **Apply dialog**: the target path ran out of the dialog. Mono text in dialogs now wraps anywhere.
- **Games, "All Roblox games" card**: a tile pattern sat above a large empty gap, so it read as a
  placeholder. It now lists the real general profiles, each linking to the editor.
- **Dashboard Health card** was captured while still loading. The capture now waits for every skeleton to
  go. This was a timing problem in the screenshots, not in the app.
- **Asset Studio**: "Remove from list" now lines up with the details list.
- **Settings nav** highlighted "Updates & about" when Advanced was opened, because the last section is
  too short to scroll to the top. At the bottom of the page, the section you asked for now stays highlighted.
- **Asset Studio export help** read "a PNG at320 × 179": a missing space.

Checked and holding up:
- **Text fits** at 1280×720 and at 150 % scaling. The sidebar, topbar and three-panel editor don't
  overflow, and long paths wrap.
- **Honesty labels are visible wherever an effect is implied:**
  - "In-game effect: not verified" on the applied profile.
  - "Illustration · not a Roblox screenshot" on the arena art.
  - "Offline approximation · not a Roblox capture" on the editor preview.
  - "Local approximation · not a Roblox render" in Asset Studio.
  - "Live application unsupported" on the imported asset list.
- **Real state comes through.** "Roblox is running" is a real warning, since the processes were running
  during capture.
- **Contrast**: text tokens #ECEDEF, #A3A8B0 and the weakest, #8A9099 (5.4:1 on cards), pass WCAG AA 4.5:1
  on surfaces #0C0D10 to #22262C. Ember #FF6A3D buttons carry dark #1A0C06 text; ember is otherwise
  used for icons and accents, not small body text.
- **Keyboard**: every control can be tabbed to and shows the 2 px focus ring. The compare handles and
  the waveform are role=slider and respond to arrow keys.

Known limits, left as they are:
- At 2560×1440 with 100 % scaling, pages keep a readable maximum width, so wide margins remain. This is
  intended; most 1440p users run at 125–150 %.
- The Asset Studio stage is large and mostly empty until a file is dropped. That empty state is designed.
- The seeded "Rivals · my comp setup" has one duplicated flag rule, so it shows 13 rules and 12 flags in
  the file. That comes from the seed data, not the UI.

## Generated vs hand-made assets

- **AI-generated (ForgeGUI):**
  - `web/assets/generated/logo-gen-*.png`, cleaned up into `logo-*.png` and `firetier.ico`.
  - `arena-gen.png`, cropped into `arena-640/1280.jpg`.
  - Both are labelled as illustrations wherever they appear.
- **Hand-made SVG:**
  - `icons.svg` (the icon sprite).
  - Every thumbnail in `thumbs/` and illustration in `illus/` (produced by `design/tools/make_illus.py`).
  - The editor's live before/after preview, which is drawn on a canvas in `web/js/preview.js`.
- No screen in the app is a static image standing in for the interface.
