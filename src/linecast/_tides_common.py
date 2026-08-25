"""Helpers shared by the tide providers.

Every provider caches under the same directory, works in feet, picks the
nearest station the same way, and measures its y-axis range the same way;
this module holds those pieces once. The provider modules keep what is
genuinely theirs: URLs, payload shapes, and unit or timezone quirks.
"""

import re
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone, tzinfo
from pathlib import Path
from typing import Any

from linecast import _paths
from linecast._cache import read_cache, read_stale, write_cache
from linecast._geo import haversine_nm
from linecast._runtime import log_failure

M_TO_FT = 1 / 0.3048
NEAREST_STATION_CACHE_MAX_AGE = 3600
NEAREST_STATION_MAX_NM = 100
Y_RANGE_CACHE_MAX_AGE = 7 * 86400


def cache_dir() -> Path:
    """The directory every tide provider caches under."""
    return _paths.cache_dir("tides")


# ---------------------------------------------------------------------------
# Legacy cache files
# ---------------------------------------------------------------------------
# Names from before predictions and y-ranges were keyed by month: one NOAA
# file per day of predictions or extremes, and one y-range file per date
# window. Nothing reads them any more; the month-keyed files have six
# digits where these have eight.
_LEGACY_CACHE_NAME = re.compile(
    r"^(?:(?:pred|hilo)_\d+_\d{8}"
    r"|(?:chs_|tc_|qld_)?yrange_.+_\d{8}_\d{8})\.json$"
)
_swept = False


def sweep_legacy_cache(cache_dir: Path | None = None) -> None:
    """Delete the cache files the per-day layout left behind. Once per process.

    One directory listing, best effort: a file that will not go is left
    for next time, and a directory that is not there yet is fine.
    """
    global _swept
    if _swept:
        return
    _swept = True
    if cache_dir is None:
        cache_dir = _paths.cache_dir("tides")
    try:
        entries = list(cache_dir.iterdir())
    except OSError:
        return
    for path in entries:
        if _LEGACY_CACHE_NAME.match(path.name):
            try:
                path.unlink()
            except OSError:
                pass


# ---------------------------------------------------------------------------
# Calendar months
# ---------------------------------------------------------------------------
def month_start(day: date) -> date:
    """First day of the calendar month containing *day*."""
    return day.replace(day=1)


def month_after(first: date) -> date:
    """First day of the month following *first* (itself a first-of-month)."""
    return (first + timedelta(days=32)).replace(day=1)


def y_range_window(center_date: date) -> tuple[date, date, str]:
    """The span the y-axis range is measured over, as (start, end, key).

    The calendar month before *center_date*'s through the month after:
    at least 30 days either side, which covers two spring/neap cycles.
    Anchoring to the calendar instead of the date keeps the cache key
    (like "202608") the same all month, so one request serves every day
    of the month rather than a fresh 61-day request and a new file each
    day.
    """
    first = month_start(center_date)
    start = month_start(first - timedelta(days=1))
    end = month_after(month_after(first)) - timedelta(days=1)
    return start, end, f"{first:%Y%m}"


# ---------------------------------------------------------------------------
# Nearest station
# ---------------------------------------------------------------------------
def station_coords(station: dict[str, Any], lat_key: str = "lat",
                   lng_key: str = "lng") -> tuple[float, float] | None:
    """(lat, lng) as floats from a station record, or None when unusable."""
    try:
        return float(station[lat_key]), float(station[lng_key])
    except (KeyError, ValueError, TypeError):
        return None


