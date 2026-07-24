"""High-level operations shared by the CLI, GUI, and daemon.

Every mutation goes: load state -> change -> save state -> re-apply hosts.
This keeps /etc/hosts in sync with the source-of-truth state file, and enforces
the locked-session rule in exactly one place.
"""

from __future__ import annotations

import time

from . import config, hosts_engine
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
    already = any(abs(r.ended_at - s.ends_at) < 1.0 for r in state.focus_log)
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
        "blocklist_count": len(state.blocklist),
        "whitelist_count": len(state.whitelist),
        "schedules": len(state.schedules),
        "blocked_now": blocked_now,
        "universe_size": len(config.universe()),
        "focused_today_min": state.focused_today_min(),
        "streak_days": state.streak_days(),
    }
