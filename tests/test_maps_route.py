"""Tests for the OSRM routing client.

No network: _fetch is patched at the module and the module's `time` is
swapped for a canned clock, so the 1 s throttle is asserted rather than
waited out. The happy path parses tests/fixtures/osrm_route.json — a
real routing.openstreetmap.de/routed-car response for Westbrook ME ->
Portland ME, so an upstream shape change breaks these tests.
"""

import json
import sys
import urllib.error
from pathlib import Path

import pytest

# Ensure the worktree src is preferred over any installed version.
# (No sys.modules purge here: this file is collected after other test
# modules that hold references into already-imported linecast modules.)
_src = str(Path(__file__).resolve().parent.parent / "src")
if _src not in sys.path:
    sys.path.insert(0, _src)

from linecast import _maps_route as mr
from linecast._scenes import Memo

FIXTURES = Path(__file__).resolve().parent / "fixtures"
BODY = json.loads((FIXTURES / "osrm_route.json").read_text())

WESTBROOK = (43.677, -70.371)   # (lat, lon) — the fixture's origin
PORTLAND = (43.661, -70.255)


class _Clock:
    """Stand-in for the module's `time`: canned monotonic readings, and
    every sleep recorded instead of taken."""

    def __init__(self, *readings):
        self._readings = list(readings) or [0.0]
        self.slept = []

    def monotonic(self):
        return self._readings.pop(0) if len(self._readings) > 1 \
            else self._readings[0]

    def sleep(self, seconds):
        self.slept.append(seconds)


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    """Module state is global; every test starts from an empty cache and
    an open throttle gate."""
    monkeypatch.setattr(mr, "_cache", Memo(keep=mr._MAX_CACHED))
    monkeypatch.setattr(mr, "_last_request", 0.0)
    monkeypatch.setattr(mr, "time", _Clock(1000.0))


def _stub(monkeypatch, *answers):
    """Patch _fetch to walk `answers` (a body, or an exception to raise)
    and return the list of URLs it was called with."""
    seen = []
    queue = list(answers)

    def fake_fetch(url, timeout):
        seen.append(url)
        answer = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(mr, "_fetch", fake_fetch)
    return seen


class TestParseFixture:
    def test_totals_and_profile(self, monkeypatch):
        _stub(monkeypatch, BODY)
        r = mr.route("car", WESTBROOK, PORTLAND)
        assert isinstance(r.distance_m, float) and r.distance_m == 11725.0
        assert isinstance(r.duration_s, float) and r.duration_s == 776.9
        assert r.profile == "car"

    def test_coords_are_lon_lat_floats(self, monkeypatch):
        _stub(monkeypatch, BODY)
        r = mr.route("car", WESTBROOK, PORTLAND)
        line = BODY["routes"][0]["geometry"]["coordinates"]
        assert len(r.coords) == len(line) == 443
        # geojson gives [lon, lat]; the Route keeps that order, so the
        # first pair is Main Street Westbrook (-70.370996, 43.677099)
        assert r.coords[0] == (-70.370996, 43.677099)
        assert r.coords[0] == (line[0][0], line[0][1])
        assert r.coords[-1] == (line[-1][0], line[-1][1])
        assert all(isinstance(v, float) for pair in r.coords for v in pair)
        # lon is the negative one in Maine — proof the order isn't swapped
        assert r.coords[0][0] < -70 < 0 < r.coords[0][1]

    def test_steps_flattened_from_legs(self, monkeypatch):
        _stub(monkeypatch, BODY)
        r = mr.route("car", WESTBROOK, PORTLAND)
        legs = BODY["routes"][0]["legs"]
        assert len(legs) == 1 and len(r.steps) == 10 == len(legs[0]["steps"])
        assert r.steps[0] == {"distance_m": 106.9, "name": "Main Street",
                              "ref": "ME 25 Business", "type": "depart",
                              "modifier": "left",
                              "location": (-70.370996, 43.677099)}
        # a ramp has no name upstream; it stays "" rather than None
        assert r.steps[5]["name"] == "" and r.steps[5]["ref"] is None
        assert r.steps[5]["type"] == "on ramp"
        assert r.steps[6]["ref"] == "I 295; US 1"
        assert r.steps[-1]["type"] == "arrive"
        assert all(isinstance(s["distance_m"], float) for s in r.steps)

    def test_every_step_carries_its_maneuver_location(self, monkeypatch):
        # (lon, lat) like coords, so the panel can fly the map to a step
        _stub(monkeypatch, BODY)
        r = mr.route("car", WESTBROOK, PORTLAND)
        for step in r.steps:
            lon, lat = step["location"]
            assert -71 < lon < -70 and 43 < lat < 44
        # the depart maneuver is the first point of the line itself
        assert r.steps[0]["location"] == r.coords[0]

    def test_a_missing_maneuver_location_stays_none(self, monkeypatch):
        body = {"code": "Ok", "routes": [{
            "distance": 1.0, "duration": 1.0,
            "geometry": {"coordinates": [[0.0, 0.0], [1.0, 1.0]]},
            "legs": [{"steps": [{"distance": 1.0,
                                 "maneuver": {"type": "depart"}}]}],
        }]}
        _stub(monkeypatch, body)
        r = mr.route("car", WESTBROOK, PORTLAND)
        assert r.steps[0]["location"] is None


