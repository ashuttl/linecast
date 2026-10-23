"""NEXRAD radar frames from the Iowa State Mesonet (IEM) WMS.

Uses IEM's time-aware WMS-T service so we can fetch both the latest composite
and older frames (for the rewind-the-storm animation).  Frames are fetched at
exactly the framebuffer's sub-pixel dimensions (server-side resampling) and the
raw PNG bytes are cached on disk.

IEM answers a time it has not composited yet with a fully transparent
image, which looks exactly like a clear sky.  So an empty frame is not
believed while it is recent: it is not written to disk, and the live
view asks for it again a step later (see IEMSource).  Once the frame
has settled, an empty one is a clear sky and is kept like any other.
A frame with echo in it is IEM's composite and never changes.

Data: NWS NEXRAD Level III base reflectivity (n0q), composited by IEM.
Attribution: Iowa Environmental Mesonet, Iowa State University.
"""

import datetime

from linecast._cache import write_bytes_atomic
from linecast._http import fetch_bytes
from linecast._paths import cache_dir
from linecast._png import decode_rgba
from linecast._log import debug_log, log_failure

_WMS = "https://mesonet.agron.iastate.edu/cgi-bin/wms/nexrad/n0q-t.cgi"
_LAYER = "nexrad-n0q-wmst"
FRAME_STEP = 5 * 60          # radar composite cadence, seconds
_LATENCY = 5 * 60            # newest frame lags real time by ~one step
_SETTLE = 3 * FRAME_STEP     # by this age IEM has composited a frame


def _floor_step(dt):
    """Floor a UTC datetime to the nearest 5-minute frame boundary."""
    m = dt.minute - (dt.minute % 5)
    return dt.replace(minute=m, second=0, microsecond=0)


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


def latest_frame_time(now_utc: datetime.datetime | None = None) -> datetime.datetime:
    """Newest frame timestamp likely to have data, given radar latency."""
    now_utc = now_utc or _now()
    return _floor_step(now_utc - datetime.timedelta(seconds=_LATENCY))


def settled(when: datetime.datetime, now_utc: datetime.datetime | None = None) -> bool:
    """Whether IEM has surely composited the frame for `when` by now.

    Until then an empty answer may only mean that IEM is running later
    than _LATENCY allows for."""
    return ((now_utc or _now()) - when).total_seconds() >= _SETTLE


def frame_times(count: int, end: datetime.datetime | None = None
                ) -> list[datetime.datetime]:
    """`count` frame timestamps ending at `end` (default latest), oldest first."""
    end = end or latest_frame_time()
    step = datetime.timedelta(seconds=FRAME_STEP)
    return [end - step * (count - 1 - i) for i in range(count)]


def _url(bbox, w, h, when):
    minlon, minlat, maxlon, maxlat = bbox
    return (
        f"{_WMS}?SERVICE=WMS&VERSION=1.1.1&REQUEST=GetMap&LAYERS={_LAYER}"
        f"&STYLES=&FORMAT=image/png&TRANSPARENT=true&SRS=EPSG:4326"
        f"&BBOX={minlon},{minlat},{maxlon},{maxlat}&WIDTH={w}&HEIGHT={h}"
        f"&TIME={when.strftime('%Y-%m-%dT%H:%M:00Z')}"
    )


def _cache_path(bbox, w, h, when):
    key = f"{bbox[0]:.3f}_{bbox[1]:.3f}_{bbox[2]:.3f}_{bbox[3]:.3f}_{w}x{h}"
    stamp = when.strftime("%Y%m%dT%H%M")
    return cache_dir("radar", f"{key}_{stamp}.png")


def is_empty(rgba: bytearray) -> bool:
    """Whether decoded RGBA has no pixel with any opacity."""
    return not rgba[3::4].strip(b"\0")


def fetch_frame(bbox: tuple[float, float, float, float], w: int, h: int,
                when: datetime.datetime, timeout: float = 15
                ) -> tuple[int, int, bytearray]:
    """The radar frame for UTC `when`, decoded: (width, height, rgba).

    A copy on disk is final, since only a settled or non-empty frame is
    written; one that will not decode is fetched again.
    """
    when = _floor_step(when)
    path = _cache_path(bbox, w, h, when)

    try:
        if path.exists():
            frame = decode_rgba(path.read_bytes())
            debug_log(f"radar cache hit: {path.name}")
            return frame
    except Exception as exc:
        log_failure("cache", f"read of {path.name}", exc, fallback="refetching")

    url = _url(bbox, w, h, when)
    try:
        data = fetch_bytes(url, timeout=timeout)
    except Exception as exc:
        log_failure("radar/iem", "frame fetch", exc, url=url, fallback="raised")
        raise
    frame = decode_rgba(data)  # a torn answer raises here, and is not kept

    if not settled(when) and is_empty(frame[2]):
        debug_log(f"radar/iem: the {when:%H:%M} frame came back empty; "
                  f"not kept while it may not be composited yet")
        return frame
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        write_bytes_atomic(path, data)
    except OSError as exc:
        log_failure("cache", f"write of {path.name}", exc, fallback="not cached")
    return frame
