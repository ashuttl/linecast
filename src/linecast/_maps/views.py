"""What a map view is made of, and how it is fetched and kept.

A flat view is built for a bbox a margin wider than the window that
asked for it, and the frame is a crop (overscan): the band and
the source zoom still come from the window, so the crop is the map the
window itself would draw, and only the tile list follows the wider
bbox.

A view is one bbox at one terminal size.  Each register has a loader
— _get_elevation, _get_street_tiles, _get_globe, and _get_clouds for the
sky — that answers from a small cache and, live, fetches in the
background and nudges a repaint when the data lands (the scaffold is
_scenes.SceneCache).  A zoom run holds every fetch until the last tap
settles, and so does a camera in motion — but a flat view in motion
still builds one window at a time behind the frames, so what the view
has moved onto can be painted before it stops.
"""

import math
import threading
from collections import namedtuple
from concurrent.futures import ThreadPoolExecutor

from linecast import _builtup, _climate, _theme
from linecast._maps import globe as _globe
from linecast._maps import globe_now
from linecast._maps import globe_texture
from linecast._maps import streets
from linecast._maps import style as _maps_style
from linecast._elevation import elevation_grid
from linecast import _live
from linecast._live import nudge as _nudge_repaint
from linecast._color import BG_PRIMARY
from linecast._maps.i18n import ms
from linecast._maps.paint import (
    BORDER_STROKE, RIVER_STROKE, build_terrain_buffer,
)
from linecast.radar.basemap import _edge_dots
from linecast._runtime import log_failure
from linecast._scenes import FetchHold, Memo, SceneCache

ZOOM_SETTLE = 0.3        # seconds of zoom quiet before a fetch may start

# (bbox, w, h) -> sub-pixel colour buffer.  Three rather than four: a
# flat buffer is built at the overscan's size now, half again the
# window's area, and a slot holds the frame's whole picture.
_terrain_cache = Memo(keep=3)
_zoom_hold = FetchHold(ZOOM_SETTLE)  # live zoom taps push its deadline

# Raised while the camera is easing, coasting, flying or turning.  A
# view in motion is a different bbox every frame, and each would be its
# own fetch — thirty a second, every one of them stale before it
# landed, all of them competing for the network with the only view the
# reader will actually stop on.  So the loaders' own path is closed
# while the motion runs; what is on screen meanwhile is the last real
# view, re-projected — and _motion_build keeps one of those frames'
# views building all the same, so the glide is not a picture that
# never changes until it stops.
_in_motion = [False]


def hold_motion(moving, passing=True):
    """Gate every loader while the camera is moving, or let it go.

    `passing` is whether a window the view is merely passing through
    may still be built (_motion_build).  A flight says no: its loaders
    would take the frames' turn through the climb, which is the part
    of the flight where the picture is at its best, and it has a
    destination of its own on the way.
    """
    _in_motion[0] = bool(moving)
    _build_passing[0] = bool(passing)


def _held():
    return _in_motion[0] or _zoom_hold.held()


# One build at a time for a view the camera is passing through: a
# single slot, not one per key.  A frame that asks while the slot is
# full is remembered rather than started, and the newest request wins
# when it frees — the older ones are windows the view has already left.
# Nothing here is timed: the next build is paced by the last one's
# landing, which on a wide terminal is a second and more away.
_motion_lock = threading.Lock()
_motion_out = [False]     # a build for a moving view is in flight
_motion_next = [None]     # the newest (cache, key, load) asked for meanwhile
_build_passing = [True]   # whether this motion builds what it passes over
_dest_out = [0]           # destination fetches in flight (maps.prefetch_view)


