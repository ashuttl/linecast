"""Tests for the TideCheck tide data source module."""

import json
import unittest
from datetime import date, datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

from linecast import _tides_tidecheck as tc
from linecast._cache import location_cache_key


class AvailabilityTests(unittest.TestCase):
    """Tests for the is_available() / _api_key() gating logic."""

    def test_not_available_when_env_unset(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertFalse(tc.is_available())
            self.assertIsNone(tc._api_key())

    def test_not_available_when_env_empty(self):
        with patch.dict("os.environ", {"LINECAST_TIDECHECK_KEY": ""}):
            self.assertFalse(tc.is_available())

    def test_not_available_when_env_whitespace(self):
        with patch.dict("os.environ", {"LINECAST_TIDECHECK_KEY": "   "}):
            self.assertFalse(tc.is_available())

    def test_available_when_key_set(self):
        with patch.dict("os.environ", {"LINECAST_TIDECHECK_KEY": "test-key-123"}):
            self.assertTrue(tc.is_available())
            self.assertEqual(tc._api_key(), "test-key-123")

    def test_headers_include_api_key(self):
        with patch.dict("os.environ", {"LINECAST_TIDECHECK_KEY": "my-key"}):
            h = tc._headers()
            self.assertEqual(h["X-API-Key"], "my-key")
            self.assertIn("User-Agent", h)

    def test_headers_empty_without_key(self):
        with patch.dict("os.environ", {}, clear=True):
            h = tc._headers()
            self.assertNotIn("X-API-Key", h)


class NearestStationTests(unittest.TestCase):
    """Tests for find_nearest_station_tidecheck."""

    def test_returns_none_when_key_not_set(self):
        with patch.dict("os.environ", {}, clear=True):
            sid, name = tc.find_nearest_station_tidecheck(51.5, -0.1)
            self.assertIsNone(sid)
            self.assertIsNone(name)

    def test_returns_station_from_api(self):
        api_response = {
            "station": {
                "id": "london-tower-bridge",
                "name": "London Tower Bridge",
                "latitude": 51.5055,
                "longitude": -0.0754,
            }
        }
        with patch.dict("os.environ", {"LINECAST_TIDECHECK_KEY": "k"}), \
             patch.object(tc, "read_cache", return_value=None), \
             patch.object(tc, "fetch_json", return_value=api_response), \
             patch.object(tc, "write_cache") as mock_write:
            sid, name = tc.find_nearest_station_tidecheck(51.5, -0.1)

        self.assertEqual(sid, "london-tower-bridge")
        self.assertEqual(name, "London Tower Bridge")
        mock_write.assert_called_once()

    def test_returns_cached_station(self):
        cached = {"id": "cached-id", "name": "Cached Station"}
        with patch.dict("os.environ", {"LINECAST_TIDECHECK_KEY": "k"}), \
             patch.object(tc, "read_cache", return_value=cached):
            sid, name = tc.find_nearest_station_tidecheck(51.5, -0.1)

        self.assertEqual(sid, "cached-id")
        self.assertEqual(name, "Cached Station")

    def test_uses_stale_cache_on_fetch_error(self):
        stale = {"id": "stale-id", "name": "Stale Station"}
        with patch.dict("os.environ", {"LINECAST_TIDECHECK_KEY": "k"}), \
             patch.object(tc, "read_cache", return_value=None), \
             patch.object(tc, "fetch_json", side_effect=RuntimeError("network down")), \
             patch.object(tc, "read_stale", return_value=stale):
            sid, name = tc.find_nearest_station_tidecheck(51.5, -0.1)

        self.assertEqual(sid, "stale-id")
        self.assertEqual(name, "Stale Station")

    def test_returns_none_on_empty_response(self):
        with patch.dict("os.environ", {"LINECAST_TIDECHECK_KEY": "k"}), \
             patch.object(tc, "read_cache", return_value=None), \
             patch.object(tc, "fetch_json", return_value={}), \
             patch.object(tc, "read_stale", return_value=None):
            sid, name = tc.find_nearest_station_tidecheck(51.5, -0.1)

        self.assertIsNone(sid)
        self.assertIsNone(name)

    def test_handles_flat_station_response(self):
        """Some APIs return the station object directly, not wrapped."""
        api_response = {
            "id": "flat-id",
            "name": "Flat Station",
        }
        with patch.dict("os.environ", {"LINECAST_TIDECHECK_KEY": "k"}), \
             patch.object(tc, "read_cache", return_value=None), \
             patch.object(tc, "fetch_json", return_value=api_response), \
             patch.object(tc, "write_cache"):
            sid, name = tc.find_nearest_station_tidecheck(51.5, -0.1)

        self.assertEqual(sid, "flat-id")
        self.assertEqual(name, "Flat Station")


class SearchStationsTests(unittest.TestCase):
    """Tests for search_stations_tidecheck."""

    def test_returns_empty_when_key_not_set(self):
        with patch.dict("os.environ", {}, clear=True):
            results = tc.search_stations_tidecheck("london")
            self.assertEqual(results, [])

    def test_returns_normalized_results(self):
        api_response = {
            "stations": [
                {"id": "s1", "name": "Station One"},
                {"id": "s2", "name": "Station Two"},
            ]
        }
        with patch.dict("os.environ", {"LINECAST_TIDECHECK_KEY": "k"}), \
             patch.object(tc, "fetch_json_cached", return_value=api_response):
            results = tc.search_stations_tidecheck("station")

        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["id"], "s1")
        self.assertEqual(results[1]["name"], "Station Two")

    def test_handles_list_response(self):
        """API may return a bare list instead of wrapping in 'stations'."""
        api_response = [
            {"id": "s1", "name": "Station One"},
        ]
        with patch.dict("os.environ", {"LINECAST_TIDECHECK_KEY": "k"}), \
             patch.object(tc, "fetch_json_cached", return_value=api_response):
            results = tc.search_stations_tidecheck("station")

        self.assertEqual(len(results), 1)


