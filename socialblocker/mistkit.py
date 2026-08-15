"""Mist design system for the SocialBlocker GUI — tokens, ttk theme, raster art.

Outer-circle adapter (CLAUDE.md section 5): this module imports nothing from
this package and knows nothing about blocking. `gui.py` asks it for colours,
fonts, styled containers and two pieces of generated art; every decision about
*what* to show stays in `gui.py`.

Two palettes ship: **Mist** (light) and **Ink** (dark), the two desktop
directions from the original redesign. Which one is live is the desktop's
call, not ours — `detect_scheme()` asks it, and `mistkit.theme` is the active
`Palette`. Reading the desktop's colour preference is the same kind of query
as asking fontconfig which families exist, which is why it lives here.

Why generate art at all: the Mist design is built on rounded corners, soft
gradients and a stroked progress ring, and Tk's canvas has neither
anti-aliasing nor alpha compositing. So the shapes with hard edges are drawn
into an RGB byte buffer here, sampled at SCALE x SCALE per pixel and averaged
down — that averaging *is* the anti-aliasing — then encoded as a PNG with
`zlib` + `struct` and handed to `tk.PhotoImage`, which reads PNG natively in
Tk 8.6. Standard library only, per the zero-dependency rule.
"""

from __future__ import annotations

import base64
import math
import os
import re
import struct
import subprocess
import zlib
import tkinter as tk
from tkinter import font as tkfont, ttk

TAU = math.pi * 2
SCALE = 3           # subsamples per axis for edges; 9 samples per pixel


# --- tokens ----------------------------------------------------------------

def _hex(rgb: tuple) -> str:
    return "#%02x%02x%02x" % rgb


def _over(fg: tuple, bg: tuple, alpha: float) -> tuple:
    """Composite `fg` over `bg` at `alpha`, returning an opaque colour."""
    return tuple(round(f * alpha + b * (1 - alpha)) for f, b in zip(fg, bg))


class Palette:
    """One complete colour set: Mist (light) or Ink (dark).

    Callers pass only the *base* colours. Everything the mockup expressed as an
    `rgba()` overlay — hairlines, selection tints, the ring's empty track — is
    composited against its real backdrop here, once, because Tk widgets have no
    alpha channel and cannot do it at paint time.

    Ink is deliberately **not** an inversion of Mist. Two things differ:

    * **Elevation reverses.** On white, a raised surface is lighter *and* casts
      a shadow; on near-black a shadow is invisible, so elevation has to be
      carried by the surface colour alone — which is why the "white" role
      (`WHITE`: listbox, selected segment, notebook tab) is the lightest *dark*
      grey rather than white.
    * **Accents are re-picked, not reused.** `TEAL_DEEP` means "more emphatic
      than TEAL"; on white that direction is darker, on near-black it has to be
      lighter. The role is stable, the direction is not.
    """

    def __init__(self, name, dark, fog, panel, surfaces, text,
                 teal, amber, danger, edge):
        self.name, self.dark = name, dark
        self.FOG_TOP_RGB, self.FOG_BOT_RGB = fog
        self.PANEL_TOP, self.PANEL_BOT = panel
        self.CARD_RGB, raised_rgb, self.BLOBS = surfaces
        self.PINE, self.SLATE, self.SLATE_2 = text
        self.TEAL_RGB, self.TEAL_DEEP_RGB, teal_tint, teal_track = teal
        self.AMBER_RGB, amber_tint, amber_track = amber
        self.DANGER = danger
        edge_rgb, line_a, soft_a = edge

        self.FOG_TOP = _hex(self.FOG_TOP_RGB)
        self.SUNK = self.FOG_TOP        # --sunk and --fog-top are one value
        self.CARD = _hex(self.CARD_RGB)
        self.WHITE = _hex(raised_rgb)
        self.TEAL = _hex(self.TEAL_RGB)
        self.TEAL_DEEP = _hex(self.TEAL_DEEP_RGB)
        self.AMBER = _hex(self.AMBER_RGB)

        # What you draw *on top of* an accent fill: a Primary button's label, a
        # checkbox tick. Mist's accents are dark enough to take white; Ink's are
        # light, so the same role has to invert.
        self.ON_ACCENT = self.CARD if dark else self.WHITE

        self.LINE = _hex(_over(edge_rgb, self.CARD_RGB, line_a))
        self.LINE_SOFT = _hex(_over(edge_rgb, self.CARD_RGB, soft_a))
        self.TEAL_TINT = _hex(_over(self.TEAL_RGB, self.CARD_RGB, teal_tint))
        self.TEAL_TINT_RGB = _over(self.TEAL_RGB, self.CARD_RGB, teal_track)
        self.AMBER_TINT = _hex(_over(self.AMBER_RGB, self.CARD_RGB, amber_tint))
        self.AMBER_TINT_RGB = _over(self.AMBER_RGB, self.CARD_RGB, amber_track)


# Mist — straight from SocialBlocker-Mist-Desktop.html, unchanged.
MIST = Palette(
    name="Mist", dark=False,
    fog=((0xEE, 0xF3, 0xF4), (0xD9, 0xE3, 0xE6)),
    # The hero panel sits *in front of* the drifting fog, so its own gradient
    # starts much lighter than the page's --fog-top.
    panel=((0xFC, 0xFE, 0xFE), (0xE3, 0xEC, 0xEE)),
    surfaces=((0xFB, 0xFD, 0xFD), (0xFF, 0xFF, 0xFF),
              (((0xB4, 0xD6, 0xDC), 0.34), ((0x2F, 0x8F, 0x9D), 0.15),
               ((0xD2, 0xE4, 0xE7), 0.42))),
    text=("#16272c", "#5f7378", "#85989d"),
    teal=((0x2F, 0x8F, 0x9D), (0x21, 0x74, 0x80), 0.12, 0.14),
    amber=((0xB9, 0x77, 0x2F), 0.12, 0.16),
    danger="#b6503f",
    edge=((0x15, 0x26, 0x2B), 0.10, 0.06),      # hairlines are ink over card
)

