"""Live checks against every provider linecast talks to.

These are the tests that say whether the world still answers: each one
makes a real request and runs the reply through the same code the
commands use, so an outage and a changed feed both show up as a failed
test naming the provider.  They are marked integration, which the
conftest network guard honours, and the ordinary suite leaves them
out; .github/workflows/live.yml runs them on a schedule and opens an
issue when one fails.  Run them by hand with

    pytest tests/test_live_providers.py -m integration

Most fetchers absorb a failure and hand back a fallback, so a dead
feed can look like a quiet day.  The `failures` fixture turns --debug
on and reads the "<provider>: <operation> failed" lines that
log_failure writes, and every test asserts there were none.

TideCheck needs a key.  The conftest scrubs LINECAST_TIDECHECK_KEY so
no test can lean on the user's; the live test reads
LINECAST_LIVE_TIDECHECK_KEY instead and skips when it is unset.
"""

import os
from datetime import date, datetime, timedelta, timezone

import pytest

pytestmark = pytest.mark.integration

PORTLAND = (43.66, -70.25)          # Portland, Maine: NOAA tides, NWS alerts
HALIFAX = (44.65, -63.57)           # CHS tides, ECCC alerts
BRISBANE = (-27.47, 153.03)         # Queensland tides
HONG_KONG = (22.28, 114.16)         # HKO tides and warnings
PORTLAND_BBOX = (-70.35, 43.60, -70.15, 43.72)   # west, south, east, north
MANHATTAN_BBOX = (-74.02, 40.70, -73.93, 40.80)


@pytest.fixture
def failures(capfd):
    """Switch --debug on for the test and return a callable that lists
    the absorbed failures logged so far."""
    from linecast._runtime import set_debug
    set_debug(True)

    def collect():
        err = capfd.readouterr().err
        return [line for line in err.splitlines() if " failed" in line]

    yield collect
    set_debug(False)


def _today_span():
    today = date.today()
    return today, today + timedelta(days=1)


# ---------------------------------------------------------------------------
# Open-Meteo
# ---------------------------------------------------------------------------
def test_open_meteo_forecast(failures):
    from linecast._weather_sources import fetch_forecast
    data = fetch_forecast(*PORTLAND)
    assert failures() == []
    assert data is not None
    assert data["current"]["temperature_2m"] is not None
    assert len(data["hourly"]["temperature_2m"]) >= 24 * 7
    assert len(data["daily"]["sunrise"]) >= 7


def test_open_meteo_geocoder(failures):
    from linecast._weather_sources import geocode_first
    hit = geocode_first("Westbrook, Maine")
    assert failures() == []
    assert hit is not None
    lat, lng, label = hit
    assert 43 < lat < 44 and -71 < lng < -70
    assert "Westbrook" in label


def test_open_meteo_air_quality(failures):
    from linecast._weather_sources import fetch_aqi
    data = fetch_aqi(*PORTLAND)
    assert failures() == []
    assert data is not None
    assert "us_aqi" in data["current"]


def test_open_meteo_marine(failures):
    from linecast._marine import fetch_marine, parse_marine_current
    data = fetch_marine(43.55, -70.05)   # a few miles off Cape Elizabeth
    assert failures() == []
    current = parse_marine_current(data)
    assert current is not None
    assert current["wave_height"] is not None


def test_open_meteo_archive(failures):
    from linecast._weather_historical import fetch_historical
    averages = fetch_historical(*PORTLAND, date.today())
    assert failures() == []
    assert averages is not None
    assert averages.years >= 1
    assert averages.avg_high > averages.avg_low


def test_open_meteo_tides(failures):
    from linecast._tides_openmeteo import (fetch_hilo_range_openmeteo,
                                           fetch_station_metadata_openmeteo,
                                           make_station_id)
    station = make_station_id(*PORTLAND)
    meta = fetch_station_metadata_openmeteo(station)
    hilo = fetch_hilo_range_openmeteo(station, *_today_span(), timezone.utc)
    assert failures() == []
    assert meta is not None
    assert len(hilo) >= 3
    assert {t for _, _, t in hilo} <= {"H", "L"}


