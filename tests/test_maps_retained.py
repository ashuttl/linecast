"""Prepared maps preserve pre-consolidation output and never load during paint."""

from dataclasses import replace
import hashlib
import importlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from linecast import _color, _globe, _globe_now, _maps_style, maps
from linecast._maps_camera import MapCamera
from linecast._maps_hover import Hit
from linecast._runtime import RuntimeConfig


@pytest.fixture
def prepare_frame(monkeypatch):
    calls = []
    monkeypatch.setattr(maps, '_panned_place', lambda *a: 'Test place')
    monkeypatch.setattr(maps, 'ATTRIBUTION', 'WORLD CREDIT')
    # Other tests reload source modules; patch the module the renderer imports.
    monkeypatch.setattr(importlib.import_module('linecast._vtiles'),
                        'attribution_long', lambda: 'LOCAL CREDIT')
    monkeypatch.setattr(_maps_style, 'ATTRIB_TILES_SHORT', 'LOCAL SHORT')
    monkeypatch.setattr(_maps_style, 'use_metric', lambda: False)
    monkeypatch.setattr(maps._builtup, 'enabled', lambda: False)
    monkeypatch.setattr(maps._climate, 'available', lambda: False)
    monkeypatch.setattr(maps._climate, 'grid_for_lls', lambda *a: None)
    monkeypatch.setattr(_globe_now, 'subsolar', lambda: (0.0, 0.0))
    monkeypatch.setattr(_globe_now, 'city_lights_globe', lambda *a: {})
    monkeypatch.setattr(maps, '_get_clouds', lambda *a: calls.append('clouds'))

    def fields(w, h):
        elev = [[100 + x + y for x in range(w)] for y in range(h * 2)]
        fills = [[(30 + x, 60 + y, 90) for x in range(w)] for y in range(h * 2)]
        dots = [[0] * w for _ in range(h)]
        dots[h // 2][w // 2 - 6] = 255
        coast = [[0] * w for _ in range(h)]
        coast[h // 2 - 1][w // 2 - 5] = 31
        ink = (120, 140, 160)
        labels = {(w // 2 - 4, h // 2 - 2): ('京', ink, True),
                  (w // 2 - 3, h // 2 - 2): ('', None, False),
                  (w // 2 - 2, h // 2 - 2): ('e\u0301', ink, True)}
        hover = SimpleNamespace(at=lambda col, row: Hit('Elm Street', 'hov_minor',
                                                        ((w // 2 - 6, h // 2),),
                                                        tuple(labels)))
        layer = SimpleNamespace(dots=dots, color=[[maps.BORDER] * w for _ in range(h)],
                                ribbon={(w // 2 - 6, h // 2)}, hover=hover)
        return elev, fills, coast, layer, labels

    def street(camera, *args, **kwargs):
        w, h = camera.gw, camera.hc
        calls.append('street')
        _, fills, _, layer, labels = fields(w, h)
        if _color.color_mode() in ('16', 'none'):
            fills = [[None] * w for _ in range(h * 2)]
        return fills, layer, labels

    def terrain(camera, *args, **kwargs):
        w, h = camera.gw, camera.hc
        calls.append('terrain')
        elev, _, coast, layer, _ = fields(w, h)
        return maps.TerrainView(elev, coast, None, layer, None)

    def globe(camera):
        w, h = camera.gw, camera.hc
        calls.append('globe')
        elev, _, coast, layer, _ = fields(w, h)
        return SimpleNamespace(elev=elev, coast=coast, borders=layer,
                               shade=[[1.0] * w for _ in range(h * 2)],
                               atmo=[[0.0] * w for _ in range(h * 2)],
                               water=None, cover=None, lls=camera.lls(w, h * 2),
                               glow_lls=None)

    monkeypatch.setattr(maps, '_get_street', street)
    monkeypatch.setattr(maps, '_get_elevation', terrain)
    monkeypatch.setattr(maps, '_get_globe', globe)
    monkeypatch.setattr(maps, '_terrain_buffer',
                        lambda elev, camera, *a, **kw: fields(camera.gw, camera.hc)[1])
    monkeypatch.setattr(maps, 'build_terrain_buffer',
                        lambda elev, bbox, w, spy_h, **kw: fields(w, spy_h // 2)[1])
    monkeypatch.setattr(maps, '_camera_borders', lambda camera: fields(camera.gw, camera.hc)[3])
    monkeypatch.setattr(_globe, 'city_overlays',
                        lambda lat, lon, zoom, w, h, lang: {
                            pos: (entry[0], entry[1]) for pos, entry in fields(w, h)[4].items()})

    def prepare(view='terrain', world=False, sun=False, color='truecolor', camera=None,
                with_route=True):
        monkeypatch.setattr(_color, '_COLOR_MODE', color)
        maps._terrain_cache.clear()
        camera = camera or MapCamera(20, 25, 130 if world else .05, 40, 12)
        runtime = RuntimeConfig(live=False, icons='plain', lang='en', oneline=False)
        # Geographic marks stay separate from prepared cartographic labels.
        def location(x, y):
            return camera.unproject(x, y, camera.gw, camera.hc)

        home = location(camera.gw / 2 - 2.5, camera.hc / 2 + .5)
        origin = location(camera.gw / 2 - .5, camera.hc / 2 - 1.5)
        dest = location(camera.gw / 2 + 2.5, camera.hc / 2 + .5)
        route = (SimpleNamespace(coords=[(home[1], home[0]), (dest[1], dest[0])],
                                 distance_m=1000, duration_s=100, profile='car')
                 if with_route else None)
        options = dict(marker=home, origin=origin, dest=dest, route=route, runtime=runtime,
                       view=view, sun=sun, clouds=sun, mouse_pos=(camera.gw // 2 - 5,
                                                                 camera.hc // 2 + 2))
        prepared = maps.prepare_map(camera, view=view, lang=runtime.lang,
                                    marker=home, route=route, sun=sun, clouds=sun)
        output = maps.render_map(camera, prepared, 'Test place', **options)
        assert calls
        return camera, prepared, output, options

    return prepare


def forbid_preparation(monkeypatch):
    def unexpected(*args, **kwargs):
        raise AssertionError('retained paint attempted preparation')

    for name in ('_get_street', '_get_elevation', '_get_globe', '_get_clouds',
                 '_get_route_layer', '_camera_borders', '_terrain_buffer',
                 'build_terrain_buffer', '_shade_now', '_ink_dusk'):
        monkeypatch.setattr(maps, name, unexpected)
    monkeypatch.setattr(_globe, 'city_overlays', unexpected)
    monkeypatch.setattr(_globe_now, 'city_lights_globe', unexpected)


def test_initial_preview_does_not_decode_climate_or_prepare_sources(monkeypatch):
    forbid_preparation(monkeypatch)
    monkeypatch.setattr(maps._climate, 'available',
                        lambda: pytest.fail('climate decode on initial foreground frame'))
    camera = MapCamera(20, 25, 130, 40, 12)
    output = maps.render_map(camera, None, 'Home')
    assert 'Home' in output and len(output.splitlines()) == 14


@pytest.mark.parametrize('view', ['street', 'terrain'])
@pytest.mark.parametrize('world', [False, True])
@pytest.mark.parametrize('sun', [False, True])
@pytest.mark.parametrize('color', ['truecolor', '256', '16', 'none'])
def test_prepared_frame_matches_frozen_output_without_loading(
        prepare_frame, monkeypatch, view, world, sun, color):
    camera, prepared, _, options = prepare_frame(view, world, sun, color)
    assert prepared.world == world
    assert not any(entry[0] in ('+', '○', '●') for entry in prepared.overlays.values())
    forbid_preparation(monkeypatch)
    actual = maps.render_map(camera, prepared, 'Test place', **options)
    # Captured from d3dfee7 before deleting the duplicate direct renderer.
    frozen = json.loads((Path(__file__).parent / 'snapshots' /
                         'maps_retained_sha256.json').read_text())
    assert hashlib.sha256(actual.encode()).hexdigest() == frozen[
        f'{view},{world},{sun},{color}']


@pytest.mark.parametrize('view', ['street', 'terrain'])
def test_moving_preview_reprojects_fresh_marks_without_loading(prepare_frame, monkeypatch, view):
    camera, prepared, _, options = prepare_frame(view=view, sun=True)
    target = camera.zoom_at(camera.zoom / 1.2)
    seen = []
    composer = maps.compose_map if view == 'street' else maps.compose_terrain

    def inspect(base, fills, overlays, *args, **kwargs):
        seen.append(dict(overlays))
        return composer(base, fills, overlays, *args, **kwargs)

    monkeypatch.setattr(maps, 'compose_map' if view == 'street' else 'compose_terrain', inspect)
    forbid_preparation(monkeypatch)
    maps.render_map(target, prepared, 'Test place', **options)
    assert seen
    for name, glyph in [('origin', '○'), ('dest', '●')]:
        lat, lon = options[name]
        position = _globe.marker_cell(target.lat, target.lon, target.zoom,
                                      target.gw, target.hc, lat, lon)
        assert seen[-1][position][0] == glyph
    assert prepared.camera is camera


def test_world_overscan_crop_keeps_world_credit_at_a_local_target(prepare_frame, monkeypatch):
    target = MapCamera(20, 25, 13, 40, 12)
    padded = replace(target, gw=52, hc=18, zoom=19.5)
    assert target.local_tiles and not padded.local_tiles
    _, prepared, _, options = prepare_frame(view='street', camera=padded, with_route=False)
    exact = prepared.cropped(target)
    assert exact.world and exact.transformed(target).world
    forbid_preparation(monkeypatch)
    output = maps.render_map(target, exact, 'Test place', **options)
    assert 'WORLD CREDIT' in output.splitlines()[-1]
    assert 'LOCAL CREDIT' not in output.splitlines()[-1]


@pytest.mark.parametrize('view', ['street', 'terrain'])
@pytest.mark.parametrize('world', [False, True])
def test_cold_clouds_do_not_hold_back_a_prepared_base_map(
        prepare_frame, monkeypatch, view, world):
    cloud_modes = []

    def cold_clouds(zoom, height, block):
        cloud_modes.append(block)
        return None

    monkeypatch.setattr(maps, '_get_clouds', cold_clouds)
    camera, prepared, live_output, options = prepare_frame(
        view=view, world=world, sun=True)
    assert cloud_modes == [False]
    assert prepared.fills
    assert any(fill is not None for row in prepared.fills for fill in row)

    # Static output still waits for cloud data; an unavailable cloud layer does
    # not remove or otherwise change the already prepared base geography.
    printed = maps.prepare_map(camera, view=view, marker=options['marker'],
                               route=options['route'], sun=True, clouds=True,
                               wait_for_clouds=True)
    printed_output = maps.render_map(camera, printed, 'Test place', **options)
    assert cloud_modes == [False, True]
    assert printed_output == live_output
