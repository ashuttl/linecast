"""Alerts from MetService, New Zealand's weather service."""

from datetime import datetime, timezone

from linecast._log import log_failure
from linecast._paths import cache_dir
from linecast.weather.alert_feeds.cap import (
    cap_polygons, local_tag, point_in_ring, sweep_cap_files,
)
from linecast.weather.alert_feeds import _ALERT_MAX_AGE, _expired, _note_alert_cache

_METSERVICE_FEED_URL = "https://alerts.metservice.com/cap/rss"
_METSERVICE_CAP_URL = "https://alerts.metservice.com/cap/alert?id={identifier}"

# The ColourCode parameter carries MetService's public severity ladder;
# the CAP severity field stands in when an alert has no colour.
_METSERVICE_COLORS = {"red": "Extreme", "orange": "Severe", "yellow": "Moderate"}


def fetch(lat, lng, lang="en", address=None):
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

    feed_file = cache_dir("weather") / "alerts_nz_feed.xml"
    raw = fetch_bytes_cached(feed_file, _ALERT_MAX_AGE, _METSERVICE_FEED_URL, timeout=15,
                             provider="weather/alerts")
    _note_alert_cache(feed_file, _ALERT_MAX_AGE, bool(raw))
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
        # before the dedup, as SACHET's are
        if _expired(alert, now):
            continue
        dedup_key = (alert["event"], alert["severity"], alert["headline"])
        if dedup_key in seen:
            continue
        seen.add(dedup_key)
        alerts.append(alert)

    sweep_cap_files("alerts_nz_cap_", set(identifiers), "MetService")
    return alerts


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
        _METSERVICE_CAP_URL.format(identifier=identifier), timeout=6,
        provider="weather/alerts")
    if not raw:
        return None
    try:
        root = ElementTree.fromstring(raw)
    except ElementTree.ParseError as exc:
        log_failure("weather/alerts", f"CAP parse of {identifier}", exc,
                    fallback="skipped")
        return None

    status = msg_type = ""
    info_el = None
    for child in root:
        tag = local_tag(child.tag)
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
        tag = local_tag(child.tag)
        if tag in ("event", "severity", "headline", "description",
                   "effective", "onset", "expires", "web"):
            info[tag] = (child.text or "").strip()
        elif tag == "parameter":
            fields = {local_tag(c.tag): (c.text or "").strip() for c in child}
            if fields.get("valueName") == "ColourCode":
                colour = fields.get("value", "").lower()
        elif tag == "area":
            polygons = [(c.text or "") for c in child
                        if local_tag(c.tag) == "polygon"]
            rings.extend(cap_polygons({"polygon": polygons}))

    # The polygon is the warning's own account of the ground it covers;
    # a CAP file without one (rare) is taken as nationwide.
    if rings and not any(point_in_ring(lat, lng, ring) for ring in rings):
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
        "effective": info.get("onset") or info.get("effective") or "",
        "expires": info.get("expires", ""),
        "severity": severity,
        "url": info.get("web") or "https://www.metservice.com/warnings/home",
    }
