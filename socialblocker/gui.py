"""Tkinter GUI for SocialBlocker (standard library only).

Run it as your normal user:
    socialblocker gui       # or: python3 -m socialblocker.gui

Editing /etc/hosts needs root, but this window does not run as root. Reading
status needs no privileges, and every change is applied by elevating one short
`socialblocker` CLI command through pkexec. Keeping a long-lived GUI process
unprivileged is the whole point — least privilege, and no DISPLAY/XAUTHORITY
juggling. Launching the whole app with `sudo -E` still works and then skips
pkexec entirely.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog

from . import autostart, config, control
from .config import BLACKLIST, WHITELIST, OFF
from .control import LockedError


def _countdown(secs: int) -> str:
    """H:MM:SS once past an hour — a 300-min boot block would otherwise read
    as "299:25", which is unreadable."""
    m, s = divmod(int(secs), 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def _needs_pkexec() -> bool:
    """True when this process cannot write the hosts file itself."""
    return os.geteuid() != 0 and str(config.HOSTS_FILE) == "/etc/hosts"


def _root_cli(args: list[str]) -> None:
    """Run one `socialblocker` CLI command as root via pkexec.

    The elevated process is the CLI, never this window. pkexec scrubs the
    environment, so the test/dev overrides are re-attached explicitly.
    """
    env_args = [f"{k}={os.environ[k]}"
                for k in ("SOCIALBLOCKER_HOME", "SOCIALBLOCKER_HOSTS")
                if k in os.environ]
    launcher = shutil.which("socialblocker")
    if launcher:
        cmd = [launcher] + args
    else:  # dev checkout: run the module, with the repo on the import path
        env_args.append(f"PYTHONPATH={config.PROJECT_DIR}")
        cmd = [sys.executable, "-m", "socialblocker"] + args
    if env_args:
        cmd = ["env"] + env_args + cmd

    try:
        cp = subprocess.run(["pkexec"] + cmd, capture_output=True, text=True)
    except OSError:
        raise RuntimeError(
            "pkexec is not installed, so this window cannot ask for admin "
            "rights. Install policykit-1, or relaunch with: sudo -E socialblocker gui")
    if cp.returncode == 126:
        raise RuntimeError("Admin prompt was dismissed — nothing changed.")
    if cp.returncode == 127:
        raise RuntimeError("Authorisation failed — nothing changed.")
    if cp.returncode != 0:
        raise RuntimeError((cp.stderr or cp.stdout or "Command failed.").strip())


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("SocialBlocker")
        self.geometry("580x660")
        self.minsize(560, 600)

        self._build_header()
        self._build_mode_row()
        self._build_focus_box()
        self._build_autostart_box()
        self._build_lists()
        self._build_footer()

        # Unprivileged is the normal case now (pkexec elevates each change), so
        # only warn when there is no way to elevate at all.
        if _needs_pkexec() and not shutil.which("pkexec"):
            self.after(300, lambda: messagebox.showwarning(
                "Cannot apply changes",
                "Changes edit /etc/hosts, which needs admin rights, and pkexec "
                "is not installed.\n\nInstall policykit-1, or relaunch with:\n"
                "  sudo -E socialblocker gui"))

        self._render_lists()
        self._render_autostart()
        self._tick()

    # ---- layout ----
    def _build_header(self):
        f = ttk.Frame(self, padding=(12, 10))
        f.pack(fill="x")
        self.status_var = tk.StringVar(value="…")
        ttk.Label(f, textvariable=self.status_var,
                  font=("TkDefaultFont", 13, "bold")).pack(anchor="w")
        self.session_var = tk.StringVar(value="")
        ttk.Label(f, textvariable=self.session_var,
                  foreground="#0a7").pack(anchor="w")
        self.stats_var = tk.StringVar(value="")
        ttk.Label(f, textvariable=self.stats_var,
                  foreground="#667").pack(anchor="w")

    def _build_mode_row(self):
        f = ttk.LabelFrame(self, text="All-day default mode", padding=10)
        f.pack(fill="x", padx=12, pady=(0, 8))
        ttk.Button(f, text="Blacklist", command=lambda: self._set_mode(BLACKLIST)).pack(side="left", expand=True, fill="x", padx=3)
        ttk.Button(f, text="Whitelist", command=lambda: self._set_mode(WHITELIST)).pack(side="left", expand=True, fill="x", padx=3)
        ttk.Button(f, text="Off", command=lambda: self._set_mode(OFF)).pack(side="left", expand=True, fill="x", padx=3)

    def _build_focus_box(self):
        f = ttk.LabelFrame(self, text="Focus session", padding=10)
        f.pack(fill="x", padx=12, pady=(0, 8))

        # Quick presets: a preset only pre-fills the composer below (mode, locked
        # and a default duration) — the duration stays adjustable before Start.
        presets = control.list_presets()
        if presets:
            prow = ttk.Frame(f); prow.pack(fill="x", pady=(0, 8))
            ttk.Label(prow, text="Presets:").pack(side="left", padx=(0, 6))
            for p in presets:
                lock = " 🔒" if p.get("locked") else ""
                label = f"{p.get('name', '')} · {p.get('default_minutes', '?')}m{lock}"
                # p=p binds the current preset (avoids the late-binding closure bug).
                ttk.Button(prow, text=label,
                           command=lambda p=p: self._apply_preset(p)).pack(side="left", padx=2)

        row = ttk.Frame(f); row.pack(fill="x")
        ttk.Label(row, text="Minutes:").pack(side="left")
        self.minutes_var = tk.StringVar(value="90")
        ttk.Entry(row, textvariable=self.minutes_var, width=6).pack(side="left", padx=(4, 12))

        self.session_mode_var = tk.StringVar(value=WHITELIST)
        ttk.Radiobutton(row, text="Whitelist", variable=self.session_mode_var, value=WHITELIST).pack(side="left")
        ttk.Radiobutton(row, text="Blacklist", variable=self.session_mode_var, value=BLACKLIST).pack(side="left", padx=(6, 12))

        self.locked_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(row, text="🔒 Locked", variable=self.locked_var).pack(side="left")

        row2 = ttk.Frame(f); row2.pack(fill="x", pady=(8, 0))
        ttk.Button(row2, text="Start focus", command=self._start_focus).pack(side="left", expand=True, fill="x", padx=3)
        ttk.Button(row2, text="+15 min", command=lambda: self._extend(15)).pack(side="left", padx=3)
        ttk.Button(row2, text="Stop", command=self._stop_focus).pack(side="left", expand=True, fill="x", padx=3)

    def _build_autostart_box(self):
        f = ttk.LabelFrame(self, text="Start with the computer", padding=10)
        f.pack(fill="x", padx=12, pady=(0, 8))

        row = ttk.Frame(f); row.pack(fill="x")
        self.auto_enabled_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(row, text="Block at every boot for",
                        variable=self.auto_enabled_var).pack(side="left")
        self.auto_minutes_var = tk.StringVar(value="300")
        ttk.Entry(row, textvariable=self.auto_minutes_var, width=5).pack(side="left", padx=4)
        ttk.Label(row, text="min").pack(side="left", padx=(0, 10))

        self.auto_mode_var = tk.StringVar(value=BLACKLIST)
        ttk.Radiobutton(row, text="Blacklist", variable=self.auto_mode_var,
                        value=BLACKLIST).pack(side="left")
        ttk.Radiobutton(row, text="Whitelist", variable=self.auto_mode_var,
                        value=WHITELIST).pack(side="left", padx=(4, 10))
        self.auto_locked_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(row, text="🔒 Locked",
                        variable=self.auto_locked_var).pack(side="left")
        ttk.Button(row, text="Save", command=self._save_autostart).pack(side="right")

        row2 = ttk.Frame(f); row2.pack(fill="x", pady=(8, 0))
        self.service_var = tk.StringVar(value="…")
        ttk.Label(row2, textvariable=self.service_var,
                  foreground="#667").pack(side="left")
        self.service_btn = ttk.Button(row2, text="Enable at boot",
                                      command=self._enable_service)
        self.service_btn.pack(side="left", padx=8)

        self.gui_auto_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(row2, text="Open this app at login",
                        variable=self.gui_auto_var,
                        command=self._toggle_gui_autostart).pack(side="right")

    def _build_lists(self):
        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=12, pady=(0, 8))
        self.block_list = self._make_list_tab(nb, "Blacklist", "block")
        self.allow_list = self._make_list_tab(nb, "Whitelist", "allow")

    def _make_list_tab(self, nb, title, which):
        frame = ttk.Frame(nb, padding=8)
        nb.add(frame, text=title)
        lb = tk.Listbox(frame, height=8)
        lb.pack(fill="both", expand=True, side="left")
        sb = ttk.Scrollbar(frame, command=lb.yview)
        sb.pack(side="left", fill="y")
        lb.config(yscrollcommand=sb.set)

        btns = ttk.Frame(frame, padding=(8, 0))
        btns.pack(side="left", fill="y")
        ttk.Button(btns, text="Add", command=lambda: self._add_domain(which)).pack(fill="x", pady=2)
        ttk.Button(btns, text="Remove", command=lambda: self._remove_domain(which, lb)).pack(fill="x", pady=2)
        return lb

    def _build_footer(self):
        f = ttk.Frame(self, padding=(12, 0, 12, 10))
        f.pack(fill="x")
        ttk.Button(f, text="Refresh", command=self._refresh).pack(side="right")

    # ---- actions ----
    def _apply_preset(self, p):
        """Pre-fill the composer from a preset; the user still presses Start."""
        self.minutes_var.set(str(p.get("default_minutes", 25)))
        self.session_mode_var.set(p.get("mode", WHITELIST))
        self.locked_var.set(bool(p.get("locked", False)))

    def _set_mode(self, mode):
        self._do(lambda: control.set_default_mode(mode), ["mode", mode])

    def _start_focus(self):
        try:
            minutes = int(self.minutes_var.get())
        except ValueError:
            messagebox.showerror("Invalid", "Minutes must be a number.")
            return
        mode = self.session_mode_var.get()
        locked = self.locked_var.get()
        if locked and not messagebox.askyesno(
                "Locked session",
                f"Start a LOCKED {mode} session for {minutes} min?\n\n"
                "It cannot be stopped until the timer ends."):
            return
        args = ["focus", str(minutes)]
        args += ["--blacklist"] if mode == BLACKLIST else ["--whitelist"]
        if locked:
            args.append("--locked")
        self._do(lambda: control.start_session(minutes, mode=mode, locked=locked), args)

    def _stop_focus(self):
        st = control.status()
        was_boot = st["session_active"] and st["session_source"] == config.BOOT
        self._do(control.stop_session, ["stop"])
        # Stopping a session only drops you back to the all-day default, which
        # ships as blacklist — people expect "stop" to mean "unblock", so say so.
        after = control.status()
        if was_boot and not after["session_active"] and after["default_mode"] != OFF:
            messagebox.showinfo(
                "Boot block stopped",
                f"You are back on your all-day default mode "
                f"({after['default_mode']}), so those sites are still blocked.\n\n"
                f"Press 'Off' above if you want everything unblocked.")

    def _extend(self, m):
        self._do(lambda: control.extend_session(m), ["extend", str(m)])

    def _add_domain(self, which):
        d = simpledialog.askstring("Add domain", "Domain (e.g. reddit.com):", parent=self)
        if not d:
            return
        fn = control.add_to_blocklist if which == "block" else control.add_to_whitelist
        self._do(lambda: fn([d]), [which, "add", d])

    def _remove_domain(self, which, lb):
        sel = lb.curselection()
        if not sel:
            return
        d = lb.get(sel[0])
        fn = control.remove_from_blocklist if which == "block" else control.remove_from_whitelist
        self._do(lambda: fn([d]), [which, "remove", d])

    def _refresh(self):
        self._do(control.refresh, ["refresh"])

    # ---- autostart actions ----
    def _save_autostart(self):
        try:
            minutes = int(self.auto_minutes_var.get())
        except ValueError:
            messagebox.showerror("Invalid", "Boot block minutes must be a number.")
            return
        enabled = self.auto_enabled_var.get()
        mode = self.auto_mode_var.get()
        locked = self.auto_locked_var.get()
        if enabled and locked and not messagebox.askyesno(
                "Locked boot block",
                f"Every boot will start a LOCKED {mode} block for {minutes} min.\n\n"
                "You will not be able to stop it from this window until the "
                "timer ends. Continue?"):
            return
        args = ["autostart", "--session", "on" if enabled else "off",
                "--minutes", str(minutes),
                "--blacklist" if mode == BLACKLIST else "--whitelist",
                "--locked" if locked else "--unlocked"]
        self._do(lambda: control.set_autostart(enabled=enabled, minutes=minutes,
                                               mode=mode, locked=locked), args)
        self._render_autostart()

    def _enable_service(self):
        on = control.service_enabled() is not True
        self._do(lambda: control.set_service_enabled(on),
                 ["autostart", "--service", "on" if on else "off"])
        self._render_autostart()

    def _toggle_gui_autostart(self):
        # No elevation: this writes the user's own ~/.config/autostart entry.
        try:
            control.set_gui_autostart(self.gui_auto_var.get())
        except OSError as e:
            messagebox.showerror("Could not write the login entry", str(e))
        self._render_autostart()

    def _do(self, fn, cli_args=None):
        """Apply a change: directly when we have root, else via `pkexec` on the CLI."""
        try:
            if cli_args is not None and _needs_pkexec():
                _root_cli(cli_args)
            else:
                fn()
        except LockedError as e:
            messagebox.showinfo("Locked", str(e))
        except PermissionError:
            messagebox.showerror("Permission denied",
                                 "Editing /etc/hosts needs root. Relaunch with sudo.")
        except (ValueError, RuntimeError) as e:
            messagebox.showerror("Error", str(e))
        self._render_status()
        self._render_lists()

    # ---- render / tick ----
    def _render_status(self):
        st = control.status()
        lock = "  🔒 LOCKED" if st["locked"] else ""
        self.status_var.set(f"Now enforcing: {st['effective_mode'].upper()}{lock}"
                            f"    (default: {st['default_mode']})")
        if st["session_active"]:
            kind = ("Boot block" if st["session_source"] == config.BOOT
                    else "Focus session")
            self.session_var.set(f"{kind} ({st['session_mode']}): "
                                 f"{_countdown(st['session_remaining'])} remaining")
        else:
            self.session_var.set("No focus session running")
        self.stats_var.set(
            f"Blocked now: {st['blocked_now']} sites   ·   "
            f"Focused today: {st['focused_today_min']} min   ·   "
            f"Streak: {st['streak_days']} day(s)")

    def _render_autostart(self):
        """Reload the autostart panel from disk.

        Called on open and after a change — never from the 1s tick: it shells
        out to systemctl, and it would overwrite fields mid-edit.
        """
        st = control.status()
        self.auto_enabled_var.set(st["autostart_enabled"])
        self.auto_minutes_var.set(str(st["autostart_minutes"]))
        self.auto_mode_var.set(st["autostart_mode"])
        self.auto_locked_var.set(st["autostart_locked"])

        svc = control.service_enabled()
        if svc:
            self.service_var.set("Daemon at boot: enabled")
            self.service_btn.config(text="Disable at boot")
        elif svc is False:
            self.service_var.set("Daemon at boot: disabled — the block will not arm")
            self.service_btn.config(text="Enable at boot")
        else:
            self.service_var.set("Daemon at boot: not installed (run sudo ./install.sh)")
            self.service_btn.config(text="Enable at boot")

        self.gui_auto_var.set(autostart.enabled())

    def _render_lists(self):
        state = config.load_state()
        for lb, items in ((self.block_list, state.blocklist),
                          (self.allow_list, state.whitelist)):
            lb.delete(0, tk.END)
            for d in items:
                lb.insert(tk.END, d)

    def _tick(self):
        # Only the status/countdown refreshes every second; the lists are left
        # alone so a user's selection isn't wiped out mid-edit.
        self._render_status()
        self.after(1000, self._tick)


def main():
    App().mainloop()


if __name__ == "__main__":
    main()
