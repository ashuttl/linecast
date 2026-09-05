"""Bake MeteoAlarm's warning regions into the vendored data file.

Most MeteoAlarm feeds carry no polygon on a warning, only a geocode
naming a county, district, or province. This script turns the published
geometry for those codes into a small binary that
linecast._meteoalarm_regions reads at runtime to answer "which regions
is this point in?" -- and so which of a country's several hundred
warnings apply here.

Two kinds of geocode are placed:

  EMMA_ID   MeteoAlarm's own regions, from the geocodes GeoJSON its
            Redistribution Hub page links, kept in the meteoalarm-pm-group
            "documents" project on GitLab under a dated name
            (MeteoAlarm_Geocodes_2026_07_31.json; CC BY 4.0, EUMETNET).
            Keyed by bare code: PL3001. A new edition drops the codes
            feeds no longer file, so a bake from it can lose regions
            as well as gain them.
  NUTS2/3   Eurostat's statistical regions, for the feeds that file
            those instead (Bulgaria, Romania, and France at level 3;
            Hungary and Belgium at level 2), from GISCO's 2013 edition
            -- France and Hungary still file 2013 codes -- at 1:3M,
            which holds a departement's edge within a few hundred
            metres for half the bytes of the 1:1M file. Keyed by type
            and code, NUTS3/FR101, so a NUTS code and an EMMA_ID that
            share a spelling can never cross. © EuroGeographics for the
            administrative boundaries.

  CISORP    Czechia's municipalities with extended powers (ORP), 206 of
            them, finer than any region MeteoAlarm publishes. Geometry
            from the ČÚZK RÚIAN map service, which serves it in WGS84;
            codes from the Czech Statistical Office's CISORP list
            (číselník 65), which carries the RÚIAN code each maps to.
            Keyed CISORP/2101. Both open data.

Some feeds spell a code differently from the source that publishes the
ground. North Macedonia files its EMMA_IDs under the NUTS3 label, so
those are written a second time under NUTS3/ (ALIASES). ČHMÚ's Czech
feed files Prague as CISORP 1100 where the statistical office says
1000, so Prague is written under both. (It also files every ORP a
second time as an EMMA_ID of CZ0 + CISORP; MeteoAlarm's list carries
those since its 2026 editions, so both codes on an area now place it.)

    python3 scripts/build_meteoalarm_regions.py bake \
        "https://gitlab.com/meteoalarm-pm-group/documents/-/raw/master/MeteoAlarm_Geocodes_2026_07_31.json"

fetches the NUTS files from GISCO and the Czech ORP files from ČÚZK and
ČSÚ; pass --nuts3, --nuts2, --orp, and --cisorp to use local copies.
Then

    uv run python scripts/build_meteoalarm_regions.py check

pulls every live feed and prints each warning area the baked file
cannot place by any of its geocodes, so a feed that changes its codes
or its NUTS edition is caught here and not by a user.

Output: src/linecast/data/meteoalarm_regions.bin.gz

Format (all little-endian, coordinates in 1e-5 degrees):

    b"LCMA" u8 version=2  u16 nregions
    per region:  u8 len, key (ascii)
                 i32 lat_min lat_max lng_min lng_max      (bounding box)
                 u16 npolys
    per polygon: u8 nrings                                (outer, then holes)
    per ring:    u16 npts, then npts x (i32 lat, i32 lng)

Version 2 differs from 1 only in what a key may be: a bare EMMA_ID, or
a geocode type and value joined by "/" (NUTS3/FR101, CISORP/2101).

Rings are simplified with Douglas-Peucker at EPS degrees; a warning
region's edge two hundred metres off costs nobody an alert.
"""

import argparse
import collections
import csv
import gzip
import io
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

RUIAN_ORP = ("https://ags.cuzk.cz/arcgis/rest/services/RUIAN/"
             "Prohlizeci_sluzba_nad_daty_RUIAN/MapServer/14/query"
             "?where=1%3D1&outFields=kod,nazev&outSR=4326&geometryPrecision=6&f=geojson")
CISORP = ("https://apl.czso.cz/iSMS/do_cis_export"
          "?kodcis=65&typdat=0&cisjaz=203&format=2&separator=%2C")

