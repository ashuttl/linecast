"""The newest real view standing in, moved and scaled, while the next loads.

Street, terrain and the globe go through the same reprojection; what
differs is what each register carries across.  The newest view is not
always one that was drawn: a view fetched while the camera was moving
lands between frames, and the frames after it are cut from that.
"""

import re
import sys
from pathlib import Path

import pytest

_src = str(Path(__file__).resolve().parent.parent / "src")
if _src not in sys.path:
    sys.path.insert(0, _src)

from linecast import _globe, _maps_views, maps
from linecast._color import BG_PRIMARY
from linecast._radar_basemap import _BITS
from linecast._radar_i18n import rs
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


class TestReprojectGlobe:
    """Zoomed about its centre, the disk is the old disk scaled — so the
    globe borrows the flat map's axis map whole."""

    def _prev(self, bbox=BBOX):
        fill = [[(x, y) for x in range(GW)] for y in range(HC * 2)]
        coast = [[0] * GW for _ in range(HC)]
        coast[1][3] = _BITS[0][0]
        dots = [[0] * GW for _ in range(HC)]
        dots[2][5] = _BITS[0][0]
        borders = maps._ShiftedLayer(
            dots, [["ink" if d else None for d in row] for row in dots])
        return (bbox, GW, HC, fill, coast, borders)

    def test_nothing_to_carry_the_same_window_or_another_size(self):
        assert maps._reproject_globe(None, BBOX, GW, HC) is None
        assert maps._reproject_globe(self._prev(), BBOX, GW, HC) is None
        assert maps._reproject_globe(self._prev(), (2.0, 2.0, 6.0, 6.0),
                                     GW + 1, HC) is None

    def test_a_moved_centre_is_a_turn_and_gets_no_stand_in(self):
        # a drag or a spin turns the geography under a disk the size it
        # was; scaling the old picture says nothing true about that
        assert maps._reproject_globe(self._prev(), (1.0, 0.0, 9.0, 8.0),
                                     GW, HC) is None
        # nor does a zoom that drifts off centre with it
        assert maps._reproject_globe(self._prev(), (2.5, 2.0, 6.5, 6.0),
                                     GW, HC) is None

    def test_a_zoom_scales_it_exactly_as_the_flat_registers_do(self):
        # half the span about the same centre: the fill, the shoreline
        # and the borders must land where terrain's twin lands them
        bbox = (2.0, 2.0, 6.0, 6.0)
        prev = self._prev()
        fill, coast, borders = maps._reproject_globe(prev, bbox, GW, HC)
        t_fill, t_coast, t_rivers = maps._reproject_terrain(prev, bbox, GW, HC)
        assert fill == t_fill and coast == t_coast
        assert borders.dots == t_rivers.dots
        assert borders.color == t_rivers.color
        assert _count(coast) and all(f != BG_PRIMARY for row in fill
                                     for f in row)

    def test_a_disk_without_borders_carries_none(self):
        prev = (BBOX, GW, HC, [[(x, y) for x in range(GW)]
                               for y in range(HC * 2)], None, None)
        fill, coast, borders = maps._reproject_globe(
            prev, (2.0, 2.0, 6.0, 6.0), GW, HC)
        assert coast is None and borders is None and fill[0][0] == (2, 2)


def _body(frame):
    """The map's own lines, stripped of colour: header and footer out."""
    plain = re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", frame)
    return "\n".join(plain.split("\n")[1:-1])


def _ink(frame):
    return sum(1 for ch in _body(frame) if ch not in " \n")


def _braille(frame):
    return sum(1 for ch in _body(frame) if 0x2800 <= ord(ch) <= 0x28FF)


class _Runtime:
    lang = "en"
    live = True


