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

    def test_legacy_mode_from_theme_option(self):
        with patch.object(sys, "argv", ["weather", "--theme=legacy"]):
            with patch.dict("os.environ", {"LINECAST_THEME": "auto"}, clear=False):
                self.assertTrue(_theme._legacy_mode_requested())


class ThemeParseTests(unittest.TestCase):
    def test_parse_rgb_value_16bit_channels(self):
        rgb = _theme._parse_rgb_value("rgb:ffff/7fff/0000")
        self.assertEqual(rgb, (255, 127, 0))

    def test_parse_rgb_value_rejects_invalid(self):
        self.assertIsNone(_theme._parse_rgb_value("not-rgb"))


if __name__ == "__main__":
    unittest.main()
