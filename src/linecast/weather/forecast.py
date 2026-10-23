"""The forecast: Open-Meteo's hourly and daily series, and the clock
they are read by."""

from datetime import date, datetime, timedelta, timezone
from typing import Any

from linecast._cache import location_cache_key
from linecast._http import fetch_json_cached
from linecast._log import log_failure
from linecast._paths import cache_dir
from linecast._runtime import WeatherRuntime, current_runtime

# Whose forecast it is, for the credit line.
FORECAST_SOURCE = "Open-Meteo"


def local_now(data):
    """Current local time in the forecast's timezone (as naive local datetime)."""
    tz_name = data.get("timezone", "")
    if tz_name:
        try:
            from zoneinfo import ZoneInfo
            return datetime.now(ZoneInfo(tz_name)).replace(tzinfo=None)
        except Exception as exc:
            log_failure("tz", f"lookup of {tz_name}", exc, fallback="utc_offset_seconds used")
    try:
        offset_sec = int(data.get("utc_offset_seconds", 0))
        return (datetime.now(timezone.utc) + timedelta(seconds=offset_sec)).replace(tzinfo=None)
    except Exception:
        return datetime.now()


def _at(values, i, default=None):
    """values[i], or `default` when the series is missing or has no
    entry i: a series can be absent, or shorter than the times."""
    return values[i] if values is not None and 0 <= i < len(values) else default


def forecast_date(data) -> "date | None":
    """The day a forecast calls today: with past_days=1 the daily series
    starts yesterday, so index 1 is the day it was fetched.  None when
    the payload has no such series."""
    try:
        return date.fromisoformat(data["daily"]["time"][1])
    except (KeyError, IndexError, TypeError, ValueError):
        return None


def forecast_is_todays(data) -> bool:
    """Whether a forecast's today is today where it is for.

    The cache test for fetch_forecast: a copy fetched on an earlier day
    is stale however young its file, and at midnight the day it calls
    today has gone by.  Either way the next run asks Open-Meteo again
    rather than labelling the wrong day "Today" (issue #68).
    """
    made = forecast_date(data)
    return made is not None and made == local_now(data).date()


def wall_clock(data):
    """The forecast's timestamps as the clock on the wall reads them.

    Open-Meteo stamps a whole response with the zone's UTC offset at the
    moment of the request, so a forecast that spans a clock change
    labels every hour after it in the offset of the day it was fetched:
    an hour late once the clocks have gone back, an hour early once they
    have gone forward, and the sunrise and sunset beside them the same.
    Read back through the zone, the day of the change has 23 or 25
    hours and every label agrees with the wall clock (issue #110).  The
    series is left as it came without a zone, or with one the machine
    does not know, when local_now reads by the same offset.
    """
    tz_name = (data or {}).get("timezone")
    if not tz_name:
        return data
    try:
        from zoneinfo import ZoneInfo
        zone = ZoneInfo(tz_name)
        offset = timedelta(seconds=int(data.get("utc_offset_seconds", 0)))
    except Exception as exc:
        log_failure("tz", f"lookup of {tz_name}", exc, fallback="timestamps left as stamped")
        return data

    def local(text):
        try:
            stamped = datetime.fromisoformat(text)
        except (TypeError, ValueError):
            return text
        if stamped.tzinfo is not None:
            return text
        wall = ((stamped - offset).replace(tzinfo=timezone.utc)
                .astimezone(zone).replace(tzinfo=None))
        return text if wall == stamped else wall.isoformat(timespec="minutes")

    for block, keys in (("hourly", ("time",)), ("daily", ("sunrise", "sunset"))):
        series = data.get(block)
        if not isinstance(series, dict):
            continue
        for key in keys:
            values = series.get(key)
            if isinstance(values, list):
                series[key] = [local(v) for v in values]
    current = data.get("current")
    if isinstance(current, dict) and current.get("time"):
        current["time"] = local(current["time"])
    return data


def _zone(data):
    """The forecast's zone, or the fixed offset it was stamped in where
    the machine does not know the zone, as local_now reads it."""
    tz_name = (data or {}).get("timezone")
    if tz_name:
        try:
            from zoneinfo import ZoneInfo
            return ZoneInfo(tz_name)
        except Exception:
            pass
    try:
        return timezone(timedelta(seconds=int(data.get("utc_offset_seconds", 0))))
    except (TypeError, ValueError):
        return timezone.utc


