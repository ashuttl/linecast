"""Tests for the Open-Meteo global tide model data source."""

import math
import unittest
from datetime import date, datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

from linecast import _tides_openmeteo as om


def _payload(times, heights, tz="America/New_York", lat=43.625, lng=-70.208):
    return {
        "latitude": lat,
        "longitude": lng,
        "timezone": tz,
        "utc_offset_seconds": -14400,
        "hourly_units": {"time": "iso8601", "sea_level_height_msl": "m"},
        "hourly": {"time": times, "sea_level_height_msl": heights},
    }


def _tide_payload(hours=48, period=12.42, amp=1.5):
    """Synthetic sinusoidal tide, hourly, starting 2026-08-16T00:00."""
    start = datetime(2026, 8, 16)
    times = [(start + timedelta(hours=i)).strftime("%Y-%m-%dT%H:%M")
             for i in range(hours)]
    heights = [round(amp * math.sin(2 * math.pi * i / period), 3)
               for i in range(hours)]
    return _payload(times, heights)


class StationIdTests(unittest.TestCase):
    def test_round_trip(self):
        sid = om.make_station_id(43.6771, -70.3712)
        self.assertTrue(om.is_openmeteo_station_id(sid))
        lat, lng = om.parse_station_id(sid)
        self.assertAlmostEqual(lat, 43.6771, places=4)
        self.assertAlmostEqual(lng, -70.3712, places=4)

    def test_non_openmeteo_ids_rejected(self):
        self.assertFalse(om.is_openmeteo_station_id("8418150"))
        self.assertIsNone(om.parse_station_id("8418150"))
        self.assertIsNone(om.parse_station_id("om:junk"))


class SeriesTests(unittest.TestCase):
    def test_converts_metres_to_feet(self):
        data = _payload(["2026-08-16T00:00"], [1.0])
        points = om._series(data, None)
        self.assertEqual(len(points), 1)
        self.assertAlmostEqual(points[0][1], 1 / 0.3048, places=4)

    def test_skips_null_heights(self):
        data = _payload(["2026-08-16T00:00", "2026-08-16T01:00"], [None, 0.5])
        points = om._series(data, None)
        self.assertEqual(len(points), 1)

    def test_attaches_timezone(self):
        tz = ZoneInfo("America/New_York")
        data = _payload(["2026-08-16T00:00"], [0.5])
        points = om._series(data, tz)
        self.assertEqual(points[0][0].tzinfo, tz)

    def test_empty_or_malformed(self):
        self.assertEqual(om._series(None, None), [])
        self.assertEqual(om._series({}, None), [])
        self.assertEqual(om._series({"hourly": {}}, None), [])


class CoverageTests(unittest.TestCase):
    def test_wet_cell_yields_station(self):
        with patch.object(om, "_fetch_raw", return_value=_tide_payload()):
            sid, name = om.find_nearest_openmeteo(43.677, -70.371)
        self.assertEqual(sid, "om:43.6770,-70.3710")
        self.assertIsNone(name)

    def test_all_null_series_yields_none(self):
        data = _payload(["2026-08-16T00:00", "2026-08-16T01:00"], [None, None])
        with patch.object(om, "_fetch_raw", return_value=data):
            sid, name = om.find_nearest_openmeteo(39.0, -98.0)
        self.assertIsNone(sid)

    def test_fetch_failure_yields_none(self):
        with patch.object(om, "_fetch_raw", return_value=None):
            sid, name = om.find_nearest_openmeteo(43.677, -70.371)
        self.assertIsNone(sid)

    def test_missing_coords_yield_none(self):
        sid, name = om.find_nearest_openmeteo(None, None)
        self.assertIsNone(sid)


class MetadataTests(unittest.TestCase):
    def test_metadata_shape(self):
        with patch.object(om, "_fetch_raw", return_value=_tide_payload()):
            meta = om.fetch_station_metadata_openmeteo("om:43.6770,-70.3710")
        self.assertEqual(meta["source"], "openmeteo")
        self.assertEqual(meta["timeZoneCode"], "America/New_York")
        self.assertEqual(meta["lat"], 43.625)  # snapped grid cell
        self.assertEqual(meta["timezonecorr"], -4)
        self.assertEqual(meta["name"], "")

    def test_bad_station_id(self):
        self.assertIsNone(om.fetch_station_metadata_openmeteo("8418150"))


class RangeTests(unittest.TestCase):
    def test_range_filters_dates(self):
        tz = ZoneInfo("America/New_York")
        with patch.object(om, "_fetch_raw", return_value=_tide_payload(hours=72)):
            points = om.fetch_tides_range_openmeteo(
                "om:43.6770,-70.3710", date(2026, 8, 17), date(2026, 8, 17), tz)
        self.assertTrue(points)
        for dt, _h in points:
            self.assertEqual(dt.tzinfo, tz)
            self.assertGreaterEqual(dt, datetime(2026, 8, 17, tzinfo=tz))
            self.assertLessEqual(dt, datetime(2026, 8, 18, tzinfo=tz))

    def test_y_range_spans_series(self):
        with patch.object(om, "_fetch_raw", return_value=_tide_payload()), \
             patch.object(om, "read_cache", return_value=None), \
             patch.object(om, "write_cache"):
            y = om.fetch_y_range_openmeteo("om:43.6770,-70.3710",
                                           date(2026, 8, 17), None)
        self.assertIsNotNone(y)
        lo, hi = y
        self.assertLess(lo, 0)
        self.assertGreater(hi, 4)  # 1.5 m amplitude ≈ 4.9 ft


class ExtremaTests(unittest.TestCase):
    def test_finds_alternating_extrema(self):
        tz = ZoneInfo("America/New_York")
        with patch.object(om, "_fetch_raw", return_value=_tide_payload(hours=72)):
            hilo = om.fetch_hilo_range_openmeteo(
                "om:43.6770,-70.3710", date(2026, 8, 16), date(2026, 8, 18), tz)
        self.assertGreaterEqual(len(hilo), 8)  # ~4 highs + 4 lows over 3 days
        kinds = [t for _, _, t in hilo]
        for a, b in zip(kinds, kinds[1:]):
            self.assertNotEqual(a, b, "extrema should alternate H/L")

    def test_parabolic_refinement_beats_hourly_sampling(self):
        # True peak of sin(2*pi*t/12.42) is at t = 3.105 h; hourly sampling
        # alone would put it at 3.0 exactly.
        points = [(datetime(2026, 8, 16) + timedelta(hours=i),
                   math.sin(2 * math.pi * i / 12.42))
                  for i in range(13)]
        extrema = om._extrema(points)
        highs = [(dt, h) for dt, h, t in extrema if t == "H"]
        self.assertEqual(len(highs), 1)
        dt, h = highs[0]
        true_peak = datetime(2026, 8, 16) + timedelta(hours=12.42 / 4)
        self.assertLess(abs((dt - true_peak).total_seconds()), 15 * 60)
        self.assertNotEqual(dt.minute, 0)
        self.assertAlmostEqual(h, 1.0, delta=0.02)

    def test_flat_series_has_no_extrema(self):
        points = [(datetime(2026, 8, 16) + timedelta(hours=i), 1.0)
                  for i in range(10)]
        self.assertEqual(om._extrema(points), [])


if __name__ == "__main__":
    unittest.main()
