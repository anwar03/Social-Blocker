# Changelog

All notable changes to SocialBlocker. Newest first.

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