def with_app_sun(data, lat, lng):
    """*data* with each day's sunrise and sunset the app's own, from
    astro.ephemeris.sunrise_sunset, as the sunshine view and the month
    views give them, rather than Open-Meteo's, a minute or so off.

    They are written into the daily block as Open-Meteo writes its
    own, the wall clock's minute and no zone, so everything that reads
    the forecast reads them: the chart, its Today row, the narrative
    and --json. A day the Sun does not rise has neither, and a day it
    does not set runs from its midnight to the next.
    """
    daily = (data or {}).get("daily")
    if not isinstance(daily, dict) or not isinstance(daily.get("time"), list):
        return data
    from linecast.astro.ephemeris import sunrise_sunset
    from linecast._timefmt import iso_minutes
    zone = _zone(data)
    rises, sets = [], []
    for text in daily["time"]:
        try:
            rise, sset = sunrise_sunset(date.fromisoformat(text), lat, lng, zone)
        except (TypeError, ValueError):
            rise = sset = None
        rises.append(iso_minutes(rise))
        sets.append(iso_minutes(sset))
    daily["sunrise"], daily["sunset"] = rises, sets
    return data


def sun_of_day(daily, i):
    """Day *i*'s (sunrise, sunset), or (None, None) for a day the Sun
    does not rise. A day it does not set runs from midnight to
    midnight, which is the daylight it has, and stands.

    A forecast straight from Open-Meteo, as the tests' fixtures are,
    gives a day without a sunrise a sunrise and a sunset both at its
    midnight. Neither is an event: read as one, the chart marks a sunset
    at 00:00 every day of a polar night, and once wall_clock has moved
    the pair across a clock change, at 23:00 the evening before."""
    rise = _at((daily or {}).get("sunrise"), i)
    sset = _at((daily or {}).get("sunset"), i)
    if rise and rise == sset:
        return None, None
    return rise, sset


def fetch_forecast(lat: float, lng: float,
                   runtime: WeatherRuntime | None = None) -> dict[str, Any] | None:
    """Fetch hourly + daily forecast from Open-Meteo. Cached 1h, and
    only while it still says today is today. Its days carry the app's
    sunrise and sunset (with_app_sun), not Open-Meteo's."""
    if runtime is None:
        runtime = current_runtime(WeatherRuntime)
    # Each unit changes the numbers in the answer, so the file is named
    # for all three, from the same values the request sends.
    temp_unit = "celsius" if runtime.celsius else "fahrenheit"
    wind_unit = runtime.wind_unit_param
    precip_unit = "mm" if runtime.metric else "inch"
    cache_file = cache_dir(
        "weather", f"forecast_{location_cache_key(lat, lng)}"
                   f"_{temp_unit[0].upper()}_{wind_unit}_{precip_unit}.json")
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lng}"
        "&hourly=temperature_2m,apparent_temperature,precipitation,precipitation_probability,"
        "snowfall,wind_speed_10m,wind_gusts_10m,wind_direction_10m,weather_code,"
        "relative_humidity_2m,dew_point_2m,uv_index,cloud_cover"
        "&daily=temperature_2m_max,temperature_2m_min,precipitation_sum,snowfall_sum,"
        "precipitation_probability_max,weather_code,wind_speed_10m_max,wind_gusts_10m_max,"
        "cloud_cover_mean"
        f"&temperature_unit={temp_unit}"
        f"&wind_speed_unit={wind_unit}"
        f"&precipitation_unit={precip_unit}"
        "&timezone=auto&forecast_days=7&past_days=1"
        "&current=temperature_2m,apparent_temperature,weather_code,"
        "wind_speed_10m,wind_gusts_10m,relative_humidity_2m,dew_point_2m,cloud_cover,cloud_cover_high"
    )
    return with_app_sun(wall_clock(fetch_json_cached(
        cache_file,
        3600,
        url,
        timeout=10,
        fallback=None,
        fresh=forecast_is_todays,
    )), lat, lng)
