"""Local raster sources share the continuous camera without wrapping their edges."""

import math
import sys
from dataclasses import replace
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from linecast import _builtup, _elevation, _maps_views
from linecast._maps_camera import MapCamera
from linecast._radar_tiles import _lonlat_to_world
from linecast._scenes import Memo, SceneCache


class SampleCamera:
    def __init__(self, bounds, lls, scale_bbox=None):
        self.bounds = bounds
        self.scale_bbox = bounds if scale_bbox is None else scale_bbox
        self.samples = lls
        self.key = ("samples", bounds)

    def lls(self, w, h):
        assert len(self.samples) == h and all(len(row) == w for row in self.samples)
        return self.samples


def _ll_at(x, y, org_x, org_y, world):
    lon = (org_x + x) / world * 360.0 - 180.0
    lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (org_y + y) / world))))
    return lat, (lon + 180.0) % 360.0 - 180.0


def _terrain_canvas(values, org_x=180, org_y=179, world=360):
    rgba = bytearray()
    for row in values:
        for meters in row:
            value = 0 if meters is None else round((meters + 32768.0) * 256)
            rgba.extend((value >> 16, (value >> 8) & 255, value & 255,
                         0 if meters is None else 255))
    return rgba, len(values[0]), len(values), org_x, org_y, world


def test_elevation_interpolates_decoded_meters_and_keeps_missing_samples():
    canvas = _terrain_canvas([[255.0, 257.0], [355.0, 357.0]])
    middle = _ll_at(1, 1, *canvas[3:])
    camera = SampleCamera((-1, -1, 3, 1), [[middle, None]])
    result = _elevation._resample_camera(canvas, camera.lls(2, 1), camera.bounds)
    assert result[0][0] == pytest.approx(306.0)
    assert result[0][1] is None


@pytest.mark.parametrize("values,expected", [
    ([[100.0, None], [300.0, None]], 200.0),
    ([[None, None], [300.0, 500.0]], 400.0),
    ([[None, None], [None, None]], None),
])
def test_elevation_does_not_blend_transparent_tiles_into_sea_level(values, expected):
    canvas = _terrain_canvas(values)
    ll = _ll_at(1, 1, *canvas[3:])
    result = _elevation._resample_camera(canvas, [[ll]], (-1, -1, 3, 1))[0][0]
    if expected is None:
        assert result is None
    else:
        assert result == pytest.approx(expected)


def _dateline_canvas(terrain):
    # Three local tiles straddle the seam of a 256-tile world. Local width
    # 768 is not a divisor of world width 65536, so modulo-local-width gives
    # the wrong tile instead of disguising the longitude error.
    world, org_x, org_y = 65536, 65024, 32768
    values = [10] * 256 + [20] * 256 + [30] * 256
    if terrain:
        canvas = _terrain_canvas([values], org_x, org_y, world)
    else:
        rgba = bytearray(channel for v in values for channel in (v, v, v, 255))
        canvas = rgba, 768, 1, org_x, org_y, world
    bounds = (177.1875, -0.5, 181.40625, 0.5)
    return canvas, bounds


def test_elevation_unwraps_dateline_by_world_width_and_never_wraps_local_edges():
    canvas, bounds = _dateline_canvas(terrain=True)
    lls = [[_ll_at(x, 0.5, *canvas[3:]) for x in (100.5, 600.5, 767.9, 770.0)]]
    assert lls[0][1][1] < -179  # camera longitude wrapped to the western hemisphere
    result = _elevation._resample_camera(canvas, lls, bounds)[0]
    assert result == pytest.approx([10.0, 30.0, 30.0, None])


