"""Text from providers stays text (issue #119).

plain_text() on its own first: every escape sequence goes whole, every
lone control goes, and every other character stays, in every script.
Then each place provider text is read into linecast's own structures,
with a title-setting OSC standing in for anything worse: a geocoder
result, a vector-tile name, a route step, an alert, a station name.
"""

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from test_mvt import field, geom_ints, make_feature, make_layer, make_tile

from linecast._live import frame_paint
from linecast.maps.mvt import decode_tile
from linecast._plaintext import plain_text
from linecast.maps import route as mr
from linecast.maps.labels import _name
from linecast.maps.search import Result, _nominatim_result, _photon_result
from linecast.maps.ui import search_overlay

MARKER = "\x1b]0;LINECAST_REVIEW_MARKER\x07"


class TestPlainText:
    def test_osc_with_bel_goes_whole(self):
        assert plain_text(MARKER + "Park") == "Park"

    def test_osc_with_st_goes_whole(self):
        assert plain_text("\x1b]0;TITLE\x1b\\Park") == "Park"

    def test_osc8_hyperlink_goes_whole(self):
        text = "\x1b]8;;https://example.com\x1b\\Park\x1b]8;;\x1b\\"
        assert plain_text(text) == "Park"

    def test_an_unterminated_osc_runs_to_the_end(self):
        assert plain_text("Park\x1b]0;TITLE") == "Park"

    def test_csi_goes_whole(self):
        assert plain_text("\x1b[31;1mRed\x1b[0m \x1b[2J\x1b[?1049hPark") == "Red Park"

    def test_dcs_goes_whole(self):
        assert plain_text("\x1bP1$qm\x1b\\Park") == "Park"

    def test_other_escape_sequences_go(self):
        assert plain_text("\x1b7\x1b(BPark\x1bc") == "Park"

    def test_a_bare_escape_goes(self):
        assert plain_text("Park\x1b") == "Park"

    def test_c1_csi_goes_whole(self):
        assert plain_text("\u009b31mPark") == "Park"

    def test_c1_osc_goes_whole(self):
        assert plain_text("\u009d0;TITLE\u009cPark") == "Park"

    def test_lone_c1_controls_go(self):
        assert plain_text("Pa\u0085r\u0080k") == "Park"

    def test_del_and_nul_go(self):
        assert plain_text("Pa\x7fr\x00k\x08") == "Park"

    def test_line_breaks_become_spaces(self):
        assert plain_text("Deer\tIsle\nThorofare\r\nNarrows\rEnd") == \
            "Deer Isle Thorofare Narrows End"

    def test_lines_keeps_newlines(self):
        text = "First para.\r\n\r\nSecond\tpara.\rThird\x1b[2K."
        assert plain_text(text, lines=True) == "First para.\n\nSecond para.\nThird."

    def test_ordinary_unicode_is_unchanged(self):
        for text in (
            "می\u200cخواهم",                 # Persian, with ZWNJ
            "خیابان فردوسی",                  # Persian
            "القاهرة",                         # Arabic
            "תל אביב\u200f",                   # Hebrew, with RLM
            "क्\u200dष नई दिल्ली",               # Devanagari, with ZWJ
            "東京都 渋谷区 서울",               # CJK
            "👨\u200d👩\u200d👧 🏳\ufe0f\u200d🌈",   # emoji ZWJ sequences
            "Café e\u0301 Ærøskøbing",         # precomposed and combining
            "\u202aLRE\u202c \u2068iso\u2069",  # bidi embeddings, isolates
            "Nb\u00a0sp soft\u00adhyphen",     # no-break space, soft hyphen
        ):
            assert plain_text(text) is text

    def test_scripts_survive_around_a_sequence(self):
        assert plain_text("می\u200cخواهم\x1b[0m") == "می\u200cخواهم"

    def test_anything_not_a_string_comes_back_as_it_came(self):
        for value in (None, 7, 1.5, True, ["\x1b"]):
            assert plain_text(value) is value


class TestMapsSearch:
    def test_the_issue_reproduction(self):
        result = _photon_result({
            "properties": {"name": MARKER + "Park"},
            "geometry": {"coordinates": [-70, 43]},
        })
        state = SimpleNamespace(query="park", status="", purpose="", sel=0,
                                results=[result])
        paint = frame_paint("", search_overlay(state, 120, 30))
        assert MARKER not in paint
        assert "LINECAST_REVIEW_MARKER" not in paint
        assert "Park" in paint
        # the overlay's own formatting still reaches the paint
        assert "\x1b[" in paint

    def test_photon_detail_and_kind(self):
        result = _photon_result({
            "properties": {"name": "Park", "city": "Port\x1b[2Jland",
                           "state": "Maine\x07", "type": "ci\x85ty"},
            "geometry": {"coordinates": [-70, 43]},
        })
        assert result.detail == "Portland, Maine"
        assert result.kind == "city"

    def test_a_name_that_is_only_a_sequence_is_no_name(self):
        assert _photon_result({
            "properties": {"name": MARKER},
            "geometry": {"coordinates": [-70, 43]},
        }) is None

    def test_nominatim(self):
        result = _nominatim_result({
            "name": MARKER + "Park", "lat": "43.6", "lon": "-70.2",
            "address": {"city": "Portland\x1b[31m", "state": "Maine"},
        })
        assert (result.name, result.detail) == ("Park", "Portland, Maine")

    def test_a_result_built_anywhere_is_clean(self):
        # the recent-locations file is read back through Result too
        assert Result(MARKER + "Park", "a\nb", 0.0, 0.0, "point").name == "Park"


