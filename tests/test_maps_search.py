"""Tests for the geocoding-search client.

No network: the module's single fetch seam (_get_json) is patched at the
module object, and the disk cache is redirected to a temporary directory
per test. The Photon and Nominatim payloads are real responses captured
from the live services (tests/fixtures/photon_search.json — "holy don"
biased to Portland ME; tests/fixtures/nominatim_search.json — "Portland
Head Light"), so a change to either response shape breaks these tests.
A couple of edge cases the live captures happen not to contain (a
nameless feature, an empty result set) are built by hand from those same
documented shapes.
"""

import json
import sys
from pathlib import Path

import pytest

# Ensure the worktree src is preferred over any installed version.
# (No sys.modules purge here: this file is collected after other test
# modules that hold references into already-imported linecast modules.)
_src = str(Path(__file__).resolve().parent.parent / "src")
if _src not in sys.path:
    sys.path.insert(0, _src)

from linecast import _maps_search as ms

FIXTURES = Path(__file__).parent / "fixtures"
PHOTON = json.loads((FIXTURES / "photon_search.json").read_text())
NOMINATIM = json.loads((FIXTURES / "nominatim_search.json").read_text())


class _Fetch:
    """Stand-in for _get_json that records calls and replays a payload."""

    def __init__(self, payload=None, error=None):
        self.payload = payload
        self.error = error
        self.urls = []
        self.headers = []

    def __call__(self, url, headers=None, timeout=10):
        self.urls.append(url)
        self.headers.append(headers or {})
        if self.error is not None:
            raise self.error
        return self.payload

    @property
    def calls(self):
        return len(self.urls)


@pytest.fixture
def cache(tmp_path, monkeypatch):
    monkeypatch.setattr(ms, "CACHE_ROOT", tmp_path)
    return tmp_path


@pytest.fixture
def no_throttle(monkeypatch):
    """Neutralize the rate-limit gate so tests never really sleep."""
    monkeypatch.setattr(ms, "_last_hit", 0.0)
    monkeypatch.setattr(ms.time, "sleep", lambda s: None)


def _stub(monkeypatch, payload=None, error=None):
    fetch = _Fetch(payload, error)
    monkeypatch.setattr(ms, "_get_json", fetch)
    return fetch


def _named(results, name):
    return next(r for r in results if r.name == name)


class TestPhotonParse:
    def test_first_hit_is_the_portland_donut(self, monkeypatch):
        _stub(monkeypatch, PHOTON)
        results = ms.photon_search("holy don", 43.659, -70.257, 12)
        assert len(results) == len(PHOTON["features"])
        top = results[0]
        assert top.name == "Holy Donut"
        assert top.kind == "house"
        # geometry.coordinates is [lon, lat] — don't swap them
        assert isinstance(top.lat, float) and isinstance(top.lon, float)
        assert (top.lat, top.lon) == (43.6559037, -70.2748563)

    def test_extent_reordered_from_west_north_east_south(self, monkeypatch):
        _stub(monkeypatch, PHOTON)
        top = ms.photon_search("holy don", 43.659, -70.257, 12)[0]
        raw = PHOTON["features"][0]["properties"]["extent"]
        # raw is [W, N, E, S] = [-70.2749308, 43.6559824, -70.2747818,
        # 43.655825] -> (minlon, minlat, maxlon, maxlat) is (W, S, E, N)
        assert top.extent == (raw[0], raw[3], raw[2], raw[1])
        assert top.extent == (-70.2749308, 43.655825, -70.2747818, 43.6559824)
        minlon, minlat, maxlon, maxlat = top.extent
        assert minlat < maxlat and minlon < maxlon

    def test_missing_extent_is_none(self, monkeypatch):
        _stub(monkeypatch, PHOTON)
        results = ms.photon_search("holy don", 43.659, -70.257, 12)
        # the Commercial Street shop is a node: no extent in the response
        assert _named(results, "The Holy Donut").extent is None

    def test_detail_joins_city_state_country(self, monkeypatch):
        _stub(monkeypatch, PHOTON)
        results = ms.photon_search("holy don", 43.659, -70.257, 12)
        assert results[0].detail == "Portland, Maine, United States"

    def test_detail_drops_empty_segments(self, monkeypatch):
        _stub(monkeypatch, PHOTON)
        results = ms.photon_search("holy don", 43.659, -70.257, 12)
        # the Kenyan church has state + country but no city/county:
        # no doubled comma, no leading separator
        church = _named(results, "Don Bosco Holy Cross Catholic Parish Church")
        assert church.detail == "Turkana, Kenya"

    def test_nameless_features_skipped_and_addresses_fall_back(
            self, monkeypatch):
        # hand-built in the documented Photon shape: the captured live
        # response happens to name every feature
        payload = {"type": "FeatureCollection", "features": [
            {"properties": {"type": "house", "housenumber": "12",
                            "street": "Congress Street", "city": "Portland"},
             "geometry": {"coordinates": [-70.25, 43.65]}},
            {"properties": {"type": "street", "city": "Portland"},
             "geometry": {"coordinates": [-70.26, 43.66]}},
            {"properties": {"type": "city", "name": "Portland",
                            "city": "Portland", "state": "Maine"},
             "geometry": {"coordinates": [-70.27, 43.67]}},
        ]}
        _stub(monkeypatch, payload)
        results = ms.photon_search("congress", 43.659, -70.257, 12)
        assert [r.name for r in results] == ["12 Congress Street", "Portland"]
        # the city result must not repeat its own name as its context
        assert results[1].detail == "Maine"

    def test_empty_feature_list(self, monkeypatch):
        _stub(monkeypatch, {"type": "FeatureCollection", "features": []})
        assert ms.photon_search("qqqqzz", 43.659, -70.257, 12) == []


