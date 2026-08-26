"""Queensland (Australia) tide data source.

Uses the Queensland Government Open Data Portal (CKAN API).  Predictions
come from Maritime Safety Queensland's per-gauge "predicted interval
data" datasets: a full year of 10-minute astronomical predictions per
CSV resource, in metres above LAT and AEST.  This module converts to
feet for compatibility with the NOAA-based rendering pipeline.

Gauge packages carry no coordinates, so GAUGE_COORDS below holds them;
regenerate it with scripts/build_qld_tide_stations.py when the portal
adds gauges.  A gauge absent from the table is still reachable by name
(--station, --search), just never offered as the nearest station.
"""

import json
import re
import urllib.parse
from datetime import date, datetime, timezone, timedelta, tzinfo
from typing import Any

from linecast._cache import location_cache_key, read_cache, read_stale, write_cache
from linecast._geo import haversine_nm
from linecast._http import fetch_json
from linecast._runtime import log_failure
from linecast._tides_common import (
    M_TO_FT, NEAREST_STATION_MAX_NM, cache_dir, cached_y_range, dedup_sorted,
    label_hilo, nearest_station, parse_cached_dt, station_coords,
    y_range_window,
)

QLD_BASE = "https://www.data.qld.gov.au/api/3/action"
GAUGE_PKG_SUFFIX = "-tide-gauge-predicted-interval-data"
# Queensland does not observe DST; AEST is always UTC+10.
AEST = timezone(timedelta(hours=10))

# Coordinates per gauge, keyed by package name minus GAUGE_PKG_SUFFIX.
# From the gauge's description file where the package has one (degrees +
# minutes, so about a nautical mile of precision), geocoded from the
# gauge's name otherwise; both serve only to rank stations by distance.
GAUGE_COORDS = {
    "abbot-point": (-19.8823, 148.0795),
    "amrun": (-12.9474, 141.6331),
    "aurukun-archer-river": (-13.3561, 141.7267),
    "badu-island": (-10.1205, 142.1408),
    "boigu-island": (-9.2600, 142.2142),
    "bowen": (-20.0167, 148.2500),
    "brisbane-bar": (-27.3667, 153.1667),
    "bundaberg": (-24.7667, 152.3833),
    "burnett-heads": (-24.7657, 152.4096),
    "cairns": (-16.9167, 145.7667),
    "cape-ferguson": (-19.2766, 147.0612),
    "cape-flattery": (-14.9711, 145.3118),
    "cardwell": (-18.2706, 146.0164),
    "clump-point": (-17.8558, 146.1197),
    "coconut-island-poruma": (-10.0502, 143.0693),
    "cooktown": (-15.3718, 144.9029),
    "darnley-island-erub": (-9.5851, 143.7698),
    "dauan-island": (-9.4233, 142.5370),
    "deep-water-bend-pine-river": (-27.2987, 153.0338),
    "fisherman-s-landing": (-23.7934, 151.1544),
    "gladstone-auckland-point": (-23.8333, 151.2500),
    "gold-coast-seaway": (-27.9347, 153.4292),
    "golding-reciprocal-f-l-gladstone": (-23.8042, 151.2982),
    "hammond-island": (-10.5480, 142.2110),
    "hay-point": (-21.2667, 149.3000),
    "inscription-point-sweers-island": (-17.1123, 139.5958),
    "karumba": (-17.5000, 140.8333),
    "karumba-bar": (-17.4604, 140.8306),
    "kingfisher-bay-jetty": (-25.3919, 153.0330),
    "kubin-moa-island": (-10.2261, 142.2192),
    "lizard-island": (-14.6683, 145.4609),
    "lucinda": (-18.5325, 146.3373),
    "mabuiag-island": (-9.9578, 142.1796),
    "mackay": (-21.1000, 149.2167),
    "military-jetty-pumicestone-passage": (-26.8335, 153.1195),
    "mooloolaba": (-26.6667, 153.1333),
    "mornington-island": (-16.6667, 139.1667),
    "mossman": (-16.4614, 145.3727),
    "mourilyan": (-17.6000, 146.1167),
    "murray-island-meer": (-9.9170, 144.0508),
    "noosa-head": (-26.4001, 153.0910),
    "north-cardinal-beacon-townsville": (-19.2526, 146.8417),
    "pinkenba": (-27.3945, 153.1431),
    "port-alma": (-23.5833, 150.8667),
    "port-douglas": (-16.4846, 145.4636),
    "portland-roads": (-12.5959, 143.4122),
    "rockhampton": (-23.3782, 150.5134),
    "rosslyn-bay": (-23.1667, 150.8000),
    "saibai-island": (-9.3969, 142.6811),
    "scarborough": (-27.2063, 153.1139),
    "shorncliffe": (-27.3269, 153.0828),
    "shute-harbour": (-20.2833, 148.7833),
    "skardon-river": (-11.8667, 142.0106),
    "south-trees": (-23.8898, 151.2951),
    "southport": (-27.9667, 153.4167),
    "st-pauls-moa-island": (-10.2067, 142.2808),
    "stephens-island-ugar": (-9.5076, 143.5454),
    "sue-island-warraber": (-10.2079, 142.8237),
    "tangalooma": (-27.1777, 153.3735),
    "thursday-island": (-10.5667, 142.2167),
    "tin-can-bay-snapper-creek": (-25.9254, 152.9947),
    "townsville": (-19.2500, 146.8333),
    "twin-island": (-10.4624, 142.4476),
    "urangan": (-25.3000, 152.9167),
    "urangan-fairway-beacon": (-25.2970, 152.9063),
    "waddy-point-k-gari": (-24.9651, 153.3505),
    "weipa": (-12.6833, 141.8500),
    "yam-island-iama": (-9.9009, 142.7748),
    "yorke-island-masig": (-9.7525, 143.4075),
}

