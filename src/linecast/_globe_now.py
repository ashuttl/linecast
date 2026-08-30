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
hour or two.  Poleward of the geostationary ring nothing sees at all,
so the mosaic is continued rather than replaced: fractal noise
generated on the sphere itself — Photoshop's old Clouds filter, bent
around a globe so the pole holds no pinch and the antimeridian no
seam — is developed against the mosaic's own last healthy ring,
sector of longitude by sector, cloudy where the ring is cloudy, clear
where it is clear, at the white the ring actually paints.  Invented
weather, deliberately: nobody reads a forecast off the top of the
planet, and a cap that belongs to the picture beats a truthful hole
in it.  Daylight is astronomy — the subsolar
point from the clock and a civil-twilight ramp — and night dims to a
readable blue rather than black, because a map you cannot read is not
a map.  Cities burn through the dark side, graded by population: the
basemap's own registry doing its best Black Marble.
"""

import math
import threading
import time

from linecast import _radar_tiles as tiles
from linecast._geo import wrap_lon
from linecast._globe import _radius, _source_zoom, bilinear_taps, forward
from linecast._png import decode_rgba
from linecast._radar_basemap import _load_data
from linecast._runtime import log_failure
from linecast._scenes import Memo
from linecast._theme import themed
from linecast.sunshine import _declination

ATTRIBUTION = "Clouds: LibreWXR · CC BY 4.0"

# the mosaic ends at the mercator tile edge, like the elevation canvas
_CLOUD_BBOX = (-180.0, -85.05, 180.0, 85.05)
_REFRESH_S = 300     # trust a fetched index this long before re-asking

# the mosaic's alpha feathers to nothing between about the 70th and
# 72.6th parallels (measured; the ring's horizon, softened upstream).
# The cap's billows seed in from just below the feather and close to
# the ring's own cover right where it dies, so the two sources overlap
# and their max() never dips between them
_CAP_FADE0, _CAP_FULL = 68.5, 72.0
# how far the noise lets that band wander off its parallels: a border
# drawn at one exact latitude is the first thing the eye finds
_CAP_WOBBLE = 1.6
# the deck's white when the mosaic offers no measure of its own
_CAP_WHITE = 0.7
# the ring's cloudiness is measured into this many longitude sectors;
# poleward of _CAP_BLEND0 the cap settles toward the ring's mean,
# because at the pole every longitude is the same place
_CAP_SECT = 48
_CAP_BLEND0 = 78.0

# the fBm octaves (frequency over the unit sphere, weight): billow
# scales near what the mosaic's own pixels paint at planet zoom
_NOISE_OCTAVES = ((11.0, 0.5), (23.0, 0.3), (47.0, 0.2))


def _lattice(ix, iy, iz):
    """A stable pseudo-random 0..1 for one noise lattice point."""
    h = (ix * 374761393 + iy * 668265263 + iz * 2246822519) & 0xFFFFFFFF
    h = ((h ^ (h >> 13)) * 1274126177) & 0xFFFFFFFF
    return ((h ^ (h >> 16)) & 0xFFFF) / 65535.0


def _fbm(lat, lon):
    """Fractal cloud noise 0..1 at one point of the sphere.

    Value noise summed over octaves of the point's position in space,
    not of its coordinates: the texture owns no graticule, so the pole
    wears billows like everywhere else instead of the pinch every flat
    anchoring makes, and the antimeridian is nowhere.  Deterministic
    on purpose: the billows stay put under a drag and from one repaint
    to the next — weather, not static.
    """
    phi, lam = math.radians(lat), math.radians(lon)
    cp = math.cos(phi)
    x = cp * math.cos(lam) + 1.0
    y = cp * math.sin(lam) + 1.0
    z = math.sin(phi) + 1.0
    n = 0.0
    for freq, weight in _NOISE_OCTAVES:
        fx, fy, fz = x * freq, y * freq, z * freq
        ix, iy, iz = int(fx), int(fy), int(fz)
        tx, ty, tz = fx - ix, fy - iy, fz - iz
        tx = tx * tx * (3.0 - 2.0 * tx)
        ty = ty * ty * (3.0 - 2.0 * ty)
        tz = tz * tz * (3.0 - 2.0 * tz)
        e = _lattice(ix, iy, iz)
        e += (_lattice(ix + 1, iy, iz) - e) * tx
        f = _lattice(ix, iy + 1, iz)
        f += (_lattice(ix + 1, iy + 1, iz) - f) * tx
        near = e + (f - e) * ty
        e = _lattice(ix, iy, iz + 1)
        e += (_lattice(ix + 1, iy, iz + 1) - e) * tx
        f = _lattice(ix, iy + 1, iz + 1)
        f += (_lattice(ix + 1, iy + 1, iz + 1) - f) * tx
        far = e + (f - e) * ty
        n += (near + (far - near) * tz) * weight
    return n


# the noise, tabulated: clouds() runs for every sub-pixel of every
# drag frame, so per sample the texture must cost a lookup, not two
# dozen hashes.  The generator is sampled once onto a half-degree ring
# of the polar band — finer than its smallest billow — and read back
# bilinearly; the table stores a field that is smooth on the sphere,
# so reading it through the graticule reintroduces no pinch.  Indexed
# by |lat|: the caps share a pattern no view can see both of.  Built
# on first need; refresh() warms it off the paint path.  A concurrent
# build is benign — both threads compute the same deterministic table.
_NOISE_STEP = 0.5
_NOISE_LAT0 = 66.0
_NOISE_COLS = int(360.0 / _NOISE_STEP)  # divides evenly: lon wraps
_NOISE_ROWS = int((90.0 - _NOISE_LAT0) / _NOISE_STEP) + 1
_noise_table = None


def _noise_grid():
    global _noise_table
    if _noise_table is None:
        raw = [_fbm(_NOISE_LAT0 + r * _NOISE_STEP,
                    -180.0 + k * _NOISE_STEP)
               for r in range(_NOISE_ROWS)
               for k in range(_NOISE_COLS)]
        # rank-flattened: interpolated value noise pools around its
        # mean, which would squeeze every billow threshold into a
        # narrow band.  Spread evenly, cover maps to billow density
        # one for one.
        table = [0.0] * len(raw)
        last = len(raw) - 1.0
        for rank, i in enumerate(sorted(range(len(raw)),
                                        key=raw.__getitem__)):
            table[i] = rank / last
        _noise_table = table
    return _noise_table

# night floor per channel: dark enough to read as night, blue enough to
# read as moonlight, bright enough to leave the geography legible.
# The sky's inks pass through the theme's hue transfer like the ground's
# (_theme.themed), so night on a green-monochrome terminal is green
# moonlight and its cities burn in the theme's own warm.
#
# The street register keeps a higher floor, in either projection,
# because it has nothing else: terrain's night is carried by the city
# lights burning back through it, and street draws none — crush its
# fills as far and the land and the sea are one black shape until the
# terminator comes round.
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


def ink_dusk(lls, sun, night, gw, hc):
    """Per-cell RGB multipliers for braille ink, following the fills.

    apply() scales each fill channel by ``night + (1 - night) * day``;
    the same factor, averaged over a cell's two sub-pixels, dims the
    strokes drawn across it so a coastline on the night side fades
    with the sea it outlines instead of glowing at noon brightness.
    Space (None) counts as noon: nothing there is dark, only empty.
    """
    day = daylight(lls, sun)
    out = []
    for cy in range(hc):
        top, bot = day[cy * 2], day[cy * 2 + 1]
        row = []
        for cx in range(gw):
            a, b = top[cx], bot[cx]
            d = ((1.0 if a is None else a) + (1.0 if b is None else b)) / 2
            row.append(None if d >= 1.0 else
                       tuple(n + (1.0 - n) * d for n in night))
        out.append(row)
    return out


def dim_ink(ink, factor):
    """`ink` scaled by an ink_dusk factor; either None passes through."""
    if ink is None or factor is None:
        return ink
    return (int(ink[0] * factor[0]), int(ink[1] * factor[1]),
            int(ink[2] * factor[2]))


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
_cloud = {"stamp": None, "canvas": None, "checked": 0.0, "white": None,
          "cover": None}


def _mosaic_white(canvas):
    """What the mosaic calls cloud, measured where it still sees.

    Mean alpha of the clearly cloudy pixels in the bands just
    equatorward of the feather, both hemispheres — the brightness the
    cap must not outshine.  None when the canvas is too empty to say.
    """
    buf, cw, ch, _org_x, org_y, world = canvas
    total = count = 0
    for sign in (1.0, -1.0):
        for k in range(17):
            sn = math.sin(math.radians(sign * (62.0 + k * 0.5)))
            y = int((0.5 - math.log((1 + sn) / (1 - sn))
                     / (4 * math.pi)) * world - org_y)
            if not 0 <= y < ch:
                continue
            base = y * cw * 4
            for x in range(0, cw, 2):
                a = buf[base + x * 4 + 3]
                if a > 40:
                    total += a
                    count += 1
    if count < 200:
        return None
    return min(0.85, max(0.5, total / count / 255.0))


def _ring_cover(canvas, white):
    """The ring's cloudiness by longitude sector, per hemisphere.

    Mean alpha over the last band the mosaic sees whole, folded by
    `white` into the cover fraction the cap continues poleward: a
    cloudy sector gets a cloudy cap, a clear sector a clear one, and
    the hand-off matches by construction.  {northern: (sectors, mean)}
    with a smoothing pass so no sector edge ever lands in the picture;
    None when the canvas is too empty to say.
    """
    buf, cw, ch, org_x, org_y, world = canvas
    out = {}
    for northern, sign in ((True, 1.0), (False, -1.0)):
        sums = [0.0] * _CAP_SECT
        counts = [0] * _CAP_SECT
        for k in range(12):
            sn = math.sin(math.radians(sign * (63.5 + k * 0.5)))
            y = int((0.5 - math.log((1 + sn) / (1 - sn))
                     / (4 * math.pi)) * world - org_y)
            if not 0 <= y < ch:
                continue
            base = y * cw * 4
            for x in range(cw):
                s = int((x + org_x + 0.5) * _CAP_SECT / world) % _CAP_SECT
                sums[s] += buf[base + x * 4 + 3]
                counts[s] += 1
        if sum(counts) < 200:
            return None
        mean = [sums[i] / counts[i] / 255.0 if counts[i] else 0.0
                for i in range(_CAP_SECT)]
        mean = [(mean[i - 1] + 2 * mean[i] + mean[(i + 1) % _CAP_SECT]) / 4
                for i in range(_CAP_SECT)]
        cov = [min(1.0, m / white) for m in mean]
        out[northern] = (cov, sum(cov) / _CAP_SECT)
    return out


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
    _noise_grid()  # warmed here, off the paint path
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
        except Exception as exc:
            log_failure("maps/clouds", f"satellite tile {z_}/{x}/{y} decode", exc,
                        fallback="tile left transparent")
            return None

    canvas = tiles.stitch_xyz(fetch, _CLOUD_BBOX, z)
    white = _mosaic_white(canvas)
    cover = _ring_cover(canvas, white or _CAP_WHITE)
    with _cloud_lock:
        _cloud["stamp"] = (path, z)
        _cloud["canvas"] = canvas
        _cloud["white"] = white
        _cloud["cover"] = cover
    return True


def clouds(lls, canvas):
    """Per-sample cloud opacity 0..1, bilinear over the mosaic's alpha.

    Alpha 0 is clear sky and no-data alike, which is the honest merge
    equatorward: where the mosaic is dark, the sky is clear.  Poleward
    the cap takes over: the sphere's fractal noise, developed against
    the ring's measured cover.  A sector's cloudiness decides what
    fraction of its billows are cloud — a cloudy ring closing to a
    deck, a clear one staying clear — the billow a sample falls in
    grades its brightness under the ring's own white, and the two
    sources merge with max() across an overlapping fade, so neither
    edge ever shows.  The same noise wobbles the fade band off its
    parallels.
    """
    buf = canvas[0]
    cover = _cloud.get("cover")
    noise = _noise_grid() if cover is not None else None
    white = _cloud.get("white") or _CAP_WHITE
    edge0 = _CAP_FADE0 - _CAP_WOBBLE / 2
    fade = _CAP_FULL - _CAP_FADE0
    sect_w = 360.0 / _CAP_SECT
    blend = 90.0 - _CAP_BLEND0
    cols, rows = _NOISE_COLS, _NOISE_ROWS
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
            alat = ll[0] if ll[0] > 0.0 else -ll[0]
            if cover is not None and alat > edge0:
                fx = (ll[1] + 180.0) % 360.0 / _NOISE_STEP
                fy = (alat - _NOISE_LAT0) / _NOISE_STEP
                x0 = int(fx)
                nx = fx - x0
                x1 = (x0 + 1) % cols
                y0 = int(fy)
                if y0 > rows - 2:
                    y0 = rows - 2
                ny = fy - y0
                b0 = y0 * cols
                b1 = b0 + cols
                top = noise[b0 + x0]
                top += (noise[b0 + x1] - top) * nx
                bot = noise[b1 + x0]
                bot += (noise[b1 + x1] - bot) * nx
                v = top + (bot - top) * ny
                t = (alat + (v - 0.5) * _CAP_WOBBLE - _CAP_FADE0) / fade
                if t > 0.0:
                    if t > 1.0:
                        t = 1.0
                    ring, mean = cover[ll[0] > 0.0]
                    f = ((ll[1] + 180.0) / sect_w
                         + _CAP_SECT - 0.5) % _CAP_SECT
                    s0 = int(f)
                    c = ring[s0] + (ring[(s0 + 1) % _CAP_SECT]
                                    - ring[s0]) * (f - s0)
                    w = (alat - _CAP_BLEND0) / blend
                    if w > 0.0:
                        w = w * w * (3.0 - 2.0 * w)
                        c += (mean - c) * w
                    c *= t
                    u = (v - 1.0 + 1.5 * c) * 2.0
                    if u > 0.0:
                        if u > 1.0:
                            u = 1.0
                        u = u * u * (3.0 - 2.0 * u)
                        m = u * white * (0.55 + 0.7 * v)
                        if m > a:
                            a = m if m < 1.0 else 1.0
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
