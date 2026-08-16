"""Street-mode cartography — the single source of truth for map style.

Pure data and pure functions: every colour, threshold, glyph, adapter
and label rule that street mode needs, with no file or network access
and no state.  Imports are limited to the stdlib plus ``_color`` and
``_theme`` so this module can be imported from anywhere (including a
test) without dragging in the renderer.

The design intent, condensed: the terminal is not a small screen, it is
a coarse one.  A braille cell holds exactly one ink, so hierarchy is
carried by luminance ladder first and stroke weight second — no
casings, no shadows, no second accent.  The single warm mark on the map
is the motorway; the single bright mark on the screen is the user.
Type is the scarcest resource on the page, so a label that cannot be
placed cleanly is dropped, never nudged and never shrunk.

Nothing here is mode-conditional beyond the two entries in ``MODES``
and the opening zooms beside them.  Terrain mode keeps its own palette
and borrows exactly two things from this module: those zooms, and the
waterway band gates it needs to draw a river at the same size street
mode would.
"""

import math
import os
import unicodedata

from linecast._color import color_mode
from linecast._theme import is_light_theme, lerp_rgb, theme_bg

MODES = ("street", "terrain")

# ---------------------------------------------------------------------------
# Palette
# ---------------------------------------------------------------------------
# Only the ground blends toward the user's terminal background; every
# other value is an absolute anchor calibrated against the anchor
# ground.  14% of theme tint moves the ground by at most ~4 units of
# luminance, which never breaks the ladder.
GROUND_BLEND = 0.86

_GROUND_ANCHOR_DARK = (14, 15, 18)      # anchors, NOT inks — never read
_GROUND_ANCHOR_LIGHT = (250, 250, 248)  # directly; palette() swaps them


def _light():
    """Light theme, judged on the same bg this module blends against."""
    return is_light_theme(theme_bg)


def ground_color():
    anchor = _GROUND_ANCHOR_LIGHT if _light() else _GROUND_ANCHOR_DARK
    return lerp_rgb(theme_bg, anchor, GROUND_BLEND)


PALETTE_DARK = {
    # --- area fills (half-block sub-pixels) --------------------------
    "ground":         (14, 15, 18),     # anchor; palette() swaps this
    "urban":          (24, 25, 30),
    "park":           (22, 34, 26),
    "water":          (30, 44, 62),
    "building":       (34, 36, 42),
    # --- line inks (braille strokes) ---------------------------------
    "motorway":       (245, 185, 70),   # THE accent — the only warm ink
    "ramp":           (178, 138, 60),
    "trunk":          (216, 221, 232),
    "primary":        (188, 193, 206),
    "secondary":      (158, 163, 177),
    "minor":          (132, 136, 150),
    "service":        (108, 112, 124),
    "path":           (88, 92, 104),
    "rail":           (100, 96, 126),
    "transit":        (92, 88, 118),
    "aeroway":        (120, 118, 132),
    "waterway":       (78, 124, 160),   # rivers, streams, AND ferries
    "coast":          (104, 142, 176),
    "border0":        (108, 110, 130),  # == _radar_basemap.BORDER
    "border1":        (74, 76, 94),     # state / admin-1
    "route":          (120, 210, 255),  # UI, not cartography
    # --- label inks ---------------------------------------------------
    "lbl_city":       (228, 231, 240),
    "lbl_town":       (196, 200, 212),
    "lbl_village":    (150, 155, 170),  # == radar MUTED
    "lbl_area":       (134, 140, 154),
    "lbl_road":       (168, 172, 184),
    "lbl_road_minor": (118, 122, 134),
    "lbl_shield":     (232, 178, 96),
    "lbl_water":      (112, 140, 168),
    "lbl_park":       (104, 146, 116),
    "poi_ink":        (150, 155, 170),
    "poi_med":        (208, 124, 124),
    "poi_lbl":        (122, 127, 140),
}

