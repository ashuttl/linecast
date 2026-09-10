"""Bake the zoomed sky's HYG v4.1 supplement (David Nash, CC BY-SA 4.0).

    python scripts/build_deep_stars.py --from /path/to/sources

The directory must contain hygdata_v41.csv and bsc5.dat.gz. Download from:
https://raw.githubusercontent.com/astronexus/HYG-Database/main/hyg/CURRENT/hygdata_v41.csv
http://tdc-www.harvard.edu/catalogs/bsc5.dat.gz

Keep Yale's existing stars and indices. Exclude their HR/HD matches from
HYG and retain only visual magnitudes >6.5 through 12.0. HYG's RA is in
hours; its coordinates are epoch/equinox J2000. Colour defaults to neutral
when unavailable. No proper-motion extrapolation is made at runtime.

The gzip payload starts with a uint32 JSON-header length and that header
(offsets into records, magnitude histogram, source hashes). Records are
<IiBbI: RA/Dec in millidegrees, V in tenths, B-V in fiftieths, HIP number
or HYG id with bit 31 set. The 648 ten-degree RA/Dec bins each sort by
magnitude. The runtime decodes only bins intersecting the view.
"""

import argparse
import csv
import gzip
import hashlib
import json
import math
import struct
from pathlib import Path

from build_sky_catalogue import LIMIT, parse_star

DATA = Path(__file__).resolve().parent.parent / "src/linecast/data"
RECORD = struct.Struct("<IiBbI")


def select_star(row, hrs, hds):
    """A quantized HYG record, excluding the Sun and existing Yale stars."""
    if row["hr"] in hrs or row["hd"] in hds:
        return None
    ra, dec, mag = float(row["ra"]) * 15.0, float(row["dec"]), float(row["mag"])
    bv = float(row["ci"]) if row["ci"] else 0.0
    if not all(map(math.isfinite, (ra, dec, mag, bv))):
        return None
    if not (0 <= ra <= 360 and -90 <= dec <= 90 and LIMIT < mag <= 12.0):
        return None
    # Keep the quantized faint catalogue strictly after Yale's 6.5 limit.
    if round(mag * 10) <= round(LIMIT * 10):
        return None
    ident = int(row["hip"]) if row["hip"] else int(row["id"]) | (1 << 31)
    return (round(ra * 1000) % 360000, round(dec * 1000), round(mag * 10),
            max(-128, min(127, round(bv * 50))), ident)


def bake(src, out):
    yale = [s for s in map(parse_star, gzip.decompress(
        (src / "bsc5.dat.gz").read_bytes()).decode("latin-1").splitlines())
        if s is not None and s["vmag"] <= LIMIT]
    hrs = {str(s["hr"]) for s in yale}
    hds = {str(s["hd"]) for s in yale if s["hd"] is not None}
    bins = [[] for _ in range(648)]
    hist = [0] * 121
    with (src / "hygdata_v41.csv").open(newline="") as stream:
        for row in csv.DictReader(stream):
            star = select_star(row, hrs, hds)
            if star is None:
                continue
            ra, dec, mag, _bv, _ident = star
            zone = min(17, (dec + 90000) // 10000) * 36 + ra // 10000
            bins[zone].append(star)
            hist[mag] += 1
    offsets = [0]
    records = bytearray()
    for zone in bins:
        zone.sort(key=lambda s: (s[2], s[4]))
        records.extend(b"".join(RECORD.pack(*s) for s in zone))
        offsets.append(offsets[-1] + len(zone))
    header = json.dumps({"version": 1, "offsets": offsets, "histogram": hist,
                         "sources": {name: hashlib.sha256((src / name).read_bytes()).hexdigest()
                                     for name in ("hygdata_v41.csv", "bsc5.dat.gz")}},
                        separators=(",", ":")).encode()
    out.write_bytes(gzip.compress(struct.pack("<I", len(header)) + header + records,
                                  compresslevel=9, mtime=0))
    print(f"{offsets[-1]} additional stars; {len(yale) + offsets[-1]} total; "
          f"{out.stat().st_size:,} bytes")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from", dest="src", type=Path, required=True)
    args = parser.parse_args()
    bake(args.src, DATA / "stars-deep.bin.gz")
