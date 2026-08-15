"""Mist design system for the SocialBlocker GUI — tokens, ttk theme, raster art.

Outer-circle adapter (CLAUDE.md section 5): this module imports nothing from
this package and knows nothing about blocking. `gui.py` asks it for colours,
fonts, styled containers and two pieces of generated art; every decision about
*what* to show stays in `gui.py`.

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
import struct
import zlib
import tkinter as tk
from tkinter import font as tkfont, ttk

TAU = math.pi * 2
SCALE = 3           # subsamples per axis for edges; 9 samples per pixel


# --- tokens ----------------------------------------------------------------
# Straight from SocialBlocker-Mist-Desktop.html. Tk has no alpha channel, so
# the mockup's rgba() tokens are composited against their real backdrop here,
# once, instead of being faked at paint time.

def _hex(rgb: tuple) -> str:
    return "#%02x%02x%02x" % rgb


def _over(fg: tuple, bg: tuple, alpha: float) -> tuple:
    """Composite `fg` over `bg` at `alpha`, returning an opaque colour."""
    return tuple(round(f * alpha + b * (1 - alpha)) for f, b in zip(fg, bg))


FOG_TOP_RGB = (0xEE, 0xF3, 0xF4)
FOG_BOT_RGB = (0xD9, 0xE3, 0xE6)
CARD_RGB = (0xFB, 0xFD, 0xFD)
PINE_RGB = (0x16, 0x27, 0x2C)
TEAL_RGB = (0x2F, 0x8F, 0x9D)
TEAL_DEEP_RGB = (0x21, 0x74, 0x80)
AMBER_RGB = (0xB9, 0x77, 0x2F)
INK_RGB = (0x15, 0x26, 0x2B)        # the base of every rgba() line/shadow

FOG_TOP = _hex(FOG_TOP_RGB)
SUNK = FOG_TOP                       # --sunk and --fog-top are the same value
CARD = _hex(CARD_RGB)
WHITE = "#ffffff"
PINE = _hex(PINE_RGB)
SLATE = "#5f7378"
SLATE_2 = "#85989d"
TEAL = _hex(TEAL_RGB)
TEAL_DEEP = _hex(TEAL_DEEP_RGB)
AMBER = _hex(AMBER_RGB)
DANGER = "#b6503f"

LINE = _hex(_over(INK_RGB, CARD_RGB, 0.10))
LINE_SOFT = _hex(_over(INK_RGB, CARD_RGB, 0.06))
TEAL_TINT = _hex(_over(TEAL_RGB, CARD_RGB, 0.12))
TEAL_TINT_RGB = _over(TEAL_RGB, CARD_RGB, 0.14)
AMBER_TINT = _hex(_over(AMBER_RGB, CARD_RGB, 0.12))
AMBER_TINT_RGB = _over(AMBER_RGB, CARD_RGB, 0.16)


# --- typography ------------------------------------------------------------
# The mockup's Manrope + Instrument Serif are not vendored: install.sh runs as
# root and would have to guess the real user's HOME to place them. Instead we
# take the best installed match, so the look improves for free if they are ever
# installed system-wide.

UI_STACK = ("Manrope", "Inter", "Cantarell", "Ubuntu", "Noto Sans", "DejaVu Sans")
DISPLAY_STACK = ("Instrument Serif", "Bitstream Charter", "Charter",
                 "Georgia", "DejaVu Serif", "Liberation Serif")


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
        self.ui_family, self.display_family = ui, display
        self.ui = (ui, 10)
        self.ui_bold = (ui, 10, "bold")
        self.small = (ui, 9)
        self.small_bold = (ui, 9, "bold")
        self.eyebrow = (ui, 8, "bold")
        self.button = (ui, 10, "bold")
        self.h1 = (display, 25)
        self.numeral = (display, 21)
        self.ring = (display, 23)
        self.mark = (display, 14)


def track(text: str) -> str:
    """Stand-in for the mockup's `letter-spacing` on small caps labels.

    Tk fonts expose no tracking control, so a thin space between characters is
    the only way to get that airy uppercase look. Short labels only.
    """
    return " ".join(text)


# --- ttk theme -------------------------------------------------------------

def apply_theme(root: tk.Misc) -> Fonts:
    """Repaint ttk with the Mist palette; returns the resolved font roles."""
    fonts = Fonts()
    st = ttk.Style(root)
    # clam is the only built-in theme on Linux that honours per-element
    # colours; the others ignore most `configure` calls outright.
    st.theme_use("clam")
    root.configure(background=SUNK)
    st.configure(".", background=SUNK, foreground=PINE, font=fonts.ui,
                 borderwidth=0, focuscolor=TEAL)
    _style_labels(st, fonts)
    _style_buttons(st, fonts)
    _style_inputs(st, fonts)
    _style_containers(st, fonts)
    return fonts


def _style_labels(st: ttk.Style, fonts: Fonts) -> None:
    st.configure("TLabel", background=SUNK, foreground=PINE, font=fonts.ui)
    st.configure("Muted.TLabel", foreground=SLATE, font=fonts.small)
    # Everything below sits on a card, which is a lighter surface than the
    # window. ttk resolves "A.B.TLabel" by falling back to "B.TLabel", so
    # these all inherit the card background from one place.
    st.configure("Card.TLabel", background=CARD, foreground=PINE)
    st.configure("Eyebrow.Card.TLabel", foreground=SLATE, font=fonts.eyebrow)
    st.configure("Muted.Card.TLabel", foreground=SLATE, font=fonts.small)
    st.configure("Faint.Card.TLabel", foreground=SLATE_2, font=fonts.small)
    st.configure("Strong.Card.TLabel", font=fonts.ui_bold)
    st.configure("Numeral.Card.TLabel", font=fonts.numeral)
    st.configure("Unit.Card.TLabel", foreground=SLATE, font=fonts.small_bold)
    st.configure("Amber.Card.TLabel", foreground=AMBER, font=fonts.small_bold)


def _flat(st: ttk.Style, name: str, bg: str, fg: str, hover_bg: str,
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
                 relief="flat", padding=pad, font=font, focuscolor=TEAL)
    st.map(name,
           background=[("disabled", SUNK), ("pressed", hover_bg), ("active", hover_bg)],
           foreground=[("disabled", SLATE_2), ("active", hover_fg)],
           bordercolor=[("disabled", LINE_SOFT), ("active", TEAL)],
           lightcolor=[("active", hover_bg)], darkcolor=[("active", hover_bg)])


def _style_buttons(st: ttk.Style, fonts: Fonts) -> None:
    _flat(st, "TButton", CARD, PINE, WHITE, TEAL_DEEP, LINE, fonts.ui)
    _flat(st, "Primary.TButton", TEAL, WHITE, TEAL_DEEP, WHITE, TEAL,
          fonts.button, (16, 10))
    _flat(st, "Ghost.TButton", CARD, PINE, WHITE, TEAL_DEEP, LINE, fonts.button)
    _flat(st, "Danger.TButton", CARD, PINE, WHITE, DANGER, LINE, fonts.button)
    # Segmented control: the sunk track is the parent frame, so an unselected
    # segment is simply invisible against it and the selected one is white.
    _flat(st, "Seg.TButton", SUNK, SLATE, WHITE, PINE, SUNK, fonts.ui, (10, 7))
    _flat(st, "SegOn.TButton", WHITE, PINE, WHITE, PINE, WHITE, fonts.ui_bold, (10, 7))
    _flat(st, "Chip.TButton", WHITE, SLATE, WHITE, TEAL_DEEP, LINE_SOFT,
          fonts.small_bold, (8, 6))
    _flat(st, "Preset.TButton", WHITE, PINE, WHITE, TEAL_DEEP, LINE_SOFT,
          fonts.ui, (12, 9))
    st.configure("Preset.TButton", anchor="w", justify="left")
    _flat(st, "Step.TButton", SUNK, PINE, WHITE, TEAL_DEEP, SUNK, fonts.ui_bold, (9, 3))


def _style_inputs(st: ttk.Style, fonts: Fonts) -> None:
    st.configure("TEntry", fieldbackground=WHITE, foreground=PINE,
                 bordercolor=LINE, lightcolor=LINE, darkcolor=LINE,
                 insertcolor=PINE, borderwidth=1, padding=5)
    st.map("TEntry", bordercolor=[("focus", TEAL)], lightcolor=[("focus", TEAL)])
    for kind in ("TCheckbutton", "TRadiobutton"):
        st.configure(kind, background=SUNK, foreground=PINE, font=fonts.ui,
                     focuscolor=TEAL, indicatorcolor=WHITE,
                     bordercolor=LINE, lightcolor=WHITE, darkcolor=WHITE)
        st.configure("Card." + kind, background=CARD)
        st.map("Card." + kind, background=[("active", CARD)],
               indicatorcolor=[("selected", TEAL)], foreground=[("active", PINE)])
        st.map(kind, background=[("active", SUNK)],
               indicatorcolor=[("selected", TEAL)], foreground=[("active", PINE)])
    st.configure("Lock.Card.TCheckbutton", foreground=AMBER, font=fonts.ui_bold)
    st.map("Lock.Card.TCheckbutton", indicatorcolor=[("selected", AMBER)])


def _style_containers(st: ttk.Style, fonts: Fonts) -> None:
    st.configure("TFrame", background=SUNK)
    st.configure("Card.TFrame", background=CARD)
    st.configure("Sunk.TFrame", background=SUNK)
    st.configure("TNotebook", background=CARD, borderwidth=0, tabmargins=(0, 4, 0, 0))
    st.configure("TNotebook.Tab", background=SUNK, foreground=SLATE,
                 font=fonts.ui, padding=(16, 7), borderwidth=0,
                 lightcolor=SUNK, darkcolor=SUNK, bordercolor=SUNK)
    st.map("TNotebook.Tab",
           background=[("selected", WHITE), ("active", WHITE)],
           foreground=[("selected", PINE)],
           lightcolor=[("selected", WHITE)], darkcolor=[("selected", WHITE)],
           bordercolor=[("selected", LINE_SOFT)])
    st.configure("TScrollbar", background=SLATE_2, troughcolor=SUNK,
                 bordercolor=SUNK, arrowcolor=SLATE, lightcolor=SUNK,
                 darkcolor=SUNK, borderwidth=0)
    st.map("TScrollbar", background=[("active", SLATE)])


def card_options(pad: int = 14, bg: str = CARD) -> dict:
    """The `tk.Frame` options that make a Mist surface card.

    Deliberately a `tk.Frame`, not `ttk.Frame`: `highlightbackground` is the
    only reliable way to get an exact 1px border colour on Linux, and ttk
    frames have no border-colour element at all. Exposed as options, not only
    as a factory, so a widget subclass can *be* a card.
    """
    return dict(background=bg, highlightbackground=LINE_SOFT,
                highlightcolor=LINE_SOFT, highlightthickness=1,
                bd=0, padx=pad, pady=pad)


def card(parent: tk.Misc, pad: int = 14, bg: str = CARD) -> tk.Frame:
    """A Mist surface card."""
    return tk.Frame(parent, **card_options(pad, bg))


def style_listbox(lb: tk.Listbox, fonts: Fonts) -> None:
    """Mist colours for the one classic Tk widget with no ttk equivalent."""
    lb.configure(background=WHITE, foreground=PINE, font=fonts.ui,
                 selectbackground=TEAL_TINT, selectforeground=PINE,
                 highlightbackground=LINE_SOFT, highlightcolor=LINE,
                 highlightthickness=1, borderwidth=0, activestyle="none",
                 relief="flat")


# --- raster art ------------------------------------------------------------

def _chunk(tag: bytes, data: bytes) -> bytes:
    body = tag + data
    return (struct.pack(">I", len(data)) + body
            + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF))


class Raster:
    """A small RGB pixel buffer with only the primitives the Mist art needs."""

    def __init__(self, w: int, h: int, fill: tuple = (255, 255, 255)) -> None:
        self.w, self.h = w, h
        self.buf = bytearray(bytes(fill) * (w * h))

    def copy(self) -> "Raster":
        """A cheap duplicate — used to reuse an expensive backdrop render."""
        clone = Raster.__new__(Raster)
        clone.w, clone.h = self.w, self.h
        clone.buf = bytearray(self.buf)
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
        """Encode as a truecolour PNG (colour type 2, no interlace)."""
        stride = self.w * 3
        raw = b"".join(b"\x00" + bytes(self.buf[y * stride:(y + 1) * stride])
                       for y in range(self.h))
        return (b"\x89PNG\r\n\x1a\n"
                + _chunk(b"IHDR", struct.pack(">IIBBBBB", self.w, self.h,
                                              8, 2, 0, 0, 0))
                + _chunk(b"IDAT", zlib.compress(raw, 6))
                + _chunk(b"IEND", b""))

    def photo(self) -> tk.PhotoImage:
        """Hand the buffer to Tk. PhotoImage reads PNG natively in Tk 8.6, so
        no imaging library is involved."""
        return tk.PhotoImage(data=base64.b64encode(self.png()))


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

    # The hero panel in the mockup is near-white with the fog drifting behind
    # it, so its gradient starts much lighter than the page's own --fog-top.
    PANEL_TOP = (0xFC, 0xFE, 0xFE)
    PANEL_BOT = (0xE3, 0xEC, 0xEE)

    def __init__(self, w: int, h: int, top: tuple = None, bottom: tuple = None) -> None:
        self.w, self.h = max(1, w), max(1, h)
        self.top = top or FOG_TOP_RGB
        self.bottom = bottom or FOG_BOT_RGB
        self.blobs = (
            (-0.05 * w, -0.60 * h, 0.70 * w, (0xB4, 0xD6, 0xDC), 0.34),
            (0.99 * w, 0.05 * h, 0.52 * w, TEAL_RGB, 0.15),
            (0.40 * w, 1.60 * h, 0.75 * w, (0xD2, 0xE4, 0xE7), 0.42),
        )

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
               bucket / self.STEPS, AMBER_RGB if locked else TEAL_RGB)
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
                      AMBER_TINT_RGB if locked else TEAL_TINT_RGB)
            self._base, self._base_key = base, key
        return self._base


def mark_image(size: int = 26, bg: tuple = CARD_RGB) -> tk.PhotoImage:
    """The app mark: a rounded teal tile with a light source at the top left."""
    r = Raster(size, size, TEAL_DEEP_RGB)
    for y in range(size):
        for x in range(size):
            d = math.hypot(x - size * 0.3, y - size * 0.2) / (size * 1.15)
            r.blend(x, y, (0x52, 0xB3, 0xBF), max(0.0, 1.0 - d) ** 1.5)
    r.round_corners(size * 0.32, bg)
    return r.photo()
