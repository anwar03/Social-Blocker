"""Tkinter GUI for SocialBlocker (standard library only).

Run it as your normal user:
    socialblocker gui       # or: python3 -m socialblocker.gui

Editing /etc/hosts needs root, but this window does not run as root. Reading
status needs no privileges, and every change is applied by elevating one short
`socialblocker` CLI command through pkexec. Keeping a long-lived GUI process
unprivileged is the whole point — least privilege, and no DISPLAY/XAUTHORITY
juggling. Launching the whole app with `sudo -E` still works and then skips
pkexec entirely.

The look is the "Mist" direction from SocialBlocker-Mist-Desktop.html. All of
its colours, fonts and generated art live in `mistkit.py`; this module only
decides *what* to show and calls `control.py` to change anything.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog

from . import autostart, config, control, mistkit as mk
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


# --- hero copy -------------------------------------------------------------

def _hero_copy(st: dict) -> tuple:
    """(eyebrow, headline, explanation) for the current state.

    Presentation only — it reads `control.status()` and decides nothing.
    """
    if st["session_active"]:
        boot = st["session_source"] == config.BOOT
        eyebrow = "Boot block" if boot else "Focus session"
        if st["session_mode"] == WHITELIST:
            return (eyebrow, "Deep focus.",
                    "Everything in the distraction set is blocked except the "
                    "sites on your allow-list.")
        return (eyebrow, "Distractions are off.",
                "Your blacklist is enforced until the timer runs out.")
    if st["default_mode"] == OFF:
        return ("All-day default", "Everything is open.",
                "No rules are being enforced. Pick a mode below, or start a "
                "focus session when you need one.")
    if st["default_mode"] == WHITELIST:
        return ("All-day default", "Only your allow-list.",
                "Everything in the distraction set is blocked except the "
                "sites you explicitly allow.")
    return ("All-day default", "Distractions are blocked.",
            "Your blacklist is enforced all day — the rest of the web stays open.")


MODE_DESC = {
    BLACKLIST: "Blocks the sites on your blacklist. Everything else is reachable.",
    WHITELIST: "Blocks the whole distraction set except your allow-list. "
               "/etc/hosts cannot express \"allow only X\", so this is the "
               "honest approximation.",
    OFF: "Nothing is blocked. The fenced region in /etc/hosts is left empty.",
}


# --- small composite widgets ----------------------------------------------

class Segment(tk.Frame):
    """The mockup's segmented control: buttons in a sunk track, selected white."""

    def __init__(self, parent, options, command, background=mk.SUNK):
        super().__init__(parent, background=background,
                         highlightbackground=mk.LINE_SOFT,
                         highlightcolor=mk.LINE_SOFT, highlightthickness=1, bd=0)
        self.buttons = {}
        for value, label in options:
            b = ttk.Button(self, text=label, style="Seg.TButton",
                           command=lambda v=value: command(v))
            b.pack(side="left", expand=True, fill="x", padx=2, pady=2)
            self.buttons[value] = b

    def select(self, value) -> None:
        for v, b in self.buttons.items():
            b.configure(style="SegOn.TButton" if v == value else "Seg.TButton")


def card_label(parent, text, hint=None):
    """The uppercase card heading, with an optional right-aligned hint."""
    row = tk.Frame(parent, background=mk.CARD)
    row.pack(fill="x", pady=(0, 12))
    ttk.Label(row, text=mk.track(text.upper()),
              style="Eyebrow.Card.TLabel").pack(side="left")
    if hint:
        ttk.Label(row, text=hint, style="Faint.Card.TLabel").pack(side="right")
    return row


