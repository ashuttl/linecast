"""What a map view is made of, and how it is fetched and kept.

A view is one bbox at one terminal size.  Each register has a loader
— _get_elevation, _get_street, _get_globe, and _get_clouds for the
sky — that answers from a small cache and, live, fetches in the
background and nudges a repaint when the data lands.  A zoom run holds
every fetch until the last tap settles, so only the view you stop on
reaches the network.
"""

import math
import threading
from collections import namedtuple
from concurrent.futures import ThreadPoolExecutor

from linecast import (
    _builtup, _globe, _globe_now, _maps_streets, _maps_style, _theme,
)
from linecast._elevation import elevation_grid
from linecast._live import nudge as _nudge_repaint
from linecast._maps_i18n import ms
from linecast._maps_paint import (
    BORDER_STROKE, RIVER_STROKE, build_terrain_buffer,
)
from linecast._radar_basemap import _edge_dots
from linecast._runtime import debug_log

ZOOM_SETTLE = 0.3        # seconds of zoom quiet before a fetch may start

_terrain_cache = {}  # (bbox, w, h) -> sub-pixel colour buffer
_fetch_hold = [0.0]  # monotonic deadline; live zoom taps push it forward


def _fetch_held():
    """True while a live zoom gesture is still in flight."""
    import time
    return time.monotonic() < _fetch_hold[0]


def _hold_fetches():
    """Zoom taps repaint instantly, but only the view you stop on fetches.

    Each intermediate zoom is its own cache key, so without a hold a
    run of `-` presses from the default view out to the planet spawns a
    full tile fetch per step — and they all fight the one view actually
    asked for.  Each tap pushes the deadline instead; a timer nudges a
    repaint once the last deadline passes, and that repaint is the one
    that reaches the network.
    """
    import time
    deadline = time.monotonic() + ZOOM_SETTLE
    _fetch_hold[0] = deadline

    def settle():
        time.sleep(ZOOM_SETTLE + 0.02)
        if _fetch_hold[0] == deadline:
            _nudge_repaint()

    threading.Thread(target=settle, daemon=True).start()


class _ViewCache:
    """A few built views, loaded in the background when live.

    `get` answers from the cache.  Blocking, a miss runs `load` on the
    calling thread and raises what it raises.  Live, a miss starts one
    daemon worker per key — none while a zoom gesture is still in
    flight — and answers `empty` until the worker's view lands and
    nudges a repaint; a worker that fails leaves nothing behind, so the
    next repaint asks again.  The cache holds a handful of views and is
    cleared, not pruned, when it grows past that: a pan is a few
    neighbours, and a view older than the last four is not coming back.
    """

    def __init__(self, empty=None, keep=3):
        self.empty = empty
        self.keep = keep
        self._views = {}
        self._pending = set()
        self._lock = threading.Lock()

    def clear(self):
        with self._lock:
            self._views.clear()

    def _put(self, key, view):
        if len(self._views) > self.keep:
            self._views.clear()
        self._views[key] = view

    def get(self, key, block, load):
        with self._lock:
            hit = self._views.get(key)
            if hit is not None:
                return hit
            if not block:
                if key in self._pending or _fetch_held():
                    return self.empty
                self._pending.add(key)

        if block:
            hit = load()
            with self._lock:
                self._put(key, hit)
            return hit

        def worker():
            try:
                hit = load()
            except Exception:
                hit = None
            with self._lock:
                self._pending.discard(key)
                if hit is not None:
                    self._put(key, hit)
            if hit is not None:
                _nudge_repaint()

        threading.Thread(target=worker, daemon=True).start()
        return self.empty


def _view_key(bbox, gw, hc):
    """Cache key for a view, at a precision that scales with the zoom.

    A flat 4 dp is ~11 m: ample at a degree or more, but street mode
    reaches 0.0012 deg, where a one-cell pan moves the bbox by less than
    the rounding quantum — every pan would serve the previous grid, and
    min/max latitude can even round to the same number.  Rounding three
    places finer than the span keeps the quantum an order of magnitude
    below a single cell at any zoom, and is exactly today's 4 dp from
    1 deg up (so existing caches and their tests do not move).
    """
    span = bbox[3] - bbox[1]
    nd = 4 if span <= 0 else max(4, 3 + math.ceil(-math.log10(span)))
    # the theme generation rides along: a terminal theme change must
    # miss every buffer that baked the old colours in
    return (tuple(round(v, nd) for v in bbox), gw, hc, _theme.generation)


def _coast_dots(fine, gw, hc, water=None):
    """Braille masks stroking the shoreline of the elevation data.

    The coastline is *derived from the fill*: land is a sample above sea
    level, water is a sample at or below it, and a missing sample (None)
    is neither, so a hole in the elevation data never fakes a shoreline
    from either side.

    `water` is the tiles' inland mask at the same dot resolution, and it
    joins the same two masks rather than getting a stroke pass of its
    own — one union, one boundary, so a lake shore is drawn by exactly
    the rule that draws a sea shore and the two can never disagree where
    a river meets the sea.
    """
    is_land, is_water = [], []
    for dy, row in enumerate(fine):
        wet = water[dy] if water is not None else None
        is_land.append([v is not None and v > 0 and not (wet and wet[dx])
                        for dx, v in enumerate(row)])
        is_water.append([(v is not None and v <= 0) or bool(wet and wet[dx])
                         for dx, v in enumerate(row)])
    return _edge_dots(is_land, is_water, gw, hc)


