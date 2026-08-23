import unittest
from datetime import date, datetime
from unittest.mock import patch

from linecast import _tides_common as common
from linecast import _tides_noaa as noaa
from linecast._cache import location_cache_key


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
        with patch.object(noaa, "_fetch_payload", return_value=payload) as fp, \
             patch.object(noaa, "write_cache") as wc:
            rows = noaa.fetch_month("8418150", date(2026, 2, 1), "6")

        cache_file, _, url = fp.call_args.args[:3]
        self.assertEqual(cache_file.name, "pred_8418150_202602.json")
        self.assertIn("begin_date=20260201&end_date=20260228", url)
        self.assertIn("interval=6", url)
        self.assertEqual(rows, [["2026-02-01 00:00", 1.5], ["2026-02-28 23:54", 2.5]])
        self.assertEqual(wc.call_args.args, (cache_file, rows))

    def test_hilo_month_cache_name_and_rows(self):
        payload = {"predictions": [
            {"t": "2026-12-31 20:28", "v": "10.1", "type": "H"},
        ]}
        with patch.object(noaa, "_fetch_payload", return_value=payload) as fp, \
             patch.object(noaa, "write_cache"):
            rows = noaa.fetch_month("8418150", date(2026, 12, 1), "hilo")
        cache_file, _, url = fp.call_args.args[:3]
        self.assertEqual(cache_file.name, "hilo_8418150_202612.json")
        self.assertIn("begin_date=20261201&end_date=20261231", url)
        self.assertEqual(rows, [["2026-12-31 20:28", 10.1, "H"]])

    def test_cached_rows_are_returned_as_is(self):
        cached = [["2026-02-01 00:00", 1.5]]
        with patch.object(noaa, "_fetch_payload", return_value=cached), \
             patch.object(noaa, "write_cache") as wc:
            self.assertEqual(noaa.fetch_month("8418150", date(2026, 2, 1), "6"), cached)
        wc.assert_not_called()


    def test_two_threads_asking_for_one_month_make_one_request(self):
        # a subordinate station's curve and its extremes both want the
        # hi/lo month, and tides.py asks for them on two threads at once
        import tempfile
        import threading
        import time
        from pathlib import Path
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
             patch.object(noaa, "CACHE_DIR", Path(tmp)), \
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
        legacy_cache_file = noaa.CACHE_DIR / "station.json"
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
        cache_file = noaa.CACHE_DIR / f"station_{location_cache_key(lat, lng)}.json"
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


class PredictionErrorTests(unittest.TestCase):
    def test_error_payload_is_dropped_from_cache(self):
        # NOAA reports "no data" as a 200 JSON error body; it must not be
        # served as fresh cache for the next 24 hours.
        from unittest.mock import MagicMock
        cache_file = MagicMock()
        error_payload = {"error": {"message": "No Predictions data was found."}}
        with patch.object(noaa, "_fetch_payload", return_value=error_payload):
            rows = noaa._fetch_prediction_rows(
                cache_file, "http://x", row_builder=noaa._build_tide_row)

        self.assertIsNone(rows)
        cache_file.unlink.assert_called_once()


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

        with patch.object(noaa, "fetch_json_cached", return_value=payload), \
             patch.object(noaa, "write_cache") as write_cache:
            meta = noaa.fetch_station_metadata_noaa("9414290")

        self.assertIsNotNone(meta)
        self.assertEqual(meta["id"], "9414290")
        self.assertEqual(meta["name"], "San Francisco")
        self.assertEqual(meta["state"], "CA")
        self.assertEqual(meta["timezone_abbr"], "PST")
        self.assertEqual(meta["timezonecorr"], -8)
        self.assertTrue(meta["observedst"])
        self.assertEqual(write_cache.call_args.args[0].name, "station_meta_9414290.json")


if __name__ == "__main__":
    unittest.main()
