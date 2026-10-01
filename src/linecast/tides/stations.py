"""Which station a place's tides are read from, and what drawing one takes.

_station_for_location routes a place to a provider and its nearest
station, the country's own service first and Open-Meteo's global model
last.  _station_details and _station_tzinfo read the station's name and
time zone from its metadata, _station_now is the time there, and
_fetch_station fetches everything the chart needs side by side.
_find_matching_stations searches every provider's list by name, for
--station, --search and --nearby.
"""

import sys
from datetime import datetime, timezone, timedelta

from linecast._geo import haversine_nm
from linecast._location import resolve_location
from linecast._plaintext import plain_text
from linecast._log import log_failure
from linecast.tides.marine import fetch_marine
from linecast.tides.tidecheck import budget_line as tidecheck_budget_line
from linecast.tides.providers import (
    CHS, HKO, NOAA, OPENMETEO, PROVIDERS, QLD, TICON, TIDECHECK,
)


# The United States and the territories whose tides NOAA tabulates.
NOAA_COUNTRIES = {"US", "PR", "VI", "GU", "AS", "MP", "UM"}


def _is_qld_lat_lng(lat, lng):
    """Check if coordinates are roughly within Queensland, Australia.

    Queensland spans approximately:
    - Latitude: -10 (Cape York) to -29 (southern border)
    - Longitude: 138 (western border) to 154 (eastern coast)
    """
    return -30 <= lat <= -9 and 137 <= lng <= 155


def _station_for_location(lat, lng, country_code, label=""):
    """Pick a provider and station for a location: (provider, id, name).

    The regional provider for the country goes first (CHS for Canada, QLD
    for Queensland, HKO for Hong Kong). Then the TICON-4 gauges, which
    leave out the United States and Canada, and NOAA, which may have a
    station in range even when the regional one found nothing (Victoria
    BC, or an outage): in the US and its territories NOAA comes first,
    and abroad, where its stations are few and far apart, a TICON gauge
    within 30 nm does. TideCheck follows when a key is set, and
    Open-Meteo's global model is the last resort. (None, None, None) when
    nothing covers the spot.

    *label* is the name the geocoder gave the place the user asked for.
    A stationless provider names its pseudo-station by reverse-geocoding
    the point, which is a slower way of getting a worse answer, so the
    label stands in when there is one.
    """
    order = []
    if country_code == "CA":
        order.append(CHS)
    elif country_code == "AU" and _is_qld_lat_lng(lat, lng):
        order.append(QLD)
    elif country_code == "HK":
        order.append(HKO)
    if country_code in NOAA_COUNTRIES or country_code == "CA":
        order += [NOAA, TICON]
    else:
        order += [TICON, NOAA]
    if TIDECHECK.available():
        order.append(TIDECHECK)
    order.append(OPENMETEO)

    for provider in order:
        # A provider that raises is passed over like one with no station
        # in reach, so the ones after it, down to the global model, still
        # get their turn.
        try:
            if provider.stationless:
                station_id, station_name = provider.nearest(lat, lng, label=label)
            else:
                station_id, station_name = provider.nearest(lat, lng)
        except Exception as exc:
            log_failure(_provider_tag(provider), "nearest station", exc,
                        fallback="next provider", trace=True)
            continue
        if station_id is not None:
            return provider, station_id, plain_text(station_name)
    return None, None, None


def _station_details(provider, station_id, station_name):
    """The station's metadata, its display name, and its time zone."""
    station_meta = provider.station_metadata(station_id)
    if station_meta:
        # a station's name is the provider's text, never its escape sequences
        station_meta = {key: plain_text(value) for key, value in station_meta.items()}
        meta_name = station_meta.get("name", "")
        meta_state = station_meta.get("state", "")
        if meta_name:
            station_name = f"{meta_name}, {meta_state}" if meta_state else meta_name
    return station_meta, station_name, _station_tzinfo(station_meta)