class Composer(tk.Frame):
    """The focus-session composer card: duration, mode, lock, Start.

    Owns its own input state and turns it into exactly one use-case call.
    `run` is the caller's elevate-and-apply helper.
    """

    def __init__(self, parent, fonts, run):
        super().__init__(parent, **mk.card_options())
        self._run = run
        self.minutes = tk.StringVar(value="90")
        self.mode = tk.StringVar(value=WHITELIST)
        self.locked = tk.BooleanVar(value=False)
        card_label(self, "Focus session")
        self._build_stepper()
        self._build_chips()
        self.seg = Segment(self, ((WHITELIST, "Whitelist"), (BLACKLIST, "Blacklist")),
                           self.set_mode, background=mk.CARD)
        self.seg.pack(fill="x", pady=(0, 12))
        self.seg.select(WHITELIST)
        self._build_lock()
        ttk.Button(self, text="Start focus session", style="Primary.TButton",
                   command=self.start).pack(fill="x")

    def _build_stepper(self) -> None:
        row = tk.Frame(self, background=mk.CARD)
        row.pack(fill="x", pady=(0, 10))
        ttk.Label(row, text="Duration", style="Muted.Card.TLabel").pack(side="left")
        track = tk.Frame(row, background=mk.SUNK, highlightbackground=mk.LINE_SOFT,
                         highlightthickness=1, bd=0)
        track.pack(side="right")
        ttk.Button(track, text="−", width=2, style="Step.TButton",
                   command=lambda: self._nudge(-5)).pack(side="left", padx=3, pady=3)
        ttk.Entry(track, textvariable=self.minutes, width=4,
                  justify="center").pack(side="left")
        ttk.Button(track, text="+", width=2, style="Step.TButton",
                   command=lambda: self._nudge(5)).pack(side="left", padx=3, pady=3)

    def _build_chips(self) -> None:
        row = tk.Frame(self, background=mk.CARD)
        row.pack(fill="x", pady=(0, 12))
        for minutes in (25, 45, 90, 120):
            ttk.Button(row, text=f"{minutes}m", style="Chip.TButton",
                       command=lambda m=minutes: self.minutes.set(str(m))
                       ).pack(side="left", expand=True, fill="x", padx=2)

    def _build_lock(self) -> None:
        row = tk.Frame(self, background=mk.CARD)
        row.pack(fill="x", pady=(0, 14))
        ttk.Checkbutton(row, text="🔒 Locked", variable=self.locked,
                        style="Lock.Card.TCheckbutton").pack(side="left")
        ttk.Label(row, text="can't stop early",
                  style="Faint.Card.TLabel").pack(side="left", padx=8)

    def _nudge(self, delta: int) -> None:
        try:
            current = int(self.minutes.get())
        except ValueError:
            current = 90
        self.minutes.set(str(max(5, current + delta)))

    def set_mode(self, mode: str) -> None:
        self.mode.set(mode)
        self.seg.select(mode)

    def apply_preset(self, p: dict) -> None:
        """Pre-fill from a preset; the user still presses Start."""
        self.minutes.set(str(p.get("default_minutes", 25)))
        self.set_mode(p.get("mode", WHITELIST))
        self.locked.set(bool(p.get("locked", False)))

    def start(self) -> None:
        try:
            minutes = int(self.minutes.get())
        except ValueError:
            messagebox.showerror("Invalid", "Minutes must be a number.")
            return
        mode, locked = self.mode.get(), self.locked.get()
        if locked and not messagebox.askyesno(
                "Locked session",
                f"Start a LOCKED {mode} session for {minutes} min?\n\n"
                "It cannot be stopped until the timer ends."):
            return
        args = ["focus", str(minutes)]
        args += ["--blacklist"] if mode == BLACKLIST else ["--whitelist"]
        if locked:
            args.append("--locked")
        self._run(lambda: control.start_session(minutes, mode=mode, locked=locked), args)


class StatusPill(tk.Frame):
    """Title-bar state chip: a coloured dot plus one word."""

    def __init__(self, parent, fonts):
        super().__init__(parent, background=mk.WHITE, bd=0,
                         highlightbackground=mk.LINE, highlightcolor=mk.LINE,
                         highlightthickness=1, padx=10, pady=4)
        self._dot = tk.Canvas(self, width=9, height=9, background=mk.WHITE,
                              highlightthickness=0, bd=0)
        self._blob = self._dot.create_oval(0, 0, 8, 8, outline="", fill=mk.TEAL)
        self._dot.pack(side="left", padx=(0, 7))
        self._text = tk.StringVar(value="…")
        tk.Label(self, textvariable=self._text, background=mk.WHITE,
                 foreground=mk.PINE, font=fonts.small_bold).pack(side="left")

    def render(self, st: dict) -> None:
        if st["locked"]:
            label, colour = "Locked", mk.AMBER
        elif st["session_active"]:
            label, colour = "Focusing", mk.TEAL
        elif st["effective_mode"] == OFF:
            label, colour = "Off", mk.SLATE_2
        else:
            label, colour = st["effective_mode"].title(), mk.TEAL
        self._text.set(label)
        self._dot.itemconfigure(self._blob, fill=colour)


