"""Bake the globe's stitched world canvases for the wheel.

The orthographic globe samples a whole-world mosaic of terrarium
elevation tiles at zoom 1, 2 or 3 depending on terminal height.  The
tiles are immutable, so the stitched canvas is too — baking it at
release time means a fresh install draws its first globe with no
network and no PNG unfiltering at all.  Zoom 3 is left out on
purpose: its 7.5 MB would serve only very tall terminals, which
stitch and cache it locally on first use instead.

    uv run scripts/build_globe_canvas.py

Writes src/linecast/data/globe_canvas_{1,2}.bin (the same format
_globe._canvas_load reads from the user cache: zlib over a ">5I"
header — canvas w/h, world-pixel origin x/y, world size — followed
by raw RGBA).  Both files are committed; this script reruns only if
the terrarium source data ever does.
"""

import struct
import sys
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from linecast._elevation import _fetch_tile
from linecast._globe import _MERCATOR_LAT
from linecast._png import decode_rgba
from linecast._radar_tiles import stitch_xyz

ZOOMS = (1, 2)
OUT_DIR = Path(__file__).resolve().parent.parent / "src/linecast/data"


def main():
    for z in ZOOMS:
        missed = []

        def fetch(z_, x, y, missed=missed):
            data = _fetch_tile(z_, x, y, timeout=30)
            if data is None:
                missed.append((z_, x, y))
                return None
            return decode_rgba(data)

        bbox = (-180.0, -_MERCATOR_LAT, 180.0, _MERCATOR_LAT)
        canvas, cw, ch, org_x, org_y, world = stitch_xyz(fetch, bbox, z)
        if missed:
            sys.exit(f"z{z}: {len(missed)} tiles missing ({missed[:4]}…) — "
                     "a baked canvas must be complete; try again")
        blob = struct.pack(">5I", cw, ch, org_x, org_y, world) + bytes(canvas)
        out = OUT_DIR / f"globe_canvas_{z}.bin"
        out.write_bytes(zlib.compress(blob, 9))
        print(f"z{z}: {cw}x{ch} → {out.name}, "
              f"{out.stat().st_size / 1e6:.2f} MB")


if __name__ == "__main__":
    main()
