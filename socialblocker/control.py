"""High-level operations shared by the CLI, GUI, and daemon.

Every mutation goes: load state -> change -> save state -> re-apply hosts.
This keeps /etc/hosts in sync with the source-of-truth state file, and enforces
the locked-session rule in exactly one place.
"""

from __future__ import annotations

import subprocess
import time

from . import autostart, config, hosts_engine
from .config import BLACKLIST, WHITELIST, OFF, MODES, Session, ScheduleRule


class LockedError(RuntimeError):
    """Raised when the user tries to weaken protection during a locked session."""


def _guard_locked(state: config.State) -> None:
    if state.session.active() and state.session.locked:
        mins = (state.session.remaining() + 59) // 60
        raise LockedError(
            f"A locked focus session is running. It cannot be stopped for "
            f"another {mins} min. That is the point of locked mode."
        )


def _reap_completed(state: config.State) -> bool:
    """Record a focus session that has ended, then clear it. Returns True if it
    changed `state`.

    A session that runs to completion has no natural event to hook, so every
    load path reaps here (and so does the daemon). Recording is deduped on the
    session's `ends_at`, which makes it idempotent when the daemon and a CLI
    command race to reap the same expiry — the minutes are only counted once.
    """
    s = state.session
    if s.ends_at == 0 or s.active():
        return False  # nothing running, or still running
    # A boot block is enforcement, not focus work. Logging it would report ~300
    # "focused" minutes every single day, which makes the streak meaningless.
    already = (s.source == config.BOOT
               or any(abs(r.ended_at - s.ends_at) < 1.0 for r in state.focus_log))
    if not already:
        minutes = round((s.ends_at - s.started_at) / 60) if s.started_at else 0
        state.focus_log.append(config.FocusRecord(
            ended_at=s.ends_at, minutes=max(0, minutes),
            mode=s.mode, locked=s.locked))
        state.prune_log()
    state.session = Session()  # cleared; the session is over
    return True


def _load() -> config.State:
    """Load state and reap any just-completed session in-memory. Callers that
    save afterwards persist the reap; read-only callers use `reap()` instead."""
    state = config.load_state()
    _reap_completed(state)
    return state


def reap() -> bool:
    """Persistently log a just-completed session, if there is one. Used by the
    daemon (and status()) so stats stay current even without a mutating op."""
    state = config.load_state()
    if _reap_completed(state):
        config.save_state(state)
        return True
    return False


def refresh() -> tuple[str, bool, int]:
    """Re-apply whatever the state says should be enforced right now."""
    state = config.load_state()
    if _reap_completed(state):
        config.save_state(state)
    return hosts_engine.apply(state)


# --- default (all-day) mode ------------------------------------------------

def set_default_mode(mode: str) -> tuple[str, bool, int]:
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}")
    state = _load()
    # Weakening the default mode during a locked session is not allowed.
    if mode == OFF or (mode == BLACKLIST and state.default_mode == WHITELIST):
        _guard_locked(state)
    state.default_mode = mode
    config.save_state(state)
    return hosts_engine.apply(state)


# --- focus sessions --------------------------------------------------------

def start_session(minutes: int, mode: str = WHITELIST,
                  locked: bool = False) -> tuple[str, bool, int]:
    if mode not in (BLACKLIST, WHITELIST):
        raise ValueError("session mode must be 'blacklist' or 'whitelist'")
    if minutes <= 0:
        raise ValueError("session length must be positive")
    state = _load()
    if state.session.active():
        _guard_locked(state)  # cannot replace a locked session
    now = time.time()
    state.session = Session(
        mode=mode,
        started_at=now,
        ends_at=now + minutes * 60,
        locked=locked,
    )
    config.save_state(state)
    return hosts_engine.apply(state)


def stop_session() -> tuple[str, bool, int]:
    state = _load()
    _guard_locked(state)
    state.session = Session()  # cleared (stopping early does not count as focus)
    config.save_state(state)
    return hosts_engine.apply(state)


def extend_session(minutes: int) -> tuple[str, bool, int]:
    """Extending is always allowed — even during a locked session."""
    state = _load()
    if not state.session.active():
        raise RuntimeError("no active session to extend")
    state.session.ends_at += minutes * 60
    config.save_state(state)
    return hosts_engine.apply(state)


# --- list editing ----------------------------------------------------------

def _norm(domain: str) -> str:
    return domain.strip().lower().lstrip(".")


