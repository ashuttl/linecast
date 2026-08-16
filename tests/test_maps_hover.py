"""Tests for street-mode hover: what the pointer finds, and what lights.

The resolution order is the whole design — a placed glyph, then the
stroke that owns the cell's ink, then the area fill — so most of these
build a HoverIndex by hand and ask it one question at a time. Two go
through build_street_view end to end, because the join between the
`transportation` geometry and the `transportation_name` names only
exists once both have been rasterised into the same cells.
"""

import re
import sys
from pathlib import Path

import pytest

# Ensure the worktree src is preferred over any installed version.
_src = str(Path(__file__).resolve().parent.parent / "src")
if _src not in sys.path:
    sys.path.insert(0, _src)

from linecast import _color, _maps_hover as hv, _maps_i18n, _maps_style as style
from linecast import _maps_streets as st
from linecast.maps import compose_map

from test_maps_streets import (  # the tile-fixture writer, reused wholesale
    DARK_BG, EXTENT, GW, HC, LEFT_HALF, WHOLE, WORLD, Z0, classed, cmd, layer,
    feature, line_feature, polyline, rect, tile, varint, vstr, zigzag,
)
from test_maps_labels import points

ENGLISH = set(_maps_i18n._STRINGS["en"])

RED = (200, 60, 60)
GREY = (132, 136, 150)


@pytest.fixture(autouse=True)
def _truecolor(monkeypatch):
    monkeypatch.setattr(style, "color_mode", lambda: "truecolor")
    monkeypatch.setattr(style, "theme_bg", DARK_BG)


def _strip(s):
    return re.sub(r"\033\[[^m]*m", "", s)


# ---------------------------------------------------------------------------
# The word tables
# ---------------------------------------------------------------------------
class TestWords:
    """Every class the map can draw must be a class hover can say."""

    def test_every_line_class_has_a_word(self):
        # All but the route: it is UI rather than cartography, is drawn
        # in its own layer rather than into the view's ink contest, and
        # names itself in the header for as long as it exists.
        assert set(hv.LINE_WORD) == set(style.LINE_STYLES) - {"route"}

    def test_every_fill_but_the_ground_has_a_word(self):
        # The ground is not a thing; index 0 deliberately has no word.
        assert set(hv.AREA_WORD) == set(range(1, len(style.FILL_ORDER)))
        assert 0 not in hv.AREA_WORD

    def test_every_word_is_a_real_string_key(self):
        assert set(hv.LINE_WORD.values()) <= ENGLISH
        assert set(hv.AREA_WORD.values()) <= ENGLISH

    def test_glyph_marks_reuse_the_legend_words(self):
        # Hover and the ? panel name a glyph from one table, so a mark
        # can never be called one thing in the legend and another here.
        assert set(style.GLYPH_LEGEND) == set(style.GLYPH_INK)
        assert set(style.GLYPH_LEGEND.values()) <= ENGLISH


# ---------------------------------------------------------------------------
# Resolution order
# ---------------------------------------------------------------------------
def index(owner=None, feats=(), names=None, marks=None, area=None,
          texts=None, gw=4, hc=2):
    """A HoverIndex over a small grid, defaulting to empty everything."""
    return hv.HoverIndex(
        owner or [[None] * gw for _ in range(hc)],
        list(feats),
        names or {},
        marks or {},
        area or [bytearray(gw) for _ in range(hc)],
        texts or {})


WATER = style.FILL_ORDER.index("water")
PARK = style.FILL_ORDER.index("park")


