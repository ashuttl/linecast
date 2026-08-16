"""Tests for street-mode label placement.

The pure functions — occupancy, cell paths, horizontal runs — are tested
directly; the placement pass is driven by hand-encoded tiles, in the
same style as test_maps_streets. The event loop is left untested, per
house precedent.

The view is the whole world (the z0 tile), where longitude is exactly
linear in both tile and view space, so a feature's column is derivable
by hand: at gw=40 a tile x of 2048 lands on column 20.
"""

import sys
from pathlib import Path

import pytest

# Ensure the worktree src is preferred over any installed version.
_src = str(Path(__file__).resolve().parent.parent / "src")
if _src not in sys.path:
    sys.path.insert(0, _src)

from linecast import _maps_labels as lb
from linecast import _maps_streets as st
from linecast import _maps_style
from linecast._radar_basemap import _load_data

from test_maps_streets import (
    EXTENT, WORLD, feature, field, layer, line_feature, polyline, rect,
    tile, varint, vint, vstr, zigzag,
)

GW, HC = 40, 8
DARK_BG = (14, 15, 18)


@pytest.fixture(autouse=True)
def _truecolor(monkeypatch):
    monkeypatch.setattr(_maps_style, "color_mode", lambda: "truecolor")
    monkeypatch.setattr(_maps_style, "theme_bg", DARK_BG)


def point(x, y):
    return b"".join(varint(n) for n in
                    [(1 << 3) | 1, zigzag(x), zigzag(y)])


def point_feature(x, y, tags=()):
    out = field(3, 0, 1)                      # type: point
    if tags:
        out += field(2, 2, b"".join(varint(t) for t in tags))
    return out + field(4, 2, point(x, y))


def features_layer(name, items, geom):
    """One layer holding several features over a shared key/value table.

    Two layers of the same name in one tile would collide in the decoded
    dict, so everything of a kind goes in one layer — which is what a
    real tile does anyway.
    """
    keys, values, feats = [], [], []
    for args, props in items:
        tags = []
        for k, v in props.items():
            payload = vint(v) if isinstance(v, int) else vstr(v)
            if k not in keys:
                keys.append(k)
            if payload not in values:
                values.append(payload)
            tags += [keys.index(k), values.index(payload)]
        feats.append(geom(args, tags))
    return layer(name, feats, keys=keys, values=values)


def points(name, *items):
    """A point layer: items are (x, y, props)."""
    return features_layer(
        name, [((x, y), props) for x, y, props in items],
        lambda a, tags: point_feature(a[0], a[1], tags))


def lines(name, *items):
    """A linestring layer: items are (geometry, props)."""
    return features_layer(name, [(g, props) for g, props in items],
                          lambda g, tags: line_feature(g, tags))


def place_layer(x, y, props):
    return points("place", (x, y, props))


def overlays(*layers, band=7, lang="en", reserved=(), tiles=None):
    view = st.decode_view(tiles or {(0, 0, 0): tile(*layers)})
    return lb.label_overlays(view, WORLD, GW, HC, band,
                             _maps_style.palette(), lang, reserved)


def text_at(ov, row):
    """The characters placed on one row, left to right."""
    return "".join(ch for (_c, r), (ch, *_rest) in sorted(ov.items())
                   if r == row)


def all_text(ov):
    """Every placed character, row by row then column by column."""
    return "".join(ch for (c, r), (ch, *_rest)
                   in sorted(ov.items(), key=lambda kv: kv[0][::-1]))


