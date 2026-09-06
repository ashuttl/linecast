"""The deeper catalogue must add real stars without moving the bright sky."""

import importlib.util
import math
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from test_sky import LAT, LNG, NIGHT, NOON, _frame
from linecast import _sky_deep, sky
from linecast._sky_catalogue import equatorial_vector


def test_catalogue_is_compact_and_identifies_its_sources():
    records, offsets, histogram = _sky_deep._load()
    assert offsets[-1] == 108520
    assert len(records) == offsets[-1] * 14
    assert sum(histogram[:66]) == 0
    assert _sky_deep.magnitude_at(0) == 6.6
    assert _sky_deep.magnitude_at(10**9) == 12.0
    identifiers = set()
    for zone in range(648):
        previous = 6.5
        for i in range(offsets[zone], offsets[zone + 1]):
            mag, bv, vector, name = _sky_deep.star(i)
            assert previous <= mag <= 12.0
            previous = mag
            assert math.isclose(sum(v * v for v in vector), 1.0)
            assert name not in identifiers
            identifiers.add(name)
    assert 'HIP 87937' in identifiers  # Barnard's star, absent from naked-eye Yale
    assert 'HIP 32349' not in identifiers  # Sirius already belongs to Yale


@pytest.mark.parametrize('ra,dec', [(0, 0), (359.9, -15), (25, 89), (240, -89)])
def test_spatial_query_matches_full_scan_across_wrap_and_poles(ra, dec):
    direction = equatorial_vector(math.radians(ra), math.radians(dec))
    radius, limit = math.radians(6), 9.0
    edge = math.cos(radius)
    expected = set()
    for i in range(_sky_deep._load()[1][-1]):
        mag, _bv, vector, _name = _sky_deep.star(i)
        if mag <= limit and sum(a * b for a, b in zip(direction, vector)) >= edge:
            expected.add(i)
    found = _sky_deep.candidates(direction, radius, limit)
    assert {s[0] for s in found} == expected
    assert [s[1] for s in found] == sorted(s[1] for s in found)


def test_wide_and_daylight_views_do_not_load_deep_stars():
    with patch.object(_sky_deep, '_load', side_effect=AssertionError('loaded deep sky')):
        _frame(NIGHT, 100, 30, view=sky.View(100, 30, 110, 2))
        _frame(NIGHT, 240, 80, view=sky.View(100, 30, 60, 2))
        _frame(NOON, 100, 30, view=sky.View(100, 30, 6, 2))


def test_zoom_in_adds_hoverable_stars():
    view = sky.View(103, 45, 6, 0)
    with patch.object(sky, '_chip', return_value='') as chip:
        _frame(NIGHT, 160, 50, view=view, mouse_pos=(20, 20))
    args = chip.call_args.args
    hits = args[1]
    faint = [hit for hit in hits if hit[2] == 'star' and hit[3][0] < 0]
    bright = [hit for hit in hits if hit[2] == 'star' and hit[3][0] >= 0]
    assert len(faint) >= 10
    assert len(faint) > len(bright) * 3
    sx, sy, kind, payload = faint[len(faint) // 2]
    pointer = (int(sx) + 2, int(sy) // 2 + 1)
    chip_text = sky._chip(pointer, [(sx, sy, kind, payload)], *args[2:])
    assert _sky_deep.star(-payload[0] - 1)[3] in chip_text


def test_zoom_limit_is_continuous_and_twilight_reduces_gain():
    scene = sky.Scene(NIGHT, LAT, LNG)
    assert sky._view_eye_limit(scene, 110) == 6.5
    assert sky._view_eye_limit(scene, 60) == 6.5
    assert sky._view_eye_limit(scene, 6) == 11.5
    scene.darkness = 0.5
    assert sky._view_eye_limit(scene, 6) == 9.0
    scene.darkness = 0
    assert sky._view_eye_limit(scene, 6) == 6.5


def test_missing_supplement_falls_back_without_losing_bright_sky(tmp_path):
    _sky_deep._load.cache_clear()
    _sky_deep._zone.cache_clear()
    try:
        with patch.object(_sky_deep, '_DATA', tmp_path):
            assert _sky_deep.magnitude_at(100) == 6.5
            assert _sky_deep.candidates((1, 0, 0), 0.1, 10) == []
            assert len(sky.stars()) == 8404
    finally:
        _sky_deep._load.cache_clear()
        _sky_deep._zone.cache_clear()


def test_bake_converts_hours_and_excludes_cross_catalogue_duplicates():
    scripts = Path(__file__).resolve().parents[1] / 'scripts'
    if not scripts.exists():
        pytest.skip('bake scripts are excluded from source distributions')
    with patch.object(sys, 'path', [str(scripts), *sys.path]):
        spec = importlib.util.spec_from_file_location('deep_bake', scripts / 'build_deep_stars.py')
        bake = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(bake)
    row = dict(id='1', hip='42', hr='', hd='', ra='6.0', dec='-30', mag='8.34', ci='')
    assert bake.select_star(row, set(), set()) == (90000, -30000, 83, 0, 42)
    assert bake.select_star(dict(row, hr='1'), {'1'}, set()) is None
    assert bake.select_star(dict(row, hd='2'), set(), {'2'}) is None
    assert bake.select_star(dict(row, mag='6.5'), set(), set()) is None
    assert bake.select_star(dict(row, ra='nan'), set(), set()) is None
