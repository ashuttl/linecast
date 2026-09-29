"""Historical weather averages from Open-Meteo Archive API.

Fetches the past 10 years of daily highs and lows, computes the mean
high/low temperatures and precipitation for one calendar date, and
averages each year's hottest and coldest day, which give the hourly
temperature graph its scale under --temp-range climate or auto.

The Archive API is free, requires no key, and the data is immutable
for past dates — so we cache aggressively (7 days).

The archive is the slow provider on the dashboard, and the touchy one:
it takes a few seconds to answer, refuses a handful of requests in
flight at once from one address with a 429, and now and then accepts a
request and never answers it.  So this module sends it one request at a
time, retries a refusal or a timeout, and lets a request that no one is
waiting for any more give up its place in the queue.
"""

import threading
import time
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Callable, Optional

from linecast._cache import location_cache_key, read_cache
from linecast._http import HTTPError, fetch_json, fetch_json_cached
from linecast._paths import cache_dir
from linecast._log import debug_log, log_skipped
from linecast.weather.forecast import _at

_HISTORY_YEARS = 10
_CACHE_MAX_AGE = 7 * 86400  # 7 days — historical data doesn't change
_YEAR_CACHE_MAX_AGE = 3 * 3600  # this year's days are still being revised
# One archive request in flight per process: the server answers a burst
# of them with "Too many concurrent requests".
_ARCHIVE_LOCK = threading.Lock()
# Pauses before the second and third attempt after a refusal.
_RETRY_DELAYS = (1.0, 2.0)
# A request the server accepted and never answered is tried once more,
# with less patience: the first wait already spent most of the caller's.
_RETRY_TIMEOUT = 10
_RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
# Per terminal character row, not per braille dot. At this resolution a
# 10°C daily swing still has two rows in which to show its shape.
_AUTO_MAX_CELSIUS_PER_ROW = 5.0


@dataclass(frozen=True)
class HistoricalAverages:
    """Historical climate averages for a single calendar date."""
    avg_high: float   # mean daily high (in forecast units)
    avg_low: float    # mean daily low  (in forecast units)
    avg_precip: float # mean daily precipitation sum
    years: int        # number of years averaged
    # A typical year's hottest high and coldest low: each year's extreme,
    # averaged over the span. A record is one freak day; this is what a
    # hot day here is. None when the archive gave no temperatures.
    year_high: Optional[float] = None
    year_low: Optional[float] = None


class Superseded(Exception):
    """The caller stopped waiting for this answer before it was asked for."""


def _fetch_archive(url: str, timeout: float = 15,
                   stale: "Callable[[], bool] | None" = None, cache_file=None,
                   max_age=_CACHE_MAX_AGE):
    """One archive request, in its turn, retried when the server balks.

    Requests queue on _ARCHIVE_LOCK so that a run of location changes
    reaches the server one at a time instead of tripping its concurrency
    limit.  `stale` is asked before each attempt whether anyone still
    wants the answer; a request from a location the user has since left
    raises Superseded rather than take the next place's turn.  A request
    that queued behind another for the same place finds its answer in
    `cache_file` when its turn comes, and sends nothing.  A 429 or a 5xx
    is retried after a short pause; a timeout or a body cut short is
    retried once with a shorter timeout.
    """
    from http.client import IncompleteRead

    with _ARCHIVE_LOCK:
        if cache_file is not None:
            cached = read_cache(cache_file, max_age)
            if cached is not None:
                return cached
        attempt = 0
        while True:
            if stale is not None and stale():
                raise Superseded("archive request no longer wanted")
            try:
                return fetch_json(url, timeout=timeout)
            except HTTPError as exc:
                if exc.code not in _RETRY_STATUSES or attempt >= len(_RETRY_DELAYS):
                    raise
                debug_log(f"weather/climate: archive answered {exc.code}; "
                          f"retrying in {_RETRY_DELAYS[attempt]:g}s")
                time.sleep(_RETRY_DELAYS[attempt])
            except (TimeoutError, IncompleteRead) as exc:
                if attempt >= 1:
                    raise
                debug_log(f"weather/climate: archive {type(exc).__name__}; retrying once")
                timeout = min(timeout, _RETRY_TIMEOUT)
            attempt += 1


