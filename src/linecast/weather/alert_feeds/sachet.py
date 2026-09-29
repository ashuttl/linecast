"""Alerts from SACHET, India's national aggregator of CAP alerts."""

import re
from datetime import datetime, timedelta, timezone

from linecast._log import log_failure
from linecast._paths import cache_dir
from linecast.weather.alert_feeds.cap import local_tag, sweep_cap_files
from linecast.weather.alert_feeds import _cached_feed, _expired

_SACHET_FEED_URL = "https://sachet.ndma.gov.in/cap_public_website/FetchAllAlertDetails"
_SACHET_CAP_URL = ("https://sachet.ndma.gov.in/cap_public_website/FetchXMLFile"
                   "?identifier={identifier}")

_IST = timezone(timedelta(hours=5, minutes=30))

# The feed's colour is the fallback when an alert's CAP file is out of
# reach; the file itself carries the standard CAP severity.
_SACHET_COLORS = {"red": "Extreme", "orange": "Severe", "yellow": "Moderate"}

_SACHET_MONTHS = {
    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
    "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
}


def fetch(lat, lng, lang="en", address=None):
    """Fetch active alerts from SACHET, India's national CAP aggregator.

    One national feed lists every active alert — IMD weather warnings,
    CWC flood bulletins, state SDMA nowcasts — with a centroid and the
    area covered, so a single request (cached 15min) serves any location
    in the country. An alert is kept when the user sits within the disc
    of that area, plus slack for the shapes a disc misses.

    The feed's push text is often in a regional language alone; each
    alert's CAP file carries an info block per language, English always
    among them, so the kept alerts are refined from their CAP files
    (cached per alert — a SACHET update is a new identifier).
    """
    import math

    feed = _cached_feed(cache_dir("weather") / "alerts_in_feed.json",
                        _SACHET_FEED_URL, _sachet_feed, timeout=15)

    cos_lat = math.cos(math.radians(lat))
    candidates = []
    for entry in feed:
        if not isinstance(entry, dict):
            continue
        try:
            lng_str, lat_str = str(entry.get("centroid", "")).split(",")
            clat, clng = float(lat_str), float(lng_str)
        except ValueError:
            continue
        try:
            area = float(entry.get("area_covered") or 0.0)
        except (TypeError, ValueError):
            area = 0.0
        radius_km = math.sqrt(area / math.pi) if area > 0 else 0.0
        dist_km = 111.32 * math.hypot(lat - clat, (lng - clng) * cos_lat)
        if dist_km <= radius_km + 25.0:
            candidates.append((dist_km, entry))

    # Nearest first, and a ceiling on CAP fetches: past a dozen alerts on
    # one spot the marginal one adds latency, not information.
    candidates.sort(key=lambda pair: pair[0])
    now = datetime.now(timezone.utc)
    alerts = []
    seen = set()
    for _dist, entry in candidates[:12]:
        alert = (_sachet_alert_from_cap(entry, lang)
                 or _sachet_alert_from_feed(entry))
        if alert is None:
            continue
        # The cached feed can outlive an alert by up to 15min. fetch_alerts
        # drops a lapsed alert too, but here it comes before the dedup,
        # where it could stand in for the live one issued in its place.
        if _expired(alert, now):
            continue
        dedup_key = (alert["event"], alert["severity"], alert["headline"])
        if dedup_key in seen:
            continue
        seen.add(dedup_key)
        alerts.append(alert)

    # India issues nowcasts by the hundred a day; without a sweep the
    # cache would keep every one this user was ever near.
    sweep_cap_files("alerts_in_cap_", {str(entry.get("identifier"))
                                       for entry in feed if isinstance(entry, dict)},
                    "SACHET")
    return alerts


def _sachet_feed(feed):
    """The feed's entries, kept as they come: each alert is refined from
    its CAP file on every run. The feed is a bare list; anything else is
    not an answer."""
    if not isinstance(feed, list):
        raise ValueError(f"SACHET feed is a {type(feed).__name__}, not a list")
    return feed


def _sachet_datetime(s):
    """A SACHET feed time ("Sun Aug 30 21:00:00 IST 2026") as ISO 8601.

    Parsed by hand: strptime's %a and %b follow the process locale, and
    the feed's English month names must parse on a German machine too.
    """
    m = re.match(r"\w+ (\w+) (\d+) (\d+):(\d+):(\d+) IST (\d+)", str(s or ""))
    if not m:
        return ""
    month = _SACHET_MONTHS.get(m.group(1))
    if month is None:
        return ""
    day, hour, minute, second, year = (int(g) for g in m.groups()[1:])
    try:
        dt = datetime(year, month, day, hour, minute, second, tzinfo=_IST)
    except ValueError:
        return ""
    return dt.isoformat()


