"""Command-line interface for SocialBlocker.

Anything that edits /etc/hosts needs root, so most subcommands must be run with
sudo. The CLI checks and gives a friendly hint instead of a raw traceback.
"""

from __future__ import annotations

import argparse
import os
import sys
import time

from . import autostart, config, control, hosts_engine, daemon
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
        kind = "Boot block   " if st["session_source"] == config.BOOT else "Focus session"
        print(f"{kind}: {st['session_mode']} — "
              f"{_fmt_remaining(st['session_remaining'])} left")
    else:
        print("Focus session: none")
    print(f"Blacklist    : {st['blocklist_count']} domains")
    print(f"Whitelist    : {st['whitelist_count']} domains")
    print(f"Schedules    : {st['schedules']} rule(s)")
    print(f"Blocked now  : {st['blocked_now']} sites "
          f"(of {st['universe_size']} in the universe)")
    print(f"Focus today  : {st['focused_today_min']} min   ·   "
          f"streak {st['streak_days']} day(s)")
    print(f"Running from : {st['source_dir']}")


def cmd_stats(args) -> None:
    st = control.status()
    print(f"Focused today : {st['focused_today_min']} min")
    print(f"Current streak: {st['streak_days']} day(s)")
    print(f"Blocked now   : {st['blocked_now']} sites "
          f"(of {st['universe_size']} in the universe)")


def cmd_preset(args) -> None:
    if args.action == "list":
        for p in control.list_presets():
            lock = " 🔒" if p.get("locked") else ""
            print(f"  {p.get('name',''):<12} {p.get('default_minutes','?'):>3} min  "
                  f"{p.get('mode','')}{lock}")
            if p.get("blurb"):
                print(f"               {p['blurb']}")
        return
    _need_root()
    if not args.name:
        sys.exit("usage: socialblocker preset start <name> [minutes]")
    try:
        mode, locked, n = control.start_preset(args.name, minutes=args.minutes)
    except (ValueError, LockedError) as e:
        sys.exit(str(e))
    lock = " (LOCKED — cannot be stopped early)" if locked else ""
    print(f"Started preset '{args.name}': {mode}{lock}. {n} domains blocked.")


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


def _print_autostart_status() -> None:
    st = control.status()
    lock = "  🔒 locked" if st["autostart_locked"] else ""
    print(f"Boot block  : {'on' if st['autostart_enabled'] else 'off'} — "
          f"{st['autostart_minutes']} min {st['autostart_mode']}{lock}")
    svc = control.service_enabled()
    svc_txt = "enabled" if svc else "disabled" if svc is False else "not installed"
    print(f"Boot daemon : {svc_txt}   (systemd unit '{control.SERVICE_NAME}')")
    print(f"Login entry : {'yes' if control.gui_autostart_enabled() else 'no'}"
          f"   ({autostart.desktop_path()})")
    if st["autostart_enabled"] and not svc:
        print("\nNote: the boot block is armed by the daemon, and the daemon is not "
              "enabled at boot.\n      Run: sudo socialblocker autostart --service on")


def cmd_autostart(args) -> None:
    did_something = False

    # The login entry is the user's own ~/.config file — no root involved.
    if args.gui is not None:
        print(f"Login entry : {control.set_gui_autostart(args.gui == 'on')}")
        did_something = True

    if args.service is not None:
        _need_root()
        try:
            print(f"Boot daemon : {control.set_service_enabled(args.service == 'on')}")
        except RuntimeError as e:
            sys.exit(str(e))
        did_something = True

    mode = BLACKLIST if args.blacklist else WHITELIST if args.whitelist else None
    locked = True if args.locked else False if args.unlocked else None
    enabled = None if args.session is None else (args.session == "on")
    if any(v is not None for v in (enabled, args.minutes, mode, locked)):
        _need_root()
        try:
            a = control.set_autostart(enabled=enabled, minutes=args.minutes,
                                      mode=mode, locked=locked)
        except ValueError as e:
            sys.exit(str(e))
        lock = " (LOCKED — the UI will not be able to stop it)" if a.locked else ""
        print(f"Boot block  : {'on' if a.enabled else 'off'} — "
              f"{a.minutes} min {a.mode}{lock}")
        did_something = True

    if not did_something:
        _print_autostart_status()


def cmd_gui(args) -> None:
    # Imported lazily: Tkinter is a separate system package, and the CLI must
    # keep working on machines that do not have it.
    from . import gui
    gui.main()


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

    sub.add_parser("stats", help="focus stats (today, streak)").set_defaults(func=cmd_stats)

    pr = sub.add_parser("preset", help="list or start a quick-start preset")
    pr.add_argument("action", choices=["list", "start"])
    pr.add_argument("name", nargs="?", help="preset name (for 'start')")
    pr.add_argument("minutes", nargs="?", type=int,
                    help="override the preset's default duration")
    pr.set_defaults(func=cmd_preset)

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

    au = sub.add_parser(
        "autostart",
        help="start blocking automatically when the machine boots",
        description="Three independent switches. --session arms a block at every "
                    "boot, --service makes the daemon (which arms it) run at boot, "
                    "and --gui opens the app at login so you can switch it off. "
                    "With no arguments, prints the status of all three.")
    au.add_argument("--session", choices=["on", "off"],
                    help="arm a block automatically at every boot")
    au.add_argument("--minutes", type=int,
                    help="how long the boot block lasts (default 300)")
    grp3 = au.add_mutually_exclusive_group()
    grp3.add_argument("--blacklist", action="store_true",
                      help="(default) boot block just blocks distractions")
    grp3.add_argument("--whitelist", action="store_true",
                      help="boot block allows only the whitelist")
    grp4 = au.add_mutually_exclusive_group()
    grp4.add_argument("--locked", action="store_true",
                      help="boot block cannot be stopped from the UI")
    grp4.add_argument("--unlocked", action="store_true",
                      help="(default) boot block can be stopped any time")
    au.add_argument("--service", choices=["on", "off"],
                    help="run the enforcement daemon at boot (systemd)")
    au.add_argument("--gui", choices=["on", "off"],
                    help="open the app at login (XDG Startup Applications entry)")
    au.set_defaults(func=cmd_autostart)

    sub.add_parser("gui", help="open the Tkinter window").set_defaults(func=cmd_gui)

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
