#!/usr/bin/env python3
"""Maps — a street map and a terrain map in the terminal.

`--view street` (the default) is in _maps.streets and friends: vector
tiles rasterised into fills, braille strokes and labels.  Only a handful
of things on it can afford a label, so the pointer is the other half of
reading it: hover names whatever owns the ink under it and lights that
whole feature up (_maps.hover).

`--view terrain` lives here, drawn in a schematic register: colour is
categorical (flat land-cover fields, flat hypsometric bands climbing
green through straw and ochre into mauve, lavender and summit white)
while a multidirectional hillshade underneath carries everything
physical — the grammar of a geologic map rather than a photograph.
The sea is the one smooth gradient, falling to a near-black navy
abyss.  Lakes and rivers are the one thing elevation cannot tell you —
a terrarium sample over a lake is just the height of its surface — so
the inland water comes from the street tiles and joins the shoreline
the elevation already draws.
Geography keeps the radar view's braille identity: the coastline is the
sea-level contour of the elevation data itself (so it always matches
the fill), borders are Natural Earth braille strokes, cities are
labelled dots.  Drag to pan, +/- to zoom, and hover to read the
elevation under the pointer.  The inks, the palette and the composers
are in _maps.paint; the loaders and their caches are in _maps.views;
the live loop and its keys are in _maps_live.

Either flat view is built a margin wider than the window and the frame
is a crop of it (_maps.overscan), so a pan inside that margin is the
real map at the new centre and costs nothing: no fetch, no reprojection,
the same data cut at another offset.  `--print` builds the window's own
bbox and nothing beyond it.

Usage: maps [--location LAT,LNG | PLACE] [--zoom DEG] [--view MODE]
            [--print] [--search CITY]
"""

import functools
import math
import sys

from linecast import _builtup, _climate, _night_lights
from linecast._maps import globe as _globe
from linecast._maps import globe_now
from linecast._maps import hover as _maps_hover
from linecast._maps import overscan as _maps_overscan
from linecast._maps import style
from linecast._maps import ui
from linecast._color import fg, RESET, color_mode, BG_PRIMARY
from linecast._elevation import ATTRIBUTION
from linecast._framebuffer import cell_aspect, get_terminal_size
from linecast._graphics import visible_len
from linecast._live import overlay
from linecast._maps.i18n import ms
from linecast._maps.paint import (  # noqa: F401 — the inks and composers
    BATHY_STOPS, BORDER_STROKE, COAST_STROKE, HYPSO_FAMILIES, LABEL_DARK,
    LABEL_LIGHT, LAKE_FILL, MARKER, build_terrain_buffer,
    compact_colors, compose_map, compose_terrain,
)
from linecast._maps.views import (  # noqa: F401 — the loaders and caches
    SHORE_LAND, SHORE_WATER,
    TerrainView, _EMPTY_TERRAIN, _coast_dots, _elev_cache,
    _get_clouds, _get_elevation, _get_globe, _get_street,
    _globe_cache, _sphere, _street_cache, _terrain_buffer, _terrain_cache,
    _view_key, _water_subpixels, fetch_destination, take_street,
    take_terrain,
)
from linecast._radar.basemap import (  # noqa: F401 — _edge_dots is re-exported
    _BITS, BORDER, DotLayer, _edge_dots,
)
from linecast import _theme
from linecast._radar.i18n import rs
from linecast._radar.render import bbox_for
from linecast._radar.ui import (
    CROSSHAIR, DIM, MUTED, _get_basemap, _panned_place, _shift_grid,
)
from linecast._runtime import log_failure
from linecast._scenes import Memo

# Zoom is degrees of latitude top to bottom.  The floor used to be 0.1
# (about band 3); street mode's deepest classes — buildings, POI text —
# need 0.0012, which is roughly two metres per braille dot.
MIN_ZOOM_DEG = 0.0012
# past _globe.is_globe the view is an orthographic globe; at
# the ceiling the whole planet fits the screen's height with a margin
# (the disk's diameter is 2·(180/π) ≈ 114.6 zoom-degrees).  A narrow
# terminal needs more room than that: see max_zoom.
MAX_ZOOM_DEG = 130.0
ZOOM_STEP = style.ZOOM_STEP


_route_layer_cache = Memo(keep=1)   # one slot: (route id, view key) -> DotLayer


def map_cells(size=None):
    """The map's size in cells: the terminal's columns, at least 20, by
    its rows less the header and the footer, at least 8.  `size` is a
    (cols, rows) already read; None reads the terminal."""
    cols, rows = size if size is not None else get_terminal_size()
    return max(20, cols), max(8, rows - 2)


def max_zoom(gw, hc):
    """The zoom-out ceiling for a gw by hc map: the whole disk on screen.

    MAX_ZOOM_DEG frames the planet against the map's height, which is
    the binding edge on a terminal at least twice as wide as it is
    tall.  Narrower than that and the disk runs off both sides at the
    same zoom, so the ceiling rises in proportion: the planet ends up
    smaller than the height alone would make it, and whole.
    """
    # The map's height in cell widths: hc*2 sub-pixels, each cell_aspect/2.
    return MAX_ZOOM_DEG * max(1.0, hc * 2 * (cell_aspect() / 2.0) / gw)


def wide_source(view, lat, zoom, gw, hc):
    """Whether this register draws the window from the world's sources.

    Terrain is one camera from the valley to the planet, so what is
    left to ask is only where the ground comes from: the terrarium
    tiles and the vector polygons while the window is a patch of
    Mercator, the baked planet beyond (`_globe.local_tiles`).  Street
    still crosses a projection at `_globe.ZOOM_DEG`, and keeps its own
    question until stage two.
    """
    if view == "street":
        return _globe.is_globe(zoom, lat)
    return not _globe.local_tiles(lat, zoom, gw, hc)


def fit_view(points, gw, hc, margin=0.15):
    """The view that frames `points` on a gw by hc map: (lat, lon, zoom).

    `points` are (lat, lon).  The centre is the middle of their box;
    the zoom is whichever of the box's height and its width, taken at
    the map's aspect, asks for more, with `margin` of the window left
    clear on every side so an endpoint's pin and label sit inside the
    frame rather than on it.  Clamped to the same range the keys walk.
    """
    lats = [p[0] for p in points]
    lons = [p[1] for p in points]
    lat_c = max(-80.0, min(80.0, (min(lats) + max(lats)) / 2))
    lon_c = (min(lons) + max(lons)) / 2
    lat_span = max(lats) - min(lats)
    # The width in the zoom's own unit, degrees of latitude down the
    # screen: hc*2 sub-pixels tall, each cell_aspect/2 cell widths.
    lon_span = ((max(lons) - min(lons)) * math.cos(math.radians(lat_c))
                * (hc * 2) * (cell_aspect() / 2.0) / gw)
    zoom = max(lat_span, lon_span) / (1 - 2 * margin)
    return lat_c, lon_c, max(MIN_ZOOM_DEG, min(max_zoom(gw, hc), zoom))


def _get_route_layer(route, bbox, gw, hc, project=None):
    """The route as its own ranked braille layer, memoized per view.

    Cool cyan, deliberately not the marker's yellow and never the
    motorway's amber: two UI accents in total, yellow for your points
    and cyan for your route, so a route can never read as a road.

    `project` is the view's own placement of a (lon, lat) on the dot
    grid, for a terrain view the camera draws: the line has to run
    along the valley the hillshade puts under it, not the one the bbox
    would.
    """
    if route is None:
        return None

    def build():
        layer = DotLayer(bbox, gw, hc)
        ink = style.palette().get("route",
                                        style.PALETTE_DARK["route"])
        rank = style.LINE_STYLES["route"][3]
        layer._draw_lines([route.coords], ink, width=2, rank=rank,
                          project=project)
        return layer

    return _route_layer_cache.get((id(route), _view_key(bbox, gw, hc)), build)


def _scale_bar(bbox, graph_w):
    """`├────────┤ 500 m`, or "" when no nice distance fits the view.

    Lives at the left of the footer, ahead of the attribution: it is the
    one piece of furniture that tells you what the map *means*, and it
    is cheaper than a grid.
    """
    best = style.scale_bar(bbox, graph_w,
                                 style.use_metric())
    if best is None:
        return ""
    cells, label = best
    return (f"{fg(*DIM)}├{'─' * cells}┤{RESET} "
            f"{fg(*MUTED)}{label}{RESET}  ")


class _ShiftedLayer:
    """Duck-typed stand-in for a ranked DotLayer during a drag preview."""
    __slots__ = ("dots", "color", "ribbon")

    def __init__(self, dots, color, ribbon=()):
        self.dots = dots
        self.color = color
        self.ribbon = set(ribbon)