def nearest_station(
    cache_file: Path, lat: float, lng: float,
    load_stations: Callable[[], list[dict[str, Any]] | None],
    coords: Callable[[dict[str, Any]], tuple[float, float] | None],
    ident: Callable[[dict[str, Any]], tuple[str, str]],
    tag: str = "tides",
) -> tuple[str | None, str | None]:
    """Pick the closest station within 100 nm, cached per location for an hour.

    *load_stations* returns the provider's station list; *coords* maps a
    station to (lat, lng), or None to leave it out; *ident* maps the chosen
    station to (id, name). When the list cannot be had (empty, or the
    loader raised) the last pick for this location is reused if there is
    one, so the lookup works offline.  *tag* names the provider in the
    debug log.
    """
    cached = read_cache(cache_file, NEAREST_STATION_CACHE_MAX_AGE)
    if cached:
        return cached["id"], cached["name"]

    try:
        stations = load_stations()
    except Exception as exc:
        stations = None
        log_failure(tag, "station list", exc, fallback="last pick reused if any")
    if not stations:
        stale = read_stale(cache_file)
        if stale:
            return stale["id"], stale["name"]
        return None, None

    best, best_dist = None, float("inf")
    for station in stations:
        point = coords(station)
        if point is None:
            continue
        distance = haversine_nm(lat, lng, *point)
        if distance < best_dist:
            best, best_dist = station, distance

    if best is None or best_dist > NEAREST_STATION_MAX_NM:
        return None, None

    station_id, station_name = ident(best)
    write_cache(cache_file, {"id": station_id, "name": station_name,
                             "lat": lat, "lng": lng})
    return station_id, station_name


# ---------------------------------------------------------------------------
# Y-axis range
# ---------------------------------------------------------------------------
def cached_y_range(cache_file: Path, load_heights: Callable[[], list[float] | None],
                   ) -> tuple[float, float] | None:
    """(min, max) of the heights *load_heights* returns, cached for 7 days.

    None when there are no heights; nothing is written then, so the next
    run asks again.
    """
    cached = read_cache(cache_file, Y_RANGE_CACHE_MAX_AGE)
    if cached is not None:
        return (cached["min"], cached["max"])

    heights = load_heights()
    if not heights:
        return None

    result = {"min": min(heights), "max": max(heights)}
    write_cache(cache_file, result)
    return (result["min"], result["max"])


# ---------------------------------------------------------------------------
# Timestamps
# ---------------------------------------------------------------------------
def parse_iso(s: str) -> datetime:
    """datetime.fromisoformat after dropping a trailing Z and any fraction."""
    s = s.rstrip("Z")
    if "." in s:
        s = s[:s.index(".")]
    return datetime.fromisoformat(s)


def parse_utc_iso(s: str, station_tz: tzinfo | None = None) -> datetime:
    """An ISO UTC timestamp as an aware datetime, in *station_tz* when given."""
    dt = parse_iso(s).replace(tzinfo=timezone.utc)
    if station_tz is not None:
        return dt.astimezone(station_tz)
    return dt


def parse_cached_dt(iso_str: str, station_tz: tzinfo | None) -> datetime:
    """A datetime written to cache with isoformat(), aware again if a tz is given."""
    dt = datetime.fromisoformat(iso_str)
    if dt.tzinfo is None and station_tz is not None:
        dt = dt.replace(tzinfo=station_tz)
    return dt


def local_day_bounds(start_date: date, end_date: date,
                     station_tz: tzinfo | None) -> tuple[datetime, datetime]:
    """Midnight opening *start_date* and midnight closing *end_date*.

    Aware in *station_tz* when one is given, naive otherwise.
    """
    lo = datetime(start_date.year, start_date.month, start_date.day)
    hi = datetime(end_date.year, end_date.month, end_date.day) + timedelta(days=1)
    if station_tz is not None:
        lo = lo.replace(tzinfo=station_tz)
        hi = hi.replace(tzinfo=station_tz)
    return lo, hi


def dedup_sorted(points: list[tuple[datetime, float]]) -> list[tuple[datetime, float]]:
    """(datetime, height) points sorted by time, one per minute."""
    seen = set()
    unique = []
    for dt, height in points:
        key = dt.replace(second=0, microsecond=0)
        if key not in seen:
            seen.add(key)
            unique.append((dt, height))
    unique.sort(key=lambda p: p[0])
    return unique


# ---------------------------------------------------------------------------
# Timezones
# ---------------------------------------------------------------------------
def tz_offset_hours(tz_code: str) -> float:
    """Current UTC offset in hours for an IANA timezone (0 when unknown)."""
    if not tz_code:
        return 0
    try:
        from zoneinfo import ZoneInfo
        now = datetime.now(ZoneInfo(tz_code))
        return now.utcoffset().total_seconds() / 3600
    except Exception as exc:
        log_failure("tz", f"lookup of {tz_code}", exc, fallback="offset 0")
        return 0


