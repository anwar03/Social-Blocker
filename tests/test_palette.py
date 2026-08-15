"""Palette + colour-scheme-detection tests.

Run from the repo root:

    python3 -m unittest discover -s tests

`mistkit.Palette` is pure arithmetic on colours, so these need no Tk root, no
display and no root privileges. The point is to keep a future palette edit from
quietly wrecking legibility: contrast is the thing a screenshot review is worst
at judging and a ratio is best at.
"""

import os
import unittest

from socialblocker import mistkit as mk


def _relative_luminance(rgb):
    """WCAG 2.x relative luminance of an 8-bit sRGB triple."""
    channels = []
    for value in rgb:
        v = value / 255.0
        channels.append(v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4)
    r, g, b = channels
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(fg_hex, bg_hex):
    """WCAG contrast ratio between two "#rrggbb" strings (1.0 .. 21.0)."""
    def rgb(h):
        h = h.lstrip("#")
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    a, b = _relative_luminance(rgb(fg_hex)), _relative_luminance(rgb(bg_hex))
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)


class ContrastTests(unittest.TestCase):
    """Every text role has to stay readable on its own surface."""

    # 4.5 is WCAG AA for body text; the small-caps "faint" role is the one
    # deliberately below it, as a de-emphasis device, so it gets AA-large.
    BODY_MIN = 4.5
    FAINT_MIN = 2.9

    def test_text_roles_are_legible_on_their_card(self):
        for pal in (mk.MIST, mk.INK):
            for role in ("PINE", "SLATE", "DANGER"):
                with self.subTest(palette=pal.name, role=role):
                    self.assertGreaterEqual(
                        _contrast(getattr(pal, role), pal.CARD), self.BODY_MIN)
            with self.subTest(palette=pal.name, role="SLATE_2"):
                self.assertGreaterEqual(
                    _contrast(pal.SLATE_2, pal.CARD), self.FAINT_MIN)

    def test_accent_fills_carry_their_own_label(self):
        """ON_ACCENT is what sits on a TEAL fill — the Primary button, a tick."""
        for pal in (mk.MIST, mk.INK):
            with self.subTest(palette=pal.name):
                self.assertGreaterEqual(_contrast(pal.ON_ACCENT, pal.TEAL), 3.0)

    def test_surfaces_are_distinguishable(self):
        """Elevation has to be *visible*, or every card edge disappears."""
        for pal in (mk.MIST, mk.INK):
            with self.subTest(palette=pal.name):
                self.assertNotEqual(pal.SUNK, pal.CARD)
                self.assertNotEqual(pal.CARD, pal.WHITE)
                # A hairline that matches its card is not a hairline.
                self.assertNotEqual(pal.LINE_SOFT, pal.CARD)


class PaletteShapeTests(unittest.TestCase):

    def test_ink_inverts_the_elevation_order(self):
        """Mist raises surfaces towards white; Ink raises them away from black."""
        lum = lambda h: _relative_luminance(  # noqa: E731
            tuple(int(h.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)))
        self.assertLess(lum(mk.MIST.SUNK), lum(mk.MIST.CARD))
        self.assertLess(lum(mk.MIST.CARD), lum(mk.MIST.WHITE))
        self.assertLess(lum(mk.INK.SUNK), lum(mk.INK.CARD))
        self.assertLess(lum(mk.INK.CARD), lum(mk.INK.WHITE))
        # ...and Ink's brightest surface still stays darker than Mist's dimmest.
        self.assertLess(lum(mk.INK.WHITE), lum(mk.MIST.SUNK))

    def test_both_palettes_expose_every_role_the_gui_reads(self):
        """A role missing from one palette is a crash the moment it is selected."""
        roles = [r for r in vars(mk.MIST) if r.isupper()]
        self.assertEqual(sorted(roles), sorted(r for r in vars(mk.INK) if r.isupper()))
        self.assertIn("BLOBS", roles)

    def test_use_scheme_rebinds_the_active_palette(self):
        try:
            self.assertIs(mk.use_scheme("dark"), mk.INK)
            self.assertIs(mk.theme, mk.INK)
            self.assertIs(mk.use_scheme("light"), mk.MIST)
            self.assertIs(mk.theme, mk.MIST)
            # An unknown name must not leave the app without a palette.
            self.assertIs(mk.use_scheme("chartreuse"), mk.MIST)
        finally:
            mk.use_scheme("light")


class DetectionTests(unittest.TestCase):
    """The env override is the seam that makes this testable off a desktop."""

    def setUp(self):
        self._saved = os.environ.get(mk.SCHEME_ENV)

    def tearDown(self):
        os.environ.pop(mk.SCHEME_ENV, None)
        if self._saved is not None:
            os.environ[mk.SCHEME_ENV] = self._saved

    def test_env_override_wins(self):
        for value in ("light", "dark", "DARK", "  light  "):
            with self.subTest(value=value):
                os.environ[mk.SCHEME_ENV] = value
                self.assertEqual(mk.detect_scheme(), value.strip().lower())

    def test_detection_always_answers_with_a_known_scheme(self):
        """Including on a machine with no desktop at all — a GUI that will not
        open because it could not guess a colour is the worse failure."""
        for value in ("", "chartreuse"):
            with self.subTest(value=value):
                os.environ[mk.SCHEME_ENV] = value
                self.assertIn(mk.detect_scheme(), mk.PALETTES)

    def test_probes_survive_a_missing_command(self):
        self.assertEqual(mk._ask(["socialblocker-no-such-binary"]), "")


if __name__ == "__main__":
    unittest.main()
