# Changelog

All notable changes to SocialBlocker. Newest first.

## 2026-08-16 — Rounded cards, and the redraw bug they exposed

- **Cards are rounded.** `mk.card()` now returns a themed **`ttk.Frame`** whose
  background is the same 9-patch image element the buttons use, replacing the
  `tk.Frame` + `highlightthickness` border — that border can only ever be a
  rectangle. Children still pack and grid normally and the corners survive a
  resize, which a canvas-drawn card would not give for free. Applied to every
  card, not just the presets, so the surfaces stay one design language:
  presets, mode, composer, list panel, stat tiles, startup.
- Preset metadata is `50m · whitelist · locked` (single-spaced separators,
  monospace) and the cards get a little more air.
- **Fixed: resized widgets redrew over their own stale pixels.** The 9-patch
  tiles had transparent corners, so Tk composited each redraw onto whatever
  was already in the window instead of clearing it first. Harmless for a button
  that never changes size; very visible on a card, which stretches — measured
  on a live resize, the old narrower panel stayed visible underneath the new
  one, and every card looked clipped on the right.
  - *Fix:* every tile is now **opaque**, its corners painted against the colour
    really behind the widget (cards against the page, buttons and fields
    against the card). An opaque tile makes every redraw a full overwrite.
    `pill_image()` takes `bg` as a required argument so this cannot be
    forgotten; the transparent path is gone rather than left as a trap.
  - This is the same trade the hero already made with `round_corners`. It costs
    the "works on any background" property, which Tk could not actually honour.

## 2026-08-15 — Title bar: drawn reload glyph, icon button, rounded status chip

- **`mistkit.reload_icon()`** draws the circular arrow — a ring with a gap plus
  an arrowhead, anti-aliased, one flat colour with an alpha channel. *Why not
  "↻" (U+21BB):* it is present in some UI fonts and missing or badly matched in
  others, it cannot follow the palette, and it cannot be recoloured per state.
  The drawn glyph sits equally well on a white pill, the teal app tile and a
  dark card. Used in the title bar and on the list panel's Refresh.
- **The app mark now carries that glyph in white**, stamped into the teal tile
  before the corners are cut.
- **Refresh became an icon-only round button.** New `Icon.TButton`, and it
  deliberately does *not* use the 9-patch the other buttons use:
  a 9-patch reserves `border` pixels per side, which also become the label's
  padding, so the smallest true circle it can draw is `2 * radius + icon`
  across — measured, a 15px glyph at radius 17 gave a **49px** button, far too
  heavy for a title bar. An icon button has one fixed size, so the image is
  the whole face at natural size and nothing is stretched: **34x34**.
- **`StatusPill` is a `tk.Canvas` instead of a `tk.Frame`** so it can actually
  be round; `highlightthickness` only ever draws a rectangle. The panel image
  depends solely on the width and there are five possible labels, so the few
  widths that occur are cached rather than re-rasterised at 1 Hz.
- The wordmark's "Blocker" is italic serif, matching the reference.

## 2026-08-15 — Stop rewriting /etc/hosts on every daemon tick

- **`hosts_engine.apply()` now skips the write when nothing changed.** It
  rendered the region and called `_atomic_write` unconditionally, so the
  5-second daemon loop replaced `/etc/hosts` ~17k times a day and ran a
  resolver flush with each one. `os.replace` is atomic, so this was never a
  corruption risk — but it is pure churn, it defeats any backup or file-watcher
  that keys on mtime, and it destroyed the file's own mtime as the answer to
  "when did my blocking last change?". *Measured before:* mtime advanced twice
  in a 12-second window with an empty fence. *After:* three re-applies leave
  the mtime untouched (now a test).
  - The skip keys on **content**, never on "we already applied this", so
    tamper repair is unchanged: edit or delete the region and the next tick
    still writes it back. Covered by two new tests.
- **`apply()` returns `Applied(mode, locked, count, changed)`** — a NamedTuple
  instead of a bare 3-tuple. *Why the extra field:* once a write only happens
  on a real change, `changed` is the only way to tell an idle no-op from a
  repair, and the daemon now logs `repaired /etc/hosts — the managed region had
  been modified`. That event was previously **invisible**: the daemon only logs
  when its description string changes, and a repair does not change it. Tamper
  repair is the headline feature of locked mode and it had no evidence.