class MetadataTests(unittest.TestCase):
    """Tests for fetch_station_metadata_tidecheck."""

    def test_returns_none_when_key_not_set(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertIsNone(tc.fetch_station_metadata_tidecheck("any-id"))

    def test_returns_cached_metadata(self):
        cached = {"id": "x", "name": "Cached", "source": "tidecheck"}
        with patch.dict("os.environ", {"LINECAST_TIDECHECK_KEY": "k"}), \
             patch.object(tc, "read_cache", return_value=cached):
            meta = tc.fetch_station_metadata_tidecheck("x")

        self.assertEqual(meta["source"], "tidecheck")

    def test_normalizes_api_response(self):
        api_response = {
            "station": {
                "id": "tokyo-bay",
                "name": "Tokyo Bay",
                "latitude": 35.65,
                "longitude": 139.77,
                "timezone": "Asia/Tokyo",
            },
            "extremes": [],
        }
        with patch.dict("os.environ", {"LINECAST_TIDECHECK_KEY": "k"}), \
             patch.object(tc, "read_cache", return_value=None), \
             patch.object(tc, "fetch_json_cached", return_value=api_response), \
             patch.object(tc, "write_cache") as mock_write:
            meta = tc.fetch_station_metadata_tidecheck("tokyo-bay")

        self.assertEqual(meta["id"], "tokyo-bay")
        self.assertEqual(meta["name"], "Tokyo Bay")
        self.assertEqual(meta["source"], "tidecheck")
        self.assertEqual(meta["timeZoneCode"], "Asia/Tokyo")
        self.assertEqual(meta["timezone_abbr"], "JST")
        mock_write.assert_called_once()


class HiloRangeTests(unittest.TestCase):
    """Tests for fetch_hilo_range_tidecheck."""

    def test_returns_empty_when_key_not_set(self):
        with patch.dict("os.environ", {}, clear=True):
            result = tc.fetch_hilo_range_tidecheck("id", date(2026, 3, 1), date(2026, 3, 2), None)
            self.assertEqual(result, [])

    def test_parses_extremes_correctly(self):
        raw_data = {
            "extremes": [
                {"time": "2026-03-27T06:30:00Z", "height": 1.8, "type": "high"},
                {"time": "2026-03-27T12:45:00Z", "height": 0.3, "type": "low"},
                {"time": "2026-03-27T18:50:00Z", "height": 1.6, "type": "high"},
            ],
        }
        with patch.dict("os.environ", {"LINECAST_TIDECHECK_KEY": "k"}), \
             patch.object(tc, "read_cache", return_value=None), \
             patch.object(tc, "_fetch_tides_raw", return_value=raw_data), \
             patch.object(tc, "write_cache"):
            result = tc.fetch_hilo_range_tidecheck(
                "test-id", date(2026, 3, 27), date(2026, 3, 27), timezone.utc)

        self.assertEqual(len(result), 3)
        dt0, h0, t0 = result[0]
        self.assertEqual(t0, "H")
        self.assertAlmostEqual(h0, 1.8, places=1)
        self.assertEqual(result[1][2], "L")
        self.assertEqual(result[2][2], "H")

    def test_returns_cached_hilo(self):
        cached = [
            {"dt": "2026-03-27T06:30:00+00:00", "v": 1.8, "t": "H"},
            {"dt": "2026-03-27T12:45:00+00:00", "v": 0.3, "t": "L"},
        ]
        with patch.dict("os.environ", {"LINECAST_TIDECHECK_KEY": "k"}), \
             patch.object(tc, "read_cache", return_value=cached):
            result = tc.fetch_hilo_range_tidecheck(
                "test-id", date(2026, 3, 27), date(2026, 3, 27), timezone.utc)

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0][2], "H")


