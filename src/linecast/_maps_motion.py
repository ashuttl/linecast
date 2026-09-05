"""How the map moves: the last real frame, re-projected into the next.

The sky and the moon animate by arithmetic — every frame is a fresh
view of data already in memory.  The map cannot: a frame at a new
view is a fetch, elevation tiles or vector tiles or a stitched globe,
and a flight through forty in-between views would be forty fetches.
What the map can do is keep the last frame it drew from real data and
re-project *that* into wherever the camera has moved: a pan is a
shift, a zoom a scaling, a turn of the globe a per-cell projection,
and none of them touches the network.  The real view arrives when it
arrives and takes over; until then the picture on screen is the
previous one, moved.

A Geom is a frame's geometry — which projection, where it looks, how
big it is in cells.  A SampleMap says, for every cell of a target
Geom, which cell of a source Geom holds the same ground.  A Keyframe
is what a real frame was composed from, in a form any target can
resample; `placeholder()` is that resampling.  The flight path at the
end is van Wijk and Nuij's: zoom out just far enough to see both ends,
cross, zoom in, along the path that keeps the apparent speed steady.
"""

import math
import threading
import time
from math import floor

from linecast import _globe
from linecast._radar_render import bbox_for

KEEP = 3   # real frames remembered; the best-covering one serves


def ease_in_out(s):
    return s * s * (3.0 - 2.0 * s)


# ---------------------------------------------------------------------------
# Frame geometry
# ---------------------------------------------------------------------------
class Geom:
    """One frame's geometry: projection, centre, zoom and cell size.

    `zoom` is degrees of latitude top to bottom, as everywhere in maps.
    `bbox` is the flat window (meaningful on the globe only as a rough
    footprint).  The sub-pixel grid is gw wide and hc*2 tall.
    """
    __slots__ = ("globe", "lat", "lon", "zoom", "gw", "hc", "bbox")

    def __init__(self, lat, lon, zoom, gw, hc, globe=None):
        self.lat, self.lon, self.zoom = lat, lon, zoom
        self.gw, self.hc = gw, hc
        self.globe = (_globe.is_globe(zoom, lat) if globe is None
                      else globe)
        self.bbox = bbox_for(lat, lon, zoom, gw, hc)

    def same_size(self, other):
        return self.gw == other.gw and self.hc == other.hc

    def same_centre(self, other):
        # a millimetre: the centres come through a bbox and back, and
        # the last bits differ
        return (abs(self.lat - other.lat) < 1e-8
                and abs(_lon_delta(self.lon, other.lon)) < 1e-8)

    def overlap(self, other):
        """A rough fraction of `other`'s window this one covers, 0..1.

        Flat windows intersect as rectangles, the source folded by a
        turn of the planet to sit nearest the target.  A globe's
        window is its footprint, which is generous at the limb — good
        enough to pick the better of a few candidates.
        """
        minlon, minlat, maxlon, maxlat = other.bbox
        s_minlon, s_minlat, s_maxlon, s_maxlat = self.bbox
        shift = round(((minlon + maxlon) / 2 - (s_minlon + s_maxlon) / 2)
                      / 360.0) * 360.0
        s_minlon += shift
        s_maxlon += shift
        w = min(maxlon, s_maxlon) - max(minlon, s_minlon)
        h = min(maxlat, s_maxlat) - max(minlat, s_minlat)
        if w <= 0.0 or h <= 0.0:
            return 0.0
        return min(1.0, (w * h) / ((maxlon - minlon) * (maxlat - minlat)))

    def sub_lls(self):
        """(lat, lon) under each sub-pixel, None in space."""
        w, h = self.gw, self.hc * 2
        if self.globe:
            return _globe.geometry(self.lat, self.lon, self.zoom, w, h)[0]
        minlon, minlat, maxlon, maxlat = self.bbox
        lon_step = (maxlon - minlon) / w
        lat_step = (maxlat - minlat) / h
        lons = [minlon + lon_step * (x + 0.5) for x in range(w)]
        return [[(maxlat - lat_step * (y + 0.5), lon) for lon in lons]
                for y in range(h)]

    def locator(self):
        """A function (lat, lon) -> (sub-pixel col, row) in this frame,
        or None when the point is off it."""
        w, h = self.gw, self.hc * 2
        if self.globe:
            r = _globe._radius(self.zoom, h)
            lat0, lon0 = self.lat, self.lon
            forward = _globe.forward

            def locate(lat, lon):
                ux, uy, cos_c = forward(lat, lon, lat0, lon0)
                if cos_c <= 0.0:
                    return None
                x = floor(w / 2.0 + ux * r)
                y = floor(h / 2.0 - uy * r)
                if 0 <= x < w and 0 <= y < h:
                    return x, y
                return None
            return locate

        minlon, minlat, maxlon, maxlat = self.bbox
        lon_span, lat_span = maxlon - minlon, maxlat - minlat

        def locate(lat, lon):
            y = floor((maxlat - lat) / lat_span * h)
            if not 0 <= y < h:
                return None
            x = floor(((lon - minlon) % 360.0) / lon_span * w)
            if x < w:
                return x, y
            return None
        return locate


