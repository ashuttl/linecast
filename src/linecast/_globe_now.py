"""The sky over the map: daylight and clouds, as they are right now.

Two independent facts, two independent toggles — `s` shades the map
into tonight's darkness and lights its cities, `c` lays this hour's
clouds over it — and both compose with either register, flat or globe.
Nothing here animates: every repaint draws the newest satellite mosaic
and the sun's actual position, and a slow nudge in maps.py (every half
hour) keeps a long-running view honest without ever playing frames.

Clouds ride the LibreWXR global infrared mosaic that already feeds the
radar view's satellite layer: alpha is cloud opacity, coverage runs to
about the 74th parallels, and the newest frame trails real time by an
hour or two.  Poleward of the data the sky simply stays clear, which at
planet scale is the ice caps.  Daylight is astronomy — the subsolar
point from the clock and a civil-twilight ramp — and night dims to a
readable blue rather than black, because a map you cannot read is not
a map.  Cities burn through the dark side, graded by population: the
basemap's own registry doing its best Black Marble.
"""

import math
import threading
import time

from linecast import _radar_tiles as tiles
from linecast._globe import _radius, _source_zoom, forward
from linecast._png import decode_rgba
from linecast._radar_basemap import _load_data
from linecast.sunshine import _declination

ATTRIBUTION = "Clouds: LibreWXR · CC BY 4.0"

# the mosaic ends at the mercator tile edge, like the elevation canvas
_CLOUD_BBOX = (-180.0, -85.05, 180.0, 85.05)
_REFRESH_S = 300     # trust a fetched index this long before re-asking

# night floor per channel: dark enough to read as night, blue enough to
# read as moonlight, bright enough to leave the geography legible
_NIGHT = (0.16, 0.20, 0.30)
_CLOUD_DAY = (236, 240, 244)
_CLOUD_NIGHT = (96, 106, 126)
_CITY_LIGHT = (255, 186, 110)


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
    return _declination(tm.tm_yday), (lon + 180.0) % 360.0 - 180.0


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
_cloud = {"stamp": None, "canvas": None, "checked": 0.0}


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
    prov = _provider()
    idx = tiles.fetch_index(prov, timeout)
    frames = (idx.get("satellite") or {}).get("infrared") or []
    with _cloud_lock:
        _cloud["checked"] = time.time()
    if not frames:
        return False
    z = _source_zoom(zoom, h)
    path = frames[-1]["path"]
    host = idx["host"]
    with _cloud_lock:
        if _cloud["stamp"] == (path, z) and _cloud["canvas"] is not None:
            return False

    def fetch(z_, x, y):
        data = tiles._fetch_tile(prov, host, path, z_, x, y, timeout)
        if data is None:
            return None
        try:
            return decode_rgba(data)
        except Exception:
            return None

    canvas = tiles.stitch_xyz(fetch, _CLOUD_BBOX, z)
    with _cloud_lock:
        _cloud["stamp"] = (path, z)
        _cloud["canvas"] = canvas
    return True


def clouds(lls, canvas):
    """Per-sample cloud opacity 0..1, bilinear over the mosaic's alpha.

    Alpha 0 is clear sky and no-data alike, which is the honest merge:
    where the geostationary ring cannot see, nothing is drawn.
    """
    buf, cw, ch, org_x, org_y, world = canvas
    out = []
    for row in lls:
        o = []
        for ll in row:
            if ll is None:
                o.append(0.0)
                continue
            lat = min(85.05, max(-85.05, ll[0]))
            wx, wy = tiles._lonlat_to_world(ll[1], lat)
            fx = wx * world - org_x - 0.5
            fy = min(max(wy * world - org_y - 0.5, 0.0), ch - 1.0)
            x0 = int(fx) % cw
            x1 = (x0 + 1) % cw
            y0 = int(fy)
            y1 = min(y0 + 1, ch - 1)
            tx, ty = fx - int(fx), fy - y0
            a = ((buf[(y0 * cw + x0) * 4 + 3] * (1 - tx)
                  + buf[(y0 * cw + x1) * 4 + 3] * tx) * (1 - ty)
                 + (buf[(y1 * cw + x0) * 4 + 3] * (1 - tx)
                    + buf[(y1 * cw + x1) * 4 + 3] * tx) * ty)
            o.append(a / 255.0)
        out.append(o)
    return out


def _light_weight(pop):
    """Population → glow 0..1: a town glimmers, a megacity blazes."""
    return max(0.0, min(1.0, (math.log10(max(pop, 1.0)) - 4.0) / 3.5))


def city_lights_globe(lat0, lon0, zoom, gw, h):
    """{(x, y): glow} on the gw×h sub-pixel grid, orthographic."""
    r = _radius(zoom, h)
    out = {}
    for entry in _load_data()["cities"]:
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


def apply(buf, day, cloud, lights):
    """Shade a sub-pixel RGB buffer into this moment, in place.

    `day` and `cloud` are each optional, because the sun and the
    clouds are separate facts about the sky: without `day` every
    sample counts as noon (clouds still whiten it); without `cloud`
    the sky is simply clear.  Order is the physics: clouds reflect
    the sunlight, night falls on clouds and ground alike, the
    infrared keeps night clouds faintly slate, and the cities burn
    through last.  A None pixel (a palette that paints no fills)
    stays None — there is nothing there to shade.
    """
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
                r *= _NIGHT[0] + (1.0 - _NIGHT[0]) * d
                g *= _NIGHT[1] + (1.0 - _NIGHT[1]) * d
                b *= _NIGHT[2] + (1.0 - _NIGHT[2]) * d
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
