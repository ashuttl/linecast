"""Motion surfaces cover the full sphere without fetching or moving its light."""

from dataclasses import replace
import math
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from linecast import _maps_globe as globe
from linecast._maps_camera import MapCamera
from linecast._scenes import Memo


@pytest.fixture
def world(monkeypatch):
    data = {"cities": [[0, 0, 1000000, "A"], [170, -20, 2000000, "B"]], "lakes": []}
    monkeypatch.setattr(globe, "_textures", Memo(keep=2))
    monkeypatch.setattr(globe, "_clouds", Memo(keep=1))
    monkeypatch.setattr(globe, "_SIZE", (16, 8))
    monkeypatch.setattr(globe, "_load_data", lambda: data)
    monkeypatch.setattr(globe, "color_mode", lambda: "truecolor")
    monkeypatch.setattr(globe._globe, "elevation", lambda points, zoom, h:
                        [[100.] * len(row) for row in points])
    monkeypatch.setattr(globe._climate, "grid_for_lls", lambda points:
                        [bytearray(len(row)) for row in points])
    monkeypatch.setattr(globe._globe_now, "peek", lambda: None)
    return data


def _uniform_surface(rgb=(200, 160, 120)):
    texture = globe._Texture(4, 2, (bytes(rgb * 4),) * 2)
    return globe.GlobeSurface(texture, None, None, (), (1, 2, 3), (.2, .2, .2))


def test_bilinear_samples_wrap_the_seam_and_clamp_the_poles():
    first = bytes(channel for value in (0, 40, 120, 200) for channel in (value, 20, 30))
    last = bytes(channel for value in (20, 60, 140, 220) for channel in (value, 40, 50))
    texture = globe._Texture(4, 2, (first, last))
    lls = [[(0, -180), (0, 180), (0, 540), (90, -135), (-90, -135), None]]
    sampled, _ = texture.sample(lls, (1, 2, 3))
    assert sampled[0][:3] == [(110, 30, 40)] * 3
    assert sampled[0][3:] == [(90, 20, 30), (110, 40, 50), (1, 2, 3)]


def test_polar_colour_and_cloud_opacity_converge_independently_of_longitude():
    row = bytes(channel for value in (0, 120, 240, 120) for channel in (value,) * 3)
    texture = globe._Texture(4, 2, (row, row))
    clouds = (bytes((0, 80, 240, 80)),) * 2
    for lat in (-90, -89.999, 89.999, 90):
        points = [[(lat, lon) for lon in (-180, -80, 0, 120, 180)]]
        pixels, opacity = texture.sample(points, (0, 0, 0), clouds)
        assert pixels[0] == [(120, 120, 120)] * 5
        assert opacity[0] == pytest.approx([100 / 255] * 5, abs=.00003)


def test_subpixel_rotation_changes_surface_colour_gradually():
    row = bytes(channel for value in (0, 120, 240, 120) for channel in (value, value, value))
    surface = replace(_uniform_surface(), texture=globe._Texture(4, 2, (row, row)))
    camera = MapCamera(0, -90, 130, 41, 20)
    pixels = [surface.render(replace(camera, lon=camera.lon + delta))[19][20][0]
              for delta in (0, .75, 1.5, 2.25)]
    assert pixels == sorted(pixels)
    assert 0 < pixels[-1] - pixels[0] <= 4
    assert all(b - a <= 2 for a, b in zip(pixels, pixels[1:]))


def test_limb_and_atmosphere_stay_with_the_current_disk_during_rotation():
    surface = _uniform_surface()
    camera = MapCamera(0, 0, 130, 41, 20)
    baseline = surface.render(camera)
    for lat, lon in ((0, 179), (45, -179), (90, 15), (-90, 120)):
        assert surface.render(replace(camera, lat=lat, lon=lon)) == baseline
    assert baseline[19][20][0] > baseline[19][3][0]
    assert baseline[0][0] == surface.background


@pytest.mark.parametrize("lat,lon,zoom", [
    (0, 0, 130), (0, 179.999, 130), (60, -179.999, 130),
    (90, 0, 130), (-90, 170, 130), (-35, 179, 30),
])
def test_every_visible_sample_has_surface_on_previously_unseen_hemispheres(world, lat, lon, zoom):
    source = MapCamera(30, -70, 130, 40, 20)
    surface = globe.prepare_surface(source)
    camera = replace(source, lat=lat, lon=lon, zoom=zoom)
    pixels = surface.render(camera)
    for row, points in zip(pixels, camera.lls(camera.gw, camera.hc * 2)):
        for pixel, ll in zip(row, points):
            assert pixel is not None and len(pixel) == 3
            if ll is not None:
                assert pixel != surface.background


def test_lake_fill_keeps_islands_and_uses_existing_polygon_semantics(world):
    def ring(radius):
        return [(-radius, -radius), (radius, -radius), (radius, radius),
                (-radius, radius), (-radius, -radius)]

    world["lakes"] = [[ring(45), ring(22.5)]]
    water = globe._lake_mask(16, 8)
    assert water[3][6] == 1
    assert water[4][8] == 0
    assert water[0][0] == 0