# Ink — the dark sibling of the same design language. Contrast against its own
# card, measured: PINE 13.5, SLATE 7.1, TEAL 6.5, AMBER 7.3, DANGER 5.0 — all
# above Mist's equivalents, so nothing here is a legibility regression.
INK = Palette(
    name="Ink", dark=True,
    fog=((0x0E, 0x18, 0x1C), (0x08, 0x10, 0x13)),
    panel=((0x13, 0x20, 0x25), (0x0B, 0x14, 0x18)),
    surfaces=((0x16, 0x24, 0x2A), (0x1E, 0x2F, 0x36),
              # On a dark field a blob only reads if it is *lighter* than the
              # panel, so these glow rather than shade.
              (((0x2C, 0x56, 0x61), 0.55), ((0x2F, 0x8F, 0x9D), 0.22),
               ((0x21, 0x3E, 0x47), 0.60))),
    text=("#e6eef0", "#9db1b7", "#74898f"),
    teal=((0x4F, 0xB3, 0xC2), (0x86, 0xD5, 0xE0), 0.22, 0.26),
    amber=((0xDF, 0xA4, 0x5F), 0.22, 0.30),
    danger="#e0705c",
    # Hairlines invert too: light over card, and stronger, because a 6% overlay
    # that reads as a hairline on white is invisible on near-black.
    edge=((0xC6, 0xDC, 0xE0), 0.16, 0.10),
)

PALETTES = {"light": MIST, "dark": INK}

theme = MIST        # the active palette; `apply_theme` rebinds it


def use_scheme(scheme: str) -> Palette:
    """Make `scheme` ("light"/"dark") the active palette and return it."""
    global theme
    theme = PALETTES.get(scheme, MIST)
    return theme


# --- desktop colour scheme --------------------------------------------------
# Same kind of call as asking fontconfig what families exist: a question for the
# desktop, answered once at start-up and re-checked while the window is open.

SCHEME_ENV = "SOCIALBLOCKER_THEME"


def detect_scheme() -> str:
    """"light" or "dark", from the desktop's own setting.

    Tried in order: the env override, the XDG portal (the cross-desktop
    standard), GNOME's own key, then the GTK theme name for desktops older
    than `color-scheme`. Falls back to light rather than failing — a GUI that
    refuses to open because it could not guess a colour is a bad trade.
    """
    override = os.environ.get(SCHEME_ENV, "").strip().lower()
    if override in PALETTES:
        return override
    for probe in (_from_portal, _from_gsettings, _from_gtk_theme):
        scheme = probe()
        if scheme:
            return scheme
    return "light"


def _ask(cmd: list) -> str:
    """Run one short desktop query; "" on any failure.

    The timeout is the point: a missing tool or a wedged session bus must never
    be able to hold the window open-less, or freeze it once it is open.
    """
    try:
        cp = subprocess.run(cmd, capture_output=True, text=True, timeout=1.5)
    except (OSError, subprocess.SubprocessError):
        return ""
    return cp.stdout.strip() if cp.returncode == 0 else ""


def _from_portal() -> str:
    """XDG desktop portal — works on GNOME, KDE and wlroots alike.

    `Read` and not `ReadOne`: ReadOne is the newer spelling and is missing from
    portal builds still in the field (measured on this machine: UnknownMethod).
    0 = no preference, 1 = prefer dark, 2 = prefer light.
    """
    out = _ask(["gdbus", "call", "--session",
                "--dest", "org.freedesktop.portal.Desktop",
                "--object-path", "/org/freedesktop/portal/desktop",
                "--method", "org.freedesktop.portal.Settings.Read",
                "org.freedesktop.appearance", "color-scheme"])
    found = re.search(r"uint32 (\d+)", out)
    return {"1": "dark", "2": "light"}.get(found.group(1), "") if found else ""


def _from_gsettings() -> str:
    """GNOME's own key, for a session with no portal running."""
    out = _ask(["gsettings", "get", "org.gnome.desktop.interface", "color-scheme"])
    if "prefer-dark" in out:
        return "dark"
    return "light" if "prefer-light" in out else ""


def _from_gtk_theme() -> str:
    """Before `color-scheme` existed, only the theme name said dark."""
    out = _ask(["gsettings", "get", "org.gnome.desktop.interface", "gtk-theme"])
    return "dark" if out.strip("' ").lower().endswith("-dark") else ""


# --- typography ------------------------------------------------------------
# The mockup's Manrope + Instrument Serif are not vendored: install.sh runs as
# root and would have to guess the real user's HOME to place them. Instead we
# take the best installed match, so the look improves for free if they are ever
# installed system-wide.

UI_STACK = ("Manrope", "Inter", "Cantarell", "Ubuntu", "Noto Sans", "DejaVu Sans")
DISPLAY_STACK = ("Instrument Serif", "Bitstream Charter", "Charter",
                 "Georgia", "DejaVu Serif", "Liberation Serif")
# Domains and preset metadata are read as *data*, not prose — a monospace face
# aligns the dots and stops "rn" from reading as "m" in a hostname.
MONO_STACK = ("JetBrains Mono", "Fira Mono", "Ubuntu Mono", "DejaVu Sans Mono",
              "Liberation Mono", "Courier")


def _first_installed(stack: tuple, default: str) -> str:
    """First family in `stack` that fontconfig actually knows about."""
    have = {name.lower() for name in tkfont.families()}
    for name in stack:
        if name.lower() in have:
            return name
    return default


class Fonts:
    """Named type roles, resolved once against what is really installed.

    Needs an existing Tk root: `tkfont.families()` is a query to the
    interpreter, not a static table.
    """

    def __init__(self) -> None:
        ui = _first_installed(UI_STACK, "TkDefaultFont")
        display = _first_installed(DISPLAY_STACK, ui)
        mono = _first_installed(MONO_STACK, "TkFixedFont")
        self.ui_family, self.display_family, self.mono_family = ui, display, mono
        self.ui = (ui, 10)
        self.ui_bold = (ui, 10, "bold")
        self.small = (ui, 9)
        self.small_bold = (ui, 9, "bold")
        self.eyebrow = (ui, 8, "bold")
        self.button = (ui, 10, "bold")
        self.h1 = (display, 25)
        self.numeral = (display, 21)
        self.ring = (display, 23)
        self.mark = (display, 15, "italic")
        self.mono = (mono, 10)
        self.mono_small = (mono, 8)