# The provider used to draw from the storm-tide monitoring feed, whose
# stations were these slugs.  A saved TIDE_STATION or --station value
# from that era resolves to the gauge nearest the old site.
LEGACY_MONITORING_SITES = {
    "abellpoint": (-20.2608, 148.7103),
    "bananabank": (-27.5411, 153.3368),
    "birkdale": (-27.4747, 153.2190),
    "boigultg": (-9.2293, 142.2209),
    "bundaberg": (-24.7704, 152.3819),
    "coombabahst": (-27.9184, 153.3442),
    "donnybrook": (-26.9980, 153.0709),
    "hallsbay": (-26.8797, 153.1170),
    "lagunaltg": (-20.6020, 148.6818),
    "maroochydore": (-26.6431, 153.0888),
    "noosamunna": (-26.0000, 153.0000),
    "poruma": (-10.0493, 143.0639),
    "rabybay": (-27.5155, 153.2796),
    "scarborough": (-27.1936, 153.1093),
    "stpauls": (-10.1957, 142.3341),
    "tangalooma": (-27.1780, 153.3710),
    "tewantinmb": (-26.3951, 153.0421),
    "thursdayisland": (-10.5863, 142.2216),
    "tincanbay": (-25.8990, 153.0139),
    "townsvillecard": (-19.1266, 146.9095),
    "tuan": (-25.6822, 152.8843),
    "tweedsbj": (-28.1721, 153.5577),
    "warraber": (-10.2042, 142.8222),
    "whyteislandnx": (-27.4017, 153.1574),
}


def _safe_name(station_name):
    """A station name as a cache file name component."""
    return station_name.replace(" ", "_").replace("/", "_")


