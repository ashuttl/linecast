"""The sky over the map: daylight and clouds, as they are right now.

Two independent facts, two independent toggles — `s` shades the map
into tonight's darkness and lights its cities, `c` lays this hour's
clouds over it — and both compose with either register, flat or globe.
Nothing here animates: every repaint draws the newest satellite mosaic
and the sun's actual position, and a slow nudge in maps.py (every half
hour) keeps a long-running view honest without ever playing frames.

Clouds ride the LibreWXR global infrared mosaic that already feeds the
radar view's satellite layer: alpha is cloud opacity, coverage runs to
about the 72nd parallels, and the newest frame trails real time by an
hour or two.  Poleward of the geostationary ring a coarse Open-Meteo
cloud-cover lattice stands in — model, not satellite, the same trade
the radar view makes where no radar reaches — fading in exactly where
the mosaic's own feathered edge fades out, so a pole-centred globe
doesn't wear a moat of suspiciously clear sky.  Daylight is astronomy — the subsolar
point from the clock and a civil-twilight ramp — and night dims to a
readable blue rather than black, because a map you cannot read is not
a map.  Cities burn through the dark side, graded by population: the
basemap's own registry doing its best Black Marble.
"""

import datetime
import math
import threading
import time

from linecast import _radar_tiles as tiles
from linecast._cache import read_cache, read_stale, write_cache
from linecast._geo import wrap_lon
from linecast._globe import _radius, _source_zoom, bilinear_taps, forward
from linecast._http import fetch_json
from linecast._paths import cache_dir
from linecast._png import decode_rgba
from linecast._radar_basemap import _load_data
from linecast._runtime import log_failure
from linecast._scenes import Memo
from linecast._theme import themed
from linecast.sunshine import _declination

ATTRIBUTION = "Clouds: LibreWXR + Open-Meteo · CC BY 4.0"

# the mosaic ends at the mercator tile edge, like the elevation canvas
_CLOUD_BBOX = (-180.0, -85.05, 180.0, 85.05)
_REFRESH_S = 300     # trust a fetched index this long before re-asking

# polar cap lattice: rings of Open-Meteo cloud cover poleward of the
# mosaic, one point at each pole.  Coarse on purpose — at planet scale
# a whole cap is a hundred pixels — and hourly, so one fetch a quarter
# of a day keeps a long-running view honest.
_CAP_LATS = [72.0, 76.0, 80.0, 84.0, 88.0]
_CAP_NLON = 12
_CAP_TTL = 6 * 3600
# the mosaic's own alpha feathers to nothing between these parallels
# (measured; the ring's horizon, softened upstream) — the model fades
# in over the same band, so neither source ever shows an edge
_CAP_FADE0, _CAP_FADE1 = 70.0, 72.6

# night floor per channel: dark enough to read as night, blue enough to
# read as moonlight, bright enough to leave the geography legible.
# The sky's inks pass through the theme's hue transfer like the ground's
# (_theme.themed), so night on a green-monochrome terminal is green
# moonlight and its cities burn in the theme's own warm.
#
# The street planet keeps a higher floor, because it has nothing else:
# terrain's night is carried by the city lights burning through it, and
# the street map draws none — crush its two fills as far and the land
# and the sea are one black shape until the terminator comes round.
def _rebuild():
    global _NIGHT, NIGHT_STREET, _CLOUD_DAY, _CLOUD_NIGHT, _CITY_LIGHT
    _NIGHT = tuple(c / 255.0 for c in themed((41, 51, 77)))
    NIGHT_STREET = tuple(c / 255.0 for c in themed((108, 118, 140)))
    _CLOUD_DAY = themed((236, 240, 244))
    _CLOUD_NIGHT = themed((96, 106, 126))
    _CITY_LIGHT = themed((255, 186, 110))


_rebuild()
from linecast import _theme  # noqa: E402 — the hook needs the palette above
_theme.on_reload(_rebuild)


def subsolar(t=None):
    """(lat, lon) of the point under the sun at unix time `t` (now).

    Declination shares sunshine's formula; the longitude adds the
    equation of time, worth up to four degrees — a braille cell's worth
    of terminator at planet scale.
    """
    tm = time.gmtime(time.time() if t is None else t)
    utc_h = tm.tm_hour + tm.tm_min / 60.0 + tm.tm_sec / 3600.0
    b = math.radians(360.0 / 364.0 * (tm.tm_yday - 81))
    eot_min = (9.87 * math.sin(2 * b) - 7.53 * math.cos(b)
               - 1.5 * math.sin(b))
    lon = 15.0 * (12.0 - utc_h - eot_min / 60.0)
    return _declination(tm.tm_yday), wrap_lon(lon)


