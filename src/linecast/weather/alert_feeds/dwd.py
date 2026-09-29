"""Alerts from the Deutscher Wetterdienst, by way of Bright Sky."""

from linecast._cache import location_cache_key
from linecast._paths import cache_dir
from linecast.weather.sources import _cached_feed


def fetch(lat, lng, lang="en", address=None):
    """Fetch DWD alerts via Bright Sky API (Germany). Cached 15min."""
    return _cached_feed(
        cache_dir("weather") / f"alerts_de_{location_cache_key(lat, lng)}_{lang}.json",
        f"https://api.brightsky.dev/alerts?lat={lat}&lon={lng}",
        lambda data: _parse_brightsky(data, lang), timeout=10)


def _parse_brightsky(data, lang):
    """Bright Sky's alerts, normalized."""
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
            "effective": a.get("onset") or a.get("effective") or "",
            "expires": a.get("expires", ""),
            "severity": severity,
            "url": "",
        })
    return alerts
