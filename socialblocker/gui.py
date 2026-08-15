"""Tkinter GUI for SocialBlocker (standard library only).

Run it as your normal user:
    socialblocker gui       # or: python3 -m socialblocker.gui

Editing /etc/hosts needs root, but this window does not run as root. Reading
status needs no privileges, and every change is applied by elevating one short
`socialblocker` CLI command through pkexec. Keeping a long-lived GUI process
unprivileged is the whole point — least privilege, and no DISPLAY/XAUTHORITY
juggling. Launching the whole app with `sudo -E` still works and then skips
pkexec entirely.

The look is the "Mist" direction from SocialBlocker-Mist-Desktop.html, with
"Ink" as its dark sibling. Which of the two is showing is the desktop's
decision, followed live. All colours, fonts and generated art live in
`mistkit.py`; this module only decides *what* to show and calls `control.py`
to change anything.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tkinter as tk
from tkinter import ttk, messagebox

from . import autostart, config, control, mistkit as mk
from .widgets import (DomainList, PillGroup, Scroller, StatusPill,
                      Stepper, TabStrip)
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



# --- cards -----------------------------------------------------------------

def card_label(parent, text, hint=None):
    """The uppercase card heading, with an optional right-aligned hint."""
    row = tk.Frame(parent, background=mk.theme.CARD)
    row.pack(fill="x", pady=(0, 12))
    ttk.Label(row, text=mk.track(text.upper()),
              style="Eyebrow.Card.TLabel").pack(side="left")
    if hint:
        ttk.Label(row, text=hint, style="Faint.Card.TLabel").pack(side="right")
    return row


def section_label(parent, text, fonts):
    """A heading for a group of cards, sitting on the page rather than in one."""
    tk.Label(parent, text=mk.track(text.upper()), background=mk.theme.SUNK,
             foreground=mk.theme.SLATE, font=fonts.eyebrow, anchor="w"
             ).pack(fill="x", pady=(18, 9))


class PresetCard(ttk.Frame):
    """One preset as a whole-card button: name, then its settings as data.

    The metadata line is monospace on purpose — "50m · whitelist · locked" is
    three fields, not a sentence, and a fixed pitch makes three cards side by
    side scan as a table.
    """

    def __init__(self, parent, preset, fonts, command):
        super().__init__(parent, style=mk.CARD_STYLE, padding=(17, 15))
        self._command, self._preset = command, preset
        name = tk.Label(self, text=preset.get("name", "?"), anchor="w",
                        background=mk.theme.CARD, foreground=mk.theme.PINE,
                        font=fonts.ui_bold)
        name.pack(fill="x")
        bits = [f"{preset.get('default_minutes', '?')}m", preset.get("mode", "")]
        if preset.get("locked"):
            bits.append("locked")
        meta = tk.Label(self, text=" · ".join(b for b in bits if b), anchor="w",
                        background=mk.theme.CARD, foreground=mk.theme.SLATE,
                        font=fonts.mono_small)
        meta.pack(fill="x", pady=(5, 0))
        for widget in (self, name, meta):
            widget.bind("<Button-1>", self._click)
            widget.bind("<Enter>", lambda _e: self._hover(True))
            widget.bind("<Leave>", lambda _e: self._hover(False))

    def _hover(self, on: bool) -> None:
        # A ttk.Frame has no widget states, so the whole style is swapped —
        # both are prebuilt, so this is a pointer change, not a re-render.
        self.configure(style=mk.CARD_HOVER_STYLE if on else mk.CARD_STYLE)

    def _click(self, _event=None) -> None:
        self._command(self._preset)


class Composer(ttk.Frame):
    """The focus-session composer: duration, mode, lock, Start.

    Owns its own input state and turns it into exactly one use-case call.
    `run` is the caller's elevate-and-apply helper.
    """

    def __init__(self, parent, fonts, run):
        super().__init__(parent, style=mk.CARD_STYLE, padding=16)
        self._run = run
        self.minutes = tk.StringVar(value="90")
        self.mode = tk.StringVar(value=WHITELIST)
        self.locked = tk.BooleanVar(value=False)
        card_label(self, "Focus session")

        row = tk.Frame(self, background=mk.theme.CARD)
        row.pack(fill="x", pady=(0, 14))
        Stepper(row, self.minutes, self._nudge, fonts).pack(side="left")
        self.pills = PillGroup(row, ((WHITELIST, "Whitelist"),
                                     (BLACKLIST, "Blacklist")), self.set_mode)
        self.pills.pack(side="left", padx=(10, 0))
        self.pills.select(WHITELIST)

        ttk.Checkbutton(self, text="Lock session (can't stop early)",
                        variable=self.locked, style="Card.TCheckbutton"
                        ).pack(anchor="w", pady=(0, 14))
        ttk.Button(self, text="Start focus", style="Primary.TButton",
                   command=self.start).pack(fill="x")

    def _nudge(self, delta: int) -> None:
        try:
            current = int(self.minutes.get())
        except ValueError:
            current = 90
        self.minutes.set(str(max(5, current + delta)))

    def set_mode(self, mode: str) -> None:
        self.mode.set(mode)
        self.pills.select(mode)

    def apply_preset(self, preset: dict) -> None:
        """Pre-fill from a preset; the user still presses Start."""
        self.minutes.set(str(preset.get("default_minutes", 25)))
        self.set_mode(preset.get("mode", WHITELIST))
        self.locked.set(bool(preset.get("locked", False)))

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


class ListPanel(ttk.Frame):
    """Both domain lists in one card: tabs, rows, and the edit controls.

    `run` and `refresh` are injected the same way the other cards get them —
    this panel calls use cases, it never elevates anything itself.
    """

    PLACEHOLDER = "add a domain…"

    def __init__(self, parent, fonts, run, refresh):
        super().__init__(parent, style=mk.CARD_STYLE, padding=16)
        self._run, self._refresh, self._fonts = run, refresh, fonts
        self.which = "block"
        self.tabs = TabStrip(self, (("block", "Blacklist"), ("allow", "Whitelist")),
                             self.show, fonts)
        self.tabs.pack(fill="x", pady=(0, 4))
        self.rows = DomainList(self, fonts, height=8)
        self.rows.pack(fill="both", expand=True)
        self._build_controls(fonts)
        self.tabs.select(self.which)

    def _build_controls(self, fonts) -> None:
        add = tk.Frame(self, background=mk.theme.CARD)
        add.pack(fill="x", pady=(12, 0))
        self.entry = ttk.Entry(add, style="Mono.TEntry")
        self.entry.pack(side="left", fill="x", expand=True)
        self.entry.bind("<Return>", lambda _e: self._add())
        self.entry.bind("<FocusIn>", self._clear_placeholder)
        self.entry.bind("<FocusOut>", self._show_placeholder)
        self._show_placeholder()
        ttk.Button(add, text="Add", style="Primary.TButton",
                   command=self._add).pack(side="left", padx=(8, 0))

        buttons = tk.Frame(self, background=mk.theme.CARD)
        buttons.pack(fill="x", pady=(10, 0))
        ttk.Button(buttons, text="Remove", style="Danger.TButton",
                   command=self._remove).pack(side="left")
        self._reload = mk.reload_icon(13, mk.theme.PINE)
        ttk.Button(buttons, text=" Refresh", image=self._reload,
                   compound="left", style="Ghost.TButton",
                   command=self._refresh).pack(side="left", padx=(8, 0))

    # ---- placeholder: ttk.Entry has no such option, so it is done by hand ----
    def _showing_placeholder(self) -> bool:
        return self.entry.get() == self.PLACEHOLDER

    def _clear_placeholder(self, _event=None) -> None:
        if self._showing_placeholder():
            self.entry.delete(0, tk.END)
            self.entry.configure(foreground=mk.theme.PINE)

    def _show_placeholder(self, _event=None) -> None:
        if not self.entry.get():
            self.entry.insert(0, self.PLACEHOLDER)
            self.entry.configure(foreground=mk.theme.SLATE_2)

    # ---- use cases ----
    def show(self, which: str) -> None:
        self.which = which
        self.tabs.select(which)
        self.render(config.load_state())

    def render(self, state) -> None:
        self.tabs.set_count("block", len(state.blocklist))
        self.tabs.set_count("allow", len(state.whitelist))
        items = state.blocklist if self.which == "block" else state.whitelist
        self.rows.fill(sorted(items))

    def _add(self) -> None:
        domain = "" if self._showing_placeholder() else self.entry.get().strip()
        if not domain:
            return
        add = (control.add_to_blocklist if self.which == "block"
               else control.add_to_whitelist)
        self._run(lambda: add([domain]), [self.which, "add", domain])
        self.entry.delete(0, tk.END)
        self._show_placeholder()

    def _remove(self) -> None:
        domain = self.rows.selected()
        if not domain:
            messagebox.showinfo("Nothing selected",
                                "Pick a domain in the list first.")
            return
        drop = (control.remove_from_blocklist if self.which == "block"
                else control.remove_from_whitelist)
        self._run(lambda: drop([domain]), [self.which, "remove", domain])


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
        super().__init__(parent, height=self.HEIGHT, background=mk.theme.SUNK,
                         highlightthickness=0, bd=0)
        self.fonts = fonts
        self._fog = mk.Fog(900, self.HEIGHT, mk.theme.PANEL_TOP, mk.theme.PANEL_BOT)
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
        self._eyebrow = self.create_text(pad, 28, anchor="w", fill=mk.theme.SLATE,
                                         font=f.eyebrow)
        self._lock = self.create_text(pad, 28, anchor="w", fill=mk.theme.AMBER,
                                      font=f.eyebrow, text=mk.track("LOCKED"))
        self._title = self.create_text(pad, 64, anchor="w", fill=mk.theme.PINE, font=f.h1)
        self._sub = self.create_text(pad, 96, anchor="nw", fill=mk.theme.SLATE,
                                     font=f.small, width=380)
        self._ring = self.create_image(0, 0, anchor="nw")
        self._value = self.create_text(0, 0, fill=mk.theme.PINE, font=f.ring)
        self._cap = self.create_text(0, 0, fill=mk.theme.SLATE, font=f.eyebrow)
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
                           mk.theme.PANEL_TOP, mk.theme.PANEL_BOT)
        field = self._fog.raster(0, 0, self._width, self.HEIGHT, step=2)
        field.round_corners(self.RADIUS, mk.theme.FOG_TOP_RGB)
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


class StartupPanel(ttk.Frame):
    """The "start with the computer" settings, as a tab.

    `run` is the caller's elevate-and-apply helper — this panel never talks to
    pkexec itself.
    """

    def __init__(self, parent, fonts, run):
        super().__init__(parent, style=mk.CARD_STYLE, padding=(17, 15))
        self._run = run
        self.enabled = tk.BooleanVar(value=False)
        self.minutes = tk.StringVar(value="300")
        self.mode = tk.StringVar(value=BLACKLIST)
        self.locked = tk.BooleanVar(value=False)
        self.gui_auto = tk.BooleanVar(value=False)
        self.service = tk.StringVar(value="…")
        self._build(fonts)

    def _build(self, fonts) -> None:
        row = tk.Frame(self, background=mk.theme.CARD)
        row.pack(fill="x")
        ttk.Checkbutton(row, text="Block at every boot for", variable=self.enabled,
                        style="Card.TCheckbutton").pack(side="left")
        ttk.Entry(row, textvariable=self.minutes, width=5,
                  justify="center").pack(side="left", padx=6)
        ttk.Label(row, text="min", style="Muted.Card.TLabel").pack(side="left")
        ttk.Button(row, text="Save", style="Primary.TButton",
                   command=self._save).pack(side="right")

        row2 = tk.Frame(self, background=mk.theme.CARD)
        row2.pack(fill="x", pady=(12, 0))
        for value, label in ((BLACKLIST, "Blacklist"), (WHITELIST, "Whitelist")):
            ttk.Radiobutton(row2, text=label, value=value, variable=self.mode,
                            style="Card.TRadiobutton").pack(side="left", padx=(0, 14))
        ttk.Checkbutton(row2, text="🔒 Locked", variable=self.locked,
                        style="Lock.Card.TCheckbutton").pack(side="left")

        row3 = tk.Frame(self, background=mk.theme.CARD)
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
    THEME_EVERY = 10        # ticks between desktop colour-scheme checks

    def __init__(self):
        super().__init__()
        self.title("SocialBlocker")
        self._size_window()
        self._ticks = 0
        self._scheme = mk.detect_scheme()
        self._build_ui()

        # Unprivileged is the normal case now (pkexec elevates each change), so
        # only warn when there is no way to elevate at all.
        if _needs_pkexec() and not shutil.which("pkexec"):
            self.after(300, lambda: messagebox.showwarning(
                "Cannot apply changes",
                "Changes edit /etc/hosts, which needs admin rights, and pkexec "
                "is not installed.\n\nInstall policykit-1, or relaunch with:\n"
                "  sudo -E socialblocker gui"))
        self._tick()

    def _size_window(self) -> None:
        """Fit the screen rather than assuming a desktop-sized one."""
        height = min(900, self.winfo_screenheight() - 120)
        self.geometry(f"940x{height}")
        self.minsize(860, 460)

    def _build_ui(self) -> None:
        """Style, then build the whole window and fill it from disk."""
        self.fonts = mk.apply_theme(self, self._scheme)
        self._build_topbar()
        self.body = Scroller(self)
        self.body.pack(fill="both", expand=True)
        self._build_body(self.body.inner)
        self._render_lists()
        self.startup.render()
        st = control.status()
        self._render_status(st)
        # Explicitly, not left to the tick: on a rebuild the tick counter is
        # mid-cycle, so the stat tiles would sit on "—" for up to 10 seconds.
        self._render_stats(st)

    def _restyle(self, scheme: str) -> None:
        """Rebuild the window in the other colour scheme.

        Tk bakes a widget's colours in at construction and has no restyle call,
        so a live theme change means a new widget tree whichever way you cut it.
        That is affordable because the window is a pure function of
        `control.status()` — the composer's three inputs and the open list tab
        are the only state that is not on disk, so they are what is carried.
        """
        self._scheme = scheme
        carried = (self.composer.minutes.get(), self.composer.mode.get(),
                   self.composer.locked.get(), self.lists.which)
        self.body.release()
        for child in self.winfo_children():
            child.destroy()
        self._build_ui()
        self.composer.minutes.set(carried[0])
        self.composer.set_mode(carried[1])
        self.composer.locked.set(carried[2])
        self.lists.show(carried[3])

    # ---- layout ----
    def _build_topbar(self) -> None:
        bar = tk.Frame(self, background=mk.theme.CARD, padx=18, pady=11,
                       highlightbackground=mk.theme.LINE_SOFT,
                       highlightthickness=1, bd=0)
        bar.pack(fill="x")
        self._mark = mk.mark_image(28, mk._rgb(mk.theme.CARD))
        tk.Label(bar, image=self._mark, background=mk.theme.CARD).pack(side="left")
        tk.Label(bar, text="Social", background=mk.theme.CARD,
                 foreground=mk.theme.PINE,
                 font=self.fonts.ui_bold).pack(side="left", padx=(10, 0))
        tk.Label(bar, text="Blocker", background=mk.theme.CARD,
                 foreground=mk.theme.TEAL_DEEP,
                 font=self.fonts.mark).pack(side="left")
        # Icon-only: the mark, the wordmark and the status chip already fill
        # this bar, and "Refresh" is the one action here — a label adds width
        # without adding meaning.
        self._reload = mk.reload_icon(15, mk.theme.PINE)
        refresh = ttk.Button(bar, image=self._reload, style="Icon.TButton",
                             command=self._refresh)
        refresh.pack(side="right")
        self.pill = StatusPill(bar, self.fonts)
        self.pill.pack(side="right", padx=12)

    def _build_body(self, parent) -> None:
        parent.configure(padx=18, pady=16)
        self.hero = Hero(parent, self.fonts, lambda: self._extend(15),
                         self._stop_focus)
        self.hero.pack(fill="x")
        self._build_presets(parent)

        columns = tk.Frame(parent, background=mk.theme.SUNK)
        columns.pack(fill="x", pady=(14, 0))
        columns.columnconfigure(0, weight=1, uniform="col")
        columns.columnconfigure(1, weight=1, uniform="col")
        left = tk.Frame(columns, background=mk.theme.SUNK)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 7))
        self._build_mode_card(left)
        self.composer = Composer(left, self.fonts, self._do)
        self.composer.pack(fill="x", pady=(14, 0))
        self.lists = ListPanel(columns, self.fonts, self._do, self._refresh)
        self.lists.grid(row=0, column=1, sticky="nsew", padx=(7, 0))

        self._build_stats(parent)
        self._build_startup(parent)

    def _build_presets(self, parent) -> None:
        section_label(parent, "Quick presets", self.fonts)
        row = tk.Frame(parent, background=mk.theme.SUNK)
        row.pack(fill="x")
        presets = control.list_presets()
        if not presets:
            tk.Label(row, text="No presets in data/presets.json.",
                     background=mk.theme.SUNK, foreground=mk.theme.SLATE,
                     font=self.fonts.small).pack(anchor="w")
            return
        for i, preset in enumerate(presets):
            row.columnconfigure(i, weight=1, uniform="preset")
            # preset=preset binds this one (avoids the late-binding closure bug).
            card = PresetCard(row, preset, self.fonts,
                              lambda p=preset: self.composer.apply_preset(p))
            card.grid(row=0, column=i, sticky="nsew",
                      padx=(0 if i == 0 else 7, 0 if i == len(presets) - 1 else 7))

    def _build_mode_card(self, parent) -> None:
        card = mk.card(parent)
        card.pack(fill="x")
        card_label(card, "All-day default mode")
        self.mode_pills = PillGroup(card, ((BLACKLIST, "Blacklist"),
                                           (WHITELIST, "Whitelist"),
                                           (OFF, "Off")), self._set_mode)
        self.mode_pills.pack(fill="x")
        self.mode_desc = tk.StringVar(value="")
        ttk.Label(card, textvariable=self.mode_desc, style="Muted.Card.TLabel",
                  wraplength=380, justify="left").pack(fill="x", pady=(12, 0))

    def _build_stats(self, parent) -> None:
        row = tk.Frame(parent, background=mk.theme.SUNK)
        row.pack(fill="x", pady=(14, 0))
        self.stat_vars = {}
        specs = (("focused_today_min", "Focused today", "min"),
                 ("blocked_now", "Blocked now", "sites"),
                 ("streak_days", "Streak", "days"))
        for i, (key, title, unit) in enumerate(specs):
            row.columnconfigure(i, weight=1, uniform="stat")
            card = mk.card(row, pad=13)
            card.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 6,
                                                            0 if i == 2 else 6))
            ttk.Label(card, text=mk.track(title.upper()),
                      style="Eyebrow.Card.TLabel").pack(anchor="w")
            value = tk.Frame(card, background=mk.theme.CARD)
            value.pack(anchor="w", pady=(8, 0))
            var = tk.StringVar(value="—")
            ttk.Label(value, textvariable=var,
                      style="Numeral.Card.TLabel").pack(side="left")
            ttk.Label(value, text=unit, style="Unit.Card.TLabel").pack(side="left",
                                                                      padx=(5, 0))
            self.stat_vars[key] = var

    def _build_startup(self, parent) -> None:
        section_label(parent, "Start with the computer", self.fonts)
        self.startup = StartupPanel(parent, self.fonts, self._do)
        self.startup.pack(fill="x")

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

    def _extend(self, minutes) -> None:
        self._do(lambda: control.extend_session(minutes), ["extend", str(minutes)])

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
        self.pill.render(*_pill_state(st))
        self.hero.render(st)
        self.mode_pills.select(st["default_mode"])
        self.mode_desc.set(MODE_DESC.get(st["default_mode"], ""))

    def _render_stats(self, st: dict) -> None:
        for key, var in self.stat_vars.items():
            var.set(str(st[key]))

    def _render_lists(self) -> None:
        self.lists.render(config.load_state())

    def _tick(self) -> None:
        # The countdown needs 1 Hz; the stat tiles change at most once a minute,
        # and the lists are left alone so a selection isn't wiped out mid-edit.
        st = control.status()
        self._render_status(st)
        if self._ticks % self.STATS_EVERY == 0:
            self._render_stats(st)
        self._ticks += 1
        # Every 10s, not every second: the probe shells out to the desktop
        # (measured 6.7ms median, 10.4ms worst), and someone changing their
        # system theme is not waiting on a stopwatch.
        if self._ticks % self.THEME_EVERY == 0:
            scheme = mk.detect_scheme()
            if scheme != self._scheme:
                self._restyle(scheme)
        self.after(1000, self._tick)


def _pill_state(st: dict) -> tuple:
    """(label, dot colour) for the title-bar status chip."""
    if st["locked"]:
        return "Locked", mk.theme.AMBER
    if st["session_active"]:
        return "Focusing", mk.theme.TEAL
    if st["effective_mode"] == OFF:
        return "Off", mk.theme.SLATE_2
    return st["effective_mode"].title(), mk.theme.TEAL


def main():
    App().mainloop()


if __name__ == "__main__":
    main()
