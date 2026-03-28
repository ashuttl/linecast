"""Tests for historical weather comparison feature."""

import sys
from datetime import date
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from linecast._weather_historical import (
    HistoricalAverages,
    _compute_averages,
    fetch_historical,
    format_historical_comparison,
)
from linecast._runtime import WeatherRuntime


# ---------------------------------------------------------------------------
# _compute_averages
# ---------------------------------------------------------------------------

class TestComputeAverages:
    """Test averaging logic for historical archive data."""

    def _make_data(self, rows):
        """Build a minimal archive-API-shaped dict from (date, hi, lo, precip) tuples."""
        return {
            "daily": {
                "time": [r[0] for r in rows],
                "temperature_2m_max": [r[1] for r in rows],
                "temperature_2m_min": [r[2] for r in rows],
                "precipitation_sum": [r[3] for r in rows],
            }
        }

    def test_single_matching_day(self):
        data = self._make_data([
            ("2023-03-27", 60.0, 40.0, 0.1),
            ("2023-03-28", 65.0, 42.0, 0.0),
        ])
        result = _compute_averages(data, 3, 27)
        assert result is not None
        assert result.avg_high == 60.0
        assert result.avg_low == 40.0
        assert result.avg_precip == 0.1
        assert result.years == 1

    def test_multiple_years_averaged(self):
        data = self._make_data([
            ("2020-07-04", 80.0, 60.0, 0.0),
            ("2021-07-04", 90.0, 70.0, 0.5),
            ("2022-07-04", 85.0, 65.0, 0.2),
            ("2021-07-05", 75.0, 55.0, 0.0),  # different date, should be ignored
        ])
        result = _compute_averages(data, 7, 4)
        assert result is not None
        assert result.years == 3
        assert result.avg_high == round((80 + 90 + 85) / 3, 1)
        assert result.avg_low == round((60 + 70 + 65) / 3, 1)
        assert result.avg_precip == round((0.0 + 0.5 + 0.2) / 3, 2)

    def test_no_matching_day(self):
        data = self._make_data([
            ("2023-01-15", 30.0, 20.0, 0.0),
        ])
        result = _compute_averages(data, 6, 15)
        assert result is None

    def test_empty_data(self):
        assert _compute_averages({}, 3, 27) is None
        assert _compute_averages({"daily": {}}, 3, 27) is None
        assert _compute_averages({"daily": {"time": []}}, 3, 27) is None

    def test_handles_none_values(self):
        """Rows with None temps should be skipped."""
        data = {
            "daily": {
                "time": ["2020-03-27", "2021-03-27"],
                "temperature_2m_max": [None, 60.0],
                "temperature_2m_min": [None, 40.0],
                "precipitation_sum": [None, 0.1],
            }
        }
        result = _compute_averages(data, 3, 27)
        assert result is not None
        assert result.years == 1
        assert result.avg_high == 60.0

    def test_feb_29_leap_day(self):
        """Leap day (Feb 29) should match only years that have it."""
        data = self._make_data([
            ("2020-02-29", 50.0, 30.0, 0.0),
            ("2024-02-29", 55.0, 35.0, 0.1),
        ])
        result = _compute_averages(data, 2, 29)
        assert result is not None
        assert result.years == 2
        assert result.avg_high == 52.5


# ---------------------------------------------------------------------------
# format_historical_comparison
# ---------------------------------------------------------------------------

class TestFormatComparison:
    """Test the short annotation formatting."""

    def _runtime(self, celsius=False, lang="en"):
        return WeatherRuntime(live=False, emoji=False, lang=lang,
                              celsius=celsius, metric=celsius, shading=True)

    def test_above_average_fahrenheit(self):
        hist = HistoricalAverages(avg_high=60.0, avg_low=40.0, avg_precip=0.1, years=10)
        text = format_historical_comparison(65.0, 42.0, hist, self._runtime())
        assert "above" in text.lower()
        assert "5" in text

    def test_below_average_fahrenheit(self):
        hist = HistoricalAverages(avg_high=60.0, avg_low=40.0, avg_precip=0.1, years=10)
        text = format_historical_comparison(55.0, 38.0, hist, self._runtime())
        assert "below" in text.lower()
        assert "5" in text

    def test_near_average_fahrenheit(self):
        hist = HistoricalAverages(avg_high=60.0, avg_low=40.0, avg_precip=0.1, years=10)
        text = format_historical_comparison(61.0, 41.0, hist, self._runtime())
        assert "avg" in text.lower()
        # Should say "near avg" not "above" or "below"
        assert "above" not in text.lower()
        assert "below" not in text.lower()

    def test_above_average_celsius(self):
        hist = HistoricalAverages(avg_high=15.0, avg_low=5.0, avg_precip=2.0, years=10)
        text = format_historical_comparison(18.0, 7.0, hist, self._runtime(celsius=True))
        assert "3" in text

    def test_near_average_celsius(self):
        hist = HistoricalAverages(avg_high=15.0, avg_low=5.0, avg_precip=2.0, years=10)
        text = format_historical_comparison(15.5, 5.5, hist, self._runtime(celsius=True))
        # 0.5 difference is within 1.5 threshold for Celsius
        assert "above" not in text.lower()
        assert "below" not in text.lower()

    def test_french_locale(self):
        hist = HistoricalAverages(avg_high=60.0, avg_low=40.0, avg_precip=0.1, years=10)
        text = format_historical_comparison(70.0, 50.0, hist, self._runtime(lang="fr"))
        assert "moy" in text.lower()

    def test_japanese_locale(self):
        hist = HistoricalAverages(avg_high=60.0, avg_low=40.0, avg_precip=0.1, years=10)
        text = format_historical_comparison(70.0, 50.0, hist, self._runtime(lang="ja"))
        assert len(text) > 0


