"""Air quality: Open-Meteo's pollutants, and the national indices read
from them or published beside them, India's CPCB AQI and Canada's AQHI."""

from datetime import datetime, timedelta, timezone
from typing import Any

from linecast._cache import location_cache_key
from linecast._http import fetch_json_cached
from linecast._i18n import base_language
from linecast._log import log_failure
from linecast._paths import cache_dir


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


# Canada's Air Quality Health Index (Health Canada, 2008): one number
# from 1 to 10+ for the day's health risk, from the three-hour trailing
# means of nitrogen dioxide and ozone in ppb and PM2.5 in µg/m³, each
# weighted by an exponential term, the sum scaled so that 10 sits at
# the top of the observed range. British Columbia's AQHI-Plus (2018),
# which the other provinces have taken up, publishes the greater of
# that and the one-hour PM2.5 divided by ten, rounded up, so that a
# smoke plume the slow means would understate is reported at once.
# Open-Meteo states the gases in µg/m³; ppb at 25 °C and 1 atm is
# 24.45 / molar mass of that.
_AQHI_SCALE = 10 / 10.4 * 100
_AQHI_WEIGHTS = {"nitrogen_dioxide": 0.000871, "ozone": 0.000537, "pm2_5": 0.000487}
_PPB_PER_UGM3 = {"nitrogen_dioxide": 24.45 / 46.0055, "ozone": 24.45 / 48.0, "pm2_5": 1.0}


def canada_aqhi(no2_ppb, o3_ppb, pm25):
    """The unrounded AQHI for three-hour mean concentrations."""
    import math
    w = _AQHI_WEIGHTS
    return _AQHI_SCALE * ((math.exp(w["nitrogen_dioxide"] * no2_ppb) - 1)
                          + (math.exp(w["ozone"] * o3_ppb) - 1)
                          + (math.exp(w["pm2_5"] * pm25) - 1))


def aqhi_published(value):
    """The whole number Environment Canada prints for an index value:
    rounded, never below 1. Past 10 it is shown as "10+"."""
    return max(1, int(value + 0.5))


def canada_aqhi_computed(aqi_data):
    """The AQHI, with the AQHI-Plus rule, from an Open-Meteo air quality
    response: the three-hour means ending at the current hour, and the
    current hour's PM2.5 alone divided by ten and rounded up, whichever
    is greater. None without the three pollutants for that hour."""
    import math
    if not isinstance(aqi_data, dict):
        return None
    hourly = aqi_data.get("hourly") or {}
    times = hourly.get("time") or []
    now = (aqi_data.get("current") or {}).get("time")
    try:
        end = times.index(now) + 1
    except ValueError:
        return None
    means = {}
    for pollutant, per_ugm3 in _PPB_PER_UGM3.items():
        values = [v for v in (hourly.get(pollutant) or [])[max(0, end - 3):end] if v is not None]
        if not values:
            return None
        means[pollutant] = sum(values) / len(values) * per_ugm3
    latest_pm = (hourly.get("pm2_5") or [None])[end - 1]
    if latest_pm is None:
        return None
    index = aqhi_published(canada_aqhi(means["nitrogen_dioxide"], means["ozone"], means["pm2_5"]))
    return max(index, math.ceil(latest_pm / 10))


def aqhi_category(value, lang="en"):
    """Health Canada's name for the risk at an index value, in English
    or, for a French reader, in French."""
    band = 0 if value <= 3 else 1 if value <= 6 else 2 if value <= 10 else 3
    if base_language(lang) == "fr":
        return ("Risque faible", "Risque modéré", "Risque élevé", "Risque très élevé")[band]
    return ("Low risk", "Moderate risk", "High risk", "Very high risk")[band]


def fmt_aqhi(value):
    """The index as printed: "4", or "10+" past ten."""
    return "10+" if value > 10 else str(value)


# Environment Canada publishes the AQHI it reports for each community:
# hourly observations for about 120 of them (Quebec, which runs its own
# index, is not among them), and hourly forecasts for some 200 more.
# A place is given the nearest community's number within this reach;
# beyond it, the index is computed from the pollutants above.
_AQHI_API = "https://api.weather.gc.ca/collections/aqhi-{feed}-realtime/items"
AQHI_REACH_KM = 75


def _aqhi_features(feed, lat, lng, max_age):
    span = 1.0
    bbox = f"{lng - span:.3f},{lat - span:.3f},{lng + span:.3f},{lat + span:.3f}"
    extra = "&latest=true" if feed == "observations" else ""
    url = f"{_AQHI_API.format(feed=feed)}?f=json&limit=1000&bbox={bbox}{extra}"
    cache_file = cache_dir("weather") / f"aqhi_ca_{feed}_{location_cache_key(lat, lng)}.json"
    data = fetch_json_cached(cache_file, max_age, url, timeout=10, fallback=None)
    return (data or {}).get("features") or []


