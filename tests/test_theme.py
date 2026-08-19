import contextlib
import sys
import unittest
from unittest.mock import patch

from linecast import _color, _theme


class ThemeModeTests(unittest.TestCase):
    def test_legacy_mode_from_env(self):
        with patch.dict("os.environ", {"LINECAST_THEME": "classic"}, clear=False):
            self.assertTrue(_theme._legacy_mode_requested())

    def test_legacy_mode_from_flag(self):
        with patch.object(sys, "argv", ["weather", "--classic-colors"]):
            with patch.dict("os.environ", {"LINECAST_THEME": "auto"}, clear=False):
                self.assertTrue(_theme._legacy_mode_requested())

    def test_theme_option_no_longer_selects_legacy_mode(self):
        # --theme now picks the radar colour palette, not the terminal mode
        with patch.object(sys, "argv", ["radar", "--theme=rainbow"]):
            with patch.dict("os.environ", {"LINECAST_THEME": "auto"}, clear=False):
                self.assertFalse(_theme._legacy_mode_requested())


def _ansi16(colors):
    """A 16-slot palette with slots 1..6 taken from `colors` (r g y b m c)."""
    ansi = [(0, 0, 0)] * 16
    ansi[7] = (200, 200, 200)
    ansi[15] = (255, 255, 255)
    for i, c in enumerate(colors, start=1):
        ansi[i] = c
        ansi[i + 8] = c
    return tuple(ansi)


_CANONICAL = _ansi16([(205, 0, 0), (0, 205, 0), (205, 205, 0),
                      (0, 0, 205), (205, 0, 205), (0, 205, 205)])
_MONO_GREEN = _ansi16([(40, 160, 70), (80, 220, 120), (120, 235, 150),
                       (20, 120, 55), (60, 190, 95), (100, 225, 135)])
_ALL_GRAY = _ansi16([(90, 90, 90), (130, 130, 130), (170, 170, 170),
                     (70, 70, 70), (110, 110, 110), (150, 150, 150)])


class ThemedTests(unittest.TestCase):
    @contextlib.contextmanager
    def _theme_active(self, ansi):
        with patch.object(_theme, "theme_available", True), \
             patch.object(_theme, "theme_legacy_mode", False), \
             patch.object(_theme, "theme_ansi", ansi), \
             patch.object(_color, "_COLOR_MODE", "truecolor"):
            yield

    def test_identity_without_theme(self):
        with patch.object(_theme, "theme_available", False):
            self.assertEqual(_theme.themed((6, 12, 30)), (6, 12, 30))

    def test_identity_in_16_color_mode(self):
        with self._theme_active(_MONO_GREEN):
            with patch.object(_color, "_COLOR_MODE", "16"):
                self.assertEqual(_theme.themed((6, 12, 30)), (6, 12, 30))

    def test_neutral_passes_through(self):
        with self._theme_active(_MONO_GREEN):
            self.assertEqual(_theme.themed((128, 128, 128)),
                             (128, 128, 128))

    def test_canonical_theme_is_near_identity(self):
        with self._theme_active(_CANONICAL):
            for color in ((96, 138, 92), (30, 44, 62), (245, 185, 70)):
                out = _theme.themed(color)
                for a, b in zip(out, color):
                    self.assertLess(abs(a - b), 10, (color, out))

    def test_monochrome_theme_collapses_hue(self):
        with self._theme_active(_MONO_GREEN):
            # the bathymetric navy, the motorway amber, the urban violet
            for color in ((6, 12, 30), (245, 185, 70), (140, 124, 160)):
                r, g, b = _theme.themed(color)
                self.assertGreaterEqual(g, r, (color, (r, g, b)))
                self.assertGreaterEqual(g, b, (color, (r, g, b)))

    def test_luminance_is_preserved(self):
        with self._theme_active(_MONO_GREEN):
            for color in ((6, 12, 30), (96, 138, 92), (240, 240, 248),
                          (245, 185, 70), (74, 118, 156)):
                out = _theme.themed(color)
                self.assertLess(
                    abs(_theme.luminance(out) - _theme.luminance(color)),
                    0.015, (color, out))

    def test_gray_theme_greys_the_map(self):
        with self._theme_active(_ALL_GRAY):
            r, g, b = _theme.themed((245, 185, 70))
            self.assertLess(max(r, g, b) - min(r, g, b), 12)


class ThemeParseTests(unittest.TestCase):
    def test_parse_rgb_value_16bit_channels(self):
        rgb = _theme._parse_rgb_value("rgb:ffff/7fff/0000")
        self.assertEqual(rgb, (255, 127, 0))

    def test_parse_rgb_value_rejects_invalid(self):
        self.assertIsNone(_theme._parse_rgb_value("not-rgb"))


if __name__ == "__main__":
    unittest.main()
