"""Tests for the TICON-4 gauges: the bundled constants and what is predicted
from them.

Nothing here is fetched. The bundle (data/ticon.json.gz) is read once for
the module; the tests of the search's edges and of a file that cannot be
read give the module a small file of their own instead.

One prediction is held against an agency's own: the Japan Meteorological
Agency's 2026 tide table for Tokyo, the row for 1 October (hourly heights
and the day's highs and lows, in centimetres, from
data.jma.go.jp/kaiyou/data/db/tide/suisan/txt/2026/TK.txt).
"""

import gzip
import json
import math
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from linecast._paths import data_path
from linecast.tides import harmonic, ticon
from linecast.tides.common import M_TO_FT

UTC = timezone.utc
BREST = "ticon:brest-822-fra-uhslc_fd"
TOKYO = "ticon:tokyo-ma15-jpn-jodc_jma"
PARIS = ZoneInfo("Europe/Paris")
JST = ZoneInfo("Asia/Tokyo")

# JMA's table for Tokyo, 1 October 2026: the height at each hour from
# 0:00 to 23:00, then the highs and the lows.
JMA_TOKYO_HOURS_CM = (41, 25, 29, 51, 85, 123, 155, 176, 182, 175, 159, 139,
                      123, 114, 117, 132, 155, 178, 193, 197, 186, 162, 130, 95)
JMA_TOKYO_TURNS = (("01:20", 24, "L"), ("07:55", 183, "H"), ("13:15", 114, "L"),
                   ("18:45", 197, "H"))

# A spread of gauges for the checks that take a year of hours each: a
# large Atlantic tide, the largest in the bundle (the Severn), a mixed
# Pacific one, a Baltic one of a few centimetres, a polar one, and one
# whose zone is three quarters of an hour off the others'.
A_SPREAD = ("brest-822-fra-uhslc_fd", "severn_bridge-ssc-gbr-cco", "tokyo-ma15-jpn-jodc_jma",
            "ueckermnde-9690088-deu-wsv", "scott_base-663a-nzl-uhslc_rq",
            "chatham-079-nzl-uhslc_fd")


@pytest.fixture(scope="module")
def raw():
    """The bundled file as it is on disk."""
    return json.loads(gzip.decompress(data_path("ticon.json.gz").read_bytes()))


@pytest.fixture(scope="module")
def gauges():
    return ticon.stations()


@pytest.fixture(scope="module")
def year_of_hours():
    """{id: (gauge, its tide, the heights of 2026 at each hour UTC)} for A_SPREAD."""
    out = {}
    for ident in A_SPREAD:
        gauge = ticon.station_by_id(ticon.PREFIX + ident)
        tide = harmonic.Tide(gauge["constants"], z0=gauge["z0"])
        hours = tide.series(datetime(2026, 1, 1, tzinfo=UTC),
                            datetime(2026, 12, 31, 23, tzinfo=UTC), 60)
        out[ident] = (gauge, tide, [h for _t, h in hours])
    return out


def _forget():
    ticon._bundle.cache_clear()
    ticon._tide.cache_clear()


@pytest.fixture
def bundle_file(tmp_path):
    """A path the module reads its bundle from instead of the real one.
    The test writes it (or leaves it missing) before asking anything; the
    real bundle is read again afterwards."""
    path = tmp_path / "ticon.json.gz"
    with patch.object(ticon, "data_path", return_value=path):
        _forget()
        yield path
    _forget()


def _row(ident, name, region, lat, lng, *, tz="UTC", datum="LAT", z0=1500,
         amps=(1000, 250), lags=(900, 1200)):
    """One station as the file has it: millimetres and tenths of a degree."""
    return [ident, name, region, "Nowhere", lat, lng, tz, datum, z0, list(amps), list(lags)]


def _write(path, rows, constituents=("M2", "S2")):
    payload = {"source": "a test", "attribution": "", "constituents": list(constituents),
               "stations": rows}
    path.write_bytes(gzip.compress(json.dumps(payload).encode()))


