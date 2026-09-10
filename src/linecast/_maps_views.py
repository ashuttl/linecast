"""What a map view is made of, and how it is fetched and kept.

A view is one camera at one terminal size. These synchronous, bounded memos
run inside MapApp's single scene worker, or on the caller for static output.
Independent source fetches overlap within a build; no loader schedules a
second scene. Clouds retain their separate background weather refresh.
"""

import threading
from collections import namedtuple
from concurrent.futures import ThreadPoolExecutor

from linecast import (
    _builtup, _climate, _globe, _globe_now, _maps_streets, _maps_style, _theme,
)
from linecast._elevation import elevation_grid
from linecast._live import nudge as _nudge_repaint
from linecast._maps_i18n import ms
from linecast._maps_paint import (
    BORDER_STROKE, RIVER_STROKE, build_terrain_buffer,
)
from linecast._radar_basemap import _edge_dots
from linecast._runtime import log_failure
from linecast._scenes import Memo

_terrain_cache = Memo(keep=4)  # exact camera and source flags -> colour buffer


def _view_key(camera):
    """Every projected layer shares the exact camera and current theme."""
    return camera.key, _theme.generation


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


def _tile_water(camera):
    """(inland water, rivers, land cover, ocean) for the camera, or Nones.

    Terrain mode's one network dependency beyond the elevation tiles,
    and an optional one: every failure degrades to the sea-level-only
    map this used to be, never to an error.
    """
    try:
        band, tiles = _maps_streets.fetch_view(camera.bounds, camera.hc, camera=camera)
        if not any(tiles.values()):
            return None, None, None, None
        return _maps_streets.build_water_view(camera.bounds, camera.gw, camera.hc, tiles,
                                              band, RIVER_STROKE, camera=camera)
    except Exception as exc:
        log_failure("maps/vtiles", "inland water", exc, fallback="sea-level-only terrain")
        return None, None, None, None


def _builtup_layer(camera):
    """The built-up fraction grid for the view, or None when the layer
    is off or could not be read — the same never-an-error contract as
    the tile water."""
    if not _builtup.enabled():
        return None
    try:
        return _builtup.builtup_grid(camera.bounds, camera.gw, camera.hc * 2, camera=camera)
    except Exception as exc:
        log_failure("maps/builtup", "layer", exc, fallback="layer off")
        return None


class TerrainView(namedtuple("TerrainView", "elev coast water rivers cover complete",
                             defaults=(True,))):
    """One view's ground truth: the averaged elevation grid, the braille
    shoreline, the sub-pixel inland water mask, the river layer and the
    sub-pixel land-cover grid.

    The water, river, and cover fields are None when vector tiles could not be read;
    every consumer treats that as "no inland water or cover known", which
    is exactly what terrain mode drew before them. ``complete`` describes
    required elevation coverage; partial ground stays usable while it retries.
    """
    __slots__ = ()


class StreetView(namedtuple("StreetView", "fills layer labels complete", defaults=(True,))):
    """Usable street layers and whether every requested tile arrived."""
    __slots__ = ()


_elev_cache = Memo(keep=4)    # -> TerrainView
_street_cache = Memo(keep=4)  # -> StreetView
_globe_cache = Memo(keep=4)   # -> GlobeView


def _keep_complete(cache, key, load):
    view = cache.get(key)
    if view is None:
        view = load()
        if view.complete:
            cache.put(key, view)
    return view


def _get_elevation(camera):
    """Load or reuse this camera's terrain; required source errors propagate."""
    gw, hc = camera.gw, camera.hc

    def load():
        # fetch at 2x and box-average down: point-sampled elevation makes
        # the hillshade step visibly at cell edges; averaging anti-aliases
        # tone transitions and blends shorelines. The fine grid also yields
        # the braille coastline before it is averaged away.
        # The three sources are independent, so their fetches overlap:
        # the wait is the slowest of them, not the sum.  Only the
        # elevation may fail the view; the other two degrade to None.
        with ThreadPoolExecutor(max_workers=2) as pool:
            water_job = pool.submit(_tile_water, camera)
            builtup_job = pool.submit(_builtup_layer, camera)
            fine = elevation_grid(camera.bounds, gw * 2, hc * 4, camera=camera)
        if not any(value is not None for row in fine for value in row):
            raise RuntimeError(ms('offline', 'en'))
        complete = all(value is not None for row in fine for value in row)
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
            rivers, cover, complete)

    return _keep_complete(_elev_cache, _view_key(camera), load)


