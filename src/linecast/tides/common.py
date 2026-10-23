"""Helpers shared by the tide providers.

Every provider caches under the same directory, works in feet,
describes its stations in the same metadata (StationMeta), and measures
its y-axis range over the same window; this module holds those pieces
once.  So too the nearest-station search NOAA, CHS, QLD, HKO and JMA
share (TICON, Kartverket, TideCheck and Open-Meteo find theirs their own
way), the locks the fixed blocks are fetched under, and the reading of
a gauge's record at the predicted turns.  The provider modules keep what
is genuinely theirs: URLs, payload shapes, and unit or timezone quirks.
"""

import math
import re
import threading
from collections.abc import Callable
from concurrent.futures import Future
from datetime import date, datetime, timedelta, timezone, tzinfo
from pathlib import Path
from typing import Any, TypedDict

from linecast import _paths
from linecast._cache import read_cache, read_stale, write_cache
from linecast._geo import haversine_nm
from linecast._log import log_failure

M_TO_FT = 1 / 0.3048
NEAREST_STATION_CACHE_MAX_AGE = 3600
NEAREST_STATION_MAX_NM = 100
Y_RANGE_CACHE_MAX_AGE = 7 * 86400


def cache_dir() -> Path:
    """The directory every tide provider caches under."""
    return _paths.cache_dir("tides")


class _StationMetaRequired(TypedDict):
    id: str
    name: str
    state: str
    lat: float | str
    lng: float | str
    timezone_abbr: str
    timezonecorr: float
    observedst: bool


class StationMeta(_StationMetaRequired, total=False):
    """A station's metadata, in the shape NOAA's mdapi gave it first and
    every provider's station_metadata returns.  The view reads it, and
    it is cached as JSON, so a key it does not find shows up far away:
    a missing timezonecorr cost the TICON gauges their night shading.

    id: the station's id, as --station takes it.
    name: its name as the header shows it, with state after a comma;
        "" for a stationless provider, whose caller holds a better one.
    state: what follows the name: the state or province ("ME", "NS"),
        a region, or a country; "" for none.
    lat, lng: where it is, in degrees, a number or a string of one: the
        daylight shading, the Moon's rises and sets, the sea forecast,
        the makeup view's latitude.
    timezone_abbr: NOAA's abbreviation for the station's clock ("EST",
        "AKST"), which _station_tzinfo maps to a zone when there is no
        IANA name; the others give a UTC offset ("UTC-3") or "".  NOAA's
        and CHS's cached files without it are read as unparsed.
    timezonecorr: the clock's offset from UTC in hours, a number: NOAA's
        standard time, and the others' offset when the metadata was
        made.  The zone of last resort, for a clock without a zone.
    observedst: whether the clock keeps summer time, which settles an
        abbreviation's zone ("AST" is Halifax with it, Puerto Rico
        without).
    timeZoneCode: the IANA zone ("America/Halifax"; CHS's legacy names
        go through zone_info), the station's clock wherever it is given.
    source: the provider's name; TideCheck's cache checks it.
    datum: the chart datum the heights are above, where the provider
        says ("LAT", "MSL"): TICON's gauges, and Open-Meteo's model,
        which is above mean sea level.  The month view brightens a
        minus tide only on a low-water datum.
    """

    timeZoneCode: str
    source: str
    datum: str


class Unreachable(Exception):
    """A provider could not be asked: the request failed, and nothing was
    kept to answer from.  Not the same as no station: offline, a coast
    the global model could not be asked about is not taken for one
    without tides."""