def fetch_historical(lat: float, lng: float, target_date: date,
                     celsius: bool = False, metric: bool = False,
                     stale: "Callable[[], bool] | None" = None) -> Optional[HistoricalAverages]:
    """Fetch historical averages for *target_date* at the given location.

    Returns ``HistoricalAverages`` or ``None`` if data is unavailable.
    Uses Open-Meteo's Archive API with the same temperature/precipitation
    units as the forecast so values are directly comparable.  `stale`
    tells the network step that the answer is no longer wanted (see
    _fetch_archive); a cached answer is returned regardless.
    """
    data = fetch_history(lat, lng, target_date.year, celsius, metric, stale)
    if not data:
        return None

    return _compute_averages(data, target_date.month, target_date.day)


def history_span(year):
    """(first, last) of the complete years the archive is asked for when
    it is `year`: the ten before it."""
    return year - _HISTORY_YEARS, year - 1


def _archive_url(lat, lng, start_date, end_date, celsius, metric, extra=""):
    temp_unit = "celsius" if celsius else "fahrenheit"
    precip_unit = "mm" if metric else "inch"
    return (
        "https://archive-api.open-meteo.com/v1/archive"
        f"?latitude={lat}&longitude={lng}"
        f"&start_date={start_date}&end_date={end_date}"
        f"&daily=temperature_2m_max,temperature_2m_min,precipitation_sum{extra}"
        f"&temperature_unit={temp_unit}"
        f"&precipitation_unit={precip_unit}"
        "&timezone=auto"
    )


def _units_tag(celsius, metric):
    return ("C" if celsius else "F") + ("mm" if metric else "in")


def fetch_history(lat, lng, year, celsius=False, metric=False, stale=None):
    """The archive's daily highs, lows and precipitation for the ten
    complete years before `year`, as it answered them, or None.

    The request depends only on that span, the units, and the location --
    not on the calendar day -- so one download serves every day of the
    year, and the dashboard's scale and the year view share it.  The span
    (and so the key) rolls over on 1 January, exactly when a new complete
    year becomes available and the request itself changes."""
    start_year, end_year = history_span(year)
    cache_file = (
        cache_dir("weather")
        / f"hist_{location_cache_key(lat, lng)}_{start_year}-{end_year}"
          f"_{_units_tag(celsius, metric)}.json"
    )
    url = _archive_url(lat, lng, f"{start_year}-01-01", f"{end_year}-12-31",
                       celsius, metric)
    return fetch_json_cached(
        cache_file,
        _CACHE_MAX_AGE,
        url,
        timeout=15,
        fallback=None,
        fetch=lambda url, timeout: _fetch_archive(url, timeout, stale=stale,
                                                  cache_file=cache_file),
    )


def fetch_year_to_date(lat, lng, today, celsius=False, metric=False, stale=None):
    """The archive's days from 1 January of `today`'s year through the
    day before, with their weather codes and snowfall, or None.

    The archive keeps up to the day now, but its latest days are revised
    as the reanalysis catches up with them, so the answer is kept for a
    few hours rather than a week.

    The request stops at yesterday: the forecast has today, and the
    archive refuses a day past today in UTC, which east of Greenwich is
    often the place's today.  Its yesterday never is.  On 1 January
    there is nothing to ask for."""
    end = today - timedelta(days=1)
    if end.year != today.year:
        return {}
    cache_file = (
        cache_dir("weather")
        / f"year_{location_cache_key(lat, lng)}_{today.year}"
          f"_{_units_tag(celsius, metric)}.json"
    )
    # The day's weather code picks the precipitation's ink, as the
    # dashboard's daily rows do, and its snowfall tells snow from rain.
    url = _archive_url(lat, lng, f"{today.year}-01-01", end.isoformat(),
                       celsius, metric, extra=",weather_code,snowfall_sum")
    return fetch_json_cached(
        cache_file,
        _YEAR_CACHE_MAX_AGE,
        url,
        timeout=15,
        fallback=None,
        fetch=lambda url, timeout: _fetch_archive(url, timeout, stale=stale,
                                                  cache_file=cache_file,
                                                  max_age=_YEAR_CACHE_MAX_AGE),
    )


