"""Radar frame cache and prefetcher.

Decoded frames are memoised per view (bbox, size, theme) and warmed in
the background by a prefetch worker, displayed frame first. A view change
bumps a generation so a superseded worker stands down; the live loop's
auto-play gate waits on PLAY_READY of the window (or the worker
finishing) before the animation starts. A frame that came back short of
tiles is refused rather than memoised, and a source that cannot serve
even the displayed frame is stepped over. The active RadarSource lives
here too, since every fetch goes through it: use() puts one in,
reroute() picks one for a new place in the background, and source()
reads it.
"""

import atexit
import math
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from linecast.terminal import theme as _theme
from linecast.radar import sources as _sources
from linecast.radar import warnings as _warnings
from linecast.terminal.live import nudge as _nudge  # a landed frame repaints the live view
from linecast.radar.render import _bbox_key, build_radar_buffer
from linecast._log import debug_log, log_failure

MAX_REWIND_MIN = 180  # how far back scrubbing can go (IEM; tile sources
                      # are limited to what their index publishes, ~2 h)
N_FRAMES = MAX_REWIND_MIN // 5 + 1  # frames in the rewind window
PLAY_READY = 0.8  # fraction of the frame window that must be buffered
                  # before auto-play starts (a completed prefetch also opens
                  # the gate, so a few permanently failing frames can't
                  # stall playback forever)

_source = None  # the active RadarSource, put in by use()
_fell_back = False  # this route has been stepped down once already
_route_gen = 0      # bumped by reroute(), so only the newest pick lands
_route_lock = threading.Lock()  # guards the three above


def source():
    """The RadarSource every fetch goes through."""
    return _source


def use(src):
    """Send every fetch through `src`: the source main() picked for the
    location, or the same index under another theme."""
    global _source
    with _route_lock:
        _source = src


def reroute(lat, lon, n_frames, theme):
    """Pick the source for a new location without waiting for it.

    The pick may fetch a source's index, which can take its whole
    timeout, so it runs on a thread of its own; the source in hand
    serves until the new one lands, and its landing repaints.  Only the
    newest pick lands, and the route it starts may be stepped down once
    again (see fall_back).  A theme chosen while the pick was out is
    carried over to the source it lands with.
    """
    global _route_gen
    with _route_lock:
        _route_gen += 1
        gen = _route_gen
        was = getattr(_source, "theme", None)

    def work():
        global _source, _fell_back
        src = _sources.get_source(lat, lon, n_frames, theme)
        with _route_lock:
            if gen != _route_gen:
                return  # a later pick is out; it lands instead
            now = getattr(_source, "theme", None)
            if now != was and hasattr(src, "with_theme"):
                src = src.with_theme(now)  # same index, no fetch
            _source, _fell_back = src, False
        debug_log(f"radar: routed to {getattr(src, 'label', src)}")
        _nudge()

    threading.Thread(target=work, daemon=True).start()


def source_tag():
    """The active source's name for the debug log."""
    return getattr(_source, "tag", "radar")

# in-memory cache of decoded frames: key -> (radar_buffer, echo_pct)
_frame_cache = {}
# why each frame that did not load failed, by the same key, until it
# lands: a view says so, rather than "loading" for a frame no worker is
# fetching any more and an empty map that reads as a clear sky
_failures = {}
_frame_lock = threading.Lock()  # guards both
_KEEP = N_FRAMES + 8  # entries each keeps: about the rewind window
_prefetch_lock = threading.Lock()  # guards the prefetch globals below
_prefetch_key = None  # the view, layer and frame window being prefetched
_prefetch_gen = 0     # bumped when the view changes; stale workers stand down
_prefetch_done = False  # current window's prefetch worker has finished
_buffering = False    # auto-play is held while the frame window buffers
# A window none of whose frames arrived is asked for again, but not on
# the next repaint: the key it failed under and the monotonic time
# before which no new worker starts for it.
RETRY_HOLD = 30.0
_retry_key = None
_retry_at = 0.0


def _view_key(bbox, gw, hc, src=None):
    # theme is part of the view: switching palettes must not serve old
    # colours, and neither must a terminal theme change (terminal.theme.generation).
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
    # A digest of the token rides with the timestamp, so an image a
    # source replaces under the same time is not served forever: a
    # nowcast frame is re-predicted, and a frame IEM may not have
    # composited yet is listed under a new token each step.
    import hashlib
    stamp = frame.time.strftime("%Y%m%dT%H%M")
    stamp += ":" + hashlib.sha1(str(frame.token).encode()).hexdigest()[:8]
    return _view_key(bbox, gw, hc, src) + (layer, stamp)


def _load_frame(bbox, gw, hc, frame, layer="radar"):
    """Return (radar_buffer, echo). Memoised; fetches + decodes on miss.

    A frame that lost tiles raises IncompleteFrame out of the source and
    is never reached by the memo below, so the holes it would have shown
    are neither drawn nor kept: the prefetcher tries it again, and until
    it lands the view holds the nearest frame it does have and says this
    one is unavailable (failure()), as it does for any fetch that fails.
    """
    # one source for the key and the fetch: a theme swap replaces _source
    # between the two, and the new palette must not land under the old key
    src = _source
    key = _frame_key(bbox, gw, hc, frame, layer, src)
    with _frame_lock:
        hit = _frame_cache.get(key)
    if hit is not None:
        return hit
    try:
        if layer == "sat":
            pw, ph, rgba = src.satellite_rgba(bbox, gw, hc, frame)
        else:
            pw, ph, rgba = src.frame_rgba(bbox, gw, hc, frame)
    except Exception as exc:
        with _frame_lock:
            _failures[key] = str(exc) or type(exc).__name__
            _trim(_failures)
        raise
    result = build_radar_buffer(rgba, pw, ph, gw, hc)
    with _frame_lock:
        _frame_cache[key] = result
        _failures.pop(key, None)
        _trim(_frame_cache)
    _nudge()  # a frame is ready
    return result


