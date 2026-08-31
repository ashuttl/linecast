"""Radar frame cache and prefetcher.

Decoded frames are memoised per view (bbox, size, theme) and warmed in
the background by a prefetch worker, displayed frame first. A view change
bumps a generation so a superseded worker stands down; the live loop's
auto-play gate waits on PLAY_READY of the window (or the worker
finishing) before the animation starts. A frame that came back short of
tiles is refused rather than memoised, and a source that cannot serve
even the displayed frame is stepped over. The active RadarSource lives
here too, since every fetch goes through it; radar.main() installs it.
"""

import atexit
import math
import threading
from concurrent.futures import ThreadPoolExecutor

from linecast import _theme
from linecast import _radar_sources
from linecast import _radar_warnings
from linecast._live import nudge as _nudge  # a landed frame repaints the live view
from linecast._radar_render import _bbox_key, build_radar_buffer
from linecast._radar_ui import _get_basemap
from linecast._runtime import debug_log, log_failure

MAX_REWIND_MIN = 180  # how far back scrubbing can go (IEM; tile sources
                      # are limited to what their index publishes, ~2 h)
N_FRAMES = MAX_REWIND_MIN // 5 + 1  # frames in the rewind window
PLAY_READY = 0.8  # fraction of the frame window that must be buffered
                  # before auto-play starts (a completed prefetch also opens
                  # the gate, so a few permanently failing frames can't
                  # stall playback forever)

_source = None  # active RadarSource, chosen per location in main()
_fell_back = False  # the chain has been stepped down once already
frame_load_failed = False  # a static render's frame did not arrive


def source_tag():
    """The active source's name for the debug log."""
    return getattr(_source, "tag", "radar")

# in-memory cache of decoded frames: key -> (radar_buffer, echo_pct)
_frame_cache = {}
_frame_lock = threading.Lock()
_prefetch_lock = threading.Lock()  # guards the three prefetch globals below
_prefetch_key = None  # (bbox, w, h) currently being prefetched
_prefetch_gen = 0     # bumped when the view changes; stale workers stand down
_prefetch_done = False  # current window's prefetch worker has finished
_buffering = False    # auto-play is held while the frame window buffers


def _view_key(bbox, gw, hc, src=None):
    # theme is part of the view: switching palettes must not serve old
    # colours, and neither must a terminal theme change (_theme.generation).
    # So is the source: two of them can be on the same theme and publish a
    # frame for the same minute, and falling from one to the other must not
    # serve the frame the first one drew.
    if src is None:
        src = _source
    return (_bbox_key(bbox), gw, hc, getattr(src, "kind", None),
            getattr(src, "theme", None), _theme.generation)


def _sat_timeline():
    """Satellite-only frame list: the hourly mosaics, played as discrete
    steps so cloud features visibly move between frames."""
    return list(getattr(_source, "satellite_frames", lambda: [])())


def _frame_key(bbox, gw, hc, frame, layer="radar", src=None):
    stamp = frame.time.strftime("%Y%m%dT%H%M")
    if frame.future:
        # nowcast frames are re-predicted under the same timestamp; a token
        # digest keeps a superseded prediction from being served forever
        import hashlib
        stamp += ":" + hashlib.sha1(str(frame.token).encode()).hexdigest()[:8]
    return _view_key(bbox, gw, hc, src) + (layer, stamp)


def _load_frame(bbox, gw, hc, frame, layer="radar"):
    """Return (radar_buffer, echo). Memoised; fetches + decodes on miss.

    A frame that lost tiles raises IncompleteFrame out of the source and
    is never reached by the memo below, so the holes it would have shown
    are neither drawn nor kept: the prefetcher tries it again, and until
    it lands the view holds the nearest frame it does have.
    """
    # one source for the key and the fetch: a theme swap replaces _source
    # between the two, and the new palette must not land under the old key
    src = _source
    key = _frame_key(bbox, gw, hc, frame, layer, src)
    with _frame_lock:
        hit = _frame_cache.get(key)
    if hit is not None:
        return hit
    if layer == "sat":
        pw, ph, rgba = src.satellite_rgba(bbox, gw, hc, frame)
    else:
        pw, ph, rgba = src.frame_rgba(bbox, gw, hc, frame)
    result = build_radar_buffer(rgba, pw, ph, gw, hc,
                                sea=_get_basemap(bbox, gw, hc).sea)
    with _frame_lock:
        _frame_cache[key] = result
        if len(_frame_cache) > N_FRAMES + 8:  # bound to the rewind window
            for old in list(_frame_cache)[:len(_frame_cache) - (N_FRAMES + 8)]:
                _frame_cache.pop(old, None)
    _nudge()  # a frame is ready
    return result


def _cached_frame(bbox, gw, hc, frame, layer="radar"):
    """Cache-only lookup; never touches the network."""
    key = _frame_key(bbox, gw, hc, frame, layer)
    with _frame_lock:
        return _frame_cache.get(key)


def _loaded_mask(bbox, gw, hc, frames, layer="radar"):
    """Which frames of the window are already decoded and cached."""
    keys = [_frame_key(bbox, gw, hc, f, layer) for f in frames]
    with _frame_lock:
        return [k in _frame_cache for k in keys]


def _nearest_cached(bbox, gw, hc, when, layer="radar"):
    """The cached frame for this view closest in time to `when`, or None."""
    prefix = _view_key(bbox, gw, hc) + (layer,)
    want = int(when.strftime("%Y%m%d%H%M"))
    with _frame_lock:
        keys = [k for k in _frame_cache if k[:len(prefix)] == prefix]
        if not keys:
            return None
        best = min(keys, key=lambda k: abs(
            int(k[len(prefix)].split(":")[0].replace("T", "")) - want))
        return _frame_cache.get(best)


