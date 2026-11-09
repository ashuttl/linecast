"""Bake the vendored lake-depth grids maps/lake_depth.py reads.

Two public-domain NOAA NCEI sources, one recipe each:

- The Great Lakes, from NCEI's 3 arc-second grid of each lake: metres
  above its own low water datum (negative is water, positive land,
  -9999 unsounded).  https://www.ncei.noaa.gov/products/great-lakes-bathymetry
- Lake Baikal, from ETOPO 2022 at 15 arc-seconds, which carries the
  GEBCO soundings of the largest lakes as the bed's elevation.  The
  depth is the lake's surface level less the bed, over the cells that
  are lower than the surface and joined to the lake, so a valley
  below lake level across the shore is not read as water.
  https://www.ncei.noaa.gov/products/etopo-global-relief-model

Each region in lake_depth.REGIONS becomes one PNG at a hundredth of a
degree: a cell is the mean depth of the sounded water in it, in the
region's metres per grey level, and a cell with no water is 0.  The
mean is over the wet samples alone, so a shore cell reads the
nearshore depth rather than a fraction of it; the bilinear read then
shelves it to the land's 0 next door.

    uv run --with numpy --with tifffile --with imagecodecs scripts/build_lake_depth_grid.py DIR

where DIR holds the sources unpacked ({lake}_lld/{lake}_lld.flt beside
its .hdr, and the ETOPO tiles as named on the server), or let it
download what is missing — about 300 MB, kept in DIR for a rerun:

    uv run --with numpy --with tifffile --with imagecodecs \
        scripts/build_lake_depth_grid.py --fetch DIR

The grids land in src/linecast/data and are committed; this script
reruns only when a source does.
"""

import argparse
import io
import sys
import tarfile
import urllib.request
from collections import deque
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from polygon_grid import encode_png_gray
from linecast.maps.lake_depth import PITCH, REGIONS

OUT_DIR = Path(__file__).resolve().parent.parent / "src/linecast/data"

NCEI_LAKES = ("superior", "michigan", "huron", "erie", "ontario")
NCEI_URL = ("https://www.ngdc.noaa.gov/mgg/greatlakes/{lake}/data/binary_float/"
            "{lake}_lld.flt.tar.gz")
ETOPO_URL = ("https://www.ngdc.noaa.gov/mgg/global/relief/ETOPO2022/data/15s/"
             "15s_surface_elev_gtif/{name}")
ETOPO_TILE = "ETOPO_2022_v1_15s_{tile}_surface.tif"

# what each region is baked from: the NCEI lakes, or ETOPO tiles with
# the lake's surface level and a point in the lake to grow it from
RECIPES = {
    "lake_depth_great_lakes": ("ncei", NCEI_LAKES),
    "lake_depth_baikal": ("etopo", {"tiles": ("N60E090", "N60E105"),
                                    "surface": 456.0,
                                    "seed": (53.5, 108.0)}),
}


# ---------------------------------------------------------------------------
# sources
# ---------------------------------------------------------------------------


def fetch_ncei(lake, into):
    """Download and unpack one lake's grid into `into`, unless it is there."""
    if (into / f"{lake}_lld" / f"{lake}_lld.flt").exists():
        return
    url = NCEI_URL.format(lake=lake)
    print(f"fetching {url}")
    with urllib.request.urlopen(url, timeout=600) as resp:
        blob = resp.read()
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tar:
        for m in tar.getmembers():
            name = m.name.split("/")[-1]
            if m.isfile() and name.startswith(f"{lake}_lld."):
                target = into / f"{lake}_lld" / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(tar.extractfile(m).read())


def fetch_etopo(tile, into):
    """Download one ETOPO 2022 surface tile into `into`, unless it is there."""
    name = ETOPO_TILE.format(tile=tile)
    if (into / name).exists():
        return
    url = ETOPO_URL.format(name=name)
    print(f"fetching {url}")
    with urllib.request.urlopen(url, timeout=600) as resp:
        (into / name).write_bytes(resp.read())


def read_ncei(lake, into):
    """(depth metres, NaN where dry or unsounded; (ulx, uly), the centre
    of the top-left cell; cell size) from one lake's binary-float grid."""
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
    return depth, (float(hdr["ULXMAP"]), float(hdr["ULYMAP"])), float(hdr["XDIM"])


