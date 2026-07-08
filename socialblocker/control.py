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


def refresh() -> tuple[str, bool, int]:
    """Re-apply whatever the state says should be enforced right now."""
    return hosts_engine.apply(config.load_state())


# --- default (all-day) mode ------------------------------------------------

def set_default_mode(mode: str) -> tuple[str, bool, int]:
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}")
    state = config.load_state()
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
    state = config.load_state()
    if state.session.active():
        _guard_locked(state)  # cannot replace a locked session
    state.session = Session(
        mode=mode,
        ends_at=time.time() + minutes * 60,
        locked=locked,
    )
    config.save_state(state)
    return hosts_engine.apply(state)


def stop_session() -> tuple[str, bool, int]:
    state = config.load_state()
    _guard_locked(state)
    state.session = Session()  # cleared
    config.save_state(state)
    return hosts_engine.apply(state)


def extend_session(minutes: int) -> tuple[str, bool, int]:
    """Extending is always allowed — even during a locked session."""
    state = config.load_state()
    if not state.session.active():
        raise RuntimeError("no active session to extend")
    state.session.ends_at += minutes * 60
    config.save_state(state)
    return hosts_engine.apply(state)


# --- list editing ----------------------------------------------------------

def _norm(domain: str) -> str:
    return domain.strip().lower().lstrip(".")


def add_to_blocklist(domains: list[str]) -> None:
    state = config.load_state()
    state.blocklist = sorted(set(state.blocklist) | {_norm(d) for d in domains if _norm(d)})
    config.save_state(state)
    hosts_engine.apply(state)


def remove_from_blocklist(domains: list[str]) -> None:
    state = config.load_state()
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
    state = config.load_state()
    state.whitelist = sorted(set(state.whitelist) | {_norm(d) for d in domains if _norm(d)})
    config.save_state(state)
    hosts_engine.apply(state)


def remove_from_whitelist(domains: list[str]) -> None:
    state = config.load_state()
    drop = {_norm(d) for d in domains}
    state.whitelist = sorted(d for d in state.whitelist if d not in drop)
    config.save_state(state)
    hosts_engine.apply(state)


# --- schedules -------------------------------------------------------------

def add_schedule(rule: ScheduleRule) -> None:
    state = config.load_state()
    state.schedules.append(rule)
    config.save_state(state)
    hosts_engine.apply(state)


def clear_schedules() -> None:
    state = config.load_state()
    _guard_locked(state)
    state.schedules = []
    config.save_state(state)
    hosts_engine.apply(state)


# --- status ----------------------------------------------------------------

def status() -> dict:
    state = config.load_state()
    mode, locked = state.effective()
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
    }
