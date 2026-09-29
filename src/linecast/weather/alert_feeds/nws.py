"""Alerts from the US National Weather Service."""

from linecast._cache import location_cache_key
from linecast._paths import cache_dir
from linecast.weather.alert_feeds.cap import parse_iso_aware
from linecast.weather.sources import _cached_feed


def fetch(lat, lng, lang="en", address=None):
    """Fetch active NWS alerts (US). Cached 15min."""
    return _cached_feed(
        cache_dir("weather") / f"alerts_{location_cache_key(lat, lng)}.json",
        f"https://api.weather.gov/alerts/active?point={lat},{lng}",
        _parse_nws, headers={"Accept": "application/geo+json"}, timeout=10)


def _parse_nws(data):
    """NWS's GeoJSON as normalized alerts, actual ones only."""
    features = data.get("features", [])
    alerts = []
    for feature in features:
        props = feature.get("properties") or {}
        if props.get("status") != "Actual":
            continue
        alerts.append({
            "event": props.get("event", ""),
            "headline": props.get("headline", ""),
            "description": props.get("description", ""),
            **_nws_window(props),
            "severity": props.get("severity", ""),
            "url": props.get("web", ""),
        })
    return alerts


def _nws_window(props):
    """The effective and expires of a normalized alert from NWS alert
    properties: when the hazard begins and ends.

    NWS's own effective and expires are the bulletin's: issued now, good
    until the next update. A High Wind Watch for Saturday is issued on
    Wednesday and expires Thursday morning, to be reissued. The event
    runs from onset to ends. ends is null when there is no set end, and
    then expires stands in, unless it falls before the onset, which says
    nothing about the event at all.
    """
    start = props.get("onset") or props.get("effective") or ""
    end = props.get("ends") or props.get("expires") or ""
    if not props.get("ends"):
        onset, expires = parse_iso_aware(start), parse_iso_aware(end)
        if onset and expires and expires <= onset:
            end = ""
    return {"effective": start, "expires": end}
