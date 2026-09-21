"""The planet, shaded once, so a globe frame is a lookup per sample.

Every globe frame used to rebuild the world: terrarium elevation for
fifty thousand braille dots, a hillshade over the sub-pixels under
them, the Natural Earth borders re-stroked and the lakes re-filled —
all of it from data that does not change between frames.  Only the
centre changes.  So the planet is baked once into an equirectangular
texture, in the projection-free coordinates `_globe.geometry` already
hands out, and a frame samples it.

Two pitches, because a frame samples at two.  A mask plane at the
braille dot's pitch carries the bits a stroke is cut from — water,
lake, border — so the coastline stays derived from the fill and the
borders stay a braille layer.  A pair of coarser fill levels carry the
colour a sub-pixel takes and the metres the readout probe reports; a
frame picks the coarsest level still no coarser than its own
sub-pixels, which is what keeps a wide view from sparkling and a close
one from going soft.

Borders are stroked into all three, each at its own pitch, and read
from whichever is coarsest without being coarser than a dot.  One
plane would not do: a stroke cut for the mask and read at a wider
view's dots is sampled finer than it was drawn, and comes back
dashed.  It is the rule the fill levels already follow, applied to the
one layer that is a line rather than a field.

Longitude is the one thing a spin changes, and on an equirectangular
texture longitude is a column.  So the sample-to-texel map is memoised
per (centre latitude, zoom, grid) and the frame rolls the planes
sideways instead — one C-speed slice per row against fifty thousand
additions.

Baking is a second or two of pure Python, so it never happens on the
way to a live frame: the first globe frame without a texture starts
one thread for that key and draws through the old path meanwhile.
"""

import math
import struct
import threading
import time
import zlib
from array import array
from collections import namedtuple
from operator import itemgetter

from linecast import _cache, _climate, _live, _theme
from linecast._maps import globe as _globe
from linecast._maps import paint
from linecast._maps import style
from linecast._color import BG_PRIMARY, color_mode
from linecast._live import nudge as _nudge_repaint
from linecast._paths import cache_dir, data_path
from linecast._radar.basemap import _BITS, DotLayer, _bresenham, _load_data
from linecast._radar.tiles import _TILE_SIZE
from linecast._runtime import log_failure
from linecast._scenes import Memo

# mask bits, one texel to a byte
SAMPLED = 0x80   # on the planet at all, so padding is in neither mask
WATER = 1        # sea or lake: what the coastline is cut from
LAKE = 2         # inland water alone, which the fills tint apart
BORDER = 4

_FORMAT = 2      # on-disk layout; a change renames every cached texture

# A lake that fills fewer than this many texels is not baked at all,
# which is `_globe._LAKE_MIN_DOTS` moved to where it can be paid once:
# the mask's pitch is a braille dot's, so a lake too small to hold
# three texels is the speckle that rule has always dropped.
_LAKE_MIN_TEXELS = 3

# Borders are stroked into every plane a frame can read them from —
# the mask and both fill levels — because a stroke read at a pitch
# coarser than the one it was cut for comes back dashed, and never
# sampling finer than the pitch is the rule the fill already follows.
# A frame takes the coarsest plane still no coarser than its own dots,
# which holds a dot to about two texels of whatever it reads, and two
# filled texels is the stroke that survives that: a stroke touching
# only at its corners is stepped over on a diagonal, and a three-texel
# one comes back half as thick again as the line the old path drew.
# The three planes were measured apart and wanted the same brush,
# because the pitch each is read at is what the plane choice equalises.
#
# The exception is the widest zoom on a terminal under about twelve
# rows: `_globe._source_zoom` floors at 1, level 1 is the coarsest
# plane there is, and a dot spans nearly three of its texels.  A
# slanted border thins there.  The planet is forty dots across at that
# size, so what it costs is a dot here and there on a disk that has
# few to begin with.
_BORDER_BRUSH = ((0, 0), (0, 1), (1, 0), (1, 1))

# rows shaded per build_terrain_buffer call: enough that the one-row
# halo each band needs for its gradients is a rounding error, few
# enough that a bake never holds more than a band of colour tuples
_BAND = 64