def _play_gate(bbox, gw, hc, frames, layer, playing):
    """Auto-play gate: hold the animation on the displayed frame until
    enough of the window has buffered, so the loop plays smoothly instead
    of stuttering past frames that are still fetching. Returns the loaded
    mask and whether playback is held; live_loop consults the gate through
    the _buffering global."""
    global _buffering
    mask = _loaded_mask(bbox, gw, hc, frames, layer)
    n_loaded = sum(mask)
    _buffering = (playing and not _prefetch_done
                  and n_loaded < len(frames)
                  and n_loaded < math.ceil(len(frames) * PLAY_READY))
    return mask, _buffering


def _ensure_prefetch(bbox, gw, hc, frames, start_idx=0, layer="radar"):
    """Warm the frame window in the background, displayed frame first.

    A view change (pan/zoom/resize/theme) bumps the generation so a
    superseded worker stops issuing fetches for a view nobody is looking
    at. The key also covers the frame window itself, so a long-running
    session re-warms whenever the index publishes a new frame (or
    re-predicts a nowcast) — cached frames hit instantly, only the new
    images fetch.
    """
    global _prefetch_key, _prefetch_gen, _prefetch_done
    key = (_view_key(bbox, gw, hc), layer,
           tuple((f.time, str(f.token)) for f in frames))
    with _prefetch_lock:
        if _prefetch_key == key:
            return
        _prefetch_key = key
        _prefetch_done = False
        _prefetch_gen += 1
        gen = _prefetch_gen
    ordered = frames[start_idx:] + frames[:start_idx]  # current frame first
    want_warnings = _radar_warnings.covers(bbox)

    def worker():
        loaded = 0

        def load(f):
            nonlocal loaded
            if gen != _prefetch_gen:
                return False  # view moved on; don't fetch for a stale bbox
            if not _safe_load(bbox, gw, hc, f, layer):
                return False
            loaded += 1
            return True

        # the displayed frame first and alone, so it has every tile
        # connection to itself (and its warnings follow at once); the
        # rest of the window then fills in behind it (tile fetches share
        # one process-wide pool)
        if not load(ordered[0]) and gen == _prefetch_gen and _fall_back():
            # the source changed under us: this window's frames belong to
            # the old one, so leave them and let the repaint start again
            # against the new source's own index
            _nudge()
            return
        if want_warnings and not ordered[0].future:
            _warm_warnings(ordered[0])
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(load, ordered[1:]))
        with _prefetch_lock:
            global _prefetch_key, _prefetch_done
            current = gen == _prefetch_gen
            if current:
                _prefetch_done = True  # opens the auto-play gate
                if loaded == 0:
                    # nothing arrived (offline?) — allow a later render
                    # to retry
                    _prefetch_key = None
        if current:
            _nudge()
        if want_warnings:
            # the rest of the window's warning polygons, one fetch at a
            # time after the frames: each is a ~100 ms request, and inside
            # the pool it held up that thread's next frame
            for f in ordered[1:]:
                if gen != _prefetch_gen:
                    return
                if not f.future:
                    _warm_warnings(f)

    threading.Thread(target=worker, daemon=True).start()


def stand_down():
    """Stop the prefetcher issuing fetches: every frame it has not started
    yet is skipped, as after a view change.  Runs at interpreter exit.

    The worker's pool threads are not daemons, and the interpreter joins
    them on the way out — a join that would otherwise wait for every
    frame still queued behind the sentinel.  Bumping the generation makes
    each queued load return at once, so quitting is prompt.  Registered
    with threading's own exit hooks rather than atexit: those run before
    the executor threads are joined, atexit only after.
    """
    global _prefetch_gen, _prefetch_key
    with _prefetch_lock:
        _prefetch_gen += 1
        _prefetch_key = None


getattr(threading, "_register_atexit", atexit.register)(stand_down)


def _fall_back():
    """Swap _source for the next one down the chain.  True if it moved.

    The displayed frame is the one the source gets every tile connection
    to itself; when even that comes back short, the host is not serving,
    and waiting on the rest of the window only spends more time to learn
    it again.  Once per session, so a source that is merely having a bad
    minute is not abandoned on the strength of a second one.
    """
    global _source, _fell_back
    if _fell_back:
        return False
    nxt = _radar_sources.demote(_source)
    if nxt is None:
        _fell_back = True  # nothing to fall to; stop asking
        return False
    debug_log(f"{source_tag()}: the displayed frame did not arrive; "
              f"falling back to {nxt.label}")
    _source, _fell_back = nxt, True
    return True


def _safe_load(bbox, gw, hc, frame, layer="radar"):
    try:
        _load_frame(bbox, gw, hc, frame, layer)
        return True
    except Exception as exc:
        log_failure(source_tag(), f"prefetch of the {frame.time:%H:%M} frame", exc,
                    fallback="frame skipped")
        return False


def _warm_warnings(frame):
    """Prefetch the warning polygons valid at a frame's time (best-effort)."""
    try:
        if _radar_warnings.cached_at(frame.time) is None:
            _radar_warnings.warnings_at(frame.time)
            _nudge()
    except Exception as exc:
        log_failure("radar/warnings", "prefetch", exc, url=_radar_warnings._URL,
                    fallback="frame shown without warnings")
