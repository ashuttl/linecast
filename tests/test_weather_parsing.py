"""Tests for weather API response parsing.

These use real API responses saved as fixtures. If an upstream API changes
its response format, these tests will catch the breakage.
"""

import json
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import patch, MagicMock

FIXTURES = Path(__file__).parent / "fixtures"

# Ensure the package is importable
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


def _load(name):
    return json.loads((FIXTURES / name).read_text())


# ---------------------------------------------------------------------------
# Open-Meteo forecast parsing
# ---------------------------------------------------------------------------

class TestOpenMeteoForecast:
    """Verify we can parse a real Open-Meteo response without errors."""

    def setup_method(self):
        self.data = _load("open_meteo_forecast.json")

    def test_top_level_keys(self):
        for key in ("current", "hourly", "daily", "timezone", "utc_offset_seconds"):
            assert key in self.data, f"Missing top-level key: {key}"

    def test_current_conditions(self):
        current = self.data["current"]
        for key in ("temperature_2m", "apparent_temperature", "weather_code",
                     "wind_speed_10m", "wind_gusts_10m"):
            assert key in current, f"Missing current key: {key}"
            assert isinstance(current[key], (int, float)), f"{key} should be numeric"

    def test_hourly_arrays_aligned(self):
        hourly = self.data["hourly"]
        n = len(hourly["time"])
        assert n > 0, "No hourly time entries"
        for key in ("temperature_2m", "precipitation_probability",
                     "weather_code", "wind_speed_10m"):
            assert key in hourly, f"Missing hourly key: {key}"
            assert len(hourly[key]) == n, f"hourly[{key}] length mismatch"

    def test_daily_arrays_aligned(self):
        daily = self.data["daily"]
        n = len(daily["time"])
        assert n > 0, "No daily time entries"
        for key in ("temperature_2m_max", "temperature_2m_min",
                     "precipitation_sum", "weather_code", "sunrise", "sunset"):
            assert key in daily, f"Missing daily key: {key}"
            assert len(daily[key]) == n, f"daily[{key}] length mismatch"

    def test_hourly_timestamps_parseable(self):
        for t in self.data["hourly"]["time"][:5]:
            dt = datetime.fromisoformat(t)
            assert dt.year >= 2024

    def test_daily_sunrise_sunset_parseable(self):
        daily = self.data["daily"]
        for s in daily["sunrise"]:
            if s:
                dt = datetime.fromisoformat(s)
                assert dt.hour < 12  # sunrise before noon

    def test_render_header_succeeds(self):
        """Smoke test: render_header doesn't crash on real data."""
        import linecast.weather as w
        result = w.render_header(self.data, 80, "Test City")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_render_hourly_succeeds(self):
        """Smoke test: render_hourly doesn't crash on real data."""
        import linecast.weather as w
        now = datetime.fromisoformat(self.data["hourly"]["time"][24])
        result = w.render_hourly(self.data, 80, now=now)
        assert isinstance(result, list)

    def test_comparative_line_succeeds(self):
        """Smoke test: _comparative_line doesn't crash on real data."""
        import linecast.weather as w
        now = datetime.fromisoformat(self.data["hourly"]["time"][24])
        result = w._comparative_line(self.data["daily"], now)
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# NWS alerts parsing
# ---------------------------------------------------------------------------

class TestNWSAlerts:
    """Verify we can parse a real NWS alerts response."""

    def setup_method(self):
        self.data = _load("nws_alerts.json")

    def test_top_level_structure(self):
        assert "features" in self.data
        assert isinstance(self.data["features"], list)

    def test_alert_properties_shape(self):
        """If there are alerts, each has the fields we extract."""
        for feature in self.data["features"]:
            props = feature["properties"]
            # These are the fields _fetch_alerts_nws extracts
            for key in ("event", "headline", "description", "severity"):
                assert key in props, f"Missing alert property: {key}"


# ---------------------------------------------------------------------------
# ECCC alerts parsing
# ---------------------------------------------------------------------------

class TestECCCAlerts:
    """Verify we can parse a real ECCC alerts response."""

    def setup_method(self):
        self.data = _load("eccc_alerts.json")

    def test_top_level_structure(self):
        assert "features" in self.data
        assert isinstance(self.data["features"], list)

    def test_alert_properties_shape(self):
        """If there are alerts, each has the fields we extract."""
        for feature in self.data["features"]:
            props = feature["properties"]
            # At minimum, ECCC features have these
            assert isinstance(props, dict)
