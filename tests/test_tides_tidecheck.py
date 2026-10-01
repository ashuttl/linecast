"""Tests for the TideCheck tide data source module."""

import json
import os
import tempfile
import time
import unittest
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch
from zoneinfo import ZoneInfo

from linecast._cache import location_cache_key
from linecast.tides import common
from linecast.tides import tidecheck as tc


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

    def test_a_key_saved_in_config_is_used(self):
        from linecast import _config
        _config.write_config({"units": "metric", "tidecheck_key": " saved-key "})
        self.assertTrue(tc.is_available())
        self.assertEqual(tc._headers(), {"X-API-Key": "saved-key"})
        # an empty variable is no key at all, so the saved one stands
        with patch.dict("os.environ", {"LINECAST_TIDECHECK_KEY": ""}):
            self.assertEqual(tc._api_key(), "saved-key")

    def test_the_environment_beats_the_saved_key(self):
        from linecast import _config
        _config.write_config({"tidecheck_key": "saved-key"})
        with patch.dict("os.environ", {"LINECAST_TIDECHECK_KEY": "env-key"}):
            self.assertEqual(tc._api_key(), "env-key")

    def test_a_saved_key_that_is_not_text_is_no_key(self):
        from linecast import _config
        for junk in ("", "   ", 12345, None, ["k"]):
            _config.write_config({"tidecheck_key": junk})
            self.assertFalse(tc.is_available(), junk)

    def test_headers_include_api_key(self):
        with patch.dict("os.environ", {"LINECAST_TIDECHECK_KEY": "my-key"}):
            h = tc._headers()
            # the User-Agent is attached by _http.fetch_bytes, not here
            self.assertEqual(h, {"X-API-Key": "my-key"})

    def test_headers_empty_without_key(self):
        with patch.dict("os.environ", {}, clear=True):
            h = tc._headers()
            self.assertNotIn("X-API-Key", h)