class TestResolutionOrder:
    def test_a_glyph_beats_the_stroke_beneath_it(self):
        # A POI sits on cells a road may also cross; the glyph is what
        # the reader can actually see there.
        owner = [[0, None, None, None], [None] * 4]
        idx = index(owner=owner, feats=[("minor", "")],
                    marks={(0, 0): ("poi_hospital", "Mercy", 3)})
        # A glyph has no ink of its own: its cells are all characters.
        assert idx.at(0, 0) == hv.Hit("Mercy", "poi_hospital", (), ((0, 0),))

    def test_a_stroke_beats_the_fill_beneath_it(self):
        area = [bytearray([WATER, 0, 0, 0]), bytearray(4)]
        idx = index(owner=[[0, None, None, None], [None] * 4],
                    feats=[("waterway_major", "")], area=area)
        assert idx.at(0, 0).kind == "hov_river"

    def test_the_fill_answers_when_nothing_is_drawn(self):
        area = [bytearray([WATER, PARK, 0, 0]), bytearray(4)]
        idx = index(area=area)
        assert idx.at(0, 0) == hv.Hit("", "hov_water", (), ())
        assert idx.at(1, 0) == hv.Hit("", "hov_park", (), ())

    def test_bare_ground_says_nothing_rather_than_naming_the_paper(self):
        assert index().at(2, 0) is None

    def test_off_the_grid_is_a_miss_not_a_crash(self):
        idx = index()
        assert idx.at(-1, 0) is None
        assert idx.at(0, -1) is None
        assert idx.at(99, 0) is None
        assert idx.at(0, 99) is None


class TestMarks:
    def test_every_cell_of_a_label_lights_the_whole_label(self):
        entry = ("poi_civic", "Portland City Hall", 0)
        marks = {(0, 0): entry, (1, 0): entry, (2, 0): entry}
        hit = index(marks=marks).at(1, 0)
        assert hit.name == "Portland City Hall"
        assert set(hit.glyphs) == {(0, 0), (1, 0), (2, 0)}

    def test_two_unnamed_marks_of_a_class_stay_apart(self):
        # The sequence number is what keeps one unnamed café from
        # lighting up the other one across the view.
        marks = {(0, 0): ("poi_other", "", 0), (3, 1): ("poi_other", "", 1)}
        assert index(marks=marks).at(0, 0).glyphs == ((0, 0),)


class TestStrokes:
    def test_an_unnamed_stroke_lights_only_its_own_cells(self):
        owner = [[0, 0, 1, None], [None] * 4]
        idx = index(owner=owner, feats=[("service", ""), ("service", "")])
        hit = idx.at(0, 0)
        assert hit == hv.Hit("", "hov_service", ((0, 0), (1, 0)), ())
        assert idx.at(2, 0).cells == ((2, 0),)

    def test_a_named_stroke_lights_every_cell_of_the_name(self):
        # draw_lines merges by (class, name), so one owner index already
        # covers every segment the tile split the river into.
        owner = [[0, None, 0, None], [None] * 4]
        idx = index(owner=owner, feats=[("waterway_major", "Presumpscot")])
        assert idx.at(0, 0) == hv.Hit("Presumpscot", "hov_river",
                                      ((0, 0), (2, 0)), ())

    def test_the_road_name_index_supplies_what_the_stroke_lacks(self):
        # `transportation` carries no names; the join is by cell.
        path = ((0, 0), (1, 0), (2, 0))
        names = {c: {"minor": ("Fox Street", path)} for c in path}
        idx = index(owner=[[0, 0, 0, None], [None] * 4],
                    feats=[("minor", "")], names=names)
        assert idx.at(1, 0) == hv.Hit("Fox Street", "hov_minor", path, ())

    def test_a_name_of_the_wrong_class_is_not_borrowed(self):
        # Taking the only name at a cell was measured over downtown
        # Portland: 13% more names, all of them class disagreements —
        # which is how a shoreline gets labelled after the trail beside
        # it.  A stroke that reports its class alone has told the truth.
        names = {(0, 0): {"path": ("Back Cove Trail", ((0, 0),))}}
        idx = index(owner=[[0, None, None, None], [None] * 4],
                    feats=[("coast", "")], names=names)
        assert idx.at(0, 0) == hv.Hit("", "hov_coast", ((0, 0),), ())

    def test_a_stroke_lights_the_label_that_names_it(self):
        # A road label is written across the road rather than anchored
        # to it, so the link back is the name itself.
        texts = {(0, 1): "Fox Street", (1, 1): "Fox Street"}
        idx = index(owner=[[0, 0, None, None], [None] * 4],
                    feats=[("minor", "Fox Street")], texts=texts)
        hit = idx.at(0, 0)
        assert hit.cells == ((0, 0), (1, 0))
        assert set(hit.glyphs) == {(0, 1), (1, 1)}

    def test_a_stroke_never_lights_someone_else_s_label(self):
        # The whole bug: a label a hovered road passes behind belongs to
        # something else, and bolting the two letters they share on to
        # the highlight says the road is called "ll".
        idx = index(owner=[[0, 0, None, None], [None] * 4],
                    feats=[("minor", "")],
                    texts={(0, 0): "Thompson Hill", (1, 0): "Thompson Hill"})
        assert idx.at(0, 0).glyphs == ()

    def test_a_ramp_borrows_the_name_of_the_road_it_leaves(self):
        # OpenMapTiles flags `ramp` on the geometry layer and not on the
        # name layer, so a slip road's name is filed under its parent.
        names = {(0, 0): {"motorway": ("I 295", ((0, 0),))}}
        idx = index(owner=[[0, None, None, None], [None] * 4],
                    feats=[("ramp", "")], names=names)
        assert idx.at(0, 0).name == "I 295"
        assert idx.at(0, 0).kind == "hov_ramp"


