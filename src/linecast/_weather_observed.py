"""The sky as a nearby station last saw it, over the model's guess.

The forecast's current condition is the model's for the quarter hour,
and a model can keep a fog deck or a shower for hours after the sky
has cleared. Airports report what is overhead at least hourly, in
METARs, and the Aviation Weather Center serves the world's as JSON
without a key. Where a station is close and its report recent, its
sky stands in for the model's weather code; the temperature, wind and
the rest stay the model's, which the graph and the prose agree with.
"""

import json
import math
import time
from typing import Any

from linecast._cache import location_cache_key
from linecast._http import fetch_bytes, fetch_json_cached
from linecast._paths import cache_dir
from linecast._runtime import log_failure

_METAR_URL = ("https://aviationweather.gov/api/data/metar"
              "?bbox={south:.3f},{west:.3f},{north:.3f},{east:.3f}&format=json")

# A station farther than this is weather somewhere else: a sea breeze
# or a valley fog can end within a few miles.
MAX_DISTANCE_KM = 25.0
# Reports come on the hour, and between when the weather changes; one
# older than this has missed at least one.
MAX_AGE_S = 90 * 60

# Cloud amounts in eighths of the sky, as a weather code: FEW is one or
# two oktas, SCT three or four, BKN five to seven, OVC all eight. The
# codes have no "mostly cloudy", so BKN is taken as partly cloudy rather
# than claim a sky with gaps in it is overcast.
_COVER_CODES = {
    "SKC": 0, "CLR": 0, "NSC": 0, "NCD": 0, "CAVOK": 0,
    "FEW": 1, "SCT": 2, "BKN": 2, "OVC": 3,
    # The sky hidden by fog or the like, seen only as far up as given.
    "VV": 45, "OVX": 45,
}


# Reports that cannot speak for high cloud. CAVOK and NSC say nothing of
# cloud above 5,000 ft; an automated station's ceilometer reaches about
# 12,000 ft, so its CLR or NCD means clear below that. Over such a
# report the model's high cloud still counts: a sheet of cirrus the
# station cannot see is still in the sky.
_BLIND_ABOVE = {"CAVOK", "NSC", "NCD", "CLR"}


def _sees_high_cloud(metar):
    raw = f" {metar.get('rawOb') or ''} "
    if " AUTO " in raw:
        return False
    return not (_BLIND_ABOVE & {metar.get("cover"), *(
        layer.get("cover") for layer in metar.get("clouds") or [])})


def _cover_code(percent):
    """Cloud cover as the model labels it: under a fifth clear, under
    half mostly clear, under four fifths partly cloudy, else overcast."""
    return 0 if percent < 20 else 1 if percent < 50 else 2 if percent < 80 else 3


def _intensity(token, light, moderate, heavy):
    return light if token.startswith("-") else heavy if token.startswith("+") else moderate


def _weather_token_code(token):
    """The weather code for one METAR present-weather group, or None."""
    core = token.lstrip("+-")
    if core.startswith("VC") or core.startswith("RE"):
        return None   # in the vicinity, or recent: not overhead now
    if "TS" in core:
        return 96 if ("GR" in core or "GS" in core) else 95
    if core.startswith("FZ"):
        if "RA" in core:
            return _intensity(token, 66, 67, 67)
        if "DZ" in core:
            return _intensity(token, 56, 57, 57)
        if "FG" in core:
            return 48
    if core.startswith("SH"):
        if "SN" in core:
            return _intensity(token, 85, 86, 86)
        return _intensity(token, 80, 81, 82)
    if "SN" in core:
        return _intensity(token, 71, 73, 75)
    if any(p in core for p in ("SG", "IC", "PL")):
        return 77
    if "RA" in core or "UP" in core:
        return _intensity(token, 61, 63, 65)
    if "DZ" in core:
        return _intensity(token, 51, 53, 55)
    if core == "FG":   # not MIFG, BCFG or PRFG: shallow or in patches
        return 45
    return None