# rows of baking between breaths, and the length of one
_BREATHE_ROWS = 16
_BREATHE_S = 0.01


def _breathe(y):
    """Hand the frame loop the interpreter for a moment, every so often.

    A bake is pure Python, so a live view's repaint and a bake are
    rivals for the one lock that matters — and the repaint is the one
    that waits on the terminal, which is exactly the thread the GIL
    treats worst.  Off the live loop the bake runs flat out; on it, it
    stops for long enough, often enough, that a drag still turns.
    """
    if _live._running and not y % _BREATHE_ROWS:
        time.sleep(_BREATHE_S)


Level = namedtuple("Level", "w h r g b elev border")
# The colour planes are None for the street register, which paints two
# flat fills and asks the texture only where the water is.  `border`
# is this level's own stroke, one texel to a byte, for the frames
# whose dots are too coarse to read the mask's.

Texture = namedtuple("Texture", "z register mask mask_w mask_h levels")


class _BytePlane:
    """One texture plane, kept as rows and handed out rolled.

    A frame wants the plane flat with longitude zero under the view's
    centre meridian, which is a slice and a join per row.  The result
    is kept beside the rows, so a repaint that has not turned the
    planet pays nothing; it is kept as one tuple, replaced whole, so a
    worker rolling for its own centre can never hand another thread a
    plane rolled for someone else's.
    """
    __slots__ = ("rows", "_cached")

    def __init__(self, rows):
        self.rows = rows
        self._cached = (None, None)

    def at(self, shift):
        cached = self._cached
        if cached[0] == shift:
            return cached[1]
        rows = self.rows
        flat = (b"".join(rows) if not shift
                else b"".join([r[shift:] + r[:shift] for r in rows]))
        self._cached = (shift, flat)
        return flat


class _ShortPlane(_BytePlane):
    """A plane of signed 16-bit metres, rolled the same way."""
    __slots__ = ()

    def at(self, shift):
        cached = self._cached
        if cached[0] == shift:
            return cached[1]
        flat = array("h")
        for r in self.rows:
            flat.extend(r[shift:])
            flat.extend(r[:shift])
        self._cached = (shift, flat)
        return flat


def _mask_dims(z):
    """The mask plane's texel grid for a terrarium source zoom.

    Twice the source canvas across, so the bits a braille dot lands on
    come from an interpolated elevation rather than the nearest tile
    pixel — that is what keeps the coastline the smooth contour
    bilinear sampling used to draw — and half that tall, because an
    equirectangular planet is twice as wide as it is high.
    """
    world = _TILE_SIZE << z
    return world * 2, world


def _texel_degrees(tex, level):
    return 180.0 / tex.levels[level].h


def _border_planes(tex):
    """Every plane the borders are stroked into, finest pitch first.

    Each carries the bits for a texel that is 0 or 1 already, except
    the mask, where the border shares a byte with the water bits and a
    translation table cuts it out.
    """
    return ((tex.mask_w, tex.mask_h, tex.mask, _BORDER_TABLE),
            *((lv.w, lv.h, lv.border, None) for lv in tex.levels))


def border_level_for(tex, zoom, hc):
    """Which border plane a frame's braille dots should read.

    `level_for`'s rule, for `level_for`'s reason, one step finer: a
    dot spans zoom/(hc*4) degrees, and a stroke cut at a pitch coarser
    than that would be read finer than it was drawn.  Below it, the
    coarsest plane is the one whose stroke was widened for the widest
    resample — read the mask's two texels at a dot pitch twice theirs
    and the diagonals dash.
    """
    span = zoom / (hc * 4.0)
    planes = _border_planes(tex)
    best = 0
    for i in range(len(planes)):
        if 180.0 / planes[i][1] <= span:
            best = i
    return best


def level_for(tex, zoom, hc):
    """The coarsest fill level still no coarser than a sub-pixel.

    A sub-pixel spans zoom/(hc*2) degrees.  Sampling a texture finer
    than that throws texels away and sparkles; sampling one coarser
    softens what the screen could have shown.  So a frame takes the
    last level that still fits inside its own sub-pixel.
    """
    span = zoom / (hc * 2.0)
    best = 0
    for i in range(len(tex.levels)):
        if _texel_degrees(tex, i) <= span:
            best = i
    return best


