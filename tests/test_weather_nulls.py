"""Nulls in the weather data: the view degrades, it does not die.

Open-Meteo writes null for an hour or a day it has no value for, and
for a whole variable where the model does not carry it.  Every render
path -- the dashboard at two sizes, --json, --oneline -- is run over
the fixture with one field nulled at a time, at an index in the past
day, one inside the visible window, and the last one.  The alert
parsers get the same for the fields their feeds have sent null in.
"""

import copy
import json
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from linecast._weather import sources
from linecast import weather
from linecast._oneline import weather_oneline
from linecast._runtime import WeatherRuntime, weather_parser
from linecast._weather.alerts import build_alert_modal, render_alerts_mapped
from linecast._weather.historical import HistoricalAverages
from linecast._weather.json import build_payload
from linecast._weather.sections import comparative_sentence

FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 3, 5, 14, 30)
HIST = HistoricalAverages(avg_high=40.0, avg_low=25.0, avg_precip=0.1, years=10,
                          year_high=91.3, year_low=-3.6)

HOURLY_FIELDS = ("temperature_2m", "apparent_temperature", "precipitation",
                 "precipitation_probability", "weather_code", "wind_speed_10m",
                 "wind_gusts_10m", "wind_direction_10m", "relative_humidity_2m",
                 "dew_point_2m", "uv_index", "cloud_cover", "snowfall")
DAILY_FIELDS = ("temperature_2m_max", "temperature_2m_min", "precipitation_sum",
                "precipitation_probability_max", "weather_code", "wind_speed_10m_max",
                "wind_gusts_10m_max", "sunrise", "sunset")
CURRENT_FIELDS = ("temperature_2m", "apparent_temperature", "weather_code",
                  "wind_speed_10m", "wind_gusts_10m", "relative_humidity_2m",
                  "dew_point_2m")


def _runtime(*argv):
    namespace = weather_parser().parse_args(["--print", *argv])
    return WeatherRuntime.from_sources(namespace, environ={})


def _fixture():
    """The saved forecast, with the fields the current request adds."""
    data = json.loads((FIXTURES / "open_meteo_forecast.json").read_text(encoding="utf-8"))
    hourly = data["hourly"]
    n = len(hourly["time"])
    hourly["relative_humidity_2m"] = [60] * n
    hourly["dew_point_2m"] = [20.0] * n
    hourly["uv_index"] = [0.0 if (i % 24) < 8 or (i % 24) > 17 else 7.0 for i in range(n)]
    hourly["cloud_cover"] = [(i * 7) % 100 for i in range(n)]
    hourly["snowfall"] = [0.0] * n
    # a windy hour in the window, so the wind row and its chip have work
    hourly["wind_speed_10m"][hourly["time"].index("2026-03-05T17:00")] = 30.0
    data["current"]["relative_humidity_2m"] = 60
    data["current"]["dew_point_2m"] = 20.0
    return data


def _mutations():
    data = _fixture()
    now_i = data["hourly"]["time"].index("2026-03-05T14:00")
    for key in HOURLY_FIELDS:
        for label, index in (("past", 2), ("window", now_i + 3), ("last", -1)):
            m = copy.deepcopy(data)
            m["hourly"][key][index] = None
            yield f"hourly.{key}[{label}]", m
        m = copy.deepcopy(data)
        m["hourly"][key] = [None] * len(m["hourly"]["time"])
        yield f"hourly.{key}[all]", m
    for key in DAILY_FIELDS:
        for label, index in (("yesterday", 0), ("today", 1), ("tomorrow", 2), ("last", -1)):
            m = copy.deepcopy(data)
            m["daily"][key][index] = None
            yield f"daily.{key}[{label}]", m
        m = copy.deepcopy(data)
        m["daily"][key] = [None] * len(m["daily"]["time"])
        yield f"daily.{key}[all]", m
    for key in CURRENT_FIELDS:
        m = copy.deepcopy(data)
        m["current"][key] = None
        yield f"current.{key}", m


