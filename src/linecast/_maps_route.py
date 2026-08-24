"""Turn-by-turn routing — the directions client for maps.

Talks OSRM v5 to the FOSSGIS demo servers. The primary host is
routing.openstreetmap.de, which selects the profile by path prefix
(routed-car / routed-bike / routed-foot) and really does run three
distinct datasets; router.project-osrm.org is kept as a fallback for
car only, because its profile URL segment is decorative — it answers
every profile with the car dataset.

Both hosts are volunteer-run with no SLA and ask for at most one
request per second and a real User-Agent, so this module gates every
network call behind a monotonic 1 s throttle and memoizes results (a
re-render, or the user pressing the directions key again, must not
cost a request). Failures are split in two: RouteUnavailable is the
server's problem, NoRoute is the user's — callers word them
differently.

Directions data © OpenStreetMap contributors.
"""

import json
import time
import urllib.error
import urllib.request

from linecast import USER_AGENT
from linecast._http import MAX_JSON_BYTES, read_limited
from linecast._runtime import debug_log

PROFILES = ("car", "bike", "foot")

ATTRIBUTION = "Directions © OpenStreetMap contributors"

_PRIMARY = "https://routing.openstreetmap.de/routed-{profile}/route/v1/driving/"
_FALLBACK = "https://router.project-osrm.org/route/v1/driving/"
_QUERY = "?overview=full&geometries=geojson&steps=true"

# FOSSGIS requires a User-Agent that identifies the client and can be
# contacted; a bare "linecast/1.8.0" is not enough.
_UA = f"{USER_AGENT} (+https://github.com/ashuttl/linecast)"

_MIN_INTERVAL = 1.0  # the hosts' published rate limit
_last_request = 0.0  # monotonic stamp of the last network call

_MAX_CACHED = 8
_cache = {}

# URLError and socket.timeout are both OSError; JSONDecodeError is a
# ValueError. A malformed body raises out of _parse instead.
_TRANSPORT = (urllib.error.URLError, OSError, ValueError)
_MALFORMED = (KeyError, IndexError, TypeError, ValueError)


class RouteUnavailable(Exception):
    """The routing service could not be reached or made no sense."""


class NoRoute(Exception):
    """The service answered, but there is no route between these points."""


class Route:
    """One routed line: geometry, totals, and flattened maneuvers."""

    __slots__ = ("coords", "distance_m", "duration_s", "steps", "profile")

    def __init__(self, coords, distance_m, duration_s, steps, profile):
        self.coords = coords  # [(lon, lat)] — GeoJSON order, ready to rasterize
        self.distance_m = distance_m
        self.duration_s = duration_s
        self.steps = steps
        self.profile = profile


def _fetch(url, timeout):
    """The raw request: the decoded JSON body, or an exception."""
    debug_log(f"route fetch {url}")
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(read_limited(resp, MAX_JSON_BYTES))


def _throttle():
    """Sleep out whatever is left of the 1 s gap since the last call."""
    global _last_request
    now = time.monotonic()
    wait = _MIN_INTERVAL - (now - _last_request)
    if wait > 0:
        time.sleep(wait)
        now += wait
    _last_request = now


def _parse(body, profile):
    """An OSRM body -> Route. Raises NoRoute when code != "Ok"."""
    if body.get("code") != "Ok":
        raise NoRoute(body.get("code") or "Unknown")
    routes = body.get("routes") or []
    if not routes:
        raise NoRoute("NoRoute")
    first = routes[0]
    # geojson coordinates are [lon, lat]; keep that order all the way
    # through to the polyline rasterizer
    coords = [(float(c[0]), float(c[1]))
              for c in first["geometry"]["coordinates"]]
    steps = []
    for leg in first.get("legs") or []:
        for step in leg.get("steps") or []:
            man = step.get("maneuver") or {}
            loc = man.get("location")
            steps.append({
                "distance_m": float(step.get("distance") or 0.0),
                "name": step.get("name") or "",  # often "" on ramps
                "ref": step.get("ref"),
                "type": man.get("type") or "",
                "modifier": man.get("modifier"),
                # (lon, lat) like coords, so a step can be flown to
                "location": ((float(loc[0]), float(loc[1]))
                             if loc else None),
            })
    return Route(coords, float(first["distance"]), float(first["duration"]),
                 steps, profile)


