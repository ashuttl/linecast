"""Close in, the terrain register carries the street map's lines and
names over the shaded ground (style.ROADS_BAND)."""

import re
import types

import pytest

from linecast._xyz import bbox_for
from linecast.maps import style
from linecast.maps import view as maps
from linecast.terminal.color import BG_PRIMARY

GW, HC = 8, 4
CLOSE = 0.01     # degrees of latitude: a town, well inside ROADS_BAND
WIDE = 4.0       # a region, outside it


class _Layer:
    """A street layer as the renderer reads it: dots, inks, a ribbon
    and the hover index."""

    def __init__(self, dots, hover=None):
        self.dots = dots
        self.color = [[(200, 200, 200)] * GW for _ in range(HC)]
        self.ribbon = set()
        self.hover = hover


def _window(zoom):
    return maps._Window.of(bbox_for(43.66, -70.26, zoom, GW, HC), GW, HC)


def _terrain_view():
    elev = [[10.0] * GW for _ in range(HC * 2)]
    return maps.TerrainView(elev, [[0] * GW for _ in range(HC)], None, None, None)


def _street_view(labels=None, hover=None, col=0):
    dots = [[0] * GW for _ in range(HC)]
    dots[0][col] = 0x01   # one dot, in the top row
    return (None, _Layer(dots, hover), labels if labels is not None else {})


def _plain(line):
    return re.sub(r"\x1b\[[0-9;]*m", "", line)


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.setattr(maps, "_last_terrain", [None])
    monkeypatch.setattr(maps, "_last_street", [None])
    monkeypatch.setattr(maps, "_get_elevation", lambda *a, **k: _terrain_view())
    monkeypatch.setattr(maps._places, "terrain_overlays", lambda *a, **k: {})
    monkeypatch.setattr(maps, "_terrain_buffer",
                        lambda view, bbox, gw, hc, wide=False:
                        [[(90, 90, 90)] * gw for _ in range(hc * 2)])


def _render(window, mouse_pos=None, **kw):
    return maps._render_terrain(window, True, (0, 0), mouse_pos, maps._Marks(),
                                "en", None, **kw)


class TestWhichWindows:
    def test_a_town_carries_the_streets(self):
        assert maps._roads(_window(CLOSE))

    def test_a_region_does_not(self):
        assert not maps._roads(_window(WIDE))

    def test_the_planet_does_not(self):
        win = maps._Window.of(bbox_for(0.0, 0.0, 125.0, GW, HC), GW, HC)
        assert win.wide and not maps._roads(win)

    def test_the_band_is_the_style_s(self):
        assert style.ROADS_BAND >= style.GAZETTEER_BAND


class TestTheFrame:
    def test_the_street_dots_ride_the_ground(self, monkeypatch):
        monkeypatch.setattr(maps, "_get_street", lambda *a, **k: _street_view())
        lines, _r, _h, _l, _e = _render(_window(CLOSE))
        assert "⠁" in lines[0]    # the one dot, as braille

    def test_a_region_asks_for_no_streets(self, monkeypatch):
        asked = []
        monkeypatch.setattr(maps, "_get_street",
                            lambda *a, **k: asked.append(a) or _street_view())
        lines, _r, _h, _l, _e = _render(_window(WIDE))
        assert asked == [] and "⠁" not in lines[0]

    def test_the_tiles_names_stand_the_gazetteer_down(self, monkeypatch):
        named = []
        monkeypatch.setattr(maps._places, "terrain_overlays",
                            lambda *a, **k: named.append(1) or {})
        monkeypatch.setattr(maps, "_get_street", lambda *a, **k: _street_view(
            labels={(2, 1): ("Q", (255, 255, 255))}))
        lines, _r, _h, _l, _e = _render(_window(CLOSE))
        assert named == [] and "Q" in lines[1]

    def test_until_they_land_the_gazetteer_names_the_ground(self, monkeypatch):
        named = []
        monkeypatch.setattr(maps._places, "terrain_overlays",
                            lambda *a, **k: named.append(1) or {})
        monkeypatch.setattr(maps, "_get_street", lambda *a, **k: (None, None, None))
        _render(_window(CLOSE))
        assert named == [1]

    def test_labels_off_hides_the_streets_too(self, monkeypatch):
        monkeypatch.setattr(maps, "_get_street", lambda *a, **k: _street_view(
            labels={(2, 1): ("Q", (255, 255, 255))}))
        lines, _r, _h, _l, _e = _render(_window(CLOSE), show_labels=False)
        assert "⠁" not in lines[0] and "Q" not in lines[1]

    def test_the_pointer_over_a_road_names_it(self, monkeypatch):
        hit = types.SimpleNamespace(cells=[(0, 0)], glyphs=[])
        index = types.SimpleNamespace(at=lambda c, r: hit if (c, r) == (0, 0) else None)
        monkeypatch.setattr(maps, "_get_street",
                            lambda *a, **k: _street_view(hover=index))
        monkeypatch.setattr(maps._hover, "readout", lambda h, lang: "Main Street")
        _l, readout, hover, _ld, _e = _render(_window(CLOSE), mouse_pos=(1, 2))
        assert hover == " · Main Street"
        _l, readout, hover, _ld, _e = _render(_window(CLOSE), mouse_pos=(3, 3))
        assert hover == "" and "ft" in readout or "m" in readout

    def test_a_failed_street_build_leaves_the_ground_alone(self, monkeypatch):
        def offline(*a, **k):
            raise RuntimeError("offline")
        monkeypatch.setattr(maps, "_get_street", offline)
        lines, _r, _h, loading, err = _render(_window(CLOSE))
        assert err is None and len(lines) == HC


