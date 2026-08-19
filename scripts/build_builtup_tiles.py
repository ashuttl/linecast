"""Build built-up-surface XYZ tiles from GHSL GHS-BUILT-S rasters.

Converts the European Commission JRC's Global Human Settlement Layer
built-up surface (the 4326 3-arcsecond tiles, ~92 m cells holding m² of
built-up per cell) into the grayscale Web-Mercator PNG pyramid that
linecast's terrain mode samples for its urban tint: pixel value 0-255 =
fraction of the cell that is built.  Tiles with nothing built are not
written — absence means zero, which keeps a global set to a few hundred
megabytes.

Source data: https://ghsl.jrc.ec.europa.eu/download.php (CC-BY 4.0,
cite "GHSL © European Commission JRC").  Either hand it GeoTIFFs you
downloaded yourself:

    uv run --with rasterio scripts/build_builtup_tiles.py \
        out_tiles/ GHS_BUILT_S_*_R5_C11.tif --zooms 5-10

or let it walk the whole JRC tile grid itself — the global bake:

    uv run --with rasterio scripts/build_builtup_tiles.py \
        out_tiles/ --fetch --zooms 5-9

The global run downloads each 10°x10° source (~50 MB), tiles it, and
deletes it before moving on, so disk stays bounded; a `.done` file in
the output directory makes it resumable, and tiles at region seams
max-merge with whatever an earlier source wrote.  Then point linecast
at the result:

    LINECAST_BUILTUP_URL=file:///path/to/out_tiles linecast maps ...

Requires rasterio (pulls GDAL); everything else is stdlib.  Nearest-
neighbour sampling: the source cells (~92 m) and the deepest target
pixels (~150 m at z10) are close enough that averaging would only
soften the settlement edges the terrain view wants.
"""

import argparse
import math
import struct
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
import zlib
from pathlib import Path

import numpy as np
import rasterio

TILE = 256

FETCH_URL = ("https://jeodpp.jrc.ec.europa.eu/ftp/jrc-opendata/GHSL/"
             "GHS_BUILT_S_GLOBE_R2023A/GHS_BUILT_S_E2020_GLOBE_R2023A"
             "_4326_3ss/V1-0/tiles/GHS_BUILT_S_E2020_GLOBE_R2023A"
             "_4326_3ss_V1_0_R{r}_C{c}.zip")


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


def lonlat_to_world(lon, lat):
    x = (lon + 180.0) / 360.0
    s = np.clip(np.sin(np.radians(lat)), -0.9999, 0.9999)
    y = 0.5 - np.log((1 + s) / (1 - s)) / (4 * math.pi)
    return x, y


def world_to_lonlat(wx, wy):
    lon = wx * 360.0 - 180.0
    lat = np.degrees(np.arctan(np.sinh((0.5 - wy) * 2 * math.pi)))
    return lon, lat


class Source:
    """One GHSL 4326 raster held in memory with its geotransform."""

    def __init__(self, path):
        with rasterio.open(path) as src:
            self.a = src.read(1)
            self.x0, self.dx = src.transform.c, src.transform.a
            self.y0, self.dy = src.transform.f, -src.transform.e
            self.h, self.w = self.a.shape
        self.bounds = (self.x0, self.y0 - self.h * self.dy,
                       self.x0 + self.w * self.dx, self.y0)

    def sample(self, lon, lat):
        """Fraction 0-255 at (lon[cols], lat[rows]); 0 outside."""
        col = np.floor((lon - self.x0) / self.dx).astype(int)
        row = np.floor((self.y0 - lat) / self.dy).astype(int)
        ok_c = (col >= 0) & (col < self.w)
        ok_r = (row >= 0) & (row < self.h)
        vals = self.a[row.clip(0, self.h - 1)[:, None],
                      col.clip(0, self.w - 1)[None, :]].astype(np.float64)
        # cell area: 3 arcsec is ~92.66 m of latitude, cos(lat) of longitude
        area = 92.66 * 92.66 * np.cos(np.radians(lat))[:, None]
        frac = np.clip(vals / area, 0.0, 1.0)
        frac[~ok_r, :] = 0.0
        frac[:, ~ok_c] = 0.0
        return (frac * 255.0 + 0.5).astype(np.uint8)