def fetch_destination(work):
    """Run `work` — a view a motion is *heading for* — off the loop.

    A loader is pure Python for a second and more at a time, and two
    of them do not take half as long each: they take twice, and the
    frames in between wait on the same interpreter lock.  So a window
    the view is only passing over stands aside while the window it is
    going to is on its way — the one the reader will stop on is worth
    more than any of the ones they will not — and the counting starts
    here, on the caller's thread, so the next frame already sees it.
    """
    with _motion_lock:
        _dest_out[0] += 1

    def counted():
        try:
            work()
        finally:
            with _motion_lock:
                _dest_out[0] -= 1

    threading.Thread(target=counted, daemon=True).start()


def _motion_build(cache, key, load):
    """Ask for `key` while the camera moves, if the slot is free.

    Zoom taps keep their hold: a run of them is a view a fetch behind
    at every step, which is what the hold is for.  Nor does anything
    start while the view this motion is heading for is itself being
    fetched, or while a flight is in the air.
    """
    if not (_in_motion[0] and _build_passing[0]) or _zoom_hold.held():
        return
    if _dest_out[0]:
        return
    if cache.peek(key) is not None or cache.pending(key):
        return
    with _motion_lock:
        if _motion_out[0]:
            _motion_next[0] = (cache, key, load)
            return
        _motion_out[0] = True
    _start_motion_build(cache, key, load)


def _start_motion_build(cache, key, load):
    """Build one moving view off the frame's thread, then take the next."""

    def worker():
        try:
            cache.get(key, True, load)
        except Exception as exc:
            log_failure("worker", f"{cache.name} in motion", exc,
                        fallback="the frame keeps its stand-in")
        finally:
            with _motion_lock:
                # a view asked for by a camera that has since stopped is
                # a window nobody is looking at; the resting frame asks
                # for its own
                nxt = _motion_next[0] if _in_motion[0] else None
                _motion_next[0] = None
                _motion_out[0] = nxt is not None
        # the view landed under its own key, and the frames are cut
        # from the newest one that has: a moving loop would repaint
        # anyway, but one that has come to rest needs waking
        _nudge_repaint()
        if nxt is not None:
            _start_motion_build(*nxt)

    threading.Thread(target=worker, daemon=True).start()


# The newest real view each flat register has *landed*, as
# (bbox, gw, hc, ...), whether or not any frame has drawn it.  The bbox
# is the overscan's, not the window's: a landed view covers a margin
# beyond the frame that asked for it, and the frames after it are crops
# of that (maps._last_street, maps._last_terrain).  A view fetched while
# the camera moves is never rendered by the frame that asked for it —
# that frame had moved on before it arrived — but it is a far truer
# source for the ones that follow than the view the motion started from.
_street_landed = [None]
_terrain_landed = [None]


def take_street():
    """The newest street view to have landed, once, or None."""
    landed, _street_landed[0] = _street_landed[0], None
    return landed


def take_terrain():
    """The newest terrain view to have landed, once, or None."""
    landed, _terrain_landed[0] = _terrain_landed[0], None
    return landed


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


def _coast_dots(fine, gw, hc, water=None, min_dots=None):
    """Braille masks stroking the shoreline of the elevation data.

    The coastline is *derived from the fill*: land is a sample above sea
    level, water is a sample at or below it, and a missing sample (None)
    is neither, so a hole in the elevation data never fakes a shoreline
    from either side.

    `water` is the tiles' inland mask at the same dot resolution, and it
    joins the same two masks rather than getting a stroke pass of its
    own — one union, one boundary, so a lake shore is drawn by exactly
    the rule that draws a sea shore and the two can never disagree where
    a river meets the sea.  What joins is the *stroked* half of it: the
    bodies holding at least `min_dots` dots on screen
    (style.SHORE_MIN_DOTS by default, and `streets.stroked_water`
    for the rule, the window's edge included).  The fill still takes the
    whole mask, so a pond keeps its water and loses only its ring.  The
    sea is never weighed — it arrives from the elevation, not the tiles.

    `min_dots=0` turns the rule off, which is how the globe asks for it:
    its lakes come from vendored polygons and are already sieved as they
    are carved, by the same reasoning one resolution up.
    """
    return shore_edges(shore_bits(fine, water, min_dots), gw, hc)