def _aqhi_distance_km(feature, lat, lng):
    from linecast._geo import haversine_nm
    try:
        flng, flat = feature["geometry"]["coordinates"][:2]
    except (KeyError, TypeError, ValueError):
        return None
    return haversine_nm(lat, lng, flat, flng) * 1.852


def _parse_utc(text):
    try:
        return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def pick_aqhi(observations, forecasts, lat, lng, now):
    """Environment Canada's number for the place, from the feeds' features:
    the nearest community's observation for an hour not more than two
    old, else the nearest community's latest forecast for the hour
    nearest now, within three; None beyond reach or with stale feeds.
    Returns {"aqhi", "place", "kind", "time"} with kind "observed" or
    "forecast"."""
    def within_reach(features):
        near = []
        for f in features:
            km = _aqhi_distance_km(f, lat, lng)
            if km is not None and km <= AQHI_REACH_KM:
                near.append((km, f))
        return sorted(near, key=lambda pair: pair[0])

    for _km, f in within_reach(observations):
        p = f.get("properties") or {}
        when = _parse_utc(p.get("observation_datetime"))
        value = p.get("aqhi")
        if p.get("aqhi_type") != "AQHI-Observation" or when is None or value is None:
            continue
        if not (timedelta(0) <= now - when <= timedelta(hours=2)):
            continue
        return {"aqhi": aqhi_published(float(value)), "place": p.get("location_name_en", ""),
                "kind": "observed", "time": when.isoformat()}

    by_place = {}
    for km, f in within_reach(forecasts):
        p = f.get("properties") or {}
        if p.get("aqhi_type") != "AQHI-Forecast" or p.get("aqhi") is None:
            continue
        by_place.setdefault(p.get("location_id"), (km, []))[1].append(p)
    for _place_id, (_km, items) in sorted(by_place.items(), key=lambda kv: kv[1][0]):
        published = max(p.get("publication_datetime") or "" for p in items)
        best = None
        for p in items:
            if p.get("publication_datetime") != published:
                continue
            when = _parse_utc(p.get("forecast_datetime"))
            if when is None:
                continue
            off = abs(now - when)
            if off <= timedelta(hours=3) and (best is None or off < best[0]):
                best = (off, p, when)
        if best is not None:
            _off, p, when = best
            return {"aqhi": aqhi_published(float(p["aqhi"])),
                    "place": p.get("location_name_en", ""),
                    "kind": "forecast", "time": when.isoformat()}
    return None


def fetch_canada_aqhi(lat, lng, now=None):
    """Environment Canada's AQHI for the nearest community, or None.
    The observations feed is asked first, then the forecasts; each is
    cached, the observations for half an hour and the forecasts for
    one, since a station reads hourly and a forecast is issued twice a
    day."""
    now = now or datetime.now(timezone.utc)
    observations = _aqhi_features("observations", lat, lng, 1800)
    report = pick_aqhi(observations, [], lat, lng, now)
    if report is None:
        forecasts = _aqhi_features("forecasts", lat, lng, 3600)
        report = pick_aqhi([], forecasts, lat, lng, now)
    return report


_UNSET = object()


def apply_national_index(aqi_data, country_code, lat=None, lng=None, canada=_UNSET):
    """Attach the country's own air quality index where linecast knows
    one, and return the response, which is new when Canada's report
    comes without one.

    India reads the CPCB scale computed from the pollutants
    (apply_india_aqi). Canada reads the AQHI as Environment Canada
    reports it for the nearest community, passed in as `canada` when the
    caller fetched it beside the forecast, else fetched here; with no
    community in reach the index is computed from the pollutants, with
    the AQHI-Plus rule. render_header and the JSON payload show the
    national number in place of the US AQI when present.
    """
    if country_code == "IN":
        apply_india_aqi(aqi_data, country_code)
        return aqi_data
    if country_code != "CA":
        return aqi_data
    report = canada
    if report is _UNSET:
        try:
            report = fetch_canada_aqhi(lat, lng)
        except Exception as exc:  # noqa: BLE001 - a feed's failure is logged, never fatal
            log_failure("weather", "Canada's AQHI", exc, fallback="computed from the pollutants")
            report = None
    if report is None:
        value = canada_aqhi_computed(aqi_data)
        if value is None:
            return aqi_data
        report = {"aqhi": value, "kind": "computed", "place": ""}
    if not isinstance(aqi_data, dict):
        aqi_data = {}
    current = aqi_data.setdefault("current", {})
    current["aqhi"] = report["aqhi"]
    current["aqhi_source"] = report["kind"]
    current["aqhi_place"] = report.get("place") or ""
    return aqi_data