# ---------------------------------------------------------------------------
# Legacy cache files
# ---------------------------------------------------------------------------
# Names from before predictions and y-ranges were keyed by month: one NOAA
# file per day of predictions or extremes, and one y-range file per date
# window. Nothing reads them any more; the month-keyed files have six
# digits where these have eight. The QLD provider's move from the
# storm-tide monitoring feed to the predicted-interval gauges also
# orphaned its station list and the files keyed by the feed's
# all-lowercase site slugs (gauge names carry capitals).
_LEGACY_CACHE_NAME = re.compile(
    r"^(?:(?:pred|hilo)_\d+_\d{8}"
    r"|(?:chs_|tc_|qld_)?yrange_.+_\d{8}_\d{8}"
    r"|qld_all_stations"
    r"|qld_meta_[a-z0-9]+"
    r"|qld_pred_[a-z0-9]+_\d{8}_\d{8}"
    r"|qld_yrange_[a-z0-9]+_\d{6})\.json$"
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


def months_covering(start_date: date, end_date: date) -> list[date]:
    """First-of-month dates for every calendar month the range touches."""
    first = month_start(start_date)
    months = []
    while first <= end_date:
        months.append(first)
        first = month_after(first)
    return months


# cache file name -> the fetch for that file under way
_fetching: dict[str, Future] = {}
_fetching_lock = threading.Lock()


def fetch_once(name: str, fetch: Callable[[], Any]) -> Any:
    """fetch() for the cache file *name*, made once among the threads
    that want it at the same time.

    The providers fetch by fixed blocks, a month or a year, and two
    threads can want the same block at once: the day view asks for its
    curve, its turns and its axis side by side, and a subordinate NOAA
    station's curve and turns both come from its hi/lo month.  The first
    makes the request; the others wait for it and take what it brought
    back, a stale copy or the fallback included.  When they took turns
    instead, each read the file the first had written, but where the
    first had failed each asked again, one timeout after another.
    """
    with _fetching_lock:
        running = _fetching.get(name)
        mine = running is None
        if mine:
            running = _fetching[name] = Future()
    if not mine:
        return running.result()
    try:
        result = fetch()
    except BaseException as exc:
        running.set_exception(exc)
        raise
    finally:
        with _fetching_lock:
            _fetching.pop(name, None)
    running.set_result(result)
    return result


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


# ---------------------------------------------------------------------------
# Tides computed from their constants
# ---------------------------------------------------------------------------
# A provider with a harmonic.Tide (in metres, UTC) rather than a table
# serves it through these, in the shapes the NOAA pipeline reads.
def _utc_bounds(start_date, end_date, station_tz):
    lo, hi = local_day_bounds(start_date, end_date, station_tz)
    if station_tz is None:
        lo, hi = lo.replace(tzinfo=timezone.utc), hi.replace(tzinfo=timezone.utc)
    return lo, hi


def _station_time(t, station_tz):
    return t.astimezone(station_tz) if station_tz is not None else t.replace(tzinfo=None)


def computed_range(tide, start_date: date, end_date: date,
                   station_tz: tzinfo | None) -> list[tuple[datetime, float]]:
    """Six-minute heights in feet across the dates, as NOAA serves its own."""
    lo, hi = _utc_bounds(start_date, end_date, station_tz)
    return [(_station_time(t, station_tz), h * M_TO_FT) for t, h in tide.series(lo, hi, 6)]


def computed_hilo(tide, start_date: date, end_date: date,
                  station_tz: tzinfo | None) -> list[tuple[datetime, float, str]]:
    """The highs and lows across the dates, in feet."""
    lo, hi = _utc_bounds(start_date, end_date, station_tz)
    return [(_station_time(t, station_tz), h * M_TO_FT, kind)
            for t, h, kind in tide.extremes(lo, hi)]


def computed_y_range(tide, center_date: date,
                     station_tz: tzinfo | None) -> tuple[float, float] | None:
    """(lowest, highest) of the highs and lows over the y-axis window.

    Three months of turns take a few hundredths of a second, so unlike
    the fetched ranges this one is not cached.
    """
    start, end, _key = y_range_window(center_date)
    heights = [h for _t, h, _k in computed_hilo(tide, start, end, station_tz)]
    return (min(heights), max(heights)) if heights else None


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
# CHS names its stations' zones the old way, Canada/Atlantic. Debian 13
# and Ubuntu 23.10 moved those names to tzdata-legacy, which is not
# installed by default, so each is looked up by the name it links to.
LEGACY_ZONES = {
    "Canada/Atlantic": "America/Halifax",
    "Canada/Central": "America/Winnipeg",
    "Canada/Eastern": "America/Toronto",
    "Canada/Mountain": "America/Edmonton",
    "Canada/Newfoundland": "America/St_Johns",
    "Canada/Pacific": "America/Vancouver",
    "Canada/Saskatchewan": "America/Regina",
    "Canada/Yukon": "America/Whitehorse",
}


def zone_info(tz_code: str) -> tzinfo:
    """ZoneInfo for an IANA name, legacy Canadian names included."""
    from zoneinfo import ZoneInfo
    return ZoneInfo(LEGACY_ZONES.get(tz_code, tz_code))


def tz_offset_hours(tz_code: str) -> float:
    """Current UTC offset in hours for an IANA timezone (0 when unknown)."""
    if not tz_code:
        return 0
    try:
        now = datetime.now(zone_info(tz_code))
        return now.utcoffset().total_seconds() / 3600
    except Exception as exc:
        log_failure("tz", f"lookup of {tz_code}", exc, fallback="offset 0")
        return 0


def iana_to_abbr(tz_code: str) -> str:
    """The timezone_abbr a provider that names its zone gives it: the
    zone's offset from UTC now ("UTC+9", "UTC+5:30"), or "UTC" for an
    unknown or empty one.  Only NOAA's abbreviations are read for a
    zone (StationMeta), and the IANA name is what any other is read
    by, so a familiar abbreviation here would say nothing."""
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


# ---------------------------------------------------------------------------
# What a gauge measured, against the turns predicted for it
# ---------------------------------------------------------------------------
def measured_turns(turns: list[tuple[datetime, float, str]], level: list[float | None],
                   start: datetime, last: date, step: int,
                   gap: int | None = 2) -> dict[date, tuple[float, float]]:
    """{day: (lowest, highest)} of the water the gauge measured at each
    day's predicted turns of the tide, through *last*, in the gauge's
    own unit.  *level* is what it read every *step* seconds from *start*,
    None where it sent nothing.

    Each turn takes the readings nearer to it than to the turns either
    side, and reads their highest for a high water and their lowest for
    a low; a day's range is then taken from its turns as the predicted
    one is.  A day's plain highest reading will not do: where the higher
    high water falls near midnight, as it does in Vancouver in summer,
    the water at midnight is the evening's high still ebbing, and the
    day after would read five feet over a prediction it matched.
    A reading or two gone missing costs a few inches at most, even at
    Fundy's range, but more than *gap* running are a hole the turn
    itself may be in, and the day is left out.  *gap* is None where the
    readings are the gauge's own highs and lows with nothing between
    them, as NOAA's verified ones are: a turn then wants only a reading.
    """
    at = [(moment - start).total_seconds() / step for moment, _h, _k in turns]
    reach = 3 * 3600 / step
    found, missed = {}, set()
    for i, (moment, _height, kind) in enumerate(turns):
        day = moment.date()
        if day > last:
            break
        lo = (at[i - 1] + at[i]) / 2 if i else at[i] - reach
        hi = (at[i] + at[i + 1]) / 2 if i + 1 < len(turns) else at[i] + reach
        window = level[max(0, math.ceil(lo)):max(0, math.ceil(hi))]
        seen = [v for v in window if v is not None]
        longest = run = 0
        if gap is not None:
            for v in window:
                run = run + 1 if v is None else 0
                longest = max(longest, run)
        if not seen or (gap is not None and longest > gap):
            missed.add(day)
            continue
        found.setdefault(day, []).append(max(seen) if kind == "H" else min(seen))
    return {day: (min(v), max(v)) for day, v in found.items() if day not in missed}
