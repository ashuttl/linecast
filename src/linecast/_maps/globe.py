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
import threading
import zlib
from collections import namedtuple

from linecast import _cache
from linecast._elevation import _fetch_tile, decode_meters
from linecast._framebuffer import cell_aspect
from linecast._geo import wrap_lon
from linecast._paths import cache_dir, data_path
from linecast._png import decode_rgba
from linecast._radar.basemap import (
    CITY, CITY_LABEL, DotLayer, _load_data, _localized)
from linecast._textwidth import char_width
from linecast._radar.tiles import _TILE_SIZE, stitch_xyz
from linecast._runtime import log_failure
from linecast._scenes import Memo
from linecast._theme import themed

# `zoom` (degrees of latitude the screen spans) at which the flat map
# hands the view to the globe — at the equator.  See is_globe.
ZOOM_DEG = 45.0


def is_globe(zoom, lat):
    """Whether a view centred at `lat` spanning `zoom` degrees is a globe.

    The flat map is equirectangular about its centre, and its width in
    longitude grows as 1/cos(lat): a window that is a modest 9° tall
    at 78°S is as wide as one 45° tall at the equator, and it runs off
    both edges of the tile world — the antimeridian and the 85th
    parallel — while stretching the ice five times too wide.  So the
    hand-off is judged by the window's *widest* extent, and the poles
    go round at zooms the equator never would.  A window that reaches
    past the 85th parallel goes round whatever its width: the tiles
    end there, and the globe has a pole.
    """
    cos_lat = max(0.05, math.cos(math.radians(lat)))
    return (zoom / cos_lat >= ZOOM_DEG
            or abs(lat) + zoom / 2 > _MERCATOR_LAT)

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


from linecast import _theme  # noqa: E402 — the hook needs the palette above
_theme.on_reload(_rebuild)

# lls (the coarse per-sample lat/lon grid) and glow_lls (the limb
# point each rim-glow sample grazes) ride along for the now register,
# which re-shades a cached view into the current moment; water is the
# sub-pixel inland mask the elevation data cannot report.  fill and wet
# are the baked texture's answers — the shaded sub-pixel colour and the
# sub-pixel water of both kinds — and are None whenever the view was
# built the long way, from elevation, instead (see globe_texture).
GlobeView = namedtuple("GlobeView",
                       "elev coast shade atmo cover borders lls glow_lls "
                       "water fill wet",
                       defaults=(None, None, None, None, None))


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


def _aspect():
    """A grid row's height in column widths, as the screen has it.

    Every grid here is cut from the terminal's cells the same way -- a
    column is a cell wide and a row half a cell tall, or half and a
    quarter for dots -- so one number serves them all: 1.0 on the 2:1
    cell that makes a half-block's two sub-pixels square, and read
    from the terminal's font where it can be.  _radius is rows per
    plane unit; columns per plane unit are _radius times this, and
    the disk is round on the screen rather than on the grid.
    """
    return cell_aspect() / 2.0


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
# Six rather than four: the terrain register asks for three grids per
# view now — the window's own sub-pixels for the sun, and the built
# view's sub-pixels and dots — and a zoom step has the grid it is
# leaving still on screen while the one it is going to is built.
_GEOMETRY_KEEP = 6
_geometry_cache = Memo(keep=_GEOMETRY_KEEP)
# the view workers run geometry() and city_overlays() side by side (a
# drag starts one per key), so the memos' lookup and evict-then-insert
# happen under a lock; a miss computes outside it, and two workers
# computing the same key is fine where an exception is not
_memo_lock = threading.Lock()


def _project(lat0, zoom, w, h, aspect=1.0):
    """The w×h grid inverted about longitude 0: (base, zs, rhos).

    Latitude comes back through atan2 rather than asin.  The two agree
    exactly on paper — the three components of a unit vector — but a
    sample near a pole has |sin lat| close to 1, where asin loses half
    its digits to the flat top of the sine, and atan2 against the
    horizontal component keeps them.  It costs nothing: the horizontal
    component is a hypot of two numbers already in hand.
    """
    r = _radius(zoom, h)
    rx = r * aspect
    sin0, cos0 = (math.sin(math.radians(lat0)),
                  math.cos(math.radians(lat0)))
    sqrt, hypot, atan2, degrees = (math.sqrt, math.hypot, math.atan2,
                                   math.degrees)
    base, zs, rhos = [], [], []
    for y in range(h):
        uy = (h / 2.0 - y - 0.5) / r
        b_row, z_row, rho_row = [], [], []
        for x in range(w):
            ux = (x + 0.5 - w / 2.0) / rx
            rho2 = ux * ux + uy * uy
            rho_row.append(sqrt(rho2))
            if rho2 > 1.0:
                b_row.append(None)
                z_row.append(None)
                continue
            z = sqrt(1.0 - rho2)
            north = uy * cos0 + z * sin0
            equator = z * cos0 - uy * sin0
            b_row.append((degrees(atan2(north, hypot(ux, equator))),
                          degrees(atan2(ux, equator))))
            z_row.append(z)
        base.append(b_row)
        zs.append(z_row)
        rhos.append(rho_row)
    return base, zs, rhos


def _memo_project(lat0, zoom, w, h):
    aspect = _aspect()
    key = (lat0, zoom, w, h, aspect)
    with _memo_lock:
        hit = _geometry_cache.get(key)
    if hit is None:
        hit = _project(lat0, zoom, w, h, aspect)
        with _memo_lock:
            _geometry_cache.put(key, hit)
    return hit


def relative(lat0, zoom, w, h):
    """Each sample's (lat, longitude east of the view centre), or None.

    geometry() without its one moving part.  What a spin or a sideways
    drag changes is lon0, and lon0 is a constant offset on this grid —
    so anything keyed to the geography rather than to the meridian can
    be worked out once and kept.  Shared between callers: read it,
    don't write it.
    """
    return _memo_project(lat0, zoom, w, h)[0]


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
    base, zs, rhos = _memo_project(lat0, zoom, w, h)
    lls = [[None if b is None else (b[0], wrap_lon(lon0 + b[1]))
            for b in b_row] for b_row in base]
    return lls, zs, rhos


# ---------------------------------------------------------------------------
# The camera: one window, as a piece of the sphere
# ---------------------------------------------------------------------------
#
# geometry() answers what is under each sample.  A *source* needs three
# other things about the same window, and none of them depends on how
# many samples it is cut into: which ground to fetch (`bounds`), at what
# scale to fetch and shade it (`scale_bbox`), and whether the Mercator
# sources may be asked about it at all (`local_tiles`).  They are
# gathered on a Camera so a loader can be handed one object rather than
# five numbers, and so the trigonometry each of them shares is worked
# out once.

