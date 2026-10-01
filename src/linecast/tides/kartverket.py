"""Kartverket tide data source, for Norway, Svalbard and Jan Mayen.

Kartverket's water level API (the Norwegian Mapping Authority's
hydrographic service) predicts the tide for any point on the coast. It
divides the coast into tidal zones, each taking the tide of a reference
station scaled by a factor and shifted by a few minutes, so there is no
station to pick: as with Open-Meteo's model, the "station" is the place
itself, `kv:<lat>,<lng>`, and the caller names it. A point inland, or
outside Norway, answers <nodata>.

  tab  the high and low waters, labelled; a year to a request
  pre  the predicted height every ten minutes; a month to a request
       (a year at ten minutes is nearly four megabytes of XML)

Both are asked for in UTC and put on the station's clock; heights are
centimetres above chart datum, converted to feet.

What the water did is measured at the thirty-three permanent gauges.
The year view's pen takes a gauge's record only where the gauge is
close and its tide is the place's own (see gauge_for). There is no
flood stage: Kartverket publishes the astronomical levels
and storm surge return levels, and the storm surge warning levels are
MET Norway's, outside this API.

The data is CC BY 4.0. Kartverket asks that it be cached; everything
here is.
"""

import threading
from datetime import date, datetime, timedelta, timezone, tzinfo
from typing import Any
from xml.etree import ElementTree

from linecast._cache import location_cache_key
from linecast._geo import haversine_nm
from linecast._http import fetch_bytes, fetch_json_cached
from linecast._log import log_failure, log_skipped
from linecast.tides.common import (
    M_TO_FT, cache_dir, cached_y_range, iana_to_abbr, local_day_bounds,
    month_after, month_start, tz_offset_hours, y_range_window,
)

KV_BASE = "https://vannstand.kartverket.no/tideapi.php"
TAG = "tides/kartverket"

# The permanent gauges, from tide_request=stationlist in September 2026.
# The list changes seldom, and keeping it here spares every --search, the
# world over, a request to Kartverket.
GAUGES = [
    {"code": "ANX", "name": "Andenes", "lat": 69.326067, "lng": 16.134848},
    {"code": "BGO", "name": "Bergen", "lat": 60.398046, "lng": 5.320487},
    {"code": "BOO", "name": "Bodø", "lat": 67.292330, "lng": 14.399770},
    {"code": "BRJ", "name": "Bruravik", "lat": 60.492094, "lng": 6.893949},
    {"code": "BOH", "name": "Bøfjorden", "lat": 61.135925, "lng": 5.339699},
    {"code": "EYD", "name": "Eydehavn", "lat": 58.494604, "lng": 8.875352},
    {"code": "HFT", "name": "Hammerfest", "lat": 70.664750, "lng": 23.678690},
    {"code": "HAR", "name": "Harstad", "lat": 68.801261, "lng": 16.548236},
    {"code": "HEI", "name": "Heimsjøen", "lat": 63.425224, "lng": 9.101504},
    {"code": "HRO", "name": "Helgeroa", "lat": 58.995212, "lng": 9.856379},
    {"code": "HVG", "name": "Honningsvåg", "lat": 70.980318, "lng": 25.972697},
    {"code": "KAB", "name": "Kabelvåg", "lat": 68.212639, "lng": 14.482149},
    {"code": "KAZ", "name": "Kaupanger", "lat": 61.182480, "lng": 7.252396},
    {"code": "KSU", "name": "Kristiansund", "lat": 63.113920, "lng": 7.736140},
    {"code": "LEH", "name": "Leirvik", "lat": 59.766394, "lng": 5.503670},
    {"code": "MSU", "name": "Mausund", "lat": 63.869331, "lng": 8.665231},
    {"code": "MAY", "name": "Måløy", "lat": 61.933776, "lng": 5.113310},
    {"code": "NVK", "name": "Narvik", "lat": 68.428286, "lng": 17.425759},
    {"code": "NYA", "name": "Ny-Ålesund", "lat": 78.928545, "lng": 11.938015},
    {"code": "OSC", "name": "Oscarsborg", "lat": 59.678073, "lng": 10.604861},
    {"code": "OSL", "name": "Oslo", "lat": 59.908559, "lng": 10.734510},
    {"code": "RVK", "name": "Rørvik", "lat": 64.859456, "lng": 11.230107},
    {"code": "SBG", "name": "Sandnes", "lat": 58.868232, "lng": 5.746613},
    {"code": "SIE", "name": "Sirevåg", "lat": 58.505200, "lng": 5.791602},
    {"code": "SOY", "name": "Solumstrand", "lat": 59.710622, "lng": 10.273018},
    {"code": "SVG", "name": "Stavanger", "lat": 58.974339, "lng": 5.730121},
    {"code": "TRG", "name": "Tregde", "lat": 58.006377, "lng": 7.554759},
    {"code": "TOS", "name": "Tromsø", "lat": 69.646110, "lng": 18.954790},
    {"code": "TRD", "name": "Trondheim", "lat": 63.436484, "lng": 10.391669},
    {"code": "TAZ", "name": "Træna", "lat": 66.496624, "lng": 12.088633},
    {"code": "VAW", "name": "Vardø", "lat": 70.374978, "lng": 31.104015},
    {"code": "VIK", "name": "Viker", "lat": 59.036046, "lng": 10.949769},
    {"code": "AES", "name": "Ålesund", "lat": 62.469414, "lng": 6.151946},
]
GAUGE_BY_CODE = {g["code"]: g for g in GAUGES}