def track(text: str) -> str:
    """Stand-in for the mockup's `letter-spacing` on small caps labels.

    Tk fonts expose no tracking control, so a thin space between characters is
    the only way to get that airy uppercase look. Short labels only.
    """
    return " ".join(text)


# --- ttk theme -------------------------------------------------------------

def apply_theme(root: tk.Misc, scheme: str = None) -> Fonts:
    """Repaint ttk in `scheme` (default: the desktop's); returns the fonts.

    Also rebinds the module-level `theme`, so callers read their colours from
    `mistkit.theme` afterwards and get whichever palette is live.
    """
    p = use_scheme(scheme or detect_scheme())
    fonts = Fonts()
    st = ttk.Style(root)
    # clam is the only built-in theme on Linux that honours per-element
    # colours; the others ignore most `configure` calls outright.
    st.theme_use("clam")
    root.configure(background=p.SUNK)
    st.configure(".", background=p.SUNK, foreground=p.PINE, font=fonts.ui,
                 borderwidth=0, focuscolor=p.TEAL)
    _style_labels(st, fonts, p)
    _style_buttons(st, fonts, p)
    _style_inputs(st, fonts, p)
    _style_containers(st, fonts, p)
    return fonts


def _style_labels(st: ttk.Style, fonts: Fonts, p: Palette) -> None:
    st.configure("TLabel", background=p.SUNK, foreground=p.PINE, font=fonts.ui)
    st.configure("Muted.TLabel", foreground=p.SLATE, font=fonts.small)
    # Everything below sits on a card, which is a different surface from the
    # window. ttk resolves "A.B.TLabel" by falling back to "B.TLabel", so
    # these all inherit the card background from one place.
    st.configure("Card.TLabel", background=p.CARD, foreground=p.PINE)
    st.configure("Eyebrow.Card.TLabel", foreground=p.SLATE, font=fonts.eyebrow)
    st.configure("Muted.Card.TLabel", foreground=p.SLATE, font=fonts.small)
    st.configure("Faint.Card.TLabel", foreground=p.SLATE_2, font=fonts.small)
    st.configure("Strong.Card.TLabel", font=fonts.ui_bold)
    st.configure("Numeral.Card.TLabel", font=fonts.numeral)
    st.configure("Unit.Card.TLabel", foreground=p.SLATE, font=fonts.small_bold)
    st.configure("Amber.Card.TLabel", foreground=p.AMBER, font=fonts.small_bold)


def _flat(st: ttk.Style, p: Palette, name: str, bg: str, fg: str, hover_bg: str,
          hover_fg: str, border: str = "", font=None, pad=(14, 8)) -> None:
    """One flat button style.

    clam draws a 3D bevel from `lightcolor`/`darkcolor`; setting both to the
    border colour is what actually flattens a ttk button. `focuscolor` stays
    teal on purpose — losing the keyboard focus ring to look prettier is not
    a trade worth making.
    """
    edge = border or bg
    st.configure(name, background=bg, foreground=fg, bordercolor=edge,
                 lightcolor=edge, darkcolor=edge, borderwidth=1,
                 relief="flat", padding=pad, font=font, focuscolor=p.TEAL)
    st.map(name,
           background=[("disabled", p.SUNK), ("pressed", hover_bg), ("active", hover_bg)],
           foreground=[("disabled", p.SLATE_2), ("active", hover_fg)],
           bordercolor=[("disabled", p.LINE_SOFT), ("active", p.TEAL)],
           lightcolor=[("active", hover_bg)], darkcolor=[("active", hover_bg)])


# Generated button faces, kept alive here: Tk does not own PhotoImages, and a
# themed element that loses its image renders as nothing at all.
_PILL_TILE = 28         # every face is one 28px tile, stretched by the 9-patch
_PILL_RADIUS = 9
_ICON_TILE = 34         # round icon buttons: radius is half of this
_pill_images: dict = {}
_pill_elements: set = set()


def _pill_style(st: ttk.Style, p: Palette, scheme: str, name: str,
                faces: tuple, font, pad, radius: float = _PILL_RADIUS,
                tile: int = _PILL_TILE) -> None:
    """Give `name` a rounded 9-patch face per widget state.

    `faces` is ordered `((state, fill, border), ...)` with the default first;
    ttk takes the first matching spec, so "selected" must precede "active" or a
    hovered selection would fall back to the hover face.

    The element is created once per (scheme, name) and never again: ttk has no
    way to redefine an element, so a theme switch makes a *new* one and only
    re-points the layout. That is why the name carries the scheme.
    """
    key = (scheme, name)
    element = "%s.%s.pill" % (name, scheme)
    if key not in _pill_elements:
        images = [(state, pill_image(tile, radius, fill, _rgb(p.CARD), border))
                  for state, fill, border in faces]
        _pill_images[key] = images
        st.element_create(element, "image", images[0][1],
                          *[(state, img) for state, img in images[1:]],
                          border=int(radius), sticky="nsew")
        _pill_elements.add(key)
    st.layout(name, [(element, {"sticky": "nsew", "children": [
        ("Button.padding", {"sticky": "nsew", "children": [
            ("Button.label", {"sticky": "nsew"})]})]})])
    # width=0 matters: clam's TButton sets `width: -11`, an 11-character
    # minimum that every derived style inherits. Left alone it makes "Off" and
    # "Blacklist" exactly the same 140px wide, which is not a pill row.
    # The 9-patch `border` is also reserved as padding around the label, so the
    # per-style padding below is *on top of* that inset, not instead of it.
    st.configure(name, font=font, padding=pad, anchor="center", width=0,
                 foreground=p.PINE, background=p.CARD)


