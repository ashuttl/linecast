"""Hybrid compositor for the radar view.

Per terminal cell, the layers resolve in priority order:

  1. city marker / label   → text glyph
  2. warning outline (braille stroke over the echo colour)
  3. radar echo (half-block RGB fill)  → the weather, painted on top
  4. braille geography (sea stipple / coast / border dots)
  5. bare land             → background

Radar (weather) is a half-block colour fill; geography is braille. A cell is a
single glyph, so where radar and geography overlap the radar wins that cell —
which is exactly what you want: the storm sits on the map.  Warning outlines
must beat the radar fill (they matter most inside the storm), so their braille
strokes keep the echo colour as the cell background.
"""

import math

from linecast._color import fg, bg, lerp, RESET, BG_PRIMARY
from linecast._framebuffer import halfblock
from linecast._radar_basemap import SEA


def bbox_for(lat, lon, zoom, graph_w, height_cells):
    """Geographic window so map sub-cells render ~square on screen.

    `zoom` is the degrees of latitude shown top-to-bottom.
    """
    spy_h = height_cells * 2
    half_lat = zoom / 2
    minlat, maxlat = lat - half_lat, lat + half_lat
    lon_span = zoom * (graph_w / spy_h) / math.cos(math.radians(lat))
    return (lon - lon_span / 2, minlat, lon + lon_span / 2, maxlat)


def build_radar_buffer(rgba, pw, ph, graph_w, height_cells):
    """Blend a decoded radar frame into a sub-pixel buffer over the background.

    Returns (buffer, echo_fraction). buffer[spy][x] is an (r,g,b) tuple where
    there is an echo, else None. 1:1 map: PNG pixel (x,y) → sub-pixel (x,y).
    """
    spy_h = height_cells * 2
    buf = [[None] * graph_w for _ in range(spy_h)]
    opaque = 0
    for y in range(min(ph, spy_h)):
        row = buf[y]
        base = y * pw
        for x in range(min(pw, graph_w)):
            i = (base + x) * 4
            a = rgba[i + 3]
            if a == 0:
                continue
            opaque += 1
            echo = (rgba[i], rgba[i + 1], rgba[i + 2])
            row[x] = echo if a >= 250 else lerp(BG_PRIMARY, echo, a / 255)
    total = max(1, min(ph, spy_h) * min(pw, graph_w))
    return buf, 100 * opaque / total


def compose(basemap, radar, overlays, graph_w, height_cells, warnings=None):
    """Composite geography + radar + overlays into a list of ANSI line strings."""
    base_bg = bg(*BG_PRIMARY)
    lines = []
    for cy in range(height_cells):
        top_row = radar[cy * 2]
        bot_row = radar[cy * 2 + 1]
        parts = []
        for cx in range(graph_w):
            ov = overlays.get((cx, cy))
            if ov is not None:
                ch, color = ov
                parts.append(f"{base_bg}{fg(*color)}{ch}")
                continue
            top, bot = top_row[cx], bot_row[cx]
            if warnings is not None:
                wmask = warnings.dots[cy][cx]
                if wmask:
                    # dark bg cuts the stroke out of the echo fill, so the
                    # outline stays readable over any echo colour
                    parts.append(f"{base_bg}{fg(*warnings.color[cy][cx])}"
                                 f"{chr(0x2800 + wmask)}")
                    continue
            if top is not None or bot is not None:
                parts.append(halfblock(top or BG_PRIMARY, bot or BG_PRIMARY))
                continue
            mask = basemap.dots[cy][cx]
            if mask:
                color = basemap.color[cy][cx] or SEA
                parts.append(f"{base_bg}{fg(*color)}{chr(0x2800 + mask)}")
            else:
                parts.append(f"{base_bg} ")
        parts.append(RESET)
        lines.append("".join(parts))
    return lines