# ---------------------------------------------------------------------------
# The readout and the highlight
# ---------------------------------------------------------------------------
class TestReadout:
    def test_a_name_and_a_class_read_together(self):
        hit = hv.Hit("Franklin Street", "hov_primary", (), ())
        assert hv.readout(hit, "en") == "Franklin Street · primary road"

    def test_a_nameless_feature_is_just_its_class(self):
        assert hv.readout(hv.Hit("", "hov_water", (), ()), "en") == "water"

    def test_a_classless_mark_is_just_its_name(self):
        assert hv.readout(hv.Hit("Somewhere", "", (), ()), "en") == "Somewhere"

    def test_the_class_translates_and_the_placename_does_not(self):
        hit = hv.Hit("Rue de Rivoli", "hov_minor", (), ())
        assert hv.readout(hit, "fr") == "Rue de Rivoli · rue"


class TestHighlight:
    def test_a_dark_theme_lifts_an_ink_toward_white(self, monkeypatch):
        monkeypatch.setattr(style, "theme_bg", (14, 15, 18))
        assert all(a > b for a, b in zip(hv.highlight(GREY), GREY))

    def test_a_light_theme_lifts_an_ink_toward_black(self, monkeypatch):
        monkeypatch.setattr(style, "theme_bg", (250, 250, 248))
        assert all(a < b for a, b in zip(hv.highlight(GREY), GREY))

    def test_it_never_becomes_a_new_hue(self, monkeypatch):
        # The style spec spends exactly three accents; a hovered feature
        # keeps its own ink and only moves along its ladder.
        monkeypatch.setattr(style, "theme_bg", (14, 15, 18))
        amber = style.PALETTE_DARK["motorway"]
        lift = hv.highlight(amber)
        assert lift[0] > lift[1] > lift[2]      # still warm

    def test_an_unpainted_ink_stays_unpainted(self):
        assert hv.highlight(None) is None


class _Layer:
    """Duck-type for the ranked DotLayer compose_map reads."""

    def __init__(self, dots, color):
        self.dots, self.color, self.ribbon = dots, color, set()


