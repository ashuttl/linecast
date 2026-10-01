import re
import sys
import unittest
from contextlib import ExitStack
from datetime import date, datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

from linecast.tides import view as tides
from linecast.tides import chs as _tides_chs
from linecast.tides import hko as _tides_hko
from linecast.tides import jma as _tides_jma
from linecast.tides import kartverket as _tides_kartverket
from linecast.tides import noaa as _tides_noaa
from linecast.tides import openmeteo as _tides_openmeteo
from linecast.tides import qld as _tides_qld
from linecast.tides import stations as _tides_stations
from linecast.tides import ticon as _tides_ticon
from linecast.tides import tidecheck as _tides_tidecheck
from linecast._runtime import TidesRuntime
from linecast.tides.chart import prepare_tide_window
from linecast.tides.providers import (
    CHS, HKO, JMA, KARTVERKET, NOAA, OPENMETEO, PROVIDERS, QLD, TICON, TIDECHECK,
    provider_for_id,
)


def _no_bundled_stations():
    """The station lists that ship with linecast emptied (JMA's, the
    Norwegian gauges, TICON-4's), so a search finds only what the test's
    own lists hold."""
    stack = ExitStack()
    stack.enter_context(patch.object(_tides_jma, "STATIONS", []))
    stack.enter_context(patch.object(_tides_kartverket, "GAUGES", []))
    stack.enter_context(patch.object(_tides_ticon, "stations", return_value=[]))
    return stack


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
             patch.object(tides, "prepare_tide_window", side_effect=fake_prepare_tide_window), \
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

    def test_render_footer_names_the_data_source(self):
        now_local = datetime(2026, 3, 5, 12, 0, 0)
        preds = [(now_local + timedelta(hours=h), float(h % 12))
                 for h in range(-6, 30)]
        with patch.object(tides, "_station_now", return_value=now_local), \
             patch.object(tides, "get_terminal_size", return_value=(80, 24)):
            out = tides.render("CCH", "Cheung Chau", predictions=preds,
                               hilo=[], provider=HKO)
        self.assertIn("Hong Kong Observatory", out)

    def test_render_reads_now_in_the_data_zone_when_metadata_has_none(self):
        # CHS and TideCheck answer aware datetimes whatever the metadata
        # says, and a cached row keeps its offset; a station whose
        # metadata did not arrive must still draw rather than fall over
        # comparing a naive now with them
        tz = ZoneInfo("America/Halifax")
        start = datetime.now(tz).replace(minute=0, second=0, microsecond=0)
        preds = [(start + timedelta(hours=h), float(h % 12))
                 for h in range(-24, 30)]
        hilo = [(start + timedelta(hours=3), 11.0, "H"),
                (start + timedelta(hours=9), 0.0, "L")]
        self.assertIs(_tides_stations._station_now(None, preds).tzinfo, tz)
        with patch.object(tides, "get_terminal_size", return_value=(80, 24)):
            out = tides.render("abc", "Halifax", station_meta=None,
                               predictions=preds, hilo=hilo, provider=HKO)
        self.assertTrue(isinstance(out, str) and out)

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


class InfoLineTests(unittest.TestCase):
    """The range on the pill is the highest high less the lowest low."""

    def setUp(self):
        self.runtime = TidesRuntime(live=False, icons="plain", lang="en",
                                    metric=False, oneline=False)
        self.now = datetime(2026, 3, 5, 12, 0)
        self.preds = [(self.now + timedelta(hours=h), 2.0) for h in range(-6, 19)]

    def _pill(self, hilo):
        window = prepare_tide_window(self.preds, hilo, self.now - timedelta(hours=6))
        line = tides._info_line(window, 2.0, self.now, 80, 0, True, self.runtime)
        return re.sub(r"\x1b\[[0-9;]*m", "", line)

    def test_range_spans_high_to_low(self):
        pill = self._pill([(self.now + timedelta(hours=3), 5.0, "H"),
                           (self.now + timedelta(hours=9), 1.5, "L")])
        self.assertIn("Δ3.5", pill)

    def test_no_range_from_a_lone_low(self):
        # a diurnal station's day can hold one extreme; measured against
        # zero, a lone low of 1.5 ft read as a range of -1.5
        pill = self._pill([(self.now + timedelta(hours=9), 1.5, "L")])
        self.assertIn("1.5", pill)
        self.assertNotIn("Δ", pill)

    def test_no_range_from_a_lone_high(self):
        pill = self._pill([(self.now + timedelta(hours=3), 5.0, "H")])
        self.assertIn("5.0", pill)
        self.assertNotIn("Δ", pill)