def _reach(gauge):
    """Every amplitude at once: as far from the mean level as the water
    could go if the nodal factors were all one."""
    return sum(amp for _name, amp, _lag in gauge["constants"])


def _fastest(gauge):
    """Every constituent rising at its fastest at once, in metres an hour."""
    return sum(amp * math.radians(harmonic.speed(name)) for name, amp, _lag in gauge["constants"])


class TestBundleFile:
    """The file on disk has the shape the module reads."""

    def test_it_names_its_source_and_carries_the_credit_the_licence_asks_for(self, raw):
        assert "TICON-4" in raw["source"]
        assert "Hart-Davis" in raw["attribution"]
        assert "CC BY 4.0" in raw["attribution"]

    def test_its_constituents_are_ones_the_tide_machine_knows_each_once(self, raw):
        names = raw["constituents"]
        assert len(names) == len(set(names))
        assert set(names) <= set(harmonic.CONSTITUENTS)
        assert {"M2", "S2", "N2", "K1", "O1"} <= set(names)

    def test_every_station_has_the_eleven_columns(self, raw):
        width = len(raw["constituents"])
        for row in raw["stations"]:
            assert len(row) == 11, row[0]
            ident, name, region, country, lat, lng, tz, datum, z0, amps, lags = row
            assert all(isinstance(text, str) for text in (ident, name, region, country,
                                                         tz, datum)), ident
            assert ident and name and country and tz and datum, ident
            assert len(amps) == len(lags) == width, ident

    def test_amplitudes_are_whole_millimetres_and_lags_tenths_of_a_degree(self, raw):
        for row in raw["stations"]:
            z0, amps, lags = row[8], row[9], row[10]
            assert isinstance(z0, int) and z0 >= 0, row[0]
            assert all(isinstance(a, int) and a >= 0 for a in amps), row[0]
            assert all(isinstance(g, int) and 0 <= g <= 3600 for g in lags), row[0]


class TestReadingTheBundle:
    """What the module makes of a file, shown on a small one."""

    def test_millimetres_and_tenths_come_out_as_metres_and_degrees(self, bundle_file):
        _write(bundle_file, [_row("a", "Alpha", "Region", 1.5, 2.5, tz="Europe/Paris",
                                  datum="LAT", z0=1500, amps=(1000, 250), lags=(900, 1205))])
        assert ticon.stations() == [{
            "id": "a", "name": "Alpha", "region": "Region", "country": "Nowhere",
            "lat": 1.5, "lng": 2.5, "tz": "Europe/Paris", "datum": "LAT", "z0": 1.5,
            "constants": [("M2", 1.0, 90.0), ("S2", 0.25, 120.5)],
        }]

    def test_a_constituent_the_gauge_does_not_have_is_left_out(self, bundle_file):
        _write(bundle_file, [_row("a", "Alpha", "", 0.0, 0.0, amps=(0, 250), lags=(0, 1200))])
        assert ticon.station_by_id("ticon:a")["constants"] == [("S2", 0.25, 120.0)]

    def test_a_file_with_no_stations_is_an_empty_list(self, bundle_file):
        _write(bundle_file, [])
        assert ticon.stations() == []
        assert ticon.find_nearest_station_ticon(48.38, -4.49) == (None, None)

    def test_the_gauge_is_predicted_from_its_own_constants_and_level(self, bundle_file):
        # S2 alone, lagging 90°, is high at 3:00 and 15:00 UTC, by its
        # amplitude over the mean level
        _write(bundle_file, [_row("a", "Alpha", "", 0.0, 0.0, z0=2000, amps=(0, 500),
                                  lags=(0, 900))])
        points = ticon.fetch_tides_range_ticon("ticon:a", date(2026, 3, 5), date(2026, 3, 5),
                                               UTC)
        by_time = dict(points)
        assert by_time[datetime(2026, 3, 5, 15, tzinfo=UTC)] == pytest.approx(2.5 * M_TO_FT)
        assert by_time[datetime(2026, 3, 5, 9, tzinfo=UTC)] == pytest.approx(1.5 * M_TO_FT)
        turns = ticon.fetch_hilo_range_ticon("ticon:a", date(2026, 3, 5), date(2026, 3, 5), UTC)
        assert [((t + timedelta(seconds=30)).strftime("%H:%M"), kind)
                for t, _h, kind in turns] == [("03:00", "H"), ("09:00", "L"),
                                              ("15:00", "H"), ("21:00", "L")]
        assert [h for _t, h, _kind in turns] == pytest.approx(
            [2.5 * M_TO_FT, 1.5 * M_TO_FT] * 2, abs=1e-6)


