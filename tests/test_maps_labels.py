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
    EXTENT, WORLD, field, layer, line_feature, polyline, rect, tile,
    varint, vint, vstr, zigzag,
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

    def test_off_view_cells_are_dropped_and_break_the_run(self):
        path = lb.cell_path([(0, 0), (40, 0), (0, 0)], 10, 2)
        assert all(0 <= c < 10 for c, _r in path)
        # It leaves and comes back, so the columns are not one run.
        assert lb.horizontal_runs(path) != [(0, 0, 9)]

    def test_a_far_vertex_costs_a_step_not_a_hundred_thousand(self):
        path = lb.cell_path([(0, 0), (2_000_000, 0)], 10, 2)
        assert len(path) <= 11


class TestHorizontalRuns:
    def test_a_straight_row_is_one_run(self):
        cells = [(c, 3) for c in range(6)]
        assert lb.horizontal_runs(cells) == [(3, 0, 5)]

    def test_right_to_left_is_the_same_run(self):
        cells = [(c, 3) for c in range(5, -1, -1)]
        assert lb.horizontal_runs(cells) == [(3, 0, 5)]

    def test_a_row_change_splits_the_run(self):
        cells = [(0, 0), (1, 0), (2, 0), (3, 1), (4, 1), (5, 1)]
        assert lb.horizontal_runs(cells) == [(0, 0, 2), (1, 3, 5)]

    def test_a_direction_change_splits_the_run(self):
        cells = [(0, 0), (1, 0), (2, 0), (1, 0), (0, 0)]
        runs = lb.horizontal_runs(cells)
        assert runs[0] == (0, 0, 2)

    def test_a_single_cell_is_not_a_run(self):
        assert lb.horizontal_runs([(4, 1)]) == []
        assert lb.horizontal_runs([]) == []

    def test_a_column_gap_is_not_a_run(self):
        assert lb.horizontal_runs([(0, 0), (4, 0)]) == []

    def test_a_vertical_road_produces_nothing(self):
        # Accepted, not worked around: a rotated glyph is not available
        # and a letter-per-row column of text is unreadable.
        assert lb.horizontal_runs([(2, r) for r in range(8)]) == []


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
    """Below band 3 settlements come from Natural Earth and the tile
    contributes country/state only; from band 3 up the tile is the sole
    source.  The class sets are disjoint, so nothing is de-duplicated."""

    def test_low_bands_ignore_tile_settlements(self):
        town = place_layer(2048, 2048, {"class": "town", "name": "Tileton"})
        assert "Tileton" not in text_at(overlays(town, band=2), HC // 2)
        assert "Tileton" in text_at(overlays(town, band=3), HC // 2)

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

    def test_a_street_name_rides_its_own_horizontal_run(self):
        road = lines("transportation_name",
                     (polyline((0, 2048), (4096, 2048)),
                      {"class": "primary", "name": "Long Street"}))
        assert "Long Street" in text_at(overlays(road), HC // 2)

    def test_a_road_with_no_horizontal_run_goes_unlabelled(self):
        road = lines("transportation_name",
                     (polyline((2048, 0), (2048, 4096)),
                      {"class": "primary", "name": "Vertical Way"}))
        assert overlays(road) == {}

    def test_a_name_too_long_for_its_run_is_dropped_not_shrunk(self):
        road = lines("transportation_name",
                     (polyline((2000, 2048), (2200, 2048)),
                      {"class": "primary",
                       "name": "Extraordinarily Long Boulevard"}))
        assert overlays(road) == {}


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