def _box_average(fine, gw, hc):
    """The 2x fine elevation grid averaged down to the fill's sub-pixels.

    A shoreline sub-pixel averages land and sea dots, and the plain
    mean lands above zero — every coast would bulge a sub-pixel of low
    green into the water.  So the same >=2-of-4 rule as
    _water_subpixels: enough wet dots make a wet sub-pixel, averaged
    over the wet dots only, and the fill agrees with the coastline
    drawn at dot resolution.  A sub-pixel with no samples is None.
    """
    grid = []
    for y in range(hc * 2):
        r0, r1 = fine[y * 2], fine[y * 2 + 1]
        row = []
        for x in range(gw):
            vals = [v for v in (r0[x * 2], r0[x * 2 + 1],
                                r1[x * 2], r1[x * 2 + 1])
                    if v is not None]
            if not vals:
                row.append(None)
                continue
            wet = [v for v in vals if v <= 0]
            if len(wet) >= 2:
                row.append(sum(wet) / len(wet))
            else:
                row.append(sum(vals) / len(vals))
        grid.append(row)
    return grid


def _water_subpixels(water, gw, hc):
    """The dot-resolution inland mask reduced to the fill's sub-pixels.

    A sub-pixel spans 2x2 dots and counts as water on the same >=2-of-4
    rule street mode's fills use, so a pond too small to hold a
    half-block does not tint one.
    """
    out = []
    for spy in range(hc * 2):
        top, bot = water[spy * 2], water[spy * 2 + 1]
        out.append([top[x * 2] + top[x * 2 + 1]
                    + bot[x * 2] + bot[x * 2 + 1] >= 2 for x in range(gw)])
    return out


def _tile_water(bbox, gw, hc):
    """(inland water dot mask, river layer) for the view, or (None, None).

    Terrain mode's one network dependency beyond the elevation tiles,
    and an optional one: every failure degrades to the sea-level-only
    map this used to be, never to an error.
    """
    try:
        band, tiles = _maps_streets.fetch_view(bbox, hc)
        if not any(tiles.values()):
            return None, None, None, None
        return _maps_streets.build_water_view(bbox, gw, hc, tiles, band,
                                              RIVER_STROKE)
    except Exception as exc:
        debug_log(f"terrain inland water unavailable: {exc}")
        return None, None, None, None


def _builtup_layer(bbox, gw, hc):
    """The built-up fraction grid for the view, or None when the layer
    is off or could not be read — the same never-an-error contract as
    the tile water."""
    if not _builtup.enabled():
        return None
    try:
        return _builtup.builtup_grid(bbox, gw, hc * 2)
    except Exception as exc:
        debug_log(f"builtup layer unavailable: {exc}")
        return None


class TerrainView(namedtuple("TerrainView", "elev coast water rivers cover")):
    """One view's ground truth: the averaged elevation grid, the braille
    shoreline, the sub-pixel inland water mask, the river layer and the
    sub-pixel land-cover grid.

    The last three are None whenever the vector tiles could not be read;
    every consumer treats that as "no inland water or cover known", which
    is exactly what terrain mode drew before them."""
    __slots__ = ()


_EMPTY_TERRAIN = TerrainView(None, None, None, None, None)
_elev_cache = _ViewCache(_EMPTY_TERRAIN)   # view key -> TerrainView
_street_cache = _ViewCache((None, None, None))  # -> (fills, layer, labels)
_globe_cache = _ViewCache()   # (lat, lon, zoom, w, h) -> GlobeView