class TestGlobeStandInFrame:
    """A zoom step that crosses a terrarium level, frame by frame.

    The level the zoom lands on has no texture in memory, so the globe
    stops being warm and the view goes through the non-blocking loader,
    which misses.  What used to be painted then was a blank disk.
    """

    COLS, ROWS = 40, 14
    LAT, LON = 40.7, -74.0

    def _view(self, gw, hc):
        spy = hc * 2
        return _globe.GlobeView(
            [[100.0] * gw for _ in range(spy)],          # elev
            [[0xFF] * gw for _ in range(hc)],            # coast
            [[1.0] * gw for _ in range(spy)],            # shade
            [[0.0] * gw for _ in range(spy)],            # atmo
            None, None,                                  # cover, borders
            fill=[[(180, 90, 40)] * gw for _ in range(spy)])

    def _frame(self, monkeypatch, zoom, view, register="terrain", **kw):
        monkeypatch.setattr(maps, "get_terminal_size",
                            lambda: (self.COLS, self.ROWS))
        monkeypatch.setattr(maps, "_get_globe", lambda *a, **k: view)
        return maps.render_map(self.LAT, self.LON, "Somewhere", zoom,
                               runtime=_Runtime(), block=False,
                               view=register, **kw)

    def test_a_level_crossing_draws_the_scaled_disk(self, monkeypatch):
        gw, hc = maps.map_cells((self.COLS, self.ROWS))
        maps._last_globe.clear()
        real = self._frame(monkeypatch, 120.0, self._view(gw, hc))
        stand = self._frame(monkeypatch, 80.0, None)
        maps._last_globe.clear()
        blank = self._frame(monkeypatch, 80.0, None)
        assert _braille(real) and _braille(stand) and not _braille(blank)
        assert _ink(stand) > 4 * _ink(blank)

    def test_a_moved_centre_keeps_the_loading_frame(self, monkeypatch):
        gw, hc = maps.map_cells((self.COLS, self.ROWS))
        maps._last_globe.clear()
        self._frame(monkeypatch, 120.0, self._view(gw, hc))
        monkeypatch.setattr(self, "LON", self.LON + 20.0, raising=False)
        spun = self._frame(monkeypatch, 80.0, None)
        assert not _braille(spun)

    def test_another_terminal_keeps_the_loading_frame(self, monkeypatch):
        gw, hc = maps.map_cells((self.COLS, self.ROWS))
        maps._last_globe.clear()
        self._frame(monkeypatch, 120.0, self._view(gw, hc))
        monkeypatch.setattr(self, "COLS", self.COLS + 6, raising=False)
        resized = self._frame(monkeypatch, 80.0, None)
        assert not _braille(resized)

    def test_the_real_view_wins_as_soon_as_it_lands(self, monkeypatch):
        gw, hc = maps.map_cells((self.COLS, self.ROWS))
        maps._last_globe.clear()
        self._frame(monkeypatch, 120.0, self._view(gw, hc))
        tag = rs("loading", "en")
        stand = self._frame(monkeypatch, 80.0, None)
        landed = self._frame(monkeypatch, 80.0, self._view(gw, hc))
        # the stand-in says so, the way the flat registers' does; the
        # real view drops the tag and is the one drawn
        assert tag in stand and tag not in landed
        assert _braille(landed) >= _braille(stand)

    def test_each_register_carries_its_own_disk(self, monkeypatch):
        # the street planet draws no borders and strokes its shore in
        # the street map's ink; it must not be handed terrain's disk
        gw, hc = maps.map_cells((self.COLS, self.ROWS))
        maps._last_globe.clear()
        self._frame(monkeypatch, 120.0, self._view(gw, hc))
        assert not _braille(self._frame(monkeypatch, 80.0, None, "street"))
        self._frame(monkeypatch, 120.0, self._view(gw, hc), "street")
        assert _braille(self._frame(monkeypatch, 80.0, None, "street"))

    def test_the_sky_shades_the_stand_in_where_it_now_is(self, monkeypatch):
        # sun and clouds are applied to the carried disk on the sphere
        # it now sits on, as the flat terrain stand-in is shaded
        gw, hc = maps.map_cells((self.COLS, self.ROWS))
        maps._last_globe.clear()
        self._frame(monkeypatch, 120.0, self._view(gw, hc))
        lit = self._frame(monkeypatch, 80.0, None, sun=True)
        plain = self._frame(monkeypatch, 80.0, None)
        assert _braille(lit) and lit != plain


ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07]*\x07")
COLS, ROWS = 60, 20


def _braille_between(frame, lo, hi):
    """Braille cells in columns [lo, hi) of a frame's map rows."""
    rows = [ANSI.sub("", line) for line in frame.split("\n")[1:-1]]
    return sum(1 for row in rows for ch in row[lo:hi]
               if 0x2800 <= ord(ch) <= 0x28FF)


