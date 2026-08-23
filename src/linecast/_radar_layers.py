"""Weather condition layers for the radar view (temperature fill, wind arrows).

Data: Open-Meteo multi-point sampling.  A coarse lattice of points is laid
over the view bbox and fetched as one hourly request (temperature, wind speed
and direction, yesterday through tomorrow), so the layers can follow the
radar scrubber through time.  Values between lattice points are interpolated
bilinearly; wind is interpolated as u/v vector components so directions
never take the long way around 0°/360°.

Rendering follows the radar view's layering principle: the temperature field
is a *background tint* (geography braille and radar echoes stay on top), and
wind is a lattice of arrow glyphs.  Wind speed is encoded as *contrast*, not
hue: arrows sit on the theme's background→foreground axis, fading to
invisible in near-calm and reaching full text contrast in storm-force wind —
so "how visible is the arrow" simply is "how windy is it", and the neutrals
never fight the radar echo colours for attention.
"""

import datetime
import math

from linecast import _theme
from linecast._cache import CACHE_ROOT, read_cache, read_stale, write_cache
from linecast._color import lerp, interp_stops, BG_PRIMARY
from linecast._http import fetch_json
from linecast import USER_AGENT

# lattice resolution: 10x6 keeps one fetch cheap while resolving synoptic
# gradients (~0.6° spacing at the default 6° zoom)
_NX, _NY = 10, 6
_FIELD_TTL = 1800  # seconds before a cached field is refetched
_QUANT = 0.25      # bbox snap so small pans reuse the cached lattice

# temperature ramp (°C), tinted toward the terminal background at render time
TEMP_STOPS = [
    (-35, (120, 70, 180)),
    (-20, (110, 90, 220)),
    (-10, (80, 120, 230)),
    (0, (70, 160, 220)),
    (8, (80, 190, 170)),
    (15, (110, 200, 110)),
    (22, (215, 210, 100)),
    (28, (235, 160, 80)),
    (34, (235, 100, 70)),
    (42, (200, 50, 120)),
]

# wind speed → contrast: hidden below CALM_KMH (Beaufort 0–1), then a
# faint-to-full ramp topping out at storm force
CALM_KMH = 5.0
_FULL_KMH = 80.0
_MIN_LEVEL = 0.25  # faintest visible arrow's position on the bg→fg axis

# arrow glyph per 45° sector of the direction the wind blows *toward*
_ARROWS = "↑↗→↘↓↙←↖"


def wind_color(speed_kmh):
    """Neutral arrow colour for a wind speed, or None when too calm to draw.

    Contrast carries the meaning: the colour walks the terminal theme's
    background→foreground axis, so faster wind reads brighter on dark
    themes and darker on light themes — always *more visible*.
    """
    if speed_kmh < CALM_KMH:
        return None
    t = min(1.0, (speed_kmh - CALM_KMH) / (_FULL_KMH - CALM_KMH)) ** 0.8
    level = _MIN_LEVEL + (1.0 - _MIN_LEVEL) * t
    # read the theme at call time: the palette probe may refine fg/bg
    return _theme.lerp_rgb(_theme.theme_bg, _theme.theme_fg, level)


def field_key(bbox):
    """Cache key for the lattice covering `bbox` (snapped outward)."""
    minlon, minlat, maxlon, maxlat = bbox
    q = _QUANT
    return (math.floor(minlon / q) * q, math.floor(minlat / q) * q,
            math.ceil(maxlon / q) * q, math.ceil(maxlat / q) * q)


class Field:
    """A time-indexed lattice of temperature and wind over one bbox."""

    def __init__(self, payload):
        self.lats = payload["lats"]    # descending (north edge first)
        self.lons = payload["lons"]
        self.times = [datetime.datetime.fromisoformat(t).replace(
            tzinfo=datetime.timezone.utc) for t in payload["times"]]
        self.temp = payload["temp"]    # [point][t] °C, point = j*NX + i
        # wind stored as vector components (km/h, toward-direction) so
        # interpolation is linear; direction recovered per sample
        self.u = payload["u"]
        self.v = payload["v"]

    def nearest_time_idx(self, when):
        if when.tzinfo is None:
            when = when.replace(tzinfo=datetime.timezone.utc)
        return min(range(len(self.times)),
                   key=lambda i: abs((self.times[i] - when).total_seconds()))

    def _bilinear(self, arr, t, lon, lat):
        nx, ny = len(self.lons), len(self.lats)
        fx = (lon - self.lons[0]) / (self.lons[-1] - self.lons[0]) * (nx - 1)
        fy = (self.lats[0] - lat) / (self.lats[0] - self.lats[-1]) * (ny - 1)
        fx = max(0.0, min(nx - 1.001, fx))
        fy = max(0.0, min(ny - 1.001, fy))
        i, j = int(fx), int(fy)
        tx, ty = fx - i, fy - j
        p00 = arr[j * nx + i][t]
        p10 = arr[j * nx + i + 1][t]
        p01 = arr[(j + 1) * nx + i][t]
        p11 = arr[(j + 1) * nx + i + 1][t]
        top = p00 + (p10 - p00) * tx
        bot = p01 + (p11 - p01) * tx
        return top + (bot - top) * ty

    def sample_temp(self, t, lon, lat):
        return self._bilinear(self.temp, t, lon, lat)

    def sample_wind(self, t, lon, lat):
        """(speed_kmh, bearing_toward_deg) at a point."""
        u = self._bilinear(self.u, t, lon, lat)
        v = self._bilinear(self.v, t, lon, lat)
        speed = math.hypot(u, v)
        bearing = math.degrees(math.atan2(u, v)) % 360.0
        return speed, bearing