MUTATIONS = list(_mutations())


def _render(data, cols, rows, runtime, mouse_pos=None):
    with patch("linecast.weather.get_terminal_size", return_value=(cols, rows)), \
         patch("linecast.weather._local_now_for_data", return_value=NOW), \
         patch("linecast._weather.hourly._local_now_for_data", return_value=NOW), \
         patch("linecast._weather.daily._local_now_for_data", return_value=NOW):
        output, _ = weather.render_from_data(
            data, [], runtime, location_name="Toronto", historical=HIST,
            mouse_pos=mouse_pos)
    return output


@pytest.mark.parametrize("name,data", MUTATIONS, ids=[name for name, _ in MUTATIONS])
class TestOneNull:
    def test_the_dashboard_renders(self, name, data):
        for cols, rows in ((100, 40), (40, 10)):
            output = _render(copy.deepcopy(data), cols, rows, _runtime())
            assert output and "Could not fetch" not in output

    def test_the_hover_chips_render(self, name, data):
        # the hourly chip across the chart, the daily chip down the rows
        for col in range(1, 100, 9):
            _render(copy.deepcopy(data), 100, 40, _runtime(), mouse_pos=(col, 5))
        for row in range(1, 40, 3):
            _render(copy.deepcopy(data), 100, 40, _runtime(), mouse_pos=(50, row))

    def test_json_serialises(self, name, data):
        payload = build_payload(copy.deepcopy(data), "Toronto", "CA", _runtime(),
                                historical=HIST, now=NOW)
        json.dumps(payload, ensure_ascii=False, allow_nan=False)

    def test_oneline_renders(self, name, data):
        assert weather_oneline(copy.deepcopy(data), "Toronto", _runtime())


class TestWhatANullBecomes:
    def test_a_null_high_drops_the_comparison_sentence(self):
        morning = NOW.replace(hour=9)   # today against yesterday
        daily = {"temperature_2m_max": [50.0, None, 60.0]}
        assert comparative_sentence(daily, NOW, _runtime()) == ""
        assert comparative_sentence(daily, morning, _runtime()) == ""
        daily = {"temperature_2m_max": [None, 55.0, 60.0]}
        assert comparative_sentence(daily, morning, _runtime()) == ""
        daily = {"temperature_2m_max": [50.0, 55.0, None]}
        assert comparative_sentence(daily, NOW, _runtime()) == ""
        daily = {"temperature_2m_max": [50.0, 55.0, 60.0]}
        assert comparative_sentence(daily, NOW, _runtime())
        assert comparative_sentence(daily, morning, _runtime())

    def test_a_null_current_temperature_is_left_off_not_printed_as_zero(self):
        data = _fixture()
        data["current"]["temperature_2m"] = None
        line = weather_oneline(data, "Toronto", _runtime())
        assert "0°" not in line
        header = _render(data, 100, 40, _runtime()).split("\n")[0]
        assert "0°F" not in header

    def test_a_day_with_no_temperatures_gets_no_row(self):
        from linecast._weather.daily import render_daily_mapped
        data = _fixture()
        data["daily"]["temperature_2m_max"][3] = None
        lines, spans = render_daily_mapped(data, 100, _runtime(), now=NOW)
        assert [span["index"] for span in spans] == [1, 2, 4, 5, 6, 7]
        assert len(lines) == 6

    def test_a_null_hour_in_the_curve_carries_its_neighbour(self):
        from linecast._weather.hourly import _filled, _present
        assert _filled([None, 3.0, None, None, 5.0, None]) == [3.0, 3.0, 3.0, 3.0, 5.0, 5.0]
        assert _filled([None, None]) == []
        assert _filled([None, 0.2, None], fill=0) == [0, 0.2, 0]
        assert _present([None, 1, None, 2]) == [1, 2]

    def test_daylight_columns_never_go_through_the_machine_clock(self):
        # Interpolated in place, so a window on the machine's DST night
        # keeps its hours: the round trip through a timestamp used to
        # move 02:00 to 03:00 in a zone that springs forward then.
        from datetime import timedelta
        from linecast._weather.hourly import _compute_daylight_columns, _daylight_factor
        dts = [datetime(2026, 3, 8, 0, 0) + timedelta(hours=h) for h in range(25)]
        events = [(datetime(2026, 3, 8, 2, 0), datetime(2026, 3, 8, 2, 30))]
        cols = _compute_daylight_columns(dts, events, 25)
        assert cols == [_daylight_factor(dt, events) for dt in dts]


