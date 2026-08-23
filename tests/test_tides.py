import unittest
from datetime import date, datetime, timedelta
from unittest.mock import patch

from linecast import tides
from linecast import _tides_common
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

        with patch.object(_tides_common, "read_cache", side_effect=fake_read_cache), \
             patch.object(_tides_common, "read_stale", return_value=None), \
             patch.object(_tides_noaa, "fetch_all_stations_noaa",
                          return_value=payload["stations"]), \
             patch.object(_tides_common, "write_cache") as write_cache:
            station_id, station_name = tides.find_nearest_station(47.61, -122.33)

        self.assertEqual((station_id, station_name), ("222", "Second Harbor"))
        self.assertEqual(calls[0][1], _tides_common.NEAREST_STATION_CACHE_MAX_AGE)
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
        preds = [(datetime(2026, 3, 6, 0, 0), 0.2), (datetime(2026, 3, 6, 12, 0), 1.8),
                 (datetime(2026, 3, 6, 23, 54), 0.4)]
        hilo = [(datetime(2026, 3, 6, 4, 30), 1.8, "H"),
                (datetime(2026, 3, 6, 11, 0), 0.2, "L")]

        with patch.object(tides, "_station_now", return_value=now_local), \
             patch.object(_tides_noaa, "fetch_all_stations_noaa", return_value=[]), \
             patch.object(_tides_noaa, "fetch_tides_range", return_value=preds) as fetch_tides, \
             patch.object(_tides_noaa, "fetch_hilo_range", return_value=hilo) as fetch_hilo, \
             patch.object(tides, "get_terminal_size", return_value=(80, 24)):
            output = tides.render("123", "Test Harbor", offset_minutes=120)

        self.assertEqual(fetch_tides.call_args.args[1:3], (scrubbed_date, scrubbed_date))
        self.assertEqual(fetch_hilo.call_args.args[1:3], (scrubbed_date, scrubbed_date))
        self.assertTrue(isinstance(output, str) and output)


if __name__ == "__main__":
    unittest.main()


class StaticRenderTests(unittest.TestCase):
    """--print output must be plain lines: no \\x00 overlay channel and no
    cursor-positioned tooltips (they only mean something under live_loop)."""

    def _render(self, fullscreen):
        from linecast._runtime import TidesRuntime
        now = datetime.now()
        start = now - timedelta(hours=12)
        preds = [(start + timedelta(minutes=30 * i), float(i % 12)) for i in range(96)]
        runtime = TidesRuntime.from_sources(argv=("--print",), environ={})
        return tides.render(
            "123", "Test Harbor", station_meta=None, runtime=runtime,
            fullscreen=fullscreen, predictions=preds, hilo=[], y_range=(0.0, 12.0),
        )

    def test_static_render_has_no_overlay_channel(self):
        self.assertNotIn("\x00", self._render(fullscreen=False))

    def test_live_render_keeps_now_tooltip_overlay(self):
        self.assertIn("\x00", self._render(fullscreen=True))


class StationSearchTests(unittest.TestCase):
    NOAA = [
        {"id": "8418150", "name": "PORTLAND", "state": "ME",
         "lat": 43.66, "lng": -70.25},
        {"id": "9439221", "name": "Portland Morrison Street Bridge",
         "state": "OR", "lat": 45.51, "lng": -122.67},
        {"id": "8638671", "name": "Lafayette River", "state": "VA",
         "lat": 36.89, "lng": -76.31},
    ]
    CHS = [
        {"id": "5cebf1df3d0f4a073c4bbd1e", "officialName": "Saint John",
         "latitude": 45.25, "longitude": -66.06},
    ]
    QLD = [
        {"name": "Brisbane Bar", "lat": -27.37, "lng": 153.17},
    ]

    def _matches(self, query, location=(44.41, -70.03, "US")):
        with patch.object(tides, "_fetch_all_stations", return_value=self.NOAA), \
             patch.object(tides, "_fetch_all_stations_chs", return_value=self.CHS), \
             patch.object(tides, "_fetch_all_stations_qld", return_value=self.QLD), \
             patch.object(tides, "_tidecheck_available", return_value=False), \
             patch.object(tides, "resolve_location", return_value=location):
            return tides._find_matching_stations(query)

    def test_multiword_query_matches_full_state_name(self):
        matches = self._matches("portland maine")
        self.assertEqual([m["id"] for m in matches], ["8418150"])

    def test_results_sorted_by_distance_from_location(self):
        matches = self._matches("portland")
        self.assertEqual([m["id"] for m in matches], ["8418150", "9439221"])
        self.assertLess(matches[0]["dist_nm"], matches[1]["dist_nm"])

    def test_no_location_sorts_alphabetically(self):
        matches = self._matches("portland", location=(None, None, None))
        self.assertEqual([m["id"] for m in matches], ["8418150", "9439221"])
        self.assertIsNone(matches[0]["dist_nm"])

    def test_country_token_matches_chs_stations(self):
        matches = self._matches("saint john canada")
        self.assertEqual([m["source"] for m in matches], ["chs"])

    def test_qld_station_matched_by_region_token(self):
        matches = self._matches("brisbane queensland")
        self.assertEqual([m["source"] for m in matches], ["qld"])
        self.assertEqual(matches[0]["id"], matches[0]["name"])
