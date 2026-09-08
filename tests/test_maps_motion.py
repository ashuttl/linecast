"""Map motion keeps its geometry continuous while targets and input change."""

import math
import sys
from dataclasses import replace
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from linecast._geo import wrap_lon
from linecast._maps_camera import MapCamera
from linecast._maps_motion import CameraMotion


def _same_position(a, b):
    assert a.lat == pytest.approx(b.lat, abs=1e-10)
    assert wrap_lon(a.lon - b.lon) == pytest.approx(0, abs=1e-10)
    assert a.zoom == pytest.approx(b.zoom, rel=1e-12)
    assert (a.gw, a.hc) == (b.gw, b.hc)


def _distance(a, b):
    """Angular surface distance, independently measured by haversine."""
    da = math.radians(b.lat - a.lat)
    dl = math.radians(b.lon - a.lon)
    value = (math.sin(da / 2) ** 2 + math.cos(math.radians(a.lat)) *
             math.cos(math.radians(b.lat)) * math.sin(dl / 2) ** 2)
    return 2 * math.asin(math.sqrt(min(1, max(0, value))))


def test_zoom_interpolates_in_log_space_and_crosses_the_short_dateline_path():
    start = MapCamera(20, 170, 64, 118, 40)
    target = replace(start, lat=60, lon=-170, zoom=4)
    motion = CameraMotion(start)
    motion.move(target, now=0)
    middle = motion.sample(motion.duration / 2)
    assert abs(wrap_lon(middle.lon - 180)) < 10
    assert _distance(start, middle) == pytest.approx(_distance(start, target) / 2)
    assert _distance(middle, target) == pytest.approx(_distance(start, target) / 2)
    assert middle.zoom == pytest.approx(math.sqrt(start.zoom * target.zoom))
    assert motion.moving


def test_motion_settles_to_the_exact_target_at_its_deadline():
    start = MapCamera(20, 170, 64, 118, 40)
    target = replace(start, lat=60, lon=-170, zoom=4)
    motion = CameraMotion(start)
    motion.move(target, now=10.0)
    assert motion.sample(10.0 + motion.duration) is target
    assert not motion.moving
    assert motion.sample(1000) is target


def test_first_motion_sample_preserves_the_exact_camera_and_key():
    start = MapCamera(20, 10, 12, 118, 40)
    motion = CameraMotion(start)
    motion.move(replace(start, lat=25, zoom=6), now=10)
    assert motion.sample(10) is start
    assert motion.sample(9) is start


def test_panning_preserves_the_exact_zoom_throughout_motion():
    start = MapCamera(20, 10, 12, 118, 40)
    motion = CameraMotion(start)
    motion.move(replace(start, lat=25), now=0)
    for fraction in (0.1, 0.25, 0.5, 0.75, 0.9):
        assert motion.sample(motion.duration * fraction).zoom == start.zoom


def test_retargeting_and_reversing_start_at_the_current_displayed_position():
    start = MapCamera(20, 10, 20, 118, 40)
    motion = CameraMotion(start)
    motion.move(replace(start, lon=40, zoom=10), now=0)
    displayed = motion.sample(0.1)
    reverse = replace(displayed, lon=-20, zoom=30)
    motion.move(reverse, now=0.1)
    _same_position(motion.sample(0.1), displayed)
    assert motion.sample(0.12).lon < displayed.lon
    assert motion.target is reverse
    assert motion.sample(1) is reverse


def test_immediate_motion_cancels_an_animation_without_a_trailing_settle():
    start = MapCamera(20, 10, 20, 118, 40)
    motion = CameraMotion(start)
    motion.move(replace(start, lon=40), now=0)
    dragged = replace(start, lon=12, lat=21)
    motion.move(dragged, animate=False, now=0.1)
    assert motion.sample(0.1) is dragged
    assert motion.sample(10) is dragged
    assert not motion.moving


def test_an_unchanged_target_does_not_start_an_animation():
    camera = MapCamera(20, 10, 20, 118, 40)
    motion = CameraMotion(camera)
    same = replace(camera)
    motion.move(same, now=2)
    assert motion.sample(2) is same
    assert not motion.moving