class TestFailureModes:
    def test_code_not_ok_raises_no_route(self, monkeypatch):
        _stub(monkeypatch, {"code": "NoSegment", "message": "no segment"})
        with pytest.raises(mr.NoRoute):
            mr.route("car", WESTBROOK, PORTLAND)

    def test_empty_routes_list_raises_no_route(self, monkeypatch):
        _stub(monkeypatch, {"code": "Ok", "routes": []})
        with pytest.raises(mr.NoRoute):
            mr.route("car", WESTBROOK, PORTLAND)

    def test_no_route_is_not_retried_on_the_fallback(self, monkeypatch):
        # the user's problem, not the server's: asking twice is rude
        seen = _stub(monkeypatch, {"code": "NoRoute"})
        with pytest.raises(mr.NoRoute):
            mr.route("car", WESTBROOK, PORTLAND)
        assert len(seen) == 1

    def test_transport_failure_on_both_hosts_is_unavailable(self, monkeypatch):
        seen = _stub(monkeypatch, urllib.error.URLError("down"))
        with pytest.raises(mr.RouteUnavailable):
            mr.route("car", WESTBROOK, PORTLAND)
        assert len(seen) == 2
        assert "routing.openstreetmap.de/routed-car" in seen[0]
        assert "router.project-osrm.org" in seen[1]

    def test_malformed_body_is_unavailable(self, monkeypatch):
        # code says Ok but the geometry is missing -> not a NoRoute
        _stub(monkeypatch, {"code": "Ok", "routes": [{"distance": 1.0}]})
        with pytest.raises(mr.RouteUnavailable):
            mr.route("car", WESTBROOK, PORTLAND)

    def test_bike_has_no_fallback(self, monkeypatch):
        seen = _stub(monkeypatch, OSError("timed out"))
        with pytest.raises(mr.RouteUnavailable):
            mr.route("bike", WESTBROOK, PORTLAND)
        # project-osrm routes everything with the car dataset, so a bike
        # request must fail rather than silently degrade
        assert len(seen) == 1 and "routed-bike" in seen[0]

    def test_unknown_profile_rejected(self):
        assert mr.PROFILES == ("car", "bike", "foot")
        with pytest.raises(ValueError):
            mr.route("hovercraft", WESTBROOK, PORTLAND)


class TestFallback:
    def test_car_falls_back_to_project_osrm(self, monkeypatch):
        seen = _stub(monkeypatch, urllib.error.URLError("down"), BODY)
        r = mr.route("car", WESTBROOK, PORTLAND)
        assert r.distance_m == 11725.0
        assert len(seen) == 2
        # lon,lat order, primary first
        assert seen[0] == ("https://routing.openstreetmap.de/routed-car"
                           "/route/v1/driving/-70.371,43.677;-70.255,43.661"
                           "?overview=full&geometries=geojson&steps=true")
        assert seen[1] == ("https://router.project-osrm.org"
                           "/route/v1/driving/-70.371,43.677;-70.255,43.661"
                           "?overview=full&geometries=geojson&steps=true")


class TestCache:
    def test_repeat_call_reuses_the_object(self, monkeypatch):
        seen = _stub(monkeypatch, BODY)
        first = mr.route("car", WESTBROOK, PORTLAND)
        assert mr.route("car", WESTBROOK, PORTLAND) is first
        assert len(seen) == 1

    def test_profile_is_part_of_the_key(self, monkeypatch):
        seen = _stub(monkeypatch, BODY)
        mr.route("car", WESTBROOK, PORTLAND)
        mr.route("foot", WESTBROOK, PORTLAND)
        assert len(seen) == 2

    def test_no_route_is_cached_too(self, monkeypatch):
        seen = _stub(monkeypatch, {"code": "NoRoute"})
        for _ in range(3):
            with pytest.raises(mr.NoRoute):
                mr.route("car", WESTBROOK, PORTLAND)
        assert len(seen) == 1

    def test_ninth_route_evicts_the_oldest(self, monkeypatch):
        _stub(monkeypatch, BODY)
        for i in range(9):
            mr.route("car", WESTBROOK, (43.661, -70.255 + i * 0.01))
        assert len(mr._cache) == 8
        # the first insertion (offset 0) is the one that went
        assert ("car", 43.677, -70.371, 43.661, -70.255) not in mr._cache
        assert ("car", 43.677, -70.371, 43.661, -70.245) in mr._cache

    def test_key_rounds_to_five_places(self, monkeypatch):
        seen = _stub(monkeypatch, BODY)
        mr.route("car", WESTBROOK, PORTLAND)
        # a sub-millimetre nudge is the same request
        mr.route("car", (43.6770000004, -70.371), PORTLAND)
        assert len(seen) == 1