# Positron-derived, ladder inverted: on a light theme the road ladder
# runs dark-for-important, and admin lines go desaturated red-violet so
# a border can never read as a road.
PALETTE_LIGHT = {
    "ground":         (250, 250, 248),  # anchor; palette() swaps this
    "urban":          (242, 241, 238),
    "park":           (223, 234, 222),
    "water":          (206, 216, 222),
    "building":       (214, 214, 212),
    "motorway":       (176, 116, 20),
    "ramp":           (196, 146, 64),
    "trunk":          (52, 54, 66),
    "primary":        (76, 78, 90),
    "secondary":      (102, 104, 114),
    "minor":          (126, 128, 136),
    "service":        (150, 150, 156),
    "path":           (172, 172, 176),
    "rail":           (126, 122, 144),
    "transit":        (150, 146, 166),
    "aeroway":        (186, 186, 192),
    "waterway":       (108, 146, 178),
    "coast":          (86, 124, 158),
    "border0":        (196, 158, 162),
    "border1":        (216, 186, 190),
    "route":          (0, 132, 196),
    "lbl_city":       (38, 42, 52),
    "lbl_town":       (66, 70, 82),
    "lbl_village":    (104, 110, 124),
    "lbl_area":       (120, 126, 140),
    "lbl_road":       (96, 100, 112),
    "lbl_road_minor": (140, 144, 156),
    "lbl_shield":     (150, 96, 12),
    "lbl_water":      (78, 116, 150),
    "lbl_park":       (70, 118, 84),
    "poi_ink":        (104, 110, 124),
    "poi_med":        (172, 66, 66),
    "poi_lbl":        (130, 136, 148),
}

# In 16-colour every dark fill collapses to index 0, so the auto
# nearest-RGB path is unusable and the composer selects this coarse
# table instead.  Each anchor is chosen so _rgb_to_ansi16 returns the
# exact index in the comment; a None means "not painted — the cell
# keeps the terminal's own background".  Keys absent here fall back to
# _PALETTE_16_DEFAULT (ANSI 7).
PALETTE_16 = {
    "ground": None, "urban": None, "park": None, "building": None,
    "water":      (0, 0, 128),        # 4  navy
    "coast":      (92, 92, 255),      # 12 bright blue
    "waterway":   (92, 92, 255),      # 12
    "motorway":   (128, 128, 0),      # 3  yellow (the accent, dimmed)
    "ramp":       (128, 128, 0),      # 3
    "trunk":      (255, 255, 255),    # 15
    "primary":    (255, 255, 255),    # 15
    "secondary":  (192, 192, 192),    # 7
    "minor":      (192, 192, 192),    # 7
    "service":    (128, 128, 128),    # 8
    "path":       (128, 128, 128),    # 8
    "rail":       (128, 128, 128),    # 8
    "transit":    (128, 128, 128),    # 8
    "aeroway":    (128, 128, 128),    # 8
    "border0":    (128, 128, 128),    # 8
    "border1":    (128, 128, 128),    # 8
    "route":      (0, 255, 255),      # 14 bright cyan
    "lbl_city":   (255, 255, 255),    # 15
    "lbl_road":   (255, 255, 255),    # 15
    "lbl_shield": (255, 255, 255),    # 15
    "poi_med":    (255, 0, 0),        # 9
}
_PALETTE_16_DEFAULT = (192, 192, 192)   # 7

# Maps-local marker remap for the coarse table: bright yellow is the
# only yellow-family index left once the motorway drops to ANSI 3, and
# the marker must out-rank it.  radar.MARKER is not touched.
MARKER_16 = (255, 255, 0)               # 11


def palette():
    """The ink table for the current colour mode and theme."""
    mode = color_mode()
    if mode in ("16", "none"):
        p = dict(PALETTE_16)
        if mode == "16" and _light():
            # Top-ladder marks must not vanish on a white terminal.
            for k, v in p.items():
                if v == (255, 255, 255):
                    p[k] = (0, 0, 0)
        return p
    p = dict(PALETTE_LIGHT if _light() else PALETTE_DARK)
    p["ground"] = ground_color()
    return p


