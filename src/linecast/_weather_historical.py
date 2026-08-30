"""Historical weather averages from Open-Meteo Archive API.

Fetches the same calendar date over the past 10 years, computes mean
high/low temperatures and precipitation, and returns a simple result
object for annotating the current weather display.

The Archive API is free, requires no key, and the data is immutable
for past dates — so we cache aggressively (7 days).
"""

from dataclasses import dataclass
from datetime import date
from typing import Optional

from linecast._cache import location_cache_key
from linecast._http import fetch_json_cached
from linecast._paths import cache_dir
from linecast._runtime import log_skipped

_HISTORY_YEARS = 10
_CACHE_MAX_AGE = 7 * 86400  # 7 days — historical data doesn't change


@dataclass(frozen=True)
class HistoricalAverages:
    """Historical climate averages for a single calendar date."""
    avg_high: float   # mean daily high (in forecast units)
    avg_low: float    # mean daily low  (in forecast units)
    avg_precip: float # mean daily precipitation sum
    years: int        # number of years averaged


def fetch_historical(lat: float, lng: float, target_date: date,
                     celsius: bool = False, metric: bool = False) -> Optional[HistoricalAverages]:
    """Fetch historical averages for *target_date* at the given location.

    Returns ``HistoricalAverages`` or ``None`` if data is unavailable.
    Uses Open-Meteo's Archive API with the same temperature/precipitation
    units as the forecast so values are directly comparable.
    """
    # The archive request covers the last N complete years and depends only
    # on that year span, the units, and the location -- not on the calendar
    # day. Key the cache the same way so one download serves every day of
    # the year; the target day is picked out client-side in _compute_averages.
    # The span (and so the key) rolls over on 1 January, exactly when a new
    # complete year becomes available and the request itself changes.
    end_year = target_date.year - 1  # most recent complete year
    start_year = end_year - _HISTORY_YEARS + 1

    temp_tag = "C" if celsius else "F"
    precip_tag = "mm" if metric else "in"
    cache_file = (
        cache_dir("weather")
        / f"hist_{location_cache_key(lat, lng)}_{start_year}-{end_year}_{temp_tag}{precip_tag}.json"
    )

    start_date = f"{start_year}-01-01"
    end_date = f"{end_year}-12-31"

    temp_unit = "celsius" if celsius else "fahrenheit"
    precip_unit = "mm" if metric else "inch"

    url = (
        "https://archive-api.open-meteo.com/v1/archive"
        f"?latitude={lat}&longitude={lng}"
        f"&start_date={start_date}&end_date={end_date}"
        "&daily=temperature_2m_max,temperature_2m_min,precipitation_sum"
        f"&temperature_unit={temp_unit}"
        f"&precipitation_unit={precip_unit}"
        "&timezone=auto"
    )

    data = fetch_json_cached(
        cache_file,
        _CACHE_MAX_AGE,
        url,
        timeout=15,
        fallback=None,
    )
    if not data:
        return None

    return _compute_averages(data, target_date.month, target_date.day)


def _compute_averages(data, month: int, day: int) -> Optional[HistoricalAverages]:
    """Extract matching month-day rows from archive response and average them."""
    daily = data.get("daily", {})
    times = daily.get("time", [])
    highs = daily.get("temperature_2m_max", [])
    lows = daily.get("temperature_2m_min", [])
    precips = daily.get("precipitation_sum", [])

    if not times:
        return None

    sum_hi = 0.0
    sum_lo = 0.0
    sum_precip = 0.0
    count = 0

    dropped = 0
    bad = None
    for i, t in enumerate(times):
        # times are "YYYY-MM-DD" strings
        try:
            parts = t.split("-")
            m, d = int(parts[1]), int(parts[2])
        except (IndexError, ValueError) as exc:
            dropped += 1
            bad = exc
            continue

        if m == month and d == day:
            hi = highs[i] if i < len(highs) else None
            lo = lows[i] if i < len(lows) else None
            pr = precips[i] if i < len(precips) else None
            if hi is not None and lo is not None:
                sum_hi += hi
                sum_lo += lo
                sum_precip += (pr if pr is not None else 0)
                count += 1
    log_skipped("weather/climate", "daily dates", dropped, len(times), bad)

    if count == 0:
        return None

    return HistoricalAverages(
        avg_high=round(sum_hi / count, 1),
        avg_low=round(sum_lo / count, 1),
        avg_precip=round(sum_precip / count, 2),
        years=count,
    )


def format_historical_comparison(current_high: float, current_low: float,
                                 hist: HistoricalAverages, runtime) -> str:
    """Format a short comparison string like '3° above avg' or 'avg 68°'.

    Returns an empty string if the difference is negligible.
    """
    from linecast._weather_i18n import _s

    diff = current_high - hist.avg_high
    abs_diff = abs(diff)

    # Thresholds: smaller for Celsius since 1°C ~ 1.8°F
    threshold = 1.5 if getattr(runtime, "celsius", False) else 2.5
    if abs_diff < threshold:
        return _s("hist_near_avg", runtime)

    rounded = round(abs_diff)
    deg = "\u00b0"
    if diff > 0:
        return _s("hist_above_avg", runtime, diff=f"{rounded}{deg}")
    else:
        return _s("hist_below_avg", runtime, diff=f"{rounded}{deg}")