def _style_buttons(st: ttk.Style, fonts: Fonts, p: Palette) -> None:
    scheme = "dark" if p.dark else "light"
    tint = _over(p.TEAL_RGB, _rgb(p.CARD), 0.10)

    # The neutral pill: mode choices. `selected` is a real ttk state, so the
    # front-end flips it with `.state(["selected"])` instead of swapping styles.
    _pill_style(st, p, scheme, "Pill.TButton",
                ((None, _rgb(p.SUNK), None),
                 ("selected", p.TEAL_RGB, None),
                 ("active", tint, None)), fonts.ui, (9, 4))
    st.map("Pill.TButton",
           foreground=[("selected", p.ON_ACCENT), ("active", p.TEAL_DEEP)])

    _pill_style(st, p, scheme, "Primary.TButton",
                ((None, p.TEAL_RGB, None),
                 ("pressed", p.TEAL_DEEP_RGB, None),
                 ("active", p.TEAL_DEEP_RGB, None)), fonts.button, (10, 6))
    st.configure("Primary.TButton", foreground=p.ON_ACCENT)
    st.map("Primary.TButton", foreground=[("disabled", p.SLATE_2),
                                          ("active", p.ON_ACCENT)])

    # Outlined pill: an action that is available but not the point of the card.
    _pill_style(st, p, scheme, "Ghost.TButton",
                ((None, _rgb(p.CARD), _rgb(p.LINE)),
                 ("active", _rgb(p.WHITE), p.TEAL_RGB)), fonts.ui, (8, 4))
    st.map("Ghost.TButton", foreground=[("disabled", p.SLATE_2),
                                        ("active", p.TEAL_DEEP)])

    _pill_style(st, p, scheme, "Danger.TButton",
                ((None, _rgb(p.CARD), _rgb(p.LINE)),
                 ("active", _rgb(p.WHITE), _rgb(p.DANGER))), fonts.ui, (8, 4))
    st.map("Danger.TButton", foreground=[("active", p.DANGER)])

    _icon_style(st, scheme, "Icon.TButton",
                ((None, _rgb(p.CARD), _rgb(p.LINE)),
                 ("active", _rgb(p.WHITE), p.TEAL_RGB)), _rgb(p.CARD))

    # The stepper's - and + are glyphs inside the group's own border, so they
    # get no face of their own — a pill inside a pill reads as clutter.
    _flat(st, p, "Step.TButton", p.CARD, p.SLATE, p.CARD, p.TEAL_DEEP, p.CARD,
          fonts.ui_bold, (10, 4))
    _flat(st, p, "TButton", p.CARD, p.PINE, p.WHITE, p.TEAL_DEEP, p.LINE, fonts.ui)


def _icon_style(st: ttk.Style, scheme: str, name: str, faces: tuple,
                bg: tuple) -> None:
    """A fixed-size round button face — no 9-patch, because none is possible.

    A 9-patch keeps its corners unstretched by reserving `border` pixels on
    each side, which also become the label's padding. So the smallest truly
    circular button it can produce is `2 * radius + icon` across: at radius 17
    a 15px glyph gives a 49px button, far too heavy for a title bar. An icon
    button has one fixed size, so the honest answer is to skip the 9-patch and
    let the image be the whole face at its natural size.
    """
    key = (scheme, name)
    element = "%s.%s.icon" % (name, scheme)
    if key not in _pill_elements:
        images = [(state, pill_image(_ICON_TILE, _ICON_TILE / 2.0, fill, bg, border))
                  for state, fill, border in faces]
        _pill_images[key] = images
        st.element_create(element, "image", images[0][1],
                          *[(state, img) for state, img in images[1:]],
                          sticky="nsew")
        _pill_elements.add(key)
    st.layout(name, [(element, {"sticky": "nsew", "children": [
        ("Button.label", {"sticky": "nsew"})]})])
    st.configure(name, anchor="center", width=0, padding=0)


def _rgb(hex_colour: str) -> tuple:
    h = hex_colour.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _field_element(st: ttk.Style, scheme: str, p: Palette) -> None:
    """The same 9-patch trick for text fields, so an input matches a button."""
    key = (scheme, "field")
    element = "field.%s.pill" % scheme
    if key not in _pill_elements:
        card_bg = _rgb(p.CARD)
        images = [(None, pill_image(_PILL_TILE, _PILL_RADIUS, _rgb(p.WHITE),
                                    card_bg, _rgb(p.LINE))),
                  ("focus", pill_image(_PILL_TILE, _PILL_RADIUS, _rgb(p.WHITE),
                                       card_bg, p.TEAL_RGB, 1.4))]
        _pill_images[key] = images
        st.element_create(element, "image", images[0][1],
                          *[(state, img) for state, img in images[1:]],
                          border=_PILL_RADIUS, sticky="nsew")
        _pill_elements.add(key)
    st.layout("TEntry", [(element, {"sticky": "nsew", "children": [
        ("Entry.padding", {"sticky": "nsew", "children": [
            ("Entry.textarea", {"sticky": "nsew"})]})]})])


def _style_inputs(st: ttk.Style, fonts: Fonts, p: Palette) -> None:
    scheme = "dark" if p.dark else "light"
    _field_element(st, scheme, p)
    st.configure("TEntry", foreground=p.PINE, insertcolor=p.PINE, padding=7)
    st.configure("Mono.TEntry", font=fonts.mono)
    # clam's indicator element takes `indicatorbackground` (the box) and
    # `indicatorforeground` (the tick). It has no `indicatorcolor` at all —
    # that spelling belongs to the default/alt themes and is silently ignored
    # here, which is why an unstyled box comes out white whatever the palette.
    for kind in ("TCheckbutton", "TRadiobutton"):
        st.configure(kind, background=p.SUNK, foreground=p.PINE, font=fonts.ui,
                     focuscolor=p.TEAL, indicatorbackground=p.WHITE,
                     indicatorforeground=p.ON_ACCENT,
                     upperbordercolor=p.LINE, lowerbordercolor=p.LINE,
                     bordercolor=p.LINE, lightcolor=p.WHITE, darkcolor=p.WHITE)
        st.configure("Card." + kind, background=p.CARD)
        for style in (kind, "Card." + kind):
            base = p.CARD if style.startswith("Card.") else p.SUNK
            st.map(style, background=[("active", base)],
                   foreground=[("active", p.PINE)],
                   indicatorbackground=[("disabled", base), ("selected", p.TEAL)])
    st.configure("Lock.Card.TCheckbutton", foreground=p.AMBER, font=fonts.ui_bold)
    st.map("Lock.Card.TCheckbutton",
           indicatorbackground=[("disabled", p.CARD), ("selected", p.AMBER)])