# How close to a gauge a place must be for the gauge's record to be the
# water there (see gauge_for): the towns the gauges stand in, not the
# fjords beyond them.
GAUGE_REACH_NM = 5
# A day with fewer ten-minute readings than three quarters of its 144
# has lost enough to miss a high or low water, and is left out rather
# than drawn short.
MIN_READINGS = 108


# ---------------------------------------------------------------------------
# Pseudo-station IDs
# ---------------------------------------------------------------------------
def make_station_id(lat: float, lng: float) -> str:
    """Encode coordinates as a Kartverket pseudo-station ID."""
    return f"kv:{float(lat):.4f},{float(lng):.4f}"


def is_kartverket_station_id(station_id: str) -> bool:
    return str(station_id).startswith("kv:")


def parse_station_id(station_id: str) -> tuple[float, float] | None:
    """Decode a `kv:lat,lng` pseudo-station ID to (lat, lng) or None."""
    try:
        lat_str, lng_str = str(station_id)[3:].split(",")
        return float(lat_str), float(lng_str)
    except (ValueError, IndexError) as exc:
        log_failure(TAG, "parse of station id", exc, fallback="no station")
        return None


def gauge_at(station_id: str) -> dict[str, Any] | None:
    """The permanent gauge a station ID stands on, as --search gives them."""
    coords = parse_station_id(station_id)
    if coords is None:
        return None
    station_id = make_station_id(*coords)   # as typed, it may carry more digits
    return next((g for g in GAUGES
                 if make_station_id(g["lat"], g["lng"]) == station_id), None)


# ---------------------------------------------------------------------------
# The clock
# ---------------------------------------------------------------------------
def _zone_name(lat: float, lng: float) -> str:
    """Norway's clock, under the name Svalbard and Jan Mayen give it
    there: the only coast north of 74° or west of Greenwich."""
    return "Arctic/Longyearbyen" if lat >= 74 or lng < 0 else "Europe/Oslo"


def _zone(coords: tuple[float, float], station_tz: tzinfo | None = None) -> tzinfo:
    """The station's zone as the caller has it, else the point's own."""
    if station_tz is not None:
        return station_tz
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(_zone_name(*coords))
    except Exception as exc:
        log_failure(TAG, "time zone", exc, fallback="UTC+1")
        return timezone(timedelta(hours=1))


def _utc(moment: datetime) -> str:
    """An aware datetime as the API's fromtime and totime take it, in UTC."""
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M")


# ---------------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------------
# cache file name -> lock held while that file fetches, so the day view's
# y-range and highs and lows, asked for side by side, make one request
_locks: dict[str, threading.Lock] = {}
_locks_lock = threading.Lock()


def _lock(name):
    with _locks_lock:
        return _locks.setdefault(name, threading.Lock())


def _fetch_xml(url, timeout=10):
    """The answer's root element. Kartverket answers a bad request with
    an <error> and a 200, which is raised here so it is not cached."""
    root = ElementTree.fromstring(fetch_bytes(url, timeout=timeout))
    error = root.find(".//error")
    if error is not None:
        raise ValueError((error.text or "error").strip())
    return root


def _cached(cache_file, max_age, url, transform, timeout=20, fresh=None):
    with _lock(cache_file.name):
        return fetch_json_cached(cache_file, max_age, url, timeout=timeout,
                                 fallback=None, fetch=_fetch_xml, fresh=fresh,
                                 transform=transform, provider=TAG)


