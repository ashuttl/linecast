"""Weather data/source helpers: geocoding, forecast fetches, and alerts."""

import re
import sys
from datetime import datetime, timezone, timedelta
from typing import Any

from linecast._cache import read_cache, write_cache, location_cache_key
from linecast._http import fetch_json, fetch_json_cached
from linecast._paths import cache_dir
from linecast._runtime import WeatherRuntime, current_runtime, log_failure


def _local_now_for_data(data):
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


def _country_code(addr):
    """The ISO country code of a Nominatim address, upper-cased.

    Hong Kong and Macau come back as China with the region in the
    ISO 3166-2 field ("CN-HK", "CN-MO"); each has its own weather
    service and tide stations, so they get their own codes, as the
    forward geocoder and the IP lookup already give them.
    """
    region = str(addr.get("ISO3166-2-lvl3", "")).upper()
    if region in ("CN-HK", "CN-MO"):
        return region[3:]
    return str(addr.get("country_code", "")).upper()


def _reverse_geocode(lat, lng, lang=None):
    """Reverse geocode coordinates to a display name via Nominatim. Cached.

    Returns (display_name, country_code, address) tuple. `lang` localizes
    the returned names (Nominatim accept-language); cached per language.
    """
    cache_file = cache_dir("weather") / "location.json"
    cached = read_cache(cache_file, 86400)  # 24h cache
    if (cached and cached.get("lat") == round(lat, 4)
            and cached.get("lng") == round(lng, 4)
            and cached.get("lang", None) == lang):
        return cached.get("name", ""), cached.get("country_code", ""), cached.get("address", {})

    try:
        url = (
            f"https://nominatim.openstreetmap.org/reverse"
            f"?lat={lat}&lon={lng}&format=json&zoom=10"
        )
        if lang:
            url += f"&accept-language={lang}"
        data = fetch_json(url, timeout=10)
        addr = data.get("address", {})
        # Nominatim files small places under keys all the way down to
        # hamlet (Fayette, Maine is one); without them the name comes back
        # empty and the caller falls back to the timezone city (issue #50).
        name = (addr.get("city") or addr.get("town") or addr.get("village")
                or addr.get("hamlet") or addr.get("municipality") or "")
        state = addr.get("state", "")
        country_code = _country_code(addr)
        if name and state:
            display = f"{name}, {state}"
        elif name:
            display = name
        else:
            display = ""
    except Exception as exc:
        log_failure("location/geocoder", "reverse geocode", exc,
                    url="nominatim.openstreetmap.org", fallback="unnamed location")
        return "", "", {}

    # the answer is in hand; keeping it is a separate, best-effort matter
    write_cache(cache_file, {
        "lat": round(lat, 4), "lng": round(lng, 4), "lang": lang,
        "name": display, "country_code": country_code,
        "address": addr,
    })
    return display, country_code, addr


def fetch_forecast(lat: float, lng: float,
                   runtime: WeatherRuntime | None = None) -> dict[str, Any] | None:
    """Fetch hourly + daily forecast from Open-Meteo. Cached 1h."""
    if runtime is None:
        runtime = current_runtime(WeatherRuntime)
    temp_tag = "C" if runtime.celsius else "F"
    wind_tag = "m" if runtime.metric else "i"
    cache_file = cache_dir(
        "weather", f"forecast_{location_cache_key(lat, lng)}_{temp_tag}{wind_tag}.json")
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lng}"
        "&hourly=temperature_2m,apparent_temperature,precipitation,precipitation_probability,"
        "snowfall,wind_speed_10m,wind_gusts_10m,wind_direction_10m,weather_code,"
        "relative_humidity_2m,dew_point_2m,uv_index"
        "&daily=temperature_2m_max,temperature_2m_min,precipitation_sum,"
        "precipitation_probability_max,weather_code,wind_speed_10m_max,wind_gusts_10m_max,"
        "sunrise,sunset"
        f"&temperature_unit={'celsius' if runtime.celsius else 'fahrenheit'}"
        f"&wind_speed_unit={'kmh' if runtime.metric else 'mph'}"
        f"&precipitation_unit={'mm' if runtime.metric else 'inch'}"
        "&timezone=auto&forecast_days=7&past_days=1"
        "&current=temperature_2m,apparent_temperature,weather_code,"
        "wind_speed_10m,wind_gusts_10m,relative_humidity_2m,dew_point_2m"
    )
    return fetch_json_cached(
        cache_file,
        3600,
        url,
        timeout=10,
        fallback=None,
    )


def fetch_aqi(lat: float, lng: float) -> dict[str, Any] | None:
    """Fetch current AQI from Open-Meteo Air Quality API. Cached 1h.

    The hourly pollutant series covers the past day so the Indian AQI,
    which is defined over running averages, can be computed on-device
    (india_aqi below).
    """
    cache_file = cache_dir("weather") / f"aqi_{location_cache_key(lat, lng)}.json"
    url = (
        "https://air-quality-api.open-meteo.com/v1/air-quality"
        f"?latitude={lat}&longitude={lng}"
        "&current=us_aqi,european_aqi,pm2_5,pm10"
        "&hourly=pm2_5,pm10,nitrogen_dioxide,sulphur_dioxide,"
        "carbon_monoxide,ozone"
        "&past_days=1&forecast_days=1"
    )
    return fetch_json_cached(
        cache_file,
        3600,
        url,
        timeout=10,
        fallback=None,
    )


# CPCB National AQI (India, 2014): each pollutant maps onto the shared
# index bands through its own concentration breakpoints, and the AQI is
# the worst sub-index. Concentrations in µg/m³ (Open-Meteo's unit; the
# CPCB states CO in mg/m³, converted here). The top band is open-ended
# ("250+" for PM2.5); its ceiling below continues the slope of the band
# before it, and the index is capped at 500 either way.
_INDIA_AQI_INDEX = (0, 50, 100, 200, 300, 400, 500)
_INDIA_AQI_BREAKPOINTS = {
    "pm2_5": (0, 30, 60, 90, 120, 250, 380),
    "pm10": (0, 50, 100, 250, 350, 430, 510),
    "nitrogen_dioxide": (0, 40, 80, 180, 280, 400, 520),
    "sulphur_dioxide": (0, 40, 80, 380, 800, 1600, 2400),
    "ozone": (0, 50, 100, 168, 208, 748, 1288),
    "carbon_monoxide": (0, 1000, 2000, 10000, 17000, 34000, 51000),
}

# Averaging windows, in hours: 24 for the particulates and gases, 8 for
# CO and ozone, per the CPCB's definition.
_INDIA_AQI_WINDOWS = {
    "pm2_5": 24, "pm10": 24, "nitrogen_dioxide": 24, "sulphur_dioxide": 24,
    "ozone": 8, "carbon_monoxide": 8,
}


def _india_sub_index(pollutant, concentration):
    """One pollutant's CPCB sub-index, linear within its band."""
    breakpoints = _INDIA_AQI_BREAKPOINTS[pollutant]
    if concentration >= breakpoints[-1]:
        return 500.0
    for band in range(1, len(breakpoints)):
        if concentration <= breakpoints[band]:
            c_lo, c_hi = breakpoints[band - 1], breakpoints[band]
            i_lo, i_hi = _INDIA_AQI_INDEX[band - 1], _INDIA_AQI_INDEX[band]
            return i_lo + (i_hi - i_lo) * (concentration - c_lo) / (c_hi - c_lo)
    return 500.0


def india_aqi(aqi_data):
    """The CPCB National AQI from an Open-Meteo air quality response.

    Averages each pollutant's hourly series over its window, ending at
    the current hour, and takes the worst sub-index. Following the CPCB,
    no index is reported without particulate data, and a window more
    than half empty is not averaged.

    Returns None when the response has no hourly series (an older cached
    response) or too little data; the caller falls back to the US AQI.
    """
    if not isinstance(aqi_data, dict):
        return None
    hourly = aqi_data.get("hourly") or {}
    times = hourly.get("time") or []
    now = (aqi_data.get("current") or {}).get("time")
    try:
        end = times.index(now) + 1
    except ValueError:
        return None

    worst = None
    has_pm = False
    for pollutant, window in _INDIA_AQI_WINDOWS.items():
        series = hourly.get(pollutant) or []
        values = [v for v in series[max(0, end - window):end] if v is not None]
        if len(values) < window // 2 + 1:
            continue
        sub = _india_sub_index(pollutant, sum(values) / len(values))
        if pollutant in ("pm2_5", "pm10"):
            has_pm = True
        if worst is None or sub > worst:
            worst = sub
    if worst is None or not has_pm:
        return None
    return worst


