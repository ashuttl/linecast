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
from collections import namedtuple

from linecast._elevation import _fetch_tile, decode_meters
from linecast._png import decode_rgba
from linecast._radar_basemap import (
    CITY, CITY_LABEL, DotLayer, _cell_width, _load_data, _localized)
from linecast._radar_tiles import _TILE_SIZE, _lonlat_to_world, stitch_xyz

# `zoom` (degrees of latitude the screen spans) at which the flat map
# hands the view to the globe
ZOOM_DEG = 45.0

# Mercator tiles end at the 85th parallel; samples poleward of it clamp
# to that ring, which reads as polar ocean in the north and the ice
# plateau in the south — what is actually there, within a band no
# terminal cell resolves at planet scale.
_MERCATOR_LAT = 85.05

_ATMOSPHERE = (104, 148, 198)

GlobeView = namedtuple("GlobeView", "elev coast shade atmo cover borders")


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


def geometry(lat0, lon0, zoom, w, h):
    """Inverse projection for every sample of a w×h grid over the screen.

    Returns (lls, zs, rhos): per sample the (lat, lon) under it (None in
    space), the viewing cosine (None in space; 1 at the centre of the
    disk, 0 at the limb), and the distance from the disk centre in disk
    radii (space included — the atmosphere needs the near-misses).
    """
    r = _radius(zoom, h)
    sin0, cos0 = (math.sin(math.radians(lat0)),
                  math.cos(math.radians(lat0)))
    lls, zs, rhos = [], [], []
    for y in range(h):
        uy = (h / 2.0 - y - 0.5) / r
        ll_row, z_row, rho_row = [], [], []
        for x in range(w):
            ux = (x + 0.5 - w / 2.0) / r
            rho2 = ux * ux + uy * uy
            rho_row.append(math.sqrt(rho2))
            if rho2 > 1.0:
                ll_row.append(None)
                z_row.append(None)
                continue
            z = math.sqrt(1.0 - rho2)
            lat = math.degrees(math.asin(
                min(1.0, max(-1.0, uy * cos0 + z * sin0))))
            lon = lon0 + math.degrees(math.atan2(ux, z * cos0 - uy * sin0))
            if lon > 180.0:
                lon -= 360.0
            elif lon < -180.0:
                lon += 360.0
            ll_row.append((lat, lon))
            z_row.append(z)
        lls.append(ll_row)
        zs.append(z_row)
        rhos.append(rho_row)
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


def _world_canvas(z, timeout):
    """The whole world's terrarium tiles stitched at zoom `z`, memoised."""
    hit = _canvas_cache.get(z)
    if hit is not None:
        return hit

    def fetch(z_, x, y):
        data = _fetch_tile(z_, x, y, timeout)
        if data is None:
            return None
        try:
            return decode_rgba(data)
        except Exception:
            return None

    bbox = (-180.0, -_MERCATOR_LAT, 180.0, _MERCATOR_LAT)
    hit = stitch_xyz(fetch, bbox, z)
    if len(_canvas_cache) > 1:
        _canvas_cache.clear()
    _canvas_cache[z] = hit
    return hit


def elevation(lls, zoom, h, timeout=15):
    """Meters under each visible sample of a geometry() grid.

    The source zoom follows the finest detail the grid can show —
    zoom/h degrees per sample — and the whole world at that zoom is a
    few dozen immutable, disk-cached tiles, so the globe costs the
    network almost nothing after its first spin.
    """
    z = _source_zoom(zoom, h)
    canvas, cw, ch, org_x, org_y, world = _world_canvas(z, timeout)
    grid = []
    for ll_row in lls:
        row = []
        for ll in ll_row:
            if ll is None:
                row.append(None)
                continue
            lat = min(_MERCATOR_LAT, max(-_MERCATOR_LAT, ll[0]))
            wx, wy = _lonlat_to_world(ll[1], lat)
            fx = wx * world - org_x - 0.5
            fy = min(max(wy * world - org_y - 0.5, 0.0), ch - 1.0)
            x0 = int(fx) % cw
            x1 = (x0 + 1) % cw  # the antimeridian is a seam only on paper
            y0 = int(fy)
            y1 = min(y0 + 1, ch - 1)
            tx, ty = fx - int(fx), fy - y0
            vals = []
            for yy, wgt_y in ((y0, 1.0 - ty), (y1, ty)):
                base = yy * cw * 4
                for xx, wgt in ((x0, wgt_y * (1.0 - tx)),
                                (x1, wgt_y * tx)):
                    j = base + xx * 4
                    if canvas[j + 3]:
                        vals.append((decode_meters(
                            canvas[j], canvas[j + 1], canvas[j + 2]), wgt))
            if not vals:
                row.append(None)
            else:
                wsum = sum(wgt for _, wgt in vals)
                row.append(sum(v * wgt for v, wgt in vals) / wsum
                           if wsum > 0 else vals[0][0])
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


def border_layer(lat0, lon0, zoom, gw, hc, color):
    """Natural Earth borders stroked onto the globe as a braille layer.

    Both endpoints of a segment must face the viewer, and a segment
    whose endpoints are more than ~70 degrees of arc apart is skipped —
    two points that far apart in the vendored polylines are an artifact
    of simplification, and their chord would slice across the disk.
    """
    layer = DotLayer((0.0, 0.0, 1.0, 1.0), gw, hc)
    r = _radius(zoom, hc * 4)
    cx, cy = gw * 2 / 2.0, hc * 4 / 2.0
    for coords in _load_data()["borders"]:
        prev = None
        for lon, lat in coords:
            ux, uy, cos_c = forward(lat, lon, lat0, lon0)
            if cos_c <= 0.02:
                prev = None
                continue
            p = (cx + ux * r, cy - uy * r, ux, uy, cos_c)
            if prev is not None:
                arc = prev[2] * ux + prev[3] * uy + prev[4] * cos_c
                if arc > 0.34:
                    layer._dot_line(prev[0], prev[1], p[0], p[1], color)
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


def city_overlays(lat0, lon0, zoom, gw, hc, lang="en"):
    """{(col,row): (char, color)} for the biggest visible cities + labels.

    The same biggest-first greedy placement as the flat basemap's, with
    one extra gate: nothing lands within the outer tenth of the disk,
    where orthographic compression stacks a continent into a cell and a
    label would point at geography it half covers.
    """
    max_cities = max(6, min(24, (gw * hc) // 400))
    r = _radius(zoom, hc * 2)
    ranked = []
    for entry in _load_data()["cities"]:
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
