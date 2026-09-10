"""Cull invisible sky arcs without changing the original braille raster."""

import math
import random
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from linecast import _color, sky
from linecast._runtime import RuntimeConfig


def _unculled_arc(dots, a, b, cam, f, cx, cy, graph_w, graph_h):
    """Freeze the pre-culling rasterizer to check complete output equivalence.

    Keep this independent of the production culling and sampling code: a
    skipped visible sample, changed step count, or changed rounding must fail.
    """
    pa, pb = sky.project(a, f, cx, cy), sky.project(b, f, cx, cy)
    if pa is None or pb is None:
        return
    length = math.hypot(pb[0] - pa[0], pb[1] - pa[1])
    if length > 6.0 * f:
        return
    steps = max(1, int(length * 2.0))
    u0, u1, u2 = cam[2], cam[5], cam[8]
    ax, ay, az = a
    bx, by, bz = b
    braille = ((0x01, 0x02, 0x04, 0x40), (0x08, 0x10, 0x20, 0x80))
    for i in range(steps + 1):
        t = i / steps
        x, y, z = ax + (bx - ax) * t, ay + (by - ay) * t, az + (bz - az) * t
        n = math.sqrt(x * x + y * y + z * z)
        if n < 1e-9:
            continue
        x, y, z = x / n, y / n, z / n
        if u0 * x + u1 * y + u2 * z < 0.0:
            continue
        k = 2.0 * f / (1.0 + z)
        sx, sy = cx + x * k, cy - y * k
        dx, dy = int(sx * 2.0), int(sy * 2.0)
        col, row = dx >> 1, dy >> 2
        if 0 <= col < graph_w and 0 <= row < graph_h:
            dots[(col, row)] = dots.get((col, row), 0) | braille[dx & 1][dy & 3]


def _unit(vector):
    length = math.sqrt(sum(value * value for value in vector))
    return tuple(value / length for value in vector)


def _assert_same(a, b, cam, width, height, fov, f=None):
    if f is None:
        f = sky.focal_length(width, fov)
    args = a, b, cam, f, width / 2.0, float(height), width, height
    expected, actual = {}, {}
    _unculled_arc(expected, *args)
    sky._plot_arc(actual, *args)
    assert actual == expected
    return actual


@pytest.mark.parametrize("kind", ["outside_view", "below_horizon"])
def test_invisible_arcs_stop_before_projection_or_sampling(kind):
    if kind == "outside_view":
        # Both points are above the horizon but far to the right of a 6° view.
        a, b = (_unit((1.0, 0.0, z)) for z in (0.4, 0.5))
        cam = sky.camera_matrix(0, 90)
    else:
        # Both points project near the center but lie below its horizon.
        a, b = _unit((0.0, -0.2, 1.0)), _unit((0.2, -0.2, 1.0))
        cam = sky.camera_matrix(0, 0)
    dots = {(0, 0): 1}
    with patch.object(sky, "project", side_effect=AssertionError("arc was not culled")):
        sky._plot_arc(dots, a, b, cam, sky.focal_length(118, 6), 59, 40, 118, 40)
    assert dots == {(0, 0): 1}


def test_arc_crossing_view_survives_with_both_endpoints_outside():
    width, height = 118, 40
    f = sky.focal_length(width, 110)
    a = sky.unproject(-5, height, f, width / 2, height)
    b = sky.unproject(width + 5, height, f, width / 2, height)
    dots = _assert_same(a, b, sky.camera_matrix(0, 90), width, height, 110)
    assert len(dots) == width


def test_negative_corner_coordinates_still_round_into_the_first_cell():
    width, height = 118, 40
    f = sky.focal_length(width, 6)
    a = sky.unproject(-0.49, -0.49, f, width / 2, height)
    b = sky.unproject(-0.48, -0.48, f, width / 2, height)
    assert _assert_same(a, b, sky.camera_matrix(0, 90), width, height, 6) == {(0, 0): 1}


def test_near_tangent_horizon_preserves_the_original_rounding():
    # Found by differential fuzzing: both endpoint dot products round below
    # zero, but an interpolated sample can round above it. A strict <0 early
    # rejection dropped a braille cell. Keep the original per-sample decision
    # on every platform, even if its floating-point result differs slightly.
    a = (-0.6821148587810812, 0.6959768385777965, -0.22435587710893906)
    b = (-0.6490376508312155, -0.7240647402809003, 0.23341032471904422)
    cam = (-0.3897935043006232, 0.920902287979045, 0.0,
           0.8764868428932489, 0.37099362486601123, 0.30681353383415544,
           -0.2825452852908099, -0.11959392252007327, 0.9517696441136361)
    with patch.object(sky, "project", wraps=sky.project) as projected:
        _assert_same(a, b, cam, 118, 40, 236, f=17.72538826131303)
    assert projected.call_count == 4  # Both reference and production retained the arc.


@pytest.mark.parametrize("width,height,fov", [
    (20, 6, 6), (78, 24, 110), (118, 40, 6),
    (198, 60, 236), (300, 8, 20), (20, 100, 60),
])
def test_deterministic_arc_equivalence_across_shapes_and_zoom(width, height, fov):
    rng = random.Random(20260908)

    def direction():
        return _unit(tuple(rng.gauss(0, 1) for _ in range(3)))

    for index in range(30):
        cam = sky.camera_matrix(rng.uniform(-720, 720), rng.uniform(-12, 98))
        a, b = direction(), direction()
        _assert_same(a, b, cam, width, height, fov)
        if index < 5:
            _assert_same(a, a, cam, width, height, fov)
            _assert_same(a, tuple(-v for v in a), cam, width, height, fov)
            for sign in (-1, 1):
                noise = direction()
                scale = 10 ** rng.uniform(-13, -3)
                almost = _unit(tuple(sign * v + scale * n for v, n in zip(a, noise)))
                _assert_same(a, almost, cam, width, height, fov)


@pytest.mark.parametrize("size,view", [
    ((120, 40), sky.View(180, 30, 6, 2)),
    ((80, 24), sky.View(359, 90, 110, 2, "chinese")),
    ((80, 24), sky.View(0, 0, 236, 2, "hawaiian")),
])
def test_complete_night_frames_keep_figures_labels_and_colors(size, view):
    runtime = RuntimeConfig(live=True, icons="plain", lang="en", oneline=False)
    now = datetime(2026, 9, 8, 3, tzinfo=timezone.utc)
    with patch.object(sky, "get_terminal_size", return_value=size), \
            patch.object(sky, "install_banner", return_value=""), \
            patch.object(_color, "_COLOR_MODE", "truecolor"):
        with patch.object(sky, "_plot_arc", _unculled_arc):
            expected = sky.render(now, 40.7128, -74.006, runtime, view, fullscreen=True)
        actual = sky.render(now, 40.7128, -74.006, runtime, view, fullscreen=True)
    assert actual == expected
