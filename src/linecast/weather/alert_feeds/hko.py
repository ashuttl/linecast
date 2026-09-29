"""Alerts from the Hong Kong Observatory."""

from linecast._i18n import base_language
from linecast._paths import cache_dir
from linecast.weather.sources import _cached_feed

# The warnsum feed is a dict keyed by warning type; each entry names the
# warning and carries a code, which for rainstorms and tropical cyclones
# says how bad (amber/red/black; signal 1/3/8/9/10). The Observatory
# publishes it in English and in both Chinese scripts.
HKO_WARNINGS_URL = ("https://data.weather.gov.hk/weatherAPI/opendata/"
                    "weather.php?dataType=warnsum&lang={lang}")
_HKO_LANG = {"zh": "sc", "zh-Hant": "tc"}

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


def _parse_hko_warnsum(data, lang="en"):
    """Parse HKO warnsum JSON dict into normalised alert list."""
    site = _HKO_LANG.get(base_language(lang), "en")
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
            "url": f"https://www.hko.gov.hk/{site}/detail.htm",
        })
    return alerts


def fetch(lat, lng, lang="en", address=None):
    """Fetch active HKO weather warnings (Hong Kong), in the reader's
    language where the Observatory speaks it. The warnings are the
    whole territory's, wherever in it the place is. Cached 10min."""
    feed = _HKO_LANG.get(base_language(lang), "en")
    return _cached_feed(
        cache_dir("weather") / f"alerts_hk_{feed}.json", HKO_WARNINGS_URL.format(lang=feed),
        lambda data: _parse_hko_warnsum(data, lang), max_age=600, timeout=10)
