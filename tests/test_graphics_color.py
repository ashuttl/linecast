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


class ColorMemoTests(unittest.TestCase):
    """fg/bg memoize on the raw arguments; the escape codes must not change."""

    def setUp(self):
        from linecast import _color
        self._color = _color
        _color._FG_MEMO.clear()
        _color._BG_MEMO.clear()

    def _direct(self, which, mode, r, g, b):
        c = self._color
        f = c._fg_for_mode if which == "fg" else c._bg_for_mode
        return f(mode, c._channel(r), c._channel(g), c._channel(b))

    def test_memoized_codes_match_the_uncached_path(self):
        from unittest.mock import patch
        c = self._color
        inputs = [(0, 0, 0), (255, 255, 255), (12.4, 99.6, 200.5), (-5, 300, 0.0),
                  (1e400, float("nan"), True), ("x", None, [1])]
        for mode in ("truecolor", "256", "16", "none"):
            with patch.object(c, "_COLOR_MODE", mode):
                for rgb in inputs:
                    for _ in range(2):   # miss, then hit
                        self.assertEqual(c.fg(*rgb), self._direct("fg", mode, *rgb))
                        self.assertEqual(c.bg(*rgb), self._direct("bg", mode, *rgb))

    def test_memo_keys_on_colour_mode(self):
        from unittest.mock import patch
        c = self._color
        with patch.object(c, "_COLOR_MODE", "truecolor"):
            self.assertEqual(c.bg(1, 2, 3), "\033[48;2;1;2;3m")
        with patch.object(c, "_COLOR_MODE", "none"):
            self.assertEqual(c.bg(1, 2, 3), "")

    def test_memo_clears_when_full(self):
        from unittest.mock import patch
        c = self._color
        with patch.object(c, "_MEMO_LIMIT", 4), patch.object(c, "_COLOR_MODE", "truecolor"):
            for i in range(4):
                c.fg(i, 0, 0)
            self.assertEqual(len(c._FG_MEMO), 4)
            self.assertEqual(c.fg(9, 0, 0), "\033[38;2;9;0;0m")
            self.assertEqual(len(c._FG_MEMO), 1)
