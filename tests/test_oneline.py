"""Tests for --oneline compact single-line renderers."""

import importlib
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

# Ensure the worktree src is preferred over any installed version.
_src = str(Path(__file__).resolve().parent.parent / "src")
if _src not in sys.path:
    sys.path.insert(0, _src)
# Force re-import from the worktree if linecast was already loaded.
for _key in sorted(sys.modules):
    if _key == "linecast" or _key.startswith("linecast."):
        del sys.modules[_key]

from linecast._oneline import weather_oneline, sunshine_oneline, tides_oneline
from linecast._runtime import WeatherRuntime, TidesRuntime, RuntimeConfig


# Strip ANSI escape sequences for content assertions
def _strip_ansi(s):
    return re.sub(r"\x1b\[[0-9;]*m", "", s)


# ---------------------------------------------------------------------------
# Weather oneline
# ---------------------------------------------------------------------------

class TestWeatherOneline:
    def _runtime(self, **overrides):
        defaults = dict(
            live=False, emoji=True, lang="en", oneline=True,
            celsius=False, metric=False, shading=True,
        )
        defaults.update(overrides)
        return WeatherRuntime(**defaults)

    def _sample_data(self):
        return {
            "current": {
                "temperature_2m": 58,
                "apparent_temperature": 55,
                "weather_code": 2,
                "wind_speed_10m": 8,
                "wind_gusts_10m": 12,
                "relative_humidity_2m": 32,
                "dew_point_2m": 40,
            },
        }

    def test_basic_output(self):
        rt = self._runtime()
        line = weather_oneline(self._sample_data(), "Portland, ME", rt)
        plain = _strip_ansi(line)
        assert "Portland" in plain
        assert "58" in plain
        assert "Partly Cloudy" in plain

    def test_no_data(self):
        rt = self._runtime()
        line = weather_oneline(None, "Portland", rt)
        assert "No weather data" in line

    def test_metric_units(self):
        rt = self._runtime(celsius=True, metric=True)
        data = self._sample_data()
        data["current"]["temperature_2m"] = 14  # Celsius value
        data["current"]["wind_speed_10m"] = 12
        line = weather_oneline(data, "Berlin", rt)
        plain = _strip_ansi(line)
        assert "km/h" in plain
        assert "\u00b0C" in plain

    def test_imperial_units(self):
        rt = self._runtime(celsius=False, metric=False)
        line = weather_oneline(self._sample_data(), "Portland", rt)
        plain = _strip_ansi(line)
        assert "mph" in plain
        assert "\u00b0F" in plain

    def test_humidity_shown(self):
        rt = self._runtime()
        line = weather_oneline(self._sample_data(), "Portland", rt)
        plain = _strip_ansi(line)
        assert "32%" in plain

    def test_localized_description(self):
        rt = self._runtime(lang="fr")
        line = weather_oneline(self._sample_data(), "Paris", rt)
        plain = _strip_ansi(line)
        assert "Partiellement nuageux" in plain

    def test_no_location(self):
        rt = self._runtime()
        line = weather_oneline(self._sample_data(), "", rt)
        plain = _strip_ansi(line)
        # Should not crash and should still have temperature
        assert "58" in plain

    def test_short_location_name(self):
        """Only the first part of a comma-separated location is used."""
        rt = self._runtime()
        line = weather_oneline(self._sample_data(), "Portland, ME, US", rt)
        plain = _strip_ansi(line)
        assert "Portland" in plain
        assert "ME" not in plain


# ---------------------------------------------------------------------------
# Sunshine oneline
# ---------------------------------------------------------------------------