# How far the box rasteriser may sit from the camera and still be the
# same picture: a twentieth of a braille dot, which is under the width
# of the thinnest thing drawn and well under the rounding that turns a
# polygon edge into a dot.
AFFINE_DOTS = 0.05

# A dot spans at most this much longitude before the Mercator sources
# are refused: the vector tiles are fetched two zooms ahead of the
# screen's own detail, and a dot coarser than a z1 tile pixel would
# have them reaching for footprints the size of a continent.
_MAX_DOT_DEGREES = 360.0 / (_TILE_SIZE * 2)


def cap_sine(zoom, gw, hc):
    """The sine of the arc from the view centre to the window's corner.

    A plane unit is the sine of an arc, and the corner of the window is
    the farthest point of it from the centre, so this is the window's
    reach over the sphere in one number.  It does not depend on how
    finely the window is sampled — only on the zoom and the terminal's
    own shape — so the dot grid and the sub-pixel grid agree about it.
    Greater than one means the corner is off the disk, in space.
    """
    return math.radians(zoom) * math.hypot(gw / (4.0 * hc * _aspect()), 0.5)


def cap(zoom, gw, hc):
    """The spherical cap the window covers, in radians; π/2 at most."""
    return math.asin(min(1.0, cap_sine(zoom, gw, hc)))


def _unproject(ux, uy, sin0, cos0):
    """(lat, longitude east of the centre) at a point of the plane."""
    rho2 = ux * ux + uy * uy
    if rho2 > 1.0:
        return None
    z = math.sqrt(1.0 - rho2)
    north = uy * cos0 + z * sin0
    equator = z * cos0 - uy * sin0
    return (math.degrees(math.atan2(north, math.hypot(ux, equator))),
            math.degrees(math.atan2(ux, equator)))


def scale_bbox(lat0, lon0, zoom, gw, hc):
    """The window's bbox taken as a scale and nothing else.

    `_radar_render.bbox_for`, with the one guard a camera needs: at the
    pole itself the cosine is zero and the longitude span is infinite,
    and a source asked for its detail would divide by it.  Everywhere a
    view can actually sit this is bbox_for's own arithmetic, number for
    number, so a detail zoom or a hillshade taken from it is the one the
    flat map has always taken.
    """
    half_lat = zoom / 2.0
    cos_lat = max(1e-9, math.cos(math.radians(lat0)))
    span = zoom * (gw / (hc * 2 * _aspect())) / cos_lat
    return (lon0 - span / 2, lat0 - half_lat, lon0 + span / 2, lat0 + half_lat)


def bounds(lat0, lon0, zoom, gw, hc, steps=32, pad=True):
    """A source bbox holding every sample of the window, and a margin.

    Longitude is unwrapped about the centre rather than wrapped into
    ±180, because a stitch across the antimeridian is one canvas and
    not two: the tile helpers take a bbox whose east edge may sit past
    180 and wrap the columns themselves.

    Latitude over the window's rectangle is stationary only on the
    line through the centre, and that line meets the rectangle's top
    and bottom edges — so walking the border is enough to find both
    extremes, and longitude's extremes are on the border for the same
    reason.  A window that reaches off the disk, or over a pole, has
    its extremes on the limb instead; there the enclosing spherical cap
    is the honest answer, and at a pole that is every longitude.

    The margin is a cell on every side, for a sampler whose bilinear
    tap wants the sample beyond the last one.  `pad` off leaves it
    out, for a source that cuts its features to tiles and taps
    nothing: the walk itself misses no extreme, because the extremes
    sit on the corners and the centre lines, which are lattice points
    of any even number of steps.
    """
    rad = math.radians(zoom)
    ux_max = rad * gw / (4.0 * hc * _aspect())
    uy_max = rad / 2.0
    sin0 = math.sin(math.radians(lat0))
    cos0 = math.cos(math.radians(lat0))
    # the visible pole sits at |uy| = cos lat0, whichever it is
    if math.hypot(ux_max, uy_max) > 1.0 or cos0 <= uy_max:
        arc = math.degrees(cap(zoom, gw, hc))
        lo, hi = max(-90.0, lat0 - arc), min(90.0, lat0 + arc)
        sin_cap = math.sin(math.radians(arc))
        if abs(lat0) + arc >= 90.0 or cos0 <= sin_cap:
            return (lon0 - 180.0, lo, lon0 + 180.0, hi)
        half = math.degrees(math.asin(min(1.0, sin_cap / cos0)))
        return (lon0 - half, lo, lon0 + half, hi)
    lats, lons = [], []
    for i in range(steps + 1):
        t = -1.0 + 2.0 * i / steps
        for ux, uy in ((t * ux_max, uy_max), (t * ux_max, -uy_max),
                       (ux_max, t * uy_max), (-ux_max, t * uy_max)):
            lat, dlon = _unproject(ux, uy, sin0, cos0)
            lats.append(lat)
            lons.append(dlon)
    if not pad:
        return (lon0 + min(lons), min(lats), lon0 + max(lons), max(lats))
    # a cell of margin on every side, for the bilinear tap
    pad_lat = zoom / hc
    pad_lon = (max(lons) - min(lons) + 1e-12) / gw
    return (lon0 + min(lons) - pad_lon, max(-90.0, min(lats) - pad_lat),
            lon0 + max(lons) + pad_lon, min(90.0, max(lats) + pad_lat))