# The two bits a dot can carry: land, water, both (never), or neither —
# a hole in the elevation data, which is stroked from no side.
SHORE_LAND, SHORE_WATER = 1, 2


def shore_bits(fine, water=None, min_dots=None):
    """The land and water masks packed a byte a dot, row after row.

    What `_coast_dots` cuts the shoreline out of, kept rather than
    thrown away once the stroke is drawn.  A window cropped off the
    built view's centre has to cut its own, because a shore is not
    only a line: it is the boundary of the fill beside it, and the
    whole point of deriving one from the other is that the two cannot
    disagree.  Carry the stroke across and it lands where resampling
    rounds it, which is not always where the resampled fill puts the
    water's edge.  Carry the land and the water instead — areas, which
    nearest sampling moves only at their own edge — and cutting the
    stroke again by the same rule gives a shore that is still on its
    own shore (`_maps_overscan.Resample.bits`).

    `bytes` rather than two grids of booleans: it is a sixth of the
    memory to carry with a view, and the masks come back out of it
    with a translation table, which is a pass of C rather than of
    Python.
    """
    if water is not None and min_dots != 0:
        water = streets.stroked_water(water, min_dots)
    rows = []
    for dy, row in enumerate(fine):
        wet = water[dy] if water is not None else None
        rows.append(bytes(
            (SHORE_LAND if v is not None and v > 0 and not (wet and wet[dx])
             else 0)
            | (SHORE_WATER if (v is not None and v <= 0)
               or (wet and wet[dx]) else 0)
            for dx, v in enumerate(row)))
    return rows


def shore_edges(shore, gw, hc):
    """The braille shoreline of packed land/water bits."""
    return _edge_dots([[v & SHORE_LAND for v in row] for row in shore],
                      [[v & SHORE_WATER for v in row] for row in shore],
                      gw, hc)


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


def _tile_water(bbox, gw, hc, window=None, camera=None):
    """(inland water dot mask, river layer) for the view, or (None, None).

    Terrain mode's one network dependency beyond the elevation tiles,
    and an optional one: every failure degrades to the sea-level-only
    map this used to be, never to an error.

    With a camera the tiles are chosen by its footprint and the
    polygons are rasterised onto its sphere; the bbox still says what
    scale the view is drawn at, which is what picks the band.
    """
    try:
        band, tiles = streets.fetch_view(
            bbox, hc, window, None if camera is None else camera.footprint)
        if not any(tiles.values()):
            return None, None, None, None
        return streets.build_water_view(bbox, gw, hc, tiles, band,
                                              RIVER_STROKE, camera)
    except Exception as exc:
        log_failure("maps/vtiles", "inland water", exc, fallback="sea-level-only terrain")
        return None, None, None, None


def _builtup_layer(bbox, gw, hc, camera=None):
    """The built-up fraction grid for the view, or None when the layer
    is off or could not be read — the same never-an-error contract as
    the tile water."""
    if not _builtup.enabled():
        return None
    try:
        return _builtup.builtup_grid(bbox, gw, hc * 2, camera=camera)
    except Exception as exc:
        log_failure("maps/builtup", "layer", exc, fallback="layer off")
        return None


class TerrainView(namedtuple("TerrainView",
                            "elev coast water rivers cover "
                            "borders fill shade atmo lls glow shore",
                            defaults=(None,) * 7)):
    """One view's ground truth: the averaged elevation grid, the braille
    shoreline, the sub-pixel inland water mask, the river layer and the
    sub-pixel land-cover grid.

    Three of those are None whenever the vector tiles could not be read;
    every consumer treats that as "no inland water or cover known", which
    is exactly what terrain mode drew before them.

    The rest are what the register gained when it took the camera at
    every zoom.  `borders` is the Natural Earth stroke, projected onto
    the same sphere the fill is, at any zoom.  `fill` is the baked
    planet's own shaded sub-pixels, and is set only when the view came
    from the texture rather than from elevation.  `shade`, `atmo`,
    `lls` and `glow` are the sphere's: the viewing cosine the limb
    falls off by, the rim, the geography under each sub-pixel and the
    limb point each rim sample grazes.  `shade` arrives once the
    falloff can move a sub-pixel at all, a few degrees of zoom out;
    the other three only once the limb is on the screen.  `shore` is
    the land and water the coastline was cut from, at dot pitch, for a
    window that has to cut its own (`shore_bits`)."""
    __slots__ = ()


