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

import sys

from linecast import (
    _builtup, _climate, _globe, _globe_now, _maps_hover, _maps_style,
    _maps_ui,
)
from linecast._color import fg, RESET, color_mode, BG_PRIMARY
from linecast._elevation import ATTRIBUTION
from linecast._framebuffer import get_terminal_size
from linecast._graphics import visible_len
from linecast._live import overlay
from linecast._maps_i18n import ms
from linecast._maps_paint import (  # noqa: F401 — the inks and composers
    BATHY_STOPS, BORDER_STROKE, COAST_STROKE, HYPSO_FAMILIES, LABEL_DARK,
    LABEL_LIGHT, LAKE_FILL, MARKER, build_terrain_buffer,
    compose_map, compose_terrain,
)
from linecast._maps_views import (  # noqa: F401 — the loaders and caches
    TerrainView, _coast_dots, _elev_cache,
    _get_clouds, _get_elevation, _get_globe, _get_street, _globe_cache,
    _street_cache, _terrain_buffer, _terrain_cache, _view_key,
    _water_subpixels,
)
from linecast._radar_basemap import (  # noqa: F401 — _edge_dots is re-exported
    BORDER, DotLayer, _edge_dots,
)
from linecast import _theme
from linecast._radar_i18n import rs
from linecast._radar_ui import (
    CROSSHAIR, DIM, MUTED,
    _panned_place,
)
from linecast._maps_preview import PreparedMap
from linecast._scenes import Memo

# Zoom is degrees of latitude top to bottom.  The floor used to be 0.1
# (about band 3); street mode's deepest classes — buildings, POI text —
# need 0.0012, which is roughly two metres per braille dot.
MIN_ZOOM_DEG = 0.0012
# The live map is orthographic at every scale. At the ceiling
# the whole planet fits the screen's height with a margin
# (the disk's diameter is 2·(180/π) ≈ 114.6 zoom-degrees).  A narrow
# terminal needs more room than that: see max_zoom.
MAX_ZOOM_DEG = 130.0
ZOOM_STEP = 1.5          # matches radar, so the two views feel the same


_route_layer_cache = Memo(keep=1)   # one slot: (route id, view key) -> DotLayer
_projected_borders = Memo(keep=4)


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
    return MAX_ZOOM_DEG * max(1.0, hc * 2 / gw)


def _get_route_layer(route, camera):
    """The route as its own ranked braille layer, memoized per view.

    Cool cyan, deliberately not the marker's yellow and never the
    motorway's amber: two UI accents in total, yellow for your points
    and cyan for your route, so a route can never read as a road.
    """
    if route is None:
        return None

    def build():
        layer = DotLayer(camera.bounds, camera.gw, camera.hc, camera=camera)
        ink = _maps_style.palette().get("route",
                                        _maps_style.PALETTE_DARK["route"])
        rank = _maps_style.LINE_STYLES["route"][3]
        layer._draw_lines([route.coords], ink, width=2, rank=rank)
        return layer

    return _route_layer_cache.get((id(route), camera.key, _theme.generation), build)


def _camera_borders(camera):
    from linecast._radar_basemap import _load_data

    def build():
        layer = DotLayer(camera.bounds, camera.gw, camera.hc, camera=camera)
        layer._draw_lines(_load_data()["borders"], BORDER)
        return layer

    return _projected_borders.get((camera.key, _theme.generation), build)


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


def _prepare_terrain(camera, lang, route_layer, show_labels, sun, clouds,
                     wait_for_clouds):
    gw, hc = camera.gw, camera.hc
    view = _get_elevation(camera)
    terrain = _terrain_buffer(view.elev, camera, view.water, view.cover)
    if sun or clouds:
        terrain = _shade_now(
            terrain, camera.lls(gw, hc * 2), sun,
            _get_clouds(camera.zoom, hc, wait_for_clouds) if clouds else None,
            _globe_now.city_lights_globe(camera.lat, camera.lon, camera.zoom,
                                         gw, hc * 2) if sun else {})
    return PreparedMap(
        camera, terrain, layer=_camera_borders(camera) if show_labels else None,
        coast=view.coast if show_labels else None,
        strokes=tuple(s for s in (view.rivers if show_labels else None, route_layer)
                      if s is not None),
        overlays=_city_labels(camera, lang) if show_labels else {}, elev=view.elev)