def _lon_delta(a, b):
    """The signed shortest turn from longitude a to b, in (-180, 180]."""
    return (b - a + 180.0) % 360.0 - 180.0


# ---------------------------------------------------------------------------
# Sampling one frame into another
# ---------------------------------------------------------------------------
class SampleMap:
    """For each cell of a target frame, the source cell with the same
    ground.

    Two forms: separable (a column map and a row map, when the source
    is the target shifted and scaled — a pan, a zoom, either
    projection about its own centre) and per-cell (a grid of source
    positions, when the projection turns).  `same_scale` says whether
    a glyph — one character in one cell — can be carried across
    without stretching a word.
    """
    __slots__ = ("gw", "hc", "cols", "rows_sub", "rows_cell", "sub", "cell",
                 "same_scale")

    def __init__(self, gw, hc, same_scale, cols=None, rows_sub=None,
                 sub=None):
        self.gw, self.hc = gw, hc
        self.same_scale = same_scale
        self.cols, self.rows_sub, self.sub = cols, rows_sub, sub
        if rows_sub is not None:
            self.rows_cell = [(-1 if r < 0 else r // 2)
                              for r in rows_sub[0::2]]
            self.cell = None
        else:
            self.rows_cell = None
            self.cell = [[None if p is None else (p[0], p[1] // 2)
                          for p in row] for row in sub[0::2]]

    def grid(self, src, fill, sub=False):
        """`src` (a sub-pixel grid if `sub`, else a cell grid) resampled
        into the target, `fill` wherever the source has nothing."""
        if src is None:
            return None
        w = self.gw
        blank = [fill] * w
        out = []
        if self.cols is not None:
            cols = self.cols
            for r in (self.rows_sub if sub else self.rows_cell):
                if r < 0:
                    out.append(blank[:])
                    continue
                s = src[r]
                out.append([s[c] if c >= 0 else fill for c in cols])
            return out
        for row in (self.sub if sub else self.cell):
            out.append([fill if p is None else src[p[1]][p[0]]
                        for p in row])
        return out

    def cells(self, members):
        """The set of target cells whose source cell is in `members`."""
        if not members:
            return set()
        out = set()
        if self.cols is not None:
            cols = self.cols
            for y, r in enumerate(self.rows_cell):
                if r < 0:
                    continue
                for x, c in enumerate(cols):
                    if c >= 0 and (c, r) in members:
                        out.add((x, y))
            return out
        for y, row in enumerate(self.cell):
            for x, p in enumerate(row):
                if p is not None and p in members:
                    out.add((x, y))
        return out

    def glyphs(self, overlays):
        """`overlays` ({(col, row): glyph}) carried to the target, one
        cell each; empty when the scale differs, where a word would
        come apart."""
        if not overlays or not self.same_scale:
            return {}
        inverse = {}
        if self.cols is not None:
            cols = self.cols
            for y, r in enumerate(self.rows_cell):
                if r < 0:
                    continue
                for x, c in enumerate(cols):
                    if c >= 0:
                        inverse.setdefault((c, r), (x, y))
        else:
            for y, row in enumerate(self.cell):
                for x, p in enumerate(row):
                    if p is not None:
                        inverse.setdefault(p, (x, y))
        out = {}
        for pos, glyph in overlays.items():
            at = inverse.get(pos)
            if at is not None:
                out[at] = glyph
        return out


def sample_map(src, dst):
    """The SampleMap from `src` into `dst`, or None if the sizes differ."""
    if not src.same_size(dst):
        return None
    gw, h = dst.gw, dst.hc * 2
    if not src.globe and not dst.globe:
        # a shift and a scale of the flat window: separable
        minlon, minlat, maxlon, maxlat = dst.bbox
        s_minlon, s_minlat, s_maxlon, s_maxlat = src.bbox
        s_lon_span, s_lat_span = s_maxlon - s_minlon, s_maxlat - s_minlat
        lon_step, lat_step = (maxlon - minlon) / gw, (maxlat - minlat) / h
        cols = []
        for x in range(gw):
            lon = minlon + lon_step * (x + 0.5)
            c = floor(((lon - s_minlon) % 360.0) / s_lon_span * gw)
            cols.append(c if c < gw else -1)
        rows = []
        for y in range(h):
            lat = maxlat - lat_step * (y + 0.5)
            r = floor((s_maxlat - lat) / s_lat_span * h)
            rows.append(r if 0 <= r < h else -1)
        same = abs(src.zoom / dst.zoom - 1.0) < 0.02
        return SampleMap(gw, dst.hc, same, cols=cols, rows_sub=rows)
    if src.globe and dst.globe and src.same_centre(dst):
        # the disc scales about its centre: separable too
        f = dst.zoom / src.zoom
        cols = []
        for x in range(gw):
            c = floor(gw / 2.0 + (x + 0.5 - gw / 2.0) * f)
            cols.append(c if 0 <= c < gw else -1)
        rows = []
        for y in range(h):
            r = floor(h / 2.0 + (y + 0.5 - h / 2.0) * f)
            rows.append(r if 0 <= r < h else -1)
        return SampleMap(gw, dst.hc, abs(f - 1.0) < 0.02, cols=cols,
                         rows_sub=rows)
    # a turn of the globe, or a change of projection: cells collapse
    # and spread, so no glyph survives it whole
    locate = src.locator()
    sub = [[None if ll is None else locate(ll[0], ll[1]) for ll in row]
           for row in dst.sub_lls()]
    return SampleMap(gw, dst.hc, False, sub=sub)


# ---------------------------------------------------------------------------
# Keyframes
# ---------------------------------------------------------------------------
class Keyframe:
    """What one real frame was composed from.

    `register` is the view mode ("terrain" or "street"); `composer` is
    which composer drew it ("terrain" for the hillshade and the globe,
    "map" for the flat street map).  `fill` is the sub-pixel colour
    grid as drawn, shading included.  `layers` are (dots, color,
    ribbon) braille layers in draw order — for the street map the
    ranked layer first, then the route; for terrain the rivers and the
    route; for the globe the borders.  `basemap` is the flat terrain
    map's (dots, color) border grids, `coast` its shoreline masks,
    `glyphs` the labels, `dusk` the per-cell ink dimming.
    """
    __slots__ = ("geom", "register", "composer", "fill", "layers", "coast",
                 "basemap", "glyphs", "dusk", "coast_ink", "generation",
                 "stamp")

    def __init__(self, geom, register, composer, fill, layers=(), coast=None,
                 basemap=None, glyphs=None, dusk=None, coast_ink=None,
                 generation=None):
        self.geom = geom
        self.register, self.composer = register, composer
        self.fill = fill
        self.layers = list(layers)
        self.coast = coast
        self.basemap = basemap
        self.glyphs = glyphs or {}
        self.dusk = dusk
        self.coast_ink = coast_ink
        self.generation = generation
        self.stamp = time.monotonic()


def placeholder(kf, dst):
    """`kf` re-projected into the `dst` geometry, or None if it cannot
    be (a different terminal size)."""
    m = sample_map(kf.geom, dst)
    if m is None:
        return None
    layers = [(m.grid(dots, 0), m.grid(color, None), m.cells(ribbon))
              for dots, color, ribbon in kf.layers]
    basemap = None
    if kf.basemap is not None:
        basemap = (m.grid(kf.basemap[0], 0), m.grid(kf.basemap[1], None))
    out = Keyframe(dst, kf.register, kf.composer, m.grid(kf.fill, None, sub=True),
                   layers, coast=m.grid(kf.coast, 0), basemap=basemap,
                   glyphs=m.glyphs(kf.glyphs), dusk=m.grid(kf.dusk, None),
                   coast_ink=kf.coast_ink, generation=kf.generation)
    return out


_keyframes = []
_lock = threading.Lock()


def remember(kf):
    """Keep a real frame for the placeholders to come."""
    with _lock:
        _keyframes.append(kf)
        del _keyframes[:-KEEP]


def forget():
    with _lock:
        del _keyframes[:]


def best(dst, register, generation):
    """The remembered frame that covers `dst` best, or None.

    Only frames of the same register, size and theme generation are
    candidates; among them the greatest overlap wins, the newer one on
    a tie.
    """
    with _lock:
        candidates = list(_keyframes)
    pick, score = None, 0.0
    for kf in reversed(candidates):
        if (kf.register != register or kf.generation != generation
                or not kf.geom.same_size(dst)):
            continue
        cover = kf.geom.overlap(dst)
        if cover > score:
            pick, score = kf, cover
    return pick


# ---------------------------------------------------------------------------
# The flight path
# ---------------------------------------------------------------------------
RHO = 1.42          # van Wijk's trade-off between zooming and panning
SPEED = 3.0         # path units per second
FLIGHT_MIN = 0.45   # seconds, so a short hop still reads as motion
FLIGHT_MAX = 2.8    # seconds, so a long one does not outstay itself


class Flight:
    """A smooth flight from one view to another.

    Van Wijk and Nuij, "Smooth and efficient zooming and panning"
    (2003): the camera rises just high enough to see both ends, crosses,
    and descends, along the path on which the picture appears to move
    at a constant speed.  `w` is the visible height in degrees (the
    zoom), `u` the distance along the ground in the same units.
    """
    __slots__ = ("lat0", "lon0", "w0", "lat1", "lon1", "w1", "u1", "r0",
                 "S", "k", "duration")

    def __init__(self, lat0, lon0, w0, lat1, lon1, w1, speed=SPEED):
        self.lat0, self.lon0, self.w0 = lat0, lon0, w0
        self.lat1, self.lon1, self.w1 = lat1, lon1, w1
        dlat = lat1 - lat0
        dlon = _lon_delta(lon0, lon1) * math.cos(math.radians((lat0 + lat1) / 2))
        self.u1 = math.hypot(dlat, dlon)
        rho = RHO
        if self.u1 < 1e-6:
            # a pure zoom: exponential in the height
            self.k = 1.0 if w1 > w0 else -1.0
            self.r0 = None
            self.S = abs(math.log(w1 / w0)) / rho
        else:
            u1 = self.u1
            b0 = (w1 * w1 - w0 * w0 + rho ** 4 * u1 * u1) / (2 * w0 * rho * rho * u1)
            b1 = (w1 * w1 - w0 * w0 - rho ** 4 * u1 * u1) / (2 * w1 * rho * rho * u1)
            r0 = math.log(-b0 + math.sqrt(b0 * b0 + 1.0))
            r1 = math.log(-b1 + math.sqrt(b1 * b1 + 1.0))
            self.r0 = r0
            self.k = None
            self.S = (r1 - r0) / rho
        self.duration = max(FLIGHT_MIN, min(FLIGHT_MAX, self.S / speed))

    def at(self, t):
        """(lat, lon, zoom) `t` seconds in; the end past the duration."""
        if t >= self.duration:
            return self.lat1, self.lon1, self.w1
        s = max(0.0, t / self.duration) * self.S
        rho = RHO
        if self.r0 is None:
            frac = 0.0
            w = self.w0 * math.exp(self.k * rho * s)
        else:
            r0 = self.r0
            u = (self.w0 / (rho * rho) * math.cosh(r0) * math.tanh(rho * s + r0)
                 - self.w0 / (rho * rho) * math.sinh(r0))
            w = self.w0 * math.cosh(r0) / math.cosh(rho * s + r0)
            frac = max(0.0, min(1.0, u / self.u1))
        lat = self.lat0 + (self.lat1 - self.lat0) * frac
        lon = self.lon0 + _lon_delta(self.lon0, self.lon1) * frac
        lon = (lon + 180.0) % 360.0 - 180.0
        return lat, lon, w
