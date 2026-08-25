import unittest
from datetime import date, datetime, timedelta
from unittest.mock import patch

from linecast import tides
from linecast import _tides_chs
from linecast import _tides_hko
from linecast import _tides_noaa
from linecast import _tides_openmeteo
from linecast import _tides_qld
from linecast import _tides_tidecheck
from linecast._tides_providers import (
    CHS, HKO, NOAA, OPENMETEO, PROVIDERS, QLD, TIDECHECK, provider_for_id,
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
        from linecast._runtime import TidesRuntime, tides_parser
        now = datetime.now()
        start = now - timedelta(hours=12)
        preds = [(start + timedelta(minutes=30 * i), float(i % 12)) for i in range(96)]
        runtime = TidesRuntime.from_sources(tides_parser().parse_args(["--print"]), environ={})
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
        with patch.object(_tides_noaa, "fetch_all_stations_noaa", return_value=self.NOAA), \
             patch.object(_tides_chs, "fetch_all_stations_chs", return_value=self.CHS), \
             patch.object(_tides_qld, "fetch_all_stations_qld", return_value=self.QLD), \
             patch.object(_tides_tidecheck, "is_available", return_value=False), \
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

    def test_tidecheck_joins_the_pool_when_a_key_is_set(self):
        hit = [{"id": "fes2022-lisbon", "name": "Lisbon, Portugal",
                "lat": 38.71, "lng": -9.14}]
        with patch.object(_tides_noaa, "fetch_all_stations_noaa", return_value=[]), \
             patch.object(_tides_chs, "fetch_all_stations_chs", return_value=[]), \
             patch.object(_tides_qld, "fetch_all_stations_qld", return_value=[]), \
             patch.object(_tides_hko, "STATIONS", []), \
             patch.object(_tides_tidecheck, "is_available", return_value=True), \
             patch.object(_tides_tidecheck, "search_stations_tidecheck",
                          return_value=hit) as search, \
             patch.object(tides, "resolve_location", return_value=(44.41, -70.03, "US")):
            matches = tides._find_matching_stations("lisbon")
            # --nearby sends an empty query, which has nothing to search for
            self.assertEqual(tides._find_matching_stations(""), [])

        self.assertEqual([m["source"] for m in matches], ["tidecheck"])
        self.assertIsNotNone(matches[0]["dist_nm"])
        search.assert_called_once_with("lisbon")


class ProviderRegistryTests(unittest.TestCase):
    """The provider records stand in for the modules and never capture
    their functions at import, so a patched module function is seen."""

    def test_registry_is_keyed_by_source_name(self):
        self.assertEqual(list(PROVIDERS),
                         ["noaa", "chs", "qld", "hko", "tidecheck", "openmeteo"])
        for name, provider in PROVIDERS.items():
            self.assertEqual(provider.name, name)

    def test_station_ids_route_to_their_provider(self):
        self.assertIs(provider_for_id("8418150"), NOAA)
        self.assertIs(provider_for_id("5cebf1df3d0f4a073c4bbd1e"), CHS)
        self.assertIs(provider_for_id("123456789012345678901234"), CHS)
        self.assertIs(provider_for_id("om:43.6770,-70.3710"), OPENMETEO)
        self.assertIs(provider_for_id("CCH"), HKO)
        self.assertIs(provider_for_id("pt1"), HKO)
        self.assertIsNone(provider_for_id("portland maine"))
        self.assertIsNone(provider_for_id("Brisbane Bar"))

    def test_provider_for_id_tidecheck_slug_needs_a_key(self):
        with patch("linecast._tides_tidecheck.is_available", return_value=False):
            self.assertIsNone(provider_for_id("fes2022-lisbon"))
        with patch("linecast._tides_tidecheck.is_available", return_value=True):
            self.assertIs(provider_for_id("fes2022-lisbon"), TIDECHECK)
            self.assertIsNone(provider_for_id("lisbon"))
            self.assertIsNone(provider_for_id("Fes2022-Lisbon"))
            self.assertIsNone(provider_for_id("portland maine"))

    def test_names_for_ids(self):
        stations = [{"id": "8418150", "name": "PORTLAND", "state": "ME"}]
        with patch.object(_tides_noaa, "fetch_all_stations_noaa", return_value=stations):
            self.assertEqual(NOAA.name_for_id("8418150"), "PORTLAND, ME")
            self.assertEqual(NOAA.name_for_id("9999999"), "Station 9999999")
        self.assertEqual(CHS.name_for_id("5cebf1df3d0f4a073c4bbd1e"), "Station 5cebf1df")
        self.assertEqual(OPENMETEO.name_for_id("om:1,2"), "Tide model")
        self.assertEqual(HKO.name_for_id("qub"), "Quarry Bay")

    def test_records_call_through_the_modules(self):
        args = ("id", date(2026, 8, 20), date(2026, 8, 21), None)
        calls = [
            (NOAA, _tides_noaa, {
                "nearest": ("find_nearest_station", (1.0, 2.0)),
                "station_metadata": ("fetch_station_metadata_noaa", ("id",)),
                "tides_range": ("fetch_tides_range_with_fallback", args),
                "hilo_range": ("fetch_hilo_range", args),
            }),
            (CHS, _tides_chs, {
                "nearest": ("find_nearest_station_chs", (1.0, 2.0)),
                "station_metadata": ("fetch_station_metadata_chs", ("id",)),
                "tides_range": ("fetch_tides_range_chs", args),
                "hilo_range": ("fetch_hilo_range_chs", args),
                "y_range": ("fetch_y_range_chs", ("id", date(2026, 8, 20), None)),
            }),
            (QLD, _tides_qld, {
                "nearest": ("find_nearest_station_qld", (1.0, 2.0)),
                "station_metadata": ("fetch_station_metadata_qld", ("id",)),
                "tides_range": ("fetch_tides_range_qld", args),
                "hilo_range": ("fetch_hilo_range_qld", args),
                "y_range": ("fetch_y_range_qld", ("id", date(2026, 8, 20), None)),
            }),
            (TIDECHECK, _tides_tidecheck, {
                "nearest": ("find_nearest_station_tidecheck", (1.0, 2.0)),
                "station_metadata": ("fetch_station_metadata_tidecheck", ("id",)),
                "tides_range": ("fetch_tides_range_tidecheck", args),
                "hilo_range": ("fetch_hilo_range_tidecheck", args),
                "y_range": ("fetch_y_range_tidecheck", ("id", date(2026, 8, 20), None)),
            }),
            (OPENMETEO, _tides_openmeteo, {
                "station_metadata": ("fetch_station_metadata_openmeteo", ("id",)),
                "tides_range": ("fetch_tides_range_openmeteo", args),
                "hilo_range": ("fetch_hilo_range_openmeteo", args),
                "y_range": ("fetch_y_range_openmeteo", ("id", date(2026, 8, 20), None)),
            }),
        ]
        for provider, module, methods in calls:
            for method, (func, call_args) in methods.items():
                with self.subTest(provider=provider.name, method=method), \
                     patch.object(module, func, return_value="patched") as fn:
                    self.assertEqual(getattr(provider, method)(*call_args), "patched")
                    fn.assert_called_once_with(*call_args)

    def test_noaa_y_range_drops_the_timezone(self):
        with patch.object(_tides_noaa, "fetch_y_range", return_value=(0.0, 9.0)) as fy:
            self.assertEqual(NOAA.y_range("8418150", date(2026, 8, 20), "tz"), (0.0, 9.0))
        fy.assert_called_once_with("8418150", date(2026, 8, 20))

    def test_tidecheck_availability_follows_the_key(self):
        with patch.object(_tides_tidecheck, "is_available", return_value=False):
            self.assertFalse(TIDECHECK.available())
        with patch.object(_tides_tidecheck, "is_available", return_value=True):
            self.assertTrue(TIDECHECK.available())
        self.assertTrue(NOAA.available())

    def test_openmeteo_nearest_is_labelled_with_the_place(self):
        with patch.object(_tides_openmeteo, "find_nearest_openmeteo",
                          return_value=("om:43.6770,-70.3710", None)), \
             patch("linecast._sunshine_json._location_label", return_value="Portland, ME"):
            self.assertEqual(OPENMETEO.nearest(43.677, -70.371),
                             ("om:43.6770,-70.3710", "Portland, ME (model)"))
        with patch.object(_tides_openmeteo, "find_nearest_openmeteo",
                          return_value=(None, None)):
            self.assertEqual(OPENMETEO.nearest(39.0, -98.0), (None, None))


class LocationRoutingTests(unittest.TestCase):
    def _route(self, lat, lng, country, chs=(None, None), qld=(None, None),
               noaa=(None, None), tidecheck=(None, None), key=False,
               openmeteo=(None, None)):
        with patch.object(_tides_chs, "find_nearest_station_chs", return_value=chs) as f_chs, \
             patch.object(_tides_qld, "find_nearest_station_qld", return_value=qld) as f_qld, \
             patch.object(_tides_noaa, "find_nearest_station", return_value=noaa) as f_noaa, \
             patch.object(_tides_tidecheck, "is_available", return_value=key), \
             patch.object(_tides_tidecheck, "find_nearest_station_tidecheck",
                          return_value=tidecheck) as f_tc, \
             patch.object(_tides_openmeteo, "find_nearest_openmeteo",
                          return_value=openmeteo), \
             patch("linecast._sunshine_json._location_label", return_value="Somewhere"):
            picked = tides._station_for_location(lat, lng, country)
        asked = [name for name, f in (("chs", f_chs), ("qld", f_qld),
                                      ("noaa", f_noaa), ("tidecheck", f_tc))
                 if f.called]
        return picked, asked

    def test_us_goes_straight_to_noaa(self):
        picked, asked = self._route(43.68, -70.36, "US", noaa=("8418150", "PORTLAND"))
        self.assertEqual(picked, (NOAA, "8418150", "PORTLAND"))
        self.assertEqual(asked, ["noaa"])

    def test_canada_tries_chs_first(self):
        picked, asked = self._route(45.25, -66.06, "CA", chs=("5ceb", "Saint John"),
                                    noaa=("8410140", "EASTPORT"))
        self.assertEqual(picked, (CHS, "5ceb", "Saint John"))
        self.assertEqual(asked, ["chs"])

    def test_canada_falls_back_to_noaa_across_the_border(self):
        picked, asked = self._route(48.42, -123.37, "CA", noaa=("9449880", "FRIDAY HARBOR"))
        self.assertEqual(picked, (NOAA, "9449880", "FRIDAY HARBOR"))
        self.assertEqual(asked, ["chs", "noaa"])

    def test_queensland_tries_qld_but_the_rest_of_australia_does_not(self):
        picked, asked = self._route(-16.92, 145.78, "AU", qld=("Cairns", "Cairns"))
        self.assertEqual(picked, (QLD, "Cairns", "Cairns"))
        self.assertEqual(asked, ["qld"])
        _picked, asked = self._route(-33.87, 151.21, "AU")
        self.assertNotIn("qld", asked)

    def test_hong_kong_answers_from_its_own_station_list(self):
        picked, asked = self._route(22.28, 114.16, "HK")
        self.assertEqual(picked, (HKO, "QUB", "Quarry Bay"))
        self.assertEqual(asked, [])

    def test_tidecheck_only_when_a_key_is_set(self):
        _picked, asked = self._route(38.72, -9.14, "PT")
        self.assertEqual(asked, ["noaa"])
        picked, asked = self._route(38.72, -9.14, "PT", key=True,
                                    tidecheck=("fes2022-lisbon", "Lisbon"))
        self.assertEqual(picked, (TIDECHECK, "fes2022-lisbon", "Lisbon"))
        self.assertEqual(asked, ["noaa", "tidecheck"])

    def test_openmeteo_is_the_last_resort(self):
        picked, _asked = self._route(38.72, -9.14, "PT", openmeteo=("om:38.7200,-9.1400", None))
        self.assertEqual(picked, (OPENMETEO, "om:38.7200,-9.1400", "Somewhere (model)"))

    def test_nothing_in_range(self):
        picked, _asked = self._route(39.0, -98.0, "US", key=True)
        self.assertEqual(picked, (None, None, None))