def _city_labels(camera, lang):
    # None ink lets the composer choose contrast against the local fill.
    return {pos: (ch, None) for pos, (ch, _ink) in _globe.city_overlays(
        camera.lat, camera.lon, camera.zoom, camera.gw, camera.hc, lang).items()}


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


def _prepare_globe(camera, lang, route_layer, show_labels, street, sun, clouds,
                   wait_for_clouds):
    """World sources and local tiles produce the same retained map layers."""
    gw, hc = camera.gw, camera.hc
    view = _get_globe(camera)
    palette = _maps_style.palette()

    def build():
        if street:
            terrain = _globe.fill_buffer(
                view.elev, palette.get("water"), palette.get("ground"),
                BG_PRIMARY, view.water)
        else:
            # The shader expects a geographic bbox. An equatorial scale-only
            # bbox gives equal pixel metres in both axes, including at the poles.
            scale = (0.0, -camera.zoom / 2, camera.zoom * gw / (hc * 2), camera.zoom / 2)
            terrain = build_terrain_buffer(
                view.elev, scale, gw, hc * 2, water=view.water,
                cover=view.cover, climate=_climate.grid_for_lls(view.lls) or ())
        _globe.shade_buffer(terrain, view.shade, view.atmo, BG_PRIMARY)
        return terrain

    terrain = _terrain_cache.get((camera.key, street, _theme.generation), build)
    dusk = None
    if (sun or clouds) and view.lls is not None:
        terrain = _shade_now(
            terrain, view.lls, sun,
            _get_clouds(camera.zoom, hc, wait_for_clouds) if clouds else None,
            _globe_now.city_lights_globe(camera.lat, camera.lon, camera.zoom,
                                         gw, hc * 2) if sun and not street else {},
            glow=(view.atmo, view.glow_lls) if view.glow_lls is not None else None,
            night=_globe_now.NIGHT_STREET if street else None)
        if street:
            dusk = _ink_dusk(view.lls, sun, gw, hc)
    return PreparedMap(
        camera, terrain, coast=view.coast if show_labels else None,
        strokes=tuple(s for s in (view.borders if show_labels and not street else None,
                                 route_layer) if s is not None),
        overlays=_city_labels(camera, lang) if show_labels else {},
        elev=None if street else view.elev, street=street, world=True,
        coast_ink=palette.get("coast") if street else None, ink_dusk=dusk)


def _hover(frame, mouse_pos, lang):
    """(readout, highlighted ink cells, highlighted glyph cells).

    Transformed frames have no hover index until detail is ready at their
    camera, so a moving map never answers about the old geography.
    """
    index = frame.hover
    if index is None or mouse_pos is None:
        return "", None, None
    # the same 1-based frame the elevation probe reads: one column of
    # left margin, one header row above the map
    hit = index.at(mouse_pos[0] - 1, mouse_pos[1] - 2)
    if hit is None:
        return "", None, None
    text = _maps_hover.readout(hit, lang)
    return ((f" · {text}" if text else ""),
            set(hit.cells) or None, set(hit.glyphs) or None)


def _prepare_street(camera, lang, route_layer, show_labels, sun, clouds,
                    wait_for_clouds, reserved):
    gw, hc = camera.gw, camera.hc
    fills, layer, labels = _get_street(camera, lang, reserved)
    dusk = None
    if sun or clouds:
        lls = camera.lls(gw, hc * 2)
        fills = _shade_now(
            fills, lls, sun,
            _get_clouds(camera.zoom, hc, wait_for_clouds) if clouds else None,
            {}, night=_globe_now.NIGHT_STREET)
        dusk = _ink_dusk(lls, sun, gw, hc)
    return PreparedMap(
        camera, fills, layer=layer, overlays=dict(labels) if show_labels else {},
        strokes=(route_layer,) if route_layer is not None else (),
        hover=layer.hover, street=True, ink_dusk=dusk)