# ---------------------------------------------------------------------------
# sampling
# ---------------------------------------------------------------------------

_SAMPLER_KEEP = 6      # the two or three grids a view reads, twice over
_sampler_cache = Memo(keep=_SAMPLER_KEEP)
_sampler_lock = threading.Lock()

_LAND_TABLE = bytes(1 if i & SAMPLED and not i & WATER else 0
                    for i in range(256))
_WATER_TABLE = bytes(1 if i & WATER else 0 for i in range(256))
_BORDER_TABLE = bytes(1 if i & BORDER else 0 for i in range(256))


def _row_getters(lat0, zoom, w, h, tw, th):
    """Per grid row, (first visible column, count, a getter for its texels).

    The getter is an `operator.itemgetter` over the row's texel
    indices, which pulls a whole row out of a rolled plane in C.  The
    indices carry longitude *east of the view centre*, so they outlive
    every spin and every sideways drag; the frame supplies the centre
    as the roll.
    """
    out = []
    kx, ky = tw / 360.0, th / 180.0
    last = th - 1
    for b_row in _globe.relative(lat0, zoom, w, h):
        # the disk's samples are one run per row, so the row's texels
        # are one comprehension rather than a test per sample
        x0, n = 0, len(b_row)
        while x0 < n and b_row[x0] is None:
            x0 += 1
        n -= x0
        while n and b_row[x0 + n - 1] is None:
            n -= 1
        idx = [min(last, int((90.0 - b[0]) * ky)) * tw
               + int((b[1] + 180.0) * kx) % tw
               for b in b_row[x0:x0 + n]]
        if len(idx) > 1:
            out.append((x0, len(idx), itemgetter(*idx)))
        elif idx:
            # itemgetter of one index returns the texel itself, not a
            # one-texel sequence, and every caller here joins what it
            # gets back; the lambda is what makes the one-sample row
            # (a pole, or the last row of the disk) the same shape
            out.append((x0, 1, lambda p, i=idx[0]: (p[i],)))
        else:
            out.append((x0, 0, None))
    return out


def _sampler(lat0, zoom, w, h, tw, th):
    key = (lat0, zoom, w, h, _globe._aspect(), tw, th)
    with _sampler_lock:
        hit = _sampler_cache.get(key)
    if hit is None:
        hit = _row_getters(lat0, zoom, w, h, tw, th)
        with _sampler_lock:
            _sampler_cache.put(key, hit)
    return hit


def _shift(lon0, tw):
    """The texel column longitude `lon0` falls in, as a roll.

    Whole texels, because nearest sampling quantises to them anyway.
    The roll and the row's own column index round apart, so a centre
    half a texel off can put a sample in the texel next to the one its
    longitude falls in — never further, and never up or down, since
    the latitude is floored on its own and the roll does not touch it.
    One texel east or west is below the pitch of everything read
    through it, so it moves the planet no further than nearest
    sampling already does.
    """
    return round(lon0 / 360.0 * tw) % tw


Sampled = namedtuple("Sampled", "fill elev land water borders")
# fill and elev are sub-pixel grids (fill None for the street globe);
# land and water are the dot masks the coastline is cut from, and
# borders the braille layer already stroked.


def _plane_rows(lat0, lon0, zoom, gw, hc, tw, th, plane, tables):
    """One dot-pitch row set per table, read out of one texture plane.

    A table is the 256-byte translation from a texel to a 0 or a 1;
    None means the plane holds those already.
    """
    dw = gw * 2
    rows = _sampler(lat0, zoom, dw, hc * 4, tw, th)
    flat = plane.at(_shift(lon0, tw))
    blank = bytes(dw)
    out = [[] for _ in tables]
    for x0, n, get in rows:
        if not n:
            for dst in out:
                dst.append(blank)
            continue
        f = bytes(get(flat))
        head, tail = bytes(x0), bytes(dw - x0 - n)
        for dst, table in zip(out, tables):
            dst.append(head + (f if table is None else f.translate(table))
                       + tail)
    return out


