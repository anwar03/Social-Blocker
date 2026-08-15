# Changelog

All notable changes to SocialBlocker. Newest first.

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
