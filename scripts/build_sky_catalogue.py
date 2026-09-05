"""Bake the sky: the star catalogue, the constellations, and the Milky Way.

The sky view and the moon view share one set of stars, the Yale Bright
Star Catalogue, 5th revised edition (Hoffleit & Warren, 1991), as served
by the Harvard-Smithsonian Center for Astrophysics. The constellation
figures, the constellation names in many languages, the star names, and
the Milky Way's outline are Olaf Frohn's d3-celestial data files (BSD
licence), which draw on the IAU's lists.

    uv run scripts/build_sky_catalogue.py [--from DIR]

Writes three files under src/linecast/data/:

- stars.bin: one six-byte record per star to visual magnitude 6.5,
  brightest first — right ascension and declination (J2000) in hundredths
  of a degree as little-endian uint16 and int16, the magnitude in tenths
  as int8, and the B−V colour index in fiftieths as int8.
- sky.json.gz: {"names": [[index, name, designation], …] for every star
  with a proper name or a Bayer or Flamsteed designation, indexed into
  stars.bin; "constellations": one record per constellation with its IAU
  abbreviation, Latin name and genitive, label position, names in the
  languages linecast speaks where they differ from the Latin, and its
  figure as polylines of [ra, dec] in hundredths of a degree}.
- milkyway.bin.gz: a 720×360 byte raster of the Milky Way's brightness
  in galactic coordinates — longitude 180° at the left edge running to
  −180°, latitude +90° at the top — from the five nested outline
  contours, softened so a terminal cell reads as glow rather than as a
  step.

`--from DIR` reads the source files from a directory instead of
downloading them. The outputs are committed; this script reruns only if
the sources do.
"""

import gzip
import json
import math
import struct
import sys
import urllib.request
from pathlib import Path

BSC_URL = "http://tdc-www.harvard.edu/catalogs/bsc5.dat.gz"
CELESTIAL = "https://raw.githubusercontent.com/ofrohn/d3-celestial/master/data/"
LIMIT = 6.5
DATA = Path(__file__).resolve().parent.parent / "src/linecast/data"

# The languages linecast speaks that the constellation data names.
OUR_LANGS = ("fr", "es", "de", "it", "fi", "ja", "ko", "zh")

GREEK = {
    "Alp": "α", "Bet": "β", "Gam": "γ", "Del": "δ", "Eps": "ε", "Zet": "ζ",
    "Eta": "η", "The": "θ", "Iot": "ι", "Kap": "κ", "Lam": "λ", "Mu": "μ",
    "Nu": "ν", "Xi": "ξ", "Omi": "ο", "Pi": "π", "Rho": "ρ", "Sig": "σ",
    "Tau": "τ", "Ups": "υ", "Phi": "φ", "Chi": "χ", "Psi": "ψ", "Ome": "ω",
}
SUPERSCRIPT = {"1": "¹", "2": "²", "3": "³", "4": "⁴", "5": "⁵", "6": "⁶",
               "7": "⁷", "8": "⁸", "9": "⁹"}

# Equatorial (J2000) to galactic: the rows are the galactic x, y, z axes
# in equatorial coordinates (Hipparcos, vol. 1, §1.5.3).
EQ_TO_GAL = (
    (-0.0548755604, -0.8734370902, -0.4838350155),
    (+0.4941094279, -0.4448296300, +0.7469822445),
    (-0.8676661490, -0.1980763734, +0.4559837762),
)
MW_W, MW_H = 720, 360


def fetch(name, src):
    if src is not None:
        return (src / name).read_bytes()
    url = BSC_URL if name == "bsc5.dat.gz" else CELESTIAL + name
    print(f"fetching {url}")
    return urllib.request.urlopen(url).read()


