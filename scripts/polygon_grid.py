"""Polygons onto the vendored grids' tenth of a degree, and the PNG they ship as.

Shared by the build scripts for climate.png and glaciers.png, which run
it under `uv run --with numpy --with pillow`.
"""

import struct
import zlib

W, H = 3600, 1800        # a tenth of a degree
SS = 8                   # supersamples per cell, each way


def encode_png_gray(w, h, data):
    """Grayscale 8-bit PNG bytes from a row-major bytes-like of w*h."""
    def chunk(ctype, body):
        return (struct.pack(">I", len(body)) + ctype + body
                + struct.pack(">I", zlib.crc32(ctype + body) & 0xFFFFFFFF))

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 0, 0, 0, 0)
    raw = bytearray()
    for y in range(h):
        raw.append(0)  # filter: none
        raw += data[y * w:(y + 1) * w]
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
            + chunk(b"IEND", b""))


def polygons(geom):
    """Each polygon of a GeoJSON-style (Multi)Polygon as a list of rings."""
    if geom["type"] == "Polygon":
        return [geom["coordinates"]]
    if geom["type"] == "MultiPolygon":
        return geom["coordinates"]
    return []


def rasterise(geometries):
    """(H, W) uint8 share of each cell the geometries cover, 0..255.

    Each cell is supersampled SS ways in each direction; a polygon's
    first ring is its outline and the rest are its holes.
    """
    import numpy as np
    from PIL import Image, ImageDraw

    counts = np.zeros((H, W), dtype=np.uint16)
    for geom in geometries:
        for rings in polygons(geom):
            # supersample coordinates: x east from 180°W, y south from 90°N
            pts = [[((lon + 180.0) * W / 360.0 * SS,
                     (90.0 - lat) * H / 180.0 * SS) for lon, lat, *_ in ring]
                   for ring in rings]
            xs = [x for ring in pts for x, _ in ring]
            ys = [y for ring in pts for _, y in ring]
            # whole cells around the polygon, so the block sums align
            cx0, cy0 = max(0, int(min(xs) // SS)), max(0, int(min(ys) // SS))
            cx1 = min(W, int(max(xs) // SS) + 1)
            cy1 = min(H, int(max(ys) // SS) + 1)
            if cx1 <= cx0 or cy1 <= cy0:
                continue
            ox, oy = cx0 * SS, cy0 * SS
            img = Image.new("1", ((cx1 - cx0) * SS, (cy1 - cy0) * SS), 0)
            draw = ImageDraw.Draw(img)
            for i, ring in enumerate(pts):
                if len(ring) >= 3:
                    draw.polygon([(x - ox, y - oy) for x, y in ring],
                                 fill=0 if i else 1)
            block = np.asarray(img, dtype=np.uint16)
            block = block.reshape(cy1 - cy0, SS, cx1 - cx0, SS).sum(axis=(1, 3))
            counts[cy0:cy1, cx0:cx1] += block
    counts = np.minimum(counts, SS * SS).astype(np.uint32)
    return ((counts * 255 + SS * SS // 2) // (SS * SS)).astype(np.uint8)
