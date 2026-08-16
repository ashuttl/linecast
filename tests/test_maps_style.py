"""Tests for the street-mode style tables.

_maps_style is pure data plus pure functions, so everything here is
exact: the colour assertions run the real _color ladder rather than
trusting the table comments, and the zoom/scale assertions carry their
derivations.

Colour mode and theme are read through names bound in the module
namespace, so both are patched on the module object (never re-imported)
— the house pattern that survives the test_oneline sys.modules purge.
"""

import math
import sys
from pathlib import Path

import pytest

# Ensure the worktree src is preferred over any installed version.
_src = str(Path(__file__).resolve().parent.parent / "src")
if _src not in sys.path:
    sys.path.insert(0, _src)

from linecast import _maps_style as ms
from linecast._color import _CUBE_LEVELS, _rgb_to_ansi16, _rgb_to_xterm256
from linecast._framebuffer import visible_len
from linecast._theme import luminance

DARK_BG = (14, 15, 18)
LIGHT_BG = (253, 246, 227)      # solarized light, a real cream terminal
LEGACY_BG = (15, 23, 42)        # --classic-colors forces exactly this

# The road ladder, least to most important. Every mode must keep these
# six distinguishable and strictly ordered.
LADDER = ("path", "service", "minor", "secondary", "primary", "trunk")


def _mode(monkeypatch, mode, bg=DARK_BG):
    """Pin the colour mode and terminal background for one test."""
    monkeypatch.setattr(ms, "color_mode", lambda: mode)
    monkeypatch.setattr(ms, "theme_bg", bg)