def _location_url(coords, datatype, lo, hi, interval=None):
    lat, lng = coords
    url = (f"{KV_BASE}?tide_request=locationdata&lat={lat:.4f}&lon={lng:.4f}"
           f"&datatype={datatype}&refcode=cd&fromtime={_utc(lo)}&totime={_utc(hi)}"
           f"&tzone=0&dst=0&lang=en")
    return url + (f"&interval={interval}" if interval else "")


def _feet_per(unit):
    """Feet in one of the answer's units."""
    per = {"cm": M_TO_FT / 100, "m": M_TO_FT}.get((unit or "").strip().lower())
    if per is None:
        raise ValueError(f"heights in {unit!r}")
    return per


def _location_block(root):
    """The answer's <locationdata>, or None when it says <nodata>: the
    point is inland, or not in Norway.

    That answer says why ("too far away from the coast"); a <nodata>
    with no reason, which whole zones gave while Kartverket updated its
    tables on 30 September 2026, is a failure instead, so a day of
    "no tides here" is not cached on its word.
    """
    block = root.find("locationdata")
    if block is None:
        raise ValueError("no locationdata in the answer")
    nodata = block.find("nodata")
    if nodata is not None:
        if not nodata.get("info", "").strip():
            raise ValueError("no data, and no reason given")
        return None
    if (block.findtext("reflevelcode") or "").strip().upper() != "CD":
        raise ValueError(f"heights on {block.findtext('reflevelcode')!r}, not chart datum")
    return block


def _waterlevels(block, what):
    """(epoch seconds, feet, flag) for each predicted <waterlevel>."""
    levels = []
    dropped = 0
    bad = None
    for data in block.iter("data"):
        if data.get("type") != "prediction":
            continue
        per = _feet_per(data.get("unit"))
        for level in data.iter("waterlevel"):
            try:
                moment = datetime.fromisoformat(level.get("time", ""))
                levels.append((int(moment.timestamp()),
                               round(float(level.get("value")) * per, 4),
                               level.get("flag", "")))
            except (TypeError, ValueError) as exc:
                dropped += 1
                bad = exc
    log_skipped(TAG, what, dropped, dropped + len(levels), bad)
    return levels


def _extreme_rows(root):
    """A year's high and low waters as the cache keeps them, [[epoch,
    feet, "H" or "L"], ...]; none where Kartverket has no water, which
    is cached like any other answer: the coast stays where it is."""
    block = _location_block(root)
    if block is None:
        return []
    rows = [[t, h, "H" if flag == "high" else "L"]
            for t, h, flag in _waterlevels(block, "high and low waters")
            if flag in ("high", "low")]
    if not rows:
        raise ValueError("no high or low waters in the answer")
    return rows


def _height_rows(root):
    """A month's ten-minute heights as the cache keeps them: [[epoch, feet], ...]."""
    block = _location_block(root)
    if block is None:
        return []
    rows = [[t, h] for t, h, _flag in _waterlevels(block, "heights")]
    if not rows:
        raise ValueError("no heights in the answer")
    return rows


# ---------------------------------------------------------------------------
# A year of highs and lows, a month of heights
# ---------------------------------------------------------------------------
def _year_extremes(coords, year):
    """The point's high and low waters for one of its local years, as
    _extreme_rows keeps them, or None when they could not be had.

    One request, some hundred kilobytes. A past year's predictions do
    not change and are kept for 30 days; this year's and those to come
    for a day, in case Kartverket revises them.
    """
    zone = _zone(coords)
    url = _location_url(coords, "tab", datetime(year, 1, 1, tzinfo=zone),
                        datetime(year + 1, 1, 1, tzinfo=zone))
    max_age = 30 * 86400 if year < datetime.now(zone).year else 86400
    rows = _cached(cache_dir() / f"kv_hilo_{location_cache_key(*coords)}_{year}.json",
                   max_age, url, _extreme_rows)
    return rows if isinstance(rows, list) else None


def _month_heights(coords, first):
    """The point's ten-minute heights for one local calendar month, as
    [[epoch, feet], ...]: one request, kept like the year's highs and
    lows, a month to a file so the day view's weeks and the month view
    read the same one."""
    zone = _zone(coords)
    lo, hi = local_day_bounds(first, month_after(first) - timedelta(days=1), zone)
    url = _location_url(coords, "pre", lo, hi, interval=10)
    past = first < month_start(datetime.now(zone).date())
    rows = _cached(cache_dir() / f"kv_pred_{location_cache_key(*coords)}_{first:%Y%m}.json",
                   30 * 86400 if past else 86400, url, _height_rows)
    return rows if isinstance(rows, list) else []