def _sachet_alert_from_feed(entry):
    """A normalized alert from a SACHET feed entry alone."""
    event = str(entry.get("disaster_type") or "").strip()
    message = str(entry.get("warning_message") or "").strip()
    if not event and not message:
        return None
    severity = _SACHET_COLORS.get(
        str(entry.get("severity_color") or "").lower(), "Moderate")
    return {
        "event": event or "Alert",
        "headline": message or event,
        "description": message,
        "effective": _sachet_datetime(entry.get("effective_start_time")),
        "expires": _sachet_datetime(entry.get("effective_end_time")),
        "severity": severity,
        "url": "https://sachet.ndma.gov.in/",
    }


def _sachet_cap_infos(identifier):
    """The info blocks of one SACHET CAP file, as dicts; None on failure.

    Cached without expiry: an alert's CAP file never changes — SACHET
    issues updates under a new identifier — and the per-identifier files
    are swept once the alert leaves the feed (cap.sweep_cap_files).
    """
    from xml.etree import ElementTree

    from linecast._http import fetch_bytes_cached

    # A shorter timeout than usual: these fetches run one after another,
    # and a dozen of them must not hold the dashboard for two minutes.
    raw = fetch_bytes_cached(
        cache_dir("weather") / f"alerts_in_cap_{identifier}.xml", None,
        _SACHET_CAP_URL.format(identifier=identifier), timeout=6,
        provider="weather/alerts",
    )
    if not raw:
        return None
    try:
        root = ElementTree.fromstring(raw)
    except ElementTree.ParseError as exc:
        log_failure("weather/alerts", f"CAP parse of {identifier}", exc,
                    fallback="feed entry used")
        return None

    infos = []
    for info_el in root.iter():
        if local_tag(info_el.tag) != "info":
            continue
        info = {}
        for child in info_el:
            tag = local_tag(child.tag)
            if tag in ("language", "event", "severity", "headline",
                       "description", "instruction", "effective", "onset",
                       "expires"):
                info[tag] = (child.text or "").strip()
        infos.append(info)
    return infos or None


# SACHET tags a CAP info block with its own uppercase language code.
# Most are the ISO 639-1 code upcased ("HI", "MR"); these are not.
_SACHET_CAP_LANGS = {"od": "or", "tl": "te"}


def _sachet_cap_lang(code):
    """A SACHET CAP language code ("en-IN", "HI", "TL") as ISO 639-1."""
    code = code.partition("-")[0].lower()
    return _SACHET_CAP_LANGS.get(code, code)


def _sachet_alert_from_cap(entry, lang):
    """A normalized alert from a SACHET CAP file, or None to fall back.

    An alert often carries its info in the state language besides
    English; --lang picks it, so `--lang hi` reads SACHET's own Hindi
    even though the app's UI does not speak it.
    """
    identifier = entry.get("identifier")
    if not identifier:
        return None
    infos = _sachet_cap_infos(identifier)
    if not infos:
        return None

    def _in_lang(iso):
        return next((i for i in infos
                     if _sachet_cap_lang(i.get("language", "")) == iso), None)
    info = _in_lang(lang.lower()) or _in_lang("en") or infos[0]

    event = info.get("event", "").strip()
    headline = " ".join(info.get("headline", "").split())
    description = " ".join(info.get("description", "").split())
    instruction = " ".join(info.get("instruction", "").split())
    if not event and not headline:
        return None
    if instruction and instruction.lower() != "please follow sdma guidelines.":
        description = f"{description} {instruction}".strip()
    severity = info.get("severity", "").capitalize()
    if severity not in ("Extreme", "Severe", "Moderate", "Minor"):
        severity = _SACHET_COLORS.get(
            str(entry.get("severity_color") or "").lower(), "Moderate")
    return {
        "event": event or "Alert",
        "headline": headline or event,
        "description": description or headline,
        "effective": info.get("onset") or info.get("effective") or "",
        "expires": info.get("expires", ""),
        "severity": severity,
        "url": "https://sachet.ndma.gov.in/",
    }
