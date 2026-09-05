"""The MeteoAlarm region file: what the bake script writes, the runtime
reads; the loader fails soft; and the shipped file holds together.

tests/test_weather_parsing.py asks the shipped file about real places.
This file is about the contract around it: scripts/build_meteoalarm_regions.py
and linecast._meteoalarm_regions agree on the format, a missing or
broken file costs nobody an alert, and the file that ships carries
every country the runtime will ask it about.

linecast is imported inside fixtures and tests, never at module level:
tests/test_oneline.py re-imports the package mid-session, and a module
object bound at collection time would be the stale one.
"""

import gzip
import importlib.util
import re
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

BAKE_SCRIPT = Path(__file__).parent.parent / "scripts" / "build_meteoalarm_regions.py"


@pytest.fixture(scope="module")
def bake():
    """The bake script as a module. The sdist leaves scripts/ out."""
    if not BAKE_SCRIPT.exists():
        pytest.skip("scripts/build_meteoalarm_regions.py is not in this tree")
    spec = importlib.util.spec_from_file_location("build_meteoalarm_regions", BAKE_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def mr():
    """The runtime module, with its cache left the way it was found."""
    from linecast import _meteoalarm_regions
    saved = (_meteoalarm_regions._REGIONS, _meteoalarm_regions._CODES)
    _meteoalarm_regions._REGIONS, _meteoalarm_regions._CODES = None, None
    yield _meteoalarm_regions
    _meteoalarm_regions._REGIONS, _meteoalarm_regions._CODES = saved


def _square(lat0, lat1, lng0, lng1):
    """A closed GeoJSON ring, [lng, lat] order, around a lat/lng box."""
    return [[lng0, lat0], [lng1, lat0], [lng1, lat1], [lng0, lat1], [lng0, lat0]]


# Two regions the way the bake script sees them: a plain polygon, and a
# multipolygon whose first part has a hole.
GEOMETRY = [
    ("AA001", {"type": "Polygon", "coordinates": [_square(50, 51, 10, 11)]}),
    ("NUTS3/AA001", {"type": "MultiPolygon", "coordinates": [
        [_square(52, 53, 10, 11), _square(52.2, 52.4, 10.2, 10.4)],
        [_square(54, 55, 12, 13)],
    ]}),
]


class TestRoundTrip:
    """pack() in the script and _parse() in the runtime are one format."""

    def test_packed_regions_parse_back(self, bake, mr):
        raw, npts = bake.pack(GEOMETRY)
        regions = mr._parse(raw)
        assert [key for key, _, _ in regions] == ["AA001", "NUTS3/AA001"]
        assert npts == 4 + 4 + 4 + 4
        _, bbox, polygons = regions[1]
        assert bbox == pytest.approx((52.0, 55.0, 10.0, 13.0))
        assert len(polygons) == 2
        outer, holes = polygons[0]
        assert len(outer) == 4 and len(holes) == 1
        assert polygons[1][1] == []

    def test_the_hole_and_the_second_part_survive(self, bake, mr):
        raw, _ = bake.pack(GEOMETRY)
        mr._REGIONS = mr._parse(raw)
        assert mr.regions_at(50.5, 10.5) == {"AA001"}
        assert mr.regions_at(52.5, 10.5) == {"NUTS3/AA001"}
        assert mr.regions_at(52.3, 10.3) == set()      # inside the hole
        assert mr.regions_at(54.5, 12.5) == {"NUTS3/AA001"}
        assert mr.known("NUTS3/AA001") and not mr.known("AA002")

    def test_a_baked_file_loads_from_disk(self, bake, mr, tmp_path):
        raw, _ = bake.pack(GEOMETRY)
        path = tmp_path / "regions.bin.gz"
        path.write_bytes(gzip.compress(raw))
        with patch.object(mr, "_PATH", str(path)):
            assert mr.regions_at(50.5, 10.5) == {"AA001"}

    def test_coordinates_keep_five_decimals(self, bake, mr):
        ring = [[10.123456, 50.654321], [11, 50], [11, 51], [10.123456, 50.654321]]
        raw, _ = bake.pack([("AA001", {"type": "Polygon", "coordinates": [ring]})])
        (_, _, polygons), = mr._parse(raw)
        lat, lng = polygons[0][0][0]
        assert (lat, lng) == pytest.approx((50.65432, 10.12346), abs=1e-9)


class TestSimplification:
    def test_a_point_on_a_straight_edge_is_dropped(self, bake):
        ring = [(0, 0), (1, 0), (2, 0), (2, 2), (0, 2), (0, 0)]
        assert bake.simplify_ring(ring, 0.01) == [(0, 0), (2, 0), (2, 2), (0, 2)]

    def test_a_corner_past_the_tolerance_is_kept(self, bake):
        ring = [(0, 0), (1, 0.5), (2, 0), (2, 2), (0, 2), (0, 0)]
        assert (1, 0.5) in bake.simplify_ring(ring, 0.01)

    def test_a_ring_too_small_to_simplify_is_returned_whole(self, bake):
        assert bake.simplify_ring([(0, 0), (1, 0), (0, 1)], 0.01) == [(0, 0), (1, 0), (0, 1)]

    def test_a_polyline_keeps_its_ends(self, bake):
        line = [(0, 0), (1, 0.001), (2, -0.001), (3, 0)]
        assert bake.douglas_peucker(line, 0.01) == [(0, 0), (3, 0)]


class TestRegionSelection:
    """regions() keys each source the way key_for will look it up."""

    def test_sources_are_keyed_by_type_and_aliased_where_a_feed_mislabels(self, bake):
        geom = {"type": "Polygon", "coordinates": [_square(0, 1, 0, 1)]}
        geocodes = {"features": [
            {"properties": {"type": "EMMA_ID", "code": "PL3001", "country": "PL"},
             "geometry": geom},
            {"properties": {"type": "EMMA_ID", "code": "MK001", "country": "MK"},
             "geometry": geom},
            {"properties": {"type": "NUTS3", "code": "PL911", "country": "PL"},
             "geometry": geom},
        ]}
        nuts3 = {"features": [
            {"properties": {"CNTR_CODE": "FR", "NUTS_ID": "FR101"}, "geometry": geom},
            {"properties": {"CNTR_CODE": "DE", "NUTS_ID": "DE111"}, "geometry": geom},
        ]}
        nuts2 = {"features": [
            {"properties": {"CNTR_CODE": "HU", "NUTS_ID": "HU10"}, "geometry": geom},
            {"properties": {"CNTR_CODE": "FR", "NUTS_ID": "FR10"}, "geometry": geom},
        ]}
        orp = {"features": [
            {"properties": {"kod": 19, "nazev": "Praha"}, "geometry": geom},
            {"properties": {"kod": 582786, "nazev": "Brno"}, "geometry": geom},
        ]}
        cisorp = [{"kod_ruian": "19", "chodnota": "1000"},
                  {"kod_ruian": "582786", "chodnota": "6203"}]

        items = bake.regions(geocodes, nuts3, nuts2, orp, cisorp)

        assert [key for key, _ in items] == [
            "CISORP/1000", "CISORP/1100", "CISORP/6203",
            "MK001", "NUTS2/HU10", "NUTS3/FR101", "NUTS3/MK001", "PL3001",
        ]
        for key, geometry in items:
            assert geometry is geom, key


def _coded_feed(area_desc, code):
    """One Moderate warning naming its ground by EMMA_ID."""
    return {"warnings": [{"alert": {"info": [{
        "language": "en-GB", "severity": "Moderate", "event": "Storm",
        "area": [{"areaDesc": area_desc,
                  "geocode": [{"valueName": "EMMA_ID", "value": code}]}],
    }]}}]}


def _alerts(data, lat, lng, address):
    from linecast import _weather_sources as ws
    with patch.object(ws, "fetch_json_cached", return_value=data), \
            patch.object(ws, "write_cache", lambda *a, **k: None):
        return ws._fetch_alerts_meteoalarm(lat, lng, "poland", address=address)


class TestLoaderFailsSoft:
    """Without the file, alerts go back to matching on the area name."""

    @pytest.fixture(autouse=True)
    def _debug(self, mr):
        from linecast._runtime import set_debug
        set_debug(True)
        yield
        set_debug(False)

    def _check_fallback(self, mr, capsys):
        assert mr.regions_at(52.23, 21.01) == set()
        assert not mr.known("PL1465")
        mr.regions_at(52.23, 21.01)
        lines = [line for line in capsys.readouterr().err.splitlines()
                 if "weather/alerts: meteoalarm regions failed" in line]
        assert len(lines) == 1, "the failure is logged once, not on every call"
        assert lines[0].endswith("; matching alerts by area name")
        # and the area name is what decides, the code counting for nothing
        data = _coded_feed("powiat chodzieski", "PL3001")
        assert len(_alerts(data, 52.995, 16.92, {"county": "powiat chodzieski"})) == 1
        assert _alerts(data, 52.995, 16.92, {"city": "Warszawa"}) == []

    def test_a_missing_file(self, mr, tmp_path, capsys):
        with patch.object(mr, "_PATH", str(tmp_path / "missing.bin.gz")):
            self._check_fallback(mr, capsys)

    def test_a_file_of_another_version(self, mr, tmp_path, capsys):
        path = tmp_path / "v1.bin.gz"
        path.write_bytes(gzip.compress(b"LCMA\x01\x00\x00"))
        with patch.object(mr, "_PATH", str(path)):
            self._check_fallback(mr, capsys)

    def test_a_truncated_file(self, bake, mr, tmp_path, capsys):
        raw, _ = bake.pack(GEOMETRY)
        path = tmp_path / "cut.bin.gz"
        path.write_bytes(gzip.compress(raw[:len(raw) // 2]))
        with patch.object(mr, "_PATH", str(path)):
            self._check_fallback(mr, capsys)

    def test_a_file_that_is_not_gzip(self, mr, tmp_path, capsys):
        path = tmp_path / "plain.bin.gz"
        path.write_bytes(b"not gzip at all")
        with patch.object(mr, "_PATH", str(path)):
            self._check_fallback(mr, capsys)


KEY = re.compile(r"[A-Z]{2}[A-Z0-9]+|(NUTS2|NUTS3|CISORP)/[A-Z0-9]+")


class TestShippedFile:
    """The file in the wheel is whole, and covers what the router routes."""

    @pytest.fixture(autouse=True)
    def _load(self, mr):
        self.mr = mr
        self.regions = mr._load()
        assert self.regions, "the shipped file did not load"

    def test_keys_are_unique_and_spelled_as_key_for_spells_them(self):
        keys = [key for key, _, _ in self.regions]
        assert len(set(keys)) == len(keys)
        assert all(KEY.fullmatch(key) for key in keys)

    def test_every_ring_closes_a_shape_inside_its_bounding_box(self):
        for key, (lat_min, lat_max, lng_min, lng_max), polygons in self.regions:
            assert polygons, key
            for outer, holes in polygons:
                for ring in (outer, *holes):
                    assert len(ring) >= 3, key
                    for lat, lng in ring:
                        assert lat_min <= lat <= lat_max, key
                        assert lng_min <= lng <= lng_max, key

    def test_every_meteoalarm_country_has_ground_or_files_polygons(self):
        # A new member added to the router needs a re-bake; this is
        # where that shows. Switzerland, the UK and Ukraine put a CAP
        # polygon on every warning and publish no EMMA regions; Estonia,
        # Israel, Luxembourg and Sweden file polygons too, and their
        # regions left MeteoAlarm's list in its 2026 editions.
        from linecast._weather_sources import _METEOALARM_SLUGS
        emma_countries = {key[:2] for key, _, _ in self.regions if "/" not in key}
        assert (set(_METEOALARM_SLUGS) - emma_countries
                == {"CH", "EE", "GB", "IL", "LU", "SE", "UA"})

    def test_the_typed_regions_are_the_ones_the_bake_script_declares(self, bake):
        # The countries the script lists under NUTS, plus the alias
        # written for North Macedonia, and no others: a country added to
        # the script without a re-bake, or baked and then dropped from
        # the script, fails here.
        by_type = {}
        for key, _, _ in self.regions:
            kind, _, code = key.partition("/")
            if code:
                by_type.setdefault(kind, set()).add(code[:2])
        expected = {level: set(countries) for level, countries in bake.NUTS.items()}
        for country, level in bake.ALIASES.items():
            expected.setdefault(level, set()).add(country)
        cisorp = by_type.pop("CISORP", set())  # Czech ORP codes carry no country
        assert by_type == expected
        assert {"10", "11"} <= cisorp  # Prague, under both its spellings

    def test_a_lookup_is_quick(self):
        # A weather call in Europe pays this once; it must not be felt.
        import time
        start = time.perf_counter()
        for _ in range(20):
            self.mr.regions_at(48.8566, 2.3522)
        assert (time.perf_counter() - start) / 20 < 0.05