# ---------------------------------------------------------------------------
# Stars
# ---------------------------------------------------------------------------
def parse_star(line):
    """A star from a catalogue line, or None if it has no position.

    Fixed columns (1-based) per the catalogue's ReadMe: HR 1-4, Name 5-14
    (Flamsteed 5-7, Bayer 8-10, superscript 11, constellation 12-14),
    HD 26-31, RAh 76-77, RAm 78-79, RAs 80-83, DE- 84, DEd 85-86, DEm
    87-88, DEs 89-90, Vmag 103-107, B-V 110-114. A few entries (novae,
    clusters) have no position.
    """
    try:
        hr = int(line[0:4])
        ra = (int(line[75:77]) + int(line[77:79]) / 60.0
              + float(line[79:83]) / 3600.0) * 15.0
        dec = (int(line[84:86]) + int(line[86:88]) / 60.0
               + int(line[88:90]) / 3600.0)
        if line[83] == "-":
            dec = -dec
        vmag = float(line[102:107])
    except ValueError:
        return None
    try:
        bv = float(line[109:114])
    except ValueError:
        bv = 0.0
    try:
        hd = int(line[25:31])
    except ValueError:
        hd = None
    flam = line[4:7].strip()
    bayer = GREEK.get(line[7:10].strip())
    sup = SUPERSCRIPT.get(line[10], "")
    con = line[11:14].strip()
    desig = ""
    if con and bayer:
        desig = f"{bayer}{sup} {con}"
    elif con and flam:
        desig = f"{flam} {con}"
    return dict(hr=hr, ra=ra, dec=dec, vmag=vmag, bv=bv, hd=hd, desig=desig)


def bake_stars(src):
    raw = gzip.decompress(fetch("bsc5.dat.gz", src))
    stars = [s for s in map(parse_star, raw.decode("latin-1").splitlines())
             if s is not None and s["vmag"] <= LIMIT]
    stars.sort(key=lambda s: (s["vmag"], s["hr"]))
    out = DATA / "stars.bin"
    out.write_bytes(b"".join(
        struct.pack("<Hhbb", round(s["ra"] * 100) % 36000, round(s["dec"] * 100),
                    round(s["vmag"] * 10),
                    max(-128, min(127, round(s["bv"] * 50))))
        for s in stars))
    print(f"wrote {out} ({out.stat().st_size} bytes, {len(stars)} stars to {LIMIT})")
    return stars


def bake_names(stars, src):
    """[[index, proper name, designation], …] for the stars that have either."""
    by_hd = {}
    for entry in json.loads(fetch("starnames.json", src)).values():
        hd = entry.get("hd", "").replace("HD", "").replace(" ", "").strip()
        if hd.isdigit() and entry.get("name"):
            by_hd[int(hd)] = entry["name"]
    names = []
    for i, s in enumerate(stars):
        proper = by_hd.get(s["hd"], "") if s["hd"] is not None else ""
        if proper or s["desig"]:
            names.append([i, proper, s["desig"]])
    print(f"  {sum(1 for n in names if n[1])} named stars, "
          f"{len(names)} with a designation")
    return names


# ---------------------------------------------------------------------------
# Constellations
# ---------------------------------------------------------------------------
def hundredths(ra, dec):
    return [round(ra * 100) % 36000, round(dec * 100)]


def bake_constellations(src):
    lines = {f["id"]: f["geometry"]["coordinates"]
             for f in json.loads(fetch("constellations.lines.json", src))["features"]}
    records = []
    for f in json.loads(fetch("constellations.json", src))["features"]:
        p = f["properties"]
        # Serpens is one constellation in two parts; the data carries the
        # parts as Ser1 and Ser2 with one name, and both are kept.
        latin = p["la"] or p["name"]
        names = {lang: p[lang] for lang in OUR_LANGS
                 if p.get(lang) and p[lang] != latin}
        ra, dec = f["geometry"]["coordinates"]
        records.append({
            "id": f["id"], "name": latin, "gen": p["gen"],
            "at": hundredths(ra, dec), "names": names,
            "lines": [[hundredths(ra, dec) for ra, dec in line]
                      for line in lines.get(f["id"], [])],
        })
    print(f"  {len(records)} constellations, "
          f"{sum(len(r['lines']) for r in records)} figure lines")
    return records


# ---------------------------------------------------------------------------
# The Milky Way
# ---------------------------------------------------------------------------
def to_galactic(ra_deg, dec_deg):
    """Galactic longitude and latitude in degrees, l in (-180, 180]."""
    ra, dec = math.radians(ra_deg), math.radians(dec_deg)
    v = (math.cos(dec) * math.cos(ra), math.cos(dec) * math.sin(ra), math.sin(dec))
    x, y, z = (sum(r[i] * v[i] for i in range(3)) for r in EQ_TO_GAL)
    lon = math.degrees(math.atan2(y, x))
    return lon, math.degrees(math.asin(max(-1.0, min(1.0, z))))


