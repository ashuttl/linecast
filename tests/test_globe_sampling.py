"""World sampling wraps geography, including a stitch's repeated edge tile."""

import pytest

from linecast import _globe, _globe_now, _radar_tiles


@pytest.mark.parametrize('west', [-360.0, -180.0, 0.0])
@pytest.mark.parametrize('crop_rows', [False, True])
def test_padded_world_is_continuous_across_the_dateline(monkeypatch, west, crop_rows):
    # Exercise the real stitch layout: inclusive east bounds add a copy of
    # the first tile. Its final column is NOT the world's final column.
    monkeypatch.setattr(_radar_tiles, '_TILE_SIZE', 4)

    def tile(z, tx, ty):
        pixels = bytearray()
        for y in range(4):
            for x in range(4):
                wx, wy = tx * 4 + x, ty * 4 + y
                height = 32768 + 10 * wx + 100 * wy
                pixels.extend((height >> 8, height & 255, 0,
                               20 + 20 * wx + 2 * wy))
        return 4, 4, pixels

    hit = _radar_tiles.stitch_xyz(tile, (west, -85.05, west + 360, 85.05), 1)
    pixels, width, height, origin_x, origin_y, world = hit
    assert (width, height, world) == (12, 8, 8)
    if crop_rows:
        # Cloud mosaics may retain a vertical source offset. Longitude wrap
        # must leave the row stride, source origin, and interpolation intact.
        hit = (pixels[2 * width * 4:6 * width * 4], width, 4, origin_x, 2, world)
    monkeypatch.setattr(_globe, '_world_canvas', lambda z, timeout: hit)
    monkeypatch.setitem(_globe_now._cloud, 'cover', None)

    deltas = (-.25, 0.0, .25)
    points = [(0.0, seam + delta * 360 / world)
              for seam in (-180.0, 180.0) for delta in deltas]
    # At the equator, row centres 3 and 4 average to 3.5. Either spelling
    # of the dateline blends world columns 7 and 0 with these known weights.
    expected_heights = [350 + 70 * (.5 - delta) for delta in deltas] * 2
    expected_alpha = [(27 + 140 * (.5 - delta)) / 255 for delta in deltas] * 2
    assert _globe.elevation([points], 125, 8)[0] == pytest.approx(expected_heights)
    assert _globe_now.clouds([points], hit)[0] == pytest.approx(expected_alpha)
    for tap in _globe.bilinear_taps(points, hit):
        assert 0.0 <= tap[4] < 1.0 and 0.0 <= tap[5] <= 1.0