_EMPTY_TERRAIN = TerrainView(None, None, None, None, None)
# The three registers' scenes, all gated by the zoom hold and by motion.
# The flat two keep three views rather than four: each is an overscan
# now, half again the window's area, and a pan that stays inside one of
# them never asks for another — so the neighbours a fourth slot used to
# hold are ground this view already covers.
_elev_cache = SceneCache(_EMPTY_TERRAIN, keep=3, held=_held,
                         name="terrain")  # -> TerrainView
_street_cache = SceneCache((None, None, None), keep=3, held=_held,
                           name="street")  # -> (fills, layer, labels)
_globe_cache = SceneCache(held=_held,
                          name="globe")   # (lat, lon, zoom, w, h) -> GlobeView


def _get_elevation(bbox, gw, hc, block, window=None):
    """A TerrainView for the view; live mode fetches in the background.

    The window is a patch of the sphere at every zoom now.  Where the
    box rasteriser is still the camera's own picture — a twentieth of a
    braille dot apart, which is the whole of street scale and a little
    above it — it is the one that runs, because it is separable, it is
    what the caches already hold, and it is the same map.  Past that
    the camera samples every source: the elevation through its inverse
    projection, the vector polygons through its forward one.
    """
    cam = _globe.Camera.for_bbox(bbox, gw, hc)
    camera = None if _globe.affine_ok(cam.lat, cam.zoom, gw, hc) else cam

    def load():
        # fetch at 2x and box-average down: point-sampled elevation makes
        # the hillshade step visibly at cell edges; averaging anti-aliases
        # tone transitions and blends shorelines. The fine grid also yields
        # the braille coastline before it is averaged away.
        # The three sources are independent, so their fetches overlap:
        # the wait is the slowest of them, not the sum.  Only the
        # elevation may fail the view; the other two degrade to None.
        with ThreadPoolExecutor(max_workers=2) as pool:
            water_job = pool.submit(_tile_water, bbox, gw, hc, window, camera)
            builtup_job = pool.submit(_builtup_layer, bbox, gw, hc, camera)
            fine = elevation_grid(bbox, gw * 2, hc * 4, camera=camera)
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
        shore = shore_bits(fine, water)
        view = TerrainView(
            _box_average(fine, gw, hc), shore_edges(shore, gw, hc),
            _water_subpixels(water, gw, hc) if water is not None else None,
            rivers, cover, shore=shore,
            borders=_globe.border_layer(cam.lat, cam.lon, cam.zoom, gw, hc,
                                        BORDER_STROKE),
            shade=(_globe.geometry(cam.lat, cam.lon, cam.zoom,
                                   gw, hc * 2)[1]
                   if _globe.limb_shading(cam.zoom, gw, hc) else None))
        _terrain_landed[0] = (tuple(bbox), gw, hc, view)
        return view

    key = _view_key(bbox, gw, hc)
    view = _elev_cache.get(key, block, load)
    if not block and view is _elev_cache.empty:
        _motion_build(_elev_cache, key, load)
    return view


