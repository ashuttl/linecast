"""Tests for the Open-Meteo global tide model data source."""

import math
import os
import shutil
import tempfile
import time
import unittest
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

from linecast import _http
from linecast.tides import common
from linecast.tides import harmonic
from linecast.tides import openmeteo as om


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

    def test_hours_past_a_clock_change_are_on_the_new_clock(self):
        # fetched in AEST, before Sydney's clocks go forward on 4 October:
        # every hour is stamped +10, the ones after 02:00 as well
        tz = ZoneInfo("Australia/Sydney")
        data = _payload(["2026-10-04T01:00", "2026-10-04T02:00",
                         "2026-10-05T10:00"], [0.1, 0.2, 0.3],
                        tz="Australia/Sydney")
        data["utc_offset_seconds"] = 36000
        points = om._series(data, tz)
        self.assertEqual([p[0].strftime("%d %H:%M %Z") for p in points],
                         ["04 01:00 AEST", "04 03:00 AEDT", "05 11:00 AEDT"])

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
             patch.object(common, "read_cache", return_value=None), \
             patch.object(common, "write_cache"):
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

    def test_a_high_beside_a_clock_change_is_timed_on_the_instants(self):
        # 01:00 AEST and 03:00 AEDT are an hour apart, not two
        tz = ZoneInfo("Australia/Sydney")
        points = [(datetime(2026, 10, 4, 1, tzinfo=tz), 1.0),
                  (datetime(2026, 10, 4, 3, tzinfo=tz), 2.0),
                  (datetime(2026, 10, 4, 4, tzinfo=tz), 0.0)]
        [(dt, _h, typ)] = om._extrema(points)
        self.assertEqual(typ, "H")
        self.assertEqual(dt.strftime("%H:%M %Z"), "01:50 AEST")

    def test_flat_series_has_no_extrema(self):
        points = [(datetime(2026, 8, 16) + timedelta(hours=i), 1.0)
                  for i in range(10)]
        self.assertEqual(om._extrema(points), [])


STATION = "om:43.6770,-70.3710"
NEW_YORK = ZoneInfo("America/New_York")

# The tide the model is given in these tests, in metres about mean sea
# level: a semidiurnal one of about Portland, Maine's size. Round
# numbers, not NOAA's constants; the fit is compared with this, the tide
# its series was made from.
TRUTH = harmonic.Tide([("M2", 1.36, 103.0), ("S2", 0.21, 139.0), ("N2", 0.30, 73.0),
                       ("K1", 0.14, 201.0), ("O1", 0.11, 182.0)], z0=0.03)
# A centimetre, in feet: what the model's heights are rounded to here
CENTIMETRE = 0.01 / 0.3048


class _Today(date):
    """The module's date, with today held at 1 October 2026."""

    @classmethod
    def today(cls):
        return date(2026, 10, 1)


def _year_payload(first, last, height=TRUTH.height, offset=-14400, tz="America/New_York"):
    """The model's answer for the hours of *first* through *last*: local
    stamps, every one in the offset the response was made in, and the
    height in metres at the instant each names (None where *height*
    gives none)."""
    stamp = datetime(first.year, first.month, first.day)
    end = datetime(last.year, last.month, last.day) + timedelta(days=1)
    shift = timedelta(seconds=offset)
    times, heights = [], []
    while stamp < end:
        metres = height(stamp.replace(tzinfo=timezone.utc) - shift)
        times.append(stamp.strftime("%Y-%m-%dT%H:%M"))
        heights.append(None if metres is None else round(metres, 2))
        stamp += timedelta(hours=1)
    data = _payload(times, heights, tz=tz)
    data["utc_offset_seconds"] = offset
    return data


