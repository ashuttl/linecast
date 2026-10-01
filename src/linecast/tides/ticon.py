"""Tide gauges around the world, predicted here from their constants.

TICON-4 (Hart-Davis, Dettmering and Seitz, 2025) fitted the harmonic
constants of every gauge in the GESLA-4 sea-level archive; the Slackwater
database cleans them up, names each gauge and finds its time zone, and
derives its mean sea level and chart datum from the record. linecast
bundles the 1,215 gauges outside the United States and Canada whose
licence allows it (scripts/build_ticon_stations.py writes
data/ticon.json.gz), and the tide machine in tides/harmonic.py adds up
their constants for whatever dates the view asks for. There is no
request and no horizon: next week and the year 2040 cost the same.

Heights are above the chart datum Slackwater gives the gauge's country
(LAT in most of Europe, MLLW in Japan, mean sea level where the tide is
too small to chart), in the gauge's own time zone. A gauge is used for
places within 30 nautical miles of it; tides change too much along a
coast for one farther off to stand in, and the global model takes over
there.

Checked against: the same tide machine fed NOAA's constants reproduces
NOAA's tables to a few millimetres. TICON-4's constants, from different
records than the agencies' own, put 2026's highs and lows within a
minute or two (half of them; nine in ten within four) and 2 cm of
Kartverket's at Andenes and Ny-Ålesund, Tokyo's hourly heights within
3 cm of JMA's (the turns within 4 minutes, nine in ten within 12), and
Portland's highs and lows within 2 minutes and 3 cm of NOAA's. The
chart datums agree with the agencies' to 2 cm in Norway and 3.5 in
Tokyo.
"""

import gzip
import json
from datetime import date, datetime, timedelta, timezone, tzinfo
from functools import lru_cache
from typing import Any

from linecast._geo import haversine_nm
from linecast._log import log_failure
from linecast._paths import data_path
from linecast.tides import harmonic
from linecast.tides.common import M_TO_FT, local_day_bounds, y_range_window

PREFIX = "ticon:"
# How far a gauge's tide is allowed to stand in for a place's.
MAX_NM = 30


@lru_cache(maxsize=1)
def _bundle() -> dict[str, Any]:
    """The bundled constants as {id: station}, each station a dict of the
    file's columns. Empty when the file cannot be read."""
    try:
        raw = json.loads(gzip.decompress(data_path("ticon.json.gz").read_bytes()))
    except (OSError, ValueError) as exc:
        log_failure("tides/ticon", "read of ticon.json.gz", exc, fallback="no TICON stations")
        return {}
    names = raw["constituents"]
    stations = {}
    for (ident, name, region, country, lat, lng, tz, datum, z0,
         amps, phases) in raw["stations"]:
        stations[ident] = {
            "id": ident, "name": name, "region": region, "country": country,
            "lat": lat, "lng": lng, "tz": tz, "datum": datum, "z0": z0 / 1000,
            "constants": [(n, a / 1000, p / 10)
                          for n, a, p in zip(names, amps, phases) if a],
        }
    return stations


def station_by_id(station_id: str) -> dict[str, Any] | None:
    """The bundled gauge for a "ticon:" id, or None."""
    if not station_id.startswith(PREFIX):
        return None
    return _bundle().get(station_id[len(PREFIX):])


def is_ticon_station_id(text: str) -> bool:
    return text.startswith(PREFIX)


def stations() -> list[dict[str, Any]]:
    return list(_bundle().values())


def _region(station: dict[str, Any]) -> str:
    """The gauge's region, unless it only repeats the gauge's name
    ("Tokyo", Tokyo)."""
    region = station["region"]
    return region if region.lower() not in station["name"].lower() else ""


def display_name(station: dict[str, Any]) -> str:
    """"Brest, Brittany": the gauge and its region, as NOAA's read
    "Portland, ME"."""
    region = _region(station)
    return f"{station['name']}, {region}" if region else station["name"]


def find_nearest_station_ticon(lat: float, lng: float) -> tuple[str | None, str | None]:
    """The closest gauge within MAX_NM as (id, name), else (None, None).

    The list is bundled, so this needs no network and no cache.
    """
    best, best_dist = None, float("inf")
    for station in _bundle().values():
        distance = haversine_nm(lat, lng, station["lat"], station["lng"])
        if distance < best_dist:
            best, best_dist = station, distance
    if best is None or best_dist > MAX_NM:
        return None, None
    return PREFIX + best["id"], display_name(best)


def fetch_station_metadata_ticon(station_id: str) -> dict[str, Any] | None:
    """Station metadata in the shape the NOAA pipeline reads."""
    s = station_by_id(station_id)
    if s is None:
        return None
    return {
        "id": station_id,
        "name": s["name"],
        "state": _region(s),
        "lat": s["lat"],
        "lng": s["lng"],
        "timezone_abbr": "",
        "timeZoneCode": s["tz"],
        "observedst": False,
        "datum": s["datum"],
        "source": "ticon",
    }


@lru_cache(maxsize=8)
def _tide(station_id: str) -> harmonic.Tide | None:
    s = station_by_id(station_id)
    if s is None:
        return None
    return harmonic.Tide(s["constants"], z0=s["z0"])


def _window(start_date, end_date, station_tz):
    lo, hi = local_day_bounds(start_date, end_date, station_tz)
    if station_tz is None:
        lo, hi = lo.replace(tzinfo=timezone.utc), hi.replace(tzinfo=timezone.utc)
    return lo, hi


def _local(t: datetime, station_tz: tzinfo | None) -> datetime:
    return t.astimezone(station_tz) if station_tz is not None else t.replace(tzinfo=None)


def fetch_tides_range_ticon(station_id: str, start_date: date, end_date: date,
                            station_tz: tzinfo | None) -> list[tuple[datetime, float]]:
    """Six-minute heights across the dates, in feet, as NOAA serves them."""
    tide = _tide(station_id)
    if tide is None:
        return []
    lo, hi = _window(start_date, end_date, station_tz)
    return [(_local(t, station_tz), h * M_TO_FT) for t, h in tide.series(lo, hi, 6)]


def fetch_hilo_range_ticon(station_id: str, start_date: date, end_date: date,
                           station_tz: tzinfo | None) -> list[tuple[datetime, float, str]]:
    """The highs and lows across the dates, in feet."""
    tide = _tide(station_id)
    if tide is None:
        return []
    lo, hi = _window(start_date, end_date, station_tz)
    return [(_local(t, station_tz), h * M_TO_FT, kind) for t, h, kind in tide.extremes(lo, hi)]


def fetch_y_range_ticon(station_id: str, center_date: date,
                        station_tz: tzinfo | None) -> tuple[float, float] | None:
    """(lowest, highest) of the highs and lows over the y-axis window.

    Three months of extremes take a few hundredths of a second to
    compute, so unlike the network providers' this is not cached.
    """
    start, end, _key = y_range_window(center_date)
    heights = [h for _t, h, _k in fetch_hilo_range_ticon(station_id, start, end, station_tz)]
    if not heights:
        return None
    return min(heights), max(heights)
