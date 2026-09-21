"""Which water gets a shoreline, and which is only filled in.

Every body of inland water is painted.  Only a body big enough on
screen — style.SHORE_MIN_DOTS dots of it — is given a braille shore,
because a ring round each of the thousand unnamed ponds in the Maine
woods is a speckle and not a map.  The rule is one function,
`_maps_streets.stroked_water`, and both flat registers ask it the same
question: street mode before it strokes its own water fill, terrain
mode inside `_coast_dots`, where the tiles' lakes join the elevation's
sea.  So these tests come in pairs — the mask, then each register.

The threshold is in *screen* dots and not in hectares, which is the
whole design: a pond that was a speck at a county view is a lake at a
township view, and earns its shore on the way in.
"""

import sys
from pathlib import Path

import pytest

# Ensure the worktree src is preferred over any installed version.
_src = str(Path(__file__).resolve().parent.parent / "src")
if _src not in sys.path:
    sys.path.insert(0, _src)

from linecast import _maps_streets as st
from linecast import _maps_style as style
from linecast import _theme
from linecast._maps_views import _coast_dots

from test_maps_streets import (  # the tile-fixture writer, reused wholesale
    DARK_BG, EXTENT, WORLD, Z0, as_text, classed, dot_mask, feature, layer,
    polyline, rect, tagged_line, tile, vstr,
)

MIN = style.SHORE_MIN_DOTS


@pytest.fixture(autouse=True)
def _truecolor(monkeypatch):
    monkeypatch.setattr(style, "color_mode", lambda: "truecolor")
    monkeypatch.setattr(_theme, "theme_bg", DARK_BG)


def blank(dw, dh):
    return [bytearray(dw) for _ in range(dh)]


def blob(mask, x0, y0, w, h):
    """Paint a w x h rectangle of water and return its dot count."""
    for y in range(y0, y0 + h):
        for x in range(x0, x0 + w):
            mask[y][x] = 1
    return w * h


