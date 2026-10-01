import json
import math
import os
import tempfile
import time
import unittest
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

from linecast import _http
from linecast.tides import common
from linecast.tides import noaa
from linecast._cache import location_cache_key


class _PrivateCache(unittest.TestCase):
    """A cache directory of the test's own, for what a fetch leaves in it."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        env = patch.dict(os.environ, {"LINECAST_CACHE_DIR": tmp.name})
        env.start()
        self.addCleanup(env.stop)

    @staticmethod
    def expired(path, content):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(content))
        then = time.time() - 60 * 86400
        os.utime(path, (then, then))


class TidesRangeTests(unittest.TestCase):
    MARCH = [["2026-03-30 23:54", 1.2], ["2026-03-31 00:00", 0.8],
             ["2026-03-31 23:54", 1.0]]
    APRIL = [["2026-04-01 00:00", 0.9], ["2026-04-02 00:00", 1.1]]

    def _fake_month(self, station_id, first, interval):
        self.assertEqual(station_id, "123")
        self.assertEqual(interval, "6")
        return {date(2026, 3, 1): self.MARCH, date(2026, 4, 1): self.APRIL}[first]

    def test_range_spanning_months_asks_once_per_month(self):
        with patch.object(noaa, "fetch_month", side_effect=self._fake_month) as fm:
            points = noaa.fetch_tides_range(
                "123", date(2026, 3, 31), date(2026, 4, 1), station_tz=None)

        self.assertEqual([c.args[1] for c in fm.call_args_list],
                         [date(2026, 3, 1), date(2026, 4, 1)])
        # Trimmed to the requested dates, in order, as datetimes
        self.assertEqual(points, [
            (datetime(2026, 3, 31, 0, 0), 0.8),
            (datetime(2026, 3, 31, 23, 54), 1.0),
            (datetime(2026, 4, 1, 0, 0), 0.9),
        ])

    def test_range_within_one_month_is_one_chunk(self):
        with patch.object(noaa, "fetch_month", side_effect=self._fake_month) as fm:
            points = noaa.fetch_tides_range(
                "123", date(2026, 3, 5), date(2026, 3, 20), station_tz=None)
        self.assertEqual(fm.call_count, 1)
        self.assertEqual(points, [])

    def test_range_applies_station_timezone(self):
        from datetime import timezone, timedelta
        tz = timezone(timedelta(hours=-4))
        with patch.object(noaa, "fetch_month", side_effect=self._fake_month):
            points = noaa.fetch_tides_range(
                "123", date(2026, 4, 1), date(2026, 4, 1), station_tz=tz)
        self.assertEqual(points, [(datetime(2026, 4, 1, 0, 0, tzinfo=tz), 0.9)])

    def test_hilo_range_keeps_type(self):
        rows = [["2026-03-05 05:38", 8.0, "H"], ["2026-03-05 11:32", 1.8, "L"],
                ["2026-03-06 06:10", 8.2, "H"]]
        with patch.object(noaa, "fetch_month", return_value=rows) as fm:
            points = noaa.fetch_hilo_range(
                "123", date(2026, 3, 5), date(2026, 3, 5), station_tz=None)
        self.assertEqual(fm.call_args.args[2], "hilo")
        self.assertEqual(points, [(datetime(2026, 3, 5, 5, 38), 8.0, "H"),
                                  (datetime(2026, 3, 5, 11, 32), 1.8, "L")])

    def test_failed_month_yields_no_points(self):
        with patch.object(noaa, "fetch_month", return_value=None):
            self.assertEqual(noaa.fetch_tides_range(
                "123", date(2026, 3, 5), date(2026, 3, 6), station_tz=None), [])


class MonthChunkTests(unittest.TestCase):
    def test_month_is_requested_whole_and_cached_by_month(self):
        payload = {"predictions": [
            {"t": "2026-02-01 00:00", "v": "1.5"},
            {"t": "2026-02-28 23:54", "v": "2.5"},
            {"t": "bad", "v": "9"},
        ]}
        with patch.object(_http, "read_cache", return_value=None), \
             patch.object(_http, "fetch_json", return_value=payload) as fj, \
             patch.object(_http, "write_cache") as wc:
            rows = noaa.fetch_month("8418150", date(2026, 2, 1), "6")

        cache_file, written = wc.call_args.args
        url = fj.call_args.args[0]
        self.assertEqual(cache_file.name, "pred_8418150_202602.json")
        self.assertIn("begin_date=20260201&end_date=20260228", url)
        self.assertIn("interval=6", url)
        self.assertEqual(rows, [["2026-02-01 00:00", 1.5], ["2026-02-28 23:54", 2.5]])
        self.assertEqual(written, rows)

    def test_hilo_month_cache_name_and_rows(self):
        payload = {"predictions": [
            {"t": "2026-12-31 20:28", "v": "10.1", "type": "H"},
        ]}
        with patch.object(_http, "read_cache", return_value=None), \
             patch.object(_http, "fetch_json", return_value=payload) as fj, \
             patch.object(_http, "write_cache") as wc:
            rows = noaa.fetch_month("8418150", date(2026, 12, 1), "hilo")
        cache_file, url = wc.call_args.args[0], fj.call_args.args[0]
        self.assertEqual(cache_file.name, "hilo_8418150_202612.json")
        self.assertIn("begin_date=20261201&end_date=20261231", url)
        self.assertEqual(rows, [["2026-12-31 20:28", 10.1, "H"]])

    def test_cached_rows_are_returned_as_is(self):
        cached = [["2026-02-01 00:00", 1.5]]
        with patch.object(_http, "read_cache", return_value=cached), \
             patch.object(_http, "write_cache") as wc:
            self.assertEqual(noaa.fetch_month("8418150", date(2026, 2, 1), "6"), cached)
        wc.assert_not_called()


    def test_two_threads_asking_for_one_month_make_one_request(self):
        # a subordinate station's curve and its extremes both want the
        # hi/lo month, and tides/stations.py asks for them on two threads at once
        import os
        import tempfile
        import threading
        import time
        from linecast import _http
        calls = []
        payload = {"predictions": [
            {"t": "2026-02-01 00:00", "v": "1.5", "type": "H"}]}

        def slow_fetch(url, headers=None, timeout=10):
            calls.append(url)
            time.sleep(0.1)  # long enough for the second thread to arrive
            return payload

        results = []
        with tempfile.TemporaryDirectory() as tmp, \
             patch.dict(os.environ, {"LINECAST_CACHE_DIR": tmp}), \
             patch.object(_http, "fetch_json", slow_fetch):
            def ask():
                results.append(noaa.fetch_month("8410875", date(2026, 2, 1), "hilo"))
            ts = [threading.Thread(target=ask) for _ in range(2)]
            for t in ts:
                t.start()
            for t in ts:
                t.join()
        self.assertEqual(len(calls), 1, calls)
        self.assertEqual(results, [[["2026-02-01 00:00", 1.5, "H"]]] * 2)


class StationLookupTests(unittest.TestCase):
    def test_find_nearest_station_uses_location_scoped_cache(self):
        legacy_cache_file = common.cache_dir() / "station.json"
        stations = [
            {"id": "111", "name": "First Harbor", "lat": 40.0, "lng": -70.0},
            {"id": "222", "name": "Second Harbor", "lat": 47.61, "lng": -122.33},
        ]
        calls = []

        def fake_read_cache(path, max_age):
            calls.append((path, max_age))
            if path == legacy_cache_file:
                return {"id": "111", "name": "First Harbor"}
            return None

        with patch.object(common, "read_cache", side_effect=fake_read_cache), \
             patch.object(common, "read_stale", return_value=None), \
             patch.object(noaa, "fetch_all_stations_noaa", return_value=stations), \
             patch.object(common, "write_cache") as write_cache:
            station_id, station_name = noaa.find_nearest_station(47.61, -122.33)

        self.assertEqual((station_id, station_name), ("222", "Second Harbor"))
        self.assertEqual(calls[0][1], common.NEAREST_STATION_CACHE_MAX_AGE)
        expected = f"station_{location_cache_key(47.61, -122.33)}.json"
        self.assertEqual(calls[0][0].name, expected)
        self.assertEqual(write_cache.call_args.args[0].name, expected)

    def test_find_nearest_station_skips_subordinate_stations(self):
        # Westbrook, ME: Fore River (subordinate) is nearer than Portland
        # (reference), but subordinate stations can't serve the 6-minute
        # series, so the reference station must win.
        stations = [
            {"id": "8418268", "name": "Fore River", "type": "S",
             "lat": "43.64", "lng": "-70.30"},
            {"id": "8418150", "name": "PORTLAND", "type": "R",
             "lat": "43.6567", "lng": "-70.2467"},
        ]
        with patch.object(common, "read_cache", return_value=None), \
             patch.object(noaa, "fetch_all_stations_noaa", return_value=stations), \
             patch.object(common, "write_cache"):
            station_id, station_name = noaa.find_nearest_station(43.68, -70.36)

        self.assertEqual((station_id, station_name), ("8418150", "PORTLAND"))

    def test_find_nearest_station_tolerates_missing_type(self):
        stations = [
            {"id": "1", "name": "Typeless", "lat": "43.68", "lng": "-70.36"},
        ]
        with patch.object(common, "read_cache", return_value=None), \
             patch.object(noaa, "fetch_all_stations_noaa", return_value=stations), \
             patch.object(common, "write_cache"):
            station_id, _ = noaa.find_nearest_station(43.68, -70.36)

        self.assertEqual(station_id, "1")

    def test_find_nearest_station_uses_stale_cache_on_fetch_error(self):
        lat, lng = 47.61, -122.33
        cache_file = common.cache_dir() / f"station_{location_cache_key(lat, lng)}.json"
        stale = {"id": "222", "name": "Second Harbor"}

        def fake_read_stale(path):
            self.assertEqual(path, cache_file)
            return stale

        with patch.object(common, "read_cache", return_value=None), \
             patch.object(noaa, "fetch_all_stations_noaa", return_value=[]), \
             patch.object(common, "read_stale", side_effect=fake_read_stale), \
             patch.object(common, "write_cache") as write_cache:
            station_id, station_name = noaa.find_nearest_station(lat, lng)

        self.assertEqual((station_id, station_name), ("222", "Second Harbor"))
        write_cache.assert_not_called()


class StationListTests(_PrivateCache):
    def setUp(self):
        super().setUp()
        noaa._stations_memo = None

    def tearDown(self):
        noaa._stations_memo = None

    def test_an_answer_without_stations_is_not_kept_as_the_list(self):
        # kept, it would be fresh for a month, and every lookup in that
        # month would find no station anywhere
        cache_file = common.cache_dir() / "all_stations.json"
        with patch.object(_http, "fetch_json", return_value={"errorMsg": "down"}):
            self.assertEqual(noaa.fetch_all_stations_noaa(), [])
        self.assertFalse(cache_file.exists())
        self.assertIsNone(noaa._stations_memo)

    def test_nor_written_over_the_last_list(self):
        cache_file = common.cache_dir() / "all_stations.json"
        stations = [{"id": "8418150", "name": "Portland"}]
        self.expired(cache_file, stations)
        with patch.object(_http, "fetch_json", return_value={"errorMsg": "down"}):
            self.assertEqual(noaa.fetch_all_stations_noaa(), stations)
        self.assertEqual(json.loads(cache_file.read_text()), stations)


class SubordinateStationTests(unittest.TestCase):
    STATIONS = [
        {"id": "8418268", "name": "Fore River", "type": "S"},
        {"id": "8418150", "name": "PORTLAND", "type": "R"},
    ]
    HILO = [
        (datetime(2026, 8, 20, 5, 38), 8.0, "H"),
        (datetime(2026, 8, 20, 11, 32), 1.8, "L"),
    ]

    def test_subordinate_range_skips_six_minute_fetch(self):
        with patch.object(noaa, "fetch_all_stations_noaa", return_value=self.STATIONS), \
             patch.object(noaa, "fetch_tides_range",
                          side_effect=AssertionError("must not ask for 6-min")), \
             patch.object(noaa, "fetch_hilo_range", return_value=self.HILO) as fh:
            preds = noaa.fetch_tides_range_with_fallback(
                "8418268", date(2026, 8, 20), date(2026, 8, 20), None)

        self.assertTrue(preds)
        self.assertEqual(preds[0], (datetime(2026, 8, 20, 5, 38), 8.0))
        self.assertEqual(preds[-1], (datetime(2026, 8, 20, 11, 32), 1.8))
        # A day of extremes either side anchors the curve at the window edges
        self.assertEqual(fh.call_args.args[1:3], (date(2026, 8, 19), date(2026, 8, 21)))

    def test_reference_station_uses_real_series(self):
        real = [(datetime(2026, 8, 20, 0, 0), 4.2)]
        with patch.object(noaa, "fetch_all_stations_noaa", return_value=self.STATIONS), \
             patch.object(noaa, "fetch_tides_range", return_value=real), \
             patch.object(noaa, "fetch_hilo_range",
                          side_effect=AssertionError("no fallback needed")):
            preds = noaa.fetch_tides_range_with_fallback(
                "8418150", date(2026, 8, 20), date(2026, 8, 20), None)
        self.assertEqual(preds, real)

    def test_reference_station_without_a_series_is_synthesized(self):
        with patch.object(noaa, "fetch_all_stations_noaa", return_value=self.STATIONS), \
             patch.object(noaa, "fetch_tides_range", return_value=[]), \
             patch.object(noaa, "fetch_hilo_range", return_value=self.HILO):
            preds = noaa.fetch_tides_range_with_fallback(
                "8418150", date(2026, 8, 20), date(2026, 8, 20), None)
        self.assertEqual(preds[0], (datetime(2026, 8, 20, 5, 38), 8.0))


class SynthesisTests(unittest.TestCase):
    def test_cosine_between_two_extremes(self):
        high = (datetime(2026, 8, 20, 6, 0), 10.0, "H")
        low = (datetime(2026, 8, 20, 12, 0), 2.0, "L")
        curve = noaa.synthesize_tides_from_hilo([high, low])

        self.assertEqual(curve[0], (datetime(2026, 8, 20, 6, 0), 10.0))
        self.assertEqual(curve[-1], (datetime(2026, 8, 20, 12, 0), 2.0))
        # Midpoint of a cosine half-cycle is the mean of the extremes
        mid = dict(curve)[datetime(2026, 8, 20, 9, 0)]
        self.assertAlmostEqual(mid, 6.0)
        # Monotonic on a falling limb
        heights = [h for _, h in curve]
        self.assertEqual(heights, sorted(heights, reverse=True))
        # 6-minute sampling over 6 hours: 60 steps + the final extreme
        self.assertEqual(len(curve), 61)

    def test_gaps_and_degenerate_inputs(self):
        lone = [(datetime(2026, 8, 20, 6, 0), 10.0, "H")]
        self.assertEqual(noaa.synthesize_tides_from_hilo(lone), [])
        self.assertEqual(noaa.synthesize_tides_from_hilo([]), [])
        # A 20-hour gap is not a tide cycle; nothing is invented across it
        far = [(datetime(2026, 8, 20, 0, 0), 10.0, "H"),
               (datetime(2026, 8, 20, 20, 0), 2.0, "L")]
        self.assertEqual(noaa.synthesize_tides_from_hilo(far), [])

    def test_unsorted_input_is_sorted_first(self):
        low = (datetime(2026, 8, 20, 12, 0), 2.0, "L")
        high = (datetime(2026, 8, 20, 6, 0), 10.0, "H")
        curve = noaa.synthesize_tides_from_hilo([low, high])
        self.assertEqual(curve[0][0], datetime(2026, 8, 20, 6, 0))


class PredictionErrorTests(_PrivateCache):
    # NOAA reports "no data" as a 200 JSON error body; it must not be
    # served as fresh cache for the next 24 hours.
    ERROR = {"error": {"message": "No Predictions data was found."}}

    def test_error_payload_is_not_cached(self):
        cache_file = common.cache_dir() / "pred_1_202602.json"
        with patch.object(_http, "fetch_json", return_value=self.ERROR):
            rows = noaa._fetch_prediction_rows(
                cache_file, "http://x", row_builder=noaa._build_tide_row)
        self.assertIsNone(rows)
        self.assertFalse(cache_file.exists())

    def test_error_payload_leaves_the_last_rows_standing(self):
        cache_file = common.cache_dir() / "pred_1_202602.json"
        cached = [["2026-02-01 00:00", 1.5]]
        self.expired(cache_file, cached)
        with patch.object(_http, "fetch_json", return_value=self.ERROR):
            rows = noaa._fetch_prediction_rows(
                cache_file, "http://x", row_builder=noaa._build_tide_row)
        self.assertEqual(rows, cached)
        self.assertEqual(json.loads(cache_file.read_text()), cached)


class YRangeTests(unittest.TestCase):
    def test_consecutive_days_share_one_cache_file(self):
        payload = {"predictions": [{"t": "2026-07-01 00:30", "v": "9.7", "type": "H"},
                                   {"t": "2026-07-01 06:40", "v": "-0.4", "type": "L"}]}
        seen = []

        def fake_read_cache(path, max_age):
            seen.append(path.name)
            return None

        with patch.object(common, "read_cache", side_effect=fake_read_cache), \
             patch.object(noaa, "fetch_json", return_value=payload) as fj, \
             patch.object(common, "write_cache"):
            for day in (date(2026, 8, 23), date(2026, 8, 24)):
                self.assertEqual(noaa.fetch_y_range("8418150", day), (-0.4, 9.7))

        self.assertEqual(seen, ["yrange_8418150_202608.json"] * 2)
        self.assertIn("begin_date=20260701&end_date=20260930", fj.call_args.args[0])


class MetadataTests(unittest.TestCase):
    def test_fetch_station_metadata_normalizes_and_caches(self):
        payload = {
            "stations": [
                {
                    "id": "9414290",
                    "name": "San Francisco",
                    "state": "CA",
                    "lat": "37.8063",
                    "lng": "-122.4659",
                    "timezone": "pst",
                    "timezonecorr": -8,
                    "observedst": True,
                    "details": {},
                }
            ]
        }

        with patch.object(_http, "read_cache", return_value=None), \
             patch.object(_http, "fetch_json", return_value=payload), \
             patch.object(_http, "write_cache") as write_cache:
            meta = noaa.fetch_station_metadata_noaa("9414290")

        self.assertIsNotNone(meta)
        self.assertEqual(meta["id"], "9414290")
        self.assertEqual(meta["name"], "San Francisco")
        self.assertEqual(meta["state"], "CA")
        self.assertEqual(meta["timezone_abbr"], "PST")
        self.assertEqual(meta["timezonecorr"], -8)
        self.assertTrue(meta["observedst"])
        cache_file, written = write_cache.call_args.args
        self.assertEqual(cache_file.name, "station_meta_9414290.json")
        self.assertEqual(written, meta)

    def test_a_station_mdapi_does_not_know_is_no_metadata(self):
        with patch.object(_http, "read_cache", return_value=None), \
             patch.object(_http, "read_stale", return_value=None), \
             patch.object(_http, "fetch_json", return_value={"stations": []}), \
             patch.object(_http, "write_cache") as write_cache:
            self.assertIsNone(noaa.fetch_station_metadata_noaa("0000000"))
        write_cache.assert_not_called()

    def test_a_subordinate_station_keeps_its_reference_stations_clock(self):
        # mdapi gives Back Cove no zone and no summer time; NOAA's
        # local times for it are Portland's EDT all the same
        cached = {
            "8418175": {"id": "8418175", "name": "Back Cove", "state": "ME",
                        "timezone_abbr": "", "timezonecorr": -5, "observedst": False},
            "8418150": {"id": "8418150", "name": "Portland", "state": "ME",
                        "timezone_abbr": "EST", "timezonecorr": -5, "observedst": True},
            "TEC5647": {"id": "TEC5647", "name": "Belize City", "state": "",
                        "timezone_abbr": "", "timezonecorr": -6, "observedst": False},
        }
        stations = [
            {"id": "8418175", "type": "S", "reference_id": "8418150"},
            {"id": "8418150", "type": "R", "reference_id": ""},
            {"id": "TEC5647", "type": "S", "reference_id": "8418150"},
        ]
        with patch.object(noaa, "fetch_json_cached",
                          side_effect=lambda path, *a, **k: cached[path.stem.split("_")[-1]]), \
             patch.object(noaa, "fetch_all_stations_noaa", return_value=stations):
            back_cove = noaa.fetch_station_metadata_noaa("8418175")
            belize = noaa.fetch_station_metadata_noaa("TEC5647")

        self.assertEqual(back_cove["timezone_abbr"], "EST")
        self.assertTrue(back_cove["observedst"])
        from linecast.tides.stations import _station_tzinfo
        self.assertEqual(_station_tzinfo(back_cove).key, "America/New_York")
        # a reference on another standard offset lends no clock
        self.assertEqual(belize["timezone_abbr"], "")
        self.assertEqual(_station_tzinfo(belize).utcoffset(None).total_seconds(), -6 * 3600)


# A tide for the gauge tests: a turn every 6 h 12 min from half past
# midnight on New Year's Day, the lows and highs each of two heights, as
# a tide with a daily inequality has.  The gauge runs LATE behind the
# tables and OVER feet above them all year.
TURN_EVERY = timedelta(minutes=372)
TURNS = (("L", 0.2), ("H", 9.0), ("L", 2.5), ("H", 11.0))
LATE = timedelta(minutes=12)
OVER = 0.4


def _predicted(year):
    """[(datetime, feet, "H"/"L")]: the year's predicted turns."""
    moment, k, turns = datetime(year, 1, 1, 0, 30), 0, []
    while moment.year == year:
        kind, feet = TURNS[k % 4]
        turns.append((moment, feet, kind))
        moment, k = moment + TURN_EVERY, k + 1
    return turns