# The newest real view in each register, and the ground every frame is
# cut from: street as (bbox, graph_w, height_cells, fills, layer,
# labels), terrain as (bbox, graph_w, height_cells, fill buffer, coast,
# rivers, elevation, borders, the land and water bits).  The bbox and
# the size are the *overscan's* — a view is built a margin wider than
# the window that asked for it — so a frame whose window falls inside
# one of these needs nothing fetched at all: at the built view's own
# centre it is a crop of it, and off that centre a resample of it.
#
# A window that has moved past the margin is still drawn from here,
# moved and scaled, while the next view builds: a flat view at a new
# window is a network fetch, and between a gesture and the data there
# is nothing else to draw.
#
# Newest, not last drawn: a view fetched while the camera was moving is
# never drawn by the frame that asked for it, which had moved on by the
# time it arrived.  It is still the truer picture of where the reader
# now is, so each frame takes what has landed since the last one
# (_take_landing) before deciding what it is cutting from.
_last_street = [None]
_last_terrain = [None]
# And the last real globe in each register, kept for the same reason:
# (bbox, graph_w, height_cells, sub-pixel fill, coast mask, border
# layer), the fill as the geometry left it — limb falloff and
# atmosphere already in, this hour's sun and cloud still out, so the
# stand-in is shaded where it now is like every other.  The centre is
# read back off the bbox rather than carried: a globe's stand-in only
# ever answers a zoom.
_last_globe = {}


def _axis_map(n, lo, span, plo, pspan, sub, flip):
    """For each of n sub-cells along one axis of the new view, which old
    sub-cell sits under its centre, or -1 for none. `flip` counts from
    the top, the way rows run."""
    out = []
    for i in range(n):
        f = (i + 0.5) / n
        v = (lo + span * (1.0 - f)) if flip else (lo + span * f)
        g = ((plo + pspan - v) if flip else (v - plo)) / pspan
        j = int(math.floor(g * sub))
        out.append(j if 0 <= j < sub else -1)
    return out


