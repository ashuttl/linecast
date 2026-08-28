#!/usr/bin/env python3
"""Maps — a street map and a terrain map in the terminal.

`--view street` (the default) is in _maps_streets and friends: vector
tiles rasterised into fills, braille strokes and labels.  Only a handful
of things on it can afford a label, so the pointer is the other half of
reading it: hover names whatever owns the ink under it and lights that
whole feature up (_maps_hover).

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
are in _maps_paint; the loaders and their caches are in _maps_views;
the live loop and its keys are in _maps_live.

Usage: maps [--location LAT,LNG | PLACE] [--zoom DEG] [--view MODE]
            [--print] [--search CITY]
"""

import functools
import sys

from linecast import (
    _builtup, _climate, _globe, _globe_now, _maps_hover, _maps_style,
    _maps_ui,
)
from linecast._color import fg, RESET, BOLD, color_mode, BG_PRIMARY
from linecast._elevation import ATTRIBUTION
from linecast._framebuffer import get_terminal_size
from linecast._graphics import visible_len
from linecast._live import overlay
from linecast._maps_i18n import ms
from linecast._maps_paint import (  # noqa: F401 — the inks and composers
    BATHY_STOPS, BORDER_STROKE, COAST_STROKE, HYPSO_FAMILIES, LABEL_DARK,
    LABEL_LIGHT, LAKE_FILL, MARKER, _BADGE, build_terrain_buffer,
    compose_map, compose_terrain,
)
from linecast._maps_views import (  # noqa: F401 — the loaders and caches
    TerrainView, _EMPTY_TERRAIN, _coast_dots, _elev_cache,
    _get_clouds, _get_elevation, _get_globe, _get_street, _globe_cache,
    _street_cache, _terrain_buffer, _terrain_cache, _view_key,
    _water_subpixels,
)
from linecast._radar_basemap import (  # noqa: F401 — _edge_dots is re-exported
    BORDER, DotLayer, _edge_dots,
)
from linecast import _theme
from linecast._radar_i18n import rs
from linecast._radar_render import bbox_for
from linecast._radar_ui import (
    CROSSHAIR, DIM, MUTED,
    _ShiftedBasemap, _get_basemap, _panned_place, _shift_grid,
)
from linecast._runtime import log_failure
from linecast._scenes import Memo

# Zoom is degrees of latitude top to bottom.  The floor used to be 0.1
# (about band 3); street mode's deepest classes — buildings, POI text —
# need 0.0012, which is roughly two metres per braille dot.
MIN_ZOOM_DEG = 0.0012
# past _globe.is_globe the view is an orthographic globe; at
# the ceiling the whole planet fits the screen's height with a margin
# (the disk's diameter is 2·(180/π) ≈ 114.6 zoom-degrees)
MAX_ZOOM_DEG = 130.0
ZOOM_STEP = 1.5          # matches radar, so the two views feel the same


_route_layer_cache = Memo(keep=1)   # one slot: (route id, view key) -> DotLayer


def map_cells(size=None):
    """The map's size in cells: the terminal's columns, at least 20, by
    its rows less the header and the footer, at least 8.  `size` is a
    (cols, rows) already read; None reads the terminal."""
    cols, rows = size if size is not None else get_terminal_size()
    return max(20, cols), max(8, rows - 2)


def _get_route_layer(route, bbox, gw, hc):
    """The route as its own ranked braille layer, memoized per view.

    Cool cyan, deliberately not the marker's yellow and never the
    motorway's amber: two UI accents in total, yellow for your points
    and cyan for your route, so a route can never read as a road.
    """
    if route is None:
        return None

    def build():
        layer = DotLayer(bbox, gw, hc)
        ink = _maps_style.palette().get("route",
                                        _maps_style.PALETTE_DARK["route"])
        rank = _maps_style.LINE_STYLES["route"][3]
        layer._draw_lines([route.coords], ink, width=2, rank=rank)
        return layer

    return _route_layer_cache.get((id(route), _view_key(bbox, gw, hc)), build)