def _style_containers(st: ttk.Style, fonts: Fonts, p: Palette) -> None:
    st.configure("TFrame", background=p.SUNK)
    _card_styles(st, "dark" if p.dark else "light", p)
    st.configure("Card.TFrame", background=p.CARD)
    st.configure("Sunk.TFrame", background=p.SUNK)
    # bordercolor/lightcolor/darkcolor are the client-area frame, not the tabs.
    # Left unset, clam draws its own light bevel there — invisible on Mist,
    # a bright white rectangle on Ink.
    st.configure("TScrollbar", background=p.LINE, troughcolor=p.CARD,
                 bordercolor=p.CARD, lightcolor=p.CARD, darkcolor=p.CARD,
                 borderwidth=0, width=8)
    st.map("TScrollbar", background=[("active", p.SLATE_2)])
    # Drop clam's stepper arrows: at this width they render as two specks, and
    # nothing in this window is navigated one line at a time.
    st.layout("Vertical.TScrollbar",
              [("Vertical.Scrollbar.trough", {"sticky": "ns", "children": [
                  ("Vertical.Scrollbar.thumb", {"unit": 1, "sticky": "nsew"})]})])

    # The domain list. A Treeview, not a Listbox, because only a Treeview can
    # put an icon on a row — and it drops the one classic Tk widget that had
    # no ttk styling at all.
    st.configure("Domains.Treeview", background=p.CARD, fieldbackground=p.CARD,
                 foreground=p.PINE, font=fonts.mono, rowheight=27,
                 borderwidth=0, relief="flat")
    st.map("Domains.Treeview",
           background=[("selected", p.TEAL_TINT)],
           foreground=[("selected", p.PINE)])
    st.layout("Domains.Treeview", [("Treeview.treearea", {"sticky": "nsew"})])


CARD_STYLE = "Card.TFrame"
CARD_HOVER_STYLE = "Hover.Card.TFrame"
CARD_RADIUS = 11


def _card_styles(st: ttk.Style, scheme: str, p: Palette) -> None:
    """Rounded card surfaces, as a themed `ttk.Frame`.

    The same 9-patch trick as the buttons, one level up. It beats drawing the
    card on a canvas because children still pack and grid normally and the
    corners survive a resize for free — and it beats `tk.Frame`, whose
    `highlightthickness` border can only ever be a rectangle.

    The frame's own window background is the *page* colour, and the rounded
    image is composited over it, which is what makes the corners read as cut
    out rather than painted. Children are inset by the padding, so their flat
    `CARD` backgrounds never reach a corner.
    """
    for name, edge in ((CARD_STYLE, _rgb(p.LINE_SOFT)),
                       (CARD_HOVER_STYLE, p.TEAL_RGB)):
        key = (scheme, name)
        element = "%s.%s.pane" % (name, scheme)
        if key not in _pill_elements:
            image = pill_image(_PILL_TILE, CARD_RADIUS, _rgb(p.CARD),
                               _rgb(p.SUNK), edge)
            _pill_images[key] = [(None, image)]
            st.element_create(element, "image", image,
                              border=CARD_RADIUS, sticky="nsew")
            _pill_elements.add(key)
        st.layout(name, [(element, {"sticky": "nsew"})])
        st.configure(name, background=p.SUNK)


def card(parent: tk.Misc, pad=14, style: str = CARD_STYLE) -> ttk.Frame:
    """A Mist surface card."""
    return ttk.Frame(parent, style=style, padding=pad)


def rounded_rect(w: int, h: int, radius: float, fill: str,
                 border: str = None, bg: str = None) -> tk.PhotoImage:
    """An opaque rounded panel, corners cut to `bg`.

    For a `tk.Canvas` backdrop rather than a ttk element: a canvas background
    is a solid colour with no alpha, so the corners have to be painted with
    whatever is really behind — the caller says what that is.
    """
    behind = _rgb(bg or theme.CARD)
    r = Raster(w, h, behind)
    edge = _rgb(border) if border else None
    body = _rgb(fill)
    for y in range(h):
        for x in range(w):
            outer = _rrect_coverage(x, y, 0, 0, w, h, radius)
            if outer <= 0.0:
                continue
            r.blend(x, y, edge or body, outer)
            if edge:
                r.blend(x, y, body,
                        _rrect_coverage(x, y, 1, 1, w - 2, h - 2, radius - 1))
    return r.photo()


def _in_open_ring(x: float, y: float, cx: float, cy: float, radius: float,
                  half: float, start: float, end: float) -> bool:
    """Inside an annulus, and within the angular sweep that is drawn.

    Angles run clockwise from 12 o'clock, matching `Raster.ring`, so the gap in
    a reload glyph is simply the sweep that is left out.
    """
    d = math.hypot(x - cx, y - cy)
    if abs(d - radius) > half:
        return False
    return start <= (math.atan2(x - cx, -(y - cy)) % TAU) <= end


def _in_triangle(x: float, y: float, a: tuple, b: tuple, c: tuple) -> bool:
    def side(p, q):
        return (q[0] - p[0]) * (y - p[1]) - (q[1] - p[1]) * (x - p[0])
    s1, s2, s3 = side(a, b), side(b, c), side(c, a)
    return (s1 >= 0 and s2 >= 0 and s3 >= 0) or (s1 <= 0 and s2 <= 0 and s3 <= 0)


