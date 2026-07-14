import sys
import unittest
from unittest.mock import patch

from linecast import _theme


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


class ThemeParseTests(unittest.TestCase):
    def test_parse_rgb_value_16bit_channels(self):
        rgb = _theme._parse_rgb_value("rgb:ffff/7fff/0000")
        self.assertEqual(rgb, (255, 127, 0))

    def test_parse_rgb_value_rejects_invalid(self):
        self.assertIsNone(_theme._parse_rgb_value("not-rgb"))


if __name__ == "__main__":
    unittest.main()
