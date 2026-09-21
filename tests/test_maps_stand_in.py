"""The last real view standing in, moved and scaled, while the next loads.

Street and terrain go through the same reprojection; what differs is
what each register carries across."""

import sys
from pathlib import Path

_src = str(Path(__file__).resolve().parent.parent / "src")
if _src not in sys.path:
    sys.path.insert(0, _src)

from linecast import maps
from linecast._color import BG_PRIMARY
from linecast._radar_basemap import _BITS
from linecast._radar_render import bbox_for

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


class TestReprojectTerrain:
    """Terrain's stand-in is the street one's twin: the shaded ground,
    the shoreline and the rivers all move and scale together."""

    def _prev(self, dots=None):
        fill = [[(x, y) for x in range(GW)] for y in range(HC * 2)]
        coast = [[0] * GW for _ in range(HC)]
        coast[1][3] = _BITS[0][0]
        rdots = dots or [[0] * GW for _ in range(HC)]
        rivers = maps._ShiftedLayer(
            rdots, [["ink" if d else None for d in row] for row in rdots])
        return (BBOX, GW, HC, fill, coast, rivers)

    def test_same_view_or_other_size_does_not_stand_in(self):
        assert maps._reproject_terrain(self._prev(), BBOX, GW, HC) is None
        assert maps._reproject_terrain(self._prev(), (1.0, 0.0, 9.0, 8.0),
                                       GW + 1, HC) is None

    def test_a_pan_moves_the_fill_the_coast_and_the_rivers_together(self):
        rdots = [[0] * GW for _ in range(HC)]
        rdots[2][5] = _BITS[0][0]
        fill, coast, rivers = maps._reproject_terrain(
            self._prev(rdots), (1.0, 0.0, 9.0, 8.0), GW, HC)
        # one degree east: everything moves one cell left
        assert fill[0][0] == (1, 0)
        assert fill[0][GW - 1] == BG_PRIMARY
        assert coast[1][2] == _BITS[0][0] and _count(coast) == 1
        assert rivers.dots[2][4] == _BITS[0][0]
        assert rivers.color[2][4] == "ink"

    def test_a_view_without_tiles_carries_no_rivers(self):
        prev = (BBOX, GW, HC, [[(x, y) for x in range(GW)]
                               for y in range(HC * 2)], None, None)
        fill, coast, rivers = maps._reproject_terrain(
            prev, (1.0, 0.0, 9.0, 8.0), GW, HC)
        assert coast is None and rivers is None
        assert fill[0][0] == (1, 0)

    def test_it_reprojects_exactly_as_the_street_one_does(self):
        # the same window, the same grids: the two registers must not
        # drift apart
        dots = _full()
        bbox = (2.0, 2.0, 6.0, 6.0)
        street_fills, street_layer = maps._reproject_street(
            _prev(dots), bbox, GW, HC, BG_PRIMARY)
        fill, _coast, rivers = maps._reproject_terrain(
            self._prev(dots), bbox, GW, HC)
        assert fill == street_fills
        assert rivers.dots == street_layer.dots
        assert rivers.color == street_layer.color


class TestTerrainStandInFrame:
    def test_a_stand_in_frame_does_not_cut_a_basemap(self, monkeypatch):
        # the borders and city names are a third of a second of
        # polygon filling per window; a frame in motion goes without
        # them, as it goes without labels, until the real view lands
        cut = []
        monkeypatch.setattr(maps, "_get_basemap",
                            lambda *a: cut.append(a) or None)
        monkeypatch.setattr(maps, "_get_elevation",
                            lambda *a: maps._EMPTY_TERRAIN)
        fill = [[(1, 2, 3)] * GW for _ in range(HC * 2)]
        monkeypatch.setattr(maps, "_last_terrain", [(BBOX, GW, HC, fill, None, None)])
        lines, _r, _h, loading, err = maps._render_terrain(
            (1.0, 0.0, 9.0, 8.0), GW, HC, False, (0, 0), None, None, None,
            None, "en", None)
        assert loading and err is None and cut == []
        assert len(lines) == HC
        # a frame that is not waiting on a view still gets its borders,
        # even one whose view failed to load

        def offline(*a):
            raise RuntimeError("offline")

        monkeypatch.setattr(maps, "_get_elevation", offline)
        _l, _r, _h, loading, err = maps._render_terrain(
            (1.0, 0.0, 9.0, 8.0), GW, HC, True, (0, 0), None, None, None,
            None, "en", None)
        assert not loading and err == "offline" and len(cut) == 1


class TestPrefetchAround:
    """What a landed view asks for next."""

    def _asked(self, monkeypatch, spans):
        return self._views(monkeypatch,
                           [(0.0, 0.0, span * 2, span) for span in spans])

    def _views(self, monkeypatch, bboxes, height_cells=8):
        from linecast import _maps_streets as ms
        asked = []
        monkeypatch.setattr(ms, "prefetch_tiles", lambda keys: asked.append(list(keys)))
        monkeypatch.setattr(ms, "tile_info", lambda: ("t", "v", 14))
        monkeypatch.setattr(ms, "_last_span", None)
        for bbox in bboxes:
            _band, _z, keys = ms.view_tiles(bbox, height_cells)
            ms.prefetch_around(bbox, height_cells, keys)
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

    def test_a_view_across_the_seam_rings_like_any_other(self, monkeypatch):
        # Fiji on a 160x45 terminal: eight tiles at z13, and a ring
        # around them rather than every tile at that zoom
        gw, hc = maps.map_cells((160, 45))
        asked, keys = self._views(
            monkeypatch, [bbox_for(-17.0, 179.999, 0.05, gw, hc)], hc)
        assert len(asked) <= 9 * len(keys)
        xs = {k[1] for k in asked}
        assert 0 in xs and (1 << keys[0][0]) - 1 in xs  # both sides of it

    def test_a_zoom_on_a_wide_terminal_keeps_its_guess(self, monkeypatch):
        # London at 160x45: twelve tiles, a ring of eighteen and a
        # guess of fifteen at the next zoom, all inside the cap
        from linecast import _maps_streets as ms
        gw, hc = maps.map_cells((160, 45))
        asked, keys = self._views(
            monkeypatch, [bbox_for(51.5, -0.12, 0.075, gw, hc),
                          bbox_for(51.5, -0.12, 0.05, gw, hc)], hc)
        assert 0 < len(asked) <= 3 * ms._MAX_TILES
        assert any(k[0] > keys[0][0] for k in asked)  # the guess survives

    def test_the_guess_gives_way_to_the_cap(self, monkeypatch):
        from linecast import _maps_streets as ms
        monkeypatch.setattr(ms, "_MAX_TILES", 4)
        gw, hc = maps.map_cells((160, 45))
        asked, keys = self._views(
            monkeypatch, [bbox_for(51.5, -0.12, 0.075, gw, hc),
                          bbox_for(51.5, -0.12, 0.05, gw, hc)], hc)
        assert 0 < len(asked) <= 3 * ms._MAX_TILES
        assert all(k[0] == keys[0][0] for k in asked)  # the ring alone
