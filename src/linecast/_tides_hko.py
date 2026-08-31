"""Hong Kong Observatory tide data source.

Uses the HKO Open Data API for the year's astronomical tide predictions
at each of its stations:

  HHOT  hourly heights, one row per day: [MM, DD, h01, ..., h24]
  HLT   highs and lows, one row per day: [MM, DD, time, height, ...]
        with up to four events; the unused slots are empty strings.

Both take a station code and a year, and the year after this one is
published in advance. Times are HKT (UTC+8, no DST) and heights are
metres above chart datum; this module converts to feet for the
NOAA-shaped pipeline. HLT does not say which events are highs, so
the labels are inferred from the neighbours.

The station list is fixed: HKO does not publish one through the API.
Coordinates come from HKO's geodata store (EPSG:4326). Two stations
the API still answers for are left out because their predictions are
computed rather than observed: Chi Ma Wan (CMW, closed 1997) and Lok
On Pai (LOP, closed 1999).
"""

from datetime import date, datetime, timedelta, timezone, tzinfo
from typing import Any

from linecast._cache import location_cache_key
from linecast._http import fetch_json_cached
from linecast._runtime import log_skipped
from linecast._tides_common import (
    M_TO_FT, cache_dir, cached_y_range, label_hilo, local_day_bounds,
    nearest_station, station_coords, y_range_window,
)

HKO_BASE = "https://data.weather.gov.hk/weatherAPI/opendata/opendata.php"
# Hong Kong does not observe DST; HKT is always UTC+8.
HKT = timezone(timedelta(hours=8))

STATIONS = [
    {"id": "CCH", "name": "Cheung Chau", "lat": 22.214167, "lng": 114.023056},
    {"id": "CLK", "name": "Chek Lap Kok (E)", "lat": 22.320556, "lng": 113.945278},
    {"id": "KCT", "name": "Kwai Chung", "lat": 22.323611, "lng": 114.122778},
    {"id": "KLW", "name": "Ko Lau Wan", "lat": 22.458611, "lng": 114.360833},
    {"id": "MWC", "name": "Ma Wan", "lat": 22.363889, "lng": 114.071389},
    {"id": "PT1", "name": "Po Toi", "lat": 22.163300, "lng": 114.253100},
    {"id": "QUB", "name": "Quarry Bay", "lat": 22.291111, "lng": 114.213333},
    {"id": "SPW", "name": "Shek Pik", "lat": 22.220278, "lng": 113.894444},
    {"id": "TAO", "name": "Tai O", "lat": 22.255000, "lng": 113.865556},
    {"id": "TBT", "name": "Tsim Bei Tsui", "lat": 22.487222, "lng": 114.014167},
    {"id": "TMW", "name": "Tai Miu Wan", "lat": 22.269722, "lng": 114.288611},
    {"id": "TPK", "name": "Tai Po Kau", "lat": 22.442500, "lng": 114.183889},
    {"id": "WAG", "name": "Waglan Island", "lat": 22.183056, "lng": 114.302778},
]
STATION_BY_ID = {s["id"]: s for s in STATIONS}


def is_hko_station_id(text: str) -> bool:
    """True for one of the station codes above, in any case."""
    return text.upper() in STATION_BY_ID


def find_nearest_station_hko(lat: float, lng: float) -> tuple[str | None, str | None]:
    """The closest station within 100 nm as (id, name), else (None, None)."""
    return nearest_station(
        cache_dir() / f"hko_station_{location_cache_key(lat, lng)}.json",
        lat, lng, lambda: STATIONS, station_coords,
        lambda s: (s["id"], s["name"]), tag="tides/hko",
    )


def fetch_station_metadata_hko(station_id: str) -> dict[str, Any] | None:
    """Station metadata in the shape the NOAA pipeline reads."""
    s = STATION_BY_ID.get(station_id.upper())
    if s is None:
        return None
    return {
        "id": s["id"],
        "name": s["name"],
        "state": "HK",
        "lat": s["lat"],
        "lng": s["lng"],
        "timezone_abbr": "HKT",
        "timezonecorr": 8,
        "timeZoneCode": "Asia/Hong_Kong",
        "observedst": False,
        "source": "hko",
    }