def _get_elevation(bbox, gw, hc, block):
    """A TerrainView for the view; live mode fetches in the background."""

    def load():
        # fetch at 2x and box-average down: point-sampled elevation makes
        # the hillshade step visibly at cell edges; averaging anti-aliases
        # tone transitions and blends shorelines. The fine grid also yields
        # the braille coastline before it is averaged away.
        # The three sources are independent, so their fetches overlap:
        # the wait is the slowest of them, not the sum.  Only the
        # elevation may fail the view; the other two degrade to None.
        with ThreadPoolExecutor(max_workers=2) as pool:
            water_job = pool.submit(_tile_water, bbox, gw, hc)
            builtup_job = pool.submit(_builtup_layer, bbox, gw, hc)
            fine = elevation_grid(bbox, gw * 2, hc * 4)
        water, rivers, cover, ocean = water_job.result()
        bu = builtup_job.result()
        if bu is not None:
            # measured settlement fills wherever the vector story left
            # bare ground; the street-density proxy still runs, so the
            # two agree where both know and cover for each other's gaps
            if cover is None:
                cover = [bytearray(gw) for _ in range(hc * 2)]
            grades = [(lo, _maps_style.COVER_ORDER.index(k) + 1)
                      for lo, k in _maps_style.COVER_BUILTUP_GRADES]
            settlement = {gid for _, gid in grades}
            floor = grades[-1][0]
            for crow, brow in zip(cover, bu):
                for x, f in enumerate(brow):
                    if f >= floor and (not crow[x]
                                       or crow[x] in settlement):
                        crow[x] = next(gid for lo, gid in grades
                                       if f >= lo)
        if ocean is not None:
            # The OSM coastline outranks the elevation data over the
            # sea, without appeal: coastal DEMs report tidal water as a
            # mudflat's metre, a pier's five, a bridge deck's forty —
            # thresholding on "clearly dry land" leaves every harbor
            # green-flecked.  Where the tiles say sea, the sample is
            # sea; real bathymetry (already merged in) stays, anything
            # else drops just under the waterline — and the fill, the
            # derived coastline and the readout all follow.
            for frow, orow in zip(fine, ocean):
                for dx, o in enumerate(orow):
                    if o:
                        e = frow[dx]
                        frow[dx] = -0.5 if e is None else min(e, -0.5)
        return TerrainView(
            _box_average(fine, gw, hc), _coast_dots(fine, gw, hc, water),
            _water_subpixels(water, gw, hc) if water is not None else None,
            rivers, cover)

    return _elev_cache.get(_view_key(bbox, gw, hc), block, load)


def _get_street(bbox, gw, hc, block, lang="en", reserved=()):
    """(fills, ranked layer, label overlays) for the view; live mode
    fetches in the background, exactly as the elevation path does."""

    def load():
        band, tiles = _maps_streets.fetch_view(bbox, hc)
        if not any(tiles.values()):
            raise RuntimeError(ms('offline', 'en'))
        return _maps_streets.build_street_view(bbox, gw, hc, tiles, band,
                                               lang, reserved)

    key = _view_key(bbox, gw, hc) + (lang, tuple(sorted(reserved)))
    return _street_cache.get(key, block, load)




def _terrain_buffer(elev, bbox, gw, hc, water=None, cover=None):
    # the tile flags are part of the key: the same view rendered once
    # offline and once with tiles is two different pictures
    key = _view_key(bbox, gw, hc) + (water is not None, cover is not None)
    buf = _terrain_cache.get(key)
    if buf is None:
        buf = build_terrain_buffer(elev, bbox, gw, hc * 2, water, cover)
        if len(_terrain_cache) > 3:
            _terrain_cache.clear()
        _terrain_cache[key] = buf
    return buf


def _get_globe(lat0, lon0, zoom, gw, hc, block):
    """A GlobeView for the view; live mode fetches in the background."""

    def load():
        # the fine grid feeds the coastline and box-averages into the
        # fill, exactly as the flat view does; the sub-pixel geometry
        # adds what only a sphere has — a viewing angle and a limb
        flls, _zs, _rhos = _globe.geometry(lat0, lon0, zoom, gw * 2, hc * 4)
        fine = _globe.elevation(flls, zoom, hc * 4)
        lls, zs, rhos = _globe.geometry(lat0, lon0, zoom, gw, hc * 2)
        grid = _box_average(fine, gw, hc)
        atmo = _globe.atmosphere(rhos, zoom, hc * 2)
        return _globe.GlobeView(
            grid, _coast_dots(fine, gw, hc), zs, atmo,
            _globe.ice_cover(lls, grid,
                             _maps_style.COVER_ORDER.index("ice") + 1),
            _globe.border_layer(lat0, lon0, zoom, gw, hc, BORDER_STROKE),
            lls, _globe.limb_lls(lat0, lon0, zoom, gw, hc * 2, atmo))

    key = (round(lat0, 2), round(lon0, 2), round(zoom, 1), gw, hc)
    return _globe_cache.get(key, block, load)


_clouds_pending = [False]
_clouds_lock = threading.Lock()


def _get_clouds(zoom, hc, block):
    """The stitched cloud canvas for the now register, or None.

    Blocking mode fetches only when no canvas exists at all — a
    drag-synchronous repaint must never wait on the network, and a
    stale canvas is still this hour's weather.  Freshening always
    happens in the background, nudging a repaint when it lands.
    """
    canvas = _globe_now.peek()
    if block and canvas is None:
        try:
            _globe_now.refresh(zoom, hc * 4)
        except Exception:
            pass
        return _globe_now.peek()
    if canvas is not None and not _globe_now.stale():
        return canvas
    with _clouds_lock:
        if _clouds_pending[0]:
            return canvas
        _clouds_pending[0] = True

    def worker():
        try:
            changed = _globe_now.refresh(zoom, hc * 4)
        except Exception:
            changed = False
        with _clouds_lock:
            _clouds_pending[0] = False
        if changed:
            _nudge_repaint()

    threading.Thread(target=worker, daemon=True).start()
    return canvas


_theme.track_imports(globals(), "linecast._maps_paint")
