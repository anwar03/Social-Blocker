"""Background enforcement loop.

Runs as root (systemd). Every `interval` seconds it re-applies the effective
mode. This does two jobs:

  1. Schedule/session transitions take effect automatically (a session that has
     expired simply stops matching, a schedule window opens/closes on time).
  2. It repairs tampering — if someone deletes the managed block from
     /etc/hosts during a locked session, it comes right back. That is what makes
     locked mode actually stick for a userland tool.
"""

from __future__ import annotations

import signal
import time

from . import config, control, hosts_engine


class _Stop(Exception):
    pass


def _handle_signal(signum, frame):
    raise _Stop()


def run(interval: int = 5) -> None:
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    last_desc = None
    print(f"[socialblocker] daemon started (interval={interval}s)", flush=True)

    # Arm the configured boot block. Safe to call on every start: control keys
    # it on the boot id, so a systemd Restart=always crash-loop cannot re-arm a
    # session the user already stopped.
    armed = control.arm_boot_session()
    if armed is not None:
        mode, locked, n = armed
        print(f"[socialblocker] {time.strftime('%H:%M:%S')} autostart armed "
              f"{mode} locked={locked} n={n}", flush=True)

    try:
        while True:
            # Log a focus session the moment it completes, so stats stay current
            # even if the user never runs a CLI command.
            if control.reap():
                print(f"[socialblocker] {time.strftime('%H:%M:%S')} "
                      f"focus session completed — logged", flush=True)
            state = config.load_state()
            mode, locked, n = hosts_engine.apply(state)
            desc = f"{mode} locked={locked} n={n} " \
                   f"session_left={state.session.remaining()}"
            if desc != last_desc:
                print(f"[socialblocker] {time.strftime('%H:%M:%S')} enforcing {desc}",
                      flush=True)
                last_desc = desc
            time.sleep(interval)
    except _Stop:
        print("[socialblocker] daemon stopping (leaving current rules in place)",
              flush=True)
