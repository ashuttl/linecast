"""Render the production radar composite (braille geography + radar fill) to a
PNG for visual QA, using the real linecast modules.

    NE_DIR unused; needs data/basemap.json already built.
    python3 prototype/preview_radar.py [lat] [lon] [zoom] out.png
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from linecast._color import BG_PRIMARY  # noqa: E402
from linecast._radar_basemap import Basemap, _BITS, SEA  # noqa: E402
from linecast._radar_render import bbox_for, build_radar_buffer  # noqa: E402
from linecast._radar_sources import get_source  # noqa: E402
from png_encode import encode_rgb  # noqa: E402

MARKER = (255, 240, 120)
S = 5  # pixels per braille dot


def main():
    lat = float(sys.argv[1]) if len(sys.argv) > 1 else 29.95
    lon = float(sys.argv[2]) if len(sys.argv) > 2 else -90.07
    zoom = float(sys.argv[3]) if len(sys.argv) > 3 else 6.0
    out = sys.argv[4] if len(sys.argv) > 4 else "radar_preview.png"

    graph_w, height_cells = 150, 46
    bbox = bbox_for(lat, lon, zoom, graph_w, height_cells)
    bm = Basemap(bbox, graph_w, height_cells)

    src = get_source(lat, lon, 37)
    frame = src.current_frames()[-1]
    when = frame.time
    pw, ph, rgba = src.frame_rgba(bbox, graph_w, height_cells, frame)
    radar, echo = build_radar_buffer(rgba, pw, ph, graph_w, height_cells)
    print(f"source: {type(src).__name__}")

    overlays = dict(bm.city_overlays())
    overlays[(graph_w // 2, height_cells // 2)] = ("+", MARKER)

    DW, DH = graph_w * 2, height_cells * 4
    grid = [[BG_PRIMARY] * DW for _ in range(DH)]

    for cy in range(height_cells):
        for cx in range(graph_w):
            r0, c0 = cy * 4, cx * 2
            ov = overlays.get((cx, cy))
            top, bot = radar[cy * 2][cx], radar[cy * 2 + 1][cx]
            # only point markers render in the PNG; labels are terminal-only glyphs
            if ov is not None and ov[0] in ("•", "+"):
                col = ov[1]
                for dr in (1, 2):
                    for dc in (0, 1):
                        grid[r0 + dr][c0 + dc] = col
            elif top is not None or bot is not None:
                for dc in (0, 1):
                    grid[r0][c0 + dc] = top or BG_PRIMARY
                    grid[r0 + 1][c0 + dc] = top or BG_PRIMARY
                    grid[r0 + 2][c0 + dc] = bot or BG_PRIMARY
                    grid[r0 + 3][c0 + dc] = bot or BG_PRIMARY
            else:
                mask = bm.dots[cy][cx]
                if mask:
                    col = bm.color[cy][cx] or SEA
                    for dc in (0, 1):
                        for dr in (0, 1, 2, 3):
                            if mask & _BITS[dc][dr]:
                                grid[r0 + dr][c0 + dc] = col

    def get_px(px, py):
        return grid[py // S][px // S]

    data = encode_rgb(DW * S, DH * S, get_px)
    with open(out, "wb") as fh:
        fh.write(data)
    print(f"wrote {out} ({DW*S}x{DH*S}) · {echo:.0f}% echo · frame {when} · bbox {bbox}")


if __name__ == "__main__":
    main()