class Scroller(tk.Frame):
    """A vertically scrollable body.

    The full Mist layout is taller than a 768px laptop screen, so the window
    stays usable by scrolling rather than by cutting sections.
    """

    def __init__(self, parent):
        super().__init__(parent, background=mk.SUNK)
        self.canvas = tk.Canvas(self, background=mk.SUNK, highlightthickness=0, bd=0)
        bar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=bar.set)
        bar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.inner = tk.Frame(self.canvas, background=mk.SUNK)
        self._win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", lambda e: self.canvas.configure(
            scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(
            self._win, width=e.width))
        for seq in ("<Button-4>", "<Button-5>", "<MouseWheel>"):
            self.canvas.bind_all(seq, self._on_wheel)
        # Building the page leaves the view wherever the last child landed
        # (measured: 0.127 down, i.e. the bottom). A page opens at the top.
        self.after_idle(lambda: self.canvas.yview_moveto(0.0))

    def _on_wheel(self, event) -> None:
        # Leave the domain lists their own wheel; only the page scrolls here.
        if isinstance(event.widget, tk.Listbox):
            return
        up = getattr(event, "num", 0) == 4 or getattr(event, "delta", 0) > 0
        self.canvas.yview_scroll(-1 if up else 1, "units")


class Hero(tk.Canvas):
    """The status hero: fog field, headline, and the countdown ring.

    A single canvas because Tk cannot stack widgets over a background image —
    text and the live buttons are canvas items placed on the generated art.
    """

    HEIGHT = 186
    RING = 128
    PAD = 26
    RADIUS = 8          # at half-resolution, so 16px once zoomed back up

    def __init__(self, parent, fonts, on_extend, on_stop):
        super().__init__(parent, height=self.HEIGHT, background=mk.SUNK,
                         highlightthickness=0, bd=0)
        self.fonts = fonts
        self._fog = mk.Fog(900, self.HEIGHT, mk.Fog.PANEL_TOP, mk.Fog.PANEL_BOT)
        self._art = mk.RingArt(self._fog, self.RING)
        self._bg_photo = None            # both kept alive; Tk does not own images
        self._ring_photo = None
        self._origin = (0, 0)
        self._width = 0
        self._resize_job = None
        self._st = None
        self._build(on_extend, on_stop)
        self.bind("<Configure>", self._reflow)

    def _build(self, on_extend, on_stop) -> None:
        f, pad = self.fonts, self.PAD
        self.create_image(0, 0, anchor="nw", image=self._bg_photo, tags="bg")
        self._eyebrow = self.create_text(pad, 28, anchor="w", fill=mk.SLATE,
                                         font=f.eyebrow)
        self._lock = self.create_text(pad, 28, anchor="w", fill=mk.AMBER,
                                      font=f.eyebrow, text=mk.track("LOCKED"))
        self._title = self.create_text(pad, 64, anchor="w", fill=mk.PINE, font=f.h1)
        self._sub = self.create_text(pad, 96, anchor="nw", fill=mk.SLATE,
                                     font=f.small, width=380)
        self._ring = self.create_image(0, 0, anchor="nw")
        self._value = self.create_text(0, 0, fill=mk.PINE, font=f.ring)
        self._cap = self.create_text(0, 0, fill=mk.SLATE, font=f.eyebrow)
        self._extend_btn = ttk.Button(self, text="+15 min", style="Ghost.TButton",
                                      command=on_extend)
        self._stop_btn = ttk.Button(self, text="Stop", style="Danger.TButton",
                                    command=on_stop)
        self._extend = self.create_window(pad, 150, anchor="w",
                                          window=self._extend_btn)
        self._stop = self.create_window(pad, 150, anchor="w", window=self._stop_btn)

    def _reflow(self, event=None) -> None:
        """Right-align the ring and keep the fog matched to the real width.

        The field is a function of width, and the ring cuts its backdrop out
        of that field, so a resize invalidates both. Regenerating costs ~160ms,
        so a drag is debounced — but the first layout paints immediately, or
        the window would open showing bare canvas.
        """
        width = max(400, self.winfo_width())
        if width != self._width:
            first, self._width = self._width == 0, width
            if self._resize_job is not None:
                self.after_cancel(self._resize_job)
            self._resize_job = None
            if first:
                self._repaint_field()
            else:
                self._resize_job = self.after(220, self._repaint_field)
        x = max(self.PAD, width - self.PAD - self.RING)
        y = (self.HEIGHT - self.RING) // 2
        self._origin = (x, y)
        self.coords(self._ring, x, y)
        self.coords(self._value, x + self.RING / 2, y + self.RING / 2 - 8)
        self.coords(self._cap, x + self.RING / 2, y + self.RING / 2 + 18)
        self.itemconfigure(self._sub, width=max(200, x - self.PAD - 24))
        # Measured, not guessed: the button's width depends on the resolved
        # font, so a hard-coded offset collides on some systems.
        self.coords(self._stop, self.PAD + self._extend_btn.winfo_reqwidth() + 10, 150)

    def _repaint_field(self) -> None:
        """Re-render the fog at the current width, with rounded corners.

        Half resolution then `zoom(2)`: the field is smooth everywhere, so
        nothing visible is lost and it is 4x cheaper. The corners are cut to
        the page colour, which is how a Tk widget gets a border-radius at all.
        """
        self._resize_job = None
        self._fog = mk.Fog(self._width, self.HEIGHT,
                           mk.Fog.PANEL_TOP, mk.Fog.PANEL_BOT)
        field = self._fog.raster(0, 0, self._width, self.HEIGHT, step=2)
        field.round_corners(self.RADIUS, mk.FOG_TOP_RGB)
        self._bg_photo = field.photo().zoom(2)
        self.itemconfigure("bg", image=self._bg_photo)
        self._art = mk.RingArt(self._fog, self.RING)    # its backdrop moved
        if self._st is not None:
            self._render_ring(self._st)

    def render(self, st: dict) -> None:
        self._st = st
        eyebrow, title, sub = _hero_copy(st)
        self.itemconfigure(self._eyebrow, text=mk.track(eyebrow.upper()))
        self.itemconfigure(self._title, text=title)
        self.itemconfigure(self._sub, text=sub)
        self._place_lock(eyebrow, st["locked"])
        self._render_ring(st)
        live = "normal" if st["session_active"] else "hidden"
        self.itemconfigure(self._extend, state=live)
        self.itemconfigure(self._stop, state=live)

    def _place_lock(self, eyebrow: str, locked: bool) -> None:
        if not locked:
            self.itemconfigure(self._lock, state="hidden")
            return
        self.itemconfigure(self._lock, state="normal")
        self.coords(self._lock, self.bbox(self._eyebrow)[2] + 14, 28)

    def _render_ring(self, st: dict) -> None:
        total = st["session_total"]
        frac = 1.0 - st["session_remaining"] / total if total > 0 else 0.0
        key = self._art.key(frac, st["locked"], self._origin)
        self._ring_photo = self._art.image(key)
        self.itemconfigure(self._ring, image=self._ring_photo)
        if st["session_active"]:
            self.itemconfigure(self._value, text=_countdown(st["session_remaining"]))
            self.itemconfigure(self._cap, text=mk.track("LEFT"))
        else:
            self.itemconfigure(self._value, text=str(st["blocked_now"]))
            self.itemconfigure(self._cap, text=mk.track("BLOCKED"))