def _assert_anchor(camera, ll, anchor):
    lat, lon = ll
    assert camera.project(lon, lat, camera.gw, camera.hc) == pytest.approx(anchor, abs=1e-8)


def test_pointer_anchor_stays_fixed_through_every_zoom_frame():
    start = MapCamera(47, 179.7, 12, 118, 40)
    anchor = (70, 30)
    ll = start.unproject(*anchor, start.gw, start.hc)
    target = start.zoom_at(6, *anchor)
    motion = CameraMotion(start)
    motion.move(target, anchor=anchor, now=0)
    for fraction in (0, 0.1, 0.25, 0.5, 0.75, 0.9, 1):
        _assert_anchor(motion.sample(motion.duration * fraction), ll, anchor)
    assert motion.sample(1) is target


def test_repeated_zoom_at_a_new_pointer_position_preserves_continuity_and_anchor():
    start = MapCamera(47, 179.7, 12, 118, 40)
    motion = CameraMotion(start)
    first_anchor = (70, 30)
    motion.move(start.zoom_at(6, *first_anchor), anchor=first_anchor, now=0)
    now = 0.1
    current = motion.sample(now)
    anchor = (30, 12)
    ll = current.unproject(*anchor, current.gw, current.hc)
    # This is the live wheel contract: build the target from the displayed
    # camera, using the same timestamp for the subsequent retarget.
    target = current.zoom_at(3, *anchor)
    motion.move(target, anchor=anchor, now=now)
    _same_position(motion.sample(now), current)
    for fraction in (0.1, 0.5, 0.9, 1):
        _assert_anchor(motion.sample(now + motion.duration * fraction), ll, anchor)
    assert motion.sample(1) is target


@pytest.mark.parametrize("lat", [-89, 89])
def test_pole_crossing_takes_the_short_surface_path(lat):
    start = MapCamera(lat, 0, 12, 118, 40)
    target = replace(start, lon=180)
    motion = CameraMotion(start)
    motion.move(target, now=0)
    middle = motion.sample(motion.duration / 2)
    assert abs(middle.lat) == pytest.approx(90, abs=1e-10)
    assert _distance(start, middle) == pytest.approx(math.radians(1))
    assert _distance(middle, target) == pytest.approx(math.radians(1))
    for fraction in (.1, .25, .75, .9):
        camera = motion.sample(motion.duration * fraction)
        assert _distance(start, camera) + _distance(camera, target) == pytest.approx(
            math.radians(2))
        assert camera.zoom == start.zoom
    assert motion.sample(motion.duration) is target


def test_deep_street_pan_does_not_lose_tiny_camera_changes():
    start = MapCamera(43, 179.99999, .0012, 118, 40)
    target = replace(start, lat=start.lat + .000001, lon=start.lon + .000001)
    motion = CameraMotion(start)
    motion.move(target, now=0)
    middle = motion.sample(motion.duration / 2)
    assert middle.lat == pytest.approx(start.lat + .0000005, abs=1e-11)
    assert middle.lon == pytest.approx(start.lon + .0000005, abs=1e-11)
    assert middle.zoom == start.zoom


def test_centre_zoom_keeps_its_exact_geographic_position():
    start = MapCamera(43.68, -70.37, 12, 118, 40)
    motion = CameraMotion(start)
    motion.move(replace(start, zoom=6), now=0)
    for fraction in (.1, .25, .5, .75, .9):
        camera = motion.sample(motion.duration * fraction)
        assert (camera.lat, camera.lon) == (start.lat, start.lon)


def test_an_antipodal_reset_has_a_finite_deterministic_surface_path():
    start = MapCamera(43, 0, 12, 118, 40)
    target = replace(start, lat=-43, lon=180)
    motion = CameraMotion(start)
    motion.move(target, now=0)
    middle = motion.sample(motion.duration / 2)
    assert all(math.isfinite(v) for v in (middle.lat, middle.lon))
    assert _distance(start, middle) == pytest.approx(math.pi / 2)
    assert _distance(middle, target) == pytest.approx(math.pi / 2)
    assert motion.sample(motion.duration / 2) == middle
    assert motion.sample(motion.duration) is target