# ---------------------------------------------------------------------------
# Location
# ---------------------------------------------------------------------------
def test_ipinfo_geolocation(failures):
    from linecast._location import get_location
    lat, lng, country = get_location()
    assert failures() == []
    assert lat is not None and lng is not None
    assert len(country or "") == 2


@pytest.mark.parametrize("provider", ["ipwho.is", "GeoJS"])
def test_geolocation_fallbacks(failures, provider):
    # the second and third opinions, asked directly: get_location would
    # only reach them with ipinfo down
    from linecast._http import fetch_json
    from linecast._location import PROVIDERS
    _name, url, parse = next(p for p in PROVIDERS if p[0] == provider)
    lat, lng, country = parse(
        fetch_json(url, headers={"Accept": "application/json"}, timeout=10))
    assert failures() == []
    assert -90 <= lat <= 90 and -180 <= lng <= 180
    assert len(country) == 2


def test_photon_geocoder_fallback(failures):
    # the geocoder's second source, asked directly: _geocode_query would
    # only reach it with Open-Meteo down
    from linecast._weather_sources import _photon_query
    results = _photon_query("Westbrook, Maine")
    assert failures() == []
    assert any(r["admin1"] == "Maine" and r["country_code"] == "US"
               for r in results)


def test_nominatim_reverse(failures):
    from linecast._weather_sources import _reverse_geocode
    name, country, address = _reverse_geocode(*PORTLAND)
    assert failures() == []
    assert country == "US"
    assert name
    assert address.get("country_code") == "us"


# ---------------------------------------------------------------------------
# Alerts, one feed per country the router knows
# ---------------------------------------------------------------------------
ALERT_FEEDS = [
    ("US", PORTLAND, "NWS"),
    ("CA", HALIFAX, "Environment Canada"),
    ("DE", (52.52, 13.40), "Bright Sky"),
    ("NO", (59.91, 10.75), "MET Norway"),
    ("IE", (53.35, -6.26), "Met Éireann"),
    ("JP", (35.68, 139.69), "JMA"),
    ("HK", HONG_KONG, "HKO"),
    ("CN", (39.90, 116.40), "CMA"),
    ("NL", (52.37, 4.90), "MeteoAlarm"),
]


@pytest.mark.parametrize("country, point, provider", ALERT_FEEDS,
                         ids=[f[2] for f in ALERT_FEEDS])
def test_alerts(failures, country, point, provider):
    from linecast._weather_sources import fetch_alerts
    alerts = fetch_alerts(*point, country_code=country, address={})
    assert failures() == [], provider
    assert isinstance(alerts, list)
    for alert in alerts:
        assert alert.get("event") or alert.get("headline"), alert


# ---------------------------------------------------------------------------
# MeteoAlarm: every feed's warnings can still be placed
# ---------------------------------------------------------------------------
# A warning with no CAP polygon is matched by a geocode against the
# region file baked into the wheel, and that file only knows the codes
# the feeds filed when it was baked. A feed that moves to a new NUTS
# edition, or starts filing a code type the file lacks, would fall back
# to matching on the area name without a word; this asks every feed,
# every day, whether the file still places all of it.
from linecast._weather_sources import _METEOALARM_SLUGS  # noqa: E402


@pytest.mark.parametrize("country, slug", sorted(_METEOALARM_SLUGS.items()),
                         ids=sorted(_METEOALARM_SLUGS))
def test_meteoalarm_feed_is_placed(failures, country, slug):
    from linecast._http import fetch_json
    from linecast._weather_sources import (_METEOALARM_FEED_BYTES, _cap_polygons,
                                           _region_keys)
    # under the runtime's own cap, so a feed outgrowing it fails here too
    feed = fetch_json(f"https://feeds.meteoalarm.org/api/v1/warnings/feeds-{slug}",
                      headers={"Accept": "application/json"}, timeout=15,
                      limit=_METEOALARM_FEED_BYTES)
    assert failures() == []
    unplaced = {}
    for w in feed.get("warnings", []):
        for info in w.get("alert", {}).get("info", []):
            for area in info.get("area", []):
                if _cap_polygons(area) or _region_keys([area]):
                    continue
                codes = " ".join(f"{g.get('valueName')}/{g.get('value')}"
                                 for g in area.get("geocode") or []) or "(no geocode)"
                unplaced[codes] = unplaced.get(codes, 0) + 1
    assert not unplaced, (
        f"{country}: {sum(unplaced.values())} areas the region file cannot place: "
        + "; ".join(f"{n} x [{codes}]" for codes, n in sorted(unplaced.items())[:12]))


