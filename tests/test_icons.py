"""Icon-set resolution: flags beat env, env beats terminal detection."""

import unittest

from linecast._runtime import RuntimeConfig, default_icons, weather_parser


def _args(*argv):
    return weather_parser().parse_args(list(argv))


class IconDefaultTests(unittest.TestCase):
    def test_plain_when_nothing_is_known(self):
        self.assertEqual(default_icons({}), "plain")

    def test_terminals_that_bundle_the_glyphs_get_nerd(self):
        self.assertEqual(default_icons({"TERM_PROGRAM": "WezTerm"}), "nerd")
        self.assertEqual(default_icons({"TERM_PROGRAM": "ghostty"}), "nerd")
        self.assertEqual(default_icons({"KITTY_WINDOW_ID": "1"}), "nerd")

    def test_other_terminals_stay_plain(self):
        self.assertEqual(default_icons({"TERM_PROGRAM": "iTerm.app"}), "plain")
        self.assertEqual(default_icons({"TERM": "xterm-256color"}), "plain")


class IconResolutionTests(unittest.TestCase):
    def test_default_is_plain(self):
        rt = RuntimeConfig.from_sources(_args("--print"), environ={})
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
        rt = RuntimeConfig.from_sources(
            _args("--print"), environ={"LINECAST_ICONS": "wingdings"})
        self.assertEqual(rt.icons, "plain")

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