class ChartRowTests(unittest.TestCase):
    """A time label under the curve is read whole: the now, hover and
    midnight lines stop at it, as they do at a height label."""

    def _row(self, **lines):
        blank = [[("\u2800", 0.0)] * 20]
        overlays = {0: [(6, "12:39p", (1, 2, 3), True)]}
        row = tides._render_tide_braille_rows(blank, [1.0] * 20, lines.pop("midnight", set()),
                                              overlays=overlays, **lines)[0]
        return re.sub(r"\x1b\[[0-9;]*m", "", row)

    def test_the_now_line_does_not_cut_a_time_label(self):
        self.assertEqual(self._row(now_col=9).strip(), "12:39p")

    def test_the_hover_and_midnight_lines_do_not_cut_a_time_label(self):
        self.assertEqual(self._row(hover_col=8).strip(), "12:39p")
        self.assertEqual(self._row(midnight={7}).strip(), "12:39p")

    def test_the_lines_still_run_beside_it(self):
        self.assertEqual(self._row(now_col=2, midnight={15}).strip(), "│   12:39p   │")


class HeaderNameTests(unittest.TestCase):
    """A station list's capitals are title-cased; a geocoder's name is
    already written the way its language writes it."""

    def _header(self, name):
        from linecast._parsers import tides_parser
        runtime = TidesRuntime.from_sources(
            tides_parser().parse_args(["--print"]), environ={})
        return re.sub(r"\033\[[0-9;]*m", "", tides._render_header_line(80, name, runtime))

    def test_capitals_are_title_cased(self):
        self.assertIn("Portland, ME ", self._header("PORTLAND, me"))

    def test_a_geocoders_name_is_left_alone(self):
        self.assertIn("Osaka, préfecture d'Osaka, Japon ",
                      self._header("Osaka, préfecture d'Osaka, Japon"))


