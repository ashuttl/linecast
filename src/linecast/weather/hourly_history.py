"""The month view's Celsius archive and recent model estimates."""

import math
from datetime import date, timedelta
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from linecast._cache import location_cache_key
from linecast._http import fetch_json_cached
from linecast._log import log_failure
from linecast._paths import cache_dir
from linecast.weather.historical import _fetch_archive, history_span
from linecast.weather.month import Temperatures

HISTORY_AGE = 7 * 86400
YEAR_AGE = 3 * 3600
RECENT_AGE = 3600


def _validate(data):
    ZoneInfo(data["timezone"])
    hourly = data["hourly"]
    if not hourly.get("time") or len(hourly["time"]) != len(hourly["temperature_2m"]):
        raise ValueError("hourly temperatures are empty or incomplete")
    return data


def read_archive(lat, lng, first, last, *, year=False, stale=None):
    """A cached span, with stale data standing in on a failed refresh.

    Unix timestamps distinguish both occurrences of an autumn clock hour.
    The caller pads historical boundaries by a day: the API's UTC offset
    can differ from the offset at the beginning or end of a long request.
    """
    key = location_cache_key(lat, lng)
    tag = f"year_{last.year}" if year else f"hist_{first.year + 1}-{last.year - (last.month == 1)}"
    path = cache_dir("weather") / f"hourly_{key}_{tag}.json"
    age = YEAR_AGE if year else HISTORY_AGE
    params = dict(latitude=lat, longitude=lng, start_date=first, end_date=last,
                  hourly="temperature_2m", temperature_unit="celsius",
                  timezone="auto", timeformat="unixtime")
    url = "https://archive-api.open-meteo.com/v1/archive?" + urlencode(params)

    def validate(data):
        return dict(_validate(data), _requested_end=last.isoformat())

    return fetch_json_cached(
        path, age, url, timeout=30, provider="weather/hourly",
        fresh=lambda data: data.get("_requested_end") == last.isoformat(),
        fetch=lambda url, timeout: _fetch_archive(url, timeout, stale=stale),
        transform=validate)


def read_recent(lat, lng, today):
    """Recent model hours, cached separately so the archive can replace them.

    Tomorrow supplies the interpolation endpoint for today's last hour.
    The renderer reveals these hours only as the local clock reaches them.
    """
    key = location_cache_key(lat, lng)
    path = cache_dir("weather") / f"hourly_{key}_recent.json"
    params = dict(latitude=lat, longitude=lng, start_date=today - timedelta(days=7),
                  end_date=today + timedelta(days=1), hourly="temperature_2m",
                  temperature_unit="celsius", timezone="auto", timeformat="unixtime")
    url = "https://api.open-meteo.com/v1/forecast?" + urlencode(params)

    def validate(data):
        _validate(data)
        if not any(isinstance(v, (int, float)) and math.isfinite(v)
                   for v in data["hourly"]["temperature_2m"]):
            raise ValueError("recent temperatures are missing")
        return dict(data, _requested_day=today.isoformat())

    return fetch_json_cached(
        path, RECENT_AGE, url, timeout=10, provider="weather/hourly",
        fresh=lambda data: data.get("_requested_day") == today.isoformat(),
        transform=validate)


def fetch_month(lat, lng, today, *, stale=None):
    """Return the indexed archive, recent hours, and request completeness.

    Recent estimates fill gaps when rendering, never in the comparison mean.
    Missing spans leave their cells blank. Current-year values are not averaged.
    """
    span = history_span(today.year)
    end = today - timedelta(days=1)
    history_end = min(date(today.year, 1, 1), end)
    requests = [(date(span[0] - 1, 12, 31), history_end, False)]
    if end.year == today.year:
        requests.append((date(today.year - 1, 12, 31), end, True))
    payloads, complete = [], True
    for first, last, year in requests:
        if stale and stale():
            return None, False
        data = read_archive(lat, lng, first, last, year=year, stale=stale)
        if data:
            payloads.append(data)
        complete = complete and bool(data and data.get("_requested_end") == last.isoformat())
    if stale and stale():
        return None, False
    recent = read_recent(lat, lng, today)
    complete = complete and bool(recent and recent.get("_requested_day") == today.isoformat())
    if stale and stale():
        return None, False
    if not payloads and not recent:
        return None, False
    try:
        series = Temperatures.build(payloads, span, recent=recent)
        return (series, complete) if series.days or recent else (None, False)
    except (KeyError, TypeError, ValueError) as exc:
        log_failure("weather/hourly", "index archive", exc, fallback="empty month")
        return None, False