def _fetch_station(provider, station_id, station_meta, station_tz, live):
    """Everything the view draws for a station, fetched side by side:
    (fetch_start, fetch_end, y_range, marine_data, predictions, hilo).

    Live mode pre-fetches ~7 days in each direction; the static view
    needs today and its neighbours. Only the metadata was a dependency;
    the y-axis range (fixed from historical hilo data), the marine
    conditions, and the predictions themselves are independent, so a
    cold start costs one round trip. The fetches run on daemon threads,
    so Ctrl-C does not wait for one stuck in its timeout.
    """
    from linecast._fanout import Fanout

    def fetch_marine_data():
        # Marine/wave conditions are optional; never crash the tides view
        try:
            lat = station_meta.get("lat") if station_meta else None
            lng = station_meta.get("lng") if station_meta else None
            if lat is not None and lng is not None:
                return fetch_marine(float(lat), float(lng))
        except Exception as exc:
            log_failure("marine/open-meteo", "marine fetch", exc,
                        fallback="no marine line")
        return None

    today = _station_now(station_meta).date()
    days = 7 if live else 1
    fetch_start = today - timedelta(days=days)
    fetch_end = today + timedelta(days=days)
    fanout = Fanout()
    fut_y_range = fanout.submit(provider.y_range, station_id, today, station_tz)
    fut_marine = fanout.submit(fetch_marine_data)
    fut_preds = fanout.submit(provider.tides_range, station_id,
                              fetch_start, fetch_end, station_tz)
    fut_hilo = fanout.submit(provider.hilo_range, station_id,
                             fetch_start, fetch_end, station_tz)
    tag = _provider_tag(provider)
    y_range = fanout.settle(fut_y_range, "y-range", tag=tag, note="auto-scaled axis")
    marine_data = fanout.settle(fut_marine, "marine", tag=tag, note="no marine line")
    preds = fanout.settle(fut_preds, "predictions", tag=tag, note="no tide data")
    hilo = fanout.settle(fut_hilo, "hi/lo", tag=tag, note="no high/low markers")
    return fetch_start, fetch_end, y_range, marine_data, preds, hilo


# NOAA's zone abbreviations, standard and summer time alike, and the
# zone each stands for; the four that turn on the state or on whether
# the station keeps summer time are settled in _abbr_zone.
_ABBR_ZONES = {
    **dict.fromkeys(("CST", "CDT"), "America/Chicago"),
    **dict.fromkeys(("PST", "PDT"), "America/Los_Angeles"),
    **dict.fromkeys(("AKST", "AKDT"), "America/Anchorage"),
    **dict.fromkeys(("HST", "HDT"), "Pacific/Honolulu"),
    "CHST": "Pacific/Guam",
    "SST": "Pacific/Pago_Pago",
}


def _abbr_zone(tz_abbr, state, observedst):
    """The IANA zone for a NOAA station's abbreviation, or None."""
    if tz_abbr in ("EST", "EDT"):
        return "America/Puerto_Rico" if state in ("PR", "VI") else "America/New_York"
    if tz_abbr in ("MST", "MDT"):
        return "America/Phoenix" if not observedst or state == "AZ" else "America/Denver"
    if tz_abbr in ("HAST", "HADT"):
        # NOAA's name for the Aleutians west of 169.5°W, which keep
        # summer time; Hawaii does not
        return "America/Adak" if observedst else "Pacific/Honolulu"
    if tz_abbr in ("AST", "ADT"):
        return "America/Halifax" if observedst else "America/Puerto_Rico"
    return _ABBR_ZONES.get(tz_abbr)


def _station_tzinfo(meta):
    """Resolve a station timezone to tzinfo using metadata and safe fallbacks."""
    if not meta:
        return None

    # CHS stations provide IANA timezone directly
    tz_code = meta.get("timeZoneCode")
    if tz_code:
        try:
            from zoneinfo import ZoneInfo
            return ZoneInfo(tz_code)
        except Exception as exc:
            log_failure("tz", f"lookup of {tz_code}", exc, fallback="abbreviation mapping")

    tz_abbr = str(meta.get("timezone_abbr", "")).upper()
    state = str(meta.get("state", "")).upper()
    observedst = bool(meta.get("observedst", False))

    if tz_abbr in ("UTC", "GMT", "Z"):
        return timezone.utc
    zone_name = _abbr_zone(tz_abbr, state, observedst)

    if zone_name:
        try:
            from zoneinfo import ZoneInfo
            return ZoneInfo(zone_name)
        except Exception as exc:
            log_failure("tz", f"lookup of {zone_name}", exc, fallback="fixed offset")

    # Fallback: fixed offset from metadata (less precise around DST boundaries)
    corr = meta.get("timezonecorr")
    if corr is None:
        return None
    try:
        return timezone(timedelta(hours=float(corr)))
    except (TypeError, ValueError, OverflowError) as exc:
        log_failure("tz", "offset from metadata", exc, fallback="no timezone")
        return None