def _is_coarse(p):
    """True for a PALETTE_16-shaped table (ground is never painted)."""
    return p.get("ground") is None


def ink(key, p=None):
    """One ink by key.  Hot paths hold a palette() dict and pass it in.

    May return None in the coarse table for the fills it does not paint.
    """
    if p is None:
        p = palette()
    if key in p:
        return p[key]
    return _PALETTE_16_DEFAULT if _is_coarse(p) else PALETTE_DARK[key]


# ---------------------------------------------------------------------------
# Zoom: the z_eff model
# ---------------------------------------------------------------------------
_EQUATOR_M_PER_PX = 156543.03392        # web-mercator z0 pixel, equator


def z_eff(bbox, height_cells):
    """Style zoom: the slippy zoom whose 256px tile pixel is one dot.

    Derived from the bbox rather than from --zoom plus aspect maths, so
    it can never drift from what is actually on screen.  It scales with
    terminal height (a taller window has finer dots and earns more
    detail) and deliberately not with width.
    """
    minlon, minlat, maxlon, maxlat = bbox
    lat_c = (minlat + maxlat) / 2.0
    m_per_dot = (maxlat - minlat) * 110540.0 / (height_cells * 4)
    return math.log2(
        _EQUATOR_M_PER_PX * math.cos(math.radians(lat_c)) / m_per_dot)


def z_src(z, band):
    """Source tile zoom for a style zoom and its band.

    B6+ clamps to z14 because the poi layer is effectively z14-only
    (measured: 2 features at z13 vs 933 at z14).  Without the clamp,
    tier-1 glyphs would be near-absent for the bottom half of B6 and
    then pop in — an empty promise.  Overzoom past z14 is pure geometry
    scaling, and B6/B7 sharing one tile set is perfect cache reuse.
    """
    if band >= 6:
        return 14
    return min(14, max(0, int(math.floor(z + 0.5))))


BAND_EDGES = (4.0, 6.0, 8.0, 10.5, 11.5, 13.0, 14.5)   # 7 cuts -> B0..B7

# Opening zoom per view, in degrees of latitude.  A street map four
# degrees tall is a road atlas — B1, motorways and nothing else — so
# street opens on a neighbourhood instead, around B5, where the streets
# have names.  Terrain opens wide, which is where relief reads.
DEFAULT_ZOOM = {"street": 0.05, "terrain": 4.0}


def band_for(z):
    return sum(z >= e for e in BAND_EDGES)


# ---------------------------------------------------------------------------
# Lines
# ---------------------------------------------------------------------------
SOLID, DASH11, DASH24, DASH33, DASH44 = None, (1, 1), (2, 4), (3, 3), (4, 4)

