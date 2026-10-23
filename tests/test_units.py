import io
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from linecast import _config
from linecast.settings import units, wind
from linecast import _log
from linecast import _runtime
from linecast._runtime import (
    RuntimeConfig, TidesRuntime, WeatherRuntime, current_runtime, default_units, resolve_units,
    set_current, units_pref, use_metric,
)
from linecast._parsers import tides_parser, weather_parser


class ConfigDirMixin(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        # the cache dir too: own_country() reads the IP-geolocation
        # cache, which another test may have populated
        patcher = patch.dict(os.environ, {
            "LINECAST_CONFIG_DIR": self._tmpdir.name,
            "LINECAST_CACHE_DIR": self._tmpdir.name,
        })
        patcher.start()
        self.addCleanup(patcher.stop)


class UnitsCommandTests(ConfigDirMixin):
    def test_set_metric_saves_and_show_reports_it(self):
        with redirect_stdout(io.StringIO()):
            units._cmd_set("metric")
        self.assertEqual(_config.saved("units"), "metric")

        out = io.StringIO()
        with redirect_stdout(out):
            units._cmd_show()
        self.assertIn("metric", out.getvalue())

    def test_auto_clears_the_saved_units(self):
        with redirect_stdout(io.StringIO()):
            units._cmd_set("imperial")
            units._cmd_auto()
        self.assertIsNone(_config.saved("units"))

    def test_saved_units_ignores_junk_values(self):
        _config.write_config({"units": "cubits"})
        self.assertIsNone(_config.saved("units"))


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

    def test_linecast_units_applies_to_every_command(self):
        env = {"LINECAST_UNITS": "imperial"}
        self.assertEqual(units_pref("WEATHER_UNITS", env), "imperial")
        self.assertEqual(units_pref("TIDES_UNITS", env), "imperial")

    def test_weather_units_does_not_reach_the_other_commands(self):
        # README: WEATHER_UNITS is for the weather command, LINECAST_UNITS
        # for every command.  moon, sky and the rest build a plain
        # RuntimeConfig, which has no env var of its own.
        env = {"WEATHER_UNITS": "imperial", "LINECAST_UNITS": "metric"}
        self.assertEqual(
            resolve_units(None, env, RuntimeConfig._legacy_units_env, country="US"),
            ("metric", "LINECAST_UNITS"))
        self.assertEqual(
            resolve_units(None, env, WeatherRuntime._legacy_units_env, country="US"),
            ("imperial", "WEATHER_UNITS"))
        self.assertEqual(
            resolve_units(None, {"WEATHER_UNITS": "imperial"},
                          RuntimeConfig._legacy_units_env, country="FR"),
            ("metric", "auto"))

    def test_command_env_var_overrides_linecast_units(self):
        env = {"WEATHER_UNITS": "metric", "LINECAST_UNITS": "imperial"}
        self.assertEqual(units_pref("WEATHER_UNITS", env), "metric")
        self.assertEqual(units_pref("TIDES_UNITS", env), "imperial")


class ResolveUnitsTests(ConfigDirMixin):
    def test_flags_win_over_everything(self):
        _config.write_config({"units": "metric"})
        value, source = resolve_units(
            _weather_args("--imperial"), {"WEATHER_UNITS": "metric"})
        self.assertEqual((value, source), ("imperial", "flag"))

    def test_auto_follows_the_country(self):
        self.assertEqual(resolve_units(None, {}, country="US"),
                         ("imperial", "auto"))
        self.assertEqual(resolve_units(None, {}, country="FR"),
                         ("metric", "auto"))
        self.assertEqual(resolve_units(None, {}, country=None),
                         ("metric", "auto"))

    def test_default_units_policy(self):
        self.assertEqual(default_units("US"), "imperial")
        self.assertEqual(default_units("CA"), "metric")
        self.assertEqual(default_units(None), "metric")

    def test_auto_resolves_offline_in_the_sandbox(self):
        # no saved location, no IP cache: own_country() must answer
        # None without touching the network, and the default is metric
        self.assertEqual(resolve_units(None, {}), ("metric", "auto"))


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

    def test_imperial_flag_pins_imperial(self):
        _config.write_config({"units": "metric"})
        rt = WeatherRuntime.from_sources(
            _weather_args("--print", "--imperial"), environ={})
        self.assertFalse(rt.metric)
        self.assertFalse(rt.celsius)

    def test_country_feeds_the_auto_default(self):
        us = WeatherRuntime.from_sources(_weather_args("--print"),
                                         environ={}, country="US")
        self.assertFalse(us.metric)
        self.assertFalse(us.celsius)
        fr = WeatherRuntime.from_sources(_weather_args("--print"),
                                         environ={}, country="FR")
        self.assertTrue(fr.metric)
        self.assertTrue(fr.celsius)

    def test_config_wins_over_country(self):
        _config.write_config({"units": "metric"})
        rt = TidesRuntime.from_sources(tides_parser().parse_args(["--print"]),
                                       environ={}, country="US")
        self.assertTrue(rt.metric)


class WindUnitsTests(ConfigDirMixin):
    """--wind-units and LINECAST_WIND_UNITS choose the wind unit,
    whatever the units and the language."""

    def _rt(self, *argv, environ=None):
        return WeatherRuntime.from_sources(
            _weather_args("--print", *argv), environ=environ or {}, country=None)

    def test_the_default_follows_the_units_and_the_language(self):
        self.assertEqual(self._rt("--lang", "en", "--metric").wind_unit, "km/h")
        self.assertEqual(self._rt("--lang", "ja", "--metric").wind_unit, "m/s")
        self.assertEqual(self._rt("--lang", "ja", "--imperial").wind_unit, "mph")

    def test_the_flag_wins_over_the_units_and_the_language(self):
        rt = self._rt("--lang", "en", "--metric", "--wind-units", "m/s")
        self.assertEqual((rt.wind_unit, rt.wind_unit_param), ("m/s", "ms"))
        self.assertTrue(rt.metric)
        rt = self._rt("--lang", "ja", "--metric", "--wind-units", "km/h")
        self.assertEqual(rt.wind_unit, "km/h")
        rt = self._rt("--imperial", "--wind-units", "km/h")
        self.assertEqual(rt.wind_unit, "km/h")
        self.assertFalse(rt.metric)
        rt = self._rt("--metric", "--wind-units", "mph")
        self.assertEqual(rt.wind_unit, "mph")

    def test_the_flag_takes_the_usual_spellings(self):
        self.assertEqual(self._rt("--wind-units", "ms").wind_unit, "m/s")
        self.assertEqual(self._rt("--wind-units", "KMH").wind_unit, "km/h")
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            _weather_args("--wind-units", "furlongs")

    def test_the_env_var_applies_below_the_flag(self):
        env = {"LINECAST_WIND_UNITS": "m/s"}
        self.assertEqual(self._rt("--lang", "en", environ=env).wind_unit, "m/s")
        self.assertEqual(self._rt("--wind-units", "mph", environ=env).wind_unit, "mph")
        # junk in the variable is ignored
        rt = self._rt("--lang", "en", "--metric", environ={"LINECAST_WIND_UNITS": "fast"})
        self.assertEqual(rt.wind_unit, "km/h")

    def test_the_radar_takes_it_too(self):
        from linecast._parsers import radar_parser
        rt = RuntimeConfig.from_sources(
            radar_parser().parse_args(["--wind-units", "m/s"]), environ={}, country=None)
        self.assertEqual(rt.wind_unit, "m/s")
        self.assertEqual(rt.wind_from_kmh(36), 10)

    def test_knots(self):
        rt = self._rt("--lang", "en", "--wind-units", "knots")
        self.assertEqual((rt.wind_unit, rt.wind_unit_param), ("kn", "kn"))
        self.assertAlmostEqual(rt.wind_kmh(10), 18.52)
        self.assertAlmostEqual(rt.wind_from_kmh(18.52), 10)
        from linecast.weather.i18n import fmt_wind
        self.assertEqual(fmt_wind(10, rt), "10kn")
        self.assertEqual(fmt_wind(10, self._rt("--lang", "ja", "--wind-units", "kt")),
                         "10ノット")
        self.assertEqual(fmt_wind(10, self._rt("--lang", "fr", "--wind-units", "kn")),
                         "10 nd")

    def test_the_saved_setting_applies_below_the_env_var(self):
        with redirect_stdout(io.StringIO()):
            wind._cmd_set("kn")
        self.assertEqual(_config.saved("wind"), "kn")
        self.assertEqual(self._rt("--lang", "en", "--metric").wind_unit, "kn")
        rt = self._rt("--lang", "en", environ={"LINECAST_WIND_UNITS": "m/s"})
        self.assertEqual(rt.wind_unit, "m/s")
        self.assertEqual(self._rt("--wind-units", "mph").wind_unit, "mph")
        with redirect_stdout(io.StringIO()):
            wind._cmd_auto()
        self.assertIsNone(_config.saved("wind"))
        self.assertEqual(self._rt("--lang", "en", "--metric").wind_unit, "km/h")

    def test_the_saved_setting_ignores_junk(self):
        _config.write_config({"wind": "furlongs"})
        self.assertIsNone(_config.saved("wind"))
        _config.write_config({"wind": "KNOTS"})
        self.assertEqual(_config.saved("wind"), "kn")

    def test_the_command_takes_the_usual_spellings(self):
        with patch("sys.argv", ["linecast wind", "knots"]), \
                redirect_stdout(io.StringIO()) as out:
            wind.main()
        self.assertEqual(_config.saved("wind"), "kn")
        self.assertEqual(out.getvalue(), "Wind speeds set to kn\n")
        with patch("sys.argv", ["linecast wind"]), redirect_stdout(io.StringIO()) as out:
            wind.main()
        self.assertTrue(out.getvalue().startswith("kn  [fixed]"))

    def test_the_label_follows_the_unit(self):
        from linecast.weather.i18n import fmt_wind
        self.assertEqual(fmt_wind(10, self._rt("--lang", "en", "--metric",
                                               "--wind-units", "mph")), "10mph")
        self.assertEqual(fmt_wind(10, self._rt("--lang", "ru", "--imperial",
                                               "--wind-units", "m/s")), "10\u00a0м/с")


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
        # no country in the sandbox: the auto default is metric
        self.assertTrue(rt.celsius)
        self.assertTrue(rt.metric)
        self.assertEqual(rt.lang, "en")
        self.assertFalse(_log.debug_enabled())

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
    """use_metric() reads the running command's resolved units."""

    def setUp(self):
        super().setUp()
        self.addCleanup(set_current, None)
        set_current(None)

    def test_follows_the_stashed_runtime(self):
        set_current(WeatherRuntime.from_sources(
            _weather_args("--print", "--imperial"), environ={}))
        self.assertFalse(use_metric())
        set_current(WeatherRuntime.from_sources(
            _weather_args("--print", "--metric"), environ={}))
        self.assertTrue(use_metric())

    def test_config_applies_before_any_main(self):
        _config.write_config({"units": "imperial"})
        self.assertFalse(use_metric())


if __name__ == "__main__":
    unittest.main()
