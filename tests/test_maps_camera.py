"""One camera must agree across scales, grids, pointers and source coverage."""

import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from linecast import _globe
from linecast._maps_camera import MapCamera


@pytest.mark.parametrize("lat", [-90, -80, 0, 43, 80, 90])
@pytest.mark.parametrize("zoom", [0.0012, 0.1, 2, 30, 125])
def test_screen_geographic_roundtrip_at_every_scale(lat, zoom):
    camera = MapCamera(lat, 179.99, zoom, 120, 38)
    for x, y in ((0.5, 0.5), (60.5, 38.5), (119.5, 75.5), (15.5, 40.5)):
        ll = camera.unproject(x, y, 120, 76)
        if ll is not None:
            assert camera.project(ll[1], ll[0], 120, 76) == pytest.approx((x, y), abs=2e-6)


@pytest.mark.parametrize("lat,lon,zoom", [(0, 0, 125), (43, -70, 30), (80, 179, 0.0012)])
def test_square_sample_grids_match_existing_globe(lat, lon, zoom):
    camera = MapCamera(lat, lon, zoom, 40, 20)
    old, _zs, _rhos = _globe.geometry(lat, lon, zoom, 40, 40)
    new = camera.lls(40, 40)
    for y in (0, 9, 20, 39):
        for x in (0, 9, 20, 39):
            if old[y][x] is None:
                assert new[y][x] is None
            else:
                assert new[y][x] == pytest.approx(old[y][x], abs=1e-8)


def test_labels_fill_and_braille_have_the_same_physical_location():
    camera = MapCamera(43, -70, 2, 120, 38)
    cell = camera.project(-69.6, 43.3, 120, 38)
    fill = camera.project(-69.6, 43.3, 120, 76)
    dot = camera.project(-69.6, 43.3, 240, 152)
    assert fill == pytest.approx((cell[0], cell[1] * 2))
    assert dot == pytest.approx((cell[0] * 2, cell[1] * 4))
    assert camera.unproject(*cell, 120, 38) == pytest.approx((43.3, -69.6))


@pytest.mark.parametrize("lat,lon,zoom", [(0, 179, 2), (70, -179, 12), (43, 0, 30),
                                          (0, 0, 125), (85, 170, 40)])
def test_source_bounds_cover_view_including_dateline_and_limb(lat, lon, zoom):
    camera = MapCamera(lat, lon, zoom, 80, 22)
    lo, south, hi, north = camera.bounds
    for row in camera.lls(40, 22):
        for ll in row:
            if ll is None:
                continue
            phi, lam = ll
            lam = camera.lon + (lam - camera.lon + 180) % 360 - 180
            assert lo - 1e-8 <= lam <= hi + 1e-8
            assert south - 1e-8 <= phi <= north + 1e-8


def test_local_tiles_exclude_limb_and_unsupported_poles():
    assert MapCamera(43, -70, 0.0012, 120, 38).local_tiles
    assert MapCamera(43, -70, 2, 120, 38).local_tiles
    assert not MapCamera(43, -70, 125, 120, 38).local_tiles
    assert not MapCamera(89, 0, 0.0012, 120, 38).local_tiles


def test_camera_keys_do_not_round_away_street_movement():
    a = MapCamera(43, 179, 0.0012, 120, 38)
    b = MapCamera(43.000001, 179, 0.0012, 120, 38)
    c = MapCamera(43, 179, 0.0013, 120, 38)
    assert len({a.key, b.key, c.key}) == 3
    assert MapCamera(43, 539, 0.0012, 120, 38).key == a.key


@pytest.mark.parametrize("zoom", [0.0012, 2, 30, 125])
def test_pan_centres_the_surface_picked_opposite_the_cell_delta(zoom):
    camera = MapCamera(43, 179.99, zoom, 120, 38)
    moved = camera.pan(4, 2)
    expected = camera.unproject(56, 17, 120, 38)
    assert (moved.lat, moved.lon) == pytest.approx(expected)


def test_large_drags_keep_moving_past_the_limb():
    camera = MapCamera(43, 0, 125, 120, 38)
    at_limb = camera.pan(2 * camera.hc / math.radians(camera.zoom), 0)
    beyond = camera.pan(2.2 * camera.hc / math.radians(camera.zoom), 0)
    assert beyond.key != at_limb.key != camera.key
    assert all(math.isfinite(v) for v in (beyond.lat, beyond.lon))
    near = camera.pan((2 + 1e-8) * camera.hc / math.radians(camera.zoom), 0)
    assert (near.lat, near.lon) == pytest.approx((at_limb.lat, at_limb.lon), abs=1e-5)


def test_a_northward_drag_can_cross_a_pole():
    camera = MapCamera(89, 0, 10, 120, 38)
    moved = camera.pan(0, 12)
    assert moved.lat < 89
    assert abs(moved.lon) == pytest.approx(180)
    assert camera.pan(0, 0) is camera


@pytest.mark.parametrize("zoom", [0.0012, 2, 30, 125])
def test_wheel_retains_point_under_pointer_at_all_scales(zoom):
    camera = MapCamera(43, 179.99, zoom, 120, 38)
    col, row = 70.5, 16.5
    anchor = camera.unproject(col, row, 120, 38)
    moved = camera.zoom_at(zoom / 1.4, col, row)
    assert moved.project(anchor[1], anchor[0], 120, 38) == pytest.approx((col, row), abs=1e-6)


def test_zooming_over_space_changes_only_scale():
    camera = MapCamera(43, -70, 125, 120, 38)
    assert camera.unproject(0, 0, 120, 38) is None
    moved = camera.zoom_at(100, 0, 0)
    assert (moved.lat, moved.lon, moved.zoom) == (43, -70, 100)


@pytest.mark.parametrize("args", [(math.nan, 0, 1, 80, 22), (91, 0, 1, 80, 22),
                                   (0, 0, 0, 80, 22), (0, 0, 1, 0, 22)])
def test_invalid_cameras_fail_before_rendering(args):
    with pytest.raises(ValueError):
        MapCamera(*args)


@pytest.mark.parametrize("lon", [-3781, -541, 539, 3779])
def test_camera_normalizes_multiple_turns_without_changing_geography(lon):
    camera = MapCamera(43, lon, 2, 120, 38)
    assert camera.lon == 179
    assert camera.unproject(60, 19, 120, 38) == pytest.approx((43, 179))
