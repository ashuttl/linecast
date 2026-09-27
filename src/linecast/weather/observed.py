"""The sky as a nearby station last saw it, over the model's guess.

The forecast's current condition is the model's for the quarter hour,
and a model can keep a fog deck or a shower for hours after the sky
has cleared. Airports report what is overhead at least hourly, in
METARs, and the Aviation Weather Center serves the world's as JSON
without a key. Where a station is close and its report recent, its
sky stands in for the model's weather code and cloud cover; the
temperature, wind and the rest stay the model's, which the graph and
the prose agree with.
"""

import json
import math
import re
import time
from typing import Any

from linecast._cache import location_cache_key
from linecast._http import fetch_bytes, fetch_json_cached
from linecast._paths import cache_dir
from linecast._plaintext import plain_text
from linecast._runtime import log_failure
from linecast.weather.cover import REPORT_COVER

_METAR_URL = ("https://aviationweather.gov/api/data/metar"
              "?bbox={south:.3f},{west:.3f},{north:.3f},{east:.3f}&format=json")
_HISTORY_URL = "https://aviationweather.gov/api/data/metar?ids={station}&hours=25&format=json"

# A station farther than this is weather somewhere else: a sea breeze
# or a valley fog can end within a few miles.
MAX_DISTANCE_KM = 25.0
# Reports come on the hour, and between when the weather changes; one
# older than this has missed at least one.
MAX_AGE_S = 90 * 60

# A report's cloud amounts, in eighths of the sky: FEW is one or two,
# SCT three or four, BKN five to seven, OVC all eight (REPORT_COVER).
# These say there is none, or none the report speaks for.
_CLEAR = {"SKC", "CLR", "NSC", "NCD", "CAVOK"}
# The sky hidden by fog or the like, seen only as far up as given.
_OBSCURED = {"VV", "OVX"}


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


def _automated(metar):
    """Whether a report is from an automated station in the US manner,
    AO1 or AO2: the stations whose reports carry what their gauge caught."""
    raw = f" {metar.get('rawOb') or ''} "
    return " AO1 " in raw or " AO2 " in raw


def _cover_code(percent):
    """A cloud cover as the weather code Open-Meteo gives it: under a
    fifth clear, under half mostly clear, under four fifths partly
    cloudy, else overcast. The code stays in Open-Meteo's terms; the
    name shown is the cover's (cover.py)."""
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


def metar_sky(metar: dict[str, Any]) -> tuple[int, float | None] | None:
    """A METAR, as the Aviation Weather Center's JSON gives it, as a WMO
    weather code and a cloud cover in percent: the code its present
    weather where it has any, else its sky's. None when it reports
    neither."""
    covers = [layer.get("cover") for layer in metar.get("clouds") or []]
    covers.append(metar.get("cover"))
    amounts = [REPORT_COVER[c] for c in covers if c in REPORT_COVER]
    cover = (100 if _OBSCURED & set(covers) else max(amounts) if amounts
             else 0 if _CLEAR & set(covers) else None)
    codes = [c for c in (_weather_token_code(t)
                         for t in (metar.get("wxString") or "").split())
             if c is not None]
    if codes:
        return max(codes, key=_SEVERITY.index), cover
    if _OBSCURED & set(covers):
        return 45, cover
    if cover is None:
        return None
    return _cover_code(cover), cover


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
    {code, cover, station, name, distance_km, time, sees_high_cloud,
    automated}; None where there is none within MAX_DISTANCE_KM and
    MAX_AGE_S."""
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
        sky = metar_sky(metar)
        if sky is None:
            continue
        if best is None or distance < best["distance_km"]:
            best = {"code": sky[0], "cover": sky[1],
                    "station": plain_text(metar.get("icaoId") or ""),
                    "name": plain_text(metar.get("name") or ""),
                    "distance_km": round(distance, 1),
                    "time": int(metar["obsTime"]),
                    "sees_high_cloud": _sees_high_cloud(metar),
                    "automated": _automated(metar)}
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
                      observation: dict[str, Any] | None,
                      precipitation: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """The forecast with a station's sky in place of the model's current
    weather code and cloud cover, and the station noted beside it; with
    what its gauge caught in the last day, where it has one, for the
    prose to give in place of the model's hours."""
    if not data or not observation:
        return data
    if precipitation:
        data["observed_precipitation"] = precipitation
    current = data.get("current")
    if not isinstance(current, dict):
        return data
    code, cover = observation["code"], observation.get("cover")
    high = current.get("cloud_cover_high")
    if (code <= 3 and cover is not None and high is not None
            and not observation.get("sees_high_cloud") and high > cover):
        code, cover = _cover_code(high), high
    current.setdefault("model_weather_code", current.get("weather_code"))
    current.setdefault("model_cloud_cover", current.get("cloud_cover"))
    current["weather_code"] = code
    if cover is not None:
        current["cloud_cover"] = cover
    current["observed"] = {k: observation[k]
                           for k in ("station", "name", "distance_km", "time")}
    return data


# What a station's rain gauge caught.  US automated stations put it in
# their remarks, and the Aviation Weather Center decodes it: `precip`,
# the inches since the last routine report, in each report, and the
# three- and six-hour totals in the reports that close those periods.