class TestAFileThatCannotBeRead:
    """With no bundle there are no gauges, and every question has its
    empty answer rather than an error."""

    def _nothing_anywhere(self):
        assert ticon.stations() == []
        assert ticon.station_by_id(BREST) is None
        assert ticon.find_nearest_station_ticon(48.38, -4.49) == (None, None)
        assert ticon.fetch_station_metadata_ticon(BREST) is None
        day = date(2026, 7, 1)
        assert ticon.fetch_tides_range_ticon(BREST, day, day, PARIS) == []
        assert ticon.fetch_hilo_range_ticon(BREST, day, day, PARIS) == []
        assert ticon.fetch_y_range_ticon(BREST, day, PARIS) is None

    def test_a_missing_file(self, bundle_file):
        assert not bundle_file.exists()
        self._nothing_anywhere()

    def test_a_file_that_is_not_gzip(self, bundle_file):
        bundle_file.write_bytes(b"not a gzip file")
        self._nothing_anywhere()

    def test_an_empty_file(self, bundle_file):
        bundle_file.write_bytes(b"")
        self._nothing_anywhere()

    def test_gzip_that_is_not_json(self, bundle_file):
        bundle_file.write_bytes(gzip.compress(b"not json"))
        self._nothing_anywhere()

    def test_a_gzip_file_cut_short(self, bundle_file):
        bundle_file.write_bytes(gzip.compress(b'{"constituents": ["M2"], "stations": []}')[:20])
        self._nothing_anywhere()

    def test_a_file_in_another_shape(self, bundle_file):
        for payload in (b"[]", b'{"stations": []}', b'{"constituents": [], "stations": [[1]]}'):
            bundle_file.write_bytes(gzip.compress(payload))
            _forget()
            self._nothing_anywhere()

    def test_the_real_bundle_is_read_again_afterwards(self, gauges):
        assert len(ticon.stations()) == len(gauges)