class StartupPanel(tk.Frame):
    """The "start with the computer" settings, as a tab.

    `run` is the caller's elevate-and-apply helper — this panel never talks to
    pkexec itself.
    """

    def __init__(self, parent, fonts, run):
        super().__init__(parent, background=mk.CARD, padx=16, pady=14)
        self._run = run
        self.enabled = tk.BooleanVar(value=False)
        self.minutes = tk.StringVar(value="300")
        self.mode = tk.StringVar(value=BLACKLIST)
        self.locked = tk.BooleanVar(value=False)
        self.gui_auto = tk.BooleanVar(value=False)
        self.service = tk.StringVar(value="…")
        self._build(fonts)

    def _build(self, fonts) -> None:
        row = tk.Frame(self, background=mk.CARD)
        row.pack(fill="x")
        ttk.Checkbutton(row, text="Block at every boot for", variable=self.enabled,
                        style="Card.TCheckbutton").pack(side="left")
        ttk.Entry(row, textvariable=self.minutes, width=5,
                  justify="center").pack(side="left", padx=6)
        ttk.Label(row, text="min", style="Muted.Card.TLabel").pack(side="left")
        ttk.Button(row, text="Save", style="Primary.TButton",
                   command=self._save).pack(side="right")

        row2 = tk.Frame(self, background=mk.CARD)
        row2.pack(fill="x", pady=(12, 0))
        for value, label in ((BLACKLIST, "Blacklist"), (WHITELIST, "Whitelist")):
            ttk.Radiobutton(row2, text=label, value=value, variable=self.mode,
                            style="Card.TRadiobutton").pack(side="left", padx=(0, 14))
        ttk.Checkbutton(row2, text="🔒 Locked", variable=self.locked,
                        style="Lock.Card.TCheckbutton").pack(side="left")

        row3 = tk.Frame(self, background=mk.CARD)
        row3.pack(fill="x", pady=(16, 0))
        ttk.Label(row3, textvariable=self.service,
                  style="Muted.Card.TLabel").pack(side="left")
        self.service_btn = ttk.Button(row3, text="Enable at boot",
                                      style="Ghost.TButton", command=self._toggle_service)
        self.service_btn.pack(side="left", padx=10)
        ttk.Checkbutton(row3, text="Open this app at login", variable=self.gui_auto,
                        style="Card.TCheckbutton",
                        command=self._toggle_gui).pack(side="right")

    def _save(self) -> None:
        try:
            minutes = int(self.minutes.get())
        except ValueError:
            messagebox.showerror("Invalid", "Boot block minutes must be a number.")
            return
        enabled, mode, locked = self.enabled.get(), self.mode.get(), self.locked.get()
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
        self._run(lambda: control.set_autostart(enabled=enabled, minutes=minutes,
                                                mode=mode, locked=locked), args)
        self.render()

    def _toggle_service(self) -> None:
        on = control.service_enabled() is not True
        self._run(lambda: control.set_service_enabled(on),
                  ["autostart", "--service", "on" if on else "off"])
        self.render()

    def _toggle_gui(self) -> None:
        # No elevation: this writes the user's own ~/.config/autostart entry.
        try:
            control.set_gui_autostart(self.gui_auto.get())
        except OSError as e:
            messagebox.showerror("Could not write the login entry", str(e))
        self.render()

    def render(self) -> None:
        """Reload from disk. Never called from the tick — it shells out to
        systemctl, and it would overwrite fields mid-edit."""
        st = control.status()
        self.enabled.set(st["autostart_enabled"])
        self.minutes.set(str(st["autostart_minutes"]))
        self.mode.set(st["autostart_mode"])
        self.locked.set(st["autostart_locked"])
        svc = control.service_enabled()
        if svc:
            self.service.set("Daemon at boot: enabled")
            self.service_btn.configure(text="Disable at boot")
        elif svc is False:
            self.service.set("Daemon at boot: disabled — the block will not arm")
            self.service_btn.configure(text="Enable at boot")
        else:
            self.service.set("Daemon at boot: not installed (run sudo ./install.sh)")
            self.service_btn.configure(text="Enable at boot")
        self.gui_auto.set(autostart.enabled())