class TestComposeHighlight:
    """The composer's half: lit cells go bold in a lifted ink."""

    def _compose(self, hot, monkeypatch, overlays=None, hot_glyphs=None):
        monkeypatch.setattr(_color, "_COLOR_MODE", "truecolor")
        monkeypatch.setitem(compose_map.__globals__, "color_mode",
                            lambda: "truecolor")
        # BOLD is bound at import from a tty check, so a piped test run
        # has it empty; patch the composer's own global, as the colour
        # mode already is.
        monkeypatch.setitem(compose_map.__globals__, "BOLD", "\033[1m")
        fills = [[DARK_BG, DARK_BG], [DARK_BG, DARK_BG]]
        layer_ = _Layer([[0x01, 0x01]], [[GREY, GREY]])
        return compose_map(fills, layer_, overlays or {}, 2, 1, hot=hot,
                           hot_glyphs=hot_glyphs)[0]

    def test_a_lit_cell_goes_bold_and_a_cold_one_does_not(self, monkeypatch):
        lit = self._compose({(0, 0)}, monkeypatch)
        assert "\033[1m" in lit
        assert lit.count("\033[1m") == 1     # only the one cell
        assert "\033[1m" not in self._compose(None, monkeypatch)

    def test_a_lit_cell_keeps_its_braille(self, monkeypatch):
        assert _strip(self._compose({(0, 0)}, monkeypatch)) == "⠁⠁"

    def test_the_lift_is_the_cell_s_own_ink(self, monkeypatch):
        monkeypatch.setattr(style, "theme_bg", DARK_BG)
        want = hv.highlight(GREY)
        assert f"38;2;{want[0]};{want[1]};{want[2]}" \
            in self._compose({(0, 0)}, monkeypatch)

    def test_a_letter_the_hot_stroke_runs_behind_stays_plain(self,
                                                             monkeypatch):
        # The cell is a character, and the character belongs to a label
        # of something else; the road merely passes behind it.
        line = self._compose({(0, 0), (1, 0)}, monkeypatch,
                             overlays={(0, 0): ("H", GREY, False)})
        assert "\033[1m" not in line.split("H")[0]
        assert _strip(line) == "H⠁"

    def test_a_letter_of_the_hot_feature_s_own_label_goes_bold(self,
                                                               monkeypatch):
        line = self._compose({(1, 0)}, monkeypatch,
                             overlays={(0, 0): ("H", GREY, False)},
                             hot_glyphs={(0, 0)})
        assert line.count("\033[1m") == 2       # the letter and the ink