def _get_street(camera, lang="en", reserved=()):
    """Load or reuse the camera's fills, ranked layer and label overlays."""
    bbox, gw, hc = camera.bounds, camera.gw, camera.hc

    def load():
        # the settlement raster fetches alongside the vector tiles, as
        # the terrain path overlaps its sources; below its debut band
        # the layer is never asked for, so a deep view pays nothing
        band, _z_src, keys = _maps_streets.view_tiles(bbox, hc, camera=camera)
        with ThreadPoolExecutor(max_workers=1) as pool:
            bu_job = (pool.submit(_builtup_layer, camera)
                      if band >= _maps_style.FILL_DEBUT["builtup"]
                      else None)
            tiles = _maps_streets.fetch_tiles(keys)
        if not any(tiles.values()):
            raise RuntimeError(ms('offline', 'en'))
        layers = _maps_streets.build_street_view(
            bbox, gw, hc, tiles, band, lang, reserved,
            bu_job.result() if bu_job is not None else None, camera=camera)
        return StreetView(*layers, complete=all(tiles.get(key) is not None for key in keys))

    key = _view_key(camera) + (lang, tuple(sorted(reserved)))
    return _keep_complete(_street_cache, key, load)


def _terrain_buffer(elev, camera, water=None, cover=None, *, complete=True):
    # the tile flags are part of the key: the same view rendered once
    # offline and once with tiles is two different pictures
    key = _view_key(camera) + (water is not None, cover is not None)

    def build():
        # Climate chooses the terrain's colour family, so it must follow
        # the same inverse projection as elevation and land cover. An empty
        # tuple explicitly disables the legacy bbox fallback if unavailable.
        climate = _climate.grid_for_lls(camera.lls(camera.gw, camera.hc * 2)) or ()
        return build_terrain_buffer(elev, camera.scale_bbox, camera.gw, camera.hc * 2,
                                     water, cover, climate=climate)

    # A recovered source at this same camera must paint its new pixels,
    # rather than inheriting the previous attempt's incomplete colour buffer.
    return _terrain_cache.get(key, build) if complete else build()


def _get_globe(camera):
    """Load or reuse the coarse world source under this camera."""
    lat0, lon0, zoom, gw, hc = camera.lat, camera.lon, camera.zoom, camera.gw, camera.hc

    def load():
        # the fine grid feeds the coastline and box-averages into the
        # fill, exactly as the flat view does; the sub-pixel geometry
        # adds what only a sphere has — a viewing angle and a limb
        flls, _zs, _rhos = _globe.geometry(lat0, lon0, zoom, gw * 2, hc * 4)
        fine = _globe.elevation(flls, zoom, hc * 4)
        lls, zs, rhos = _globe.geometry(lat0, lon0, zoom, gw, hc * 2)
        grid = _box_average(fine, gw, hc)
        atmo = _globe.atmosphere(rhos, zoom, hc * 2)
        # the lakes come from the vendored polygons rather than the
        # tiles, but they join the fill and the shoreline by exactly
        # the flat view's rule: one mask, one union, one boundary
        wet = _globe.lake_mask(lat0, lon0, zoom, gw * 2, hc * 4)
        return _globe.GlobeView(
            grid, _coast_dots(fine, gw, hc, wet), zs, atmo,
            _globe.ice_cover(lls, grid,
                             _maps_style.COVER_ORDER.index("ice") + 1),
            _globe.border_layer(lat0, lon0, zoom, gw, hc, BORDER_STROKE),
            lls, _globe.limb_lls(lat0, lon0, zoom, gw, hc * 2, atmo),
            _water_subpixels(wet, gw, hc) if wet is not None else None)

    return _globe_cache.get(_view_key(camera), load)


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
        except Exception as exc:
            log_failure("maps/clouds", "refresh", exc, fallback="no cloud layer")
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
        except Exception as exc:
            log_failure("maps/clouds", "background refresh", exc,
                        fallback="previous canvas kept")
            changed = False
        with _clouds_lock:
            _clouds_pending[0] = False
        if changed:
            _nudge_repaint()

    threading.Thread(target=worker, daemon=True).start()
    return canvas


_theme.track_imports(globals(), "linecast._maps_paint")