def _remember(key, value):
    _cache[key] = value
    if len(_cache) > _MAX_CACHED:
        for old in list(_cache)[:len(_cache) - _MAX_CACHED]:
            _cache.pop(old, None)


def route(profile, origin, dest, timeout=10):
    """Route from origin to dest as (lat, lon) pairs.

    Raises NoRoute when the service says there is none, and
    RouteUnavailable when it could not be asked.
    """
    if profile not in PROFILES:
        raise ValueError(f"unknown routing profile: {profile}")
    olat, olon = origin
    dlat, dlon = dest
    key = (profile, round(olat, 5), round(olon, 5),
           round(dlat, 5), round(dlon, 5))
    hit = _cache.get(key)
    if hit is not None:
        debug_log(f"route cache hit: {key}")
        if isinstance(hit, NoRoute):
            raise NoRoute(*hit.args)
        return hit

    # NB: OSRM wants lon,lat — the reverse of every other coordinate in
    # this codebase
    path = f"{olon},{olat};{dlon},{dlat}{_QUERY}"
    urls = [_PRIMARY.format(profile=profile) + path]
    if profile == "car":
        urls.append(_FALLBACK + path)

    failure = None
    for url in urls:
        _throttle()
        try:
            body = _fetch(url, timeout)
        except _TRANSPORT as exc:
            debug_log(f"route fetch failed: {exc}")
            failure = exc
            continue
        try:
            result = _parse(body, profile)
        except NoRoute as exc:
            _remember(key, exc)  # don't re-ask for a route that isn't there
            raise
        except _MALFORMED as exc:
            debug_log(f"route parse failed: {exc}")
            failure = exc
            continue
        _remember(key, result)
        return result
    raise RouteUnavailable(f"routing service unavailable: {failure}")


def decode_polyline(s, precision=5):
    """Decode an encoded-polyline string to [(lat, lon)].

    Unused while we ask for geometries=geojson, kept as the safety
    valve for a host that ignores the parameter (polyline5 is OSRM's
    default) — and Valhalla's polyline6, hence the precision knob.
    """
    coords, i, lat, lon, f = [], 0, 0, 0, 10 ** precision
    while i < len(s):
        for which in (0, 1):
            shift = result = 0
            while True:
                b = ord(s[i]) - 63
                i += 1
                result |= (b & 0x1F) << shift
                shift += 5
                if b < 0x20:
                    break
            delta = ~(result >> 1) if result & 1 else result >> 1
            if which == 0:
                lat += delta
            else:
                lon += delta
        coords.append((lat / f, lon / f))
    return coords


_MODIFIER_GLYPHS = {
    "uturn": "↺",
    "sharp left": "↰",
    "left": "←",
    "slight left": "↖",
    "straight": "↑",
    "slight right": "↗",
    "right": "→",
    "sharp right": "↱",
}

_TYPE_GLYPHS = {
    "depart": "●",
    "arrive": "◆",
    "roundabout": "↻",
    "rotary": "↻",
    "roundabout turn": "↻",
    "exit roundabout": "↻",
    "exit rotary": "↻",
}


def maneuver_glyph(step):
    """One character for a step's maneuver. The type wins where it
    carries more meaning than the turn direction (a roundabout's
    modifier only says which way you leave it); everything unknown
    falls back to straight-ahead."""
    override = _TYPE_GLYPHS.get(step.get("type"))
    if override:
        return override
    return _MODIFIER_GLYPHS.get(step.get("modifier"), "↑")
