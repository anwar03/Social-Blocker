"""Configuration, paths, and persistent state for SocialBlocker.

State is stored under /etc/socialblocker because the enforcement engine has to
edit /etc/hosts (root-only). Everything the daemon, CLI, and GUI need to agree
on lives in a single JSON state file so they never fight each other.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field, asdict
from datetime import date
from pathlib import Path

# --- Paths -----------------------------------------------------------------

PKG_DIR = Path(__file__).resolve().parent
PROJECT_DIR = PKG_DIR.parent
DATA_DIR = PROJECT_DIR / "data"

# System config dir (override with SOCIALBLOCKER_HOME, mainly for testing).
CONFIG_DIR = Path(os.environ.get("SOCIALBLOCKER_HOME", "/etc/socialblocker"))
STATE_FILE = CONFIG_DIR / "state.json"

HOSTS_FILE = Path(os.environ.get("SOCIALBLOCKER_HOSTS", "/etc/hosts"))

# Markers that fence off the block we manage inside /etc/hosts.
MARK_BEGIN = "# >>> socialblocker >>>"
MARK_END = "# <<< socialblocker <<<"

# Modes
OFF = "off"
BLACKLIST = "blacklist"
WHITELIST = "whitelist"
MODES = (OFF, BLACKLIST, WHITELIST)

# How many days of completed-session history to keep (bounds state.json size).
LOG_RETENTION_DAYS = 90


# --- Bundled default lists -------------------------------------------------

def _load_json(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def default_blocklist() -> list[str]:
    data = _load_json(DATA_DIR / "blocklist.json")
    domains: list[str] = []
    for group in data.get("categories", {}).values():
        domains.extend(group)
    return sorted(set(domains))


def default_whitelist() -> list[str]:
    data = _load_json(DATA_DIR / "whitelist.example.json")
    return sorted(set(data.get("allow", [])))


def universe() -> list[str]:
    data = _load_json(DATA_DIR / "universe.json")
    return sorted(set(data.get("domains", [])))


def presets() -> list[dict]:
    """Bundled quick-start focus presets (see data/presets.json).

    A preset is only a starting point: it carries a *default* duration, mode and
    locked flag. The UI/CLI may override the duration when actually starting.
    """
    data = _load_json(DATA_DIR / "presets.json")
    return list(data.get("presets", []))


# --- State model -----------------------------------------------------------

@dataclass
class Session:
    """An active focus block."""
    mode: str = WHITELIST          # what to enforce while it runs
    ends_at: float = 0.0           # unix time; 0 == not running
    started_at: float = 0.0        # unix time the session began (for stats)
    locked: bool = False           # if True, cannot be stopped early

    def active(self) -> bool:
        return self.ends_at > time.time()

    def remaining(self) -> int:
        return max(0, int(self.ends_at - time.time()))


@dataclass
class FocusRecord:
    """A completed focus session, kept so we can show focus stats.

    `ended_at` doubles as a dedupe key: reaping the same expiry twice (e.g. the
    daemon and a CLI command racing) must not double-count it.
    """
    ended_at: float = 0.0          # unix time the session ended
    minutes: int = 0               # actual focused minutes (includes extensions)
    mode: str = WHITELIST
    locked: bool = False


@dataclass
class ScheduleRule:
    """Automatically switch to `mode` during [start, end] on given weekdays.

    Times are "HH:MM" (24h). days is a list of ints, Mon=0 .. Sun=6.
    """
    start: str = "09:00"
    end: str = "12:00"
    mode: str = WHITELIST
    days: list[int] = field(default_factory=lambda: [0, 1, 2, 3, 4])
    locked: bool = False
    enabled: bool = True


@dataclass
class State:
    # The mode enforced when no session/schedule overrides it.
    default_mode: str = BLACKLIST
    blocklist: list[str] = field(default_factory=default_blocklist)
    whitelist: list[str] = field(default_factory=default_whitelist)
    session: Session = field(default_factory=Session)
    schedules: list[ScheduleRule] = field(default_factory=list)
    focus_log: list[FocusRecord] = field(default_factory=list)

    # ---- effective mode resolution ----
    def effective(self) -> tuple[str, bool]:
        """Return (mode, locked) that should be enforced right now.

        Priority: active session > matching schedule rule > default_mode.
        """
        if self.session.active():
            return self.session.mode, self.session.locked

        rule = self._current_rule()
        if rule is not None:
            return rule.mode, rule.locked

        return self.default_mode, False

    def _current_rule(self) -> ScheduleRule | None:
        now = time.localtime()
        now_min = now.tm_hour * 60 + now.tm_min
        wd = now.tm_wday
        for r in self.schedules:
            if not r.enabled or wd not in r.days:
                continue
            if _to_min(r.start) <= now_min < _to_min(r.end):
                return r
        return None

    # ---- focus stats (derived from the log) ----
    def focused_today_min(self) -> int:
        """Total focused minutes from sessions that completed today (local)."""
        today = _day_ord(time.time())
        return sum(r.minutes for r in self.focus_log
                   if _day_ord(r.ended_at) == today)

    def streak_days(self) -> int:
        """Consecutive days (up to today) with at least one completed session.

        If nothing is completed today yet, the streak is measured up to
        yesterday so an in-progress day does not reset it prematurely.
        """
        days = {_day_ord(r.ended_at) for r in self.focus_log if r.minutes > 0}
        if not days:
            return 0
        today = _day_ord(time.time())
        cursor = today if today in days else today - 1
        if cursor not in days:
            return 0
        streak = 0
        while cursor in days:
            streak += 1
            cursor -= 1
        return streak

    def prune_log(self) -> None:
        """Drop records older than the retention window (bounds state size)."""
        cutoff = _day_ord(time.time()) - LOG_RETENTION_DAYS
        self.focus_log = [r for r in self.focus_log
                          if _day_ord(r.ended_at) >= cutoff]

    # ---- persistence ----
    def to_dict(self) -> dict:
        d = asdict(self)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "State":
        st = cls(
            default_mode=d.get("default_mode", BLACKLIST),
            blocklist=d.get("blocklist") or default_blocklist(),
            whitelist=d.get("whitelist") or default_whitelist(),
        )
        sess = d.get("session") or {}
        st.session = Session(
            mode=sess.get("mode", WHITELIST),
            ends_at=float(sess.get("ends_at", 0.0)),
            started_at=float(sess.get("started_at", 0.0)),
            locked=bool(sess.get("locked", False)),
        )
        st.schedules = [
            ScheduleRule(**{**asdict(ScheduleRule()), **r})
            for r in (d.get("schedules") or [])
        ]
        st.focus_log = [
            FocusRecord(
                ended_at=float(r.get("ended_at", 0.0)),
                minutes=int(r.get("minutes", 0)),
                mode=r.get("mode", WHITELIST),
                locked=bool(r.get("locked", False)),
            )
            for r in (d.get("focus_log") or [])
        ]
        return st


def _to_min(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def _day_ord(ts: float) -> int:
    """Local-calendar day number for a unix timestamp (contiguous integers so
    consecutive days differ by 1 — used for the focus streak)."""
    return date.fromtimestamp(ts).toordinal()


# --- Load / save -----------------------------------------------------------

def ensure_config_dir() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def load_state() -> State:
    if STATE_FILE.exists():
        try:
            return State.from_dict(_load_json(STATE_FILE))
        except (json.JSONDecodeError, KeyError, ValueError):
            pass  # corrupt state -> fall back to fresh defaults
    return State()


def save_state(state: State) -> None:
    ensure_config_dir()
    tmp = STATE_FILE.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(state.to_dict(), fh, indent=2)
    os.replace(tmp, STATE_FILE)  # atomic