def prepare_map(camera, *, view="terrain", lang="en", marker=None, route=None,
                show_labels=True, sun=False, clouds=False, wait_for_clouds=False):
    """Build geography for one camera, without composing terminal output.

    Live Maps calls this on its single scene worker. Static output calls it
    directly. Source errors propagate to those callers; optional weather can
    arrive later in live mode, while --print waits for its first cloud canvas.
    """
    route_layer = _get_route_layer(route, camera)
    if not camera.local_tiles:
        return _prepare_globe(camera, lang, route_layer, show_labels,
                              view == "street", sun, clouds, wait_for_clouds)
    if view == "street":
        centre = (camera.gw // 2, camera.hc // 2)
        home = _globe.marker_cell(camera.lat, camera.lon, camera.zoom,
                                  camera.gw, camera.hc, *(marker or (camera.lat, camera.lon)))
        return _prepare_street(camera, lang, route_layer, show_labels, sun, clouds,
                               wait_for_clouds, (home, centre) if home else (centre,))
    return _prepare_terrain(camera, lang, route_layer, show_labels, sun, clouds,
                            wait_for_clouds)


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


def _place_marks(overlays, marker_cell, origin_cell, dest_cell, gw, hc, street):
    """Paint user marks at the displayed camera over cartographic labels."""
    for cell, glyph in ((marker_cell, "+"), (origin_cell, "○"), (dest_cell, "●")):
        if cell is not None:
            overlays[cell] = _mark(glyph, MARKER, street)
    centre = (gw // 2, hc // 2)
    if marker_cell != centre:
        overlays[centre] = _mark("+", CROSSHAIR, street)
    return overlays


def _elev_readout(elev, mouse_pos, graph_w, height_cells,
                  centre=True):
    """The elevation under the pointer, or at the view centre — or ""
    when the view has no elevation yet.  `centre` off keeps the pointer
    probe but drops the standing centre one: pointing is a question,
    but a view wide enough to be a globe isn't asking about one spot."""
    if elev is None:
        return ""
    probe = None
    if mouse_pos is not None:
        # the same 1-based frame the hover index reads: one column of
        # left margin, one header row above the map
        pcol, prow = mouse_pos[0] - 1, mouse_pos[1] - 2
        if 0 <= pcol < graph_w and 0 <= prow < height_cells:
            probe = elev[prow * 2][pcol]
    if probe is None:
        if not centre:
            return ""
        probe = elev[height_cells][graph_w // 2]  # centre sub-pixel row
    if probe is None:
        return ""
    return f" · {_maps_style.fmt_elev(probe)}"


def _compose_prepared(prepared, camera, mouse_pos, marker_cell, dest_cell,
                      origin_cell, lang, sun):
    """Paint retained geography at the displayed camera, without loading data."""
    gw, hc = camera.gw, camera.hc
    if prepared is None:
        fills = [[BG_PRIMARY] * gw for _ in range(hc * 2)]
        marks = _place_marks({}, marker_cell, origin_cell, dest_cell, gw, hc, False)
        return compose_terrain(None, fills, marks, gw, hc), "", ""
    frame = prepared.transformed(camera)
    marks = _place_marks(dict(frame.overlays), marker_cell, origin_cell, dest_cell,
                         gw, hc, frame.street)
    hover, hot, hot_glyphs = _hover(frame, mouse_pos, lang)
    if frame.street and frame.layer is not None:
        lines = compose_map(frame.fills, frame.layer, marks, gw, hc,
                            strokes=frame.strokes, hot=hot, hot_glyphs=hot_glyphs,
                            ink_dusk=frame.ink_dusk)
        readout = ""
    else:
        lines = compose_terrain(frame.layer, frame.fills, marks, gw, hc,
                                coast=frame.coast, strokes=frame.strokes,
                                coast_ink=frame.coast_ink, ink_dusk=frame.ink_dusk)
        readout = _elev_readout(frame.elev, mouse_pos, gw, hc,
                                centre=not frame.world and not sun)
    return lines, readout, hover


def render_map(camera, prepared, location_name, *, marker=None, runtime=None,
               mouse_pos=None, view="terrain", search=None, route=None, dest=None,
               origin=None, directions=None, note="", sun=False, clouds=False,
               refining=False, error=None):
    """Compose a retained map and its UI. This path never prepares geography."""
    lang = runtime.lang if runtime else "en"
    lat, lon, zoom = camera.lat, camera.lon, camera.zoom
    graph_w, height_cells = camera.gw, camera.hc
    cols, rows = graph_w, height_cells + 2
    m_lat, m_lon = marker if marker else (lat, lon)
    globe = prepared.world if prepared is not None else not camera.local_tiles

    def cell(point):
        return (_globe.marker_cell(lat, lon, zoom, graph_w, height_cells,
                                    point[0], point[1]) if point is not None else None)

    map_lines, readout, hover = _compose_prepared(
        prepared, camera, mouse_pos, cell((m_lat, m_lon)), cell(dest), cell(origin),
        lang, sun)
    loading = refining or (prepared is None and error is None)
    err = error

    # A note is a reply to something you asked for and outranks
    # everything; hover is what you are pointing at *now*, so it beats
    # the standing route summary, which beats the view's own probe.
    if note:
        readout = f" · {note}"
    elif hover:
        readout = hover
    elif route is not None:
        readout = f" · {_maps_ui.route_summary(route, lang)}"
    elif sun and not readout:
        # with daylight on the fact of interest is the sun, not the
        # centre pixel: name what it stands over, from the same offline
        # gazetteer that names a panned view
        s_lat, s_lon = _globe_now.subsolar()
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
    foot_width = cols - visible_len(_help.hint(lang, cols)) - 3 if live else cols

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
              if view != "street" and prepared is not None
              and _climate.available() else None)
        if globe:
            # either register's globe draws from the elevation tiles
            # (borders and cities are vendored Natural Earth); terrain's
            # adds the climate grid, this hour's clouds add theirs
            base = f"{ATTRIBUTION} · {kg}" if kg else ATTRIBUTION
            attribs = ((f"{base} · {_globe_now.ATTRIBUTION}",
                        base, ATTRIBUTION) if clouds
                       else (base, ATTRIBUTION))
        elif view == "street":
            from linecast._vtiles import attribution_long
            tiles_long = attribution_long()
            if _builtup.enabled():
                # the settlement raster tints street ground too, and its
                # CC-BY credit rides the long rung as it does on terrain
                tiles_long = f"{tiles_long} · {_builtup.ATTRIBUTION}"
            attribs = ((f"{tiles_long} · {_globe_now.ATTRIBUTION}",
                        tiles_long,
                        _maps_style.ATTRIB_TILES_SHORT) if clouds
                       else (tiles_long, _maps_style.ATTRIB_TILES_SHORT))
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
        scale = (_scale_bar(camera.scale_bbox, graph_w)
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
    # One floating thing at a time, through the one overlay channel;
    # Search sits above the steps panel; the live loop owns help.
    if search is not None and search.open:
        # Any-motion mouse reporting is what makes a torn escape
        # sequence likely, and a torn sequence looks like ESC — which is
        # exactly the key guarding a text buffer.  Turn 1003 off for as
        # long as the field is open, and back on when it closes.
        return overlay(out, _maps_ui.search_overlay(search, cols, rows, lang),
                       motion=False)
    if directions is not None and directions.panel:
        floating = _maps_ui.directions_overlay(directions, cols, rows, lang,
                                               home_label=location_name)
        if floating:
            return overlay(out, floating, motion=True)
    if live:
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
