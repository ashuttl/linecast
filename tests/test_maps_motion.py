"""The arithmetic a map in motion moves along: the flight path, the
easing, and the window's width in longitude."""

import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from linecast._maps import motion as mm
from linecast.radar.render import bbox_for

GW, HC = 40, 12


class TestEase:
    def test_it_starts_and_ends_at_rest(self):
        assert mm.ease_in_out(0.0) == 0.0
        assert mm.ease_in_out(1.0) == 1.0
        assert mm.ease_in_out(0.5) == pytest.approx(0.5)
        # flat at both ends: the first and last tenths move least
        steps = [mm.ease_in_out(k / 10) for k in range(11)]
        gaps = [b - a for a, b in zip(steps, steps[1:])]
        assert gaps[0] < gaps[len(gaps) // 2] > gaps[-1]

    def test_it_never_overshoots(self):
        assert all(0.0 <= mm.ease_in_out(k / 50) <= 1.0 for k in range(51))


class TestLongitude:
    def test_the_short_way_round(self):
        assert mm.lon_delta(170.0, -170.0) == pytest.approx(20.0)
        assert mm.lon_delta(-170.0, 170.0) == pytest.approx(-20.0)
        assert mm.lon_delta(0.0, 10.0) == pytest.approx(10.0)

    def test_the_span_is_the_renderers_own(self):
        # not a 2:1 cell assumed here and a bbox computed there: the
        # camera and the renderer must agree or the map slides
        for lat, zoom in ((0.0, 2.0), (60.0, 0.05), (-45.0, 30.0)):
            minlon, _, maxlon, _ = bbox_for(lat, -70.0, zoom, GW, HC)
            assert mm.lon_span(lat, zoom, GW, HC) == pytest.approx(
                maxlon - minlon)

    def test_the_span_widens_toward_the_pole(self):
        assert (mm.lon_span(60.0, 2.0, GW, HC)
                > mm.lon_span(0.0, 2.0, GW, HC))


class TestFlight:
    def test_the_ends_are_exact(self):
        f = mm.Flight(43.68, -70.37, 0.05, 43.66, -70.25, 0.02)
        assert f.at(0.0) == (43.68, -70.37, 0.05)
        assert f.at(f.duration) == (43.66, -70.25, 0.02)
        assert f.at(f.duration + 5.0) == (43.66, -70.25, 0.02)

    def test_a_hop_rises_to_see_both_ends_then_settles(self):
        f = mm.Flight(43.68, -70.37, 0.05, 44.0, -71.0, 0.05)
        peak = max(f.at(f.duration * k / 20)[2] for k in range(21))
        assert peak > 0.05
        assert peak < 2.0   # but not to the planet for a short hop
        mid = f.at(f.duration / 2)
        assert 43.68 < mid[0] < 44.0

    def test_a_long_flight_goes_up_to_the_globe(self):
        f = mm.Flight(51.5, -0.1, 0.05, 35.7, 139.7, 0.05)
        peak = max(f.at(f.duration * k / 40)[2] for k in range(41))
        assert peak > 45.0
        assert f.duration == mm.FLIGHT_MAX

    def test_a_short_hop_still_reads_as_motion(self):
        f = mm.Flight(43.68, -70.37, 0.05, 43.6801, -70.3701, 0.05)
        assert f.duration == mm.FLIGHT_MIN

    def test_a_pure_zoom_is_exponential(self):
        f = mm.Flight(10.0, 20.0, 1.0, 10.0, 20.0, 4.0)
        lat, lon, zoom = f.at(f.duration / 2)
        assert (lat, lon) == (10.0, 20.0)
        assert zoom == pytest.approx(2.0)
        assert f.duration >= mm.FLIGHT_MIN

    def test_the_longitude_takes_the_short_way_round(self):
        f = mm.Flight(0.0, 170.0, 1.0, 0.0, -170.0, 1.0)
        _lat, lon, _zoom = f.at(f.duration / 2)
        assert abs(abs(lon) - 180.0) < 1e-6
        # and every step stays inside the wrapped range
        lons = [f.at(f.duration * k / 20)[1] for k in range(21)]
        assert all(-180.0 <= v <= 180.0 for v in lons)

    def test_position_and_zoom_move_monotonically_on_a_pure_pan(self):
        f = mm.Flight(0.0, 0.0, 1.0, 0.0, 5.0, 1.0)
        lons = [f.at(f.duration * k / 30)[1] for k in range(31)]
        assert lons == sorted(lons)
        zooms = [f.at(f.duration * k / 30)[2] for k in range(31)]
        top = zooms.index(max(zooms))
        assert zooms[:top + 1] == sorted(zooms[:top + 1])
        assert zooms[top:] == sorted(zooms[top:], reverse=True)
        assert math.isclose(zooms[0], zooms[-1])

    def test_the_duration_is_bounded_at_both_ends(self):
        for args in ((0.0, 0.0, 1.0, 0.0, 0.0001, 1.0),
                     (0.0, 0.0, 0.01, 60.0, 179.0, 0.01),
                     (0.0, 0.0, 130.0, 0.0, 0.0, 0.0012)):
            f = mm.Flight(*args)
            assert mm.FLIGHT_MIN <= f.duration <= mm.FLIGHT_MAX