def fill_feature(grid, rings):
    """Add one to every raster cell inside the spherical polygon *rings*.

    The test is the even-odd rule along the meridian from the cell to the
    north galactic pole, which is known to lie outside every outline: a
    cell is inside when an odd number of ring edges cross its longitude
    above it. Done column by column, that is the classic scanline fill
    turned on its side, exact on the sphere because a galactic meridian
    is the ray the rule wants. Edges that cross the ±180° seam are split
    there.
    """
    crossings = [[] for _ in range(MW_W)]
    for ring in rings:
        pts = [to_galactic(ra, dec) for ra, dec in ring]
        for (l0, b0), (l1, b1) in zip(pts, pts[1:] + pts[:1]):
            if l1 - l0 > 180.0:
                l1 -= 360.0
            elif l0 - l1 > 180.0:
                l1 += 360.0
            if l0 == l1:
                continue
            lo, hi = sorted((l0, l1))
            # Columns whose centre longitude lies within the edge's span.
            # Column x spans longitude 180 - x/2 down to 180 - (x+1)/2.
            for x in range(MW_W):
                lon = 180.0 - (x + 0.5) * 360.0 / MW_W
                for shift in (0.0, -360.0, 360.0):
                    lx = lon + shift
                    if lo <= lx < hi:
                        crossings[x].append(b0 + (b1 - b0) * (lx - l0) / (l1 - l0))
    for x, col in enumerate(crossings):
        col.sort(reverse=True)
        for top, bottom in zip(col[0::2], col[1::2]):
            # Rows whose centre latitude falls between the two crossings.
            r0 = max(0, int(math.floor((90.0 - top) * MW_H / 180.0)))
            r1 = min(MW_H, int(math.ceil((90.0 - bottom) * MW_H / 180.0)))
            for row in range(r0, r1):
                lat = 90.0 - (row + 0.5) * 180.0 / MW_H
                if bottom <= lat < top:
                    grid[row][x] += 1


def soften(grid, passes=3, radius=3):
    """Box-blur the raster, wrapping in longitude, so the contour steps
    read as a glow. Three passes of a box are close to a Gaussian."""
    for _ in range(passes):
        # Along rows (longitude, wrapping).
        out = [[0.0] * MW_W for _ in range(MW_H)]
        span = 2 * radius + 1
        for r in range(MW_H):
            row = grid[r]
            acc = sum(row[(x) % MW_W] for x in range(-radius, radius + 1))
            for x in range(MW_W):
                out[r][x] = acc / span
                acc += row[(x + radius + 1) % MW_W] - row[(x - radius) % MW_W]
        grid = out
        # Down columns (latitude, clamped).
        out = [[0.0] * MW_W for _ in range(MW_H)]
        for x in range(MW_W):
            for r in range(MW_H):
                lo, hi = max(0, r - radius), min(MW_H - 1, r + radius)
                out[r][x] = sum(grid[k][x] for k in range(lo, hi + 1)) / (hi - lo + 1)
        grid = out
    return grid


def bake_milky_way(src):
    grid = [[0] * MW_W for _ in range(MW_H)]
    for f in json.loads(fetch("mw.json", src))["features"]:
        for polygon in f["geometry"]["coordinates"]:
            fill_feature(grid, polygon)
    peak = max(max(row) for row in grid)
    print(f"  Milky Way contours nest {peak} deep")
    grid = soften(grid)
    out = DATA / "milkyway.bin.gz"
    out.write_bytes(gzip.compress(bytes(
        min(255, int(round(v * 255.0 / peak))) for row in grid for v in row), 9))
    print(f"wrote {out} ({out.stat().st_size} bytes, {MW_W}x{MW_H})")


def main():
    src = None
    if len(sys.argv) == 3 and sys.argv[1] == "--from":
        src = Path(sys.argv[2])
    stars = bake_stars(src)
    sky = {"names": bake_names(stars, src),
           "constellations": bake_constellations(src)}
    out = DATA / "sky.json.gz"
    out.write_bytes(gzip.compress(
        json.dumps(sky, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), 9))
    print(f"wrote {out} ({out.stat().st_size} bytes)")
    bake_milky_way(src)


if __name__ == "__main__":
    main()
