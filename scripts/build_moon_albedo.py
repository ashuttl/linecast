"""Bake the moon view's albedo map from NASA's LRO mosaic.

The lunar disc shades its maria from a real image rather than a list
of circles: the CGI Moon Kit from NASA's Scientific Visualization
Studio, an equirectangular mosaic of Lunar Reconnaissance Orbiter
Wide Angle Camera imagery (public domain).

    uv run scripts/build_moon_albedo.py

Writes src/linecast/data/moon_albedo.png: an 8-bit greyscale
equirectangular map of the whole Moon — longitude −180…180 left to
right with the near side in the middle, latitude 90…−90 top to bottom
— scaled so the bright highlands sit near 255. The view ignores
libration, so at rest only the near side shows; the far side is there
for when the disc is dragged round. The file is committed; this
script reruns only if the source does. The JPEG decode goes through
macOS `sips` or ImageMagick, whichever is present — the package itself
reads only PNG.
"""

import shutil
import struct
import subprocess
import sys
import tempfile
import urllib.request
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from linecast._png import decode_rgba

SOURCE = ("https://svs.gsfc.nasa.gov/vis/a000000/a004700/a004720/"
          "lroc_color_poles_1k.jpg")
WIDTH, HEIGHT = 512, 256
OUT = Path(__file__).resolve().parent.parent / "src/linecast/data/moon_albedo.png"


def _chunk(kind, body):
    return (struct.pack(">I", len(body)) + kind + body
            + struct.pack(">I", zlib.crc32(kind + body)))


def encode_grey(width, height, pixels):
    raw = b"".join(b"\0" + bytes(pixels[y * width:(y + 1) * width])
                   for y in range(height))
    return (b"\x89PNG\r\n\x1a\n"
            + _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0))
            + _chunk(b"IDAT", zlib.compress(raw, 9))
            + _chunk(b"IEND", b""))


def to_png(jpg, png):
    """Resize the JPEG to WIDTH×HEIGHT and write it as PNG."""
    if shutil.which("sips"):
        cmd = ["sips", "-z", str(HEIGHT), str(WIDTH), "-s", "format", "png",
               str(jpg), "--out", str(png)]
    elif shutil.which("magick") or shutil.which("convert"):
        cmd = [shutil.which("magick") or "convert", str(jpg),
               "-resize", f"{WIDTH}x{HEIGHT}!", str(png)]
    else:
        sys.exit("need macOS sips or ImageMagick to decode the JPEG")
    subprocess.run(cmd, check=True, capture_output=True)


def main():
    with tempfile.TemporaryDirectory() as tmp:
        jpg = Path(tmp) / "moon.jpg"
        png = Path(tmp) / "moon.png"
        jpg.write_bytes(urllib.request.urlopen(SOURCE).read())
        to_png(jpg, png)
        w, h, rgba = decode_rgba(png.read_bytes())
    assert (w, h) == (WIDTH, HEIGHT)
    grey = [(rgba[i] * 299 + rgba[i + 1] * 587 + rgba[i + 2] * 114) // 1000
            for i in range(0, len(rgba), 4)]
    # Anchor the highlands at white: the 90th percentile stands in for
    # "typical bright highland", so crater rays and the brightest floors
    # clip rather than pull everything else down. A mild gamma keeps the
    # ordinary highland near white and leaves the maria their contrast.
    # The percentile is taken over the near side alone, as it was when
    # the map stopped there, so the face at rest keeps its look.
    half = WIDTH // 2
    near = [grey[y * WIDTH + x]
            for y in range(HEIGHT) for x in range(half // 2, half // 2 + half)]
    ref = sorted(near)[int(len(near) * 0.90)]
    scaled = bytes(int(255 * min(1.0, v / ref) ** 0.8) for v in grey)
    OUT.write_bytes(encode_grey(WIDTH, HEIGHT, scaled))
    print(f"wrote {OUT} ({OUT.stat().st_size} bytes, highland ref {ref})")


if __name__ == "__main__":
    main()
