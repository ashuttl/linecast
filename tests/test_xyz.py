"""The slippy-map arithmetic maps and radar share: which tiles a stitch
asks for, and which source pixel a resample reads."""

import pytest

from linecast import _xyz
from linecast.maps.vtiles import tiles_for_bbox


def _asked(bbox, z):
    asked = []

    def fetch(z_, x, y):
        asked.append((z_, x, y))
        return None

    _xyz.stitch_xyz(fetch, bbox, z)
    return asked


class TestTheTilesAStitchAsksFor:
    @pytest.mark.parametrize("z", [1, 2, 3])
    def test_the_whole_world_is_each_tile_once(self, z):
        # the east edge was floored, so the world was n columns and
        # tile 0 again: 72 tiles for a z3 cloud refresh instead of 64
        asked = _asked((-180.0, -85.05, 180.0, 85.05), z)
        n = 1 << z
        assert len(asked) == n * n
        assert len(set(asked)) == n * n

    @pytest.mark.parametrize("bbox, z", [
        ((-180.0, -85.05, 180.0, 85.05), 3),
        ((0.0, 0.0, 90.0, 40.0), 3),         # edges on tile boundaries
        ((-70.4, 43.6, -70.2, 43.7), 12),
        ((179.9, -17.0, 180.1, -16.8), 8),   # across the antimeridian
        ((-180.1, -17.0, -179.9, -16.8), 8),
    ])
    def test_a_stitch_asks_what_the_vector_tiles_would(self, bbox, z):
        assert sorted(_asked(bbox, z)) == sorted(tiles_for_bbox(bbox, z))

    def test_the_canvas_is_as_wide_as_the_tiles(self):
        _canvas, cw, _ch, org_x, _org_y, world = _xyz.stitch_xyz(
            lambda *a: None, (-180.0, -85.05, 180.0, 85.05), 2)
        assert (cw, org_x) == (world, 0)


class TestWhereAResampleReads:
    def test_west_of_the_antimeridian_reads_the_west_side(self):
        # tile 1 is the half of the world east of Greenwich, so its last
        # column is the ground just west of 180°; the sample there read
        # tile 0's first column, across the line, when x was truncated
        def fetch(z, x, y):
            ink = (0, 0, 255, 255) if x == 1 else (255, 0, 0, 255)
            return 256, 256, bytearray(ink * (256 * 256))

        bbox = (-180.4, -10.0, -179.6, 10.0)
        w, h, out = _xyz.reproject_xyz(fetch, bbox, 2, 2, 1)
        west, east = out[0:4], out[4:8]
        assert tuple(west) == (0, 0, 255, 255)
        assert tuple(east) == (255, 0, 0, 255)


class TestMendingAStitch:
    @staticmethod
    def _tile(x):
        return 256, 256, bytearray((x, 0, 0, 255) * (256 * 256))

    def test_a_stitch_names_the_tiles_it_is_missing(self):
        missing = []
        _xyz.stitch_xyz(lambda z, x, y: None if (x, y) == (1, 0) else self._tile(x),
                        (-180.0, -85.05, 180.0, 85.05), 1, missing)
        assert missing == [(1, 1, 0)]

    @pytest.mark.parametrize("bbox, z", [
        ((-180.0, -85.05, 180.0, 85.05), 1),
        ((-180.1, -17.0, -179.9, -16.8), 8),   # starts west of the antimeridian
    ])
    def test_only_the_missing_tiles_are_asked_and_pasted_where_they_go(self, bbox, z):
        down = set(tiles_for_bbox(bbox, z)[:1])
        missing = []
        whole = _xyz.stitch_xyz(lambda *t: self._tile(t[1]), bbox, z)
        short = _xyz.stitch_xyz(lambda *t: None if t in down else self._tile(t[1]),
                                bbox, z, missing)
        assert set(missing) == down
        asked = []

        def fetch(*tile):
            asked.append(tile)
            return self._tile(tile[1])

        mended, still = _xyz.mend_xyz(fetch, short, missing)
        assert asked == missing and still == []
        assert mended[0] == whole[0] and mended[1:] == whole[1:]
        # a copy: a frame still drawing from the short canvas keeps it
        assert mended[0] is not short[0] and short[0] != whole[0]

    def test_a_mend_that_brings_nothing_hands_the_canvas_back(self):
        missing = []
        short = _xyz.stitch_xyz(lambda *t: None, (-180.0, -85.05, 180.0, 85.05), 1, missing)
        mended, still = _xyz.mend_xyz(lambda *t: None, short, missing)
        assert mended is short and still == missing
