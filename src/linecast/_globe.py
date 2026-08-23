"""Orthographic globe for planet-scale zooms.

Web Mercator is the right projection for a street you walk and the
wrong one for a planet you regard: zoomed far enough out, Greenland
balloons, the poles smear into taffy, and there is an edge of the
world.  Past ZOOM_DEG the terrain view hands its geometry to this
module — for each sub-pixel, invert an orthographic projection to a
latitude and longitude (or to space), sample the same terrarium
elevation the flat map draws from, and let the existing paint pipeline
(bathymetry, hypsometry, hillshade, braille coastline) do exactly what
it always does.  Only the geometry changes; the planet keeps its look.

The disk is shaded twice: hillshade inside the paint pipeline, then a
limb falloff by viewing angle out here, which is what turns a round
map into a sphere.  Space gets a one-sub-pixel breath of atmosphere.
"""

import math
import struct
import zlib
from collections import namedtuple
from pathlib import Path

from linecast import _cache
from linecast._elevation import _fetch_tile, decode_meters
from linecast._geo import wrap_lon
from linecast._png import decode_rgba
from linecast._radar_basemap import (
    CITY, CITY_LABEL, DotLayer, _cell_width, _load_data, _localized)
from linecast._radar_tiles import _TILE_SIZE, stitch_xyz
from linecast._theme import themed

# `zoom` (degrees of latitude the screen spans) at which the flat map
# hands the view to the globe
ZOOM_DEG = 45.0

# Mercator tiles end at the 85th parallel; samples poleward of it clamp
# to that ring, which reads as polar ocean in the north and the ice
# plateau in the south — what is actually there, within a band no
# terminal cell resolves at planet scale.
_MERCATOR_LAT = 85.05

_ATMOSPHERE = themed((104, 148, 198))
_AIRGLOW = themed((96, 150, 116))


def _rebuild():
    global _ATMOSPHERE, _AIRGLOW
    _ATMOSPHERE = themed((104, 148, 198))
    _AIRGLOW = themed((96, 150, 116))


from linecast import _theme
_theme.on_reload(_rebuild)

# lls (the coarse per-sample lat/lon grid) and glow_lls (the limb
# point each rim-glow sample grazes) ride along for the now register,
# which re-shades a cached view into the current moment
GlobeView = namedtuple("GlobeView",
                       "elev coast shade atmo cover borders lls glow_lls",
                       defaults=(None, None))


def ice_cover(lls, elev, ice_id):
    """Sub-pixel cover grid painting the planet's ice sheets, or None.

    The vector landcover tiles never make it to planet scale, but the
    two great ice sheets are a fact of latitude and altitude: everything
    south of the Antarctic Circle's approach is ice, and high ground in
    the far north is the Greenland dome (with the St Elias icefields
    riding the same rule).  A heuristic, but one that is wrong about
    almost no terminal cell at these zooms.
    """
    rows = []
    any_ice = False
    for ll_row, e_row in zip(lls, elev):
        row = bytearray(len(e_row))
        for x, (ll, e) in enumerate(zip(ll_row, e_row)):
            if ll is None or e is None or e <= 0:
                continue
            lat = ll[0]
            if (lat <= -60.0 or (lat >= 66.5 and e > 1800.0)
                    or (lat > 59.0 and e > 2200.0)):
                row[x] = ice_id
                any_ice = True
        rows.append(row)
    return rows if any_ice else None


def _radius(zoom, h):
    """Disk radius in grid units for an h-row grid spanning the screen.

    Sized so one row at the *centre* of the disk spans zoom/h degrees
    of arc — the same scale the flat map draws at — because that is
    what makes the hand-off seamless: crossing ZOOM_DEG changes the
    projection, not the size of anything under the cursor.  A plane
    unit is a radian at the centre (orthographic is sine-compressed
    toward the limb), hence 180/π rather than 90.
    """
    return h * (180.0 / math.pi) / zoom


