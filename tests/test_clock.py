import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from linecast import _config, clock
from linecast._runtime import (
    RuntimeConfig, default_clock, resolve_clock, sunshine_parser,
    weather_parser,
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


class ClockCommandTests(ConfigDirMixin):
    def test_set_12_saves_and_show_reports_it(self):
        with redirect_stdout(io.StringIO()):
            clock._cmd_set("12")
        self.assertEqual(_config.saved_clock(), "12")

        out = io.StringIO()
        with redirect_stdout(out):
            clock._cmd_show()
        self.assertIn("12-hour", out.getvalue())

    def test_auto_clears_the_saved_clock(self):
        with redirect_stdout(io.StringIO()):
            clock._cmd_set("24")
            clock._cmd_auto()
        self.assertIsNone(_config.saved_clock())

    def test_saved_clock_ignores_junk_values(self):
        _config.write_config({"clock": "13"})
        self.assertIsNone(_config.saved_clock())

    def test_saved_clock_tolerates_a_bare_number(self):
        _config.write_config({"clock": 24})
        self.assertEqual(_config.saved_clock(), "24")


class ResolveClockTests(ConfigDirMixin):
    def test_default_is_24h(self):
        self.assertEqual(resolve_clock(None, {}), ("24", "auto"))
        self.assertEqual(default_clock(), "24")
        self.assertEqual(default_clock("FR"), "24")

    def test_default_is_12h_where_the_12_hour_clock_is_written(self):
        for country in ("US", "CA", "AU", "NZ", "IN", "PH"):
            self.assertEqual(default_clock(country), "12", country)
        self.assertEqual(resolve_clock(None, {}, country="US"), ("12", "auto"))

    def test_saved_location_country_feeds_the_default(self):
        _config.write_config({"location": {"lat": 43.7, "lng": -70.4,
                                           "name": "Westbrook", "country": "US"}})
        self.assertEqual(resolve_clock(None, {}), ("12", "auto"))

    def test_config_beats_the_country(self):
        _config.write_config({"clock": "24"})
        self.assertEqual(resolve_clock(None, {}, country="US"), ("24", "config"))

    def test_config_beats_the_default(self):
        _config.write_config({"clock": "12"})
        self.assertEqual(resolve_clock(None, {}), ("12", "config"))

    def test_env_beats_config(self):
        _config.write_config({"clock": "24"})
        self.assertEqual(resolve_clock(None, {"LINECAST_CLOCK": "12"}),
                         ("12", "LINECAST_CLOCK"))

    def test_flag_beats_env(self):
        args = weather_parser().parse_args(["--print", "--24h"])
        self.assertEqual(resolve_clock(args, {"LINECAST_CLOCK": "12"}),
                         ("24", "flag"))

    def test_junk_env_value_is_ignored(self):
        self.assertEqual(resolve_clock(None, {"LINECAST_CLOCK": "twelve"}),
                         ("24", "auto"))


class RuntimeClockTests(ConfigDirMixin):
    def test_runtime_carries_the_resolved_clock(self):
        args = sunshine_parser().parse_args(["--print", "--12h"])
        rt = RuntimeConfig.from_sources(args, environ={})
        self.assertFalse(rt.use_24h)

    def test_runtime_defaults_to_24h(self):
        args = sunshine_parser().parse_args(["--print"])
        rt = RuntimeConfig.from_sources(args, environ={})
        self.assertTrue(rt.use_24h)

    def test_config_12h_reaches_the_runtime(self):
        _config.write_config({"clock": "12"})
        args = sunshine_parser().parse_args(["--print"])
        rt = RuntimeConfig.from_sources(args, environ={})
        self.assertFalse(rt.use_24h)


if __name__ == "__main__":
    unittest.main()
