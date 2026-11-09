"""Bake the vendored lake-depth grid from NOAA NCEI's Great Lakes bathymetry.

NCEI publishes each of the five lakes as a 3 arc-second grid of
metres above its own low water datum (negative is water, positive is
land, -9999 unsounded), public domain:

    https://www.ncei.noaa.gov/products/great-lakes-bathymetry

This reduces them to the hundredth of a degree maps/lake_depth.py
reads: each cell of a region's box is the mean depth of the sounded
water in it, in two-metre steps (0..255 is 0..510 m), and a cell with
no water is 0.  The mean is over the wet samples alone, so a shore
cell reads the nearshore depth rather than a fraction of it; the
bilinear read then shelves it to the land's 0 next door.

    uv run --with numpy scripts/build_lake_depth_grid.py DIR

where DIR holds the five binary-float grids unpacked
({lake}_lld/{lake}_lld.flt beside its .hdr), or let it download them
itself — about 220 MB, which it keeps in DIR for a rerun:

    uv run --with numpy scripts/build_lake_depth_grid.py --fetch DIR

Either way the grid lands at src/linecast/data/lake_depth_great_lakes.png,
which is committed — this script reruns only when NCEI does.
"""

import argparse
import io
import sys
import tarfile
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from polygon_grid import encode_png_gray
from linecast.maps.lake_depth import PITCH, REGIONS, STEP

LAKES = ("superior", "michigan", "huron", "erie", "ontario")
URL = ("https://www.ngdc.noaa.gov/mgg/greatlakes/{lake}/data/binary_float/"
       "{lake}_lld.flt.tar.gz")
OUT_DIR = Path(__file__).resolve().parent.parent / "src/linecast/data"


def fetch(lake, into):
    """Download and unpack one lake's grid into `into`, unless it is there."""
    flt = into / f"{lake}_lld" / f"{lake}_lld.flt"
    if flt.exists():
        return
    url = URL.format(lake=lake)
    print(f"fetching {url}")
    with urllib.request.urlopen(url, timeout=600) as resp:
        blob = resp.read()
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tar:
        members = [m for m in tar.getmembers()
                   if m.isfile() and m.name.split("/")[-1].startswith(f"{lake}_lld.")]
        for m in members:
            target = into / f"{lake}_lld" / m.name.split("/")[-1]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(tar.extractfile(m).read())


def read_grid(lake, into):
    """(depth metres as float32 array with NaN where dry or unsounded,
    (ulx, uly) centre of the top-left cell, cell size)."""
    import numpy as np

    base = into / f"{lake}_lld" / f"{lake}_lld"
    hdr = {}
    for line in base.with_suffix(".hdr").read_text().splitlines():
        parts = line.split()
        if len(parts) == 2:
            hdr[parts[0].upper()] = parts[1]
    ncols, nrows = int(hdr["NCOLS"]), int(hdr["NROWS"])
    if hdr.get("NBITS", "32") != "32" or hdr.get("PIXELTYPE", "FLOAT") != "FLOAT":
        sys.exit(f"{lake}: expected 32-bit float samples")
    order = "<" if hdr.get("BYTEORDER", "I").upper().startswith(("I", "L")) else ">"
    data = np.fromfile(base.with_suffix(".flt"), dtype=f"{order}f4")
    if data.size != ncols * nrows:
        sys.exit(f"{lake}: {data.size} samples for {ncols}x{nrows}")
    data = data.reshape(nrows, ncols).astype(np.float32)
    nodata = float(hdr.get("NODATA", "-9999"))
    depth = np.where((data == nodata) | (data >= 0.0), np.nan, -data)
    return (depth, (float(hdr["ULXMAP"]), float(hdr["ULYMAP"])),
            float(hdr["XDIM"]))


def bake(region_bbox, grids):
    """The region's cells, row-major bytes, from the lakes' grids."""
    import numpy as np

    minlon, minlat, maxlon, maxlat = region_bbox
    w = round((maxlon - minlon) / PITCH)
    h = round((maxlat - minlat) / PITCH)
    sums = np.zeros(w * h, dtype=np.float64)
    counts = np.zeros(w * h, dtype=np.int64)
    for depth, (ulx, uly), cell in grids:
        rows, cols = np.nonzero(~np.isnan(depth))
        lon = ulx + cols * cell
        lat = uly - rows * cell
        tx = np.floor((lon - minlon) / PITCH).astype(np.int64)
        ty = np.floor((maxlat - lat) / PITCH).astype(np.int64)
        keep = (tx >= 0) & (tx < w) & (ty >= 0) & (ty < h)
        idx = ty[keep] * w + tx[keep]
        sums += np.bincount(idx, weights=depth[rows[keep], cols[keep]],
                            minlength=w * h)
        counts += np.bincount(idx, minlength=w * h)
    mean = np.where(counts > 0, sums / np.maximum(counts, 1), 0.0)
    levels = np.clip(np.rint(mean / STEP), 0, 255).astype(np.uint8)
    # a sounded cell shallower than a step still reads as water
    levels[(counts > 0) & (levels == 0)] = 1
    return w, h, levels.tobytes(), float(mean.max()), int((counts > 0).sum())


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("dir", help="where the unpacked NCEI grids are, or go")
    ap.add_argument("--fetch", action="store_true",
                    help="download any lake's grid that is not in DIR")
    args = ap.parse_args()
    into = Path(args.dir)
    into.mkdir(parents=True, exist_ok=True)
    if args.fetch:
        for lake in LAKES:
            fetch(lake, into)
    grids = [read_grid(lake, into) for lake in LAKES]
    for stem, bbox in REGIONS:
        w, h, cells, deepest, wet = bake(bbox, grids)
        out = OUT_DIR / f"{stem}.png"
        out.write_bytes(encode_png_gray(w, h, cells))
        print(f"{stem}: {w}x{h}, {wet} wet cells, deepest {deepest:.0f} m "
              f"→ {out.name}, {out.stat().st_size / 1e3:.0f} KB")


if __name__ == "__main__":
    main()