def daylight(lls, sun):
    """Per-sample day factor: 1 in sunshine, 0 at night, None in space.

    The ramp runs from civil twilight's far edge (sun 9° down) to a few
    degrees of morning, smoothstepped — the terminator is a band, not
    a line, and the band is what makes the sphere read as lit.
    """
    sin_d = math.sin(math.radians(sun[0]))
    cos_d = math.cos(math.radians(sun[0]))
    out = []
    for row in lls:
        o = []
        for ll in row:
            if ll is None:
                o.append(None)
                continue
            phi = math.radians(ll[0])
            cos_z = (math.sin(phi) * sin_d + math.cos(phi) * cos_d
                     * math.cos(math.radians(ll[1] - sun[1])))
            elev = math.degrees(math.asin(max(-1.0, min(1.0, cos_z))))
            t = max(0.0, min(1.0, (elev + 9.0) / 12.0))
            o.append(t * t * (3.0 - 2.0 * t))
        out.append(o)
    return out


def flat_lls(bbox, w, h):
    """The (lat, lon) under each sample of a flat w×h view.

    What geometry() is to the globe, one line of arithmetic is to the
    flat map — this exists so daylight and clouds shade either
    projection through the same functions.
    """
    minlon, minlat, maxlon, maxlat = bbox
    return [[(maxlat - (maxlat - minlat) * (y + 0.5) / h,
              minlon + (maxlon - minlon) * (x + 0.5) / w)
             for x in range(w)] for y in range(h)]


_cloud_lock = threading.Lock()
_cloud = {"stamp": None, "canvas": None, "checked": 0.0, "cap": None}


def _fetch_cap(timeout):
    """One request for both caps: hourly cover at every lattice point."""
    pts = []
    for sign in (1.0, -1.0):
        for alat in _CAP_LATS:
            for k in range(_CAP_NLON):
                pts.append((sign * alat, -180.0 + k * 360.0 / _CAP_NLON))
        pts.append((sign * 90.0, 0.0))
    lat_q = ",".join(f"{lat:.1f}" for lat, _ in pts)
    lon_q = ",".join(f"{lon:.1f}" for _, lon in pts)
    url = ("https://api.open-meteo.com/v1/forecast"
           f"?latitude={lat_q}&longitude={lon_q}"
           "&hourly=cloud_cover&forecast_days=2&timezone=UTC")
    results = fetch_json(url, timeout=timeout)
    if isinstance(results, dict):
        results = [results]
    cover = [[x if x is not None else 0.0
              for x in p["hourly"]["cloud_cover"]] for p in results]
    return {"times": results[0]["hourly"]["time"], "cover": cover}


def _refresh_cap(timeout):
    """Bring the polar lattice up to date.  Returns True when it changed.

    Same fallback posture as the mosaic: a stale lattice on a network
    failure beats a clear pole that isn't.
    """
    cpath = cache_dir("maps", "polar_clouds.json")
    payload = read_cache(cpath, _CAP_TTL)
    if payload is None:
        try:
            payload = _fetch_cap(timeout)
            write_cache(cpath, payload)
        except Exception as exc:
            payload = read_stale(cpath)
            log_failure("maps/clouds", "polar cap fetch", exc, url="api.open-meteo.com",
                        fallback="stale cache" if payload is not None else "no polar cap")
    if payload is None or payload == _cloud.get("cap"):
        return False
    with _cloud_lock:
        _cloud["cap"] = payload
    return True


def _cap_grids():
    """Per-hemisphere cover rings for this hour, or None.

    {northern: [ring][lon_idx]} in cover fraction 0..1, the pole's
    single point widened into a ring of its own so bilinear sampling
    needs no special case at 90°.
    """
    cap = _cloud.get("cap")
    if cap is None:
        return None
    now = datetime.datetime.now(datetime.timezone.utc)
    times = [datetime.datetime.fromisoformat(t).replace(
        tzinfo=datetime.timezone.utc) for t in cap["times"]]
    t = min(range(len(times)),
            key=lambda i: abs((times[i] - now).total_seconds()))
    per, block = _CAP_NLON, len(_CAP_LATS) * _CAP_NLON + 1
    grids = {}
    for northern, base in ((True, 0), (False, block)):
        rings = [[cap["cover"][base + r * per + k][t] / 100.0
                  for k in range(per)] for r in range(len(_CAP_LATS))]
        rings.append([cap["cover"][base + block - 1][t] / 100.0] * per)
        grids[northern] = rings
    return grids