# ---------------------------------------------------------------------------
# Occupancy
# ---------------------------------------------------------------------------
class TestOccupancy:
    def test_a_claim_blocks_its_own_cells(self):
        occ = lb.Occupancy(20, 3)
        assert occ.free(1, 5, 4)
        occ.claim(1, 5, 4)
        assert not occ.free(1, 5, 4)
        assert not occ.free(1, 8, 1)

    def test_one_cell_of_padding_either_side(self):
        # The padding *is* the halo: a label flattens its cells' braille,
        # and one free cell each side stops it touching the next mark.
        occ = lb.Occupancy(20, 3)
        occ.claim(1, 5, 4)          # cells 5..8, padded to 4..9
        assert not occ.free(1, 4, 1)
        assert not occ.free(1, 9, 1)
        assert not occ.free(1, 3, 1)   # 3 is adjacent to the padded 4
        assert occ.free(1, 11, 1)

    def test_padding_does_not_wrap_or_run_off_the_edge(self):
        occ = lb.Occupancy(10, 3)
        occ.claim(0, 0, 2)
        assert not occ.free(0, 0, 1)
        assert occ.free(0, 4, 6)       # exactly fills the row
        assert not occ.free(0, 5, 6)   # one past the edge
        assert not occ.free(0, -1, 2)

    def test_rows_are_independent(self):
        occ = lb.Occupancy(20, 3)
        occ.claim(1, 5, 4)
        assert occ.free(0, 5, 4)
        assert occ.free(2, 5, 4)
        assert not occ.free(-1, 5, 4)
        assert not occ.free(3, 5, 4)


# ---------------------------------------------------------------------------
# Cell paths and runs
# ---------------------------------------------------------------------------
class TestCellPath:
    def test_dots_collapse_into_cells(self):
        # A cell is 2 dots wide and 4 tall.
        pts = [(0, 0), (2, 0), (4, 0)]
        assert lb.cell_path(pts, 10, 2) == [(0, 0), (1, 0), (2, 0)]

    def test_cells_between_distant_vertices_are_walked(self):
        # A generalised road has few vertices; the cells it crosses must
        # still be contiguous or no run can carry a label.
        path = lb.cell_path([(0, 0), (12, 0)], 10, 2)
        assert path == [(c, 0) for c in range(7)]

    def test_off_view_cells_are_dropped(self):
        path = lb.cell_path([(0, 0), (40, 0), (0, 0)], 10, 2)
        assert path
        assert all(0 <= c < 10 and 0 <= r < 2 for c, r in path)

    def test_a_far_vertex_costs_a_step_not_a_hundred_thousand(self):
        path = lb.cell_path([(0, 0), (2_000_000, 0)], 10, 2)
        assert len(path) <= 11


