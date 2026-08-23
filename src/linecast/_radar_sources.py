"""Pluggable radar sources behind one small contract.

A source exposes:
  .label / .attribution   — footer text (.model_attribution, if present,
                            replaces it where has_radar() is false)
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
import threading
import time

from linecast._png import decode_rgba
from linecast._radar_source import fetch_frame, frame_times
from linecast import _radar_tiles as tiles
from linecast import _radar_palettes as palettes

# rough lower-48 bounding box; IEM/NEXRAD coverage
_CONUS = (-127.0, 23.0, -65.0, 50.0)

_REFRESH_S = 60  # how long a tile source trusts its frame list

# Called from the refresh thread when a background index refresh changes
# the frame list; the live radar hangs a repaint nudge here.
on_index_refresh = None

# Colour themes in picker display order: ours first, then the server's.
# A str names one of our own palettes, coloured here from the grayscale
# scheme; an int is a LibreWXR server-rendered scheme (the tile-path
# colour id).
THEMES = {
    "terminal": "terminal",
    "dusk": "dusk",
    "ember": "ember",
    "ink": "ink",
    "marangai": "marangai",
    "dark-sky": 8,
    "universal-blue": 2,
    "rainbow": 7,
    "nexrad": 6,
    "original": 1,
    "titan": 3,
    "twc": 4,
    "meteored": 5,
    "datameteo": 9,
    "viper": 10,
    "mrms": 11,
    "max-storm": 12,
    "black-white": 0,
}
DEFAULT_THEME = "terminal"
# (universal-blue is the palette we rendered before LibreWXR)


def is_local(theme):
    """True for a theme coloured here rather than on the tile server."""
    return isinstance(theme, str)


def theme_id(value):
    """Resolve a theme name or bare numeric id to a theme id, or None."""
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


# Where LibreWXR composites real radar (rough boxes, from its source list:
# MRMS/ECCC, OPERA + DINI, JMA, CWA, MET Malaysia, PAGASA, MARN).  Outside
# these it serves model-derived precipitation, which is smoother and coarser
# than radar, and the footer should say so.
_RADAR_REGIONS = (
    (-170.0, 24.0, -52.0, 72.0),   # United States and Canada
    (-25.0, 34.0, 45.0, 72.0),     # Europe
    (122.0, 24.0, 150.0, 46.0),    # Japan
    (118.0, 21.0, 123.0, 26.0),    # Taiwan
    (99.0, 0.5, 120.0, 8.0),       # Malaysia, Singapore, Brunei
    (116.0, 4.0, 127.0, 21.0),     # Philippines
    (-91.0, 12.5, -87.0, 15.0),    # El Salvador
)


def has_radar(lat, lon):
    """True where LibreWXR's frames come from radar rather than a model."""
    return any(w <= lon <= e and s <= lat <= n
               for w, s, e, n in _RADAR_REGIONS)


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
    """Shared body for sources speaking the RainViewer v2 tile protocol.

    The first index fetch is synchronous (a source with no frames is no
    source). After that the frame list refreshes in a background thread
    once it is _REFRESH_S old, and the stale list is served meanwhile, so
    a render never waits on the network for the index.
    """

    def __init__(self, provider, index_from=None):
        self.provider = provider
        self._sat_provider = tiles.satellite_provider(provider)
        self.host = None
        self._frames = []
        self._sat_frames = []
        self._checked_at = 0.0
        self._refresh_lock = threading.Lock()
        self._refreshing = False
        if index_from is not None:
            # same index under other settings (a theme switch): no network
            self.host = index_from.host
            self._frames = index_from._frames
            self._sat_frames = index_from._sat_frames
            self._checked_at = index_from._checked_at
        else:
            self._refresh()

    def _refresh(self):
        """Fetch the index and rebuild the frame lists. Returns True when
        the radar frame list changed."""
        idx = tiles.fetch_index(self.provider)
        radar = idx.get("radar", {})
        frames = []
        for f in radar.get("past") or []:
            frames.append(Frame(_utc(f["time"]), f["path"], False))
        for f in radar.get("nowcast") or []:
            frames.append(Frame(_utc(f["time"]), f["path"], True))
        frames.sort(key=lambda fr: fr.time)
        # hourly global cloud mosaic; absent from indexes without satellite
        sat = (idx.get("satellite") or {}).get("infrared") or []
        sat_frames = sorted(
            (Frame(_utc(f["time"]), f["path"], False) for f in sat),
            key=lambda fr: fr.time)
        changed = ([(f.time, f.token) for f in frames]
                   != [(f.time, f.token) for f in self._frames])
        # whole-list assignments: a reader on another thread sees either
        # the old list or the new one, never a half-built one
        self.host = idx["host"]
        self._frames = frames
        self._sat_frames = sat_frames
        self._checked_at = time.time()
        return changed

    def _refresh_in_background(self):
        with self._refresh_lock:
            if self._refreshing:
                return
            self._refreshing = True

        def work():
            changed = False
            try:
                changed = self._refresh()
            except Exception:
                pass
            finally:
                with self._refresh_lock:
                    self._refreshing = False
                    self._checked_at = time.time()  # a failure backs off too
            hook = on_index_refresh
            if changed and hook is not None:
                hook()

        threading.Thread(target=work, daemon=True).start()

    def current_frames(self):
        if time.time() - self._checked_at > _REFRESH_S:
            self._refresh_in_background()
        return self._frames

    def satellite_frames(self):
        self.current_frames()  # shares the index refresh
        return self._sat_frames

    smooth = False  # bilinear resample; only right for raw gray tiles

    def frame_rgba(self, bbox, gw, hc, frame):
        return tiles.reproject(self.provider, self.host, frame.token,
                               bbox, gw, hc * 2, mutable=frame.future,
                               smooth=self.smooth)

    def satellite_rgba(self, bbox, gw, hc, frame):
        return tiles.reproject(self._sat_provider, self.host, frame.token,
                               bbox, gw, hc * 2)


class RainViewerSource(_TileSource):
    label = "RainViewer"
    attribution = "Weather data by RainViewer"

    def __init__(self):
        super().__init__(tiles.rainviewer_provider())


class LibreWXRSource(_TileSource):
    label = "LibreWXR"
    attribution = "Weather data by LibreWXR · CC BY 4.0"
    model_attribution = "Precipitation model by LibreWXR (no radar here) · CC BY 4.0"
    themes = THEMES  # advertises the in-radar theme picker

    def __init__(self, theme=THEMES[DEFAULT_THEME], index_from=None):
        self.theme = theme
        self.palette = palettes.PALETTES.get(theme)
        self.smooth = self.palette is not None
        super().__init__(tiles.librewxr_provider(
            theme if self.palette is None else tiles.RAW_COLOR,
            smooth=self.palette is None), index_from=index_from)

    def with_theme(self, theme):
        """This source's index under another theme; never touches the network."""
        return LibreWXRSource(theme, index_from=self)

    def frame_rgba(self, bbox, gw, hc, frame):
        w, h, rgba = super().frame_rgba(bbox, gw, hc, frame)
        if self.palette is not None:
            palettes.apply(rgba, self.palette)
        return w, h, rgba


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