class TestPhotonRequest:
    def test_url_carries_the_bias_parameters(self, monkeypatch):
        fetch = _stub(monkeypatch, PHOTON)
        ms.photon_search("holy don", 43.659, -70.257, 12.7, limit=5)
        url = fetch.urls[0]
        assert url.startswith("https://photon.komoot.io/api?")
        assert "q=holy+don" in url
        assert "lat=43.659" in url and "lon=-70.257" in url
        assert "zoom=12" in url  # truncated to an int
        assert "location_bias_scale=0.5" in url
        assert "limit=5" in url
        assert "linecast/" in fetch.headers[0]["User-Agent"]

    def test_supported_language_is_requested(self, monkeypatch):
        fetch = _stub(monkeypatch, PHOTON)
        ms.photon_search("holy don", 43.659, -70.257, 12, lang="fr")
        assert "lang=fr" in fetch.urls[0]

    def test_unsupported_language_is_omitted(self, monkeypatch):
        # Photon only speaks en/de/fr; asking for es errors instead of
        # falling back, so the parameter is dropped entirely
        fetch = _stub(monkeypatch, PHOTON)
        ms.photon_search("holy don", 43.659, -70.257, 12, lang="es")
        assert "lang=es" not in fetch.urls[0]
        assert "lang=" not in fetch.urls[0]

    def test_transport_error_raises(self, monkeypatch):
        _stub(monkeypatch, error=OSError("no route to host"))
        with pytest.raises(ms.SearchUnavailable):
            ms.photon_search("holy don", 43.659, -70.257, 12)

    def test_garbled_response_raises(self, monkeypatch):
        _stub(monkeypatch, ["not", "a", "feature", "collection"])
        with pytest.raises(ms.SearchUnavailable):
            ms.photon_search("holy don", 43.659, -70.257, 12)


