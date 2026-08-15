"""Desktop-session autostart entry — the GNOME "Startup Applications" list.

This is the *user-level* half of starting with the machine: an XDG `.desktop`
file in ~/.config/autostart, which the desktop session launches at login. It
only opens the GUI, so the boot block is visible and can be switched off. It
enforces nothing — enforcement is the root systemd daemon's job, and that runs
before anyone logs in.

The GUI is launched **unprivileged** on purpose. It reads state.json for status
and escalates a single CLI command through pkexec when the user actually
changes something, so a long-lived Tk process never holds root.
"""

from __future__ import annotations

import os
import pwd
import shutil
import sys
from pathlib import Path

from . import config

DESKTOP_FILE = "socialblocker.desktop"


def _owner() -> pwd.struct_passwd:
    """The human whose desktop session this entry belongs to.

    Under sudo (or pkexec) the effective user is root, and root's ~/.config is
    not the directory the desktop session reads — writing there would silently
    do nothing and the entry would never appear in Startup Applications.
    SUDO_USER / PKEXEC_UID name the real user; otherwise we are that user.
    """
    name = os.environ.get("SUDO_USER")
    if name:
        try:
            return pwd.getpwnam(name)
        except KeyError:
            pass
    uid = os.environ.get("PKEXEC_UID")
    if uid and uid.isdigit():
        try:
            return pwd.getpwuid(int(uid))
        except KeyError:
            pass
    return pwd.getpwuid(os.getuid())


def _autostart_dir(owner: pwd.struct_passwd) -> Path:
    # XDG_CONFIG_HOME is only trustworthy when we *are* the owner; under sudo it
    # still holds the invoking shell's value and may point anywhere.
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg and owner.pw_uid == os.getuid():
        return Path(xdg) / "autostart"
    return Path(owner.pw_dir) / ".config" / "autostart"


def desktop_path() -> Path:
    """Where the autostart entry lives for the real desktop user."""
    return _autostart_dir(_owner()) / DESKTOP_FILE


def _exec_command() -> tuple[str, str]:
    """Return (Exec, Path) for the entry: how to launch the GUI, and from where."""
    launcher = shutil.which("socialblocker")
    if launcher:
        return launcher + " gui", ""
    # Dev checkout, not installed: run the module and set the working directory
    # to the repo so the package is importable.
    return sys.executable + " -m socialblocker.gui", str(config.PROJECT_DIR)


def _render() -> str:
    exec_cmd, workdir = _exec_command()
    lines = [
        "[Desktop Entry]",
        "Type=Application",
        "Version=1.0",
        "Name=SocialBlocker",
        "Comment=Focus blocker — opens at login so the boot block is visible",
        "Exec=" + exec_cmd,
    ]
    if workdir:
        lines.append("Path=" + workdir)
    lines += [
        "Terminal=false",
        "X-GNOME-Autostart-enabled=true",
    ]
    return "\n".join(lines) + "\n"


def enabled() -> bool:
    return desktop_path().exists()


def enable() -> Path:
    """Write the autostart entry. Returns the path written."""
    owner = _owner()
    directory = _autostart_dir(owner)
    created = [p for p in (directory, directory.parent) if not p.exists()]
    directory.mkdir(parents=True, exist_ok=True)

    path = directory / DESKTOP_FILE
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(_render())
    os.replace(tmp, path)  # atomic

    # Running as root, everything we just made would be root-owned and the
    # user could not edit or untick it in Startup Applications.
    if os.geteuid() == 0 and owner.pw_uid != 0:
        for p in created + [path]:
            os.chown(p, owner.pw_uid, owner.pw_gid)
    return path


def disable() -> bool:
    """Remove the autostart entry. Returns True if there was one."""
    path = desktop_path()
    if path.exists():
        path.unlink()
        return True
    return False