class TestGauges:
    """Every gauge in the bundle is one the tide machine can use."""

    def test_there_are_the_1215_the_docs_count(self, raw, gauges):
        # the module's docstring and docs/sources.md both give the number;
        # a rebuild that changes it changes them
        assert len(gauges) == len(raw["stations"]) == 1215

    def test_ids_are_distinct(self, raw):
        idents = [row[0] for row in raw["stations"]]
        assert len(set(idents)) == len(idents)

    def test_none_is_in_the_united_states_or_canada(self, gauges):
        countries = {g["country"] for g in gauges}
        assert not countries & {"United States", "Canada"}
        assert len(countries) > 90

    def test_every_gauge_is_somewhere_on_the_globe(self, gauges):
        for g in gauges:
            assert -90 <= g["lat"] <= 90 and -180 <= g["lng"] <= 180, g["id"]
        # and not all in one corner of it
        assert min(g["lat"] for g in gauges) < -60 and max(g["lat"] for g in gauges) > 60
        assert min(g["lng"] for g in gauges) < -150 and max(g["lng"] for g in gauges) > 150

    def test_every_time_zone_is_one_the_zone_database_has(self, gauges):
        for name in {g["tz"] for g in gauges}:
            ZoneInfo(name)

    def test_every_gauge_has_the_main_constituents_and_a_dozen_in_all(self, gauges):
        for g in gauges:
            names = {name for name, _amp, _lag in g["constants"]}
            assert {"M2", "K1"} <= names, g["id"]
            assert len(names) >= 12, g["id"]
            assert len(names) == len(g["constants"]), g["id"]

    def test_amplitudes_are_metres_and_lags_degrees(self, gauges):
        for g in gauges:
            for name, amp, lag in g["constants"]:
                # the Severn's M2, the largest here, is 4.3 m
                assert 0 < amp < 5, (g["id"], name)
                assert 0 <= lag <= 360, (g["id"], name)

    def test_the_tide_machine_keeps_every_constant_of_every_gauge(self, gauges):
        noon = datetime(2026, 10, 1, 12, tzinfo=UTC)
        for g in gauges:
            tide = harmonic.Tide(g["constants"], z0=g["z0"])
            assert tide.constants() == g["constants"], g["id"]
            # 1.2: the diurnal constituents' nodal factors reach 1.18
            assert abs(tide.height(noon) - g["z0"]) <= 1.2 * _reach(g), g["id"]

    def test_mean_sea_level_is_above_chart_datum_by_no_more_than_the_tide_can_fall(self, gauges):
        for g in gauges:
            if g["datum"] == "MSL":
                assert g["z0"] == 0, g["id"]
            else:
                assert 0 < g["z0"] <= _reach(g), g["id"]

    def test_gauges_on_mean_sea_level_are_the_ones_with_little_tide(self, gauges):
        on_msl = [g for g in gauges if g["datum"] == "MSL"]
        assert on_msl
        assert max(_reach(g) for g in on_msl) < 0.5

    def test_no_two_gauges_are_within_a_kilometre(self, gauges):
        by_lat = sorted(gauges, key=lambda g: g["lat"])
        for i, a in enumerate(by_lat):
            for b in by_lat[i + 1:]:
                if b["lat"] - a["lat"] > 0.01:  # 1.1 km of latitude
                    break
                east = (b["lng"] - a["lng"] + 180) % 360 - 180
                km = 111.2 * math.hypot(b["lat"] - a["lat"],
                                        east * math.cos(math.radians(a["lat"])))
                assert km >= 1, (a["id"], b["id"])


class TestLookup:
    """A gauge by its "ticon:" id."""

    def test_an_id_gives_its_gauge(self):
        gauge = ticon.station_by_id(BREST)
        assert gauge["id"] == "brest-822-fra-uhslc_fd"
        assert gauge["name"] == "Brest"
        assert gauge["country"] == "France"
        assert gauge["tz"] == "Europe/Paris"
        assert (gauge["lat"], gauge["lng"]) == pytest.approx((48.383, -4.5), abs=0.01)

    def test_the_prefix_is_what_makes_it_a_ticon_id(self):
        assert ticon.is_ticon_station_id(BREST)
        assert not ticon.is_ticon_station_id("brest-822-fra-uhslc_fd")
        assert not ticon.is_ticon_station_id("8418150")
        assert not ticon.is_ticon_station_id("")
        assert ticon.station_by_id("brest-822-fra-uhslc_fd") is None
        assert ticon.station_by_id("TICON:brest-822-fra-uhslc_fd") is None

    def test_an_id_no_gauge_has_is_none(self):
        assert ticon.station_by_id("ticon:atlantis-000-xxx-none") is None
        assert ticon.station_by_id("ticon:") is None
        assert ticon.station_by_id("") is None

    def test_metadata_is_in_the_shape_the_noaa_pipeline_reads(self):
        assert ticon.fetch_station_metadata_ticon(BREST) == {
            "id": BREST, "name": "Brest", "state": "Brittany",
            "lat": 48.383, "lng": -4.5,
            "timezone_abbr": "", "timeZoneCode": "Europe/Paris", "observedst": False,
            "datum": "LAT", "source": "ticon",
        }

    def test_metadata_leaves_out_a_region_that_repeats_the_name(self):
        meta = ticon.fetch_station_metadata_ticon(TOKYO)
        assert (meta["name"], meta["state"]) == ("Tokyo", "")
        assert meta["timeZoneCode"] == "Asia/Tokyo"

    def test_metadata_for_an_unknown_gauge_is_none(self):
        assert ticon.fetch_station_metadata_ticon("ticon:atlantis-000-xxx-none") is None
        assert ticon.fetch_station_metadata_ticon("8418150") is None


