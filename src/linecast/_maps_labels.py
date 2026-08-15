"""Street-mode labels — the scarcest resource on the page.

Four inks, two cases, and a budget of about sixteen labels for the whole
view.  Everything here follows from that scarcity: candidates are
ranked, walked in strict priority order, and a label that cannot be
placed cleanly is **dropped** — never nudged, never shrunk, never
abbreviated.  Only road labels and shields may move at all, and only by
sliding along their own line to a different horizontal run.

The other governing rule is determinism under pan.  Sort keys carry no
screen coordinate (park names are the one exception, and screen-bbox
area is stable under translation), features from several tiles are
ordered by tile key before sorting, and the occupancy grid is filled
strictly in priority order.  A label that survives at one pan position
survives at the next unless its cells genuinely collide — no flicker, no
shuffling.

Measured consequence of the horizontal-run rule, worth knowing before
anyone calls it a bug: a cell is two dots wide and four tall, so a road
only a few degrees off horizontal changes row every seven columns or
so.  Over downtown Portland the longest in-view run is 7 cells, which
carries a shield ("295") or a short name but not "Oxford Street".
Shields and place names therefore do most of the labelling work, and
street names appear only on genuinely long horizontal stretches.  That
is the drop-not-shrink rule doing exactly what it says; relaxing it
would mean either abbreviating names or letting a label wander off its
own road.
"""

from linecast import _maps_style as style
from linecast._framebuffer import visible_len
from linecast._radar_basemap import (
    _bresenham, _cell_width, _load_data, _localized,
)
from linecast._vtiles import projector

LABEL_LAYERS = ("place", "water_name", "park", "transportation_name",
                "poi", "mountain_peak", "aerodrome_label")

_DEFAULT_EXTENT = 4096