def local_tiles(lat0, zoom, gw, hc, margin=False):
    """Whether the Mercator sources may be asked about this window.

    `margin` says the window is the overscan of one already within
    reach, and the first refusal is then not this window's to make: a
    margin a quarter again as wide as a window in the last degrees
    before the hand-off would be sent to the planet while the window
    it serves is on the tiles, and a crop of the texture is not the
    picture `--print` draws.  The other three stand, because they say
    whether the tiles can be stitched at all.

    Four refusals.  A window wide enough to be the planet is drawn
    from the world's own baked texture, which is where `is_globe` has
    always sent it and where the terrarium tiles for it are the ones
    already stitched into a canvas.  A window whose corner has left
    the disk is the planet too, whatever its zoom says — a terminal
    five times wider than it is tall gets there before `is_globe`
    does — and the ground behind its limb is a hemisphere, which is
    not a footprint to stitch tiles across.  A dot spanning more than
    the vector source's own detail asks it for footprints it never
    carries, which is a small terminal at a wide zoom rather than any
    ordinary view.  And the tiles end at the 85th parallel, so a
    window reaching past it would be stitched from a ring of ice.

    The branch this arithmetic comes from put the first refusal at a
    15° cap, and the terrain register is not ready for that: between
    15° and 45° the baked planet is coarser than the screen and the
    canvas it would be baked from is not one the wheel ships.  So the
    source hand-off stays where it is; what moves in this stage is the
    projection, not the sources.
    """
    if (not margin and is_globe(zoom, lat0)) or cap_sine(zoom, gw, hc) >= 1.0:
        return False
    cos0 = math.cos(math.radians(lat0))
    if zoom / (hc * 4.0) / max(1e-12, cos0) > _MAX_DOT_DEGREES:
        return False
    # the window's own latitudes, without walking its whole border:
    # `bounds` shows they are stationary on the centre meridian, and
    # is_globe has already turned away everything wide enough for the
    # limb or a pole to be in the way.  Asked of every frame, so kept
    # to two inversions and a pad of one row.
    uy_max = math.radians(zoom) / 2.0
    sin0 = math.sin(math.radians(lat0))
    edge = zoom / hc
    for uy in (-uy_max, uy_max):
        at = _unproject(0.0, uy, sin0, cos0)
        if at is None or not (-_MERCATOR_LAT + edge < at[0]
                              < _MERCATOR_LAT - edge):
            return False
    return True


def affine_error(lat0, zoom, gw, hc, reach=1.0):
    """The box rasteriser's worst distance from the camera, in dots.

    The flat view places a feature linearly in longitude and latitude;
    the camera places it on the sphere.  The two agree at the centre
    and part company by two terms — the parallel bending toward the
    pole as it runs away from the centre meridian, and the meridian's
    own foreshortening — neither of which a separable map can carry.
    The first is the one that bites, and it carries sin φ0 cos φ0: at
    the equator the two maps agree for degrees, and at forty-five it is
    a dot per degree of zoom.

    Both terms are smooth over the window, so the worst of them is
    found by walking a lattice across it.  Across the *window*, which
    is all that is drawn: a vertex beyond the edge reaches the picture
    only through the segment it draws into it, and that segment enters
    where the bound already holds.  `reach` widens the lattice for a
    caller that wants more margin than that.

    The answer is in braille dots of the grid the rasteriser writes,
    which is what makes it comparable with AFFINE_DOTS.
    """
    dh = hc * 4
    r = _radius(zoom, dh)
    rx = r * _aspect()
    phi0 = math.radians(lat0)
    sin0, cos0 = math.sin(phi0), math.cos(phi0)
    box = scale_bbox(lat0, 0.0, zoom, gw, hc)
    half_lon = math.radians((box[2] - box[0]) / 2.0) * reach
    half_lat = math.radians((box[3] - box[1]) / 2.0) * reach
    # the box map, in the same units: a degree of longitude is dw/span
    # dots across and a degree of latitude dh/zoom dots down
    kx = rx * cos0
    ky = r
    worst = 0.0
    n = 8
    for i in range(n + 1):
        delta = -half_lon + 2.0 * half_lon * i / n
        cos_d, sin_d = math.cos(delta), math.sin(delta)
        for j in range(n + 1):
            dphi = -half_lat + 2.0 * half_lat * j / n
            phi = phi0 + dphi
            cos_p, sin_p = math.cos(phi), math.sin(phi)
            ex = rx * cos_p * sin_d - kx * delta
            ey = r * (cos0 * sin_p - sin0 * cos_p * cos_d) - ky * dphi
            e = math.hypot(ex, ey)
            if e > worst:
                worst = e
    return worst


def affine_ok(lat0, zoom, gw, hc):
    """Whether the flat box rasteriser is the camera's own picture."""
    return affine_error(lat0, zoom, gw, hc) <= AFFINE_DOTS


def crop_dots(lat0, cap, gw, hc, dcol, drow):
    """How far a *slice* taken `dcol, drow` cells off centre is, in dots.

    Two orthographic views of the same ground at the same scale and
    different centres are not a translation of one another, and the
    difference has two terms.

    The one that bites is first order and is the convergence of the
    meridians: move the centre east by δ and the picture turns by
    δ·sin φ0 about the point under the eye, because the two views hang
    their grids from meridians that are not parallel.  It vanishes at
    the equator and is most of the error anywhere else — a twenty
    column pan at the Alps turns the picture by half a degree, which
    is a dot and a half at the corner of a 160x45 window.

    The second is the sphere curving away: the far side of the window
    is nearer the limb in one view than in the other, which slides the
    ground along the offset by ρ²/2 of it.

    Both are measured at the corner, the farthest sample from the
    centre and the worst of them: `cap` is the window's reach over the
    sphere in radians (`cap`/`cap_sine`) and its half-diagonal in dots
    follows from the window's own size.  This is what a slice is out
    by, which is what a frame in motion shows; a frame at rest
    resamples instead and is out by nothing (`_maps_overscan.Resample`).
    """
    aspect = _aspect()
    # the zoom that put this cap on screen, so a caller need only hand
    # over the window's reach (cap_sine, inverted)
    rad_zoom = math.sin(min(cap, math.pi / 2)) / math.hypot(
        gw / (4.0 * hc * aspect), 0.5)
    # a column of the window in radians of longitude (scale_bbox), and
    # the turn a centre moved that far east makes of the picture
    colw = rad_zoom / (2.0 * hc * aspect
                       * max(1e-9, math.cos(math.radians(lat0))))
    turn = abs(dcol * colw * math.sin(math.radians(lat0)))
    corner = math.hypot(gw, 2.0 * hc)
    bend = 0.5 * cap * cap * math.hypot(4.0 * drow, 2.0 * dcol / aspect)
    return turn * corner + bend


# The index maps a resample is a gather over, kept across frames: a
# window at rest repaints for a pointer or a clock without moving, and
# a pan that comes back lands on the map it left.  Six: three grids
# (sub-pixels, dots, cells) for the window in hand and for one more.
_CROP_INDEX_KEEP = 6
_crop_index_cache = Memo(keep=_CROP_INDEX_KEEP)


