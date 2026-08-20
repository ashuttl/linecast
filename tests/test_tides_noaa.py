import unittest
from datetime import date, datetime
from unittest.mock import patch

from linecast import _tides_noaa as noaa
from linecast._cache import location_cache_key


class TidesRangeTests(unittest.TestCase):
    def test_fetch_tides_range_dedupes_midnight_boundary_points(self):
        start = date(2026, 3, 5)
        end = date(2026, 3, 6)

        def fake_fetch_tides(station_id, day):
            self.assertEqual(station_id, "123")
            if day == start:
                return [(23.5, 1.2), (24.0, 0.8)]
            return [(0.0, 0.8), (1.0, 1.0)]

        with patch.object(noaa, "fetch_tides", side_effect=fake_fetch_tides):
            points = noaa.fetch_tides_range("123", start, end, station_tz=None)

        self.assertEqual(len(points), 3)
        self.assertEqual(points[0], (datetime(2026, 3, 5, 23, 30), 1.2))
        self.assertEqual(points[1], (datetime(2026, 3, 6, 0, 0), 0.8))
        self.assertEqual(points[2], (datetime(2026, 3, 6, 1, 0), 1.0))


class StationLookupTests(unittest.TestCase):
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
        with patch.object(noaa, "read_cache", return_value=None), \
             patch.object(noaa, "fetch_all_stations_noaa", return_value=stations), \
             patch.object(noaa, "write_cache"):
            station_id, station_name = noaa.find_nearest_station(43.68, -70.36)

        self.assertEqual((station_id, station_name), ("8418150", "PORTLAND"))

    def test_find_nearest_station_tolerates_missing_type(self):
        stations = [
            {"id": "1", "name": "Typeless", "lat": "43.68", "lng": "-70.36"},
        ]
        with patch.object(noaa, "read_cache", return_value=None), \
             patch.object(noaa, "fetch_all_stations_noaa", return_value=stations), \
             patch.object(noaa, "write_cache"):
            station_id, _ = noaa.find_nearest_station(43.68, -70.36)

        self.assertEqual(station_id, "1")

    def test_find_nearest_station_uses_stale_cache_on_fetch_error(self):
        lat, lng = 47.61, -122.33
        cache_file = noaa.CACHE_DIR / f"station_{location_cache_key(lat, lng)}.json"
        stale = {"id": "222", "name": "Second Harbor"}

        def fake_read_stale(path):
            self.assertEqual(path, cache_file)
            return stale

        with patch.object(noaa, "read_cache", return_value=None), \
             patch.object(noaa, "fetch_all_stations_noaa", return_value=[]), \
             patch.object(noaa, "read_stale", side_effect=fake_read_stale), \
             patch.object(noaa, "write_cache") as write_cache:
            station_id, station_name = noaa.find_nearest_station(lat, lng)

        self.assertEqual((station_id, station_name), ("222", "Second Harbor"))
        write_cache.assert_not_called()


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
                cache_file, "http://x", row_builder=noaa._build_tide_row,
                tuple_builder=lambda row: (row["h"], row["v"]))

        self.assertIsNone(rows)
        cache_file.unlink.assert_called_once()


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