class NearestStationTests(unittest.TestCase):
    """Tests for find_nearest_station_tidecheck, in a cache of their own."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        env = patch.dict("os.environ", {"LINECAST_CACHE_DIR": tmp.name,
                                        "LINECAST_TIDECHECK_KEY": "k"})
        env.start()
        self.addCleanup(env.stop)

    def _pick_file(self, lat, lng):
        return common.cache_dir() / f"tc_station_{location_cache_key(lat, lng)}.json"

    def _cached(self, lat, lng, pick, age=0):
        path = self._pick_file(lat, lng)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(pick))
        then = time.time() - age
        os.utime(path, (then, then))

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
        with patch.object(tc, "fetch_json", return_value=api_response):
            sid, name = tc.find_nearest_station_tidecheck(38.72, -9.14)

        self.assertEqual(sid, "fes2022-lisbon")
        self.assertEqual(name, "Lisbon, Lisbon, Portugal")
        # the pick is kept for the place, and the request counted
        self.assertEqual(json.loads(self._pick_file(38.72, -9.14).read_text()),
                         {"id": "fes2022-lisbon", "name": "Lisbon, Lisbon, Portugal",
                          "lat": 38.72, "lng": -9.14})
        self.assertEqual(tc.requests_today(), 1)

    def test_far_station_rejected_like_noaa_cutoff(self):
        api_response = [{"id": "somewhere", "name": "Somewhere",
                         "distanceKm": 400}]
        with patch.object(tc, "fetch_json", return_value=api_response):
            sid, name = tc.find_nearest_station_tidecheck(46.8, 8.2)

        self.assertIsNone(sid)
        self.assertIsNone(name)
        self.assertFalse(self._pick_file(46.8, 8.2).exists())

    def test_returns_cached_station(self):
        self._cached(51.5, -0.1, {"id": "cached-id", "name": "Cached Station"})
        with patch.object(tc, "fetch_json") as fetch:
            sid, name = tc.find_nearest_station_tidecheck(51.5, -0.1)

        fetch.assert_not_called()
        self.assertEqual(sid, "cached-id")
        self.assertEqual(name, "Cached Station")

    def test_uses_stale_cache_on_fetch_error(self):
        self._cached(51.5, -0.1, {"id": "stale-id", "name": "Stale Station"}, age=86400)
        with patch.object(tc, "fetch_json", side_effect=RuntimeError("network down")):
            sid, name = tc.find_nearest_station_tidecheck(51.5, -0.1)

        self.assertEqual(sid, "stale-id")
        self.assertEqual(name, "Stale Station")

    def test_returns_none_on_empty_response(self):
        with patch.object(tc, "fetch_json", return_value={}):
            sid, name = tc.find_nearest_station_tidecheck(51.5, -0.1)

        self.assertIsNone(sid)
        self.assertIsNone(name)

    def test_handles_flat_station_response(self):
        """Some APIs return the station object directly, not wrapped."""
        api_response = {
            "id": "flat-id",
            "name": "Flat Station",
        }
        with patch.object(tc, "fetch_json", return_value=api_response):
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

    def test_fetched_extremes_are_placed_as_cached_ones_are(self):
        # Lisbon's clocks go back at 2am on 25 October: 27 hours pass
        # between these two, which the wall clock counts as 26
        from datetime import datetime
        from zoneinfo import ZoneInfo
        lisbon = ZoneInfo("Europe/Lisbon")
        raw_data = {"extremes": [
            {"time": "2026-10-24T11:00:00Z", "height": 1.8, "type": "high"},
            {"time": "2026-10-25T14:00:00Z", "height": 0.3, "type": "low"},
        ]}
        with patch.dict("os.environ", {"LINECAST_TIDECHECK_KEY": "k"}), \
             patch.object(tc, "read_cache", return_value=None), \
             patch.object(tc, "_fetch_tides_raw", return_value=raw_data), \
             patch.object(tc, "write_cache") as write_cache:
            fetched = tc.fetch_hilo_range_tidecheck(
                "fes2022-lisbon", date(2026, 10, 24), date(2026, 10, 25), lisbon)
        rows = write_cache.call_args.args[1]
        with patch.dict("os.environ", {"LINECAST_TIDECHECK_KEY": "k"}), \
             patch.object(tc, "read_cache", return_value=rows):
            cached = tc.fetch_hilo_range_tidecheck(
                "fes2022-lisbon", date(2026, 10, 24), date(2026, 10, 25), lisbon)
        start = datetime(2026, 10, 24, 12, 0, tzinfo=lisbon)
        for points in (fetched, cached):
            self.assertEqual([(p[0] - start).total_seconds() / 3600 for p in points], [0, 27])


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
             patch.object(common, "read_cache", return_value=None), \
             patch.object(tc, "_fetch_tides_raw", return_value=raw_data), \
             patch.object(common, "write_cache"):
            result = tc.fetch_y_range_tidecheck("test-id", date(2026, 3, 27), None)

        self.assertIsNotNone(result)
        self.assertAlmostEqual(result[0], -0.1 / 0.3048, places=2)
        self.assertAlmostEqual(result[1], 2.1 / 0.3048, places=2)

    def test_returns_cached_y_range(self):
        cached = {"min": -0.5, "max": 3.0}
        with patch.dict("os.environ", {"LINECAST_TIDECHECK_KEY": "k"}), \
             patch.object(common, "read_cache", return_value=cached):
            result = tc.fetch_y_range_tidecheck("test-id", date(2026, 3, 27), None)

        self.assertEqual(result, (-0.5, 3.0))

    def test_cache_key_is_month_anchored(self):
        seen = []

        def fake_read_cache(path, max_age):
            seen.append(path.name)
            return {"min": 0.0, "max": 1.0}

        with patch.dict("os.environ", {"LINECAST_TIDECHECK_KEY": "k"}), \
             patch.object(common, "read_cache", side_effect=fake_read_cache):
            tc.fetch_y_range_tidecheck("test-id", date(2026, 3, 27), None)
            tc.fetch_y_range_tidecheck("test-id", date(2026, 3, 28), None)

        self.assertEqual(seen, ["tc_yrange_test-id_202603.json"] * 2)


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


if __name__ == "__main__":
    unittest.main()


class BudgetTests(unittest.TestCase):
    """The per-day request tally and the line that reports it."""

    def setUp(self):
        self.env = patch.dict("os.environ", {"LINECAST_TIDECHECK_KEY": "k"})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.tally = {}

        def read_stale(path):
            return self.tally.get(path.name)

        def write_cache(path, data):
            self.tally[path.name] = data

        for name, fn in (("read_stale", read_stale), ("write_cache", write_cache)):
            p = patch.object(tc, name, side_effect=fn)
            p.start()
            self.addCleanup(p.stop)

    def test_each_network_request_counts(self):
        self.assertEqual(tc.requests_today(), 0)
        with patch.object(tc, "fetch_json", return_value=[]):
            tc._fetch("https://example.invalid/x")
            tc._fetch("https://example.invalid/y")
        self.assertEqual(tc.requests_today(), 2)

    def test_cache_hits_do_not_count(self):
        with patch("linecast._http.read_cache", return_value={"id": "s", "name": "S"}), \
             patch.object(tc, "fetch_json") as fetch:
            tc.find_nearest_station_tidecheck(38.7, -9.1)
        fetch.assert_not_called()
        self.assertEqual(tc.requests_today(), 0)

    def test_budget_line(self):
        self.assertEqual(
            tc.budget_line(),
            "TideCheck: 0 of 50 free-tier requests used today (UTC)")
        self.tally[tc._tally_file().name] = {"count": 50}
        self.assertIn("all 50 free-tier requests used", tc.budget_line())
        with patch.dict("os.environ", {"LINECAST_TIDECHECK_PAID": "1"}):
            self.assertEqual(tc.budget_line(), "TideCheck: 50 requests sent today (UTC)")
        with patch.dict("os.environ", {"LINECAST_TIDECHECK_KEY": ""}):
            self.assertIsNone(tc.budget_line())

    def test_a_garbled_tally_reads_as_zero(self):
        self.tally[tc._tally_file().name] = "junk"
        self.assertEqual(tc.requests_today(), 0)

    def test_the_fifty_first_request_is_never_sent(self):
        self.tally[tc._tally_file().name] = {"count": 50}
        with patch("linecast._http.read_cache", return_value=None), \
             patch("linecast._http.read_stale", return_value=None), \
             patch.object(tc, "fetch_json") as fetch, \
             patch("linecast._http.log_failure") as logged:
            sid, name = tc.find_nearest_station_tidecheck(38.72, -9.14)

        fetch.assert_not_called()
        self.assertIsNone(sid)
        self.assertIsNone(name)
        # a refused request costs nothing, so the tally does not move
        self.assertEqual(tc.requests_today(), 50)
        # and --debug says why the station is missing
        logged.assert_called_once()
        self.assertEqual(logged.call_args.args[0], "tides/tidecheck")
        self.assertIsInstance(logged.call_args.args[2], tc.BudgetExhausted)
        self.assertEqual(logged.call_args.kwargs["fallback"], "fallback value")

    def test_a_refused_request_serves_the_station_it_has(self):
        self.tally[tc._tally_file().name] = {"count": 50}
        stale = {"id": "fes2022-lisbon", "name": "Lisbon"}
        with patch("linecast._http.read_cache", return_value=None), \
             patch("linecast._http.read_stale", return_value=stale), \
             patch.object(tc, "fetch_json") as fetch:
            sid, name = tc.find_nearest_station_tidecheck(38.72, -9.14)

        fetch.assert_not_called()
        self.assertEqual(sid, "fes2022-lisbon")
        self.assertEqual(name, "Lisbon")

    def test_a_refused_tides_fetch_serves_the_cached_copy(self):
        self.tally[tc._tally_file().name] = {"count": 50}
        payload = {"station": {"id": "fes2022-lisbon"}, "extremes": []}
        with patch.object(tc, "fetch_json") as fetch, \
             patch("linecast._http.read_cache", return_value=None), \
             patch("linecast._http.read_stale", return_value=payload):
            self.assertEqual(tc._fetch_tides_raw("fes2022-lisbon"), payload)
        fetch.assert_not_called()

    def test_the_fiftieth_request_still_goes_out(self):
        self.tally[tc._tally_file().name] = {"count": 49}
        with patch.object(tc, "fetch_json", return_value=[]) as fetch:
            tc._fetch("https://example.invalid/x")
        fetch.assert_called_once()
        self.assertEqual(tc.requests_today(), 50)

        with patch.object(tc, "fetch_json") as fetch:
            with self.assertRaises(tc.BudgetExhausted):
                tc._fetch("https://example.invalid/y")
        fetch.assert_not_called()
        self.assertEqual(tc.requests_today(), 50)

    def test_a_paid_plan_is_not_held_to_the_cap(self):
        self.tally[tc._tally_file().name] = {"count": 50}
        with patch.dict("os.environ", {"LINECAST_TIDECHECK_PAID": "1"}), \
             patch.object(tc, "fetch_json", return_value=[]) as fetch:
            tc._fetch("https://example.invalid/x")
        fetch.assert_called_once()
        self.assertEqual(tc.requests_today(), 51)


def _quarter_hours(start, count, height=lambda i: 1.0):
    """timeSeries rows as the API writes them, fifteen minutes apart from
    *start* (an aware UTC datetime): {"time": "…T00:15:00.000Z", "height": metres}."""
    return [{"time": (start + timedelta(minutes=15 * i)).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
             "height": height(i)} for i in range(count)]


class SeriesCurveTests(unittest.TestCase):
    """The curve is the response's own fifteen-minute series, where it
    has one, and is drawn between the highs and lows where it has not."""

    EXTREMES = [
        {"time": "2026-03-27T00:00:00.000Z", "localTime": "2026-03-27T00:00:00+00:00",
         "localDate": "2026-03-27", "height": 1.0, "type": "high"},
        {"time": "2026-03-27T06:00:00.000Z", "localTime": "2026-03-27T06:00:00+00:00",
         "localDate": "2026-03-27", "height": 0.2, "type": "low"},
        {"time": "2026-03-27T12:00:00.000Z", "localTime": "2026-03-27T12:00:00+00:00",
         "localDate": "2026-03-27", "height": 1.5, "type": "high"},
    ]

    def _curve(self, raw, tz=timezone.utc, start=date(2026, 3, 27), end=date(2026, 3, 27)):
        """The curve for a response, with nothing read from the cache or
        kept in it, and no request made."""
        with patch.dict("os.environ", {"LINECAST_TIDECHECK_KEY": "k"}), \
             patch.object(tc, "read_cache", return_value=None), \
             patch.object(tc, "_fetch_tides_raw", return_value=raw), \
             patch.object(tc, "fetch_json", side_effect=AssertionError("no request")), \
             patch.object(tc, "write_cache"):
            return tc.fetch_tides_range_tidecheck("fes2022-lisbon", start, end, tz)

    def test_a_row_whose_time_is_null_is_passed_over(self):
        raw = {"datum": "MLLW", "extremes": self.EXTREMES, "timeSeries": [
            {"time": None, "height": 1.0},
            {"time": 20260327, "height": 1.0},
            {"time": "2026-03-27T00:15:00.000Z", "height": 0.994},
            {"time": "2026-03-27T00:30:00.000Z", "height": None},
        ]}
        curve = self._curve(raw)
        self.assertEqual([when.strftime("%H:%M") for when, _height in curve], ["00:15"])

    def test_a_turn_whose_time_is_null_is_passed_over(self):
        extremes = [{"time": None, "height": 0.5, "type": "low"}, *self.EXTREMES]
        with patch.dict("os.environ", {"LINECAST_TIDECHECK_KEY": "k"}), \
             patch.object(tc, "read_cache", return_value=None), \
             patch.object(tc, "_fetch_tides_raw", return_value={"extremes": extremes}), \
             patch.object(tc, "write_cache"):
            turns = tc.fetch_hilo_range_tidecheck("fes2022-lisbon", date(2026, 3, 27),
                                                  date(2026, 3, 27), timezone.utc)
        self.assertEqual([kind for _when, _height, kind in turns], ["H", "L", "H"])

    def test_an_answer_that_is_a_list_is_no_turns(self):
        with patch.dict("os.environ", {"LINECAST_TIDECHECK_KEY": "k"}), \
             patch.object(tc, "read_cache", return_value=None), \
             patch.object(tc, "_fetch_tides_raw", return_value=[{"extremes": []}]), \
             patch.object(tc, "write_cache"):
            self.assertEqual(tc.fetch_hilo_range_tidecheck(
                "fes2022-lisbon", date(2026, 3, 27), date(2026, 3, 27), timezone.utc), [])

    def test_the_series_is_the_curve_at_its_own_instants(self):
        raw = {"datum": "MLLW", "extremes": self.EXTREMES, "timeSeries": [
            {"time": "2026-03-27T00:00:00.000Z", "height": 1.0},
            {"time": "2026-03-27T00:15:00.000Z", "height": 0.994},
            {"time": "2026-03-27T00:30:00.000Z", "height": 0.976},
        ]}
        curve = self._curve(raw)
        self.assertEqual([t for t, _h in curve],
                         [datetime(2026, 3, 27, 0, m, tzinfo=timezone.utc) for m in (0, 15, 30)])
        # metres, as every TideCheck height is; the pipeline works in feet
        for (_t, feet), metres in zip(curve, (1.0, 0.994, 0.976)):
            self.assertAlmostEqual(feet, metres / 0.3048, places=6)

    def test_nothing_is_drawn_between_the_samples(self):
        start = datetime(2026, 3, 27, tzinfo=timezone.utc)
        raw = {"extremes": self.EXTREMES, "timeSeries": _quarter_hours(start, 49)}
        curve = self._curve(raw)
        # twelve hours of the API's quarter hours, not the six-minute
        # steps of a curve made from the three turns
        self.assertEqual(len(curve), 49)
        self.assertEqual({b[0] - a[0] for a, b in zip(curve, curve[1:])},
                         {timedelta(minutes=15)})

    def test_the_curve_is_whole_where_the_turns_are_days_apart(self):
        # A sea with hardly a tide: the API names a high and, forty
        # hours on, a low. Too far apart to be one falling tide, so a
        # curve made from the turns draws nothing between them.
        extremes = [
            {"time": "2026-03-27T02:00:00.000Z", "height": 0.31, "type": "high"},
            {"time": "2026-03-28T18:00:00.000Z", "height": 0.22, "type": "low"},
        ]
        start = datetime(2026, 3, 27, tzinfo=timezone.utc)
        series = _quarter_hours(start, 2 * 96 + 1, height=lambda i: 0.25 + 0.0001 * i)
        self.assertEqual(self._curve({"extremes": extremes}, end=date(2026, 3, 28)), [])
        curve = self._curve({"extremes": extremes, "timeSeries": series},
                            end=date(2026, 3, 28))
        self.assertEqual((curve[0][0], curve[-1][0]), (start, start + timedelta(days=2)))
        self.assertEqual({b[0] - a[0] for a, b in zip(curve, curve[1:])},
                         {timedelta(minutes=15)})

    def test_the_curve_runs_on_to_midnight_utc_past_the_last_turn(self):
        # The end of a real answer for Mumbai (October 2026): the API's
        # days are UTC's, so the series stops at 00:00Z, which is 05:30
        # in the morning there, a quarter hour after the last high water
        mumbai = ZoneInfo("Asia/Kolkata")
        raw = {
            "station": {"id": "fes2022-mumbai", "name": "Mumbai", "timezone": "Asia/Kolkata"},
            "datum": "MLLW",
            "extremes": [
                {"time": "2026-10-30T17:45:34.027Z", "localTime": "2026-10-30T23:15:34+05:30",
                 "localDate": "2026-10-30", "height": -1.323, "type": "low"},
                {"time": "2026-10-30T23:44:38.344Z", "localTime": "2026-10-31T05:14:38+05:30",
                 "localDate": "2026-10-31", "height": 8.649, "type": "high"},
            ],
            "timeSeries": [
                {"time": "2026-10-30T23:30:00.000Z", "height": 8.631},
                {"time": "2026-10-30T23:45:00.000Z", "height": 8.649},
                {"time": "2026-10-31T00:00:00.000Z", "height": 8.62},
            ],
        }
        curve = self._curve(raw, tz=mumbai, start=date(2026, 10, 30), end=date(2026, 10, 31))
        last, feet = curve[-1]
        self.assertEqual(last.isoformat(), "2026-10-31T05:30:00+05:30")
        self.assertAlmostEqual(feet, 8.62 / 0.3048, places=6)
        with patch.dict("os.environ", {"LINECAST_TIDECHECK_KEY": "k"}), \
             patch.object(tc, "read_cache", return_value=None), \
             patch.object(tc, "_fetch_tides_raw", return_value=raw), \
             patch.object(tc, "write_cache"):
            turns = tc.fetch_hilo_range_tidecheck(
                "fes2022-mumbai", date(2026, 10, 30), date(2026, 10, 31), mumbai)
        self.assertGreater(last, turns[-1][0])

    def test_samples_are_placed_as_the_highs_and_lows_are(self):
        # Lisbon's clocks go back at 01:00 UTC on 25 October 2026. The
        # samples either side are a quarter hour apart all the same,
        # and the low among them sits on the sample taken at its instant.
        lisbon = ZoneInfo("Europe/Lisbon")
        start = datetime(2026, 10, 25, 0, 30, tzinfo=timezone.utc)
        raw = {"timeSeries": _quarter_hours(start, 4), "extremes": [
            {"time": "2026-10-24T19:00:00.000Z", "height": 3.1, "type": "high"},
            {"time": "2026-10-25T01:00:00.000Z", "height": 0.4, "type": "low"},
        ]}
        curve = self._curve(raw, tz=lisbon, start=date(2026, 10, 25), end=date(2026, 10, 25))
        self.assertEqual([t.strftime("%H:%M %z") for t, _h in curve],
                         ["01:30 +0100", "01:45 +0100", "01:00 +0000", "01:15 +0000"])
        self.assertEqual([b[0] - a[0] for a, b in zip(curve, curve[1:])],
                         [timedelta(minutes=15)] * 3)
        with patch.dict("os.environ", {"LINECAST_TIDECHECK_KEY": "k"}), \
             patch.object(tc, "read_cache", return_value=None), \
             patch.object(tc, "_fetch_tides_raw", return_value=raw), \
             patch.object(tc, "write_cache"):
            turns = tc.fetch_hilo_range_tidecheck(
                "fes2022-lisbon", date(2026, 10, 25), date(2026, 10, 25), lisbon)
        low = turns[-1][0]
        self.assertEqual(low, curve[2][0])
        self.assertEqual(low.utcoffset(), curve[2][0].utcoffset())

    def test_a_series_out_of_order_comes_back_in_order(self):
        start = datetime(2026, 3, 27, tzinfo=timezone.utc)
        rows = _quarter_hours(start, 8, height=lambda i: 0.1 * i)
        curve = self._curve({"extremes": self.EXTREMES, "timeSeries": rows[4:] + rows[:4]})
        self.assertEqual([round(h * 0.3048, 6) for _t, h in curve],
                         [round(0.1 * i, 6) for i in range(8)])

    def test_rows_that_cannot_be_read_are_left_out_and_the_rest_kept(self):
        raw = {"extremes": self.EXTREMES, "timeSeries": [
            {"time": "2026-03-27T00:00:00.000Z", "height": 1.0},
            {"time": "not a time", "height": 0.9},
            {"height": 0.9},
            {"time": "2026-03-27T00:45:00.000Z"},
            {"time": "2026-03-27T01:00:00.000Z", "height": None},
            {"time": "2026-03-27T01:15:00.000Z", "height": "high"},
            None,
            {"time": "2026-03-27T01:30:00.000Z", "height": 0.8},
        ]}
        with patch.object(tc, "log_skipped") as skipped:
            curve = self._curve(raw)
        self.assertEqual([t.strftime("%H:%M") for t, _h in curve], ["00:00", "01:30"])
        # and --debug says how many went
        self.assertEqual(skipped.call_args.args[:4], ("tides/tidecheck", "series", 6, 8))

    def test_a_response_with_no_series_has_its_curve_made_from_the_turns(self):
        unreadable = [{"time": "not a time", "height": 1.0}, {"height": 1.0}]
        for name, series in (("null", None), ("empty", []), ("not a list", {"0": 1.0}),
                             ("no row readable", unreadable)):
            with self.subTest(series=name):
                curve = self._curve({"extremes": self.EXTREMES, "timeSeries": series})
                # six-minute steps from the first turn to the last
                self.assertEqual(curve[0][0], datetime(2026, 3, 27, tzinfo=timezone.utc))
                self.assertEqual(curve[-1][0], datetime(2026, 3, 27, 12, tzinfo=timezone.utc))
                self.assertEqual({b[0] - a[0] for a, b in zip(curve, curve[1:])},
                                 {timedelta(minutes=6)})
                self.assertAlmostEqual(curve[60][1], 0.2 / 0.3048, places=6)

    def test_a_response_with_neither_is_no_curve(self):
        for raw in (None, {}, {"extremes": [], "timeSeries": []},
                    {"extremes": None, "timeSeries": None}):
            with self.subTest(raw=raw):
                self.assertEqual(self._curve(raw), [])

    def test_a_series_marked_in_feet_is_left_in_feet(self):
        raw = {"unit": "feet", "extremes": self.EXTREMES,
               "timeSeries": [{"time": "2026-03-27T00:00:00.000Z", "height": 3.5}]}
        self.assertEqual([h for _t, h in self._curve(raw)], [3.5])


class SeriesRequestTests(unittest.TestCase):
    """What the curve costs the day's fifty requests, counted in a cache
    of the test's own; the answers come from a stub, never the service."""

    RAW = {
        "station": {"id": "fes2022-lisbon", "name": "Lisbon", "timezone": "Europe/Lisbon"},
        "datum": "MLLW",
        "extremes": [
            {"time": "2026-03-27T00:00:00.000Z", "height": 1.0, "type": "high"},
            {"time": "2026-03-27T06:00:00.000Z", "height": 0.2, "type": "low"},
        ],
        "timeSeries": [
            {"time": "2026-03-27T00:00:00.000Z", "height": 1.0},
            {"time": "2026-03-27T00:15:00.000Z", "height": 0.994},
        ],
    }

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        env = patch.dict("os.environ", {"LINECAST_CACHE_DIR": tmp.name,
                                        "LINECAST_TIDECHECK_KEY": "k"})
        env.start()
        self.addCleanup(env.stop)
        fetch = patch.object(tc, "fetch_json", return_value=self.RAW)
        self.fetch = fetch.start()
        self.addCleanup(fetch.stop)

    def test_the_curve_and_the_turns_share_one_request(self):
        day = date(2026, 3, 27)
        curve = tc.fetch_tides_range_tidecheck("fes2022-lisbon", day, day, timezone.utc)
        turns = tc.fetch_hilo_range_tidecheck("fes2022-lisbon", day, day, timezone.utc)
        again = tc.fetch_tides_range_tidecheck("fes2022-lisbon", day, day, timezone.utc)
        self.assertEqual(len(curve), 2)
        self.assertEqual([k for _t, _h, k in turns], ["H", "L"])
        self.assertEqual(again, curve)
        self.fetch.assert_called_once()
        self.assertEqual(tc.requests_today(), 1)

    def test_the_request_covers_the_range_with_two_days_to_spare(self):
        def days_asked(start, end):
            self.fetch.reset_mock()
            tc.fetch_tides_range_tidecheck("fes2022-lisbon", start, end, timezone.utc)
            url = self.fetch.call_args.args[0]
            self.assertIn("/station/fes2022-lisbon/tides?", url)
            self.assertIn("datum=MLLW", url)
            return int(url.split("days=")[1].split("&")[0])

        self.assertEqual(days_asked(date(2026, 3, 27), date(2026, 3, 27)), 3)
        self.assertEqual(days_asked(date(2026, 3, 27), date(2026, 4, 2)), 9)
        # a month view's 31 days, and the 30 that are the most the API serves
        self.assertEqual(days_asked(date(2026, 3, 1), date(2026, 3, 31)), 30)

    def test_without_a_key_nothing_is_asked(self):
        with patch.dict("os.environ", {"LINECAST_TIDECHECK_KEY": ""}):
            self.assertEqual(tc.fetch_tides_range_tidecheck(
                "fes2022-lisbon", date(2026, 3, 27), date(2026, 3, 27), timezone.utc), [])
        self.fetch.assert_not_called()
        self.assertEqual(tc.requests_today(), 0)

    def test_a_refused_request_draws_the_curve_from_the_copy_it_has(self):
        day = date(2026, 3, 27)
        curve = tc.fetch_tides_range_tidecheck("fes2022-lisbon", day, day, timezone.utc)
        # the copy has gone stale and the day's budget is spent
        raw_file = common.cache_dir() / "tc_raw_fes2022-lisbon_3d.json"
        then = time.time() - 2 * 86400
        os.utime(raw_file, (then, then))
        tc.write_cache(tc._tally_file(), {"count": tc.FREE_TIER_LIMIT})
        self.fetch.reset_mock()
        self.assertEqual(
            tc.fetch_tides_range_tidecheck("fes2022-lisbon", day, day, timezone.utc), curve)
        self.fetch.assert_not_called()