def _basis(lat, lon):
    """(east, north, out) unit vectors at a point, in geocentric axes.

    The three axes an orthographic view hangs its plane from: `forward`
    is a point dotted with each of them.
    """
    phi, lam = math.radians(lat), math.radians(lon)
    sin_p, cos_p = math.sin(phi), math.cos(phi)
    sin_l, cos_l = math.sin(lam), math.cos(lam)
    return ((-sin_l, cos_l, 0.0),
            (-sin_p * cos_l, -sin_p * sin_l, cos_p),
            (cos_p * cos_l, cos_p * sin_l, sin_p))


def turn(src_lat, src_lon, dst_lat, dst_lon):
    """The map from one view's plane to another's: two rows of a rotation.

    Two orthographic views of the same sphere differ by a rotation of
    the sphere and by nothing else, so a point of `dst`'s plane lands
    on `src`'s through three multiplies an axis — the third reading the
    point's depth, which the plane's own two coordinates cannot carry
    and a translation therefore cannot either.  Exact at any
    separation: there is no small angle anywhere in it.
    """
    e_s, n_s, _o_s = _basis(src_lat, src_lon)
    e_d, n_d, o_d = _basis(dst_lat, dst_lon)

    def dot(a, b):
        return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]

    return ((dot(e_s, e_d), dot(e_s, n_d), dot(e_s, o_d)),
            (dot(n_s, e_d), dot(n_s, n_d), dot(n_s, o_d)))


def _grid_plane(cam, dw, dh):
    """(columns, rows) per plane unit for a dw x dh grid over `cam`.

    `_radius` for a grid that need not be one of the two the renderers
    draw on: the rows follow the zoom as they always do, and the
    columns follow the window's own shape, so a grid of whole cells —
    twice as tall as it is wide, where a sub-pixel or a dot is square —
    is placed by the same arithmetic as the rest.
    """
    rad = math.radians(cam.zoom)
    return (2.0 * dw * cam.hc * _aspect() / (rad * cam.gw), dh / rad)


def crop_index(src, dst, dw, dh, sdw, sdh):
    """Where each sample of a dw x dh grid over `dst` sits in `src`'s.

    A flat index into a sdw x sdh grid over `src` laid row after row —
    nearest sample, and -1 for a sample `src` does not hold or one off
    the disk.  -1 is the last element of a Python list, so a caller
    appends its own blank and gathers the whole row with one
    `operator.itemgetter`, which is where the speed is: the projection
    is walked once for a pair of cameras and the frames after it are C.

    This is the honest answer to a question a crop only approximates.
    A crop takes the samples the built view already holds at an offset;
    these are the samples the *window* would have taken, found in the
    built view by the rotation between the two (`turn`).
    """
    key = (src.lat, src.lon, src.zoom, src.gw, src.hc,
           dst.lat, dst.lon, dst.zoom, dst.gw, dst.hc,
           dw, dh, sdw, sdh, _aspect())
    with _memo_lock:
        hit = _crop_index_cache.get(key)
    if hit is not None:
        return hit
    (a, b, c), (e, f, g) = turn(src.lat, src.lon, dst.lat, dst.lon)
    rx, r = _grid_plane(dst, dw, dh)
    srx, sr = _grid_plane(src, sdw, sdh)
    sqrt = math.sqrt
    uxs = [(x + 0.5 - dw / 2.0) / rx for x in range(dw)]
    ux2 = [v * v for v in uxs]
    out = []
    for y in range(dh):
        uy = (dh / 2.0 - y - 0.5) / r
        # the depth is sqrt(1 - ux^2 - uy^2); the row's share of it is
        # constant, so only the column's is taken per sample
        top = 1.0 - uy * uy
        b_uy, f_uy = b * uy, f * uy
        row = []
        add = row.append
        for i, ux in enumerate(uxs):
            under = top - ux2[i]
            if under < 0.0:
                add(-1)
                continue
            z = sqrt(under)
            # the bounds are tested before the floor, because int()
            # rounds toward zero and would pull a sample half a cell
            # off the west or north edge back onto it
            fx = sdw / 2.0 + (a * ux + b_uy + c * z) * srx
            fy = sdh / 2.0 - (e * ux + f_uy + g * z) * sr
            if 0.0 <= fx < sdw and 0.0 <= fy < sdh:
                add(int(fy) * sdw + int(fx))
            else:
                add(-1)
        out.extend(row)
    with _memo_lock:
        _crop_index_cache.put(key, out)
    return out