class TestTheViewInHand:
    def test_streets_that_land_later_join_the_view(self, monkeypatch):
        # the ground landed first and was stored without its streets;
        # the frame after the streets land gives the stored view them
        win = _window(CLOSE)
        monkeypatch.setattr(maps, "_get_street", lambda *a, **k: (None, None, None))
        _render(win)
        stored = maps._last_terrain[0]
        assert stored[9] is None
        monkeypatch.setattr(maps, "_get_street", lambda *a, **k: _street_view())
        maps._street_lines(win, False, "en", (), stored)
        assert maps._last_terrain[0][9] is not None

    def test_a_stand_in_carries_the_lines(self, monkeypatch):
        win = _window(CLOSE)
        monkeypatch.setattr(maps, "_get_street", lambda *a, **k: _street_view(col=3))
        lines, _r, _h, _l, _e = _render(win)
        assert _plain(lines[0]).index("\u2801") == 3
        prev = maps._last_terrain[0]
        assert prev[9] is not None
        # the next window, a cell east, before its view lands
        monkeypatch.setattr(maps, "_get_elevation",
                            lambda *a, **k: maps._EMPTY_TERRAIN)
        monkeypatch.setattr(maps, "_get_street", lambda *a, **k: (None, None, None))
        bbox = prev[0]
        step = (bbox[2] - bbox[0]) / GW
        moved = maps._Window.of((bbox[0] + step, bbox[1], bbox[2] + step, bbox[3]),
                                GW, HC)
        monkeypatch.setattr(maps, "_last_terrain", [prev])
        lines, _r, _h, loading, _e = maps._render_terrain(
            moved, False, (0, 0), None, maps._Marks(), "en", None)
        assert loading
        # the dot came along, a cell west of where the last view drew it
        assert _plain(lines[0]).index("\u2801") == 2

    def test_an_older_record_without_streets_still_stands_in(self, monkeypatch):
        fill = [[BG_PRIMARY] * GW for _ in range(HC * 2)]
        win = _window(CLOSE)
        prev = (tuple(win.frame.bbox), win.frame.gw, win.frame.hc, fill, None, None,
                None, None, None)
        monkeypatch.setattr(maps, "_last_terrain", [prev])
        monkeypatch.setattr(maps, "_get_elevation", lambda *a, **k: maps._EMPTY_TERRAIN)
        monkeypatch.setattr(maps, "_get_street", lambda *a, **k: (None, None, None))
        lines, _r, _h, loading, _e = maps._render_terrain(
            _window(CLOSE), False, (0, 0), None, maps._Marks(), "en", None)
        assert len(lines) == HC


class TestInks:
    def test_a_grey_name_takes_the_grounds_contrast_ink(self):
        out = maps._ground_inks({(0, 0): ("A", (180, 180, 180), False)})
        assert out[(0, 0)] == ("A", None, False)

    def test_a_coloured_ink_is_the_things_own(self):
        out = maps._ground_inks({(0, 0): ("I", (90, 140, 230), True)})
        assert out[(0, 0)] == ("I", (90, 140, 230), True)

    def test_an_ink_already_unset_stays_so(self):
        out = maps._ground_inks({(1, 0): ("x", None)})
        assert out[(1, 0)] == ("x", None)
