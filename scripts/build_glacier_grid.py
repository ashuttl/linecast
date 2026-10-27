"""Bake the vendored glacier grid from Natural Earth's glaciated areas.

Rasterises Natural Earth's 1:10m glaciated areas (public domain) onto
the Köppen grid's tenth of a degree, supersampled eight ways in each
direction, and writes each cell's ice fraction (0 none, 255 all) as a
grayscale PNG the package ships and maps/glaciers.py samples.

Natural Earth leaves out the Antarctic ice sheet's floating edges, and
the elevation data reports the shelves as land, so everything south of
60°S is ice: the shader never paints cover on the sea, and the few
dry valleys and nunataks are wrong about no terminal cell.

    uv run --with numpy --with pillow \
        scripts/build_glacier_grid.py ne_10m_glaciated_areas.geojson

or let it download the GeoJSON itself:

    uv run --with numpy --with pillow scripts/build_glacier_grid.py --fetch

Either way the grid lands at src/linecast/data/glaciers.png, which is
committed — this script reruns only when Natural Earth does.
"""

import argparse
import json
import struct
import zlib
from pathlib import Path

GEOJSON_URL = ("https://raw.githubusercontent.com/nvkelso/natural-earth-vector/"
               "master/geojson/ne_10m_glaciated_areas.geojson")
OUT = Path(__file__).resolve().parent.parent / "src/linecast/data/glaciers.png"

W, H = 3600, 1800        # a tenth of a degree, as climate.png
SS = 8                   # supersamples per cell, each way
ANTARCTIC = -60.0


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
    """Each polygon of a (Multi)Polygon as a list of rings."""
    if geom["type"] == "Polygon":
        return [geom["coordinates"]]
    if geom["type"] == "MultiPolygon":
        return geom["coordinates"]
    return []


def rasterise(features):
    """(H, W) supersample counts, 0..SS*SS, of the polygons' cover."""
    import numpy as np
    from PIL import Image, ImageDraw

    counts = np.zeros((H, W), dtype=np.uint16)
    for feat in features:
        for rings in polygons(feat["geometry"]):
            # supersample coordinates: x east from 180°W, y south from 90°N
            pts = [[((lon + 180.0) * W / 360.0 * SS,
                     (90.0 - lat) * H / 180.0 * SS) for lon, lat in ring]
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
    return np.minimum(counts, SS * SS)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("geojson", nargs="?", help="ne_10m_glaciated_areas.geojson")
    ap.add_argument("--fetch", action="store_true",
                    help=f"download {GEOJSON_URL}")
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()

    if args.fetch:
        import urllib.request
        print(f"downloading {GEOJSON_URL} (~6 MB) ...")
        with urllib.request.urlopen(GEOJSON_URL) as resp:
            data = json.loads(resp.read())
    elif args.geojson:
        data = json.loads(Path(args.geojson).read_text())
    else:
        ap.error("give a GeoJSON path or --fetch")

    import numpy as np
    counts = rasterise(data["features"])
    frac = (counts.astype(np.uint32) * 255 + SS * SS // 2) // (SS * SS)
    frac = frac.astype(np.uint8)
    frac[int((90.0 - ANTARCTIC) * H / 180.0):, :] = 255
    print(f"{len(data['features'])} features, "
          f"{int((frac > 0).sum())} cells with ice")

    png = encode_png_gray(W, H, frac.tobytes())
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(png)
    print(f"wrote {args.out} ({len(png)} bytes)")


if __name__ == "__main__":
    main()
