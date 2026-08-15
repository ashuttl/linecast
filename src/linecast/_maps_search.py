"""Place search — Photon while typing, Nominatim for the one-shot.

Two geocoders, two very different etiquettes. Photon
(photon.komoot.io) advertises search-as-you-type as a feature of the
engine, so it powers the interactive prompt: every keystroke may ask.
The public instance is fair use with no availability guarantee, so
nothing here retries or hammers, and a failure just degrades the UI.

Nominatim is the fallback for a single submitted query and nothing
else. Its usage policy explicitly prohibits autocomplete, demands an
identifying User-Agent, allows at most one request per second, and
asks that results be cached — so this module gates network hits behind
a monotonic clock, keeps answers on disk for a week, and never calls
it per keystroke.

Both are OpenStreetMap: attribute "© OpenStreetMap contributors".
"""

import hashlib
import json
import math
import time
import urllib.parse
import urllib.request

from linecast import USER_AGENT
from linecast._cache import CACHE_ROOT, read_cache, read_stale, write_cache
from linecast._runtime import debug_log

PHOTON_URL = "https://photon.komoot.io/api"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"

ATTRIBUTION = "© OpenStreetMap contributors"

# Photon translates place names into these three and nothing else;
# asking for anything more gets an error instead of English.
PHOTON_LANGS = ("en", "de", "fr")

_SEARCH_TTL = 7 * 86400
_NOMINATIM_INTERVAL = 1.0  # seconds between network hits, per policy
_last_hit = 0.0

# Fallback view heights (degrees of latitude) for results that arrive
# without an extent — roughly "what you'd want to see" per feature class.
_KIND_ZOOM = {
    "house": 0.006, "street": 0.006,
    "district": 0.03, "locality": 0.03, "suburb": 0.03,
    "neighbourhood": 0.03,
    "city": 0.08, "town": 0.08, "village": 0.08,
    "county": 0.6, "state": 4.0, "country": 20.0,
}
_DEFAULT_ZOOM = 0.08


class SearchUnavailable(Exception):
    """The geocoder could not be reached or spoke gibberish."""


class Result:
    """One place: what to show, where it is, and how big it is."""

    __slots__ = ("name", "detail", "lat", "lon", "kind", "extent")

    def __init__(self, name, detail, lat, lon, kind, extent=None):
        self.name = name
        self.detail = detail
        self.lat = lat
        self.lon = lon
        self.kind = kind
        self.extent = extent  # (minlon, minlat, maxlon, maxlat) or None

    def __repr__(self):
        return (f"Result({self.name!r}, {self.detail!r}, "
                f"{self.lat!r}, {self.lon!r}, {self.kind!r})")


def _get_json(url, headers=None, timeout=10):
    """The single network seam for this module."""
    debug_log(f"search fetch {url}")
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def _detail(parts, name):
    """Join locality context, dropping blanks, dupes, and the name
    itself — "Portland, Portland, Maine" helps nobody."""
    out = []
    for part in parts:
        part = (part or "").strip()
        if part and part != name and part not in out:
            out.append(part)
    return ", ".join(out)


# ---------------------------------------------------------------------------
# Photon
# ---------------------------------------------------------------------------

def photon_search(query, lat, lon, zoom, lang="en", limit=8, timeout=6):
    """Biased type-ahead results near (lat, lon) at the current zoom."""
    params = [("q", query), ("lat", lat), ("lon", lon), ("zoom", int(zoom)),
              ("location_bias_scale", "0.5"), ("limit", int(limit))]
    if lang in PHOTON_LANGS:
        params.append(("lang", lang))
    url = f"{PHOTON_URL}?{urllib.parse.urlencode(params)}"
    try:
        data = _get_json(url, headers={"User-Agent": USER_AGENT},
                         timeout=timeout)
    except Exception as exc:
        debug_log(f"photon search failed: {exc}")
        raise SearchUnavailable(str(exc)) from exc
    try:
        features = data.get("features") or []
        return [r for r in (_photon_result(f) for f in features) if r]
    except (AttributeError, TypeError, ValueError, KeyError) as exc:
        debug_log(f"photon response unreadable: {exc}")
        raise SearchUnavailable(str(exc)) from exc


def _photon_result(feature):
    """One GeoJSON feature → Result, or None when it has no name."""
    props = feature.get("properties") or {}
    name = (props.get("name") or "").strip()
    if not name:
        street = (props.get("street") or "").strip()
        house = (props.get("housenumber") or "").strip()
        name = f"{house} {street}".strip() if street else ""
    if not name:
        return None
    lon, lat = (feature.get("geometry") or {})["coordinates"][:2]
    locality = (props.get("city") or props.get("locality")
                or props.get("district") or props.get("county"))
    detail = _detail([locality, props.get("state"), props.get("country")],
                     name)
    return Result(name, detail, float(lat), float(lon),
                  props.get("type") or "", _photon_extent(props.get("extent")))


