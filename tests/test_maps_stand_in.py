"""The last street view standing in, moved and scaled, while the next loads."""

import sys
from pathlib import Path

_src = str(Path(__file__).resolve().parent.parent / "src")
if _src not in sys.path:
    sys.path.insert(0, _src)

from linecast import maps
from linecast._radar_basemap import _BITS

GW, HC = 8, 4
BBOX = (0.0, 0.0, 8.0, 8.0)  # one degree per cell column, two per row


def _prev(dots=None):
    fills = [[(x, y) for x in range(GW)] for y in range(HC * 2)]
    dots = dots or [[0] * GW for _ in range(HC)]
    color = [["ink" if d else None for d in row] for row in dots]
    return (BBOX, GW, HC, fills, maps._ShiftedLayer(dots, color))


def _full():
    return [[0xFF] * GW for _ in range(HC)]


def _count(dots):
    return sum(bin(b).count("1") for row in dots for b in row)


class TestReprojectStreet:
    def test_same_view_or_other_size_does_not_stand_in(self):
        assert maps._reproject_street(_prev(), BBOX, GW, HC, "g") is None
        assert maps._reproject_street(_prev(), (1.0, 0.0, 9.0, 8.0),
                                      GW + 1, HC, "g") is None

    def test_pan_shifts_fills_and_dots(self):
        dots = [[0] * GW for _ in range(HC)]
        dots[1][3] = _BITS[0][0]
        fills, layer = maps._reproject_street(
            _prev(dots), (1.0, 0.0, 9.0, 8.0), GW, HC, "g")
        # one degree east: everything moves one cell left
        assert fills[0][0] == (1, 0)
        assert fills[0][GW - 1] == "g"
        assert layer.dots[1][2] == _BITS[0][0]
        assert layer.color[1][2] == "ink"
        assert _count(layer.dots) == 1

    def test_zoom_out_keeps_ink_inside_and_leaves_the_edge_blank(self):
        # twice the span, centred on the old view
        fills, layer = maps._reproject_street(
            _prev(_full()), (-4.0, -4.0, 12.0, 12.0), GW, HC, "g")
        assert layer.dots[0][0] == 0 and fills[0][0] == "g"
        assert layer.dots[HC // 2][GW // 2]
        assert fills[HC][GW // 2] != "g"

    def test_zoom_in_stays_solid(self):
        fills, layer = maps._reproject_street(
            _prev(_full()), (2.0, 2.0, 6.0, 6.0), GW, HC, "g")
        assert _count(layer.dots) == GW * HC * 8
        assert all(f != "g" for row in fills for f in row)


class TestPrefetchAround:
    """What a landed view asks for next."""

    def _asked(self, monkeypatch, spans):
        from linecast import _maps_streets as ms
        asked = []
        monkeypatch.setattr(ms, "prefetch_tiles", lambda keys: asked.append(list(keys)))
        monkeypatch.setattr(ms, "tile_info", lambda: ("t", "v", 14))
        monkeypatch.setattr(ms, "_last_span", [None])
        for span in spans:
            bbox = (0.0, 0.0, span * 2, span)
            _band, _z, keys = ms.view_tiles(bbox, 8)
            ms.prefetch_around(bbox, 8, keys)
        return asked[-1], keys

    def test_a_pan_asks_only_for_the_ring(self, monkeypatch):
        asked, keys = self._asked(monkeypatch, [1.0, 1.0])
        z = keys[0][0]
        assert asked and all(k[0] == z for k in asked)  # no other zoom level

    def test_a_zoom_asks_the_way_the_reader_went(self, monkeypatch):
        out, keys = self._asked(monkeypatch, [1.0, 1.5])
        assert any(k[0] < keys[0][0] for k in out)      # coarser tiles
        assert not any(k[0] > keys[0][0] for k in out)  # and nothing finer
        into, keys = self._asked(monkeypatch, [1.5, 1.0])
        assert not any(k[0] < keys[0][0] for k in into)