def find_point_kartverket(lat: float | None, lng: float | None) -> str | None:
    """The pseudo-station ID for a point Kartverket predicts the tide at,
    or None. This year's high and low waters there are what tells, and
    the day view reads them from the cache straight after."""
    if lat is None or lng is None:
        return None
    station_id = make_station_id(lat, lng)
    coords = parse_station_id(station_id)
    if not _year_extremes(coords, datetime.now(_zone(coords)).year):
        return None
    return station_id


# ---------------------------------------------------------------------------
# Station metadata
# ---------------------------------------------------------------------------
def fetch_station_metadata_kartverket(station_id: str) -> dict[str, Any] | None:
    """NOAA-shaped metadata for the point, which needs no request. The
    name is left empty: the place's own name, which the caller holds,
    is a better one than any this could make up."""
    coords = parse_station_id(station_id)
    if coords is None:
        return None
    zone = _zone_name(*coords)
    return {
        "id": station_id,
        "name": "",
        "state": "",
        "lat": coords[0],
        "lng": coords[1],
        "timezone_abbr": iana_to_abbr(zone),
        "timezonecorr": tz_offset_hours(zone),
        "timeZoneCode": zone,
        "observedst": True,
        "source": "kartverket",
    }


# ---------------------------------------------------------------------------
# Ranges
# ---------------------------------------------------------------------------
def _in_range(rows, start_date, end_date, zone):
    """The rows whose moment falls on the local days given, in time order
    and once each: files meet at a midnight both of them hold."""
    lo, hi = local_day_bounds(start_date, end_date, zone)
    lo_t, hi_t = lo.timestamp(), hi.timestamp()
    unique = {row[0]: row for row in rows if lo_t <= row[0] < hi_t}
    return [unique[t] for t in sorted(unique)]


def fetch_tides_range_kartverket(station_id: str, start_date: date, end_date: date,
                                 station_tz: tzinfo | None = None,
                                 ) -> list[tuple[datetime, float]]:
    """Ten-minute predictions from *start_date* through *end_date*, as
    sorted (datetime, height_ft) points, a month's file at a time."""
    coords = parse_station_id(station_id)
    if coords is None:
        return []
    zone = _zone(coords, station_tz)
    rows = []
    first = month_start(start_date)
    while first <= end_date:
        rows.extend(_month_heights(coords, first))
        first = month_after(first)
    return [(datetime.fromtimestamp(t, zone), h)
            for t, h in _in_range(rows, start_date, end_date, zone)]


def fetch_hilo_range_kartverket(station_id: str, start_date: date, end_date: date,
                                station_tz: tzinfo | None = None,
                                ) -> list[tuple[datetime, float, str]]:
    """Highs and lows from *start_date* through *end_date*, as sorted
    (datetime, height_ft, "H"/"L") tuples, a year's file at a time."""
    coords = parse_station_id(station_id)
    if coords is None:
        return []
    zone = _zone(coords, station_tz)
    rows = []
    for year in range(start_date.year, end_date.year + 1):
        rows.extend(_year_extremes(coords, year) or [])
    return [(datetime.fromtimestamp(t, zone), h, kind)
            for t, h, kind in _in_range(rows, start_date, end_date, zone)]


def fetch_y_range_kartverket(station_id: str, center_date: date,
                             station_tz: tzinfo | None = None) -> tuple[float, float] | None:
    """The y-axis range from the highs and lows around *center_date*,
    read from the year's file, so it costs no request of its own.
    Cached 7 days, keyed by month like the other providers."""
    coords = parse_station_id(station_id)
    if coords is None:
        return None
    start, end, key = y_range_window(center_date)
    return cached_y_range(
        cache_dir() / f"kv_yrange_{location_cache_key(*coords)}_{key}.json",
        lambda: [h for _, h, _ in fetch_hilo_range_kartverket(
            station_id, start, end, station_tz)])


# ---------------------------------------------------------------------------
# What a gauge measured
# ---------------------------------------------------------------------------
def gauge_for(station_id: str, year: int) -> dict[str, Any] | None:
    """The permanent gauge whose record is the water at this point, or None.

    The nearest gauge, if it is within GAUGE_REACH_NM, and if the year's
    high and low waters Kartverket predicts at the point are the very
    ones it predicts at the gauge, every time and height: the same tide
    on the same chart datum, so the gauge's readings and the point's
    predictions can be laid one over the other. A zone that
    scales or shifts the gauge's tide fails, and so does one whose chart
    datum is set apart from the gauge's, as it is across the mouth of
    the inner Oslofjord, thirty centimetres under the lowest tide inside
    and twenty outside. Asking is one more year of highs and lows, at
    the gauge; none when the point is the gauge's own, as --search
    gives them.
    """
    coords = parse_station_id(station_id)
    if coords is None:
        return None
    gauge = min(GAUGES, key=lambda g: haversine_nm(*coords, g["lat"], g["lng"]))
    if haversine_nm(*coords, gauge["lat"], gauge["lng"]) > GAUGE_REACH_NM:
        return None
    here = _year_extremes(coords, year)
    there = _year_extremes(parse_station_id(make_station_id(gauge["lat"], gauge["lng"])), year)
    return gauge if here and here == there else None


