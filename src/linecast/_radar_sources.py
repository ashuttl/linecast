"""Pluggable radar sources behind one small contract.

A source exposes:
  .label / .attribution   — footer text
  .current_frames()       — ordered Frame list, oldest → newest (may include
                            forecast frames flagged .future)
  .frame_rgba(bbox, gw, hc, frame) → (pw, ph, rgba)  at gw × hc*2, EPSG:4326

Region routing: the continental US uses IEM/NEXRAD (deep 3h history, no zoom
ceiling, native projection); everywhere else uses RainViewer (global, plus
forecast/nowcast frames where available).
"""

import datetime

from linecast._png import decode_rgba
from linecast._radar_source import fetch_frame, frame_times
from linecast import _radar_rainviewer as rv

# rough lower-48 bounding box; IEM/NEXRAD coverage
_CONUS = (-127.0, 23.0, -65.0, 50.0)


def _in_conus(lat, lon):
    w, s, e, n = _CONUS
    return w <= lon <= e and s <= lat <= n


class Frame:
    """One radar frame: a UTC time, a source-specific token, past-or-future."""
    __slots__ = ("time", "token", "future")

    def __init__(self, time, token, future=False):
        self.time = time
        self.token = token
        self.future = future


class IEMSource:
    label = "NEXRAD · IEM"
    attribution = "NEXRAD · IEM"

    def __init__(self, n_frames):
        self.n_frames = n_frames

    def current_frames(self):
        # timestamps are cheap to recompute, so newer frames appear live
        return [Frame(t, t) for t in frame_times(self.n_frames)]

    def frame_rgba(self, bbox, gw, hc, frame):
        png = fetch_frame(bbox, gw, hc * 2, when=frame.token)
        return decode_rgba(png)


class RainViewerSource:
    label = "RainViewer"
    attribution = "Weather data by RainViewer"

    def __init__(self):
        self.host = None
        self._frames = []
        self._built_at = 0.0
        self._refresh()

    def _refresh(self):
        import time
        idx = rv.fetch_index()
        self.host = idx["host"]
        radar = idx.get("radar", {})
        frames = []
        for f in radar.get("past") or []:
            frames.append(Frame(_utc(f["time"]), f["path"], False))
        for f in radar.get("nowcast") or []:
            frames.append(Frame(_utc(f["time"]), f["path"], True))
        frames.sort(key=lambda fr: fr.time)
        self._frames = frames
        self._built_at = time.time()

    def current_frames(self):
        import time
        if not self._frames or (time.time() - self._built_at) > 60:
            try:
                self._refresh()
            except Exception:
                pass
        return self._frames

    def frame_rgba(self, bbox, gw, hc, frame):
        return rv.reproject(self.host, frame.token, bbox, gw, hc * 2)


def _utc(epoch):
    return datetime.datetime.fromtimestamp(epoch, datetime.timezone.utc)


def get_source(lat, lon, n_frames):
    """Pick the best source for a location, falling back to IEM on failure."""
    if _in_conus(lat, lon):
        return IEMSource(n_frames)
    try:
        src = RainViewerSource()
        if src.current_frames():
            return src
    except Exception:
        pass
    return IEMSource(n_frames)
