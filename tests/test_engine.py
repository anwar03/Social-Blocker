"""Engine tests for the focus-stats / presets additions.

Run from the repo root:

    python3 -m unittest discover -s tests

These never touch the real /etc/hosts: the SOCIALBLOCKER_HOME / SOCIALBLOCKER_HOSTS
overrides are set (to a throwaway temp dir) *before* importing the package, so
config resolves its paths there. No root required.
"""

import os
import tempfile
import time
import unittest
from datetime import date

# --- redirect state + hosts to a throwaway dir BEFORE importing the package ---
_TMP = tempfile.mkdtemp(prefix="sb-test-")
os.environ["SOCIALBLOCKER_HOME"] = _TMP
os.environ["SOCIALBLOCKER_HOSTS"] = os.path.join(_TMP, "hosts")

from socialblocker import config, control, hosts_engine  # noqa: E402
from socialblocker.config import BLACKLIST, WHITELIST, OFF  # noqa: E402


def _ts_days_ago(n: int, hour: int = 12) -> float:
    """Unix timestamp at local noon, n calendar days ago."""
    d = date.fromordinal(date.today().toordinal() - n)
    return time.mktime((d.year, d.month, d.day, hour, 0, 0, 0, 0, -1))


class EngineTest(unittest.TestCase):
    def setUp(self):
        # Fresh state + a minimal hosts file for every test.
        config.ensure_config_dir()
        if config.STATE_FILE.exists():
            config.STATE_FILE.unlink()
        with open(config.HOSTS_FILE, "w", encoding="utf-8") as fh:
            fh.write("127.0.0.1\tlocalhost\n")

    # ---- blocked-now (effective count) ----
    def test_blocked_now_matches_engine(self):
        control.set_default_mode(BLACKLIST)
        st = control.status()
        self.assertEqual(st["blocked_now"], len(config.load_state().blocklist))

        control.set_default_mode(WHITELIST)
        state = config.load_state()
        expect = len(hosts_engine.domains_for_mode(state, WHITELIST))
        self.assertEqual(control.status()["blocked_now"], expect)
        self.assertEqual(control.status()["universe_size"], len(config.universe()))

        control.set_default_mode(OFF)
        self.assertEqual(control.status()["blocked_now"], 0)

    # ---- reaping a completed session ----
    def test_reap_logs_once_and_is_idempotent(self):
        st = config.load_state()
        now = time.time()
        st.session = config.Session(mode=WHITELIST, started_at=now - 3600,
                                    ends_at=now - 10, locked=False)
        config.save_state(st)

        self.assertTrue(control.reap())     # first reap records it
        self.assertFalse(control.reap())    # nothing left to reap

        after = config.load_state()
        self.assertEqual(len(after.focus_log), 1)
        self.assertEqual(after.focus_log[0].minutes, 60)
        self.assertFalse(after.session.active())
        self.assertEqual(after.session.ends_at, 0)

    def test_reap_dedupes_on_ended_at(self):
        # Simulates the daemon+CLI race: the record already exists but the
        # session was not cleared yet — reap must not double-count it.
        now = time.time()
        end = now - 5
        st = config.load_state()
        st.session = config.Session(mode=WHITELIST, started_at=now - 1800, ends_at=end)
        st.focus_log = [config.FocusRecord(ended_at=end, minutes=30, mode=WHITELIST)]
        config.save_state(st)

        control.reap()
        after = config.load_state()
        self.assertEqual(len(after.focus_log), 1)

    def test_stop_early_does_not_count(self):
        control.start_session(30, mode=WHITELIST, locked=False)
        control.stop_session()
        after = config.load_state()
        self.assertEqual(after.focus_log, [])
        self.assertEqual(after.focused_today_min(), 0)

    # ---- stats derivations ----
    def test_focused_today_and_streak(self):
        st = config.load_state()
        st.focus_log = [
            config.FocusRecord(ended_at=_ts_days_ago(0), minutes=25, mode=WHITELIST),
            config.FocusRecord(ended_at=_ts_days_ago(0), minutes=15, mode=WHITELIST),
            config.FocusRecord(ended_at=_ts_days_ago(1), minutes=50, mode=WHITELIST),
            config.FocusRecord(ended_at=_ts_days_ago(2), minutes=90, mode=WHITELIST),
            config.FocusRecord(ended_at=_ts_days_ago(4), minutes=30, mode=WHITELIST),
        ]
        config.save_state(st)
        state = config.load_state()
        self.assertEqual(state.focused_today_min(), 40)   # 25 + 15 today
        self.assertEqual(state.streak_days(), 3)          # today, -1, -2 (gap at -3)

    def test_streak_holds_when_nothing_today_yet(self):
        st = config.load_state()
        st.focus_log = [
            config.FocusRecord(ended_at=_ts_days_ago(1), minutes=50, mode=WHITELIST),
            config.FocusRecord(ended_at=_ts_days_ago(2), minutes=50, mode=WHITELIST),
        ]
        config.save_state(st)
        # Nothing completed today, but yesterday+the day before -> streak 2.
        self.assertEqual(config.load_state().streak_days(), 2)

    def test_log_pruning_bounds_growth(self):
        st = config.load_state()
        st.focus_log = [
            config.FocusRecord(ended_at=_ts_days_ago(0), minutes=10, mode=WHITELIST),
            config.FocusRecord(ended_at=_ts_days_ago(config.LOG_RETENTION_DAYS + 5),
                               minutes=10, mode=WHITELIST),
        ]
        st.prune_log()
        self.assertEqual(len(st.focus_log), 1)

    # ---- locked-mode enforcement stays intact ----
    def test_locked_stop_refused_extend_allowed(self):
        control.start_session(30, mode=WHITELIST, locked=True)
        with self.assertRaises(control.LockedError):
            control.stop_session()
        control.extend_session(15)  # extending is always allowed
        self.assertTrue(config.load_state().session.active())

    # ---- presets ----
    def test_presets_list_and_start(self):
        names = [p["name"] for p in control.list_presets()]
        self.assertIn("Deep Work", names)

        mode, locked, n = control.start_preset("Deep Work")
        self.assertEqual(mode, WHITELIST)
        self.assertTrue(locked)

    def test_preset_minutes_override(self):
        control.start_preset("Sprint", minutes=5)
        remaining = config.load_state().session.remaining()
        self.assertGreater(remaining, 4 * 60)      # ~5 min, not the 25-min default
        self.assertLessEqual(remaining, 5 * 60)

    def test_unknown_preset_raises(self):
        with self.assertRaises(ValueError):
            control.start_preset("does-not-exist")

    # ---- backward compatibility with pre-stats state files ----
    def test_loads_old_state_without_focus_log(self):
        old = {
            "default_mode": "blacklist",
            "blocklist": ["reddit.com"],
            "whitelist": ["github.com"],
            "session": {"mode": "whitelist", "ends_at": 0.0, "locked": False},
            "schedules": [],
        }
        import json
        with open(config.STATE_FILE, "w", encoding="utf-8") as fh:
            json.dump(old, fh)
        state = config.load_state()   # must not raise
        self.assertEqual(state.focus_log, [])
        self.assertEqual(state.session.started_at, 0.0)
        self.assertEqual(state.focused_today_min(), 0)
        self.assertEqual(state.streak_days(), 0)


if __name__ == "__main__":
    unittest.main()