def _predicted_range(year):
    """{day: (lowest, highest)} of the predicted turns."""
    days = {}
    for moment, feet, _kind in _predicted(year):
        lo, hi = days.get(moment.date(), (feet, feet))
        days[moment.date()] = (min(lo, feet), max(hi, feet))
    return days


def _stamp(moment):
    return moment.strftime("%Y-%m-%d %H:%M")


def _verified(year, through):
    """The gauge's highs and lows up to *through*, as NOAA verifies them."""
    return [(_stamp(moment + LATE), f"{feet + OVER:.3f}")
            for moment, feet, _kind in _predicted(year) if moment + LATE <= through]


def _levels(year, begin, end):
    """The gauge's six-minute levels from *begin* up to *end*: half a
    cosine from each turn to the next."""
    turns = [(moment + LATE, feet + OVER) for moment, feet, _kind in _predicted(year)]
    rows, k, moment = [], 0, begin
    while moment < end:
        while k + 2 < len(turns) and turns[k + 1][0] <= moment:
            k += 1
        (t1, h1), (t2, h2) = turns[k], turns[k + 1]
        frac = min(1.0, max(0.0, (moment - t1) / (t2 - t1)))
        rows.append((_stamp(moment), f"{h1 + (h2 - h1) * (1 - math.cos(math.pi * frac)) / 2:.3f}"))
        moment += timedelta(minutes=6)
    return rows