# A trace, too little to measure, which the Aviation Weather Center gives
# as half a hundredth.  It adds nothing to a total.
_TRACE = 0.005
# An hourly station sends 24 routine reports a day.  With fewer than this
# it missed hours, and what fell in them; with more than a day and a bit
# of them it reports more often than hourly, and each report's amount is
# no longer the hour's.
_MIN_ROUTINE = 20
_MAX_ROUTINE = 26
# The precipitation a report's remarks say began or ended during the
# hour, as in RAB0957 or SNB12E40: the weather that fell and stopped
# again between two reports.
_BEGAN_OR_ENDED = re.compile(r"(?<![A-Z])((?:FZ|SH)?(?:RA|DZ|SN|SG|PL|GS|GR|IC|UP))(?=[BE]\d)")
_SNOW_CODES = {71, 73, 75, 77, 85, 86}
_FREEZING_CODES = {56, 57, 66, 67}
_AMOUNTS = ("precip", "pcp3hr", "pcp6hr", "pcp24hr")


def _precip_codes(metar):
    """The weather codes of the precipitation a report names: falling at
    the time of the report, or begun or ended in the hour before it."""
    _, _, remarks = (metar.get("rawOb") or "").partition(" RMK ")
    tokens = (metar.get("wxString") or "").split() + _BEGAN_OR_ENDED.findall(remarks)
    return {c for c in map(_weather_token_code, tokens) if c is not None and c >= 51}


def _hour_kind(metar):
    """What a report's precipitation fell as: "snow", "mix" for anything
    freezing or for snow with rain, or "rain", which is also what an
    amount with no weather named is taken for."""
    codes = _precip_codes(metar)
    snow = codes & _SNOW_CODES
    if codes & _FREEZING_CODES or (snow and codes - snow):
        return "mix"
    return "snow" if snow else "rain"


def station_precipitation(reports: list[dict[str, Any]],
                          now: float | None = None) -> dict[str, Any] | None:
    """What a station's gauge caught in the last 24 hours, from its
    reports as the Aviation Weather Center's JSON gives them, as
    {station, precip, rain_hours, snow_hours, mix_hours}: the total in
    inches, and the hours with a measurable amount by what it fell as.

    None where the reports cannot say: hours are missing, the gauge is
    out (PNO) or its amount could not be read (P////), or the station
    gave no amount all day and either named rain it did not measure or
    cannot tell rain from nothing (AO1).  A station that tells them
    apart (AO2) and named no precipitation all day was dry."""
    now = time.time() if now is None else now
    day = []
    for metar in reports:
        try:
            when = float(metar["obsTime"])
        except (KeyError, TypeError, ValueError):
            continue
        if now - 24 * 3600 < when <= now + 600:
            day.append((when, metar))
    if not day:
        return None
    day.sort(key=lambda item: item[0])
    # One routine report an hour: a correction replaces the report it corrects
    routine = {}
    for when, metar in day:
        if metar.get("metarType") == "METAR":
            routine[metar.get("reportTime") or when] = (when, metar)
    if not _MIN_ROUTINE <= len(routine) <= _MAX_ROUTINE:
        return None
    raws = [f" {metar.get('rawOb') or ''} " for _, metar in day]
    if any(" PNO " in raw or " P//// " in raw or " 6//// " in raw for raw in raws):
        return None
    station = plain_text(day[-1][1].get("icaoId") or "")
    if not any(metar.get(k) is not None for _, metar in day for k in _AMOUNTS):
        if all(" AO2 " in raw for raw in raws) and not any(_precip_codes(m) for _, m in day):
            return {"station": station, "precip": 0.0,
                    "rain_hours": 0, "snow_hours": 0, "mix_hours": 0}
        return None
    hours = [metar for _, metar in sorted(routine.values(), key=lambda item: item[0])]
    # A special report since the last routine one carries what has fallen
    # since that report, the hour so far
    last_when, last = day[-1]
    if last.get("metarType") == "SPECI" and last_when > max(routine.values(),
                                                              key=lambda item: item[0])[0]:
        hours.append(last)
    total = 0.0
    kinds = {"rain": 0, "snow": 0, "mix": 0}
    for metar in hours:
        try:
            amount = float(metar.get("precip") or 0)
        except (TypeError, ValueError):
            return None
        if amount > _TRACE:
            total += amount
            kinds[_hour_kind(metar)] += 1
    return {"station": station, "precip": round(total, 2),
            "rain_hours": kinds["rain"], "snow_hours": kinds["snow"],
            "mix_hours": kinds["mix"]}


def fetch_station_history(station: str) -> list[dict[str, Any]]:
    """A station's reports, routine and special, over the last 25 hours.
    Cached 10 min."""
    if not re.fullmatch(r"[A-Z0-9]{3,5}", station or ""):
        return []
    cache_file = cache_dir("weather", f"metar_{station}_day.json")
    reports = fetch_json_cached(cache_file, 600, _HISTORY_URL.format(station=station),
                                timeout=6, fallback=[], fetch=_fetch_reports)
    return reports if isinstance(reports, list) else []


def fetch_station_precipitation(observation: dict[str, Any] | None) -> dict[str, Any] | None:
    """What the station behind the current conditions caught in its gauge
    over the last day, or None.  Only a US-style automated station
    reports its gauge, so only one is asked for its day of reports."""
    if not observation or not observation.get("automated"):
        return None
    try:
        return station_precipitation(fetch_station_history(observation["station"]))
    except Exception as exc:
        log_failure("weather", "station precipitation", exc,
                    fallback="the model's last 24 hours")
        return None