class Camera:
    """One window, as the sources see it.

    The centre, the zoom and the window's size in cells, and nothing
    else; what a source asks of it — the ground it covers, the scale
    it is drawn at, whether the Mercator sources may be asked at all —
    is worked out on the first ask and kept.  A loader takes one of
    these instead of five numbers, and reads the grid it wants off it.
    """

    __slots__ = ("lat", "lon", "zoom", "gw", "hc", "aspect",
                 "_bounds", "_footprint", "_scale", "_local")

    def __init__(self, lat, lon, zoom, gw, hc):
        self.lat, self.lon, self.zoom = lat, lon, zoom
        self.gw, self.hc = gw, hc
        self.aspect = _aspect()
        self._bounds = self._footprint = self._scale = self._local = None

    @classmethod
    def for_bbox(cls, bbox, gw, hc):
        """The camera a flat view's bbox stands for.

        Every caller downstream of `bbox_for` still speaks in bboxes —
        the overscan plans in them, the caches key on them — and a
        bbox about a centre is a centre and a zoom, so the two
        languages meet here rather than in thirty signatures.
        """
        return cls((bbox[1] + bbox[3]) / 2.0, (bbox[0] + bbox[2]) / 2.0,
                   bbox[3] - bbox[1], gw, hc)

    @property
    def bounds(self):
        if self._bounds is None:
            self._bounds = bounds(self.lat, self.lon, self.zoom,
                                  self.gw, self.hc)
        return self._bounds

    @property
    def footprint(self):
        """`bounds` without its cell of margin: the ground the window
        shows and nothing beyond it, for the vector tiles.

        A tile carries every feature that touches it, so the tiles
        under the window's own ground are the tiles its picture is cut
        from — which is what the box rasteriser has always asked for.
        The margin exists for the bilinear tap, and asked of the vector
        sources it reaches a tile ring further in one view in nine:
        the default street view's overscan on a 160x45 terminal at New
        York asks twelve tiles with it and eight without.
        """
        if self._footprint is None:
            self._footprint = bounds(self.lat, self.lon, self.zoom,
                                     self.gw, self.hc, pad=False)
        return self._footprint

    @property
    def scale_bbox(self):
        if self._scale is None:
            self._scale = scale_bbox(self.lat, self.lon, self.zoom,
                                     self.gw, self.hc)
        return self._scale

    @property
    def local_tiles(self):
        if self._local is None:
            self._local = local_tiles(self.lat, self.zoom, self.gw, self.hc)
        return self._local

    def base(self, w, h):
        """The same grid with longitude east of the centre, shared.

        `relative`'s memo, which a sampler wants for two reasons: it is
        built once for a view and read by every source, and a longitude
        measured from the centre is already unwrapped for a footprint
        that crosses the antimeridian.  Read it, do not write it.
        """
        return relative(self.lat, self.zoom, w, h)

    def project(self, lon, lat, dw, dh):
        """(lon, lat) to grid edges on a dw×dh grid over the window.

        Grid *edges*, as every rasteriser here works in: a sample's
        centre is half a cell past its index, which is exactly where
        the inverse projection puts it.  A point on the far side of the
        planet comes back anyway — nothing local reaches one, and a
        polygon cannot be filled from a ring with holes in it.
        """
        r = _radius(self.zoom, dh)
        phi, delta = math.radians(lat), math.radians(lon - self.lon)
        phi0 = math.radians(self.lat)
        cos_p = math.cos(phi)
        ux = cos_p * math.sin(delta)
        uy = (math.cos(phi0) * math.sin(phi)
              - math.sin(phi0) * cos_p * math.cos(delta))
        return (dw / 2.0 + ux * r * self.aspect, dh / 2.0 - uy * r)

    def cell(self, lon, lat):
        """(column, row) of a point on the window, in cells, as floats.

        `marker_cell`'s arithmetic, for a caller placing many points.
        Not `project` on a grid of cells: every grid here is a column
        wide and half a cell or less tall, and the plane's two axes are
        scaled by that ratio — so a point is placed on the sub-pixel
        grid and the row halved, which is what the marks do.
        """
        x, y = self.project(lon, lat, self.gw, self.hc * 2)
        return x, y / 2.0

    def screen_cell(self, lon, lat):
        """(column, row) of a point, or None hidden or off the window.

        `cell` with the two rejections a placement needs: the far
        hemisphere, which no window reaches, and the cells outside the
        window, which the flat rasteriser rejects by its bbox.
        """
        return marker_cell(self.lat, self.lon, self.zoom, self.gw, self.hc,
                           lat, lon)

    def ground(self, col, row):
        """(lat, lon) under the middle of a cell, or None off the disk.

        `cell` run backwards, for the two questions a rasteriser cannot
        answer from a bbox once the window is a patch of a sphere: what
        sea a body of water opens into, and which of a world list's
        places are on the screen at all.  A cell's middle is its own
        column's middle and the boundary between its two sub-pixels,
        which is where `cell` puts a point it rounds into that cell.
        """
        r = _radius(self.zoom, self.hc * 2)
        ux = (col + 0.5 - self.gw / 2.0) / (r * self.aspect)
        uy = (self.hc - (row + 0.5) * 2.0) / r
        at = _unproject(ux, uy, math.sin(math.radians(self.lat)),
                        math.cos(math.radians(self.lat)))
        if at is None:
            return None
        return (at[0], wrap_lon(self.lon + at[1]))

    def plane(self, dw, dh):
        """(rx, r, sin lat0, cos lat0, half width, half height) for a grid.

        What a rasteriser needs to place a vertex without calling this
        class per vertex.  The projection is not separable — a
        longitude moves a point up the screen as well as across it —
        but it is *bilinear* in the two axes' trigonometry:

            ux = cos φ · sin δ
            uy = cos φ0 · sin φ − sin φ0 · cos φ · cos δ

        so a tile's rows and columns can each be turned once and every
        vertex after that is four multiplies.  That is what makes the
        camera affordable on a quarter of a million polygon vertices.
        """
        r = _radius(self.zoom, dh)
        phi0 = math.radians(self.lat)
        return (r * self.aspect, r, math.sin(phi0), math.cos(phi0),
                dw / 2.0, dh / 2.0)

    def __repr__(self):
        return (f"Camera({self.lat:.4f}, {self.lon:.4f}, {self.zoom:.4g}, "
                f"{self.gw}x{self.hc})")


_canvas_cache = Memo(keep=2)  # this zoom's canvas and the last one's


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
    return cache_dir("maps", f"globe_canvas_v1_{z}.bin")


def _canvas_read(path):
    try:
        blob = zlib.decompress(path.read_bytes())
        cw, ch, org_x, org_y, world = struct.unpack(">5I", blob[:20])
        canvas = bytearray(blob[20:])
        if len(canvas) != cw * ch * 4:
            return None
        return canvas, cw, ch, org_x, org_y, world
    except FileNotFoundError:
        return None  # not baked yet: the usual cold-cache case
    except Exception as exc:
        log_failure("cache", f"read of {path.name}", exc, fallback="restitching")
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
    vendored = data_path(f"globe_canvas_{z}.bin")
    return _canvas_read(vendored) or _canvas_read(_canvas_path(z))


def _canvas_store(z, hit):
    canvas, cw, ch, org_x, org_y, world = hit
    try:
        path = _canvas_path(z)
        path.parent.mkdir(parents=True, exist_ok=True)
        _cache.write_bytes_atomic(
            path, zlib.compress(struct.pack(">5I", cw, ch, org_x, org_y,
                                            world) + bytes(canvas), 6))
    except Exception as exc:
        log_failure("cache", f"write of globe canvas z{z}", exc, fallback="not cached")


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
            except Exception as exc:
                log_failure("maps/elevation", f"globe tile {z_}/{x}/{y} decode", exc,
                            fallback="hole left, canvas not cached")
                missed[0] = True
                return None

        bbox = (-180.0, -_MERCATOR_LAT, 180.0, _MERCATOR_LAT)
        hit = stitch_xyz(fetch, bbox, z)
        # a canvas with holes (a tile the network dropped) must not be
        # frozen to disk: the holes would outlive the outage
        if not missed[0]:
            _canvas_store(z, hit)
    _canvas_cache.put(z, hit)
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


def limb_shading(zoom, gw, hc):
    """Whether the limb falloff can change a sub-pixel at this zoom.

    The falloff is a multiply by 0.58 + 0.42·√z, and z is one at the
    centre of the disk: a window small enough is a window where the
    deepest corner of it is still scaled by something that rounds to
    unity in eight bits.  Below that the falloff is arithmetic that
    cannot move a pixel, and skipping it is what keeps a close terrain
    view the bytes it has always been.  Above it the vignette arrives
    one channel step at a time, which is the whole point of a camera
    that does not switch.
    """
    rho2 = min(1.0, cap_sine(zoom, gw, hc) ** 2)
    m = 0.58 + 0.42 * math.sqrt(math.sqrt(max(0.0, 1.0 - rho2)))
    return (1.0 - m) * 255.0 >= 0.5