class TestNames:
    """The database's names, where it has them wrong (the build script's
    NAMES): seven Channel Coastal Observatory gauges carried one
    another's, and three had lost their letters outside ASCII."""

    def test_a_channel_gauge_is_named_for_where_it_stands(self, gauges):
        channel = [gauge for gauge in gauges if gauge["id"].endswith("-gbr-cco")]
        assert len(channel) == 12
        for gauge in channel:
            slug = gauge["id"].split("-")[0].replace("_", " ")
            assert gauge["name"].lower() == slug, gauge["id"]

    def test_brighton_is_found_at_brighton(self):
        station_id, name = ticon.find_nearest_station_ticon(50.82, -0.14)
        assert station_id == "ticon:brighton-btn-gbr-cco"
        assert name.startswith("Brighton")

    def test_names_keep_their_letters(self, gauges):
        names = {gauge["id"]: gauge["name"] for gauge in gauges}
        assert names["nylesund-823-nor-uhslc_fd"] == "Ny-Ålesund"
        assert names["ueckermnde-9690088-deu-wsv"] == "Ueckermünde"
        assert names["wittowerfhre-9670055-deu-wsv"] == "Wittower Fähre"


class TestDisplayName:
    """The gauge and its region, unless the region only repeats the gauge."""

    def test_a_gauge_and_its_region(self):
        assert ticon.display_name({"name": "Brest", "region": "Brittany"}) == "Brest, Brittany"

    def test_a_region_of_the_same_name_is_not_said_twice(self):
        assert ticon.display_name({"name": "Tokyo", "region": "Tokyo"}) == "Tokyo"
        assert ticon.display_name({"name": "ST HELENA", "region": "St Helena"}) == "ST HELENA"

    def test_a_region_inside_the_gauges_name_is_not_said_twice(self):
        assert ticon.display_name({"name": "Aomoriko", "region": "Aomori"}) == "Aomoriko"

    def test_no_region_is_the_name_alone(self):
        assert ticon.display_name({"name": "Scott Base", "region": ""}) == "Scott Base"


class TestNearest:
    """The closest gauge, if one is within thirty nautical miles."""

    def test_a_place_at_a_gauge_gets_that_gauge(self):
        assert ticon.find_nearest_station_ticon(48.383, -4.5) == (BREST, "Brest, Brittany")

    def test_a_place_a_few_miles_off_gets_it_too(self):
        # Tokyo Station, two nautical miles from the gauge
        assert ticon.find_nearest_station_ticon(35.681, 139.767) == (TOKYO, "Tokyo")

    def test_the_united_states_is_left_to_noaa(self):
        assert ticon.find_nearest_station_ticon(43.66, -70.25) == (None, None)  # Portland, Maine
        assert ticon.find_nearest_station_ticon(21.3, -157.87) == (None, None)  # Honolulu

    def test_the_open_ocean_and_the_poles_have_no_gauge(self):
        assert ticon.find_nearest_station_ticon(0.0, 0.0) == (None, None)
        assert ticon.find_nearest_station_ticon(90.0, 0.0) == (None, None)
        assert ticon.find_nearest_station_ticon(-90.0, 0.0) == (None, None)

    def test_a_gauge_stands_in_up_to_thirty_miles_and_no_farther(self, bundle_file):
        # a degree of latitude is sixty nautical miles
        _write(bundle_file, [_row("a", "Alpha", "Region", 10.0, 20.0)])
        assert ticon.MAX_NM == 30
        assert ticon.find_nearest_station_ticon(10.48, 20.0) == ("ticon:a", "Alpha, Region")
        assert ticon.find_nearest_station_ticon(9.52, 20.0) == ("ticon:a", "Alpha, Region")
        assert ticon.find_nearest_station_ticon(10.52, 20.0) == (None, None)
        assert ticon.find_nearest_station_ticon(9.48, 20.0) == (None, None)

    def test_the_nearer_of_two_is_chosen(self, bundle_file):
        _write(bundle_file, [_row("a", "Alpha", "", 10.0, 20.0), _row("b", "Beta", "", 10.2, 20.0)])
        assert ticon.find_nearest_station_ticon(10.05, 20.0) == ("ticon:a", "Alpha")
        assert ticon.find_nearest_station_ticon(10.15, 20.0) == ("ticon:b", "Beta")

    def test_a_gauge_across_the_antimeridian_is_near(self, bundle_file):
        # 0.2° of longitude at 17° S is eleven and a half nautical miles
        _write(bundle_file, [_row("a", "Alpha", "", -17.0, 179.9)])
        assert ticon.find_nearest_station_ticon(-17.0, -179.9) == ("ticon:a", "Alpha")
        assert ticon.find_nearest_station_ticon(-17.0, 179.0) == (None, None)

    def test_near_the_pole_longitude_hardly_counts(self, bundle_file):
        # opposite sides of the pole, 0.3° of latitude apart over the top
        _write(bundle_file, [_row("a", "Alpha", "", 89.8, 0.0)])
        assert ticon.find_nearest_station_ticon(89.9, 180.0) == ("ticon:a", "Alpha")
        assert ticon.find_nearest_station_ticon(90.0, 77.0) == ("ticon:a", "Alpha")
        assert ticon.find_nearest_station_ticon(89.0, 180.0) == (None, None)