def test_camera_elevation_uses_inverse_points_and_coverage_not_a_flat_bbox(monkeypatch):
    camera = MapCamera(45, 0, 20, 6, 2)
    canvas = _terrain_canvas([[float(x + 10 * y) for x in range(256)]
                             for y in range(256)], 0, 0, 256)
    calls = []

    def stitch(_fetch, bounds, z):
        calls.append((bounds, z))
        return canvas

    monkeypatch.setattr(_elevation, "stitch_xyz", stitch)
    result = _elevation._resample((-1, -1, 1, 1), 6, 4, 0, 15, camera=camera)
    assert calls == [(camera.bounds, 0)]
    for row, points in zip(result, camera.lls(6, 4)):
        for value, (lat, lon) in zip(row, points):
            wx, wy = _lonlat_to_world(lon, lat)
            assert value == pytest.approx((wx * 256 - 0.5) + 10 * (wy * 256 - 0.5))


def test_bathymetry_and_fine_elevation_use_the_same_camera(monkeypatch):
    camera = SampleCamera((179, 0, 181, 1), [[None] * 4], (0, 0, 0.001, 0.001))
    zoom_calls, sample_calls = [], []
    monkeypatch.setattr(_elevation, "_pick_zoom",
                        lambda bbox, w, cap: zoom_calls.append((bbox, w, cap)) or 11)

    def sample(bbox, w, h, z, timeout, camera=None):
        sample_calls.append((bbox, w, h, z, timeout, camera))
        return [[0.0, 20.0, None, -5.0] if z == 12 else [-100.0, -200.0, -300.0, -20.0]]

    monkeypatch.setattr(_elevation, "_resample", sample)
    result = _elevation.elevation_grid(camera.bounds, 4, 1, timeout=7, camera=camera)
    assert result == [[-100.0, 20.0, -300.0, -20.0]]
    assert zoom_calls == [(camera.scale_bbox, 4, _elevation.MAX_ZOOM)]
    assert [call[3] for call in sample_calls] == [12, _elevation.BATHY_ZOOM]
    assert all(call[-1] is camera and call[4] == 7 for call in sample_calls)


def test_builtup_samples_the_correct_local_tile_across_the_dateline(monkeypatch):
    canvas, bounds = _dateline_canvas(terrain=False)
    camera = SampleCamera(bounds, [[_ll_at(600.5, 0.5, *canvas[3:])]])
    calls = []
    monkeypatch.setattr(_builtup, "stitch_xyz",
                        lambda fetch, bbox, z: calls.append(bbox) or canvas)
    assert _builtup.builtup_grid((-1, -1, 1, 1), 1, 1, camera=camera) == [[30]]
    assert calls == [bounds]


def test_builtup_smoothing_does_not_spill_into_space(monkeypatch):
    canvas, bounds = _dateline_canvas(terrain=False)
    ll = _ll_at(600.5, 0.5, *canvas[3:])
    camera = SampleCamera(bounds, [[ll, None, ll]])
    monkeypatch.setattr(_builtup, "stitch_xyz", lambda *args: canvas)
    assert _builtup.builtup_grid(bounds, 3, 1, camera=camera) == [[15, 0, 15]]


def test_terrain_loader_passes_one_camera_to_every_source(monkeypatch):
    camera = MapCamera(45, 179.9, 0.01, 2, 1)
    calls = []
    monkeypatch.setattr(_maps_views, "_elev_cache", SceneCache())

    def water(bbox, w, h, camera=None):
        calls.append(("water", w, h, camera))
        return None, None, None, None

    def builtup(bbox, w, h, camera=None):
        calls.append(("builtup", w, h, camera))
        return None

    def elevation(bbox, w, h, camera=None):
        calls.append(("elevation", w, h, camera))
        return [[100.0] * w for _ in range(h)]

    monkeypatch.setattr(_maps_views, "_tile_water", water)
    monkeypatch.setattr(_maps_views, "_builtup_layer", builtup)
    monkeypatch.setattr(_maps_views, "elevation_grid", elevation)
    terrain = _maps_views._get_elevation(camera.bounds, 2, 1, True, camera=camera)
    assert terrain.elev == [[100.0, 100.0], [100.0, 100.0]]
    assert {(name, w, h) for name, w, h, _ in calls} == {
        ("water", 2, 1), ("builtup", 2, 1), ("elevation", 4, 4)}
    assert all(call[-1] is camera for call in calls)