class StaticRenderTests(unittest.TestCase):
    """--print output must be plain lines: no \\x00 overlay channel and no
    cursor-positioned tooltips (they only mean something under live_loop)."""

    def _render(self, fullscreen):
        from linecast._runtime import TidesRuntime
        from linecast._parsers import tides_parser
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

    def _matches(self, query, location=(44.41, -70.03, "US"), bundled=False):
        with (ExitStack() if bundled else _no_bundled_stations()), \
             patch.object(_tides_noaa, "fetch_all_stations_noaa", return_value=self.NOAA), \
             patch.object(_tides_chs, "fetch_all_stations_chs", return_value=self.CHS), \
             patch.object(_tides_qld, "fetch_all_stations_qld", return_value=self.QLD), \
             patch.object(_tides_tidecheck, "is_available", return_value=False), \
             patch.object(_tides_stations, "resolve_location", return_value=location):
            return _tides_stations._find_matching_stations(query)

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

    def test_a_bundled_gauge_joins_the_pool(self):
        # TICON-4 has two gauges at Portland, Victoria; from Maine they
        # are the farthest Portlands there are
        matches = self._matches("portland", bundled=True)
        self.assertEqual([m["source"] for m in matches], ["noaa", "noaa", "ticon", "ticon"])
        self.assertTrue(all(m["id"].startswith("ticon:") for m in matches[2:]))

    def test_a_japanese_station_is_found_by_either_name(self):
        for query in ("東京", "tokyo"):
            with self.subTest(query=query):
                ids = [m["id"] for m in self._matches(query, bundled=True)]
                self.assertIn("jma:TK", ids)

    def test_a_norwegian_gauge_is_found_without_its_letters(self):
        for query in ("tromsø", "tromso"):
            with self.subTest(query=query):
                found = [m for m in self._matches(query, bundled=True)
                         if m["source"] == "kartverket"]
                self.assertEqual([m["name"] for m in found], ["Tromsø"])
                self.assertTrue(found[0]["id"].startswith("kv:"))

    def test_a_provider_that_raises_leaves_the_others_listed(self):
        with _no_bundled_stations(), \
             patch.object(_tides_chs, "fetch_all_stations_chs",
                          side_effect=TypeError("null in the list")):
            with patch.object(_tides_noaa, "fetch_all_stations_noaa", return_value=self.NOAA), \
                 patch.object(_tides_qld, "fetch_all_stations_qld", return_value=self.QLD), \
                 patch.object(_tides_tidecheck, "is_available", return_value=False), \
                 patch.object(_tides_stations, "resolve_location",
                              return_value=(44.41, -70.03, "US")):
                matches = _tides_stations._find_matching_stations("portland")
        self.assertEqual([m["id"] for m in matches], ["8418150", "9439221"])

    def test_tidecheck_joins_the_pool_when_a_key_is_set(self):
        hit = [{"id": "fes2022-lisbon", "name": "Lisbon, Portugal",
                "lat": 38.71, "lng": -9.14}]
        with _no_bundled_stations(), \
             patch.object(_tides_noaa, "fetch_all_stations_noaa", return_value=[]), \
             patch.object(_tides_chs, "fetch_all_stations_chs", return_value=[]), \
             patch.object(_tides_qld, "fetch_all_stations_qld", return_value=[]), \
             patch.object(_tides_hko, "STATIONS", []), \
             patch.object(_tides_tidecheck, "is_available", return_value=True), \
             patch.object(_tides_tidecheck, "search_stations_tidecheck",
                          return_value=hit) as search, \
             patch.object(_tides_stations, "resolve_location", return_value=(44.41, -70.03, "US")):
            matches = _tides_stations._find_matching_stations("lisbon")
            # --nearby sends an empty query, which has nothing to search for
            self.assertEqual(_tides_stations._find_matching_stations(""), [])

        self.assertEqual([m["source"] for m in matches], ["tidecheck"])
        self.assertIsNotNone(matches[0]["dist_nm"])
        search.assert_called_once_with("lisbon")