class App(tk.Tk):

    STATS_EVERY = 10        # ticks between the (more expensive) stats refresh

    def __init__(self):
        super().__init__()
        self.title("SocialBlocker")
        self.fonts = mk.apply_theme(self)
        self._size_window()
        self._ticks = 0

        self._build_topbar()
        body = Scroller(self)
        body.pack(fill="both", expand=True)
        self._build_body(body.inner)

        # Unprivileged is the normal case now (pkexec elevates each change), so
        # only warn when there is no way to elevate at all.
        if _needs_pkexec() and not shutil.which("pkexec"):
            self.after(300, lambda: messagebox.showwarning(
                "Cannot apply changes",
                "Changes edit /etc/hosts, which needs admin rights, and pkexec "
                "is not installed.\n\nInstall policykit-1, or relaunch with:\n"
                "  sudo -E socialblocker gui"))

        self._render_lists()
        self.startup.render()
        self._tick()

    def _size_window(self) -> None:
        """Fit the screen rather than assuming a desktop-sized one."""
        height = min(900, self.winfo_screenheight() - 120)
        self.geometry(f"900x{height}")
        self.minsize(820, 460)

    # ---- layout ----
    def _build_topbar(self) -> None:
        bar = tk.Frame(self, background=mk.CARD, padx=18, pady=11,
                       highlightbackground=mk.LINE_SOFT, highlightthickness=1, bd=0)
        bar.pack(fill="x")
        self._mark = mk.mark_image(26, mk.CARD_RGB)
        tk.Label(bar, image=self._mark, background=mk.CARD).pack(side="left")
        tk.Label(bar, text="Social", background=mk.CARD, foreground=mk.PINE,
                 font=self.fonts.ui_bold).pack(side="left", padx=(10, 0))
        tk.Label(bar, text="Blocker", background=mk.CARD, foreground=mk.TEAL_DEEP,
                 font=self.fonts.mark).pack(side="left")
        ttk.Button(bar, text="Refresh", style="Ghost.TButton",
                   command=self._refresh).pack(side="right")
        self.pill = StatusPill(bar, self.fonts)
        self.pill.pack(side="right", padx=12)

    def _build_body(self, parent) -> None:
        parent.configure(padx=18, pady=16)
        self.hero = Hero(parent, self.fonts, lambda: self._extend(15), self._stop_focus)
        self.hero.pack(fill="x")
        self._build_mode_card(parent)
        columns = tk.Frame(parent, background=mk.SUNK)
        columns.pack(fill="x", pady=(14, 0))
        columns.columnconfigure(0, weight=1, uniform="col")
        columns.columnconfigure(1, weight=1, uniform="col")
        self.composer = Composer(columns, self.fonts, self._do)
        self.composer.grid(row=0, column=1, sticky="nsew", padx=(7, 0))
        self._build_presets(columns)      # after the composer: presets fill it
        self._build_stats(parent)
        self._build_tabs(parent)

    def _build_mode_card(self, parent) -> None:
        card = mk.card(parent)
        card.pack(fill="x", pady=(14, 0))
        card_label(card, "All-day default mode",
                   "what runs when no focus session is active")
        self.mode_seg = Segment(card, ((BLACKLIST, "Blacklist"),
                                       (WHITELIST, "Whitelist"),
                                       (OFF, "Off")), self._set_mode)
        self.mode_seg.pack(fill="x")
        self.mode_desc = tk.StringVar(value="")
        ttk.Label(card, textvariable=self.mode_desc, style="Muted.Card.TLabel",
                  wraplength=760, justify="left").pack(fill="x", pady=(11, 0))

    def _build_presets(self, parent) -> None:
        card = mk.card(parent)
        card.grid(row=0, column=0, sticky="nsew", padx=(0, 7))
        card_label(card, "Quick presets", "pre-fills the composer")
        presets = control.list_presets()
        if not presets:
            ttk.Label(card, text="No presets in data/presets.json.",
                      style="Muted.Card.TLabel").pack(anchor="w")
            return
        for p in presets:
            lock = "  🔒" if p.get("locked") else ""
            label = (f"{p.get('name', '')}\n{p.get('default_minutes', '?')} min · "
                     f"{p.get('mode', WHITELIST)}{lock}")
            # p=p binds the current preset (avoids the late-binding closure bug).
            ttk.Button(card, text=label, style="Preset.TButton",
                       command=lambda p=p: self.composer.apply_preset(p)
                       ).pack(fill="x", pady=3)

    def _build_stats(self, parent) -> None:
        row = tk.Frame(parent, background=mk.SUNK)
        row.pack(fill="x", pady=(14, 0))
        self.stat_vars = {}
        specs = (("focused_today_min", "Focused today", "min"),
                 ("blocked_now", "Blocked now", "sites"),
                 ("streak_days", "Streak", "days"))
        for i, (key, title, unit) in enumerate(specs):
            row.columnconfigure(i, weight=1, uniform="stat")
            card = mk.card(row, pad=13)
            card.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 7,
                                                            0 if i == 2 else 7))
            ttk.Label(card, text=mk.track(title.upper()),
                      style="Eyebrow.Card.TLabel").pack(anchor="w")
            value = tk.Frame(card, background=mk.CARD)
            value.pack(anchor="w", pady=(8, 0))
            var = tk.StringVar(value="—")
            ttk.Label(value, textvariable=var,
                      style="Numeral.Card.TLabel").pack(side="left")
            ttk.Label(value, text=unit, style="Unit.Card.TLabel").pack(side="left",
                                                                      padx=(5, 0))
            self.stat_vars[key] = var

    def _build_tabs(self, parent) -> None:
        nb = ttk.Notebook(parent)
        nb.pack(fill="both", expand=True, pady=(14, 0))
        self.block_list = self._make_list_tab(nb, "Blacklist", "block")
        self.allow_list = self._make_list_tab(nb, "Whitelist", "allow")
        self.startup = StartupPanel(nb, self.fonts, self._do)
        nb.add(self.startup, text="Startup")

    def _make_list_tab(self, nb, title, which):
        frame = tk.Frame(nb, background=mk.CARD, padx=14, pady=14)
        nb.add(frame, text=title)
        lb = tk.Listbox(frame, height=7)
        mk.style_listbox(lb, self.fonts)
        lb.pack(fill="both", expand=True, side="left")
        sb = ttk.Scrollbar(frame, command=lb.yview)
        sb.pack(side="left", fill="y", padx=(2, 0))
        lb.config(yscrollcommand=sb.set)

        btns = tk.Frame(frame, background=mk.CARD, padx=12)
        btns.pack(side="left", fill="y")
        ttk.Button(btns, text="Add", style="Ghost.TButton",
                   command=lambda: self._add_domain(which)).pack(fill="x", pady=3)
        ttk.Button(btns, text="Remove", style="Ghost.TButton",
                   command=lambda: self._remove_domain(which, lb)).pack(fill="x", pady=3)
        return lb

    # ---- actions ----
    def _set_mode(self, mode) -> None:
        self._do(lambda: control.set_default_mode(mode), ["mode", mode])

    def _stop_focus(self) -> None:
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

    def _extend(self, m) -> None:
        self._do(lambda: control.extend_session(m), ["extend", str(m)])

    def _add_domain(self, which) -> None:
        d = simpledialog.askstring("Add domain", "Domain (e.g. reddit.com):", parent=self)
        if not d:
            return
        fn = control.add_to_blocklist if which == "block" else control.add_to_whitelist
        self._do(lambda: fn([d]), [which, "add", d])

    def _remove_domain(self, which, lb) -> None:
        sel = lb.curselection()
        if not sel:
            return
        d = lb.get(sel[0])
        fn = control.remove_from_blocklist if which == "block" else control.remove_from_whitelist
        self._do(lambda: fn([d]), [which, "remove", d])

    def _refresh(self) -> None:
        self._do(control.refresh, ["refresh"])

    def _do(self, fn, cli_args=None) -> None:
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
        st = control.status()
        self._render_status(st)
        self._render_stats(st)
        self._render_lists()

    # ---- render / tick ----
    def _render_status(self, st: dict) -> None:
        self.pill.render(st)
        self.hero.render(st)
        self.mode_seg.select(st["default_mode"])
        self.mode_desc.set(MODE_DESC.get(st["default_mode"], ""))

    def _render_stats(self, st: dict) -> None:
        for key, var in self.stat_vars.items():
            var.set(str(st[key]))

    def _render_lists(self) -> None:
        state = config.load_state()
        for lb, items in ((self.block_list, state.blocklist),
                          (self.allow_list, state.whitelist)):
            lb.delete(0, tk.END)
            for d in items:
                lb.insert(tk.END, d)

    def _tick(self) -> None:
        # The countdown needs 1 Hz; the stat tiles change at most once a minute,
        # and the lists are left alone so a selection isn't wiped out mid-edit.
        st = control.status()
        self._render_status(st)
        if self._ticks % self.STATS_EVERY == 0:
            self._render_stats(st)
        self._ticks += 1
        self.after(1000, self._tick)


def main():
    App().mainloop()


if __name__ == "__main__":
    main()
