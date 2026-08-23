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
are in _maps_paint; the loaders and their caches are in _maps_views.

Usage: maps [--location LAT,LNG | PLACE] [--zoom DEG] [--view MODE]
            [--print] [--search CITY]
"""

import functools
import math
import os
import sys
import threading

from linecast import (
    _builtup, _climate, _globe, _globe_now, _maps_hover, _maps_route,
    _maps_style, _maps_ui, _maps_views,
)
from linecast._color import fg, RESET, BOLD, color_mode, BG_PRIMARY
from linecast._elevation import ATTRIBUTION
from linecast._framebuffer import get_terminal_size
from linecast._graphics import live_loop, visible_len
from linecast._location import get_location
from linecast._maps_i18n import ms
from linecast._maps_paint import (  # noqa: F401 — the inks and composers
    BATHY_STOPS, BORDER_STROKE, COAST_STROKE, HYPSO_FAMILIES, LABEL_DARK,
    LABEL_LIGHT, LAKE_FILL, MARKER, _BADGE, build_terrain_buffer,
    compose_map, compose_terrain,
)
from linecast._maps_search import (
    SearchUnavailable, fly_to_zoom, resolve_place,
)
from linecast._maps_views import (  # noqa: F401 — the loaders and caches
    TerrainView, _EMPTY_TERRAIN, _ViewCache, _coast_dots, _elev_cache,
    _get_clouds, _get_elevation, _get_globe, _get_street, _globe_cache,
    _hold_fetches, _nudge_repaint, _street_cache, _terrain_buffer,
    _terrain_cache, _view_key, _water_subpixels,
)
from linecast._radar_basemap import (  # noqa: F401 — _edge_dots is re-exported
    _BITS, BORDER, DotLayer, _edge_dots,
)
from linecast import _theme
from linecast._radar_i18n import rs
from linecast._radar_render import bbox_for
from linecast._runtime import RuntimeConfig, maps_parser
from linecast.radar import (
    CROSSHAIR, DIM, MUTED,
    _ShiftedBasemap, _get_basemap, _panned_place, _shift_grid,
)

# Zoom is degrees of latitude top to bottom.  The floor used to be 0.1
# (about band 3); street mode's deepest classes — buildings, POI text —
# need 0.0012, which is roughly two metres per braille dot.
MIN_ZOOM_DEG = 0.0012
# past _globe.ZOOM_DEG the terrain view is an orthographic globe; at
# the ceiling the whole planet fits the screen's height with a margin
# (the disk's diameter is 2·(180/π) ≈ 114.6 zoom-degrees)
MAX_ZOOM_DEG = 130.0
ZOOM_STEP = 1.5          # matches radar, so the two views feel the same


_route_layer_cache = {}   # one slot: (route id, view key) -> DotLayer


def _get_route_layer(route, bbox, gw, hc):
    """The route as its own ranked braille layer, memoized per view.

    Cool cyan, deliberately not the marker's yellow and never the
    motorway's amber: two UI accents in total, yellow for your points
    and cyan for your route, so a route can never read as a road.
    """
    if route is None:
        return None
    key = (id(route), _view_key(bbox, gw, hc))
    hit = _route_layer_cache.get(key)
    if hit is not None:
        return hit
    layer = DotLayer(bbox, gw, hc)
    ink = _maps_style.palette().get("route", _maps_style.PALETTE_DARK["route"])
    rank = _maps_style.LINE_STYLES["route"][3]
    layer._draw_lines([route.coords], ink, width=2, rank=rank)
    _route_layer_cache.clear()
    _route_layer_cache[key] = layer
    return layer


def _scale_bar(bbox, graph_w, lang):
    """`├────────┤ 500 m`, or "" when no nice distance fits the view.

    Lives at the left of the footer, ahead of the attribution: it is the
    one piece of furniture that tells you what the map *means*, and it
    is cheaper than a grid.
    """
    best = _maps_style.scale_bar(bbox, graph_w,
                                 _maps_style.use_metric(lang))
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




def _shade_now(buf, lls, sun, canvas, lights, glow=None):
    """A copy of `buf` shaded into the present moment.

    The cached buffer stays pristine — daylight moves with the clock,
    so the moment is applied per repaint, never memoised.  `glow` is
    the globe's (atmo, limb lls) pair: the rim glow is scattered
    sunlight, so the terminator gates it too.
    """
    buf = [row[:] for row in buf]
    sub = _globe_now.subsolar() if sun else None
    day = _globe_now.daylight(lls, sub) if sun else None
    cloud = _globe_now.clouds(lls, canvas) if canvas is not None else None
    _globe_now.apply(buf, day, cloud, lights if sun else {})
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
            err = str(exc)
    else:
        view = _get_globe(lat0, lon0, zoom, graph_w, height_cells, False)
        loading = view is None

    elev = view.elev if view is not None else None
    coast = (view.coast if view is not None and show_labels
             else None)
    borders = (view.borders if view is not None and show_labels
               else None)
    if elev is not None:
        key = (round(lat0, 2), round(lon0, 2), round(zoom, 1),
               graph_w, height_cells, street)
        terrain = _terrain_cache.get(key)
        if terrain is None:
            if street:
                p = _maps_style.palette()
                terrain = _globe.fill_buffer(elev, p.get("water"),
                                             p.get("ground"), BG_PRIMARY)
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
                    elev, sbbox, graph_w, spy_h, cover=view.cover,
                    climate=_climate.grid_for_lls(view.lls) or ())
            _globe.shade_buffer(terrain, view.shade, view.atmo, BG_PRIMARY)
            if len(_terrain_cache) > 2:
                _terrain_cache.clear()
            _terrain_cache[key] = terrain
        if (sun or clouds) and view.lls is not None:
            terrain = _shade_now(
                terrain, view.lls, sun,
                _get_clouds(zoom, height_cells, block) if clouds else None,
                _globe_now.city_lights_globe(lat0, lon0, zoom, graph_w,
                                             height_cells * 2) if sun else {},
                glow=(view.atmo, view.glow_lls)
                if view.glow_lls is not None else None)
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
                            height_cells, coast=coast, strokes=strokes)
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
    if sun or clouds:
        # the sky over the streets: the fills darken and cloud over,
        # the strokes and glyphs stay ink — a lit window is ink too
        fills = _shade_now(
            fills, _globe_now.flat_lls(bbox, graph_w, height_cells * 2),
            sun,
            (_get_clouds(bbox[3] - bbox[1], height_cells, block)
             if clouds else None),
            _globe_now.city_lights_flat(bbox, graph_w, height_cells * 2)
            if sun else {})

    hover, hot, hot_glyphs = _hover(layer, mouse_pos, pan_offset, lang)

    overlays = dict(labels) if show_labels else {}
    dx, dy = pan_offset
    if dx or dy:
        layer = _ShiftedLayer(
            _shift_grid(layer.dots, dx, dy, 0),
            _shift_grid(layer.color, dx, dy, None),
            {(c + dx, r + dy) for c, r in layer.ribbon})
        fills = _shift_grid(fills, dx, dy * 2, None)
        route_layer = _shift_layer(route_layer, dx, dy)
    overlays = _place_marks(overlays, marker_cell, origin_cell, dest_cell,
                            dx, dy, graph_w, height_cells, True)

    strokes = [route_layer] if route_layer is not None else None
    lines = compose_map(fills, layer, overlays, graph_w, height_cells,
                        strokes=strokes, hot=hot, hot_glyphs=hot_glyphs)
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
    return f" · {_maps_style.fmt_elev(probe, lang)}"


def render_map(lat, lon, location_name, zoom, marker=None, runtime=None,
               block=True, pan_offset=(0, 0), mouse_pos=None,
               view="terrain", search=None, route=None, dest=None,
               origin=None, directions=None,
               note="", helping=False, show_labels=True, sun=False,
               clouds=False, **_):
    lang = runtime.lang if runtime else "en"
    cols, rows = get_terminal_size()
    graph_w = max(20, cols)
    height_cells = max(8, rows - 2)

    bbox = bbox_for(lat, lon, zoom, graph_w, height_cells)
    m_lat, m_lon = marker if marker else (lat, lon)
    globe = zoom >= _globe.ZOOM_DEG
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
        scale = (_scale_bar(bbox, graph_w, lang)
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
        return out + ("\x00\033[?1003l"
                      + _maps_ui.search_overlay(search, cols, rows, lang))
    if helping:
        overlay = _maps_ui.help_overlay(cols, rows, lang, route is not None)
        if overlay:
            return out + "\x00\033[?1003h" + overlay
    if directions is not None and directions.panel:
        overlay = _maps_ui.directions_overlay(directions, cols, rows, lang,
                                              home_label=location_name)
        if overlay:
            return out + "\x00\033[?1003h" + overlay
    if not block:
        out += "\x00\033[?1003h"
    return out


def main():
    args = maps_parser().parse_args()
    runtime = RuntimeConfig.from_sources(namespace=args)
    # --view now is launch sugar, not a register: the terrain planet
    # with the sky switched on — daylight (s) and clouds (c), both
    # toggleable once inside
    sky = args.view == "now"
    if sky:
        args.view = "terrain"
        if args.zoom is None:
            args.zoom = MAX_ZOOM_DEG
    if args.zoom is None:
        args.zoom = _maps_style.DEFAULT_ZOOM[args.view]

    if args.profile not in _maps_route.PROFILES:
        print(f"maps: invalid profile '{args.profile}' — choose "
              f"{', '.join(_maps_route.PROFILES)}", file=sys.stderr)
        sys.exit(2)

    if args.search:
        from linecast._weather_sources import _search_locations
        _search_locations(args.search, lang=runtime.lang)
        return

    override = args.location or os.environ.get("WEATHER_LOCATION", "").strip()
    location_name = ""
    if override:
        try:
            parts = override.split(",")
            lat, lon = float(parts[0]), float(parts[1])
        except (ValueError, IndexError):
            from linecast._weather_sources import geocode_first
            hit = geocode_first(override, lang=runtime.lang)
            if hit is None:
                print(f'No locations matching "{override}".', file=sys.stderr)
                sys.exit(1)
            lat, lon, location_name = hit
    else:
        lat, lon, _cc = get_location()
        if lat is None:
            print("Could not determine location.", file=sys.stderr)
            sys.exit(1)

    if not location_name:
        try:
            from linecast._weather_sources import _reverse_geocode
            location_name = _reverse_geocode(lat, lon, lang=runtime.lang)[0] or ""
        except Exception:
            location_name = ""

    # --to and --from resolve through the map's own geocoders, never
    # the weather one: that is settlement-level only and exits the
    # process when the network is down, which is no way to fail a
    # lighthouse.
    def _endpoint(query, flag):
        try:
            hit = resolve_place(query, runtime.lang, near=(lat, lon))
        except SearchUnavailable:
            print(f"maps: could not reach a geocoder for {flag}",
                  file=sys.stderr)
            sys.exit(1)
        if hit is None:
            print(f'No locations matching "{query}".', file=sys.stderr)
            sys.exit(1)
        return hit

    dest = _endpoint(args.to, "--to") if args.to else None
    origin = _endpoint(args.from_, "--from") if args.from_ else None

    if runtime.live:
        _maps_views._live_refresh = True
        zoom = [args.zoom]
        center = [lat, lon]
        pan_preview = [0, 0]
        drag_base = [None]   # centre at globe-drag start, or None
        drag_sync = [False]  # next repaint renders the globe blocking
        spinning = [0]       # active spin generation; 0 = parked
        spin_seq = [0]       # last generation ever started
        view = [args.view]
        show_labels = [True]
        sun = [sky]          # s: daylight shading + night city lights
        clouds = [sky]       # c: this hour's cloud cover
        search = _maps_ui.SearchState()
        helping = [False]
        routes = _maps_ui.RouteState(profile=args.profile, home=(lat, lon))
        if origin is not None:
            routes.set_origin(origin.lat, origin.lon, origin.name)
        if dest is not None:
            routes.select(dest.lat, dest.lon, dest.name)
            routes.request()

        def zoom_to(new_zoom, at=None):
            """Apply a clamped zoom, keeping the point under `at` fixed.

            `at` is a terminal (col, row) in the same 1-based frame as
            mouse_pos; None zooms about the view centre.  Anchoring is
            the difference between a wheel that explores and one that
            makes you chase the thing you were looking at.
            """
            new_zoom = max(MIN_ZOOM_DEG, min(MAX_ZOOM_DEG, new_zoom))
            if new_zoom == zoom[0]:
                return False
            cols, rows = get_terminal_size()
            gw, hc = max(20, cols), max(8, rows - 2)
            pcol, prow = (at[0] - 1, at[1] - 2) if at else (-1, -1)
            # anchored zoom is a flat-map identity — on either side of
            # the globe hand-off, zoom about the centre instead
            if (zoom[0] >= _globe.ZOOM_DEG or new_zoom >= _globe.ZOOM_DEG):
                pcol = -1
            if 0 <= pcol < gw and 0 <= prow < hc:
                fx, fy = (pcol + 0.5) / gw, (prow + 0.5) / hc
                lon_span = (zoom[0] * (gw / (hc * 2))
                            / math.cos(math.radians(center[0])))
                plat = center[0] + zoom[0] * (0.5 - fy)
                plon = center[1] + lon_span * (fx - 0.5)
                lat_c = max(-80.0, min(80.0, plat - new_zoom * (0.5 - fy)))
                new_span = (new_zoom * (gw / (hc * 2))
                            / math.cos(math.radians(lat_c)))
                center[0] = lat_c
                center[1] = plon - new_span * (fx - 0.5)
                if center[1] > 180.0:
                    center[1] -= 360.0
                elif center[1] < -180.0:
                    center[1] += 360.0
            zoom[0] = new_zoom
            _hold_fetches()
            return True

        def spin(gen):
            """The r screensaver: the planet turns while you watch.

            Each tick walks the centre meridian westward and repaints
            through the same warm-canvas blocking path a drag uses, so
            the geography drifts eastward the way it actually does —
            about a degree a second, six minutes to the revolution.
            The spin yields to a drag in progress and parks itself the
            moment a zoom crosses back inside the hand-off.
            """
            import time
            while spinning[0] == gen:
                time.sleep(0.4)
                if spinning[0] != gen:
                    break
                if zoom[0] < _globe.ZOOM_DEG:
                    spinning[0] = 0
                    break
                if drag_base[0] is not None:
                    continue  # a drag steers; the spin waits its turn
                center[1] = (center[1] - 0.4 + 180.0) % 360.0 - 180.0
                drag_sync[0] = True
                _nudge_repaint()

        def cloud_tick():
            """The sky's slow heartbeat.

            Every half hour while the sky is switched on: the newest
            mosaic frame if clouds are showing, the sun where it now
            is, one repaint.  Never an animation — a view left running
            all evening simply stays true.
            """
            import time
            while True:
                time.sleep(1800)
                if not (sun[0] or clouds[0]):
                    continue
                if clouds[0]:
                    cols, rows = get_terminal_size()
                    try:
                        _globe_now.refresh(zoom[0], max(8, rows - 2) * 4)
                    except Exception:
                        pass
                _nudge_repaint()

        threading.Thread(target=cloud_tick, daemon=True).start()

        def on_action(key):
            if key == '+':
                return zoom_to(zoom[0] / ZOOM_STEP)
            if key == '-':
                return zoom_to(zoom[0] * ZOOM_STEP)
            if key == 'v':
                nxt = _maps_style.MODES.index(view[0]) + 1
                view[0] = _maps_style.MODES[nxt % len(_maps_style.MODES)]
                return True
            if key == 'l':
                show_labels[0] = not show_labels[0]
                return True
            if key == 's':
                sun[0] = not sun[0]
                return True
            if key == 'c':
                clouds[0] = not clouds[0]
                return True
            if key == 'r':
                if spinning[0]:
                    spinning[0] = 0
                    return False
                cols, rows = get_terminal_size()
                hc = max(8, rows - 2)
                if (zoom[0] < _globe.ZOOM_DEG
                        or not _globe.warm(zoom[0], hc * 4)):
                    return False  # only a warm globe spins
                spin_seq[0] += 1
                spinning[0] = spin_seq[0]
                threading.Thread(target=spin, args=(spinning[0],),
                                 daemon=True).start()
                return False  # the first tick is the repaint
            return False

        def on_wheel(direction, col, row):
            return zoom_to(zoom[0] * (ZOOM_STEP if direction < 0
                                      else 1.0 / ZOOM_STEP), at=(col, row))

        def fly_to(result):
            """Jump to a search result and frame it, instantly.

            No animation and no mode change: searching an address in
            terrain mode gives terrain at that address.  Predictability
            beats cleverness, and there is nothing to restore.
            """
            cols, rows = get_terminal_size()
            gw, hc = max(20, cols), max(8, rows - 2)
            center[0], center[1] = result.lat, result.lon
            zoom[0] = max(MIN_ZOOM_DEG, min(
                MAX_ZOOM_DEG, fly_to_zoom(result, (hc * 2) / gw)))

        def fly_to_step(step):
            """Frame one maneuver: centre on it, zoomed to roughly the
            distance the step covers, so a highway leg shows its whole
            run and a city turn shows its corner."""
            loc = step.get("location")
            if loc is None:
                return
            span = max(0.004, step["distance_m"] * 2.4 / 110540.0)
            zoom[0] = max(MIN_ZOOM_DEG, min(MAX_ZOOM_DEG, span))
            center[0] = max(-80.0, min(80.0, loc[1]))
            center[1] = loc[0]

        def intercept(action):
            """Maps owns dispatch: the search panel eats every key while
            it is open, the directions panel takes the arrows, and
            nothing else here consumes one."""
            if search.open:
                cols, rows = get_terminal_size()
                bbox = bbox_for(center[0], center[1], zoom[0],
                                max(20, cols), max(8, rows - 2))
                z = int(_maps_style.z_eff(bbox, max(8, rows - 2)))
                return search.handle(action, center[0], center[1], z,
                                     runtime.lang)
            if helping[0]:
                # Any key closes the panel; anything but the three
                # dismiss keys is then handled as usual, so `/` from
                # help opens search in one press.
                helping[0] = False
                if action in ('key:?', 'escape', 'quit'):
                    return True
            if action == 'key:?':
                helping[0] = True
                return True
            if routes.panel:
                # The directions panel: arrows walk the maneuvers and
                # the map flies along; the field rows name their own
                # keys, and `d` — its opening job done — edits the
                # destination its row promises.  Everything else
                # (zoom, v, n) still reaches the map underneath.
                if action in ('escape', 'quit'):
                    return routes.close_panel()
                if action in ('fwd', 'back', 'key:enter'):
                    # live_loop's time-scrub names: 'back' is the down
                    # arrow, which walks down the list — onward through
                    # the maneuvers.  Enter steps onward too.
                    step = routes.step_move(
                        -1 if action == 'fwd' else 1)
                    if step is not None:
                        fly_to_step(step)
                    return True
                if action == 'key:d':
                    search.start("route")
                    return True
            if action == 'key:/':
                search.start()
                return True
            if action == 'key:d':
                if routes.press() == "search":
                    search.start("route")
                return True
            if action == 'open':
                # o: re-point the origin, panel open or not.
                search.start("origin")
                return True
            if action == 'key:p':
                return routes.cycle_profile()
            if action == 'reset':
                # n / space: the one deliberately destructive key.
                routes.clear()
                return False        # and the loop still recentres
            return False

        def on_click(col, row):
            """A click on the directions panel acts on the row it hit —
            fields open their search or cycle the mode, a step takes
            the focus and the map flies to it.  Anywhere else, a click
            stays what it always was: nothing."""
            if search.open or not routes.panel or routes.panel_rows is None:
                return False
            width, acts = routes.panel_rows
            act = acts.get(row) if col <= width else None
            if act == 'from':
                search.start("origin")
            elif act == 'to':
                search.start("route")
            elif act == 'mode':
                routes.cycle_profile()
            elif isinstance(act, tuple):
                routes.step = act[1]
                fly_to_step(routes.route.steps[act[1]])
            else:
                return False
            return True

        def on_drag(dcol, drow, done):
            cols, rows = get_terminal_size()
            gw, hc = max(20, cols), max(8, rows - 2)
            # On the globe the disk stays put and the geography turns
            # under the cursor: every motion event recentres the view
            # from the drag-start centre and the repaint re-projects the
            # sphere, so the drag *is* the rotation rather than a
            # shifted snapshot of it.  Only a warm view rotates live —
            # until the world canvas is stitched there is nothing to
            # re-project without blocking on the network — and a drag
            # keeps whichever idiom it started with.
            globing = drag_base[0] is not None or (
                not (pan_preview[0] or pan_preview[1])
                and zoom[0] >= _globe.ZOOM_DEG
                and _globe.warm(zoom[0], hc * 4))
            if globing:
                if drag_base[0] is None:
                    if done:
                        return False  # a click, not a drag
                    drag_base[0] = (center[0], center[1])
                base_lat, base_lon = drag_base[0]
                lat = max(-80.0, min(80.0,
                                     base_lat + drow * zoom[0] / hc))
                lon = base_lon - (dcol * (zoom[0] / (hc * 2))
                                  / math.cos(math.radians(base_lat)))
                lon = (lon + 180.0) % 360.0 - 180.0
                changed = center != [lat, lon]
                center[0], center[1] = lat, lon
                drag_sync[0] = drag_sync[0] or changed
                if done:
                    drag_base[0] = None
                return changed or done
            if not done:
                changed = pan_preview != [dcol, drow]
                pan_preview[0], pan_preview[1] = dcol, drow
                return changed
            had_preview = pan_preview[0] or pan_preview[1]
            pan_preview[0] = pan_preview[1] = 0
            if not (dcol or drow):
                return bool(had_preview)
            lon_span = (zoom[0] * (gw / (hc * 2))
                        / math.cos(math.radians(center[0])))
            center[0] = max(-80.0, min(80.0, center[0] + drow * zoom[0] / hc))
            center[1] += -dcol * lon_span / gw
            if center[1] > 180.0:
                center[1] -= 360.0
            elif center[1] < -180.0:
                center[1] += 360.0
            return True

        def render(mouse_pos=None, **_):
            # A search committed from a background reply lands here: the
            # worker cannot move the view itself, so it parks the result
            # and the next repaint applies it.
            hit = search.take_chosen()
            if hit is not None:
                fly_to(hit)
                if search.purpose == "route":
                    routes.select(hit.lat, hit.lon, hit.name)
                    routes.request()
                elif search.purpose == "origin":
                    routes.set_origin(hit.lat, hit.lon, hit.name)
                    if routes.dest is not None:
                        routes.request()
            # A rotating globe repaints synchronously: its canvas is
            # warm, so "blocking" is ~a tenth of a second of arithmetic,
            # and the alternative is a blank disk between frames.
            sync = drag_sync[0] and zoom[0] >= _globe.ZOOM_DEG
            drag_sync[0] = False
            return render_map(
                center[0], center[1], location_name, zoom[0],
                marker=(lat, lon), runtime=runtime, block=sync,
                pan_offset=(pan_preview[0], pan_preview[1]),
                mouse_pos=mouse_pos, view=view[0], search=search,
                route=routes.route, dest=routes.dest,
                origin=routes.origin, directions=routes,
                note=_maps_ui.route_note(routes, runtime.lang),
                helping=helping[0], show_labels=show_labels[0],
                sun=sun[0], clouds=clouds[0])

        live_loop(
            render,
            interval=3600,  # elevation doesn't change; repaint on input only
            mouse=True,
            on_action=on_action,
            on_drag=on_drag,
            on_wheel=on_wheel,
            intercept=intercept,
            text_mode=lambda: search.open,
            on_click=on_click,
        )
        spinning[0] = 0  # the loop is over; let the spin thread park
    else:
        found = note = None
        start = (origin.lat, origin.lon) if origin else (lat, lon)
        if dest is not None:
            try:
                found = _maps_route.route(args.profile, start,
                                          (dest.lat, dest.lon))
            except _maps_route.NoRoute:
                note = ms('dir_none', runtime.lang)
            except _maps_route.RouteUnavailable:
                note = ms('dir_unavailable', runtime.lang)
        print(render_map(lat, lon, location_name, args.zoom,
                         runtime=runtime, view=args.view, route=found,
                         dest=(dest.lat, dest.lon) if dest else None,
                         origin=((origin.lat, origin.lon, origin.name)
                                 if origin else None),
                         note=note or "", sun=sky, clouds=sky))
        if found is not None:
            # the turn-by-turn list rides below the map: --print asked
            # for directions, so it gets the directions
            print()
            for line in _maps_ui.steps_text(
                    found, runtime.lang,
                    origin_label=origin.name if origin else location_name,
                    dest_label=dest.name):
                print(line)


_theme.track_imports(globals(), "linecast._color")
_theme.track_imports(globals(), "linecast._maps_paint")


if __name__ == "__main__":
    main()