# key: (ink, weights B0..B7, dash, rank).  `weights` is indexed directly
# by band; 0 means the class is not drawn in that band.  `dash` is
# (on, off) in dots, phase-continuous along the whole polyline.
#
# The rank ordering, read as a sentence: the user's route beats every
# map mark; the motorway beats every other road; roads beat the
# coastline (a bridge is a real thing and it wins its cells); the
# coastline beats admin borders; admin borders beat waterways; a ferry
# never cuts the shoreline; nothing beats a label.
LINE_STYLES = {
    "waterway_minor": ("waterway",  (0, 0, 0, 0, 0, 0, 1, 1), SOLID,   6),
    "waterway_major": ("waterway",  (0, 0, 0, 1, 1, 1, 1, 1), SOLID,   7),
    "ferry":          ("waterway",  (0, 0, 0, 0, 0, 1, 1, 1), DASH24,  8),
    "border_state":   ("border1",   (0, 1, 1, 1, 1, 1, 1, 1), DASH24, 10),
    "border_country": ("border0",   (1, 1, 1, 1, 1, 1, 1, 1), DASH33, 11),
    "coast":          ("coast",     (1, 1, 1, 1, 1, 1, 1, 1), SOLID,  14),
    "path":           ("path",      (0, 0, 0, 0, 0, 0, 1, 1), DASH11, 16),
    "transit":        ("transit",   (0, 0, 0, 0, 0, 0, 1, 1), DASH44, 20),
    "rail":           ("rail",      (0, 0, 0, 0, 1, 1, 1, 1), SOLID,  22),
    "aeroway_taxi":   ("aeroway",   (0, 0, 0, 0, 0, 0, 1, 1), SOLID,  24),
    "aeroway_runway": ("aeroway",   (0, 0, 0, 0, 2, 2, 2, 2), SOLID,  26),
    "service":        ("service",   (0, 0, 0, 0, 0, 0, 1, 1), SOLID,  30),
    "minor":          ("minor",     (0, 0, 0, 0, 0, 1, 1, 1), SOLID,  34),
    "secondary":      ("secondary", (0, 0, 0, 0, 1, 1, 1, 2), SOLID,  38),
    "ramp":           ("ramp",      (0, 0, 0, 0, 0, 1, 1, 1), SOLID,  40),
    "primary":        ("primary",   (0, 0, 0, 1, 1, 2, 2, 2), SOLID,  42),
    "trunk":          ("trunk",     (0, 0, 1, 2, 2, 2, 2, 2), SOLID,  46),
    "motorway":       ("motorway",  (0, 1, 1, 2, 2, 2, 2, 3), SOLID,  50),
    "route":          ("route",     (2, 2, 2, 2, 2, 2, 2, 2), SOLID,  90),
}
RAIL_TICK_EVERY = 8      # dots between rail crossties
RIBBON_BLEND = 0.30      # w3 cells blend this far toward ink("motorway")
TUNNEL_BLEND = 0.45      # tunnels lerp this far toward the ground


def line_weight(key, band):
    """Stroke weight in dots for a style key at a band; 0 = not drawn."""
    return LINE_STYLES[key][1][band]


# --- schema adapters: OpenMapTiles -> style keys --------------------------
# Tertiary merges *down* into minor, not up into secondary (CARTO merges
# it up).  The OMT data floor for tertiary is z12, identical to minor —
# merging up would promise tertiary at B4 where the tile has none.
OMT_ROAD_CLASS = {
    "motorway": "motorway", "trunk": "trunk", "primary": "primary",
    "secondary": "secondary",
    "tertiary": "minor",
    "minor": "minor", "unclassified": "minor",
    "residential": "minor", "living_street": "minor", "road": "minor",
    "service": "service", "busway": "service", "bus_guideway": "service",
    "path": "path", "track": "path", "footway": "path",
    "pedestrian": "path", "cycleway": "path", "steps": "path",
    "bridleway": "path", "corridor": "path",
    "rail": "rail",
    "transit": "transit",
    "ferry": "ferry",
}


def road_style(props):
    """`transportation` feature -> LINE_STYLES key, or None if dropped.

    Everything not in OMT_ROAD_CLASS — pier, raceway, aerialway and
    friends — is dropped entirely.
    """
    key = OMT_ROAD_CLASS.get(props.get("class"))
    if key is None:
        return None
    if key in ("motorway", "trunk") and props.get("ramp") in (1, True):
        return "ramp"
    return key


def boundary_style(props):
    """`boundary` feature -> LINE_STYLES key, or None if dropped.

    Street mode's admin source; terrain mode keeps the Natural Earth
    borders.  Maritime boundaries are noise over water, admin_level > 4
    is noise everywhere, and `disputed` gets no special treatment — the
    dash already says "admin line".
    """
    if props.get("maritime") in (1, True):
        return None
    try:
        level = int(props.get("admin_level"))
    except (TypeError, ValueError):
        return None
    if level <= 2:
        return "border_country"
    if level in (3, 4):
        return "border_state"
    return None


# The two keys waterway_style can return.  A waterway is the one line
# class that is also an *area* class: any water wide enough to matter
# carries a polygon in the `water` layer as well as a centreline in
# `waterway`, and OpenStreetMap keeps the centreline all the way down a
# tidal estuary.  Where both exist the polygon is the truer picture and
# the centreline is a seam drawn up the middle of the sea.
WATERWAY_KEYS = ("waterway_major", "waterway_minor")

