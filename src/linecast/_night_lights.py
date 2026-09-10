"""Measured, static night lights, averaged to the view's pixel footprint.

NASA Black Marble 2016, bundled offline; see data/NIGHT_LIGHTS.md.
The scene worker loads the immutable pyramid; motion only samples it.
"""

from functools import lru_cache
import math
from pathlib import Path
import struct
import zlib

from linecast._runtime import log_failure

ATTRIBUTION = "Lights: NASA/GSFC (2016)"
_PATH = Path(__file__).parent / "data/night_lights.bin"

# How many display sub-pixels one source texel may span. Regional lights
# stay intact; local terrain takes over before the glow becomes a large blob.
_FADE_START, _FADE_END = 2.0, 6.0


def _resolution_opacity(source_pixels_per_pixel):
    t = ((source_pixels_per_pixel - 1.0 / _FADE_END)
         / (1.0 / _FADE_START - 1.0 / _FADE_END))
    t = min(1.0, max(0.0, t))
    return t * t * (3.0 - 2.0 * t)


@lru_cache(maxsize=1)
def load():
    try:
        raw = zlib.decompress(_PATH.read_bytes())
        if raw[:4] != b"NL01":
            raise ValueError("invalid night-light header")
        count, = struct.unpack_from(">I", raw, 4)
        if count != 7:
            raise ValueError("invalid night-light level count")
        levels, offset = [], 8
        for index in range(count):
            w, h = struct.unpack_from(">II", raw, offset)
            offset += 8
            if (w, h) != (2048 >> index, 1024 >> index):
                raise ValueError("invalid night-light dimensions")
            pixels = raw[offset:offset + w * h]
            if len(pixels) != w * h:
                raise ValueError("truncated night-light pixels")
            levels.append((w, h, pixels))
            offset += w * h
        if offset != len(raw):
            raise ValueError("trailing night-light data")
        return tuple(levels)
    except Exception as exc:
        log_failure("maps", "night-light map load", exc, fallback="lights off")
        return ()


def _bilinear(level, lat, lon):
    w, h, pixels = level
    fx = (lon + 180.0) % 360.0 * w / 360.0 - .5
    ix = math.floor(fx)
    x0, x1, tx = ix % w, (ix + 1) % w, fx - ix
    fy = min(h - 1.0, max(0.0, (90.0 - lat) * h / 180.0 - .5))
    y0 = int(fy)
    a, b, ty = y0 * w, min(h - 1, y0 + 1) * w, fy - y0
    top = pixels[a + x0] * (1 - tx) + pixels[a + x1] * tx
    bottom = pixels[b + x0] * (1 - tx) + pixels[b + x1] * tx
    return top * (1 - ty) + bottom * ty


def sample(levels, lls, degrees_per_pixel, zs=None):
    """Sparse {(x, y): glow} with bilinear and continuous level filtering.

    Orthographic foreshortening and converging meridians enlarge the
    geographic footprint. An area-equivalent mip level softens those
    regions too. This is a display approximation, not radiance analysis.
    """
    if not levels:
        return {}
    base = max(1e-12, degrees_per_pixel * levels[0][0] / 360.0)
    opacity = _resolution_opacity(base)
    if opacity == 0.0:
        return {}
    last = len(levels) - 1
    out = {}
    for y, row in enumerate(lls):
        for x, ll in enumerate(row):
            if ll is None:
                continue
            lat, lon = ll
            area = max(.01, abs(math.cos(math.radians(lat))))
            if zs is not None:
                area *= max(.05, zs[y][x])
            lod = min(last, max(0.0, math.log2(base / math.sqrt(area))))
            lo = int(lod)
            value = _bilinear(levels[lo], lat, lon)
            if lo < last:
                value += (_bilinear(levels[lo + 1], lat, lon) - value) * (lod - lo)
            # Lift concentrated light enough to read against the night
            # terrain, while sub-code-value averages stay dark.
            if value > 1.0:
                out[x, y] = (value / 255.0) ** .65 * opacity
    return out