def _get_street_tiles(bbox, gw, hc, block, lang="en", reserved=(),
                      window=None):
    """(fills, ranked layer, label overlays) for the view; live mode
    fetches in the background, exactly as the elevation path does.

    The window is a patch of the sphere at every zoom now.  Where the
    box rasteriser is still the camera's own picture — a twentieth of a
    braille dot apart, which is the whole of street scale and a little
    above it — it is the one that runs, because it is what the caches
    already hold and it is the same map.  Past that the camera chooses
    the tiles by its own footprint and every layer of the build is
    rasterised through its forward projection.
    """
    cam = _globe.Camera.for_bbox(bbox, gw, hc)
    camera = None if _globe.affine_ok(cam.lat, cam.zoom, gw, hc) else cam

    def load():
        # the settlement raster fetches alongside the vector tiles, as
        # the terrain path overlaps its sources; below its debut band
        # the layer is never asked for, so a deep view pays nothing
        band, _z_src, keys = streets.view_tiles(
            bbox, hc, window, None if camera is None else camera.footprint)
        with ThreadPoolExecutor(max_workers=1) as pool:
            bu_job = (pool.submit(_builtup_layer, bbox, gw, hc, camera)
                      if band >= _maps_style.FILL_DEBUT["builtup"]
                      else None)
            tiles = streets.fetch_tiles(keys)
        if not any(tiles.values()):
            raise RuntimeError(ms('offline', 'en'))
        if not block:
            # live: give the next pan or zoom a head start
            try:
                streets.prefetch_around(bbox, hc, keys, window)
            except Exception as exc:
                log_failure("maps/vtiles", "prefetch", exc, fallback="none")
        # the window's size in cells, off the hint's bbox: the hint is
        # the frame's own middle, whole cells in from every edge
        cells = None
        if window is not None:
            wbbox, whc = window
            cells = (round((wbbox[2] - wbbox[0]) / ((bbox[2] - bbox[0]) / gw)),
                     whc)
        view = streets.build_street_view(
            bbox, gw, hc, tiles, band, lang, reserved,
            bu_job.result() if bu_job is not None else None, camera, cells)
        # the whole view, labels and all: a window inside this one's
        # margin is an exact crop of it, which is a picture with its
        # names on.  A window outside it is reprojected instead, and
        # that path leaves the labels behind as it always has.
        _street_landed[0] = (tuple(bbox), gw, hc, view[0], view[1], view[2])
        return view

    key = _view_key(bbox, gw, hc) + (lang, tuple(sorted(reserved)))
    view = _street_cache.get(key, block, load)
    if not block and view is _street_cache.empty:
        _motion_build(_street_cache, key, load)
    return view




def _terrain_buffer(view, bbox, gw, hc, wide=False):
    """The view's sub-pixel colour: hillshade, then the limb, memoised.

    One builder for the whole register.  A view filled from the baked
    planet already has its colour and only needs copying; one built
    from elevation goes through the shader, with a scale-only bbox and
    a climate grid sampled from the sphere where the window is wide
    enough that its own bbox is a scale and not a footprint.  Either
    way the limb falloff goes on last and inside the memo, because it
    belongs to the picture and not to the moment.

    It is applied to the *built* view and cropped with everything else.
    That is exact: a crop is the same plane points at another offset,
    and the viewing cosine is a property of the point.
    """
    # the tile flags are part of the key: the same view rendered once
    # offline and once with tiles is two different pictures
    key = _view_key(bbox, gw, hc) + (view.water is not None,
                                     view.cover is not None,
                                     view.fill is not None, wide)

    def build():
        if view.fill is not None:
            buf = [list(row) for row in view.fill]
        elif wide:
            # the planet rebuilt from elevation: a scale-only bbox,
            # because the shader wants metres per sub-pixel and on a
            # disk that is the hand-off zoom's scale everywhere (the
            # limb compresses beyond it, and the falloff owns that).
            # The empty-tuple fallback means "no climate known" — never
            # "derive from bbox", because this bbox is scale-only
            zoom = bbox[3] - bbox[1]
            spy_h = hc * 2
            sbbox = (0.0, -zoom / 2, zoom * gw / spy_h, zoom / 2)
            buf = build_terrain_buffer(
                view.elev, sbbox, gw, spy_h, water=view.water,
                cover=view.cover,
                climate=_climate.grid_for_lls(view.lls) or ())
        else:
            # the climate families are looked up by latitude, and where
            # the elevation came through the camera the bbox's rows are
            # not its latitudes: a boundary read off the bbox would sit
            # rows from the ground it colours at the window's edges
            cam = _globe.Camera.for_bbox(bbox, gw, hc)
            climate = None
            if not _globe.affine_ok(cam.lat, cam.zoom, gw, hc):
                climate = _climate.grid_for_lls(
                    _globe.geometry(cam.lat, cam.lon, cam.zoom,
                                    gw, hc * 2)[0]) or ()
            buf = build_terrain_buffer(view.elev, bbox, gw, hc * 2,
                                       view.water, view.cover,
                                       climate=climate)
        if view.shade is not None:
            _globe.shade_buffer(buf, view.shade, view.atmo, BG_PRIMARY)
        return buf

    return _terrain_cache.get(key, build)