def _cap_cover(grids, lat, lon):
    """Bilinear cover fraction at a point, lon wrapping, lat clamped."""
    rings = grids[lat > 0]
    ring_lats = _CAP_LATS
    alat = min(abs(lat), 90.0)
    r = len(ring_lats) - 1
    for i in range(len(ring_lats) - 1):
        if alat <= ring_lats[i + 1]:
            r = i
            break
    span = (90.0 if r == len(ring_lats) - 1 else ring_lats[r + 1]) \
        - ring_lats[r]
    ty = max(0.0, min(1.0, (alat - ring_lats[r]) / span))
    fx = (lon + 180.0) % 360.0 / (360.0 / _CAP_NLON)
    k0 = int(fx) % _CAP_NLON
    k1 = (k0 + 1) % _CAP_NLON
    tx = fx - int(fx)
    top = rings[r][k0] + (rings[r][k1] - rings[r][k0]) * tx
    bot = rings[r + 1][k0] + (rings[r + 1][k1] - rings[r + 1][k0]) * tx
    return top + (bot - top) * ty


def _provider():
    # colour scheme is irrelevant to satellite tiles; 0 matches the
    # radar view's satellite layer so both share one tile cache
    return tiles.satellite_provider(tiles.librewxr_provider(0))


def peek():
    """The stitched cloud canvas, or None — never the network."""
    return _cloud["canvas"]


def stale():
    """True when the index deserves another look."""
    return time.time() - _cloud["checked"] > _REFRESH_S


def refresh(zoom, h, timeout=15):
    """Bring the canvas to the newest mosaic frame.  Blocking.

    Returns True when the canvas changed.  A canvas, once stitched, is
    never dropped on failure — stale clouds over a live terminator beat
    no clouds at all.
    """
    cap_changed = _refresh_cap(timeout)
    prov = _provider()
    idx = tiles.fetch_index(prov, timeout)
    frames = (idx.get("satellite") or {}).get("infrared") or []
    with _cloud_lock:
        _cloud["checked"] = time.time()
    if not frames:
        return cap_changed
    z = _source_zoom(zoom, h)
    path = frames[-1]["path"]
    host = idx["host"]
    with _cloud_lock:
        if _cloud["stamp"] == (path, z) and _cloud["canvas"] is not None:
            return cap_changed

    def fetch(z_, x, y):
        data = tiles._fetch_tile(prov, host, path, z_, x, y, timeout)
        if data is None:
            return None
        try:
            return decode_rgba(data)
        except Exception as exc:
            log_failure("maps/clouds", f"satellite tile {z_}/{x}/{y} decode", exc,
                        fallback="tile left transparent")
            return None

    canvas = tiles.stitch_xyz(fetch, _CLOUD_BBOX, z)
    with _cloud_lock:
        _cloud["stamp"] = (path, z)
        _cloud["canvas"] = canvas
    return True


def clouds(lls, canvas):
    """Per-sample cloud opacity 0..1, bilinear over the mosaic's alpha.

    Alpha 0 is clear sky and no-data alike, which is the honest merge
    equatorward: where the mosaic is dark, the sky is clear.  Poleward
    the model lattice takes over, smoothstepped in across the band
    where the mosaic's own edge feathers away, and the two are merged
    with max() — whichever source sees cloud there, cloud is drawn.
    """
    buf = canvas[0]
    grids = _cap_grids()
    out = []
    for row in lls:
        o = []
        for ll, tap in zip(row, bilinear_taps(row, canvas)):
            if tap is None:
                o.append(0.0)
                continue
            j00, j01, j10, j11, tx, ty = tap
            a = ((buf[j00 + 3] * (1 - tx) + buf[j01 + 3] * tx) * (1 - ty)
                 + (buf[j10 + 3] * (1 - tx) + buf[j11 + 3] * tx) * ty) / 255.0
            if grids is not None and abs(ll[0]) > _CAP_FADE0:
                t = min(1.0, (abs(ll[0]) - _CAP_FADE0)
                        / (_CAP_FADE1 - _CAP_FADE0))
                t = t * t * (3.0 - 2.0 * t)
                c = _cap_cover(grids, ll[0], ll[1])
                # cover fraction → opacity, graded so scattered cloud
                # stays a veil and full deck matches the mosaic's white
                a = max(a, t * c * c * 0.85)
            o.append(a)
        out.append(o)
    return out


