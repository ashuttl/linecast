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
    def test_find_nearest_station_uses_stale_cache_on_fetch_error(self):
        lat, lng = 47.61, -122.33
        cache_file = noaa.CACHE_DIR / f"station_{location_cache_key(lat, lng)}.json"
        stale = {"id": "222", "name": "Second Harbor"}

        def fake_read_stale(path):
            self.assertEqual(path, cache_file)
            return stale

        with patch.object(noaa, "read_cache", return_value=None), \
             patch.object(noaa, "fetch_json", side_effect=RuntimeError("boom")), \
             patch.object(noaa, "read_stale", side_effect=fake_read_stale), \
             patch.object(noaa, "write_cache") as write_cache:
            station_id, station_name = noaa.find_nearest_station(lat, lng)

        self.assertEqual((station_id, station_name), ("222", "Second Harbor"))
        write_cache.assert_not_called()


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