class TestVectorTiles:
    def test_a_name_decodes_clean_and_labels_clean(self):
        tile = make_tile(make_layer(
            name="place",
            features=[make_feature(ftype=1, tags=[0, 0, 1, 1],
                                   geometry=geom_ints([("move", [(1, 1)])]))],
            keys=["name", "name:fa"],
            values=[field(1, 2, (MARKER + "Park").encode()),
                    field(1, 2, "پارک\u200cها\x1b[0m".encode())]))
        (feat,) = decode_tile(tile)["place"]["features"]
        assert _name(feat["tags"], "en") == "Park"
        assert _name(feat["tags"], "fa") == "پارک\u200cها"


class TestRoute:
    def test_step_names_and_refs(self, monkeypatch):
        body = {"code": "Ok", "routes": [{
            "distance": 10.0, "duration": 5.0,
            "geometry": {"coordinates": [[-70.0, 43.0], [-70.1, 43.1]]},
            "legs": [{"steps": [{
                "distance": 10.0, "name": MARKER + "Main Street",
                "ref": "ME\x1b[5m 25",
                "maneuver": {"type": "depart", "location": [-70.0, 43.0]},
            }]}],
        }]}
        route = mr._parse(body, "car")
        assert route.steps[0]["name"] == "Main Street"
        assert route.steps[0]["ref"] == "ME 25"


class TestAlerts:
    def _nws(self, **props):
        base = {"status": "Actual", "event": "Heat Advisory",
                "headline": "Heat Advisory issued", "description": "Hot.",
                "severity": "Moderate", "expires": "",
                "web": "https://www.weather.gov/"}
        base.update(props)
        return {"features": [{"properties": base}]}

    def test_nws_text_is_clean_and_keeps_its_paragraphs(self):
        from linecast.weather import sources
        feed = self._nws(event="Heat\x1b[2J Advisory",
                         headline=MARKER + "Heat Advisory issued",
                         description="First.\x07\n\nSecond\x1b[31m.")
        with patch.object(sources, "fetch_json_cached", return_value=feed):
            (alert,) = sources.fetch_alerts(43.6, -70.2, "US")
        assert alert["event"] == "Heat Advisory"
        assert alert["headline"] == "Heat Advisory issued"
        assert alert["description"] == "First.\n\nSecond."

    def test_a_list_read_back_from_the_cache_is_cleaned(self):
        from linecast.weather import sources
        cached = [{"event": MARKER + "Wind Advisory", "headline": "",
                   "description": "", "expires": "", "severity": "Minor",
                   "url": ""}]
        with patch.object(sources, "fetch_json_cached", return_value=cached):
            (alert,) = sources.fetch_alerts(43.6, -70.2, "US")
        assert alert["event"] == "Wind Advisory"

    def test_the_link_is_the_apps_own_hyperlink(self):
        from linecast.weather import sources
        from linecast.weather.alerts import build_alert_modal
        feed = self._nws(web="https://www.weather.gov/\x1b\\\x1b]0;TITLE\x07")
        with patch.object(sources, "fetch_json_cached", return_value=feed):
            (alert,) = sources.fetch_alerts(43.6, -70.2, "US")
        assert alert["url"] == "https://www.weather.gov/"
        modal, _scroll = build_alert_modal(alert, 80, 24)
        text = "\n".join(modal) if isinstance(modal, list) else modal
        # the app's OSC 8 opens and closes around the url, and nothing
        # from the feed breaks out of it
        assert "\x1b]8;;https://www.weather.gov/\x1b\\" in text
        assert "\x1b]8;;\x1b\\" in text
        assert "TITLE" not in text


class TestLocations:
    def test_open_meteo_geocoder_results(self):
        from linecast.weather import sources
        answer = {"results": [{"name": MARKER + "Portland", "admin1": "Maine\x1b[0m",
                               "country": "United States", "latitude": 43.6,
                               "longitude": -70.2}]}
        with patch.object(sources, "fetch_json", return_value=answer):
            hit = sources.geocode_first("Portland")
        assert hit == (43.6, -70.2, "Portland, Maine, United States")

    def test_reverse_geocode(self):
        from linecast.weather import sources
        answer = {"address": {"town": MARKER + "Fayette", "state": "Maine\x9b2J",
                              "country_code": "us"}}
        with patch.object(sources, "fetch_json", return_value=answer), \
                patch("linecast.maps.search._throttle", lambda: None):
            name, country, addr = sources._reverse_geocode(44.41, -70.07, lang="en")
        assert name == "Fayette, Maine"
        assert country == "US"
        assert addr["town"] == "Fayette"
        # and the cached copy it answers from next time
        name, _country, _addr = sources._reverse_geocode(44.41, -70.07, lang="en")
        assert name == "Fayette, Maine"

    def test_metar_station_name(self):
        import time
        from linecast.weather.observed import nearest_observation
        now = time.time()
        report = {"lat": 43.65, "lon": -70.31, "obsTime": now - 60,
                  "icaoId": "KPWM", "name": MARKER + "Portland Intl Jetport",
                  "clouds": [{"cover": "FEW", "base": 5000}], "wxString": None}
        obs = nearest_observation(43.66, -70.26, [report], now=now)
        assert obs is not None and obs["name"] == "Portland Intl Jetport"

    def test_tide_station_name(self):
        from linecast.tides import view as tides_view
        provider = SimpleNamespace(station_metadata=lambda _id: {
            "id": "8418150", "name": MARKER + "Portland", "state": "ME\x1b[0m",
            "lat": 43.658, "lng": -70.244})
        meta, name, _tz = tides_view._station_details(provider, "8418150", "")
        assert name == "Portland, ME"
        assert meta["lat"] == 43.658