- `clear()` returns whether it removed anything, for the same reason.
- Call sites widened in `cli.py` (5) and `daemon.py`; `arm_boot_session()` is
  annotated `Applied | None`.

## 2026-08-15 — GUI relaid out to the reference design

- **Layout**: quick presets became three cards across the top; the all-day mode
  and focus composer sit in a left column; both domain lists moved into one
  right-hand card with count-badged tabs, an inline `add a domain…` field, and
  Remove / Refresh. The `ttk.Notebook` is gone, and the boot-block settings are
  a "Start with the computer" card at the foot of the page. Feature parity is
  unchanged — every control still calls the same `control.py` use case.
- **Rounded buttons, without hand-rolling a widget.** ttk cannot round a
  button, and a canvas "button" means owning hover, press, focus and keyboard
  traversal forever. Instead each style gets a **9-patch image element**
  (`Style.element_create(..., "image", ..., border=N)`): one 28px RGBA tile per
  widget state, stretched across any button width with the corners left alone.
  Real `ttk.Button`s throughout, so focus and keyboard still work.
  - `Raster` grew a real alpha channel and emits PNG colour type 6. A pill has
    to sit on a card, the page *and* the fog, so its corners must be
    transparent rather than painted with one assumed backdrop.
  - *Trap:* clam's `TButton` sets `width: -11`, an 11-character minimum that
    every derived style inherits — it made "Off" and "Blacklist" both exactly
    140px. Fixed with `width=0`; measured after: 56px and 89px.
  - The 9-patch `border` is *also* reserved as padding around the label, so
    per-style padding is on top of it and had to shrink to match.
- **`ttk.Treeview` replaces `tk.Listbox`** for the domain rows: it is the only
  stock widget that can put an image on a row (the generated "blocked" mark),
  and unlike Listbox it is themeable, so it follows a light/dark switch like
  everything else.
- **New `socialblocker/widgets.py`** — `PillGroup`, `Stepper`, `TabStrip`,
  `DomainList`, `StatusPill`, `Scroller`. Same outer circle as `gui.py`:
  imports nothing but `mistkit`, decides no policy, takes plain values and
  callbacks. Split out purely for size.
- Selection is ttk's own `selected` **state** rather than a style swap, so the
  themed element picks its own face and the focus ring survives.
- Scrollbars lost clam's stepper arrows, which rendered as two specks at 8px.
- *Cost, measured:* a live theme switch is now **1038 ms** median, up from 649,
  because the richer tree is more for Tk to lay out (`update_idletasks` alone
  is 960 ms). Generating all the pill faces is 185 ms (Mist) / 271 ms (Ink),
  but only once per scheme — a repeat `apply_theme` is 1.9 ms. See the note on
  in-place retinting below; it is the fix if this hitch ever matters.

## 2026-08-15 — GUI follows the system light/dark setting