def forward(lat, lon, lat0, lon0):
    """(ux, uy, cos_c) on the unit projection plane; visible if cos_c > 0."""
    phi, lam = math.radians(lat), math.radians(lon)
    phi0, lam0 = math.radians(lat0), math.radians(lon0)
    d = lam - lam0
    cos_phi = math.cos(phi)
    ux = cos_phi * math.sin(d)
    uy = (math.cos(phi0) * math.sin(phi)
          - math.sin(phi0) * cos_phi * math.cos(d))
    cos_c = (math.sin(phi0) * math.sin(phi)
             + math.cos(phi0) * cos_phi * math.cos(d))
    return ux, uy, cos_c


# geometry() memo: (lat0, zoom, w, h) -> (base, zs, rhos), where base
# holds each sample's (lat, longitude east of the view centre).  A
# spin or a sideways drag changes only lon0, and lon0 is a constant
# offset on the grid — so those frames skip the projection entirely.
_geometry_cache = {}
_GEOMETRY_KEEP = 4


def _project(lat0, zoom, w, h):
    """The w×h grid inverted about longitude 0: (base, zs, rhos)."""
    r = _radius(zoom, h)
    sin0, cos0 = (math.sin(math.radians(lat0)),
                  math.cos(math.radians(lat0)))
    base, zs, rhos = [], [], []
    for y in range(h):
        uy = (h / 2.0 - y - 0.5) / r
        b_row, z_row, rho_row = [], [], []
        for x in range(w):
            ux = (x + 0.5 - w / 2.0) / r
            rho2 = ux * ux + uy * uy
            rho_row.append(math.sqrt(rho2))
            if rho2 > 1.0:
                b_row.append(None)
                z_row.append(None)
                continue
            z = math.sqrt(1.0 - rho2)
            lat = math.degrees(math.asin(
                min(1.0, max(-1.0, uy * cos0 + z * sin0))))
            b_row.append((lat, math.degrees(
                math.atan2(ux, z * cos0 - uy * sin0))))
            z_row.append(z)
        base.append(b_row)
        zs.append(z_row)
        rhos.append(rho_row)
    return base, zs, rhos


def geometry(lat0, lon0, zoom, w, h):
    """Inverse projection for every sample of a w×h grid over the screen.

    Returns (lls, zs, rhos): per sample the (lat, lon) under it (None in
    space), the viewing cosine (None in space; 1 at the centre of the
    disk, 0 at the limb), and the distance from the disk centre in disk
    radii (space included — the atmosphere needs the near-misses).

    lls is fresh per call; zs and rhos do not depend on lon0 and are
    shared with other calls for the same view — read them, don't
    write them.
    """
    key = (lat0, zoom, w, h)
    hit = _geometry_cache.get(key)
    if hit is None:
        hit = _project(lat0, zoom, w, h)
        while len(_geometry_cache) >= _GEOMETRY_KEEP:
            del _geometry_cache[next(iter(_geometry_cache))]
        _geometry_cache[key] = hit
    base, zs, rhos = hit
    lls = [[None if b is None else (b[0], wrap_lon(lon0 + b[1]))
            for b in b_row] for b_row in base]
    return lls, zs, rhos


_canvas_cache = {}


def _source_zoom(zoom, h):
    """Terrarium zoom level whose detail matches zoom/h degrees per sample."""
    return min(3, max(1, round(math.log2(
        max(1e-9, 360.0 / (zoom / h) / _TILE_SIZE)))))


def warm(zoom, h):
    """True once the world canvas this view samples is already stitched.

    A warm canvas is what makes live rotation possible: re-rendering
    the globe at a new centre is then pure arithmetic, never a network
    wait, so a drag can afford to re-project every frame.
    """
    return _source_zoom(zoom, h) in _canvas_cache


def _canvas_path(z):
    return _cache.CACHE_ROOT / "maps" / f"globe_canvas_v1_{z}.bin"


def _canvas_read(path):
    try:
        blob = zlib.decompress(path.read_bytes())
        cw, ch, org_x, org_y, world = struct.unpack(">5I", blob[:20])
        canvas = bytearray(blob[20:])
        if len(canvas) != cw * ch * 4:
            return None
        return canvas, cw, ch, org_x, org_y, world
    except Exception:
        return None


