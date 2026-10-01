"""Tests for the helpers the tide providers share."""

import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from linecast.tides import common
from linecast.tides import harmonic

AEST = timezone(timedelta(hours=10))


class LegacyCacheSweepTests(unittest.TestCase):
    LEGACY = [
        "pred_8418150_20260823.json",
        "hilo_8418150_20260823.json",
        "yrange_8418150_20260724_20260922.json",
        "chs_yrange_05320_20260724_20260922.json",
        "tc_yrange_fes2022-lisbon_20260724_20260922.json",
        "qld_yrange_Gold_Coast_20260820_20260826.json",
        "qld_all_stations.json",
        "qld_meta_birkdale.json",
        "qld_pred_birkdale_20260823_20260824.json",
        "qld_yrange_birkdale_202608.json",
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
        "qld_stations.json",
        "qld_meta_Brisbane_Bar.json",
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
        self.assertEqual(common.iana_to_abbr(""), "UTC")
        self.assertEqual(common.iana_to_abbr("Not/AZone"), "UTC")
        # Zones without a mapped abbreviation show their offset instead
        self.assertEqual(common.iana_to_abbr("Asia/Tashkent"), "UTC+5")
        self.assertEqual(common.iana_to_abbr("Asia/Kathmandu"), "UTC+5:45")
        self.assertEqual(common.iana_to_abbr("Pacific/Tahiti"), "UTC-10")

    def test_format_utc_offset(self):
        self.assertEqual(common.format_utc_offset(0), "UTC")
        self.assertEqual(common.format_utc_offset(9), "UTC+9")
        self.assertEqual(common.format_utc_offset(-3.5), "UTC-3:30")
        self.assertEqual(common.format_utc_offset(5.75), "UTC+5:45")

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


class ComputedTideTests(unittest.TestCase):
    """A tide computed from its constants, served in the shapes a table
    is: feet, on the station's clock, a day running from its midnight to
    the next."""

    # A semidiurnal tide of about Portland, Maine's size, in metres. The
    # constants are round numbers, not NOAA's: nothing here is compared
    # with a published table, only the tide with itself.
    TIDE = harmonic.Tide([("M2", 1.36, 103.0), ("S2", 0.21, 139.0), ("N2", 0.30, 73.0),
                          ("K1", 0.14, 201.0), ("O1", 0.11, 182.0)], z0=1.51)
    NEW_YORK = ZoneInfo("America/New_York")
    SIX_MINUTES = timedelta(minutes=6)

    @staticmethod
    def _elapsed(points):
        """The time that passes between each point and the next."""
        instants = [p[0].astimezone(timezone.utc) for p in points]
        return {b - a for a, b in zip(instants, instants[1:])}

    def test_the_curve_runs_every_six_minutes_from_midnight_to_midnight(self):
        tz = self.NEW_YORK
        curve = common.computed_range(self.TIDE, date(2026, 8, 20), date(2026, 8, 21), tz)
        self.assertEqual(curve[0][0], datetime(2026, 8, 20, tzinfo=tz))
        self.assertEqual(curve[-1][0], datetime(2026, 8, 22, tzinfo=tz))
        self.assertEqual(len(curve), 2 * 240 + 1)
        self.assertEqual(self._elapsed(curve), {self.SIX_MINUTES})
        self.assertTrue(all(t.tzinfo is tz for t, _h in curve))

    def test_the_heights_are_the_tides_own_in_feet(self):
        curve = common.computed_range(self.TIDE, date(2026, 8, 20), date(2026, 8, 20),
                                      self.NEW_YORK)
        for t, feet in curve[::40]:
            self.assertAlmostEqual(feet * 0.3048, self.TIDE.height(t), places=9)
        # the mean level is 1.51 m, and the curve swings about it
        heights = [h for _t, h in curve]
        self.assertLess(min(heights), 1.51 / 0.3048)
        self.assertGreater(max(heights), 1.51 / 0.3048)

    def test_a_day_the_clocks_change_is_as_long_as_it_is(self):
        tz = self.NEW_YORK
        # New York's clocks go back on 1 November 2026 and forward on 8 March
        for day, hours in ((date(2026, 11, 1), 25), (date(2026, 3, 8), 23)):
            with self.subTest(day=day):
                curve = common.computed_range(self.TIDE, day, day, tz)
                self.assertEqual(len(curve), hours * 10 + 1)
                self.assertEqual(self._elapsed(curve), {self.SIX_MINUTES})
                self.assertEqual(curve[0][0], datetime(day.year, day.month, day.day, tzinfo=tz))
                self.assertEqual(curve[-1][0],
                                 datetime(day.year, day.month, day.day + 1, tzinfo=tz))

    def test_without_a_zone_the_days_are_utc_and_the_times_naive(self):
        curve = common.computed_range(self.TIDE, date(2026, 12, 31), date(2026, 12, 31), None)
        self.assertEqual((curve[0][0], curve[-1][0]),
                         (datetime(2026, 12, 31), datetime(2027, 1, 1)))
        self.assertEqual(len(curve), 241)
        t, feet = curve[100]
        self.assertAlmostEqual(feet * 0.3048,
                               self.TIDE.height(t.replace(tzinfo=timezone.utc)), places=9)
        turns = common.computed_hilo(self.TIDE, date(2026, 12, 31), date(2026, 12, 31), None)
        self.assertTrue(turns)
        self.assertTrue(all(t.tzinfo is None and datetime(2026, 12, 31) <= t
                            <= datetime(2027, 1, 1) for t, _h, _k in turns))

    def test_a_zone_a_quarter_hour_off_keeps_within_its_own_day(self):
        # Kathmandu is UTC+5:45, so its midnight falls between two of
        # the six-minute marks, which are counted on UTC's clock
        tz = ZoneInfo("Asia/Kathmandu")
        curve = common.computed_range(self.TIDE, date(2026, 8, 20), date(2026, 8, 20), tz)
        self.assertEqual(len(curve), 240)
        self.assertEqual({t.date() for t, _h in curve}, {date(2026, 8, 20)})
        self.assertEqual(self._elapsed(curve), {self.SIX_MINUTES})

    def test_the_turns_alternate_within_the_dates(self):
        tz = self.NEW_YORK
        turns = common.computed_hilo(self.TIDE, date(2026, 8, 20), date(2026, 8, 22), tz)
        # two highs and two lows a day, less one where the lunar day runs over
        self.assertIn(len(turns), (11, 12))
        kinds = [k for _t, _h, k in turns]
        self.assertTrue(all(a != b for a, b in zip(kinds, kinds[1:])), kinds)
        self.assertEqual(set(kinds), {"H", "L"})
        for t, _h, _k in turns:
            self.assertIs(t.tzinfo, tz)
            self.assertTrue(datetime(2026, 8, 20, tzinfo=tz) <= t
                            <= datetime(2026, 8, 23, tzinfo=tz))

    def test_each_turn_is_where_the_curve_turns(self):
        tz = self.NEW_YORK
        day = date(2026, 8, 20)
        curve = common.computed_range(self.TIDE, day, day, tz)
        turns = common.computed_hilo(self.TIDE, day, day, tz)
        for t, feet, kind in turns:
            # the six-minute samples either side of it: within three
            # minutes of the turn, the curve's own extreme for the hour
            near = [(dt, h) for dt, h in curve if abs(dt - t) <= timedelta(minutes=30)]
            pick = max if kind == "H" else min
            at, height = pick(near, key=lambda p: p[1])
            self.assertLessEqual(abs(at - t), timedelta(minutes=3))
            # and a hundredth of a foot is more than six minutes can hide
            self.assertAlmostEqual(feet, height, delta=0.01)

    def test_the_axis_range_is_the_range_of_three_months_of_turns(self):
        tz = self.NEW_YORK
        low, high = common.computed_y_range(self.TIDE, date(2026, 8, 23), tz)
        # July through September: the window every source's axis is
        # measured over, so springs and neaps are both inside it
        curve = common.computed_range(self.TIDE, date(2026, 7, 1), date(2026, 9, 30), tz)
        heights = [h for _t, h in curve]
        self.assertAlmostEqual(low, min(heights), delta=0.01)
        self.assertAlmostEqual(high, max(heights), delta=0.01)
        # wider than the one day's own range, which a neap would make it
        day = [h for _t, h, _k in common.computed_hilo(
            self.TIDE, date(2026, 8, 23), date(2026, 8, 23), tz)]
        self.assertLess(low, min(day))
        self.assertGreater(high, max(day))

    def test_every_day_of_the_month_has_the_same_axis(self):
        ranges = {common.computed_y_range(self.TIDE, day, self.NEW_YORK)
                  for day in (date(2026, 8, 1), date(2026, 8, 23), date(2026, 8, 31))}
        self.assertEqual(len(ranges), 1)

    def test_a_sea_with_no_tide_has_a_level_and_no_turns(self):
        still = harmonic.Tide([], z0=0.25)
        day = date(2026, 8, 20)
        curve = common.computed_range(still, day, day, timezone.utc)
        self.assertEqual({round(h, 9) for _t, h in curve}, {round(0.25 / 0.3048, 9)})
        self.assertEqual(common.computed_hilo(still, day, day, timezone.utc), [])
        self.assertIsNone(common.computed_y_range(still, day, timezone.utc))


if __name__ == "__main__":
    unittest.main()


class MeasuredTurnsTests(unittest.TestCase):
    """What a gauge read, taken at the turns the tables predict."""

    START = datetime(2026, 3, 1)
    TURNS = [(datetime(2026, 3, 1, 3), 9.0, "H"), (datetime(2026, 3, 1, 9), 1.0, "L"),
             (datetime(2026, 3, 1, 15), 8.0, "H"), (datetime(2026, 3, 1, 21), 0.5, "L"),
             (datetime(2026, 3, 2, 3), 9.0, "H")]

    def _level(self, step, readings):
        """A day and a half of nothing, with *readings* {(day, hour, minute): value}."""
        level = [None] * (36 * 3600 // step)
        for (day, hour, minute), value in readings.items():
            level[((day - 1) * 86400 + hour * 3600 + minute * 60) // step] = value
        return level

    def test_each_turn_reads_the_highest_or_lowest_of_the_readings_nearest_it(self):
        level = self._level(900, {(1, 3, 15): 9.4, (1, 5, 45): 6.0,     # the high, and its ebb
                                  (1, 6, 15): 5.0, (1, 9, 0): 1.3,      # the low's flood side
                                  (1, 14, 45): 8.2, (1, 21, 15): 0.9})
        # the gaps between are far past any allowance, so none is asked
        days = common.measured_turns(self.TURNS, level, self.START, date(2026, 3, 1), 900, None)
        self.assertEqual(days, {date(2026, 3, 1): (0.9, 9.4)})

    def test_a_reading_is_in_the_gauges_own_unit_at_any_spacing(self):
        for step in (360, 900, 3600):
            with self.subTest(step=step):
                level = self._level(step, {(1, 3, 0): 2.74, (1, 9, 0): 0.31,
                                           (1, 15, 0): 2.44, (1, 21, 0): 0.15})
                days = common.measured_turns(self.TURNS, level, self.START,
                                             date(2026, 3, 1), step, None)
                self.assertEqual(days, {date(2026, 3, 1): (0.15, 2.74)})

    def test_a_turn_with_no_reading_leaves_its_day_out(self):
        level = self._level(360, {(1, 3, 0): 9.4, (1, 9, 0): 1.3, (1, 15, 0): 8.2})
        self.assertEqual(
            common.measured_turns(self.TURNS, level, self.START, date(2026, 3, 1), 360, None), {})

    def test_a_run_of_missing_readings_longer_than_the_gap_leaves_the_day_out(self):
        whole = [5.0] * (36 * 10)
        self.assertIn(date(2026, 3, 1), common.measured_turns(
            self.TURNS, whole, self.START, date(2026, 3, 1), 360, 6))
        for missing, kept in ((6, True), (7, False)):
            with self.subTest(missing=missing):
                level = list(whole)
                level[100:100 + missing] = [None] * missing
                days = common.measured_turns(self.TURNS, level, self.START,
                                             date(2026, 3, 1), 360, 6)
                self.assertEqual(date(2026, 3, 1) in days, kept)

    def test_days_after_the_last_are_not_measured(self):
        level = [5.0] * (36 * 10)
        days = common.measured_turns(self.TURNS, level, self.START, date(2026, 3, 1), 360, 6)
        self.assertEqual(list(days), [date(2026, 3, 1)])