def _mask_rows(tex, lat0, lon0, zoom, gw, hc):
    """(land, water) dot rows read through the geometry."""
    return _plane_rows(lat0, lon0, zoom, gw, hc, tex.mask_w, tex.mask_h,
                       tex.mask, (_LAND_TABLE, _WATER_TABLE))


def _border_rows(tex, lat0, lon0, zoom, gw, hc):
    """Border dot rows, from whichever plane was cut for this dot pitch."""
    tw, th, plane, table = _border_planes(tex)[
        border_level_for(tex, zoom, hc)]
    return _plane_rows(lat0, lon0, zoom, gw, hc, tw, th, plane, (table,))[0]


def _border_layer(border, gw, hc, ink):
    """The border bits gathered into a braille layer."""
    layer = DotLayer((0.0, 0.0, 1.0, 1.0), gw, hc)
    dots, color = layer.dots, layer.color
    for dy, row in enumerate(border):
        even, odd = _BITS[0][dy & 3], _BITS[1][dy & 3]
        drow, crow = dots[dy >> 2], color[dy >> 2]
        pos = row.find(1)
        while pos >= 0:
            cx = pos >> 1
            drow[cx] |= odd if pos & 1 else even
            crow[cx] = ink
            pos = row.find(1, pos + 1)
    return layer


def _fill_rows(tex, lat0, lon0, zoom, gw, hc):
    """(sub-pixel RGB, sub-pixel metres); RGB is None for the street globe."""
    level = tex.levels[level_for(tex, zoom, hc)]
    rows = _sampler(lat0, zoom, gw, hc * 2, level.w, level.h)
    shift = _shift(lon0, level.w)
    metres = level.elev.at(shift)
    colour = (None if level.r is None
              else (level.r.at(shift), level.g.at(shift), level.b.at(shift)))
    fill = None if colour is None else []
    elev = []
    for x0, n, get in rows:
        after = gw - x0 - n
        elev.append([None] * x0 + (list(get(metres)) if n else [])
                    + [None] * after)
        if fill is None:
            continue
        span = (list(zip(get(colour[0]), get(colour[1]), get(colour[2])))
                if n else [])
        fill.append([BG_PRIMARY] * x0 + span + [BG_PRIMARY] * after)
    return fill, elev


def sample(tex, lat0, lon0, zoom, gw, hc, border_ink):
    """Everything a globe frame used to rebuild, read out of the texture."""
    land, water = _mask_rows(tex, lat0, lon0, zoom, gw, hc)
    fill, elev = _fill_rows(tex, lat0, lon0, zoom, gw, hc)
    border = _border_rows(tex, lat0, lon0, zoom, gw, hc)
    return Sampled(fill, elev, land, water,
                   _border_layer(border, gw, hc, border_ink))


# ---------------------------------------------------------------------------
# baking
# ---------------------------------------------------------------------------


def _canvas_row(canvas, cw, y):
    """(one stitched-canvas row decoded to metres, whether it had holes).

    A hole — the transparent pixel a dropped tile leaves — reads as
    sea level rather than as terrarium's -32768 metres, so a tile the
    network dropped is painted as open sea.  A texture with one in it
    is never written to disk, but nothing re-bakes it either: the
    tile stays sea for the rest of the session, and comes back on the
    next run.
    """
    chunk = canvas[y * cw * 4:(y + 1) * cw * 4]
    opaque = chunk[3::4]
    row = [r * 256 + g + b / 256.0 - 32768.0
           for r, g, b in zip(chunk[0::4], chunk[1::4], chunk[2::4])]
    if 0 in opaque:
        return [0.0 if not o else v for v, o in zip(row, opaque)], True
    return row, False


def _canvas_y(lat, world, org_y, ch):
    """Where a latitude lands on the stitched canvas: (row, row, blend)."""
    lat = max(-_globe._MERCATOR_LAT, min(_globe._MERCATOR_LAT, lat))
    sn = math.sin(math.radians(lat))
    fy = ((0.5 - math.log((1 + sn) / (1 - sn)) / (4 * math.pi)) * world
          - org_y - 0.5)
    fy = max(0.0, min(ch - 1.0, fy))
    y0 = int(fy)
    return y0, min(y0 + 1, ch - 1), fy - y0