def warm_globe_texture(zoom, hc, street=False):
    """Start the texture a globe zoom is heading for, moving or not.

    The loaders are gated while the camera moves because a view in
    flight is a new window every frame and each would be its own
    fetch.  A texture is not a fetch: it is a file on disk, or a bake
    of a canvas that ships with the program.  Held back with the rest
    it lands only once the ease and the zoom hold have both settled,
    so a zoom that crosses a terrarium level draws the level it left,
    scaled, for the whole ease.  Asked for at the tap — the
    destination zoom is known then — it is usually in memory before
    the ease ends, and the globe crosses the level warm.  Nothing else
    is let through the gate.
    """
    register = "street" if street else "terrain"
    if globe_texture.ready(zoom, hc * 4, register):
        return
    threading.Thread(target=globe_texture.for_view, daemon=True,
                     args=(zoom, hc * 4, register, False)).start()


def recentres(lat, zoom, gw, hc, street=False):
    """Whether a drag can turn the ground under the hand.

    Within the tile sources' reach it always can: the view is built a
    margin wider than the window, so the window at the new centre is a
    crop of what is already in hand.  Beyond them it is the planet, and
    the planet has to be warm.  One rule for both registers now, since
    both are drawn by one camera and both hand their ground over at
    `local_tiles`.
    """
    return (_globe.local_tiles(lat, zoom, gw, hc)
            or globe_warm(zoom, hc, street))


def globe_warm(zoom, hc, street=False):
    """Whether a globe view can be recentred without touching the network.

    A warm globe is what makes live rotation possible, and there are
    two ways to be warm now: the world canvas this zoom samples is
    stitched, or its texture is baked — in which case the canvas is
    never read at all.
    """
    return (_globe.warm(zoom, hc * 4)
            or globe_texture.ready(zoom, hc * 4,
                                    "street" if street else "terrain"))


def _sphere(zoom, gw, hc, lat0, lon0):
    """The geometry every globe view has, whichever way it is painted."""
    lls, zs, rhos = _globe.geometry(lat0, lon0, zoom, gw, hc * 2)
    atmo = _globe.atmosphere(rhos, zoom, hc * 2)
    return lls, zs, atmo, _globe.limb_lls(lat0, lon0, zoom, gw, hc * 2, atmo)


def _textured_globe(tex, lat0, lon0, zoom, gw, hc):
    """A GlobeView read out of the baked texture.

    The coastline is still cut from the fill and the lakes still join
    it — one mask, one union, one boundary, the flat view's rule — but
    the fill is a lookup now rather than a planet rebuilt from
    elevation, and the borders arrive as bits already stroked.
    """
    shot = globe_texture.sample(tex, lat0, lon0, zoom, gw, hc, BORDER_STROKE)
    lls, zs, atmo, glow = _sphere(zoom, gw, hc, lat0, lon0)
    return _globe.GlobeView(
        shot.elev, _edge_dots(shot.land, shot.water, gw, hc), zs, atmo,
        None, shot.borders, lls, glow, None, shot.fill,
        _water_subpixels(shot.water, gw, hc))


