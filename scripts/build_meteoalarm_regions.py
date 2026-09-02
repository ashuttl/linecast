"""Bake MeteoAlarm's warning regions into the vendored data file.

Most MeteoAlarm feeds carry no polygon on a warning, only a geocode: an
EMMA_ID such as PL3001, one per county, district, or province. This
script turns MeteoAlarm's published geometry for those codes into a
small binary that linecast._meteoalarm_regions reads at runtime to
answer "which regions is this point in?" -- and so which of a country's
several hundred warnings apply here.

Source: the geocodes GeoJSON from MeteoAlarm's re-users page
(https://meteoalarm.org/en/page/re-users, "geocodes json"; CC BY 4.0,
EUMETNET). Pass its path, or a URL:

    python3 scripts/build_meteoalarm_regions.py /path/to/geocodes.json

Output: src/linecast/data/meteoalarm_regions.bin.gz

Format (all little-endian, coordinates in 1e-5 degrees):

    b"LCMA" u8 version=1  u16 nregions
    per region:  u8 len, code (ascii)
                 i32 lat_min lat_max lng_min lng_max      (bounding box)
                 u16 npolys
    per polygon: u8 nrings                                (outer, then holes)
    per ring:    u16 npts, then npts x (i32 lat, i32 lng)

Rings are simplified with Douglas-Peucker at EPS degrees; a warning
region's edge two hundred metres off costs nobody an alert.
"""

import gzip
import json
import math
import os
import struct
import sys
import urllib.request

EPS = 0.002
OUT = os.path.join(os.path.dirname(__file__), "..", "src", "linecast",
                   "data", "meteoalarm_regions.bin.gz")


def douglas_peucker(pts, eps):
    """Open polyline simplification, iterative to spare the recursion limit."""
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        a, b = stack.pop()
        if b - a < 2:
            continue
        (x0, y0), (x1, y1) = pts[a], pts[b]
        dx, dy = x1 - x0, y1 - y0
        length = math.hypot(dx, dy)
        dmax, idx = 0.0, a
        for i in range(a + 1, b):
            x, y = pts[i]
            if length == 0:
                d = math.hypot(x - x0, y - y0)
            else:
                d = abs(dy * x - dx * y + x1 * y0 - y1 * x0) / length
            if d > dmax:
                dmax, idx = d, i
        if dmax > eps:
            keep[idx] = True
            stack.append((a, idx))
            stack.append((idx, b))
    return [p for p, k in zip(pts, keep) if k]


def simplify_ring(ring, eps):
    """A closed ring, simplified as two open halves so the ends survive."""
    pts = [tuple(p) for p in ring]
    if pts[0] == pts[-1]:
        pts = pts[:-1]
    if len(pts) < 4:
        return pts
    half = len(pts) // 2
    out = (douglas_peucker(pts[:half + 1], eps)[:-1]
           + douglas_peucker(pts[half:] + [pts[0]], eps)[:-1])
    return out if len(out) >= 3 else pts


def load(source):
    if source.startswith("http://") or source.startswith("https://"):
        req = urllib.request.Request(source, headers={"User-Agent": "linecast-build"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.load(resp)
    with open(source, encoding="utf-8") as fh:
        return json.load(fh)


def q(deg):
    return round(deg * 1e5)


def main(source):
    feats = load(source)["features"]
    feats = [f for f in feats if f["properties"].get("type") == "EMMA_ID"]
    feats.sort(key=lambda f: f["properties"]["code"])
    out = bytearray(b"LCMA" + struct.pack("<BH", 1, len(feats)))
    npts = 0
    for f in feats:
        code = f["properties"]["code"].encode("ascii")
        geom = f["geometry"]
        polys = (geom["coordinates"] if geom["type"] == "MultiPolygon"
                 else [geom["coordinates"]])
        packed = []
        lats, lngs = [], []
        for poly in polys:
            rings = []
            for ring in poly:
                pts = simplify_ring(ring, EPS)
                rings.append(pts)
                npts += len(pts)
                lngs.extend(p[0] for p in pts)
                lats.extend(p[1] for p in pts)
            packed.append(rings)
        out += struct.pack("<B", len(code)) + code
        out += struct.pack("<iiii", q(min(lats)), q(max(lats)), q(min(lngs)), q(max(lngs)))
        out += struct.pack("<H", len(packed))
        for rings in packed:
            assert len(rings) < 256
            out += struct.pack("<B", len(rings))
            for pts in rings:
                assert len(pts) < 65536
                out += struct.pack("<H", len(pts))
                out += b"".join(struct.pack("<ii", q(y), q(x)) for x, y in pts)
    with open(OUT, "wb") as fh:
        fh.write(gzip.compress(bytes(out), 9))
    print(f"{len(feats)} regions, {npts} points, {len(out)/1e6:.2f} MB raw, "
          f"{os.path.getsize(OUT)/1e6:.2f} MB gzipped -> {os.path.relpath(OUT)}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
