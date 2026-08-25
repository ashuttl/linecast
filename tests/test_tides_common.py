"""Tests for the helpers the tide providers share."""

import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from linecast import _tides_common as common

AEST = timezone(timedelta(hours=10))


class LegacyCacheSweepTests(unittest.TestCase):
    LEGACY = [
        "pred_8418150_20260823.json",
        "hilo_8418150_20260823.json",
        "yrange_8418150_20260724_20260922.json",
        "chs_yrange_05320_20260724_20260922.json",
        "tc_yrange_fes2022-lisbon_20260724_20260922.json",
        "qld_yrange_Gold_Coast_20260820_20260826.json",
    ]
    CURRENT = [
        "pred_8418150_202608.json",
        "hilo_8418150_202608.json",
        "yrange_8418150_202608.json",
        "chs_yrange_05320_202608.json",
        "tc_yrange_fes2022-lisbon_202608.json",
        "qld_yrange_Gold_Coast_202608.json",
        "chs_pred_05320_20260816_20260830.json",
        "chs_hilo_05320_20260816_20260830.json",
        "tc_hilo_fes2022-lisbon_20260822_20260824.json",
        "qld_pred_Gold_Coast_20260823_20260824.json",
        "all_stations.json",
        "station_meta_8418150.json",
        "station_abcd1234.json",
        "om_yrange_abcd1234.json",
    ]

    def _sweep(self, cache_dir):
        with patch.object(common, "_swept", False):
            common.sweep_legacy_cache(cache_dir)

    def test_removes_per_day_files_and_keeps_the_month_keyed_ones(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache_dir = Path(tmp)
            for name in self.LEGACY + self.CURRENT:
                (cache_dir / name).write_text("{}")
            self._sweep(cache_dir)
            self.assertEqual(sorted(p.name for p in cache_dir.iterdir()),
                             sorted(self.CURRENT))

    def test_runs_once_per_process(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache_dir = Path(tmp)
            with patch.object(common, "_swept", False):
                common.sweep_legacy_cache(cache_dir)
                (cache_dir / self.LEGACY[0]).write_text("{}")
                common.sweep_legacy_cache(cache_dir)
                self.assertTrue((cache_dir / self.LEGACY[0]).exists())

    def test_missing_directory_is_fine(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._sweep(Path(tmp) / "not-there")


class YRangeWindowTests(unittest.TestCase):
    def test_window_is_month_anchored_and_covers_30_days_each_side(self):
        for center in (date(2026, 8, 1), date(2026, 8, 23), date(2026, 8, 31),
                       date(2026, 1, 1), date(2026, 12, 31), date(2028, 2, 29)):
            start, end, key = common.y_range_window(center)
            self.assertEqual(key, center.strftime("%Y%m"))
            self.assertEqual(start.day, 1)
            self.assertEqual((end + timedelta(days=1)).day, 1)
            self.assertLessEqual(start, center - timedelta(days=30))
            self.assertGreaterEqual(end, center + timedelta(days=30))

    def test_window_edges(self):
        self.assertEqual(common.y_range_window(date(2026, 8, 23)),
                         (date(2026, 7, 1), date(2026, 9, 30), "202608"))
        self.assertEqual(common.y_range_window(date(2026, 1, 15)),
                         (date(2025, 12, 1), date(2026, 2, 28), "202601"))


class CachedYRangeTests(unittest.TestCase):
    FILE = Path("yrange_test.json")

    def test_cached_value_is_returned_without_loading(self):
        with patch.object(common, "read_cache", return_value={"min": -0.5, "max": 3.0}):
            result = common.cached_y_range(
                self.FILE, lambda: self.fail("must not load heights"))
        self.assertEqual(result, (-0.5, 3.0))

    def test_range_is_computed_and_written(self):
        with patch.object(common, "read_cache", return_value=None), \
             patch.object(common, "write_cache") as write_cache:
            result = common.cached_y_range(self.FILE, lambda: [1.0, -0.5, 3.0])
        self.assertEqual(result, (-0.5, 3.0))
        write_cache.assert_called_once_with(self.FILE, {"min": -0.5, "max": 3.0})

    def test_no_heights_is_none_and_nothing_is_written(self):
        for empty in ([], None):
            with patch.object(common, "read_cache", return_value=None), \
                 patch.object(common, "write_cache") as write_cache:
                self.assertIsNone(common.cached_y_range(self.FILE, lambda empty=empty: empty))
            write_cache.assert_not_called()


class NearestStationTests(unittest.TestCase):
    FILE = Path("station_test.json")
    STATIONS = [
        {"id": "111", "name": "First Harbor", "lat": 40.0, "lng": -70.0},
        {"id": "222", "name": "Second Harbor", "lat": "47.61", "lng": "-122.33"},
    ]

    def _pick(self, lat, lng, load_stations):
        return common.nearest_station(
            self.FILE, lat, lng, load_stations, common.station_coords,
            lambda s: (s["id"], s["name"]))

    def test_closest_station_wins_and_the_pick_is_cached(self):
        with patch.object(common, "read_cache", return_value=None), \
             patch.object(common, "write_cache") as write_cache:
            picked = self._pick(47.61, -122.33, lambda: self.STATIONS)
        self.assertEqual(picked, ("222", "Second Harbor"))
        write_cache.assert_called_once_with(
            self.FILE, {"id": "222", "name": "Second Harbor",
                        "lat": 47.61, "lng": -122.33})

    def test_cached_pick_is_returned_without_loading(self):
        with patch.object(common, "read_cache", return_value={"id": "9", "name": "Cached"}):
            picked = self._pick(0.0, 0.0, lambda: self.fail("must not load"))
        self.assertEqual(picked, ("9", "Cached"))

    def test_beyond_100_nm_is_none(self):
        with patch.object(common, "read_cache", return_value=None), \
             patch.object(common, "write_cache") as write_cache:
            picked = self._pick(39.0, -98.0, lambda: self.STATIONS)
        self.assertEqual(picked, (None, None))
        write_cache.assert_not_called()

    def test_stations_without_coordinates_are_skipped(self):
        stations = [{"id": "1", "name": "No coords"},
                    {"id": "2", "name": "Bad coords", "lat": None, "lng": "x"},
                    {"id": "3", "name": "Here", "lat": 47.61, "lng": -122.33}]
        with patch.object(common, "read_cache", return_value=None), \
             patch.object(common, "write_cache"):
            picked = self._pick(47.61, -122.33, lambda: stations)
        self.assertEqual(picked[0], "3")

    def test_stale_pick_when_the_list_is_empty(self):
        with patch.object(common, "read_cache", return_value=None), \
             patch.object(common, "read_stale", return_value={"id": "9", "name": "Stale"}), \
             patch.object(common, "write_cache") as write_cache:
            picked = self._pick(47.61, -122.33, lambda: [])
        self.assertEqual(picked, ("9", "Stale"))
        write_cache.assert_not_called()

    def test_stale_pick_when_the_loader_raises(self):
        def boom():
            raise RuntimeError("network down")

        with patch.object(common, "read_cache", return_value=None), \
             patch.object(common, "read_stale", return_value={"id": "9", "name": "Stale"}):
            picked = self._pick(47.61, -122.33, boom)
        self.assertEqual(picked, ("9", "Stale"))

    def test_none_without_a_list_or_a_stale_pick(self):
        with patch.object(common, "read_cache", return_value=None), \
             patch.object(common, "read_stale", return_value=None):
            self.assertEqual(self._pick(47.61, -122.33, lambda: []), (None, None))


class TimestampTests(unittest.TestCase):
    def test_parse_utc_iso(self):
        dt = common.parse_utc_iso("2026-03-27T14:30:00Z")
        self.assertEqual(dt, datetime(2026, 3, 27, 14, 30, tzinfo=timezone.utc))
        self.assertEqual(common.parse_utc_iso("2026-03-27T14:30:00.123Z").hour, 14)
        self.assertEqual(common.parse_utc_iso("2026-03-27T14:30:00").tzinfo, timezone.utc)

    def test_parse_utc_iso_converts_to_station_tz(self):
        tz = ZoneInfo("America/New_York")
        dt = common.parse_utc_iso("2026-03-27T14:30:00Z", tz)
        self.assertEqual(dt.tzinfo, tz)
        self.assertEqual(dt.hour, 10)

    def test_parse_iso_keeps_an_offset(self):
        dt = common.parse_iso("2026-03-27T10:00:00+10:00")
        self.assertEqual(dt.utcoffset(), timedelta(hours=10))

    def test_parse_cached_dt(self):
        naive = common.parse_cached_dt("2026-03-27T10:00:00", AEST)
        self.assertEqual(naive.tzinfo, AEST)
        aware = common.parse_cached_dt("2026-03-27T10:00:00+10:00", timezone.utc)
        self.assertEqual(aware.utcoffset(), timedelta(hours=10))
        self.assertIsNone(common.parse_cached_dt("2026-03-27T10:00:00", None).tzinfo)

    def test_local_day_bounds(self):
        lo, hi = common.local_day_bounds(date(2026, 3, 27), date(2026, 3, 28), None)
        self.assertEqual((lo, hi), (datetime(2026, 3, 27), datetime(2026, 3, 29)))
        lo, hi = common.local_day_bounds(date(2026, 3, 27), date(2026, 3, 27), AEST)
        self.assertEqual(lo, datetime(2026, 3, 27, tzinfo=AEST))
        self.assertEqual(hi, datetime(2026, 3, 28, tzinfo=AEST))

    def test_dedup_sorted(self):
        t = datetime(2026, 3, 27, 10, 0)
        points = [(t + timedelta(minutes=5), 2.0), (t, 1.0),
                  (t.replace(second=30), 9.0), (t, 1.0)]
        self.assertEqual(common.dedup_sorted(points),
                         [(t, 1.0), (t + timedelta(minutes=5), 2.0)])


class TimezoneTests(unittest.TestCase):
    def test_iana_to_abbr(self):
        self.assertEqual(common.iana_to_abbr("America/Halifax"), "AST")
        self.assertEqual(common.iana_to_abbr("Canada/Atlantic"), "AST")
        self.assertEqual(common.iana_to_abbr("Europe/Lisbon"), "UTC")
        self.assertEqual(common.iana_to_abbr(""), "UTC")

    def test_tz_offset_hours(self):
        self.assertEqual(common.tz_offset_hours(""), 0)
        self.assertEqual(common.tz_offset_hours("Not/AZone"), 0)
        self.assertEqual(common.tz_offset_hours("Australia/Brisbane"), 10)


class LabelHiloTests(unittest.TestCase):
    def test_label_hilo_basic(self):
        values = [
            (datetime(2026, 3, 27, 2, 0, tzinfo=AEST), 0.5),
            (datetime(2026, 3, 27, 8, 0, tzinfo=AEST), 2.5),
            (datetime(2026, 3, 27, 14, 0, tzinfo=AEST), 0.3),
            (datetime(2026, 3, 27, 20, 0, tzinfo=AEST), 2.8),
        ]
        labeled = common.label_hilo(values)
        self.assertEqual([t for _, _, t in labeled], ["L", "H", "L", "H"])

    def test_label_hilo_single(self):
        values = [(datetime(2026, 3, 27, 8, 0, tzinfo=AEST), 2.5)]
        self.assertEqual(common.label_hilo(values), [(*values[0], "H")])

    def test_label_hilo_empty(self):
        self.assertEqual(common.label_hilo([]), [])


if __name__ == "__main__":
    unittest.main()
