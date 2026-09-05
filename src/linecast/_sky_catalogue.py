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
_cultures = None    # {stellarium id: raw record}
_culture_cache = {}  # short name -> prepared record


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


MILKY_WAY_W, MILKY_WAY_H = 1080, 540


def milky_way():
    """The Milky Way's brightness, 0–255, as a 1080×540 raster in
    celestial coordinates: right ascension 0h at the centre, increasing
    to the left as the sky is seen from inside, declination +90° at the
    top. Empty bytes if the raster is missing."""
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


# ---------------------------------------------------------------------------
# Sky cultures
# ---------------------------------------------------------------------------
# The short names the flag and the setting take, and Stellarium's
# directory names behind them (see scripts/build_sky_catalogue.py).
CULTURES = {
    "anutan": "anutan", "belarusian": "belarusian", "blackfoot": "blackfoot",
    "boorong": "boorong", "bugis": "bugis", "chinese": "chinese",
    "chinese-modern": "chinese_contemporary", "hawaiian": "hawaiian_starlines",
    "indian": "indian", "japanese": "japanese_moon_stations", "mandar": "mandar",
    "maori": "maori", "mongolian": "mongolian", "norse": "norse",
    "romanian": "romanian", "ruelle": "ruelle", "sami": "sami",
    "siberian": "siberian", "tongan": "tongan", "tukano": "tukano",
    "snt": "western_SnT", "rey": "western_rey",
}
# The culture a language brings with it, as the moon's calendars do.
CULTURE_OF_LANG = {"zh": "chinese"}


def resolve_culture(flag, lang):
    """The sky culture to draw, or None for the IAU sky.

    Precedence: the --culture flag > the `linecast culture` setting > the
    culture native to the UI language > none. 'none' anywhere in that
    chain stops it.
    """
    from linecast._config import saved_culture
    choice = flag or saved_culture() or CULTURE_OF_LANG.get(lang)
    return None if choice in (None, "none", "iau") else choice


def _load_cultures():
    global _cultures
    if _cultures is None:
        try:
            raw = json.loads(gzip.decompress((_DATA / "cultures.json.gz").read_bytes()))
            _cultures = {c["id"]: c for c in raw}
        except Exception as exc:
            log_failure("sky", "sky cultures load", exc, fallback="no cultures")
            _cultures = {}
    return _cultures


def culture(short):
    """A culture prepared for drawing: its title, region, credits, and
    `figures` as constellation records (english and native names, an
    `iau` code where the culture keeps the IAU figure, the label point
    and the lines as equatorial unit vectors), and `star_names` as
    {index: (english, native)}. None for a name the data lacks."""
    if short in _culture_cache:
        return _culture_cache[short]
    raw = _load_cultures().get(CULTURES.get(short, short))
    if raw is None:
        return None

    def vec(pair):
        ra, dec = pair
        return equatorial_vector(math.radians(ra / 100.0), math.radians(dec / 100.0))

    prepared = {
        "id": short, "title": raw["title"], "region": raw["region"],
        "native_lang": raw["native_lang"], "fallback": raw["fallback"],
        "authors": raw["authors"], "license": raw["license"],
        "figures": [{
            "id": f"{short}:{i}", "english": c["english"], "native": c["native"],
            "iau": c.get("iau"), "at": vec(c["at"]),
            "lines": [[vec(p) for p in line] for line in c["lines"]],
        } for i, c in enumerate(raw["constellations"])],
        "star_names": {int(k): tuple(v) for k, v in raw["star_names"].items()},
    }
    _culture_cache[short] = prepared
    return prepared


def culture_title(short):
    prepared = culture(short)
    return prepared["title"] if prepared else short


def _pick(english, native, native_lang, lang):
    """Which of a culture's two names to show: the native one where the
    display language is the culture's own, or where there is no English;
    the English one otherwise, and where the culture has no language of
    its own and no native form."""
    if native_lang:
        if lang == native_lang:
            return native
        return english or native
    return native or english


def figures_for(short, lang):
    """The constellation records to draw for a culture, in the shape of
    `constellations()` plus the label text in `name` and the other form of
    the name in `detail`: an IAU figure keeps its localized name."""
    prepared = culture(short)
    if prepared is None:
        return []
    iau = {r["id"]: r for r in constellations()}
    out = []
    for fig in prepared["figures"]:
        native_lang = prepared["native_lang"]
        if fig["iau"] and fig["iau"] in iau and not (native_lang and lang == native_lang
                                                     and fig["native"]):
            name = constellation_name(iau[fig["iau"]], lang)
            detail = fig["native"] or fig["english"]
        else:
            name = _pick(fig["english"], fig["native"], native_lang, lang)
            detail = fig["native"] if name == fig["english"] else fig["english"]
        if not name:
            continue
        out.append({"id": fig["id"], "name": name, "gen": "", "names": {},
                    "detail": detail if detail != name else "",
                    "at": fig["at"], "lines": fig["lines"]})
    return out


def names_for(short, lang):
    """{index: (name, designation)} for a culture: its own star names,
    with the IAU names behind them where the culture asks for that
    fallback. The designation stays the IAU one, so the chip can say
    which star a name belongs to."""
    prepared = culture(short)
    if prepared is None:
        return star_names()
    iau = star_names()
    out = dict(iau) if prepared["fallback"] else {}
    for index, (english, native) in prepared["star_names"].items():
        name = _pick(english, native, prepared["native_lang"], lang)
        if name:
            out[index] = (name, iau.get(index, ("", ""))[1])
    return out