class ProviderRegistryTests(unittest.TestCase):
    """The provider records stand in for the modules and never capture
    their functions at import, so a patched module function is seen."""

    def test_registry_is_keyed_by_source_name(self):
        self.assertEqual(list(PROVIDERS),
                         ["noaa", "chs", "qld", "hko", "jma", "kartverket", "ticon",
                          "tidecheck", "openmeteo"])
        for name, provider in PROVIDERS.items():
            self.assertEqual(provider.name, name)

    def test_station_ids_route_to_their_provider(self):
        self.assertIs(provider_for_id("8418150"), NOAA)
        self.assertIs(provider_for_id("5cebf1df3d0f4a073c4bbd1e"), CHS)
        self.assertIs(provider_for_id("123456789012345678901234"), CHS)
        self.assertIs(provider_for_id("om:43.6770,-70.3710"), OPENMETEO)
        self.assertIs(provider_for_id("CCH"), HKO)
        self.assertIs(provider_for_id("pt1"), HKO)
        self.assertIs(provider_for_id("jma:TK"), JMA)
        self.assertIs(provider_for_id("kv:69.6500,18.9600"), KARTVERKET)
        self.assertIs(provider_for_id("ticon:portland-61410-aus-bom"), TICON)
        self.assertIsNone(provider_for_id("portland maine"))
        self.assertIsNone(provider_for_id("Brisbane Bar"))

    def test_provider_for_id_tidecheck_slug_needs_a_key(self):
        with patch("linecast.tides.tidecheck.is_available", return_value=False):
            self.assertIsNone(provider_for_id("fes2022-lisbon"))
        with patch("linecast.tides.tidecheck.is_available", return_value=True):
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
        self.assertEqual(JMA.name_for_id("jma:TK"), "Tokyo")
        self.assertEqual(TICON.name_for_id("ticon:portland-61410-aus-bom"),
                         "Portland, Victoria")
        self.assertEqual(TICON.name_for_id("ticon:nope"), "Station ticon:nope")
        # a point where one of Kartverket's own gauges stands takes its name
        tromso = _tides_kartverket.make_station_id(69.64611, 18.95479)
        self.assertEqual(KARTVERKET.name_for_id(tromso), "Tromsø")

    def test_footer_label_translates_a_description_not_a_name(self):
        def runtime(lang):
            return TidesRuntime(live=False, icons="nerd", lang=lang, metric=True, oneline=False)
        self.assertEqual(NOAA.footer_label(runtime("fr")), "NOAA")
        self.assertEqual(OPENMETEO.footer_label(runtime("en")), "Open-Meteo tide model")
        self.assertEqual(OPENMETEO.footer_label(runtime("de")), "Open-Meteo-Gezeitenmodell")

    def test_a_source_is_named_as_it_names_itself(self):
        def runtime(lang):
            return TidesRuntime(live=False, icons="nerd", lang=lang, metric=True, oneline=False)
        self.assertEqual(JMA.footer_label(runtime("ja")), "気象庁")
        self.assertEqual(JMA.footer_label(runtime("en")), "Japan Meteorological Agency")
        self.assertEqual(JMA.footer_label(runtime("zh")), "Japan Meteorological Agency")
        for lang in ("zh", "zh-Hant", "zh-HK"):
            self.assertEqual(HKO.footer_label(runtime(lang)), "香港天文台", lang)
        self.assertEqual(HKO.footer_label(runtime("ja")), "Hong Kong Observatory")

    def test_only_a_source_that_stops_weeks_ahead_has_no_year_view(self):
        self.assertEqual([p.name for p in PROVIDERS.values() if not p.year_view],
                         ["tidecheck"])

    def test_only_the_model_calls_its_past_modeled(self):
        self.assertEqual({p.name: p.observed_label for p in PROVIDERS.values()
                          if p.observed_label != "measured"}, {"openmeteo": "modeled"})

    def test_a_source_with_no_gauge_or_flood_level_answers_with_nothing(self):
        for provider in (QLD, HKO, TICON, TIDECHECK):
            with self.subTest(provider=provider.name):
                self.assertEqual(provider.observed_extremes("id", 2026, date(2026, 10, 1)), {})
        for provider in PROVIDERS.values():
            if provider is not NOAA:
                with self.subTest(provider=provider.name):
                    self.assertIsNone(provider.flood_stage("id"))

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
            (JMA, _tides_jma, {
                "nearest": ("find_nearest_station_jma", (1.0, 2.0)),
                "station_metadata": ("fetch_station_metadata_jma", ("id",)),
                "tides_range": ("fetch_tides_range_jma", args),
                "hilo_range": ("fetch_hilo_range_jma", args),
                "y_range": ("fetch_y_range_jma", ("id", date(2026, 8, 20), None)),
                "observed_extremes": ("fetch_observed_extremes_jma",
                                      ("id", 2026, date(2026, 8, 20))),
            }),
            (KARTVERKET, _tides_kartverket, {
                "station_metadata": ("fetch_station_metadata_kartverket", ("id",)),
                "tides_range": ("fetch_tides_range_kartverket", args),
                "hilo_range": ("fetch_hilo_range_kartverket", args),
                "y_range": ("fetch_y_range_kartverket", ("id", date(2026, 8, 20), None)),
                "observed_extremes": ("fetch_observed_extremes_kartverket",
                                      ("id", 2026, date(2026, 8, 20))),
            }),
            (TICON, _tides_ticon, {
                "nearest": ("find_nearest_station_ticon", (1.0, 2.0)),
                "station_metadata": ("fetch_station_metadata_ticon", ("id",)),
                "tides_range": ("fetch_tides_range_ticon", args),
                "hilo_range": ("fetch_hilo_range_ticon", args),
                "y_range": ("fetch_y_range_ticon", ("id", date(2026, 8, 20), None)),
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
             patch("linecast.sunshine.json._location_label", return_value="Portland, ME"):
            self.assertEqual(OPENMETEO.nearest(43.677, -70.371),
                             ("om:43.6770,-70.3710", "Portland, ME"))
        with patch.object(_tides_openmeteo, "find_nearest_openmeteo",
                          return_value=(None, None)):
            self.assertEqual(OPENMETEO.nearest(39.0, -98.0), (None, None))

    def test_kartverket_nearest_is_the_point_named_for_the_place(self):
        with patch.object(_tides_kartverket, "find_point_kartverket",
                          return_value="kv:69.6500,18.9600"), \
             patch("linecast.sunshine.json._location_label", return_value="Tromsø, Troms"):
            self.assertEqual(KARTVERKET.nearest(69.65, 18.96),
                             ("kv:69.6500,18.9600", "Tromsø, Troms"))
            # the geocoder's own name for the place stands in where there is one
            self.assertEqual(KARTVERKET.nearest(69.65, 18.96, label="Tromsø"),
                             ("kv:69.6500,18.9600", "Tromsø"))
        # and a point the service has no water at has no station
        with patch.object(_tides_kartverket, "find_point_kartverket", return_value=None):
            self.assertEqual(KARTVERKET.nearest(43.66, -70.25), (None, None))


class LocationRoutingTests(unittest.TestCase):
    def _route(self, lat, lng, country, chs=(None, None), qld=(None, None),
               noaa=(None, None), tidecheck=(None, None), key=False,
               openmeteo=(None, None), jma=(None, None), kartverket=None,
               ticon=(None, None)):
        """Who was picked for the place, and who was asked, in the order
        they were asked.  HKO answers from its own list and Open-Meteo
        is always last, so neither is recorded."""
        asked = []

        def answers(name, value):
            def nearest(*_args, **_kwargs):
                asked.append(name)
                return value
            return nearest
        with patch.object(_tides_chs, "find_nearest_station_chs",
                          side_effect=answers("chs", chs)), \
             patch.object(_tides_qld, "find_nearest_station_qld",
                          side_effect=answers("qld", qld)), \
             patch.object(_tides_jma, "find_nearest_station_jma",
                          side_effect=answers("jma", jma)), \
             patch.object(_tides_kartverket, "find_point_kartverket",
                          side_effect=answers("kartverket", kartverket)), \
             patch.object(_tides_ticon, "find_nearest_station_ticon",
                          side_effect=answers("ticon", ticon)), \
             patch.object(_tides_noaa, "find_nearest_station",
                          side_effect=answers("noaa", noaa)), \
             patch.object(_tides_tidecheck, "is_available", return_value=key), \
             patch.object(_tides_tidecheck, "find_nearest_station_tidecheck",
                          side_effect=answers("tidecheck", tidecheck)), \
             patch.object(_tides_openmeteo, "find_nearest_openmeteo",
                          return_value=openmeteo), \
             patch("linecast.sunshine.json._location_label", return_value="Somewhere"):
            picked = _tides_stations._station_for_location(lat, lng, country)
        return picked, asked

    def test_a_provider_that_raises_is_passed_over(self):
        # the Open-Meteo model is the last resort, and still gets its turn
        with patch.object(_tides_chs, "find_nearest_station_chs",
                          side_effect=TypeError("null in the list")), \
             patch.object(_tides_noaa, "find_nearest_station",
                          side_effect=KeyError("id")), \
             patch.object(_tides_ticon, "find_nearest_station_ticon",
                          side_effect=ValueError("a gauge with no constants")), \
             patch.object(_tides_tidecheck, "is_available", return_value=False), \
             patch.object(_tides_openmeteo, "find_nearest_openmeteo",
                          return_value=("om:45.2500,-66.0600", "Saint John")):
            picked = _tides_stations._station_for_location(45.25, -66.06, "CA", label="Saint John")
        self.assertEqual(picked, (OPENMETEO, "om:45.2500,-66.0600", "Saint John"))

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

    def test_japan_reads_its_own_tables_first(self):
        picked, asked = self._route(35.65, 139.77, "JP", jma=("jma:TK", "Tokyo"))
        self.assertEqual(picked, (JMA, "jma:TK", "Tokyo"))
        self.assertEqual(asked, ["jma"])
        # and a spot the tables do not reach goes on down the list
        _picked, asked = self._route(24.3, 153.98, "JP")
        self.assertEqual(asked, ["jma", "ticon", "noaa"])

    def test_norway_and_svalbard_ask_kartverket_first(self):
        for country in ("NO", "SJ"):
            with self.subTest(country=country):
                picked, asked = self._route(69.65, 18.96, country,
                                            kartverket="kv:69.6500,18.9600")
                self.assertEqual(picked, (KARTVERKET, "kv:69.6500,18.9600", "Somewhere"))
                self.assertEqual(asked, ["kartverket"])

    def test_abroad_a_ticon_gauge_comes_before_noaa(self):
        gauge = ("ticon:cascais-209-prt-uhslc_fd", "Cascais, Lisbon")
        picked, asked = self._route(38.72, -9.14, "PT", ticon=gauge,
                                    noaa=("9999999", "FAR AWAY"))
        self.assertEqual(picked, (TICON,) + gauge)
        self.assertEqual(asked, ["ticon"])

    def test_at_home_noaa_comes_before_a_ticon_gauge(self):
        for country in ("US", "CA"):
            with self.subTest(country=country):
                _picked, asked = self._route(43.68, -70.36, country)
                self.assertLess(asked.index("noaa"), asked.index("ticon"))

    def test_tidecheck_only_when_a_key_is_set(self):
        _picked, asked = self._route(38.72, -9.14, "PT")
        self.assertEqual(asked, ["ticon", "noaa"])
        picked, asked = self._route(38.72, -9.14, "PT", key=True,
                                    tidecheck=("fes2022-lisbon", "Lisbon"))
        self.assertEqual(picked, (TIDECHECK, "fes2022-lisbon", "Lisbon"))
        self.assertEqual(asked, ["ticon", "noaa", "tidecheck"])

    def test_openmeteo_is_the_last_resort(self):
        picked, _asked = self._route(38.72, -9.14, "PT", openmeteo=("om:38.7200,-9.1400", None))
        self.assertEqual(picked, (OPENMETEO, "om:38.7200,-9.1400", "Somewhere"))

    def test_nothing_in_range(self):
        picked, _asked = self._route(39.0, -98.0, "US", key=True)
        self.assertEqual(picked, (None, None, None))

    def test_a_spent_tidecheck_budget_falls_through_to_openmeteo(self):
        # The day's 50 free-tier requests are gone and nothing is cached,
        # so TideCheck cannot name a station and Open-Meteo answers.
        with patch.dict("os.environ", {"LINECAST_TIDECHECK_PAID": ""}), \
             patch.object(_tides_tidecheck, "is_available", return_value=True), \
             patch.object(_tides_tidecheck, "requests_today",
                          return_value=_tides_tidecheck.FREE_TIER_LIMIT), \
             patch.object(_tides_tidecheck, "read_cache", return_value=None), \
             patch.object(_tides_tidecheck, "read_stale", return_value=None), \
             patch.object(_tides_tidecheck, "fetch_json") as fetch, \
             patch.object(_tides_noaa, "find_nearest_station",
                          return_value=(None, None)), \
             patch.object(_tides_ticon, "find_nearest_station_ticon",
                          return_value=(None, None)), \
             patch.object(_tides_openmeteo, "find_nearest_openmeteo",
                          return_value=("om:38.7200,-9.1400", None)), \
             patch("linecast.sunshine.json._location_label",
                   return_value="Lisbon"):
            picked = _tides_stations._station_for_location(38.72, -9.14, "PT")

        fetch.assert_not_called()
        self.assertEqual(picked, (OPENMETEO, "om:38.7200,-9.1400", "Lisbon"))


class LocationLabelTests(unittest.TestCase):
    """Coordinates are the last resort, not the second."""

    def _label(self, name, address, saved=None):
        from linecast.sunshine.json import _location_label
        with patch("linecast._config.saved_location", return_value=saved), \
             patch("linecast._geocode.reverse_geocode",
                   return_value=(name, "AU", address)):
            return _location_label(-41.1576, 146.2589)

    def test_an_empty_name_falls_through_to_the_address(self):
        # Nominatim gives a hamlet on a Tasmanian river an empty name and
        # a perfectly good address beside it; the header used to print the
        # coordinates and ignore the address it was holding.
        self.assertEqual(
            self._label("", {"state": "Tasmania", "country": "Australia"}),
            "Tasmania, Australia")

    def test_a_name_still_wins(self):
        self.assertEqual(
            self._label("Devonport, Tasmania", {"state": "Tasmania"}),
            "Devonport, Tasmania")

    def test_coordinates_remain_the_last_resort(self):
        self.assertEqual(self._label("", {}), "-41.1576,146.2589")


class AddressLabelTests(unittest.TestCase):
    """Two tiers at most, narrowest first."""

    def _label(self, address):
        from linecast.sunshine.json import _address_label
        return _address_label(address)

    def test_a_region_pairs_with_its_country(self):
        self.assertEqual(
            self._label({"state": "Tasmania", "country": "Australia"}),
            "Tasmania, Australia")

    def test_a_locality_pairs_with_its_region(self):
        self.assertEqual(
            self._label({"city": "Edinburgh", "state": "Scotland",
                         "country": "United Kingdom"}),
            "Edinburgh, Scotland")

    def test_a_county_pairs_with_its_state_not_its_country(self):
        self.assertEqual(
            self._label({"county": "Latrobe", "state": "Tasmania",
                         "country": "Australia"}),
            "Latrobe, Tasmania")

    def test_a_country_alone_will_do(self):
        self.assertEqual(self._label({"country": "Australia"}), "Australia")

    def test_nothing_usable_is_empty(self):
        self.assertEqual(self._label({}), "")
        self.assertEqual(self._label(None), "")
        self.assertEqual(self._label({"ocean": "Pacific"}), "")


class StationLabelTests(unittest.TestCase):
    """The forward geocoder already named the place; tides should use it."""

    def test_a_stationless_provider_takes_the_geocoders_label(self):
        with patch.object(_tides_noaa, "find_nearest_station",
                          return_value=(None, None)), \
             patch.object(_tides_ticon, "find_nearest_station_ticon",
                          return_value=(None, None)), \
             patch.object(_tides_tidecheck, "is_available", return_value=False), \
             patch.object(_tides_openmeteo, "find_nearest_openmeteo",
                          return_value=("om:-41.1576,146.2589", None)), \
             patch("linecast.sunshine.json._location_label") as reverse:
            picked = _tides_stations._station_for_location(
                -41.1576, 146.2589, "AU", label="Leith, Tasmania, Australia")
        self.assertEqual(picked[0], OPENMETEO)
        self.assertEqual(picked[2], "Leith, Tasmania, Australia")
        # and the round trip to name what we could already name is spared
        reverse.assert_not_called()

    def test_a_real_station_keeps_its_own_name(self):
        # The header names the station, and NOAA knows what its stations
        # are called better than the user's query does.
        with patch.object(_tides_noaa, "find_nearest_station",
                          return_value=("8418150", "PORTLAND")), \
             patch.object(_tides_tidecheck, "is_available", return_value=False):
            picked = _tides_stations._station_for_location(43.68, -70.36, "US",
                                                           label="Portland, Maine")
        self.assertEqual(picked, (NOAA, "8418150", "PORTLAND"))

    def test_without_a_label_the_provider_still_names_itself(self):
        with patch.object(_tides_noaa, "find_nearest_station",
                          return_value=(None, None)), \
             patch.object(_tides_ticon, "find_nearest_station_ticon",
                          return_value=(None, None)), \
             patch.object(_tides_tidecheck, "is_available", return_value=False), \
             patch.object(_tides_openmeteo, "find_nearest_openmeteo",
                          return_value=("om:-41.1576,146.2589", None)), \
             patch("linecast.sunshine.json._location_label",
                   return_value="Tasmania, Australia"):
            picked = _tides_stations._station_for_location(-41.1576, 146.2589, "AU")
        self.assertEqual(picked[2], "Tasmania, Australia")

    def test_only_stationless_providers_are_overridden(self):
        # the model and Kartverket predict for the point asked about
        for provider in (OPENMETEO, KARTVERKET):
            self.assertTrue(provider.stationless, provider.name)
        for provider in (NOAA, CHS, HKO, QLD, JMA, TICON, TIDECHECK):
            self.assertFalse(provider.stationless, provider.name)


class CtrlCTests(unittest.TestCase):
    @unittest.skipIf(sys.platform == "win32", "Windows has no SIGINT to send oneself")
    def test_ctrl_c_does_not_wait_for_a_stuck_provider(self):
        # One of the station's fetches is stuck in its timeout; Ctrl-C
        # while the view waits for it quits at once, rather than when
        # the timeout runs out.
        import os
        import signal
        import threading
        import time
        from linecast.tides.providers import TideProvider

        class Stuck(TideProvider):
            name = "noaa"

            def y_range(self, *args):
                time.sleep(3)

            def tides_range(self, *args):
                return []

            def hilo_range(self, *args):
                return []

        start = time.monotonic()
        with self.assertRaises(KeyboardInterrupt):
            threading.Timer(0.2, os.kill, (os.getpid(), signal.SIGINT)).start()
            _tides_stations._fetch_station(Stuck(), "8418150", None, None, live=False)
        self.assertLess(time.monotonic() - start, 1.5)


class TestNoColor(unittest.TestCase):
    """Without color the pills' half blocks would read as stray marks;
    the text stands alone, as weather's place does."""

    def setUp(self):
        from linecast.terminal import color as _color
        patcher = patch.object(_color, "_COLOR_MODE", "none")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.runtime = TidesRuntime(live=False, icons="plain", lang="en", oneline=False,
                                    metric=True)

    def test_the_station_is_its_name(self):
        line = tides._render_header_line(60, "PORTLAND, ME", self.runtime)
        self.assertTrue(line.startswith("Portland, ME "))
        self.assertNotIn("▐", line)
        self.assertNotIn("▌", line)

    def test_the_stats_are_the_text(self):
        now = datetime(2026, 9, 29, 12, 0)
        window = {"hilo": [(now + timedelta(hours=3), 9.8, "H"),
                           (now + timedelta(hours=9), 0.4, "L")]}
        line = tides._info_line(window, 5.0, now, 60, 0, True, self.runtime)
        self.assertNotIn("▐", line)
        self.assertNotIn("▌", line)
        self.assertEqual(line.strip(), "↗ 1.5m  ▲3.0m 15:00  ▼0.1m 21:00  Δ2.9m")