def _canvas_load(z):
    """A stitched canvas baked earlier, or None.

    Terrarium tiles are immutable, so the derived canvas is too: a disk
    hit replaces sixty-four PNG unfilterings with one C-speed inflate,
    which is the difference between a first frame and a loading frame.
    The wheel ships z1 and z2 (scripts/build_globe_canvas.py), so those
    globes need no network at all; z3 — very tall terminals only — is
    stitched once on this machine and cached.
    """
    vendored = Path(__file__).parent / "data" / f"globe_canvas_{z}.bin"
    return _canvas_read(vendored) or _canvas_read(_canvas_path(z))


def _canvas_store(z, hit):
    canvas, cw, ch, org_x, org_y, world = hit
    try:
        path = _canvas_path(z)
        path.parent.mkdir(parents=True, exist_ok=True)
        _cache.write_bytes_atomic(
            path, zlib.compress(struct.pack(">5I", cw, ch, org_x, org_y,
                                            world) + bytes(canvas), 6))
    except Exception:
        pass


def _world_canvas(z, timeout):
    """The whole world's terrarium tiles stitched at zoom `z`, memoised."""
    hit = _canvas_cache.get(z)
    if hit is not None:
        return hit

    hit = _canvas_load(z)
    if hit is None:
        missed = [False]

        def fetch(z_, x, y):
            data = _fetch_tile(z_, x, y, timeout)
            if data is None:
                missed[0] = True
                return None
            try:
                return decode_rgba(data)
            except Exception:
                missed[0] = True
                return None

        bbox = (-180.0, -_MERCATOR_LAT, 180.0, _MERCATOR_LAT)
        hit = stitch_xyz(fetch, bbox, z)
        # a canvas with holes (a tile the network dropped) must not be
        # frozen to disk: the holes would outlive the outage
        if not missed[0]:
            _canvas_store(z, hit)
    if len(_canvas_cache) > 1:
        _canvas_cache.clear()
    _canvas_cache[z] = hit
    return hit


def bilinear_taps(ll_row, canvas):
    """Where one row of samples lands on a stitched world canvas.

    Per sample, the byte offsets of the four pixels around it —
    (j00, j01, j10, j11) for (x0,y0), (x1,y0), (x0,y1), (x1,y1) — and
    the (tx, ty) blend between them, or None in space.  The elevation
    canvas and the cloud mosaic share the mercator layout, so both
    samplers share this; each reads its own channel from the taps.
    Straight-line arithmetic on purpose: this runs for every sub-pixel
    of every drag frame.
    """
    _canvas, cw, ch, org_x, org_y, world = canvas
    log, sin, radians = math.log, math.sin, math.radians
    four_pi = 4 * math.pi
    lat_max = _MERCATOR_LAT
    ch1 = ch - 1.0
    cw4 = cw * 4
    out = []
    app = out.append
    for ll in ll_row:
        if ll is None:
            app(None)
            continue
        lat = ll[0]
        # samples poleward of the tiles' edge clamp to their last ring
        if lat > lat_max:
            lat = lat_max
        elif lat < -lat_max:
            lat = -lat_max
        sn = sin(radians(lat))
        # _lonlat_to_world, inlined
        fx = (ll[1] + 180.0) / 360.0 * world - org_x - 0.5
        fy = (0.5 - log((1 + sn) / (1 - sn)) / four_pi) * world - org_y - 0.5
        if fy < 0.0:
            fy = 0.0
        elif fy > ch1:
            fy = ch1
        ix = int(fx)
        x0 = ix % cw
        x1 = (x0 + 1) % cw  # the antimeridian is a seam only on paper
        y0 = int(fy)
        y1 = y0 + 1
        if y1 >= ch:
            y1 = ch - 1
        b0 = y0 * cw4
        b1 = y1 * cw4
        app((b0 + x0 * 4, b0 + x1 * 4, b1 + x0 * 4, b1 + x1 * 4,
             fx - ix, fy - y0))
    return out


