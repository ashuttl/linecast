"""Retained fills, braille geometry and text follow the same spherical camera."""

from dataclasses import replace
import math
from types import SimpleNamespace

import pytest

from linecast._maps_camera import MapCamera
from linecast._maps_preview import PreparedMap
from linecast._textwidth import visible_len


def source(camera, **extra):
    fills = [[(x, y, 0) for x in range(camera.gw)] for y in range(camera.hc * 2)]
    return PreparedMap(camera, fills, **extra)


def layer(dots, color=(20, 40, 60), ribbon=(), hover=None):
    return SimpleNamespace(dots=dots, color=[[color] * len(row) for row in dots],
                           ribbon=set(ribbon), hover=hover)


def test_identity_reuses_immutable_snapshot_and_hover():
    camera = MapCamera(0, 0, 100, 4, 2)
    fills = [[(1, 2, 3)] * 4 for _ in range(4)]
    dots = [[0, 1, 0, 0], [0] * 4]
    overlays = {(1, 1): ('e\u0301', (3, 2, 1), True)}
    index = object()
    prepared = PreparedMap(camera, fills, layer=layer(dots, hover=index),
                           overlays=overlays, hover=index)
    fills[0][0] = (9, 9, 9)
    dots[0][1] = 255
    overlays.clear()
    assert prepared.fills[0][0] == (1, 2, 3)
    assert prepared.layer.dots[0][1] == 1
    assert prepared.overlays[(1, 1)][0] == 'e\u0301'
    assert prepared.transformed(replace(camera)) is prepared
    assert prepared.hover is index and prepared.layer.hover is index
    with pytest.raises(TypeError):
        prepared.overlays[(1, 1)] = ('x', None)


def test_zoom_scales_subpixels_and_actual_braille_dots():
    camera = MapCamera(0, 0, 100, 4, 2)
    dots = [[0, 128, 0, 0], [0] * 4]
    ink = (12, 34, 56)
    prepared = source(camera, coast=dots, layer=layer(dots, ink, ribbon={(1, 0)}),
                      strokes=(layer(dots, ink),), street=True, coast_ink=ink)
    result = prepared.transformed(replace(camera, zoom=50))
    # One lower-right source dot becomes four geometric dots, not an enlarged
    # braille character or several copies of its original cell mask.
    assert result.coast == ((0, 228, 0, 0), (0, 0, 0, 0))
    assert result.layer.dots == result.coast == result.strokes[0].dots
    assert result.layer.color[0][1] == ink
    assert result.layer.ribbon == {(0, 0), (1, 0)}
    assert result.fills[0][:2] == ((1, 1, 0), (1, 1, 0))
    assert result.street and result.coast_ink == ink


def test_uncolored_braille_survives_resampling():
    camera = MapCamera(0, 0, 100, 4, 2)
    dots = [[0, 128, 0, 0], [0] * 4]
    result = source(camera, layer=layer(dots, None)).transformed(replace(camera, zoom=50))
    assert result.layer.dots[0][1] == 228
    assert result.layer.color[0][1] is None


def test_zoom_out_reports_missing_coverage_as_empty_samples():
    camera = MapCamera(0, 0, 10, 10, 5)
    prepared = source(camera, coast=[[255] * 10 for _ in range(5)])
    result = prepared.transformed(replace(camera, zoom=20))
    assert all(value is None for value in result.fills[0])
    assert result.fills[5][5] is not None
    assert all(value == 0 for value in result.coast[0])


@pytest.mark.parametrize('lat,lon,zoom', [(26.7, -171.1, 111), (80.5, 88.1, 60),
                                       (-18.3, 2.7, .004)])
