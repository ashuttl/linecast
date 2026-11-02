"""Measured, static night lights, averaged to the view's pixel footprint.

NASA Black Marble 2016, bundled offline; see data/NIGHT_LIGHTS.md.
The scene worker loads the immutable pyramid; motion only samples it.
"""

from functools import lru_cache
import math
import struct
import zlib

from linecast._paths import data_path
from linecast._log import log_failure

ATTRIBUTION = "Lights: NASA/GSFC (2016)"
_PATH = data_path("night_lights.bin")

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


def sample(levels, lls, degrees_per_pixel, zs=None, day=None, below=None):
    """Sparse {(x, y): glow} with bilinear and continuous level filtering.

    Orthographic foreshortening and converging meridians enlarge the
    geographic footprint. An area-equivalent mip level softens those
    regions too. This is a display approximation, not radiance analysis.

    With `day` (a per-sample day factor, None in space) only the
    samples whose factor is below `below` are sampled: the rest are
    the ones the sun outshines, and a drag frame need not price them.
    """
    if not levels:
        return {}
    base = max(1e-12, degrees_per_pixel * levels[0][0] / 360.0)
    opacity = _resolution_opacity(base)
    if opacity == 0.0:
        return {}
    last = len(levels) - 1
    cos, radians, log2, sqrt, floor = (math.cos, math.radians, math.log2,
                                       math.sqrt, math.floor)
    out = {}
    # The bilinear read is written out in the loop rather than called:
    # every night-side sub-pixel of every drag frame with the sun on
    # comes through here, and the calls a sample were a tenth of the
    # time.  Longitude wraps, latitude clamps to the last row.
    for y, row in enumerate(lls):
        z_row = zs[y] if zs is not None else None
        d_row = day[y] if day is not None else None
        for x, ll in enumerate(row):
            if ll is None:
                continue
            if d_row is not None:
                d = d_row[x]
                if d is None or d > below:
                    continue
            lat, lon = ll
            area = max(.01, abs(cos(radians(lat))))
            if z_row is not None:
                area *= max(.05, z_row[x])
            lod = min(last, max(0.0, log2(base / sqrt(area))))
            lo = int(lod)
            # the level the lod sits in, then the one above it where
            # there is one, blended by the fraction between them
            value = 0.0
            for lv in (lo, lo + 1):
                if lv > last:
                    break
                w, h, pixels = levels[lv]
                fx = (lon + 180.0) % 360.0 * w / 360.0 - .5
                ix = floor(fx)
                x0, x1, tx = ix % w, (ix + 1) % w, fx - ix
                fy = min(h - 1.0, max(0.0, (90.0 - lat) * h / 180.0 - .5))
                y0 = int(fy)
                a, b, ty = y0 * w, min(h - 1, y0 + 1) * w, fy - y0
                top = pixels[a + x0] * (1 - tx) + pixels[a + x1] * tx
                bottom = pixels[b + x0] * (1 - tx) + pixels[b + x1] * tx
                if lv == lo:
                    value = top * (1 - ty) + bottom * ty
                else:
                    value += (top * (1 - ty) + bottom * ty - value) * (lod - lo)
            # Lift concentrated light enough to read against the night
            # terrain, while sub-code-value averages stay dark.
            if value > 1.0:
                out[x, y] = (value / 255.0) ** .65 * opacity
    return out
