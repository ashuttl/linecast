"""The tide providers, one record each, and the registry tides.py uses.

Each provider is a small class whose methods call its module's functions
at call time rather than capturing them at import, so patching a module
function (as the tests do) reaches the provider. Where a provider cannot
do something, its record says so in the method rather than by a flag.
"""

from datetime import date, datetime, tzinfo
from typing import Any

from linecast import _tides_chs as chs
from linecast import _tides_hko as hko
from linecast import _tides_noaa as noaa
from linecast import _tides_openmeteo as openmeteo
from linecast import _tides_qld as qld
from linecast import _tides_tidecheck as tidecheck

# Full names for the state/territory abbreviations NOAA stations carry, so
# queries like "portland maine" match "PORTLAND, ME".
US_STATE_NAMES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas",
    "CA": "California", "CO": "Colorado", "CT": "Connecticut",
    "DE": "Delaware", "FL": "Florida", "GA": "Georgia", "HI": "Hawaii",
    "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa",
    "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine",
    "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan",
    "MN": "Minnesota", "MS": "Mississippi", "MO": "Missouri",
    "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico",
    "NY": "New York", "NC": "North Carolina", "ND": "North Dakota",
    "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania",
    "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota",
    "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont",
    "VA": "Virginia", "WA": "Washington", "WV": "West Virginia",
    "WI": "Wisconsin", "WY": "Wyoming", "DC": "District of Columbia",
    "PR": "Puerto Rico", "VI": "Virgin Islands", "GU": "Guam",
    "AS": "American Samoa", "MP": "Northern Mariana Islands",
}


def _matches(haystack, tokens):
    """True when every query token appears in a station's searchable text."""
    return all(t in haystack for t in tokens)


class TideProvider:
    """What tides.py asks of a source.

    Station IDs are strings the provider recognises: NOAA's digits, CHS's
    24-hex ObjectIds, QLD's station names, HKO's three-letter codes,
    TideCheck's slugs, Open-Meteo's "om:lat,lng". Every method takes and returns the shapes the NOAA
    pipeline was built on: (datetime, height_ft) points, (datetime,
    height_ft, "H"/"L") extremes, and NOAA-shaped metadata dicts.
    """

    name: str = ""   # the source key: cache names and the --json payload
    tag: str = ""    # suffix on --search and --nearby listing lines
    label: str = ""  # the source's human name: the view's footer
    # True for a model with no stations behind it, whose "station" is the
    # requested point: the name it returns is one it made up for that
    # point, so a caller holding a better name should use its own.
    stationless: bool = False

    def available(self) -> bool:
        """False when the provider needs something the user has not set up."""
        return True

    def id_matches(self, text: str) -> bool:
        """True when a --station value looks like one of this provider's IDs."""
        return False

    def name_for_id(self, station_id: str) -> str:
        """Display name for a station given by ID, before metadata arrives."""
        return f"Station {station_id}"

    def nearest(self, lat: float, lng: float) -> tuple[str | None, str | None]:
        """(station_id, station_name) within range of a point, or (None, None).

        A *stationless* provider takes a further ``label`` keyword: the
        name the caller already holds for the point, which saves it
        working one out.
        """
        raise NotImplementedError

    def search(self, query: str, tokens: list[str]) -> list[dict[str, Any]]:
        """Stations matching a text query as {source, id, name, lat, lng} dicts."""
        return []

    def station_metadata(self, station_id: str) -> dict[str, Any] | None:
        raise NotImplementedError

    def tides_range(self, station_id: str, start_date: date, end_date: date,
                    station_tz: tzinfo | None) -> list[tuple[datetime, float]]:
        raise NotImplementedError

    def hilo_range(self, station_id: str, start_date: date, end_date: date,
                   station_tz: tzinfo | None) -> list[tuple[datetime, float, str]]:
        raise NotImplementedError

    def y_range(self, station_id: str, center_date: date,
                station_tz: tzinfo | None) -> tuple[float, float] | None:
        raise NotImplementedError


def _noaa_label(station):
    name = station.get("name", "")
    state = station.get("state", "")
    return f"{name}, {state}" if state else name