def test_rotation_matches_direct_spherical_reference(lat, lon, zoom):
    # Close views use nearby source centres so the check includes useful
    # samples rather than merely exercising entirely uncovered geography.
    original = (MapCamera(lat + .0007, lon - .0009, .005, 15, 9)
                if zoom < 1 else MapCamera(20.2, 175.3, 130, 15, 9))
    target = MapCamera(lat, lon, zoom, 15, 9)
    elev = [[y * 15 + x for x in range(15)] for y in range(18)]
    prepared = source(original, elev=elev)
    result = prepared.transformed(target)
    checked = 0
    for y in range(18):
        for x in range(15):
            point = target.unproject(x + .5, y + .5, 15, 18)
            if point is None:
                continue  # camera-space atmosphere is deliberately retained
            plat, plon = point
            expected = None
            if original.visible(plon, plat):
                sx, sy = original.project(plon, plat, 15, 18)
                ix, iy = math.floor(sx), math.floor(sy)
                if 0 <= ix < 15 and 0 <= iy < 18:
                    expected = elev[iy][ix]
                    checked += 1
            assert result.elev[y][x] == expected
    assert checked > 0


def test_newly_visible_hemisphere_is_not_taken_from_the_back_of_source():
    camera = MapCamera(0, 0, 130, 20, 10)
    result = source(camera).transformed(replace(camera, lon=180))
    assert result.fills[10][10] is None


def test_text_keeps_bold_width_and_combining_marks_during_zoom():
    camera = MapCamera(0, 0, 10, 20, 10)
    ink = (10, 20, 30)
    overlays = {(7, 5): ('京', ink, True), (8, 5): ('', None, False),
                (9, 5): ('e\u0301', ink, True), (10, 5): ('x', ink, True)}
    result = source(camera, overlays=overlays).transformed(replace(camera, zoom=5))
    assert dict(result.overlays) == {
        (6, 6): ('京', ink, True), (7, 6): ('', None, False),
        (8, 6): ('e\u0301', ink, True), (9, 6): ('x', ink, True),
    }
    assert sum(visible_len(entry[0]) for entry in result.overlays.values()) == 4


def test_clipped_wide_label_never_leaves_a_continuation():
    camera = MapCamera(0, 0, 10, 20, 10)
    prepared = source(camera, overlays={(0, 5): ('京', None), (1, 5): ('', None)})
    result = prepared.transformed(replace(camera, zoom=9))
    assert not result.overlays


def test_labels_on_new_far_hemisphere_disappear():
    camera = MapCamera(0, 0, 130, 20, 10)
    prepared = source(camera, overlays={(10, 5): ('X', None)})
    assert not prepared.transformed(replace(camera, lon=180)).overlays


def test_zoom_keeps_city_dot_attached_to_its_point_without_scaling_name():
    camera = MapCamera(0, 0, 10, 40, 20)
    overlays = {(12, 10): ('•', None), (13, 10): ('A', None), (14, 10): ('B', None)}
    prepared = source(camera, overlays=overlays)
    target = replace(camera, zoom=5)
    lat, lon = camera.unproject(12.5, 10.5, 40, 20)
    x, y = target.project(lon, lat, 40, 20)
    cell, row = math.floor(x), math.floor(y)
    result = prepared.transformed(target)
    assert dict(result.overlays) == {(cell, row): ('•', None),
                                     (cell + 1, row): ('A', None),
                                     (cell + 2, row): ('B', None)}


def test_primed_preview_never_expands_source_rasters_on_the_foreground(monkeypatch):
    from linecast import _maps_preview

    camera = MapCamera(0, 0, 10, 10, 5)
    dots = [[255] * 10 for _ in range(5)]
    prepared = source(camera, coast=dots, layer=layer(dots, ribbon={(2, 2)}),
                      strokes=(layer(dots),), overlays={(5, 2): ('A', None)})
    assert prepared.prime() is prepared

    def unexpected(*args, **kwargs):
        raise AssertionError('expanding retained geometry on foreground')

    monkeypatch.setattr(_maps_preview, '_expanded', unexpected)
    result = prepared.transformed(replace(camera, zoom=8))
    assert result.coast[2][5] == 255
    assert result.layer.dots[2][5] == result.strokes[0].dots[2][5] == 255