# How far the water has to run, in dots, on each side of a centreline
# dot before the polygon is judged able to speak for itself.  Three is
# a channel seven dots across — about three cells wide, the point at
# which the fill and its coastline read as a shape rather than as a
# line.  Narrower than that and the polygon is a hairline the centreline
# is still carrying, so the centreline stays: a stream is a linestring
# or it is nothing.
WATERWAY_HIDE_DOTS = 3


def waterway_style(props):
    """`waterway` feature -> LINE_STYLES key, or None if dropped."""
    cls = props.get("class")
    if cls == "river":
        return "waterway_major"
    if cls in ("stream", "canal", "ditch", "drain"):
        return "waterway_minor"
    return None


# Terrain mode's waterway gates, replacing the LINE_STYLES weights.  A
# river appears two bands earlier there than in street mode, because
# the reason street holds it back — a dense road net it would compete
# with for ink — does not exist over a hillshade, and a continental
# terrain view that can carry the Rhine should.  Streams keep street's
# deep gate: at any wider zoom they are drainage noise.  B0 draws
# nothing; at half a hemisphere a river is a scratch.
TERRAIN_WATERWAY_WEIGHTS = {
    "waterway_major": (0, 1, 1, 1, 1, 1, 1, 1),
    "waterway_minor": (0, 0, 0, 0, 0, 0, 1, 1),
}


def aeroway_style(props):
    """`aeroway` feature -> LINE_STYLES key, or None if dropped.

    Aeroways get no fill anywhere — runways and taxiways are strokes.
    """
    cls = props.get("class")
    if cls == "runway":
        return "aeroway_runway"
    if cls == "taxiway":
        return "aeroway_taxi"
    return None


# ---------------------------------------------------------------------------
# Fills
# ---------------------------------------------------------------------------
# Every area class is a solid half-block sub-pixel fill; braille is
# reserved for line work, the coast and glyphs.  There is no stipple
# anywhere — a braille cell holds one foreground colour, so a stipple
# fill and a road stroke in the same cell would have to fight for the
# ink, and the failure would be total rather than cosmetic.
FILL_ORDER = ("ground", "urban", "park", "water", "building")

# Debut band per fill key.  `park` is a union of three sources with two
# different floors, so it carries a pair.
FILL_DEBUT = {"water": 0, "park": 3, "park_extra": 5, "urban": 5,
              "building": 7}

URBAN_LANDUSE = ("residential", "commercial", "industrial", "retail")

# landcover is otherwise never rendered: no grass, no wood, no
# farmland, no wetland, no sand.  Green-washing a rural view buys the
# reader nothing.  This is the single largest declutter decision here.
PARK_LANDCOVER_SUBCLASS = ("park",)
PARK_LANDUSE_CLASS = ("cemetery",)


# ---------------------------------------------------------------------------
# Labels
# ---------------------------------------------------------------------------
# Four emphasis states, two cases.  No italics (unreliable), no
# underline, no reverse video (reserved for UI panels), no ink outside
# this table.  case is "title", "spaced" or "upper".
LABEL_STYLES = {
    "city":         ("lbl_city", "title", True),
    "town":         ("lbl_town", "title", False),
    "village":      ("lbl_village", "title", False),
    "hamlet":       ("lbl_village", "title", False),
    "suburb":       ("lbl_area", "spaced", False),
    "neighbourhood": ("lbl_area", "spaced", False),
    "state":        ("lbl_area", "spaced", True),
    "country":      ("lbl_area", "spaced", True),
    "park":         ("lbl_area", "spaced", False),
    # The one area name that is not spaced.  Spacing doubles a name, and
    # an island label has to fit *on the island*: over Casco Bay,
    # "GREAT DIAMOND ISLAND" wants 39 cells across an island 24 cells
    # wide, so spacing it is the same as deleting it.  Title case in the
    # area ink, and no settlement dot, is what separates it from the
    # village of the same name sitting on it.
    "island":       ("lbl_area", "title", False),
    "water":        ("lbl_water", "spaced", False),
    "road":         ("lbl_road", "title", False),
    "road_minor":   ("lbl_road_minor", "title", False),
    "shield":       ("lbl_shield", "upper", True),
    "poi":          ("poi_lbl", "title", False),
}