def _elevation_plane(hit, tw, th):
    """Metres per texel of the mask grid, as rows of doubles.

    The stitched canvas is Mercator and the texture is not, but the
    two share their longitudes: a texel column lands on a canvas
    column exactly, and at twice the canvas's width halfway between
    two of them.  So a row costs one blend down the canvas and one
    across it, both whole-row comprehensions, instead of four taps and
    a decode per texel.

    The rows are arrays, not lists: a list of floats holds each value
    in its own object, four times the bytes, and at z3 the plane is
    eight million of them.
    """
    canvas, cw, ch, _org_x, org_y, world = hit
    holes = False
    cache = {}
    rows = []
    for ty in range(th):
        _breathe(ty)
        lat = 90.0 - (ty + 0.5) * 180.0 / th
        y0, y1, t = _canvas_y(lat, world, org_y, ch)
        cache = {y: cache[y] if y in cache else _canvas_row(canvas, cw, y)
                 for y in (y0, y1)}
        holes = holes or cache[y0][1] or cache[y1][1]
        a, b = cache[y0][0], cache[y1][0]
        mid = ([va + (vb - va) * t for va, vb in zip(a, b)] if t
               else list(a))[:world]
        row = array("d", bytes(8 * tw))
        row[0::2] = array("d", [0.25 * p + 0.75 * c
                                for p, c in zip(mid[-1:] + mid[:-1], mid)])
        row[1::2] = array("d", [0.75 * c + 0.25 * n
                                for c, n in zip(mid, mid[1:] + mid[:1])])
        rows.append(row)
    return rows, holes


def _crossings(rings, ty, tw, th):
    """Where a polygon's rings cross texture row `ty`, in x texels."""
    yc = 90.0 - (ty + 0.5) * 180.0 / th
    xs = []
    for ring in rings:
        for i in range(len(ring) - 1):
            ax, ay = ring[i]
            bx, by = ring[i + 1]
            if (ay <= yc < by) or (by <= yc < ay):
                lon = ax + (yc - ay) / (by - ay) * (bx - ax)
                xs.append((lon + 180.0) / 360.0 * tw)
    xs.sort()
    return xs


def _lake_plane(tw, th):
    """The vendored lake polygons scan-filled into the texture grid.

    Even-odd across a lake's rings, so an island in a lake stays dry,
    and a lake that comes out smaller than a braille dot is dropped
    whole rather than left to speckle the disk.
    """
    rows = [bytearray(tw) for _ in range(th)]
    for n, rings in enumerate(_load_data().get("lakes", ())):
        _breathe(n)
        lats = [p[1] for ring in rings for p in ring]
        y0 = max(0, int((90.0 - max(lats)) / 180.0 * th))
        y1 = min(th - 1, int((90.0 - min(lats)) / 180.0 * th) + 1)
        spans, painted = [], 0
        for ty in range(y0, y1 + 1):
            xs = _crossings(rings, ty, tw, th)
            for i in range(0, len(xs) - 1, 2):
                xa, xb = int(xs[i] + 0.5), min(tw, int(xs[i + 1] + 0.5))
                if xb > xa:
                    spans.append((ty, xa, xb))
                    painted += xb - xa
        if painted < _LAKE_MIN_TEXELS:
            continue
        for ty, xa, xb in spans:
            row = rows[ty]
            for x in range(xa, xb):
                row[x] = 1
    return rows


def _border_plane(tw, th):
    """The vendored border polylines stroked into a texel grid."""
    rows = [bytearray(tw) for _ in range(th)]
    kx, ky = tw / 360.0, th / 180.0
    last = th - 1
    for n, coords in enumerate(_load_data()["borders"]):
        _breathe(n)
        prev = None
        for lon, lat in coords:
            y = int((90.0 - lat) * ky)
            p = (int((lon + 180.0) * kx) % tw,
                 last if y > last else max(0, y))
            # a step of half the world is the antimeridian, not a border
            if prev is not None and abs(prev[0] - p[0]) * 2 <= tw:
                for x, y_ in _bresenham(prev[0], prev[1], p[0], p[1]):
                    for ox, oy in _BORDER_BRUSH:
                        rows[min(last, y_ + oy)][(x + ox) % tw] = 1
            prev = p
    return rows