# ---------------------------------------------------------------------------
# End to end, through the rasteriser
# ---------------------------------------------------------------------------
def _road_tile(cls="secondary", name="Fox Street"):
    """A road across the middle of the world, named in the other layer.

    OpenMapTiles files geometry in `transportation` and names in
    `transportation_name`, over its own copy of the same line — which is
    exactly the join hover has to make.
    """
    across = polyline((0, EXTENT // 2), (EXTENT, EXTENT // 2))
    geom = layer("transportation",
                 [line_feature(across, tags=(0, 0))],
                 keys=("class",), values=(vstr(cls),))
    named = layer("transportation_name",
                  [line_feature(across, tags=(0, 0, 1, 1))],
                  keys=("class", "name"),
                  values=(vstr(cls), vstr(name)))
    return tile(geom, named)


def _multiline(*paths):
    """Several linestrings in one feature's geometry.

    This is what a tile encoder does to a class before it ships it: the
    cursor carries across parts, which is why the deltas here are taken
    from wherever the previous part ended rather than from the origin.
    """
    nums, cx, cy = [], 0, 0
    for pts in paths:
        nums += [cmd(1, 1), zigzag(pts[0][0] - cx), zigzag(pts[0][1] - cy),
                 cmd(2, len(pts) - 1)]
        cx, cy = pts[0]
        for p in pts[1:]:
            nums += [zigzag(p[0] - cx), zigzag(p[1] - cy)]
            cx, cy = p
    return b"".join(varint(n) for n in nums)


def _merged_tile(cls="minor"):
    """Two unconnected streets, shipped as one multi-part feature.

    Not a contrivance: OpenMapTiles merges every line sharing a class
    and its attributes, so a whole town's unnamed residential streets
    arrive as a single feature with hundreds of parts in it.
    """
    left = ((0, EXTENT // 2), (int(EXTENT * 0.4), EXTENT // 2))
    right = ((int(EXTENT * 0.6), EXTENT // 2), (EXTENT, EXTENT // 2))
    return tile(layer("transportation",
                      [line_feature(_multiline(left, right), tags=(0, 0))],
                      keys=("class",), values=(vstr(cls),)))


def _lake_tile(name, cls="lake", geom=LEFT_HALF, at=EXTENT // 4):
    """A lake, named in `water_name`.

    OpenMapTiles files the water *polygon* in `water` and its name in
    `water_name`, as a bare point — so naming a lake is an attachment
    between a point and the body of water it lands in.  `at` is where
    that point falls, which decides where the label is centred and so
    whether it fits the view at all.
    """
    return tile(classed("water", geom, cls),
                points("water_name",
                       (at, EXTENT // 2, {"class": cls, "name": name})))


def _hover_at(tiles, band=7, gw=GW, hc=HC):
    _fills, layer_, _overlays = st.build_street_view(
        WORLD, gw, hc, {Z0: tiles}, band)
    return layer_.hover


def _hover_owner(idx, cell):
    """The ink-contest winner at a cell, straight off the grid."""
    return idx.owner[cell[1]][cell[0]]


class TestEndToEnd:
    def test_a_road_is_named_from_the_other_layer(self):
        idx = _hover_at(_road_tile())
        hits = [idx.at(c, r) for r in range(HC) for c in range(GW)]
        named = [h for h in hits if h and h.name]
        assert named, "the road was drawn but never named"
        assert named[0].name == "Fox Street"
        assert named[0].kind == "hov_secondary"

    def test_hovering_one_end_lights_the_whole_road(self):
        idx = _hover_at(_road_tile())
        hits = [h for h in (idx.at(c, r) for r in range(HC)
                            for c in range(GW)) if h and h.name]
        # every cell the road crosses belongs to the one lit set
        assert len(set(hits[0].cells)) >= GW - 1

    def test_water_answers_where_no_stroke_does(self):
        idx = _hover_at(tile(classed("water", LEFT_HALF, "lake")))
        # column 0 is deep inside the lake; column 3 is open ground
        assert idx.at(0, 0).kind == "hov_water"
        assert idx.at(GW - 1, 0) is None

    def test_a_body_of_water_is_one_feature(self):
        # Every stretch of this body's rim answers with the same thing,
        # whatever that thing turns out to be called.  (This one is out
        # in the South Pacific, so the vendored marine list has a name
        # for it — see test_the_open_sea_takes_the_name_of_its_sea.)
        idx = _hover_at(tile(classed("water", LEFT_HALF, "lake")))
        rim = [h for h in (idx.at(c, r) for r in range(HC)
                           for c in range(GW))
               if h and h.kind in ("hov_coast", "hov_water")]
        assert rim, "the lake drew no shore"
        assert len({h.cells for h in rim}) == 1

    def test_the_open_sea_takes_the_name_of_its_sea(self):
        # `water_name` had nothing to say here, but the vendored marine
        # list does, and a reader pointing at open water would rather be
        # told which sea than told "water".  It is the answer the wide
        # bands already give; it just no longer stops at band 3.
        idx = _hover_at(tile(classed("water", LEFT_HALF, "ocean")))
        hit = idx.at(0, 0)
        assert hit.name == "South Pacific Ocean"
        assert hv.readout(hit, "en") == "South Pacific Ocean · water"

    def test_a_named_body_still_outranks_the_sea_it_sits_in(self):
        # The backdrop goes under the tile's own names, never over them.
        idx = _hover_at(_lake_tile("Graham Lake"))
        assert idx.at(0, 0).name == "Graham Lake"

    def test_one_part_of_a_merged_feature_lights_alone(self):
        # The tile's feature is not the reader's street.  Owning it per
        # feature lit every unnamed road in the view at once.
        idx = _hover_at(_merged_tile())
        left, right = idx.at(0, 0), idx.at(GW - 1, 0)
        assert left is not None and right is not None
        assert left.kind == right.kind == "hov_minor"
        assert set(left.cells).isdisjoint(right.cells)

    def test_a_named_lake_names_itself_from_the_middle_and_the_rim(self):
        # One thing cannot have two readouts: pointing at the water and
        # pointing at the edge of it are the same question.
        idx = _hover_at(_lake_tile("Graham Lake"))
        middle, rim = idx.at(0, 0), idx.at(2, 0)
        assert middle.name == rim.name == "Graham Lake"
        assert middle.kind == rim.kind == "hov_water"
        assert middle.cells == rim.cells        # both light the rim
        assert hv.readout(middle, "en") == "Graham Lake · water"

    def test_a_lake_lights_its_rim_and_never_its_fill(self):
        # The fill is painted behind everything; lifting it would light
        # the ground rather than a thing standing on it.
        idx = _hover_at(_lake_tile("Graham Lake"))
        hit = idx.at(0, 0)
        assert hit.cells, "the lake drew no shore to light"
        assert all(_hover_owner(idx, c) is not None for c in hit.cells)
        assert (0, 0) not in hit.cells          # the water itself, unlit

    def test_a_lake_lights_the_label_that_names_it(self):
        # A wider view than the rest of these: a water name is set in
        # spaced caps, so "P O N D" wants seven cells, and it has to fit
        # inside its own water or it is dropped before it is written.
        idx = _hover_at(_lake_tile("Pond", geom=WHOLE, at=EXTENT // 2),
                        gw=12, hc=2)
        written = {c for c, n in idx.texts.items() if n == "Pond"}
        assert len(written) == 7, "the lake's name was never written"
        assert set(idx.at(0, 0).glyphs) == written

    def test_a_body_is_named_even_when_its_label_was_dropped(self):
        # Naming the water is worth more than one label: the budget
        # decides what gets written, never what a pointer may know.
        idx = _hover_at(_lake_tile("Umbagog"))  # too wide for the lake
        assert not idx.texts
        assert idx.at(0, 0).name == "Umbagog"

    def test_two_ponds_stay_apart_even_unnamed(self):
        # The tile names neither, and "water" is all either can say —
        # but it can say it about one pond instead of about every pond.
        west = rect(0, -EXTENT, EXTENT // 4, 2 * EXTENT)
        east = rect(EXTENT * 3 // 4, -EXTENT, EXTENT, 2 * EXTENT)
        idx = _hover_at(tile(layer(
            "water",
            [feature(west, tags=(0, 0)), feature(east, tags=(0, 0))],
            keys=("class",), values=(vstr("lake"),))))
        left, right = idx.at(0, 0), idx.at(GW - 1, 0)
        assert left.kind == right.kind == "hov_water"
        assert left.cells and right.cells
        assert set(left.cells).isdisjoint(right.cells)

    def test_a_class_the_band_does_not_draw_is_not_hoverable(self):
        # A service road has no weight at band 4, so nothing owns the
        # ink and hover must not claim it does.
        idx = _hover_at(_road_tile(cls="service"), band=4)
        assert all(idx.at(c, r) is None
                   for r in range(HC) for c in range(GW))

    def test_a_legend_gloss_is_reduced_to_its_general_term(self):
        # "civic · school" covers a glyph's whole range; a pointer is
        # over one thing, and the alternatives would arrive wearing the
        # readout's own separator.
        hit = hv.Hit("Portland City Hall", "poi_civic", (), ())
        assert hv.readout(hit, "en") == "Portland City Hall · civic"
        assert hv.readout(hit, "de") == "Portland City Hall · Amt"

    def test_a_single_term_gloss_is_untouched(self):
        hit = hv.Hit("", "poi_hospital", (), ())
        assert hv.readout(hit, "en") == "hospital"