class _Marine:
    """Open-Meteo's marine API for one place: it answers a request for a
    year and one for the forecast window with what the test gives it
    (None is the network down), and keeps the URLs it was asked."""

    def __init__(self, year=None, window=None):
        self.year, self.window, self.urls = year, window, []

    def __call__(self, url, headers=None, timeout=10):
        self.urls.append(url)
        answer = self.year if "start_date=" in url else self.window
        if answer is None:
            raise OSError("network down")
        return answer

    @property
    def years_asked(self):
        """(first day, last day) of each year request, in order."""
        return [(url.split("start_date=")[1][:10], url.split("end_date=")[1][:10])
                for url in self.urls if "start_date=" in url]

    @property
    def windows_asked(self):
        return sum("past_days=" in url for url in self.urls)


class _OwnCache(unittest.TestCase):
    """A cache of the test's own, today held at 1 October 2026 (so last
    year is 2025), and no tide remembered from an earlier test."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.cache = tmp.name
        for change in (patch.dict(os.environ, {"LINECAST_CACHE_DIR": tmp.name}),
                       patch.object(om, "date", _Today),
                       patch.dict(om._tides, clear=True)):
            change.start()
            self.addCleanup(change.stop)

    def _ask(self, marine):
        """Requests go to *marine* for the rest of the test."""
        fetch = patch.object(_http, "fetch_json", side_effect=marine)
        fetch.start()
        self.addCleanup(fetch.stop)
        return marine

    def _aged(self, seconds):
        """Every file in the cache was written *seconds* ago."""
        for path in common.cache_dir().iterdir():
            then = time.time() - seconds
            os.utime(path, (then, then))


class FittedTideTests(_OwnCache):
    """The tide fitted to last year's model hours predicts any date.

    The fit is made once for the class, through the first request for a
    curve, and each test reads it back from the file it was kept in.
    """

    DAY = date(2026, 10, 15)   # two weeks on, past the model's eight-day forecast

    @classmethod
    def setUpClass(cls):
        kept = tempfile.TemporaryDirectory()
        cls.addClassCleanup(kept.cleanup)
        cls.kept = kept.name
        cls.marine = _Marine(year=_year_payload(date(2025, 1, 1), date(2025, 12, 31)))
        with patch.dict(os.environ, {"LINECAST_CACHE_DIR": kept.name}), \
             patch.object(om, "date", _Today), patch.dict(om._tides, clear=True), \
             patch.object(_http, "fetch_json", side_effect=cls.marine):
            cls.first_curve = om.fetch_tides_range_openmeteo(STATION, cls.DAY, cls.DAY, NEW_YORK)

    def setUp(self):
        super().setUp()
        shutil.copytree(self.kept, self.cache, dirs_exist_ok=True)
        # the year is on file and so is the fit: there is nothing to ask,
        # and with the network down an asking would show
        self.offline = self._ask(_Marine())

    def test_last_year_is_asked_for_once_and_whole(self):
        self.assertEqual(self.marine.years_asked, [("2025-01-01", "2025-12-31")])
        self.assertEqual(self.marine.windows_asked, 0)
        self.assertIn("latitude=43.677&longitude=-70.371", self.marine.urls[0])
        self.assertIn("hourly=sea_level_height_msl", self.marine.urls[0])

    def test_a_day_past_the_forecast_is_served_every_six_minutes(self):
        curve = self.first_curve
        self.assertEqual(curve[0][0], datetime(2026, 10, 15, tzinfo=NEW_YORK))
        self.assertEqual(curve[-1][0], datetime(2026, 10, 16, tzinfo=NEW_YORK))
        self.assertEqual(len(curve), 241)
        self.assertEqual({b[0] - a[0] for a, b in zip(curve, curve[1:])},
                         {timedelta(minutes=6)})

    def test_the_fit_follows_its_series_on_days_the_series_never_reached(self):
        # the day after the year it was fitted to, a day this autumn,
        # and one the summer after next: all within a centimetre
        for day in (date(2026, 1, 1), self.DAY, date(2027, 6, 21)):
            with self.subTest(day=day):
                curve = om.fetch_tides_range_openmeteo(STATION, day, day, NEW_YORK)
                self.assertEqual(len(curve), 241)
                worst = max(abs(feet - TRUTH.height(t) / 0.3048) for t, feet in curve)
                self.assertLess(worst, CENTIMETRE)

    def test_the_turns_are_the_tides_own_to_the_minute(self):
        turns = om.fetch_hilo_range_openmeteo(STATION, self.DAY, self.DAY + timedelta(days=1),
                                              NEW_YORK)
        lo = datetime(2026, 10, 15, tzinfo=NEW_YORK)
        true = TRUTH.extremes(lo, lo + timedelta(days=2))
        self.assertEqual([k for _t, _h, k in turns], [k for _t, _h, k in true])
        self.assertIn(len(turns), (7, 8))
        for (t, feet, _k), (true_t, metres, _kind) in zip(turns, true):
            self.assertIs(t.tzinfo, NEW_YORK)
            self.assertLess(abs(t - true_t), timedelta(minutes=1))
            self.assertAlmostEqual(feet, metres / 0.3048, delta=CENTIMETRE)

    def test_the_axis_is_the_fitted_tides_over_the_months_around_the_date(self):
        low, high = om.fetch_y_range_openmeteo(STATION, self.DAY, NEW_YORK)
        # September through November of the tide the series was made from
        lo = datetime(2026, 9, 1, tzinfo=NEW_YORK)
        heights = [h / 0.3048 for _t, h, _k in
                   TRUTH.extremes(lo, datetime(2026, 12, 1, tzinfo=NEW_YORK))]
        self.assertAlmostEqual(low, min(heights), delta=CENTIMETRE)
        self.assertAlmostEqual(high, max(heights), delta=CENTIMETRE)
        # it is sums alone, so no file is kept of it
        self.assertEqual([p.name for p in common.cache_dir().glob("*yrange*")], [])

    def test_the_constants_are_kept_so_another_run_asks_nothing(self):
        # a run with the fit on file and nothing else: not the year it
        # was made from, and no network
        for path in common.cache_dir().glob("om_year_*"):
            path.unlink()
        self.assertEqual([p.name for p in common.cache_dir().iterdir()],
                         [f"om_fit_{om.location_cache_key(43.677, -70.371)}_2025.json"])
        with patch.object(harmonic, "fit", side_effect=AssertionError("fitted again")):
            curve = om.fetch_tides_range_openmeteo(STATION, self.DAY, self.DAY, NEW_YORK)
        self.assertEqual([t for t, _h in curve], [t for t, _h in self.first_curve])
        for (_t, a), (_t2, b) in zip(curve, self.first_curve):
            self.assertAlmostEqual(a, b, places=9)
        self.assertEqual(self.offline.urls, [])

    def test_the_curve_the_turns_and_the_axis_share_one_fit(self):
        # the year is on file but no fit of it
        for path in common.cache_dir().glob("om_fit_*"):
            path.unlink()
        with patch.object(harmonic, "fit", return_value=TRUTH) as fit:
            curve = om.fetch_tides_range_openmeteo(STATION, self.DAY, self.DAY, NEW_YORK)
            turns = om.fetch_hilo_range_openmeteo(STATION, self.DAY, self.DAY, NEW_YORK)
            axis = om.fetch_y_range_openmeteo(STATION, self.DAY, NEW_YORK)
        fit.assert_called_once()
        self.assertEqual(self.offline.urls, [])
        samples, names = fit.call_args.args
        self.assertEqual(len(samples), 365 * 24)
        self.assertEqual(names, om.FIT_NAMES)
        self.assertEqual(len(curve), 241)
        self.assertTrue(turns)
        self.assertLess(axis[0], axis[1])
        # each hour is the instant its stamp names in the answer's offset
        self.assertEqual(samples[0][0], datetime(2025, 1, 1, 4, tzinfo=timezone.utc))
        self.assertAlmostEqual(samples[0][1], TRUTH.height(samples[0][0]), delta=0.005)


class NoFitTests(_OwnCache):
    """Where last year cannot be had, or is too little of a year, the
    model's own hourly window is served as it comes."""

    DAY = date(2026, 8, 17)

    def _marine(self, year):
        """The place's year as given, and a forecast window of three
        days of hours from 16 August 2026."""
        return self._ask(_Marine(year=year, window=_tide_payload(hours=72)))

    def _curve(self):
        return om.fetch_tides_range_openmeteo(STATION, self.DAY, self.DAY, NEW_YORK)

    def _assert_the_models_own_hours(self, curve):
        self.assertEqual(len(curve), 25)
        self.assertEqual({b[0] - a[0] for a, b in zip(curve, curve[1:])}, {timedelta(hours=1)})

    def test_under_300_days_of_hours_are_not_fitted(self):
        year = _year_payload(date(2025, 1, 1), date(2025, 1, 1) + timedelta(days=298))
        marine = self._marine(year)
        with patch.object(harmonic, "fit", side_effect=AssertionError("fitted")):
            self._assert_the_models_own_hours(self._curve())
            turns = om.fetch_hilo_range_openmeteo(STATION, self.DAY, self.DAY, NEW_YORK)
        self.assertEqual(marine.windows_asked, 1)
        # the turns are found by a parabola through the hours either
        # side, so they do not all fall on the hour
        self.assertGreaterEqual(len(turns), 3)
        self.assertTrue(any(t.minute for t, _h, _k in turns))
        self.assertEqual(list(common.cache_dir().glob("om_fit_*")), [])

    def test_300_days_of_hours_are_enough(self):
        year = _year_payload(date(2025, 1, 1), date(2025, 1, 1) + timedelta(days=299))
        marine = self._marine(year)
        with patch.object(harmonic, "fit", return_value=TRUTH) as fit:
            curve = self._curve()
        fit.assert_called_once()
        self.assertEqual(len(curve), 241)
        self.assertEqual(marine.windows_asked, 0)

    def test_hours_the_model_has_none_for_do_not_count_toward_the_300(self):
        # a whole year asked for, and ten weeks of it null
        hole = (datetime(2025, 3, 1, tzinfo=timezone.utc),
                datetime(2025, 5, 10, tzinfo=timezone.utc))
        year = _year_payload(
            date(2025, 1, 1), date(2025, 12, 31),
            height=lambda t: None if hole[0] <= t < hole[1] else TRUTH.height(t))
        self._marine(year)
        with patch.object(harmonic, "fit", side_effect=AssertionError("fitted")):
            self._assert_the_models_own_hours(self._curve())

    def test_a_place_the_model_has_no_sea_for_is_not_fitted(self):
        nulls = _year_payload(date(2025, 1, 1), date(2025, 12, 31), height=lambda t: None)
        window = _payload(["2026-08-17T00:00", "2026-08-17T01:00"], [None, None])
        self._ask(_Marine(year=nulls, window=window))
        with patch.object(harmonic, "fit", side_effect=AssertionError("fitted")):
            self.assertEqual(self._curve(), [])
            self.assertEqual(
                om.fetch_hilo_range_openmeteo(STATION, self.DAY, self.DAY, NEW_YORK), [])
            self.assertIsNone(om.fetch_y_range_openmeteo(STATION, self.DAY, NEW_YORK))

    def test_a_year_out_of_reach_leaves_the_window_and_its_dates(self):
        marine = self._marine(None)
        self._assert_the_models_own_hours(self._curve())
        self.assertEqual(marine.years_asked, [("2025-01-01", "2025-12-31")])
        # a date outside the window is simply absent
        self.assertEqual(om.fetch_tides_range_openmeteo(
            STATION, date(2026, 10, 15), date(2026, 10, 15), NEW_YORK), [])
        low, high = om.fetch_y_range_openmeteo(STATION, self.DAY, NEW_YORK)
        self.assertLess(low, 0)
        self.assertGreater(high, 4)

    def test_a_place_without_its_year_waits_five_minutes_to_ask_again(self):
        clock = [1000.0]
        held = patch.object(om, "time", SimpleNamespace(monotonic=lambda: clock[0]))
        held.start()
        self.addCleanup(held.stop)
        marine = self._marine(None)
        self._curve()
        self.assertEqual(len(marine.years_asked), 1)
        # the turns and the axis ask at once, and the next frame soon after
        clock[0] += 10
        om.fetch_hilo_range_openmeteo(STATION, self.DAY, self.DAY, NEW_YORK)
        self._assert_the_models_own_hours(self._curve())
        self.assertEqual(len(marine.years_asked), 1)
        clock[0] += 300
        self._curve()
        self.assertEqual(len(marine.years_asked), 2)
        # and once the year can be had, the tide is fitted and is not asked for again
        marine.year = _year_payload(date(2025, 1, 1), date(2025, 12, 31))
        clock[0] += 301
        with patch.object(harmonic, "fit", return_value=TRUTH) as fit:
            self.assertEqual(len(self._curve()), 241)
            clock[0] += 3600
            self.assertEqual(len(self._curve()), 241)
        fit.assert_called_once()
        self.assertEqual(len(marine.years_asked), 3)

    def test_a_kept_fit_that_cannot_be_read_is_made_again(self):
        year = _year_payload(date(2025, 1, 1), date(2025, 12, 31))
        self._ask(_Marine(year=year))
        fit_file = (common.cache_dir()
                    / f"om_fit_{om.location_cache_key(43.677, -70.371)}_2025.json")
        for kept in ({"z0": 0.03}, {"constants": [["M2", 1.36]], "z0": 0.03}, [1, 2]):
            with self.subTest(kept=kept), patch.dict(om._tides, clear=True), \
                 patch.object(harmonic, "fit", return_value=TRUTH) as fit:
                om.write_cache(fit_file, kept)
                self.assertEqual(len(self._curve()), 241)
                fit.assert_called_once()
                self.assertEqual(om.read_cache(fit_file, 60)["z0"], 0.03)
                self.assertEqual(len(om.read_cache(fit_file, 60)["constants"]), 5)


