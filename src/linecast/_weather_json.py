"""Machine-readable JSON payload for `weather --json`.

Builds a plain-dict snapshot of the fetched weather data for external
consumers (e.g. a desktop widget). Values are passed through in the units
already baked into the fetch (per WeatherRuntime); missing values become
None rather than raising.
"""

from dataclasses import asdict
from datetime import datetime

from linecast._weather_i18n import _wmo_icons, wmo_label
from linecast._weather_sections import comparative_sentence
from linecast._weather_sources import FORECAST_SOURCE, _local_now_for_data, alert_source

SCHEMA_VERSION = 1


def _at(seq, i):
    """seq[i] or None when the list is missing or too short."""
    if not seq or i < 0 or i >= len(seq):
        return None
    return seq[i]


def _condition_name(code, runtime):
    if code is None:
        return None
    return wmo_label(code, runtime.lang, default=None)


def _icon(code, runtime):
    if code is None:
        return None
    icons = _wmo_icons(runtime)
    return icons.get(code, icons[0])


def _now_hour_index(times, now):
    """First dt >= floor(now), or len(times) when the forecast has expired."""
    if not times:
        return 0
    floor = now.replace(minute=0, second=0, microsecond=0)
    for i, t in enumerate(times):
        try:
            if datetime.fromisoformat(t) >= floor:
                return i
        except (TypeError, ValueError):
            continue
    return len(times)


def build_payload(data, location_name, country_code, runtime,
                  alerts=None, aqi_data=None, historical=None, now=None):
    """Build the `weather --json` payload dict from preloaded data."""
    data = data or {}
    if now is None:
        now = _local_now_for_data(data)

    current = data.get("current") or {}
    cur_code = current.get("weather_code")
    hourly = data.get("hourly") or {}
    daily = data.get("daily") or {}

    # Hourly: everything from the current hour to the end of the forecast
    # (consumers window/scroll as they like). Arrays start at midnight
    # yesterday (past_days=1), so locate "now" first.
    h_times = hourly.get("time") or []
    start = _now_hour_index(h_times, now)
    hourly_out = []
    for i in range(start, len(h_times)):
        code = _at(hourly.get("weather_code"), i)
        hourly_out.append({
            "time": _at(h_times, i),
            "temperature": _at(hourly.get("temperature_2m"), i),
            "feels_like": _at(hourly.get("apparent_temperature"), i),
            "precipitation_probability": _at(hourly.get("precipitation_probability"), i),
            "precipitation": _at(hourly.get("precipitation"), i),
            "weather_code": code,
            "icon": _icon(code, runtime),
            "condition": _condition_name(code, runtime),
            "wind_speed": _at(hourly.get("wind_speed_10m"), i),
            "wind_direction": _at(hourly.get("wind_direction_10m"), i),
            "uv_index": _at(hourly.get("uv_index"), i),
            "cloud_cover": _at(hourly.get("cloud_cover"), i),
        })

    # A stale cache still carries useful predictions, but its index 1
    # is the fetch date, not necessarily today.
    d_times = daily.get("time") or []
    today = now.date().isoformat()
    start = next((i for i, day in enumerate(d_times) if day >= today), len(d_times))
    today_index = start if _at(d_times, start) == today else -1
    daily_out = []
    for i in range(start, min(start + 7, len(d_times))):
        code = _at(daily.get("weather_code"), i)
        daily_out.append({
            "date": _at(d_times, i),
            "high": _at(daily.get("temperature_2m_max"), i),
            "low": _at(daily.get("temperature_2m_min"), i),
            "precipitation_probability": _at(daily.get("precipitation_probability_max"), i),
            "precipitation": _at(daily.get("precipitation_sum"), i),
            "weather_code": code,
            "icon": _icon(code, runtime),
            "condition": _condition_name(code, runtime),
            "sunrise": _at(daily.get("sunrise"), i),
            "sunset": _at(daily.get("sunset"), i),
            "wind_speed": _at(daily.get("wind_speed_10m_max"), i),
            "wind_gusts": _at(daily.get("wind_gusts_10m_max"), i),
        })

    aqi_out = None
    if aqi_data and isinstance(aqi_data, dict):
        aqi_current = aqi_data.get("current") or {}
        aqi_out = {
            "us_aqi": aqi_current.get("us_aqi"),
            "european_aqi": aqi_current.get("european_aqi"),
            "pm2_5": aqi_current.get("pm2_5"),
            "pm10": aqi_current.get("pm10"),
        }
        india_value = aqi_current.get("india_aqi")
        if india_value is not None:
            from linecast._weather_sources import india_aqi_category
            aqi_out["india_aqi"] = round(india_value)
            aqi_out["india_aqi_category"] = india_aqi_category(india_value)
        aqhi = aqi_current.get("aqhi")
        if aqhi is not None:
            from linecast._weather_sources import aqhi_category
            aqi_out["aqhi"] = aqhi
            aqi_out["aqhi_category"] = aqhi_category(aqhi)
            computed = aqi_current.get("aqhi_source") == "computed"
            aqi_out["aqhi_source"] = FORECAST_SOURCE if computed else alert_source("CA")

    return {
        "schema": SCHEMA_VERSION,
        "location": location_name or "",
        "country_code": country_code or None,
        "timezone": data.get("timezone") or None,
        "fetched_at": current.get("time"),
        "summary": comparative_sentence(daily, now, runtime) or None,
        "units": {
            "temperature": runtime.temp_unit,
            "wind": runtime.wind_unit,
            "precipitation": runtime.precip_unit,
        },
        "current": {
            "time": current.get("time"),
            "temperature": current.get("temperature_2m"),
            "feels_like": current.get("apparent_temperature"),
            "humidity": current.get("relative_humidity_2m"),
            "dew_point": current.get("dew_point_2m"),
            "wind_speed": current.get("wind_speed_10m"),
            "wind_gusts": current.get("wind_gusts_10m"),
            "weather_code": cur_code,
            "condition": _condition_name(cur_code, runtime),
            "icon": _icon(cur_code, runtime),
        },
        "today": {
            "high": _at(daily.get("temperature_2m_max"), today_index),
            "low": _at(daily.get("temperature_2m_min"), today_index),
            "sunrise": _at(daily.get("sunrise"), today_index),
            "sunset": _at(daily.get("sunset"), today_index),
            "precipitation_probability": _at(daily.get("precipitation_probability_max"),
                                             today_index),
            "precipitation": _at(daily.get("precipitation_sum"), today_index),
        },
        "hourly": hourly_out,
        "daily": daily_out,
        "alerts": list(alerts or []),
        "aqi": aqi_out,
        "historical": asdict(historical) if historical is not None else None,
        "sources": {
            "forecast": FORECAST_SOURCE,
            "air_quality": FORECAST_SOURCE,
            "alerts": alert_source(country_code),
        },
    }
