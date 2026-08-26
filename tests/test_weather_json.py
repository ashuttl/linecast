"""Tests for the `weather --json` machine-readable payload."""

import json
import sys
from datetime import datetime
from pathlib import Path

# Ensure the worktree src is preferred over any installed version.
# (No sys.modules purge here: this file is collected after other test
# modules that hold references into already-imported linecast modules.)
_src = str(Path(__file__).resolve().parent.parent / "src")
if _src not in sys.path:
    sys.path.insert(0, _src)

from linecast._runtime import WeatherRuntime, weather_parser
from linecast._weather_historical import HistoricalAverages
from linecast._weather_json import build_payload

FIXTURES = Path(__file__).parent / "fixtures"

# Matches test_render_snapshots.py — fixture data covers 2026-03-04..03-11
FIXED_NOW = datetime(2026, 3, 5, 14, 30)

EXPECTED_TOP_KEYS = {
    "schema", "location", "country_code", "timezone", "fetched_at", "summary",
    "units", "current", "today", "hourly", "daily", "alerts", "aqi",
    "historical",
}


def _load_fixture():
    return json.loads((FIXTURES / "open_meteo_forecast.json").read_text())


def _runtime(**overrides):
    defaults = dict(
        live=False, icons="emoji", lang="en", oneline=False,
        celsius=False, metric=False, shading=False,
    )
    defaults.update(overrides)
    return WeatherRuntime(**defaults)


def _payload(**kwargs):
    defaults = dict(
        data=_load_fixture(),
        location_name="Toronto, Ontario",
        country_code="CA",
        runtime=_runtime(),
        now=FIXED_NOW,
    )
    defaults.update(kwargs)
    return build_payload(**defaults)


class TestPayloadShape:
    def test_top_level_keys_exact(self):
        assert set(_payload().keys()) == EXPECTED_TOP_KEYS

    def test_round_trips_through_json(self):
        payload = _payload()
        text = json.dumps(payload, ensure_ascii=False)
        assert json.loads(text) == payload

    def test_schema_and_identity(self):
        p = _payload()
        assert p["schema"] == 1
        assert p["location"] == "Toronto, Ontario"
        assert p["country_code"] == "CA"
        assert p["timezone"] == "America/Toronto"
        assert p["fetched_at"] == "2026-03-05T21:00"

    def test_summary_compares_tomorrow_after_2pm(self):
        # FIXED_NOW is 14:30, so the sentence looks ahead: tomorrow vs today.
        summary = _payload()["summary"]
        assert isinstance(summary, str) and summary
        assert "Tomorrow will be" in summary
        assert "today" in summary

    def test_summary_compares_yesterday_before_2pm(self):
        summary = _payload(now=FIXED_NOW.replace(hour=9))["summary"]
        assert isinstance(summary, str) and summary
        assert "Today will be" in summary
        assert "yesterday" in summary

    def test_summary_null_without_daily_history(self):
        data = _load_fixture()
        data["daily"]["temperature_2m_max"] = data["daily"]["temperature_2m_max"][:2]
        assert _payload(data=data)["summary"] is None

    def test_units_imperial_default(self):
        assert _payload()["units"] == {
            "temperature": "°F", "wind": "mph", "precipitation": "″",
        }

    def test_units_metric(self):
        p = _payload(runtime=_runtime(celsius=True, metric=True))
        assert p["units"] == {
            "temperature": "°C", "wind": "km/h", "precipitation": "mm",
        }


class TestCurrent:
    def test_current_fields(self):
        data = _load_fixture()
        cur = _payload()["current"]
        assert cur["time"] == data["current"]["time"]
        assert cur["temperature"] == data["current"]["temperature_2m"]
        assert cur["feels_like"] == data["current"]["apparent_temperature"]
        assert cur["wind_speed"] == data["current"]["wind_speed_10m"]
        assert cur["wind_gusts"] == data["current"]["wind_gusts_10m"]
        assert cur["weather_code"] == data["current"]["weather_code"]
        assert cur["condition"] == "Overcast"  # WMO 3
        assert isinstance(cur["icon"], str) and cur["icon"]

    def test_current_missing_humidity_is_null(self):
        # The older fixture lacks relative_humidity_2m / dew_point_2m
        cur = _payload()["current"]
        assert cur["humidity"] is None
        assert cur["dew_point"] is None

    def test_localized_condition(self):
        cur = _payload(runtime=_runtime(lang="fr"))["current"]
        assert cur["condition"] == "Couvert"