def _first_opaque(canvas, taps):
    """The first tap with data, undiluted — for a sample whose only
    opaque neighbours carry zero weight (it sits exactly on a pixel
    beside a hole)."""
    for j in taps:
        if canvas[j + 3]:
            return decode_meters(canvas[j], canvas[j + 1], canvas[j + 2])
    return None


def elevation(lls, zoom, h, timeout=15):
    """Meters under each visible sample of a geometry() grid.

    The source zoom follows the finest detail the grid can show —
    zoom/h degrees per sample — and the whole world at that zoom is a
    few dozen immutable, disk-cached tiles, so the globe costs the
    network almost nothing after its first spin.

    Bilinear over the four surrounding pixels, weighting only those
    with data (a tile the network dropped leaves a transparent hole).
    The inner loop is decode_meters and the blend written out by hand:
    it runs tens of thousands of times per drag frame, and temporaries
    were most of its cost.
    """
    z = _source_zoom(zoom, h)
    hit = _world_canvas(z, timeout)
    canvas = hit[0]
    grid = []
    for ll_row in lls:
        row = []
        app = row.append
        for tap in bilinear_taps(ll_row, hit):
            if tap is None:
                app(None)
                continue
            j00, j01, j10, j11, tx, ty = tap
            acc = 0.0
            ws = 0.0
            if canvas[j00 + 3]:
                w = (1.0 - ty) * (1.0 - tx)
                acc += ((canvas[j00] * 256 + canvas[j00 + 1]
                         + canvas[j00 + 2] / 256.0) - 32768.0) * w
                ws += w
            if canvas[j01 + 3]:
                w = (1.0 - ty) * tx
                acc += ((canvas[j01] * 256 + canvas[j01 + 1]
                         + canvas[j01 + 2] / 256.0) - 32768.0) * w
                ws += w
            if canvas[j10 + 3]:
                w = ty * (1.0 - tx)
                acc += ((canvas[j10] * 256 + canvas[j10 + 1]
                         + canvas[j10 + 2] / 256.0) - 32768.0) * w
                ws += w
            if canvas[j11 + 3]:
                w = ty * tx
                acc += ((canvas[j11] * 256 + canvas[j11 + 1]
                         + canvas[j11 + 2] / 256.0) - 32768.0) * w
                ws += w
            if ws > 0.0:
                app(acc / ws)
            else:
                app(_first_opaque(canvas, (j00, j01, j10, j11)))
        grid.append(row)
    return grid


def shade_buffer(buf, shade, atmo, bg):
    """Limb-darken the disk and breathe the atmosphere onto space.

    `buf` is the paint pipeline's sub-pixel RGB grid, modified in
    place; `shade` and `atmo` come from a GlobeView.  The falloff is
    gentle — the sun already lives in the hillshade — but it is what
    makes the edge of the disk read as the edge of a sphere.
    """
    for y, row in enumerate(buf):
        s_row, a_row = shade[y], atmo[y]
        for x, px in enumerate(row):
            z = s_row[x]
            if z is not None:
                m = 0.58 + 0.42 * math.sqrt(z)
                row[x] = (int(px[0] * m), int(px[1] * m), int(px[2] * m))
            elif a_row[x] > 0.0:
                a = a_row[x] * 0.6
                row[x] = (int(bg[0] + (_ATMOSPHERE[0] - bg[0]) * a),
                          int(bg[1] + (_ATMOSPHERE[1] - bg[1]) * a),
                          int(bg[2] + (_ATMOSPHERE[2] - bg[2]) * a))


def atmosphere(rhos, zoom, h):
    """Per-sample rim alpha: 1 at the limb fading to 0 a breath out."""
    width = 2.5 / _radius(zoom, h)
    out = []
    for rho_row in rhos:
        out.append([max(0.0, 1.0 - (rho - 1.0) / width)
                    if rho > 1.0 else 0.0 for rho in rho_row])
    return out