def india_aqi_category(value):
    """The CPCB's name for an index value, as its bulletins print it."""
    for ceiling, name in ((50, "Good"), (100, "Satisfactory"),
                          (200, "Moderate"), (300, "Poor"),
                          (400, "Very Poor")):
        if value <= ceiling:
            return name
    return "Severe"


def apply_india_aqi(aqi_data, country_code):
    """Attach the CPCB index to an air quality response for India.

    render_header and the JSON payload show it in place of the US AQI
    when present; elsewhere the response passes through untouched.
    """
    if country_code != "IN" or not isinstance(aqi_data, dict):
        return
    value = india_aqi(aqi_data)
    if value is not None:
        aqi_data.setdefault("current", {})["india_aqi"] = value


# Alerts past this many are cut, gravest first. Enough for a bad day on
# one point -- a hurricane's watch, warning, surge, and flood advisories
# fit -- and few enough that a feed gone wrong stays a band, not a wall.
MAX_ALERTS = 8

_SEVERITY_RANK = {"Extreme": 0, "Severe": 1, "Moderate": 2, "Minor": 3}


def fetch_alerts(lat: float, lng: float, country_code: str = "", lang: str = "en",
                 address: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Fetch active weather alerts from the appropriate provider.

    Routes to the best available source for each country, then keeps
    the board readable: the gravest alerts first, and no more than
    MAX_ALERTS of them. A feed that files one warning per county can
    land hundreds on a single point (issue #57); past a handful, the
    pills stop informing and start papering the screen.
    """
    alerts = _fetch_alerts_routed(lat, lng, country_code, lang, address)
    return _trim_alerts(alerts)


def _trim_alerts(alerts):
    """The gravest alerts first, at most MAX_ALERTS of them.

    The sort is stable, so a provider's own order holds within a
    severity; an unknown severity sorts last.
    """
    ranked = sorted(alerts, key=lambda a: _SEVERITY_RANK.get(a.get("severity"), 9))
    return ranked[:MAX_ALERTS]


def _fetch_alerts_routed(lat, lng, country_code, lang, address):
    if country_code == "US":
        return _fetch_alerts_nws(lat, lng)
    if country_code == "CA":
        return _fetch_alerts_eccc(lat, lng, lang=lang)
    if country_code == "DE":
        return _fetch_alerts_brightsky(lat, lng, lang=lang)
    if country_code == "NO":
        return _fetch_alerts_metno(lat, lng)
    if country_code == "IE":
        return _fetch_alerts_meteireann(lat, lng)
    if country_code == "JP":
        return _fetch_alerts_jma(lat, lng, lang=lang)
    if country_code == "HK":
        return _fetch_alerts_hko()
    if country_code == "CN":
        return _fetch_alerts_cma(lat, lng, lang=lang)
    if country_code == "IN":
        return _fetch_alerts_sachet(lat, lng, lang=lang)
    if country_code == "NZ":
        return _fetch_alerts_metservice(lat, lng)
    slug = _METEOALARM_SLUGS.get(country_code)
    if slug:
        return _fetch_alerts_meteoalarm(lat, lng, slug, lang=lang, address=address)
    return []


def _fetch_alerts_nws(lat, lng):
    """Fetch active NWS alerts (US). Cached 15min."""
    cache_file = cache_dir("weather") / f"alerts_{location_cache_key(lat, lng)}.json"
    url = f"https://api.weather.gov/alerts/active?point={lat},{lng}"
    data = fetch_json_cached(
        cache_file,
        900,
        url,
        headers={"Accept": "application/geo+json"},
        timeout=10,
        fallback=[],
    )
    if isinstance(data, list):
        return data

    features = data.get("features", [])
    alerts = []
    for feature in features:
        props = feature.get("properties", {})
        if props.get("status") != "Actual":
            continue
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
    cache_file = cache_dir("weather") / f"alerts_ca_{location_cache_key(lat, lng)}_{lang}.json"
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
        headers={"Accept": "application/json"},
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
        expires = props.get("event_end_datetime") or props.get("expiration_datetime") or ""

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


def _fetch_alerts_brightsky(lat, lng, lang="en"):
    """Fetch DWD alerts via Bright Sky API (Germany). Cached 15min."""
    cache_file = cache_dir("weather") / f"alerts_de_{location_cache_key(lat, lng)}_{lang}.json"
    url = f"https://api.brightsky.dev/alerts?lat={lat}&lon={lng}"
    data = fetch_json_cached(
        cache_file, 900, url,
        timeout=10, fallback=[],
    )
    if isinstance(data, list):
        return data

    # Prefer user's language, fall back to English, then German
    prefer_de = lang == "de"
    alerts = []
    for a in data.get("alerts", []):
        severity = (a.get("severity") or "").capitalize()
        if prefer_de:
            event = a.get("event_de") or a.get("event_en") or ""
            headline = a.get("headline_de") or a.get("headline_en") or ""
            description = a.get("description_de") or a.get("description_en") or ""
        else:
            event = a.get("event_en") or a.get("event_de") or ""
            headline = a.get("headline_en") or a.get("headline_de") or ""
            description = a.get("description_en") or a.get("description_de") or ""
        alerts.append({
            "event": event.capitalize() if event else "",
            "headline": headline,
            "description": description,
            "effective": a.get("effective", ""),
            "expires": a.get("expires", ""),
            "severity": severity,
            "url": "",
        })
    write_cache(cache_file, alerts)
    return alerts


def _fetch_alerts_metno(lat, lng):
    """Fetch MetAlerts from MET Norway. Cached 15min.

    Uses api.met.no with lat/lon coordinate filtering.
    """
    cache_file = cache_dir("weather") / f"alerts_no_{location_cache_key(lat, lng)}.json"
    url = (
        f"https://api.met.no/weatherapi/metalerts/2.0/current.json"
        f"?lat={lat}&lon={lng}"
    )
    data = fetch_json_cached(
        cache_file, 900, url,
        timeout=10, fallback=[],
    )
    if isinstance(data, list):
        return data

    alerts = []
    seen = set()
    for feature in data.get("features", []):
        props = feature.get("properties", {})
        event = (props.get("event") or "").capitalize()
        severity = props.get("severity", "")
        if not event:
            continue
        dedup_key = (event, severity)
        if dedup_key in seen:
            continue
        seen.add(dedup_key)
        when = feature.get("when", {}).get("interval", ["", ""])
        effective = when[0] if len(when) > 0 else ""
        expires = when[1] if len(when) > 1 else ""
        web = (props.get("web") or "").strip()
        alerts.append({
            "event": event,
            "headline": (props.get("title") or "").strip(),
            "description": props.get("description") or props.get("instruction") or "",
            "effective": effective,
            "expires": expires,
            "severity": severity,
            "url": web,
        })
    write_cache(cache_file, alerts)
    return alerts


def _fetch_alerts_meteireann(lat, lng):
    """Fetch active warnings from Met Éireann (Ireland). Cached 15min."""

    cache_file = cache_dir("weather") / f"alerts_ie_{location_cache_key(lat, lng)}.json"
    url = "https://prodapi.metweb.ie/warnings/active"
    data = fetch_json_cached(
        cache_file, 900, url,
        headers={"Accept": "application/json"},
        timeout=10, fallback=[],
    )
    if isinstance(data, list):
        return data

    warnings_data = data.get("warnings", {})
    alerts = []
    seen = set()
    for category in ("national", "marine", "environmental"):
        for w in warnings_data.get(category, []):
            headline = w.get("headline") or ""
            if not headline:
                continue
            desc = w.get("description") or w.get("text") or ""
            if desc.lower() in ("nil", ""):
                desc = ""
            level = (w.get("level") or "").lower()
            severity = _meteireann_severity(level)

            dedup_key = (headline, severity)
            if dedup_key in seen:
                continue
            seen.add(dedup_key)

            effective = _parse_meteireann_dt(w.get("validFrom") or w.get("issuedAt") or "")
            expires = _parse_meteireann_dt(w.get("validUntil") or "")
            alerts.append({
                "event": headline,
                "headline": headline,
                "description": desc,
                "effective": effective,
                "expires": expires,
                "severity": severity,
                "url": "",
            })
    write_cache(cache_file, alerts)
    return alerts


def _meteireann_severity(level):
    """Map Met Éireann colour levels to standard severity."""
    if level == "red":
        return "Extreme"
    if level == "orange":
        return "Severe"
    if level == "yellow":
        return "Moderate"
    return "Minor"


def _parse_meteireann_dt(s):
    """Parse Met Éireann datetime to ISO format.

    Input: "HH:MM Weekday DD/MM/YYYY" -> "YYYY-MM-DDTHH:MM:00"
    """
    import re
    if not s:
        return ""
    m = re.match(r"(\d{2}):(\d{2})\s+\w+\s+(\d{2})/(\d{2})/(\d{4})", s)
    if m:
        hour, minute, day, month, year = m.groups()
        return f"{year}-{month}-{day}T{hour}:{minute}:00"
    return ""


# ---------------------------------------------------------------------------
# MeteoAlarm (pan-European, 32 countries)
# ---------------------------------------------------------------------------

# ISO 3166-1 alpha-2 -> MeteoAlarm feed slug
# DE, NO, IE excluded — they have dedicated providers above
_METEOALARM_SLUGS = {
    "AT": "austria", "BE": "belgium", "BA": "bosnia-herzegovina",
    "BG": "bulgaria", "HR": "croatia",
    "CY": "cyprus", "CZ": "czechia", "DK": "denmark", "EE": "estonia",
    "FI": "finland", "FR": "france", "GR": "greece",
    "HU": "hungary", "IS": "iceland", "IL": "israel", "IT": "italy",
    "LV": "latvia", "LT": "lithuania", "LU": "luxembourg", "MT": "malta",
    "MD": "moldova", "ME": "montenegro",
    "NL": "netherlands", "MK": "republic-of-north-macedonia",
    "PL": "poland", "PT": "portugal",
    "RO": "romania", "RS": "serbia", "SK": "slovakia", "SI": "slovenia",
    "ES": "spain", "SE": "sweden", "CH": "switzerland",
    "UA": "ukraine", "GB": "united-kingdom",
}


def _fetch_alerts_meteoalarm(lat, lng, slug, lang="en", address=None):
    """Fetch MeteoAlarm warnings for a European country. Cached 15min.

    Filters by severity and area match against the user's Nominatim address.
    Prefers the user's language for alert text, falling back to English.
    """
    cache_file = cache_dir(
        "weather", f"alerts_eu_{slug}_{location_cache_key(lat, lng)}_{lang}.json")
    url = f"https://feeds.meteoalarm.org/api/v1/warnings/feeds-{slug}"
    data = fetch_json_cached(
        cache_file, 900, url,
        headers={"Accept": "application/json"},
        timeout=15, fallback=[],
    )
    if isinstance(data, list):
        return data

    warnings = data.get("warnings", [])
    per_warning_descs = [
        [area.get("areaDesc", "")
         for info in w.get("alert", {}).get("info", [])
         for area in info.get("area", [])]
        for w in warnings
    ]
    location_words = _drop_feed_wide_words(
        _extract_location_words(address), per_warning_descs)
    here = _regions_here(lat, lng, warnings)
    alerts = []
    seen = {}
    national = []
    national_seen = set()
    for w in warnings:
        alert_obj = w.get("alert", {})
        infos = alert_obj.get("info", [])
        # Prefer user's language, fall back to English, then first available
        preferred_info = None
        en_info = None
        other_info = None
        area_descs = []
        areas = []
        for info in infos:
            info_lang = info.get("language", "")
            if info_lang.startswith(lang):
                preferred_info = info
            elif info_lang.startswith("en"):
                en_info = info
            elif other_info is None:
                other_info = info
            for area in info.get("area", []):
                area_descs.append(area.get("areaDesc", ""))
                areas.append(area)
        info = preferred_info or en_info or other_info
        if not info:
            continue
        codes = _region_keys(areas)

        severity = info.get("severity", "")
        if severity == "Minor":
            continue

        event = info.get("event") or ""
        if not event:
            continue
        # MeteoAlarm providers (e.g. DMI) often prefix the event name with
        # the English color level ("yellow Tåge", "orange Regn").  Strip it
        # since we already convey severity via the pill background colour.
        event = re.sub(r"^(?:yellow|orange|red|green)\s+", "", event, flags=re.IGNORECASE)

        # The feed is the whole country's, so every alert has to earn its
        # place. A CAP polygon settles it outright: it is the warning's
        # own account of the ground it covers, and it tells a gauge on one
        # brook apart from a red warning for half the country, which no
        # reading of an areaDesc can. Where the feed carries geometry,
        # nothing else is consulted -- not even severity, since being
        # outside an Extreme warning's polygon means being outside it.
        rings = [ring for area in areas for ring in _cap_polygons(area)]
        if rings:
            matched = any(_point_in_ring(lat, lng, ring) for ring in rings)
            geometric = True
        elif codes and here:
            # No polygon, but a geocode: an EMMA_ID, NUTS, or CISORP code
            # names a region whose ground we carry, so it is as
            # good as a polygon. Only where the point is in some region
            # of the data, though; off the coast, or in a country the
            # data lacks, the codes prove nothing and the areaDesc must do.
            matched = bool(codes & here)
            geometric = True
        else:
            geometric = False
            # No geometry: fall back to reading the areaDesc against the
            # user's address. Extreme is exempt -- at that level the
            # country should hear about it wherever it is -- and so is a
            # user we hold no address for, there being nothing to match.
            if severity == "Extreme" or not location_words:
                matched = True
            else:
                matched = any(_area_matches(ad, location_words)
                              for ad in area_descs)

        alert = {
            "event": event,
            "headline": info.get("headline") or event,
            "description": info.get("description") or "",
            "effective": info.get("effective") or info.get("onset") or "",
            "expires": info.get("expires") or "",
            "severity": severity,
            "url": info.get("web") or "",
        }

        if not matched:
            if geometric:
                continue  # the warning says where it applies; believe it
            # Read off an areaDesc, "no match" is a weaker finding. A
            # Severe warning for one river gauge 500km away is noise, but
            # a red warning for the whole country carries an areaDesc
            # that matches nobody's address either, and dropping that
            # would be the worse mistake. Hold the unmatched Severe ones
            # back and show them only if nothing local turned up: a
            # national warning still lands on an empty board, and a single
            # brook no longer outranks the local picture.
            key = (event, severity)
            if severity == "Severe" and key not in national_seen:
                national_seen.add(key)
                national.append(alert)
            continue

        # The text, not the ground, tells one warning from another.
        # Poland's service files a storm as one warning per county, word
        # for word the same across a province, and every county in the
        # province matched a Masovian address: 28 pills for one storm
        # (issue #57). Two warnings that read the same are one warning
        # to the reader. Where there is no text, the ground covered is
        # all that tells them apart, and it stays in the key: on
        # (event, severity) alone a country in flood collapses to one
        # arbitrary river's warning.
        dedup_key = (event, severity,
                     alert["description"] or " | ".join(area_descs))
        # Of the copies, keep the one whose ground reads most like the
        # user's address, so the headline names their own county.
        score = sum(1 for word in location_words
                    if any(word in ad.lower() for ad in area_descs))
        held = seen.get(dedup_key)
        if held is not None:
            if score > held[0]:
                alerts[held[1]] = alert
                seen[dedup_key] = (score, held[1])
            continue
        seen[dedup_key] = (score, len(alerts))
        alerts.append(alert)

    if not alerts:
        alerts = national
    write_cache(cache_file, alerts)
    return alerts


# Words that name an administrative tier rather than a place. Nominatim
# gives Edinburgh a county of "City of Edinburgh" and the Rhône one of
# "Auvergne-Rhône-Alpes Region"; left in, "city" and "region" match a good
# part of Europe's areaDescs and the filter stops filtering.
#
# Addresses come back in the country's own language, and so do the
# areaDescs, so every MeteoAlarm country's tier words belong here too.
# Warsaw's address is "Warszawa, województwo mazowieckie", and every
# Polish areaDesc begins "województwo ..."; that one word matched the
# whole country's warnings, 419 of them (issue #57).
_GENERIC_PLACE_WORDS = frozenset({
    # English, and the English names Nominatim gives foreign tiers
    "administrative", "area", "autonomous", "borough", "canton", "city",
    "community", "council", "county", "department", "district",
    "division", "metropolitan", "municipality", "oblast", "okrug",
    "prefecture", "province", "raion", "region", "regional", "state",
    "territory", "unitary", "voivodeship",
    # Polish
    "województwo", "powiat", "gmina", "miasto",
    # Czech, Slovak
    "kraj", "okres", "obec", "hlavní", "město", "mesto",
    # Hungarian
    "megye", "vármegye", "járás", "város", "kerület",
    # Romanian, Moldovan
    "județul", "județ", "municipiul", "comuna", "sectorul", "raionul",
    # Bulgarian, Serbian, Macedonian, Montenegrin
    "област", "община", "општина", "округ", "град", "opština", "grad",
    # Croatian, Slovenian, Bosnian
    "županija", "općina", "občina", "mestna", "kanton",
    # German (Austria, Switzerland, Luxembourg)
    "bezirk", "landkreis", "kreis", "gemeinde", "stadt", "regierungsbezirk",
    # Dutch, Flemish
    "provincie", "gemeente", "arrondissement", "gewest", "stad",
    # French (France, Belgium, Switzerland, Luxembourg)
    "département", "région", "commune", "métropole", "communauté", "ville",
    # Spanish, Catalan, Galician, Basque
    "provincia", "comunidad", "autónoma", "municipio", "comarca",
    "comunitat", "província", "autònoma", "concello", "probintzia",
    # Portuguese
    "distrito", "concelho", "freguesia", "município", "região",
    # Italian
    "regione", "comune", "città", "metropolitana",
    # Greek, Cypriot
    "περιφέρεια", "περιφερειακή", "ενότητα", "δήμος", "νομός", "επαρχία",
    # Danish, Swedish, Finnish, Icelandic
    "kommune", "län", "kommun", "maakunta", "kunta", "seutukunta",
    "sveitarfélag", "sýsla",
    # Estonian, Latvian, Lithuanian
    "maakond", "vald", "linn", "novads", "pagasts", "pilsēta",
    "apskritis", "rajonas", "savivaldybė", "miestas", "seniūnija",
    # Maltese, Irish, Hebrew
    "reġjun", "kunsill", "lokali", "contae", "מחוז", "נפת", "נפה",
})

# A word the feed itself shows to be a tier word: one found in the areas
# of this share of a country's warnings names no single place, whatever
# language it is in. Judged only on a feed big enough to be telling; in
# a quiet country with three warnings, all in one province, the
# province's name matches all three and is not generic for it.
_FEED_WIDE_SHARE = 0.8
_FEED_WIDE_MIN_WARNINGS = 20


def _drop_feed_wide_words(location_words, per_warning_descs):
    """Location words minus any that match most of the feed.

    per_warning_descs holds one list of areaDesc strings per warning.
    The list of tier words above cannot know every language Nominatim
    speaks; this reads the tier words off the feed at hand instead.
    """
    if len(per_warning_descs) < _FEED_WIDE_MIN_WARNINGS:
        return location_words
    limit = _FEED_WIDE_SHARE * len(per_warning_descs)
    kept = set()
    for word in location_words:
        hits = sum(1 for descs in per_warning_descs
                   if any(word in d.lower() for d in descs))
        if hits < limit:
            kept.add(word)
    return kept


def _region_keys(areas):
    """The geocodes on a warning's areas that the data has ground for.

    Each is looked up by type and value: EMMA_IDs as themselves, a
    NUTS3, NUTS2, or CISORP code under its type. France's FR101 is both
    a NUTS3 code and an EMMA_ID; the type keeps them from crossing.
    """
    from linecast._meteoalarm_regions import key_for, known
    keys = set()
    for area in areas:
        for geocode in area.get("geocode") or []:
            key = key_for(geocode.get("valueName") or "", geocode.get("value") or "")
            if known(key):
                keys.add(key)
    return keys


def _regions_here(lat, lng, warnings):
    """The region keys covering the point, looked up only if a warning could use them."""
    from linecast._meteoalarm_regions import regions_at
    for w in warnings:
        for info in w.get("alert", {}).get("info", []):
            if _region_keys(info.get("area", [])):
                return regions_at(lat, lng)
    return set()


def _extract_location_words(address):
    """Extract location words from a Nominatim address for area matching."""
    if not address:
        return set()
    words = set()
    for key in ("city", "town", "village", "county", "state", "municipality",
                "suburb", "district", "region"):
        val = address.get(key, "")
        if val:
            for word in val.split():
                word = word.strip("(),.").lower()
                if len(word) >= 3 and word not in _GENERIC_PLACE_WORDS:
                    words.add(word)
    return words


def _cap_polygons(area):
    """The closed rings on a CAP area, as [[(lat, lng), ...], ...].

    CAP writes a ring as space-separated "lat,lon" pairs; MeteoAlarm
    carries them in a list, one per ring. Anything unparseable is skipped
    rather than raised on -- a malformed ring must not cost the user an
    alert, and an area with no usable ring falls back to areaDesc.
    """
    raw = area.get("polygon")
    if not raw:
        return []
    rings = []
    for ring in (raw if isinstance(raw, list) else [raw]):
        points = []
        for pair in str(ring).split():
            lat_str, _, lng_str = pair.partition(",")
            try:
                points.append((float(lat_str), float(lng_str)))
            except ValueError:
                continue
        if len(points) >= 3:
            rings.append(points)
    return rings


def _point_in_ring(lat, lng, ring):
    """True when (lat, lng) falls inside a closed ring. See _meteoalarm_regions."""
    from linecast._meteoalarm_regions import point_in_ring
    return point_in_ring(lat, lng, ring)


def _area_matches(area_desc, location_words):
    """Check if a MeteoAlarm areaDesc contains any of the user's location words."""
    if not area_desc or not location_words:
        return False
    desc_lower = area_desc.lower()
    return any(word in desc_lower for word in location_words)


# ---------------------------------------------------------------------------
# JMA (Japan Meteorological Agency)
# ---------------------------------------------------------------------------

# Center coordinates for each JMA forecast office, used for nearest-match lookup.
# Hokkaido is subdivided into 8 offices; Okinawa into 3; all others are 1:1 with prefectures.
_JMA_OFFICES = [
    # Hokkaido
    (45.4, 141.7, "011000"), (43.8, 142.4, "012000"),
    (44.0, 144.3, "013000"), (42.9, 143.2, "014030"),
    (43.0, 145.0, "014100"), (41.8, 140.7, "015000"),
    (43.1, 141.3, "016000"), (42.6, 141.6, "017000"),
    # Tohoku
    (40.8, 140.7, "020000"), (39.7, 141.1, "030000"),
    (38.3, 140.9, "040000"), (39.7, 140.1, "050000"),
    (38.2, 140.3, "060000"), (37.7, 140.5, "070000"),
    # Kanto
    (36.3, 140.4, "080000"), (36.6, 139.9, "090000"),
    (36.4, 139.1, "100000"), (35.9, 139.6, "110000"),
    (35.6, 140.1, "120000"), (35.7, 139.7, "130000"),
    (35.4, 139.6, "140000"),
    # Chubu
    (37.9, 139.0, "150000"), (36.7, 137.2, "160000"),
    (36.6, 136.6, "170000"), (36.1, 136.2, "180000"),
    (35.7, 138.6, "190000"), (36.2, 138.2, "200000"),
    (35.4, 136.8, "210000"), (34.9, 138.4, "220000"),
    (35.2, 137.0, "230000"),
    # Kinki
    (34.7, 136.5, "240000"), (35.0, 136.1, "250000"),
    (35.0, 135.8, "260000"), (34.7, 135.5, "270000"),
    (34.9, 134.7, "280000"), (34.7, 135.8, "290000"),
    (34.0, 135.4, "300000"),
    # Chugoku
    (35.5, 134.2, "310000"), (35.5, 133.1, "320000"),
    (34.7, 133.9, "330000"), (34.4, 132.5, "340000"),
    (34.2, 131.5, "350000"),
    # Shikoku
    (34.1, 134.6, "360000"), (34.3, 134.0, "370000"),
    (33.8, 132.8, "380000"), (33.6, 133.5, "390000"),
    # Kyushu
    (33.6, 130.4, "400000"), (33.3, 130.3, "410000"),
    (32.7, 129.9, "420000"), (32.8, 130.7, "430000"),
    (33.2, 131.6, "440000"), (31.9, 131.4, "450000"),
    (31.6, 130.6, "460100"),
    # Okinawa
    (26.3, 127.8, "471000"), (24.8, 125.3, "472000"),
    (24.3, 124.2, "473000"),
]

# JMA warning code -> (English name, Japanese name, severity)
_JMA_WARNING_NAMES = {
    # Special Warnings (\u7279\u5225\u8b66\u5831)
    "32": ("Special Blizzard Warning", "\u66b4\u98a8\u96ea\u7279\u5225\u8b66\u5831", "Extreme"),
    "33": ("Special Heavy Rain Warning", "\u5927\u96e8\u7279\u5225\u8b66\u5831", "Extreme"),
    "35": ("Special Storm Warning", "\u66b4\u98a8\u7279\u5225\u8b66\u5831", "Extreme"),
    "36": ("Special Heavy Snow Warning", "\u5927\u96ea\u7279\u5225\u8b66\u5831", "Extreme"),
    "37": ("Special High Wave Warning", "\u6ce2\u6d6a\u7279\u5225\u8b66\u5831", "Extreme"),
    "38": ("Special Storm Surge Warning", "\u9ad8\u6f6e\u7279\u5225\u8b66\u5831", "Extreme"),
    # Warnings (\u8b66\u5831)
    "02": ("Blizzard Warning", "\u66b4\u98a8\u96ea\u8b66\u5831", "Severe"),
    "03": ("Heavy Rain Warning", "\u5927\u96e8\u8b66\u5831", "Severe"),
    "04": ("Flood Warning", "\u6d2a\u6c34\u8b66\u5831", "Severe"),
    "05": ("Storm Warning", "\u66b4\u98a8\u8b66\u5831", "Severe"),
    "06": ("Heavy Snow Warning", "\u5927\u96ea\u8b66\u5831", "Severe"),
    "07": ("High Wave Warning", "\u6ce2\u6d6a\u8b66\u5831", "Severe"),
    "08": ("Storm Surge Warning", "\u9ad8\u6f6e\u8b66\u5831", "Severe"),
    # Watches (\u6ce8\u610f\u5831)
    "10": ("Heavy Rain Watch", "\u5927\u96e8\u6ce8\u610f\u5831", "Moderate"),
    "12": ("Heavy Snow Watch", "\u5927\u96ea\u6ce8\u610f\u5831", "Moderate"),
    "13": ("Wind Snow Watch", "\u98a8\u96ea\u6ce8\u610f\u5831", "Moderate"),
    "14": ("Thunderstorm Watch", "\u96f7\u6ce8\u610f\u5831", "Moderate"),
    "15": ("High Wind Watch", "\u5f37\u98a8\u6ce8\u610f\u5831", "Moderate"),
    "16": ("High Wave Watch", "\u6ce2\u6d6a\u6ce8\u610f\u5831", "Moderate"),
    "17": ("Snowmelt Watch", "\u878d\u96ea\u6ce8\u610f\u5831", "Moderate"),
    "18": ("Flood Watch", "\u6d2a\u6c34\u6ce8\u610f\u5831", "Moderate"),
    "19": ("Storm Surge Watch", "\u9ad8\u6f6e\u6ce8\u610f\u5831", "Moderate"),
    "20": ("Dense Fog Watch", "\u6fc3\u9727\u6ce8\u610f\u5831", "Moderate"),
    "21": ("Dry Air Watch", "\u4e7e\u71e5\u6ce8\u610f\u5831", "Minor"),
    "22": ("Avalanche Watch", "\u306a\u3060\u308c\u6ce8\u610f\u5831", "Moderate"),
    "23": ("Low Temperature Watch", "\u4f4e\u6e29\u6ce8\u610f\u5831", "Minor"),
    "24": ("Frost Watch", "\u971c\u6ce8\u610f\u5831", "Minor"),
    "25": ("Icing Watch", "\u7740\u6c37\u6ce8\u610f\u5831", "Moderate"),
    "26": ("Snow Accretion Watch", "\u7740\u96ea\u6ce8\u610f\u5831", "Moderate"),
    "27": ("Other Watch", "\u305d\u306e\u4ed6\u306e\u6ce8\u610f\u5831", "Minor"),
}

_JMA_ACTIVE = {"\u767a\u8868", "\u7d99\u7d9a"}


def _jma_office_for_coords(lat, lng):
    """Find the nearest JMA office code for given coordinates."""
    import math
    cos_lat = math.cos(math.radians(lat))
    best_code = "130000"
    best_dist = float("inf")
    for olat, olng, code in _JMA_OFFICES:
        dlat = lat - olat
        dlng = (lng - olng) * cos_lat
        dist = dlat * dlat + dlng * dlng
        if dist < best_dist:
            best_dist = dist
            best_code = code
    return best_code


def _fetch_alerts_jma(lat, lng, lang="en"):
    """Fetch active JMA weather warnings (Japan). Cached 15min."""
    office_code = _jma_office_for_coords(lat, lng)
    cache_file = cache_dir("weather") / f"alerts_jp_{office_code}_{lang}.json"
    url = f"https://www.jma.go.jp/bosai/warning/data/warning/{office_code}.json"
    data = fetch_json_cached(
        cache_file, 900, url,
        timeout=10, fallback=[],
    )
    if isinstance(data, list):
        return data

    headline = data.get("headlineText", "")
    report_dt = data.get("reportDatetime", "")
    use_ja = lang == "ja"

    # Collect all active warning codes across all areas
    active_codes = set()
    for area_type in data.get("areaTypes", []):
        for area in area_type.get("areas", []):
            for w in area.get("warnings", []):
                if w.get("status", "") in _JMA_ACTIVE:
                    active_codes.add(w.get("code", ""))

    severity_order = {"Extreme": 0, "Severe": 1, "Moderate": 2, "Minor": 3}
    alerts = []
    seen = set()
    for code in sorted(active_codes, key=lambda c: severity_order.get(
            _JMA_WARNING_NAMES.get(c, ("", "", "Minor"))[2], 3)):
        info = _JMA_WARNING_NAMES.get(code)
        if not info:
            continue
        en_name, ja_name, severity = info
        event = ja_name if use_ja else en_name
        dedup_key = (event, severity)
        if dedup_key in seen:
            continue
        seen.add(dedup_key)
        alerts.append({
            "event": event,
            "headline": headline if use_ja else event,
            "description": headline,
            "effective": report_dt,
            "expires": "",
            "severity": severity,
            "url": "https://www.jma.go.jp/bosai/warning/",
        })

    write_cache(cache_file, alerts)
    return alerts


# ---------------------------------------------------------------------------
# HKO (Hong Kong Observatory)
# ---------------------------------------------------------------------------

# The warnsum feed is a dict keyed by warning type; each entry names the
# warning and carries a code, which for rainstorms and tropical cyclones
# says how bad (amber/red/black; signal 1/3/8/9/10).
HKO_WARNINGS_URL = ("https://data.weather.gov.hk/weatherAPI/opendata/"
                    "weather.php?dataType=warnsum&lang=en")

_HKO_WARNING_INFO = {
    "WFIRE": ("Fire Danger Warning", "Moderate"),
    "WFROST": ("Frost Warning", "Minor"),
    "WHOT": ("Very Hot Weather Warning", "Minor"),
    "WCOLD": ("Cold Weather Warning", "Minor"),
    "WMSGNL": ("Strong Monsoon Signal", "Moderate"),
    "WRAIN": ("Rainstorm Warning", "Moderate"),
    "WFNTSA": ("Special Announcement on Flooding (NT)", "Moderate"),
    "WL": ("Landslip Warning", "Moderate"),
    "WTCSGNL": ("Tropical Cyclone Warning Signal", "Moderate"),
    "WTMW": ("Tsunami Warning", "Extreme"),
    "WTS": ("Thunderstorm Warning", "Minor"),
}

# Severity by code, where the code says more than the type does.
_HKO_CODE_SEV = {
    "WRAINB": "Severe", "WRAINR": "Moderate", "WRAINA": "Minor",
    "TC10": "Extreme", "TC9": "Extreme",
    "TC8NE": "Severe", "TC8SE": "Severe", "TC8NW": "Severe", "TC8SW": "Severe",
    "TC8": "Severe", "TC3": "Moderate", "TC1": "Minor",
    "WFIRER": "Severe",
}


def _parse_hko_warnsum(data):
    """Parse HKO warnsum JSON dict into normalised alert list."""
    alerts = []
    for key, info in _HKO_WARNING_INFO.items():
        entry = data.get(key)
        if not entry:
            continue
        if entry.get("actionCode") == "CANCEL":
            continue

        base_event, base_sev = info
        code = entry.get("code", key)
        severity = _HKO_CODE_SEV.get(code, base_sev)
        event = entry.get("name") or base_event
        alerts.append({
            "event": event,
            "headline": event,
            "description": "",
            "effective": entry.get("issueTime", ""),
            "expires": entry.get("expireTime", ""),
            "severity": severity,
            "url": "https://www.hko.gov.hk/en/detail.htm",
        })

    severity_order = {"Extreme": 0, "Severe": 1, "Moderate": 2, "Minor": 3}
    alerts.sort(key=lambda a: severity_order.get(a["severity"], 3))
    return alerts


def _fetch_alerts_hko():
    """Fetch active HKO weather warnings (Hong Kong). Cached 10min."""
    cache_file = cache_dir("weather") / "alerts_hk.json"
    url = HKO_WARNINGS_URL
    data = fetch_json_cached(cache_file, 600, url, timeout=10, fallback=[])
    if isinstance(data, list):
        return data

    alerts = _parse_hko_warnsum(data)
    write_cache(cache_file, alerts)
    return alerts


# ---------------------------------------------------------------------------
# CMA (China Meteorological Administration)
# ---------------------------------------------------------------------------

# Warning type names parsed from titles: Chinese -> English
_CMA_WARNING_NAMES = {
    "\u53f0\u98ce": "Typhoon",
    "\u66b4\u96e8": "Rainstorm",
    "\u66b4\u96ea": "Blizzard",
    "\u5bd2\u6f6e": "Cold Wave",
    "\u5927\u98ce": "Strong Wind",
    "\u6c99\u5c18\u66b4": "Sandstorm",
    "\u9ad8\u6e29": "Heat Wave",
    "\u5e72\u65f1": "Drought",
    "\u96f7\u7535": "Thunderstorm",
    "\u51b0\u96b9": "Hail",
    "\u971c\u51bb": "Frost",
    "\u5927\u96fe": "Dense Fog",
    "\u973e": "Haze",
    "\u9053\u8def\u7ed3\u51b0": "Road Icing",
    "\u68ee\u6797\u706b\u9669": "Forest Fire Risk",
    "\u96f7\u96e8\u5927\u98ce": "Thunderstorm Gale",
    "\u5f3a\u5bf9\u6d41": "Severe Convection",
}

# CMA color -> severity
_CMA_COLORS = {
    "\u7ea2": "Extreme",   # red
    "\u6a59": "Severe",    # orange
    "\u9ec4": "Moderate",  # yellow
    "\u84dd": "Minor",     # blue
}

# CMA color -> English name
_CMA_COLOR_EN = {
    "\u7ea2": "Red",
    "\u6a59": "Orange",
    "\u9ec4": "Yellow",
    "\u84dd": "Blue",
}

# Pic URL level code -> severity
_CMA_PIC_LEVELS = {
    "001": "Extreme",
    "002": "Severe",
    "003": "Moderate",
    "004": "Minor",
}

# Center coordinates for each Chinese province, used for nearest-match lookup.
# Maps (lat, lng) -> 2-digit GB/T 2260 province code prefix.
_CMA_PROVINCES = [
    (39.9, 116.4, "11"),    # Beijing
    (39.1, 117.2, "12"),    # Tianjin
    (38.0, 114.5, "13"),    # Hebei
    (37.9, 112.5, "14"),    # Shanxi
    (40.8, 111.7, "15"),    # Inner Mongolia
    (41.8, 123.4, "21"),    # Liaoning
    (43.9, 125.3, "22"),    # Jilin
    (45.8, 126.5, "23"),    # Heilongjiang
    (31.2, 121.5, "31"),    # Shanghai
    (32.1, 118.8, "32"),    # Jiangsu
    (30.3, 120.2, "33"),    # Zhejiang
    (31.8, 117.3, "34"),    # Anhui
    (26.1, 119.3, "35"),    # Fujian
    (28.7, 115.9, "36"),    # Jiangxi
    (36.7, 117.0, "37"),    # Shandong
    (34.8, 113.7, "41"),    # Henan
    (30.6, 114.3, "42"),    # Hubei
    (28.2, 112.9, "43"),    # Hunan
    (23.1, 113.3, "44"),    # Guangdong
    (22.8, 108.3, "45"),    # Guangxi
    (20.0, 110.3, "46"),    # Hainan
    (29.6, 106.5, "50"),    # Chongqing
    (30.6, 104.1, "51"),    # Sichuan
    (26.6, 106.7, "52"),    # Guizhou
    (25.0, 102.7, "53"),    # Yunnan
    (29.6, 91.1, "54"),     # Tibet
    (34.3, 108.9, "61"),    # Shaanxi
    (36.1, 103.8, "62"),    # Gansu
    (36.6, 101.8, "63"),    # Qinghai
    (38.5, 106.3, "64"),    # Ningxia
    (43.8, 87.6, "65"),     # Xinjiang
]


def _cma_provinces_for_coords(lat, lng, n=3):
    """Return the *n* nearest CMA province codes for given coordinates.

    Using multiple candidates handles border cities that are closer to a
    neighbouring province's centre than their own.
    """
    import math
    cos_lat = math.cos(math.radians(lat))
    dists = []
    for plat, plng, code in _CMA_PROVINCES:
        dlat = lat - plat
        dlng = (lng - plng) * cos_lat
        dists.append((dlat * dlat + dlng * dlng, code))
    dists.sort()
    return [code for _, code in dists[:n]]


def _fetch_alerts_cma(lat, lng, lang="en"):
    """Fetch active CMA weather warnings (China). Cached 15min.

    Uses nmc.cn/rest/findAlarm which has county-level alerts nationwide,
    filtered by the nearest province codes from the alertid prefix.
    """
    provinces = _cma_provinces_for_coords(lat, lng)
    tag = provinces[0]
    cache_file = cache_dir("weather") / f"alerts_cn_{tag}_{lang}.json"

    data = fetch_json_cached(
        cache_file, 900,
        "http://www.nmc.cn/rest/findAlarm?pageNo=1&pageSize=500",
        timeout=10, fallback=[],
    )
    if isinstance(data, list):
        return data

    alerts = _parse_cma_data(data, provinces, lang)
    write_cache(cache_file, alerts)
    return alerts


def _parse_cma_data(data, provinces, lang="en"):
    """Parse CMA findAlarm response into normalized alerts.

    *provinces* is a list of 2-digit province code strings; alerts whose
    alertid starts with any of them are included.
    """
    import re

    if not isinstance(data, dict):
        return []

    prefixes = tuple(provinces) if isinstance(provinces, list) else (provinces,)

    page = data.get("data", {}).get("page", {})
    entries = page.get("list", [])
    province_alarms = data.get("data", {}).get("provinceAlarms", [])

    use_zh = lang == "zh"
    alerts = []
    seen = set()

    # Province-level alarms first (most important), then county-level
    for entry in province_alarms + entries:
        alertid = entry.get("alertid", "")
        if alertid[:2] not in prefixes:
            continue

        title = entry.get("title", "")
        pic = entry.get("pic", "")
        issuetime = entry.get("issuetime", "")
        detail_url = entry.get("url", "")

        # Extract warning type and color from title
        tm = re.search(r'\u53d1\u5e03(.+?)(\u7ea2|\u6a59|\u9ec4|\u84dd)\u8272\u9884\u8b66', title)
        if tm:
            zh_type = tm.group(1)
            color = tm.group(2)
            severity = _CMA_COLORS.get(color, "Moderate")
        else:
            zh_type = ""
            severity = _cma_severity_from_pic(pic)
            color = ""

        # Build event name — deduplicate by warning type + severity
        if use_zh:
            event = title.split("\u53d1\u5e03")[-1] if "\u53d1\u5e03" in title else title
        else:
            en_name = _CMA_WARNING_NAMES.get(zh_type, "") if zh_type else ""
            if en_name:
                color_en = _CMA_COLOR_EN.get(color, "")
                event = f"{color_en} {en_name} Warning".strip()
            else:
                event = title

        dedup_key = (zh_type or title, severity)
        if dedup_key in seen:
            continue
        seen.add(dedup_key)

        effective = _parse_cma_issuetime(issuetime)
        url = f"http://www.nmc.cn{detail_url}" if detail_url else ""

        alerts.append({
            "event": event,
            "headline": title if use_zh else event,
            "description": title,
            "effective": effective,
            "expires": "",
            "severity": severity,
            "url": url,
        })

    severity_order = {"Extreme": 0, "Severe": 1, "Moderate": 2, "Minor": 3}
    alerts.sort(key=lambda a: severity_order.get(a["severity"], 3))
    return alerts


def _cma_severity_from_pic(pic_url):
    """Extract severity from CMA pic URL like .../p0007003.png."""
    if not pic_url:
        return "Moderate"
    base = pic_url.rsplit(".", 1)[0]  # strip .png
    code = base[-3:] if len(base) >= 3 else ""
    return _CMA_PIC_LEVELS.get(code, "Moderate")


def _parse_cma_issuetime(s):
    """Parse CMA issuetime '2026/03/07 22:39' -> '2026-03-07T22:39:00'."""
    if not s:
        return ""
    s = s.strip()
    # Format: "2026/03/07 22:39"
    if len(s) >= 16 and s[4] == "/" and s[7] == "/" and s[10] == " ":
        return f"{s[0:4]}-{s[5:7]}-{s[8:10]}T{s[11:16]}:00"
    return ""


# ---------------------------------------------------------------------------
# SACHET (National Disaster Management Authority, India)
# ---------------------------------------------------------------------------

_SACHET_FEED_URL = "https://sachet.ndma.gov.in/cap_public_website/FetchAllAlertDetails"
_SACHET_CAP_URL = ("https://sachet.ndma.gov.in/cap_public_website/FetchXMLFile"
                   "?identifier={identifier}")

_IST = timezone(timedelta(hours=5, minutes=30))

# The feed's colour is the fallback when an alert's CAP file is out of
# reach; the file itself carries the standard CAP severity.
_SACHET_COLORS = {"red": "Extreme", "orange": "Severe", "yellow": "Moderate"}

_SACHET_MONTHS = {
    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
    "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
}


def _fetch_alerts_sachet(lat, lng, lang="en"):
    """Fetch active alerts from SACHET, India's national CAP aggregator.

    One national feed lists every active alert — IMD weather warnings,
    CWC flood bulletins, state SDMA nowcasts — with a centroid and the
    area covered, so a single request (cached 15min) serves any location
    in the country. An alert is kept when the user sits within the disc
    of that area, plus slack for the shapes a disc misses.

    The feed's push text is often in a regional language alone; each
    alert's CAP file carries an info block per language, English always
    among them, so the kept alerts are refined from their CAP files
    (cached per alert — a SACHET update is a new identifier).
    """
    import math

    feed = fetch_json_cached(
        cache_dir("weather") / "alerts_in_feed.json", 900,
        _SACHET_FEED_URL, timeout=15, fallback=None,
    )
    if not isinstance(feed, list):
        return []

    cos_lat = math.cos(math.radians(lat))
    candidates = []
    for entry in feed:
        if not isinstance(entry, dict):
            continue
        try:
            lng_str, lat_str = str(entry.get("centroid", "")).split(",")
            clat, clng = float(lat_str), float(lng_str)
        except ValueError:
            continue
        try:
            area = float(entry.get("area_covered") or 0.0)
        except (TypeError, ValueError):
            area = 0.0
        radius_km = math.sqrt(area / math.pi) if area > 0 else 0.0
        dist_km = 111.32 * math.hypot(lat - clat, (lng - clng) * cos_lat)
        if dist_km <= radius_km + 25.0:
            candidates.append((dist_km, entry))

    # Nearest first, and a ceiling on CAP fetches: past a dozen alerts on
    # one spot the marginal one adds latency, not information.
    candidates.sort(key=lambda pair: pair[0])
    now = datetime.now(timezone.utc)
    alerts = []
    seen = set()
    for _dist, entry in candidates[:12]:
        alert = (_sachet_alert_from_cap(entry, lang)
                 or _sachet_alert_from_feed(entry))
        if alert is None:
            continue
        expires = _parse_iso_aware(alert["expires"])
        if expires is not None and expires < now:
            continue  # the cached feed can outlive an alert by up to 15min
        dedup_key = (alert["event"], alert["severity"], alert["headline"])
        if dedup_key in seen:
            continue
        seen.add(dedup_key)
        alerts.append(alert)

    severity_order = {"Extreme": 0, "Severe": 1, "Moderate": 2, "Minor": 3}
    alerts.sort(key=lambda a: severity_order.get(a["severity"], 3))

    _sweep_sachet_cap_files(feed)
    return alerts


def _sweep_sachet_cap_files(feed):
    """Drop cached CAP files for alerts no longer in the feed.

    India issues nowcasts by the hundred a day; without a sweep the
    cache would keep every one this user was ever near.
    """
    live = {str(entry.get("identifier"))
            for entry in feed if isinstance(entry, dict)}
    try:
        for path in cache_dir("weather").glob("alerts_in_cap_*.xml"):
            if path.stem[len("alerts_in_cap_"):] not in live:
                path.unlink(missing_ok=True)
    except OSError as exc:
        log_failure("cache", "sweep of SACHET CAP files", exc,
                    fallback="left in place")


def _parse_iso_aware(iso_str):
    """An ISO timestamp as an aware UTC datetime, or None."""
    try:
        dt = datetime.fromisoformat(iso_str)
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        return None
    return dt.astimezone(timezone.utc)


def _sachet_datetime(s):
    """A SACHET feed time ("Sun Aug 30 21:00:00 IST 2026") as ISO 8601.

    Parsed by hand: strptime's %a and %b follow the process locale, and
    the feed's English month names must parse on a German machine too.
    """
    m = re.match(r"\w+ (\w+) (\d+) (\d+):(\d+):(\d+) IST (\d+)", str(s or ""))
    if not m:
        return ""
    month = _SACHET_MONTHS.get(m.group(1))
    if month is None:
        return ""
    day, hour, minute, second, year = (int(g) for g in m.groups()[1:])
    try:
        dt = datetime(year, month, day, hour, minute, second, tzinfo=_IST)
    except ValueError:
        return ""
    return dt.isoformat()


def _sachet_alert_from_feed(entry):
    """A normalized alert from a SACHET feed entry alone."""
    event = str(entry.get("disaster_type") or "").strip()
    message = str(entry.get("warning_message") or "").strip()
    if not event and not message:
        return None
    severity = _SACHET_COLORS.get(
        str(entry.get("severity_color") or "").lower(), "Moderate")
    return {
        "event": event or "Alert",
        "headline": message or event,
        "description": message,
        "effective": _sachet_datetime(entry.get("effective_start_time")),
        "expires": _sachet_datetime(entry.get("effective_end_time")),
        "severity": severity,
        "url": "https://sachet.ndma.gov.in/",
    }


def _sachet_cap_infos(identifier):
    """The info blocks of one SACHET CAP file, as dicts; None on failure.

    Cached without expiry: an alert's CAP file never changes — SACHET
    issues updates under a new identifier — and the per-identifier files
    are swept once the alert leaves the feed (_sweep_sachet_cap_files).
    """
    from xml.etree import ElementTree

    from linecast._http import fetch_bytes_cached

    # A shorter timeout than usual: these fetches run one after another,
    # and a dozen of them must not hold the dashboard for two minutes.
    raw = fetch_bytes_cached(
        cache_dir("weather") / f"alerts_in_cap_{identifier}.xml", None,
        _SACHET_CAP_URL.format(identifier=identifier), timeout=6,
    )
    if not raw:
        return None
    try:
        root = ElementTree.fromstring(raw)
    except ElementTree.ParseError as exc:
        log_failure("weather/alerts", f"CAP parse of {identifier}", exc,
                    fallback="feed entry used")
        return None

    def _local(tag):
        return tag.rsplit("}", 1)[-1]

    infos = []
    for info_el in root.iter():
        if _local(info_el.tag) != "info":
            continue
        info = {}
        for child in info_el:
            tag = _local(child.tag)
            if tag in ("language", "event", "severity", "headline",
                       "description", "instruction", "effective", "onset",
                       "expires"):
                info[tag] = (child.text or "").strip()
        infos.append(info)
    return infos or None


# SACHET tags a CAP info block with its own uppercase language code.
# Most are the ISO 639-1 code upcased ("HI", "MR"); these are not.
_SACHET_CAP_LANGS = {"od": "or", "tl": "te"}


def _sachet_cap_lang(code):
    """A SACHET CAP language code ("en-IN", "HI", "TL") as ISO 639-1."""
    code = code.partition("-")[0].lower()
    return _SACHET_CAP_LANGS.get(code, code)


def _sachet_alert_from_cap(entry, lang):
    """A normalized alert from a SACHET CAP file, or None to fall back.

    An alert often carries its info in the state language besides
    English; --lang picks it, so `--lang hi` reads SACHET's own Hindi
    even though the app's UI does not speak it.
    """
    identifier = entry.get("identifier")
    if not identifier:
        return None
    infos = _sachet_cap_infos(identifier)
    if not infos:
        return None

    def _in_lang(iso):
        return next((i for i in infos
                     if _sachet_cap_lang(i.get("language", "")) == iso), None)
    info = _in_lang(lang.lower()) or _in_lang("en") or infos[0]

    event = info.get("event", "").strip()
    headline = " ".join(info.get("headline", "").split())
    description = " ".join(info.get("description", "").split())
    instruction = " ".join(info.get("instruction", "").split())
    if not event and not headline:
        return None
    if instruction and instruction.lower() != "please follow sdma guidelines.":
        description = f"{description} {instruction}".strip()
    severity = info.get("severity", "").capitalize()
    if severity not in ("Extreme", "Severe", "Moderate", "Minor"):
        severity = _SACHET_COLORS.get(
            str(entry.get("severity_color") or "").lower(), "Moderate")
    return {
        "event": event or "Alert",
        "headline": headline or event,
        "description": description or headline,
        "effective": info.get("effective") or info.get("onset") or "",
        "expires": info.get("expires", ""),
        "severity": severity,
        "url": "https://sachet.ndma.gov.in/",
    }


# ---------------------------------------------------------------------------
# MetService (New Zealand)
# ---------------------------------------------------------------------------

_METSERVICE_FEED_URL = "https://alerts.metservice.com/cap/rss"
_METSERVICE_CAP_URL = "https://alerts.metservice.com/cap/alert?id={identifier}"

# The ColourCode parameter carries MetService's public severity ladder;
# the CAP severity field stands in when an alert has no colour.
_METSERVICE_COLORS = {"red": "Extreme", "orange": "Severe", "yellow": "Moderate"}


def _fetch_alerts_metservice(lat, lng):
    """Fetch active MetService warnings (New Zealand). Feed cached 15min.

    The public CAP feed (CC BY 4.0) lists every current watch, warning
    and advisory as an RSS item pointing at a CAP file, which carries
    the polygon of the ground it covers, so alerts are kept by
    point-in-polygon: a road snowfall warning for the Desert Road should
    not follow a user in Auckland. CAP files are cached per identifier —
    a MetService update is a new identifier — and swept once their alert
    leaves the feed.
    """
    from xml.etree import ElementTree

    from linecast._http import fetch_bytes_cached

    raw = fetch_bytes_cached(
        cache_dir("weather") / "alerts_nz_feed.xml", 900,
        _METSERVICE_FEED_URL, timeout=15)
    if not raw:
        return []
    try:
        feed = ElementTree.fromstring(raw)
    except ElementTree.ParseError as exc:
        log_failure("weather/alerts", "MetService feed parse", exc,
                    fallback="no alerts")
        return []

    identifiers = [guid.text.strip() for guid in feed.iter("guid")
                   if guid.text and guid.text.strip()]

    now = datetime.now(timezone.utc)
    alerts = []
    seen = set()
    for identifier in identifiers[:30]:
        alert = _metservice_alert_from_cap(identifier, lat, lng)
        if alert is None:
            continue
        expires = _parse_iso_aware(alert["expires"])
        if expires is not None and expires < now:
            continue  # the cached feed can outlive an alert by up to 15min
        dedup_key = (alert["event"], alert["severity"], alert["headline"])
        if dedup_key in seen:
            continue
        seen.add(dedup_key)
        alerts.append(alert)

    severity_order = {"Extreme": 0, "Severe": 1, "Moderate": 2, "Minor": 3}
    alerts.sort(key=lambda a: severity_order.get(a["severity"], 3))

    _sweep_metservice_cap_files(identifiers)
    return alerts


def _sweep_metservice_cap_files(identifiers):
    """Drop cached CAP files for alerts no longer in the feed."""
    live = set(identifiers)
    try:
        for path in cache_dir("weather").glob("alerts_nz_cap_*.xml"):
            if path.stem[len("alerts_nz_cap_"):] not in live:
                path.unlink(missing_ok=True)
    except OSError as exc:
        log_failure("cache", "sweep of MetService CAP files", exc,
                    fallback="left in place")


def _metservice_alert_from_cap(identifier, lat, lng):
    """One feed item as a normalized alert, or None when it does not
    apply: the CAP file is out of reach or malformed, the alert is a
    test or a cancellation, or its polygons say the user is outside the
    warned ground.
    """
    from xml.etree import ElementTree

    from linecast._http import fetch_bytes_cached

    # A shorter timeout than usual: these fetches run one after another,
    # and a stormy week's worth must not hold the dashboard for long.
    raw = fetch_bytes_cached(
        cache_dir("weather") / f"alerts_nz_cap_{identifier}.xml", None,
        _METSERVICE_CAP_URL.format(identifier=identifier), timeout=6)
    if not raw:
        return None
    try:
        root = ElementTree.fromstring(raw)
    except ElementTree.ParseError as exc:
        log_failure("weather/alerts", f"CAP parse of {identifier}", exc,
                    fallback="skipped")
        return None

    def _local(tag):
        return tag.rsplit("}", 1)[-1]

    status = msg_type = ""
    info_el = None
    for child in root:
        tag = _local(child.tag)
        if tag == "status":
            status = (child.text or "").strip()
        elif tag == "msgType":
            msg_type = (child.text or "").strip()
        elif tag == "info" and info_el is None:
            info_el = child
    if status != "Actual" or msg_type == "Cancel" or info_el is None:
        return None

    info = {}
    colour = ""
    rings = []
    for child in info_el:
        tag = _local(child.tag)
        if tag in ("event", "severity", "headline", "description",
                   "effective", "onset", "expires", "web"):
            info[tag] = (child.text or "").strip()
        elif tag == "parameter":
            fields = {_local(c.tag): (c.text or "").strip() for c in child}
            if fields.get("valueName") == "ColourCode":
                colour = fields.get("value", "").lower()
        elif tag == "area":
            polygons = [(c.text or "") for c in child
                        if _local(c.tag) == "polygon"]
            rings.extend(_cap_polygons({"polygon": polygons}))

    # The polygon is the warning's own account of the ground it covers;
    # a CAP file without one (rare) is taken as nationwide.
    if rings and not any(_point_in_ring(lat, lng, ring) for ring in rings):
        return None

    headline = " ".join(info.get("headline", "").split())
    event = headline or info.get("event", "").capitalize()
    if not event:
        return None
    severity = _METSERVICE_COLORS.get(colour, "")
    if not severity:
        severity = info.get("severity", "").capitalize()
        if severity not in ("Extreme", "Severe", "Moderate", "Minor"):
            severity = "Moderate"
    return {
        "event": event,
        "headline": headline or event,
        "description": " ".join(info.get("description", "").split()),
        "effective": info.get("effective") or info.get("onset") or "",
        "expires": info.get("expires", ""),
        "severity": severity,
        "url": info.get("web") or "https://www.metservice.com/warnings/home",
    }


def _photon_query(query, lang="en", timeout=10):
    """Photon's answer to a place name, reshaped to the Open-Meteo
    geocoder's result dicts — the second source when Open-Meteo doesn't
    answer. Photon speaks en/de/fr only; any other language asks in
    English rather than getting an error back."""
    import urllib.parse

    from linecast import user_agent
    from linecast._maps_search import PHOTON_LANGS, PHOTON_URL

    params = [("q", query), ("limit", 10)]
    if lang in PHOTON_LANGS:
        params.append(("lang", lang))
    url = f"{PHOTON_URL}?{urllib.parse.urlencode(params)}"
    data = fetch_json(url, headers={"User-Agent": user_agent()}, timeout=timeout)
    results = []
    for feature in data.get("features") or []:
        props = feature.get("properties") or {}
        name = (props.get("name") or "").strip()
        coords = (feature.get("geometry") or {}).get("coordinates") or []
        if not name or len(coords) < 2:
            continue
        results.append({
            "name": name,
            "latitude": float(coords[1]),
            "longitude": float(coords[0]),
            "admin1": props.get("state", ""),
            "country": props.get("country", ""),
            "country_code": props.get("countrycode", ""),
        })
    return results


def _geocode_query(query, lang="en"):
    """Geocode a place name via Open-Meteo, falling back to Photon.
    Returns list of result dicts."""
    import urllib.parse

    url = (
        "https://geocoding-api.open-meteo.com/v1/search"
        f"?name={urllib.parse.quote(query)}&count=10&language={lang}"
    )
    try:
        data = fetch_json(url, timeout=10)
    except Exception as exc:
        log_failure("location/geocoder", "geocode", exc, url=url, fallback="Photon")
        try:
            return _photon_query(query, lang=lang)
        except Exception as photon_exc:
            log_failure("location/photon", "geocode", photon_exc,
                        fallback="exiting")
            print(f"Search failed: {exc}", file=sys.stderr)
            sys.exit(1)
    return data.get("results", [])


def geocode_first(query: str, lang: str = "en") -> tuple[float, float, str] | None:
    """Geocode a place name and return the top result as (lat, lng, label).

    Returns ``None`` if nothing matches.
    """
    results = _geocode_query(query, lang=lang)
    if not results:
        return None
    r = results[0]
    lat = r.get("latitude", 0)
    lng = r.get("longitude", 0)
    parts = [r.get("name", "")]
    if r.get("admin1"):
        parts.append(r["admin1"])
    if r.get("country"):
        parts.append(r["country"])
    return lat, lng, ", ".join(parts)


def _search_locations(query, lang="en"):
    """Search cities using Open-Meteo geocoding API and print results."""
    results = _geocode_query(query, lang=lang)
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
    print("   or: linecast location set LAT,LNG")
    print("   or: export WEATHER_LOCATION=LAT,LNG")
