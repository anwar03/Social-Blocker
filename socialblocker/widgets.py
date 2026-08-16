"""Composite Mist widgets for the GUI — presentation only.

Outer circle, same as `gui.py` and `mistkit.py`: nothing here imports
`control`, `config` or the engine, and nothing here decides policy. Each class
takes plain values and callbacks, so `gui.py` stays the only place that knows
what a mode or a session *is*.

Split out of `gui.py` purely for size: these are the pieces the Mist layout
needs that Tk does not ship — a pill group backed by ttk's `selected` state,
a stepper on a rounded panel, a tab strip with count badges, and the domain
list.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import font as tkfont, ttk

from . import mistkit as mk


class PillGroup(tk.Frame):
    """A row of rounded choice buttons; exactly one is selected.

    Selection is ttk's own `selected` state rather than a style swap, so the
    themed element picks the right face and the widget keeps its focus ring.

    `stretch` turns the row into a segmented control: equal columns that divide
    the parent's width, for a group that owns its whole line. Left off, each
    pill is its own label's width — which is what a group sharing a line with
    something else (the composer's, beside the stepper) needs. The pill face is
    a 9-patch, so widening a button re-tiles its edges and leaves the corner
    radius alone.

    `height` pins the row instead of letting the pills' own font decide it —
    for a group sharing a line with a taller control, so the two agree on any
    font rather than only on the machine they were measured on. Same 9-patch
    reasoning as `stretch`: growing a pill re-tiles its edges, not its corners.
    """

    def __init__(self, parent, options, command, background=None, gap=6,
                 stretch=False, height=None):
        super().__init__(parent, background=background or mk.theme.CARD)
        self.buttons = {}
        if height:
            # Geometry propagation off, or the tallest pill would set the
            # height back. Width still comes from the parent's cell.
            self.configure(height=height)
            self.grid_propagate(False)
            self.rowconfigure(0, weight=1)
        for i, (value, label) in enumerate(options):
            b = ttk.Button(self, text=label, style="Pill.TButton",
                           takefocus=True, command=lambda v=value: command(v))
            if stretch:
                # The gaps are their own fixed columns rather than padding
                # inside the pill columns. `uniform` equalises *columns*, so
                # padding there would come out of the pill and leave whichever
                # one carries no trailing gap wider than its neighbours.
                column = i * 2
                if i:
                    self.columnconfigure(column - 1, minsize=gap)
                self.columnconfigure(column, weight=1, uniform="pill")
                b.grid(row=0, column=column, sticky="nsew" if height else "ew")
            else:
                b.pack(side="left", padx=(0, gap))
            self.buttons[value] = b

    def select(self, value) -> None:
        for other, button in self.buttons.items():
            button.state(["selected"] if other == value else ["!selected"])


class Stepper(tk.Canvas):
    """`- 50 min +` inside one rounded panel.

    A canvas because Tk cannot round a container: the panel is a generated
    image and the three controls are canvas windows on top of it. It never
    needs a resize repaint — but its width is *measured*, not fixed. Every
    part of it is a function of the resolved UI font, and a hard-coded panel
    that fits on one machine has the value sitting on top of the `-` button on
    the next.
    """

    HEIGHT, RADIUS = 40, 11
    MIN_WIDTH = 152     # so a narrow font still gives a panel, not a sliver
    EDGE = 6            # panel edge to a step button
    SIDE = HEIGHT - 2 * EDGE    # the step buttons are square, so one side
    GAP = 12            # step button to the value group
    UNIT_GAP = 5        # the value to its "min"

    def __init__(self, parent, variable, on_step, fonts, background=None):
        self._bg = background or mk.theme.CARD
        super().__init__(parent, height=self.HEIGHT, background=self._bg,
                         highlightthickness=0, bd=0)
        # No `width=`: that is in characters, and the canvas item below sets
        # the real size in pixels. Two sizing rules would just disagree.
        minus = ttk.Button(self, text="−", style="Step.TButton",
                           command=lambda: on_step(-5))
        plus = ttk.Button(self, text="+", style="Step.TButton",
                          command=lambda: on_step(5))
        # A classic tk.Entry, not ttk: the panel already draws the border, and
        # a ttk.Entry would paint its own rounded face inside this one.
        entry = tk.Entry(self, textvariable=variable, width=4, justify="center",
                         font=fonts.ui_bold, background=mk.theme.SUNK,
                         foreground=mk.theme.PINE, insertbackground=mk.theme.PINE,
                         relief="flat", highlightthickness=0, bd=0)
        self._place(minus, plus, entry, fonts)

    def _place(self, minus, plus, entry, fonts) -> None:
        """Size the panel to its contents, then lay them out on it.

        The two step buttons are the exception to the measuring: they are
        given `SIDE` on both axes rather than their requested width, because
        "square" has to survive a font change. A ttk button sizes to its
        label, and `−` and `+` do not measure the same in every face — left
        to themselves they would be two different rectangles.
        """
        unit = tkfont.Font(family=fonts.small[0], size=fonts.small[1]).measure("min")
        value = entry.winfo_reqwidth() + self.UNIT_GAP + unit
        width = max(self.MIN_WIDTH,
                    2 * (self.EDGE + self.SIDE + self.GAP) + value)
        self.configure(width=width)
        self._panel = mk.rounded_rect(width, self.HEIGHT, self.RADIUS,
                                      mk.theme.SUNK, mk.theme.LINE_SOFT, self._bg)
        self.create_image(0, 0, anchor="nw", image=self._panel)
        middle = self.HEIGHT // 2
        self.create_window(self.EDGE, middle, anchor="w", window=minus,
                           width=self.SIDE, height=self.SIDE)
        self.create_window(width - self.EDGE, middle, anchor="e", window=plus,
                           width=self.SIDE, height=self.SIDE)
        # The value group is centred on the panel, not on the space between the
        # buttons: the two are the same thing while the buttons match, and this
        # keeps "min" reading as part of the number if they ever stop matching.
        left = (width - value) / 2
        self.create_window(left, middle, anchor="w", window=entry)
        self.create_text(left + entry.winfo_reqwidth() + self.UNIT_GAP, middle,
                         anchor="w", text="min", fill=mk.theme.SLATE,
                         font=fonts.small)


class TabStrip(tk.Frame):
    """Text tabs with a count badge and an underline on the active one.

    Not a `ttk.Notebook`: the panels below are swapped by the caller, and a
    notebook would bring its own tab chrome that cannot be made to look like
    this. A tab is a label plus a 2px underline frame that is simply recoloured.
    """

    def __init__(self, parent, tabs, command, fonts, background=None):
        bg = background or mk.theme.CARD
        super().__init__(parent, background=bg)
        self._parts = {}
        self._fonts = fonts
        for value, label in tabs:
            holder = tk.Frame(self, background=bg)
            holder.pack(side="left", padx=(0, 20))
            row = tk.Frame(holder, background=bg)
            row.pack()
            name = tk.Label(row, text=label, background=bg, font=fonts.ui_bold,
                            foreground=mk.theme.SLATE)
            name.pack(side="left")
            badge = tk.Label(row, text="0", background=mk.theme.SUNK,
                             foreground=mk.theme.SLATE, font=fonts.small_bold,
                             padx=6, pady=1)
            badge.pack(side="left", padx=(7, 0))
            rule = tk.Frame(holder, height=2, background=bg)
            rule.pack(fill="x", pady=(7, 0))
            for widget in (holder, row, name, badge):
                widget.bind("<Button-1>", lambda _e, v=value: command(v))
            self._parts[value] = (name, badge, rule)

    def set_count(self, value, count: int) -> None:
        self._parts[value][1].configure(text=str(count))

    def select(self, value) -> None:
        for other, (name, badge, rule) in self._parts.items():
            on = other == value
            name.configure(foreground=mk.theme.TEAL_DEEP if on else mk.theme.SLATE)
            badge.configure(
                background=mk.theme.TEAL_TINT if on else mk.theme.SUNK,
                foreground=mk.theme.TEAL_DEEP if on else mk.theme.SLATE)
            rule.configure(background=mk.theme.TEAL if on else mk.theme.CARD)


class DomainList(tk.Frame):
    """The scrollable domain rows, each with a "blocked" mark.

    A `ttk.Treeview` in tree-only mode: it is the sole stock widget that can
    put an image on a row, and unlike `tk.Listbox` it is themeable, so it
    follows the palette on a light/dark switch like everything else.
    """

    def __init__(self, parent, fonts, height=8, background=None):
        super().__init__(parent, background=background or mk.theme.CARD)
        self.icon = mk.blocked_icon()          # one image, shared by every row
        self.tree = ttk.Treeview(self, style="Domains.Treeview", height=height,
                                 selectmode="browse", show="tree")
        bar = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=bar.set)
        bar.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)

    def fill(self, domains) -> None:
        keep = self.selected()
        self.tree.delete(*self.tree.get_children())
        for domain in domains:
            self.tree.insert("", "end", iid=domain, text="  " + domain,
                             image=self.icon)
        # Refilling on every change would otherwise silently drop the user's
        # selection, and Remove reads exactly that.
        if keep and self.tree.exists(keep):
            self.tree.selection_set(keep)

    def selected(self):
        chosen = self.tree.selection()
        return chosen[0] if chosen else None


class StatusPill(tk.Canvas):
    """Title-bar state chip: a coloured dot plus one word, in a rounded pill.

    A canvas so the pill can actually be round — `tk.Frame`'s
    `highlightthickness` border is always a rectangle. The panel image depends
    only on the width, and there are five possible labels, so the handful of
    widths that occur are cached rather than re-rasterised on every tick.
    """

    HEIGHT = 30
    PAD, DOT, GAP = 13, 8, 8

    def __init__(self, parent, fonts, background=None):
        self._bg = background or mk.theme.CARD
        super().__init__(parent, height=self.HEIGHT, width=self.HEIGHT,
                         background=self._bg, highlightthickness=0, bd=0)
        self._font = tkfont.Font(font=fonts.small_bold)
        self._panels: dict = {}
        self._width = 0
        self._image = self.create_image(0, 0, anchor="nw")
        mid = self.HEIGHT / 2.0
        self._blob = self.create_oval(self.PAD, mid - self.DOT / 2,
                                      self.PAD + self.DOT, mid + self.DOT / 2,
                                      outline="", fill=mk.theme.TEAL)
        self._label = self.create_text(self.PAD + self.DOT + self.GAP, mid,
                                       anchor="w", fill=mk.theme.PINE,
                                       font=fonts.small_bold, text="…")

    def render(self, label: str, colour: str) -> None:
        self.itemconfigure(self._label, text=label)
        self.itemconfigure(self._blob, fill=colour)
        width = (self.PAD * 2 + self.DOT + self.GAP
                 + self._font.measure(label))
        if width != self._width:
            self._width = width
            self.configure(width=width)
            self.itemconfigure(self._image, image=self._panel(width))

    def _panel(self, width: int):
        if width not in self._panels:
            self._panels[width] = mk.rounded_rect(
                width, self.HEIGHT, self.HEIGHT / 2.0, mk.theme.WHITE,
                mk.theme.LINE, self._bg)
        return self._panels[width]


class Scroller(tk.Frame):
    """A vertically scrollable body.

    The full Mist layout is taller than a 768px laptop screen, so the window
    stays usable by scrolling rather than by cutting sections.
    """

    WHEEL = ("<Button-4>", "<Button-5>", "<MouseWheel>")

    def __init__(self, parent):
        super().__init__(parent, background=mk.theme.SUNK)
        self.canvas = tk.Canvas(self, background=mk.theme.SUNK,
                                highlightthickness=0, bd=0)
        bar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=bar.set)
        bar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.inner = tk.Frame(self.canvas, background=mk.theme.SUNK)
        self._win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", lambda e: self.canvas.configure(
            scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(
            self._win, width=e.width))
        # bind_all, so the wheel works while the pointer is over any child.
        # The flip side: these outlive this widget, so `release` must be called
        # before a Scroller is destroyed — see App._restyle.
        for seq in self.WHEEL:
            self.canvas.bind_all(seq, self._on_wheel)
        # Building the page leaves the view wherever the last child landed
        # (measured: 0.127 down, i.e. the bottom). A page opens at the top.
        self.after_idle(lambda: self.canvas.yview_moveto(0.0))

    def release(self) -> None:
        """Drop the application-level wheel bindings.

        Destroying the widget does not remove them — they live on the "all"
        bindtag — so a rebuilt window would stack a second handler on top of
        one pointing at a dead canvas, and the next scroll would raise.
        """
        for seq in self.WHEEL:
            self.unbind_all(seq)

    def _on_wheel(self, event) -> None:
        # Leave the domain list its own wheel; only the page scrolls here.
        if isinstance(event.widget, ttk.Treeview):
            return
        up = getattr(event, "num", 0) == 4 or getattr(event, "delta", 0) > 0
        self.canvas.yview_scroll(-1 if up else 1, "units")