IANA_ABBR = {
    "Canada/Pacific": "PST", "America/Vancouver": "PST",
    "Canada/Mountain": "MST", "America/Edmonton": "MST",
    "Canada/Central": "CST", "America/Winnipeg": "CST",
    "Canada/Eastern": "EST", "America/Toronto": "EST",
    "Canada/Atlantic": "AST", "America/Halifax": "AST",
    "Canada/Newfoundland": "NST", "America/St_Johns": "NST",
    "Europe/London": "GMT", "Europe/Paris": "CET", "Europe/Berlin": "CET",
    "Europe/Rome": "CET", "Europe/Madrid": "CET", "Europe/Amsterdam": "CET",
    "Europe/Brussels": "CET", "Europe/Vienna": "CET",
    "Europe/Athens": "EET", "Europe/Helsinki": "EET",
    "Europe/Istanbul": "TRT", "Europe/Moscow": "MSK",
    "Asia/Tokyo": "JST", "Asia/Shanghai": "CST", "Asia/Hong_Kong": "HKT",
    "Asia/Seoul": "KST", "Asia/Kolkata": "IST", "Asia/Bangkok": "ICT",
    "Asia/Singapore": "SGT", "Asia/Dubai": "GST",
    "Australia/Sydney": "AEST", "Australia/Perth": "AWST",
    "Australia/Adelaide": "ACST", "Australia/Brisbane": "AEST",
    "Pacific/Auckland": "NZST", "Pacific/Fiji": "FJT",
    "Pacific/Honolulu": "HST", "Pacific/Guam": "ChST",
    "America/New_York": "EST", "America/Chicago": "CST",
    "America/Denver": "MST", "America/Los_Angeles": "PST",
    "America/Anchorage": "AKST", "America/Phoenix": "MST",
    "America/Sao_Paulo": "BRT", "America/Argentina/Buenos_Aires": "ART",
    "America/Mexico_City": "CST", "America/Lima": "PET",
    "America/Bogota": "COT", "America/Santiago": "CLT",
    "Africa/Cairo": "EET", "Africa/Lagos": "WAT",
    "Africa/Johannesburg": "SAST", "Africa/Nairobi": "EAT",
}


def iana_to_abbr(tz_code: str) -> str:
    """Display label for an IANA timezone.

    Zones with a familiar abbreviation get it ("AST"); the rest fall back
    to their current numeric offset ("UTC+9", "UTC+5:30"), which is at
    least honest.  Unknown or empty zones read "UTC".
    """
    abbr = IANA_ABBR.get(tz_code)
    if abbr:
        return abbr
    return format_utc_offset(tz_offset_hours(tz_code))


def format_utc_offset(hours: float) -> str:
    """"UTC", "UTC+9", "UTC-3:30" for an offset in hours."""
    if not hours:
        return "UTC"
    sign = "+" if hours > 0 else "-"
    whole, frac = divmod(abs(hours), 1)
    minutes = round(frac * 60)
    label = f"UTC{sign}{int(whole)}"
    return f"{label}:{minutes:02d}" if minutes else label


# ---------------------------------------------------------------------------
# High/low labelling
# ---------------------------------------------------------------------------
def label_hilo(values: list[tuple[datetime, float]]) -> list[tuple[datetime, float, str]]:
    """Infer H/L labels for a sequence of extrema (dt, height) tuples.

    For sources that publish turning points without saying which are
    highs: each value is compared with its neighbours, so peaks read "H"
    and troughs "L".
    """
    if not values:
        return []
    if len(values) == 1:
        return [(*values[0], "H")]

    labeled = []
    for i, (dt, height) in enumerate(values):
        if i == 0:
            is_high = height > values[1][1]
        elif i == len(values) - 1:
            is_high = height > values[-2][1]
        else:
            is_high = height > values[i - 1][1] and height > values[i + 1][1]
        labeled.append((dt, height, "H" if is_high else "L"))
    return labeled
