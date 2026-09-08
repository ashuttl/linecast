"""Fast local previews must stay within a fraction of one geometric dot."""

from dataclasses import replace
import math

import pytest

from linecast._maps_camera import MapCamera
from linecast._maps_preview import _Warp, _radii


@pytest.mark.parametrize('gw,hc', [(120, 38), (200, 58)])
@pytest.mark.parametrize('lat,zoom', [(0, 1), (43, .01), (80, .0012), (-80, .0012)])
@pytest.mark.parametrize('scale', [.7, 1, 1.3])
def test_local_affine_stays_below_a_twentieth_dot_everywhere(gw, hc, lat, zoom, scale):
    base = MapCamera(lat, 179.999, zoom, gw, hc)
    source = replace(base, gw=gw + 2 * (gw // 4), hc=hc + 2 * (hc // 4),
                     zoom=zoom * (hc + 2 * (hc // 4)) / hc)
    target = replace(base.pan(8, 3), zoom=zoom * scale)
    warp = _Warp(source, target)
    assert warp.affine is not None
    ax, ay, du, dv = warp.affine
    sw, sh, w, h = source.gw * 2, source.hc * 4, gw * 2, hc * 4
    sr_x, sr_y = _radii(source, sw, sh)
    tr_x, tr_y = _radii(target, w, h)
    for j in range(13):
        y = h * j / 12
        for i in range(13):
            x = w * i / 12
            # The independent camera roundtrip includes corners and edges,
            # not just sample centers; the production bound covers all of them.
            lat, lon = target.unproject(x, y, w, h)
            sx, sy = source.project(lon, lat, sw, sh)
            u, v = (x - w / 2) / tr_x, (h / 2 - y) / tr_y
            approx_x = sw / 2 + sr_x * (ax * u + du)
            approx_y = sh / 2 - sr_y * (ay * v + dv)
            dx, dy = sx - approx_x, sy - approx_y
            assert math.hypot(dx, dy) < .05
            # The same registration bound also holds after enlarging source
            # dots into the target, so wheel zoom cannot magnify the error.
            assert math.hypot(dx * tr_x / (sr_x * ax),
                              dy * tr_y / (sr_y * ay)) < .05


@pytest.mark.parametrize('camera,delta', [
    (MapCamera(89, 0, .0012, 120, 38), (1, 1)),
    (MapCamera(43, 0, 130, 120, 38), (1, 1)),
    (MapCamera(43, 0, 5, 400, 10), (1, 1)),
    (MapCamera(80, 0, 1, 200, 58), (20, 4)),
    (MapCamera(43, 0, 5, 200, 58), (20, 4)),
])
def test_poles_globes_and_excessive_curvature_keep_exact_rotation(camera, delta):
    warp = _Warp(camera, camera.pan(*delta))
    assert not warp.centered
    assert warp.affine is None


def test_affine_never_uses_source_back_hemisphere():
    camera = MapCamera(43, 0, .01, 120, 38)
    warp = _Warp(camera, replace(camera, lat=-43, lon=180))
    assert warp.affine is None


def test_local_sampling_uses_separable_rows_without_a_pixel_mapping(monkeypatch):
    camera = MapCamera(43, -70, .01, 120, 38)
    warp = _Warp(camera, camera.pan(4, 2))
    assert warp.affine is not None

    def unexpected(*args):
        raise AssertionError('full per-pixel spherical mapping on local preview')

    monkeypatch.setattr(warp, 'mapping', unexpected)
    grid = tuple(tuple((x, y) for x in range(120)) for y in range(76))
    result = warp.sample(grid, 120, 76)
    xs, ys = warp.axes(120, 76, 120, 76)
    for y, row in enumerate(result):
        for x, value in enumerate(row):
            expected = (grid[ys[y]][xs[x]] if 0 <= xs[x] < 120 and 0 <= ys[y] < 76
                        else None)
            assert value == expected
