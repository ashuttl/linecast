import unittest

from linecast import _graphics


class _TTY:
    def __init__(self, is_tty):
        self._is_tty = is_tty

    def isatty(self):
        return self._is_tty


class DetectColorModeTests(unittest.TestCase):
    def test_no_color_env_disables_color(self):
        env = {"TERM": "xterm-256color", "NO_COLOR": "1"}
        mode = _graphics.detect_color_mode(environ=env, stream=_TTY(True))
        self.assertEqual(mode, "none")

    def test_colorterm_truecolor_wins(self):
        env = {"TERM": "xterm-256color", "COLORTERM": "truecolor"}
        mode = _graphics.detect_color_mode(environ=env, stream=_TTY(True))
        self.assertEqual(mode, "truecolor")

    def test_term_256color_detected(self):
        env = {"TERM": "screen-256color"}
        mode = _graphics.detect_color_mode(environ=env, stream=_TTY(True))
        self.assertEqual(mode, "256")

    def test_defaults_to_16_for_basic_tty(self):
        env = {"TERM": "xterm"}
        mode = _graphics.detect_color_mode(environ=env, stream=_TTY(True))
        self.assertEqual(mode, "16")

    def test_non_tty_defaults_to_none(self):
        env = {"TERM": "xterm-256color"}
        mode = _graphics.detect_color_mode(environ=env, stream=_TTY(False))
        self.assertEqual(mode, "none")

    def test_linecast_color_override(self):
        env = {"TERM": "dumb", "LINECAST_COLOR": "256"}
        mode = _graphics.detect_color_mode(environ=env, stream=_TTY(False))
        self.assertEqual(mode, "256")


class ColorMappingTests(unittest.TestCase):
    def test_xterm_red_maps_to_196(self):
        self.assertEqual(_graphics._rgb_to_xterm256(255, 0, 0), 196)

    def test_fg_none_is_empty(self):
        self.assertEqual(_graphics._fg_for_mode("none", 1, 2, 3), "")

    def test_fg_16_uses_basic_escape(self):
        self.assertEqual(_graphics._fg_for_mode("16", 255, 0, 0), "\033[91m")

    def test_bg_256_uses_5bit_sequence(self):
        seq = _graphics._bg_for_mode("256", 12, 34, 56)
        self.assertTrue(seq.startswith("\033[48;5;"))
        self.assertTrue(seq.endswith("m"))


if __name__ == "__main__":
    unittest.main()
