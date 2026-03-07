"""Weather data/source helpers: geocoding, forecast fetches, and alerts."""

import sys
from datetime import datetime, timezone, timedelta

from linecast import USER_AGENT
from linecast._cache import CACHE_ROOT, read_cache, write_cache, location_cache_key
from linecast._http import fetch_json, fetch_json_cached
from linecast._runtime import WeatherRuntime

CACHE_DIR = CACHE_ROOT / "weather"


def _location_from_timezone(tz_str):
    """Extract display name from timezone like 'America/New_York' -> 'New York'."""
    if not tz_str or "/" not in tz_str:
        return ""
    return tz_str.rsplit("/", 1)[-1].replace("_", " ")


def _local_now_for_data(data):
    """Current local time in the forecast's timezone (as naive local datetime)."""
    tz_name = data.get("timezone", "")
    if tz_name:
        try:
            from zoneinfo import ZoneInfo
            return datetime.now(ZoneInfo(tz_name)).replace(tzinfo=None)
        except Exception:
            pass
    try:
        offset_sec = int(data.get("utc_offset_seconds", 0))
        return (datetime.now(timezone.utc) + timedelta(seconds=offset_sec)).replace(tzinfo=None)
    except Exception:
        return datetime.now()


def _reverse_geocode(lat, lng):
    """Reverse geocode coordinates to a display name via Nominatim. Cached.

    Returns (display_name, country_code) tuple.
    """
    cache_file = CACHE_DIR / "location.json"
    cached = read_cache(cache_file, 86400)  # 24h cache
    if cached and cached.get("lat") == round(lat, 4) and cached.get("lng") == round(lng, 4):
        return cached.get("name", ""), cached.get("country_code", "")

    try:
        url = (
            f"https://nominatim.openstreetmap.org/reverse"
            f"?lat={lat}&lon={lng}&format=json&zoom=10"
        )
        data = fetch_json(url, headers={"User-Agent": USER_AGENT}, timeout=10)
        addr = data.get("address", {})
        name = addr.get("city") or addr.get("town") or addr.get("village") or ""
        state = addr.get("state", "")
        country_code = addr.get("country_code", "").upper()
        if name and state:
            display = f"{name}, {state}"
        elif name:
            display = name
        else:
            display = ""
        write_cache(cache_file, {
            "lat": round(lat, 4), "lng": round(lng, 4),
            "name": display, "country_code": country_code,
        })
        return display, country_code
    except Exception:
        return "", ""


def fetch_forecast(lat, lng, runtime=None):
    """Fetch hourly + daily forecast from Open-Meteo. Cached 1h."""
    if runtime is None:
        runtime = WeatherRuntime.from_sources()
    unit_suffix = "_metric" if runtime.metric else ""
    cache_file = CACHE_DIR / f"forecast_{location_cache_key(lat, lng)}{unit_suffix}.json"
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lng}"
        "&hourly=temperature_2m,apparent_temperature,precipitation,precipitation_probability,"
        "snowfall,wind_speed_10m,wind_gusts_10m,wind_direction_10m,weather_code"
        "&daily=temperature_2m_max,temperature_2m_min,precipitation_sum,"
        "precipitation_probability_max,weather_code,wind_speed_10m_max,wind_gusts_10m_max,"
        "sunrise,sunset"
        f"&temperature_unit={'celsius' if runtime.metric else 'fahrenheit'}"
        f"&wind_speed_unit={'kmh' if runtime.metric else 'mph'}"
        f"&precipitation_unit={'mm' if runtime.metric else 'inch'}"
        "&timezone=auto&forecast_days=7&past_days=1"
        "&current=temperature_2m,apparent_temperature,weather_code,"
        "wind_speed_10m,wind_gusts_10m"
    )
    return fetch_json_cached(
        cache_file,
        3600,
        url,
        headers={"User-Agent": USER_AGENT},
        timeout=10,
        fallback=None,
    )


def fetch_alerts(lat, lng, country_code="", lang="en"):
    """Fetch active weather alerts from the appropriate provider.

    Routes to NWS (US), Environment Canada (CA), or returns [] for unsupported regions.
    """
    if country_code == "US":
        return _fetch_alerts_nws(lat, lng)
    if country_code == "CA":
        return _fetch_alerts_eccc(lat, lng, lang=lang)
    return []