# ČHMÚ's feed spells Prague's CISORP 1100; the statistical office's list
# says 1000.
CISORP_FEED_SPELLINGS = {"1000": ("1000", "1100")}


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


def read(source):
    if source.startswith("http://") or source.startswith("https://"):
        req = urllib.request.Request(source, headers={"User-Agent": "linecast-build"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            return resp.read().decode("utf-8")
    with open(source, encoding="utf-8") as fh:
        return fh.read()


def load(source):
    return json.loads(read(source))


def load_csv(source):
    return list(csv.DictReader(io.StringIO(read(source))))


def q(deg):
    return round(deg * 1e5)


def regions(geocodes, nuts3, nuts2, orp, cisorp):
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
    code_by_ruian = {row["kod_ruian"]: row["chodnota"] for row in cisorp}
    for f in orp["features"]:
        code = code_by_ruian[str(f["properties"]["kod"])]
        for spelling in CISORP_FEED_SPELLINGS.get(code, (code,)):
            out[f"CISORP/{spelling}"] = f["geometry"]
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
    orp = load(args.orp or RUIAN_ORP)
    cisorp = load_csv(args.cisorp or CISORP)
    items = regions(geocodes, nuts3, nuts2, orp, cisorp)
    raw, npts = pack(items)
    with open(OUT, "wb") as fh:
        fh.write(gzip.compress(raw, 9))
    kinds = collections.Counter(k.partition("/")[0] if "/" in k else "EMMA_ID"
                                for k, _ in items)
    print(f"{len(items)} regions ({', '.join(f'{n} {t}' for t, n in sorted(kinds.items()))}), "
          f"{npts} points, {len(raw)/1e6:.2f} MB raw, "
          f"{os.path.getsize(OUT)/1e6:.2f} MB gzipped -> {os.path.relpath(OUT)}")


def check(args):
    """Pull every live feed and report the areas the file cannot place.

    An area is placed when it carries a polygon or any geocode the
    file knows. The Czech feed files each ORP twice, as a CISORP the
    file knows and as an EMMA_ID it does not; that area is placed.
    """
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
        for w in warnings:
            for info in w.get("alert", {}).get("info", []):
                for area in info.get("area", []):
                    geocodes = [(g.get("valueName"), g.get("value"))
                                for g in area.get("geocode") or []]
                    hit = sorted({t for t, v in geocodes if key_for(t, v) in keys})
                    if area.get("polygon"):
                        placed["polygon"] += 1
                    elif hit:
                        placed["+".join(hit)] += 1
                    else:
                        unplaced[" ".join(f"{t}/{v}" for t, v in geocodes)
                                 or "(no geocode)"] += 1
        unplaced_total += sum(unplaced.values())
        summary = ", ".join(f"{n} by {t}" for t, n in sorted(placed.items()))
        print(f"{country} {slug}: {len(warnings)} warnings, "
              f"{sum(placed.values())} areas placed"
              f"{': ' + summary if summary else ''}")
        if unplaced:
            shown = sorted(unplaced.items())
            more = ""
            if not args.all and len(shown) > 12:
                shown, more = shown[:12], f"    ... {len(unplaced) - 12} more"
            print(f"    UNPLACED {sum(unplaced.values())} areas:")
            for geocodes, n in shown:
                print(f"    {n:4d} x [{geocodes}]")
            if more:
                print(more)
    print(f"{unplaced_total} areas unplaced")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("bake", help="build the data file")
    p.add_argument("geocodes", help="MeteoAlarm geocodes GeoJSON, path or URL")
    p.add_argument("--nuts3", help="GISCO NUTS 2013 level-3 GeoJSON (default: fetch)")
    p.add_argument("--nuts2", help="GISCO NUTS 2013 level-2 GeoJSON (default: fetch)")
    p.add_argument("--orp", help="RÚIAN ORP GeoJSON in WGS84 (default: fetch)")
    p.add_argument("--cisorp", help="ČSÚ CISORP list, CSV (default: fetch)")
    p.set_defaults(func=bake)
    p = sub.add_parser("check", help="report live geocodes the file cannot place")
    p.add_argument("--file", default=OUT)
    p.add_argument("--all", action="store_true", help="list every unplaced area")
    p.set_defaults(func=check)
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
