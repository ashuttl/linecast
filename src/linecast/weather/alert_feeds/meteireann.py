"""Alerts from Met Éireann."""

import re
from datetime import datetime

from linecast._cache import location_cache_key
from linecast._log import log_failure
from linecast._paths import cache_dir
from linecast.weather.alert_feeds import _cached_feed

# Met Éireann files a national warning under county codes, the FIPS
# codes (EI07 is Dublin), with a code of a digit more for some islands
# (EI101 off Galway; EI031, though it starts like Clare's, is the Aran
# Islands, so Galway's too). Keyed by the county's ISO 3166-2 code,
# which Nominatim gives as ISO3166-2-lvl6 (IE-D), with the English
# name for an address that carries only "County Dublin".
_METEIREANN_COUNTIES = {
    "CW": ("Carlow", ("EI01",)),
    "CN": ("Cavan", ("EI02",)),
    "CE": ("Clare", ("EI03",)),
    "CO": ("Cork", ("EI04", "EI041", "EI042", "EI043")),
    "DL": ("Donegal", ("EI06", "EI061")),
    "D": ("Dublin", ("EI07",)),
    "G": ("Galway", ("EI10", "EI101", "EI102", "EI103", "EI031", "EI032", "EI033")),
    "KY": ("Kerry", ("EI11", "EI111", "EI112")),
    "KE": ("Kildare", ("EI12",)),
    "KK": ("Kilkenny", ("EI13",)),
    "LM": ("Leitrim", ("EI14",)),
    "LS": ("Laois", ("EI15",)),
    "LK": ("Limerick", ("EI16",)),
    "LD": ("Longford", ("EI18",)),
    "LH": ("Louth", ("EI19",)),
    "MO": ("Mayo", ("EI20", "EI201", "EI202", "EI203", "EI204")),
    "MH": ("Meath", ("EI21",)),
    "MN": ("Monaghan", ("EI22",)),
    "OY": ("Offaly", ("EI23",)),
    "RN": ("Roscommon", ("EI24",)),
    "SO": ("Sligo", ("EI25",)),
    "TA": ("Tipperary", ("EI26",)),
    "WD": ("Waterford", ("EI27",)),
    "WH": ("Westmeath", ("EI29",)),
    "WX": ("Wexford", ("EI30",)),
    "WW": ("Wicklow", ("EI31",)),
}
_METEIREANN_CODES = {c for _name, codes in _METEIREANN_COUNTIES.values() for c in codes}


def _meteireann_county(address):
    """The ISO code (D, CO, ...) of the county a Nominatim address is in, or ""."""
    if not address:
        return ""
    region = str(address.get("ISO3166-2-lvl6", ""))
    if region.startswith("IE-") and region[3:] in _METEIREANN_COUNTIES:
        return region[3:]
    county = str(address.get("county", "")).lower()
    if county.startswith("county "):
        county = county[len("county "):]
    for iso, (name, _codes) in _METEIREANN_COUNTIES.items():
        if county == name.lower():
            return iso
    return ""


def _meteireann_warning_applies(regions, county):
    """Whether a warning filed for `regions` is for the reader's county.

    A warning with no regions (a gale at sea, most environmental ones)
    is for everyone, as is one whose regions are not all county codes
    this table knows: a code it has never seen should show a warning,
    not hide it. When the county is unknown, every warning applies.
    """
    if not county or not isinstance(regions, list) or not regions:
        return True
    codes = [r.strip().upper() for r in regions if isinstance(r, str)]
    if len(codes) != len(regions) or not all(c in _METEIREANN_CODES for c in codes):
        return True
    return any(c in _METEIREANN_COUNTIES[county][1] for c in codes)


def fetch(lat, lng, lang="en", address=None):
    """Fetch active warnings from Met Éireann (Ireland). Cached 15min.

    The feed is the whole country's. A national warning names the
    counties it is for, and is shown only in those when the address
    says which county the reader is in.
    """
    county = _meteireann_county(address)
    return _cached_feed(
        cache_dir("weather") / f"alerts_ie_{location_cache_key(lat, lng)}.json",
        "https://prodapi.metweb.ie/warnings",
        lambda data: _parse_meteireann(data, county),
        headers={"Accept": "application/json"}, timeout=10)


def _parse_meteireann(data, county):
    """Met Éireann's warnings, the county's and everyone's, normalized."""
    warnings_data = data.get("warnings") or {}
    alerts = []
    seen = set()
    for category in ("national", "marine", "environmental"):
        # a category with nothing in force can be null rather than empty
        for w in warnings_data.get(category) or []:
            headline = w.get("headline") or ""
            if not headline:
                continue
            desc = w.get("description") or w.get("text") or ""
            if desc.lower() in ("nil", ""):
                desc = ""
            if not _meteireann_warning_applies(w.get("regions"), county):
                continue
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

    Input: "HH:MM Weekday DD/MM/YYYY" -> "YYYY-MM-DDTHH:MM:00+01:00"

    The feed gives Irish local time with no offset. The offset is added
    so the time can be compared with the clock as well as shown; when
    the zone data is missing the time stays naive, as it always was.
    """
    if not s:
        return ""
    m = re.match(r"(\d{2}):(\d{2})\s+\w+\s+(\d{2})/(\d{2})/(\d{4})", s)
    if not m:
        return ""
    hour, minute, day, month, year = (int(g) for g in m.groups())
    try:
        dt = datetime(year, month, day, hour, minute)
    except ValueError:
        return ""
    try:
        from zoneinfo import ZoneInfo
        dt = dt.replace(tzinfo=ZoneInfo("Europe/Dublin"))
    except Exception as exc:
        log_failure("weather/alerts", "Irish time zone", exc,
                    fallback="time left without an offset")
    return dt.isoformat()