def _mask_plane(elev, lakes, borders, tw):
    """The three bits and the sampled marker, one texel to a byte."""
    rows = []
    for ty, (e_row, l_row, b_row) in enumerate(zip(elev, lakes, borders)):
        _breathe(ty)
        row = bytearray(tw)
        for x in range(tw):
            v = SAMPLED
            if l_row[x]:
                v |= WATER | LAKE
            elif e_row[x] <= 0.0:
                v |= WATER
            if b_row[x]:
                v |= BORDER
            row[x] = v
        rows.append(bytes(row))
    return rows


def _halve(elev, lakes, w):
    """One mip step: metres and lake bits at half the pitch.

    The two rules the flat view reduces its fine grid by, kept — the
    wet samples alone decide a wet sample's depth, and two of four wet
    dots make one — so a shoreline neither bulges green into the
    water nor speckles a pond into a cell.
    """
    hw = w // 2
    out_e, out_l = [], []
    for y in range(0, len(elev), 2):
        _breathe(y)
        e0, e1, l0, l1 = elev[y], elev[y + 1], lakes[y], lakes[y + 1]
        e_row = array("d", bytes(8 * hw))
        l_row = bytearray(hw)
        for x in range(hw):
            x2 = x * 2
            q = (e0[x2], e0[x2 + 1], e1[x2], e1[x2 + 1])
            wet = [v for v in q if v <= 0.0]
            e_row[x] = (sum(wet) / len(wet) if len(wet) >= 2
                        else sum(q) * 0.25)
            if l0[x2] + l0[x2 + 1] + l1[x2] + l1[x2 + 1] >= 2:
                l_row[x] = 1
        out_e.append(e_row)
        out_l.append(l_row)
    return out_e, out_l, hw


def _band_lls(lo, hi, w, h):
    return [[(90.0 - (y + 0.5) * 180.0 / h,
              -180.0 + (x + 0.5) * 360.0 / w) for x in range(w)]
            for y in range(lo, hi)]


def _shade(elev, lakes, w, h):
    """The texture through the terrain shader, as three byte planes.

    A band at a time, and each band's colour tuples are packed into
    byte rows before the next is shaded: the tuples are the bake's
    largest transient, and only ever one band of them exists.
    """
    ice_id = style.COVER_ORDER.index("ice") + 1
    planes = ([], [], [])
    for y0 in range(0, h, _BAND):
        _breathe(y0)
        y1 = min(h, y0 + _BAND)
        lo, hi = max(0, y0 - 1), min(h, y1 + 1)
        band = elev[lo:hi]
        lls = _band_lls(lo, hi, w, h)
        # A scale-only bbox, the shape the globe has always handed the
        # shader: the whole width at the equator, so the figure it
        # works a slope out over is the metres a texel spans there and
        # nowhere else.  Narrowing it by the cosine of each row's
        # latitude would be the truer footprint and the wrong picture
        # — the ice sheets come out salt-and-pepper, because a slope
        # taken over a fifth of the distance is five times the slope,
        # while the old disk was shaded by one figure throughout.
        buf = paint.build_terrain_buffer(
            band, (0.0, -(hi - lo) * 90.0 / h, 360.0, (hi - lo) * 90.0 / h),
            w, hi - lo, water=lakes[lo:hi],
            cover=_globe.ice_cover(lls, band, ice_id),
            climate=_climate.grid_for_lls(lls) or ())
        for row in buf[y0 - lo:y1 - lo]:
            for i in range(3):
                planes[i].append(bytes([px[i] for px in row]))
    return tuple(_BytePlane(rows) for rows in planes)


def _metre_planes(rows):
    ceil = math.ceil
    # ceil, not round: it is the only rounding that never moves a
    # sample across the waterline, and the waterline is the coastline
    return _ShortPlane([array("h", [max(-32768, min(32767, ceil(v)))
                                    for v in row]) for row in rows])