- **`mistkit.py` now ships two palettes: Mist (light) and Ink (dark).** The flat
  token constants became a `Palette` object, with `mistkit.theme` naming the
  active one. *Why an object and not 25 rebound module globals:* one binding is
  one source of truth, `from mistkit import CARD` cannot silently capture a
  stale colour, and `Palette` is pure arithmetic — testable without a Tk root.
  - Ink is **not** an inversion of Mist. Elevation reverses (a shadow is
    invisible on near-black, so a raised surface can only be a *lighter*
    surface — which is why the "white" role is the lightest dark grey), and
    accents are re-picked rather than reused (`TEAL_DEEP` means "more emphatic
    than TEAL": darker on white, lighter on black). New `ON_ACCENT` role for
    what is drawn *on* an accent fill, since white-on-teal only works on Mist.
  - *Measured, not eyeballed:* contrast against each palette's own card —
    PINE 15.1→13.5, SLATE 4.9→7.1, TEAL 3.7→6.5, AMBER 3.6→7.3, DANGER
    4.9→5.0 (Mist→Ink). Ink is more contrasty at every role. Mist's own token
    values are byte-identical to before; the light theme did not move.
- **`mistkit.detect_scheme()`** — `SOCIALBLOCKER_THEME` override, then the XDG
  portal (`org.freedesktop.appearance color-scheme`), then GNOME's `gsettings`
  key, then the GTK theme name, then light. Every probe is a subprocess with a
  1.5s timeout: a missing tool or a wedged session bus must never keep the
  window from opening. *`Read`, not `ReadOne`* — ReadOne is the newer spelling
  and is absent from portal builds still in the field (verified here).
- **The GUI follows a theme change live**, polled every 10 ticks. *Why polling
  and not a D-Bus signal subscription:* a subscription needs a long-lived
  `gdbus monitor` child and a reader thread; the probe measures **6.7 ms
  median / 10.4 ms worst**, which is under one frame, so a 10s poll is ~0.07%
  of one core and cannot stall the UI thread.
  - Tk bakes colours in at construction and has no restyle call, so a switch
    rebuilds the widget tree. That is affordable because the window is a pure
    function of `control.status()`; the composer's three inputs are the only
    state not on disk and are carried across explicitly. *Cost, measured:*
    **649 ms** (destroy 64 + build 158 + ring 83 + Tk layout/paint 337, the
    last including the ~160 ms fog raster). A visible hitch on a rare,
    deliberate action; the cheaper alternative is retinting the classic
    widgets in place instead of rebuilding — not done, it needs a role
    registry at every construction site.
  - Verified read-only: three switches during a **locked** session left
    `state.json` and the hosts file byte-identical, and `stop` stayed refused.
- **Two latent Mist bugs surfaced by Ink and fixed** — both were silently
  wrong all along and only *looked* right because clam's defaults are white:
  - `indicatorcolor` **does not exist** on clam's checkbutton/radiobutton
    indicator (its options are `indicatorbackground` / `indicatorforeground`),
    so every indicator styling call since the Mist port had been a no-op and
    every checkbox rendered `#ffffff` on Ink.
  - `ttk.Notebook` left `bordercolor`/`lightcolor`/`darkcolor` unset, so clam
    drew its own `#eeebe7` bevel around the tab client area.
- **`gui.py`**: `Segment`'s `background=mk.SUNK` default argument was evaluated
  at *import*, which would have frozen one palette forever — now resolved per
  call. `Scroller.release()` added: its wheel handlers are `bind_all`, which
  outlives the widget, so a rebuild would otherwise stack a second handler on a
  destroyed canvas (verified: handler count stays at 1 across four switches).
- **New `tests/test_palette.py`** (9 tests) — WCAG contrast floors per role per
  palette, the elevation ordering, role parity between the two palettes, and
  the detection fallback chain. No Tk root, no display, no root needed.

## 2026-08-15 — GUI: the "Mist" desktop look

- **New `socialblocker/mistkit.py`** — the Mist design system as an outer-circle
  adapter: the palette from `SocialBlocker-Mist-Desktop.html`, font resolution,
  a `ttk.Style` theme on `clam`, and a small raster engine. *Why:* the tokens
  and the art are ~250 lines of pure rendering with no project knowledge;
  keeping them in `gui.py` would have buried the part that actually matters,
  the call-through to `control.py`. It imports nothing from this package.
  - *Rounded corners and a smooth ring in Tk:* Tk's canvas has neither
    anti-aliasing nor alpha compositing, so the fog field and the countdown
    ring are drawn into an RGB byte buffer, sampled 3x3 per pixel and averaged
    down (SSAA), encoded as PNG with `zlib` + `struct`, and loaded through
    `tk.PhotoImage`, which reads PNG natively in Tk 8.6. **Zero new
    dependencies** — the alternative was vendoring an imaging library.
  - The mockup's `rgba()` tokens are composited against their real backdrop
    once, at import, because Tk widgets have no alpha channel.
  - *Measured:* the ring redraw was **p95 121 ms → 50.7 ms** (median 34.9 ms)
    by caching the fog+track backdrop, which never changes with the countdown,
    and skipping subsampling on pixels fully inside the stroke. The fog field
    costs ~160 ms, once, at half resolution + `zoom(2)`.
- **`gui.py` rebuilt to the Mist layout** — status hero with a live countdown
  ring, a segmented all-day mode control, presets and the focus composer side
  by side, three stat tiles, and the lists. Same features as before; the
  boot-block settings moved into a **Startup** tab so the page stays shorter.
  All `control.py` calls, the pkexec elevation and the locked-mode behaviour
  are unchanged — the front-end stayed thin.
  - The body **scrolls**: the full layout is ~960px tall and this machine has a
    1360x768 output, so a fixed layout would have cut off the lists.
  - Two measured layout bugs fixed: the page opened scrolled to the bottom
    (now forced to the top after layout), and the hero's `+15 / Stop` buttons
    collided because their offset was hard-coded rather than measured from the
    resolved font.
- **`control.status()` gains `session_started_at` and `session_total`** —
  the ring needs elapsed/total and only `session_remaining` was exposed. Derived
  in `control.py` so no front-end does arithmetic on the session entity, and so
  `extend` rescales the total instead of overshooting it. Both keys are
  additive; nothing existing changed.
- **Fonts are resolved, not bundled.** Mist wants Manrope + Instrument Serif;
  the app falls back through Inter / Cantarell / Ubuntu / DejaVu Sans and
  Charter / DejaVu Serif. *Why not vendor them:* `install.sh` runs as root and
  would have to re-derive the real user's `HOME` to place fonts — the same
  `pwd`/`chown` problem `autostart.py` already carries — and ~400KB of binary
  sits badly in a repo whose headline feature is having nothing to install.

## 2026-08-15 — install: run from any folder, and an editable (`--link`) install

- **`install.sh --link`** — an *editable install* (`pip install -e` equivalent):
  the `/usr/local/bin/socialblocker` launcher and the systemd unit point at the
  checkout itself instead of a copy. *Why:* the command already worked from any
  directory, but `/opt/socialblocker` is a **snapshot** — every source edit
  needed a reinstall before the global command or the daemon saw it. Copy stays
  the default (it survives an unmounted disk and is not user-writable).
  - The unit gains **`RequiresMountsFor=$PREFIX`** when the code is not on the
    root filesystem. *Why:* this checkout lives on `/media/upstal` (`/dev/sdb`);
    without it the daemon starts before the disk is mounted and `Restart=always`
    turns that into a crash loop at every boot.
  - `--link` warns when the prefix is not root-owned: the root daemon would be
    executing code any local user can rewrite — a privilege-escalation path, so
    it is stated rather than hidden.
  - install.sh now **restarts an already-running daemon**, rejects prefixes
    containing spaces (`PYTHONPATH` is passed unquoted through `env`), and
    generates the launcher directly instead of writing it and then `sed`-ing it.
- `control.status()` gains **`source_dir`**, printed by the CLI as
  `Running from:`. *Why:* with two install modes there was no way to tell a stale
  `/opt` copy from the checkout you just edited — exactly the confusion that
  wasted time during the autostart work.
- `systemd/socialblocker.service`: comment now says it is a template rewritten by
  install.sh, not a file to hand-edit.
- Verified by running both modes against sandboxed paths (launcher + unit
  inspected, `systemd-analyze verify` clean) and running the generated link-mode
  launcher from `/tmp`. 23 tests pass, incl. a new `source_dir` assertion.

## 2026-08-15 — CLAUDE.md: §5 restated as Clean Architecture, in this project's names

- Rewrote §5 to state the **dependency rule** explicitly (inner never imports
  outer), with the real import chain `cli/gui/daemon -> control -> hosts_engine
  -> config` and a term-mapping table (entities/use case/adapter/driver ->
  `config.py`/`control.py`/`hosts_engine.py`/`cli.py`). *Why:* the layering was
  already correct but was written as house style, so there was nothing to appeal
  to when deciding where a new module belongs.
- **Kept this project's module names**; did not adopt `core/application/`,
  `core/services/<platform>/`, `commons/dto/`, `clients/`, `iac/`. *Why:* those
  describe a TypeScript/Lambda monorepo. Five modules and ~1800 lines do not need
  a directory per circle, and the folder churn would break §2's YAGNI rule and
  every documented command path. The named equivalents are in the table instead.
- Documented `SOCIALBLOCKER_HOME` / `SOCIALBLOCKER_HOSTS` as **the** dependency-
  inversion seam (the project's port), so tests substitute the hosts file rather
  than hard-coding a path.
- Recorded the one real dependency-rule violation: `control.py` (inner) imports
  `autostart.py` (outer adapter — `pwd`, `chown`, `~/.config`), with the
  inversion to apply if autostart grows. Also added `autostart.py`, `systemd/`
  and `install.sh` to the tree, which the old diagram omitted.

## 2026-08-15 — CLAUDE.md: Clean Code limits added to §6

- Added a **Clean Code limits** subsection to §6 Code Style: function/class size
  ceilings (≤25 lines / ≤250 lines, preferring far smaller), intent-revealing
  names, and SOLID applied where it helps. *Why:* §6 said "functions small and
  single-purpose" with no number, which is unenforceable in review.
- Adapted the accompanying error rule to this codebase: purpose-specific
  exception classes (as `control.LockedError` already does) kept in one place, so
  `cli.py` and `gui.py` catch the same types. *Why:* the rule as written referred
  to a `commons/` package of shared error codes — a JS/TS layout that does not
  exist here, and adding one would fight the stdlib-only, five-module design.

## 2026-08-15 — autostart: block automatically at boot

- **Block on every boot (default 300 min), switchable off from the UI.** Three
  deliberately independent switches: the state flag that arms a block, the
  systemd service that runs the daemon which arms it, and an XDG `.desktop`
  entry that opens the GUI at login. *Why:* the first is useless without the
  second, and without the third there is no visible way to switch it off.
  - `config.py`: `Autostart` config (`enabled`/`minutes=300`/`mode=blacklist`/
    `locked=False`/`last_boot_id`), `Session.source` (`manual` vs `boot`), and
    `boot_id()` reading `/proc/sys/kernel/random/boot_id` (falls back to
    `/proc/stat` btime). Backward-compatible load — old `state.json` still works.
  - `control.py`: `arm_boot_session()` — **idempotent per boot, not per process**.
    The daemon runs under `Restart=always`, so keying on process start would
    re-arm a full timer on every crash-restart, undoing the user's Stop. The boot
    id is the idempotency key, saved in the same atomic write as the session so a
    crash can't mark a boot handled with nothing armed. An active session is never
    replaced — rebooting does not escape a locked session. Also `set_autostart()`
    (stamps the current boot on enable, so it takes effect from the *next* boot,
    not from the next daemon restart today), `service_enabled()` /
    `set_service_enabled()` (systemctl; `disable` omits `--now` so nothing
    silently unblocks), and the `.desktop` wrappers.
  - Boot blocks are **excluded from `focus_log`**: logging ~300 min every day
    would make "focused today" and the streak meaningless.
  - `autostart.py` (new): writes `~/.config/autostart/socialblocker.desktop`
    atomically. Resolves the *real* desktop user via `SUDO_USER`/`PKEXEC_UID` and
    chowns the result — under sudo, `$HOME` is root's and the entry would land
    where the session never reads it.
  - `daemon.py`: arms once at startup and logs it.
  - `cli.py`: `autostart [--session on|off] [--minutes N] [--blacklist|--whitelist]
    [--locked|--unlocked] [--service on|off] [--gui on|off]`, bare `autostart`
    prints all three (and warns when the block is armed but the daemon is not
    enabled). New `gui` subcommand — the README had documented it for a while
    without it existing.
  - `gui.py`: "Start with the computer" panel; the window now runs **unprivileged**
    and elevates one CLI command per change through `pkexec` (least privilege — no
    long-lived root Tk process, and no `DISPLAY`/`XAUTHORITY` juggling). Stopping a
    boot block now says you are back on the all-day default, since "stop" reads as
    "unblock". Fixed the countdown showing `299:25` for long blocks (now `4:59:02`).
  - `tests/test_engine.py`: 10 new cases (22 total, all passing) — arm-once-per-boot,
    stopped-stays-stopped across a restart, re-arm on a new boot, locked session
    survives reboot, enable takes effect next boot, unknown boot id never arms,
    boot block not logged as focus, config validation, `.desktop` write/idempotency.
  - Verified end-to-end against a throwaway hosts file (simulated boot → armed →
    stopped → crash-restart stays off → new boot re-arms), and the GUI was built
    and laid out for real (unmapped window, so nothing popped up on screen).
  - `README.md` / `install.sh`: documented the three switches, plus the two facts
    that otherwise read as bugs — enabling takes effect from the *next* boot, and
    an **Upgrading** section (the daemon runs `/opt/socialblocker`, so a checkout
    edit does nothing until `sudo ./install.sh && sudo systemctl restart`).

## 2026-07-24 — GUI parity: stats + presets

- **Tkinter `gui.py` brought to parity** with the CLI's new engine features.
  *Why:* CLAUDE.md §5 — both front-ends must reach the same features through
  `control.py`; the previous entry left the GUI behind.
  - Header now shows a live stats line: **Blocked now · Focused today · Streak**
    (from `control.status()`, refreshed each tick).
  - **Preset buttons** above the composer (from `control.list_presets()`); a click
    only pre-fills minutes/mode/locked — the duration stays adjustable before Start,
    matching the "preset = starting point" decision. Uses `p=p` default-binding to
    dodge the late-binding closure bug.
  - GUI stays thin — no business logic added; it only reads status and calls existing
    `control` functions. Verified by module import + the 12 engine tests still passing
    (Tkinter itself needs a display, so the window wasn't launched here).

## 2026-07-24 — engine: focus stats + presets

- **Focus stats (focused-today, streak) + blocked-now count + presets** wired into
  the engine so the redesign's new surfaces have real data behind them. *Why:* the
  Mist mockup shows these; the truth belongs in the engine, not the front-end.
  - `config.py`: added `Session.started_at` (for true focused-minutes incl. extends),
    a `FocusRecord` + `State.focus_log` history with backward-compatible migration
    (old `state.json` still loads), derivations `focused_today_min()` / `streak_days()`,
    and `prune_log()` (90-day retention — bounds state size). Added `presets()` loader.
  - `control.py`: `_reap_completed()` records a session the moment it ends and clears
    it — a completed session has no natural event, so every load path reaps here; it's
    **idempotent** (deduped on `ends_at`) so the daemon and a CLI can't double-count a
    race. Added `reap()`, `list_presets()`, `start_preset(name, minutes=None)` (duration
    stays overridable — preset is only a starting point), and enriched `status()` with
    `blocked_now` (reused from `hosts_engine.domains_for_mode`, not re-derived),
    `universe_size`, `focused_today_min`, `streak_days`. Locked-mode enforcement stays
    the single choke point — presets go through `start_session`.
  - `daemon.py`: reaps each tick so stats stay current even without a CLI command.
  - `cli.py`: `status` now shows blocked-now / focus-today / streak; new `stats` and
    `preset list|start <name> [minutes]` commands.
  - `data/presets.json`: bundled Deep Work / Sprint / Wind-down (editable, no code change).
  - `tests/test_engine.py`: 12 unittest cases (reap idempotency + dedupe, streak,
    stop-doesn't-count, pruning, locked enforcement regression, presets + override,
    backward-compat load) — all pass, run without root via SOCIALBLOCKER_HOME/HOSTS.
  - Front-end parity (§5) completed in the GUI entry above (same day).

## 2026-07-24 — Mist desktop mockup
- **Built `SocialBlocker-Mist-Desktop.html`** — realized the `1a Desktop · Mist —
  calm, light & airy` direction from `SocialBlocker-Redesign.html` (which only held
  `dc-import` placeholders) as a real, fully-interactive mockup. *Why:* to have a
  working reference UI for the redesign, not just a spec. Covers the whole GTK app
  feature set — all-day mode (blacklist/whitelist/off), focus session with minute
  stepper + presets, locked sessions (Stop refused while locked), +15/Stop, live
  countdown ring, stats (focused-today / blocked-now / streak), and blacklist/
  whitelist management. Seeded with real domains from `data/`. Theme: Instrument
  Serif (display) + Manrope (UI, variable font both embedded as base64 data-URIs so
  it works under the artifact CSP), cool teal-on-mist palette matching the catalog's
  `oklch(0.6 0.085 205)` accent. Single-theme light on purpose — Mist *is* the light
  identity; Ink is the dark sibling. Mockup only; does not touch the Python engine.
