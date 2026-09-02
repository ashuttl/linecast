"""Bake MeteoAlarm's warning regions into the vendored data file.

Most MeteoAlarm feeds carry no polygon on a warning, only a geocode
naming a county, district, or province. This script turns the published
geometry for those codes into a small binary that
linecast._meteoalarm_regions reads at runtime to answer "which regions
is this point in?" -- and so which of a country's several hundred
warnings apply here.

Two kinds of geocode are placed:

  EMMA_ID   MeteoAlarm's own regions, from the geocodes GeoJSON on its
            re-users page (https://meteoalarm.org/en/page/re-users,
            "geocodes json"; CC BY 4.0, EUMETNET). Keyed by bare code:
            PL3001.
  NUTS2/3   Eurostat's statistical regions, for the feeds that file
            those instead (Bulgaria, Romania, and France at level 3;
            Hungary and Belgium at level 2), from GISCO's 2013 edition
            -- France and Hungary still file 2013 codes -- at 1:3M,
            which holds a departement's edge within a few hundred
            metres for half the bytes of the 1:1M file. Keyed by type
            and code, NUTS3/FR101, so a NUTS code and an EMMA_ID that
            share a spelling can never cross. © EuroGeographics for the
            administrative boundaries.

North Macedonia files its EMMA_IDs under the NUTS3 label, so those are
written a second time under NUTS3/ as well (ALIASES).

    python3 scripts/build_meteoalarm_regions.py bake /path/to/geocodes.json

fetches the two NUTS files from GISCO; pass --nuts3 and --nuts2 to use
local copies. Then

    uv run python scripts/build_meteoalarm_regions.py check

pulls every live feed and prints each geocode the baked file cannot
place, so a feed that changes its codes or its NUTS edition is caught
here and not by a user.

Output: src/linecast/data/meteoalarm_regions.bin.gz

Format (all little-endian, coordinates in 1e-5 degrees):

    b"LCMA" u8 version=2  u16 nregions
    per region:  u8 len, key (ascii)
                 i32 lat_min lat_max lng_min lng_max      (bounding box)
                 u16 npolys
    per polygon: u8 nrings                                (outer, then holes)
    per ring:    u16 npts, then npts x (i32 lat, i32 lng)

Version 2 differs from 1 only in what a key may be: a bare EMMA_ID, or
a geocode type and value joined by "/".

Rings are simplified with Douglas-Peucker at EPS degrees; a warning
region's edge two hundred metres off costs nobody an alert.
"""

import argparse
import collections
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

GISCO = ("https://gisco-services.ec.europa.eu/distribution/v2/nuts/geojson/"
         "NUTS_RG_03M_2013_4326_LEVL_{level}.geojson")

# Which countries' NUTS regions to carry, by level: the feeds that file
# NUTS codes, at the level they file them.
NUTS = {"NUTS3": ("BG", "RO", "FR"), "NUTS2": ("HU", "BE")}

# Feeds whose geocodes are EMMA_IDs under another type name.
ALIASES = {"MK": "NUTS3"}


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


def regions(geocodes, nuts3, nuts2):
    """(key, geometry) for every region to bake, in key order."""
    out = {}
    for f in geocodes["features"]:
        props = f["properties"]
        if props.get("type") != "EMMA_ID":
            continue
        code = props["code"]
        out[code] = f["geometry"]
        alias = ALIASES.get(props.get("country") or code[:2])
        if alias:
            out[f"{alias}/{code}"] = f["geometry"]
    for level, data in (("NUTS3", nuts3), ("NUTS2", nuts2)):
        for f in data["features"]:
            props = f["properties"]
            if props["CNTR_CODE"] in NUTS[level]:
                out[f"{level}/{props['NUTS_ID']}"] = f["geometry"]
    return sorted(out.items())