def _compute_averages(data, month: int, day: int) -> Optional[HistoricalAverages]:
    """Extract matching month-day rows from archive response and average them."""
    # The archive writes null for a day it has no value for and for a
    # whole block it could not produce; a partial answer still yields
    # the years it has, as the forecast's nulls do (issue #112).
    daily = data.get("daily") or {}
    times = daily.get("time") or []
    highs = daily.get("temperature_2m_max") or []
    lows = daily.get("temperature_2m_min") or []
    precips = daily.get("precipitation_sum") or []

    if not times:
        return None

    sum_hi = 0.0
    sum_lo = 0.0
    sum_precip = 0.0
    count = 0

    dropped = 0
    bad = None
    year_highs = {}  # year -> its hottest high so far
    year_lows = {}
    for i, t in enumerate(times):
        # times are "YYYY-MM-DD" strings, or null for a day the archive
        # could not date
        try:
            parts = t.split("-")
            y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
        except (AttributeError, IndexError, ValueError) as exc:
            dropped += 1
            bad = exc
            continue

        hi = _at(highs, i)
        lo = _at(lows, i)
        if hi is not None:
            year_highs[y] = max(hi, year_highs.get(y, hi))
        if lo is not None:
            year_lows[y] = min(lo, year_lows.get(y, lo))

        if m == month and d == day:
            pr = _at(precips, i)
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
        year_high=(round(sum(year_highs.values()) / len(year_highs), 1)
                   if year_highs else None),
        year_low=(round(sum(year_lows.values()) / len(year_lows), 1)
                  if year_lows else None),
    )


def temperature_scale(runtime, historical, forecast_range, n_rows=2):
    """The (low, high) the hourly temperature graph is drawn against.

    --temp-range climate spans a typical year's hottest
    and coldest day at the location, so the graph holds still from day
    to day and a mild day looks mild; without an archive answer it is
    the forecast's own range, which --temp-range forecast asks for
    outright. world is the same span everywhere, -40 to 50°C. The
    climate and world spans widen, and only widen, when the forecast
    reaches past either end: a heat wave beyond the usual year touches
    the top, as it should. auto (the default) uses that widened climate
    span only when n_rows can show it at no more than 5°C (9°F) per
    terminal row; otherwise it uses the forecast's own range."""
    mode = getattr(runtime, "temp_range", "auto")
    if mode in ("auto", "climate"):
        if historical is None or historical.year_low is None or historical.year_high is None:
            return forecast_range
        lo, hi = historical.year_low, historical.year_high
    elif mode == "world":
        lo, hi = (-40, 50) if runtime.celsius else (-40, 122)
    else:
        return forecast_range
    lo, hi = min(lo, forecast_range[0]), max(hi, forecast_range[1])
    if mode == "auto":
        max_per_row = _AUTO_MAX_CELSIUS_PER_ROW * (1 if runtime.celsius else 1.8)
        if (hi - lo) / max(1, n_rows) > max_per_row:
            return forecast_range
    return lo, hi


def format_historical_comparison(current_high: float, hist: HistoricalAverages, runtime) -> str:
    """Format a short comparison string like '3° above avg' or 'avg 68°'.

    Returns an empty string if the difference is negligible.
    """
    from linecast.weather.i18n import _s

    diff = current_high - hist.avg_high
    abs_diff = abs(diff)

    # Thresholds: smaller for Celsius since 1°C ~ 1.8°F
    threshold = 1.5 if getattr(runtime, "celsius", False) else 2.5
    if abs_diff < threshold:
        return _s("hist_near_avg", runtime)

    rounded = round(abs_diff)
    deg = "°"
    if diff > 0:
        return _s("hist_above_avg", runtime, diff=f"{rounded}{deg}")
    else:
        return _s("hist_below_avg", runtime, diff=f"{rounded}{deg}")
