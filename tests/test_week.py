import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from linecast import _config
from linecast.settings import week
from linecast._runtime import (
    RuntimeConfig, default_week_start, moon_parser, resolve_week_start,
    sunshine_parser,
)


class ConfigDirMixin(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        patcher = patch.dict(os.environ, {
            "LINECAST_CONFIG_DIR": self._tmpdir.name,
            "LINECAST_CACHE_DIR": self._tmpdir.name,
        })
        patcher.start()
        self.addCleanup(patcher.stop)


class WeekCommandTests(ConfigDirMixin):
    def test_set_sunday_saves_and_show_reports_it(self):
        with redirect_stdout(io.StringIO()):
            week._cmd_set("sunday")
        self.assertEqual(_config.saved_week_start(), "sunday")

        out = io.StringIO()
        with redirect_stdout(out):
            week._cmd_show()
        self.assertIn("sunday  [fixed]", out.getvalue())

    def test_auto_clears_the_saved_week(self):
        with redirect_stdout(io.StringIO()):
            week._cmd_set("saturday")
            week._cmd_auto()
        self.assertIsNone(_config.saved_week_start())

    def test_saved_week_ignores_junk_values(self):
        _config.write_config({"week": "friday"})
        self.assertIsNone(_config.saved_week_start())

    def test_saved_week_tolerates_case_and_spaces(self):
        _config.write_config({"week": " Monday "})
        self.assertEqual(_config.saved_week_start(), "monday")


class ResolveWeekStartTests(ConfigDirMixin):
    def test_default_is_monday(self):
        self.assertEqual(resolve_week_start(None, {}), ("monday", "auto"))
        self.assertEqual(default_week_start(), "monday")
        for country in ("FR", "GB", "IE", "DE", "AU", "NZ", "CN", "UA"):
            self.assertEqual(default_week_start(country), "monday", country)

    def test_default_is_sunday_where_the_calendars_open_on_it(self):
        for country in ("US", "CA", "JP", "KR", "BR", "MX", "IL", "IN"):
            self.assertEqual(default_week_start(country), "sunday", country)
        self.assertEqual(resolve_week_start(None, {}, country="US"),
                         ("sunday", "auto"))

    def test_default_is_saturday_in_egypt_and_the_gulf(self):
        for country in ("EG", "AE", "QA", "IR"):
            self.assertEqual(default_week_start(country), "saturday", country)

    def test_saved_location_country_feeds_the_default(self):
        _config.write_config({"location": {"lat": 43.7, "lng": -70.4,
                                           "name": "Westbrook", "country": "US"}})
        self.assertEqual(resolve_week_start(None, {}), ("sunday", "auto"))

    def test_config_beats_the_country(self):
        _config.write_config({"week": "monday"})
        self.assertEqual(resolve_week_start(None, {}, country="US"),
                         ("monday", "config"))

    def test_env_beats_config(self):
        _config.write_config({"week": "monday"})
        self.assertEqual(resolve_week_start(None, {"LINECAST_WEEK_START": "Sunday"}),
                         ("sunday", "LINECAST_WEEK_START"))

    def test_flag_beats_env(self):
        args = moon_parser().parse_args(["--print", "--week-start", "saturday"])
        self.assertEqual(resolve_week_start(args, {"LINECAST_WEEK_START": "sunday"}),
                         ("saturday", "flag"))

    def test_junk_env_value_is_ignored(self):
        self.assertEqual(resolve_week_start(None, {"LINECAST_WEEK_START": "tuesday"}),
                         ("monday", "auto"))


class RuntimeWeekStartTests(ConfigDirMixin):
    def test_runtime_carries_the_resolved_week_start(self):
        args = moon_parser().parse_args(["--print", "--week-start", "sunday"])
        rt = RuntimeConfig.from_sources(args, environ={})
        self.assertEqual(rt.week_start, "sunday")

    def test_runtime_defaults_to_monday(self):
        args = moon_parser().parse_args(["--print"])
        rt = RuntimeConfig.from_sources(args, environ={})
        self.assertEqual(rt.week_start, "monday")

    def test_config_reaches_a_command_without_the_flag(self):
        _config.write_config({"week": "sunday"})
        args = sunshine_parser().parse_args(["--print"])
        rt = RuntimeConfig.from_sources(args, environ={})
        self.assertEqual(rt.week_start, "sunday")


if __name__ == "__main__":
    unittest.main()