class TestAgainstJma:
    """Tokyo on 1 October 2026 against JMA's own tide table.

    TICON-4's constants come from a different record than JMA's, and the
    two datums differ by about three centimetres, so this is the
    agreement the module's docstring claims rather than an exact one: on
    this day the hours are 3 cm low on average and 9 cm low at worst,
    and the turns are within six minutes.
    """

    DAY = date(2026, 10, 1)

    def test_each_hour_is_within_a_decimetre_and_the_day_within_five_centimetres(self):
        points = dict(ticon.fetch_tides_range_ticon(TOKYO, self.DAY, self.DAY, JST))
        off = [points[datetime(2026, 10, 1, hour, tzinfo=JST)] / M_TO_FT * 100 - cm
               for hour, cm in enumerate(JMA_TOKYO_HOURS_CM)]
        assert max(abs(d) for d in off) < 10
        assert math.sqrt(sum(d * d for d in off) / len(off)) < 5

    def test_the_turns_are_the_same_four_within_ten_minutes_and_a_decimetre(self):
        turns = ticon.fetch_hilo_range_ticon(TOKYO, self.DAY, self.DAY, JST)
        assert [kind for _t, _h, kind in turns] == [kind for _at, _cm, kind in JMA_TOKYO_TURNS]
        for (t, height, _kind), (at, cm, _) in zip(turns, JMA_TOKYO_TURNS):
            hour, minute = map(int, at.split(":"))
            jma = datetime(2026, 10, 1, hour, minute, tzinfo=JST)
            assert abs((t - jma).total_seconds()) < 600, at
            assert height / M_TO_FT * 100 == pytest.approx(cm, abs=10), at


