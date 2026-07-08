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

from . import config, hosts_engine


class _Stop(Exception):
    pass


def _handle_signal(signum, frame):
    raise _Stop()


def run(interval: int = 5) -> None:
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    last_desc = None
    print(f"[socialblocker] daemon started (interval={interval}s)", flush=True)
    try:
        while True:
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