def bake(z, register, timeout=15):
    """(the whole planet at source zoom `z`, whether its data had holes)."""
    hit = _globe._world_canvas(z, timeout)
    tw, th = _mask_dims(z)
    elev, holes = _elevation_plane(hit, tw, th)
    lakes = _lake_plane(tw, th)
    mask = _mask_plane(elev, lakes, _border_plane(tw, th), tw)
    levels, w = [], tw
    for _ in range(2):
        elev, lakes, w = _halve(elev, lakes, w)
        h = len(elev)
        rgb = ((None,) * 3 if register == "street"
               else _shade(elev, lakes, w, h))
        levels.append(Level(w, h, *rgb, _metre_planes(elev),
                            _BytePlane([bytes(r)
                                        for r in _border_plane(w, h)])))
    return Texture(z, register, _BytePlane(mask), tw, th,
                   tuple(levels)), holes


# ---------------------------------------------------------------------------
# keeping
# ---------------------------------------------------------------------------


def _stat_key(path):
    try:
        st = path.stat()
        return (st.st_size, st.st_mtime_ns)
    except OSError:
        return (0, 0)


def _digest(z, register):
    """What the baked bytes depend on, as one number in the file's name.

    The data the texture is carved from and, for the register that
    paints colour, every ink it is carved with — so a terminal that
    changes its theme misses the texture shaded for the old one
    instead of painting last night's palette.
    """
    parts = [_FORMAT, z, register,
             _stat_key(data_path(f"globe_canvas_{z}.bin")),
             _stat_key(data_path("basemap.json.gz"))]
    if register != "street":
        parts += [color_mode(), paint.HYPSO_FAMILIES,
                  paint.BATHY_STOPS, paint.LAKE_FILL,
                  style.COVER_COLOR, style.COVER_BLEND,
                  BG_PRIMARY]
    return zlib.crc32(repr(parts).encode()) & 0xFFFFFFFF


def _path(z, register):
    return cache_dir("maps", f"globe_texture_v{_FORMAT}_{z}_{register}_"
                             f"{_digest(z, register):08x}.bin")


def _dump(tex):
    out = [struct.pack(">4I", tex.z, tex.mask_w, tex.mask_h, len(tex.levels)),
           tex.mask.at(0)]
    for lv in tex.levels:
        out.append(struct.pack(">3I", lv.w, lv.h, lv.r is not None))
        out += [p.at(0) for p in (lv.r, lv.g, lv.b) if p is not None]
        out.append(lv.elev.at(0).tobytes())
        out.append(lv.border.at(0))
    return zlib.compress(b"".join(out), 6)


def _split(blob, off, rows, width):
    return [blob[off + y * width:off + (y + 1) * width] for y in range(rows)]


def _undump(blob, register):
    z, mw, mh, nlevels = struct.unpack(">4I", blob[:16])
    off = 16
    mask = _BytePlane(_split(blob, off, mh, mw))
    off += mw * mh
    levels = []
    for _ in range(nlevels):
        w, h, coloured = struct.unpack(">3I", blob[off:off + 12])
        off += 12
        planes = [None] * 3
        for i in range(3 if coloured else 0):
            planes[i] = _BytePlane(_split(blob, off, h, w))
            off += w * h
        elev = _ShortPlane([array("h", blob[off + y * w * 2:
                                            off + (y + 1) * w * 2])
                            for y in range(h)])
        off += w * h * 2
        border = _BytePlane(_split(blob, off, h, w))
        off += w * h
        levels.append(Level(w, h, *planes, elev, border))
    if off != len(blob):
        # a short plane would not fail here but on the first frame
        # that samples it, and on every frame after
        raise ValueError(f"globe texture is {len(blob)} bytes, not {off}")
    return Texture(z, register, mask, mw, mh, tuple(levels))


def _load(z, register):
    """A texture baked on an earlier run, or None."""
    try:
        return _undump(zlib.decompress(_path(z, register).read_bytes()),
                       register)
    except FileNotFoundError:
        return None  # not baked yet: the usual cold-cache case
    except Exception as exc:
        log_failure("cache", f"read of globe texture z{z}", exc,
                    fallback="rebaking")
        return None


def _store(z, register, tex):
    try:
        path = _path(z, register)
        path.parent.mkdir(parents=True, exist_ok=True)
        for old in path.parent.glob(f"globe_texture_v*_{z}_{register}_*.bin"):
            if old != path:
                old.unlink(missing_ok=True)
        _cache.write_bytes_atomic(path, _dump(tex))
    except Exception as exc:
        log_failure("cache", f"write of globe texture z{z}", exc,
                    fallback="not cached")