class ModeledYearTests(_OwnCache):
    """The model's own heights, a day at a time: the year view's pen."""

    TODAY = date(2026, 10, 1)

    def setUp(self):
        super().setUp()
        self.marine = self._ask(_Marine())

    def _modeled(self, data, year=2026, today=None, station=STATION):
        """The modeled days where the model's answer for the year is *data*."""
        self.marine.year = data
        return om.fetch_modeled_extremes_openmeteo(station, year, today or self.TODAY)

    def test_each_day_has_the_models_lowest_and_highest_in_feet(self):
        times = [f"2026-09-{day}T{hour:02d}:00" for day in (28, 29) for hour in range(24)]
        heights = [round(-1.2 + 0.1 * hour, 2) for hour in range(24)] \
            + [round(1.5 - 0.05 * hour, 2) for hour in range(24)]
        data = _payload(times, heights, tz="Europe/London")
        data["utc_offset_seconds"] = 3600
        days = self._modeled(data)
        self.assertEqual(sorted(days), [date(2026, 9, 28), date(2026, 9, 29)])
        for day, (low, high) in {date(2026, 9, 28): (-1.2, 1.1),
                                 date(2026, 9, 29): (0.35, 1.5)}.items():
            self.assertAlmostEqual(days[day][0], low / 0.3048, places=6)
            self.assertAlmostEqual(days[day][1], high / 0.3048, places=6)
        # the shape the year view takes for a gauge's measurements
        for day, pair in days.items():
            self.assertIs(type(day), date)
            self.assertIsInstance(pair, tuple)
            self.assertEqual(len(pair), 2)

    def test_a_day_is_the_places_own_whatever_offset_the_answer_is_stamped_in(self):
        # Asked for in October, the whole year comes stamped in summer
        # time. In January New York is an hour behind that: the hour
        # stamped 00:00 on the 15th was 23:00 on the 14th there.
        data = _payload(["2026-01-14T12:00", "2026-01-15T00:00", "2026-01-15T01:00",
                         "2026-01-15T12:00"], [0.1, 2.0, 0.2, 0.3])
        days = self._modeled(data)
        self.assertEqual(sorted(days), [date(2026, 1, 14), date(2026, 1, 15)])
        self.assertAlmostEqual(days[date(2026, 1, 14)][1], 2.0 / 0.3048, places=6)
        self.assertAlmostEqual(days[date(2026, 1, 15)][1], 0.3 / 0.3048, places=6)

    def test_only_the_years_days_before_today_are_kept(self):
        data = _payload(["2026-01-01T00:00",    # 23:00 on New Year's Eve in New York
                         "2026-01-01T01:00", "2026-09-30T23:00",
                         "2026-10-01T00:00"],   # today
                        [9.0, 0.1, 0.2, 9.0])
        self.assertEqual(sorted(self._modeled(data)), [date(2026, 1, 1), date(2026, 9, 30)])

    def test_hours_the_model_has_none_for_are_skipped(self):
        data = _payload(["2026-09-28T00:00", "2026-09-28T01:00", "2026-09-28T02:00",
                         "2026-09-29T00:00", "not a time"], [0.4, None, 0.6, None, 0.5])
        days = self._modeled(data)
        self.assertEqual(sorted(days), [date(2026, 9, 28)])
        self.assertAlmostEqual(days[date(2026, 9, 28)][0], 0.4 / 0.3048, places=6)
        self.assertAlmostEqual(days[date(2026, 9, 28)][1], 0.6 / 0.3048, places=6)

    def test_this_year_is_asked_for_through_yesterday_and_a_past_year_whole(self):
        data = _payload(["2026-09-28T00:00"], [0.4])
        self._modeled(data)
        self.assertEqual(self.marine.years_asked, [("2026-01-01", "2026-09-30")])
        self._modeled(data, year=2024)
        self.assertEqual(self.marine.years_asked[1:], [("2024-01-01", "2024-12-31")])

    def test_a_year_with_no_day_behind_it_is_nothing_and_asks_nothing(self):
        data = _payload(["2027-01-01T00:00"], [0.4])
        self.assertEqual(self._modeled(data, year=2027), {})
        self.assertEqual(self._modeled(data, year=2026, today=date(2026, 1, 1)), {})
        self.assertEqual(self.marine.urls, [])

    def test_a_year_that_cannot_be_had_is_nothing_not_an_error(self):
        self.assertEqual(self._modeled(None), {})
        for n, answer in enumerate(({}, {"hourly": None}, {"hourly": {"time": None}},
                                    {"error": True, "reason": "out of range"}, [], [1])):
            with self.subTest(answer=answer):
                # a place of its own each time, so no answer is read from another's file
                self.assertEqual(self._modeled(answer, station=f"om:1{n}.0000,20.0000"), {})
        # and an ID that is not a place at all
        self.assertEqual(self._modeled(_payload(["2026-09-28T00:00"], [0.4]),
                                       station="8418150"), {})

    def test_a_zone_this_machine_does_not_know_is_read_in_utc_days(self):
        for n, tz in enumerate(("Mars/Olympus_Mons", "", None)):
            with self.subTest(tz=tz):
                data = _payload(["2026-03-01T00:30", "2026-03-01T12:00"], [0.4, 0.5], tz=tz)
                data["utc_offset_seconds"] = 3600
                days = self._modeled(data, station=f"om:2{n}.0000,20.0000")
                # 00:30 on 1 March, an hour ahead of UTC, is still February in UTC
                self.assertEqual(sorted(days), [date(2026, 2, 28), date(2026, 3, 1)])

    def test_this_years_hours_are_kept_three_hours(self):
        data = _payload(["2026-09-28T00:00"], [0.4])
        first = self._modeled(data)
        self._aged(2 * 3600)
        self.assertEqual(om.fetch_modeled_extremes_openmeteo(STATION, 2026, self.TODAY), first)
        self.assertEqual(len(self.marine.urls), 1)
        self._aged(4 * 3600)
        om.fetch_modeled_extremes_openmeteo(STATION, 2026, self.TODAY)
        self.assertEqual(len(self.marine.urls), 2)

    def test_a_copy_made_while_the_year_ran_is_not_taken_for_the_finished_year(self):
        """Asked for in October, the year's file stops in September. In
        January it is a day old and the year is over: it is asked for
        again, where it would have stood for all of 2026 for a year."""
        self._modeled(_payload(["2026-09-30T12:00"], [0.4]))
        self._aged(86400)
        whole = _payload(["2026-09-30T12:00", "2026-12-31T23:00"], [0.4, 0.9])
        days = self._modeled(whole, today=date(2027, 1, 5))
        self.assertEqual(self.marine.years_asked,
                         [("2026-01-01", "2026-09-30"), ("2026-01-01", "2026-12-31")])
        self.assertEqual(sorted(days), [date(2026, 9, 30), date(2026, 12, 31)])
        # and the whole year, once had, is kept
        self._aged(300 * 86400)
        self._modeled(whole, today=date(2027, 11, 1))
        self.assertEqual(len(self.marine.urls), 2)

    def test_a_finished_year_is_kept_a_year(self):
        data = _payload(["2025-12-31T12:00"], [0.4])
        first = self._modeled(data, year=2025)
        self._aged(300 * 86400)
        self.assertEqual(om.fetch_modeled_extremes_openmeteo(STATION, 2025, self.TODAY), first)
        self.assertEqual(len(self.marine.urls), 1)
        self._aged(367 * 86400)
        om.fetch_modeled_extremes_openmeteo(STATION, 2025, self.TODAY)
        self.assertEqual(len(self.marine.urls), 2)