def read_etopo(tile, into, surface):
    """(depth metres below `surface`, NaN where not below it; (ulx, uly);
    cell size) from one ETOPO tile, georeferenced from its own tags."""
    import numpy as np
    import tifffile

    with tifffile.TiffFile(into / ETOPO_TILE.format(tile=tile)) as tif:
        page = tif.pages[0]
        elev = page.asarray().astype(np.float32)
        scale = page.tags["ModelPixelScaleTag"].value
        tie = page.tags["ModelTiepointTag"].value
    # the tiepoint is the top-left corner of the top-left pixel, in
    # the raster's (i, j) then the world's (x, y); the centre is half
    # a pixel in
    cell = float(scale[0])
    if abs(float(scale[1]) - cell) > 1e-9:
        sys.exit(f"{tile}: pixels are not square")
    ulx = float(tie[3]) + (0.5 - float(tie[0])) * cell
    uly = float(tie[4]) - (0.5 - float(tie[1])) * cell
    depth = np.where(elev < surface - 1.0, surface - elev, np.nan)
    return depth, (ulx, uly), cell


# ---------------------------------------------------------------------------
# baking
# ---------------------------------------------------------------------------


def accumulate(region_bbox, grids):
    """(w, h, sum of depth per cell, count of wet samples per cell)."""
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
    return w, h, sums, counts


def joined_to(counts, w, h, region_bbox, seed):
    """The wet cells reachable from the cell under `seed`, 4-connected."""
    import numpy as np

    minlon, _minlat, _maxlon, maxlat = region_bbox
    sx = int((seed[1] - minlon) / PITCH)
    sy = int((maxlat - seed[0]) / PITCH)
    if not (0 <= sx < w and 0 <= sy < h and counts[sy * w + sx]):
        sys.exit(f"the seed {seed} is not on sounded water")
    seen = np.zeros(w * h, dtype=bool)
    seen[sy * w + sx] = True
    queue = deque([(sx, sy)])
    while queue:
        x, y = queue.popleft()
        for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
            if 0 <= nx < w and 0 <= ny < h:
                i = ny * w + nx
                if counts[i] and not seen[i]:
                    seen[i] = True
                    queue.append((nx, ny))
    return seen


def levels_for(sums, counts, step):
    """Grey levels from the per-cell means: 0 is no water, and a sounded
    cell shallower than a step still reads as water."""
    import numpy as np

    mean = np.where(counts > 0, sums / np.maximum(counts, 1), 0.0)
    if mean.max() > 255 * step:
        sys.exit(f"deepest cell {mean.max():.0f} m overflows {step} m steps")
    levels = np.clip(np.rint(mean / step), 0, 255).astype(np.uint8)
    levels[(counts > 0) & (levels == 0)] = 1
    return levels, float(mean.max()), int((counts > 0).sum())


def bake(stem, bbox, step, into, fetch):
    kind, spec = RECIPES[stem]
    if kind == "ncei":
        if fetch:
            for lake in spec:
                fetch_ncei(lake, into)
        grids = [read_ncei(lake, into) for lake in spec]
        w, h, sums, counts = accumulate(bbox, grids)
    else:
        if fetch:
            for tile in spec["tiles"]:
                fetch_etopo(tile, into)
        grids = [read_etopo(tile, into, spec["surface"]) for tile in spec["tiles"]]
        w, h, sums, counts = accumulate(bbox, grids)
        lake = joined_to(counts, w, h, bbox, spec["seed"])
        sums[~lake] = 0.0
        counts[~lake] = 0
    levels, deepest, wet = levels_for(sums, counts, step)
    out = OUT_DIR / f"{stem}.png"
    out.write_bytes(encode_png_gray(w, h, levels.tobytes()))
    print(f"{stem}: {w}x{h}, {wet} wet cells, deepest {deepest:.0f} m "
          f"→ {out.name}, {out.stat().st_size / 1e3:.0f} KB")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("dir", help="where the unpacked sources are, or go")
    ap.add_argument("--fetch", action="store_true",
                    help="download any source that is not in DIR")
    ap.add_argument("--only", nargs="*", metavar="STEM",
                    help="bake only these regions (default: all)")
    args = ap.parse_args()
    into = Path(args.dir)
    into.mkdir(parents=True, exist_ok=True)
    for stem, bbox, step in REGIONS:
        if args.only and stem not in args.only:
            continue
        bake(stem, bbox, step, into, args.fetch)


if __name__ == "__main__":
    main()
