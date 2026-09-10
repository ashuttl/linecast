"""Bake NASA Black Marble 2016 into an offline night-light pyramid.

    uv run --with pillow scripts/build_night_lights.py [--source local.tif]

Source, credits, format and display treatment: src/linecast/data/NIGHT_LIGHTS.md.
Pillow is build-time only; the installed app reads zlib-compressed bytes.
"""

import argparse
import hashlib
import io
import struct
import urllib.request
import zlib
from pathlib import Path

from PIL import Image

SOURCE = ("https://assets.science.nasa.gov/content/dam/science/esd/eo/images/"
          "imagerecords/144000/144897/BlackMarble_2016_01deg_gray_geo.tif")
OUT = Path(__file__).resolve().parent.parent / "src/linecast/data/night_lights.bin"
WIDTHS = (2048, 1024, 512, 256, 128, 64, 32)


def bake(source):
    image = Image.open(io.BytesIO(source))
    if image.size != (3600, 1800):
        raise ValueError(f"unexpected NASA source dimensions: {image.size}")
    image = image.convert("L")
    raw = bytearray(b"NL01" + struct.pack(">I", len(WIDTHS)))
    for width in WIDTHS:
        height = width // 2
        # Area means, never maxima: a tiny bright source must not fill a
        # coarse terminal pixel with its peak brightness. Each level comes
        # from the original to avoid accumulating 8-bit rounding errors.
        level = image.resize((width, height), Image.Resampling.BOX)
        raw += struct.pack(">II", width, height) + level.tobytes()
    return zlib.compress(raw, 9)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, help="use a downloaded NASA GeoTIFF")
    args = parser.parse_args()
    source = (args.source.read_bytes() if args.source else
              urllib.request.urlopen(SOURCE, timeout=60).read())
    OUT.write_bytes(bake(source))
    print(f"source SHA-256: {hashlib.sha256(source).hexdigest()}")
    print(f"wrote {OUT} ({OUT.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