def _built_globe(lat0, lon0, zoom, gw, hc):
    """A GlobeView rebuilt from elevation, for a planet not yet baked."""
    # the fine grid feeds the coastline and box-averages into the
    # fill, exactly as the flat view does; the sub-pixel geometry
    # adds what only a sphere has — a viewing angle and a limb
    flls, _zs, _rhos = _globe.geometry(lat0, lon0, zoom, gw * 2, hc * 4)
    fine = _globe.elevation(flls, zoom, hc * 4)
    lls, zs, atmo, glow = _sphere(zoom, gw, hc, lat0, lon0)
    grid = _box_average(fine, gw, hc)
    # the lakes come from the vendored polygons rather than the
    # tiles, but they join the fill and the shoreline by exactly
    # the flat view's rule: one mask, one union, one boundary.  Not
    # its screen-area rule, though: lake_mask has already dropped
    # what is too small to draw (_LAKE_MIN_DOTS) and the baked
    # texture sieves at the same size, so sieving again here would
    # thin the built globe and not the textured one
    wet = _globe.lake_mask(lat0, lon0, zoom, gw * 2, hc * 4)
    return _globe.GlobeView(
        grid, _coast_dots(fine, gw, hc, wet, min_dots=0), zs, atmo,
        _globe.ice_cover(lls, grid,
                         _maps_style.COVER_ORDER.index("ice") + 1),
        _globe.border_layer(lat0, lon0, zoom, gw, hc, BORDER_STROKE),
        lls, glow,
        _water_subpixels(wet, gw, hc) if wet is not None else None)


def _get_globe(lat0, lon0, zoom, gw, hc, block, street=False):
    """A GlobeView for the view; live mode fetches in the background."""
    register = "street" if street else "terrain"

    def load():
        tex = globe_texture.for_view(zoom, hc * 4, register, block)
        if tex is None:
            return _built_globe(lat0, lon0, zoom, gw, hc)
        return _textured_globe(tex, lat0, lon0, zoom, gw, hc)

    # the texture's readiness is part of the key: the view drawn the
    # long way while the planet baked must not outlive the bake, but
    # it stays on screen until its textured successor has landed
    ready = globe_texture.ready(zoom, hc * 4, register)
    key = (round(lat0, 2), round(lon0, 2), round(zoom, 1), gw, hc, register,
           _theme.generation, ready)
    view = _globe_cache.get(key, block, load)
    if view is None and ready:
        view = _globe_cache.peek(key[:-1] + (False,))
    return view


_clouds_pending = [False]
_clouds_lock = threading.Lock()


def _get_clouds(zoom, hc, block):
    """The stitched cloud canvas for the now register, or None.

    Blocking mode fetches only when no canvas exists at all, and never
    on the live loop, where every warm globe frame blocks: a frame must
    not wait on the network, and the whole view would stop dead for a
    layer that is only the weather over it.  A stale canvas is still
    this hour's, and a missing one is a planet without cloud for a few
    frames.  Live, freshening happens in the background and nudges a
    repaint when it lands.
    """
    canvas = globe_now.peek()
    if block and canvas is None and not _live._running:
        try:
            globe_now.refresh(zoom, hc * 4)
        except Exception as exc:
            log_failure("maps/clouds", "refresh", exc, fallback="no cloud layer")
        return globe_now.peek()
    if canvas is not None and not globe_now.stale():
        return canvas
    with _clouds_lock:
        if _clouds_pending[0]:
            return canvas
        _clouds_pending[0] = True

    def worker():
        try:
            changed = globe_now.refresh(zoom, hc * 4)
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


_theme.track_imports(globals(), "linecast._maps.paint")
