"""Weather data/source helpers: geocoding, forecast fetches, and alerts."""

import re
import sys
from datetime import datetime, timezone, timedelta

from linecast import USER_AGENT
from linecast._cache import CACHE_ROOT, read_cache, read_stale, write_cache, location_cache_key
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

    Returns (display_name, country_code, address) tuple.
    """
    cache_file = CACHE_DIR / "location.json"
    cached = read_cache(cache_file, 86400)  # 24h cache
    if cached and cached.get("lat") == round(lat, 4) and cached.get("lng") == round(lng, 4):
        return cached.get("name", ""), cached.get("country_code", ""), cached.get("address", {})

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
            "address": addr,
        })
        return display, country_code, addr
    except Exception:
        return "", "", {}


def fetch_forecast(lat, lng, runtime=None):
    """Fetch hourly + daily forecast from Open-Meteo. Cached 1h."""
    if runtime is None:
        runtime = WeatherRuntime.from_sources()
    temp_tag = "C" if runtime.celsius else "F"
    wind_tag = "m" if runtime.metric else "i"
    cache_file = CACHE_DIR / f"forecast_{location_cache_key(lat, lng)}_{temp_tag}{wind_tag}.json"
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
        headers={"User-Agent": USER_AGENT},
        timeout=10,
        fallback=None,
    )


def fetch_aqi(lat, lng):
    """Fetch current AQI from Open-Meteo Air Quality API. Cached 1h."""
    cache_file = CACHE_DIR / f"aqi_{location_cache_key(lat, lng)}.json"
    url = (
        "https://air-quality-api.open-meteo.com/v1/air-quality"
        f"?latitude={lat}&longitude={lng}"
        "&current=us_aqi,european_aqi,pm2_5,pm10"
    )
    return fetch_json_cached(
        cache_file,
        3600,
        url,
        headers={"User-Agent": USER_AGENT},
        timeout=10,
        fallback=None,
    )


def fetch_alerts(lat, lng, country_code="", lang="en", address=None):
    """Fetch active weather alerts from the appropriate provider.

    Routes to the best available source for each country.
    """
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
    if country_code == "CN":
        return _fetch_alerts_cma(lat, lng, lang=lang)
    slug = _METEOALARM_SLUGS.get(country_code)
    if slug:
        return _fetch_alerts_meteoalarm(lat, lng, slug, lang=lang, address=address)
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
    cache_file = CACHE_DIR / f"alerts_de_{location_cache_key(lat, lng)}_{lang}.json"
    url = f"https://api.brightsky.dev/alerts?lat={lat}&lon={lng}"
    data = fetch_json_cached(
        cache_file, 900, url,
        headers={"User-Agent": USER_AGENT},
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
    cache_file = CACHE_DIR / f"alerts_no_{location_cache_key(lat, lng)}.json"
    url = (
        f"https://api.met.no/weatherapi/metalerts/2.0/current.json"
        f"?lat={lat}&lon={lng}"
    )
    data = fetch_json_cached(
        cache_file, 900, url,
        headers={"User-Agent": USER_AGENT},
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
    import re

    cache_file = CACHE_DIR / f"alerts_ie_{location_cache_key(lat, lng)}.json"
    url = "https://prodapi.metweb.ie/warnings/active"
    data = fetch_json_cached(
        cache_file, 900, url,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
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
    "AT": "austria", "BE": "belgium", "BG": "bulgaria", "HR": "croatia",
    "CY": "cyprus", "CZ": "czechia", "DK": "denmark", "EE": "estonia",
    "FI": "finland", "FR": "france", "GR": "greece",
    "HU": "hungary", "IS": "iceland", "IT": "italy",
    "LV": "latvia", "LT": "lithuania", "LU": "luxembourg", "MT": "malta",
    "NL": "netherlands", "PL": "poland", "PT": "portugal",
    "RO": "romania", "RS": "serbia", "SK": "slovakia", "SI": "slovenia",
    "ES": "spain", "SE": "sweden", "CH": "switzerland", "GB": "united-kingdom",
}


def _fetch_alerts_meteoalarm(lat, lng, slug, lang="en", address=None):
    """Fetch MeteoAlarm warnings for a European country. Cached 15min.

    Filters by severity and area match against the user's Nominatim address.
    Prefers the user's language for alert text, falling back to English.
    """
    cache_file = CACHE_DIR / f"alerts_eu_{slug}_{location_cache_key(lat, lng)}_{lang}.json"
    url = f"https://feeds.meteoalarm.org/api/v1/warnings/feeds-{slug}"
    data = fetch_json_cached(
        cache_file, 900, url,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        timeout=15, fallback=[],
    )
    if isinstance(data, list):
        return data

    location_words = _extract_location_words(address)
    alerts = []
    seen = set()
    for w in data.get("warnings", []):
        alert_obj = w.get("alert", {})
        infos = alert_obj.get("info", [])
        # Prefer user's language, fall back to English, then first available
        preferred_info = None
        en_info = None
        other_info = None
        area_descs = []
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
        info = preferred_info or en_info or other_info
        if not info:
            continue

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

        # For Moderate: only include if area matches user's location
        if severity == "Moderate" and location_words:
            if not any(_area_matches(ad, location_words) for ad in area_descs):
                continue

        dedup_key = (event, severity)
        if dedup_key in seen:
            continue
        seen.add(dedup_key)

        alerts.append({
            "event": event,
            "headline": info.get("headline") or event,
            "description": info.get("description") or "",
            "effective": info.get("effective") or info.get("onset") or "",
            "expires": info.get("expires") or "",
            "severity": severity,
            "url": info.get("web") or "",
        })
    write_cache(cache_file, alerts)
    return alerts


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
                if len(word) >= 3:
                    words.add(word.lower())
    return words


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
    cache_file = CACHE_DIR / f"alerts_jp_{office_code}_{lang}.json"
    url = f"https://www.jma.go.jp/bosai/warning/data/warning/{office_code}.json"
    data = fetch_json_cached(
        cache_file, 900, url,
        headers={"User-Agent": USER_AGENT},
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
    cache_file = CACHE_DIR / f"alerts_cn_{tag}_{lang}.json"

    data = fetch_json_cached(
        cache_file, 900,
        "http://www.nmc.cn/rest/findAlarm?pageNo=1&pageSize=500",
        headers={"User-Agent": USER_AGENT},
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
        if not alertid[:2] in prefixes:
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


def _geocode_query(query, lang="en"):
    """Geocode a place name via Open-Meteo. Returns list of result dicts."""
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
    return data.get("results", [])


def geocode_first(query, lang="en"):
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
    print("   or: export WEATHER_LOCATION=LAT,LNG")
