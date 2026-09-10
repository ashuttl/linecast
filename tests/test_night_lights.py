"""Satellite light geography, footprint filtering, and offline fallback."""

import math

import pytest

from linecast import _globe, _globe_now, _night_lights


def test_bundled_raster_locates_cities_and_keeps_remote_ground_dark():
    levels = _night_lights.load()
    assert len(levels) == 7
    for lat, lon in ((40.7, -74), (51.5, -.1), (35.7, 139.7)):
        assert _night_lights._bilinear(levels[0], lat, lon) > 150
    for lat, lon in ((75, -40), (-80, 0), (0, -130), (24, 15)):
        assert _night_lights._bilinear(levels[0], lat, lon) < 5
    assert all(0 <= v <= 255 for _, _, pixels in levels for v in pixels)


def test_coarse_levels_preserve_mean_instead_of_promoting_peak_light():
    levels = _night_lights.load()
    means = [sum(pixels) / len(pixels) for _, _, pixels in levels]
    assert max(means) - min(means) < .15
    assert max(levels[-1][2]) < max(levels[0][2]) / 4


def test_bilinear_wraps_longitude_and_clamps_latitude():
    level = (4, 2, bytes((0, 40, 120, 200, 20, 60, 140, 220)))
    assert [_night_lights._bilinear(level, 0, lon) for lon in (-180, 180, 540)] == [110]*3
    assert _night_lights._bilinear(level, 90, -135) == 0
    assert _night_lights._bilinear(level, -90, -135) == 20


def test_poles_and_space_have_no_invented_lights():
    points = [[(lat, lon) for lat in (-90, 90) for lon in (-180, -60, 0, 80, 180)] + [None]]
    assert _night_lights.sample(_night_lights.load(), points, 1) == {}


def test_resolution_blend_is_continuous_across_level_boundary():
    levels = ((4, 2, bytes([200]*8)), (2, 1, bytes([20]*2)))
    points = [[(0, 0), None]]
    values = [_night_lights.sample(levels, points, d) for d in (179.99, 180, 180.01)]
    assert all((1, 0) not in value for value in values)
    weights = [v[0, 0] for v in values]
    assert max(weights) - min(weights) < .001


@pytest.mark.parametrize("contents", [None, b"broken raster"])
def test_unavailable_asset_stays_off_without_fetching(monkeypatch, tmp_path, contents):
    path = tmp_path / "night_lights.bin"
    if contents is not None:
        path.write_bytes(contents)
    monkeypatch.setattr(_night_lights, "_PATH", path)
    assert _night_lights.load.__wrapped__() == ()
    assert _night_lights.sample((), [[(0, 0)]], 1) == {}


def test_globe_and_flat_sample_the_same_geographic_source():
    # Odd dimensions put a pixel exactly on the view centre.
    lat, lon, zoom, w, h = 40.7, -74, 10, 21, 21
    globe = _globe_now.city_lights_globe(lat, lon, zoom, w, h)
    flat = _globe_now.city_lights_flat((lon-5, lat-5, lon+5, lat+5), w, h)
    assert globe[10, 10] == pytest.approx(flat[10, 10])
    points, _, _ = _globe.geometry(lat, lon, zoom, w, h)
    assert all(points[y][x] is not None and math.isfinite(v) for (x, y), v in globe.items())


def test_lights_fade_with_source_magnification_without_changing_regional_views():
    levels = ((4, 2, bytes([255] * 8)),)
    points = [[(0, 0)]]
    # This synthetic source has 90-degree texels. The same thresholds
    # apply to the real raster regardless of the terminal's dimensions.
    for degrees in (180, 90, 45):
        assert _night_lights.sample(levels, points, degrees)[0, 0] == 1.0
    fading = [_night_lights.sample(levels, points, d)[0, 0] for d in (44, 30, 20, 16)]
    assert 1 > fading[0] > fading[1] > fading[2] > fading[3] > 0
    assert _night_lights.sample(levels, points, 15) == {}
    assert _night_lights.sample(levels, points, .01) == {}


def test_resolution_fade_has_no_step_at_either_boundary():
    opacity = _night_lights._resolution_opacity
    for boundary in (.5, 1 / 6):
        assert abs(opacity(boundary - 1e-6) - opacity(boundary + 1e-6)) < 1e-9


def test_close_zoom_lights_disappear_in_flat_and_globe_views():
    assert _globe_now.city_lights_globe(53.35, -2, 2.6, 160, 110) == {}
    assert _globe_now.city_lights_flat((-3.3, 52.05, -.7, 54.65), 110, 110) == {}