def test_changed_camera_drops_hover_and_resamples_dusk_after_resize():
    camera = MapCamera(0, 0, 10, 10, 5)
    index = object()
    prepared = source(camera, hover=index, layer=layer([[0] * 10 for _ in range(5)],
                                                      hover=index),
                      ink_dusk=[[(.2, .3, .4)] * 10 for _ in range(5)])
    result = prepared.transformed(replace(camera, gw=20, hc=10))
    assert len(result.fills) == 20 and len(result.fills[0]) == 20
    assert len(result.ink_dusk) == 10 and len(result.ink_dusk[0]) == 20
    assert result.ink_dusk[5][10] == (.2, .3, .4)
    assert result.hover is None and result.layer.hover is None


def test_overscan_crop_keeps_exact_pixels_dots_and_whole_text_runs():
    target = MapCamera(32, 14, 10, 20, 10)
    # Width and height padding differ: aspect ratio need not match, only
    # physical pixels per degree. This source has dx=2, dy=3 cell padding.
    padded = replace(target, gw=24, hc=16, zoom=16)
    dots = [[(x + y) % 256 for x in range(24)] for y in range(16)]
    overlays = {(1, 4): ('a', None), (2, 4): ('b', None), (3, 4): ('c', None),
                (5, 4): ('京', (1, 2, 3), True), (6, 4): ('', None, False)}
    prepared = source(padded, coast=dots, layer=layer(dots, ribbon={(2, 3), (0, 0)}),
                      overlays=overlays, elev=[[y * 24 + x for x in range(24)]
                                               for y in range(32)])
    result = prepared.cropped(target)
    assert result.fills[0][0] == (2, 6, 0)
    assert result.fills[-1][-1] == (21, 25, 0)
    assert result.elev[0][0] == 6 * 24 + 2
    assert result.coast[0][0] == dots[3][2]
    assert result.layer.dots == result.coast
    assert result.layer.ribbon == {(0, 0)}
    assert dict(result.overlays) == {(3, 1): ('京', (1, 2, 3), True),
                                     (4, 1): ('', None, False)}
    assert result.transformed(target) is result


def test_overscan_crop_translates_hover_and_removes_hidden_label_interception():
    from linecast._maps_hover import HoverIndex

    target = MapCamera(0, 0, 10, 4, 2)
    padded = replace(target, gw=8, hc=4, zoom=20)
    owner = [[0] * 8 for _ in range(4)]
    index = HoverIndex(owner, {0: ('minor', 'Elm Street')}, {},
                       {(2, 1): ('place', 'Hidden label', 1),
                        (4, 1): ('place', 'Visible label', 2)},
                       [[0] * 8 for _ in range(4)])
    overlays = {(1, 1): ('a', None), (2, 1): ('b', None),
                (4, 1): ('X', None)}
    prepared = source(padded, layer=layer([[0] * 8 for _ in range(4)], hover=index),
                      overlays=overlays, hover=index)
    cropped = prepared.cropped(target)
    assert index.at(2, 1).name == 'Hidden label'  # source stays intact
    road = cropped.hover.at(0, 0)
    assert road.name == 'Elm Street'
    assert set(road.cells) == {(x, y) for x in range(4) for y in range(2)}
    label = cropped.hover.at(2, 0)
    assert label.name == 'Visible label' and label.glyphs == ((2, 0),)
    assert cropped.layer.hover is cropped.hover
    assert cropped.hover.at(-1, 0) is None and cropped.hover.at(4, 0) is None


@pytest.mark.parametrize('changes', [dict(lat=1), dict(lon=1), dict(zoom=11),
                                     dict(gw=9), dict(hc=5), dict(gw=20)])
def test_crop_rejects_noninteger_noncentral_or_rescaled_view(changes):
    camera = MapCamera(0, 0, 10, 10, 6)
    prepared = source(camera)
    with pytest.raises(ValueError, match='crop requires'):
        prepared.cropped(replace(camera, **changes))
