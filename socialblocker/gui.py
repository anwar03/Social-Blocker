"""Tkinter GUI for SocialBlocker (standard library only).

Because it edits /etc/hosts, launch it with root, e.g.:
    sudo -E python3 -m socialblocker.gui
    # or, on a desktop:  pkexec env DISPLAY=$DISPLAY XAUTHORITY=$XAUTHORITY \\
    #                      python3 -m socialblocker.gui
"""

from __future__ import annotations

import os
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog

from . import config, control
from .config import BLACKLIST, WHITELIST, OFF
from .control import LockedError


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("SocialBlocker")
        self.geometry("560x520")
        self.minsize(520, 480)

        self._build_header()
        self._build_mode_row()
        self._build_focus_box()
        self._build_lists()
        self._build_footer()

        if os.geteuid() != 0 and str(config.HOSTS_FILE) == "/etc/hosts":
            self.after(300, lambda: messagebox.showwarning(
                "Not running as root",
                "Changes edit /etc/hosts and will fail without root.\n\n"
                "Relaunch with:\n  sudo -E python3 -m socialblocker.gui"))

        self._render_lists()
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
        self._do(lambda: control.set_default_mode(mode))

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
        self._do(lambda: control.start_session(minutes, mode=mode, locked=locked))

    def _stop_focus(self):
        self._do(control.stop_session)

    def _extend(self, m):
        self._do(lambda: control.extend_session(m))

    def _add_domain(self, which):
        d = simpledialog.askstring("Add domain", "Domain (e.g. reddit.com):", parent=self)
        if not d:
            return
        fn = control.add_to_blocklist if which == "block" else control.add_to_whitelist
        self._do(lambda: fn([d]))

    def _remove_domain(self, which, lb):
        sel = lb.curselection()
        if not sel:
            return
        d = lb.get(sel[0])
        fn = control.remove_from_blocklist if which == "block" else control.remove_from_whitelist
        self._do(lambda: fn([d]))

    def _refresh(self):
        self._do(control.refresh)

    def _do(self, fn):
        try:
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
            secs = st["session_remaining"]
            m, s = divmod(secs, 60)
            self.session_var.set(f"Focus session ({st['session_mode']}): "
                                 f"{m:02d}:{s:02d} remaining")
        else:
            self.session_var.set("No focus session running")
        self.stats_var.set(
            f"Blocked now: {st['blocked_now']} sites   ·   "
            f"Focused today: {st['focused_today_min']} min   ·   "
            f"Streak: {st['streak_days']} day(s)")

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