# ---------------------------------------------------------------------------
# Candidates
# ---------------------------------------------------------------------------
class TestPlaceCandidates:
    def test_a_city_gets_its_anchor_and_name(self):
        ov = overlays(place_layer(2048, 2048,
                                  {"class": "city", "name": "Metropolis"}))
        assert "•Metropolis" in text_at(ov, HC // 2)

    def test_an_unlisted_class_is_dropped_never_guessed_at(self):
        ov = overlays(place_layer(2048, 2048,
                                  {"class": "island", "name": "Nowhere"}))
        assert ov == {}

    def test_an_area_class_is_spaced_caps_with_no_anchor(self):
        ov = overlays(place_layer(2048, 2048,
                                  {"class": "suburb", "name": "Old Port"}))
        row = text_at(ov, HC // 2)
        assert row == _maps_style.spaced("Old Port")
        assert "•" not in row

    def test_a_class_outside_its_band_window_is_not_a_candidate(self):
        # Country names render B0-B2; deeper than that they are noise.
        args = place_layer(2048, 2048,
                           {"class": "country", "name": "Atlantis"})
        assert overlays(args, band=1) != {}
        assert overlays(args, band=5) == {}

    def test_ranked_places_win_the_cell_they_share(self):
        # A city outranks a village, so the village is the one dropped.
        ov = overlays(points(
            "place",
            (2048, 2048, {"class": "village", "name": "Bree"}),
            (2100, 2048, {"class": "city", "name": "Gondor"})))
        row = text_at(ov, HC // 2)
        assert "Gondor" in row
        assert "Bree" not in row

    def test_a_name_in_the_readers_language_is_preferred(self):
        ov = overlays(place_layer(2048, 2048,
                                  {"class": "city", "name": "Cologne",
                                   "name:de": "Köln"}), lang="de")
        assert "Köln" in text_at(ov, HC // 2)


class TestPlaceSourceSwitch:
    """Natural Earth leads below band 3 and the tile's own places fill
    in underneath; from band 3 up the tile is the sole source."""

    def _cands(self, layers, band):
        view = st.decode_view({(0, 0, 0): tile(*layers)})
        return lb.place_candidates(view, WORLD, GW, HC, band, "en")

    def test_low_bands_still_take_tile_settlements(self):
        # Natural Earth is a world list — over three counties of Maine
        # it holds one city — so it cannot be the only source.
        town = place_layer(2048, 2048, {"class": "town", "name": "Tileton"})
        assert "Tileton" in [c[2] for c in self._cands([town], 2)]
        assert "Tileton" in text_at(overlays(town, band=3), HC // 2)

    def test_the_vendored_majors_still_lead_below_the_switch(self):
        town = place_layer(2048, 2048, {"class": "town", "name": "Tileton"})
        names = [c[2] for c in self._cands([town], 2)]
        biggest = max(_load_data()["cities"], key=lambda e: e[2])[3]
        assert names[0] == biggest
        assert names.index("Tileton") > 100

    def test_a_place_named_by_both_sources_appears_once(self):
        biggest = max(_load_data()["cities"], key=lambda e: e[2])[3]
        town = place_layer(2048, 2048, {"class": "city", "name": biggest})
        names = [c[2] for c in self._cands([town], 2)]
        assert names.count(biggest) == 1

    def test_the_tile_rank_orders_the_towns(self):
        many = points("place", *[
            (1000 + i * 300, 2048,
             {"class": "town", "name": f"T{i}", "rank": 20 - i})
            for i in range(6)])
        names = [c[2] for c in self._cands([many], 3)]
        assert names == ["T5", "T4", "T3", "T2", "T1", "T0"]

    def test_low_bands_keep_tile_country_and_state_names(self):
        state = place_layer(2048, 2048,
                            {"class": "state", "name": "Maine"})
        assert overlays(state, band=2) != {}

    def test_low_bands_take_settlements_from_natural_earth(self):
        # The whole world at band 0: the vendored cities are the source,
        # and the biggest of them must be among the survivors.
        view = st.decode_view({(0, 0, 0): tile(layer("place", []))})
        ov = lb.label_overlays(view, WORLD, 200, 40, 0,
                               _maps_style.palette(), "en")
        placed = "".join(ch for _pos, (ch, *_r) in sorted(ov.items()))
        assert placed
        biggest = max(_load_data()["cities"], key=lambda e: e[2])[3]
        assert biggest[:4] in placed


class TestRoadLabels:
    def test_a_shield_is_the_ref_upper_cased_and_hyphenated(self):
        road = lines("transportation_name",
                     (polyline((1024, 2048), (3072, 2048)),
                      {"class": "motorway", "ref": "i 95"}))
        assert "I-95" in text_at(overlays(road), HC // 2)

    def test_a_long_ref_is_not_a_shield(self):
        road = lines("transportation_name",
                     (polyline((1024, 2048), (3072, 2048)),
                      {"class": "motorway", "ref": "A-1234567"}))
        assert text_at(overlays(road), HC // 2) == ""

    def test_a_street_name_is_centred_on_its_own_road(self):
        road = lines("transportation_name",
                     (polyline((0, 2048), (4096, 2048)),
                      {"class": "primary", "name": "Long Street"}))
        assert "Long Street" in text_at(overlays(road), HC // 2)

    def test_a_vertical_road_is_labelled_too(self):
        # The old rule wanted a horizontal run of road; measured over
        # downtown Portland the longest one is about seven cells where
        # the names want fifteen, so almost nothing was ever labelled.
        # The name is written across the road instead.
        road = lines("transportation_name",
                     (polyline((2048, 0), (2048, 4096)),
                      {"class": "primary", "name": "Vertical Way"}))
        placed = all_text(overlays(road))
        assert "Vertical Way" in placed

    def test_a_name_wider_than_the_view_is_still_dropped(self):
        road = lines("transportation_name",
                     (polyline((2000, 2048), (2200, 2048)),
                      {"class": "primary", "name": "X" * (GW + 4)}))
        assert overlays(road) == {}

    def test_every_segment_of_a_street_is_one_candidate(self):
        # OpenStreetMap splits a street at each junction; labelling the
        # first fragment in the tile is not labelling the street.
        road = lines(
            "transportation_name",
            (polyline((0, 2048), (1024, 2048)),
             {"class": "primary", "name": "Long Street"}),
            (polyline((1024, 2048), (4096, 2048)),
             {"class": "primary", "name": "Long Street"}))
        ov = overlays(road)
        assert all_text(ov).count("Long Street") == 1
        view = st.decode_view({(0, 0, 0): tile(road)})
        _shields, streets = lb.road_candidates(view, WORLD, GW, HC, 7, "en")
        assert len(streets) == 1
        assert len(streets[0][3]) > GW // 2      # both segments' cells

    def test_a_road_below_its_own_debut_band_is_not_named(self):
        # A name has no business on screen at a zoom where the road it
        # names is not drawn.
        road = lines("transportation_name",
                     (polyline((0, 2048), (4096, 2048)),
                      {"class": "secondary", "name": "Ridge Road"}))
        assert "Ridge Road" not in all_text(overlays(road, band=3))
        assert "Ridge Road" in all_text(overlays(road, band=4))

    def test_a_numbered_road_is_labelled_by_its_number_alone(self):
        # You navigate ME-196 by "196", not by "Lisbon Street"; a second
        # label on the same road says less and costs the same.
        road = lines("transportation_name",
                     (polyline((0, 2048), (4096, 2048)),
                      {"class": "trunk", "ref": "196",
                       "name": "Lisbon Street"}))
        placed = all_text(overlays(road, band=2))
        assert "196" in placed
        assert "Lisbon Street" not in placed

    def test_shields_are_ordered_by_road_not_by_number(self):
        # The four shields a view can afford should be the four biggest
        # roads, not the four lowest numbers.
        road = lines(
            "transportation_name",
            (polyline((0, 1024), (4096, 1024)),
             {"class": "trunk", "ref": "11"}),
            (polyline((0, 3072), (4096, 3072)),
             {"class": "motorway", "ref": "95"}))
        view = st.decode_view({(0, 0, 0): tile(road)})
        shields, _streets = lb.road_candidates(view, WORLD, GW, HC, 2, "en")
        assert [s[2] for s in shields] == ["95", "11"]


class TestPoi:
    def _poi(self, x, props):
        return points("poi", (x, 2048, props))

    def test_a_tier_one_landmark_gets_its_glyph(self):
        ov = overlays(self._poi(2048, {"class": "hospital"}), band=6)
        assert _maps_style.GLYPH_MEDICAL in text_at(ov, HC // 2)

    def test_noise_is_dropped_before_anything_else(self):
        assert overlays(self._poi(2048, {"class": "parking",
                                         "name": "Lot A"})) == {}

    def test_an_indoor_feature_is_dropped(self):
        assert overlays(self._poi(2048, {"class": "hospital",
                                         "indoor": 1})) == {}

    def test_an_unnamed_tier_three_is_dropped(self):
        assert overlays(self._poi(2048, {"class": "cafe"})) == {}
        named = self._poi(2048, {"class": "cafe", "name": "Bard"})
        assert _maps_style.GLYPH_GENERIC in text_at(overlays(named),
                                                    HC // 2)

    def test_a_tier_one_poi_is_named_at_the_deepest_band(self):
        poi = self._poi(2048, {"class": "museum", "name": "Art Museum"})
        assert "Art Museum" in text_at(overlays(poi, band=7), HC // 2)
        assert "Art Museum" not in text_at(overlays(poi, band=6), HC // 2)

    def test_a_long_poi_name_is_the_one_thing_that_truncates(self):
        poi = self._poi(2048, {"class": "museum",
                               "name": "Museum of Extremely Fine Art"})
        row = text_at(overlays(poi, band=7), HC // 2)
        assert "…" in row
        assert len(row) <= _maps_style.POI_TEXT_MAX + 3

    def test_a_peak_carries_its_elevation_from_band_five(self):
        peak = points("mountain_peak",
                      (2048, 2048, {"name": "Katahdin", "ele": 1606}))
        assert "Katahdin 5,269 ft" in text_at(overlays(peak, band=5),
                                              HC // 2)
        assert text_at(overlays(peak, band=4), HC // 2) \
            == _maps_style.GLYPH_PEAK

    def test_an_aerodrome_is_a_glyph_and_never_a_name(self):
        field_ = points("aerodrome_label",
                        (2048, 2048, {"name": "Portland Jetport"}))
        assert text_at(overlays(field_, band=4), HC // 2) \
            == _maps_style.GLYPH_AIRPORT


# ---------------------------------------------------------------------------
# Budgets, priority and determinism
# ---------------------------------------------------------------------------
class TestPlacementDiscipline:
    def _cities(self, n):
        return points("place", *[
            (200 + i * 180, 2048,
             {"class": "city", "name": f"City{i:02d}", "rank": i + 1})
            for i in range(n)])

    def test_the_place_budget_is_a_ceiling(self):
        ov = overlays(self._cities(20))
        anchors = sum(1 for v in ov.values()
                      if v[0] == _maps_style.GLYPH_GENERIC)
        assert anchors == _maps_style.place_budget(
            _maps_style.label_budget(GW, HC))

    def test_the_highest_ranked_candidates_are_the_survivors(self):
        ov = overlays(self._cities(20))
        placed = "".join(ch for _pos, (ch, *_r) in sorted(ov.items()))
        assert "City00" in placed
        assert "City19" not in placed

    def test_reserved_cells_are_routed_around(self):
        # The marker and the crosshair are placed first and always win;
        # a label must not try to share their cells.
        cell = (20, HC // 2)
        ov = overlays(place_layer(2048, 2048,
                                  {"class": "city", "name": "Metropolis"}),
                      reserved=(cell,))
        assert cell not in ov

    def test_placement_does_not_depend_on_feature_order(self):
        a = (1000, 2048, {"class": "city", "name": "Alpha"})
        b = (3000, 2048, {"class": "town", "name": "Beta"})
        assert overlays(points("place", a, b)) \
            == overlays(points("place", b, a))

    def test_a_duplicate_across_a_seam_is_placed_once(self):
        # The same feature clipped into two tiles: keep the first in tile
        # order and discard the rest, so a seam never doubles a label.
        one = tile(place_layer(2048, 2048,
                               {"class": "city", "name": "Twice"}))
        placed = all_text(overlays(tiles={(1, 0, 0): one, (1, 1, 0): one}))
        assert placed.count("Twice") == 1


class TestWideGlyphs:
    def test_a_double_width_name_keeps_the_row_aligned(self):
        # The swallowed column carries an empty sentinel, exactly as the
        # Natural Earth city labels do, so the row stays in step.
        ov = overlays(place_layer(2048, 2048,
                                  {"class": "city", "name": "東京"}))
        row = HC // 2
        cols = sorted(c for (c, r) in ov if r == row)
        # anchor, then each wide glyph plus the column it swallows
        assert [ov[(c, row)][0] for c in cols] == ["•", "東", "", "京", ""]

    def test_cjk_is_never_spaced_or_upper_cased(self):
        ov = overlays(place_layer(2048, 2048,
                                  {"class": "suburb", "name": "銀座"}))
        assert text_at(ov, HC // 2) == "銀座"


# ---------------------------------------------------------------------------
# Water
# ---------------------------------------------------------------------------
def water_grid(rows):
    """A cell-resolution water mask from an ASCII picture ('~' = water)."""
    return [[ch == "~" for ch in row] for row in rows]


class TestWaterRegions:
    def test_separate_bodies_are_separate_regions(self):
        index, regions = lb.water_regions(water_grid([
            "~~..~",
            "~~...",
            ".....",
        ]))
        assert len(regions) == 2
        areas = sorted(a for a, _anchor, _span in regions)
        assert areas == [1, 4]
        assert index[2][0] == -1

    def test_the_anchor_is_a_cell_of_its_own_region(self):
        # A crescent's centre of mass is outside it, so the anchor is
        # the nearest cell that is actually in the shape.
        mask = water_grid([
            "~~~~~",
            "~...~",
            "~~~~~",
        ])
        index, regions = lb.water_regions(mask)
        assert len(regions) == 1
        _area, (col, row), _span = regions[0]
        assert mask[row][col]

    def test_the_span_is_the_width_the_label_has_to_fit(self):
        _index, regions = lb.water_regions(water_grid([".~~~.", ".~~~."]))
        assert regions[0][2] == 3

    def test_an_empty_view_has_no_regions(self):
        index, regions = lb.water_regions(water_grid(["...", "..."]))
        assert regions == []
        assert index == [[-1] * 3, [-1] * 3]


class TestWaterAttachment:
    MASK = water_grid(["..~~~", "..~~~", "..~~~"])

    def test_a_point_on_the_water_names_the_water_under_it(self):
        index, regions = lb.water_regions(self.MASK)
        area, at, _span = lb._attach((3, 1), index, regions, 5, 3)
        assert at == (3, 1)
        assert area == 9

    def test_a_point_off_the_view_is_dragged_to_the_water(self):
        # The Gulf of Maine's own anchor sits seventy cells off the
        # right edge of a view it fills a third of; the label still
        # belongs on the water you can see.
        index, regions = lb.water_regions(self.MASK)
        hit = lb._attach((9, 1), index, regions, 5, 3)
        assert hit is not None
        _area, at, _span = hit
        assert self.MASK[at[1]][at[0]]

    def test_a_point_further_than_a_view_away_is_dropped(self):
        # Sebago Lake's anchor is two screens west of a Portland
        # harbour view.  Dragging it to the edge names Casco Bay after
        # a lake you cannot see, so it is not dragged at all.
        index, regions = lb.water_regions(self.MASK)
        assert lb._attach((-6, 1), index, regions, 5, 3) is None
        assert lb._attach((10, 1), index, regions, 5, 3) is None
        assert lb._attach((3, -4), index, regions, 5, 3) is None

    def test_a_point_that_reaches_no_water_is_dropped(self):
        index, regions = lb.water_regions(water_grid(["....."] * 3))
        assert lb._attach((2, 1), index, regions, 5, 3) is None
        assert lb._attach(None, index, regions, 5, 3) is None


class TestWaterNames:
    """OpenMapTiles' water_name generalisation is inverted for small
    features — every gut on the Maine coast is in the tile from z8,
    while Casco Bay and Sebago Lake wait until z10 — so class decides
    when a water name may appear, not the tile's own zoom filtering."""

    def _water(self, cls, name):
        return points("water_name", (2048, 2048, {"class": cls,
                                                  "name": name}))

    def _sea(self):
        # A whole-view lake, so any name fits inside it.
        from test_maps_streets import WHOLE, classed
        return classed("water", WHOLE, "lake")

    def test_a_strait_waits_for_the_navigation_bands(self):
        gut = [self._sea(), self._water("strait", "The Gut")]
        assert "T H E   G U T" not in all_text(overlays(*gut, band=3))
        assert "T H E   G U T" in all_text(overlays(*gut, band=6))

    def test_a_bay_shows_early(self):
        bay = [self._sea(), self._water("bay", "Casco Bay")]
        assert "C A S C O   B A Y" in all_text(overlays(*bay, band=3))

    def test_a_lake_waits_for_band_three(self):
        lake = [self._sea(), self._water("lake", "Sebago Lake")]
        assert "S E B A G O" not in all_text(overlays(*lake, band=2))
        assert "S E B A G O" in all_text(overlays(*lake, band=3))

    def test_an_area_label_must_fit_inside_the_area_it_names(self):
        # A forest parcel ten cells across does not get a forty-cell
        # name laid over the county it sits in.
        speck = layer("park", [feature(rect(2040, 2040, 2056, 2056),
                                       tags=(0, 0))],
                      keys=("name",), values=(vstr("Leavitt Plantation"),))
        assert overlays(speck, band=7) == {}

    def test_a_park_big_enough_to_hold_its_name_keeps_it(self):
        from test_maps_streets import WHOLE
        big = layer("park", [feature(WHOLE, tags=(0, 0))],
                    keys=("name",), values=(vstr("City Park"),))
        assert "C I T Y   P A R K" in all_text(overlays(big, band=7))