def reload_icon(size: int = 16, colour: str = None) -> tk.PhotoImage:
    """A circular arrow, drawn rather than borrowed from a font.

    "↻" is U+21BB: present in some UI fonts, missing or comically mismatched in
    others, and it cannot pick up the palette. This is a ring with a gap plus an
    arrowhead, in one flat colour with a real alpha channel, so the same glyph
    sits on a white pill, a teal tile or a dark card.
    """
    r = Raster(size, size, _rgb(colour or theme.PINE), alpha=0)
    _draw_reload(r)
    return r.photo()


def _draw_reload(r: "Raster") -> None:
    """Fill an alpha raster with the reload glyph's coverage."""
    size = r.w
    c = (size - 1) / 2.0
    radius, half = size * 0.32, max(0.85, size * 0.085)
    # The stroke sweeps clockwise and stops at 12 o'clock, where the tangent
    # points right — so that is where the head goes and which way it faces.
    start, end = 0.16 * TAU, TAU
    tip = (c + half * 3.2, c - radius)
    base = ((c - half * 0.5, c - radius - half * 2.2),
            (c - half * 0.5, c - radius + half * 2.2))
    for y in range(size):
        for x in range(size):
            hit = 0
            for sy in range(SCALE):
                py = y + (sy + 0.5) / SCALE
                for sx in range(SCALE):
                    px = x + (sx + 0.5) / SCALE
                    if (_in_open_ring(px, py, c, c, radius, half, start, end)
                            or _in_triangle(px, py, tip, base[0], base[1])):
                        hit += 1
            if hit:
                r.alpha[y * size + x] = round(hit / (SCALE * SCALE) * 255)


def blocked_icon(size: int = 14) -> tk.PhotoImage:
    """The little "blocked" mark shown against each domain row.

    A muted ring with a diagonal bar — drawn rather than depending on an emoji
    font that may or may not be installed and may or may not be colourful.
    """
    r = Raster(size, size, _rgb(theme.SLATE_2), alpha=0)
    c, outer = (size - 1) / 2.0, size / 2.0 - 0.5
    for y in range(size):
        for x in range(size):
            d = math.hypot(x - c, y - c)
            ring = 1.0 - min(1.0, max(0.0, abs(d - (outer - 1.1)) - 0.4))
            # The bar is the distance to the y = x diagonal through the centre.
            bar = 1.0 - min(1.0, max(0.0, abs((x - c) + (y - c)) / 1.4 - 0.5))
            cover = max(ring, bar if d <= outer - 0.6 else 0.0)
            r.alpha[y * size + x] = round(min(1.0, cover) * 210)
    return r.photo()


# --- raster art ------------------------------------------------------------

def _chunk(tag: bytes, data: bytes) -> bytes:
    body = tag + data
    return (struct.pack(">I", len(data)) + body
            + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF))


class Raster:
    """A small pixel buffer with only the primitives the Mist art needs.

    Opaque RGB by default. Pass `alpha` to add a real alpha channel, which is
    what a button pill needs: `round_corners` bakes one backdrop into the
    corners and only looks right where that backdrop actually is, whereas an
    RGBA image can sit on a card, the page or the fog alike. Tk 8.6's
    PhotoImage reads RGBA PNG and composites it, so this costs nothing extra
    at display time.
    """

    def __init__(self, w: int, h: int, fill: tuple = (255, 255, 255),
                 alpha: int = None) -> None:
        self.w, self.h = w, h
        self.buf = bytearray(bytes(fill) * (w * h))
        self.alpha = bytearray([alpha]) * (w * h) if alpha is not None else None

    def copy(self) -> "Raster":
        """A cheap duplicate — used to reuse an expensive backdrop render."""
        clone = Raster.__new__(Raster)
        clone.w, clone.h = self.w, self.h
        clone.buf = bytearray(self.buf)
        clone.alpha = bytearray(self.alpha) if self.alpha is not None else None
        return clone

    def blend(self, x: int, y: int, rgb: tuple, alpha: float) -> None:
        """Paint `rgb` over one pixel at `alpha` (0..1)."""
        if alpha <= 0.0:
            return
        i = (y * self.w + x) * 3
        if alpha >= 1.0:
            self.buf[i:i + 3] = bytes(rgb)
            return
        buf, inv = self.buf, 1.0 - alpha
        for k in range(3):
            buf[i + k] = round(rgb[k] * alpha + buf[i + k] * inv)

    def round_corners(self, radius: float, bg: tuple) -> None:
        """Cut the four corners back to `bg` with anti-aliased coverage.

        With a flat colour behind the image this is indistinguishable from a
        real border-radius, which Tk widgets cannot do at all.
        """
        r = int(math.ceil(radius))
        for cx, cy in ((r, r), (self.w - r, r), (r, self.h - r),
                       (self.w - r, self.h - r)):
            x0 = 0 if cx == r else self.w - r
            y0 = 0 if cy == r else self.h - r
            for y in range(y0, min(self.h, y0 + r)):
                for x in range(x0, min(self.w, x0 + r)):
                    self.blend(x, y, bg, 1.0 - _disc_coverage(x, y, cx, cy, radius))

    def ring(self, cx: float, cy: float, radius: float, width: float,
             frac: float, rgb: tuple) -> None:
        """Stroke `frac` of a turn clockwise from 12 o'clock, with round caps.

        Only the annulus band is visited — a full-image scan would be ~7x the
        pixels for the same result.
        """
        if frac <= 0.0:
            return
        half = width / 2.0
        outer, inner = radius + half + 1.0, max(0.0, radius - half - 1.0)
        solid = half - 0.75           # inside this band a pixel is fully covered
        end = frac * TAU
        caps = _cap_centres(radius, half, frac)
        for y in range(max(0, int(cy - outer)), min(self.h, int(cy + outer) + 1)):
            dy = y + 0.5 - cy
            for x in range(max(0, int(cx - outer)), min(self.w, int(cx + outer) + 1)):
                dx = x + 0.5 - cx
                d = math.hypot(dx, dy)
                if d > outer or d < inner:
                    continue
                # Subsampling only pays for itself on the edges; a pixel well
                # inside the stroke is opaque and can skip all 9 samples.
                if abs(d - radius) <= solid and _well_inside(dx, dy, d, end):
                    self.blend(x, y, rgb, 1.0)
                else:
                    self.blend(x, y, rgb,
                               _arc_coverage(x - cx, y - cy, radius, half, frac, caps))

    def png(self) -> bytes:
        """Encode as PNG — colour type 2 (RGB), or 6 (RGBA) if there is alpha."""
        stride = self.w * 3
        rows = []
        for y in range(self.h):
            row = self.buf[y * stride:(y + 1) * stride]
            if self.alpha is not None:
                row = bytearray()
                for x in range(self.w):
                    i = (y * self.w + x) * 3
                    row += self.buf[i:i + 3]
                    row.append(self.alpha[y * self.w + x])
            rows.append(b"\x00" + bytes(row))
        colour_type = 6 if self.alpha is not None else 2
        return (b"\x89PNG\r\n\x1a\n"
                + _chunk(b"IHDR", struct.pack(">IIBBBBB", self.w, self.h,
                                              8, colour_type, 0, 0, 0))
                + _chunk(b"IDAT", zlib.compress(b"".join(rows), 6))
                + _chunk(b"IEND", b""))

    def photo(self) -> tk.PhotoImage:
        """Hand the buffer to Tk. PhotoImage reads PNG natively in Tk 8.6, so
        no imaging library is involved."""
        return tk.PhotoImage(data=base64.b64encode(self.png()))