class _NOAA(TideProvider):
    name = "noaa"
    label = "NOAA"

    def id_matches(self, text):
        return text.isdigit()

    def name_for_id(self, station_id):
        for s in (noaa.fetch_all_stations_noaa() or []):
            if str(s.get("id", "")) == station_id:
                return _noaa_label(s)
        return f"Station {station_id}"

    def nearest(self, lat, lng):
        return noaa.find_nearest_station(lat, lng)

    def search(self, query, tokens):
        found = []
        for s in (noaa.fetch_all_stations_noaa() or []):
            state = s.get("state", "")
            haystack = (
                f"{s.get('name', '')} {state} {US_STATE_NAMES.get(state.upper(), '')}"
            ).lower()
            if _matches(haystack, tokens):
                found.append({
                    "source": self.name, "id": str(s.get("id", "")),
                    "name": _noaa_label(s),
                    "lat": s.get("lat"), "lng": s.get("lng"),
                })
        return found

    def station_metadata(self, station_id):
        return noaa.fetch_station_metadata_noaa(station_id)

    def tides_range(self, station_id, start_date, end_date, station_tz):
        return noaa.fetch_tides_range_with_fallback(
            station_id, start_date, end_date, station_tz)

    def hilo_range(self, station_id, start_date, end_date, station_tz):
        return noaa.fetch_hilo_range(station_id, start_date, end_date, station_tz)

    def y_range(self, station_id, center_date, station_tz):
        # NOAA serves its predictions in station local time already.
        return noaa.fetch_y_range(station_id, center_date)


class _CHS(TideProvider):
    name = "chs"
    tag = " (Canada)"
    label = "CHS"

    def id_matches(self, text):
        return chs.is_chs_station_id(text)

    def name_for_id(self, station_id):
        return f"Station {station_id[:8]}"

    def nearest(self, lat, lng):
        return chs.find_nearest_station_chs(lat, lng)

    def search(self, query, tokens):
        found = []
        for s in (chs.fetch_all_stations_chs() or []):
            name = s.get("officialName", "")
            if _matches(f"{name} canada".lower(), tokens):
                found.append({
                    "source": self.name, "id": str(s.get("id", "")), "name": name,
                    "lat": s.get("latitude"), "lng": s.get("longitude"),
                })
        return found

    def station_metadata(self, station_id):
        return chs.fetch_station_metadata_chs(station_id)

    def tides_range(self, station_id, start_date, end_date, station_tz):
        return chs.fetch_tides_range_chs(station_id, start_date, end_date, station_tz)

    def hilo_range(self, station_id, start_date, end_date, station_tz):
        return chs.fetch_hilo_range_chs(station_id, start_date, end_date, station_tz)

    def y_range(self, station_id, center_date, station_tz):
        return chs.fetch_y_range_chs(station_id, center_date, station_tz)


class _QLD(TideProvider):
    """Queensland stations are identified by name, so there is no ID form
    to recognise; a name reaches the provider through search."""

    name = "qld"
    tag = " (QLD, Australia)"
    label = "Queensland Open Data"

    def nearest(self, lat, lng):
        return qld.find_nearest_station_qld(lat, lng)

    def search(self, query, tokens):
        found = []
        for s in (qld.fetch_all_stations_qld() or []):
            name = s.get("name", "")
            if _matches(f"{name} qld queensland australia".lower(), tokens):
                found.append({
                    "source": self.name, "id": name, "name": name,
                    "lat": s.get("lat"), "lng": s.get("lng"),
                })
        if not found and tokens:
            # A saved value from the monitoring-feed era ("birkdale")
            # names a site that is gone; offer the gauge nearest it.
            legacy = qld.legacy_station_for_slug(query)
            if legacy:
                found.append({
                    "source": self.name, "id": legacy["name"],
                    "name": legacy["name"],
                    "lat": legacy.get("lat"), "lng": legacy.get("lng"),
                })
        return found

    def station_metadata(self, station_id):
        return qld.fetch_station_metadata_qld(station_id)

    def tides_range(self, station_id, start_date, end_date, station_tz):
        return qld.fetch_tides_range_qld(station_id, start_date, end_date, station_tz)

    def hilo_range(self, station_id, start_date, end_date, station_tz):
        return qld.fetch_hilo_range_qld(station_id, start_date, end_date, station_tz)

    def y_range(self, station_id, center_date, station_tz):
        return qld.fetch_y_range_qld(station_id, center_date, station_tz)


class _HKO(TideProvider):
    """Hong Kong Observatory: a fixed list of thirteen stations, so the
    search and the nearest lookup need no network."""

    name = "hko"
    tag = " (Hong Kong)"
    label = "Hong Kong Observatory"

    def id_matches(self, text):
        return hko.is_hko_station_id(text)

    def name_for_id(self, station_id):
        return hko.STATION_BY_ID[station_id.upper()]["name"]

    def nearest(self, lat, lng):
        return hko.find_nearest_station_hko(lat, lng)

    def search(self, query, tokens):
        found = []
        for s in hko.STATIONS:
            name = s["name"]
            if _matches(f"{name} hong kong hk".lower(), tokens):
                found.append({
                    "source": self.name, "id": s["id"], "name": name,
                    "lat": s["lat"], "lng": s["lng"],
                })
        return found

    def station_metadata(self, station_id):
        return hko.fetch_station_metadata_hko(station_id)

    def tides_range(self, station_id, start_date, end_date, station_tz):
        return hko.fetch_tides_range_hko(station_id, start_date, end_date, station_tz)

    def hilo_range(self, station_id, start_date, end_date, station_tz):
        return hko.fetch_hilo_range_hko(station_id, start_date, end_date, station_tz)

    def y_range(self, station_id, center_date, station_tz):
        return hko.fetch_y_range_hko(station_id, center_date, station_tz)


