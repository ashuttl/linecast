"""Hybrid compositor for the radar view.

The sea, land and radar echo all resolve to per-sub-pixel colours (two per
cell, rendered as half-blocks); glyphs are stamped on top with the cell's
blended colour as their background, so text and braille read as transparent
overlays on the weather rather than punching dark holes in it.

Per terminal cell, the layers resolve in priority order:

  1. city marker / label   → text glyph over the cell's blended colour
  2. warning outline (braille stroke, dark bg cut out of the echo)
  3. coast / border braille → stroke over the cell's blended colour
  4. radar echo blended over sea fill / land at half-block resolution

A glyph cell collapses its two sub-pixels into one background colour, so full
half-block resolution is lost only where a glyph actually sits.  Warning
outlines keep a dark background instead of the blend: they matter most inside
the brightest echoes, where a same-colour background would swallow them.
"""

import math

from linecast._color import fg, bg, lerp, RESET, BG_PRIMARY
from linecast._framebuffer import halfblock
from linecast._radar_basemap import COAST, SEA_FILL
from linecast._theme import ensure_contrast


def bbox_for(lat, lon, zoom, graph_w, height_cells):
    """Geographic window so map sub-cells render ~square on screen.

    `zoom` is the degrees of latitude shown top-to-bottom.
    """
    spy_h = height_cells * 2
    half_lat = zoom / 2
    minlat, maxlat = lat - half_lat, lat + half_lat
    lon_span = zoom * (graph_w / spy_h) / math.cos(math.radians(lat))
    return (lon - lon_span / 2, minlat, lon + lon_span / 2, maxlat)


def build_radar_buffer(rgba, pw, ph, graph_w, height_cells, sea=None):
    """Blend a decoded radar frame into a sub-pixel buffer over the background.

    Returns (buffer, echo_fraction). buffer[spy][x] is an (r,g,b) tuple where
    there is an echo, else None. 1:1 map: PNG pixel (x,y) → sub-pixel (x,y).
    ``sea`` is the basemap's sub-pixel water mask; translucent echo edges
    blend against the sea fill there instead of the land background.
    """
    spy_h = height_cells * 2
    buf = [[None] * graph_w for _ in range(spy_h)]
    opaque = 0
    for y in range(min(ph, spy_h)):
        row = buf[y]
        srow = sea[y] if sea is not None else None
        base = y * pw
        for x in range(min(pw, graph_w)):
            i = (base + x) * 4
            a = rgba[i + 3]
            if a == 0:
                continue
            opaque += 1
            echo = (rgba[i], rgba[i + 1], rgba[i + 2])
            if a >= 250:
                row[x] = echo
            else:
                under = SEA_FILL if srow is not None and srow[x] else BG_PRIMARY
                row[x] = lerp(under, echo, a / 255)
    total = max(1, min(ph, spy_h) * min(pw, graph_w))
    return buf, 100 * opaque / total


def compose(basemap, radar, overlays, graph_w, height_cells, warnings=None):
    """Composite geography + radar + overlays into a list of ANSI line strings."""
    base_bg = bg(*BG_PRIMARY)
    sea = getattr(basemap, "sea", None)
    lines = []
    for cy in range(height_cells):
        top_row = radar[cy * 2]
        bot_row = radar[cy * 2 + 1]
        sea_top = sea[cy * 2] if sea is not None else None
        sea_bot = sea[cy * 2 + 1] if sea is not None else None
        parts = []
        for cx in range(graph_w):
            # resolve the cell's two sub-pixels: echo where present, else the
            # underlying sea fill / land background
            top = top_row[cx]
            if top is None:
                top = SEA_FILL if sea_top is not None and sea_top[cx] else BG_PRIMARY
            bot = bot_row[cx]
            if bot is None:
                bot = SEA_FILL if sea_bot is not None and sea_bot[cx] else BG_PRIMARY
            ov = overlays.get((cx, cy))
            if ov is not None:
                ch, color = ov
                if ch == "":
                    # trailing column of a preceding double-width glyph: the
                    # glyph already covers it, so emit nothing to stay aligned
                    continue
                # a label can land on any echo colour; nudge its fg toward
                # the nearer pole until it clears the blended background
                cell = lerp(top, bot, 0.5)
                parts.append(f"{bg(*cell)}"
                             f"{fg(*ensure_contrast(color, cell, 3.0))}{ch}")
                continue
            if warnings is not None:
                wmask = warnings.dots[cy][cx]
                if wmask:
                    # dark bg cuts the stroke out of the echo fill, so the
                    # outline stays readable over any echo colour
                    parts.append(f"{base_bg}{fg(*warnings.color[cy][cx])}"
                                 f"{chr(0x2800 + wmask)}")
                    continue
            mask = basemap.dots[cy][cx]
            if mask:
                color = basemap.color[cy][cx] or COAST
                parts.append(f"{bg(*lerp(top, bot, 0.5))}{fg(*color)}"
                             f"{chr(0x2800 + mask)}")
            else:
                parts.append(halfblock(top, bot))
        parts.append(RESET)
        lines.append("".join(parts))
    return lines