class _Datagetter:
    """NOAA's datagetter for one gauge: it answers each product with the
    rows it holds inside the dates asked, or with the error it gives
    when it holds none, and keeps what it was asked of the gauge.  The
    tide tables it is also asked for are kept apart, in `tables`: the
    year view has them before it asks what the gauge measured.

    Rows are as NOAA writes them: a verified high or low is
    {"t": "2026-08-30 04:00", "v": "9.871", "ty": "HH", "f": "0,0,0,0"},
    a preliminary six-minute level {"t": …, "v": "5.108", "s": "0.023",
    "f": "1,0,0,0", "q": "p"}, a predicted turn {"t": …, "v": "9.000",
    "type": "H"}.
    """

    NOTHING = {"error": {"message": "No data was found. This product may not be offered "
                                    "at this station at the requested time."}}

    def __init__(self, high_low=(), water_level=()):
        self.rows = {"high_low": [{"t": t, "v": v, "ty": "H ", "f": "0,0,0,0"}
                                  for t, v in high_low],
                     "water_level": [{"t": t, "v": v, "s": "0.023", "f": "1,0,0,0", "q": "p"}
                                     for t, v in water_level]}
        self.urls = []
        self.tables = []

    def __call__(self, url, headers=None, timeout=10):
        product, begin, end = self._asked(url)
        lo, hi = (f"{d[:4]}-{d[4:6]}-{d[6:]}" for d in (begin, end))
        if product == "predictions":
            self.tables.append(url)
            return {"predictions": [
                {"t": _stamp(moment), "v": f"{feet:.3f}", "type": kind}
                for moment, feet, kind in _predicted(int(begin[:4]))
                if lo <= _stamp(moment)[:10] <= hi]}
        self.urls.append(url)
        data = [row for row in self.rows[product] if lo <= row["t"][:10] <= hi]
        if not data:
            return self.NOTHING
        return {"metadata": {"id": "8418150", "name": "Portland", "lat": "43.6581",
                             "lon": "-70.2442"}, "data": data}

    @staticmethod
    def _asked(url):
        from urllib.parse import parse_qs, urlsplit
        query = {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}
        return query["product"], query["begin_date"], query["end_date"]

    @property
    def asked(self):
        """(product, first day, last day) of each request of the gauge, in order."""
        return [self._asked(url) for url in self.urls]


