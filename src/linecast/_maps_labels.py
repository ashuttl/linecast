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

Two measurements shaped what is here, both worth knowing before anyone
"fixes" it back:

*Roads.* A cell is two dots wide and four tall, so a road a few degrees
off horizontal changes row every seven columns or so; over downtown
Portland the longest stretch of road holding a single row is 7 cells
where the names want 15.  Requiring a label to sit along a flat run
therefore labelled almost nothing.  Writing the name across the road
instead — horizontally, centred on a cell the road passes through —
labels 29 of 33 named roads in the same view, and reads the way a
paper map does.  Following the line character by character was tried
and rejected: on a cell grid it renders as falling confetti.

*Water.* OpenMapTiles' `water_name` generalisation is inverted for
small features.  Every gut, narrows and thorofare on the Maine coast is
in the tile from z8, while Casco Bay and Sebago Lake do not appear
until z10 — so a three-county view labelled itself "Jaquish Gut" and
"The Gut" while the Gulf of Maine, whose own anchor point sits seventy
cells off the right edge, went unnamed.  Hence the class gates, the
Natural Earth switch below band 3 (that list is area-ranked and
generalised for exactly this scale), and labelling the water you can
see rather than the point the data hands you.
"""

from linecast import _maps_style as style
from linecast._framebuffer import visible_len
from linecast._radar_basemap import (
    _bresenham, _cell_width, _load_data, _localized, marine_region,
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


def water_regions(water):
    """Connected components of the on-screen water: (area, anchor) each.

    A water body's own label point is often nowhere near the part of it
    you can see — the Gulf of Maine's anchor sits seventy cells off the
    right edge of a view it fills a third of.  So the label goes on the
    water instead: each component gets the one of its own cells closest
    to its centre of mass, which is inside the shape even when the
    shape is a crescent.

    Returns (index grid, [(area, (col, row)), ...]) with the index grid
    holding -1 where there is no water.
    """
    hc = len(water)
    gw = len(water[0]) if hc else 0
    index = [[-1] * gw for _ in range(hc)]
    regions = []
    for row in range(hc):
        for col in range(gw):
            if not water[row][col] or index[row][col] >= 0:
                continue
            idx = len(regions)
            cells, stack = [], [(col, row)]
            index[row][col] = idx
            while stack:
                c, r = stack.pop()
                cells.append((c, r))
                for nc, nr in ((c - 1, r), (c + 1, r), (c, r - 1),
                               (c, r + 1)):
                    if (0 <= nc < gw and 0 <= nr < hc
                            and water[nr][nc] and index[nr][nc] < 0):
                        index[nr][nc] = idx
                        stack.append((nc, nr))
            mid_c = sum(c for c, _r in cells) / len(cells)
            mid_r = sum(r for _c, r in cells) / len(cells)
            anchor = min(cells, key=lambda p: ((p[0] - mid_c) ** 2
                                               + (p[1] - mid_r) ** 2 * 4))
            span = max(c for c, _r in cells) - min(c for c, _r in cells) + 1
            regions.append((len(cells), anchor, span))
    return index, regions


# How far outside the view a water label point may sit and still be
# dragged in, as a fraction of the view.  A quarter, measured over
# Portland and Casco Bay: it keeps a bay whose anchor sits just past the
# edge of the water filling the screen, and drops Lamson Cove, which is
# seventy-two cells east of a hundred-and-sixteen-cell view and was
# being written across Back Cove.
_DRAG_MARGIN = 4

# And how far a point may then reach *across* the view to find water.
# Two cells: enough that a name point landing a cell off its own lake
# still finds it (Graham Lake's is one cell out), and short enough that
# the reach can never become a search.  Unbounded it scanned the whole
# row, which is how the Portland sewage plant's "Aeration Tanks" — five
# cells inland — ended up naming the cove.
_DRAG_REACH = 2


def _attach(cell, index, regions, graph_w, height_cells, drag=True):
    """(region area, where to put the label, span, region) for a water
    label point.

    A point inside the view names the water under it; a point just
    outside is dragged to the edge it left through, which is how a bay
    whose anchor is out at sea still names the bay you are looking at.
    Returns None when the point does not reach water at all.

    `drag` is that second half, and the caller turns it off for the
    small classes.  A tile hands over one point per body, at its middle,
    so what an off-screen point means depends entirely on how big the
    body can be: an ocean's middle is routinely off the edge of any view
    of its shore, while a *lake* whose middle is off screen is simply a
    lake that is off screen.  Bar Harbor was naming a pond at its west
    edge "Seal Cove Pond", which is twenty-one cells further west on the
    other side of Mount Desert Island.

    The two bounds above are what keep that from becoming "the nearest
    water anywhere".  Unbounded on either axis, the clamp pulls any
    anchor on the planet onto whatever water shares its row — a
    Portland harbour view labelled itself "Sebago Lake", twenty-five
    kilometres inland, and a Back Cove view labelled itself "Lamson
    Cove", which is out past Munjoy Hill in Casco Bay.  Connectivity
    makes that worse rather than better: Back Cove runs into the bay
    under Tukey's Bridge, so the two are one region and a name landing
    anywhere on it is dragged to the whole blob's centre of mass.
    """
    if cell is None:
        return None
    if not drag and not _in_view(cell, graph_w, height_cells):
        return None
    if not (-graph_w // _DRAG_MARGIN <= cell[0]
            < graph_w + graph_w // _DRAG_MARGIN
            and -height_cells // _DRAG_MARGIN <= cell[1]
            < height_cells + height_cells // _DRAG_MARGIN):
        return None
    col = max(0, min(graph_w - 1, cell[0]))
    row = max(0, min(height_cells - 1, cell[1]))
    idx = index[row][col]
    if idx < 0:                       # water within reach along the row
        for d in range(1, _DRAG_REACH + 1):
            for c in (col - d, col + d):
                if 0 <= c < graph_w and index[row][c] >= 0:
                    idx = index[row][c]
                    break
            if idx >= 0:
                break
        if idx < 0:
            return None
    area, anchor, span = regions[idx]
    inside = (cell == (col, row)) and index[row][col] == idx
    return area, (cell if inside else anchor), span, idx


def _land_run(water, cell):
    """Cells of unbroken land across `cell`'s row, through `cell`.

    An island's label point is the only geometry the tile gives it — the
    place layer carries islands as bare points, never polygons — so the
    shape has to be read back off the water mask.  This is the park
    rule's `span` by another route, and it is what stops "Great
    Chebeague Island" being written across four miles of open water at a
    band where the island itself is three cells across.

    A point that lands on water scores 0 and the name is dropped: an
    island too small to hold a whole cell of land is too small to hold
    its own name.

    This is the one label measurement taken off the screen rather than
    off the feature, so it is the one that can change under a pan: an
    island half out of the frame measures short.  It is not a hole in
    the determinism rule so much as the same answer twice — a name
    centred on a half-visible island runs off the edge, and occupancy
    would have dropped it anyway.
    """
    col, row = cell
    if not (0 <= row < len(water) and 0 <= col < len(water[row])):
        return 0
    if water[row][col]:
        return 0
    lo = hi = col
    while lo > 0 and not water[row][lo - 1]:
        lo -= 1
    while hi < len(water[row]) - 1 and not water[row][hi + 1]:
        hi += 1
    return hi - lo + 1


def _centroid(parts):
    """Mean of a feature's dot-space vertices, as a cell coordinate."""
    xs = [p[0] for part in parts for p in part]
    ys = [p[1] for part in parts for p in part]
    if not xs:
        return None
    return (int(sum(xs) / len(xs)) // 2, int(sum(ys) / len(ys)) // 4)


def _screen_box(parts):
    """(area, width) of a feature's bounding box, in cells.

    Both are stable under a pure pan, which is what lets a park name
    keep its place in the sort as the view slides.
    """
    xs = [p[0] for part in parts for p in part]
    ys = [p[1] for part in parts for p in part]
    if not xs:
        return 0.0, 0
    width = (max(xs) - min(xs)) / 2.0
    height = (max(ys) - min(ys)) / 4.0
    return width * height, int(width)


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
def _features(view, bbox, graph_w, height_cells, layer_name, dedupe=True):
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
            if dedupe and key[1] is not None and key in seen:
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

    The bundled Natural Earth cities lead below band 3: 5227 of them,
    population-sorted, with localised names in seventeen languages that
    the tiles do not match.  But that is a *world* list — over a
    three-county view of Maine it contains exactly one city — so the
    tile's own `place` layer fills in underneath it, ranked by the rank
    the tile carries for the purpose.  Names seen twice keep the first,
    which is the Natural Earth one and therefore the localised one.
    """
    out = []
    low = band < style.PLACE_SOURCE_BAND
    for props, parts in _features(view, bbox, graph_w, height_cells,
                                  "place"):
        cls = props.get("class")
        rank = style.CLASS_RANK.get(cls)
        if rank is None:                  # an unlisted class is dropped
            continue
        lo, hi = style.CLASS_BANDS.get(cls, (0, 99))
        if not lo <= band <= hi:
            continue
        name = _name(props, lang)
        cell = _centroid(parts)
        if name and _in_view(cell, graph_w, height_cells):
            # Below the switch the tile's settlements sort after the
            # vendored ones, which take ranks 1..n among themselves.
            tile_rank = _rank(props) + (1000 if low else 0)
            out.append(((rank, tile_rank, name), cls, name, cell))

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
    seen, unique = set(), []
    for cand in out:
        if cand[2] in seen:
            continue
        seen.add(cand[2])
        unique.append(cand)
    return unique


def water_park_candidates(view, bbox, graph_w, height_cells, band, lang,
                          water_mask=None, waters=None):
    """Water bodies and park names — they share one ceiling of three.

    Below band 3 the names come from the bundled Natural Earth marine
    list, exactly as settlements do: it is area-ranked and generalised
    for this scale, so a three-county view is told it is looking at the
    Gulf of Maine rather than at three of its guts.  From band 3 up the
    tile layer takes over, class-gated.

    A `waters` dict, if given, collects {cell: name} for every cell of
    every *named* body on screen, whether or not its name won a place on
    the page.  Naming water is this function's whole job, and the answer
    is worth more than one label: it is what lets a pointer anywhere on
    a lake say which lake, and the label budget has no business
    deciding that.  Bodies are the connected components of the water
    mask, so a name reaches exactly as far as the water a reader would
    trace with a finger — across a narrows, never across the isthmus.

    A body of water gets exactly one name.  Several always reach for the
    same one — Back Cove is one region with the bay it drains into, and
    the tile offers "Back Cove", "Lamson Cove" from out past Munjoy
    Hill, and the sewage plant's "Chlorine Contact Tanks" — and writing
    all three across the same water is not three facts, it is two
    mistakes.  The contest is settled once, here, so the label and the
    pointer can never disagree about what the water is called.
    """
    water, parks = [], []
    index, regions = (water_regions(water_mask) if water_mask
                      else (None, None))
    best = {}      # region -> (choice key, candidate)

    def claim(region, choice, candidate):
        """Offer a name for a body; the best offer wins the body."""
        if region is None:
            water.append(candidate)
        elif region not in best or choice < best[region][0]:
            best[region] = (choice, candidate)

    if index is not None and band < style.PLACE_SOURCE_BAND:
        minlon, minlat, maxlon, maxlat = bbox
        big = sorted(range(len(regions)), key=lambda i: regions[i],
                     reverse=True)[:4]
        for region in big:
            area, (col, row), span = regions[region]
            lon = minlon + (col + 0.5) / graph_w * (maxlon - minlon)
            lat = maxlat - (row + 0.5) / height_cells * (maxlat - minlat)
            name = marine_region(lat, lon)
            if name:
                claim(region, (0, 0, name),
                      ((-area, name), "water", name, (col, row), span))
    else:
        for props, parts in _features(view, bbox, graph_w, height_cells,
                                      "water_name"):
            name = _name(props, lang)
            if not name:
                continue
            cls = props.get("class")
            if band < style.WATER_BANDS.get(cls, style.WATER_BAND_DEFAULT):
                continue
            cell = _centroid(parts)
            # Only water big enough that its own middle may lie off the
            # screen is allowed to be dragged in from off it.  The rank
            # table already orders the classes by exactly that.
            rank = style.WATER_RANK.get(cls, 4)
            hit = (_attach(cell, index, regions, graph_w, height_cells,
                           rank <= style.WATER_RANK["bay"])
                   if index is not None else None)
            if hit is not None:
                area, at, span, region = hit
                # A name whose point lands on the water it names beats
                # one dragged in from off the edge, whatever their
                # classes: the tile put that point there on purpose.
                # Then the class, so a bay outranks the basin beside it.
                choice = (at != cell, rank, name)
                key = (rank, -area, name)
                claim(region, choice, (key, "water", name, at, span))
            elif index is None and _in_view(cell, graph_w, height_cells):
                # No mask to check against, so the point is all there
                # is.  With a mask, a name that reaches no water is a
                # name for water the reader cannot see, and this module
                # labels the water that is on the screen — the whole
                # reason the mask is consulted at all.  It is also the
                # only span-less path there is: `graph_w` here means
                # "unmeasured", and an unmeasured name is exactly the
                # one that ends up written across a whole cove.
                water.append(((rank, 0, name), "water", name, cell,
                              graph_w))
    named = {}
    for region, (_choice, candidate) in best.items():
        named[region] = candidate[2]
        water.append(candidate)
    if waters is not None and index is not None:
        for row, line in enumerate(index):
            for col, region in enumerate(line):
                name = named.get(region) if region >= 0 else None
                if name:
                    waters[(col, row)] = name
    for props, parts in _features(view, bbox, graph_w, height_cells, "park"):
        name = _name(props, lang)
        cell = _centroid(parts)
        if name and _in_view(cell, graph_w, height_cells):
            area, span = _screen_box(parts)
            parks.append(((-area, 0, name), "park", name, cell, span))
    water.sort(key=lambda c: c[0])
    parks.sort(key=lambda c: c[0])
    return water + parks


def road_candidates(view, bbox, graph_w, height_cells, band, lang):
    """(shields, street names), each sorted into placement order.

    Every segment carrying the same name is merged into one candidate:
    OpenStreetMap splits a street at each junction, so a single feature
    is often ten cells of road, and labelling it means labelling the
    street rather than whichever fragment came first in the tile.

    On a highway the ref is the single most valuable label on screen —
    you navigate by "I-95", not "Maine Turnpike" — so shields outrank
    street names and get their own budget.
    """
    refs, names, numbered = {}, {}, set()
    for props, parts in _features(view, bbox, graph_w, height_cells,
                                  "transportation_name", dedupe=False):
        cells = [c for part in parts
                 for c in cell_path(part, graph_w, height_cells)]
        if not cells:
            continue
        cls = props.get("class")
        key = style.OMT_ROAD_CLASS.get(cls)
        ref = str(props.get("ref") or "").strip()
        name = _name(props, lang)
        if (ref and cls in style.SHIELD_CLASSES
                and len(ref) <= style.SHIELD_MAX_REF):
            shield = refs.setdefault(ref.replace(" ", "-").upper(),
                                     [style.LINE_STYLES[key or cls][3], []])
            shield[0] = max(shield[0], style.LINE_STYLES[key or cls][3])
            shield[1].extend(cells)
            # You navigate a numbered road by its number. Spending a
            # second label on "Lisbon Street" for ME-196 says less and
            # costs the same.
            numbered.add(name)
        key = style.OMT_ROAD_CLASS.get(cls)
        # A road's name has no business on screen at a zoom where the
        # road itself is not drawn: the class's own band gate decides.
        if key is not None and not style.LINE_STYLES[key][1][band]:
            key = None
        if name and key is not None and name not in numbered:
            entry = names.setdefault(name, [style.LINE_STYLES[key][3], []])
            entry[0] = max(entry[0], style.LINE_STYLES[key][3])
            entry[1].extend(cells)

    # The four shields a view can afford should be the four biggest
    # roads, not the four lowest numbers: an interstate outranks a
    # state route whatever they are called.
    shields = sorted(((-rank, text), "shield", text, cells)
                     for text, (rank, cells) in refs.items())
    streets = sorted(((-rank, name), "road" if rank >= 38 else "road_minor",
                      name, cells)
                     for name, (rank, cells) in names.items()
                     if name not in numbered)
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
def _emit(overlays, occ, row, col, text, ink, bold, mark=None):
    """Claim a run of cells and write one character into each.

    A double-width glyph writes an empty sentinel into the column it
    swallows, so the row stays aligned — the same idiom the Natural
    Earth city labels use.

    `mark` is (hover dict, entry): the same entry object is filed under
    every cell the label lands on, so a pointer anywhere along the text
    finds the whole of it.
    """
    occ.claim(row, col, visible_len(text))
    c = col
    for ch in text:
        overlays[(c, row)] = (ch, ink, bold)
        if mark is not None:
            mark[0][(c, row)] = mark[1]
        if _cell_width(ch) == 2:
            overlays[(c + 1, row)] = ("", ink, False)
            if mark is not None:
                mark[0][(c + 1, row)] = mark[1]
            c += 1
        c += 1


def _text_mark(texts, name):
    """The `mark` that files a written name against the cells it took.

    None when no caller asked for the index, and None for a nameless
    label, which has nothing a hovered feature could ever match.
    """
    return (texts, name) if texts is not None and name else None


def _place_point(overlays, occ, cell, text, ink, bold, anchor=None,
                 mark=None):
    """A label at its anchor, or dropped.  Anchored labels take the
    anchor cell plus the text to its right; area labels are centred on
    the feature and carry no mark at all."""
    col, row = cell
    n = visible_len(text)
    if anchor is not None:
        if not occ.free(row, col, n + 1):
            return False
        overlays[(col, row)] = (anchor[0], anchor[1], anchor[2])
        if mark is not None:
            mark[0][(col, row)] = mark[1]
        occ.claim(row, col, 1)
        if n:
            _emit(overlays, occ, row, col + 1, text, ink, bold, mark)
        return True
    col -= n // 2
    if not occ.free(row, col, n):
        return False
    _emit(overlays, occ, row, col, text, ink, bold, mark)
    return True


# Where along a road to try writing its name, as fractions of the path.
# The middle first, because that is where a reader looks for it.
_ANCHORS = (0.50, 0.25, 0.75, 0.12, 0.62, 0.38, 0.88)


def _place_beside(overlays, occ, cells, text, ink, bold, repeat, limit,
                  mark=None):
    """Write a road's name horizontally, centred on the road itself.

    Text has to sit on one row, and a road almost never does: measured
    over downtown Portland, the longest stretch of road holding a
    single row is about seven cells, where the names want fifteen. So
    the label is centred on a cell the road actually passes through and
    written across it — the association is by contact, the way a paper
    map does it, rather than by tracking the line character by
    character (which a cell grid can only render as falling confetti).

    Anchors are tried at fixed fractions of the path, so the choice
    does not depend on where the view happens to sit.  Every instance
    carries the same `mark`, so hovering the road lights all of them —
    a repeated name is one label written twice, not two labels.
    """
    n = visible_len(text)
    placed = []
    for fraction in _ANCHORS:
        if len(placed) >= limit:
            break
        col, row = cells[min(len(cells) - 1, int(len(cells) * fraction))]
        col -= n // 2
        # Distance in view cells, with rows weighted for the cell's 2:1
        # aspect — a repeat one row down is still a repeat.
        if any(abs(col - pc) + 2 * abs(row - pr) < repeat
               for pc, pr in placed):
            continue
        if not occ.free(row, col, n):
            continue
        _emit(overlays, occ, row, col, text, ink, bold, mark)
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
                   lang="en", reserved=(), water_mask=None, marks=None,
                   texts=None, waters=None):
    """{(col, row): (char, ink, bold)} for one view.

    Walked in strict priority order — places, water and park names,
    shields, street names, POI glyphs, POI names — each against its own
    ceiling.  Sub-budgets are ceilings, not reservations: unused place
    slots do not flow to streets.  The page is allowed to be
    under-filled.

    A `marks` dict, if given, collects {cell: (i18n key, name, seq)} for
    the POI glyphs that were actually placed — hover's first lookup, and
    the only one that has to be taken from placement rather than from
    the raster, because a glyph is the one mark that owns cells no
    stroke may claim.  Road and place labels are deliberately absent:
    they are written across the very feature they name, so the ink
    contest underneath already answers for them.

    A `texts` dict collects {cell: name} for exactly those other labels.
    They are not a lookup — hovering the word "Bridge Street" still
    resolves to the road under it — but the reverse direction: hover the
    road and its name should go bold with it, which needs to know where
    the writing landed.  Keyed on the raw name rather than the cased
    text, because that is the name the raster's own index will report.

    A `waters` dict collects {cell: name} for the named bodies of water,
    filled whether or not their names won a place on the page — the
    naming itself happens in water_park_candidates.
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
        text = _cased(name, case)
        # An island name belongs on the island, the same way a park name
        # belongs inside the park — but the tile hands islands over as
        # bare points, so the width has to come off the water mask.
        if (cls == "island" and water_mask is not None
                and _land_run(water_mask, cell) < visible_len(text)):
            continue
        if _place_point(overlays, occ, cell, text, ink, bold,
                        anchor, _text_mark(texts, name)):
            budget -= 1
            placed += 1

    # 3 — water bodies and park names, sharing one ceiling
    budget = style.water_park_budget(total)
    for _key, kind, name, cell, span in water_park_candidates(
            view, bbox, graph_w, height_cells, band, lang, water_mask,
            waters):
        if budget <= 0 or placed >= total:
            break
        ink, case, bold = _style_for(kind, palette)
        text = _cased(name, case)
        # An area label belongs inside the area it names. A forest
        # parcel ten cells across does not get a forty-nine-cell name
        # laid over the county it sits in — that reads as a label for
        # the county.
        if visible_len(text) > span:
            continue
        if _place_point(overlays, occ, cell, text, ink, bold,
                        mark=_text_mark(texts, name)):
            budget -= 1
            placed += 1

    shields, streets = road_candidates(view, bbox, graph_w, height_cells,
                                       band, lang)

    # 4 — route shields: the amber and the bold *are* the shield
    budget = style.shield_budget(total)
    for _key, kind, text, cells in shields:
        if budget <= 0 or placed >= total:
            break
        ink, case, bold = _style_for(kind, palette)
        n = _place_beside(overlays, occ, cells, _cased(text, case), ink,
                          bold, style.SHIELD_REPEAT_CELLS,
                          min(budget, style.max_instances(
                              graph_w * height_cells)),
                          _text_mark(texts, text))
        budget -= n
        placed += n

    # 5 — street names, major to minor
    budget = style.street_budget(total)
    for _key, kind, name, cells in streets:
        if budget <= 0 or placed >= total:
            break
        ink, case, bold = _style_for(kind, palette)
        n = _place_beside(overlays, occ, cells, _cased(name, case), ink,
                          bold, style.ROAD_REPEAT_CELLS,
                          min(budget, style.max_instances(
                              graph_w * height_cells)),
                          _text_mark(texts, name))
        budget -= n
        placed += n

    # 6 and 7 — POI glyphs, and names for the tier-1 few at the bottom
    glyphs = style.poi_glyph_budget(graph_w, height_cells)
    text_budget = style.poi_text_budget(total)
    for seq, (key, glyph, ink_key, name, cell) in enumerate(poi_candidates(
            view, bbox, graph_w, height_cells, band, lang)):
        if glyphs <= 0:
            break
        ink = palette.get(ink_key, style._PALETTE_16_DEFAULT)
        label = name if text_budget > 0 else ""
        lbl_ink = palette.get("poi_lbl", style._PALETTE_16_DEFAULT)
        # The sort key holds the full name; `name` here is the label,
        # which the budget may have blanked and the ellipsis shortened.
        # Hover wants the whole of it — it has a header to spend.
        mark = (marks, (style.GLYPH_LEGEND[glyph], key[2], seq)) \
            if marks is not None else None
        if label and _place_point(overlays, occ, cell, label, lbl_ink, False,
                                  anchor=(glyph, ink, False), mark=mark):
            glyphs -= 1
            text_budget -= 1
        elif _place_point(overlays, occ, cell, "", ink, False,
                          anchor=(glyph, ink, False), mark=mark):
            glyphs -= 1
    return overlays
