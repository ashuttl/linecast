"""Icon-set resolution: flags beat env, env beats terminal detection."""

import unittest
from unittest import mock

from linecast._runtime import RuntimeConfig, default_icons, weather_parser


def _args(*argv):
    return weather_parser().parse_args(list(argv))


class _Stream:
    """A stand-in for stdout with a chosen tty state and encoding."""

    def __init__(self, tty=True, encoding="utf-8"):
        self._tty = tty
        self.encoding = encoding

    def isatty(self):
        return self._tty


TTY = _Stream()
PIPE = _Stream(tty=False)


class IconDefaultTests(unittest.TestCase):
    def test_terminals_that_bundle_the_glyphs_get_nerd(self):
        self.assertEqual(default_icons({"TERM_PROGRAM": "WezTerm"}, TTY), "nerd")
        self.assertEqual(default_icons({"TERM_PROGRAM": "ghostty"}, TTY), "nerd")
        self.assertEqual(default_icons({"KITTY_WINDOW_ID": "1"}, TTY), "nerd")

    def test_other_interactive_terminals_get_emoji(self):
        self.assertEqual(default_icons({"TERM_PROGRAM": "iTerm.app"}, TTY), "emoji")
        self.assertEqual(default_icons({"TERM": "xterm-256color"}, TTY), "emoji")
        # Windows Terminal announces itself through WT_SESSION, not TERM
        self.assertEqual(default_icons({"WT_SESSION": "guid"}, TTY), "emoji")

    def test_piped_output_stays_plain(self):
        self.assertEqual(default_icons({"TERM": "xterm-256color"}, PIPE), "plain")

    def test_an_encoding_without_emoji_stays_plain(self):
        latin1 = _Stream(encoding="cp1252")
        self.assertEqual(default_icons({"TERM": "xterm-256color"}, latin1), "plain")

    def test_no_terminal_at_all_stays_plain(self):
        # TERM, TERM_PROGRAM and WT_SESSION all unset: the legacy
        # Windows console, even when stdout is an interactive tty.
        self.assertEqual(default_icons({}, TTY), "plain")
        self.assertEqual(default_icons({"TERM": "dumb"}, TTY), "plain")

    def test_bundling_terminal_beats_the_stream(self):
        # nerd glyphs are single-cell and safe to pipe; the terminal is
        # what decides, as before
        self.assertEqual(default_icons({"TERM_PROGRAM": "WezTerm"}, PIPE), "nerd")


class IconResolutionTests(unittest.TestCase):
    def test_default_is_emoji_on_an_interactive_terminal(self):
        with mock.patch("sys.stdout", TTY):
            rt = RuntimeConfig.from_sources(
                _args("--print"), environ={"TERM": "xterm-256color"})
        self.assertEqual(rt.icons, "emoji")

    def test_default_is_plain_when_piped(self):
        with mock.patch("sys.stdout", PIPE):
            rt = RuntimeConfig.from_sources(
                _args("--print"), environ={"TERM": "xterm-256color"})
        self.assertEqual(rt.icons, "plain")

    def test_bundling_terminal_defaults_to_nerd(self):
        rt = RuntimeConfig.from_sources(
            _args("--print"), environ={"TERM_PROGRAM": "WezTerm"})
        self.assertEqual(rt.icons, "nerd")

    def test_env_picks_the_set(self):
        for name in ("nerd", "emoji", "plain"):
            rt = RuntimeConfig.from_sources(
                _args("--print"), environ={"LINECAST_ICONS": name})
            self.assertEqual(rt.icons, name)

    def test_junk_env_value_falls_back_to_detection(self):
        with mock.patch("sys.stdout", TTY):
            rt = RuntimeConfig.from_sources(
                _args("--print"),
                environ={"LINECAST_ICONS": "wingdings",
                         "TERM": "xterm-256color"})
        self.assertEqual(rt.icons, "emoji")

    def test_icons_flag_beats_env(self):
        rt = RuntimeConfig.from_sources(
            _args("--print", "--icons", "nerd"),
            environ={"LINECAST_ICONS": "emoji"})
        self.assertEqual(rt.icons, "nerd")

    def test_emoji_flag_is_an_alias(self):
        rt = RuntimeConfig.from_sources(_args("--print", "--emoji"),
                                        environ={})
        self.assertEqual(rt.icons, "emoji")


if __name__ == "__main__":
    unittest.main()


class SavedIconsTests(unittest.TestCase):
    """`linecast icons` persists a set; env and flags still beat it."""

    def setUp(self):
        import os
        import tempfile
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        patcher = mock.patch.dict(os.environ, {"LINECAST_CONFIG_DIR": tmp.name,
                                               "LINECAST_CACHE_DIR": tmp.name})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_set_and_show(self):
        import io
        from contextlib import redirect_stdout
        from linecast import _config, icons
        with redirect_stdout(io.StringIO()):
            icons._cmd_set("nerd")
        self.assertEqual(_config.saved_icons(), "nerd")
        out = io.StringIO()
        with redirect_stdout(out):
            icons._cmd_show()
        self.assertIn("nerd", out.getvalue())
        with redirect_stdout(io.StringIO()):
            icons._cmd_auto()
        self.assertIsNone(_config.saved_icons())

    def test_saved_icons_ignores_junk(self):
        from linecast import _config
        _config.write_config({"icons": "webdings"})
        self.assertIsNone(_config.saved_icons())

    def test_config_beats_detection(self):
        from linecast import _config
        from linecast._runtime import resolve_icons
        _config.write_config({"icons": "nerd"})
        with mock.patch("sys.stdout", TTY):
            self.assertEqual(resolve_icons(None, {"TERM": "xterm-256color"}),
                             ("nerd", "config"))
            rt = RuntimeConfig.from_sources(
                _args("--print"), environ={"TERM": "xterm-256color"})
        self.assertEqual(rt.icons, "nerd")

    def test_env_and_flags_beat_config(self):
        from linecast import _config
        from linecast._runtime import resolve_icons
        _config.write_config({"icons": "nerd"})
        self.assertEqual(resolve_icons(None, {"LINECAST_ICONS": "plain"}),
                         ("plain", "LINECAST_ICONS"))
        self.assertEqual(resolve_icons(_args("--icons", "emoji"),
                                       {"LINECAST_ICONS": "plain"}),
                         ("emoji", "flag"))