class ObservedExtremesTests(_PrivateCache):
    """A year of what the gauge measured: NOAA's verified highs and lows
    as far as they reach, then the preliminary levels up to yesterday,
    both read at the turns the tables predict."""

    TODAY = date(2026, 10, 1)
    # Verified through August, which NOAA ends at midnight in Greenwich:
    # eight in the evening on the 31st, with that day's last low still
    # to come.  The preliminary series holds the verified days too.
    VERIFIED = _verified(2026, datetime(2026, 8, 31, 20))
    PRELIMINARY = _levels(2026, datetime(2026, 8, 1), datetime(2027, 1, 1))

    def _observed(self, gauge, year=2026, today=None):
        with patch.object(_http, "fetch_json", side_effect=gauge):
            return noaa.fetch_observed_extremes("8418150", year, today or self.TODAY)

    @staticmethod
    def _aged(seconds, *names):
        for name in names:
            path = common.cache_dir() / name
            then = time.time() - seconds
            os.utime(path, (then, then))

    @staticmethod
    def _files():
        return sorted(p.name for p in common.cache_dir().glob("obs_*"))

    def assert_over_the_tables(self, days, first, last):
        """Every day from *first* through *last* reads OVER feet above
        its predicted range, low water and high."""
        predicted = _predicted_range(first.year)
        for n in range((last - first).days + 1):
            day = first + timedelta(days=n)
            self.assertIn(day, days)
            for measured, table in zip(days[day], predicted[day]):
                self.assertAlmostEqual(measured, table + OVER, places=3, msg=str(day))
        self.assertEqual(len(days), (last - first).days + 1)

    def test_the_verified_turns_and_the_preliminary_levels_make_one_year(self):
        gauge = _Datagetter(self.VERIFIED, self.PRELIMINARY)
        days = self._observed(gauge)
        self.assert_over_the_tables(days, date(2026, 1, 1), date(2026, 9, 30))
        # the year in one request, and the weeks after in another, which
        # begins on the last verified day: its evening is not verified yet
        self.assertEqual(gauge.asked, [("high_low", "20260101", "20260930"),
                                       ("water_level", "20260831", "20260930")])

    def test_a_turn_measured_past_midnight_counts_for_the_day_it_was_predicted_on(self):
        # The tables put the higher high water at 23:54 on 7 January and
        # the gauge saw it at 00:06 on the 8th, a day whose own high is
        # the lower one.  Read by the gauge's dates the 7th would fall
        # two feet short of its prediction and the 8th pass it by two.
        late = [(m, feet) for m, feet, _kind in _predicted(2026)
                if (m + LATE).date() != m.date()]
        self.assertEqual(late[0], (datetime(2026, 1, 7, 23, 54), 11.0))
        self.assertEqual(_predicted_range(2026)[date(2026, 1, 8)][1], 9.0)
        days = self._observed(_Datagetter(self.VERIFIED, self.PRELIMINARY))
        self.assertAlmostEqual(days[date(2026, 1, 7)][1], 11.0 + OVER, places=3)
        self.assertAlmostEqual(days[date(2026, 1, 8)][1], 9.0 + OVER, places=3)

    def test_the_water_at_midnight_is_not_a_days_high_or_low(self):
        # 13 September has one high water, the lower of the two, at
        # 12:18.  At midnight the higher one of the evening before has
        # only begun to ebb, two feet above it, and the next is nearly
        # in as the day ends.  The 5th is the same the other way up:
        # one low water, and midnight below it.
        samples = dict(self.PRELIMINARY)
        self.assertGreater(float(samples["2026-09-13 00:00"]), 9.0 + OVER + 1.9)
        self.assertLess(float(samples["2026-09-05 00:00"]), 2.5 + OVER - 1.9)
        days = self._observed(_Datagetter(self.VERIFIED, self.PRELIMINARY))
        self.assertAlmostEqual(days[date(2026, 9, 13)][1], 9.0 + OVER, places=3)
        self.assertAlmostEqual(days[date(2026, 9, 5)][0], 2.5 + OVER, places=3)

    def test_a_hole_around_a_turn_leaves_the_day_out(self):
        # 10 September 03:06 to 03:42: seven readings, and a turn may be
        # in the hole.  Six gone are read across.
        def without(first, last):
            return [row for row in self.PRELIMINARY
                    if not f"2026-09-10 {first}" <= row[0] <= f"2026-09-10 {last}"]

        days = self._observed(_Datagetter(self.VERIFIED, without("03:06", "03:42")))
        self.assertNotIn(date(2026, 9, 10), days)
        self.assertIn(date(2026, 9, 9), days)
        self.assertIn(date(2026, 9, 11), days)
        with tempfile.TemporaryDirectory() as tmp, \
             patch.dict(os.environ, {"LINECAST_CACHE_DIR": tmp}):
            days = self._observed(_Datagetter(self.VERIFIED, without("03:06", "03:36")))
        self.assertIn(date(2026, 9, 10), days)

    def test_the_levels_are_asked_for_in_feet_above_mllw_on_the_stations_clock(self):
        gauge = _Datagetter(self.VERIFIED, self.PRELIMINARY)
        self._observed(gauge)
        for url in gauge.urls:
            self.assertIn("station=8418150", url)
            self.assertIn("datum=MLLW", url)
            self.assertIn("units=english", url)
            self.assertIn("time_zone=lst_ldt", url)

    def test_a_long_wait_for_verification_is_filled_31_days_at_a_time(self):
        gauge = _Datagetter(_verified(2026, datetime(2026, 7, 15, 20)),
                            _levels(2026, datetime(2026, 7, 1), datetime(2026, 10, 1)))
        days = self._observed(gauge)
        self.assertEqual(gauge.asked[1:], [("water_level", "20260715", "20260814"),
                                           ("water_level", "20260815", "20260914"),
                                           ("water_level", "20260915", "20260930")])
        self.assert_over_the_tables(days, date(2026, 1, 1), date(2026, 9, 30))

    def test_a_finished_year_is_asked_for_whole_and_needs_no_preliminary_levels(self):
        gauge = _Datagetter(_verified(2025, datetime(2026, 1, 1)))
        days = self._observed(gauge, year=2025)
        self.assertEqual(gauge.asked, [("high_low", "20250101", "20251231")])
        self.assert_over_the_tables(days, date(2025, 1, 1), date(2025, 12, 31))

    def test_the_year_stops_at_yesterday(self):
        # 2 January: the year so far is one day
        gauge = _Datagetter(water_level=_levels(2026, datetime(2026, 1, 1),
                                                datetime(2026, 1, 3)))
        days = self._observed(gauge, today=date(2026, 1, 2))
        self.assertEqual(gauge.asked, [("high_low", "20260101", "20260101"),
                                       ("water_level", "20260101", "20260101")])
        self.assert_over_the_tables(days, date(2026, 1, 1), date(2026, 1, 1))

    def test_a_year_with_no_day_behind_it_asks_nothing(self):
        gauge = _Datagetter(self.VERIFIED, self.PRELIMINARY)
        # New Year's Day, and a year not yet begun
        self.assertEqual(self._observed(gauge, year=2026, today=date(2026, 1, 1)), {})
        self.assertEqual(self._observed(gauge, year=2027), {})
        self.assertEqual(gauge.urls + gauge.tables, [])

    def test_a_station_without_a_gauge_answers_with_nothing(self):
        gauge = _Datagetter()
        self.assertEqual(self._observed(gauge), {})
        # with no verified day to start from, only the last weeks are
        # looked at, not the whole year a month at a time
        self.assertEqual(gauge.asked, [("high_low", "20260101", "20260930"),
                                       ("water_level", "20260816", "20260915"),
                                       ("water_level", "20260916", "20260930")])

    def test_no_gauge_is_an_answer_that_is_kept(self):
        gauge = _Datagetter()
        self._observed(gauge)
        asked = len(gauge.urls)
        self.assertEqual(self._observed(gauge), {})
        self.assertEqual(len(gauge.urls), asked)

    def test_noaa_out_of_reach_is_no_measurements_not_an_error(self):
        with patch.object(_http, "fetch_json", side_effect=OSError("network down")):
            self.assertEqual(noaa.fetch_observed_extremes("8418150", 2026, self.TODAY), {})
        # and nothing was kept of the failure: the next run asks again
        gauge = _Datagetter(self.VERIFIED, self.PRELIMINARY)
        self.assertEqual(len(self._observed(gauge)), 273)

    def test_measurements_without_the_tables_are_not_drawn(self):
        gauge = _Datagetter(self.VERIFIED, self.PRELIMINARY)

        def no_tables(url, headers=None, timeout=10):
            if "product=predictions" in url:
                raise OSError("network down")
            return gauge(url, headers, timeout)

        with patch.object(_http, "fetch_json", side_effect=no_tables):
            self.assertEqual(noaa.fetch_observed_extremes("8418150", 2026, self.TODAY), {})

    def test_a_reading_that_cannot_be_read_is_left_out(self):
        bad = {"2026-09-10 05:00": "",          # a sample the gauge missed
               "2026-09-10 05:06": "n/a"}
        levels = [(t, bad.get(t, v)) for t, v in self.PRELIMINARY] + [("not a time", "30.0")]
        gauge = _Datagetter(self.VERIFIED, levels)
        gauge.rows["water_level"].append({"t": "2026-09-10 05:12"})
        days = self._observed(gauge)
        self.assert_over_the_tables(days, date(2026, 1, 1), date(2026, 9, 30))

    def test_an_answer_of_another_shape_is_no_measurements(self):
        for answer in ({"data": None}, {"metadata": None, "data": []}, {}):
            with self.subTest(answer=answer), tempfile.TemporaryDirectory() as tmp, \
                 patch.dict(os.environ, {"LINECAST_CACHE_DIR": tmp}), \
                 patch.object(_http, "fetch_json", return_value=answer):
                self.assertEqual(noaa.fetch_observed_extremes("8418150", 2026, self.TODAY), {})

    def test_this_years_turns_are_kept_a_day_and_its_levels_three_hours(self):
        gauge = _Datagetter(self.VERIFIED, self.PRELIMINARY)
        first = self._observed(gauge)
        self.assertEqual(len(gauge.urls), 2)
        names = ("obs_hl_8418150_2026.json", "obs_wl_8418150_20260831.json")
        self.assertEqual(self._files(), sorted(names))

        self._aged(2 * 3600, *names)
        self.assertEqual(self._observed(gauge), first)
        self.assertEqual(len(gauge.urls), 2)

        self._aged(4 * 3600, *names)
        self.assertEqual(self._observed(gauge), first)
        self.assertEqual([product for product, _lo, _hi in gauge.asked[2:]], ["water_level"])

        self._aged(25 * 3600, *names)
        self._observed(gauge)
        self.assertEqual([product for product, _lo, _hi in gauge.asked[3:]],
                         ["high_low", "water_level"])

    def test_a_past_year_is_kept_a_month(self):
        gauge = _Datagetter(_verified(2025, datetime(2026, 1, 1)))
        first = self._observed(gauge, year=2025)
        self._aged(20 * 86400, "obs_hl_8418150_2025.json")
        self.assertEqual(self._observed(gauge, year=2025), first)
        self.assertEqual(len(gauge.urls), 1)
        self._aged(31 * 86400, "obs_hl_8418150_2025.json")
        self._observed(gauge, year=2025)
        self.assertEqual(len(gauge.urls), 2)

    def test_a_copy_made_while_the_year_ran_does_not_stand_for_the_finished_year(self):
        """On 31 December the year's files stop at the 30th. Two days
        on the year is past and they are two days old: they are asked
        for again, where a past year's month of grace would have kept
        the year a day short."""
        gauge = _Datagetter(self.VERIFIED, self.PRELIMINARY)
        self._observed(gauge, today=date(2026, 12, 31))
        asked = len(gauge.urls)
        made = datetime(2026, 12, 31, 12, tzinfo=timezone.utc).timestamp()
        for path in common.cache_dir().glob("obs_*"):
            os.utime(path, (made, made))
        with patch("time.time", return_value=made + 2 * 86400):
            self._observed(gauge, today=date(2027, 1, 2))
        self.assertEqual(gauge.asked[asked], ("high_low", "20260101", "20261231"))
        self.assertEqual(gauge.asked[-1][0], "water_level")
        self.assertEqual(gauge.asked[-1][2], "20261231")

    def test_a_copy_made_since_the_year_ended_is_kept_the_month(self):
        gauge = _Datagetter(self.VERIFIED, self.PRELIMINARY)
        self._observed(gauge, today=date(2027, 1, 3))
        asked = len(gauge.urls)
        made = datetime(2027, 1, 3, 12, tzinfo=timezone.utc).timestamp()
        for path in common.cache_dir().glob("obs_*"):
            os.utime(path, (made, made))
        with patch("time.time", return_value=made + 20 * 86400):
            self._observed(gauge, today=date(2027, 1, 23))
        self.assertEqual(len(gauge.urls), asked)


