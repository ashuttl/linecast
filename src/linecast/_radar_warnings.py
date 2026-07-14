"""Storm-based warning polygons for the radar view.

NWS warnings for tornado, severe thunderstorm, flash flood, special marine,
and snow squall are issued as literal lat/lon polygons ("storm-based
warnings").  IEM — the same provider as the CONUS radar frames — serves them
as GeoJSON, and its ``?ts=`` parameter returns the polygons valid at any past
instant, so warnings rewind in lockstep with the radar timeline.

Warnings are geographic (not view-dependent): the raw polygon list is cached
per frame timestamp and rasterised per view by the renderer.
"""

import threading

from linecast._http import fetch_json

_URL = "https://mesonet.agron.iastate.edu/geojson/sbw.geojson"

# phenomena code -> outline colour, in conventional NWS map colours,
# listed least-severe-first (the draw order, so severe wins overlaps)
WARNING_COLORS = {
    "MA": (255, 145, 40),   # special marine — orange
    "SQ": (198, 125, 255),  # snow squall — violet
    "FF": (90, 220, 110),   # flash flood — green
    "SV": (255, 205, 60),   # severe thunderstorm — yellow
    "TO": (255, 65, 65),    # tornado — red
}
EMERGENCY = (255, 80, 220)  # tornado/flash-flood emergency — magenta
_SEVERITY = {p: i for i, p in enumerate(WARNING_COLORS)}

# NWS coverage incl. Alaska/Hawaii/Puerto Rico/Guam-adjacent waters; views
# entirely outside skip the fetch
_US_BOX = (-180.0, 15.0, -60.0, 72.0)

_cache = {}   # ts key -> [(severity, color, rings), ...]
_lock = threading.Lock()
_MAX_CACHED = 48  # a little over the radar rewind window


def covers(bbox):
    """Could this view contain NWS warnings at all?"""
    minlon, minlat, maxlon, maxlat = bbox
    w, s, e, n = _US_BOX
    return not (maxlon < w or minlon > e or maxlat < s or minlat > n)


def _key(when):
    return when.strftime("%Y%m%dT%H%M")


def _parse(feature_collection):
    """GeoJSON -> [(severity, color, rings)] sorted least-severe-first."""
    out = []
    for ft in feature_collection.get("features", ()):
        props = ft.get("properties", {})
        phen = props.get("phenomena")
        if props.get("significance") != "W" or phen not in WARNING_COLORS:
            continue
        color = (EMERGENCY if props.get("is_emergency")
                 else WARNING_COLORS[phen])
        g = ft.get("geometry") or {}
        polys = ([g["coordinates"]] if g.get("type") == "Polygon"
                 else g["coordinates"] if g.get("type") == "MultiPolygon"
                 else [])
        rings = [ring for poly in polys for ring in poly if len(ring) >= 4]
        if rings:
            # emergencies above their base phenomena, severe above the rest
            sev = _SEVERITY[phen] + (10 if props.get("is_emergency") else 0)
            out.append((sev, color, rings))
    out.sort(key=lambda w: w[0])
    return out


def warnings_at(when):
    """Warnings valid at `when` (UTC). Fetches on miss; raises on failure."""
    key = _key(when)
    with _lock:
        hit = _cache.get(key)
    if hit is not None:
        return hit
    raw = fetch_json(f"{_URL}?ts={when.strftime('%Y-%m-%dT%H:%M:%SZ')}")
    parsed = _parse(raw)
    with _lock:
        _cache[key] = parsed
        if len(_cache) > _MAX_CACHED:
            for old in list(_cache)[:len(_cache) - _MAX_CACHED]:
                _cache.pop(old, None)
    return parsed


def cached_at(when):
    """Cache-only lookup; never touches the network. None if not warmed."""
    with _lock:
        return _cache.get(_key(when))