def _in_rrect(x: float, y: float, x0: float, y0: float,
              w: float, h: float, radius: float) -> bool:
    """Is a point inside a rounded rectangle?

    Clamping the point into the rect's straight "core" and measuring the
    distance from there handles all four corners and the flat edges with one
    test — inside the core the distance is 0, in a corner it is the distance
    to that corner's arc centre.
    """
    radius = max(0.0, min(radius, w / 2.0, h / 2.0))
    cx = min(max(x, x0 + radius), x0 + w - radius)
    cy = min(max(y, y0 + radius), y0 + h - radius)
    return math.hypot(x - cx, y - cy) <= radius


def _rrect_coverage(px: int, py: int, x0: float, y0: float,
                    w: float, h: float, radius: float) -> float:
    """Fraction of one pixel inside a rounded rect (SCALE x SCALE samples)."""
    hit = 0
    for sy in range(SCALE):
        y = py + (sy + 0.5) / SCALE
        for sx in range(SCALE):
            if _in_rrect(px + (sx + 0.5) / SCALE, y, x0, y0, w, h, radius):
                hit += 1
    return hit / (SCALE * SCALE)


def pill_image(size: int, radius: float, fill: tuple, bg: tuple,
               border: tuple = None, width: float = 1.0) -> tk.PhotoImage:
    """One rounded-rect face, as a tile for a ttk 9-patch element.

    Only `size` x `size` pixels are generated no matter how wide the widget
    ends up: ttk stretches the flat middle and leaves the corner insets alone,
    so one 28px tile dresses a button of any width. That is the whole reason to
    do this as a themed element rather than as a hand-drawn canvas widget —
    ttk keeps hover, press, focus and keyboard traversal.

    `bg` is the colour really behind the widget, and the tile is **opaque**:
    the corners are painted with it rather than left transparent. That is not
    a shortcut, it is the fix for a real defect. With transparent corners Tk
    composites the tile onto whatever is already in the window instead of
    clearing first, so a widget that gets *resized* draws over its own stale
    pixels — measured on a stretched card, the old narrower panel stayed
    visible underneath it. An opaque tile makes every redraw a full overwrite.
    """
    r = Raster(size, size, bg)
    inner = width if border else 0.0
    for y in range(size):
        for x in range(size):
            outside = _rrect_coverage(x, y, 0, 0, size, size, radius)
            if outside <= 0.0:
                continue
            r.blend(x, y, border or fill, outside)
            if border:
                r.blend(x, y, fill, _rrect_coverage(
                    x, y, inner, inner, size - 2 * inner, size - 2 * inner,
                    radius - inner))
    return r.photo()


def _disc_coverage(x: int, y: int, cx: float, cy: float, radius: float) -> float:
    """Fraction of one pixel that falls inside a disc (SCALE x SCALE samples)."""
    hit = 0
    for sy in range(SCALE):
        dy = y + (sy + 0.5) / SCALE - cy
        for sx in range(SCALE):
            dx = x + (sx + 0.5) / SCALE - cx
            if dx * dx + dy * dy <= radius * radius:
                hit += 1
    return hit / (SCALE * SCALE)


def _well_inside(dx: float, dy: float, d: float, end: float) -> bool:
    """True when a pixel is more than a pixel clear of both boundary rays.

    Conservative on purpose: a false negative only costs a subsampled pixel,
    while a false positive would show as a hard aliased edge.
    """
    if end >= TAU:
        return True
    ang = math.atan2(dx, -dy) % TAU
    if not 0.0 < ang < end:
        return False
    return d * min(ang, end - ang) > 1.0


def _cap_centres(radius: float, half: float, frac: float) -> tuple:
    """Centres of the two round stroke caps, relative to the ring centre."""
    if frac >= 1.0:
        return ()
    end = frac * TAU
    return ((0.0, -radius),
            (radius * math.sin(end), -radius * math.cos(end)))


def _arc_coverage(px: float, py: float, radius: float, half: float,
                  frac: float, caps: tuple) -> float:
    hit = 0
    for sy in range(SCALE):
        dy = py + (sy + 0.5) / SCALE
        for sx in range(SCALE):
            dx = px + (sx + 0.5) / SCALE
            if _in_arc(dx, dy, radius, half, frac, caps):
                hit += 1
    return hit / (SCALE * SCALE)


def _in_arc(dx: float, dy: float, radius: float, half: float,
            frac: float, caps: tuple) -> bool:
    if abs(math.hypot(dx, dy) - radius) <= half:
        if frac >= 1.0 or math.atan2(dx, -dy) % TAU <= frac * TAU:
            return True
    return any(math.hypot(dx - qx, dy - qy) <= half for qx, qy in caps)