# ---------------------------------------------------------------------------
# Tides
# ---------------------------------------------------------------------------
def _check_hilo(hilo):
    assert len(hilo) >= 2
    assert all(isinstance(dt, datetime) for dt, _, _ in hilo)
    assert {t for _, _, t in hilo} <= {"H", "L"}


def test_noaa_tides(failures):
    from linecast._tides_noaa import fetch_hilo_range, fetch_station_metadata_noaa
    meta = fetch_station_metadata_noaa("8418150")
    hilo = fetch_hilo_range("8418150", *_today_span(), timezone.utc)
    assert failures() == []
    assert meta and "Portland" in meta.get("name", "")
    _check_hilo(hilo)


def test_chs_tides(failures):
    from linecast._tides_chs import (fetch_hilo_range_chs, fetch_station_metadata_chs,
                                     find_nearest_station_chs)
    station, _name = find_nearest_station_chs(*HALIFAX)
    assert station, "no CHS station near Halifax"
    meta = fetch_station_metadata_chs(station)
    hilo = fetch_hilo_range_chs(station, *_today_span(), timezone.utc)
    assert failures() == []
    assert meta and meta.get("name")
    _check_hilo(hilo)


def test_queensland_tides(failures):
    from linecast._tides_qld import (fetch_hilo_range_qld, fetch_station_metadata_qld,
                                     find_nearest_station_qld)
    station, _name = find_nearest_station_qld(*BRISBANE)
    assert station, "no Queensland station near Brisbane"
    meta = fetch_station_metadata_qld(station)
    hilo = fetch_hilo_range_qld(station, *_today_span(), timezone.utc)
    assert failures() == []
    assert meta and meta.get("name")
    _check_hilo(hilo)


def test_hko_tides(failures):
    from linecast._tides_hko import (fetch_hilo_range_hko, fetch_station_metadata_hko,
                                     find_nearest_station_hko)
    station, _name = find_nearest_station_hko(*HONG_KONG)
    assert station, "no HKO station near Hong Kong"
    meta = fetch_station_metadata_hko(station)
    hilo = fetch_hilo_range_hko(station, *_today_span(), timezone.utc)
    assert failures() == []
    assert meta and meta.get("name")
    _check_hilo(hilo)


def test_tidecheck_tides(failures, monkeypatch):
    key = os.environ.get("LINECAST_LIVE_TIDECHECK_KEY", "").strip()
    if not key:
        pytest.skip("LINECAST_LIVE_TIDECHECK_KEY is not set")
    monkeypatch.setenv("LINECAST_TIDECHECK_KEY", key)
    from linecast._tides_tidecheck import (fetch_hilo_range_tidecheck,
                                           find_nearest_station_tidecheck)
    station, _name = find_nearest_station_tidecheck(*PORTLAND)
    assert station, "no TideCheck station near Portland"
    hilo = fetch_hilo_range_tidecheck(station, *_today_span(), timezone.utc)
    assert failures() == []
    _check_hilo(hilo)


# ---------------------------------------------------------------------------
# Radar and clouds
# ---------------------------------------------------------------------------
def test_librewxr_radar_index(failures):
    from linecast._radar_tiles import fetch_index, librewxr_provider
    index = fetch_index(librewxr_provider(0))
    assert failures() == []
    assert index.get("host")
    assert index["radar"]["past"], "no past radar frames"