# ---------------------------------------------------------------------------
# fetch_historical (mocked HTTP)
# ---------------------------------------------------------------------------

class TestFetchHistorical:
    """Test fetch_historical with mocked HTTP."""

    def test_returns_averages_on_success(self):
        mock_data = {
            "daily": {
                "time": [f"{y}-03-27" for y in range(2016, 2026)],
                "temperature_2m_max": [60 + i for i in range(10)],
                "temperature_2m_min": [40 + i for i in range(10)],
                "precipitation_sum": [0.1 * i for i in range(10)],
            }
        }
        with patch("linecast._weather_historical.fetch_json_cached", return_value=mock_data):
            result = fetch_historical(40.7, -74.0, date(2026, 3, 27))
        assert result is not None
        assert result.years == 10
        assert result.avg_high == round(sum(60 + i for i in range(10)) / 10, 1)

    def test_returns_none_on_failure(self):
        with patch("linecast._weather_historical.fetch_json_cached", return_value=None):
            result = fetch_historical(40.7, -74.0, date(2026, 3, 27))
        assert result is None

    def test_returns_none_on_empty_data(self):
        with patch("linecast._weather_historical.fetch_json_cached", return_value={"daily": {"time": []}}):
            result = fetch_historical(40.7, -74.0, date(2026, 3, 27))
        assert result is None

    def test_celsius_flag_passed_to_url(self):
        """Verify that celsius=True uses celsius in the API URL."""
        with patch("linecast._weather_historical.fetch_json_cached", return_value=None) as mock:
            fetch_historical(40.7, -74.0, date(2026, 3, 27), celsius=True)
        url = mock.call_args[0][2]  # positional arg: url
        assert "temperature_unit=celsius" in url

    def test_fahrenheit_default(self):
        """Verify that celsius=False uses fahrenheit in the API URL."""
        with patch("linecast._weather_historical.fetch_json_cached", return_value=None) as mock:
            fetch_historical(40.7, -74.0, date(2026, 3, 27), celsius=False)
        url = mock.call_args[0][2]
        assert "temperature_unit=fahrenheit" in url

    def test_cache_file_includes_date(self):
        """Cache file should be date-specific."""
        with patch("linecast._weather_historical.fetch_json_cached", return_value=None) as mock:
            fetch_historical(40.7, -74.0, date(2026, 3, 27))
        cache_file = mock.call_args[0][0]
        assert "0327" in str(cache_file)

    def test_cache_max_age_is_long(self):
        """Historical data doesn't change — cache should be at least 24h."""
        with patch("linecast._weather_historical.fetch_json_cached", return_value=None) as mock:
            fetch_historical(40.7, -74.0, date(2026, 3, 27))
        max_age = mock.call_args[0][1]
        assert max_age >= 86400


# ---------------------------------------------------------------------------
# Integration smoke test: render_header with historical data
# ---------------------------------------------------------------------------

class TestHeaderIntegration:
    """Verify render_header doesn't crash when given historical data."""

    def test_render_header_with_historical(self):
        from linecast._weather_sections import render_header
        data = {
            "current": {
                "temperature_2m": 65.0,
                "apparent_temperature": 63.0,
                "weather_code": 1,
                "wind_speed_10m": 8.0,
                "wind_gusts_10m": 12.0,
                "relative_humidity_2m": 55,
                "dew_point_2m": 48.0,
            },
            "daily": {
                "time": ["2026-03-26", "2026-03-27", "2026-03-28"],
                "temperature_2m_max": [60.0, 65.0, 68.0],
                "temperature_2m_min": [42.0, 45.0, 48.0],
            },
        }
        hist = HistoricalAverages(avg_high=60.0, avg_low=40.0, avg_precip=0.1, years=10)
        runtime = WeatherRuntime(live=False, emoji=False, lang="en",
                                 celsius=False, metric=False, shading=True)
        result = render_header(data, 120, "Test City", runtime=runtime, historical=hist)
        assert isinstance(result, str)
        assert len(result) > 0
        # The annotation should appear somewhere in the header
        assert "avg" in result.lower()

    def test_render_header_without_historical(self):
        """Header works fine with historical=None."""
        from linecast._weather_sections import render_header
        data = {
            "current": {
                "temperature_2m": 65.0,
                "apparent_temperature": 63.0,
                "weather_code": 1,
                "wind_speed_10m": 8.0,
                "wind_gusts_10m": 12.0,
                "relative_humidity_2m": 55,
                "dew_point_2m": 48.0,
            },
            "daily": {
                "time": ["2026-03-26", "2026-03-27"],
                "temperature_2m_max": [60.0, 65.0],
                "temperature_2m_min": [42.0, 45.0],
            },
        }
        runtime = WeatherRuntime(live=False, emoji=False, lang="en",
                                 celsius=False, metric=False, shading=True)
        result = render_header(data, 120, "Test City", runtime=runtime, historical=None)
        assert isinstance(result, str)
        assert "avg" not in result.lower()
