"""The Common Alerting Protocol, as the feeds that send it write it: a
CAP file's tags, its areas' polygons and its times, and the CAP files
kept for SACHET's and MetService's alerts, one per alert."""

from datetime import timezone

from linecast._log import log_failure
from linecast._paths import cache_dir
from linecast._timefmt import from_iso


def cap_polygons(area):
    """The closed rings on a CAP area, as [[(lat, lng), ...], ...].

    CAP writes a ring as space-separated "lat,lon" pairs; MeteoAlarm
    carries them in a list, one per ring. Anything unparseable is skipped
    rather than raised on -- a malformed ring must not cost the user an
    alert, and an area with no usable ring falls back to areaDesc.
    """
    raw = area.get("polygon")
    if not raw:
        return []
    rings = []
    for ring in (raw if isinstance(raw, list) else [raw]):
        points = []
        for pair in str(ring).split():
            lat_str, _, lng_str = pair.partition(",")
            try:
                points.append((float(lat_str), float(lng_str)))
            except ValueError:
                continue
        if len(points) >= 3:
            rings.append(points)
    return rings


def point_in_ring(lat, lng, ring):
    """True when (lat, lng) falls inside a closed ring. The test is
    meteoalarm_regions', which holds it for the regions it bakes."""
    from linecast.weather.alert_feeds import meteoalarm_regions
    return meteoalarm_regions.point_in_ring(lat, lng, ring)


def parse_iso_aware(iso_str):
    """An ISO timestamp as an aware UTC datetime, or None. A trailing Z,
    which fromisoformat reads only from Python 3.11, is UTC."""
    if not isinstance(iso_str, str):
        return None
    try:
        dt = from_iso(iso_str)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return None
    return dt.astimezone(timezone.utc)


def local_tag(tag):
    """An XML tag without its namespace: "{urn:oasis:names:tc:emergency:cap:1.2}info"
    is "info"."""
    return tag.rsplit("}", 1)[-1]


def sweep_cap_files(prefix, live, service):
    """Drop the cached CAP files, named `prefix` + identifier, of the
    alerts no longer in `service`'s feed, whose identifiers are `live`.

    A CAP file is cached without expiry, since an update to an alert is
    a new alert with an identifier of its own; without a sweep the cache
    would keep every alert this user was ever near.
    """
    try:
        for path in cache_dir("weather").glob(f"{prefix}*.xml"):
            if path.stem[len(prefix):] not in live:
                path.unlink(missing_ok=True)
    except OSError as exc:
        log_failure("cache", f"sweep of {service} CAP files", exc,
                    fallback="left in place")