# The weather codes that name precipitation or fog, most severe last:
# where a report has two groups, the heavier one is the headline.
_SEVERITY = [45, 48, 51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 71, 73, 75, 77,
             80, 81, 82, 85, 86, 95, 96, 99]


def metar_weather_code(metar: dict[str, Any]) -> int | None:
    """A METAR, as the Aviation Weather Center's JSON gives it, as a
    WMO weather code: its present weather where it has any, else its
    sky cover. None when it reports neither."""
    codes = [c for c in (_weather_token_code(t)
                         for t in (metar.get("wxString") or "").split())
             if c is not None]
    if codes:
        return max(codes, key=_SEVERITY.index)
    covers = [layer.get("cover") for layer in metar.get("clouds") or []]
    covers.append(metar.get("cover"))
    known = [_COVER_CODES[c] for c in covers if c in _COVER_CODES]
    if not known:
        return None
    return 45 if 45 in known else max(known)


def _distance_km(lat1, lng1, lat2, lng2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(a))


def _fetch_reports(url, timeout):
    # Where there is no station in the box the service answers 204 with
    # no body: no reports, and worth caching as such.
    body = fetch_bytes(url, timeout=timeout)
    return json.loads(body) if body.strip() else []


def fetch_metars(lat: float, lng: float) -> list[dict[str, Any]]:
    """The latest METAR from each station within reach. Cached 10 min."""
    span = MAX_DISTANCE_KM / 111.0
    lng_span = span / max(math.cos(math.radians(lat)), 0.05)
    url = _METAR_URL.format(south=lat - span, north=lat + span,
                            west=lng - lng_span, east=lng + lng_span)
    cache_file = cache_dir("weather", f"metar_{location_cache_key(lat, lng)}.json")
    reports = fetch_json_cached(cache_file, 600, url, timeout=6, fallback=[],
                                fetch=_fetch_reports)
    return reports if isinstance(reports, list) else []


def nearest_observation(lat: float, lng: float, reports: list[dict[str, Any]],
                        now: float | None = None) -> dict[str, Any] | None:
    """The closest recent report that says what the sky is doing, as
    {code, station, name, distance_km, time, sees_high_cloud}; None where there is none
    within MAX_DISTANCE_KM and MAX_AGE_S."""
    now = time.time() if now is None else now
    best = None
    for metar in reports:
        try:
            distance = _distance_km(lat, lng, float(metar["lat"]), float(metar["lon"]))
            age = now - float(metar["obsTime"])
        except (KeyError, TypeError, ValueError):
            continue
        if distance > MAX_DISTANCE_KM or not -600 <= age <= MAX_AGE_S:
            continue
        code = metar_weather_code(metar)
        if code is None:
            continue
        if best is None or distance < best["distance_km"]:
            best = {"code": code, "station": metar.get("icaoId") or "",
                    "name": metar.get("name") or "",
                    "distance_km": round(distance, 1),
                    "time": int(metar["obsTime"]),
                    "sees_high_cloud": _sees_high_cloud(metar)}
    return best


def fetch_observation(lat: float, lng: float) -> dict[str, Any] | None:
    """The nearest usable station report, or None."""
    try:
        return nearest_observation(lat, lng, fetch_metars(lat, lng))
    except Exception as exc:
        log_failure("weather", "station observation", exc,
                    fallback="the model's current condition")
        return None


def apply_observation(data: dict[str, Any] | None,
                      observation: dict[str, Any] | None) -> dict[str, Any] | None:
    """The forecast with a station's sky in place of the model's current
    weather code, and the station noted beside it."""
    if not data or not observation:
        return data
    current = data.get("current")
    if not isinstance(current, dict):
        return data
    code = observation["code"]
    high = current.get("cloud_cover_high")
    if code <= 3 and not observation.get("sees_high_cloud") and high is not None:
        code = max(code, _cover_code(high))
    current.setdefault("model_weather_code", current.get("weather_code"))
    current["weather_code"] = code
    current["observed"] = {k: observation[k]
                           for k in ("station", "name", "distance_km", "time")}
    return data
