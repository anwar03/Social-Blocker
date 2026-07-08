"""Command-line interface for SocialBlocker.

Anything that edits /etc/hosts needs root, so most subcommands must be run with
sudo. The CLI checks and gives a friendly hint instead of a raw traceback.
"""

from __future__ import annotations

import argparse
import os
import sys
import time

from . import config, control, hosts_engine, daemon
from .config import BLACKLIST, WHITELIST, OFF
from .control import LockedError


def _need_root() -> None:
    if os.geteuid() != 0 and str(config.HOSTS_FILE) == "/etc/hosts":
        sys.exit("This command edits /etc/hosts — please run it with sudo.")


def _fmt_remaining(secs: int) -> str:
    m, s = divmod(secs, 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}h {m}m"
    return f"{m}m {s}s" if m else f"{s}s"


def cmd_status(args) -> None:
    st = control.status()
    lock = " 🔒 LOCKED" if st["locked"] else ""
    print(f"Default mode : {st['default_mode']}")
    print(f"Effective now: {st['effective_mode']}{lock}")
    if st["session_active"]:
        print(f"Focus session: {st['session_mode']} — "
              f"{_fmt_remaining(st['session_remaining'])} left")
    else:
        print("Focus session: none")
    print(f"Blacklist    : {st['blocklist_count']} domains")
    print(f"Whitelist    : {st['whitelist_count']} domains")
    print(f"Schedules    : {st['schedules']} rule(s)")


def cmd_mode(args) -> None:
    _need_root()
    try:
        mode, locked, n = control.set_default_mode(args.mode)
    except LockedError as e:
        sys.exit(str(e))
    print(f"Default mode set to '{args.mode}'. Enforcing '{mode}' "
          f"({n} domains blocked).")


def cmd_focus(args) -> None:
    _need_root()
    mode = BLACKLIST if args.blacklist else WHITELIST
    try:
        m, locked, n = control.start_session(args.minutes, mode=mode,
                                              locked=args.locked)
    except (LockedError, ValueError) as e:
        sys.exit(str(e))
    lock = " (LOCKED — cannot be stopped early)" if locked else ""
    print(f"Focus session started: {mode} for {args.minutes} min{lock}. "
          f"{n} domains blocked.")


def cmd_stop(args) -> None:
    _need_root()
    try:
        mode, locked, n = control.stop_session()
    except LockedError as e:
        sys.exit(str(e))
    print(f"Session stopped. Back to default '{mode}' ({n} domains blocked).")


def cmd_extend(args) -> None:
    _need_root()
    try:
        control.extend_session(args.minutes)
    except RuntimeError as e:
        sys.exit(str(e))
    print(f"Session extended by {args.minutes} min.")


def cmd_block(args) -> None:
    _need_root()
    try:
        if args.action == "add":
            control.add_to_blocklist(args.domains)
        else:
            control.remove_from_blocklist(args.domains)
    except LockedError as e:
        sys.exit(str(e))
    print(f"Blacklist {args.action}: {', '.join(args.domains)}")


def cmd_allow(args) -> None:
    _need_root()
    if args.action == "add":
        control.add_to_whitelist(args.domains)
    else:
        control.remove_from_whitelist(args.domains)
    print(f"Whitelist {args.action}: {', '.join(args.domains)}")


def cmd_schedule(args) -> None:
    _need_root()
    days = _parse_days(args.days)
    mode = BLACKLIST if args.blacklist else WHITELIST
    rule = config.ScheduleRule(start=args.start, end=args.end, mode=mode,
                               days=days, locked=args.locked)
    control.add_schedule(rule)
    print(f"Schedule added: {mode} {args.start}-{args.end} on days {days}"
          + (" (locked)" if args.locked else ""))


def cmd_refresh(args) -> None:
    _need_root()
    mode, locked, n = control.refresh()
    print(f"Re-applied '{mode}' ({n} domains blocked).")


def cmd_daemon(args) -> None:
    _need_root()
    daemon.run(interval=args.interval)


def cmd_list(args) -> None:
    state = config.load_state()
    which = args.which
    items = state.blocklist if which == "block" else state.whitelist
    print(f"{which}list ({len(items)} domains):")
    for d in items:
        print(f"  {d}")


def _parse_days(spec: str) -> list[int]:
    names = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
    spec = spec.lower().strip()
    if spec in ("all", "everyday", "daily"):
        return [0, 1, 2, 3, 4, 5, 6]
    if spec in ("weekdays", "week"):
        return [0, 1, 2, 3, 4]
    if spec in ("weekend", "weekends"):
        return [5, 6]
    out = []
    for tok in spec.split(","):
        tok = tok.strip()
        if tok in names:
            out.append(names[tok])
        elif tok.isdigit():
            out.append(int(tok) % 7)
    return sorted(set(out)) or [0, 1, 2, 3, 4]


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="socialblocker",
        description="Linux desktop focus blocker (blacklist / whitelist / locked focus).",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status", help="show current state").set_defaults(func=cmd_status)

    m = sub.add_parser("mode", help="set the all-day default mode")
    m.add_argument("mode", choices=[OFF, BLACKLIST, WHITELIST])
    m.set_defaults(func=cmd_mode)

    f = sub.add_parser("focus", help="start a focus session")
    f.add_argument("minutes", type=int)
    grp = f.add_mutually_exclusive_group()
    grp.add_argument("--whitelist", action="store_true", help="(default) allow only work sites")
    grp.add_argument("--blacklist", action="store_true", help="just block distractions")
    f.add_argument("--locked", action="store_true",
                   help="cannot be stopped before the timer ends")
    f.set_defaults(func=cmd_focus)

    sub.add_parser("stop", help="stop the current focus session").set_defaults(func=cmd_stop)

    e = sub.add_parser("extend", help="add minutes to the running session")
    e.add_argument("minutes", type=int)
    e.set_defaults(func=cmd_extend)

    b = sub.add_parser("block", help="edit the blacklist")
    b.add_argument("action", choices=["add", "remove"])
    b.add_argument("domains", nargs="+")
    b.set_defaults(func=cmd_block)

    a = sub.add_parser("allow", help="edit the whitelist")
    a.add_argument("action", choices=["add", "remove"])
    a.add_argument("domains", nargs="+")
    a.set_defaults(func=cmd_allow)

    s = sub.add_parser("schedule", help="add a recurring rule")
    s.add_argument("--start", default="09:00")
    s.add_argument("--end", default="12:00")
    s.add_argument("--days", default="weekdays",
                   help="weekdays|weekend|all|mon,tue,...")
    grp2 = s.add_mutually_exclusive_group()
    grp2.add_argument("--whitelist", action="store_true")
    grp2.add_argument("--blacklist", action="store_true")
    s.add_argument("--locked", action="store_true")
    s.set_defaults(func=cmd_schedule)

    ls = sub.add_parser("list", help="print a blocklist/whitelist")
    ls.add_argument("which", choices=["block", "allow"])
    ls.set_defaults(func=cmd_list)

    sub.add_parser("refresh", help="re-apply the effective mode").set_defaults(func=cmd_refresh)

    d = sub.add_parser("daemon", help="run the enforcement loop (foreground)")
    d.add_argument("--interval", type=int, default=5)
    d.set_defaults(func=cmd_daemon)

    return p


def main(argv=None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
