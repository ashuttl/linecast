"""Alerts from MET Norway."""

from linecast._cache import location_cache_key
from linecast._paths import cache_dir
from linecast.weather.alert_feeds import _cached_feed


def fetch(lat, lng, lang="en", address=None):
    """Fetch MetAlerts from MET Norway. Cached 15min.

    Uses api.met.no with lat/lon coordinate filtering.
    """
    url = (
        f"https://api.met.no/weatherapi/metalerts/2.0/current.json"
        f"?lat={lat}&lon={lng}"
    )
    return _cached_feed(
        cache_dir("weather") / f"alerts_no_{location_cache_key(lat, lng)}.json",
        url, _parse_metno, timeout=10)


def _parse_metno(data):
    """MET Norway's features as normalized alerts, one per event."""
    alerts = []
    seen = set()
    for feature in data.get("features") or []:
        props = feature.get("properties") or {}
        event = (props.get("event") or "").capitalize()
        severity = props.get("severity") or ""
        if not event:
            continue
        dedup_key = (event, severity)
        if dedup_key in seen:
            continue
        seen.add(dedup_key)
        when = (feature.get("when") or {}).get("interval") or ["", ""]
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
    return alerts