def test_scene_keys_distinguish_sub_rounding_camera_moves(monkeypatch):
    camera = MapCamera(45, 1.00001, 1.00001, 4, 2)
    moved = replace(camera, lon=camera.lon + 1e-8, zoom=camera.zoom + 1e-8)
    assert _maps_views._view_key(camera.bounds, 4, 2, camera) != (
        _maps_views._view_key(camera.bounds, 4, 2, moved))
    keys = []

    class Cache:
        def get(self, key, block, load):
            keys.append(key)
            return "kept"

    monkeypatch.setattr(_maps_views, "_globe_cache", Cache())
    for cam in (camera, moved):
        assert _maps_views._get_globe(cam.lat, cam.lon, cam.zoom, 4, 2, True,
                                     camera=cam) == "kept"
    assert keys[0] != keys[1]


def test_terrain_shading_uses_center_scale_and_exact_camera_key(monkeypatch):
    camera = MapCamera(45, 1, 10, 4, 2)
    moved = replace(camera, lon=camera.lon + 1e-8)
    calls, climate_calls = [], []
    monkeypatch.setattr(_maps_views, "_terrain_cache", Memo())
    families = [bytearray(4) for _ in range(4)]
    monkeypatch.setattr(_maps_views._climate, "grid_for_lls",
                        lambda lls: climate_calls.append(lls) or families)
    monkeypatch.setattr(_maps_views, "build_terrain_buffer",
                        lambda elev, bbox, *args, **kwargs:
                        calls.append((bbox, kwargs["climate"])) or object())
    first = _maps_views._terrain_buffer([], camera.bounds, 4, 2, camera=camera)
    again = _maps_views._terrain_buffer([], camera.bounds, 4, 2, camera=camera)
    other = _maps_views._terrain_buffer([], camera.bounds, 4, 2, camera=moved)
    assert first is again and first is not other
    assert calls == [(camera.scale_bbox, families), (moved.scale_bbox, families)]
    assert climate_calls == [camera.lls(4, 4), moved.lls(4, 4)]


def test_missing_camera_climate_disables_flat_bbox_fallback(monkeypatch):
    camera = MapCamera(45, 1, 10, 4, 2)
    monkeypatch.setattr(_maps_views, "_terrain_cache", Memo())
    monkeypatch.setattr(_maps_views._climate, "grid_for_lls", lambda lls: None)
    received = []
    monkeypatch.setattr(_maps_views, "build_terrain_buffer",
                        lambda *args, **kwargs: received.append(kwargs) or object())
    _maps_views._terrain_buffer([], camera.bounds, 4, 2, camera=camera)
    assert received == [{"climate": ()}]


def test_street_loader_passes_the_camera_through_data_and_paint(monkeypatch):
    camera = MapCamera(45, 1, 0.01, 4, 2)
    seen = []
    monkeypatch.setattr(_maps_views, "_street_cache", SceneCache())

    def tiles(bbox, h, camera=None):
        seen.append(camera)
        return 20, 13, [(13, 1, 2)]

    def build(*args, camera=None):
        seen.append(camera)
        return "fills", "lines", "labels"

    def builtup(*args, camera=None):
        seen.append(camera)
        return None

    monkeypatch.setattr(_maps_views._maps_streets, "view_tiles", tiles)
    monkeypatch.setattr(_maps_views._maps_streets, "fetch_tiles", lambda keys: {keys[0]: object()})
    monkeypatch.setattr(_maps_views._maps_streets, "build_street_view", build)
    monkeypatch.setattr(_maps_views, "_builtup_layer", builtup)
    assert _maps_views._get_street(camera.bounds, 4, 2, True, camera=camera) == (
        "fills", "lines", "labels")
    assert len(seen) == 3 and all(value is camera for value in seen)