def pack(items):
    out = bytearray(b"LCMA" + struct.pack("<BH", 2, len(items)))
    npts = 0
    for key, geom in items:
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
        key = key.encode("ascii")
        out += struct.pack("<B", len(key)) + key
        out += struct.pack("<iiii", q(min(lats)), q(max(lats)), q(min(lngs)), q(max(lngs)))
        out += struct.pack("<H", len(packed))
        for rings in packed:
            assert len(rings) < 256
            out += struct.pack("<B", len(rings))
            for pts in rings:
                assert len(pts) < 65536
                out += struct.pack("<H", len(pts))
                out += b"".join(struct.pack("<ii", q(y), q(x)) for x, y in pts)
    return bytes(out), npts


def bake(args):
    geocodes = load(args.geocodes)
    nuts3 = load(args.nuts3 or GISCO.format(level=3))
    nuts2 = load(args.nuts2 or GISCO.format(level=2))
    items = regions(geocodes, nuts3, nuts2)
    raw, npts = pack(items)
    with open(OUT, "wb") as fh:
        fh.write(gzip.compress(raw, 9))
    kinds = collections.Counter(k.partition("/")[0] if "/" in k else "EMMA_ID"
                                for k, _ in items)
    print(f"{len(items)} regions ({', '.join(f'{n} {t}' for t, n in sorted(kinds.items()))}), "
          f"{npts} points, {len(raw)/1e6:.2f} MB raw, "
          f"{os.path.getsize(OUT)/1e6:.2f} MB gzipped -> {os.path.relpath(OUT)}")


def check(args):
    """Pull every live feed and report the geocodes the file cannot place."""
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
    from linecast._meteoalarm_regions import _parse, key_for
    from linecast._weather_sources import _METEOALARM_SLUGS

    with open(args.file, "rb") as fh:
        keys = {key for key, _, _ in _parse(gzip.decompress(fh.read()))}
    unplaced_total = 0
    for country, slug in sorted(_METEOALARM_SLUGS.items()):
        url = f"https://feeds.meteoalarm.org/api/v1/warnings/feeds-{slug}"
        try:
            feed = load(url)
        except Exception as exc:
            print(f"{country} {slug}: fetch failed: {exc}")
            continue
        warnings = feed.get("warnings", [])
        placed, unplaced = collections.Counter(), collections.Counter()
        polygons = 0
        for w in warnings:
            for info in w.get("alert", {}).get("info", []):
                for area in info.get("area", []):
                    if area.get("polygon"):
                        polygons += 1
                    for geocode in area.get("geocode") or []:
                        name, value = geocode.get("valueName"), geocode.get("value")
                        if key_for(name, value) in keys:
                            placed[name] += 1
                        else:
                            unplaced[(name, value)] += 1
        unplaced_total += len(unplaced)
        summary = ", ".join(f"{n} {t}" for t, n in sorted(placed.items()))
        print(f"{country} {slug}: {len(warnings)} warnings, {polygons} polygons, "
              f"placed {summary or 'none'}")
        by_type = collections.defaultdict(list)
        for name, value in sorted(unplaced, key=str):
            by_type[name].append(str(value))
        for name, values in sorted(by_type.items(), key=str):
            shown = values if args.all or len(values) <= 12 else values[:12]
            more = "" if len(shown) == len(values) else f" ... {len(values) - len(shown)} more"
            print(f"    UNPLACED {name} ({len(values)}): {' '.join(shown)}{more}")
    print(f"{unplaced_total} distinct geocodes unplaced")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("bake", help="build the data file")
    p.add_argument("geocodes", help="MeteoAlarm geocodes GeoJSON, path or URL")
    p.add_argument("--nuts3", help="GISCO NUTS 2013 level-3 GeoJSON (default: fetch)")
    p.add_argument("--nuts2", help="GISCO NUTS 2013 level-2 GeoJSON (default: fetch)")
    p.set_defaults(func=bake)
    p = sub.add_parser("check", help="report live geocodes the file cannot place")
    p.add_argument("--file", default=OUT)
    p.add_argument("--all", action="store_true", help="list every unplaced code")
    p.set_defaults(func=check)
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
