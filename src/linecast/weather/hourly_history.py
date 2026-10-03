"""The month view's Celsius archive, shared by both colorings and all months."""

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
        ZoneInfo(data["timezone"])
        hourly = data["hourly"]
        if not hourly.get("time") or len(hourly["time"]) != len(hourly["temperature_2m"]):
            raise ValueError("hourly archive is empty or incomplete")
        return dict(data, _requested_end=last.isoformat())

    return fetch_json_cached(
        path, age, url, timeout=30, provider="weather/hourly",
        fresh=lambda data: data.get("_requested_end") == last.isoformat(),
        fetch=lambda url, timeout: _fetch_archive(url, timeout, stale=stale),
        transform=validate)


def fetch_month(lat, lng, today, *, stale=None):
    """Return the indexed temperatures and whether both requests succeeded.

    Missing spans leave their cells blank. No forecast hours are mixed into
    the archive or the comparison. Current-year values never enter the mean.
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
    if not payloads:
        return None, False
    try:
        series = Temperatures.build(payloads, span)
        return (series, complete) if series.days else (None, False)
    except (KeyError, TypeError, ValueError) as exc:
        log_failure("weather/hourly", "index archive", exc, fallback="empty month")
        return None, False