def add_to_blocklist(domains: list[str]) -> None:
    state = _load()
    state.blocklist = sorted(set(state.blocklist) | {_norm(d) for d in domains if _norm(d)})
    config.save_state(state)
    hosts_engine.apply(state)


def remove_from_blocklist(domains: list[str]) -> None:
    state = _load()
    # Shrinking protection during a locked blacklist session is blocked.
    if state.session.active() and state.session.mode == BLACKLIST:
        _guard_locked(state)
    drop = {_norm(d) for d in domains}
    state.blocklist = sorted(d for d in state.blocklist if d not in drop)
    config.save_state(state)
    hosts_engine.apply(state)


def add_to_whitelist(domains: list[str]) -> None:
    """Allowing more sites is always fine, even mid-lock (it only loosens the
    strict whitelist a little — the discussion notes this friction is expected)."""
    state = _load()
    state.whitelist = sorted(set(state.whitelist) | {_norm(d) for d in domains if _norm(d)})
    config.save_state(state)
    hosts_engine.apply(state)


def remove_from_whitelist(domains: list[str]) -> None:
    state = _load()
    drop = {_norm(d) for d in domains}
    state.whitelist = sorted(d for d in state.whitelist if d not in drop)
    config.save_state(state)
    hosts_engine.apply(state)


# --- schedules -------------------------------------------------------------

def add_schedule(rule: ScheduleRule) -> None:
    state = _load()
    state.schedules.append(rule)
    config.save_state(state)
    hosts_engine.apply(state)


def clear_schedules() -> None:
    state = _load()
    _guard_locked(state)
    state.schedules = []
    config.save_state(state)
    hosts_engine.apply(state)


# --- autostart -------------------------------------------------------------
#
# Three independent switches, deliberately separate:
#   1. the state flag below  — arm a block once per boot
#   2. the systemd service   — makes the root daemon run at boot at all
#   3. the .desktop entry    — opens the GUI at login (see autostart.py)
# (1) does nothing without (2), because the daemon is what arms it.

SERVICE_NAME = "socialblocker"


def set_autostart(enabled: bool | None = None, minutes: int | None = None,
                  mode: str | None = None,
                  locked: bool | None = None) -> config.Autostart:
    """Update the boot-block config. Only the arguments passed are changed.

    No locked-mode guard here: this configures the *next* boot and cannot
    shorten or weaken the session running right now.
    """
    state = _load()
    a = state.autostart
    was_enabled = a.enabled

    if mode is not None:
        if mode not in (BLACKLIST, WHITELIST):
            raise ValueError("autostart mode must be 'blacklist' or 'whitelist'")
        a.mode = mode
    if minutes is not None:
        if minutes <= 0:
            raise ValueError("autostart length must be positive")
        a.minutes = minutes
    if locked is not None:
        a.locked = bool(locked)
    if enabled is not None:
        a.enabled = bool(enabled)

    # Turning it on stamps the current boot as already handled, so the setting
    # takes effect from the *next* boot. Without this, a daemon crash-restart
    # later today would arm a block the user never asked for right now.
    if a.enabled and not was_enabled:
        a.last_boot_id = config.boot_id()

    config.save_state(state)
    return a


def arm_boot_session() -> hosts_engine.Applied | None:
    """Start the configured boot block, at most once per machine boot.

    Called by the daemon at startup. Returns what was applied, or None when
    nothing was armed. Skipped when:
      - autostart is off, or the boot identity is unknown (fail safe: never
        arm rather than risk arming repeatedly);
      - this boot was already handled (the `Restart=always` case);
      - a session is already running — including a locked one that survived a
        reboot, which must not be shortened or replaced by rebooting.
    """
    state = _load()
    a = state.autostart
    if not a.enabled:
        return None

    bid = config.boot_id()
    if not bid or bid == a.last_boot_id:
        return None
    a.last_boot_id = bid

    if state.session.active():
        config.save_state(state)  # remember this boot; leave the session alone
        return None

    # Written as one state object (key + session) so a single atomic save
    # records both — a crash can't leave the boot marked as handled with no
    # session started. That is why this does not route through start_session().
    now = time.time()
    state.session = Session(
        mode=a.mode,
        started_at=now,
        ends_at=now + a.minutes * 60,
        locked=a.locked,
        source=config.BOOT,
    )
    config.save_state(state)
    return hosts_engine.apply(state)


def _systemctl(*args: str):
    """Run systemctl, or return None if this machine has no systemd."""
    try:
        return subprocess.run(["systemctl"] + list(args),
                              capture_output=True, text=True)
    except OSError:
        return None