def shade_buffer(buf, shade, atmo, bg):
    """Limb-darken the disk and breathe the atmosphere onto space.

    `buf` is the paint pipeline's sub-pixel RGB grid, modified in
    place; `shade` and `atmo` come from a GlobeView.  The falloff is
    gentle — the sun already lives in the hillshade — but it is what
    makes the edge of the disk read as the edge of a sphere.

    `atmo` is None for a window the limb does not reach: there is no
    space on screen to breathe onto, and the grid of zeros it would
    take to say so is a grid the size of the frame.
    """
    for y, row in enumerate(buf):
        s_row = shade[y]
        a_row = atmo[y] if atmo is not None else None
        for x, px in enumerate(row):
            z = s_row[x]
            if z is not None:
                m = 0.58 + 0.42 * math.sqrt(z)
                row[x] = (int(px[0] * m), int(px[1] * m), int(px[2] * m))
            elif a_row is not None and a_row[x] > 0.0:
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
    rx = r * _aspect()
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
            ux = (x + 0.5 - w / 2.0) / rx
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


def fill_buffer(elev, water, ground, bg, wet=None):
    """Street-register fills for the globe: flat sea, flat ground.

    The street map's planet is the street map's idiom — two quiet
    fills and a braille coastline — bent onto the sphere, in the same
    water and ground the flat map paints, so the hand-off changes the
    curvature and nothing else.  A palette that paints no fills (the
    16-colour line map) gets background, and the coastline carries the
    geography alone, exactly as it does on the flat map.

    `wet` is the optional sub-pixel inland mask, and it takes the same
    fill the sea does: street mode draws one water, whether it is an
    ocean or a lake.
    """
    buf = []
    for y, row in enumerate(elev):
        wet_row = wet[y] if wet is not None else None
        out = []
        for x, e in enumerate(row):
            if wet_row is not None and wet_row[x]:
                out.append(water if water is not None else bg)
            elif e is None:
                out.append(bg)
            elif e <= 0:
                out.append(water if water is not None else bg)
            else:
                out.append(ground if ground is not None else bg)
        buf.append(out)
    return buf


_BORDER_TRIG = (None, None)  # (borders list identity, its trig form)


def _border_trig():
    """Every border polyline as trig, with the cap that covers it.

    forward() spends four radians() and four trig calls per vertex,
    and border_layer() asks it about twenty-five thousand vertices a
    frame; only the centre changes between frames.  Keyed to the list
    object itself so a test swapping the basemap data gets fresh
    trig.

    Each polyline carries the unit vector of its middle and the angle
    that reaches its farthest vertex, exactly as a lake does: one dot
    product against the view centre then answers whether any of it can
    be on screen.  A spherical cap is convex, so a chord between two
    vertices inside one stays inside it, and a polyline the cap test
    drops cannot have put a dot on the screen by any route.
    """
    global _BORDER_TRIG
    borders = _load_data()["borders"]
    if _BORDER_TRIG[0] is not borders:
        radians, sin, cos = math.radians, math.sin, math.cos
        trig = []
        for coords in borders:
            pts, vecs = [], []
            for lon, lat in coords:
                phi, lam = radians(lat), radians(lon)
                sin_phi, cos_phi = sin(phi), cos(phi)
                pts.append((sin_phi, cos_phi, lam))
                vecs.append((cos_phi * cos(lam), cos_phi * sin(lam), sin_phi))
            cx = sum(v[0] for v in vecs) / len(vecs)
            cy = sum(v[1] for v in vecs) / len(vecs)
            cz = sum(v[2] for v in vecs) / len(vecs)
            norm = math.sqrt(cx * cx + cy * cy + cz * cz)
            if norm < 1e-9:
                # vertices all round the sphere: no cap covers it, so
                # it is never culled
                trig.append((pts, 0.0, 0.0, 0.0, -1.0))
                continue
            cx, cy, cz = cx / norm, cy / norm, cz / norm
            cos_r = min(1.0, max(-1.0,
                                 min(v[0] * cx + v[1] * cy + v[2] * cz
                                     for v in vecs)))
            trig.append((pts, cx, cy, cz, cos_r))
        _BORDER_TRIG = (borders, trig)
    return _BORDER_TRIG[1]


def border_layer(lat0, lon0, zoom, gw, hc, color):
    """Natural Earth borders stroked onto the sphere as a braille layer.

    Both endpoints of a segment must face the viewer, and a segment
    whose endpoints are more than ~70 degrees of arc apart is skipped —
    two points that far apart in the vendored polylines are an artifact
    of simplification, and their chord would slice across the disk.
    The per-vertex arithmetic is forward() with its trig hoisted.

    Two rejections keep this affordable at a zoom where the disk is
    thousands of rows across and the window is a patch of it.  A
    polyline whose cap does not meet the window's cap is dropped
    without a vertex being touched — otherwise every border on the
    planet would be projected for a view of one valley.  And a segment
    with both ends off the same edge of the grid is dropped before
    Bresenham is asked to walk the thousands of dots between them.
    Neither changes a dot that is drawn: a rejection only ever drops
    ink that was never on screen.

    The cap test carries a slack for that promise.  What is drawn is
    the *chord* between two vertices, and a chord's middle lies inside
    the sphere, so it projects nearer the centre of the disk than its
    ends do — by the sagitta of the longest arc this draws, a little
    over seventy degrees.  The window's cap is widened by exactly that
    before the test, so a polyline dropped cannot have reached the
    screen by the one route its vertices do not describe.
    """
    layer = DotLayer((0.0, 0.0, 1.0, 1.0), gw, hc)
    dot_line = layer._dot_line
    dw, dh = gw * 2, hc * 4
    r = _radius(zoom, dh)
    rx = r * _aspect()
    cx, cy = dw / 2.0, dh / 2.0
    phi0, lam0 = math.radians(lat0), math.radians(lon0)
    sin0, cos0 = math.sin(phi0), math.cos(phi0)
    vx, vy, vz = cos0 * math.cos(lam0), cos0 * math.sin(lam0), sin0
    sin, cos, sqrt = math.sin, math.cos, math.sqrt
    view = math.asin(min(1.0, sin(cap(zoom, gw, hc)) / _CHORD_DIP))
    sin_v, cos_v = sin(view), cos(view)
    for pts, bx, by, bz, cos_r in _border_trig():
        if cos_r >= 0.0:
            # cos of the angle between the two cap centres, against
            # the cosine of their radii summed: no meeting, no ink
            d = bx * vx + by * vy + bz * vz
            sin_r = sqrt(max(0.0, 1.0 - cos_r * cos_r))
            if d < cos_r * cos_v - sin_r * sin_v:
                continue
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
            p = (cx + ux * rx, cy - uy * r, ux, uy, cos_c)
            if prev is not None:
                arc = prev[2] * ux + prev[3] * uy + prev[4] * cos_c
                if arc > 0.34 and not _off_grid(prev[0], prev[1],
                                                p[0], p[1], dw, dh):
                    dot_line(prev[0], prev[1], p[0], p[1], color)
            prev = p
    return layer


