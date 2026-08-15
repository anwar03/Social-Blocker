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

from socialblocker import autostart, config, control, hosts_engine  # noqa: E402
from socialblocker.config import BLACKLIST, WHITELIST, OFF, BOOT, MANUAL  # noqa: E402


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
        # Autostart is new too: absent config must load as "off", never armed.
        self.assertFalse(state.autostart.enabled)
        self.assertEqual(state.autostart.minutes, 300)
        self.assertEqual(state.session.source, MANUAL)


class BootAutostartTest(unittest.TestCase):
    """Arming a block once per boot (the daemon's Restart=always problem)."""

    def setUp(self):
        config.ensure_config_dir()
        if config.STATE_FILE.exists():
            config.STATE_FILE.unlink()
        with open(config.HOSTS_FILE, "w", encoding="utf-8") as fh:
            fh.write("127.0.0.1\tlocalhost\n")
        os.environ["SOCIALBLOCKER_BOOT_ID"] = "boot-1"

    def tearDown(self):
        os.environ.pop("SOCIALBLOCKER_BOOT_ID", None)

    def _enable(self, **kw):
        """Enable autostart *as if from a previous boot*, so it is due to arm."""
        control.set_autostart(enabled=True, **kw)
        st = config.load_state()
        st.autostart.last_boot_id = "an-older-boot"
        config.save_state(st)

    def test_arms_once_per_boot(self):
        self._enable(minutes=300, mode=BLACKLIST)
        self.assertIsNotNone(control.arm_boot_session())

        sess = config.load_state().session
        self.assertTrue(sess.active())
        self.assertEqual(sess.source, BOOT)
        self.assertEqual(sess.mode, BLACKLIST)
        self.assertGreater(sess.remaining(), 299 * 60)

        # The daemon restarting (same boot) must not re-arm anything.
        self.assertIsNone(control.arm_boot_session())

    def test_stopped_block_stays_stopped_until_next_boot(self):
        self._enable(minutes=300)
        control.arm_boot_session()
        control.stop_session()                       # user switches it off in the UI
        self.assertIsNone(control.arm_boot_session())  # crash-restart: stays off
        self.assertFalse(config.load_state().session.active())

        os.environ["SOCIALBLOCKER_BOOT_ID"] = "boot-2"   # actual reboot
        self.assertIsNotNone(control.arm_boot_session())
        self.assertTrue(config.load_state().session.active())

    def test_reboot_does_not_escape_a_locked_session(self):
        self._enable(minutes=300)
        control.start_session(30, mode=WHITELIST, locked=True)
        os.environ["SOCIALBLOCKER_BOOT_ID"] = "boot-2"

        self.assertIsNone(control.arm_boot_session())  # left alone, not replaced
        sess = config.load_state().session
        self.assertTrue(sess.locked)
        self.assertEqual(sess.mode, WHITELIST)
        self.assertEqual(sess.source, MANUAL)
        self.assertLessEqual(sess.remaining(), 30 * 60)

    def test_enabling_takes_effect_from_the_next_boot(self):
        # Enabling stamps the current boot, so a daemon restart later today
        # cannot spring a block the user did not ask for right now.
        control.set_autostart(enabled=True, minutes=300)
        self.assertIsNone(control.arm_boot_session())
        os.environ["SOCIALBLOCKER_BOOT_ID"] = "boot-2"
        self.assertIsNotNone(control.arm_boot_session())

    def test_disabled_never_arms(self):
        control.set_autostart(enabled=False)
        self.assertIsNone(control.arm_boot_session())
        self.assertFalse(config.load_state().session.active())

    def test_unknown_boot_id_does_not_arm(self):
        # Fail safe: if we cannot identify the boot we must not arm at all,
        # rather than arm on every single daemon start.
        self._enable(minutes=300)
        original = config.boot_id
        config.boot_id = lambda: ""
        try:
            self.assertIsNone(control.arm_boot_session())
        finally:
            config.boot_id = original
        self.assertFalse(config.load_state().session.active())

    def test_boot_block_is_not_counted_as_focus(self):
        # 300 min logged every day would make "focused today" and the streak
        # meaningless, so a completed boot block is cleared but never logged.
        self._enable(minutes=300)
        control.arm_boot_session()
        st = config.load_state()
        st.session.ends_at = time.time() - 5      # pretend it ran out
        config.save_state(st)

        control.reap()
        after = config.load_state()
        self.assertEqual(after.focus_log, [])
        self.assertEqual(after.focused_today_min(), 0)
        self.assertFalse(after.session.active())

    def test_autostart_config_is_validated(self):
        with self.assertRaises(ValueError):
            control.set_autostart(minutes=0)
        with self.assertRaises(ValueError):
            control.set_autostart(mode=OFF)


class DesktopEntryTest(unittest.TestCase):
    """The XDG autostart (.desktop) entry that Startup Applications lists."""

    def setUp(self):
        self._saved = {k: os.environ.get(k)
                       for k in ("XDG_CONFIG_HOME", "SUDO_USER", "PKEXEC_UID")}
        # Never write into the real ~/.config while testing.
        os.environ["XDG_CONFIG_HOME"] = os.path.join(_TMP, "config")
        os.environ.pop("SUDO_USER", None)
        os.environ.pop("PKEXEC_UID", None)

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_enable_writes_a_launchable_entry(self):
        self.assertFalse(autostart.enabled())
        path = autostart.enable()

        self.assertTrue(autostart.enabled())
        self.assertEqual(path, autostart.desktop_path())
        self.assertTrue(str(path).startswith(os.environ["XDG_CONFIG_HOME"]))
        body = path.read_text(encoding="utf-8")
        self.assertIn("[Desktop Entry]", body)
        self.assertIn("Type=Application", body)
        self.assertIn("X-GNOME-Autostart-enabled=true", body)
        exec_line = [ln for ln in body.splitlines() if ln.startswith("Exec=")][0]
        self.assertIn("gui", exec_line)

    def test_enable_is_idempotent_and_disable_removes(self):
        autostart.enable()
        autostart.enable()          # writing twice must not fail or duplicate
        self.assertTrue(autostart.enabled())
        self.assertTrue(autostart.disable())
        self.assertFalse(autostart.enabled())
        self.assertFalse(autostart.disable())   # already gone


if __name__ == "__main__":
    unittest.main()