# ---------------------------------------------------------------------------
# One year of one dataset
# ---------------------------------------------------------------------------
def _fetch_year(data_type: str, station_id: str, year: int) -> list[list[str]]:
    """The rows of one year's HHOT or HLT table, or [] when unavailable.

    A past year's predictions never change, so those are kept for 30
    days; the current and coming years for a day, in case HKO revises
    them.
    """
    code = station_id.upper()
    if code not in STATION_BY_ID:
        return []
    cache_file = cache_dir() / f"hko_{data_type.lower()}_{code}_{year}.json"
    max_age = 30 * 86400 if year < datetime.now(HKT).year else 86400
    url = (f"{HKO_BASE}?dataType={data_type}&station={code}"
           f"&year={year}&rformat=json")
    data = fetch_json_cached(cache_file, max_age, url, timeout=20, fallback=None)
    if not isinstance(data, dict):
        return []
    rows = data.get("data")
    return rows if isinstance(rows, list) else []


def _day(year: int, row: list[str]) -> date | None:
    try:
        return date(year, int(row[0]), int(row[1]))
    except (IndexError, ValueError, TypeError):
        return None


def parse_hhot_rows(rows: list[list[str]], year: int) -> list[tuple[datetime, float]]:
    """(datetime_hkt, height_ft) points from a year's HHOT rows.

    The hour columns are labelled 01 to 24: 24 is midnight closing the
    day, so it lands on the next date, and no row has an hour 00.
    """
    points = []
    dropped = 0
    for row in rows:
        day = _day(year, row)
        if day is None:
            dropped += 1
            continue
        midnight = datetime(day.year, day.month, day.day, tzinfo=HKT)
        for hour, val in enumerate(row[2:26], start=1):
            try:
                height_ft = float(val) * M_TO_FT
            except (ValueError, TypeError):
                continue
            points.append((midnight + timedelta(hours=hour), height_ft))
    log_skipped("tides/hko", "HHOT rows", dropped, len(rows))
    return points


def parse_hlt_rows(rows: list[list[str]], year: int) -> list[tuple[datetime, float]]:
    """(datetime_hkt, height_ft) turning points from a year's HLT rows,
    in time order and not yet labelled high or low."""
    events = []
    dropped = 0
    for row in rows:
        day = _day(year, row)
        if day is None:
            dropped += 1
            continue
        for t_str, h_str in zip(row[2::2], row[3::2]):
            if not t_str:
                break
            try:
                hhmm = t_str.zfill(4)
                dt = datetime(day.year, day.month, day.day,
                              int(hhmm[:2]), int(hhmm[2:]), tzinfo=HKT)
                height_ft = float(h_str) * M_TO_FT
            except (ValueError, TypeError):
                continue
            events.append((dt, height_ft))
    log_skipped("tides/hko", "HLT rows", dropped, len(rows))
    events.sort(key=lambda p: p[0])
    return events


# ---------------------------------------------------------------------------
# Ranges
# ---------------------------------------------------------------------------
def fetch_tides_range_hko(station_id: str, start_date: date, end_date: date,
                          station_tz: tzinfo | None = None,
                          ) -> list[tuple[datetime, float]]:
    """Hourly predictions from *start_date* through *end_date*, as sorted
    (datetime, height_ft) points. HKO is always HKT, so *station_tz* is
    accepted for the provider interface and not needed."""
    lo, hi = local_day_bounds(start_date, end_date, HKT)
    points = []
    for year in range(start_date.year, end_date.year + 1):
        points.extend(p for p in parse_hhot_rows(_fetch_year("HHOT", station_id, year), year)
                      if lo <= p[0] < hi)
    points.sort(key=lambda p: p[0])
    return points


def fetch_hilo_range_hko(station_id: str, start_date: date, end_date: date,
                         station_tz: tzinfo | None = None,
                         ) -> list[tuple[datetime, float, str]]:
    """Highs and lows from *start_date* through *end_date*, as sorted
    (datetime, height_ft, "H"/"L") tuples.

    The years are joined before labelling so the last event of December
    and the first of January see each other as neighbours.
    """
    lo, hi = local_day_bounds(start_date, end_date, HKT)
    events = []
    for year in range(start_date.year, end_date.year + 1):
        events.extend(parse_hlt_rows(_fetch_year("HLT", station_id, year), year))
    events.sort(key=lambda p: p[0])
    return [e for e in label_hilo(events) if lo <= e[0] < hi]


def fetch_y_range_hko(station_id: str, center_date: date,
                      station_tz: tzinfo | None = None) -> tuple[float, float] | None:
    """The y-axis range from the highs and lows around *center_date*.
    Cached 7 days, keyed by month like the other providers."""
    start, end, key = y_range_window(center_date)

    def heights():
        hilo = fetch_hilo_range_hko(station_id, start, end, station_tz)
        if hilo:
            return [h for _, h, _ in hilo]
        return [h for _, h in fetch_tides_range_hko(station_id, start, end, station_tz)]

    return cached_y_range(
        cache_dir() / f"hko_yrange_{station_id.upper()}_{key}.json", heights)