class TestNominatimParse:
    def test_string_coordinates_become_floats(self, cache, no_throttle,
                                              monkeypatch):
        _stub(monkeypatch, NOMINATIM)
        light = ms.nominatim_search("Portland Head Light")[0]
        assert light.name == "Portland Head Light"
        # jsonv2 sends lat/lon as strings: "43.6231093", "-70.2078663"
        assert light.lat == 43.6231093 and light.lon == -70.2078663
        assert isinstance(light.lat, float) and isinstance(light.lon, float)

    def test_kind_is_the_addresstype(self, cache, no_throttle, monkeypatch):
        _stub(monkeypatch, NOMINATIM)
        assert ms.nominatim_search("Portland Head Light")[0].kind == "man_made"

    def test_boundingbox_reordered(self, cache, no_throttle, monkeypatch):
        _stub(monkeypatch, NOMINATIM)
        light = ms.nominatim_search("Portland Head Light")[0]
        raw = NOMINATIM[0]["boundingbox"]
        # raw is ["minlat", "maxlat", "minlon", "maxlon"] as strings ->
        # (minlon, minlat, maxlon, maxlat) is (raw[2], raw[0], raw[3], raw[1])
        assert light.extent == (float(raw[2]), float(raw[0]),
                                float(raw[3]), float(raw[1]))
        assert light.extent == (-70.2079123, 43.6230777,
                                -70.2078207, 43.6231433)
        minlon, minlat, maxlon, maxlat = light.extent
        assert minlat < maxlat and minlon < maxlon

    def test_detail_from_the_address_dict(self, cache, no_throttle,
                                          monkeypatch):
        _stub(monkeypatch, NOMINATIM)
        light = ms.nominatim_search("Portland Head Light")[0]
        # address has road/village/county/state/country; village stands in
        # for city, and the postcode/ISO fields never appear
        assert light.detail == ("Captain Strout Circle, Cape Elizabeth, "
                                "Maine, United States")

    def test_name_falls_back_to_the_display_name(self, cache, no_throttle,
                                                 monkeypatch):
        item = dict(NOMINATIM[0])
        del item["name"]
        _stub(monkeypatch, [item])
        assert ms.nominatim_search("head light")[0].name == \
            "Portland Head Light"

    def test_empty_result_set(self, cache, no_throttle, monkeypatch):
        _stub(monkeypatch, [])
        assert ms.nominatim_search("qqqqzz") == []

    def test_request_shape(self, cache, no_throttle, monkeypatch):
        fetch = _stub(monkeypatch, NOMINATIM)
        ms.nominatim_search("Portland Head Light", lang="de", limit=3)
        url = fetch.urls[0]
        assert url.startswith("https://nominatim.openstreetmap.org/search?")
        assert "format=jsonv2" in url
        assert "addressdetails=1" in url
        assert "limit=3" in url
        assert "accept-language=de" in url
        # the policy requires an identifying agent with a way to reach us
        agent = fetch.headers[0]["User-Agent"]
        assert agent.startswith("linecast/")
        assert "github.com/ashuttl/linecast" in agent


class TestNominatimCache:
    def test_first_call_writes_the_cache_file(self, cache, no_throttle,
                                              monkeypatch):
        _stub(monkeypatch, NOMINATIM)
        ms.nominatim_search("Portland Head Light")
        files = list((cache / "maps" / "search").glob("*.json"))
        assert len(files) == 1
        assert len(files[0].stem) == 12  # md5 prefix
        assert json.loads(files[0].read_text()) == NOMINATIM

    def test_second_call_never_touches_the_network(self, cache, no_throttle,
                                                   monkeypatch):
        fetch = _stub(monkeypatch, NOMINATIM)
        first = ms.nominatim_search("Portland Head Light")
        again = ms.nominatim_search("  portland HEAD light ")  # normalized
        assert fetch.calls == 1
        assert [r.name for r in again] == [r.name for r in first]

    def test_language_gets_its_own_cache_entry(self, cache, no_throttle,
                                               monkeypatch):
        fetch = _stub(monkeypatch, NOMINATIM)
        ms.nominatim_search("Portland Head Light", lang="en")
        ms.nominatim_search("Portland Head Light", lang="de")
        assert fetch.calls == 2

    def test_transport_error_with_warm_cache_serves_the_cache(
            self, cache, no_throttle, monkeypatch):
        path = cache / "maps" / "search"
        path.mkdir(parents=True)
        ms._cache_path("Portland Head Light", "en").write_text(
            json.dumps(NOMINATIM))
        fetch = _stub(monkeypatch, error=OSError("down"))
        results = ms.nominatim_search("Portland Head Light")
        assert [r.name for r in results] == ["Portland Head Light"]
        assert fetch.calls == 0  # fresh cache short-circuits before the wire

    def test_transport_error_with_stale_cache_serves_the_cache(
            self, cache, no_throttle, monkeypatch):
        import os
        import time as real_time

        path = ms._cache_path("Portland Head Light", "en")
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(NOMINATIM))
        old = real_time.time() - 30 * 86400  # well past the 7-day TTL
        os.utime(path, (old, old))
        fetch = _stub(monkeypatch, error=OSError("down"))
        results = ms.nominatim_search("Portland Head Light")
        assert fetch.calls == 1  # tried the wire, fell back to disk
        assert [r.name for r in results] == ["Portland Head Light"]

    def test_transport_error_with_no_cache_raises(self, cache, no_throttle,
                                                  monkeypatch):
        _stub(monkeypatch, error=OSError("down"))
        with pytest.raises(ms.SearchUnavailable):
            ms.nominatim_search("Portland Head Light")


