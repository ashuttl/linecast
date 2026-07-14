"""Pluggable radar sources behind one small contract.

A source exposes:
  .label / .attribution   — footer text
  .current_frames()       — ordered Frame list, oldest → newest (may include
                            forecast frames flagged .future)
  .frame_rgba(bbox, gw, hc, frame) → (pw, ph, rgba)  at gw × hc*2, EPSG:4326

Region routing: LibreWXR is primary everywhere — real radar composites for
North America / Europe / East Asia, model precipitation elsewhere, nowcast
frames, and selectable colour themes.  On failure, the continental US falls
back to IEM/NEXRAD (deep 3h history, native projection) and the rest of the
world to RainViewer, with IEM as the last resort.
"""

import datetime

from linecast._png import decode_rgba
from linecast._radar_source import fetch_frame, frame_times
from linecast import _radar_tiles as tiles

# rough lower-48 bounding box; IEM/NEXRAD coverage
_CONUS = (-127.0, 23.0, -65.0, 50.0)

# LibreWXR server-rendered colour schemes (name → tile-path colour id),
# in picker display order.
THEMES = {
    "universal-blue": 2,
    "rainbow": 7,
    "nexrad": 6,
    "original": 1,
    "titan": 3,
    "twc": 4,
    "meteored": 5,
    "dark-sky": 8,
    "datameteo": 9,
    "viper": 10,
    "mrms": 11,
    "max-storm": 12,
    "black-white": 0,
}
# matches the palette we rendered before LibreWXR (RainViewer free tier)
DEFAULT_THEME = "universal-blue"


def theme_id(value):
    """Resolve a theme name or bare numeric id to a colour id, or None."""
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in THEMES:
        return THEMES[text]
    try:
        num = int(text)
    except ValueError:
        return None
    return num if num in THEMES.values() else None


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


class _TileSource:
    """Shared body for sources speaking the RainViewer v2 tile protocol."""

    def __init__(self, provider):
        self.provider = provider
        self.host = None
        self._frames = []
        self._built_at = 0.0
        self._refresh()

    def _refresh(self):
        import time
        idx = tiles.fetch_index(self.provider)
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
        return tiles.reproject(self.provider, self.host, frame.token,
                               bbox, gw, hc * 2, mutable=frame.future)


class RainViewerSource(_TileSource):
    label = "RainViewer"
    attribution = "Weather data by RainViewer"

    def __init__(self):
        super().__init__(tiles.rainviewer_provider())


class LibreWXRSource(_TileSource):
    label = "LibreWXR"
    attribution = "Weather data by LibreWXR · CC BY 4.0"
    themes = THEMES  # advertises the in-radar theme picker

    def __init__(self, theme=THEMES[DEFAULT_THEME]):
        self.theme = theme
        super().__init__(tiles.librewxr_provider(theme))


def _utc(epoch):
    return datetime.datetime.fromtimestamp(epoch, datetime.timezone.utc)


def get_source(lat, lon, n_frames, theme=None):
    """Pick the best source for a location, falling back on failure."""
    if theme is None:
        theme = THEMES[DEFAULT_THEME]
    try:
        src = LibreWXRSource(theme)
        if src.current_frames():
            return src
    except Exception:
        pass
    if not _in_conus(lat, lon):
        try:
            src = RainViewerSource()
            if src.current_frames():
                return src
        except Exception:
            pass
    return IEMSource(n_frames)