def _provider_tag(provider):
    """The provider's name in the debug log."""
    return {"openmeteo": "tides/open-meteo"}.get(provider.name, f"tides/{provider.name}")


def _station_now(meta, series=None):
    """Current datetime in station local time when possible.

    *series* is the station's data, a list of tuples that start with a
    datetime.  When the metadata gives no zone but the data is aware
    (CHS and TideCheck answer in UTC and convert, and a cached row
    keeps its offset), "now" is taken in the data's zone: a naive now
    beside aware predictions cannot be compared with them at all, and
    the view would fall over rather than draw.
    """
    tz = _station_tzinfo(meta)
    if tz is None and series:
        tz = series[0][0].tzinfo
    if tz is not None:
        return datetime.now(tz)
    return datetime.now()


def _find_matching_stations(query, cli_location=None):
    """Match stations across all providers by tokenized name/state search.

    Every whitespace-separated token of *query* must appear somewhere in a
    station's searchable text — name, state abbreviation, full state name,
    or country — so multi-word queries like "portland maine" work.

    Returns a list of dicts {source, id, name, dist_nm}, sorted by distance
    from the current location when one is known (alphabetically otherwise).

    An empty query matches every station, so callers can list the nearest
    stations by passing "".
    """
    tokens = [t for t in query.lower().split() if t]

    candidates = []
    for provider in PROVIDERS.values():
        try:
            candidates.extend(provider.search(query, tokens))
        except Exception as exc:
            log_failure(_provider_tag(provider), "station search", exc,
                        fallback="its stations left out", trace=True)

    here_lat, here_lng, _country = resolve_location(cli_location)
    for c in candidates:
        c["name"] = plain_text(c.get("name", ""))
        try:
            c["dist_nm"] = haversine_nm(
                here_lat, here_lng, float(c.pop("lat")), float(c.pop("lng")))
        except (TypeError, ValueError):
            c.pop("lat", None)
            c.pop("lng", None)
            c["dist_nm"] = None
    if here_lat is not None:
        candidates.sort(
            key=lambda c: (c["dist_nm"] is None, c["dist_nm"] or 0.0, c["name"]))
    else:
        candidates.sort(key=lambda c: c["name"])

    return candidates


def _search_stations(query, metric=False, limit=20, cli_location=None):
    """Print stations matching *query* (all stations when empty), nearest
    first, and exit."""
    nearby = not query.strip()
    matches = _find_matching_stations(query, cli_location=cli_location)

    if not matches:
        if nearby:
            print("Could not fetch any station lists (offline?).")
        else:
            print(f"No stations matching \"{query}\". "
                  "Try `linecast tides --nearby` to list the nearest stations.")
        sys.exit(0)

    if nearby:
        matches = [c for c in matches if c["dist_nm"] is not None] or matches
        print("Nearest tide stations:")

    for c in matches[:limit]:
        left = c["name"] if c["id"] == c["name"] else f"{c['id']}  {c['name']}"
        dist = ""
        if c["dist_nm"] is not None:
            if metric:
                dist = f" — {c['dist_nm'] * 1.852:.0f} km"
            else:
                dist = f" — {c['dist_nm'] * 1.15078:.0f} mi"
        print(f"  {left}{dist}{PROVIDERS[c['source']].tag}")

    if len(matches) > limit:
        print(f"  ... and {len(matches) - limit} more")
    print("\nUse `linecast tides --station <id or name>` to view one.")
    budget = tidecheck_budget_line()
    if budget:
        print(budget)
