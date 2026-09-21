"""The temperature graphs' scale under --temp-range."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from linecast._runtime import WeatherRuntime, weather_parser
from linecast._weather.historical import HistoricalAverages, temperature_scale


def _archive(year_high, year_low):
    return HistoricalAverages(avg_high=60.0, avg_low=40.0, avg_precip=0.1, years=10,
                              year_high=year_high, year_low=year_low)


def _runtime(argv=(), environ=None):
    namespace = weather_parser().parse_args(["--print", *argv])
    return WeatherRuntime.from_sources(namespace, environ=environ or {})


class TestTemperatureScale:
    def test_forecast_is_the_forecast(self):
        rt = _runtime(["--temp-range", "forecast"])
        assert temperature_scale(rt, _archive(91.3, -3.6), (52.0, 75.0)) == (52.0, 75.0)

    def test_climate_is_the_typical_years_extremes_unpadded(self):
        rt = _runtime(["--temp-range", "climate"])
        assert temperature_scale(rt, _archive(91.3, -3.6), (52.0, 75.0)) == (-3.6, 91.3)

    def test_climate_widens_to_a_forecast_past_the_usual_year(self):
        # A heat wave beyond the usual year touches the top, not the ceiling
        rt = _runtime(["--temp-range", "climate"])
        assert temperature_scale(rt, _archive(91.3, -3.6), (70.0, 103.4)) == (-3.6, 103.4)
        assert temperature_scale(rt, _archive(91.3, -3.6), (-21.0, 10.0)) == (-21.0, 91.3)

    def test_climate_without_an_archive_is_the_forecast(self):
        rt = _runtime(["--temp-range", "climate"])
        assert temperature_scale(rt, None, (52.0, 75.0)) == (52.0, 75.0)
        assert temperature_scale(rt, _archive(None, None), (52.0, 75.0)) == (52.0, 75.0)

    def test_world_is_the_same_everywhere(self):
        assert temperature_scale(_runtime(["--temp-range", "world", "--fahrenheit"]),
                                 _archive(91.3, -3.6), (52.0, 75.0)) == (-40, 122)
        assert temperature_scale(_runtime(["--temp-range", "world", "--celsius"]),
                                 None, (10.0, 20.0)) == (-40, 50)

    def test_world_widens_to_a_forecast_past_its_ends(self):
        rt = _runtime(["--temp-range", "world", "--celsius"])
        assert temperature_scale(rt, None, (30.0, 52.0)) == (-40, 52.0)


class TestTempRangeFlag:
    def test_auto_by_default(self):
        assert _runtime().temp_range == "auto"
        assert WeatherRuntime.defaults(environ={}).temp_range == "auto"
        assert WeatherRuntime(live=False, icons="emoji", lang="en",
                              oneline=False).temp_range == "auto"

    def test_flag_picks_a_scale(self):
        assert _runtime(["--temp-range=auto"]).temp_range == "auto"
        assert _runtime(["--temp-range", "climate"]).temp_range == "climate"
        assert _runtime(["--temp-range=world"]).temp_range == "world"


class TestAutoTemperatureScale:
    @pytest.mark.parametrize("units,low,high,forecast", [
        ("--celsius", -10.0, 40.0, (10.0, 20.0)),
        ("--fahrenheit", 14.0, 104.0, (50.0, 68.0)),
    ])
    def test_resolution_boundary_is_the_same_in_both_units(self, units, low, high, forecast):
        runtime = _runtime([units])
        archive = _archive(high, low)
        # The climate span is exactly 5°C / 9°F per row at ten rows.
        for rows in (2, 9, 10, 11, 20, 2):
            expected = forecast if rows < 10 else (low, high)
            assert temperature_scale(runtime, archive, forecast, n_rows=rows) == expected

    def test_a_narrow_climate_fits_even_a_short_graph(self):
        assert temperature_scale(_runtime(["--celsius"]), _archive(28, 18),
                                 (22, 25), n_rows=2) == (18, 28)

    def test_resolution_includes_forecast_beyond_the_climate_extremes(self):
        runtime = _runtime(["--celsius"])
        archive = _archive(40, -10)
        for forecast in ((10, 41), (-11, 20)):
            assert temperature_scale(runtime, archive, forecast, n_rows=10) == forecast

    @pytest.mark.parametrize("archive", [None, _archive(None, None), _archive(40, None)])
    def test_missing_climate_uses_forecast_at_any_height(self, archive):
        for rows in (2, 20):
            assert temperature_scale(_runtime(), archive, (10, 20), n_rows=rows) == (10, 20)

    @pytest.mark.parametrize("mode,expected", [
        ("climate", (-10, 40)), ("forecast", (10, 20)), ("world", (-40, 50)),
    ])
    def test_explicit_scales_do_not_depend_on_height(self, mode, expected):
        runtime = _runtime(["--temp-range", mode, "--celsius"])
        for rows in (2, 20):
            assert temperature_scale(runtime, _archive(40, -10),
                                     (10, 20), n_rows=rows) == expected


class TestFlash:
    def test_a_note_comes_down_when_its_time_is_up(self, monkeypatch):
        from linecast import _live
        from linecast.weather import WeatherApp
        view = WeatherApp({}, [], None, 43.7, -79.4, _runtime())
        view.flash(["hello"], seconds=0.0)
        monkeypatch.setattr(_live._time, "monotonic", lambda: 10 ** 9)
        assert view.flash_overlay(80, 24) == ""
        assert view._flash is None

    def test_a_note_is_boxed_while_it_is_up(self):
        from linecast.weather import WeatherApp
        view = WeatherApp({}, [], None, 43.7, -79.4, _runtime())
        view.flash(["hello there"], seconds=60.0)
        box = view.flash_overlay(80, 24)
        assert "hello there" in box and "┌" in box


class TestAxisLabels:
    def _blank_rows(self, n_rows, graph_w):
        return [[("\u2800", 0.0)] * graph_w for _ in range(n_rows)]

    def test_labels_the_two_ends_at_the_left_edge(self):
        from linecast._weather.hourly import _compute_axis_overlays
        overlays = {}
        _compute_axis_overlays((-15, 100), self._blank_rows(8, 80), 8, 80, overlays)
        assert overlays == {0: [(1, "100°", overlays[0][0][2])],
                            7: [(1, "-15°", overlays[7][0][2])]}

    def test_forecast_bounds_are_rounded_to_whole_degrees(self):
        from linecast._weather.hourly import _compute_axis_overlays
        overlays = {}
        _compute_axis_overlays((26.4, 63.6), self._blank_rows(2, 40), 2, 40, overlays)
        assert [items[0][1] for _r, items in sorted(overlays.items())] == ["64°", "26°"]

    def test_sits_just_past_the_now_line(self):
        from linecast._weather.hourly import _compute_axis_overlays
        overlays = {}
        _compute_axis_overlays((58.0, 75.0), self._blank_rows(8, 120), 8, 120, overlays,
                               now_col=2)
        assert all(items[0][0] == 3 for items in overlays.values())

    def test_moves_to_the_right_edge_when_the_curve_is_in_the_way(self):
        from linecast._weather.hourly import _compute_axis_overlays
        rows = self._blank_rows(2, 40)
        rows[0][1] = ("\u2847", 20.0)  # dots under the left label's first cell
        overlays = {}
        _compute_axis_overlays((10.0, 20.0), rows, 2, 40, overlays)
        assert overlays[0] == [(40 - 4, "20°", overlays[0][0][2])]

    def test_skips_an_end_whose_edges_are_both_taken(self):
        from linecast._weather.hourly import _compute_axis_overlays
        rows = self._blank_rows(2, 40)
        overlays = {0: [(0, "20°", (1, 2, 3)), (36, "20°", (1, 2, 3))]}
        _compute_axis_overlays((10.0, 20.0), rows, 2, 40, overlays)
        assert len(overlays[0]) == 2 and overlays[1][0][1] == "10°"