class TestDays:
    """A gauge's curve and turns for the dates a view asks for: in feet,
    on the gauge's own clock."""

    @pytest.mark.parametrize("gauge, zone, first", [
        # Tokyo's water stood through midnight on 11 March: a high and
        # a low two millimetres apart, an hour either side of it
        ("ticon:tokyo-ma15-jpn-jodc_jma", "Asia/Tokyo", date(2026, 3, 1)),
        # the Chatham Islands keep a clock 45 minutes off the hour, so a
        # day there begins and ends off the scan's grid
        ("ticon:chatham-079-nzl-uhslc_fd", "Pacific/Chatham", date(2026, 1, 1)),
        ("ticon:port_pirie-61800-aus-bom", "Australia/Adelaide", date(2026, 11, 1)),
    ])
    def test_a_months_turns_are_its_days_turns(self, gauge, zone, first):
        tz = ZoneInfo(zone)
        last = (first.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
        month = ticon.fetch_hilo_range_ticon(gauge, first, last, tz)
        by_day = []
        day = first
        while day <= last:
            by_day += ticon.fetch_hilo_range_ticon(gauge, day, day, tz)
            day += timedelta(days=1)
        # a turn on the stroke of midnight belongs to both its days
        by_day = sorted(set(by_day))
        assert [(t, kind) for t, _h, kind in by_day] == [(t, kind) for t, _h, kind in month]

    def test_a_day_is_every_six_minutes_from_midnight_to_midnight(self):
        day = date(2026, 7, 1)
        points = ticon.fetch_tides_range_ticon(BREST, day, day, PARIS)
        assert len(points) == 241
        assert points[0][0] == datetime(2026, 7, 1, tzinfo=PARIS)
        assert points[-1][0] == datetime(2026, 7, 2, tzinfo=PARIS)
        assert all(t.tzinfo is PARIS for t, _h in points)
        assert points[1][0] - points[0][0] == timedelta(minutes=6)

    def test_heights_are_the_tide_machines_in_feet_above_chart_datum(self):
        day = date(2026, 7, 1)
        gauge = ticon.station_by_id(BREST)
        tide = harmonic.Tide(gauge["constants"], z0=gauge["z0"])
        for t, feet in ticon.fetch_tides_range_ticon(BREST, day, day, PARIS)[::20]:
            assert feet == pytest.approx(tide.height(t) * M_TO_FT, abs=1e-9)

    def test_the_day_the_clocks_go_forward_is_an_hour_short(self):
        day = date(2026, 3, 29)
        points = ticon.fetch_tides_range_ticon(BREST, day, day, PARIS)
        assert len(points) == 231
        assert points[0][0].strftime("%d %H:%M %Z") == "29 00:00 CET"
        assert points[-1][0].strftime("%d %H:%M %Z") == "30 00:00 CEST"
        utc = [t.astimezone(UTC) for t, _h in points]
        assert {b - a for a, b in zip(utc, utc[1:])} == {timedelta(minutes=6)}

    def test_the_day_they_go_back_is_an_hour_long(self):
        day = date(2026, 10, 25)
        points = ticon.fetch_tides_range_ticon(BREST, day, day, PARIS)
        assert len(points) == 251
        assert points[0][0].strftime("%d %H:%M %Z") == "25 00:00 CEST"
        assert points[-1][0].strftime("%d %H:%M %Z") == "26 00:00 CET"
        utc = [t.astimezone(UTC) for t, _h in points]
        assert {b - a for a, b in zip(utc, utc[1:])} == {timedelta(minutes=6)}

    def test_several_days_run_on_without_a_seam_across_the_new_year(self):
        points = ticon.fetch_tides_range_ticon(BREST, date(2026, 12, 31), date(2027, 1, 1),
                                               PARIS)
        assert len(points) == 481
        assert points[0][0] == datetime(2026, 12, 31, tzinfo=PARIS)
        assert points[-1][0] == datetime(2027, 1, 2, tzinfo=PARIS)
        assert {b[0] - a[0] for a, b in zip(points, points[1:])} == {timedelta(minutes=6)}

    def test_with_no_zone_the_times_are_naive_utc(self):
        day = date(2026, 7, 1)
        points = ticon.fetch_tides_range_ticon(BREST, day, day, None)
        assert len(points) == 241
        assert points[0][0] == datetime(2026, 7, 1)
        assert points[0][0].tzinfo is None
        in_utc = ticon.fetch_tides_range_ticon(BREST, day, day, UTC)
        assert [h for _t, h in points] == [h for _t, h in in_utc]

    def test_the_turns_of_a_day_take_turns_and_fall_inside_it(self):
        day = date(2026, 7, 1)
        turns = ticon.fetch_hilo_range_ticon(BREST, day, day, PARIS)
        # Brest's tide is twice daily: four turns most days, sometimes three
        assert [kind for _t, _h, kind in turns] == ["L", "H", "L", "H"]
        for t, _h, _kind in turns:
            assert datetime(2026, 7, 1, tzinfo=PARIS) <= t <= datetime(2026, 7, 2, tzinfo=PARIS)
            assert t.tzinfo is PARIS

    def test_the_turns_sit_on_the_curve(self):
        day = date(2026, 7, 1)
        curve = [h for _t, h in ticon.fetch_tides_range_ticon(BREST, day, day, PARIS)]
        turns = ticon.fetch_hilo_range_ticon(BREST, day, day, PARIS)
        highest = max(h for _t, h, kind in turns if kind == "H")
        lowest = min(h for _t, h, kind in turns if kind == "L")
        # no six-minute point is past a turn, and one is within a
        # hundredth of a foot of it
        assert highest - 0.01 < max(curve) <= highest
        assert lowest <= min(curve) < lowest + 0.01

    def test_the_axis_spans_the_turns_of_the_months_either_side(self):
        low, high = ticon.fetch_y_range_ticon(BREST, date(2026, 7, 14), PARIS)
        turns = ticon.fetch_hilo_range_ticon(BREST, date(2026, 6, 1), date(2026, 8, 31), PARIS)
        heights = [h for _t, h, _kind in turns]
        assert (low, high) == pytest.approx((min(heights), max(heights)))
        # Brest's springs run about seven metres over chart datum
        assert 0 < low < 3 and 20 < high < 26

    def test_a_year_far_off_costs_nothing_more(self):
        day = date(2040, 7, 1)
        points = ticon.fetch_tides_range_ticon(BREST, day, day, PARIS)
        turns = ticon.fetch_hilo_range_ticon(BREST, day, day, PARIS)
        assert len(points) == 241
        assert len(turns) in (3, 4)
        assert all(0 < h < 26 for _t, h in points)

    def test_an_unknown_gauge_has_no_curve_no_turns_and_no_axis(self):
        day = date(2026, 7, 1)
        for ident in ("ticon:atlantis-000-xxx-none", "8418150", ""):
            assert ticon.fetch_tides_range_ticon(ident, day, day, PARIS) == []
            assert ticon.fetch_hilo_range_ticon(ident, day, day, PARIS) == []
            assert ticon.fetch_y_range_ticon(ident, day, PARIS) is None


@pytest.mark.parametrize("ident", A_SPREAD)
class TestAYearOfAGauge:
    """A gauge's prediction through 2026, hour by hour: no jumps, and
    heights where its constants and its datum say they should be."""

    def test_every_hour_is_within_the_constants_reach_of_the_mean_level(
            self, year_of_hours, ident):
        gauge, _tide, heights = year_of_hours[ident]
        assert len(heights) == 8760
        farthest = max(abs(h - gauge["z0"]) for h in heights)
        assert farthest <= 1.2 * _reach(gauge)
        # and the tide does use most of it
        assert farthest > 0.5 * _reach(gauge)

    def test_the_year_averages_to_the_mean_level(self, year_of_hours, ident):
        gauge, _tide, heights = year_of_hours[ident]
        assert sum(heights) / len(heights) == pytest.approx(gauge["z0"], abs=0.005)

    def test_no_hour_moves_the_water_faster_than_the_constants_can(self, year_of_hours, ident):
        gauge, _tide, heights = year_of_hours[ident]
        steps = [abs(b - a) for a, b in zip(heights, heights[1:])]
        assert max(steps) <= 1.2 * _fastest(gauge)

    def test_no_midnight_has_a_step_in_it(self, year_of_hours, ident):
        gauge, tide, _heights = year_of_hours[ident]
        in_a_second = 1.2 * _fastest(gauge) / 3600
        for day in range(1, 365):
            midnight = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=day)
            before = tide.height(midnight - timedelta(seconds=1))
            assert abs(tide.height(midnight) - before) <= in_a_second, midnight

    def test_the_lowest_water_of_the_year_is_near_the_datum(self, year_of_hours, ident):
        gauge, _tide, heights = year_of_hours[ident]
        span = max(heights) - min(heights)
        if gauge["datum"] == "LAT":
            # lowest astronomical tide: the year's lowest is at it or a
            # little above, the lowest of nineteen years being lower
            assert -0.02 * span <= min(heights) <= 0.1 * span
        elif gauge["datum"] == "MSL":
            assert min(heights) < 0 < max(heights)
        else:
            # Japan's nearly lowest low water: the lowest tides dip under it
            assert gauge["datum"] == "NLLW"
            assert -0.15 * span <= min(heights) <= 0.1 * span