class LastYearsPayloadTests(_OwnCache):
    """The model's cell and the place's zone are read from last year's
    answer, which is kept a year, before the forecast window is asked for."""

    def test_coverage_and_the_zone_come_from_last_year_without_the_window(self):
        year = _payload(["2025-06-01T00:00", "2025-12-31T23:00"], [0.4, 0.5])
        marine = self._ask(_Marine(year=year))
        self.assertEqual(om.find_nearest_openmeteo(43.677, -70.371), (STATION, None))
        meta = om.fetch_station_metadata_openmeteo(STATION)
        self.assertEqual((meta["timeZoneCode"], meta["lat"], meta["timezonecorr"]),
                         ("America/New_York", 43.625, -4))
        self.assertEqual(marine.years_asked, [("2025-01-01", "2025-12-31")])
        self.assertEqual(marine.windows_asked, 0)

    def test_a_last_year_of_nulls_falls_to_the_forecast_window(self):
        year = _payload(["2025-06-01T00:00", "2025-06-01T01:00"], [None, None])
        marine = self._ask(_Marine(year=year, window=_tide_payload()))
        self.assertEqual(om.find_nearest_openmeteo(43.677, -70.371), (STATION, None))
        self.assertEqual(marine.windows_asked, 1)

    def test_nulls_in_both_are_no_coverage(self):
        nulls = _payload(["2025-06-01T00:00", "2025-06-01T01:00"], [None, None])
        self._ask(_Marine(year=nulls, window=nulls))
        self.assertEqual(om.find_nearest_openmeteo(39.0, -98.0), (None, None))


if __name__ == "__main__":
    unittest.main()
