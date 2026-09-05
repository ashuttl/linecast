import glob
import io
import os
import re
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from linecast import _config, language
from linecast._i18n import LANGUAGE_CODES
from linecast._runtime import RuntimeConfig, resolve_lang, weather_parser


class ConfigDirMixin(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        patcher = patch.dict(os.environ, {
            "LINECAST_CONFIG_DIR": self._tmpdir.name,
            "LINECAST_CACHE_DIR": self._tmpdir.name,
            "LINECAST_LANG": "",
        })
        patcher.start()
        self.addCleanup(patcher.stop)


class LanguageCommandTests(ConfigDirMixin):
    def test_set_saves_and_show_reports_it(self):
        with redirect_stdout(io.StringIO()):
            language._cmd_set("fr")
        self.assertEqual(_config.saved_language(), "fr")

        out = io.StringIO()
        with redirect_stdout(out):
            language._cmd_show()
        self.assertIn("fr  French  [fixed]", out.getvalue())

    def test_show_names_the_locale_that_decided(self):
        out = io.StringIO()
        with patch.dict(os.environ, {"LANG": "ja_JP.UTF-8"}), redirect_stdout(out):
            language._cmd_show()
        self.assertIn("ja  Japanese  [auto: LANG=ja_JP.UTF-8]", out.getvalue())
        self.assertIn("linecast language <code>", out.getvalue())

    def test_auto_reports_what_the_terminal_gives(self):
        with redirect_stdout(io.StringIO()):
            language._cmd_set("fr")
        out = io.StringIO()
        with patch.dict(os.environ, {"LANG": "de_DE.UTF-8"}), redirect_stdout(out):
            language._cmd_auto()
        self.assertIsNone(_config.saved_language())
        self.assertIn("auto (de German, from LANG)", out.getvalue())

        out = io.StringIO()
        with redirect_stdout(out):
            language._cmd_auto()
        self.assertIn("auto (English)", out.getvalue())

    def test_show_lists_every_language_by_default(self):
        out = io.StringIO()
        with redirect_stdout(out):
            language._cmd_show()
        text = out.getvalue()
        self.assertIn("en  English  [default]", text)
        for code in LANGUAGE_CODES:
            self.assertIn(f" {code} ", text)

    def test_auto_clears_the_saved_language(self):
        with redirect_stdout(io.StringIO()):
            language._cmd_set("de")
            language._cmd_auto()
        self.assertIsNone(_config.saved_language())

    def test_an_unlisted_code_is_kept_and_described(self):
        # India's alerts come in the state language; the code reaches
        # them while the rest of the app stays in English.
        out = io.StringIO()
        with redirect_stdout(out):
            language._cmd_set("hi")
        self.assertEqual(_config.saved_language(), "hi")
        self.assertIn("English", out.getvalue())

    def test_saved_language_ignores_junk_values(self):
        _config.write_config({"language": "french"})
        self.assertIsNone(_config.saved_language())
        _config.write_config({"language": 12})
        self.assertIsNone(_config.saved_language())

    def test_main_rejects_a_word_that_is_not_a_code(self):
        with patch("sys.argv", ["linecast language", "french"]), \
                redirect_stdout(io.StringIO()), \
                patch("sys.stderr", io.StringIO()) as err:
            with self.assertRaises(SystemExit) as cm:
                language.main()
        self.assertEqual(cm.exception.code, 2)
        self.assertIn("two-letter", err.getvalue())


class ResolveLangTests(ConfigDirMixin):
    def test_default_is_english(self):
        self.assertEqual(resolve_lang(None, {}), ("en", "default"))

    def test_config_beats_the_default(self):
        _config.write_config({"language": "fr"})
        self.assertEqual(resolve_lang(None, {}), ("fr", "config"))

    def test_env_beats_config(self):
        _config.write_config({"language": "fr"})
        self.assertEqual(resolve_lang(None, {"LINECAST_LANG": "de"}),
                         ("de", "LINECAST_LANG"))

    def test_flag_beats_env(self):
        args = weather_parser().parse_args(["--print", "--lang", "ja"])
        self.assertEqual(resolve_lang(args, {"LINECAST_LANG": "de"}), ("ja", "flag"))

    def test_a_locale_names_its_language_in_the_first_two_letters(self):
        self.assertEqual(resolve_lang(None, {"LINECAST_LANG": "fr-FR"}),
                         ("fr", "LINECAST_LANG"))
        self.assertEqual(resolve_lang(None, {"LINECAST_LANG": "EN_us"}),
                         ("en", "LINECAST_LANG"))

    def test_junk_env_value_falls_through(self):
        _config.write_config({"language": "fr"})
        self.assertEqual(resolve_lang(None, {"LINECAST_LANG": "7"}), ("fr", "config"))

    def test_the_terminal_locale_decides_when_nothing_is_saved(self):
        self.assertEqual(resolve_lang(None, {"LANG": "de_DE.UTF-8"}), ("de", "LANG"))

    def test_config_beats_the_locale(self):
        _config.write_config({"language": "fr"})
        self.assertEqual(resolve_lang(None, {"LANG": "de_DE.UTF-8"}), ("fr", "config"))

    def test_linecast_lang_beats_the_locale(self):
        self.assertEqual(resolve_lang(None, {"LINECAST_LANG": "ja", "LANG": "de_DE.UTF-8"}),
                         ("ja", "LINECAST_LANG"))

    def test_locale_variables_in_gettext_order(self):
        env = {"LANG": "de_DE.UTF-8", "LC_MESSAGES": "fr_FR.UTF-8",
               "LC_ALL": "sv_SE.UTF-8", "LANGUAGE": "ja:de"}
        self.assertEqual(resolve_lang(None, env), ("ja", "LANGUAGE"))
        del env["LANGUAGE"]
        self.assertEqual(resolve_lang(None, env), ("sv", "LC_ALL"))
        env["LC_ALL"] = ""
        self.assertEqual(resolve_lang(None, env), ("fr", "LC_MESSAGES"))
        del env["LC_MESSAGES"]
        self.assertEqual(resolve_lang(None, env), ("de", "LANG"))

    def test_a_language_list_skips_entries_that_name_none(self):
        self.assertEqual(resolve_lang(None, {"LANGUAGE": "C:fil_PH:pt_BR"}),
                         ("pt", "LANGUAGE"))

    def test_the_c_and_posix_locales_mean_english(self):
        for value in ("C", "POSIX", "C.UTF-8", "c.utf8", ""):
            with self.subTest(value=value):
                self.assertEqual(resolve_lang(None, {"LANG": value, "LC_ALL": value}),
                                 ("en", "default"))

    def test_a_three_letter_code_is_not_trimmed_to_two(self):
        # fil_PH is Filipino, not Finnish
        self.assertEqual(resolve_lang(None, {"LANG": "fil_PH"}), ("en", "default"))
        self.assertEqual(resolve_lang(None, {"LINECAST_LANG": "fil"}), ("en", "default"))

    def test_an_english_locale_is_english_from_the_locale(self):
        self.assertEqual(resolve_lang(None, {"LANG": "en_GB.UTF-8"}), ("en", "LANG"))


class RuntimeLangTests(ConfigDirMixin):
    def test_config_language_reaches_the_runtime(self):
        _config.write_config({"language": "sv"})
        args = weather_parser().parse_args(["--print"])
        self.assertEqual(RuntimeConfig.from_sources(args, environ={}).lang, "sv")

    def test_flag_language_reaches_the_runtime(self):
        args = weather_parser().parse_args(["--print", "--lang", "ko"])
        self.assertEqual(RuntimeConfig.from_sources(args, environ={}).lang, "ko")


class LanguageListTests(unittest.TestCase):
    def test_every_string_table_language_is_listed(self):
        # The list in _i18n is the one the command and the help page
        # show, so a language with strings must not be missing from it.
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        found = set()
        for path in glob.glob(os.path.join(here, "src", "linecast", "_*_i18n.py")):
            with open(path, encoding="utf-8") as f:
                found.update(re.findall(r'^    "([a-z]{2})": \{', f.read(), re.M))
        self.assertEqual(found, set(LANGUAGE_CODES))


if __name__ == "__main__":
    unittest.main()