def service_enabled() -> bool | None:
    """Is the daemon enabled at boot? None when systemd or the unit is missing.

    Deliberately not part of status(): it spawns a process, and the GUI polls
    status once a second.
    """
    cp = _systemctl("is-enabled", SERVICE_NAME)
    if cp is None:
        return None
    val = (cp.stdout or "").strip()
    if val in ("enabled", "enabled-runtime", "static", "alias", "indirect"):
        return True
    if val in ("disabled", "masked", "masked-runtime"):
        return False
    return None  # "not-found" and friends


def set_service_enabled(on: bool) -> str:
    """Enable (and start) or disable the boot daemon. Needs root."""
    action = ["enable", "--now"] if on else ["disable"]
    cp = _systemctl(*(action + [SERVICE_NAME]))
    if cp is None:
        raise RuntimeError(
            "systemctl not found — this machine does not use systemd, so the "
            "daemon cannot be started at boot automatically.")
    if cp.returncode != 0:
        msg = (cp.stderr or cp.stdout or "").strip()
        raise RuntimeError(
            "systemctl {} {} failed: {}\nIf the unit is missing, install it "
            "with: sudo ./install.sh".format(" ".join(action), SERVICE_NAME, msg))
    # Disable intentionally omits --now: the running daemon keeps enforcing the
    # current rules until reboot, so nothing silently unblocks mid-session.
    return "enabled and started" if on else "disabled (still running until reboot)"


def gui_autostart_enabled() -> bool:
    """Is the login (.desktop) entry installed for the desktop user?"""
    return autostart.enabled()


def set_gui_autostart(on: bool) -> str:
    """Add or remove the login entry. Needs no root — it is the user's own file."""
    if on:
        return "added: {}".format(autostart.enable())
    return "removed" if autostart.disable() else "was not present"


# --- presets (quick-start focus sessions) ----------------------------------

def list_presets() -> list[dict]:
    """The bundled quick-start presets (see data/presets.json)."""
    return config.presets()


def start_preset(name: str, minutes: int | None = None) -> tuple[str, bool, int]:
    """Start a focus session from a named preset.

    A preset is only a starting point: pass `minutes` to override its default
    duration (the UI does this via the minute stepper). Locked-mode enforcement
    still happens in start_session — presets never bypass the choke point.
    """
    for p in config.presets():
        if str(p.get("name", "")).lower() == name.lower():
            mins = minutes if minutes is not None else int(p.get("default_minutes", 25))
            return start_session(mins,
                                 mode=p.get("mode", WHITELIST),
                                 locked=bool(p.get("locked", False)))
    valid = ", ".join(str(p.get("name", "")) for p in config.presets())
    raise ValueError(f"unknown preset '{name}'. Available: {valid}")


# --- status ----------------------------------------------------------------

def status() -> dict:
    state = config.load_state()
    if _reap_completed(state):
        config.save_state(state)
    mode, locked = state.effective()
    # "blocked now" is the truthful effective count from the hosts engine — the
    # same base-domain set it would write, so front-ends never re-derive it.
    blocked_now = len(hosts_engine.domains_for_mode(state, mode))
    return {
        "default_mode": state.default_mode,
        "effective_mode": mode,
        "locked": locked,
        "session_active": state.session.active(),
        "session_remaining": state.session.remaining(),
        "session_mode": state.session.mode,
        "session_source": state.session.source,
        # Elapsed-fraction inputs for a progress display. Derived here so no
        # front-end has to do arithmetic on the session entity, and so `extend`
        # correctly rescales the total rather than overshooting it.
        "session_started_at": state.session.started_at,
        "session_total": max(0, int(state.session.ends_at - state.session.started_at)),
        "blocklist_count": len(state.blocklist),
        "whitelist_count": len(state.whitelist),
        "schedules": len(state.schedules),
        "blocked_now": blocked_now,
        "universe_size": len(config.universe()),
        "focused_today_min": state.focused_today_min(),
        "streak_days": state.streak_days(),
        "autostart_enabled": state.autostart.enabled,
        "autostart_minutes": state.autostart.minutes,
        "autostart_mode": state.autostart.mode,
        "autostart_locked": state.autostart.locked,
        # Which copy of the code answered. With both copy and linked installs
        # possible, this is the only reliable way to tell whether the command
        # you just ran is the checkout you just edited.
        "source_dir": str(config.PROJECT_DIR),
    }