# An unlisted place class is dropped, never guessed at — rendering
# classes nobody chose is how noise gets in.
#
# An island slots in above the hamlet, and that is the one judgement
# call in the table.  Over Casco Bay the tile offers "Great Diamond
# Island Landing" (a ferry wharf tagged place=hamlet) and "Great Diamond
# Island"; a reader working out where they are wants the island.  A
# landform orients you, fifty houses do not — but a village still beats
# both, because a village is where the people are.
CLASS_RANK = {"country": -2, "state": -1, "city": 0, "town": 1,
              "village": 2, "island": 3, "suburb": 3, "neighbourhood": 3,
              "hamlet": 4}
WATER_RANK = {"ocean": 0, "sea": 1, "bay": 2, "lake": 3}    # .get(cls, 4)

# OpenMapTiles' water_name generalisation is *inverted* for small
# features, measured on the Maine coast: every gut, narrows and
# thorofare is in the tile from z8, while Casco Bay and Sebago Lake do
# not appear until z10.  Trusting the tile's own zoom filtering
# therefore labels a three-county view "Jaquish Gut".  Water names are
# gated by class instead: a strait is a navigation feature and waits
# until you are close enough to navigate it.
WATER_BANDS = {"ocean": 0, "sea": 0, "bay": 1, "lake": 3}
WATER_BAND_DEFAULT = 6

# Band windows for the area classes: deeper than this they are noise
# and are not candidates at all.
#
# Islands get no window, and that is measured rather than lazy: unlike
# water_name, the place layer's island generalisation runs the right way
# round.  Sampled over the Aegean, the Stockholm archipelago, Casco Bay
# and open ocean, nothing at all arrives above band 1, band 2 brings the
# named big ones (Vinalhaven, Νάξος) and the small stuff waits for band
# 3.  A hand-written gate here would only be a worse copy of that.
CLASS_BANDS = {"country": (0, 2), "state": (1, 3),
               "suburb": (5, 7), "neighbourhood": (5, 7)}

# Below this band the bundled Natural Earth cities lead — they carry
# localised names in 17 languages — and the tile's own places fill in
# underneath them.  Natural Earth is a *world* list: over a
# three-county view of Maine it holds exactly one city, so it cannot be
# the only source at any band anyone actually looks at.
PLACE_SOURCE_BAND = 3

SHIELD_MAX_REF = 6           # ref_length above this is not a shield
SHIELD_CLASSES = ("motorway", "trunk")
SHIELD_REPEAT_CELLS = 30     # min cells between repeats of one shield
ROAD_REPEAT_CELLS = 40       # ditto for street names
POI_TEXT_MAX = 14            # characters before the ellipsis


def spaced(name):
    """SPACED CAPS — the only 'larger size' the terminal has.

    No length cap and no unspaced-UPPER fallback: a long area name
    stays spaced and is simply dropped by the occupancy test if it does
    not fit.  Drop-not-shrink is the house rule, and an unspaced
    fallback would collide with the shield register.
    """
    if any(unicodedata.east_asian_width(c) in ("W", "F") for c in name):
        return name                      # CJK: never upper, never space
    return " ".join(name.upper())