def _fetch_alerts_nws(lat, lng):
    """Fetch active NWS alerts (US). Cached 15min."""
    cache_file = CACHE_DIR / f"alerts_{location_cache_key(lat, lng)}.json"
    url = f"https://api.weather.gov/alerts/active?point={lat},{lng}"
    data = fetch_json_cached(
        cache_file,
        900,
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "application/geo+json"},
        timeout=10,
        fallback=[],
    )
    if isinstance(data, list):
        return data

    features = data.get("features", [])
    alerts = []
    for feature in features:
        props = feature.get("properties", {})
        alerts.append({
            "event": props.get("event", ""),
            "headline": props.get("headline", ""),
            "description": props.get("description", ""),
            "effective": props.get("effective", ""),
            "expires": props.get("expires", ""),
            "severity": props.get("severity", ""),
            "url": props.get("web", ""),
        })
    write_cache(cache_file, alerts)
    return alerts


def _fetch_alerts_eccc(lat, lng, lang="en"):
    """Fetch active Environment Canada alerts (CA). Cached 15min.

    Uses the OGC API at api.weather.gc.ca with bbox query.
    """
    cache_file = CACHE_DIR / f"alerts_ca_{location_cache_key(lat, lng)}_{lang}.json"
    # bbox: lng-0.5, lat-0.5, lng+0.5, lat+0.5 (~50km radius)
    bbox = f"{lng - 0.5},{lat - 0.5},{lng + 0.5},{lat + 0.5}"
    url = (
        f"https://api.weather.gc.ca/collections/weather-alerts/items"
        f"?f=json&bbox={bbox}&lang={lang}&limit=20"
    )
    data = fetch_json_cached(
        cache_file,
        900,
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        timeout=10,
        fallback=[],
    )
    if isinstance(data, list):
        return data

    # Use language-appropriate fields, falling back to the other language
    name_key = f"alert_name_{lang}"
    name_fallback = "alert_name_en" if lang != "en" else "alert_name_fr"
    short_name_key = f"alert_short_name_{lang}"
    text_key = f"alert_text_{lang}"
    text_fallback = "alert_text_en" if lang != "en" else "alert_text_fr"

    features = data.get("features", [])
    alerts = []
    seen_events = set()  # deduplicate by event name
    for feature in features:
        props = feature.get("properties", {})
        event = (
            props.get(name_key, "").capitalize()
            or props.get(short_name_key, "")
            or props.get(name_fallback, "").capitalize()
        )
        severity = _eccc_severity(props)
        desc = props.get(text_key) or props.get(text_fallback) or ""
        effective = props.get("validity_datetime") or props.get("publication_datetime") or ""
        expires = props.get("expiration_datetime") or ""

        if not event:
            continue

        # Deduplicate — ECCC returns one feature per affected zone
        dedup_key = (event, severity)
        if dedup_key in seen_events:
            continue
        seen_events.add(dedup_key)

        alerts.append({
            "event": event,
            "headline": event,
            "description": desc,
            "effective": effective,
            "expires": expires,
            "severity": severity,
            "url": "",
        })
    write_cache(cache_file, alerts)
    return alerts


def _eccc_severity(props):
    """Map Environment Canada alert properties to standard severity string."""
    # ECCC uses alert_type: "warning" > "watch" > "advisory" > "statement"
    alert_type = (props.get("alert_type") or "").lower()
    if alert_type == "warning":
        return "Severe"
    if alert_type == "watch":
        return "Moderate"
    if alert_type in ("advisory", "statement", "ending"):
        return "Minor"
    return "Minor"


def _search_locations(query, lang="en"):
    """Search cities using Open-Meteo geocoding API and print results."""
    import urllib.parse

    url = (
        "https://geocoding-api.open-meteo.com/v1/search"
        f"?name={urllib.parse.quote(query)}&count=10&language={lang}"
    )
    try:
        data = fetch_json(url, headers={"User-Agent": USER_AGENT}, timeout=10)
    except Exception as exc:
        print(f"Search failed: {exc}", file=sys.stderr)
        sys.exit(1)

    results = data.get("results", [])
    if not results:
        print(f'No locations matching "{query}".')
        return

    for result in results:
        name = result.get("name", "")
        admin1 = result.get("admin1", "")
        country = result.get("country", "")
        lat = result.get("latitude", 0)
        lng = result.get("longitude", 0)
        label = name
        if admin1:
            label += f", {admin1}"
        if country:
            label += f", {country}"
        print(f"  {lat:.4f},{lng:.4f}  {label}")

    print("\nUsage: weather --location LAT,LNG")
    print("   or: export WEATHER_LOCATION=LAT,LNG")