def fetch_field(bbox, timeout=10):
    """Fetch (or load from cache) the Field for the lattice covering `bbox`."""
    key = field_key(bbox)
    minlon, minlat, maxlon, maxlat = key
    cdir = CACHE_ROOT / "radar"
    cdir.mkdir(parents=True, exist_ok=True)
    cpath = cdir / ("field_%s_%s_%s_%s.json" % tuple(
        str(round(v, 2)).replace("-", "m").replace(".", "p") for v in key))
    cached = read_cache(cpath, _FIELD_TTL)
    if cached is not None:
        return Field(cached)

    lats = [maxlat - j * (maxlat - minlat) / (_NY - 1) for j in range(_NY)]
    lons = [minlon + i * (maxlon - minlon) / (_NX - 1) for i in range(_NX)]
    lat_q = ",".join(f"{lat:.3f}" for lat in lats for _ in lons)
    lon_q = ",".join(f"{lon:.3f}" for _ in lats for lon in lons)
    url = ("https://api.open-meteo.com/v1/forecast"
           f"?latitude={lat_q}&longitude={lon_q}"
           "&hourly=temperature_2m,wind_speed_10m,wind_direction_10m"
           "&past_days=1&forecast_days=2&timezone=UTC&wind_speed_unit=kmh")
    try:
        results = fetch_json(url, headers={"User-Agent": USER_AGENT},
                             timeout=timeout)
    except Exception:
        stale = read_stale(cpath)  # network down: an old field beats none
        if stale is not None:
            return Field(stale)
        raise
    if isinstance(results, dict):  # single point never happens, but be safe
        results = [results]

    temp, u, v = [], [], []
    for point in results:
        h = point["hourly"]
        temp.append([x if x is not None else 0.0
                     for x in h["temperature_2m"]])
        pu, pv = [], []
        for spd, wdir in zip(h["wind_speed_10m"], h["wind_direction_10m"]):
            if spd is None or wdir is None:
                pu.append(0.0)
                pv.append(0.0)
                continue
            # meteorological direction is where wind comes *from*; the
            # vector (and our arrows) point where it is going
            rad = math.radians(wdir)
            pu.append(-spd * math.sin(rad))
            pv.append(-spd * math.cos(rad))
        u.append(pu)
        v.append(pv)

    payload = {"lats": lats, "lons": lons,
               "times": results[0]["hourly"]["time"],
               "temp": temp, "u": u, "v": v}
    write_cache(cpath, payload)
    return Field(payload)


def build_temp_buffer(field, t_idx, bbox, graph_w, height_cells, alpha=0.5):
    """Temperature tint as a sub-pixel RGB buffer (same shape as the radar's).

    Colors are blended toward the terminal background so braille geography
    and radar echoes stay legible on top.
    """
    minlon, minlat, maxlon, maxlat = bbox
    spy_h = height_cells * 2
    buf = []
    for spy in range(spy_h):
        lat = maxlat - (spy + 0.5) / spy_h * (maxlat - minlat)
        row = []
        for x in range(graph_w):
            lon = minlon + (x + 0.5) / graph_w * (maxlon - minlon)
            t = field.sample_temp(t_idx, lon, lat)
            row.append(lerp(BG_PRIMARY, interp_stops(TEMP_STOPS, t), alpha))
        buf.append(row)
    return buf


def wind_overlays(field, t_idx, bbox, graph_w, height_cells,
                  col_step=6, row_step=3):
    """{(col,row): (arrow_char, color)} on a staggered lattice.

    Arrows point where the wind is blowing toward; contrast encodes speed
    (see wind_color).  Near-calm cells draw nothing at all.
    """
    minlon, minlat, maxlon, maxlat = bbox
    overlays = {}
    for row in range(row_step // 2, height_cells, row_step):
        offset = (row // row_step % 2) * (col_step // 2)
        for col in range(col_step // 2 + offset, graph_w, col_step):
            lat = maxlat - (row + 0.5) / height_cells * (maxlat - minlat)
            lon = minlon + (col + 0.5) / graph_w * (maxlon - minlon)
            speed, bearing = field.sample_wind(t_idx, lon, lat)
            color = wind_color(speed)
            if color is None:
                continue
            arrow = _ARROWS[round(bearing / 45.0) % 8]
            overlays[(col, row)] = (arrow, color)
    return overlays

from linecast import _theme as _theme_mod
_theme_mod.reimport_on_reload(globals(), "linecast._color",
"BG_PRIMARY")