def _scale_bar(bbox, graph_w):
    """`├────────┤ 500 m`, or "" when no nice distance fits the view.

    Lives at the left of the footer, ahead of the attribution: it is the
    one piece of furniture that tells you what the map *means*, and it
    is cheaper than a grid.
    """
    best = _maps_style.scale_bar(bbox, graph_w,
                                 _maps_style.use_metric())
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


def _render_terrain(bbox, graph_w, height_cells, block, pan_offset,
                    mouse_pos, marker_cell, dest_cell, origin_cell, lang,
                    route_layer, show_labels=True, sun=False, clouds=False):
    """(map lines, readout, hover, loading, err) for the hillshaded view.

    Terrain's readout is its own probe — the elevation under the pointer
    — and it carries no hover slot: the braille here is geography rather
    than a network of named things, and "coastline" under the cursor
    would tell a reader less than the metres already there.
    """
    # `l` off means no ink on the planet at all: labels, borders,
    # coastlines and rivers alike, leaving the bare fields.  The
    # basemap's braille here is border strokes only (the coastline
    # comes from the elevation contour), so it isn't fetched.
    basemap = (_get_basemap(bbox, graph_w, height_cells)
               if show_labels else None)
    err = None
    loading = False
    view = _EMPTY_TERRAIN
    if block:
        try:
            view = _get_elevation(bbox, graph_w, height_cells, True)
        except Exception as exc:
            log_failure("maps/elevation", "terrain load", exc, fallback="empty terrain")
            err = str(exc)
    else:
        view = _get_elevation(bbox, graph_w, height_cells, False)
        loading = view.elev is None

    elev, coast, rivers = view.elev, view.coast, view.rivers
    if not show_labels:
        coast = rivers = None
    if elev is not None:
        terrain = _terrain_buffer(elev, bbox, graph_w, height_cells,
                                  view.water, view.cover)
        if sun or clouds:
            # the flat earth as it is: same sun, same clouds, same
            # city lights, shaded through the same functions the
            # globe uses — only the projection differs
            terrain = _shade_now(
                terrain,
                _globe_now.flat_lls(bbox, graph_w, height_cells * 2), sun,
                (_get_clouds(bbox[3] - bbox[1], height_cells, block)
                 if clouds else None),
                _globe_now.city_lights_flat(bbox, graph_w,
                                            height_cells * 2)
                if sun else {})
    else:
        terrain = [[BG_PRIMARY] * graph_w for _ in range(height_cells * 2)]

    overlays = {}
    if show_labels:
        for pos, (ch, _color) in basemap.city_overlays().items():
            overlays[pos] = (ch, None)  # None ink = per-cell contrast pick

    dx, dy = pan_offset
    if dx or dy:
        if basemap is not None:
            basemap = _ShiftedBasemap(_shift_grid(basemap.dots, dx, dy, 0),
                                      _shift_grid(basemap.color, dx, dy, None))
        terrain = _shift_grid(terrain, dx, dy * 2, None)
        if coast is not None:
            coast = _shift_grid(coast, dx, dy, 0)
        rivers = _shift_layer(rivers, dx, dy)
        route_layer = _shift_layer(route_layer, dx, dy)
    overlays = _place_marks(overlays, marker_cell, origin_cell, dest_cell,
                            dx, dy, graph_w, height_cells, False)
    readout = _elev_readout(elev, mouse_pos, dx, dy, graph_w, height_cells,
                            lang)

    # rivers under the route, which is the order the strokes list means:
    # a route along a river valley owns the cells it shares.
    strokes = [s for s in (rivers, route_layer) if s is not None] or None
    lines = compose_terrain(basemap, terrain, overlays, graph_w,
                            height_cells, coast=coast, strokes=strokes)
    return lines, readout, "", loading, err




