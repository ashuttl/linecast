"""Extended light stays positioned in the sky and usable through search."""

import math
from unittest.mock import patch

from test_sky import LAT, LNG, NIGHT, NOON, _frame, _runtime
from linecast import _sky_objects, sky
from linecast._graphics import Framebuffer
from linecast._sky_search import search, targets


def _object(ident):
    return next(r for r in _sky_objects.objects() if r['id'] == ident)


def _paint(record, fov=6, moment=NIGHT, altitude=None):
    scene = sky.Scene(moment, LAT, LNG)
    alt, az = sky.alt_az_of(sky._mat_apply(scene.horizontal, record['at']))
    cam = sky.camera_matrix(az, alt if altitude is None else altitude)
    frame = sky._mat_mul(cam, scene.horizontal)
    fb = Framebuffer(160, 50, bg_color=(0, 0, 0))
    with patch.object(_sky_objects, 'objects', return_value=[record]):
        labels, hits = _sky_objects.paint(fb, scene, cam, frame,
                                         sky.focal_length(160, fov), 80, 50, 12, (160, 160, 160))
    return fb, labels, hits


def test_catalogue_has_real_extents_and_local_names():
    assert len(_sky_objects.objects()) == 107
    m31 = _object('M31')
    assert math.isclose(m31['ra'], 10.6751)
    assert m31['size'] == [190, 60]
    assert m31['pa'] == 37.7
    assert _sky_objects.object_name(m31, 'fr') == "Galaxie d'Andromède"
    assert _sky_objects.object_name(m31, 'th') == 'Andromeda Galaxy'
    assert _object('M42')['name'] == 'Orion Nebula'
    assert _object('M45')['type'] == 'oc'


def test_search_finds_objects_by_name_and_catalogue_and_frames_them():
    pool = targets(_runtime())
    for query in ('M31', 'M 31', 'Messier 31', 'NGC 224', 'Andromeda Galaxy'):
        target = search(query, pool)[0]
        assert target.kind == 'deep_sky' and target.key['id'] == 'M31'
        assert 6 <= target.fov(110) <= 10
        alt, az = target.place(sky.Scene(NIGHT, LAT, LNG))
        assert alt > 0 and 0 <= az < 360
    assert search("Galaxie d'Andromède", targets(_runtime(lang='fr')))[0].key['id'] == 'M31'
    assert search('Orion', pool)[0].kind == 'constellation'
    assert search('Orion Nebula', pool)[0].kind == 'deep_sky'


def test_andromeda_is_extended_and_grows_with_zoom():
    wide, labels, hits = _paint(_object('M31'), fov=30)
    close, _, _ = _paint(_object('M31'), fov=6)
    def count(fb):
        return sum(pixel != (0, 0, 0) for row in fb.fb for pixel in row)

    assert count(close) > count(wide) * 10
    assert labels and hits
    assert all(hit[2] == 'deep_sky' for hit in hits)
    assert 0 < max(max(pixel) for row in close.fb for pixel in row) < 100


def test_open_cluster_is_not_painted_as_nebulosity():
    # Pleiades is below the horizon at NIGHT; choose a moment it is up.
    from datetime import timedelta
    fb, labels, hits = _paint(_object('M45'), moment=NIGHT + timedelta(hours=4))
    assert labels and hits
    assert all(pixel == (0, 0, 0) for row in fb.fb for pixel in row)


def test_daylight_and_below_horizon_hide_extended_objects():
    fb, labels, hits = _paint(_object('M31'), moment=NOON)
    assert not labels and not hits
    assert all(pixel == (0, 0, 0) for row in fb.fb for pixel in row)
    # Orion is still below the horizon at this evening's test moment.
    _, labels, hits = _paint(_object('M42'))
    assert not labels and not hits


def test_glow_is_clipped_at_horizon():
    record = dict(_object('M31'))
    scene = sky.Scene(NIGHT, LAT, LNG)
    # Place a broad test object one degree above a level east horizon.
    record['at'] = sky._mat_apply(sky._mat_transpose(scene.horizontal),
                                 sky.horizontal_vector(90, 1))
    record['size'] = [600, 600]
    record.pop('pa')
    fb, _, hits = _paint(record, fov=30, altitude=0)
    assert hits
    assert any(pixel != (0, 0, 0) for row in fb.fb[:50] for pixel in row)
    assert all(pixel == (0, 0, 0) for row in fb.fb[50:] for pixel in row)


def test_pointer_identifies_andromeda_with_extent():
    scene = sky.Scene(NIGHT, LAT, LNG)
    record = _object('M31')
    alt, az = sky.alt_az_of(sky._mat_apply(scene.horizontal, record['at']))
    view = sky.View(az, alt, 6, 2)
    with patch.object(sky, '_chip', return_value='') as chip:
        _frame(NIGHT, 160, 50, view=view, mouse_pos=(80, 25))
    args = chip.call_args.args
    hit = next(h for h in args[1] if h[2] == 'deep_sky' and h[3][0]['id'] == 'M31')
    x, y, _kind, _payload = hit
    text = sky._chip((int(x) + 2, int(y) // 2 + 1), [hit], *args[2:])
    assert 'Andromeda Galaxy' in text and 'M31' in text and '190′ × 60′' in text