def _trim(memo):
    """Drop a memo's oldest entries past _KEEP; called under _frame_lock."""
    excess = len(memo) - _KEEP
    if excess > 0:
        for old in list(memo)[:excess]:
            memo.pop(old, None)


def _cached_frame(bbox, gw, hc, frame, layer="radar"):
    """Cache-only lookup; never touches the network."""
    key = _frame_key(bbox, gw, hc, frame, layer)
    with _frame_lock:
        return _frame_cache.get(key)


def failure(bbox, gw, hc, frame, layer="radar"):
    """Why this view's frame did not load the last time it was asked
    for, or None if it has not failed (it may be on its way)."""
    key = _frame_key(bbox, gw, hc, frame, layer)
    with _frame_lock:
        return _failures.get(key)


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
    buffering()."""
    global _buffering
    mask = _loaded_mask(bbox, gw, hc, frames, layer)
    n_loaded = sum(mask)
    _buffering = (playing and not _prefetch_done
                  and n_loaded < len(frames)
                  and n_loaded < math.ceil(len(frames) * PLAY_READY))
    return mask, _buffering


def buffering():
    """Whether auto-play is held while the frame window buffers."""
    return _buffering


def _ensure_prefetch(bbox, gw, hc, frames, start_idx=0, layer="radar"):
    """Warm the frame window in the background, displayed frame first.

    A view change (pan/zoom/resize/theme) bumps the generation so a
    superseded worker stops issuing fetches for a view nobody is looking
    at. The key also covers the frame window itself, so a long-running
    session re-warms whenever the index publishes a new frame (or
    re-predicts a nowcast) — cached frames hit instantly, only the new
    images fetch.

    A window that came back empty (offline, or a source with nothing
    for this view once the chain is spent) is tried again, but only
    after RETRY_HOLD: every repaint calls this, and a worker whose
    fetches all fail at once would otherwise be replaced the moment it
    finished, which is a few hundred requests a second against a host
    that is not answering.
    """
    global _prefetch_key, _prefetch_gen, _prefetch_done
    key = (_view_key(bbox, gw, hc), layer,
           tuple((f.time, str(f.token)) for f in frames))
    with _prefetch_lock:
        if _prefetch_key == key:
            return
        if key == _retry_key and time.monotonic() < _retry_at:
            return
        _prefetch_key = key
        _prefetch_done = False
        _prefetch_gen += 1
        gen = _prefetch_gen
    ordered = frames[start_idx:] + frames[:start_idx]  # current frame first
    want_warnings = _warnings.covers(bbox)
    src = _source  # the source this window was listed by

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
        if not load(ordered[0]) and gen == _prefetch_gen and fall_back(src):
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
            global _prefetch_key, _prefetch_done, _retry_key, _retry_at
            current = gen == _prefetch_gen
            if current:
                _prefetch_done = True  # opens the auto-play gate
                if loaded == 0:
                    # nothing arrived (offline?) — a later render may
                    # retry, once the hold has passed
                    _prefetch_key = None
                    _retry_key = key
                    _retry_at = time.monotonic() + RETRY_HOLD
        if current and loaded:
            # a frame landed nudges as it lands; this one is for the
            # gate opening.  Nothing landed, nothing to repaint — and a
            # repaint here is what started the next worker at once.
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
    global _prefetch_gen, _prefetch_key, _retry_key
    with _prefetch_lock:
        _prefetch_gen += 1
        _prefetch_key = None
        _retry_key = None


getattr(threading, "_register_atexit", atexit.register)(stand_down)


def fall_back(src=None):
    """Swap `src`, the source in use by default, for the next one down
    the chain.  True if the source in use is no longer `src`.

    The displayed frame is the one the source gets every tile connection
    to itself; when even that comes back short, the host is not serving,
    and waiting on the rest of the window only spends more time to learn
    it again.  Once per route, so a source that is merely having a bad
    minute is not abandoned on the strength of a second one.  A pan
    across the edge of the lower 48 starts a new route (reroute), which
    may pick the host that failed before, since its index answering says
    nothing about its tiles, so that route may be stepped down too.

    A source replaced while this looked for the next one (a new route,
    or a theme) is left in place.
    """
    global _source, _fell_back
    with _route_lock:
        src = _source if src is None else src
        if src is not _source:
            return True  # replaced already
        if _fell_back:
            return False
        _fell_back = True
    nxt = _sources.demote(src)  # may fetch an index: not under the lock
    with _route_lock:
        if src is not _source:
            return True
        if nxt is None:
            return False  # nothing to fall to; stop asking
        debug_log(f"{getattr(src, 'tag', 'radar')}: the displayed frame did not "
                  f"arrive; falling back to {nxt.label}")
        _source = nxt
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
        if _warnings.cached_at(frame.time) is None:
            _warnings.warnings_at(frame.time)
            _nudge()
    except Exception as exc:
        log_failure("radar/warnings", "prefetch", exc, url=_warnings._URL,
                    fallback="frame shown without warnings")
