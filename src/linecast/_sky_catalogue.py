"""The baked sky: stars, their names, the constellations, the Milky Way.

Everything here is read from src/linecast/data, written by
scripts/build_sky_catalogue.py, and loaded once per process on first
use. The moon view takes its star field from `star_positions`; the sky
view takes all of it.

The stars are the Yale Bright Star Catalogue to magnitude 6.5, brightest
first, so a prefix of the list is the sky to some limiting magnitude.
Positions are J2000; at a terminal cell's resolution precession since
then does not show.
"""

import gzip
import json
import math
import struct
from pathlib import Path

from linecast._runtime import log_failure

_DATA = Path(__file__).parent / "data"

_stars = None       # [(ra_rad, dec_rad, vmag, b_v)] brightest first
_vectors = None     # [(x, y, z)] unit vectors, equatorial frame, parallel
_names = None       # {index: (proper name or "", designation or "")}
_constellations = None
_milky_way = None


def stars():
    """[(ra_rad, dec_rad, vmag, b_v)] brightest first."""
    global _stars
    if _stars is None:
        try:
            data = (_DATA / "stars.bin").read_bytes()
            _stars = [(math.radians(ra / 100.0), math.radians(dec / 100.0),
                       mag / 10.0, bv / 50.0)
                      for ra, dec, mag, bv in struct.iter_unpack("<Hhbb", data)]
        except Exception as exc:
            log_failure("stars", "star catalogue load", exc, fallback="no stars")
            _stars = []
    return _stars


def star_positions():
    """[(ra_rad, dec_rad)] brightest first — the moon view's star field."""
    return [(ra, dec) for ra, dec, _mag, _bv in stars()]


def star_vectors():
    """Unit vectors in the equatorial frame, one per star: x toward the
    vernal equinox, z toward the north celestial pole."""
    global _vectors
    if _vectors is None:
        _vectors = [equatorial_vector(ra, dec) for ra, dec, _m, _b in stars()]
    return _vectors


def equatorial_vector(ra, dec):
    """The unit vector of right ascension *ra* and declination *dec*, radians."""
    c = math.cos(dec)
    return (c * math.cos(ra), c * math.sin(ra), math.sin(dec))


def _load_sky():
    global _names, _constellations
    if _names is not None:
        return
    try:
        sky = json.loads(gzip.decompress((_DATA / "sky.json.gz").read_bytes()))
        _names = {i: (proper, desig) for i, proper, desig in sky["names"]}
        _constellations = []
        for c in sky["constellations"]:
            ra, dec = c["at"]
            _constellations.append({
                "id": c["id"], "name": c["name"], "gen": c["gen"],
                "names": c["names"],
                "at": equatorial_vector(math.radians(ra / 100.0),
                                        math.radians(dec / 100.0)),
                "lines": [[equatorial_vector(math.radians(ra / 100.0),
                                             math.radians(dec / 100.0))
                           for ra, dec in line] for line in c["lines"]],
            })
    except Exception as exc:
        log_failure("sky", "sky catalogue load", exc,
                    fallback="no names or constellations")
        _names, _constellations = {}, []


def star_names():
    """{index: (proper name or "", designation or "")}, indexed as `stars`."""
    _load_sky()
    return _names


def constellations():
    """One record per constellation: id, Latin name and genitive, names
    in other languages where they differ, the label position `at` and the
    figure `lines`, both as equatorial unit vectors."""
    _load_sky()
    return _constellations


def constellation_name(record, lang):
    """The constellation's name in *lang*, or the Latin one."""
    return record["names"].get(lang, record["name"])


MILKY_WAY_W, MILKY_WAY_H = 720, 360


def milky_way():
    """The Milky Way's brightness, 0–255, as a 720×360 raster in galactic
    coordinates: longitude 180° at the left edge running to −180°,
    latitude +90° at the top. Empty bytes if the raster is missing."""
    global _milky_way
    if _milky_way is None:
        try:
            _milky_way = gzip.decompress((_DATA / "milkyway.bin.gz").read_bytes())
            if len(_milky_way) != MILKY_WAY_W * MILKY_WAY_H:
                raise ValueError(f"raster is {len(_milky_way)} bytes")
        except Exception as exc:
            log_failure("sky", "Milky Way load", exc, fallback="no Milky Way")
            _milky_way = b""
    return _milky_way


# Equatorial (J2000) to galactic: the rows are the galactic x, y, z axes
# in equatorial coordinates (Hipparcos, vol. 1, §1.5.3). Applied to a
# vector in the frame `star_vectors` uses, it gives galactic x, y, z,
# with longitude atan2(y, x) and latitude asin(z).
EQ_TO_GAL = (
    -0.0548755604, -0.8734370902, -0.4838350155,
    +0.4941094279, -0.4448296300, +0.7469822445,
    -0.8676661490, -0.1980763734, +0.4559837762,
)
