"""Bake the vendored climate-family grid from Köppen-Geiger rasters.

Collapses the Beck et al. (2023) 1991-2020 Köppen-Geiger classification
(30 classes at 0.1°) into the four hypsometric ramp families terrain
mode blends by — 0 humid, 1 semiarid, 2 arid, 3 polar — and writes the
result as a grayscale PNG the package ships and maps/climate.py samples.
Ocean cells flood-fill from the nearest land so a coastal sub-pixel
never reads "no climate": the Sahara stays sand right up to the surf.

Tundra climbs the polar ramp whatever Köppen calls its climate.  The
polar classes stop where the warmest month passes 10°C, and much of
the Arctic's treeless ground has Julys warmer than that — Alaska's
North Slope foothills, Canada's Barren Grounds — so Köppen files it
with the boreal forest.  RESOLVE's Ecoregions 2017 puts that ground
in its tundra biome, with the Arctic's alpine tundra and Scandinavia's
fjell, and every cell at least half inside the biome is polar.

Source data: https://doi.org/10.6084/m9.figshare.21789074 (CC-BY 4.0,
cite "Beck et al. 2023") and https://ecoregions.appspot.com (CC-BY
4.0, cite "Dinerstein et al. 2017").  Hand it the extracted GeoTIFF
and the ecoregions zip:

    uv run --with tifffile --with imagecodecs --with numpy --with pillow \
        --with pyshp scripts/build_climate_grid.py \
        koppen_geiger_0p1.tif Ecoregions2017.zip

or let it download both itself:

    uv run --with tifffile --with imagecodecs --with numpy --with pillow \
        --with pyshp scripts/build_climate_grid.py --fetch

Either way the grid lands at src/linecast/data/climate.png, which is
committed — this script reruns only when a source dataset does.
"""

import argparse
import io
from collections import deque
from pathlib import Path

from polygon_grid import encode_png_gray, rasterise

ZIP_URL = "https://ndownloader.figshare.com/files/61012822"
ZIP_MEMBER = "1991_2020/koppen_geiger_0p1.tif"
ECO_URL = "https://storage.googleapis.com/teow2016/Ecoregions2017.zip"
OUT = Path(__file__).resolve().parent.parent / "src/linecast/data/climate.png"

# Köppen class (1-30) → ramp family.  B's true deserts (BWh/BWk) are
# arid, its steppes (BSh/BSk) semiarid; every A/C/D humid class keeps
# the green ramp; ET and EF go polar, as does the tundra biome (see
# above).  0 is ocean/nodata, filled below.
FAMILY = {}
for k in range(1, 31):
    FAMILY[k] = 0                    # A, C, D: humid
FAMILY[4] = FAMILY[5] = 2            # BWh, BWk: desert
FAMILY[6] = FAMILY[7] = 1            # BSh, BSk: steppe
FAMILY[29] = FAMILY[30] = 3          # ET, EF: polar


def tundra_geometries(zip_bytes):
    """The tundra biome's polygons, GeoJSON-style, from the ecoregions zip."""
    import zipfile

    import shapefile
    zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    parts = {name.rsplit(".", 1)[-1].lower(): io.BytesIO(zf.read(name))
             for name in zf.namelist()
             if name.lower().endswith((".shp", ".shx", ".dbf"))}
    reader = shapefile.Reader(shp=parts["shp"], shx=parts["shx"],
                              dbf=parts["dbf"], encoding="latin-1")
    for sr in reader.iterShapeRecords():
        if sr.record["BIOME_NAME"] == "Tundra":
            yield sr.shape.__geo_interface__


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
    ap.add_argument("ecoregions", nargs="?", help="Ecoregions2017.zip path")
    ap.add_argument("--fetch", action="store_true",
                    help=f"download {ZIP_URL} and {ECO_URL}")
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()

    if args.fetch:
        import urllib.request
        import zipfile
        print(f"downloading {ZIP_URL} (~130 MB) ...")
        with urllib.request.urlopen(ZIP_URL) as resp:
            blob = resp.read()
        tif_bytes = zipfile.ZipFile(io.BytesIO(blob)).read(ZIP_MEMBER)
        print(f"downloading {ECO_URL} (~150 MB) ...")
        with urllib.request.urlopen(ECO_URL) as resp:
            eco_bytes = resp.read()
    elif args.tif and args.ecoregions:
        tif_bytes = Path(args.tif).read_bytes()
        eco_bytes = Path(args.ecoregions).read_bytes()
    else:
        ap.error("give the GeoTIFF and the ecoregions zip, or --fetch")

    import numpy as np
    import tifffile
    grid = tifffile.imread(io.BytesIO(tif_bytes))
    h, w = grid.shape
    print(f"source {w}x{h}, classes {int(grid.min())}-{int(grid.max())}")

    lut = np.zeros(256, dtype=np.uint8)
    for k, f in FAMILY.items():
        lut[k] = f
    fam = lut[grid]
    known = (grid > 0).astype(np.uint8)
    tundra = rasterise(tundra_geometries(eco_bytes)) >= 128
    print(f"tundra cells {int(tundra.sum())}, "
          f"{int((tundra & (fam != 3)).sum())} of them not polar by Köppen")
    fam[tundra] = 3
    known[tundra] = 1
    fam = bytearray(fam.tobytes())
    known = bytearray(known.tobytes())
    print(f"land cells {sum(known)}, filling {w * h - sum(known)} from sea")
    fill_ocean(fam, known, w, h)

    png = encode_png_gray(w, h, bytes(fam))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(png)
    print(f"wrote {args.out} ({len(png)} bytes)")


if __name__ == "__main__":
    main()