def label_budget(gw, hc):
    return max(5, min(24, gw * hc // 110))      # 80x22 -> 16


def place_budget(total):
    return max(2, total * 6 // 10)              #         ->  9


def street_budget(total):
    return max(2, total * 4 // 10)              #         ->  6


def shield_budget(total):
    return 4


def water_park_budget(total):
    return min(3, total)                        # shared: water + park


def poi_glyph_budget(gw, hc):
    return max(4, min(16, gw * hc // 140))      # 80x22 -> 12


def poi_text_budget(total):
    return max(0, total * 2 // 10)              #         ->  3


def max_instances(total_visible_cells):
    """How many times one road name may repeat across the view."""
    return 1 + total_visible_cells // 40


# ---------------------------------------------------------------------------
# POI
# ---------------------------------------------------------------------------
# Ten marks, all audited against the real _framebuffer.visible_len: each
# returns 1.  No emoji-presentation characters ever — visible_len counts
# them as 2 and they break column alignment.
GLYPH_AIRPORT = "✈"     # aerodrome_label layer
GLYPH_PEAK = "▲"        # mountain_peak layer
GLYPH_STATION = "◉"     # rail or metro station — sole meaning
GLYPH_MEDICAL = "✚"
GLYPH_CIVIC = "⚑"
GLYPH_LODGING = "⌂"
GLYPH_NOTABLE = "✦"
GLYPH_WORSHIP = "†"
GLYPH_FERRY = "◆"
GLYPH_GENERIC = "•"     # also the sole place anchor

GLYPH_INK = {
    GLYPH_AIRPORT: "poi_ink",
    GLYPH_PEAK: "poi_ink",
    GLYPH_STATION: "poi_ink",
    GLYPH_MEDICAL: "poi_med",
    GLYPH_CIVIC: "poi_ink",
    GLYPH_LODGING: "poi_ink",
    GLYPH_NOTABLE: "poi_ink",
    GLYPH_WORSHIP: "poi_ink",
    GLYPH_FERRY: "lbl_water",
    GLYPH_GENERIC: "poi_ink",
}

POI_CLASS_GLYPH = {
    "railway": GLYPH_STATION,
    "hospital": GLYPH_MEDICAL, "clinic": GLYPH_MEDICAL,
    "pharmacy": GLYPH_MEDICAL, "doctors": GLYPH_MEDICAL,
    "town_hall": GLYPH_CIVIC, "police": GLYPH_CIVIC,
    "fire_station": GLYPH_CIVIC, "courthouse": GLYPH_CIVIC,
    "embassy": GLYPH_CIVIC, "post": GLYPH_CIVIC, "school": GLYPH_CIVIC,
    "college": GLYPH_CIVIC, "university": GLYPH_CIVIC,
    "library": GLYPH_CIVIC,
    "lodging": GLYPH_LODGING, "campsite": GLYPH_LODGING,
    "attraction": GLYPH_NOTABLE, "museum": GLYPH_NOTABLE,
    "art_gallery": GLYPH_NOTABLE, "monument": GLYPH_NOTABLE,
    "castle": GLYPH_NOTABLE, "theatre": GLYPH_NOTABLE,
    "viewpoint": GLYPH_NOTABLE, "information": GLYPH_NOTABLE,
    "place_of_worship": GLYPH_WORSHIP,
    "ferry_terminal": GLYPH_FERRY, "marina": GLYPH_FERRY,
    "harbor": GLYPH_FERRY,
}

POI_TIER1 = {  # landmarks: B6+, glyph regardless of name
    "railway", "hospital", "college", "university", "stadium", "harbor",
    "attraction", "castle", "monument", "town_hall", "police",
    "fire_station", "library", "theatre", "art_gallery", "museum",
}
POI_TIER2 = {  # wayfinding: B7, glyph regardless of name
    "place_of_worship", "school", "lodging", "post", "information",
    "fuel", "pharmacy", "bus", "cemetery", "campsite", "swimming",
    "golf",
}
POI_TIER3 = {  # commerce: B7, glyph only if named and budget remains
    "restaurant", "cafe", "bar", "fast_food", "beer", "grocery",
    "supermarket", "shop", "clothing_store", "bank", "bicycle", "car",
    "music", "ice_cream", "alcohol_shop", "laundry",
}
POI_NOISE = {  # never rendered, at any zoom, in any mode
    "parking", "waste_basket", "bench", "toilets", "drinking_water",
    "gate", "lift_gate", "entrance", "bicycle_parking", "dog_park",
    "pitch", "playground", "picnic_site", "telephone", "recycling",
    "fountain", "marker", "survey_point", "atm", "tree", "street_lamp",
}

POI_TIER_BAND = {1: 6, 2: 7, 3: 7}      # debut band per tier
POI_PEAK_BAND = 3                       # mountain_peak, its own layer
POI_PEAK_LABEL_BAND = 5                 # "Name 1,204 m"
POI_AIRPORT_BAND = 4                    # aerodrome_label, its own layer
POI_TEXT_BAND = 7                       # tier-1 names, and only those


def poi_tier(cls):
    """1, 2, 3 — or None for anything not admitted at any zoom.

    `parking` alone is 244 of the 933 features in the Portland z14
    tile, so POI_NOISE earns its keep before the tier lookup.
    """
    if cls in POI_NOISE:
        return None
    if cls in POI_TIER1:
        return 1
    if cls in POI_TIER2:
        return 2
    if cls in POI_TIER3:
        return 3
    return None


def poi_glyph(cls):
    """(glyph, ink key) for an admitted POI class.

    Admitted classes with no specific mark take the generic dot; an
    unnamed hospital still deserves its cross, so the glyph does not
    depend on the name.
    """
    glyph = POI_CLASS_GLYPH.get(cls, GLYPH_GENERIC)
    return glyph, GLYPH_INK[glyph]


# ---------------------------------------------------------------------------
# Cartographic furniture
# ---------------------------------------------------------------------------
ATTRIB_TILES_LONG = (
    "OpenFreeMap © OpenMapTiles © OpenStreetMap contributors")
ATTRIB_TILES_SHORT = "© OpenMapTiles © OpenStreetMap"

# Labels are stored, not computed: the obvious f"{d/1609.344:g} mi"
# scheme produces "2.00001 mi" for three of the mile entries.
NICE_M = (
    (10, "10 m"), (20, "20 m"), (50, "50 m"), (100, "100 m"),
    (200, "200 m"), (500, "500 m"), (1000, "1 km"), (2000, "2 km"),
    (5000, "5 km"), (10000, "10 km"), (20000, "20 km"),
    (50000, "50 km"), (100000, "100 km"), (200000, "200 km"),
    (500000, "500 km"), (1000000, "1000 km"), (2000000, "2000 km"),
)
NICE_IMP = (
    (15.24, "50 ft"), (30.48, "100 ft"), (60.96, "200 ft"),
    (152.4, "500 ft"), (304.8, "1000 ft"), (609.6, "2000 ft"),
    (1609.344, "1 mi"), (3218.688, "2 mi"), (8046.72, "5 mi"),
    (16093.44, "10 mi"), (32186.88, "20 mi"), (80467.2, "50 mi"),
    (160934.4, "100 mi"), (321868.8, "200 mi"), (804672.0, "500 mi"),
    (1609344.0, "1000 mi"),
)


def use_metric(lang):
    """The house units heuristic, in one place."""
    return lang != "en" or os.environ.get(
        "WEATHER_UNITS", "").lower() == "metric"


def fmt_elev(meters, lang):
    """An elevation, in the reader's units.  Unit symbols are not
    translated — matching the rest of the house."""
    if use_metric(lang):
        return f"{round(meters):,} m"
    return f"{round(meters * 3.28084):,} ft"


def scale_bar(bbox, gw, metric):
    """(cells, label) for the largest nice distance that fits, or None.

    None means omit the bar entirely rather than draw a stub.
    """
    minlon, minlat, maxlon, maxlat = bbox
    lat_c = (minlat + maxlat) / 2.0
    m_per_cell = ((maxlon - minlon) * 111320.0
                  * math.cos(math.radians(lat_c)) / gw)
    max_cells = max(4, min(20, gw // 4))
    best = None
    for d, label in (NICE_M if metric else NICE_IMP):
        n = int(round(d / m_per_cell))
        if 4 <= n <= max_cells:
            best = (n, label)            # keep the LARGEST that fits
    return best