def test_librewxr_clouds(failures):
    from linecast import _globe_now
    from linecast._radar_tiles import fetch_index
    index = fetch_index(_globe_now._provider())
    assert failures() == []
    frames = (index.get("satellite") or {}).get("infrared") or []
    assert frames, "no infrared frames"
    assert frames[-1].get("path")


def test_rainviewer_radar_index(failures):
    from linecast._radar_tiles import fetch_index, rainviewer_provider
    index = fetch_index(rainviewer_provider())
    assert failures() == []
    assert index.get("host")
    assert index["radar"]["past"], "no past radar frames"


def test_iem_radar_frame(failures):
    from linecast._radar_sources import IEMSource
    source = IEMSource(3)
    frames = source.current_frames()
    assert frames
    width, height, rgba = source.frame_rgba(PORTLAND_BBOX, 40, 10, frames[-1])
    assert failures() == []
    assert width > 0 and height > 0
    assert len(rgba) == width * height * 4


def test_iem_warnings(failures):
    from linecast._radar_warnings import warnings_at
    warnings = warnings_at(datetime.now(timezone.utc))
    assert failures() == []
    assert isinstance(warnings, list)
    for _sev, _color, rings, info in warnings:
        assert rings and isinstance(info, dict)


# ---------------------------------------------------------------------------
# Maps
# ---------------------------------------------------------------------------
def test_openfreemap_tiles(failures):
    from linecast._vtiles import fetch_tile, tile_info, tiles_for_bbox
    info = tile_info()
    assert failures() == []
    assert info is not None
    template, version, maxzoom = info
    assert "{z}" in template and maxzoom >= 10
    keys = tiles_for_bbox(PORTLAND_BBOX, 10)
    assert keys
    data = fetch_tile(*keys[0])
    assert failures() == []
    assert data, "empty or missing tile over Portland"


def test_osmus_streets_fallback(failures):
    # the street tiles' second source, asked directly: fetch_tile would
    # only reach it with OpenFreeMap down
    from linecast._http import MAX_BODY_BYTES, fetch_bytes, fetch_json, gunzip_limited
    from linecast._mvt import decode_tile
    from linecast._vtiles import FALLBACK_TILEJSON_URL, tiles_for_bbox
    tj = fetch_json(FALLBACK_TILEJSON_URL, timeout=10)
    template = tj["tiles"][0]
    assert "{z}" in template
    z, x, y = tiles_for_bbox(PORTLAND_BBOX, 10)[0]
    url = (template.replace("{z}", str(z))
           .replace("{x}", str(x)).replace("{y}", str(y)))
    data = fetch_bytes(url, headers={"Accept-Encoding": "gzip"}, timeout=15)
    if data[:2] == b"\x1f\x8b":
        data = gunzip_limited(data, MAX_BODY_BYTES)
    layers = decode_tile(data)
    assert failures() == []
    assert "water" in layers and "transportation" in layers


def test_aws_terrain_tiles(failures):
    from linecast._elevation import elevation_grid
    grid = elevation_grid(PORTLAND_BBOX, 16, 8)
    assert failures() == []
    samples = [v for row in grid for v in row if v is not None]
    assert samples, "no elevation samples arrived"
    assert -100 < max(samples) < 1000


def test_builtup_raster(failures):
    from linecast._builtup import builtup_grid
    grid = builtup_grid(MANHATTAN_BBOX, 16, 8)
    assert failures() == []
    assert max(max(row) for row in grid) > 0, "Manhattan reads as unbuilt"


def test_photon_search(failures):
    from linecast._maps_search import photon_search
    results = photon_search("Westbrook", *PORTLAND, zoom=10)
    assert failures() == []
    assert results
    assert any("Westbrook" in r.name for r in results)


def test_nominatim_search(failures):
    from linecast._maps_search import nominatim_search
    results = nominatim_search("Westbrook, Maine")
    assert failures() == []
    assert results
    assert any("Westbrook" in r.name for r in results)


def test_osrm_route(failures):
    from linecast._maps_route import route
    found = route("car", PORTLAND, (43.677, -70.371))   # to Westbrook
    assert failures() == []
    assert len(found.coords) > 10
    assert found.distance_m > 5000
