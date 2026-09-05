"""Bake the sky: the star catalogue, the constellations, and the Milky Way.

The sky view and the moon view share one set of stars, the Yale Bright
Star Catalogue, 5th revised edition (Hoffleit & Warren, 1991), as served
by the Harvard-Smithsonian Center for Astrophysics. The constellation
figures, the constellation names in many languages, and the star names
are Olaf Frohn's d3-celestial data files (BSD licence), which draw on the
IAU's lists. The Milky Way is the diffuse layer of NASA's Deep Star Maps
2020 (Scientific Visualization Studio, public domain), the unresolved
starlight of the Galaxy drawn from Gaia with the dust lanes in it, as an
equirectangular map in celestial coordinates.

    uv run scripts/build_sky_catalogue.py [--from DIR]

The Milky Way step needs ImageMagick (`magick`) to read the EXR.

The sky cultures are Stellarium's collection (github.com/Stellarium/
stellarium-skycultures), the ones whose text and lines are under a
Creative Commons licence that allows redistribution and derived work
(CC BY or CC BY-SA); the no-derivatives, non-commercial and GPL ones are
left out. Their figures name stars by Hipparcos number, so the bake also
reads the Hipparcos main catalogue (CDS I/239) for positions, and
matches Hipparcos stars to ours by HD number for the star names.

- cultures.json.gz: one record per culture with its id, title, region,
  native language, credits and licence, the constellations (english and
  native names, the IAU code where the culture keeps the IAU figures,
  the label position, and the figure as polylines of [ra, dec] in
  hundredths of a degree) and the star names by index into stars.bin.

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
- milkyway.bin.gz: a 1080×540 byte raster of the Milky Way's brightness
  in celestial coordinates, right ascension 0h at the centre increasing
  to the left (as the sky is seen from inside), declination +90° at the
  top: the NASA layer downsampled, with the sky's own floor taken off
  and a gamma that keeps the dust lanes legible beside the bulge.

`--from DIR` reads the source files from a directory instead of
downloading them. The outputs are committed; this script reruns only if
the sources do.
"""

import gzip
import json
import math
import re
import struct
import sys
import urllib.request
from pathlib import Path

BSC_URL = "http://tdc-www.harvard.edu/catalogs/bsc5.dat.gz"
CELESTIAL = "https://raw.githubusercontent.com/ofrohn/d3-celestial/master/data/"
MILKY_WAY_URL = ("https://svs.gsfc.nasa.gov/vis/a000000/a004800/a004851/"
                 "milkyway_2020_4k.exr")
HIPPARCOS_URL = "https://cdsarc.cds.unistra.fr/ftp/cats/I/239/hip_main.dat"
SKYCULTURES = "https://raw.githubusercontent.com/Stellarium/stellarium-skycultures/master/"

# The cultures shipped, by Stellarium's directory name: every one whose
# text and lines the collection puts under CC BY or CC BY-SA.
CULTURES = (
    "anutan", "belarusian", "blackfoot", "boorong", "bugis", "chinese",
    "chinese_contemporary", "hawaiian_starlines", "indian",
    "japanese_moon_stations", "mandar", "maori", "mongolian", "norse",
    "romanian", "ruelle", "sami", "siberian", "tongan", "tukano",
    "western_SnT", "western_rey",
)
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

MW_W, MW_H = 1080, 540


def fetch(name, src):
    if src is not None:
        return (src / name).read_bytes()
    url = {"bsc5.dat.gz": BSC_URL, "milkyway_2020_4k.exr": MILKY_WAY_URL,
           "hip_main.dat": HIPPARCOS_URL}.get(name, CELESTIAL + name)
    if name.startswith("sc/"):
        culture, _, filename = name[3:].partition(".")
        url = (f"{SKYCULTURES}{culture}/"
               f"{'index.json' if filename == 'json' else 'description.md'}")
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
# The sky's floor and the band's working ceiling, as fractions of the
# layer's full scale: below the floor is the dark sky's own glow and the
# grain of the source, above the ceiling only a few knots in the bulge.
# Between them a gamma under one lifts the faint outer band and keeps
# the dust lanes legible.
MW_FLOOR, MW_CEILING, MW_GAMMA = 0.016, 0.30, 0.6


def smooth(grid):
    """One pass of a 3x3 box over the raster, wrapping in right ascension:
    the layer's grain averaged away, the dust lanes (many cells wide at
    this size) kept."""
    w, h = MW_W, MW_H
    out = [0.0] * (w * h)
    for r in range(h):
        r0, r1 = max(0, r - 1), min(h - 1, r + 1)
        for x in range(w):
            acc = 0.0
            n = 0
            for rr in (r0, r, r1):
                base = rr * w
                for xx in (x - 1, x, x + 1):
                    acc += grid[base + xx % w]
                    n += 1
            out[r * w + x] = acc / n
    return out