class TestNominatimThrottle:
    @pytest.fixture
    def clock(self, monkeypatch):
        state = {"now": 1000.0, "slept": []}

        def sleep(secs):
            state["slept"].append(secs)
            state["now"] += secs

        monkeypatch.setattr(ms.time, "monotonic", lambda: state["now"])
        monkeypatch.setattr(ms.time, "sleep", sleep)
        monkeypatch.setattr(ms, "_last_hit", 0.0)
        return state

    def test_back_to_back_queries_sleep_the_remainder(self, cache, clock,
                                                      monkeypatch):
        _stub(monkeypatch, NOMINATIM)
        ms.nominatim_search("first query")
        assert clock["slept"] == []  # nothing owed on the first hit
        clock["now"] += 0.2
        ms.nominatim_search("second query")
        assert len(clock["slept"]) == 1
        assert abs(clock["slept"][0] - 0.8) < 1e-9

    def test_a_full_second_apart_never_sleeps(self, cache, clock,
                                              monkeypatch):
        _stub(monkeypatch, NOMINATIM)
        ms.nominatim_search("first query")
        clock["now"] += 1.5
        ms.nominatim_search("second query")
        assert clock["slept"] == []

    def test_cache_hits_are_not_rate_limited(self, cache, clock, monkeypatch):
        fetch = _stub(monkeypatch, NOMINATIM)
        ms.nominatim_search("first query")
        clock["now"] += 0.05
        ms.nominatim_search("first query")  # served from disk
        assert fetch.calls == 1
        assert clock["slept"] == []


class TestFlyToZoom:
    def _result(self, kind="", extent=None):
        return ms.Result("x", "", 43.0, -70.0, kind, extent)

    def test_extent_span_gets_a_quarter_of_padding(self):
        # 43.60 -> 43.70 is 0.1° of latitude; * 1.25 = 0.125
        z = ms.fly_to_zoom(self._result(extent=(-70.3, 43.6, -70.2, 43.7)))
        assert abs(z - 0.125) < 1e-9

    def test_tiny_extent_clamps_up(self):
        # a single building spans ~0.0002° -> 0.00025 padded, below the floor
        z = ms.fly_to_zoom(
            self._result(extent=(-70.2079, 43.62308, -70.2078, 43.62328)))
        assert z == 0.004

    def test_huge_extent_clamps_down(self):
        z = ms.fly_to_zoom(self._result(extent=(-180.0, -85.0, 180.0, 85.0)))
        assert z == 60.0

    def test_extent_wins_over_kind(self):
        # a country-sized kind with a small extent frames the extent
        z = ms.fly_to_zoom(
            self._result("country", extent=(-70.3, 43.6, -70.2, 43.7)))
        assert abs(z - 0.125) < 1e-9

    @pytest.mark.parametrize("kind, expected", [
        ("house", 0.006), ("street", 0.006),
        ("district", 0.03), ("locality", 0.03), ("suburb", 0.03),
        ("neighbourhood", 0.03),
        ("city", 0.08), ("town", 0.08), ("village", 0.08),
        ("county", 0.6), ("state", 4.0), ("country", 20.0),
    ])
    def test_kind_mapping(self, kind, expected):
        assert ms.fly_to_zoom(self._result(kind)) == expected

    def test_unknown_kind_gets_the_town_default(self):
        assert ms.fly_to_zoom(self._result("other")) == 0.08
        assert ms.fly_to_zoom(self._result("")) == 0.08

    def test_real_results_frame_sensibly(self, monkeypatch):
        _stub(monkeypatch, PHOTON)
        results = ms.photon_search("holy don", 43.659, -70.257, 12)
        # the Park Avenue shop has a building-sized extent -> the floor
        assert ms.fly_to_zoom(results[0]) == 0.004
        # the node with no extent falls back to its "house" kind
        assert ms.fly_to_zoom(_named(results, "The Holy Donut")) == 0.006
