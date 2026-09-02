"""MeteoAlarm's warning regions, baked: which regions cover a point.

Most MeteoAlarm feeds put no polygon on a warning, only a geocode --
an EMMA_ID such as PL3001, one per county, district, or province; for
a few feeds a NUTS code; for Czechia a CISORP, one per municipality
with extended powers -- and the feed is the whole country's. Reading
the areaDesc against the user's address was the old way of telling
which of those warnings were theirs, and it matched on a tier word
once too often (issue #57). The geometry for every EMMA_ID is
published by MeteoAlarm, Eurostat's for the NUTS regions, and the
Czech cadastre's for the ORPs; here they are, simplified and packed by
scripts/build_meteoalarm_regions.py, so the question "is this point
inside PL3001?" has a plain answer.

A region is keyed the way key_for spells it: a bare EMMA_ID, or the
geocode type and value joined by "/" (NUTS3/FR101, CISORP/2101) for
any other type, so codes of different types can never cross (#59).

Loaded on first use and kept for the process. A megabyte of gzip and
a struct walk: a few tens of milliseconds, paid only by a weather
call in a MeteoAlarm country.
"""

import gzip
import os
import struct
from array import array

from linecast._runtime import log_failure

_PATH = os.path.join(os.path.dirname(__file__), "data", "meteoalarm_regions.bin.gz")
_SCALE = 1e-5

# list of (key, (lat_min, lat_max, lng_min, lng_max), polygons), where a
# polygon is (outer_ring, [hole_ring, ...]) and a ring is [(lat, lng), ...]
# in degrees. None until loaded; [] if the data could not be read.
_REGIONS = None


def _parse(blob):
    if blob[:4] != b"LCMA" or blob[4] != 2:
        raise ValueError("not a version-2 meteoalarm_regions file")
    (nregions,) = struct.unpack_from("<H", blob, 5)
    pos = 7
    regions = []
    for _ in range(nregions):
        n = blob[pos]
        key = blob[pos + 1:pos + 1 + n].decode("ascii")
        pos += 1 + n
        bbox = tuple(v * _SCALE for v in struct.unpack_from("<iiii", blob, pos))
        pos += 16
        (npolys,) = struct.unpack_from("<H", blob, pos)
        pos += 2
        polygons = []
        for _ in range(npolys):
            nrings = blob[pos]
            pos += 1
            rings = []
            for _ in range(nrings):
                (npts,) = struct.unpack_from("<H", blob, pos)
                pos += 2
                flat = array("i")
                flat.frombytes(blob[pos:pos + npts * 8])
                pos += npts * 8
                rings.append([(flat[i] * _SCALE, flat[i + 1] * _SCALE)
                              for i in range(0, len(flat), 2)])
            polygons.append((rings[0], rings[1:]))
        regions.append((key, bbox, polygons))
    return regions


def _load():
    global _REGIONS
    if _REGIONS is None:
        try:
            with open(_PATH, "rb") as fh:
                _REGIONS = _parse(gzip.decompress(fh.read()))
        except Exception as exc:
            log_failure("weather/alerts", "meteoalarm regions", exc,
                        fallback="matching alerts by area name")
            _REGIONS = []
    return _REGIONS


def point_in_ring(lat, lng, ring):
    """True when (lat, lng) falls inside a closed ring, by ray casting.

    Cast east along the parallel and count crossings. Warning polygons
    are small enough for plate carree to be exact enough; the nearest
    edge case is a point on the boundary, which may fall either way and
    costs nothing either way.
    """
    inside = False
    j = len(ring) - 1
    for i, (lat_i, lng_i) in enumerate(ring):
        lat_j, lng_j = ring[j]
        if (lat_i > lat) != (lat_j > lat):
            cross = (lng_j - lng_i) * (lat - lat_i) / (lat_j - lat_i) + lng_i
            if lng < cross:
                inside = not inside
        j = i
    return inside


def key_for(value_name, value):
    """The data's key for a CAP geocode: the EMMA_ID itself, else type/value.

    France files NUTS3 codes, and FR101 is both a NUTS3 code and an
    EMMA_ID; the type in the key keeps them apart. The key need not be
    one the data knows -- ask known().
    """
    if value_name == "EMMA_ID":
        return value
    return f"{value_name}/{value}"


def regions_at(lat, lng):
    """The region keys whose ground includes (lat, lng), as a set.

    Regions nest -- Austria files a district inside its state, and a
    NUTS region sits over the EMMA_IDs of the same ground -- so a
    point can be in several. Empty for a point no region covers, and
    for a country the data does not know.
    """
    found = set()
    for key, (lat_min, lat_max, lng_min, lng_max), polygons in _load():
        if not (lat_min <= lat <= lat_max and lng_min <= lng <= lng_max):
            continue
        for outer, holes in polygons:
            if point_in_ring(lat, lng, outer) and not any(
                    point_in_ring(lat, lng, h) for h in holes):
                found.add(key)
                break
    return found


def known(key):
    """Whether the data carries a region under this key (see key_for)."""
    return key in _codes()


_CODES = None


def _codes():
    global _CODES
    if _CODES is None:
        _CODES = frozenset(key for key, _, _ in _load())
    return _CODES