# ---------------------------------------------------------------------------
# Occupancy
# ---------------------------------------------------------------------------
class Occupancy:
    """Per-cell claim map with one blank cell of horizontal padding.

    The padding *is* the halo: a label already flattens its cells'
    braille, and one free cell either side stops it colliding with the
    next mark.  Vertical padding was considered and rejected — at 22
    rows it would starve the view, and adjacent-row labels at different
    columns read fine.
    """

    def __init__(self, gw, hc):
        self.g = [bytearray(gw) for _ in range(hc)]

    def free(self, row, col, n):
        if row < 0 or row >= len(self.g):
            return False
        width = len(self.g[0])
        lo, hi = col - 1, col + n
        if lo < -1 or col + n > width:
            return False
        return not any(self.g[row][max(0, lo):min(width, hi + 1)])

    def claim(self, row, col, n):
        r = self.g[row]
        for c in range(max(0, col - 1), min(len(r), col + n + 1)):
            r[c] = 1


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------
def cell_path(pts, graph_w, height_cells):
    """Dot-space polyline -> the in-view cell coords it crosses.

    Cells between two vertices are walked rather than skipped, because a
    run of cells that is not contiguous cannot carry text.  Vertices are
    first clamped to a one-cell margin around the view: a road with a
    vertex several tiles away would otherwise cost a hundred thousand
    steps to reach a screen that is eighty cells wide.  Cells outside
    the view are then dropped, and the gap breaks the run — a label can
    only sit where the road is actually visible.
    """
    cells = []
    prev = last = None
    for x, y in pts:
        c = (min(graph_w, max(-1, int(x) // 2)),
             min(height_cells, max(-1, int(y) // 4)))
        steps = [c] if prev is None else _bresenham(prev[0], prev[1],
                                                    c[0], c[1])
        for step in steps:
            if step == last:
                continue
            last = step
            if 0 <= step[0] < graph_w and 0 <= step[1] < height_cells:
                cells.append(step)
        prev = c
    return cells


def horizontal_runs(cells):
    """Maximal runs that stay on one row stepping exactly one column.

    Returns [(row, col_lo, col_hi)]; run length = col_hi - col_lo + 1.
    Direction is discarded — text is always drawn left to right inside
    the run.  Vertical and steeply diagonal roads simply produce no
    runs, and so go unlabelled; a rotated glyph is not available and a
    letter-per-row column of text is unreadable.
    """
    runs, i, n = [], 0, len(cells)
    while i < n:
        row, j, step = cells[i][1], i + 1, 0
        while j < n and cells[j][1] == row:
            d = cells[j][0] - cells[j - 1][0]
            if d not in (-1, 1) or (step and d != step):
                break
            step = d
            j += 1
        if j - i >= 2:
            a, b = cells[i][0], cells[j - 1][0]
            runs.append((row, min(a, b), max(a, b)))
        i = max(j, i + 1)
    return runs


def _centroid(parts):
    """Mean of a feature's dot-space vertices, as a cell coordinate."""
    xs = [p[0] for part in parts for p in part]
    ys = [p[1] for part in parts for p in part]
    if not xs:
        return None
    return (int(sum(xs) / len(xs)) // 2, int(sum(ys) / len(ys)) // 4)


def _screen_area(parts):
    """Bounding-box area in cells — stable under a pure pan."""
    xs = [p[0] for part in parts for p in part]
    ys = [p[1] for part in parts for p in part]
    if not xs:
        return 0.0
    return (max(xs) - min(xs)) * (max(ys) - min(ys)) / 8.0


def _name(props, lang):
    """The localised name, or "" — placenames are never machine
    translated, so this only ever picks a name the data already has."""
    for key in (f"name:{lang}", "name:latin", "name"):
        value = props.get(key)
        if value:
            return str(value)
    return ""


def _rank(props, default=99):
    try:
        return int(props.get("rank"))
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# Candidate collection
# ---------------------------------------------------------------------------
def _features(view, bbox, graph_w, height_cells, layer_name):
    """(props, projected parts) per feature, in tile-then-file order.

    Duplicates across a tile seam keep the first occurrence, which is
    what makes placement independent of which tile happened to arrive
    first.
    """
    dw, dh = graph_w * 2, height_cells * 4
    seen = set()
    out = []
    for (z, tx, ty), decoded in view:
        src = decoded.get(layer_name)
        if src is None:
            continue
        project = projector(z, tx, ty, src.get("extent") or _DEFAULT_EXTENT,
                            bbox, dw, dh)
        for feat in src["features"]:
            props = feat["tags"]
            key = (layer_name, props.get("name"), props.get("ref"),
                   props.get("class"))
            if key[1] is not None and key in seen:
                continue
            seen.add(key)
            out.append((props, [[project(x, y) for x, y in part]
                                for part in feat["geometry"]]))
    return out


def _in_view(cell, graph_w, height_cells):
    return (cell is not None and 0 <= cell[0] < graph_w
            and 0 <= cell[1] < height_cells)


def place_candidates(view, bbox, graph_w, height_cells, band, lang):
    """Settlements and admin names, already sorted into priority order.

    Below band 3 the settlements come from the bundled Natural Earth
    cities — 5227 of them, population-sorted, with localised names in
    seventeen languages, which the tiles do not match — and the tile
    `place` layer contributes country and state names only.  From band 3
    up the tile layer is the sole source.  The class sets are disjoint
    below the switch, so no de-duplication heuristic ever runs.
    """
    out = []
    low = band < style.PLACE_SOURCE_BAND
    for props, parts in _features(view, bbox, graph_w, height_cells,
                                  "place"):
        cls = props.get("class")
        if low and cls not in style.PLACE_TILE_CLASSES_LOW:
            continue
        rank = style.CLASS_RANK.get(cls)
        if rank is None:                  # an unlisted class is dropped
            continue
        lo, hi = style.CLASS_BANDS.get(cls, (0, 99))
        if not lo <= band <= hi:
            continue
        name = _name(props, lang)
        cell = _centroid(parts)
        if name and _in_view(cell, graph_w, height_cells):
            out.append(((rank, _rank(props), name), cls, name, cell))

    if low:
        minlon, minlat, maxlon, maxlat = bbox
        inview = [e for e in _load_data()["cities"]
                  if minlon <= e[0] <= maxlon and minlat <= e[1] <= maxlat]
        inview.sort(key=lambda e: e[2], reverse=True)
        for i, entry in enumerate(inview):
            cell = (int((entry[0] - minlon) / (maxlon - minlon) * graph_w),
                    int((maxlat - entry[1]) / (maxlat - minlat)
                        * height_cells))
            name = _localized(entry, lang)
            if name and _in_view(cell, graph_w, height_cells):
                out.append(((style.CLASS_RANK["city"], i + 1, name),
                            "city", name, cell))
    out.sort(key=lambda c: c[0])
    return out


def water_park_candidates(view, bbox, graph_w, height_cells, lang):
    """Water bodies and park names — they share one ceiling of three."""
    water, parks = [], []
    for props, parts in _features(view, bbox, graph_w, height_cells,
                                  "water_name"):
        name = _name(props, lang)
        cell = _centroid(parts)
        if name and _in_view(cell, graph_w, height_cells):
            key = (style.WATER_RANK.get(props.get("class"), 3), name)
            water.append((key, "water", name, cell))
    for props, parts in _features(view, bbox, graph_w, height_cells, "park"):
        name = _name(props, lang)
        cell = _centroid(parts)
        if name and _in_view(cell, graph_w, height_cells):
            parks.append(((-_screen_area(parts), name), "park", name, cell))
    water.sort(key=lambda c: c[0])
    parks.sort(key=lambda c: c[0])
    return water + parks


def road_candidates(view, bbox, graph_w, height_cells, lang):
    """(shields, street names), each sorted into placement order.

    On a highway the ref is the single most valuable label on screen —
    you navigate by "I-95", not "Maine Turnpike" — so shields outrank
    street names and get their own budget.
    """
    shields, streets = [], []
    for props, parts in _features(view, bbox, graph_w, height_cells,
                                  "transportation_name"):
        cells = [c for part in parts
                 for c in cell_path(part, graph_w, height_cells)]
        runs = horizontal_runs(cells)
        if not runs:
            continue
        ref = str(props.get("ref") or "").strip()
        if (ref and props.get("class") in style.SHIELD_CLASSES
                and len(ref) <= style.SHIELD_MAX_REF):
            shields.append(((ref, runs[0][1]), "shield",
                            ref.replace(" ", "-").upper(), runs))
        name = _name(props, lang)
        if not name:
            continue
        key = style.OMT_ROAD_CLASS.get(props.get("class"))
        if key is None:
            continue
        rank = style.LINE_STYLES[key][3]
        kind = "road" if key in ("motorway", "trunk", "primary",
                                 "secondary") else "road_minor"
        streets.append(((-rank, name), kind, name, runs))
    shields.sort(key=lambda c: c[0])
    streets.sort(key=lambda c: c[0])
    return shields, streets


def poi_candidates(view, bbox, graph_w, height_cells, band, lang):
    """Glyph POI, already tiered and sorted.

    The hard filters run before tiering and in order: indoor features go
    first, then the noise list (parking alone is a quarter of a dense
    z14 tile), then anything outside the three tiers, then unnamed tier
    threes.  Tiers one and two render their glyph unnamed — an unnamed
    hospital still deserves its cross.
    """
    out = []
    for props, parts in _features(view, bbox, graph_w, height_cells, "poi"):
        if props.get("indoor") in (1, True):
            continue
        cls = props.get("class")
        tier = style.poi_tier(cls)
        if tier is None or band < style.POI_TIER_BAND[tier]:
            continue
        name = _name(props, lang)
        if tier == 3 and not name:
            continue
        cell = _centroid(parts)
        if not _in_view(cell, graph_w, height_cells):
            continue
        glyph, ink_key = style.poi_glyph(cls)
        # A POI earns a name only at the deepest band, only in tier one,
        # and only up to fourteen characters — the one place in the
        # whole label system where text is shortened rather than
        # dropped, because the glyph still carries the meaning.
        label = ""
        if name and tier == 1 and band >= style.POI_TEXT_BAND:
            label = name if len(name) <= style.POI_TEXT_MAX \
                else name[:style.POI_TEXT_MAX] + "…"
        out.append(((tier, _rank(props), name), glyph, ink_key, label,
                    cell))

    for layer_name, glyph, debut in (
            ("mountain_peak", style.GLYPH_PEAK, style.POI_PEAK_BAND),
            ("aerodrome_label", style.GLYPH_AIRPORT,
             style.POI_AIRPORT_BAND)):
        if band < debut:
            continue
        for props, parts in _features(view, bbox, graph_w, height_cells,
                                      layer_name):
            cell = _centroid(parts)
            if not _in_view(cell, graph_w, height_cells):
                continue
            # The peak is the one mark that earns its text early: an
            # unlabelled summit is a triangle, a labelled one is a
            # landmark.  An aerodrome is a glyph and never a name.
            name = _name(props, lang)
            if layer_name == "mountain_peak":
                if name and band >= style.POI_PEAK_LABEL_BAND:
                    try:
                        ele = style.fmt_elev(float(props["ele"]), lang)
                        name = f"{name} {ele}"
                    except (KeyError, TypeError, ValueError):
                        pass
                else:
                    name = ""
            else:
                name = ""
            out.append(((0, _rank(props), name), glyph,
                        style.GLYPH_INK[glyph], name, cell))
    out.sort(key=lambda c: c[0])
    return out


# ---------------------------------------------------------------------------
# Placement
# ---------------------------------------------------------------------------
def _emit(overlays, occ, row, col, text, ink, bold):
    """Claim a run of cells and write one character into each.

    A double-width glyph writes an empty sentinel into the column it
    swallows, so the row stays aligned — the same idiom the Natural
    Earth city labels use.
    """
    occ.claim(row, col, visible_len(text))
    c = col
    for ch in text:
        overlays[(c, row)] = (ch, ink, bold)
        if _cell_width(ch) == 2:
            overlays[(c + 1, row)] = ("", ink, False)
            c += 1
        c += 1


def _place_point(overlays, occ, cell, text, ink, bold, anchor=None):
    """A label at its anchor, or dropped.  Anchored labels take the
    anchor cell plus the text to its right; area labels are centred on
    the feature and carry no mark at all."""
    col, row = cell
    n = visible_len(text)
    if anchor is not None:
        if not occ.free(row, col, n + 1):
            return False
        overlays[(col, row)] = (anchor[0], anchor[1], anchor[2])
        occ.claim(row, col, 1)
        if n:
            _emit(overlays, occ, row, col + 1, text, ink, bold)
        return True
    col -= n // 2
    if not occ.free(row, col, n):
        return False
    _emit(overlays, occ, row, col, text, ink, bold)
    return True


def _place_along(overlays, occ, runs, text, ink, bold, repeat, limit):
    """Slide a label along its own line to a run that fits.

    The only movement any label is permitted, and even here the run is
    chosen deterministically: longest first, then top-down, then
    left-to-right.
    """
    n = visible_len(text)
    placed = []
    for row, lo, hi in sorted(runs, key=lambda r: (-(r[2] - r[1]), r[0],
                                                   r[1])):
        if len(placed) >= limit:
            break
        length = hi - lo + 1
        if length < n + 2:
            continue
        col = lo + (length - n) // 2
        # Distance in view cells, with rows weighted for the cell's 2:1
        # aspect — a repeat one row down is still a repeat.
        if any(abs(col - pc) + 2 * abs(row - pr) < repeat
               for pc, pr in placed):
            continue
        if not occ.free(row, col, n):
            continue
        _emit(overlays, occ, row, col, text, ink, bold)
        placed.append((col, row))
    return len(placed)


def _style_for(kind, palette):
    ink_key, case, bold = style.LABEL_STYLES[kind]
    return palette.get(ink_key, style._PALETTE_16_DEFAULT), case, bold


def _cased(text, case):
    if case == "spaced":
        return style.spaced(text)
    if case == "upper":
        return text.upper()
    return text


def label_overlays(view, bbox, graph_w, height_cells, band, palette,
                   lang="en", reserved=()):
    """{(col, row): (char, ink, bold)} for one view.

    Walked in strict priority order — places, water and park names,
    shields, street names, POI glyphs, POI names — each against its own
    ceiling.  Sub-budgets are ceilings, not reservations: unused place
    slots do not flow to streets.  The page is allowed to be
    under-filled.
    """
    occ = Occupancy(graph_w, height_cells)
    for col, row in reserved:
        if 0 <= row < height_cells and 0 <= col < graph_w:
            occ.claim(row, col, 1)
    overlays = {}

    total = style.label_budget(graph_w, height_cells)
    placed = 0

    # 2 — places, with the one anchor mark the map uses for settlements
    budget = style.place_budget(total)
    for _key, cls, name, cell in place_candidates(
            view, bbox, graph_w, height_cells, band, lang):
        if budget <= 0 or placed >= total:
            break
        kind = cls if cls in style.LABEL_STYLES else "village"
        ink, case, bold = _style_for(kind, palette)
        settlement = cls in ("city", "town", "village", "hamlet")
        anchor = (style.GLYPH_GENERIC, ink, bold) if settlement else None
        if _place_point(overlays, occ, cell, _cased(name, case), ink, bold,
                        anchor):
            budget -= 1
            placed += 1

    # 3 — water bodies and park names, sharing one ceiling
    budget = style.water_park_budget(total)
    for _key, kind, name, cell in water_park_candidates(
            view, bbox, graph_w, height_cells, lang):
        if budget <= 0 or placed >= total:
            break
        ink, case, bold = _style_for(kind, palette)
        if _place_point(overlays, occ, cell, _cased(name, case), ink, bold):
            budget -= 1
            placed += 1

    shields, streets = road_candidates(view, bbox, graph_w, height_cells,
                                       lang)

    # 4 — route shields: the amber and the bold *are* the shield
    budget = style.shield_budget(total)
    for _key, kind, text, runs in shields:
        if budget <= 0 or placed >= total:
            break
        ink, case, bold = _style_for(kind, palette)
        n = _place_along(overlays, occ, runs, _cased(text, case), ink, bold,
                         style.SHIELD_REPEAT_CELLS,
                         min(budget, style.max_instances(
                             graph_w * height_cells)))
        budget -= n
        placed += n

    # 5 — street names, major to minor
    budget = style.street_budget(total)
    for _key, kind, name, runs in streets:
        if budget <= 0 or placed >= total:
            break
        ink, case, bold = _style_for(kind, palette)
        n = _place_along(overlays, occ, runs, _cased(name, case), ink, bold,
                         style.ROAD_REPEAT_CELLS,
                         min(budget, style.max_instances(
                             graph_w * height_cells)))
        budget -= n
        placed += n

    # 6 and 7 — POI glyphs, and names for the tier-1 few at the bottom
    glyphs = style.poi_glyph_budget(graph_w, height_cells)
    text_budget = style.poi_text_budget(total)
    for _key, glyph, ink_key, name, cell in poi_candidates(
            view, bbox, graph_w, height_cells, band, lang):
        if glyphs <= 0:
            break
        ink = palette.get(ink_key, style._PALETTE_16_DEFAULT)
        label = name if text_budget > 0 else ""
        lbl_ink = palette.get("poi_lbl", style._PALETTE_16_DEFAULT)
        if label and _place_point(overlays, occ, cell, label, lbl_ink, False,
                                  anchor=(glyph, ink, False)):
            glyphs -= 1
            text_budget -= 1
        elif _place_point(overlays, occ, cell, "", ink, False,
                          anchor=(glyph, ink, False)):
            glyphs -= 1
    return overlays
