"""Projected vector fills, routes, labels and hover share one camera."""

import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from linecast import _maps_labels, _maps_streets, _maps_style
from linecast._maps_camera import MapCamera
from linecast._radar_basemap import DotLayer
from linecast._vtiles import projector, tiles_for_bbox

from test_maps_streets import EXTENT, classed, polyline, rect, tagged_line, tile


def tile_ll(px, py, z=4, tx=8, ty=5):
    lon = (tx + px / EXTENT) / (1 << z) * 360 - 180
    lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (ty + py / EXTENT) / (1 << z)))))
    return lat, lon


def camera():
    lat, lon = tile_ll(EXTENT / 2, EXTENT / 2)
    return MapCamera(lat, lon, 15, 120, 38)


def test_tile_geometry_uses_camera_instead_of_fetch_bbox():
    view = camera()
    project = projector(4, 8, 5, EXTENT, view.bounds, 240, 152, camera=view)
    for x, y in ((0, 0), (4096, 4096), (1024, 2048), (1024, 0)):
        lat, lon = tile_ll(x, y)
        assert project(x, y) == pytest.approx(view.project(lon, lat, 240, 152))
    # Longitude changes vertical position on a sphere; the former axis
    # cache silently reused the wrong row for these two points.
    assert project(0, 1024)[1] != pytest.approx(project(2048, 1024)[1])


def test_antimeridian_tiles_meet_in_projected_space():
    view = MapCamera(0, 179.9, 2, 120, 38)
    a = projector(1, 1, 0, EXTENT, view.bounds, 240, 152, camera=view)
    b = projector(1, 0, 0, EXTENT, view.bounds, 240, 152, camera=view)
    assert a(EXTENT, EXTENT) == pytest.approx(b(0, EXTENT))


def test_fills_and_hover_register_with_geographic_probe(monkeypatch):
    monkeypatch.setattr(_maps_style, "color_mode", lambda: "truecolor")
    view = camera()
    road = polyline((2600, 2048), (3600, 2048))
    tiles = {(4, 8, 5): tile(
        classed("water", rect(0, 0, 2048, 4096), "lake"),
        tagged_line("transportation", road, {"class": "minor", "name": "Test Road"}),
        tagged_line("transportation_name", road, {"class": "minor", "name": "Test Road"}))}
    fills, layer, _labels = _maps_streets.build_street_view(
        view.bounds, view.gw, view.hc, tiles, 7, camera=view)
    lat, lon = tile_ll(1024, 2048)
    x, y = view.project(lon, lat, view.gw, view.hc * 2)
    assert fills[int(y)][int(x)] == _maps_style.palette()["water"]
    lat, lon = tile_ll(3100, 2048)
    x, y = view.project(lon, lat, view.gw, view.hc)
    assert layer.dots[int(y)][int(x)]
    assert layer.hover.at(int(x), int(y)).name == "Test Road"


def test_marine_region_lookup_inverts_the_same_camera(monkeypatch):
    view = camera()
    calls = []
    monkeypatch.setattr(_maps_labels, "marine_region", lambda lat, lon: calls.append((lat, lon)))
    _maps_labels.marine_backdrop([(10, (10, 5), 4)], view.bounds, 120, 38, camera=view)
    assert calls == [view.unproject(10.5, 5.5, 120, 38)]


def test_source_zoom_uses_centre_scale_and_fetches_conservative_bounds(monkeypatch):
    view = camera()
    scales, bounds = [], []
    monkeypatch.setattr(_maps_streets, "tile_info", lambda: None)
    monkeypatch.setattr(_maps_style, "z_eff", lambda bbox, hc: scales.append(bbox) or 2)
    monkeypatch.setattr(_maps_streets, "tiles_for_bbox", lambda bbox, z: bounds.append(bbox) or [])
    _maps_streets.view_tiles(view.bounds, view.hc, camera=view)
    assert scales == [view.scale_bbox]
    assert bounds == [view.bounds]
    with pytest.raises(ValueError, match="front-facing"):
        _maps_streets.view_tiles(view.bounds, view.hc,
                                 camera=MapCamera(43, 0, 125, 120, 38))


def test_route_lines_wrap_and_clip_before_walking_at_street_scale(monkeypatch):
    view = MapCamera(0, 179.9999, 0.0012, 120, 38)
    layer = DotLayer(view.bounds, 120, 38, camera=view)
    walks = []
    monkeypatch.setattr(layer, "_dot_line", lambda *args: walks.append(args))
    layer._draw_lines([[(179.99, 0), (-179.99, 0)]], (1, 2, 3))
    assert walks
    for x0, y0, x1, y1, _ink, _rank in walks:
        assert 0 <= x0 < 240 and 0 <= x1 < 240
        assert 0 <= y0 < 152 and 0 <= y1 < 152


@pytest.mark.parametrize("gw,hc,lat,lon,zoom", [
    (20, 8, 60, 40, 5), (120, 38, 60, 40, 15),
    (200, 60, -60, 175, 15), (400, 10, 0, -179, 1),
])
def test_local_source_tiles_and_buffers_stay_on_the_visible_hemisphere(
        monkeypatch, gw, hc, lat, lon, zoom):
    view = MapCamera(lat, lon, zoom, gw, hc)
    assert view.local_tiles
    monkeypatch.setattr(_maps_streets, "tile_info", lambda: None)
    _, z, keys = _maps_streets.view_tiles(view.bounds, hc, camera=view)
    for _, tx, ty in keys:
        for x in (tx - .05, tx + 1.05):
            for y in (ty - .05, ty + 1.05):
                phi = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / (1 << z)))))
                lam = x / (1 << z) * 360 - 180
                assert view.visible(lam, phi)


@pytest.mark.parametrize("lon", [-179.9, 179.9])
def test_vector_coverage_includes_both_sides_of_the_dateline(lon):
    view = MapCamera(0, lon, 2, 120, 38)
    keys = tiles_for_bbox(view.bounds, 8)
    assert {0, 255}.issubset({tx for _z, tx, _ty in keys})