def _xterm_rgb(idx):
    """The RGB an xterm-256 index actually paints."""
    if idx >= 232:
        v = 8 + 10 * (idx - 232)
        return (v, v, v)
    i = idx - 16
    return tuple(_CUBE_LEVELS[c] for c in (i // 36, (i // 6) % 6, i % 6))


# ---------------------------------------------------------------------------
# Palette structure
# ---------------------------------------------------------------------------
def test_palettes_carry_the_same_keys():
    assert set(ms.PALETTE_DARK) == set(ms.PALETTE_LIGHT)


def test_palette_16_is_a_subset():
    # PALETTE_16 is deliberately partial: keys it omits fall back to
    # _PALETTE_16_DEFAULT. It must never invent a key of its own.
    assert set(ms.PALETTE_16) <= set(ms.PALETTE_DARK)


@pytest.mark.parametrize("mode", ["truecolor", "256", "16", "none"])
def test_ink_is_defined_for_every_key_in_every_mode(monkeypatch, mode):
    _mode(monkeypatch, mode)
    for key in ms.PALETTE_DARK:
        value = ms.ink(key)
        assert value is None or (len(value) == 3
                                 and all(0 <= c <= 255 for c in value))


def test_ink_falls_back_to_the_coarse_default(monkeypatch):
    _mode(monkeypatch, "16")
    assert "lbl_town" not in ms.PALETTE_16
    assert ms.ink("lbl_town") == ms._PALETTE_16_DEFAULT
    assert ms.ink("water") == (0, 0, 128)
    assert ms.ink("ground") is None       # coarse mode paints no ground


# ---------------------------------------------------------------------------
# Ground derivation
# ---------------------------------------------------------------------------
def test_ground_is_the_only_theme_blended_value(monkeypatch):
    # A tinted terminal bg the anchor does not already match, so the
    # blend is visible: 14% of (40,10,60) over the (14,15,18) anchor.
    _mode(monkeypatch, "truecolor", (40, 10, 60))
    p = ms.palette()
    assert p["ground"] == ms.ground_color() == (18, 14, 24)
    assert p["ground"] != ms.PALETTE_DARK["ground"]
    for key, value in ms.PALETTE_DARK.items():
        if key != "ground":
            assert p[key] == value


def test_legacy_navy_survives_as_a_faint_cast(monkeypatch):
    # --classic-colors forces theme_bg to the old navy; no branch needed.
    _mode(monkeypatch, "truecolor", LEGACY_BG)
    assert ms.ground_color() == (14, 16, 21)
    assert ms.palette() is not ms.PALETTE_DARK
    assert ms.palette()["motorway"] == ms.PALETTE_DARK["motorway"]


@pytest.mark.parametrize("bg,anchor", [
    ((0, 0, 0), ms._GROUND_ANCHOR_DARK),          # pure black terminal
    (LEGACY_BG, ms._GROUND_ANCHOR_DARK),
    (LIGHT_BG, ms._GROUND_ANCHOR_LIGHT),
    ((255, 255, 255), ms._GROUND_ANCHOR_LIGHT),   # pure white terminal
])
def test_ground_stays_within_a_few_units_of_its_anchor(monkeypatch, bg,
                                                       anchor):
    # 14% of theme tint must never move the ground far enough to break
    # the ladder above it.
    _mode(monkeypatch, "truecolor", bg)
    assert all(abs(a - b) <= 4 for a, b in zip(ms.ground_color(), anchor))


def test_light_theme_selects_the_light_palette(monkeypatch):
    _mode(monkeypatch, "truecolor", LIGHT_BG)
    p = ms.palette()
    assert p["trunk"] == ms.PALETTE_LIGHT["trunk"]
    assert p["ground"] == ms.ground_color()


# ---------------------------------------------------------------------------
# The luminance ladder
# ---------------------------------------------------------------------------
def test_road_ladder_is_monotone_in_truecolor():
    dark = [luminance(ms.PALETTE_DARK[k]) for k in LADDER]
    light = [luminance(ms.PALETTE_LIGHT[k]) for k in LADDER]
    assert dark == sorted(dark), "dark ladder must brighten with rank"
    assert light == sorted(light, reverse=True), "light ladder inverts"
    assert len(set(dark)) == len(set(light)) == len(LADDER)


def test_road_ladder_survives_the_256_snap():
    for palette, ascending in ((ms.PALETTE_DARK, True),
                               (ms.PALETTE_LIGHT, False)):
        snapped = [luminance(_xterm_rgb(_rgb_to_xterm256(*palette[k])))
                   for k in LADDER]
        assert snapped == sorted(snapped, reverse=not ascending)
        assert len(set(snapped)) == len(LADDER), "six distinct steps"


def test_dark_fills_stay_ordered_under_the_256_snap():
    # The cube's lowest non-zero level is 95, so every dark fill
    # collapses to gray; water is deliberately *lighter* than land so
    # the read survives as a value step rather than a hue step.
    order = ("ground", "park", "building", "water")
    snapped = [luminance(_xterm_rgb(_rgb_to_xterm256(*ms.PALETTE_DARK[k])))
               for k in order]
    assert snapped == sorted(snapped)
    assert len(set(snapped)) == len(order)


def test_motorway_and_marker_never_collide():
    marker = (255, 240, 120)                    # radar.MARKER, unchanged
    motorway = ms.PALETTE_DARK["motorway"]
    assert luminance(marker) > luminance(motorway) * 1.4
    assert _rgb_to_xterm256(*marker) != _rgb_to_xterm256(*motorway)
    # ...and in the coarse table the marker takes bright yellow while
    # the motorway drops to dark yellow.
    assert _rgb_to_ansi16(*ms.MARKER_16) == 11
    assert _rgb_to_ansi16(*ms.PALETTE_16["motorway"]) == 3


def test_only_sanctioned_inks_are_warm():
    warm = {k for k, v in ms.PALETTE_DARK.items() if v[0] > v[2] + 20}
    assert warm == {"motorway", "ramp", "lbl_shield", "poi_med"}


# ---------------------------------------------------------------------------
# 16-colour snapping
# ---------------------------------------------------------------------------
# Every anchor in PALETTE_16 exists only to land on an exact index. If
# one is edited without re-running the ladder, this table catches it.
EXPECT_16 = {
    "water": 4, "coast": 12, "waterway": 12, "motorway": 3, "ramp": 3,
    "trunk": 15, "primary": 15, "secondary": 7, "minor": 7,
    "service": 8, "path": 8, "rail": 8, "transit": 8, "aeroway": 8,
    "border0": 8, "border1": 8, "route": 14, "lbl_city": 15,
    "lbl_road": 15, "lbl_shield": 15, "poi_med": 9,
}


def test_every_coarse_anchor_hits_its_exact_index():
    painted = {k for k, v in ms.PALETTE_16.items() if v is not None}
    assert painted == set(EXPECT_16), "a new anchor needs a verified index"
    for key, idx in EXPECT_16.items():
        assert _rgb_to_ansi16(*ms.PALETTE_16[key]) == idx, key


def test_coarse_fills_are_unpainted():
    for key in ("ground", "urban", "park", "building"):
        assert ms.PALETTE_16[key] is None


def test_coarse_light_theme_swaps_white_for_black(monkeypatch):
    _mode(monkeypatch, "16", LIGHT_BG)
    p = ms.palette()
    assert p["trunk"] == (0, 0, 0)
    assert _rgb_to_ansi16(*p["trunk"]) == 0
    assert p["lbl_city"] == p["lbl_road"] == p["lbl_shield"] == (0, 0, 0)
    assert p["secondary"] == (192, 192, 192)    # mid-ladder untouched
    assert p["water"] == (0, 0, 128)


def test_none_mode_keeps_the_coarse_table_unswapped(monkeypatch):
    # `none` emits no escapes at all, so the light-theme swap is moot;
    # what matters is that the fills stay unpainted.
    _mode(monkeypatch, "none", LIGHT_BG)
    p = ms.palette()
    assert p["trunk"] == (255, 255, 255)
    assert p["ground"] is None


# ---------------------------------------------------------------------------
# Zoom
# ---------------------------------------------------------------------------
def test_z_eff_matches_hand_derived_views():
    # (a) the --zoom 4.0 default on an 80x24 terminal (hc=22) at lat
    #     43.66: m/dot = 4.0*110540/88 = 5024.5;
    #     z = log2(156543.034*cos43.66 / 5024.5) = 4.494 -> band 1.
    assert ms.z_eff((-71.0, 41.66, -69.0, 45.66), 22) == pytest.approx(
        4.4944, abs=5e-4)
    # (b) --zoom 0.1, the old floor: m/dot = 126 -> 9.816 -> band 3.
    assert ms.z_eff((-71.0, 43.61, -69.0, 43.71), 22) == pytest.approx(
        9.8163, abs=5e-4)
    # (c) 1 degree at the equator over 25 cells: m/dot = 110540/100 =
    #     1105.4; z = log2(156543.034/1105.4) = 7.1458.
    assert ms.z_eff((0.0, -0.5, 1.0, 0.5), 25) == pytest.approx(
        7.1458, abs=5e-4)


def test_z_eff_scales_with_height_not_width():
    tall = ms.z_eff((-71.0, 43.61, -69.0, 43.71), 44)
    short = ms.z_eff((-71.0, 43.61, -69.0, 43.71), 22)
    assert tall == pytest.approx(short + 1.0)   # twice the rows, one z
    wide = ms.z_eff((-75.0, 43.61, -65.0, 43.71), 22)
    assert wide == short                        # width changes nothing


def test_band_for_at_every_edge():
    eps = 1e-9
    for i, edge in enumerate(ms.BAND_EDGES):
        assert ms.band_for(edge - eps) == i
        assert ms.band_for(edge) == i + 1
    assert ms.band_for(-1.0) == 0
    assert ms.band_for(99.0) == len(ms.BAND_EDGES)


def test_band_for_matches_the_reference_zooms():
    assert ms.band_for(0.59) == 0
    assert ms.band_for(4.49) == 1
    assert ms.band_for(9.82) == 3
    assert ms.band_for(13.00) == 6
    assert ms.band_for(14.88) == 7


def test_z_src_rounds_to_nearest_and_clamps():
    assert ms.z_src(4.49, 1) == 4
    assert ms.z_src(4.51, 1) == 5
    assert ms.z_src(-3.0, 0) == 0
    assert ms.z_src(0.59, 0) == 1
    # B6+ pins every layer to z14 so the z14-only poi layer is present
    # the moment B6 debuts tier-1 glyphs.
    for band in (6, 7):
        for z in (13.0, 14.88, 15.88, 20.0):
            assert ms.z_src(z, band) == 14
    assert ms.z_src(13.9, 5) == 14              # clamped by min(), too


def test_every_line_class_debuts_at_or_after_its_data_floor():
    # A band must never ask for a class the tile does not carry.
    floors = {"motorway": 1, "trunk": 2, "primary": 3, "secondary": 4,
              "minor": 5, "service": 6, "path": 6, "transit": 6,
              "rail": 4}
    for key, first_band in floors.items():
        weights = ms.LINE_STYLES[key][1]
        assert weights[first_band] > 0, key
        assert all(w == 0 for w in weights[:first_band]), key


# ---------------------------------------------------------------------------
# Line styles and adapters
# ---------------------------------------------------------------------------
def test_line_ranks_read_as_the_intended_sentence():
    rank = {k: v[3] for k, v in ms.LINE_STYLES.items()}
    assert rank["route"] > rank["motorway"]         # the user beats the map
    assert rank["motorway"] > rank["trunk"] > rank["primary"]
    assert rank["primary"] > rank["secondary"] > rank["minor"]
    assert rank["minor"] > rank["service"] > rank["rail"]
    assert rank["rail"] > rank["transit"] > rank["path"]
    assert rank["path"] > rank["coast"]             # a bridge wins its cell
    assert rank["coast"] > rank["border_country"] > rank["border_state"]
    assert rank["border_state"] > rank["ferry"]     # ferry never cuts shore
    assert rank["ferry"] > rank["waterway_major"] > rank["waterway_minor"]
    assert len(set(rank.values())) == len(rank), "ranks must be distinct"


def test_every_line_ink_exists_in_the_palette():
    for key, (ink_key, weights, dash, rank) in ms.LINE_STYLES.items():
        assert ink_key in ms.PALETTE_DARK, key
        assert len(weights) == 8, key
        assert all(0 <= w <= 3 for w in weights), key
        assert dash is None or (len(dash) == 2 and all(d > 0 for d in dash))


def test_line_weight_indexes_directly_by_band():
    assert ms.line_weight("motorway", 0) == 0
    assert ms.line_weight("motorway", 1) == 1
    assert ms.line_weight("motorway", 7) == 3   # the only w3 in the table
    assert sum(1 for k in ms.LINE_STYLES
               if 3 in ms.LINE_STYLES[k][1]) == 1


def test_road_adapter_merges_tertiary_down():
    # Tertiary's OMT floor (z12) is minor's, not secondary's — merging
    # up would promise tertiary at B4 where the tile has none.
    assert ms.road_style({"class": "tertiary"}) == "minor"
    assert ms.road_style({"class": "residential"}) == "minor"
    assert ms.road_style({"class": "secondary"}) == "secondary"


def test_road_adapter_ramp_override():
    assert ms.road_style({"class": "motorway", "ramp": 1}) == "ramp"
    assert ms.road_style({"class": "trunk", "ramp": 1}) == "ramp"
    assert ms.road_style({"class": "motorway"}) == "motorway"
    assert ms.road_style({"class": "motorway", "ramp": 0}) == "motorway"
    # A ramp off a primary is still a primary — only motorway/trunk.
    assert ms.road_style({"class": "primary", "ramp": 1}) == "primary"


def test_road_adapter_drops_what_the_spec_drops():
    for cls in ("pier", "raceway", "aerialway", "", None, "unknown"):
        assert ms.road_style({"class": cls}) is None
    assert ms.road_style({}) is None


def test_boundary_adapter():
    assert ms.boundary_style({"admin_level": 2}) == "border_country"
    assert ms.boundary_style({"admin_level": 1}) == "border_country"
    assert ms.boundary_style({"admin_level": 4}) == "border_state"
    assert ms.boundary_style({"admin_level": 3}) == "border_state"
    assert ms.boundary_style({"admin_level": 5}) is None
    assert ms.boundary_style({"admin_level": 2, "maritime": 1}) is None
    assert ms.boundary_style({"admin_level": 2, "disputed": 1}) \
        == "border_country"
    assert ms.boundary_style({}) is None


def test_waterway_and_aeroway_adapters():
    assert ms.waterway_style({"class": "river"}) == "waterway_major"
    for cls in ("stream", "canal", "ditch", "drain"):
        assert ms.waterway_style({"class": cls}) == "waterway_minor"
    assert ms.waterway_style({"class": "dock"}) is None
    assert ms.aeroway_style({"class": "runway"}) == "aeroway_runway"
    assert ms.aeroway_style({"class": "taxiway"}) == "aeroway_taxi"
    for cls in ("apron", "helipad", None):
        assert ms.aeroway_style({"class": cls}) is None


def test_every_adapter_target_is_a_real_style_key():
    produced = set()
    produced.update(ms.OMT_ROAD_CLASS.values())
    produced.update({"ramp", "border_country", "border_state",
                     "waterway_major", "waterway_minor",
                     "aeroway_runway", "aeroway_taxi"})
    assert produced <= set(ms.LINE_STYLES)


# ---------------------------------------------------------------------------
# Labels
# ---------------------------------------------------------------------------
def test_spaced_caps():
    assert ms.spaced("Portland") == "P O R T L A N D"
    assert ms.spaced("east end") == "E A S T   E N D"   # space -> 3 cells


def test_spaced_leaves_wide_scripts_alone():
    # CJK is never uppercased and never spaced: the glyphs are already
    # double-width and spacing would double the cost again.
    assert ms.spaced("東京") == "東京"
    assert ms.spaced("ソウル") == "ソウル"


def test_label_styles_use_only_palette_inks():
    for cls, (ink_key, case, bold) in ms.LABEL_STYLES.items():
        assert ink_key in ms.PALETTE_DARK, cls
        assert case in ("title", "spaced", "upper"), cls
        assert isinstance(bold, bool)


def test_only_four_label_classes_are_bold():
    bold = {c for c, style in ms.LABEL_STYLES.items() if style[2]}
    assert bold == {"city", "state", "country", "shield"}


def test_class_rank_orders_places_and_omits_the_rest():
    ranks = ms.CLASS_RANK
    assert ranks["country"] < ranks["state"] < ranks["city"]
    assert ranks["city"] < ranks["town"] < ranks["village"] < ranks["hamlet"]
    assert ranks["suburb"] == ranks["neighbourhood"]
    # An unlisted class has no rank at all — the caller drops it rather
    # than guessing a default.
    assert ranks.get("isolated_dwelling") is None
    assert ranks.get("island") is None


def test_water_rank():
    assert ms.WATER_RANK["ocean"] < ms.WATER_RANK["sea"]
    assert ms.WATER_RANK["sea"] < ms.WATER_RANK["bay"]
    assert ms.WATER_RANK["bay"] < ms.WATER_RANK["lake"]
    assert ms.WATER_RANK.get("pond", 4) == 4


def test_water_bands_gate_the_navigation_features_late():
    # The tiles carry every gut from z8 and Casco Bay only from z10, so
    # class decides when a water name may show, not the tile's zoom.
    assert ms.WATER_BANDS["ocean"] == ms.WATER_BANDS["sea"] == 0
    assert ms.WATER_BANDS["bay"] < ms.WATER_BANDS["lake"]
    assert ms.WATER_BAND_DEFAULT > max(ms.WATER_BANDS.values())
    for cls in ("strait", "dock", "swimming_pool"):
        assert cls not in ms.WATER_BANDS


# ---------------------------------------------------------------------------
# Budgets
# ---------------------------------------------------------------------------
def test_budgets_at_the_reference_terminal():
    # 80x24 -> gw 80, hc 22: the numbers the spec was written against.
    total = ms.label_budget(80, 22)
    assert total == 16
    assert ms.place_budget(total) == 9
    assert ms.street_budget(total) == 6
    assert ms.shield_budget(total) == 4
    assert ms.water_park_budget(total) == 3
    assert ms.poi_glyph_budget(80, 22) == 12
    assert ms.poi_text_budget(total) == 3


def test_budgets_clamp_at_both_extremes():
    assert ms.label_budget(20, 8) == 5           # floor
    assert ms.label_budget(400, 100) == 24       # ceiling
    assert ms.poi_glyph_budget(20, 8) == 4
    assert ms.poi_glyph_budget(400, 100) == 16
    assert ms.place_budget(2) == 2
    assert ms.street_budget(2) == 2
    assert ms.water_park_budget(2) == 2
    assert ms.poi_text_budget(2) == 0            # may legitimately be 0


def test_sub_budgets_are_ceilings_not_reservations():
    # They deliberately over-subscribe the total: unused place slots do
    # not flow to streets, and the page may be under-filled.
    total = ms.label_budget(80, 22)
    assert (ms.place_budget(total) + ms.street_budget(total)) <= total


def test_road_label_repeat_allowance():
    assert ms.max_instances(0) == 1
    assert ms.max_instances(39) == 1
    assert ms.max_instances(40) == 2
    assert ms.max_instances(120) == 4


# ---------------------------------------------------------------------------
# POI
# ---------------------------------------------------------------------------
def test_every_glyph_is_single_width():
    for glyph in ms.GLYPH_INK:
        assert visible_len(glyph) == 1, repr(glyph)
        assert len(glyph) == 1                   # no variation selector
        assert ord(glyph) < 0x1F000              # no emoji block


def test_the_glyph_set_is_exactly_ten_marks():
    assert len(ms.GLYPH_INK) == 10
    assert ms.GLYPH_STATION not in (ms.GLYPH_GENERIC, ms.GLYPH_PEAK)
    for glyph, ink_key in ms.GLYPH_INK.items():
        assert ink_key in ms.PALETTE_DARK, glyph


def test_medical_and_ferry_are_the_only_off_ink_glyphs():
    off = {g for g, k in ms.GLYPH_INK.items() if k != "poi_ink"}
    assert off == {ms.GLYPH_MEDICAL, ms.GLYPH_FERRY}
    assert ms.GLYPH_INK[ms.GLYPH_MEDICAL] == "poi_med"
    assert ms.GLYPH_INK[ms.GLYPH_FERRY] == "lbl_water"


def test_poi_tiers_are_disjoint():
    assert not (ms.POI_TIER1 & ms.POI_TIER2)
    assert not (ms.POI_TIER1 & ms.POI_TIER3)
    assert not (ms.POI_TIER2 & ms.POI_TIER3)
    tiers = ms.POI_TIER1 | ms.POI_TIER2 | ms.POI_TIER3
    assert not (tiers & ms.POI_NOISE)


def test_poi_tier_lookup():
    assert ms.poi_tier("hospital") == 1
    assert ms.poi_tier("school") == 2
    assert ms.poi_tier("cafe") == 3
    # Noise is dropped before tiering: parking alone is 244 of the 933
    # features in the Portland z14 tile.
    assert ms.poi_tier("parking") is None
    assert ms.poi_tier("bench") is None
    assert ms.poi_tier("something_new") is None


def test_poi_glyph_assignment():
    assert ms.poi_glyph("hospital") == (ms.GLYPH_MEDICAL, "poi_med")
    assert ms.poi_glyph("railway") == (ms.GLYPH_STATION, "poi_ink")
    assert ms.poi_glyph("place_of_worship") == (ms.GLYPH_WORSHIP, "poi_ink")
    assert ms.poi_glyph("museum") == (ms.GLYPH_NOTABLE, "poi_ink")
    assert ms.poi_glyph("harbor") == (ms.GLYPH_FERRY, "lbl_water")
    assert ms.poi_glyph("post") == (ms.GLYPH_CIVIC, "poi_ink")
    # An admitted class with no mark of its own takes the generic dot.
    assert ms.poi_glyph("stadium") == (ms.GLYPH_GENERIC, "poi_ink")


def test_station_glyph_has_exactly_one_meaning():
    stations = {c for c, g in ms.POI_CLASS_GLYPH.items()
                if g == ms.GLYPH_STATION}
    assert stations == {"railway"}


def test_peak_and_airport_debut_from_their_own_layers():
    # Both satisfy the data-floor invariant: mountain_peak is z7+ and
    # aerodrome_label is present well before B4.
    assert ms.POI_PEAK_BAND == 3
    assert ms.POI_AIRPORT_BAND == 4
    assert ms.POI_PEAK_LABEL_BAND > ms.POI_PEAK_BAND
    assert ms.POI_TIER_BAND[1] == 6
    assert ms.POI_TIER_BAND[2] == ms.POI_TIER_BAND[3] == 7


# ---------------------------------------------------------------------------
# Furniture
# ---------------------------------------------------------------------------
def _bbox_for(m_per_cell, gw):
    """A bbox at the equator whose cells are m_per_cell metres wide."""
    lon = m_per_cell * gw / 111320.0
    return (0.0, -0.5, lon, 0.5)


def test_scale_bar_keeps_the_largest_distance_that_fits():
    # 300 m/cell over 80 columns (max 20 cells): 5 mi would need 27
    # cells, so 2 mi at 11 wins; metric takes 5 km at 17.
    bbox = _bbox_for(300.0, 80)
    assert ms.scale_bar(bbox, 80, False) == (11, "2 mi")
    assert ms.scale_bar(bbox, 80, True) == (17, "5 km")


def test_scale_bar_exact_multiple_imperial_labels():
    # The pre-rendered labels exist because f"{d/1609.344:g} mi" makes
    # "2.00001 mi" for exactly these entries.
    assert ms.scale_bar(_bbox_for(300.0, 80), 80, False)[1] == "2 mi"
    assert ms.scale_bar(_bbox_for(600.0, 80), 80, False) == (13, "5 mi")
    assert dict(ms.NICE_IMP)[3218.688] == "2 mi"
    assert dict(ms.NICE_IMP)[8046.72] == "5 mi"
    for _, label in ms.NICE_IMP + ms.NICE_M:
        assert "." not in label


def test_scale_bar_omitted_when_nothing_fits():
    # A whole-globe view: even 1000 mi is under the four-cell minimum.
    assert ms.scale_bar((0.0, -0.5, 360.0, 0.5), 80, False) is None


def test_scale_bar_stays_within_its_cell_window():
    for m in (1.0, 12.5, 300.0, 4000.0, 90000.0, 250000.0):
        for gw in (20, 40, 80, 200):
            best = ms.scale_bar(_bbox_for(m, gw), gw, True)
            if best is not None:
                assert 4 <= best[0] <= max(4, min(20, gw // 4))
                assert best[0] <= gw


def test_nice_tables_are_ascending():
    for table in (ms.NICE_M, ms.NICE_IMP):
        distances = [d for d, _ in table]
        assert distances == sorted(distances)
        assert len(set(distances)) == len(distances)


def test_use_metric(monkeypatch):
    monkeypatch.delenv("WEATHER_UNITS", raising=False)
    assert ms.use_metric("fr") is True
    assert ms.use_metric("en") is False
    monkeypatch.setenv("WEATHER_UNITS", "metric")
    assert ms.use_metric("en") is True
    monkeypatch.setenv("WEATHER_UNITS", "imperial")
    assert ms.use_metric("en") is False


def test_attribution_short_form_is_actually_shorter():
    assert visible_len(ms.ATTRIB_TILES_SHORT) < visible_len(
        ms.ATTRIB_TILES_LONG)
    assert "OpenStreetMap" in ms.ATTRIB_TILES_SHORT
    assert "OpenFreeMap" in ms.ATTRIB_TILES_LONG


def test_modes():
    # Street leads: it is the default view, and `v` cycles from it.
    assert ms.MODES == ("street", "terrain")
    assert ms.MODES[0] == "street", "the cycle must start at the default"


def test_default_zoom_covers_every_mode():
    assert set(ms.DEFAULT_ZOOM) == set(ms.MODES)
    # street opens on a neighbourhood, terrain on a region
    assert ms.DEFAULT_ZOOM["street"] < ms.DEFAULT_ZOOM["terrain"]
    # and that neighbourhood is deep enough to have named streets (B5+)
    # in a typical window
    deg = ms.DEFAULT_ZOOM["street"]
    bbox = (-70.3, 43.6, -70.3 + deg * 2, 43.6 + deg)
    assert ms.band_for(ms.z_eff(bbox, 48)) >= 5


def test_fill_order_is_bottom_to_top():
    # Water over park (a pond in a park), park over urban, buildings
    # last. Aeroways get no fill at all.
    assert ms.FILL_ORDER == ("ground", "urban", "park", "water", "building")
    assert "aeroway" not in ms.FILL_ORDER
    for key in ms.FILL_ORDER:
        assert key in ms.PALETTE_DARK


def test_module_touches_neither_disk_nor_network():
    source = (Path(ms.__file__)).read_text()
    for forbidden in ("open(", "urllib", "requests", "socket", "Path(",
                      "_vtiles", "_http"):
        assert forbidden not in source, forbidden
    assert math is not None      # stdlib only, and only what it needs