_TEXTURE_KEEP = 6      # three source zooms, two registers
_texture_cache = Memo(keep=_TEXTURE_KEEP)

# How long a key waits after a failed bake before another is started.
# A bake fails on the network or on the disk, and neither is mended by
# the next repaint: without the wait every frame would start a worker
# to fail the same way, and a live view repaints many times a second.
# `_scenes.FetchHold`'s bargain, with a failure in place of a gesture.
_BAKE_HOLD_S = 30.0

_pending = set()
_held = {}             # key -> when its bake last failed, monotonic
_texture_lock = threading.Lock()


def _key(z, register):
    # the theme generation rides along so a terminal that changes its
    # theme mid-session misses the texture shaded for the old one
    return (z, register, _theme.generation, color_mode())


def _build(z, register, key):
    tex = _load(z, register)
    if tex is None:
        tex, holes = bake(z, register)
        if _key(z, register) != key:
            # the theme changed under the bake: the bands shaded before
            # it carry the old inks, so the result belongs to no key
            # and the next frame starts over
            return None
        if not holes:
            _store(z, register, tex)
    return tex


def _holding(key):
    """Whether this key's last bake failed too recently to try again.

    Called under `_texture_lock`.
    """
    failed = _held.get(key)
    return failed is not None and time.monotonic() - failed < _BAKE_HOLD_S


def _finish(key, tex):
    with _texture_lock:
        _pending.discard(key)
        if tex is None:
            _held[key] = time.monotonic()
        else:
            _held.pop(key, None)
            _texture_cache.put(key, tex)
    return tex


def ready(zoom, h, register):
    """Whether a view at this zoom has its texture already; never builds.

    A view's cache key carries this, so the frame built the old way
    while the planet baked is not the one still on screen after it
    lands.
    """
    with _texture_lock:
        return _key(_globe._source_zoom(zoom, h), register) in _texture_cache


def for_view(zoom, h, register, block):
    """The texture a globe view at this zoom samples, or None.

    None means "draw the planet the old way this once": a bake is a
    second or two of arithmetic and a live frame may never wait on it,
    so a miss starts one thread for that key and nudges a repaint when
    it lands.  Off the live loop there is no later repaint to nudge —
    `--print` has one frame and then exits, taking the bake with it —
    so a blocking caller there builds the texture on the spot, which
    is the bargain `block` strikes everywhere else a view is loaded,
    and leaves it on disk for every run after.

    A texture already on disk is read on the calling thread, which is
    a view's own worker: a few tens of milliseconds, against the two
    hundred the old path costs — and the old path running beside a
    load starves the frame loop of the interpreter for longer than
    either takes alone.  Only a bake goes to a thread of its own.

    A bake that raises is held for `_BAKE_HOLD_S`, so a view that
    cannot be baked draws the old way for half a minute rather than
    starting a worker a frame.
    """
    z = _globe._source_zoom(zoom, h)
    key = _key(z, register)
    with _texture_lock:
        hit = _texture_cache.get(key)
        if hit is not None:
            return hit
        if key in _pending or _holding(key):
            return None
        _pending.add(key)

    if block and not _live._running:
        try:
            return _finish(key, _build(z, register, key))
        except Exception as exc:
            log_failure("maps/globe", "texture bake", exc,
                        fallback="unbaked globe")
            return _finish(key, None)

    tex = _load(z, register)
    if tex is not None:
        return _finish(key, tex)

    def worker():
        try:
            tex = _build(z, register, key)
        except Exception as exc:
            log_failure("worker", "globe texture bake", exc,
                        fallback="unbaked globe")
            tex = None
        if _finish(key, tex) is not None:
            _nudge_repaint()

    threading.Thread(target=worker, daemon=True).start()
    return None


def clear():
    """Forget every texture, every bake and every sampler.

    For the tests, which swap the basemap data and the theme under a
    module meant to notice neither more than once.
    """
    with _texture_lock:
        _texture_cache.clear()
        _pending.clear()
        _held.clear()
    with _sampler_lock:
        _sampler_cache.clear()
