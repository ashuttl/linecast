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

    def test_returns_first_station_from_list_response(self):
        # Live shape: a bare array sorted by distance, with label and
        # distanceKm (confirmed against the real API, 2026-08).
        api_response = [
            {"id": "fes2022-lisbon", "slug": "lisbon", "name": "Lisbon",
             "region": "Lisbon", "country": "Portugal", "lat": 38.71,
             "lng": -9.14, "label": "Lisbon, Lisbon, Portugal",
             "distanceKm": 1},
            {"id": "fes2022-almada", "name": "Almada", "distanceKm": 6},
        ]
        with patch.dict("os.environ", {"LINECAST_TIDECHECK_KEY": "k"}), \
             patch.object(tc, "read_cache", return_value=None), \
             patch.object(tc, "fetch_json", return_value=api_response), \
             patch.object(tc, "write_cache") as mock_write:
            sid, name = tc.find_nearest_station_tidecheck(38.72, -9.14)

        self.assertEqual(sid, "fes2022-lisbon")
        self.assertEqual(name, "Lisbon, Lisbon, Portugal")
        mock_write.assert_called_once()

    def test_far_station_rejected_like_noaa_cutoff(self):
        api_response = [{"id": "somewhere", "name": "Somewhere",
                         "distanceKm": 400}]
        with patch.dict("os.environ", {"LINECAST_TIDECHECK_KEY": "k"}), \
             patch.object(tc, "read_cache", return_value=None), \
             patch.object(tc, "fetch_json", return_value=api_response), \
             patch.object(tc, "write_cache"):
            sid, name = tc.find_nearest_station_tidecheck(46.8, 8.2)

        self.assertIsNone(sid)
        self.assertIsNone(name)

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
        # Live shape: station carries lat/lng/timezone/country in the
        # tides response (richer than the docs promise).
        api_response = {
            "station": {
                "id": "cascais-209a-prt-uhslc_rq",
                "name": "Cascais",
                "region": "Lisbon",
                "country": "Portugal",
                "lat": 38.692,
                "lng": -9.417,
                "type": "reference",
                "timezone": "Europe/Lisbon",
            },
            "datum": "MLLW",
            "extremes": [],
        }
        with patch.dict("os.environ", {"LINECAST_TIDECHECK_KEY": "k"}), \
             patch.object(tc, "read_cache", return_value=None), \
             patch.object(tc, "_fetch_tides_raw", return_value=api_response), \
             patch.object(tc, "write_cache") as mock_write:
            meta = tc.fetch_station_metadata_tidecheck("cascais-209a-prt-uhslc_rq")

        self.assertEqual(meta["id"], "cascais-209a-prt-uhslc_rq")
        self.assertEqual(meta["name"], "Cascais")
        self.assertEqual(meta["state"], "Portugal")
        self.assertEqual(meta["lat"], 38.692)
        self.assertEqual(meta["source"], "tidecheck")
        self.assertEqual(meta["timeZoneCode"], "Europe/Lisbon")
        mock_write.assert_called_once()


class HiloRangeTests(unittest.TestCase):
    """Tests for fetch_hilo_range_tidecheck."""

    def test_returns_empty_when_key_not_set(self):
        with patch.dict("os.environ", {}, clear=True):
            result = tc.fetch_hilo_range_tidecheck("id", date(2026, 3, 1), date(2026, 3, 2), None)
            self.assertEqual(result, [])

    def test_parses_extremes_and_converts_meters_to_feet(self):
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
        # TideCheck heights are meters; the pipeline works in feet
        self.assertAlmostEqual(h0, 1.8 / 0.3048, places=2)
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

    def test_synthesizes_curve_from_extremes(self):
        """The API publishes extremes only; a cosine curve is built from them."""
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
        # First point matches the first extreme, converted meters -> feet
        self.assertAlmostEqual(result[0][1], 1.0 / 0.3048, places=2)
        # Monotonic descent from the opening high to the low
        first_hour = [h for _, h in result[:10]]
        self.assertEqual(first_hour, sorted(first_hour, reverse=True))


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
        self.assertAlmostEqual(result[0], -0.1 / 0.3048, places=2)
        self.assertAlmostEqual(result[1], 2.1 / 0.3048, places=2)

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

    def test_default_assumes_meters(self):
        # The live API reports meters and carries no unit field
        response = {}
        result = tc._maybe_convert_height(1.0, response)
        self.assertAlmostEqual(result, 1.0 / 0.3048, places=2)


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


if __name__ == "__main__":
    unittest.main()