# How near the disk's centre the middle of the longest chord this
# strokes can fall, as a fraction of its ends' distance: the arc gate
# below admits chords of up to about seventy degrees, and the middle of
# one lies cos(35°) of the way out.
_CHORD_DIP = 0.8188

# Half a dot of slack on every edge, because the walker rounds its
# endpoints: a segment ending at -0.4 draws its first dot at zero.
_EDGE = 0.51


def _off_grid(x0, y0, x1, y1, dw, dh):
    """Whether a segment lies wholly off one edge of a dot grid."""
    return ((x0 < -_EDGE and x1 < -_EDGE)
            or (x0 > dw - _EDGE and x1 > dw - _EDGE)
            or (y0 < -_EDGE and y1 < -_EDGE)
            or (y0 > dh - _EDGE and y1 > dh - _EDGE))


# A lake that would paint fewer than this many dots is not drawn: one
# or two dots tint no sub-pixel of fill, and the shoreline stroked
# round them reads as dirt on the disk rather than as water.  The
# Canadian Shield alone would speckle a whole province.
_LAKE_MIN_DOTS = 3

# _lake_trig() memo: (lake polygons in projection-ready trig, each
# with the spherical cap that covers it).  Keyed to the list object
# itself so a test swapping the basemap data gets fresh trig.
_LAKE_TRIG = (None, None)


def _lake_trig():
    """Every lake as rings of (sin lat, cos lat, lon), plus its cap.

    The same per-vertex hoist border_layer() gets, and one addition:
    the unit vector of the polygon's middle and the angle that reaches
    its farthest vertex.  A single dot product against the view centre
    then answers both questions a frame asks of a lake — is all of it
    on the near side of the limb, and is it wider than a dot — without
    touching a vertex.
    """
    global _LAKE_TRIG
    lakes = _load_data().get("lakes", ())
    if _LAKE_TRIG[0] is not lakes:
        radians, sin, cos = math.radians, math.sin, math.cos
        out = []
        for rings in lakes:
            pts, vecs = [], []
            for ring in rings:
                trig = []
                for lon, lat in ring:
                    phi, lam = radians(lat), radians(lon)
                    sin_phi, cos_phi = sin(phi), cos(phi)
                    trig.append((sin_phi, cos_phi, lam))
                    vecs.append((cos_phi * cos(lam), cos_phi * sin(lam),
                                 sin_phi))
                pts.append(trig)
            cx = sum(v[0] for v in vecs) / len(vecs)
            cy = sum(v[1] for v in vecs) / len(vecs)
            cz = sum(v[2] for v in vecs) / len(vecs)
            norm = math.sqrt(cx * cx + cy * cy + cz * cz)
            if norm < 1e-9:
                continue  # vertices all round the sphere: not a lake
            cx, cy, cz = cx / norm, cy / norm, cz / norm
            cos_r = min(1.0, max(-1.0, min(v[0] * cx + v[1] * cy + v[2] * cz
                                           for v in vecs)))
            out.append((pts, cx, cy, cz, cos_r,
                        math.sqrt(1.0 - cos_r * cos_r), math.acos(cos_r)))
        _LAKE_TRIG = (lakes, out)
    return _LAKE_TRIG[1]


def lake_mask(lat0, lon0, zoom, dw, dh):
    """Dot-resolution inland water over the disk, or None for none of it.

    Elevation cannot report a lake: a terrarium sample over Superior
    reads the surface's hundred and eighty metres, which is the meadow
    beside it too.  So the flat map takes its lakes from the vector
    tiles, and those stop long before planet scale — the globe carves
    the same Natural Earth lakes the radar basemap does, projected
    onto the disk and scanline-filled, even-odd across a polygon's
    rings so an island in a lake stays dry.

    A lake is drawn only if it lies wholly on the near side of the
    limb and paints more than a dot or two.  A lake on the limb is
    foreshortened to nothing anyway, and the ponds are a speckle no
    cell could resolve.
    """
    r = _radius(zoom, dh)
    rx = r * _aspect()
    ox, oy = dw / 2.0, dh / 2.0
    phi0, lam0 = math.radians(lat0), math.radians(lon0)
    sin0, cos0 = math.sin(phi0), math.cos(phi0)
    vx, vy, vz = cos0 * math.cos(lam0), cos0 * math.sin(lam0), sin0
    sin, cos, sqrt = math.sin, math.cos, math.sqrt
    rows = [bytearray(dw) for _ in range(dh)]
    any_water = False
    for pts, lx, ly, lz, cos_r, sin_r, rad in _lake_trig():
        if 2.0 * rad * r < 1.0:
            continue  # narrower than the dot that would have to hold it
        d = lx * vx + ly * vy + lz * vz
        if d <= 0.0 or d * cos_r - sqrt(max(0.0, 1.0 - d * d)) * sin_r <= 0.02:
            continue  # over the limb, in whole or in part
        prings = []
        for ring in pts:
            projected = []
            for sin_phi, cos_phi, lam in ring:
                delta = lam - lam0
                ux = cos_phi * sin(delta)
                uy = cos0 * sin_phi - sin0 * cos_phi * cos(delta)
                projected.append((ox + ux * rx, oy - uy * r))
            prings.append(projected)
        ys = [p[1] for ring in prings for p in ring]
        y0 = max(0, int(min(ys)))
        y1 = min(dh - 1, int(max(ys)) + 1)
        spans, painted = [], 0
        for y in range(y0, y1 + 1):
            yc = y + 0.5
            xs = []
            for ring in prings:
                for i in range(len(ring) - 1):
                    ax, ay = ring[i]
                    bx, by = ring[i + 1]
                    if (ay <= yc < by) or (by <= yc < ay):
                        xs.append(ax + (yc - ay) / (by - ay) * (bx - ax))
            xs.sort()
            for i in range(0, len(xs) - 1, 2):
                xa = max(0, int(xs[i] + 0.5))
                xb = min(dw, int(xs[i + 1] + 0.5))
                if xb > xa:
                    spans.append((y, xa, xb))
                    painted += xb - xa
        if painted < _LAKE_MIN_DOTS:
            continue
        any_water = True
        for y, xa, xb in spans:
            row = rows[y]
            for x in range(xa, xb):
                row[x] = 1
    return rows if any_water else None