class TestHourly:
    def test_hourly_starts_at_current_hour(self):
        data = _load_fixture()
        hourly = _payload()["hourly"]
        # FIXED_NOW is 2026-03-05 14:30 → current hour is 14:00 today,
        # which is index 24 + 14 = 38 in the past_days=1 arrays.
        assert hourly[0]["time"] == "2026-03-05T14:00"
        assert hourly[0]["temperature"] == data["hourly"]["temperature_2m"][38]

    def test_hourly_runs_to_end_of_forecast(self):
        data = _load_fixture()
        # From index 38 (current hour) to the end of the arrays.
        assert len(_payload()["hourly"]) == len(data["hourly"]["time"]) - 38

    def test_hourly_entry_shape(self):
        entry = _payload()["hourly"][0]
        assert set(entry.keys()) == {
            "time", "temperature", "feels_like", "precipitation_probability",
            "precipitation", "weather_code", "icon", "condition",
            "wind_speed", "wind_direction", "uv_index",
        }
        assert entry["condition"] is not None
        assert entry["icon"] is not None

    def test_hourly_wind_and_uv_null_on_old_fixture(self):
        # The checked-in fixture predates the wind/uv hourly keys; the
        # builder must emit nulls rather than raising.
        entry = _payload()["hourly"][0]
        assert entry["wind_speed"] is None or isinstance(entry["wind_speed"], (int, float))
        assert entry["uv_index"] is None or isinstance(entry["uv_index"], (int, float))

    def test_hourly_truncates_when_data_runs_short(self):
        data = _load_fixture()
        for key in data["hourly"]:
            data["hourly"][key] = data["hourly"][key][:48]  # ends midnight tonight
        hourly = _payload(data=data)["hourly"]
        assert len(hourly) == 10  # 14:00 .. 23:00
        assert hourly[-1]["time"] == "2026-03-05T23:00"


class TestDaily:
    def test_daily_starts_today_not_yesterday(self):
        daily = _payload()["daily"]
        assert daily[0]["date"] == "2026-03-05"

    def test_daily_seven_entries(self):
        assert len(_payload()["daily"]) == 7

    def test_daily_entry_matches_fixture(self):
        data = _load_fixture()
        day0 = _payload()["daily"][0]
        assert day0["high"] == data["daily"]["temperature_2m_max"][1]
        assert day0["low"] == data["daily"]["temperature_2m_min"][1]
        assert day0["sunrise"] == data["daily"]["sunrise"][1]
        assert day0["sunset"] == data["daily"]["sunset"][1]
        assert set(day0.keys()) == {
            "date", "high", "low", "precipitation_probability",
            "precipitation", "weather_code", "icon", "condition",
            "sunrise", "sunset", "wind_speed", "wind_gusts",
        }

    def test_today_block_is_daily_index_1(self):
        data = _load_fixture()
        today = _payload()["today"]
        assert today["high"] == data["daily"]["temperature_2m_max"][1]
        assert today["low"] == data["daily"]["temperature_2m_min"][1]
        assert today["sunrise"] == data["daily"]["sunrise"][1]
        assert today["precipitation"] == data["daily"]["precipitation_sum"][1]


class TestOptionalSections:
    def test_none_tolerance(self):
        p = _payload(alerts=None, aqi_data=None, historical=None)
        assert p["alerts"] == []
        assert p["aqi"] is None
        assert p["historical"] is None

    def test_alerts_pass_through(self):
        alert = {"event": "Wind Warning", "headline": "h", "description": "d",
                 "effective": "e", "expires": "x", "severity": "moderate",
                 "url": "https://example.com"}
        assert _payload(alerts=[alert])["alerts"] == [alert]

    def test_aqi_mapping(self):
        aqi = {"current": {"us_aqi": 42, "european_aqi": 30,
                           "pm2_5": 8.1, "pm10": 12.0}}
        assert _payload(aqi_data=aqi)["aqi"] == {
            "us_aqi": 42, "european_aqi": 30, "pm2_5": 8.1, "pm10": 12.0,
        }

    def test_historical_asdict(self):
        hist = HistoricalAverages(avg_high=41.2, avg_low=26.7,
                                  avg_precip=0.11, years=10)
        assert _payload(historical=hist)["historical"] == {
            "avg_high": 41.2, "avg_low": 26.7, "avg_precip": 0.11, "years": 10,
        }

    def test_empty_data_yields_nulls_not_errors(self):
        p = build_payload({}, "", "", _runtime(), now=FIXED_NOW)
        assert p["current"]["temperature"] is None
        assert p["today"]["high"] is None
        assert p["hourly"] == []
        assert p["daily"] == []
        assert p["timezone"] is None
        assert p["country_code"] is None


class TestLiveSuppression:
    def test_json_flag_forces_live_off(self):
        args = weather_parser().parse_args(["--json", "--live"])
        runtime = WeatherRuntime.from_sources(namespace=args)
        assert runtime.json_mode is True
        assert runtime.live is False

    def test_json_mode_defaults_false(self):
        runtime = _runtime()
        assert runtime.json_mode is False