def _daily_rows(root, zone, start, end):
    """The gauge's lowest and highest reading on each local day from
    *start* up to *end*, as [["YYYY-MM-DD", low_ft, high_ft], ...].

    The readings come as seconds after the answer's reftime (dst=2),
    a quarter less XML than a timestamp on each.
    """
    block = root.find("stationdata")
    if block is None:
        raise ValueError("no stationdata in the answer")
    days = {}
    for data in block.iter("data"):
        if data.get("type") != "observation":
            continue
        if data.get("reflevelcode", "CD") != "CD":
            raise ValueError(f"observations on {data.get('reflevelcode')}")
        per = _feet_per(data.get("unit"))
        ref = datetime.fromisoformat(data.get("reftime", "")).timestamp()
        for level in data.iter("waterlevel"):
            try:
                moment = ref + int(level.get("time"))
                height = float(level.get("value")) * per
            except (TypeError, ValueError):
                continue
            if not -15 < height < 35:
                # Norway's water keeps within a few metres of chart
                # datum, and one fault tens of metres out would flatten
                # the year's scale: the Sandnes gauge's July 2026 mean
                # in the monthly statistics is 1.4e17 centimetres.
                continue
            day = datetime.fromtimestamp(moment, zone).date()
            if not start <= day < end:
                continue
            lo, hi, n = days.get(day, (height, height, 0))
            days[day] = (min(lo, height), max(hi, height), n + 1)
    return [[day.isoformat(), round(lo, 4), round(hi, 4)]
            for day, (lo, hi, n) in sorted(days.items()) if n >= MIN_READINGS]


def _observed(gauge, start, end, max_age):
    """{day: (lowest, highest)} the gauge measured from *start* up to
    *end*, one request of ten-minute readings. The file is named by its
    first day and holds the day it ran to, and a copy that stops short
    of *end* is fetched again."""
    coords = (gauge["lat"], gauge["lng"])
    zone = _zone(coords)
    lo = datetime(start.year, start.month, start.day, tzinfo=zone)
    hi = datetime(end.year, end.month, end.day, tzinfo=zone)
    url = (f"{KV_BASE}?tide_request=stationdata&stationcode={gauge['code']}"
           f"&datatype=obs&interval=10&refcode=cd&fromtime={_utc(lo)}&totime={_utc(hi)}"
           f"&tzone=0&dst=2&lang=en")
    want = end.isoformat()
    answer = _cached(
        cache_dir() / f"kv_obs_{gauge['code']}_{start:%Y%m%d}.json", max_age, url,
        lambda root: {"end": want, "days": _daily_rows(root, zone, start, end)},
        timeout=30, fresh=lambda cached: isinstance(cached, dict) and cached.get("end") == want)
    out = {}
    for row in (answer.get("days") if isinstance(answer, dict) else None) or []:
        try:
            out[date.fromisoformat(row[0])] = (float(row[1]), float(row[2]))
        except (IndexError, TypeError, ValueError):
            continue
    return out


def fetch_observed_extremes_kartverket(station_id: str, year: int,
                                       today: date) -> dict[date, tuple[float, float]]:
    """{day: (lowest, highest)} of the water measured in *year* before
    *today*, in feet above chart datum, where a gauge stands for the
    point (gauge_for); empty elsewhere.

    A past year is one request, about three megabytes, kept for a month.
    This year is two: the months before this one, kept until the month
    turns, and this month's days, kept three hours. Finding the gauge
    may take one more, its year of highs and lows.
    """
    first = date(year, 1, 1)
    end = min(date(year + 1, 1, 1), today)
    if end <= first:
        return {}
    gauge = gauge_for(station_id, year)
    if gauge is None:
        return {}
    if year < today.year:
        return _observed(gauge, first, end, 30 * 86400)
    this_month = month_start(today)
    days = {}
    if first < this_month:
        days.update(_observed(gauge, first, this_month, 30 * 86400))
    if this_month < end:
        days.update(_observed(gauge, this_month, end, 3 * 3600))
    return days
