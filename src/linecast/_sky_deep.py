"""HYG's fainter stars, loaded only when zoom needs them.

Keep packed records in memory and decode a bounded cache of sky regions.
The bright Yale catalogue and its name indices remain independent.
See scripts/build_deep_stars.py and data/STARS.md for format and credits.
"""

import gzip
import json
import math
import struct
from functools import lru_cache

from linecast._runtime import log_failure
from linecast._sky_catalogue import _DATA, equatorial_vector

_RECORD = struct.Struct("<IiBbI")


@lru_cache(maxsize=1)
def _load():
    try:
        raw = gzip.decompress((_DATA / "stars-deep.bin.gz").read_bytes())
        size, = struct.unpack_from("<I", raw)
        header = json.loads(raw[4:4 + size])
        records = raw[4 + size:]
        offsets, hist = header["offsets"], header["histogram"]
        if (header["version"] != 1 or len(offsets) != 649 or len(hist) != 121
                or offsets[0] != 0 or offsets != sorted(offsets)
                or offsets[-1] * _RECORD.size != len(records)
                or sum(hist) != offsets[-1]):
            raise ValueError("invalid deep-star catalogue")
        return records, offsets, hist
    except Exception as exc:
        log_failure("stars", "deep star catalogue load", exc, fallback="bright stars only")
        return b"", [0] * 649, [0] * 121


def magnitude_at(rank):
    """Magnitude of a zero-based rank within the faint supplement."""
    hist = _load()[2]
    for mag, count in enumerate(hist):
        rank -= count
        if rank < 0:
            return mag / 10.0
    return next((mag / 10.0 for mag in range(120, -1, -1) if hist[mag]), 6.5)


def star(index):
    """(magnitude, colour, equatorial vector, catalogue designation)."""
    ra, dec, mag, bv, ident = _RECORD.unpack_from(_load()[0], index * _RECORD.size)
    name = f"HYG {ident & 0x7fffffff}" if ident & (1 << 31) else f"HIP {ident}"
    return (mag / 10.0, bv / 50.0,
            equatorial_vector(math.radians(ra / 1000), math.radians(dec / 1000)), name)


@lru_cache(maxsize=96)
def _zone(zone):
    offsets = _load()[1]
    return [(i, *star(i)[:3]) for i in range(offsets[zone], offsets[zone + 1])]


_CENTRES = [equatorial_vector(math.radians(ra + 5), math.radians(dec + 5))
            for dec in range(-90, 90, 10) for ra in range(0, 360, 10)]


def candidates(direction, radius, limit):
    """(index, mag, B-V, vector) within a cone, brightest first.

    radius is in radians; expand the cone by a bin's conservative maximum
    radius before culling bins. Dot products handle RA wrap and both poles.
    """
    if limit < 6.6:
        return []
    dx, dy, dz = direction
    edge = math.cos(min(math.pi, radius))
    zone_edge = math.cos(min(math.pi, radius + math.radians(10)))
    found = []
    for zone, (x, y, z) in enumerate(_CENTRES):
        if dx * x + dy * y + dz * z < zone_edge:
            continue
        for entry in _zone(zone):
            _i, mag, _bv, (x, y, z) = entry
            if mag > limit:
                break
            if dx * x + dy * y + dz * z >= edge:
                found.append(entry)
    found.sort(key=lambda s: (s[1], s[0]))
    return found