class TestThrottle:
    def test_waits_out_the_remainder(self, monkeypatch):
        clock = _Clock(1000.0, 1000.2)
        monkeypatch.setattr(mr, "time", clock)
        _stub(monkeypatch, BODY)
        mr.route("car", WESTBROOK, PORTLAND)
        mr.route("car", PORTLAND, WESTBROOK)
        # second request landed 0.2 s in -> 0.8 s of the 1 s gap is left
        assert clock.slept == pytest.approx([0.8])

    def test_no_wait_when_more_than_a_second_apart(self, monkeypatch):
        clock = _Clock(1000.0, 1002.0)
        monkeypatch.setattr(mr, "time", clock)
        _stub(monkeypatch, BODY)
        mr.route("car", WESTBROOK, PORTLAND)
        mr.route("car", PORTLAND, WESTBROOK)
        assert clock.slept == []

    def test_cache_hit_does_not_wait(self, monkeypatch):
        clock = _Clock(1000.0, 1000.1)
        monkeypatch.setattr(mr, "time", clock)
        _stub(monkeypatch, BODY)
        mr.route("car", WESTBROOK, PORTLAND)
        mr.route("car", WESTBROOK, PORTLAND)
        assert clock.slept == []

    def test_fallback_attempt_is_throttled_too(self, monkeypatch):
        clock = _Clock(1000.0, 1000.0)
        monkeypatch.setattr(mr, "time", clock)
        _stub(monkeypatch, urllib.error.URLError("down"), BODY)
        mr.route("car", WESTBROOK, PORTLAND)
        assert clock.slept == pytest.approx([1.0])


class TestDecodePolyline:
    def test_hand_encoded_pair(self):
        # "IRSI": each value is (delta * 1e5), zig-zagged then +63.
        #   lat +0.00005 -> 5   -> 5 << 1  = 10 -> chr(10 + 63) = 'I'
        #   lon -0.00010 -> -10 -> ~(-20)  = 19 -> chr(19 + 63) = 'R'
        #   lat +0.00010 -> 10  -> 10 << 1 = 20 -> chr(20 + 63) = 'S'
        #   lon +0.00005 -> 5   -> 5 << 1  = 10 -> chr(10 + 63) = 'I'
        assert mr.decode_polyline("IRSI") == [(0.00005, -0.0001),
                                              (0.00015, -0.00005)]

    def test_precision_six_scales_the_same_deltas(self):
        assert mr.decode_polyline("IRSI", precision=6) == [
            (0.000005, -0.00001), (0.000015, -0.000005)]

    def test_empty_string(self):
        assert mr.decode_polyline("") == []

    def test_multi_chunk_value(self):
        # 38.5 -> 3850000 -> <<1 = 7700000; five 5-bit chunks, all but the
        # last flagged with 0x20 — the canonical Google example's first
        # point, (38.5, -120.2), which is also lat-first
        assert mr.decode_polyline("_p~iF~ps|U") == [(38.5, -120.2)]


class TestManeuverGlyph:
    @pytest.mark.parametrize("modifier,glyph", [
        ("uturn", "↺"), ("sharp left", "↰"), ("left", "←"),
        ("slight left", "↖"), ("straight", "↑"), ("slight right", "↗"),
        ("right", "→"), ("sharp right", "↱"),
    ])
    def test_modifiers(self, modifier, glyph):
        assert mr.maneuver_glyph({"type": "turn", "modifier": modifier}) == glyph

    @pytest.mark.parametrize("mtype,glyph", [
        ("depart", "●"), ("arrive", "◆"), ("roundabout", "↻"),
        ("rotary", "↻"), ("roundabout turn", "↻"), ("exit roundabout", "↻"),
        ("exit rotary", "↻"),
    ])
    def test_type_overrides_modifier(self, mtype, glyph):
        # the fixture's depart step carries modifier "left"; the type wins
        assert mr.maneuver_glyph({"type": mtype, "modifier": "left"}) == glyph

    def test_missing_modifier_falls_back_to_straight(self):
        assert mr.maneuver_glyph({"type": "notification"}) == "↑"
        assert mr.maneuver_glyph({"type": "turn", "modifier": None}) == "↑"
        assert mr.maneuver_glyph({}) == "↑"

    def test_over_the_real_fixture_steps(self, monkeypatch):
        _stub(monkeypatch, BODY)
        r = mr.route("car", WESTBROOK, PORTLAND)
        glyphs = [mr.maneuver_glyph(s) for s in r.steps]
        assert glyphs[0] == "●" and glyphs[-1] == "◆"
        assert glyphs[1] == "↰" and glyphs[2] == "→"
        assert all(len(g) == 1 for g in glyphs)