def _with_feed(payload, fn):
    with patch.object(sources, "fetch_json_cached", return_value=payload), \
         patch.object(sources, "write_cache"):
        return fn()


def _load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class TestAlertFeedsWithNulls:
    def test_jma_with_a_null_headline_renders_and_serialises(self):
        data = _load("jma_warning_tokyo.json")
        data["headlineText"] = None
        data["reportDatetime"] = None
        alerts = _with_feed(data, lambda: sources.fetch_alerts(35.7, 139.7, "JP"))
        assert alerts
        assert all(alert["description"] == "" for alert in alerts)
        lines, _spans = render_alerts_mapped(alerts, 80, runtime=_runtime())
        assert lines
        build_alert_modal(alerts[0], 80, 24, runtime=_runtime())
        json.dumps(alerts)

    def test_an_alert_with_null_text_fields_renders(self):
        alert = {"event": None, "headline": None, "description": None,
                 "effective": None, "expires": None, "severity": None, "url": None}
        lines, _spans = render_alerts_mapped([alert], 80, runtime=_runtime())
        assert lines
        build_alert_modal(alert, 80, 24, runtime=_runtime())

    def test_eccc_with_a_null_name_falls_through_to_the_other_language(self):
        data = _load("eccc_alerts.json")
        feature = data["features"][0]
        feature["properties"]["alert_name_en"] = None
        feature["properties"]["alert_short_name_en"] = None
        feature["properties"]["alert_name_fr"] = "avertissement de pluie"
        # the parser itself: fetch_alerts would drop the fixture's alerts
        # as expired
        alerts = _with_feed(data, lambda: sources._fetch_alerts_eccc(45.0, -75.0))
        assert any(alert["event"] == "Avertissement de pluie" for alert in alerts)

    def test_meteoalarm_with_null_language_alert_and_area(self):
        data = _load("meteoalarm_netherlands.json")
        info = data["warnings"][0]["alert"]["info"][0]
        info["language"] = None
        info["severity"] = None
        data["warnings"][1]["alert"] = None
        data["warnings"][2]["alert"]["info"][0]["area"] = None
        alerts = _with_feed(data, lambda: sources.fetch_alerts(
            52.4, 4.9, "NL", address={"city": "Amsterdam"}))
        assert isinstance(alerts, list)

    def test_cma_with_null_ids_and_titles(self):
        data = _load("cma_warnings.json")
        entry = data["data"]["page"]["list"][0]
        entry["alertid"] = None
        entry["title"] = None
        assert isinstance(sources._parse_cma_data(data, ["11", "12", "13"]), list)
        data["data"] = None
        assert sources._parse_cma_data(data, ["11"]) == []

    def test_met_eireann_with_a_null_category(self):
        data = _load("meteireann_warnings.json")
        data["warnings"]["national"] = None
        alerts = _with_feed(data, lambda: sources.fetch_alerts(53.0, -6.0, "IE"))
        assert isinstance(alerts, list)

    def test_met_norway_with_a_null_when(self):
        data = _load("metno_alerts.json")
        if not data.get("features"):
            data["features"] = [{"properties": {"event": "Gale", "severity": "Moderate"}}]
        data["features"][0]["when"] = None
        alerts = _with_feed(data, lambda: sources.fetch_alerts(60.0, 10.0, "NO"))
        assert alerts and alerts[0]["expires"] == ""


