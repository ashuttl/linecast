"""Bake the vendored climate-family grid from Köppen-Geiger rasters.

Collapses the Beck et al. (2023) 1991-2020 Köppen-Geiger classification
(30 classes at 0.1°) into the four hypsometric ramp families terrain
mode blends by — 0 humid, 1 semiarid, 2 arid, 3 polar — and writes the
result as a grayscale PNG the package ships and _climate.py samples.
Ocean cells flood-fill from the nearest land so a coastal sub-pixel
never reads "no climate": the Sahara stays sand right up to the surf.

Source data: https://doi.org/10.6084/m9.figshare.21789074 (CC-BY 4.0,
cite "Beck et al. 2023").  Hand it the extracted GeoTIFF:

    uv run --with tifffile --with imagecodecs --with numpy \
        scripts/build_climate_grid.py koppen_geiger_0p1.tif

or let it download and extract the bundle itself:

    uv run --with tifffile --with imagecodecs --with numpy \
        scripts/build_climate_grid.py --fetch

Either way the grid lands at src/linecast/data/climate.png, which is
committed — this script reruns only when the source dataset does.
"""

import argparse
import struct
import zlib
from collections import deque
from pathlib import Path

ZIP_URL = "https://ndownloader.figshare.com/files/61012822"
ZIP_MEMBER = "1991_2020/koppen_geiger_0p1.tif"
OUT = Path(__file__).resolve().parent.parent / "src/linecast/data/climate.png"

# Köppen class (1-30) → ramp family.  B's true deserts (BWh/BWk) are
# arid, its steppes (BSh/BSk) semiarid; every A/C/D humid class keeps
# the green ramp; ET and EF go polar.  0 is ocean/nodata, filled below.
FAMILY = {}
for k in range(1, 31):
    FAMILY[k] = 0                    # A, C, D: humid
FAMILY[4] = FAMILY[5] = 2            # BWh, BWk: desert
FAMILY[6] = FAMILY[7] = 1            # BSh, BSk: steppe
FAMILY[29] = FAMILY[30] = 3          # ET, EF: polar


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


def fill_ocean(fam, known, w, h):
    """BFS every unknown cell to its nearest known family, in place.

    Longitude wraps (the grid is the whole planet); latitude clamps.
    """
    queue = deque((y * w + x) for y in range(h) for x in range(w)
                  if known[y * w + x])
    while queue:
        i = queue.popleft()
        y, x = divmod(i, w)
        for j in ((y * w + (x - 1) % w), (y * w + (x + 1) % w),
                  (i - w if y > 0 else i), (i + w if y < h - 1 else i)):
            if not known[j]:
                known[j] = 1
                fam[j] = fam[i]
                queue.append(j)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("tif", nargs="?", help="koppen_geiger_0p1.tif path")
    ap.add_argument("--fetch", action="store_true",
                    help=f"download {ZIP_URL} and extract {ZIP_MEMBER}")
    args = ap.parse_args()

    if args.fetch:
        import io
        import urllib.request
        import zipfile
        print(f"downloading {ZIP_URL} (~130 MB) ...")
        with urllib.request.urlopen(ZIP_URL) as resp:
            blob = resp.read()
        tif_bytes = zipfile.ZipFile(io.BytesIO(blob)).read(ZIP_MEMBER)
    elif args.tif:
        tif_bytes = Path(args.tif).read_bytes()
    else:
        ap.error("give a GeoTIFF path or --fetch")

    import io

    import numpy as np
    import tifffile
    grid = tifffile.imread(io.BytesIO(tif_bytes))
    h, w = grid.shape
    print(f"source {w}x{h}, classes {int(grid.min())}-{int(grid.max())}")

    lut = np.zeros(256, dtype=np.uint8)
    for k, f in FAMILY.items():
        lut[k] = f
    fam = bytearray(lut[grid].tobytes())
    known = bytearray((grid > 0).astype(np.uint8).tobytes())
    print(f"land cells {sum(known)}, filling {w * h - sum(known)} from sea")
    fill_ocean(fam, known, w, h)

    png = encode_png_gray(w, h, bytes(fam))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_bytes(png)
    print(f"wrote {OUT} ({len(png)} bytes)")


if __name__ == "__main__":
    main()