def _ink_dusk(lls, sun, graph_w, height_cells):
    """The street register's per-cell ink dimming, or None by day.

    The street map's strokes are its geography, and a coastline drawn
    at noon brightness across a darkened sea reads as a wire.  The
    inks fade by the fills' own night factor (see _globe_now.ink_dusk).
    """
    if not sun or lls is None:
        return None
    return _globe_now.ink_dusk(lls, _globe_now.subsolar(),
                               _globe_now.NIGHT_STREET, graph_w,
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
    sub = _globe_now.subsolar() if sun else None
    day = _globe_now.daylight(lls, sub) if sun else None
    cloud = _globe_now.clouds(lls, canvas) if canvas is not None else None
    _globe_now.apply(buf, day, cloud, lights if sun else {}, night)
    if sun and glow is not None:
        atmo, glow_lls = glow
        _globe.gate_glow(buf, atmo, _globe_now.daylight(glow_lls, sub),
                         BG_PRIMARY)
    return buf


def _render_globe(bbox, graph_w, height_cells, block, pan_offset,
                  mouse_pos, marker_cell, dest_cell, origin_cell, lang,
                  route_layer, show_labels=True, street=False, sun=False,
                  clouds=False):
    """Either view past the hand-off: the planet, orthographic.

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
    err = None
    loading = False
    view = None
    if block:
        try:
            view = _get_globe(lat0, lon0, zoom, graph_w, height_cells, True)
        except Exception as exc:
            log_failure("maps/elevation", "globe load", exc, fallback="empty globe")
            err = str(exc)
    else:
        view = _get_globe(lat0, lon0, zoom, graph_w, height_cells, False)
        loading = view is None

    elev = view.elev if view is not None else None
    dusk = None
    coast = (view.coast if view is not None and show_labels
             else None)
    borders = (view.borders if view is not None and show_labels
               and not street else None)
    palette = _maps_style.palette()
    if elev is not None:
        key = (round(lat0, 2), round(lon0, 2), round(zoom, 1),
               graph_w, height_cells, street)

        def build():
            if street:
                # the flat street map's own two fills; the 16-colour
                # table paints none, and the coastline carries it
                terrain = _globe.fill_buffer(
                    elev, palette.get("water"), palette.get("ground"),
                    BG_PRIMARY, view.water)
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
        if (sun or clouds) and view.lls is not None:
            terrain = _shade_now(
                terrain, view.lls, sun,
                _get_clouds(zoom, height_cells, block) if clouds else None,
                _globe_now.city_lights_globe(lat0, lon0, zoom, graph_w,
                                             height_cells * 2)
                if sun and not street else {},
                glow=(view.atmo, view.glow_lls)
                if view.glow_lls is not None else None,
                night=_globe_now.NIGHT_STREET if street else None)
            if street:
                dusk = _ink_dusk(view.lls, sun, graph_w, height_cells)
    else:
        terrain = [[BG_PRIMARY] * graph_w for _ in range(height_cells * 2)]

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
                             lang))

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
    # the same 1-based frame the elevation probe reads: one column of
    # left margin, one header row above the map
    hit = index.at(mouse_pos[0] - 1, mouse_pos[1] - 2)
    if hit is None:
        return "", None, None
    text = _maps_hover.readout(hit, lang)
    return ((f" · {text}" if text else ""),
            set(hit.cells) or None, set(hit.glyphs) or None)


def _render_street(bbox, graph_w, height_cells, block, pan_offset,
                   mouse_pos, marker_cell, dest_cell, origin_cell, lang,
                   route_layer, show_labels=True, sun=False, clouds=False):
    """(map lines, readout, hover, loading, err) for the vector view."""
    err = None
    loading = False
    fills = layer = labels = None
    centre = (graph_w // 2, height_cells // 2)
    reserved = (marker_cell, centre) if marker_cell else (centre,)
    if block:
        try:
            fills, layer, labels = _get_street(bbox, graph_w, height_cells,
                                               True, lang, reserved)
        except Exception as exc:
            log_failure("maps/vtiles", "street load", exc, fallback="empty street map")
            err = str(exc)
    else:
        fills, layer, labels = _get_street(bbox, graph_w, height_cells,
                                           False, lang, reserved)
        loading = fills is None

    palette = _maps_style.palette()
    if fills is None:
        ground = palette.get("ground")
        fills = [[ground] * graph_w for _ in range(height_cells * 2)]
        layer = _ShiftedLayer([[0] * graph_w for _ in range(height_cells)],
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
        # stay a map at night (see _globe_now.NIGHT_STREET).
        lls = _globe_now.flat_lls(bbox, graph_w, height_cells * 2)
        fills = _shade_now(
            fills, lls, sun,
            (_get_clouds(bbox[3] - bbox[1], height_cells, block)
             if clouds else None),
            {}, night=_globe_now.NIGHT_STREET)
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
        return _maps_style.MARKER_16
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


def _elev_readout(elev, mouse_pos, dx, dy, graph_w, height_cells, lang):
    """The elevation under the pointer, or at the view centre — or ""
    when the view has no elevation yet."""
    if elev is None:
        return ""
    probe = None
    if mouse_pos is not None:
        # the same 1-based frame the hover index reads: one column of
        # left margin, one header row above the map
        pcol, prow = mouse_pos[0] - 1 - dx, mouse_pos[1] - 2 - dy
        if 0 <= pcol < graph_w and 0 <= prow < height_cells:
            probe = elev[prow * 2][pcol]
    if probe is None:
        probe = elev[height_cells][graph_w // 2]  # centre sub-pixel row
    if probe is None:
        return ""
    return f" · {_maps_style.fmt_elev(probe)}"


def render_map(lat, lon, location_name, zoom, marker=None, runtime=None,
               block=True, pan_offset=(0, 0), mouse_pos=None,
               view="terrain", search=None, route=None, dest=None,
               origin=None, directions=None,
               note="", helping=False, show_labels=True, sun=False,
               clouds=False, **_):
    lang = runtime.lang if runtime else "en"
    cols, rows = get_terminal_size()
    graph_w, height_cells = map_cells((cols, rows))

    bbox = bbox_for(lat, lon, zoom, graph_w, height_cells)
    m_lat, m_lon = marker if marker else (lat, lon)
    globe = _globe.is_globe(zoom, lat)
    if globe:
        # markers live on a sphere now: project them orthographically,
        # and let the far hemisphere hide what it hides
        cell = _globe.marker_cell(lat, lon, zoom, graph_w, height_cells,
                                  m_lat, m_lon)
        dest_cell = (_globe.marker_cell(lat, lon, zoom, graph_w,
                                        height_cells, dest[0], dest[1])
                     if dest is not None else None)
        origin_cell = (_globe.marker_cell(lat, lon, zoom, graph_w,
                                          height_cells, origin[0], origin[1])
                       if origin is not None else None)
        route_layer = None
        draw = functools.partial(_render_globe, street=(view == "street"),
                                 sun=sun, clouds=clouds)
    else:
        cell = _marker_cell(bbox, graph_w, height_cells, m_lat, m_lon)
        dest_cell = (_marker_cell(bbox, graph_w, height_cells,
                                  dest[0], dest[1])
                     if dest is not None else None)
        origin_cell = (_marker_cell(bbox, graph_w, height_cells,
                                    origin[0], origin[1])
                       if origin is not None else None)
        route_layer = _get_route_layer(route, bbox, graph_w, height_cells)
        draw = functools.partial(
            _render_street if view == "street" else _render_terrain,
            sun=sun, clouds=clouds)
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
        readout = f" · {_maps_ui.route_summary(route, lang)}"

    panned = abs(lat - m_lat) > 1e-9 or abs(lon - m_lon) > 1e-9
    place = (_panned_place(lat, lon, lang) if panned
             else location_name or f"{lat:.2f}, {lon:.2f}")
    tag = f" · {rs('loading', lang)}" if loading else ""
    # The mode word is the affordance that tells the reader modes exist;
    # the footer hint supplies the key.
    mode = f" · {ms('mode_' + view, lang)}"

    def _header(place_str):
        return (f"{fg(*_BADGE)}{BOLD}⬤ maps{RESET}  {fg(*MUTED)}"
                f"{place_str}{RESET}{fg(*DIM)}{mode}{readout}{tag}{RESET}")

    header = _header(place)
    over = visible_len(header) - cols
    if over > 0 and len(place) > over + 1:
        header = _header(place[:len(place) - over - 1] + "…")
    header += " " * max(0, cols - visible_len(header))

    if err:
        key = 'streets_unavailable' if view == "street" else 'unavailable'
        foot = f"{fg(*DIM)}{ms(key, lang, err=err[:40])}{RESET}"
    else:
        # once a route stands, the footer teaches the route keys instead
        hint_key = 'hint_route' if route is not None else 'hint'
        hint = (f"{fg(*DIM)}{ms(hint_key, lang)}{RESET}"
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
            attribs = ((f"{base} · {_globe_now.ATTRIBUTION}",
                        base, ATTRIBUTION) if clouds
                       else (base, ATTRIBUTION))
        elif view == "street":
            attribs = ((f"{_maps_style.ATTRIB_TILES_LONG} · "
                        f"{_globe_now.ATTRIBUTION}",
                        _maps_style.ATTRIB_TILES_LONG,
                        _maps_style.ATTRIB_TILES_SHORT) if clouds
                       else (_maps_style.ATTRIB_TILES_LONG,
                             _maps_style.ATTRIB_TILES_SHORT))
        else:
            # terrain's lakes and rivers come from the tiles too, so the
            # first rung credits both sources and the fallbacks shorten;
            # the settlement raster earns its CC-BY credit when in use
            both = f"{ATTRIBUTION} · {_maps_style.ATTRIB_TILES_SHORT}"
            long = f"{both} · {kg}" if kg else both
            if clouds:
                attribs = (f"{long} · {_globe_now.ATTRIBUTION}", both,
                           ATTRIBUTION)
            elif _builtup.enabled():
                attribs = (f"{long} · {_builtup.ATTRIBUTION}", both,
                           ATTRIBUTION)
            else:
                attribs = (long, both, ATTRIBUTION)
        scale = (_scale_bar(bbox, graph_w)
                 if view == "street" and not globe else "")
        # first rung that fits wins: long+hint, short+hint, short, bare
        ladder = [f"{scale}{fg(*DIM)}{a}{RESET}  {hint}" for a in attribs]
        ladder += [f"{scale}{fg(*DIM)}{attribs[-1]}{RESET}",
                   f"{fg(*DIM)}{attribs[-1]}{RESET}", ""]
        for foot in ladder:
            if visible_len(foot) <= cols:
                break
    foot += " " * max(0, cols - visible_len(foot))

    out = "\n".join([header, *map_lines, foot])
    # One floating thing at a time, through the one overlay channel;
    # search beats help beats the steps panel.
    if search is not None and search.open:
        # Any-motion mouse reporting is what makes a torn escape
        # sequence likely, and a torn sequence looks like ESC — which is
        # exactly the key guarding a text buffer.  Turn 1003 off for as
        # long as the field is open, and back on when it closes.
        return overlay(out, _maps_ui.search_overlay(search, cols, rows, lang),
                       motion=False)
    if helping:
        floating = _maps_ui.help_overlay(cols, rows, lang, route is not None)
        if floating:
            return overlay(out, floating, motion=True)
    if directions is not None and directions.panel:
        floating = _maps_ui.directions_overlay(directions, cols, rows, lang,
                                               home_label=location_name)
        if floating:
            return overlay(out, floating, motion=True)
    if not block:
        return overlay(out, motion=True)
    return out


def main():
    # the live loop draws through render_map, so _maps_live imports this
    # module; importing it here, at the call, keeps that one-way at load
    from linecast._maps_live import main as live_main
    live_main()


_theme.track_imports(globals(), "linecast._color")
_theme.track_imports(globals(), "linecast._maps_paint")


if __name__ == "__main__":
    main()