class FloodStageTests(_PrivateCache):
    """Where the water starts to flood, brought from the station's own
    datum to the one the tide tables are on."""

    # mdapi's answers for Portland, Maine (8418150), as it gave them on
    # 30 September 2026, with the datums cut to a few of the fifteen
    LEVELS = {"nos_minor": 20.5, "nos_moderate": 21.38, "nos_major": 22.69,
              "nws_minor": 20.55, "nws_moderate": 21.55, "nws_major": 22.56, "action": None,
              "self": "https://api.tidesandcurrents.noaa.gov/mdapi/prod/webapi/"
                      "stations/8418150/floodlevels.json"}
    DATUMS = {"accepted": "Apr 17 2003", "superseded": "", "epoch": "1983-2001",
              "units": "feet", "OrthometricDatum": "NAVD88", "datums": [
                  {"name": "STND", "description": "Station Datum", "value": 0.0},
                  {"name": "MHHW", "description": "Mean Higher-High Water", "value": 18.46},
                  {"name": "MSL", "description": "Mean Sea Level", "value": 13.49},
                  {"name": "MLLW", "description": "Mean Lower-Low Water", "value": 8.55},
                  {"name": "NAVD88", "description": "North American Vertical Datum of 1988",
                   "value": 13.81}],
              "LAT": 6.426, "HAT": 20.523}

    def _stage(self, levels, datums, station="8418150"):
        self.urls = []

        def fetch(url, headers=None, timeout=10):
            self.urls.append(url)
            answer = levels if "/floodlevels.json" in url else datums
            if isinstance(answer, Exception):
                raise answer
            return answer

        with patch.object(_http, "fetch_json", side_effect=fetch):
            return noaa.fetch_flood_stage(station)

    def test_portlands_flood_stage_is_twelve_feet_above_mllw(self):
        # the Weather Service's 20.55 ft on the station's datum, where
        # MLLW stands at 8.55
        self.assertAlmostEqual(self._stage(self.LEVELS, self.DATUMS), 12.0, places=6)

    def test_both_answers_are_asked_of_the_station_and_the_datums_in_feet(self):
        self._stage(self.LEVELS, self.DATUMS)
        base = "https://api.tidesandcurrents.noaa.gov/mdapi/prod/webapi/stations/8418150"
        self.assertEqual(sorted(self.urls),
                         [f"{base}/datums.json?units=english", f"{base}/floodlevels.json"])

    def test_the_ocean_services_level_stands_in_where_the_weather_service_has_none(self):
        levels = {**self.LEVELS, "nws_minor": None}
        self.assertAlmostEqual(self._stage(levels, self.DATUMS), 20.5 - 8.55, places=6)
        del levels["nws_minor"]
        self.assertAlmostEqual(self._stage(levels, self.DATUMS, "8418151"), 20.5 - 8.55,
                               places=6)

    def test_a_station_with_no_flood_levels_has_no_flood_stage(self):
        nulls = dict.fromkeys(("nos_minor", "nos_moderate", "nos_major", "nws_minor",
                               "nws_moderate", "nws_major", "action"))
        for n, levels in enumerate((nulls, {}, None, [], {"nws_minor": "n/a"})):
            with self.subTest(levels=levels):
                self.assertIsNone(self._stage(levels, self.DATUMS, f"84181{n:02d}"))

    def test_a_station_with_no_mllw_has_no_flood_stage(self):
        without = [d for d in self.DATUMS["datums"] if d["name"] != "MLLW"]
        for n, datums in enumerate(({**self.DATUMS, "datums": without},
                                    {**self.DATUMS, "datums": None}, {}, None, [],
                                    {"datums": [{"name": "MLLW", "value": None}]})):
            with self.subTest(datums=datums):
                self.assertIsNone(self._stage(self.LEVELS, datums, f"84182{n:02d}"))

    def test_mdapi_out_of_reach_is_no_flood_stage_not_an_error(self):
        down = OSError("network down")
        self.assertIsNone(self._stage(down, down, "8418301"))
        self.assertIsNone(self._stage(self.LEVELS, down, "8418302"))
        self.assertIsNone(self._stage(down, self.DATUMS, "8418303"))

    def test_the_answers_are_kept_for_a_month(self):
        self.assertAlmostEqual(self._stage(self.LEVELS, self.DATUMS), 12.0, places=6)
        self.assertEqual(sorted(p.name for p in common.cache_dir().iterdir()),
                         ["datums_8418150.json", "flood_8418150.json"])
        for path in common.cache_dir().iterdir():
            then = time.time() - 20 * 86400
            os.utime(path, (then, then))
        down = OSError("network down")
        self.assertAlmostEqual(self._stage(down, down), 12.0, places=6)
        self.assertEqual(self.urls, [])


if __name__ == "__main__":
    unittest.main()