class _TideCheck(TideProvider):
    """Optional: inert without LINECAST_TIDECHECK_KEY."""

    name = "tidecheck"
    tag = " (TideCheck)"
    label = "TideCheck"

    def available(self):
        return tidecheck.is_available()

    def id_matches(self, text):
        # Without a key the slug is just text, and the search path will
        # say so
        return tidecheck.is_available() and tidecheck.is_tidecheck_station_id(text)

    def nearest(self, lat, lng):
        return tidecheck.find_nearest_station_tidecheck(lat, lng)

    def search(self, query, tokens):
        # The search runs server-side, so an empty query (--nearby) has
        # nothing to send; results carry coordinates like any other
        # provider's stations.
        if not tokens or not tidecheck.is_available():
            return []
        return [{
            "source": self.name, "id": str(s.get("id", "")),
            "name": s.get("name", ""),
            "lat": s.get("lat"), "lng": s.get("lng"),
        } for s in tidecheck.search_stations_tidecheck(query)]

    def station_metadata(self, station_id):
        return tidecheck.fetch_station_metadata_tidecheck(station_id)

    def tides_range(self, station_id, start_date, end_date, station_tz):
        return tidecheck.fetch_tides_range_tidecheck(
            station_id, start_date, end_date, station_tz)

    def hilo_range(self, station_id, start_date, end_date, station_tz):
        return tidecheck.fetch_hilo_range_tidecheck(
            station_id, start_date, end_date, station_tz)

    def y_range(self, station_id, center_date, station_tz):
        return tidecheck.fetch_y_range_tidecheck(station_id, center_date, station_tz)


class _OpenMeteo(TideProvider):
    """The global tide model: no stations, so nothing to search, and the
    "station" is the location itself, labelled with the place's name."""

    name = "openmeteo"
    label = "Open-Meteo tide model"
    stationless = True

    def id_matches(self, text):
        return openmeteo.is_openmeteo_station_id(text)

    def name_for_id(self, station_id):
        return "Tide model"

    def nearest(self, lat, lng, label=""):
        station_id, _ = openmeteo.find_nearest_openmeteo(lat, lng)
        if station_id is None:
            return None, None
        if label:
            # The caller geocoded a place name to get here and still has
            # what it was called; reverse-geocoding the coordinates back
            # into a worse version of it helps nobody.
            return station_id, label
        try:
            from linecast._sunshine_json import _location_label
            return station_id, _location_label(lat, lng)
        except Exception:
            return station_id, "Tide model"

    def station_metadata(self, station_id):
        return openmeteo.fetch_station_metadata_openmeteo(station_id)

    def tides_range(self, station_id, start_date, end_date, station_tz):
        return openmeteo.fetch_tides_range_openmeteo(
            station_id, start_date, end_date, station_tz)

    def hilo_range(self, station_id, start_date, end_date, station_tz):
        return openmeteo.fetch_hilo_range_openmeteo(
            station_id, start_date, end_date, station_tz)

    def y_range(self, station_id, center_date, station_tz):
        return openmeteo.fetch_y_range_openmeteo(station_id, center_date, station_tz)


NOAA = _NOAA()
CHS = _CHS()
QLD = _QLD()
HKO = _HKO()
TIDECHECK = _TideCheck()
OPENMETEO = _OpenMeteo()

# In search order: among stations at equal distance the listing keeps it.
PROVIDERS = {p.name: p for p in (NOAA, CHS, QLD, HKO, TIDECHECK, OPENMETEO)}


def provider_for_id(text: str) -> TideProvider | None:
    """The provider whose station IDs look like *text*, or None.

    Most specific first: the "om:" prefix, then CHS's 24-character hex
    ObjectId (which can happen to be all digits), then HKO's codes
    (letters, one with a digit; never all digits), then NOAA's digits,
    then TideCheck's hyphenated slugs (only once a key is set).
    """
    for provider in (OPENMETEO, CHS, HKO, NOAA, TIDECHECK):
        if provider.id_matches(text):
            return provider
    return None