def build(sources, out, zooms):
    minlon = min(s.bounds[0] for s in sources)
    minlat = min(s.bounds[1] for s in sources)
    maxlon = max(s.bounds[2] for s in sources)
    maxlat = max(s.bounds[3] for s in sources)
    x0f, y0f = lonlat_to_world(minlon, maxlat)
    x1f, y1f = lonlat_to_world(maxlon, minlat)

    written = 0
    for z in zooms:
        n = 1 << z
        tx0, tx1 = int(x0f * n), min(int(x1f * n), n - 1)
        ty0, ty1 = int(y0f * n), min(int(y1f * n), n - 1)
        for ty in range(ty0, ty1 + 1):
            wy = (ty + (np.arange(TILE) + 0.5) / TILE) / n
            _, lat = world_to_lonlat(np.zeros(TILE), wy)
            for tx in range(tx0, tx1 + 1):
                wx = (tx + (np.arange(TILE) + 0.5) / TILE) / n
                lon, _ = world_to_lonlat(wx, np.zeros(TILE))
                acc = None
                for s in sources:
                    f = s.sample(lon, lat)
                    acc = f if acc is None else np.maximum(acc, f)
                if acc.max() < 3:  # nothing built: absence means zero
                    continue
                d = out / str(z) / str(tx)
                d.mkdir(parents=True, exist_ok=True)
                path = d / f"{ty}.png"
                if path.exists():  # a neighbouring source wrote the seam
                    with rasterio.open(path) as old:
                        acc = np.maximum(acc, old.read(1))
                path.write_bytes(encode_png_gray(TILE, TILE, acc.tobytes()))
                written += 1
    return written


def fetch_all(out, zooms):
    """Walk the JRC 10°x10° grid: download, tile, delete, repeat.

    Sources already in `.done` are skipped, a 404 is remembered as
    "ocean, nothing there", and a transient failure is left un-marked
    so the next run retries it.  Crash-safe: a half-processed source
    reruns idempotently because seam tiles merge by max.
    """
    out.mkdir(parents=True, exist_ok=True)
    done_path = out / ".done"
    done = set(done_path.read_text().split()) if done_path.exists() else set()
    total = 0
    for r in range(1, 19):
        for c in range(1, 37):
            key = f"R{r}_C{c}"
            if key in done:
                continue
            try:
                with urllib.request.urlopen(FETCH_URL.format(r=r, c=c),
                                            timeout=300) as resp:
                    data = resp.read()
            except urllib.error.HTTPError as exc:
                if exc.code == 404:
                    done.add(key)
                    done_path.write_text("\n".join(sorted(done)))
                    print(f"{key}: no source (ocean)", flush=True)
                    continue
                print(f"{key}: HTTP {exc.code}, will retry next run",
                      flush=True)
                continue
            except Exception as exc:
                print(f"{key}: {exc}, will retry next run", flush=True)
                continue
            with tempfile.TemporaryDirectory() as td:
                zp = Path(td) / "src.zip"
                zp.write_bytes(data)
                del data
                with zipfile.ZipFile(zp) as z:
                    tifs = [n for n in z.namelist() if n.endswith(".tif")]
                    z.extractall(td, members=tifs)
                n = 0
                for t in tifs:
                    n += build([Source(Path(td) / t)], out, zooms)
            total += n
            done.add(key)
            done_path.write_text("\n".join(sorted(done)))
            print(f"{key}: {n} tiles ({total} this run)", flush=True)
    return total


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("out", type=Path)
    p.add_argument("tifs", nargs="*", type=Path)
    p.add_argument("--fetch", action="store_true",
                   help="download and process the whole JRC grid")
    p.add_argument("--zooms", default="5-10",
                   help="zoom range to build, e.g. 5-10 (default)")
    args = p.parse_args()
    lo, hi = (int(v) for v in args.zooms.split("-"))
    zooms = range(lo, hi + 1)
    if args.fetch:
        n = fetch_all(args.out, zooms)
    elif args.tifs:
        n = build([Source(t) for t in args.tifs], args.out, zooms)
    else:
        p.error("give source GeoTIFFs or --fetch")
    print(f"{n} tiles -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