class TestGather:
    """A provider that raises costs only its own entry."""

    def test_an_alert_parser_that_raises_keeps_the_air_quality_and_climate(self):
        with patch.object(weather, "_reverse_geocode", return_value=("Westbrook", "US", {})), \
             patch.object(weather, "fetch_forecast", return_value={"v": 1}), \
             patch.object(weather, "fetch_aqi", return_value={"aqi": 1}), \
             patch.object(weather, "fetch_historical", return_value=HIST), \
             patch.object(weather, "fetch_alerts", side_effect=TypeError("null")):
            result = weather.gather(43.0, -70.0, "", _runtime())
        assert result["data"] == {"v": 1}
        assert result["aqi"] == {"aqi": 1}
        assert result["historical"] is HIST
        assert result["alerts"] == []
        assert result["name"] == "Westbrook" and result["country_code"] == "US"

    def _gather(self, geocode, lang, geo_label=""):
        with patch.object(weather, "_reverse_geocode", side_effect=geocode), \
             patch.object(weather, "fetch_forecast", return_value={"v": 1}), \
             patch.object(weather, "fetch_aqi", return_value=None), \
             patch.object(weather, "fetch_historical", return_value=None), \
             patch.object(weather, "fetch_alerts", return_value=[]) as alerts:
            result = weather.gather(52.23, 21.01, "", _runtime("--lang", lang),
                                    geo_label=geo_label)
        return result, alerts

    @staticmethod
    def _warsaw(lat, lng, lang=None):
        if lang == "fr":
            return "Varsovie, Mazovie", "PL", {"city": "Varsovie"}
        if lang == "zh-Hant":
            return "華沙, 馬佐夫舍省", "PL", {"city": "華沙"}
        return "Warszawa, województwo mazowieckie", "PL", {"city": "Warszawa"}

    def test_coordinates_are_named_in_the_users_language(self):
        # MeteoAlarm's area names are in the country's language, so the
        # address they are matched against has to be too.
        result, alerts = self._gather(self._warsaw, "fr")
        assert result["name"] == "Varsovie, Mazovie"
        alerts.assert_called_once_with(52.23, 21.01, "PL", lang="fr",
                                       address={"city": "Warszawa"})

    def test_a_typed_place_keeps_the_geocoders_label(self):
        # Reverse geocoding names whatever boundary encloses the point;
        # the label names what was asked for, and is not asked again.
        calls = []

        def geocode(lat, lng, lang=None):
            calls.append(lang)
            return self._warsaw(lat, lng, lang)

        result, _alerts = self._gather(geocode, "fr", "Varsovie, Voïvodie de Mazovie, Pologne")
        assert result["name"] == "Varsovie, Voïvodie de Mazovie"
        assert calls == [None]

    def test_traditional_chinese_prefers_nominatim_over_the_english_label(self):
        result, _alerts = self._gather(self._warsaw, "zh-Hant", "Warsaw, Mazovia, Poland")
        assert result["name"] == "華沙, 馬佐夫舍省"

    def test_traditional_chinese_falls_back_to_the_label(self):
        def geocode(lat, lng, lang=None):
            return ("", "PL", {}) if lang else self._warsaw(lat, lng)

        result, _alerts = self._gather(geocode, "zh-Hant", "Warsaw, Mazovia, Poland")
        assert result["name"] == "Warsaw, Mazovia"

    def test_a_geocoder_that_raises_keeps_the_forecast_and_the_typed_name(self):
        with patch.object(weather, "_reverse_geocode", side_effect=OSError("down")), \
             patch.object(weather, "fetch_forecast", return_value={"v": 1}), \
             patch.object(weather, "fetch_aqi", return_value=None), \
             patch.object(weather, "fetch_historical", return_value=None), \
             patch.object(weather, "fetch_alerts", return_value=[]) as alerts:
            result = weather.gather(43.0, -70.0, "US", _runtime(), geo_label="Home")
        assert result["data"] == {"v": 1}
        assert result["name"] == "Home"
        alerts.assert_called_once_with(43.0, -70.0, "US", lang="en", address={})