def limb_lls(lat0, lon0, zoom, w, h, atmo):
    """(lat, lon) of the limb point under each rim-glow sample, or None.

    A glow sample lies off the disk, so no geography sits under it;
    what it has is the point on the limb its sightline grazes, and
    whether the sun is up *there* decides whether scattered sunlight
    can reach the sample at all.
    """
    r = _radius(zoom, h)
    sin0 = math.sin(math.radians(lat0))
    cos0 = math.cos(math.radians(lat0))
    out = []
    for y, a_row in enumerate(atmo):
        uy = (h / 2.0 - y - 0.5) / r
        row = []
        for x, a in enumerate(a_row):
            if a <= 0.0:
                row.append(None)
                continue
            ux = (x + 0.5 - w / 2.0) / r
            rho = math.hypot(ux, uy)
            nx, ny = ux / rho, uy / rho
            lat = math.degrees(math.asin(max(-1.0, min(1.0, ny * cos0))))
            lon = lon0 + math.degrees(math.atan2(nx, -ny * sin0))
            row.append((lat, wrap_lon(lon)))
        out.append(row)
    return out


def gate_glow(buf, atmo, day, bg):
    """Gate the rim glow by the sun at the limb, in place.

    Scattered sunlight needs sunlight: the glow keeps its blue only
    where its limb point still sees the sun, fading through the same
    twilight band as the ground beside it — the scattering layer
    rides high enough to stay lit across the band.  Past it the
    night limb keeps only airglow: oxygen's faint green, far dimmer,
    alpha squared so it thins to a line hugging the disk.
    """
    for y, a_row in enumerate(atmo):
        d_row = day[y]
        for x, a in enumerate(a_row):
            if a <= 0.0:
                continue
            d = d_row[x]
            if d is None or d >= 1.0:
                continue
            aa = 0.6 * (a * d + a * a * 0.08 * (1.0 - d))
            buf[y][x] = tuple(
                int(bg[i] + (_AIRGLOW[i]
                             + (_ATMOSPHERE[i] - _AIRGLOW[i]) * d
                             - bg[i]) * aa)
                for i in range(3))


def fill_buffer(elev, water, ground, bg):
    """Street-register fills for the globe: flat sea, flat ground.

    The street map's planet is the street map's idiom — two quiet
    fills and a braille coastline — bent onto the sphere.  A palette
    that paints no fills (the 16-colour line map) gets background, and
    the coastline carries the geography alone, exactly as it does on
    the flat map.
    """
    buf = []
    for row in elev:
        out = []
        for e in row:
            if e is None:
                out.append(bg)
            elif e <= 0:
                out.append(water if water is not None else bg)
            else:
                out.append(ground if ground is not None else bg)
        buf.append(out)
    return buf


_BORDER_TRIG = (None, None)  # (borders list identity, its trig form)


def _border_trig():
    """Every border vertex as (sin lat, cos lat, lon in radians), once.

    forward() spends four radians() and four trig calls per vertex,
    and border_layer() asks it about twenty-five thousand vertices a
    frame; only the centre changes between frames.  Keyed to the list
    object itself so a test swapping the basemap data gets fresh
    trig.
    """
    global _BORDER_TRIG
    borders = _load_data()["borders"]
    if _BORDER_TRIG[0] is not borders:
        radians, sin, cos = math.radians, math.sin, math.cos
        trig = []
        for coords in borders:
            pts = []
            for lon, lat in coords:
                phi = radians(lat)
                pts.append((sin(phi), cos(phi), radians(lon)))
            trig.append(pts)
        _BORDER_TRIG = (borders, trig)
    return _BORDER_TRIG[1]