def test_relief_halo_wraps_longitude_and_crosses_poles_on_the_opposite_meridian():
    padded = globe._halo([[1, 2, 3, 4], [5, 6, 7, 8]])
    assert padded == [[2, 3, 4, 1, 2, 3], [4, 1, 2, 3, 4, 1],
                      [8, 5, 6, 7, 8, 5], [6, 7, 8, 5, 6, 7]]


def test_relief_uses_latitude_dependent_metres(world, monkeypatch):
    received = []

    def paint(elev, bbox, w, h, **kwargs):
        received.append((elev, kwargs["pixel_meters"]))
        return [[(100, 120, 140)] * w for _ in range(h)]

    monkeypatch.setattr(globe._maps_paint, "build_terrain_buffer", paint)
    globe.prepare_surface(MapCamera(0, 0, 130, 40, 20))
    elev, metres = received[0]
    assert (len(elev[0]), len(elev)) == (18, 10)
    assert metres[1][0] < metres[4][0]
    assert metres[1][0] == pytest.approx(22.5 * 111320 * math.cos(math.radians(78.75)))
    assert all(north == 22.5 * 110540 for east, north in metres)


def test_explicit_uniform_pixel_metres_preserve_existing_terrain_shader_output():
    paint = globe._maps_paint.build_terrain_buffer
    elev = [[-100, 20, 180, 80], [0, 50, 300, 100], [10, 100, 400, 200]]
    bbox = (0, -1, 2, 1)
    old = paint(elev, bbox, 4, 3, climate=())
    metres = [(2 * 111320 / 4, 2 * 110540 / 3)] * 3
    assert paint(elev, bbox, 4, 3, climate=(), pixel_meters=metres) == old


def test_static_texture_cache_tracks_style_theme_and_colour_within_its_bound(world, monkeypatch):
    camera = MapCamera(0, 0, 130, 40, 20)
    first = globe.prepare_surface(camera)
    assert globe.prepare_surface(replace(camera, lon=100)).texture is first.texture
    streets = globe.prepare_surface(camera, street=True)
    assert streets.texture is not first.texture
    monkeypatch.setattr(globe._theme, "generation", globe._theme.generation + 1)
    themed = globe.prepare_surface(camera)
    assert themed.texture is not first.texture and len(globe._textures) == 2
    monkeypatch.setattr(globe, "color_mode", lambda: "16")
    assert globe.prepare_surface(camera).texture is not themed.texture
    assert len(globe._textures) == 2


def test_one_texture_is_reused_across_zoom_and_terminal_resize(world):
    camera = MapCamera(0, 0, 130, 120, 38)
    texture = globe.prepare_surface(camera).texture
    for zoom in (130, 45, .0012):
        moved = replace(camera, zoom=zoom, lon=179, gw=200, hc=80)
        assert globe.prepare_surface(moved).texture is texture


def test_production_texture_has_one_fixed_bundled_resolution():
    assert globe._SIZE == (720, 360)
    assert globe._globe._source_zoom(180, globe._SIZE[1] * 2) == 2


def test_street_none_palette_uses_background_and_has_no_city_lights(world, monkeypatch):
    monkeypatch.setattr(globe._maps_style, "palette", lambda: {"water": None, "ground": None})
    surface = globe.prepare_surface(MapCamera(0, 0, 130, 40, 20), street=True, sun=True)
    assert surface.cities == ()
    blank = bytes(surface.background * surface.texture.width)
    assert all(row == blank for row in surface.texture.rgb)


def test_cloud_snapshot_is_reused_during_spin_and_refreshes_only_on_publication(world, monkeypatch):
    canvas, revision, calls = object(), [1], []
    monkeypatch.setattr(globe._globe_now, "peek", lambda: canvas)
    monkeypatch.setattr(globe._globe_now, "revision", lambda: revision[0])

    def clouds(points, source):
        assert source is canvas
        calls.append(True)
        return [[.4] * len(row) for row in points]

    monkeypatch.setattr(globe._globe_now, "clouds", clouds)
    camera = MapCamera(0, 0, 130, 40, 20)
    first = globe.prepare_surface(camera, clouds=True)
    again = globe.prepare_surface(replace(camera, lon=100), clouds=True)
    assert first.clouds is again.clouds and len(calls) == 1
    revision[0] += 1
    refreshed = globe.prepare_surface(camera, clouds=True)
    assert refreshed.clouds is not first.clouds and len(calls) == 2
    assert len(globe._clouds) == 1


def test_render_never_loads_sources_or_reads_live_weather_state(world, monkeypatch):
    canvas = object()
    monkeypatch.setattr(globe._globe_now, "peek", lambda: canvas)
    monkeypatch.setattr(globe._globe_now, "clouds", lambda points, source:
                        [[.4] * len(row) for row in points])
    source = MapCamera(0, 0, 130, 40, 20)
    surface = globe.prepare_surface(source, sun=True, clouds=True)

    def fail(*args, **kwargs):
        pytest.fail("source loading or mutable weather lookup during surface render")

    monkeypatch.setattr(globe, "_load_data", fail)
    monkeypatch.setattr(globe._globe, "elevation", fail)
    monkeypatch.setattr(globe._globe, "_world_canvas", fail)
    monkeypatch.setattr(globe._climate, "_load", fail)
    for name in ("peek", "refresh", "revision", "_noise_grid", "clouds", "subsolar"):
        monkeypatch.setattr(globe._globe_now, name, fail)
    assert surface.render(replace(source, lat=-40, lon=179))
