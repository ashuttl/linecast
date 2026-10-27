"""Bake the vendored glacier grid from Natural Earth's glaciated areas.

Rasterises Natural Earth's 1:10m glaciated areas (public domain) onto
the Köppen grid's tenth of a degree (scripts/polygon_grid.py) and
writes each cell's ice fraction (0 none, 255 all) as a grayscale PNG
the package ships and maps/glaciers.py samples.

Natural Earth leaves out the Antarctic ice sheet's floating edges, and
the elevation data reports the shelves as land, so everything south of
60°S is ice: the shader never paints cover on the sea, and the few
dry valleys and nunataks are wrong about no terminal cell.

    uv run --with numpy --with pillow \
        scripts/build_glacier_grid.py ne_10m_glaciated_areas.geojson

or let it download the GeoJSON itself:

    uv run --with numpy --with pillow scripts/build_glacier_grid.py --fetch

Either way the grid lands at src/linecast/data/glaciers.png, which is
committed — this script reruns only when Natural Earth does.
"""

import argparse
import json
from pathlib import Path

from polygon_grid import H, encode_png_gray, rasterise, W

GEOJSON_URL = ("https://raw.githubusercontent.com/nvkelso/natural-earth-vector/"
               "master/geojson/ne_10m_glaciated_areas.geojson")
OUT = Path(__file__).resolve().parent.parent / "src/linecast/data/glaciers.png"

ANTARCTIC = -60.0


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("geojson", nargs="?", help="ne_10m_glaciated_areas.geojson")
    ap.add_argument("--fetch", action="store_true",
                    help=f"download {GEOJSON_URL}")
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()

    if args.fetch:
        import urllib.request
        print(f"downloading {GEOJSON_URL} (~6 MB) ...")
        with urllib.request.urlopen(GEOJSON_URL) as resp:
            data = json.loads(resp.read())
    elif args.geojson:
        data = json.loads(Path(args.geojson).read_text())
    else:
        ap.error("give a GeoJSON path or --fetch")

    frac = rasterise(f["geometry"] for f in data["features"])
    frac[int((90.0 - ANTARCTIC) * H / 180.0):, :] = 255
    print(f"{len(data['features'])} features, "
          f"{int((frac > 0).sum())} cells with ice")

    png = encode_png_gray(W, H, frac.tobytes())
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(png)
    print(f"wrote {args.out} ({len(png)} bytes)")


if __name__ == "__main__":
    main()