class TestTheNewestViewStandsIn:
    """A view that lands while the camera is still moving is never
    drawn by the frame that asked for it — that frame is long gone —
    but every frame after it is cut from it, so the ground the window
    has moved onto fills in during the glide instead of at the stop.
    """

    LAT, LON, ZOOM = 40.7, -74.0, 0.05

    @pytest.fixture(autouse=True)
    def _quiet(self, monkeypatch):
        monkeypatch.setattr(maps, "get_terminal_size", lambda: (COLS, ROWS))
        _maps_views._street_landed[0] = None
        _maps_views._terrain_landed[0] = None
        yield
        _maps_views._street_landed[0] = None
        _maps_views._terrain_landed[0] = None
        maps._last_street[0] = maps._last_terrain[0] = None

    def _windows(self, gw, hc):
        """(here, the view west of it, the view east of it)."""
        here = bbox_for(self.LAT, self.LON, self.ZOOM, gw, hc)
        span = here[2] - here[0]
        return (here,
                (here[0] - span * .6, here[1], here[2] - span * .6, here[3]),
                (here[0] + span * .6, here[1], here[2] + span * .6, here[3]))

    def _frame(self, view):
        return maps.render_map(self.LAT, self.LON, "New York", self.ZOOM,
                               block=False, view=view)

    def test_a_street_view_that_lands_mid_pan_paints_the_incoming_edge(
            self, monkeypatch):
        monkeypatch.setattr(maps, "_get_street",
                            lambda *a, **k: (None, None, None))
        gw, hc = maps.map_cells((COLS, ROWS))
        _here, west, east = self._windows(gw, hc)
        ink = (255, 0, 0)
        fills = [[ink] * gw for _ in range(hc * 2)]
        layer = maps._ShiftedLayer([[0xFF] * gw for _ in range(hc)],
                                   [[ink] * gw for _ in range(hc)])
        # the view the pan started from lies west: the window's east
        # edge is ground it has moved onto, and nothing is drawn there
        maps._last_street[0] = (west, gw, hc, fills, layer)
        before = self._frame("street")
        assert _braille_between(before, 0, gw // 4) > 0
        assert _braille_between(before, gw - gw // 4, gw) == 0
        # the view the pan is heading for lands between the frames
        _maps_views._street_landed[0] = (east, gw, hc, fills, layer)
        after = self._frame("street")
        assert _braille_between(after, gw - gw // 4, gw) > 0
        assert _braille_between(after, 0, gw // 4) == 0
        assert _maps_views.take_street() is None     # taken once
        assert maps._last_street[0][0] == east

    def test_a_terrain_view_that_lands_mid_pan_does_the_same(
            self, monkeypatch):
        monkeypatch.setattr(maps, "_get_elevation",
                            lambda *a, **k: maps._EMPTY_TERRAIN)
        gw, hc = maps.map_cells((COLS, ROWS))
        _here, west, east = self._windows(gw, hc)
        elev = [[120.0] * gw for _ in range(hc * 2)]
        coast = [[0xFF] * gw for _ in range(hc)]
        landed = maps.TerrainView(elev, coast, None, None, None)
        maps._last_terrain[0] = (
            west, gw, hc,
            maps._terrain_buffer(elev, west, gw, hc), coast, None)
        before = self._frame("terrain")
        assert _braille_between(before, 0, gw // 4) > 0
        assert _braille_between(before, gw - gw // 4, gw) == 0
        _maps_views._terrain_landed[0] = (east, gw, hc, landed)
        after = self._frame("terrain")
        assert _braille_between(after, gw - gw // 4, gw) > 0
        assert _braille_between(after, 0, gw // 4) == 0
        assert _maps_views.take_terrain() is None
        assert maps._last_terrain[0][0] == east

    def test_a_landing_at_another_terminal_size_is_left_alone(
            self, monkeypatch):
        monkeypatch.setattr(maps, "_get_street",
                            lambda *a, **k: (None, None, None))
        gw, hc = maps.map_cells((COLS, ROWS))
        _here, west, east = self._windows(gw, hc)
        ink = (255, 0, 0)
        fills = [[ink] * gw for _ in range(hc * 2)]
        layer = maps._ShiftedLayer([[0xFF] * gw for _ in range(hc)],
                                   [[ink] * gw for _ in range(hc)])
        maps._last_street[0] = (west, gw, hc, fills, layer)
        _maps_views._street_landed[0] = (east, gw + 1, hc, fills, layer)
        maps._render_street(bbox_for(self.LAT, self.LON, self.ZOOM, gw, hc),
                            gw, hc, False, (0, 0), None, None, None, None,
                            "en", None)
        assert maps._last_street[0][0] == west   # the usable one is kept