# ---------------------------------------------------------------------------
# The rule itself
# ---------------------------------------------------------------------------
class TestStrokedWater:
    def test_the_threshold_is_the_body_s_own_dot_count(self):
        # Two bodies of the same shape, one dot apart in size, with the
        # bar between them: the rule is area and nothing else.
        under, over = blank(40, 20), blank(40, 20)
        assert blob(under, 2, 2, MIN - 1, 1) == MIN - 1
        assert blob(over, 2, 2, MIN, 1) == MIN
        assert not any(any(row) for row in st.stroked_water(under))
        assert any(any(row) for row in st.stroked_water(over))

    def test_a_lake_survives_and_the_ponds_around_it_do_not(self):
        mask = blank(40, 20)
        blob(mask, 2, 2, 10, 8)              # the lake: 80 dots
        for x in (20, 24, 28, 32):           # four ponds: 4 dots each
            blob(mask, x, 10, 2, 2)
        out = st.stroked_water(mask)
        assert [row[2:12] for row in out[2:10]] == [row[2:12]
                                                    for row in mask[2:10]]
        assert not any(any(row[16:]) for row in out)

    def test_the_mask_it_was_given_is_left_alone(self):
        # The fill and the hover read the whole mask; only the stroke
        # reads this one, so the caller's must come back untouched.
        mask = blank(20, 20)
        blob(mask, 1, 1, 2, 2)
        before = as_text(mask)
        st.stroked_water(mask)
        assert as_text(mask) == before

    def test_a_body_is_four_connected_and_not_eight(self):
        # Two squares meeting at a corner are two ponds, not one lake —
        # the same connectivity _edge_dots strokes with, so no dot of an
        # unstroked pond can ever sit beside a stroked body's water.
        mask = blank(40, 20)
        half = (MIN // 2) + 1
        blob(mask, 2, 2, half, 1)
        blob(mask, 2 + half, 3, half, 1)
        assert not any(any(row) for row in st.stroked_water(mask))
        mask[2][2 + half] = 1               # join them: one body now
        assert any(any(row) for row in st.stroked_water(mask))

    def test_an_L_shaped_body_is_counted_whole(self):
        # The labelling walks runs row by row; a body whose rows do not
        # line up must still add up to one total.
        mask = blank(20, 20)
        arm = (MIN // 2) + 1
        blob(mask, 2, 2, arm, 1)
        blob(mask, 2, 3, 1, arm)
        assert any(any(row) for row in st.stroked_water(mask))

    def test_a_body_cut_by_the_window_is_judged_by_what_is_visible(self):
        # A lake half off screen has only its visible half to be judged
        # by, which is all the view has.  A wide strip along the edge is
        # a shore; a corner of one is not.
        edge = blank(40, 20)
        blob(edge, 0, 0, MIN, 1)
        assert any(any(row) for row in st.stroked_water(edge))
        corner = blank(40, 20)
        blob(corner, 0, 0, 2, 2)
        assert not any(any(row) for row in st.stroked_water(corner))

    def test_the_rule_can_be_turned_off(self):
        mask = blank(20, 20)
        blob(mask, 1, 1, 2, 2)
        assert st.stroked_water(mask, 1) is mask
        assert not any(any(row) for row in st.stroked_water(mask, MIN))

    def test_an_empty_mask_comes_back_empty(self):
        assert as_text(st.stroked_water(blank(8, 8))) == ["." * 8] * 8
        assert st.stroked_water([]) == []

    def test_it_agrees_with_a_flood_fill(self):
        # The run-length labelling is an optimisation of the obvious
        # thing; the obvious thing is the spec.
        mask = dot_mask([
            "~~..~~~~....~~~~",
            "~~..~~~~....~..~",
            "....~~~~....~~~~",
            "..~.........~...",
            "~~~~~~~~..~~~~~~",
            "~....~....~....~",
        ])
        assert as_text(st.stroked_water(mask, 6)) == as_text(
            _flood(mask, 6))


def _flood(mask, min_dots):
    """The same rule by per-dot flood fill, for the agreement test."""
    dh, dw = len(mask), len(mask[0])
    seen = [bytearray(dw) for _ in range(dh)]
    out = [bytearray(dw) for _ in range(dh)]
    for y in range(dh):
        for x in range(dw):
            if not mask[y][x] or seen[y][x]:
                continue
            stack, body = [(y, x)], []
            seen[y][x] = 1
            while stack:
                cy, cx = stack.pop()
                body.append((cy, cx))
                for ny, nx in ((cy - 1, cx), (cy + 1, cx),
                               (cy, cx - 1), (cy, cx + 1)):
                    if 0 <= ny < dh and 0 <= nx < dw \
                            and mask[ny][nx] and not seen[ny][nx]:
                        seen[ny][nx] = 1
                        stack.append((ny, nx))
            if len(body) >= min_dots:
                for cy, cx in body:
                    out[cy][cx] = 1
    return out


# ---------------------------------------------------------------------------
# Terrain: the tiles' lakes joining the elevation's sea
# ---------------------------------------------------------------------------
class TestTerrainCoast:
    """_coast_dots strokes the union of the sea and the *stroked* half
    of the tile mask, so a pond is dry ground as far as the stroke is
    concerned and untouched as far as the fill is."""

    GW, HC = 8, 4                            # 16 x 16 dots

    def _land(self):
        return [[80.0] * (self.GW * 2) for _ in range(self.HC * 4)]

    def test_the_lake_is_stroked_and_the_ponds_are_not(self):
        water = blank(self.GW * 2, self.HC * 4)
        blob(water, 1, 1, 5, 6)              # 30 dots
        for y in (1, 5, 9):                  # three ponds, 4 dots each
            blob(water, 10, y, 2, 2)
        dots = _coast_dots(self._land(), self.GW, self.HC, water)
        assert any(any(row[:5]) for row in dots), "the lake drew no shore"
        assert not any(any(row[5:]) for row in dots), "a pond drew one"

    def test_a_pond_earns_its_shore_at_a_closer_zoom(self):
        # The same pond, drawn twice as big because the view came in a
        # zoom: nothing about the water changed, only its size on
        # screen, and that is the whole rule.
        far = blank(self.GW * 2, self.HC * 4)
        blob(far, 4, 4, 4, 4)                # 16 dots
        assert not any(any(row)
                       for row in _coast_dots(self._land(), self.GW,
                                              self.HC, far))
        near = blank(self.GW * 2, self.HC * 4)
        blob(near, 4, 4, 6, 6)               # 36 dots
        assert any(any(row)
                   for row in _coast_dots(self._land(), self.GW,
                                          self.HC, near))

    def test_the_sea_is_never_weighed(self):
        # The sea comes from the elevation, not the tiles, and it is not
        # a body the rule has any opinion about: one dot column of it is
        # still a coast.
        fine = self._land()
        for row in fine:
            row[0] = -5.0                    # 16 dots, but sea
        assert any(any(row) for row in _coast_dots(fine, self.GW, self.HC))
        small = self._land()
        for y in range(2):
            small[y][0] = -5.0               # 2 dots of sea
        assert any(any(row) for row in _coast_dots(small, self.GW, self.HC))

    def test_min_dots_zero_is_the_globe_s_way_out(self):
        # The globe sieves its lakes as it carves them (_LAKE_MIN_DOTS),
        # on both the built and the baked path, and asks for the flat
        # view's rule to stay out of it.
        water = blank(self.GW * 2, self.HC * 4)
        blob(water, 4, 4, 2, 2)
        assert not any(any(row) for row in _coast_dots(
            self._land(), self.GW, self.HC, water))
        assert any(any(row) for row in _coast_dots(
            self._land(), self.GW, self.HC, water, min_dots=0))


# ---------------------------------------------------------------------------
# Street: the same rule, the same function, its own fill
# ---------------------------------------------------------------------------
GW, HC = 8, 4                                # 16 x 16 dots
QUARTER = rect(0, 0, EXTENT // 4, EXTENT)    # 4 dot cols x 16 rows = 64
# A pond of four dots, off on its own.  Longitude is linear in tile
# space and latitude is not, so its columns (12-13) are worked out and
# its rows (2-3) are measured; together they are dot rows 2-3 of cell
# row 0, sub-pixel row 1 — which the assertions below name.
POND = rect(EXTENT * 3 // 4, EXTENT // 4,
            EXTENT * 3 // 4 + EXTENT // 8, EXTENT // 4 + EXTENT // 8)
POND_CELL = (6, 0)


def street(*layers, band=7):
    return st.build_street_view(WORLD, GW, HC, {Z0: tile(*layers)}, band)


def water_and_pond():
    return layer("water",
                 [feature(QUARTER, tags=(0, 0)), feature(POND, tags=(0, 0))],
                 keys=("class",), values=(vstr("lake"),))


class TestStreetCoast:
    def test_the_pond_is_filled_and_only_the_lake_is_stroked(self):
        fills, layer_, _overlays = street(water_and_pond())
        water_ink = style.palette()["water"]
        # the pond is two dots by two, which is exactly one sub-pixel of
        # fill — it is water on the map
        assert fills[1][6] == water_ink
        # ...and draws no braille anywhere near itself
        assert any(layer_.dots[r][2] for r in range(HC)), \
            "the lake drew no shore"
        assert not any(m for row in layer_.dots for m in row[5:]), \
            "the pond drew one"

    def test_it_is_the_same_rule_terrain_uses(self):
        # Not "the same idea" — the same function over the same mask,
        # so the two registers cannot drift apart.
        view = st.decode_view({Z0: tile(water_and_pond())})
        mask = st.inland_water_mask(view, WORLD, GW, HC)
        _fills, layer_, _overlays = street(water_and_pond())
        expected = st._edge_dots(
            [bytearray(1 - v for v in row) for row in st.stroked_water(mask)],
            st.stroked_water(mask), GW, HC)
        for cy, row in enumerate(expected):
            for cx, m in enumerate(row):
                assert layer_.dots[cy][cx] & m == m

    def test_the_pond_still_answers_hover_from_its_fill(self):
        # Losing a shoreline is not losing an identity: a reader
        # pointing into the pond is still told they are on water.
        _fills, layer_, _overlays = street(water_and_pond())
        hit = layer_.hover.at(*POND_CELL)
        assert hit is not None and hit.kind == "hov_water"

    def test_the_lake_answers_from_its_shore_and_its_middle_alike(self):
        _fills, layer_, _overlays = street(water_and_pond())
        middle, rim = layer_.hover.at(0, 1), layer_.hover.at(2, 1)
        assert middle is not None and rim is not None
        assert middle.kind == rim.kind == "hov_water"
        assert middle.cells == rim.cells and rim.cells

    def test_a_river_centreline_is_not_a_body_of_water(self):
        # `waterway` is line work and never asks the rule anything: a
        # brook through a view of ponds is drawn as it always was.
        brook = polyline((0, EXTENT // 2), (EXTENT, EXTENT // 2))
        _fills, layer_, _overlays = street(
            tagged_line("waterway", brook, {"class": "river"}),
            classed("water", POND, "pond"))
        assert any(m for row in layer_.dots for m in row), \
            "the river was not drawn"