def bake_milky_way(src):
    import subprocess
    import tempfile
    exr = fetch("milkyway_2020_4k.exr", src)
    with tempfile.TemporaryDirectory() as tmp:
        exr_path = Path(tmp) / "milkyway.exr"
        pgm_path = Path(tmp) / "milkyway.pgm"
        exr_path.write_bytes(exr)
        # Grey, area-averaged down to the raster's size, as plain-text
        # floating point so there is nothing to decode but numbers.
        subprocess.run(["magick", str(exr_path), "-colorspace", "Gray",
                        "-define", "quantum:format=floating-point", "-depth", "32",
                        "-resize", f"{MW_W}x{MW_H}!", "-compress", "none",
                        str(pgm_path)], check=True)
        tokens = pgm_path.read_text().split()
    assert tokens[0] == "P2" and (int(tokens[1]), int(tokens[2])) == (MW_W, MW_H)
    scale = float(tokens[3])
    values = smooth([int(t) / scale for t in tokens[4:]])
    out = DATA / "milkyway.bin.gz"
    out.write_bytes(gzip.compress(bytes(
        int(round(255.0 * max(0.0, min(1.0, (v - MW_FLOOR) / (MW_CEILING - MW_FLOOR)))
                  ** MW_GAMMA))
        for v in values), 9))
    print(f"wrote {out} ({out.stat().st_size} bytes, {MW_W}x{MW_H})")


# ---------------------------------------------------------------------------
# The sky cultures
# ---------------------------------------------------------------------------
def hipparcos(src):
    """{HIP: (ra_deg, dec_deg, HD or None)} from the main catalogue."""
    out = {}
    for line in fetch("hip_main.dat", src).decode("latin-1").splitlines():
        f = line.split("|")
        try:
            hip, ra, dec = int(f[1]), float(f[8]), float(f[9])
        except (ValueError, IndexError):
            continue
        hd = f[71].strip()
        out[hip] = (ra, dec, int(hd) if hd.isdigit() else None)
    return out


def section(markdown, heading):
    """The text under a level-two heading, on one line, links reduced to
    their text and footnote marks dropped."""
    m = re.search(rf"^## {heading}s?\s*$(.*?)(?=^## |\Z)", markdown, re.S | re.M | re.I)
    if not m:
        return ""
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", m.group(1))
    text = re.sub(r"\[#?\d+\]", "", text)
    return " ".join(text.replace("_", "").split())


def bake_cultures(stars, src):
    hip = hipparcos(src)
    by_hd = {s["hd"]: i for i, s in enumerate(stars) if s["hd"] is not None}
    cultures = []
    for name in CULTURES:
        index = json.loads(fetch(f"sc/{name}.json", src))
        md = fetch(f"sc/{name}.md", src).decode("utf-8")
        constellations = []
        for record in index["constellations"]:
            lines = []
            for line in record.get("lines", []):
                pts = [hip[v] for v in line if isinstance(v, int) and v in hip]
                if len(pts) >= 2:
                    lines.append([hundredths(ra, dec) for ra, dec, _hd in pts])
            if not lines:
                continue
            # The label sits at the figure's centroid on the sphere.
            xs = ys = zs = 0.0
            seen = set()
            for line in record["lines"]:
                for v in line:
                    if isinstance(v, int) and v in hip and v not in seen:
                        seen.add(v)
                        ra, dec = math.radians(hip[v][0]), math.radians(hip[v][1])
                        xs += math.cos(dec) * math.cos(ra)
                        ys += math.cos(dec) * math.sin(ra)
                        zs += math.sin(dec)
            ra = math.degrees(math.atan2(ys, xs)) % 360.0
            dec = math.degrees(math.atan2(zs, math.hypot(xs, ys)))
            common = record.get("common_name", {})
            entry = {"english": common.get("english", ""),
                     "native": common.get("native", ""),
                     "at": hundredths(ra, dec), "lines": lines}
            if record.get("iau"):
                entry["iau"] = record["iau"]
            constellations.append(entry)
        star_names = {}
        for key, entries in index.get("common_names", {}).items():
            try:
                hip_id = int(key.split()[1])
            except (IndexError, ValueError):
                continue
            hd = hip.get(hip_id, (0, 0, None))[2]
            if hd is None or hd not in by_hd or not entries:
                continue
            first = entries[0]
            star_names[str(by_hd[hd])] = [first.get("english", ""), first.get("native", "")]
        cultures.append({
            "id": name, "title": md.split("\n", 1)[0].strip("# ").strip(),
            "region": index.get("region", ""),
            "native_lang": (index.get("native_lang") or "").split("_")[0],
            "fallback": bool(index.get("fallback_to_international_names")),
            "authors": section(md, "Author"), "license": section(md, "License"),
            "constellations": constellations, "star_names": star_names,
        })
        print(f"  {name:24} {len(constellations):3} figures, {len(star_names):4} star names"
              f"  [{cultures[-1]['license'][:40]}]")
    out = DATA / "cultures.json.gz"
    out.write_bytes(gzip.compress(
        json.dumps(cultures, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), 9))
    print(f"wrote {out} ({out.stat().st_size} bytes, {len(cultures)} cultures)")


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
    bake_cultures(stars, src)
    bake_milky_way(src)


if __name__ == "__main__":
    main()