class _Reprojection:
    """One flat window resampled into another, axis by axis.

    The view is linear in lon/lat, so each axis maps on its own and a
    pan, a zoom or any mixture of the two is two lists of indices
    rather than a per-cell projection. Fills sample the old grid under
    each new sub-cell. Dots go the other way, old to new, when the view
    grew: sampling a zoom-out thins a road to specks, where carrying
    each dot across keeps the line. Zooming in samples, which keeps it
    solid.

    The two windows need not be the same size in cells: the source is
    an overscan now, a quarter wider and taller than the frame it was
    asked for, so every map here counts the source's own sub-cells
    rather than assuming the target's.
    """
    __slots__ = ("gw", "hc", "pgw", "phc", "cols", "rows", "grow", "xs", "ys")

    def __init__(self, gw, hc, pgw, phc, cols, rows, grow, xs, ys):
        self.gw, self.hc = gw, hc
        self.pgw, self.phc = pgw, phc
        self.cols, self.rows = cols, rows
        self.grow = grow      # the new window is the wider one
        self.xs, self.ys = xs, ys   # dot maps, whichever way they run

    def fills(self, pfills, ground):
        """The old sub-pixel colour grid under the new one's cells."""
        cols, gw = self.cols, self.gw
        blank = [ground] * gw
        out = []
        for r in self.rows:
            if r < 0:
                out.append(blank[:])
                continue
            src = pfills[r]
            out.append([ground if c < 0 else src[c] for c in cols])
        return out

    def dots(self, pdots, pcolor=None):
        """(dots, color) braille grids carried into the new window.

        `pcolor` is None for a layer that has no ink of its own — the
        coastline, whose colour the composer decides.
        """
        gw, hc = self.gw, self.hc
        dots = [[0] * gw for _ in range(hc)]
        color = [[None] * gw for _ in range(hc)]
        if self.grow:
            # old dot -> new dot
            fwd_x, fwd_y = self.xs, self.ys
            for cy in range(self.phc):
                prow = pdots[cy]
                pcrow = pcolor[cy] if pcolor is not None else None
                for cx in range(self.pgw):
                    bits = prow[cx]
                    if not bits:
                        continue
                    for sx in (0, 1):
                        nx = fwd_x[cx * 2 + sx]
                        if nx < 0:
                            continue
                        for sy in range(4):
                            if not bits & _BITS[sx][sy]:
                                continue
                            ny = fwd_y[cy * 4 + sy]
                            if ny < 0:
                                continue
                            ncx, ncy = nx // 2, ny // 4
                            dots[ncy][ncx] |= _BITS[nx % 2][ny % 4]
                            if pcrow is not None:
                                color[ncy][ncx] = pcrow[cx]
            return dots, color
        # new dot <- old dot
        back_x, back_y = self.xs, self.ys
        for ny, oy in enumerate(back_y):
            if oy < 0:
                continue
            prow = pdots[oy // 4]
            pcrow = pcolor[oy // 4] if pcolor is not None else None
            row, crow = dots[ny // 4], color[ny // 4]
            for nx, ox in enumerate(back_x):
                if ox < 0:
                    continue
                if prow[ox // 2] & _BITS[ox % 2][oy % 4]:
                    row[nx // 2] |= _BITS[nx % 2][ny % 4]
                    if pcrow is not None:
                        crow[nx // 2] = pcrow[ox // 2]
        return dots, color


def _reprojection(prev, bbox, graph_w, height_cells):
    """The map from `prev`'s window into `bbox`, or None when there is
    none to make: the very same window, or a degenerate one.

    A source of another size is not one of those any more — an overscan
    is exactly that, and a terminal that has just been resized still has
    the ground its last view covered.
    """
    pbbox, pgw, phc = prev[0], prev[1], prev[2]
    if tuple(pbbox) == tuple(bbox) and (pgw, phc) == (graph_w, height_cells):
        return None
    if min(pgw, phc, graph_w, height_cells) <= 0:
        return None
    minlon, minlat, maxlon, maxlat = bbox
    pminlon, pminlat, pmaxlon, pmaxlat = pbbox
    span_x, span_y = maxlon - minlon, maxlat - minlat
    pspan_x, pspan_y = pmaxlon - pminlon, pmaxlat - pminlat
    if min(span_x, span_y, pspan_x, pspan_y) <= 0:
        return None
    fh, pfh = height_cells * 2, phc * 2
    cols = _axis_map(graph_w, minlon, span_x, pminlon, pspan_x, pgw, False)
    rows = _axis_map(fh, minlat, span_y, pminlat, pspan_y, pfh, True)
    dw, dh = graph_w * 2, height_cells * 4
    pdw, pdh = pgw * 2, phc * 4
    grow = span_x >= pspan_x
    if grow:
        xs = _axis_map(pdw, pminlon, pspan_x, minlon, span_x, dw, False)
        ys = _axis_map(pdh, pminlat, pspan_y, minlat, span_y, dh, True)
    else:
        xs = _axis_map(dw, minlon, span_x, pminlon, pspan_x, pdw, False)
        ys = _axis_map(dh, minlat, span_y, pminlat, pspan_y, pdh, True)
    return _Reprojection(graph_w, height_cells, pgw, phc, cols, rows, grow,
                         xs, ys)


def _translation(prev, bbox, graph_w, height_cells):
    """(dx, dy) of the window inside `prev`'s grid, or None.

    A pan is taken as a translation: the two windows are the same
    scale and differ in where they start, so a stand-in is `prev`
    sliced and padded rather than resampled sub-cell by sub-cell.
    Only a zoom, a resize or a rounding that does not line up needs
    the axis maps.  The very same window at the very same size is
    nobody's stand-in and comes back None, as it always has.

    A translation is what the flat register's ground *is*, and only
    what the camera's ground looks like from nearby: two orthographic
    views at different centres turn against one another
    (`_globe.crop_dots`).  This is a stand-in, drawn while the real
    view is on its way, and a slice is what it can afford; the frame
    that replaces it is the one that has to be right.
    """
    at = _maps_overscan.locate(_maps_overscan.Frame(prev[0], prev[1],
                                                    prev[2]),
                               bbox, graph_w, height_cells, inside=False)
    if at == (0, 0) and (prev[1], prev[2]) == (graph_w, height_cells):
        return None
    return at


def _reproject_street(prev, bbox, graph_w, height_cells, ground):
    """(fills, layer) of `prev` redrawn into `bbox`, or None.

    Labels and hover stay behind — they belong to the old view, and a
    name under the wrong street is worse than no name at all.
    """
    at = _translation(prev, bbox, graph_w, height_cells)
    if at is not None:
        dx, dy = at
        player = prev[4]
        cut = _maps_overscan.shift_crop
        return (cut(prev[3], dx, dy * 2, graph_w, height_cells * 2, ground),
                _ShiftedLayer(
                    cut(player.dots, dx, dy, graph_w, height_cells, 0),
                    cut(player.color, dx, dy, graph_w, height_cells, None)))
    m = _reprojection(prev, bbox, graph_w, height_cells)
    if m is None:
        return None
    player = prev[4]
    dots, color = m.dots(player.dots, player.color)
    return m.fills(prev[3], ground), _ShiftedLayer(dots, color)


def _shift_cut(layer, dx, dy, graph_w, height_cells):
    """A braille layer sliced into a window that has outrun the margin."""
    if layer is None:
        return None
    cut = _maps_overscan.shift_crop
    return _ShiftedLayer(
        cut(layer.dots, dx, dy, graph_w, height_cells, 0),
        cut(layer.color, dx, dy, graph_w, height_cells, None))


def _reproject_terrain(prev, bbox, graph_w, height_cells):
    """(fill, coast, rivers, borders) of `prev` in `bbox`, or None.

    Terrain's stand-in is the street one's twin: the shaded ground
    moves and scales, the shoreline, the rivers and the borders go with
    it, and the elevation readout waits — a probe answered from the old
    grid would name the height of somewhere else.  The fill carried
    across is the bare terrain, before the sun and the clouds, so the
    stand-in is shaded where it now is rather than dragging an old
    terminator across the screen.

    Twin in its arithmetic and not in its claim.  The street register
    is drawn on a box that is linear in longitude and latitude, where
    a pan really is a translation; terrain is drawn by the camera,
    where it is one only near the centre.  So this picture is out of
    register by `_globe.crop_dots` and is only ever the one on screen
    while the view it stands in for is being fetched.
    """
    pfill, pcoast, privers = prev[3], prev[4], prev[5]
    pborders = prev[7]
    at = _translation(prev, bbox, graph_w, height_cells)
    if at is not None:
        dx, dy = at
        cut = _maps_overscan.shift_crop
        return (cut(pfill, dx, dy * 2, graph_w, height_cells * 2,
                    BG_PRIMARY),
                cut(pcoast, dx, dy, graph_w, height_cells, 0),
                _shift_cut(privers, dx, dy, graph_w, height_cells),
                _shift_cut(pborders, dx, dy, graph_w, height_cells))
    m = _reprojection(prev, bbox, graph_w, height_cells)
    if m is None:
        return None
    coast = m.dots(pcoast)[0] if pcoast is not None else None
    rivers = None
    if privers is not None:
        rivers = _ShiftedLayer(*m.dots(privers.dots, privers.color))
    borders = None
    if pborders is not None:
        borders = _ShiftedLayer(*m.dots(pborders.dots, pborders.color))
    return m.fills(pfill, BG_PRIMARY), coast, rivers, borders


def _disk_centre(bbox):
    """The globe centre a bbox stands for, at _get_globe's own rounding:
    two windows that share a view key share a centre."""
    return (round((bbox[1] + bbox[3]) / 2, 2),
            round((bbox[0] + bbox[2]) / 2, 2))


def _reproject_globe(prev, bbox, graph_w, height_cells):
    """(fill, coast, borders) of `prev`'s disk scaled into `bbox`, or None.

    Orthographic about the centre, a zoom is a uniform scaling of the
    disk — which is exactly the map the two bboxes already describe, so
    the planet borrows the flat views' axis map whole rather than
    growing one of its own.  The limb falloff and the atmosphere ring
    ride along inside the fill, and both belong to the disk's radius,
    which scales by the same factor.

    A zoom and nothing else.  A drag or a spin turns the geography
    under a disk that stays the size it was, and no scaling of the old
    picture is honest about that, so a moved centre gets no stand-in.
    """
    # a resized terminal gets no stand-in here either: the disk's radius
    # is set by the window's own cells, so rescaling one grid into
    # another of a different shape would not be the planet it was
    if (prev is None or prev[1:3] != (graph_w, height_cells)
            or _disk_centre(prev[0]) != _disk_centre(bbox)):
        return None
    m = _reprojection(prev, bbox, graph_w, height_cells)
    if m is None:
        return None
    _pbbox, _pw, _phc, pfill, pcoast, pborders = prev
    coast = m.dots(pcoast)[0] if pcoast is not None else None
    borders = (_ShiftedLayer(*m.dots(pborders.dots, pborders.color))
               if pborders is not None else None)
    return m.fills(pfill, BG_PRIMARY), coast, borders


def _usable_landing(landed, graph_w, height_cells):
    """Whether a view that landed between frames was built for this window.

    A landing is either a window build — `--print`, a destination
    fetched blocking — or an overscan for a window this size.  Anything
    else came from a terminal that has since been resized, and taking it
    would fit the old shape of the window inside the new one.
    """
    pw, ph = _maps_overscan.padding(graph_w, height_cells)
    return tuple(landed[1:3]) in ((graph_w, height_cells),
                                  (graph_w + 2 * pw, height_cells + 2 * ph))


def _take_landing(view, graph_w, height_cells):
    """Take whatever has landed since the last frame as this frame's source.

    Once per frame and before anything else, because what has landed
    decides the rest: a window inside the new view is a crop of it and
    asks for nothing, where a moment ago it would have been reprojected
    from the view before.
    """
    if view == "street":
        landed = take_street()
        if landed is not None and _usable_landing(landed, graph_w,
                                                  height_cells):
            _last_street[0] = landed
        return
    landed = take_terrain()
    if landed is None or not _usable_landing(landed, graph_w, height_cells):
        return
    # the shaded buffer it stands in through is the one its own frame
    # would have built, and the memo hands that frame back this very grid
    lbbox, lgw, lhc, lview = landed
    _last_terrain[0] = (
        lbbox, lgw, lhc, _terrain_buffer(lview, lbbox, lgw, lhc),
        lview.coast, lview.rivers, lview.elev, lview.borders, lview.shore)


def _flat_frame(view, bbox, graph_w, height_cells, block, motion, cap=None):
    """(the view to build, where the window sits in it, what is in hand).

    A blocking frame — `--print` — builds the window's own bbox and
    nothing beyond it, so a printed map is the bytes it has always been.
    Live, the window is a crop: of the view already in hand when that
    one reaches this far, and otherwise of a fresh overscan.  The third
    value is the built view itself when it is the one in hand, which is
    what keeps a pan inside the margin from asking the loader anything
    at all.

    Terrain's margin sits evenly on every side and its `motion` is
    ignored: under one camera an overscan is the same centre with more
    cells, so a window at that centre samples the very same plane
    points and its crop is exact.  A window that has since panned off
    it is a crop of the same *ground*, which is not the same thing:
    the built view has turned with the meridians, and the samples are
    there at somewhere other than the offset.  A frame at rest goes
    and gets them (_maps_overscan.Resample); a frame in motion slices,
    and `cap` is what stops the slice being taken so far off the built
    view's centre that a reader can see it swim
    (_maps_overscan.locate).
    """
    if block:
        return (_maps_overscan.window_frame(bbox, graph_w, height_cells),
                (0, 0), None)
    last = (_last_street if view == "street" else _last_terrain)[0]
    if last is not None:
        frame = _maps_overscan.Frame(last[0], last[1], last[2])
        at = _maps_overscan.locate(frame, bbox, graph_w, height_cells,
                                   cap=cap)
        if at is not None:
            return frame, at, last
    frame, at = _maps_overscan.plan(bbox, graph_w, height_cells, motion)
    if cap is not None and not _margin_is_local(frame):
        return (_maps_overscan.window_frame(bbox, graph_w, height_cells),
                (0, 0), None)
    return frame, at, None


def _margin_is_local(frame):
    """Whether a terrain overscan can be stitched from the tiles.

    Asked of a margin round a window already within their reach, so
    the hand-off itself is not the question (`_globe.local_tiles`);
    what is left is whether the margin's corners stay on the disk and
    off the Mercator edge.  Where they do not — a window a degree or
    two short of the hand-off on a wide terminal — the window is
    built alone and does without its margin.
    """
    cam = _globe.Camera.for_bbox(frame.bbox, frame.gw, frame.hc)
    return _globe.local_tiles(cam.lat, cam.zoom, frame.gw, frame.hc,
                              margin=True)


def _get_terrain(bbox, gw, hc, block, window=None):
    """The terrain register's one loader, whatever the zoom.

    The footprint picks the source and nothing else does: within the
    Mercator sources' reach the view is stitched from terrarium tiles
    and vector polygons, and beyond it from the planet baked once into
    a texture.  Both arrive through the same camera, so the two meet
    without a seam — the detail changes at the hand-off, the shape does
    not.

    The footprint is the *window's*, when `window` says the bbox is
    its overscan: the margin is a quarter again as wide, and a crop
    has to be the map the window itself would draw.
    """
    cam = _globe.Camera.for_bbox(bbox, gw, hc)
    if window is not None:
        wcam = _globe.Camera.for_bbox(window[0], gw, window[1])
        local = wcam.local_tiles
    else:
        local = cam.local_tiles
    if local:
        return _get_elevation(bbox, gw, hc, block, window)
    view = _get_globe(cam.lat, cam.lon, cam.zoom, gw, hc, block)
    if view is None:
        return _EMPTY_TERRAIN
    return TerrainView(
        view.elev, view.coast,
        view.water if view.water is not None else view.wet,
        None, view.cover, view.borders, view.fill, view.shade, view.atmo,
        view.lls, view.glow_lls)


# How far out of register a slice may be before the resample is worth
# taking, in braille dots: a quarter of one, which is the same drift
# _maps_overscan.SLACK already lets a crop's own cell boundaries have
# and is well under the width of anything drawn.
_SLICE_DOTS = 0.25


def _exact_crop(frame, bbox, graph_w, height_cells, at, moving):
    """The resample to take a resting window out of `frame` with, or None.

    None while the view is moving: at 160x45 a slice is under a
    millisecond and a resample is ten, or thirty-five the first time
    at a new offset, and thirty frames a second against a build
    holding the interpreter lock is not where that goes.  The frames
    under a hand are a preview of the one about to land anyway.

    None, too, wherever the slice already *is* the resample — a window
    at the built view's own centre, a window whose shear is under a
    quarter of a dot, and the whole of street scale, where the ground
    was rasterised onto a box linear in longitude and latitude and a
    crop of that box is the window's own picture (`_globe.affine_ok`).
    """
    if moving:
        return None
    cam = _globe.Camera.for_bbox(frame.bbox, frame.gw, frame.hc)
    if _globe.affine_ok(cam.lat, cam.zoom, frame.gw, frame.hc):
        return None
    zoom = height_cells * frame.cell[1]
    shear = _globe.crop_dots(
        cam.lat, _globe.cap(zoom, graph_w, height_cells),
        graph_w, height_cells,
        at[0] + graph_w / 2 - frame.gw / 2,
        at[1] + height_cells / 2 - frame.hc / 2)
    if shear < _SLICE_DOTS:
        return None
    return _maps_overscan.resample(frame, bbox, graph_w, height_cells)


def _render_terrain(bbox, graph_w, height_cells, block, pan_offset,
                    mouse_pos, marker_cell, dest_cell, origin_cell, lang,
                    route_layer, show_labels=True, sun=False, clouds=False,
                    frame=None, at=(0, 0), source=None, moving=False):
    """(map lines, readout, hover, loading, err) for the hillshaded view.

    The terrain register at every zoom.  There is one geometry now —
    the orthographic camera `_globe.geometry` inverts, whose disk at a
    close zoom is thousands of rows across and whose window is a small
    patch of it — so a zoom out of a valley and on past the hand-off
    changes the scale of the picture and never its projection.  What
    the footprint still decides is where the ground comes from: the
    terrarium tiles and the vector polygons while they can be asked,
    the planet's own baked texture beyond them.

    Terrain's readout is its own probe — the elevation under the pointer
    — and it carries no hover slot: the braille here is geography rather
    than a network of named things, and "coastline" under the cursor
    would tell a reader less than the metres already there.
    """
    lat0 = (bbox[1] + bbox[3]) / 2
    lon0 = (bbox[0] + bbox[2]) / 2
    zoom = bbox[3] - bbox[1]
    wide = not _globe.local_tiles(lat0, zoom, graph_w, height_cells)
    err = None
    loading = False
    view = _EMPTY_TERRAIN
    if frame is None:
        frame = _maps_overscan.window_frame(bbox, graph_w, height_cells)
        at = (0, 0)
    obbox, ogw, ohc = frame
    dx0, dy0 = at
    cropping = (ogw, ohc) != (graph_w, height_cells)
    if source is not None:
        # the view this window is a crop of is already in hand: the
        # loader is not asked, and nothing goes to the network
        pass
    elif block:
        try:
            view = _get_terrain(obbox, ogw, ohc, True,
                                _maps_overscan.window_hint(
                                    frame, graph_w, height_cells))
        except Exception as exc:
            log_failure("maps/elevation", "terrain load", exc, fallback="empty terrain")
            err = str(exc)
    else:
        view = _get_terrain(obbox, ogw, ohc, False,
                            _maps_overscan.window_hint(
                                frame, graph_w, height_cells))
        loading = view.elev is None

    elev, coast, rivers = view.elev, view.coast, view.rivers
    borders, shore = view.borders, view.shore
    terrain = None
    if source is not None:
        (_obbox, _ogw, _ohc, terrain, coast, rivers, elev, borders,
         shore) = source
    elif elev is not None:
        terrain = _terrain_buffer(view, obbox, ogw, ohc, wide)
        _last_terrain[0] = (tuple(obbox), ogw, ohc, terrain, coast, rivers,
                            elev, borders, shore)
    exact = None
    if terrain is not None and cropping:
        # The window out of the margin.  At the built view's own centre
        # that is the sub-cells it already holds at the planned offset,
        # and nothing more is needed: an orthographic view about the
        # same centre with more cells around the same middle samples
        # the very same plane points.  Panned off that centre it is
        # the same ground somewhere other than the offset, because the
        # built view has turned with the meridians — so a frame at rest
        # gathers the samples the window would have taken, and a frame
        # in motion takes the slice and is briefly out of register.
        exact = _exact_crop(frame, bbox, graph_w, height_cells, at, moving)
        if exact is not None:
            terrain = exact.grid(terrain, BG_PRIMARY)
            elev = exact.grid(elev, None)
            if shore is not None:
                # the shore is cut again rather than carried: the flat
                # rule, that the coastline is the boundary of the fill,
                # holds for the window's fill as it did for the built
                # view's (_maps_views.shore_bits)
                coast = _edge_dots(exact.bits(shore, SHORE_LAND),
                                   exact.bits(shore, SHORE_WATER),
                                   graph_w, height_cells)
            else:
                coast = exact.dots(coast)
            rivers = exact.layer(rivers)
            borders = exact.layer(borders)
        else:
            terrain = _maps_overscan.crop_grid(terrain, dx0, dy0 * 2, graph_w,
                                               height_cells * 2)
            elev = _maps_overscan.crop_grid(elev, dx0, dy0 * 2, graph_w,
                                            height_cells * 2)
            coast = _maps_overscan.crop_grid(coast, dx0, dy0, graph_w,
                                             height_cells)
            rivers = _maps_overscan.crop_layer(rivers, dx0, dy0, graph_w,
                                               height_cells)
            borders = _maps_overscan.crop_layer(borders, dx0, dy0, graph_w,
                                                height_cells)
    if terrain is None and loading and _last_terrain[0] is not None:
        stand_in = _terrain_stand_in(_last_terrain[0], bbox, graph_w,
                                     height_cells, wide)
        if stand_in is not None:
            terrain, coast, rivers, borders = stand_in
    # Which list the names come from, and how they are chosen, still
    # flips at the old hand-off — that is stage three's to unify, and
    # it is the one flip this stage leaves.  *Where* a name lands is
    # this view's own geometry either way, so a dot and the ground it
    # points at cannot drift apart.
    cities = {}
    if show_labels and wide:
        # the planet's own placement is a memoised walk of the vendored
        # list, so a stand-in keeps its names
        cities = _globe.city_overlays(lat0, lon0, zoom, graph_w,
                                      height_cells, lang)
    elif show_labels and (elev is not None or not loading):
        # The basemap is fetched for its city names alone now; the
        # border strokes come from the camera, so they curve with
        # everything else.  It is not built for a stand-in: the names
        # are cut for each new window on this thread, a third of a
        # second of polygon filling, and a view in motion is a new
        # window thirty times a second.  They wait for the real view,
        # as the labels do — and they are cut for the overscan and
        # cropped with it, so a pan inside the margin fills the
        # polygons once for the whole of it instead of once a frame.
        basemap = _get_basemap(obbox, ogw, ohc)
        if basemap is not None:
            cam = _globe.Camera.for_bbox(obbox, ogw, ohc)
            if exact is not None:
                # the same names, placed by the window's own camera
                # rather than carried across from the built view's:
                # the ground under them has been, and a dot beside a
                # name that is not on the city is worse than either
                project = exact.place(dx0, dy0)
            elif _globe.affine_ok(cam.lat, cam.zoom, ogw, ohc):
                project = None
            else:
                project = cam.cell
            cities = basemap.city_overlays(project=project)
            if cropping:
                cities = _maps_overscan.crop_overlays(cities, dx0, dy0,
                                                      graph_w, height_cells)
    if terrain is None:
        terrain = [[BG_PRIMARY] * graph_w for _ in range(height_cells * 2)]
    if sun or clouds:
        # the ground as it is: same sun, same clouds, same city lights,
        # shaded through the same functions at every zoom, because
        # there is only one geometry left to shade.  The stand-in is
        # shaded where it now is, not where it was drawn.
        atmo = glow_lls = None
        if not wide:
            lls = _globe.geometry(lat0, lon0, zoom, graph_w,
                                  height_cells * 2)[0]
        elif view.lls is not None and source is None and not cropping:
            lls, atmo, glow_lls = view.lls, view.atmo, view.glow
        else:
            # a stand-in sits on a sphere of its own: the scaled ring
            # is the ring at the new radius, so the glow it gates is
            # worked out for the disk as it is this frame
            lls, _zs, atmo, glow_lls = _sphere(zoom, graph_w, height_cells,
                                               lat0, lon0)
        terrain = _shade_now(
            terrain, lls, sun,
            (_get_clouds(zoom, height_cells, block) if clouds else None),
            globe_now.city_lights_globe(lat0, lon0, zoom, graph_w,
                                        height_cells * 2) if sun else {},
            glow=(atmo, glow_lls) if glow_lls is not None else None)
    if not show_labels:
        coast = rivers = borders = None

    overlays = {}
    for pos, (ch, _color) in cities.items():
        overlays[pos] = (ch, None)  # None ink = per-cell contrast pick

    dx, dy = pan_offset
    if dx or dy:
        terrain = _shift_grid(terrain, dx, dy * 2, None)
        if coast is not None:
            coast = _shift_grid(coast, dx, dy, 0)
        rivers = _shift_layer(rivers, dx, dy)
        borders = _shift_layer(borders, dx, dy)
        route_layer = _shift_layer(route_layer, dx, dy)
    overlays = _place_marks(overlays, marker_cell, origin_cell, dest_cell,
                            dx, dy, graph_w, height_cells, False)
    readout = _elev_readout(elev, mouse_pos, dx, dy, graph_w, height_cells,
                            lang, centre=not (sun or wide))

    # rivers under the route, which is the order the strokes list means:
    # a route along a river valley owns the cells it shares.
    strokes = [s for s in (rivers, route_layer) if s is not None] or None
    lines = compose_terrain(None, terrain, overlays, graph_w,
                            height_cells, coast=coast, strokes=strokes,
                            borders=borders)
    return lines, readout, "", loading, err


def _terrain_stand_in(prev, bbox, graph_w, height_cells, wide):
    """The last terrain view carried into this window, or None.

    Which carriage the footprint decides.  A window the size of a
    valley is the one before it translated and scaled to well under a
    dot, so a pan or a zoom borrows the picture whole through the axis
    maps the flat views have always used.  A window the size of a
    planet has a limb in it, and no scaling of a disk is honest about
    a centre that has moved: there the stand-in answers a zoom and
    nothing else, which is exactly what it always did.  A zoom about
    the centre is a uniform scaling under this projection at *any*
    zoom, so the two paths agree about the one motion they share.
    """
    if not wide:
        return _reproject_terrain(prev, bbox, graph_w, height_cells)
    # A resized terminal gets no stand-in: the disk's radius is set by
    # the window's own cells, so rescaling one grid into another of a
    # different shape would not be the planet it was.  An overscan is
    # not that — it is this window's own camera with a margin round it,
    # and a zoom out of the last close view is cut from exactly that.
    if not _usable_landing(prev, graph_w, height_cells):
        return None
    if _disk_centre(prev[0]) != _disk_centre(bbox):
        return None
    m = _reprojection(prev, bbox, graph_w, height_cells)
    if m is None:
        return None
    (_pbbox, _pgw, _phc, pfill, pcoast, privers, _pelev, pborders,
     _pshore) = prev
    coast = m.dots(pcoast)[0] if pcoast is not None else None
    borders = (_ShiftedLayer(*m.dots(pborders.dots, pborders.color))
               if pborders is not None else None)
    return m.fills(pfill, BG_PRIMARY), coast, None, borders


def _ink_dusk(lls, sun, graph_w, height_cells):
    """The street register's per-cell ink dimming, or None by day.

    The street map's strokes are its geography, and a coastline drawn
    at noon brightness across a darkened sea reads as a wire.  The
    inks fade by the fills' own night factor (see globe_now.ink_dusk).
    """
    if not sun or lls is None:
        return None
    return globe_now.ink_dusk(lls, globe_now.subsolar(),
                               globe_now.NIGHT_STREET, graph_w,
                               height_cells)


def _shade_now(buf, lls, sun, canvas, lights, glow=None, night=None):
    """A copy of `buf` shaded into the present moment.

    The cached buffer stays pristine — daylight moves with the clock,
    so the moment is applied per repaint, never memoised.  `glow` is
    the globe's (atmo, limb lls) pair: the rim glow is scattered
    sunlight, so the terminator gates it too.  `night` is the caller's
    own night floor, where the default would leave nothing to see.
    """
    buf = [row[:] for row in buf]
    sub = globe_now.subsolar() if sun else None
    day = globe_now.daylight(lls, sub) if sun else None
    cloud = globe_now.clouds(lls, canvas) if canvas is not None else None
    globe_now.apply(buf, day, cloud, lights if sun else {}, night)
    if sun and glow is not None:
        atmo, glow_lls = glow
        _globe.gate_glow(buf, atmo, globe_now.daylight(glow_lls, sub),
                         BG_PRIMARY)
    return buf


def _render_globe(bbox, graph_w, height_cells, block, pan_offset,
                  mouse_pos, marker_cell, dest_cell, origin_cell, lang,
                  route_layer, show_labels=True, street=False, sun=False,
                  clouds=False):
    """The street register past the hand-off: the planet, orthographic.

    Terrain no longer arrives here — it is one camera at every zoom
    and is drawn by `_render_terrain` whatever the footprint — but the
    register is still a parameter, because street joins the camera in
    stage two and this is the half that will move.

    Everything downstream of the geometry belongs to the flat views —
    terrain keeps its shader, street keeps its two quiet fills, both
    keep the coastline rule, the Natural Earth borders and the city
    labels with their contrast-picked ink — so crossing the projection
    boundary changes the shape of the world, not the look of it.

    Street keeps exactly the two fills and the coast ink the flat
    street map draws with, and draws no borders, because the flat
    street map draws none: the frame before the hand-off and the frame
    after it should differ in curvature and nothing else.  The land is
    the terminal's own background, as it is on the flat map, so the
    planet reads as lit seas on a dark ground with the atmosphere
    marking its edge.  City lights it never had: they
    belong to terrain in either projection (_render_street says why),
    and the night floor that suits a register without them is the same
    one the flat street map takes.
    """
    lat0 = (bbox[1] + bbox[3]) / 2
    lon0 = (bbox[0] + bbox[2]) / 2
    zoom = bbox[3] - bbox[1]
    register = "street" if street else "terrain"
    err = None
    loading = False
    view = None
    if block:
        try:
            view = _get_globe(lat0, lon0, zoom, graph_w, height_cells, True,
                              street)
        except Exception as exc:
            log_failure("maps/elevation", "globe load", exc, fallback="empty globe")
            err = str(exc)
    else:
        view = _get_globe(lat0, lon0, zoom, graph_w, height_cells, False,
                          street)
        loading = view is None

    elev = view.elev if view is not None else None
    dusk = None
    coast = (view.coast if view is not None and show_labels
             else None)
    borders = (view.borders if view is not None and show_labels
               and not street else None)
    palette = style.palette()
    terrain = None
    lls = atmo = glow_lls = None
    if elev is not None:
        # the theme generation rides along, as it does on the flat
        # views: a terminal that changes theme must miss a buffer with
        # the old inks shaded into it
        key = (round(lat0, 2), round(lon0, 2), round(zoom, 1),
               graph_w, height_cells, street, view.fill is not None,
               _theme.generation)

        def build():
            if view.fill is not None:
                # the baked planet: the shader has already run, once
                terrain = [list(row) for row in view.fill]
            elif street:
                # the flat street map's own two fills; the 16-colour
                # table paints none, and the coastline carries it
                terrain = _globe.fill_buffer(
                    elev, palette.get("water"), palette.get("ground"),
                    BG_PRIMARY, view.wet if view.wet is not None
                    else view.water)
            else:
                # a scale-only bbox: the shader needs metres per
                # sub-pixel, which on the disk is the hand-off zoom's
                # scale everywhere (the limb compresses beyond it, and
                # the falloff owns that)
                spy_h = height_cells * 2
                sbbox = (0.0, -zoom / 2, zoom * graph_w / spy_h, zoom / 2)
                # the empty-tuple fallback means "no climate known" —
                # never "derive from bbox", because sbbox is scale-only
                terrain = build_terrain_buffer(
                    elev, sbbox, graph_w, spy_h, water=view.water,
                    cover=view.cover,
                    climate=_climate.grid_for_lls(view.lls) or ())
            _globe.shade_buffer(terrain, view.shade, view.atmo, BG_PRIMARY)
            return terrain

        terrain = _terrain_cache.get(key, build)
        lls, atmo, glow_lls = view.lls, view.atmo, view.glow_lls
        _last_globe[register] = (tuple(bbox), graph_w, height_cells,
                                 terrain, view.coast, view.borders)
    elif loading:
        # A zoom that crosses into a terrarium level still on disk, or
        # not yet baked at all, is a warm globe one frame and a cold
        # one the next, and the frames in between used to be a blank
        # disk — the black flash of a step that crossed a level.  The
        # disk it was is the disk it is, scaled: draw that until the
        # real one lands.
        carried = _reproject_globe(_last_globe.get(register), bbox,
                                   graph_w, height_cells)
        if carried is not None:
            terrain, pcoast, pborders = carried
            if show_labels:
                coast = pcoast
                borders = None if street else pborders
            if sun or clouds:
                # the sphere the stand-in now sits on: the scaled ring
                # is the ring at the new radius, so the glow it gates
                # is worked out for the disk as it is this frame
                lls, _zs, atmo, glow_lls = _sphere(zoom, graph_w,
                                                   height_cells, lat0, lon0)
    if terrain is None:
        terrain = [[BG_PRIMARY] * graph_w for _ in range(height_cells * 2)]
    elif (sun or clouds) and lls is not None:
        terrain = _shade_now(
            terrain, lls, sun,
            _get_clouds(zoom, height_cells, block) if clouds else None,
            globe_now.city_lights_globe(lat0, lon0, zoom, graph_w,
                                         height_cells * 2)
            if sun and not street else {},
            glow=(atmo, glow_lls) if glow_lls is not None else None,
            night=globe_now.NIGHT_STREET if street else None)
        if street:
            dusk = _ink_dusk(lls, sun, graph_w, height_cells)

    overlays = {}
    if show_labels:
        for pos, (ch, _color) in _globe.city_overlays(
                lat0, lon0, zoom, graph_w, height_cells, lang).items():
            overlays[pos] = (ch, None)  # None ink = per-cell contrast pick

    dx, dy = pan_offset
    if dx or dy:
        terrain = _shift_grid(terrain, dx, dy * 2, None)
        if coast is not None:
            coast = _shift_grid(coast, dx, dy, 0)
        if dusk is not None:
            dusk = _shift_grid(dusk, dx, dy, None)
        borders = _shift_layer(borders, dx, dy)
    overlays = _place_marks(overlays, marker_cell, origin_cell, dest_cell,
                            dx, dy, graph_w, height_cells, False)

    # the elevation probe is terrain's idiom; the street planet, like
    # the street map, answers with places rather than metres
    readout = ("" if street else
               _elev_readout(elev, mouse_pos, dx, dy, graph_w, height_cells,
                             lang, centre=False))

    strokes = [borders] if borders is not None else None
    lines = compose_terrain(None, terrain, overlays, graph_w,
                            height_cells, coast=coast, strokes=strokes,
                            coast_ink=palette.get("coast") if street
                            else None, ink_dusk=dusk)
    return lines, readout, "", loading, err


def _hover(layer, mouse_pos, pan_offset, lang):
    """(readout, lit ink cells, lit glyph cells), or ("", None, None).

    Nothing is resolved mid-drag: the index is built for the view as it
    was fetched, and during a pan preview what is on screen is that view
    shifted.  A pointer over a shifted map would be answered about the
    cell it used to be over, which is worse than not answering.
    """
    index = getattr(layer, "hover", None)
    if index is None or mouse_pos is None or pan_offset[0] or pan_offset[1]:
        return "", None, None
    # the same frame the elevation probe reads: terminal columns and rows
    # count from 1, and one header row sits above the map
    hit = index.at(mouse_pos[0] - 1, mouse_pos[1] - 2)
    if hit is None:
        return "", None, None
    text = _maps_hover.readout(hit, lang)
    return ((f" · {text}" if text else ""),
            set(hit.cells) or None, set(hit.glyphs) or None)


def _render_street(bbox, graph_w, height_cells, block, pan_offset,
                   mouse_pos, marker_cell, dest_cell, origin_cell, lang,
                   route_layer, show_labels=True, sun=False, clouds=False,
                   frame=None, at=(0, 0), source=None, reserved=None):
    """(map lines, readout, hover, loading, err) for the vector view."""
    err = None
    loading = False
    fills = layer = labels = None
    if frame is None:
        frame = _maps_overscan.window_frame(bbox, graph_w, height_cells)
        at = (0, 0)
    obbox, ogw, ohc = frame
    dx0, dy0 = at
    cropping = (ogw, ohc) != (graph_w, height_cells)
    if reserved is None:
        # the cells the page must route its labels around, in the built
        # view's own coordinates: the caller passes them for an overscan,
        # where the window's marks are not where the built view's are
        centre = (ogw // 2, ohc // 2)
        reserved = (marker_cell, centre) if marker_cell else (centre,)
    if source is not None:
        fills, layer, labels = source[3], source[4], source[5]
    elif block:
        try:
            fills, layer, labels = _get_street(
                obbox, ogw, ohc, True, lang, reserved,
                _maps_overscan.window_hint(frame, graph_w, height_cells))
        except Exception as exc:
            log_failure("maps/vtiles", "street load", exc, fallback="empty street map")
            err = str(exc)
    else:
        fills, layer, labels = _get_street(
            obbox, ogw, ohc, False, lang, reserved,
            _maps_overscan.window_hint(frame, graph_w, height_cells))
        loading = fills is None

    palette = style.palette()
    if fills is not None and source is None:
        _last_street[0] = (tuple(obbox), ogw, ohc, fills, layer, labels)
    if fills is not None and cropping:
        # the window out of the margin.  Labels come across as whole
        # runs or not at all — half a name straddling an edge is a
        # different word — and the hover index is read through the
        # offset rather than rebuilt for every crop.
        labels = _maps_overscan.crop_overlays(labels, dx0, dy0, graph_w,
                                              height_cells)
        hover = getattr(layer, "hover", None)
        layer = _maps_overscan.crop_layer(
            layer, dx0, dy0, graph_w, height_cells,
            hover=(_maps_overscan.CroppedHover(hover, dx0, dy0, graph_w,
                                               height_cells, labels)
                   if hover is not None else None))
        fills = _maps_overscan.crop_grid(fills, dx0, dy0 * 2, graph_w,
                                         height_cells * 2)
    if fills is None:
        ground = palette.get("ground")
        stand_in = (_reproject_street(_last_street[0], bbox, graph_w,
                                      height_cells, ground)
                    if loading and _last_street[0] is not None else None)
        if stand_in is not None:
            fills, layer = stand_in
        else:
            fills = [[ground] * graph_w for _ in range(height_cells * 2)]
            layer = _ShiftedLayer(
                [[0] * graph_w for _ in range(height_cells)],
                [[None] * graph_w for _ in range(height_cells)])
        labels = {}
    dusk = None
    if sun or clouds:
        # the sky over the streets: the fills darken and cloud over,
        # the strokes dim with them and the glyphs stay ink.  No city
        # lights — they are
        # terrain's, a picture of where the ground is built up, and
        # this map already draws the city itself.  Nothing burns back
        # through the dark here, so the fills keep a higher floor to
        # stay a map at night (see globe_now.NIGHT_STREET).
        lls = globe_now.flat_lls(bbox, graph_w, height_cells * 2)
        fills = _shade_now(
            fills, lls, sun,
            (_get_clouds(bbox[3] - bbox[1], height_cells, block)
             if clouds else None),
            {}, night=globe_now.NIGHT_STREET)
        dusk = _ink_dusk(lls, sun, graph_w, height_cells)

    hover, hot, hot_glyphs = _hover(layer, mouse_pos, pan_offset, lang)

    overlays = dict(labels) if show_labels else {}
    dx, dy = pan_offset
    if dx or dy:
        layer = _ShiftedLayer(
            _shift_grid(layer.dots, dx, dy, 0),
            _shift_grid(layer.color, dx, dy, None),
            {(c + dx, r + dy) for c, r in layer.ribbon})
        fills = _shift_grid(fills, dx, dy * 2, None)
        if dusk is not None:
            dusk = _shift_grid(dusk, dx, dy, None)
        route_layer = _shift_layer(route_layer, dx, dy)
    overlays = _place_marks(overlays, marker_cell, origin_cell, dest_cell,
                            dx, dy, graph_w, height_cells, True)

    strokes = [route_layer] if route_layer is not None else None
    lines = compose_map(fills, layer, overlays, graph_w, height_cells,
                        strokes=strokes, hot=hot, hot_glyphs=hot_glyphs,
                        ink_dusk=dusk)
    return lines, "", hover, loading, err


def _shift_layer(layer, dx, dy):
    """A braille layer moved with the drag preview, or None."""
    if layer is None:
        return None
    return _ShiftedLayer(_shift_grid(layer.dots, dx, dy, 0),
                         _shift_grid(layer.color, dx, dy, None),
                         {(c + dx, r + dy) for c, r in layer.ribbon})


def _marker_cell(bbox, graph_w, height_cells, m_lat, m_lon):
    """The home marker's cell, or None when it is off view."""
    minlon, minlat, maxlon, maxlat = bbox
    mcol = int((m_lon - minlon) / (maxlon - minlon) * graph_w)
    mrow = int((maxlat - m_lat) / (maxlat - minlat) * height_cells)
    if 0 <= mcol < graph_w and 0 <= mrow < height_cells:
        return mcol, mrow
    return None


def _marker_ink(ink, street):
    """Street mode's motorway takes ANSI 3, leaving bright yellow as the
    only yellow for the marker; terrain mode's inks are unchanged."""
    if street and color_mode() in ("16", "none"):
        return style.MARKER_16
    return ink


def _mark(glyph, ink, street):
    """A marker/crosshair/destination overlay tuple.  Street mode draws
    them bold: bold silver reads as bright white almost everywhere, so
    the user stays the brightest mark on screen even in a degraded
    palette."""
    if street:
        return (glyph, _marker_ink(ink, True), True)
    return (glyph, ink)


def _crosshair(overlays, cell, dx, dy, graph_w, height_cells, street):
    """Add the centre crosshair unless the marker already sits there."""
    centre = (graph_w // 2, height_cells // 2)
    at = (cell[0] + dx, cell[1] + dy) if cell else None
    if at != centre:
        overlays[centre] = _mark("+", CROSSHAIR, street)
    return overlays


def _place_marks(overlays, marker_cell, origin_cell, dest_cell, dx, dy,
                 graph_w, height_cells, street):
    """The user's marks over a view's own overlays: home, the route's
    origin and destination, all carried along with the drag preview,
    and the centre crosshair on top of everything."""
    if marker_cell is not None:
        overlays[marker_cell] = _mark("+", MARKER, street)
    if origin_cell is not None:
        overlays[origin_cell] = _mark("○", MARKER, street)
    if dest_cell is not None:
        overlays[dest_cell] = _mark("●", MARKER, street)
    if dx or dy:
        overlays = {(c + dx, r + dy): v for (c, r), v in overlays.items()
                    if 0 <= c + dx < graph_w and 0 <= r + dy < height_cells}
    return _crosshair(overlays, marker_cell, dx, dy, graph_w, height_cells,
                      street)


def _elev_readout(elev, mouse_pos, dx, dy, graph_w, height_cells, lang,
                  centre=True):
    """The elevation under the pointer, or at the view centre — or ""
    when the view has no elevation yet.  `centre` off keeps the pointer
    probe but drops the standing centre one: pointing is a question,
    but a view wide enough to be a globe isn't asking about one spot."""
    if elev is None:
        return ""
    probe = None
    if mouse_pos is not None:
        # the same frame the hover index reads: terminal columns and rows
        # count from 1, and one header row sits above the map
        pcol, prow = mouse_pos[0] - 1 - dx, mouse_pos[1] - 2 - dy
        if 0 <= pcol < graph_w and 0 <= prow < height_cells:
            probe = elev[prow * 2][pcol]
    if probe is None:
        if not centre:
            return ""
        probe = elev[height_cells][graph_w // 2]  # centre sub-pixel row
    if probe is None:
        return ""
    return f" · {style.fmt_elev(probe)}"


def prefetch_view(lat, lon, zoom, view, graph_w, height_cells, lang,
                  marker=None):
    """Start loading the view a motion is heading for, off the frame's thread.

    The motion gate keeps every other fetch off the network while the
    camera moves, and rightly: those views are passed through.  The
    destination is not — it is the one the reader asked for, and it is
    known before they get there: a flight's from the descent, a
    flick's from the release.  Asked for early it has a second or so
    to land, so the motion often ends on the real map rather than on a
    stand-in waiting to be replaced.  The keys are composed exactly as
    the renderer will compose them, or the work would warm a view
    nobody asks for.  While it runs, no window the view is merely
    passing over is built (_maps_views.fetch_destination).
    """
    def work():
        try:
            bbox = bbox_for(lat, lon, zoom, graph_w, height_cells)
            if wide_source(view, lat, zoom, graph_w, height_cells):
                _get_globe(lat, lon, zoom, graph_w, height_cells, True,
                           street=(view == "street"))
                return
            # the overscan *around* the resting centre, not ahead of it:
            # the motion ends here, so the margin the reader will pan
            # into next is as likely to be one way as the other — and
            # for terrain that is the only overscan there is, because a
            # margin off centre would not be an exact crop
            frame, _at = _maps_overscan.plan(bbox, graph_w, height_cells)
            if view != "street" and not _margin_is_local(frame):
                frame = _maps_overscan.window_frame(bbox, graph_w,
                                                    height_cells)
            hint = _maps_overscan.window_hint(frame, graph_w, height_cells)
            if view == "street":
                m_lat, m_lon = marker if marker else (lat, lon)
                _get_street(frame.bbox, frame.gw, frame.hc, True, lang,
                            _street_reserved(frame, m_lat, m_lon), hint)
            else:
                _get_terrain(frame.bbox, frame.gw, frame.hc, True, hint)
        except Exception as exc:
            log_failure("maps/prefetch", "destination", exc,
                        fallback="the view loads on arrival")

    fetch_destination(work)


def _street_reserved(frame, m_lat, m_lon):
    """The cells a street build must route its labels around, in the
    built view's own coordinates: the reader's marker and the middle of
    the view.  Both follow from the frame alone, so every window cropped
    out of one built view asks for it under the same key."""
    centre = (frame.gw // 2, frame.hc // 2)
    cell = _marker_cell(frame.bbox, frame.gw, frame.hc, m_lat, m_lon)
    return (cell, centre) if cell else (centre,)


def render_map(lat, lon, location_name, zoom, marker=None, runtime=None,
               block=True, pan_offset=(0, 0), mouse_pos=None,
               view="terrain", search=None, route=None, dest=None,
               origin=None, directions=None,
               note="", show_labels=True, sun=False,
               clouds=False, motion=(0, 0), moving=False, **_):
    lang = runtime.lang if runtime else "en"
    cols, rows = get_terminal_size()
    graph_w, height_cells = map_cells((cols, rows))

    bbox = bbox_for(lat, lon, zoom, graph_w, height_cells)
    m_lat, m_lon = marker if marker else (lat, lon)
    globe = wide_source(view, lat, zoom, graph_w, height_cells)
    # A mark is placed by whichever projection the ground under it was
    # drawn by.  Terrain is on the camera at every zoom, so it is the
    # camera's forward projection — except where the box rasteriser is
    # still the picture, and there the two are a twentieth of a dot
    # apart and the flat placement is the one the caches were built
    # with.  Street keeps its own hand-off until stage two.
    on_sphere = (globe if view == "street"
                 else not _globe.affine_ok(lat, zoom, graph_w, height_cells))
    if on_sphere:
        # markers live on a sphere: project them orthographically, and
        # let the far hemisphere hide what it hides
        def _cell_for(m):
            return _globe.marker_cell(lat, lon, zoom, graph_w, height_cells,
                                      m[0], m[1])
    else:
        def _cell_for(m):
            return _marker_cell(bbox, graph_w, height_cells, m[0], m[1])
    cell = _cell_for((m_lat, m_lon))
    dest_cell = _cell_for(dest) if dest is not None else None
    origin_cell = _cell_for(origin) if origin is not None else None
    if globe and view == "street":
        route_layer = None
        draw = functools.partial(_render_globe, street=True,
                                 sun=sun, clouds=clouds)
    elif globe:
        # terrain past the tiles: the same camera, filled from the
        # planet's own texture.  No overscan — the window is the view
        route_layer = None
        draw = functools.partial(_render_terrain, sun=sun, clouds=clouds)
    else:
        # what landed between frames first, because it decides whether
        # this window is a crop of a view already built or the start of
        # another one (_flat_frame)
        _take_landing(view, graph_w, height_cells)
        frame, at, source = _flat_frame(
            view, bbox, graph_w, height_cells, block,
            motion if view == "street" else (0, 0),
            cap=None if view == "street"
            else _globe.cap(zoom, graph_w, height_cells))
        # the route is drawn into the built view and cropped with it: a
        # pan inside the margin is a new window every frame and the same
        # built view, and redrawing the whole line thirty times a second
        # for a picture that has not changed is work for nothing
        project = None
        if view != "street" and route is not None:
            fcam = _globe.Camera.for_bbox(frame.bbox, frame.gw, frame.hc)
            if not _globe.affine_ok(fcam.lat, fcam.zoom, frame.gw, frame.hc):
                def project(lon, lat, _cam=fcam, _dw=frame.gw * 2,
                            _dh=frame.hc * 4):
                    return _cam.project(lon, lat, _dw, _dh)
        route_layer = _get_route_layer(route, frame.bbox, frame.gw, frame.hc,
                                       project)
        if route_layer is not None and (frame.gw, frame.hc) != (graph_w,
                                                                height_cells):
            route_layer = _maps_overscan.crop_layer(
                route_layer, at[0], at[1], graph_w, height_cells)
        draw = functools.partial(
            _render_street if view == "street" else _render_terrain,
            sun=sun, clouds=clouds, frame=frame, at=at, source=source,
            **({"reserved": _street_reserved(frame, m_lat, m_lon)}
               if view == "street" else {"moving": moving}))
    map_lines, readout, hover, loading, err = draw(
        bbox, graph_w, height_cells, block, pan_offset, mouse_pos,
        cell, dest_cell, origin_cell, lang, route_layer,
        show_labels=show_labels)

    # A note is a reply to something you asked for and outranks
    # everything; hover is what you are pointing at *now*, so it beats
    # the standing route summary, which beats the view's own probe.
    if note:
        readout = f" · {note}"
    elif hover:
        readout = hover
    elif route is not None:
        readout = f" · {ui.route_summary(route, lang)}"
    elif sun and not readout:
        # with daylight on the fact of interest is the sun, not the
        # centre pixel: name what it stands over, from the same offline
        # gazetteer that names a panned view
        s_lat, s_lon = globe_now.subsolar()
        under = _panned_place(s_lat, s_lon, lang)
        readout = f" · {ms('sun_over', lang, place=under)}"

    panned = abs(lat - m_lat) > 1e-9 or abs(lon - m_lon) > 1e-9
    place = (_panned_place(lat, lon, lang) if panned
             else location_name or f"{lat:.2f}, {lon:.2f}")
    tag = f" · {rs('loading', lang)}" if loading else ""
    # The mode word is the affordance that tells the reader modes exist;
    # the footer hint supplies the key.
    mode = f" · {ms('mode_' + view, lang)}"

    def _header(place_str):
        return (f"{fg(*MUTED)}{place_str}{RESET}"
                f"{fg(*DIM)}{mode}{readout}{tag}{RESET}")

    header = _header(place)
    over = visible_len(header) - cols
    if over > 0 and len(place) > over + 1:
        header = _header(place[:len(place) - over - 1] + "…")
    header += " " * max(0, cols - visible_len(header))
    from linecast import _help
    live = bool(getattr(runtime, 'live', False))
    foot_width = cols - visible_len(_help.hint(lang, cols)) - 2 if live else cols

    if err:
        key = 'streets_unavailable' if view == "street" else 'unavailable'
        foot = f"{fg(*DIM)}{ms(key, lang, err=err[:40])}{RESET}"
    else:
        # once a route stands, the footer teaches the route keys instead
        hint_key = 'hint_route' if route is not None else 'hint'
        hint = (f"{fg(*DIM)}{ms(hint_key, lang).split(' · ?')[0]}{RESET}"
                if sys.stdout.isatty() else "")
        # the Köppen credit is owed only where the climate grid is
        # colouring the ground: the terrain register, flat or globe
        kg = (_climate.ATTRIBUTION
              if view != "street" and _climate.available() else None)
        if globe:
            # either register's globe draws from the elevation tiles
            # (borders and cities are vendored Natural Earth); terrain's
            # adds the climate grid, this hour's clouds add theirs
            base = f"{ATTRIBUTION} · {kg}" if kg else ATTRIBUTION
            attribs = ((f"{base} · {globe_now.ATTRIBUTION}",
                        base, ATTRIBUTION) if clouds
                       else (base, ATTRIBUTION))
        elif view == "street":
            from linecast._vtiles import attribution_long
            tiles_long = attribution_long()
            if _builtup.enabled():
                # the settlement raster tints street ground too, and its
                # CC-BY credit rides the long rung as it does on terrain
                tiles_long = f"{tiles_long} · {_builtup.ATTRIBUTION}"
            attribs = ((f"{tiles_long} · {globe_now.ATTRIBUTION}",
                        tiles_long,
                        style.ATTRIB_TILES_SHORT) if clouds
                       else (tiles_long, style.ATTRIB_TILES_SHORT))
        else:
            # terrain's lakes and rivers come from the tiles too, so the
            # first rung credits both sources and the fallbacks shorten;
            # the settlement raster earns its CC-BY credit when in use
            both = f"{ATTRIBUTION} · {style.ATTRIB_TILES_SHORT}"
            long = f"{both} · {kg}" if kg else both
            if clouds:
                attribs = (f"{long} · {globe_now.ATTRIBUTION}", both,
                           ATTRIBUTION)
            elif _builtup.enabled():
                attribs = (f"{long} · {_builtup.ATTRIBUTION}", both,
                           ATTRIBUTION)
            else:
                attribs = (long, both, ATTRIBUTION)
        # the night lights are terrain's, flat or globe, and only the
        # sun puts them on screen; the rung above the ladder credits
        # them and every shorter rung stays as it was
        if sun and view != "street" and _night_lights.load():
            attribs = (f"{attribs[0]} · {_night_lights.ATTRIBUTION}",
                       *attribs)
        scale = (_scale_bar(bbox, graph_w)
                 if view == "street" and not globe else "")
        # first rung that fits wins: long+hint, short+hint, short, bare
        ladder = [f"{scale}{fg(*DIM)}{a}{RESET}  {hint}" for a in attribs]
        ladder += [f"{scale}{fg(*DIM)}{attribs[-1]}{RESET}",
                   f"{fg(*DIM)}{attribs[-1]}{RESET}", ""]
        for foot in ladder:
            if visible_len(foot) <= foot_width:
                break
    if live:
        foot = _help.footer(foot, cols, lang)
    foot += " " * max(0, cols - visible_len(foot))

    out = "\n".join([header, *map_lines, foot])
    # A cell's two halves each carry a colour, and neighbouring cells
    # are often the same colour: compact_colors drops the escapes that
    # ask for the colour already in effect.  It runs here, before the
    # overlay channel, so the body it reads is the body and nothing
    # else -- and so --print sends the shorter frame too.
    out = compact_colors(out)
    # One floating thing at a time, through the one overlay channel;
    # Search sits above the steps panel; the live loop owns help.
    if search is not None and search.open:
        # Any-motion mouse reporting is what makes a torn escape
        # sequence likely, and a torn sequence looks like ESC — which is
        # exactly the key guarding a text buffer.  Turn 1003 off for as
        # long as the field is open, and back on when it closes.
        return overlay(out, ui.search_overlay(search, cols, rows, lang),
                       motion=False)
    if directions is not None and directions.panel:
        floating = ui.directions_overlay(directions, cols, rows, lang,
                                               home_label=location_name)
        if floating:
            return overlay(out, floating, motion=True)
    if not block:
        return overlay(out, motion=True)
    return out


def main():
    # the live loop draws through render_map, so _maps.live imports this
    # module; importing it here, at the call, keeps that one-way at load
    from linecast._maps.live import main as live_main
    live_main()


_theme.track_imports(globals(), "linecast._color")
_theme.track_imports(globals(), "linecast._maps.paint")


if __name__ == "__main__":
    main()