# ---------------------------------------------------------------------------
# Station discovery
# ---------------------------------------------------------------------------
def fetch_all_stations_qld(max_age: float = 30 * 86400) -> list[dict[str, Any]]:
    """Fetch the QLD gauge list from the portal (cached 30 days).

    One package_search for the "predicted interval data" datasets gives
    every gauge with its per-year resource ids.  A gauge whose CSVs are
    not loaded into the datastore cannot be queried and is left out.
    """
    cache_file = cache_dir() / "qld_stations.json"
    cached = read_cache(cache_file, max_age)
    if cached is not None:
        return cached

    params = urllib.parse.urlencode({
        "q": '"predicted interval data"',
        "rows": "100",
    })
    url = f"{QLD_BASE}/package_search?{params}"
    try:
        data = fetch_json(url, timeout=15)
    except Exception as exc:
        stale = read_stale(cache_file)
        log_failure("tides/qld", "station list fetch", exc, url=url,
                    fallback="stale cache" if stale else "no stations")
        return stale if stale else []

    if not data or not isinstance(data, dict):
        return []

    stations = []
    for pkg in data.get("result", {}).get("results", []):
        pkg_name = pkg.get("name", "")
        if not pkg_name.endswith(GAUGE_PKG_SUFFIX):
            continue
        title = pkg.get("title", "")
        display = title.split(" tide gauge")[0].strip() or pkg_name

        # Data resources are named "<year>—<gauge> ..."; only those
        # loaded into the datastore can be queried.
        years = {}
        for res in pkg.get("resources", []):
            m = re.match(r"\s*(\d{4})\b", res.get("name") or "")
            if m and res.get("datastore_active") and res.get("id"):
                years[m.group(1)] = res["id"]
        if not years:
            continue

        coords = GAUGE_COORDS.get(pkg_name[:-len(GAUGE_PKG_SUFFIX)])
        stations.append({
            "name": display,
            "package": pkg_name,
            "lat": coords[0] if coords else None,
            "lng": coords[1] if coords else None,
            "years": years,
        })

    if stations:
        write_cache(cache_file, stations)
    return stations


def _station_record(station_name: str) -> dict[str, Any] | None:
    """The gauge record for a station name, or None.

    A monitoring-era site name (from a stale nearest-station cache or a
    saved TIDE_STATION) resolves to the gauge nearest the old site, so
    data flows under the old name too.
    """
    for s in fetch_all_stations_qld():
        if s.get("name") == station_name:
            return s
    return legacy_station_for_slug(station_name)


def find_nearest_station_qld(lat: float, lng: float) -> tuple[str | None, str | None]:
    """Find closest QLD tide gauge by haversine distance.

    Returns (station_name, station_name) or (None, None).  Cached 1 hour.
    QLD stations are identified by name, not numeric ID.
    """
    return nearest_station(
        cache_dir() / f"qld_station_{location_cache_key(lat, lng)}.json", lat, lng,
        fetch_all_stations_qld, station_coords,
        lambda s: (s["name"], s["name"]),
        tag="tides/qld",
    )


def legacy_station_for_slug(text: str) -> dict[str, Any] | None:
    """The gauge nearest an old monitoring-feed site named by *text*.

    Saved station values from the monitoring-feed era ("birkdale") name
    sites that no longer exist; the closest gauge stands in for them.
    """
    coords = LEGACY_MONITORING_SITES.get(text.strip().lower())
    if coords is None:
        return None

    best, best_dist = None, float("inf")
    for station in fetch_all_stations_qld():
        point = station_coords(station)
        if point is None:
            continue
        distance = haversine_nm(*coords, *point)
        if distance < best_dist:
            best, best_dist = station, distance
    if best is None or best_dist > NEAREST_STATION_MAX_NM:
        return None
    return best


# ---------------------------------------------------------------------------
# Station metadata
# ---------------------------------------------------------------------------
def fetch_station_metadata_qld(station_name: str) -> dict[str, Any]:
    """Build QLD station metadata, normalized to match NOAA/CHS shape.

    Returns dict with: id, name, state, lat, lng, timezone_abbr,
    timezonecorr, timeZoneCode, observedst, source.
    """
    cache_file = cache_dir() / f"qld_meta_{_safe_name(station_name)}.json"
    cached = read_cache(cache_file, 30 * 86400)
    if cached and cached.get("source") == "qld":
        return cached

    record = _station_record(station_name)
    meta = {
        "id": station_name,
        "name": station_name,
        "state": "QLD",
        "lat": record.get("lat") if record else None,
        "lng": record.get("lng") if record else None,
        "timezone_abbr": "AEST",
        "timezonecorr": 10,
        "timeZoneCode": "Australia/Brisbane",
        "observedst": False,
        "source": "qld",
    }
    write_cache(cache_file, meta)
    return meta