class TestSunshineOneline:
    def _runtime(self, **overrides):
        defaults = dict(live=False, emoji=True, lang="en", oneline=True)
        defaults.update(overrides)
        return RuntimeConfig(**defaults)

    def test_basic_output(self):
        # Portland, ME in summer (doy=172 = ~June 21)
        rt = self._runtime()
        line = sunshine_oneline(43.66, -70.26, 172, 12.0, rt)
        plain = _strip_ansi(line)
        # Should contain up/down arrows and time-like patterns
        assert "\u2191" in plain  # sunrise arrow
        assert "\u2193" in plain  # sunset arrow
        assert "h" in plain       # day length hours

    def test_contains_delta(self):
        rt = self._runtime()
        line = sunshine_oneline(43.66, -70.26, 172, 12.0, rt)
        plain = _strip_ansi(line)
        # Delta should have + or - sign with m (minutes)
        assert re.search(r"[+\u2212]\d+m", plain)

    def test_24h_format(self):
        rt = self._runtime(lang="fr")
        line = sunshine_oneline(48.86, 2.35, 172, 12.0, rt)
        plain = _strip_ansi(line)
        # 24h format should have HH:MM without a/p
        assert "a" not in plain.split("h")[0] or ":" in plain


# ---------------------------------------------------------------------------
# Tides oneline
# ---------------------------------------------------------------------------

class TestTidesOneline:
    def _runtime(self, **overrides):
        defaults = dict(live=False, emoji=True, lang="en", oneline=True, metric=False)
        defaults.update(overrides)
        return TidesRuntime(**defaults)

    def test_basic_output(self):
        rt = self._runtime()
        now = datetime(2026, 3, 27, 12, 0)
        hilo = [
            (datetime(2026, 3, 27, 8, 14), 9.2, "H"),
            (datetime(2026, 3, 27, 14, 47), 1.1, "L"),
            (datetime(2026, 3, 27, 20, 30), 8.5, "H"),
        ]
        line = tides_oneline("Casco Bay, ME", hilo, now, rt)
        plain = _strip_ansi(line)
        assert "Casco Bay" in plain
        assert "\u25b2" in plain or "High" in plain  # high tide marker
        assert "\u25bc" in plain or "Low" in plain    # low tide marker

    def test_no_hilo_data(self):
        rt = self._runtime()
        now = datetime(2026, 3, 27, 12, 0)
        line = tides_oneline("Portland, ME", [], now, rt)
        plain = _strip_ansi(line)
        assert "No tide data" in plain

    def test_metric_heights(self):
        rt = self._runtime(metric=True)
        now = datetime(2026, 3, 27, 12, 0)
        hilo = [
            (datetime(2026, 3, 27, 14, 0), 9.2, "H"),
            (datetime(2026, 3, 27, 20, 0), 1.1, "L"),
        ]
        line = tides_oneline("Station", hilo, now, rt)
        plain = _strip_ansi(line)
        # Metric uses meters, so 9.2ft * 0.3048 = ~2.8m
        assert "m" in plain
        # Height should be converted
        assert "2.8" in plain

    def test_upcoming_events_preferred(self):
        """When there are both past and future events, upcoming ones are shown."""
        rt = self._runtime()
        now = datetime(2026, 3, 27, 12, 0)
        hilo = [
            (datetime(2026, 3, 27, 6, 0), 8.0, "H"),   # past
            (datetime(2026, 3, 27, 13, 0), 1.5, "L"),   # upcoming
            (datetime(2026, 3, 27, 19, 0), 9.0, "H"),   # upcoming
        ]
        line = tides_oneline("Bay", hilo, now, rt)
        plain = _strip_ansi(line)
        # Should show the two upcoming events
        assert "1.5" in plain
        assert "9.0" in plain

    def test_short_station_name(self):
        rt = self._runtime()
        now = datetime(2026, 3, 27, 12, 0)
        hilo = [
            (datetime(2026, 3, 27, 14, 0), 5.0, "H"),
            (datetime(2026, 3, 27, 20, 0), 2.0, "L"),
        ]
        line = tides_oneline("Portland, ME", hilo, now, rt)
        plain = _strip_ansi(line)
        assert "Portland" in plain
        assert "ME" not in plain
