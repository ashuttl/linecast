import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from linecast import _config, units
from linecast import _runtime
from linecast._runtime import (
    RuntimeConfig, TidesRuntime, WeatherRuntime, current_runtime, set_current,
    tides_parser, units_pref, use_metric, weather_parser,
)


class ConfigDirMixin(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        patcher = patch.dict(os.environ, {"LINECAST_CONFIG_DIR": self._tmpdir.name})
        patcher.start()
        self.addCleanup(patcher.stop)


class UnitsCommandTests(ConfigDirMixin):
    def test_set_metric_saves_and_show_reports_it(self):
        with redirect_stdout(io.StringIO()):
            units._cmd_set("metric")
        self.assertEqual(_config.saved_units(), "metric")

        out = io.StringIO()
        with redirect_stdout(out):
            units._cmd_show()
        self.assertIn("metric", out.getvalue())

    def test_auto_clears_the_saved_units(self):
        with redirect_stdout(io.StringIO()):
            units._cmd_set("imperial")
            units._cmd_auto()
        self.assertIsNone(_config.saved_units())

    def test_saved_units_ignores_junk_values(self):
        _config.write_config({"units": "cubits"})
        self.assertIsNone(_config.saved_units())


class UnitsPrefTests(ConfigDirMixin):
    def test_config_units_apply_without_env(self):
        _config.write_config({"units": "metric"})
        self.assertEqual(units_pref("WEATHER_UNITS", {}), "metric")
        self.assertEqual(units_pref("TIDES_UNITS", {}), "metric")

    def test_env_var_overrides_config(self):
        _config.write_config({"units": "metric"})
        self.assertEqual(
            units_pref("WEATHER_UNITS", {"WEATHER_UNITS": "imperial"}),
            "imperial",
        )

    def test_no_preference_returns_none(self):
        self.assertIsNone(units_pref("WEATHER_UNITS", {}))


def _weather_args(*argv):
    return weather_parser().parse_args(list(argv))


class RuntimeUnitsTests(ConfigDirMixin):
    def test_weather_runtime_reads_config_metric(self):
        _config.write_config({"units": "metric"})
        rt = WeatherRuntime.from_sources(_weather_args("--print"), environ={})
        self.assertTrue(rt.metric)
        self.assertTrue(rt.celsius)

    def test_fahrenheit_flag_overrides_config_metric(self):
        _config.write_config({"units": "metric"})
        rt = WeatherRuntime.from_sources(
            _weather_args("--print", "--fahrenheit"), environ={})
        self.assertTrue(rt.metric)
        self.assertFalse(rt.celsius)

    def test_env_imperial_overrides_config_metric(self):
        _config.write_config({"units": "metric"})
        rt = WeatherRuntime.from_sources(
            _weather_args("--print"), environ={"WEATHER_UNITS": "imperial"})
        self.assertFalse(rt.metric)
        self.assertFalse(rt.celsius)

    def test_tides_runtime_reads_config_metric(self):
        _config.write_config({"units": "metric"})
        rt = TidesRuntime.from_sources(tides_parser().parse_args(["--print"]), environ={})
        self.assertTrue(rt.metric)
        self.assertEqual(rt.height_unit, "m")


class CurrentRuntimeTests(ConfigDirMixin):
    """Render helpers called without a runtime fall back to the one
    main() resolved, or to the command's defaults before that."""

    def setUp(self):
        super().setUp()
        self.addCleanup(set_current, None)
        set_current(None)

    def test_defaults_before_main_has_run(self):
        with patch.dict(os.environ, {"LINECAST_LANG": "", "LINECAST_ICONS": ""}):
            rt = current_runtime(WeatherRuntime)
        self.assertIsInstance(rt, WeatherRuntime)
        self.assertFalse(rt.celsius)
        self.assertEqual(rt.lang, "en")
        self.assertFalse(_runtime._DEBUG)

    def test_returns_the_runtime_main_stashed(self):
        rt = WeatherRuntime.from_sources(_weather_args("--print", "--celsius"),
                                         environ={})
        set_current(rt)
        self.assertIs(current_runtime(WeatherRuntime), rt)
        # a subclass instance serves a base-class request too
        self.assertIs(current_runtime(RuntimeConfig), rt)

    def test_another_commands_runtime_is_not_borrowed(self):
        set_current(RuntimeConfig.from_sources(
            tides_parser().parse_args(["--print"]), environ={}))
        rt = current_runtime(WeatherRuntime)
        self.assertIsInstance(rt, WeatherRuntime)
        self.assertNotEqual(rt, _runtime._current)


class UseMetricTests(ConfigDirMixin):
    def test_non_english_defaults_to_metric(self):
        self.assertTrue(use_metric("fr", {}))
        self.assertFalse(use_metric("en", {}))

    def test_config_metric_applies_in_english(self):
        _config.write_config({"units": "metric"})
        self.assertTrue(use_metric("en", {}))

    def test_config_imperial_wins_over_language(self):
        _config.write_config({"units": "imperial"})
        self.assertFalse(use_metric("fr", {}))


if __name__ == "__main__":
    unittest.main()
