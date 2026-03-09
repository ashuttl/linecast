import unittest
from datetime import date, datetime, timedelta
from unittest.mock import patch

from linecast import tides
from linecast import _tides_noaa
from linecast._cache import location_cache_key


class FindNearestStationTests(unittest.TestCase):
    def test_find_nearest_station_uses_location_scoped_cache(self):
        legacy_cache_file = _tides_noaa.CACHE_DIR / "station.json"
        payload = {
            "stations": [
                {"id": "111", "name": "First Harbor", "lat": 40.0, "lng": -70.0},
                {"id": "222", "name": "Second Harbor", "lat": 47.61, "lng": -122.33},
            ]
        }
        calls = []

        def fake_read_cache(path, max_age):
            calls.append((path, max_age))
            if path == legacy_cache_file:
                return {"id": "111", "name": "First Harbor"}
            return None

        with patch.object(_tides_noaa, "read_cache", side_effect=fake_read_cache), \
             patch.object(_tides_noaa, "read_stale", return_value=None), \
             patch.object(_tides_noaa, "fetch_json", return_value=payload), \
             patch.object(_tides_noaa, "write_cache") as write_cache:
            station_id, station_name = tides.find_nearest_station(47.61, -122.33)

        self.assertEqual((station_id, station_name), ("222", "Second Harbor"))
        self.assertEqual(calls[0][1], _tides_noaa.NEAREST_STATION_CACHE_MAX_AGE)
        self.assertEqual(
            calls[0][0].name,
            f"station_{location_cache_key(47.61, -122.33)}.json",
        )
        self.assertEqual(
            write_cache.call_args.args[0].name,
            f"station_{location_cache_key(47.61, -122.33)}.json",
        )


class RenderTests(unittest.TestCase):
    def test_render_live_window_starts_with_now_at_quarter_width(self):
        now_local = datetime(2026, 3, 5, 18, 30, 0)
        captured = {}

        class _StopRender(Exception):
            pass

        def fake_prepare_tide_window(predictions, hilo, start_dt, hours_shown=24):
            captured["start_dt"] = start_dt
            captured["hours_shown"] = hours_shown
            raise _StopRender()

        with patch.object(tides, "_station_now", return_value=now_local), \
             patch.object(tides, "get_terminal_size", return_value=(80, 24)), \
             patch.object(tides, "_prepare_tide_window", side_effect=fake_prepare_tide_window), \
             self.assertRaises(_StopRender):
            tides.render(
                "123",
                "Test Harbor",
                offset_minutes=120,
                predictions=[(now_local, 1.0)],
                hilo=[],
            )

        self.assertEqual(captured["hours_shown"], 24)
        self.assertEqual(
            captured["start_dt"],
            now_local - timedelta(hours=6) + timedelta(minutes=120),
        )

    def test_render_fetches_scrubbed_day_when_offset_crosses_midnight(self):
        now_local = datetime(2026, 3, 5, 23, 30, 0)
        scrubbed_date = date(2026, 3, 6)

        with patch.object(tides, "_station_now", return_value=now_local), \
             patch.object(
                 tides,
                 "fetch_tides",
                 return_value=[(0.0, 0.2), (12.0, 1.8), (23.9, 0.4)],
             ) as fetch_tides, \
             patch.object(
                 tides,
                 "fetch_hilo",
                 return_value=[(4.5, 1.8, "H"), (11.0, 0.2, "L")],
             ) as fetch_hilo, \
             patch.object(tides, "get_terminal_size", return_value=(80, 24)):
            output = tides.render("123", "Test Harbor", offset_minutes=120)

        self.assertEqual(fetch_tides.call_args.args[1], scrubbed_date)
        self.assertEqual(fetch_hilo.call_args.args[1], scrubbed_date)
        self.assertTrue(isinstance(output, str) and output)


if __name__ == "__main__":
    unittest.main()