class TidesRangeTests(unittest.TestCase):
    """Tests for fetch_tides_range_tidecheck."""

    def test_returns_empty_when_key_not_set(self):
        with patch.dict("os.environ", {}, clear=True):
            result = tc.fetch_tides_range_tidecheck("id", date(2026, 3, 1), date(2026, 3, 2), None)
            self.assertEqual(result, [])

    def test_synthesizes_from_extremes_when_no_time_series(self):
        """When the API returns only extremes, a cosine-interpolated curve is built."""
        raw_data = {
            "extremes": [
                {"time": "2026-03-27T00:00:00Z", "height": 1.0, "type": "high"},
                {"time": "2026-03-27T06:00:00Z", "height": 0.2, "type": "low"},
                {"time": "2026-03-27T12:00:00Z", "height": 1.5, "type": "high"},
            ],
        }
        with patch.dict("os.environ", {"LINECAST_TIDECHECK_KEY": "k"}), \
             patch.object(tc, "read_cache", return_value=None), \
             patch.object(tc, "_fetch_tides_raw", return_value=raw_data), \
             patch.object(tc, "write_cache"):
            result = tc.fetch_tides_range_tidecheck(
                "test-id", date(2026, 3, 27), date(2026, 3, 27), timezone.utc)

        self.assertTrue(len(result) > 10)  # many interpolated points
        # First point should match the first extreme
        self.assertAlmostEqual(result[0][1], 1.0, places=1)

    def test_returns_cached_predictions(self):
        cached = [
            {"dt": "2026-03-27T00:00:00+00:00", "v": 1.0},
            {"dt": "2026-03-27T00:06:00+00:00", "v": 0.98},
        ]
        with patch.dict("os.environ", {"LINECAST_TIDECHECK_KEY": "k"}), \
             patch.object(tc, "read_cache", return_value=cached):
            result = tc.fetch_tides_range_tidecheck(
                "test-id", date(2026, 3, 27), date(2026, 3, 27), timezone.utc)

        self.assertEqual(len(result), 2)
        self.assertAlmostEqual(result[0][1], 1.0, places=1)