class Fog:
    """The Mist background field: a vertical gradient plus three soft blobs.

    Colour is a pure function of absolute (x, y), which is the point: the
    countdown ring has to re-render its own patch of this exact field as a
    backdrop, and a pure function guarantees the patch lines up seamlessly.
    The blobs need no blur pass — a smoothstep falloff *is* the soft edge.
    """

    # Where each blob sits, as a fraction of the field. Only the geometry is
    # fixed here; the colours come from the active palette, because on Ink a
    # blob has to glow lighter than the field where on Mist it settles darker.
    PLACES = ((-0.05, -0.60, 0.70), (0.99, 0.05, 0.52), (0.40, 1.60, 0.75))

    def __init__(self, w: int, h: int, top: tuple = None, bottom: tuple = None) -> None:
        self.w, self.h = max(1, w), max(1, h)
        self.top = top or theme.FOG_TOP_RGB
        self.bottom = bottom or theme.FOG_BOT_RGB
        self.blobs = tuple(
            (fx * w, fy * h, fr * w, rgb, alpha)
            for (fx, fy, fr), (rgb, alpha) in zip(self.PLACES, theme.BLOBS))

    def color_at(self, x: float, y: float) -> tuple:
        t = min(1.0, max(0.0, y / max(1, self.h - 1)))
        rgb = [self.top[k] + (self.bottom[k] - self.top[k]) * t
               for k in range(3)]
        for bx, by, br, brgb, ba in self.blobs:
            d = math.hypot(x - bx, y - by)
            if d >= br:
                continue
            u = 1.0 - d / br
            a = ba * u * u * (3.0 - 2.0 * u)      # smoothstep = the "blur"
            rgb = [rgb[k] + (brgb[k] - rgb[k]) * a for k in range(3)]
        return (round(rgb[0]), round(rgb[1]), round(rgb[2]))

    def raster(self, x0: int, y0: int, w: int, h: int, step: int = 1) -> Raster:
        """Render a sub-region. `step` renders every Nth pixel, for callers
        that will `PhotoImage.zoom(step)` it back — the field is smooth
        everywhere, so nothing visible is lost and it is N^2 cheaper."""
        out = Raster(max(1, w // step), max(1, h // step))
        stride = out.w * 3
        for j in range(out.h):
            row = bytearray()
            for i in range(out.w):
                row += bytes(self.color_at(x0 + i * step, y0 + j * step))
            out.buf[j * stride:(j + 1) * stride] = row
        return out


class RingArt:
    """The countdown ring, re-rendered only when its rounded fraction moves.

    The GUI ticks at 1 Hz. Re-encoding a PNG every tick to advance the arc by
    a fraction of a pixel is pure waste, so the fraction is quantised into
    STEPS buckets. Progress is monotonic, so a bucket is never revisited and
    caching more than the current image would be waste of a second kind.
    """

    STEPS = 120

    def __init__(self, fog: Fog, size: int, stroke: int = 9) -> None:
        self.fog, self.size, self.stroke = fog, size, stroke
        self._key = None
        self._image = None
        self._base_key = None
        self._base = None

    def key(self, frac: float, locked: bool, origin: tuple) -> tuple:
        bucket = max(0, min(self.STEPS, int(round(frac * self.STEPS))))
        return (bucket, bool(locked), origin)

    def image(self, key: tuple) -> tk.PhotoImage:
        """The ring for `key`, rendering it only if it is not the current one."""
        if key != self._key:
            self._image = self._render(*key)
            self._key = key
        return self._image

    def _render(self, bucket: int, locked: bool, origin: tuple) -> tk.PhotoImage:
        r = self._backdrop(locked, origin).copy()
        c = self.size / 2.0
        r.ring(c, c, c - self.stroke / 2.0 - 2, self.stroke,
               bucket / self.STEPS,
               theme.AMBER_RGB if locked else theme.TEAL_RGB)
        return r.photo()

    def _backdrop(self, locked: bool, origin: tuple) -> Raster:
        """Fog patch + empty track. Neither depends on the countdown, so this
        is rendered once and copied — it is most of the cost of a ring."""
        key = (locked, origin)
        if key != self._base_key:
            # The backdrop is the real fog at the ring's real position, so the
            # image edges vanish into the hero instead of showing a seam.
            base = self.fog.raster(origin[0], origin[1], self.size, self.size)
            c = self.size / 2.0
            base.ring(c, c, c - self.stroke / 2.0 - 2, self.stroke, 1.0,
                      theme.AMBER_TINT_RGB if locked else theme.TEAL_TINT_RGB)
            self._base, self._base_key = base, key
        return self._base


def mark_image(size: int = 28, bg: tuple = None) -> tk.PhotoImage:
    """The app mark: a rounded teal tile, lit from the top left, holding the
    reload glyph in white.

    The tile keeps Mist's teals in both schemes — a logo that restyles itself
    stops being a logo — so only the corner cut-out follows the palette.
    """
    r = Raster(size, size, (0x21, 0x74, 0x80))
    for y in range(size):
        for x in range(size):
            d = math.hypot(x - size * 0.3, y - size * 0.2) / (size * 1.15)
            r.blend(x, y, (0x52, 0xB3, 0xBF), max(0.0, 1.0 - d) ** 1.5)
    _stamp_glyph(r, reload_glyph_mask(round(size * 0.62)), (0xFF, 0xFF, 0xFF))
    r.round_corners(size * 0.32, bg or theme.CARD_RGB)
    return r.photo()


def reload_glyph_mask(size: int) -> "Raster":
    """The reload glyph as coverage only, for stamping onto another raster."""
    mask = Raster(size, size, (0, 0, 0), alpha=0)
    _draw_reload(mask)
    return mask


def _stamp_glyph(target: "Raster", mask: "Raster", rgb: tuple) -> None:
    """Composite a coverage mask onto `target`, centred."""
    ox, oy = (target.w - mask.w) // 2, (target.h - mask.h) // 2
    for y in range(mask.h):
        for x in range(mask.w):
            target.blend(ox + x, oy + y, rgb, mask.alpha[y * mask.w + x] / 255.0)