# ---------------------------------------------------------------------------
# High/low detection
# ---------------------------------------------------------------------------
def _find_extrema(points):
    """Find local extrema (peaks and troughs) from prediction points.

    Returns list of (dt, height_ft) tuples at turning points.
    """
    if len(points) < 3:
        return list(points)

    # The readings are rounded to the centimetre, so a neap stand is a
    # staircase of equal values.  Each run of equal heights collapses to
    # one point at its middle; between two runs the height always
    # changes, so a strict turning-point test on the runs yields peaks
    # and troughs that alternate, never two lows in a row.
    runs = []
    i = 0
    while i < len(points):
        j = i
        while j + 1 < len(points) and points[j + 1][1] == points[i][1]:
            j += 1
        runs.append((points[(i + j) // 2][0], points[i][1]))
        i = j + 1

    extrema = []
    for k in range(1, len(runs) - 1):
        h_prev, h_curr, h_next = runs[k - 1][1], runs[k][1], runs[k + 1][1]
        if (h_curr > h_prev and h_curr > h_next) or (h_curr < h_prev and h_curr < h_next):
            extrema.append(runs[k])

    return extrema


# ---------------------------------------------------------------------------
# Prediction fetching
# ---------------------------------------------------------------------------
def _parse_gauge_dt(date_str, time_str):
    """AEST datetime from a record's "DD/MM/YYYY" and "HH:MM"."""
    day, month, year = date_str.split("/")
    hour, minute = time_str.split(":")
    return datetime(int(year), int(month), int(day), int(hour), int(minute),
                    tzinfo=AEST)


def _dates_by_year(start_date, end_date):
    """The days start..end inclusive, grouped as {year: ["DD/MM/YYYY", ...]}."""
    by_year: dict[int, list[str]] = {}
    d = start_date
    while d <= end_date:
        by_year.setdefault(d.year, []).append(d.strftime("%d/%m/%Y"))
        d += timedelta(days=1)
    return by_year


def _year_resources(station_name, wanted_years):
    """The station's {year: resource_id} map, covering *wanted_years*.

    None when the station is unknown (which includes the list being
    unavailable), so callers can tell that apart from a year with no
    published resource.  The station list is cached a month, so a year
    published since (the portal adds next year's resource annually)
    triggers one refresh a day until it appears.
    """
    record = _station_record(station_name)
    if record is None:
        return None
    years = record.get("years", {})
    if any(str(y) not in years for y in wanted_years):
        fetch_all_stations_qld(max_age=86400)
        record = _station_record(station_name) or record
        years = record.get("years", {})
    return years


def _search_datastore(resource_id, dates, fields, limit, timeout=20):
    """One datastore_search for *dates* of a year resource.

    Resources are occasionally re-uploaded with the old rows left in
    place; sorting newest-first lets dedup_sorted keep the fresh copy.
    """
    params = urllib.parse.urlencode({
        "resource_id": resource_id,
        "filters": json.dumps({"Date": dates}),
        "fields": fields,
        "sort": "_id desc",
        "limit": str(limit),
    })
    url = f"{QLD_BASE}/datastore_search?{params}"
    data = fetch_json(url, timeout=timeout)
    if not data or not isinstance(data, dict):
        return []
    return data.get("result", {}).get("records", [])


def _fetch_pred_chunk(station_name, start_date, end_date):
    """Fetch a chunk of QLD predictions.

    Returns list of (datetime_aest, height_ft) tuples.
    """
    start_str = start_date.strftime("%Y%m%d")
    end_str = end_date.strftime("%Y%m%d")
    cache_file = cache_dir() / f"qld_pred_{_safe_name(station_name)}_{start_str}_{end_str}.json"

    cached = read_cache(cache_file, 86400)
    if cached is not None:
        return [(parse_cached_dt(r["dt"], AEST), r["v"]) for r in cached]

    by_year = _dates_by_year(start_date, end_date)
    years = _year_resources(station_name, by_year)
    if years is None:
        return []

    rows = []
    points = []
    for year, dates in by_year.items():
        resource_id = years.get(str(year))
        if not resource_id:
            # No resource for this year (typically next year's, not yet
            # published): the range just ends where the data does.
            continue
        try:
            records = _search_datastore(resource_id, dates,
                                        "Date,Time,Reading", limit=5000)
        except Exception as exc:
            stale = read_stale(cache_file)
            log_failure("tides/qld", "predictions fetch", exc,
                        fallback="stale cache" if stale is not None else "no data")
            if stale is not None:
                return [(parse_cached_dt(r["dt"], AEST), r["v"]) for r in stale]
            return []

        for rec in records:
            try:
                dt_local = _parse_gauge_dt(rec["Date"], rec["Time"])
                height_ft = float(rec["Reading"]) * M_TO_FT
            except (KeyError, ValueError, TypeError):
                continue
            rows.append({"dt": dt_local.isoformat(), "v": height_ft})
            points.append((dt_local, height_ft))

    write_cache(cache_file, rows)
    return points


def fetch_tides_range_qld(station_name: str, start_date: date, end_date: date,
                          station_tz: tzinfo | None = None) -> list[tuple[datetime, float]]:
    """Fetch QLD interval predictions across a date range.

    Returns sorted list of (datetime, height_ft) tuples.
    The station_tz parameter is accepted for API compatibility but QLD
    stations are always AEST.
    """
    points = []
    # Fetch in two-day chunks so scrolling reuses cached days.
    d = start_date
    while d <= end_date:
        chunk_end = min(d + timedelta(days=1), end_date)
        chunk = _fetch_pred_chunk(station_name, d, chunk_end)
        if chunk:
            points.extend(chunk)
        d = chunk_end + timedelta(days=1)
    return dedup_sorted(points)


def fetch_hilo_range_qld(station_name: str, start_date: date, end_date: date,
                         station_tz: tzinfo | None = None) -> list[tuple[datetime, float, str]]:
    """Fetch QLD high/low extremes across a date range.

    Returns sorted list of (datetime, height_ft, "H"/"L") tuples.
    Derived from prediction data by finding local extrema.
    """
    # Get the full prediction series first.
    preds = fetch_tides_range_qld(station_name, start_date, end_date, station_tz)
    if not preds:
        return []

    # Find turning points.
    extrema = _find_extrema(preds)
    if not extrema:
        return []

    return label_hilo(extrema)


def fetch_y_range_qld(station_name: str, center_date: date,
                      station_tz: tzinfo | None = None) -> tuple[float, float] | None:
    """Compute y-axis range from QLD prediction data.  Cached 7 days.

    The same month-long window the other providers measure, fetched as
    heights alone: one request per year resource covers it.
    """
    start, end, key = y_range_window(center_date)

    def heights():
        by_year = _dates_by_year(start, end)
        years = _year_resources(station_name, by_year)
        if years is None:
            return None
        values = []
        for year, dates in by_year.items():
            resource_id = years.get(str(year))
            if not resource_id:
                continue
            try:
                records = _search_datastore(resource_id, dates, "Reading",
                                            limit=32000, timeout=30)
            except Exception as exc:
                log_failure("tides/qld", "y-range fetch", exc, fallback="partial range")
                continue
            for rec in records:
                try:
                    values.append(float(rec["Reading"]) * M_TO_FT)
                except (KeyError, ValueError, TypeError):
                    continue
        return values

    return cached_y_range(
        cache_dir() / f"qld_yrange_{_safe_name(station_name)}_{key}.json", heights)