class YRangeTests(unittest.TestCase):
    """Tests for fetch_y_range_tidecheck."""

    def test_returns_none_when_key_not_set(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertIsNone(tc.fetch_y_range_tidecheck("id", date(2026, 3, 27), None))

    def test_computes_range_from_extremes(self):
        raw_data = {
            "extremes": [
                {"height": 1.8, "type": "high", "time": "2026-03-27T06:00:00Z"},
                {"height": 0.2, "type": "low", "time": "2026-03-27T12:00:00Z"},
                {"height": 2.1, "type": "high", "time": "2026-03-28T06:00:00Z"},
                {"height": -0.1, "type": "low", "time": "2026-03-28T12:00:00Z"},
            ],
        }
        with patch.dict("os.environ", {"LINECAST_TIDECHECK_KEY": "k"}), \
             patch.object(tc, "read_cache", return_value=None), \
             patch.object(tc, "_fetch_tides_raw", return_value=raw_data), \
             patch.object(tc, "write_cache"):
            result = tc.fetch_y_range_tidecheck("test-id", date(2026, 3, 27), None)

        self.assertIsNotNone(result)
        self.assertAlmostEqual(result[0], -0.1, places=1)
        self.assertAlmostEqual(result[1], 2.1, places=1)

    def test_returns_cached_y_range(self):
        cached = {"min": -0.5, "max": 3.0}
        with patch.dict("os.environ", {"LINECAST_TIDECHECK_KEY": "k"}), \
             patch.object(tc, "read_cache", return_value=cached):
            result = tc.fetch_y_range_tidecheck("test-id", date(2026, 3, 27), None)

        self.assertEqual(result, (-0.5, 3.0))


class HeightConversionTests(unittest.TestCase):
    """Tests for _maybe_convert_height."""

    def test_metres_converted_to_feet(self):
        response = {"unit": "meters"}
        result = tc._maybe_convert_height(1.0, response)
        self.assertAlmostEqual(result, 1.0 / 0.3048, places=2)

    def test_feet_unchanged(self):
        response = {"unit": "feet"}
        result = tc._maybe_convert_height(5.0, response)
        self.assertEqual(result, 5.0)

    def test_default_assumes_feet(self):
        response = {}
        result = tc._maybe_convert_height(5.0, response)
        self.assertEqual(result, 5.0)


class IsoParsingTests(unittest.TestCase):
    """Tests for _parse_iso_utc."""

    def test_parses_standard_utc(self):
        dt = tc._parse_iso_utc("2026-03-27T14:30:00Z")
        self.assertEqual(dt.year, 2026)
        self.assertEqual(dt.month, 3)
        self.assertEqual(dt.hour, 14)
        self.assertEqual(dt.tzinfo, timezone.utc)

    def test_parses_with_fractional_seconds(self):
        dt = tc._parse_iso_utc("2026-03-27T14:30:00.123Z")
        self.assertEqual(dt.minute, 30)
        self.assertEqual(dt.tzinfo, timezone.utc)

    def test_parses_without_z(self):
        dt = tc._parse_iso_utc("2026-03-27T14:30:00")
        self.assertEqual(dt.tzinfo, timezone.utc)


class SynthesizeFromExtremesTests(unittest.TestCase):
    """Tests for _synthesize_from_extremes fallback."""

    def test_returns_empty_for_no_extremes(self):
        with patch.object(tc, "write_cache"):
            result = tc._synthesize_from_extremes(
                {}, date(2026, 3, 27), date(2026, 3, 27), timezone.utc)
        self.assertEqual(result, [])

    def test_cosine_interpolation_is_smooth(self):
        """The interpolated curve should smoothly transition between extremes."""
        data = {
            "extremes": [
                {"time": "2026-03-27T00:00:00Z", "height": 2.0, "type": "high"},
                {"time": "2026-03-27T06:00:00Z", "height": 0.0, "type": "low"},
            ],
        }
        with patch.object(tc, "write_cache"):
            result = tc._synthesize_from_extremes(
                data, date(2026, 3, 27), date(2026, 3, 27), timezone.utc)

        self.assertTrue(len(result) > 5)
        # First point should be near the high
        self.assertAlmostEqual(result[0][1], 2.0, places=1)
        # Last point should be near the low
        self.assertAlmostEqual(result[-1][1], 0.0, places=1)
        # Midpoint should be roughly halfway (cosine crosses 0.5 at pi/2)
        mid_idx = len(result) // 2
        self.assertTrue(0.5 < result[mid_idx][1] < 1.5)


if __name__ == "__main__":
    unittest.main()
