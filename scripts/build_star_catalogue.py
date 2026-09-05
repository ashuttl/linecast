"""Bake the moon view's star catalogue from the Yale Bright Star Catalogue.

The sky around the lunar disc is the real one: the Bright Star
Catalogue, 5th revised edition (Hoffleit & Warren, 1991), as served by
the Harvard-Smithsonian Center for Astrophysics.

    uv run scripts/build_star_catalogue.py

Writes src/linecast/data/stars.bin: one five-byte record per star to
visual magnitude 5.5, brightest first — right ascension and declination
(J2000) in hundredths of a degree as little-endian uint16 and int16,
then the magnitude in tenths as int8. The file is committed; this
script reruns only if the source does.
"""

import gzip
import struct
import urllib.request
from pathlib import Path

SOURCE = "http://tdc-www.harvard.edu/catalogs/bsc5.dat.gz"
LIMIT = 5.5
OUT = Path(__file__).resolve().parent.parent / "src/linecast/data/stars.bin"


def parse(line):
    """(ra_deg, dec_deg, vmag) from a catalogue line, or None if incomplete."""
    # Fixed columns (1-based) per the catalogue's ReadMe: RAh 76-77,
    # RAm 78-79, RAs 80-83, DE- 84, DEd 85-86, DEm 87-88, DEs 89-90,
    # Vmag 103-107. A few entries (novae, clusters) have no position.
    try:
        ra = (int(line[75:77]) + int(line[77:79]) / 60.0
              + float(line[79:83]) / 3600.0) * 15.0
        dec = (int(line[84:86]) + int(line[86:88]) / 60.0
               + int(line[88:90]) / 3600.0)
        if line[83] == "-":
            dec = -dec
        vmag = float(line[102:107])
    except ValueError:
        return None
    return ra, dec, vmag


def main():
    raw = gzip.decompress(urllib.request.urlopen(SOURCE).read())
    stars = [s for s in map(parse, raw.decode("latin-1").splitlines())
             if s is not None and s[2] <= LIMIT]
    stars.sort(key=lambda s: s[2])
    OUT.write_bytes(b"".join(
        struct.pack("<Hhb", round(ra * 100) % 36000, round(dec * 100),
                    round(vmag * 10))
        for ra, dec, vmag in stars))
    print(f"wrote {OUT} ({OUT.stat().st_size} bytes, {len(stars)} stars to {LIMIT})")
    for ra, dec, vmag in stars[:5]:
        print(f"  {ra:8.3f} {dec:+8.3f} {vmag:5.2f}")


if __name__ == "__main__":
    main()