def _light_weight(pop):
    """Population → glow 0..1: a town glimmers, a megacity blazes."""
    return max(0.0, min(1.0, (math.log10(max(pop, 1.0)) - 4.0) / 3.5))


# city_lights_globe() memo: the lights depend only on the view, but the
# sun toggle asks for them on every repaint.  Keyed with the cities
# list's identity so swapped-in test data misses.
_LIGHTS_KEEP = 4
_lights_cache = Memo(keep=_LIGHTS_KEEP)
_lights_lock = threading.Lock()  # view workers ask concurrently


def city_lights_globe(lat0, lon0, zoom, gw, h):
    """{(x, y): glow} on the gw×h sub-pixel grid, orthographic.

    Memoised per view: the dict is shared between calls, so read it.
    """
    cities = _load_data()["cities"]
    key = (lat0, lon0, zoom, gw, h, id(cities))
    with _lights_lock:
        hit = _lights_cache.get(key)
    if hit is not None:
        return hit
    hit = _light_cities(cities, lat0, lon0, zoom, gw, h)
    with _lights_lock:
        _lights_cache.put(key, hit)
    return hit


def _light_cities(cities, lat0, lon0, zoom, gw, h):
    r = _radius(zoom, h)
    out = {}
    for entry in cities:
        w = _light_weight(entry[2])
        if w <= 0.0:
            continue
        ux, uy, cos_c = forward(entry[1], entry[0], lat0, lon0)
        if cos_c <= 0.0:
            continue
        x = int(gw / 2.0 + ux * r)
        y = int(h / 2.0 - uy * r)
        if 0 <= x < gw and 0 <= y < h:
            out[(x, y)] = max(out.get((x, y), 0.0), w)
    return out


def city_lights_flat(bbox, gw, h):
    """{(x, y): glow} on the gw×h sub-pixel grid, equirectangular."""
    minlon, minlat, maxlon, maxlat = bbox
    lon_span, lat_span = maxlon - minlon, maxlat - minlat
    out = {}
    for entry in _load_data()["cities"]:
        w = _light_weight(entry[2])
        if w <= 0.0:
            continue
        x = int((entry[0] - minlon) / lon_span * gw)
        y = int((maxlat - entry[1]) / lat_span * h)
        if 0 <= x < gw and 0 <= y < h:
            out[(x, y)] = max(out.get((x, y), 0.0), w)
    return out


def apply(buf, day, cloud, lights, night=None):
    """Shade a sub-pixel RGB buffer into this moment, in place.

    `day` and `cloud` are each optional, because the sun and the
    clouds are separate facts about the sky: without `day` every
    sample counts as noon (clouds still whiten it); without `cloud`
    the sky is simply clear.  Order is the physics: clouds reflect
    the sunlight, night falls on clouds and ground alike, the
    infrared keeps night clouds faintly slate, and the cities burn
    through last.  A None pixel (a palette that paints no fills)
    stays None — there is nothing there to shade.

    `night` overrides the night floor, for a register whose night has
    no lights to carry it.
    """
    if night is None:
        night = _NIGHT
    for y, row in enumerate(buf):
        d_row = day[y] if day is not None else None
        c_row = cloud[y] if cloud is not None else None
        for x, px in enumerate(row):
            d = d_row[x] if d_row is not None else 1.0
            if d is None or px is None:
                continue
            r, g, b = px
            c = c_row[x] if c_row is not None else 0.0
            if c > 0.02:
                a = c * 0.85
                r += (_CLOUD_DAY[0] - r) * a
                g += (_CLOUD_DAY[1] - g) * a
                b += (_CLOUD_DAY[2] - b) * a
            if d < 1.0:
                r *= night[0] + (1.0 - night[0]) * d
                g *= night[1] + (1.0 - night[1]) * d
                b *= night[2] + (1.0 - night[2]) * d
                if c > 0.02:
                    a = c * 0.35 * (1.0 - d)
                    r += (_CLOUD_NIGHT[0] - r) * a
                    g += (_CLOUD_NIGHT[1] - g) * a
                    b += (_CLOUD_NIGHT[2] - b) * a
            row[x] = (int(r), int(g), int(b))
    if day is None:
        return
    for (x, y), w in lights.items():
        d = day[y][x]
        if d is None or d > 0.7 or buf[y][x] is None:
            continue
        r, g, b = buf[y][x]
        a = w * (1.0 - d) * 0.9
        buf[y][x] = (int(r + (_CITY_LIGHT[0] - r) * a),
                     int(g + (_CITY_LIGHT[1] - g) * a),
                     int(b + (_CITY_LIGHT[2] - b) * a))