def marker_cell(lat0, lon0, zoom, gw, hc, m_lat, m_lon):
    """Terminal (col, row) under a lat/lon, or None if hidden or off-screen."""
    ux, uy, cos_c = forward(m_lat, m_lon, lat0, lon0)
    if cos_c <= 0.0:
        return None  # the far hemisphere
    r = _radius(zoom, hc * 2)
    col = int(gw / 2.0 + ux * r * _aspect())
    row = int((hc * 2 / 2.0 - uy * r) / 2.0)
    if 0 <= col < gw and 0 <= row < hc:
        return (col, row)
    return None


# city_overlays() memo: the placement depends only on the view and the
# language, but every repaint asks for it — hover included.  Keyed
# with the cities list's identity so swapped-in test data misses.
_OVERLAY_KEEP = 4
_overlay_cache = Memo(keep=_OVERLAY_KEEP)


def city_overlays(lat0, lon0, zoom, gw, hc, lang="en"):
    """{(col,row): (char, color)} for the biggest visible cities + labels.

    The same biggest-first greedy placement as the flat basemap's, with
    one extra gate: nothing lands within the outer tenth of the disk,
    where orthographic compression stacks a continent into a cell and a
    label would point at geography it half covers.

    Memoised per view: the dict is shared between calls, so read it.
    """
    cities = _load_data()["cities"]
    key = (lat0, lon0, zoom, gw, hc, lang, id(cities), _aspect())
    with _memo_lock:
        hit = _overlay_cache.get(key)
    if hit is not None:
        return hit
    hit = _place_cities(cities, lat0, lon0, zoom, gw, hc, lang)
    with _memo_lock:
        _overlay_cache.put(key, hit)
    return hit


# _city_trig() memo: (cities list identity, its trig form).  Keyed to
# the list object itself so a test swapping the basemap data gets
# fresh trig.
_CITY_TRIG = (None, None)


def _city_trig(cities):
    """Every city as (entry, sin lat, cos lat, lon, x, y), biggest first.

    The per-vertex hoist _border_trig() gets, and two additions.  The
    city's place in space, so one dot product against the view centre
    drops the far hemisphere before any trig is spent on it — the cap
    test lake_mask() makes, one city wide.  And the whole list ordered
    by population once, so placement can walk it biggest-first and
    stop the moment the screen is full: a frame then looks at a few
    hundred cities rather than at every one of the five thousand.  The
    unit vector's third component is sin lat, already there.
    """
    global _CITY_TRIG
    if _CITY_TRIG[0] is not cities:
        radians, sin, cos = math.radians, math.sin, math.cos
        out = []
        for entry in cities:
            phi, lam = radians(entry[1]), radians(entry[0])
            cos_phi = cos(phi)
            out.append((entry, sin(phi), cos_phi, lam,
                        cos_phi * cos(lam), cos_phi * sin(lam)))
        # stable, so this order restricted to the cities in view is the
        # order the in-view list would sort itself into
        out.sort(key=lambda c: c[0][2], reverse=True)
        _CITY_TRIG = (cities, out)
    return _CITY_TRIG[1]


def _place_cities(cities, lat0, lon0, zoom, gw, hc, lang):
    max_cities = max(6, min(24, (gw * hc) // 400))
    r = _radius(zoom, hc * 2)
    rx = r * _aspect()
    phi0, lam0 = math.radians(lat0), math.radians(lon0)
    sin0, cos0 = math.sin(phi0), math.cos(phi0)
    vx, vy, vz = cos0 * math.cos(lam0), cos0 * math.sin(lam0), sin0
    # The farthest from the view centre a placed city can lie: the
    # screen's own corner, or the visibility gate below, whichever
    # binds first.  A cell over-generous on purpose — the cap only has
    # to pass a city on, never to decide about one.
    rho2 = ((gw / 2.0 + 1.0) / rx) ** 2 + ((hc + 2.0) / r) ** 2
    cap = (math.sqrt(1.0 - rho2) if rho2 < 0.96 else 0.2) - 1e-9
    sin, cos = math.sin, math.cos
    half_w, half_h = gw / 2.0, hc * 2 / 2.0

    overlays = {}
    placed = []
    for entry, sin_phi, cos_phi, lam, px, py in _city_trig(cities):
        if len(placed) >= max_cities:
            break
        if px * vx + py * vy + sin_phi * vz < cap:
            continue  # nowhere the screen reaches
        d = lam - lam0
        cos_d = cos(d)
        if sin0 * sin_phi + cos0 * cos_phi * cos_d < 0.2:
            continue  # forward()'s cos_c, with the trig hoisted
        ux = cos_phi * sin(d)
        uy = cos0 * sin_phi - sin0 * cos_phi * cos_d
        col = int(half_w + ux * rx)
        row = int((half_h - uy * r) / 2.0)
        if not (0 <= col < gw and 0 <= row < hc):
            continue
        if (col, row) in overlays:
            continue
        if any(abs(col - pc) < 16 and abs(row - pr) < 3 for pc, pr in placed):
            continue
        placed.append((col, row))
        overlays[(col, row)] = ("•", CITY)
        name = _localized(entry, lang)
        c = col + 1
        prev = None
        for ch in name:
            w = char_width(ch)
            if w == 0 and prev is not None:
                # A combining mark rides in its base's cell.
                kept, ink = overlays[prev]
                overlays[prev] = (kept + ch, ink)
                continue
            if c + w > gw:
                break
            if (c, row) in overlays or (w == 2 and (c + 1, row) in overlays):
                break
            overlays[(c, row)] = (ch, CITY_LABEL)
            prev = (c, row)
            if w == 2:
                overlays[(c + 1, row)] = ("", None)
            c += w
    return overlays