def border_layer(lat0, lon0, zoom, gw, hc, color):
    """Natural Earth borders stroked onto the globe as a braille layer.

    Both endpoints of a segment must face the viewer, and a segment
    whose endpoints are more than ~70 degrees of arc apart is skipped —
    two points that far apart in the vendored polylines are an artifact
    of simplification, and their chord would slice across the disk.
    The per-vertex arithmetic is forward() with its trig hoisted.
    """
    layer = DotLayer((0.0, 0.0, 1.0, 1.0), gw, hc)
    dot_line = layer._dot_line
    r = _radius(zoom, hc * 4)
    cx, cy = gw * 2 / 2.0, hc * 4 / 2.0
    phi0, lam0 = math.radians(lat0), math.radians(lon0)
    sin0, cos0 = math.sin(phi0), math.cos(phi0)
    sin, cos = math.sin, math.cos
    for pts in _border_trig():
        prev = None
        for sin_phi, cos_phi, lam in pts:
            d = lam - lam0
            cos_d = cos(d)
            cos_c = sin0 * sin_phi + cos0 * cos_phi * cos_d
            if cos_c <= 0.02:
                prev = None
                continue
            ux = cos_phi * sin(d)
            uy = cos0 * sin_phi - sin0 * cos_phi * cos_d
            p = (cx + ux * r, cy - uy * r, ux, uy, cos_c)
            if prev is not None:
                arc = prev[2] * ux + prev[3] * uy + prev[4] * cos_c
                if arc > 0.34:
                    dot_line(prev[0], prev[1], p[0], p[1], color)
            prev = p
    return layer


def marker_cell(lat0, lon0, zoom, gw, hc, m_lat, m_lon):
    """Terminal (col, row) under a lat/lon, or None if hidden or off-screen."""
    ux, uy, cos_c = forward(m_lat, m_lon, lat0, lon0)
    if cos_c <= 0.0:
        return None  # the far hemisphere
    r = _radius(zoom, hc * 2)
    col = int(gw / 2.0 + ux * r)
    row = int((hc * 2 / 2.0 - uy * r) / 2.0)
    if 0 <= col < gw and 0 <= row < hc:
        return (col, row)
    return None


# city_overlays() memo: the placement depends only on the view and the
# language, but every repaint asks for it — hover included.  Keyed
# with the cities list's identity so swapped-in test data misses.
_overlay_cache = {}
_OVERLAY_KEEP = 4


def city_overlays(lat0, lon0, zoom, gw, hc, lang="en"):
    """{(col,row): (char, color)} for the biggest visible cities + labels.

    The same biggest-first greedy placement as the flat basemap's, with
    one extra gate: nothing lands within the outer tenth of the disk,
    where orthographic compression stacks a continent into a cell and a
    label would point at geography it half covers.

    Memoised per view: the dict is shared between calls, so read it.
    """
    cities = _load_data()["cities"]
    key = (lat0, lon0, zoom, gw, hc, lang, id(cities))
    hit = _overlay_cache.get(key)
    if hit is not None:
        return hit
    hit = _place_cities(cities, lat0, lon0, zoom, gw, hc, lang)
    while len(_overlay_cache) >= _OVERLAY_KEEP:
        del _overlay_cache[next(iter(_overlay_cache))]
    _overlay_cache[key] = hit
    return hit


def _place_cities(cities, lat0, lon0, zoom, gw, hc, lang):
    max_cities = max(6, min(24, (gw * hc) // 400))
    r = _radius(zoom, hc * 2)
    ranked = []
    for entry in cities:
        lon, lat, pop = entry[0], entry[1], entry[2]
        ux, uy, cos_c = forward(lat, lon, lat0, lon0)
        if cos_c < 0.2:
            continue
        col = int(gw / 2.0 + ux * r)
        row = int((hc * 2 / 2.0 - uy * r) / 2.0)
        if 0 <= col < gw and 0 <= row < hc:
            ranked.append((pop, _localized(entry, lang), col, row))
    ranked.sort(key=lambda c: c[0], reverse=True)

    overlays = {}
    placed = []
    for _pop, name, col, row in ranked:
        if len(placed) >= max_cities:
            break
        if (col, row) in overlays:
            continue
        if any(abs(col - pc) < 16 and abs(row - pr) < 3 for pc, pr in placed):
            continue
        placed.append((col, row))
        overlays[(col, row)] = ("•", CITY)
        c = col + 1
        for ch in name:
            w = _cell_width(ch)
            if c + w > gw:
                break
            if (c, row) in overlays or (w == 2 and (c + 1, row) in overlays):
                break
            overlays[(c, row)] = (ch, CITY_LABEL)
            if w == 2:
                overlays[(c + 1, row)] = ("", None)
            c += w
    return overlays