def _photon_extent(extent):
    """Photon sends [minlon, maxlat, maxlon, minlat] — west, north, east,
    south. Reorder to the (minlon, minlat, maxlon, maxlat) this codebase
    calls a bbox."""
    if not extent or len(extent) != 4:
        return None
    west, north, east, south = (float(v) for v in extent)
    return (min(west, east), min(north, south),
            max(west, east), max(north, south))


# ---------------------------------------------------------------------------
# Nominatim
# ---------------------------------------------------------------------------

def _cache_path(query, lang):
    key = hashlib.md5(f"{lang}|{query.strip().lower()}".encode()).hexdigest()
    return CACHE_ROOT / "maps" / "search" / f"{key[:12]}.json"


def _throttle():
    """Hold the line at one request per second, sleeping the remainder."""
    global _last_hit
    now = time.monotonic()
    wait = _NOMINATIM_INTERVAL - (now - _last_hit)
    if wait > 0:
        debug_log(f"nominatim: waiting {wait:.2f}s for the rate limit")
        time.sleep(wait)
        now += wait
    _last_hit = now


def nominatim_search(query, lang="en", limit=8, timeout=10):
    """One submitted query, answered from disk when we've asked before."""
    path = _cache_path(query, lang)
    cached = read_cache(path, _SEARCH_TTL)
    if cached is not None:
        debug_log(f"search cache hit: {path.name}")
        return _nominatim_results(cached)

    params = [("q", query), ("format", "jsonv2"), ("limit", int(limit)),
              ("addressdetails", 1), ("accept-language", lang)]
    url = f"{NOMINATIM_URL}?{urllib.parse.urlencode(params)}"
    headers = {"User-Agent":
               f"{USER_AGENT} (+https://github.com/ashuttl/linecast)"}
    _throttle()
    try:
        data = _get_json(url, headers=headers, timeout=timeout)
    except Exception as exc:
        debug_log(f"nominatim search failed: {exc}")
        stale = read_stale(path)
        if stale is not None:
            debug_log(f"using stale search cache: {path.name}")
            return _nominatim_results(stale)
        raise SearchUnavailable(str(exc)) from exc
    write_cache(path, data)
    return _nominatim_results(data)


def _nominatim_results(data):
    try:
        return [r for r in (_nominatim_result(i) for i in data or []) if r]
    except (AttributeError, TypeError, ValueError, KeyError) as exc:
        debug_log(f"nominatim response unreadable: {exc}")
        raise SearchUnavailable(str(exc)) from exc


def _nominatim_result(item):
    name = (item.get("name") or "").strip()
    if not name:
        name = (item.get("display_name") or "").split(",")[0].strip()
    if not name:
        return None
    addr = item.get("address") or {}
    locality = next((addr[k] for k in
                     ("city", "town", "village", "hamlet", "suburb", "county")
                     if addr.get(k)), "")
    detail = _detail([addr.get("road"), locality, addr.get("state"),
                      addr.get("country")], name)
    # jsonv2 hands back coordinates as strings
    return Result(name, detail, float(item["lat"]), float(item["lon"]),
                  item.get("addresstype") or item.get("type") or "",
                  _nominatim_extent(item.get("boundingbox")))


def _nominatim_extent(box):
    """boundingbox is ["minlat", "maxlat", "minlon", "maxlon"] — strings,
    latitude pair first. Reorder to (minlon, minlat, maxlon, maxlat)."""
    if not box or len(box) != 4:
        return None
    minlat, maxlat, minlon, maxlon = (float(v) for v in box)
    return (minlon, minlat, maxlon, maxlat)


# ---------------------------------------------------------------------------
# Framing
# ---------------------------------------------------------------------------

def fly_to_zoom(result, aspect=0.55):
    """Degrees of latitude to show after jumping to a result: the
    feature's own size with a little air around it, or a guess from what
    kind of thing it is.

    `aspect` is the viewport's lat-span per lon-span — `(hc * 2) / gw`
    for the caller's terminal.  Framing on latitude alone would cut off
    an east-west feature (a boulevard, a county) at both ends, so the
    width is converted to the latitude span that would show it and the
    larger of the two wins.
    """
    if result.extent:
        dlat = abs(result.extent[3] - result.extent[1])
        dlon = abs(result.extent[2] - result.extent[0])
        span = max(dlat,
                   dlon * math.cos(math.radians(result.lat)) * aspect) * 1.25
        return max(0.004, min(60.0, span))
    return _KIND_ZOOM.get(result.kind, _DEFAULT_ZOOM)
