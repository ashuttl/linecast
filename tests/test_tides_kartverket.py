"""Tests for the Kartverket tide data source.

Kartverket is never reached: `kartverket()` puts an answer where the
module's fetch would be and keeps what was asked. The answers are
written here, small, in the elements and attributes the module reads;
none is a saved response, and the wording of the service's messages is
made up, but for "too far away from the coast", which the module
quotes. Every test has a cache of its own, and the module's clock
stands at noon on 10 October 2026 in Norway.
"""

import os
import time
import unicodedata
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from math import pi, sin
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

import pytest

from linecast import _log
from linecast.tides import kartverket as kv
from linecast.tides.common import M_TO_FT

UTC = timezone.utc
OSLO = ZoneInfo("Europe/Oslo")
NOW = datetime(2026, 10, 10, 12, 0, tzinfo=OSLO)
CM = M_TO_FT / 100   # feet in a centimetre, the unit Kartverket answers in
MM = CM / 10         # how closely a height is held: a millimetre

BERGEN = "kv:60.3980,5.3205"        # the gauge's own point, as --search gives it
NEAR_BERGEN = "kv:60.4100,5.3205"   # three quarters of a nautical mile north
OCT_1 = date(2026, 10, 1)
TODAY = date(2026, 10, 10)


# ---------------------------------------------------------------------------
# The cache, the clock and the service
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def cache(tmp_path):
    with patch.dict(os.environ, {"LINECAST_CACHE_DIR": str(tmp_path)}):
        yield tmp_path


class _Clock(datetime):
    """The module's datetime, with now() standing at NOW."""

    @classmethod
    def now(cls, tz=None):
        return NOW.astimezone(tz)


@pytest.fixture(autouse=True)
def clock():
    with patch.object(kv, "datetime", _Clock):
        yield


def _aged(cache, **age):
    """Every file kept so far was written this long ago."""
    then = time.time() - timedelta(**age).total_seconds()
    kept = list(cache.rglob("*.json"))
    assert kept, "nothing was kept"
    for path in kept:
        os.utime(path, (then, then))


class Service:
    """Kartverket, for as long as `kartverket()` is open: each request
    is answered with *answer*, or with what *answer* makes of the
    request's query, and an answer that is an exception is raised."""

    def __init__(self, answer):
        self.answer = answer
        self.asked = []   # each request's query, in the order asked

    def __call__(self, url, **kwargs):
        assert url.startswith(kv.KV_BASE + "?")
        query = {key: values[0] for key, values in parse_qs(urlsplit(url).query).items()}
        self.asked.append(query)
        answer = self.answer(query) if callable(self.answer) else self.answer
        if isinstance(answer, Exception):
            raise answer
        return answer

    def spans(self, datatype):
        """(fromtime, totime) of each request for *datatype*."""
        return [(q["fromtime"], q["totime"]) for q in self.asked if q["datatype"] == datatype]


@contextmanager
def kartverket(answer):
    service = Service(answer)
    with patch.object(kv, "fetch_bytes", side_effect=service):
        yield service


DOWN = OSError("network is unreachable")


# ---------------------------------------------------------------------------
# Answers
# ---------------------------------------------------------------------------
def _utc(*parts):
    return datetime(*parts, tzinfo=UTC)


def _asked(moment):
    """A fromtime or totime as the instant it names."""
    return datetime.strptime(moment, "%Y-%m-%dT%H:%M").replace(tzinfo=UTC)


def _attributes(**attributes):
    """XML attributes, leaving out any that is None."""
    return " ".join(f'{name}="{value}"' for name, value in attributes.items()
                    if value is not None)


def _tide(body, encoding="UTF-8"):
    text = f'<?xml version="1.0" encoding="{encoding}"?>\n<tide>\n{body}\n</tide>\n'
    return text.encode(encoding)


def _location(levels, unit="cm", reflevel="CD", kind="prediction", name="BERGEN",
              encoding="UTF-8"):
    """What tide_request=locationdata answers: *levels* as (time, value, flag)."""
    rows = "\n".join(f"<waterlevel {_attributes(value=value, time=when, flag=flag)}/>"
                     for when, value, flag in levels)
    return _tide(
        "<locationdata>\n"
        f'<location name="{name}" code="BGO" latitude="60.398046" longitude="5.320487"'
        f' delay="0" factor="1.00" obsname="{name}" obscode="BGO" descr="Tides from {name}"/>\n'
        + (f"<reflevelcode>{reflevel}</reflevelcode>\n" if reflevel is not None else "")
        + f"<data {_attributes(type=kind, unit=unit)}>\n{rows}\n</data>\n"
        "</locationdata>", encoding)


# Where Kartverket has no water: inland, or outside Norway.
NO_WATER = _tide('<locationdata>\n<nodata info="The position is too far away from the coast '
                 'or outside the area with predictions."/>\n</locationdata>')

# Bergen's turns on 1 October 2026 as a request in UTC is answered.
# Kartverket's printed table has them at 02:22, 08:14, 14:50 and 20:36
# by Norway's clock, at 162, 43, 155 and 50 cm (docs/sources.md).
BERGEN_TURNS = [
    ("2026-10-01T00:22:00+00:00", "162.0", "high"),
    ("2026-10-01T06:14:00+00:00", "43.0", "low"),
    ("2026-10-01T12:50:00+00:00", "155.0", "high"),
    ("2026-10-01T18:36:00+00:00", "50.0", "low"),
]


def _turns(minutes=0, factor=1.0, lift=0.0):
    """BERGEN_TURNS, each so many minutes later, scaled, and lifted so many cm."""
    return [((datetime.fromisoformat(when) + timedelta(minutes=minutes)).isoformat(),
             f"{float(cm) * factor + lift:.1f}", flag)
            for when, cm, flag in BERGEN_TURNS]


def _a_years_turns(query):
    """A `tab` answer with the four turns on 1 October of the year asked for."""
    year = query["totime"][:4]
    return _location([(when.replace("2026", year), cm, flag)
                      for when, cm, flag in BERGEN_TURNS])


def _cm(moment):
    """A tide of 12 hours 25 minutes about a metre, printed to the millimetre."""
    return round(100 + 60 * sin(2 * pi * moment.timestamp() / 44700), 1)


def _ten_minutes(query):
    """A `pre` answer: a height every ten minutes from fromtime to totime,
    both ends included, as the service gives them."""
    moment, end = _asked(query["fromtime"]), _asked(query["totime"])
    levels = []
    while moment <= end:
        levels.append((moment.isoformat(), _cm(moment), "pre"))
        moment += timedelta(minutes=10)
    return _location(levels)


def _station(readings, reftime, unit="cm", reflevel="CD", kind="observation"):
    """What tide_request=stationdata answers with dst=2: *readings* as
    (seconds after reftime, value)."""
    rows = "\n".join(f"<waterlevel {_attributes(value=value, time=seconds, flag='obs')}/>"
                     for seconds, value in readings)
    return _tide(
        "<stationdata>\n"
        '<location name="Bergen" code="BGO" latitude="60.398046" longitude="5.320487"/>\n'
        f"<data {_attributes(type=kind, unit=unit, reflevelcode=reflevel, reftime=reftime)}>\n"
        f"{rows}\n</data>\n"
        "</stationdata>")


def _flat(moment):
    return 100.0


def _readings(start, end, cm=_flat, extra=()):
    """An `obs` answer for every ten minutes from *start* up to *end*:
    *cm(moment)* centimetres each, and none where that is None."""
    readings = []
    moment = start
    while moment < end:
        value = cm(moment)
        if value is not None:
            readings.append((int((moment - start).total_seconds()), value))
        moment += timedelta(minutes=10)
    return _station([*readings, *extra], start.isoformat())


def _the_last_days(query):
    """An `obs` answer: the two days before totime, and the day after it
    as well, which is more than was asked for."""
    end = _asked(query["totime"])
    return _readings(end - timedelta(days=2), end + timedelta(days=1))


def _gauge(readings):
    """Kartverket as a point on a gauge sees it: a year's turns for the
    point, and *readings* (or what it makes of the query) for the gauge."""
    def answer(query):
        if query["tide_request"] == "locationdata":
            return _a_years_turns(query)
        return readings(query) if callable(readings) else readings
    return answer


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
class TestStationId:
    """The station is the place itself, `kv:<lat>,<lng>` to four decimal
    places: eleven metres of latitude."""

    def test_a_point_comes_back_to_four_decimal_places(self):
        station_id = kv.make_station_id(60.398046, 5.320487)
        assert station_id == "kv:60.3980,5.3205"
        assert kv.parse_station_id(station_id) == pytest.approx((60.398046, 5.320487),
                                                                abs=0.00005)

    def test_a_point_west_of_greenwich_keeps_its_sign(self):
        # Olonkinbyen, on Jan Mayen
        station_id = kv.make_station_id(70.9221, -8.7187)
        assert station_id == "kv:70.9221,-8.7187"
        assert kv.parse_station_id(station_id) == (70.9221, -8.7187)

    @pytest.mark.parametrize("other", [
        "8418150", "om:60.3980,5.3205", "jma:TK", "ticon:bergen", "BGO", "60.3980,5.3205", ""])
    def test_only_kv_ids_are_recognised(self, other):
        assert kv.is_kartverket_station_id(BERGEN)
        assert not kv.is_kartverket_station_id(other)

    @pytest.mark.parametrize("station_id", [
        "kv:", "kv:bergen", "kv:60.3980", "kv:60.3980,5.3205,0", "kv:60.3980;5.3205", "8418150"])
    def test_an_id_that_names_no_point_decodes_to_none(self, station_id):
        assert kv.parse_station_id(station_id) is None


class TestGauges:
    """The thirty-three permanent gauges, each a station at the point
    where it stands."""

    def test_there_are_thirty_three_each_with_a_code_of_its_own(self):
        assert len(kv.GAUGES) == 33
        assert len(kv.GAUGE_BY_CODE) == 33
        assert kv.GAUGE_BY_CODE["BGO"]["name"] == "Bergen"

    def test_every_gauge_is_found_at_the_id_made_from_where_it_stands(self):
        for gauge in kv.GAUGES:
            assert kv.gauge_at(kv.make_station_id(gauge["lat"], gauge["lng"])) is gauge

    def test_an_id_typed_with_all_the_gauges_digits_is_the_same_gauge(self):
        assert kv.gauge_at("kv:60.398046,5.320487") is kv.GAUGE_BY_CODE["BGO"]

    def test_a_point_beside_a_gauge_is_not_on_it(self):
        assert kv.gauge_at(NEAR_BERGEN) is None
        assert kv.gauge_at("kv:60.3981,5.3205") is None

    def test_an_id_that_names_no_point_stands_on_no_gauge(self):
        assert kv.gauge_at("kv:bergen") is None

    def test_norwegian_letters_are_kept_in_the_names(self):
        names = {code: gauge["name"] for code, gauge in kv.GAUGE_BY_CODE.items()}
        assert names["BOO"] == "Bodø"
        assert names["TOS"] == "Tromsø"
        assert names["MAY"] == "Måløy"
        assert names["TAZ"] == "Træna"
        assert names["AES"] == "Ålesund"
        assert names["NYA"] == "Ny-Ålesund"
        assert kv.gauge_at("kv:69.6461,18.9548")["name"] == "Tromsø"

    def test_the_letters_are_single_characters_not_a_letter_and_a_mark(self):
        # "å" as one code point is what a search spelling it "a" looks for
        for gauge in kv.GAUGES:
            assert gauge["name"] == unicodedata.normalize("NFC", gauge["name"])

    def test_the_gauges_stand_in_norways_waters(self):
        for gauge in kv.GAUGES:
            assert 57.9 < gauge["lat"] < 81 and 4 < gauge["lng"] < 32, gauge["name"]


class TestMetadata:
    """NOAA-shaped metadata for a point, made without asking Kartverket."""

    def test_it_needs_no_request_and_leaves_the_name_to_the_caller(self):
        with kartverket(DOWN) as service:
            meta = kv.fetch_station_metadata_kartverket(BERGEN)
        assert service.asked == []
        assert meta["id"] == BERGEN
        assert meta["name"] == ""
        assert (meta["lat"], meta["lng"]) == (60.398, 5.3205)
        assert meta["source"] == "kartverket"

    def test_the_mainland_keeps_oslos_clock(self):
        meta = kv.fetch_station_metadata_kartverket(BERGEN)
        assert meta["timeZoneCode"] == "Europe/Oslo"
        # an hour ahead of UTC, two in summer
        assert meta["timezonecorr"] in (1, 2)
        assert meta["observedst"] is True

    @pytest.mark.parametrize("station_id", [
        "kv:78.2232,15.6267",    # Longyearbyen
        "kv:74.5036,19.0011",    # Bjørnøya, south of the rest of Svalbard
        "kv:70.9221,-8.7187",    # Jan Mayen, west of Greenwich
    ])
    def test_svalbard_and_jan_mayen_keep_longyearbyens(self, station_id):
        meta = kv.fetch_station_metadata_kartverket(station_id)
        assert meta["timeZoneCode"] == "Arctic/Longyearbyen"

    def test_ny_alesund_is_the_only_gauge_on_longyearbyens_clock(self):
        zones = {gauge["code"]: kv.fetch_station_metadata_kartverket(
            kv.make_station_id(gauge["lat"], gauge["lng"]))["timeZoneCode"]
            for gauge in kv.GAUGES}
        assert zones.pop("NYA") == "Arctic/Longyearbyen"
        assert set(zones.values()) == {"Europe/Oslo"}

    def test_an_id_that_names_no_point_has_no_metadata(self):
        assert kv.fetch_station_metadata_kartverket("kv:bergen") is None


class TestHighAndLowWaters:
    """The `tab` answer: a year's high and low waters, labelled, asked
    for in UTC and put on the station's clock, in feet."""

    def test_they_come_at_their_instants_in_feet_as_h_and_l(self):
        with kartverket(_location(BERGEN_TURNS)):
            turns = kv.fetch_hilo_range_kartverket(BERGEN, OCT_1, OCT_1, OSLO)
        assert [(when.astimezone(UTC), kind) for when, _height, kind in turns] == [
            (_utc(2026, 10, 1, 0, 22), "H"), (_utc(2026, 10, 1, 6, 14), "L"),
            (_utc(2026, 10, 1, 12, 50), "H"), (_utc(2026, 10, 1, 18, 36), "L")]
        # centimetres above chart datum, as feet: 162 cm is 5.31 ft
        assert [height for _when, height, _kind in turns] == pytest.approx(
            [162 * CM, 43 * CM, 155 * CM, 50 * CM], abs=MM)
        assert turns[0][1] == pytest.approx(5.315, abs=0.001)

    def test_a_time_with_no_offset_is_read_as_utc(self):
        """The request asks for UTC; the machine's own clock has no say."""
        bare = [(when[:19], value, flag) for when, value, flag in BERGEN_TURNS]
        with kartverket(_location(bare)):
            turns = kv.fetch_hilo_range_kartverket(BERGEN, OCT_1, OCT_1, OSLO)
        assert [when.astimezone(UTC) for when, _height, _kind in turns] == [
            _utc(2026, 10, 1, 0, 22), _utc(2026, 10, 1, 6, 14),
            _utc(2026, 10, 1, 12, 50), _utc(2026, 10, 1, 18, 36)]

    def test_they_read_on_norways_clock_as_the_printed_table_has_them(self):
        with kartverket(_location(BERGEN_TURNS)):
            turns = kv.fetch_hilo_range_kartverket(BERGEN, OCT_1, OCT_1, OSLO)
        assert [when.strftime("%H:%M %Z") for when, _height, _kind in turns] == [
            "02:22 CEST", "08:14 CEST", "14:50 CEST", "20:36 CEST"]

    def test_with_no_zone_given_the_points_own_clock_is_used(self):
        with kartverket(_location(BERGEN_TURNS)):
            turns = kv.fetch_hilo_range_kartverket(BERGEN, OCT_1, OCT_1)
        assert [when.strftime("%d %H:%M") for when, _height, _kind in turns] == [
            "01 02:22", "01 08:14", "01 14:50", "01 20:36"]
        assert {when.utcoffset() for when, _height, _kind in turns} == {timedelta(hours=2)}

    def test_a_zone_the_caller_gives_sets_the_clock_and_the_days(self):
        evening = ("2026-10-01T22:30:00+00:00", "150.0", "high")   # 00:30 on the 2nd in Norway
        with kartverket(_location([*BERGEN_TURNS, evening])):
            norway = kv.fetch_hilo_range_kartverket(BERGEN, OCT_1, OCT_1, OSLO)
            greenwich = kv.fetch_hilo_range_kartverket(BERGEN, OCT_1, OCT_1, UTC)
        assert [when.strftime("%d %H:%M") for when, _height, _kind in norway] == [
            "01 02:22", "01 08:14", "01 14:50", "01 20:36"]
        assert [when.strftime("%d %H:%M") for when, _height, _kind in greenwich] == [
            "01 00:22", "01 06:14", "01 12:50", "01 18:36", "01 22:30"]
        assert {when.utcoffset() for when, _height, _kind in greenwich} == {timedelta(0)}

    def test_a_year_is_one_request_at_the_point_in_utc_on_chart_datum(self):
        with kartverket(_location(BERGEN_TURNS)) as service:
            kv.fetch_hilo_range_kartverket(BERGEN, OCT_1, OCT_1, OSLO)
            kv.fetch_hilo_range_kartverket(BERGEN, date(2026, 1, 1), date(2026, 12, 31), OSLO)
        [query] = service.asked
        assert query["tide_request"] == "locationdata"
        assert (query["lat"], query["lon"]) == ("60.3980", "5.3205")
        assert query["datatype"] == "tab"
        assert query["refcode"].upper() == "CD"
        # Norway's year, which opens at 23:00 UTC on New Year's Eve
        assert (query["fromtime"], query["totime"]) == ("2025-12-31T23:00", "2026-12-31T23:00")
        assert (query["tzone"], query["dst"]) == ("0", "0")

    def test_the_range_is_the_local_days_asked_for_in_time_order(self):
        answer = _location([
            ("2026-10-02T22:00:00+00:00", "150.0", "high"),   # midnight closing the 2nd
            ("2026-10-02T21:59:00+00:00", "40.0", "low"),     # 23:59 on the 2nd
            ("2026-10-01T21:59:00+00:00", "45.0", "low"),     # 23:59 on the 1st
            ("2026-10-01T22:00:00+00:00", "160.0", "high"),   # midnight opening the 2nd
        ])
        with kartverket(answer):
            turns = kv.fetch_hilo_range_kartverket(BERGEN, date(2026, 10, 2),
                                                   date(2026, 10, 2), OSLO)
        assert [(when.astimezone(UTC), kind) for when, _height, kind in turns] == [
            (_utc(2026, 10, 1, 22, 0), "H"), (_utc(2026, 10, 2, 21, 59), "L")]

    def test_turns_either_side_of_the_autumn_clock_change_keep_their_instants(self):
        # Norway's clocks go back at 01:00 UTC on 25 October 2026
        answer = _location([
            ("2026-10-24T21:30:00+00:00", "50.0", "low"),     # 23:30 on the 24th
            ("2026-10-25T00:30:00+00:00", "150.0", "high"),   # 02:30, summer time
            ("2026-10-25T01:30:00+00:00", "140.0", "high"),   # 02:30 again, an hour on
            ("2026-10-25T22:30:00+00:00", "45.0", "low"),     # 23:30 on the 25th
            ("2026-10-25T23:30:00+00:00", "155.0", "high"),   # 00:30 on the 26th
        ])
        day = date(2026, 10, 25)
        with kartverket(answer):
            turns = kv.fetch_hilo_range_kartverket(BERGEN, day, day, OSLO)
        assert [when.astimezone(UTC) for when, _height, _kind in turns] == [
            _utc(2026, 10, 25, 0, 30), _utc(2026, 10, 25, 1, 30), _utc(2026, 10, 25, 22, 30)]
        assert [when.strftime("%H:%M %Z") for when, _height, _kind in turns] == [
            "02:30 CEST", "02:30 CET", "23:30 CET"]

    def test_turns_either_side_of_the_spring_clock_change_keep_their_instants(self):
        # and forward at 01:00 UTC on 29 March 2026
        answer = _location([
            ("2026-03-28T22:30:00+00:00", "50.0", "low"),     # 23:30 on the 28th
            ("2026-03-29T00:30:00+00:00", "150.0", "high"),   # 01:30, winter time
            ("2026-03-29T01:30:00+00:00", "140.0", "high"),   # 03:30, summer time
            ("2026-03-29T21:30:00+00:00", "45.0", "low"),     # 23:30 on the 29th
            ("2026-03-29T22:30:00+00:00", "155.0", "high"),   # 00:30 on the 30th
        ])
        day = date(2026, 3, 29)
        with kartverket(answer):
            turns = kv.fetch_hilo_range_kartverket(BERGEN, day, day, OSLO)
        assert [when.astimezone(UTC) for when, _height, _kind in turns] == [
            _utc(2026, 3, 29, 0, 30), _utc(2026, 3, 29, 1, 30), _utc(2026, 3, 29, 21, 30)]
        assert [when.strftime("%H:%M %Z") for when, _height, _kind in turns] == [
            "01:30 CET", "03:30 CEST", "23:30 CEST"]

    def test_a_range_across_new_year_reads_both_years_and_holds_midnight_once(self):
        midnight = ("2026-12-31T23:00:00+00:00", "150.0", "high")
        years = {
            "2026-12-31T23:00": _location([("2026-12-31T16:40:00+00:00", "60.0", "low"),
                                           midnight]),
            "2027-12-31T23:00": _location([midnight,
                                           ("2027-01-01T05:10:00+00:00", "55.0", "low")]),
        }
        with kartverket(lambda query: years[query["totime"]]) as service:
            turns = kv.fetch_hilo_range_kartverket(BERGEN, date(2026, 12, 31),
                                                   date(2027, 1, 1), OSLO)
        assert service.spans("tab") == [("2025-12-31T23:00", "2026-12-31T23:00"),
                                        ("2026-12-31T23:00", "2027-12-31T23:00")]
        assert [(when.strftime("%Y-%m-%d %H:%M"), kind) for when, _height, kind in turns] == [
            ("2026-12-31 17:40", "L"), ("2027-01-01 00:00", "H"), ("2027-01-01 06:10", "L")]

    def test_a_year_that_fails_leaves_the_other_years_turns(self):
        def answer(query):
            return DOWN if query["totime"].startswith("2027") else _a_years_turns(query)

        with kartverket(answer):
            turns = kv.fetch_hilo_range_kartverket(BERGEN, date(2026, 1, 1),
                                                   date(2027, 12, 31), OSLO)
        assert [when.year for when, _height, _kind in turns] == [2026] * 4

    def test_heights_answered_in_metres_are_the_same_water(self):
        metres = [(when, f"{float(cm) / 100:.3f}", flag) for when, cm, flag in BERGEN_TURNS]
        with kartverket(_location(metres, unit="m")):
            turns = kv.fetch_hilo_range_kartverket(BERGEN, OCT_1, OCT_1, OSLO)
        assert [height for _when, height, _kind in turns] == pytest.approx(
            [162 * CM, 43 * CM, 155 * CM, 50 * CM], abs=MM)

    def test_a_waterlevel_missing_its_time_or_its_value_is_left_out_alone(self):
        answer = _location([
            BERGEN_TURNS[0],
            (None, "43.0", "low"),
            ("2026-10-01T12:50:00+00:00", None, "high"),
            ("in the evening", "50.0", "low"),
            ("2026-10-01T18:36:00+00:00", "fifty", "low"),
            BERGEN_TURNS[3],
        ])
        with kartverket(answer):
            turns = kv.fetch_hilo_range_kartverket(BERGEN, OCT_1, OCT_1, OSLO)
        assert [(when.strftime("%H:%M"), kind) for when, _height, kind in turns] == [
            ("02:22", "H"), ("20:36", "L")]

    def test_a_waterlevel_flagged_neither_high_nor_low_is_no_turn(self):
        answer = _location([*BERGEN_TURNS[:2],
                            ("2026-10-01T09:00:00+00:00", "70.0", "pre"),
                            ("2026-10-01T10:00:00+00:00", "99.0", None)])
        with kartverket(answer):
            turns = kv.fetch_hilo_range_kartverket(BERGEN, OCT_1, OCT_1, OSLO)
        assert [kind for _when, _height, kind in turns] == ["H", "L"]

    def test_only_the_predictions_are_read(self):
        # a forecast adds the weather to the tide: it is not the tide table
        forecast = _location([("2026-10-01T03:00:00+00:00", "999.0", "high")], kind="forecast")
        both = forecast.replace(
            b"</locationdata>",
            b'<data type="prediction" unit="cm">\n'
            b'<waterlevel value="162.0" time="2026-10-01T00:22:00+00:00" flag="high"/>\n'
            b"</data>\n</locationdata>")
        with kartverket(both):
            turns = kv.fetch_hilo_range_kartverket(BERGEN, OCT_1, OCT_1, OSLO)
        assert [height for _when, height, _kind in turns] == pytest.approx([162 * CM], abs=MM)

    @pytest.mark.parametrize("encoding", ["UTF-8", "ISO-8859-1"])
    def test_norwegian_letters_in_the_answer_do_not_trouble_it(self, encoding):
        answer = _location(BERGEN_TURNS, name="BODØ, MÅLØY OG TRÆNA", encoding=encoding)
        assert "Ø".encode(encoding) in answer
        with kartverket(answer):
            turns = kv.fetch_hilo_range_kartverket("kv:67.2923,14.3998", OCT_1, OCT_1, OSLO)
        assert len(turns) == 4

    def test_without_a_zone_database_norway_is_an_hour_east_of_utc(self):
        with patch("zoneinfo.ZoneInfo", side_effect=KeyError("Europe/Oslo")), \
             kartverket(_location(_turns(minutes=92 * 1440))) as service:   # 1 January 2027
            turns = kv.fetch_hilo_range_kartverket(BERGEN, date(2027, 1, 1), date(2027, 1, 1))
        assert service.spans("tab") == [("2026-12-31T23:00", "2027-12-31T23:00")]
        assert [when.astimezone(UTC) for when, _height, _kind in turns] == [
            _utc(2027, 1, 1, 0, 22), _utc(2027, 1, 1, 6, 14),
            _utc(2027, 1, 1, 12, 50), _utc(2027, 1, 1, 18, 36)]
        assert {when.utcoffset() for when, _height, _kind in turns} == {timedelta(hours=1)}


class TestTenMinuteHeights:
    """The `pre` answer: the predicted height every ten minutes, a local
    calendar month to a request."""

    def test_a_day_is_144_heights_ten_minutes_apart_in_feet(self):
        with kartverket(_ten_minutes):
            points = kv.fetch_tides_range_kartverket(BERGEN, OCT_1, OCT_1, OSLO)
        assert len(points) == 144
        assert points[0][0].astimezone(UTC) == _utc(2026, 9, 30, 22, 0)
        assert points[-1][0].astimezone(UTC) == _utc(2026, 10, 1, 21, 50)
        assert {b[0].timestamp() - a[0].timestamp() for a, b in zip(points, points[1:])} == {600}
        assert {when.tzinfo for when, _height in points} == {OSLO}
        assert [height for _when, height in points] == pytest.approx(
            [_cm(when) * CM for when, _height in points], abs=MM)

    def test_a_zone_the_caller_gives_sets_the_clock_and_the_day(self):
        day = date(2026, 10, 15)
        with kartverket(_ten_minutes):
            points = kv.fetch_tides_range_kartverket(BERGEN, day, day, UTC)
        assert len(points) == 144
        assert points[0][0] == _utc(2026, 10, 15, 0, 0)
        assert points[-1][0] == _utc(2026, 10, 15, 23, 50)
        assert {when.utcoffset() for when, _height in points} == {timedelta(0)}

    def test_a_month_is_one_request_at_ten_minutes_in_utc(self):
        with kartverket(_ten_minutes) as service:
            kv.fetch_tides_range_kartverket(BERGEN, OCT_1, OCT_1, OSLO)
            kv.fetch_tides_range_kartverket(BERGEN, date(2026, 10, 12), date(2026, 10, 31), OSLO)
        [query] = service.asked
        assert query["tide_request"] == "locationdata"
        assert (query["lat"], query["lon"]) == ("60.3980", "5.3205")
        assert (query["datatype"], query["interval"]) == ("pre", "10")
        assert query["refcode"].upper() == "CD"
        assert (query["tzone"], query["dst"]) == ("0", "0")

    def test_octobers_request_runs_from_summer_time_into_winter_time(self):
        with kartverket(_ten_minutes) as service:
            kv.fetch_tides_range_kartverket(BERGEN, OCT_1, OCT_1, OSLO)
        # midnight on 1 October is 22:00 UTC, midnight on 1 November 23:00
        assert service.spans("pre") == [("2026-09-30T22:00", "2026-10-31T23:00")]

    def test_marchs_request_runs_from_winter_time_into_summer_time(self):
        with kartverket(_ten_minutes) as service:
            kv.fetch_tides_range_kartverket(BERGEN, date(2026, 3, 1), date(2026, 3, 1), OSLO)
        assert service.spans("pre") == [("2026-02-28T23:00", "2026-03-31T22:00")]

    def test_the_day_the_clocks_go_back_has_150_heights(self):
        day = date(2026, 10, 25)
        with kartverket(_ten_minutes):
            points = kv.fetch_tides_range_kartverket(BERGEN, day, day, OSLO)
        assert len(points) == 150
        assert points[0][0].astimezone(UTC) == _utc(2026, 10, 24, 22, 0)
        assert points[-1][0].astimezone(UTC) == _utc(2026, 10, 25, 22, 50)
        assert {b[0].timestamp() - a[0].timestamp() for a, b in zip(points, points[1:])} == {600}
        # the hour from two to three comes twice, on each clock
        assert [when.strftime("%H:%M %Z") for when, _height in points[11:20]] == [
            "01:50 CEST", "02:00 CEST", "02:10 CEST", "02:20 CEST", "02:30 CEST",
            "02:40 CEST", "02:50 CEST", "02:00 CET", "02:10 CET"]
        assert points[-1][0].strftime("%d %H:%M %Z") == "25 23:50 CET"
        assert [height for _when, height in points] == pytest.approx(
            [_cm(when) * CM for when, _height in points], abs=MM)

    def test_the_day_the_clocks_go_forward_has_138_heights(self):
        day = date(2026, 3, 29)
        with kartverket(_ten_minutes):
            points = kv.fetch_tides_range_kartverket(BERGEN, day, day, OSLO)
        assert len(points) == 138
        assert points[0][0].astimezone(UTC) == _utc(2026, 3, 28, 23, 0)
        assert points[-1][0].astimezone(UTC) == _utc(2026, 3, 29, 21, 50)
        assert {b[0].timestamp() - a[0].timestamp() for a, b in zip(points, points[1:])} == {600}
        # the hour from two to three never comes
        assert [when.strftime("%H:%M %Z") for when, _height in points[11:14]] == [
            "01:50 CET", "03:00 CEST", "03:10 CEST"]

    def test_a_range_across_two_months_reads_both_and_holds_midnight_once(self):
        with kartverket(_ten_minutes) as service:
            points = kv.fetch_tides_range_kartverket(BERGEN, date(2026, 9, 30), OCT_1, OSLO)
        # both answers hold the midnight they meet at
        assert service.spans("pre") == [("2026-08-31T22:00", "2026-09-30T22:00"),
                                        ("2026-09-30T22:00", "2026-10-31T23:00")]
        assert len(points) == 288
        assert {b[0].timestamp() - a[0].timestamp() for a, b in zip(points, points[1:])} == {600}

    def test_a_range_across_new_year_reads_december_and_january(self):
        with kartverket(_ten_minutes) as service:
            points = kv.fetch_tides_range_kartverket(BERGEN, date(2026, 12, 31),
                                                     date(2027, 1, 1), OSLO)
        assert service.spans("pre") == [("2026-11-30T23:00", "2026-12-31T23:00"),
                                        ("2026-12-31T23:00", "2027-01-31T23:00")]
        assert len(points) == 288
        assert points[144][0].strftime("%Y-%m-%d %H:%M") == "2027-01-01 00:00"

    def test_a_height_missing_its_time_or_its_value_is_left_out_alone(self):
        answer = _location([
            ("2026-10-01T00:00:00+00:00", "100.0", "pre"),
            (None, "101.0", "pre"),
            ("2026-10-01T00:20:00+00:00", None, "pre"),
            ("2026-10-01T00:30:00+00:00", "103.0", None),
        ])
        with kartverket(answer):
            points = kv.fetch_tides_range_kartverket(BERGEN, OCT_1, OCT_1, OSLO)
        assert [(when.strftime("%H:%M"), height) for when, height in points] == [
            ("02:00", pytest.approx(100 * CM, abs=MM)),
            ("02:30", pytest.approx(103 * CM, abs=MM))]

    def test_a_month_that_fails_leaves_the_other_months_heights(self):
        def answer(query):
            return DOWN if query["fromtime"].startswith("2026-08") else _ten_minutes(query)

        with kartverket(answer):
            points = kv.fetch_tides_range_kartverket(BERGEN, date(2026, 9, 30), OCT_1, OSLO)
        assert [when.day for when, _height in points] == [1] * 144


FETCHES = [kv.fetch_hilo_range_kartverket, kv.fetch_tides_range_kartverket]

NOT_TIDES = {
    "an error element": _tide("<error>Missing or wrong parameters.</error>"),
    "an empty body": b"",
    "an answer cut short": _location(BERGEN_TURNS)[:200],
    "a web page": b"<!DOCTYPE html>\n<html><body><h1>503 Service Unavailable</h1></body></html>",
    "no locationdata": _tide(""),
    "no data and no reason": _tide("<locationdata>\n<nodata/>\n</locationdata>"),
    "no data and an empty reason": _tide('<locationdata>\n<nodata info=" "/>\n</locationdata>'),
    "no waterlevels": _location([]),
    "no waterlevel that can be read": _location([
        (None, "162.0", "high"), ("2026-10-01T06:14:00+00:00", None, "low"),
        ("in the evening", "fifty", "low")]),
    "another reference level": _location(BERGEN_TURNS, reflevel="MSL"),
    "no reference level": _location(BERGEN_TURNS, reflevel=None),
    "an unknown unit": _location(BERGEN_TURNS, unit="in"),
    "no unit": _location(BERGEN_TURNS, unit=None),
    "a service out of reach": DOWN,
}


class TestAnswersThatAreNotTides:
    """An answer that is not a tide table is a failed fetch: nothing
    comes back, nothing raises, and nothing is kept, so the next run
    asks again. Only "no water here", with its reason, is kept."""

    @pytest.mark.parametrize("fetch", FETCHES)
    @pytest.mark.parametrize("answer", list(NOT_TIDES.values()), ids=list(NOT_TIDES))
    def test_it_is_nothing_and_the_next_run_asks_again(self, fetch, answer):
        with kartverket(answer) as service:
            assert fetch(BERGEN, OCT_1, OCT_1, OSLO) == []
        assert len(service.asked) == 1
        with kartverket(_location(BERGEN_TURNS)) as service:
            assert len(fetch(BERGEN, OCT_1, OCT_1, OSLO)) == 4
        assert len(service.asked) == 1

    @pytest.mark.parametrize("fetch", FETCHES)
    def test_no_water_with_its_reason_is_kept_like_any_answer(self, fetch):
        with kartverket(NO_WATER) as service:
            assert fetch("kv:61.6363,8.3125", OCT_1, OCT_1, OSLO) == []
            assert fetch("kv:61.6363,8.3125", OCT_1, OCT_1, OSLO) == []
        assert len(service.asked) == 1

    @pytest.mark.parametrize("fetch", FETCHES)
    @pytest.mark.parametrize("answer", [NOT_TIDES["an error element"], NO_WATER[:60], DOWN],
                             ids=["an error element", "an answer cut short", "out of reach"])
    def test_the_last_copy_stands_in_and_is_not_written_over(self, fetch, answer, cache):
        with kartverket(_location(BERGEN_TURNS)):
            before = fetch(BERGEN, OCT_1, OCT_1, OSLO)
        _aged(cache, days=40)
        with kartverket(answer) as service:
            assert fetch(BERGEN, OCT_1, OCT_1, OSLO) == before
        assert len(service.asked) == 1
        # still expired, so a service that is back is asked
        with kartverket(_location(BERGEN_TURNS[:2])) as service:
            assert len(fetch(BERGEN, OCT_1, OCT_1, OSLO)) == 2
        assert len(service.asked) == 1


class TestFindPoint:
    """Whether Kartverket predicts the tide at a point is told by asking
    it for this year's high and low waters there."""

    def test_a_point_on_the_coast_is_its_own_station(self):
        with kartverket(_a_years_turns) as service:
            assert kv.find_point_kartverket(60.398046, 5.320487) == BERGEN
        assert service.spans("tab") == [("2025-12-31T23:00", "2026-12-31T23:00")]
        assert (service.asked[0]["lat"], service.asked[0]["lon"]) == ("60.3980", "5.3205")

    def test_the_day_view_reads_the_years_turns_without_asking_again(self):
        with kartverket(_a_years_turns) as service:
            station_id = kv.find_point_kartverket(60.398046, 5.320487)
            turns = kv.fetch_hilo_range_kartverket(station_id, OCT_1, OCT_1, OSLO)
        assert len(turns) == 4
        assert len(service.asked) == 1

    @pytest.mark.parametrize("lat, lng", [
        (43.6591, -70.2568),   # Portland, Maine
        (61.6363, 8.3125),     # Galdhøpiggen, in the mountains
        (59.3293, 18.0686),    # Stockholm
    ])
    def test_a_point_kartverket_has_no_water_at_is_no_station(self, lat, lng):
        with kartverket(NO_WATER) as service:
            assert kv.find_point_kartverket(lat, lng) is None
        assert [(q["lat"], q["lon"]) for q in service.asked] == [(f"{lat:.4f}", f"{lng:.4f}")]

    def test_no_water_is_kept_so_the_point_is_not_asked_about_again(self):
        with kartverket(NO_WATER) as service:
            assert kv.find_point_kartverket(61.6363, 8.3125) is None
            assert kv.find_point_kartverket(61.6363, 8.3125) is None
        assert len(service.asked) == 1

    def test_no_data_with_no_reason_is_no_station_and_is_not_kept(self):
        with kartverket(NOT_TIDES["no data and no reason"]):
            assert kv.find_point_kartverket(60.398046, 5.320487) is None
        with kartverket(_a_years_turns):
            assert kv.find_point_kartverket(60.398046, 5.320487) == BERGEN

    @pytest.mark.parametrize("answer", [NOT_TIDES["an error element"], DOWN],
                             ids=["an error element", "out of reach"])
    def test_a_service_that_fails_is_no_station(self, answer):
        with kartverket(answer):
            assert kv.find_point_kartverket(60.398046, 5.320487) is None

    @pytest.mark.parametrize("lat, lng", [(None, None), (60.398046, None), (None, 5.320487)])
    def test_half_a_point_is_no_station_and_is_not_asked_about(self, lat, lng):
        with kartverket(_a_years_turns) as service:
            assert kv.find_point_kartverket(lat, lng) is None
        assert service.asked == []


class TestCaching:
    """Kartverket asks that its data be cached: an answer is kept by
    point and by year or month, a day for this year's and this month's,
    thirty days for those gone by."""

    @pytest.mark.parametrize("fetch, answer", [
        (kv.fetch_hilo_range_kartverket, _location(BERGEN_TURNS)),
        (kv.fetch_tides_range_kartverket, _ten_minutes),
    ], ids=["turns", "heights"])
    def test_a_kept_answer_is_used_without_a_fetch(self, fetch, answer):
        with kartverket(answer):
            fetched = fetch(BERGEN, OCT_1, OCT_1, OSLO)
        with kartverket(DOWN) as service:
            kept = fetch(BERGEN, OCT_1, OCT_1, OSLO)
        assert service.asked == []
        assert fetched and kept == fetched

    @pytest.mark.parametrize("fetch", FETCHES)
    def test_two_points_keep_an_answer_each(self, fetch):
        stavanger = "kv:58.9743,5.7301"
        answers = {"60.3980": _location(BERGEN_TURNS), "58.9743": _location(_turns(lift=-30))}
        with kartverket(lambda query: answers[query["lat"]]) as service:
            fetch(BERGEN, OCT_1, OCT_1, OSLO)
            fetch(stavanger, OCT_1, OCT_1, OSLO)
        assert [q["lat"] for q in service.asked] == ["60.3980", "58.9743"]
        with kartverket(DOWN):
            bergen = fetch(BERGEN, OCT_1, OCT_1, OSLO)
            other = fetch(stavanger, OCT_1, OCT_1, OSLO)
        assert [p[1] for p in bergen] == pytest.approx(
            [162 * CM, 43 * CM, 155 * CM, 50 * CM], abs=MM)
        assert [p[1] for p in other] == pytest.approx(
            [132 * CM, 13 * CM, 125 * CM, 20 * CM], abs=MM)

    def test_points_that_differ_past_the_fourth_decimal_share_an_answer(self):
        with kartverket(_location(BERGEN_TURNS)) as service:
            typed = kv.fetch_hilo_range_kartverket("kv:60.398046,5.320487", OCT_1, OCT_1, OSLO)
            searched = kv.fetch_hilo_range_kartverket(BERGEN, OCT_1, OCT_1, OSLO)
        assert len(service.asked) == 1
        assert typed == searched

    def test_two_years_keep_an_answer_each(self):
        with kartverket(_a_years_turns) as service:
            kv.fetch_hilo_range_kartverket(BERGEN, OCT_1, OCT_1, OSLO)
            kv.fetch_hilo_range_kartverket(BERGEN, date(2025, 10, 1), date(2025, 10, 1), OSLO)
        assert service.spans("tab") == [("2025-12-31T23:00", "2026-12-31T23:00"),
                                        ("2024-12-31T23:00", "2025-12-31T23:00")]
        with kartverket(DOWN):
            this = kv.fetch_hilo_range_kartverket(BERGEN, OCT_1, OCT_1, OSLO)
            last = kv.fetch_hilo_range_kartverket(BERGEN, date(2025, 10, 1),
                                                  date(2025, 10, 1), OSLO)
        assert [when.year for when, _height, _kind in this] == [2026] * 4
        assert [when.year for when, _height, _kind in last] == [2025] * 4

    def test_two_months_keep_an_answer_each(self):
        september = date(2026, 9, 1)
        with kartverket(_ten_minutes) as service:
            kv.fetch_tides_range_kartverket(BERGEN, OCT_1, OCT_1, OSLO)
            kv.fetch_tides_range_kartverket(BERGEN, september, september, OSLO)
        assert service.spans("pre") == [("2026-09-30T22:00", "2026-10-31T23:00"),
                                        ("2026-08-31T22:00", "2026-09-30T22:00")]
        with kartverket(DOWN):
            this = kv.fetch_tides_range_kartverket(BERGEN, OCT_1, OCT_1, OSLO)
            last = kv.fetch_tides_range_kartverket(BERGEN, september, september, OSLO)
        assert {when.month for when, _height in this} == {10}
        assert {when.month for when, _height in last} == {9}

    def test_the_turns_and_the_heights_of_a_point_are_kept_apart(self):
        with kartverket(lambda query: _ten_minutes(query) if query["datatype"] == "pre"
                        else _location(BERGEN_TURNS)) as service:
            turns = kv.fetch_hilo_range_kartverket(BERGEN, OCT_1, OCT_1, OSLO)
            points = kv.fetch_tides_range_kartverket(BERGEN, OCT_1, OCT_1, OSLO)
        assert [q["datatype"] for q in service.asked] == ["tab", "pre"]
        assert (len(turns), len(points)) == (4, 144)

    @pytest.mark.parametrize("year, age, asks", [
        (2026, {"hours": 23}, 0),   # this year: a day
        (2026, {"hours": 25}, 1),
        (2027, {"hours": 25}, 1),   # and a year to come
        (2025, {"days": 29}, 0),    # a year gone by: thirty days
        (2025, {"days": 31}, 1),
    ])
    def test_a_years_turns_are_kept_a_day_and_a_past_years_thirty(self, year, age, asks, cache):
        day = date(year, 10, 1)
        with kartverket(_a_years_turns):
            kv.fetch_hilo_range_kartverket(BERGEN, day, day, OSLO)
        _aged(cache, **age)
        with kartverket(_a_years_turns) as service:
            assert len(kv.fetch_hilo_range_kartverket(BERGEN, day, day, OSLO)) == 4
        assert len(service.asked) == asks

    @pytest.mark.parametrize("first, age, asks", [
        (date(2026, 10, 1), {"hours": 23}, 0),   # this month: a day
        (date(2026, 10, 1), {"hours": 25}, 1),
        (date(2026, 11, 1), {"hours": 25}, 1),   # and a month to come
        (date(2026, 9, 1), {"days": 29}, 0),     # a month gone by: thirty days
        (date(2026, 9, 1), {"days": 31}, 1),
    ])
    def test_a_months_heights_are_kept_a_day_and_a_past_months_thirty(self, first, age, asks,
                                                                      cache):
        def one_height(query):
            return _location([(_asked(query["fromtime"]).isoformat(), "100.0", "pre")])

        with kartverket(one_height):
            kv.fetch_tides_range_kartverket(BERGEN, first, first, OSLO)
        _aged(cache, **age)
        with kartverket(one_height) as service:
            assert len(kv.fetch_tides_range_kartverket(BERGEN, first, first, OSLO)) == 1
        assert len(service.asked) == asks


class TestYRange:
    """The y-axis range: the lowest and highest turn from the month
    before the date's through the month after, kept by month."""

    TURNS = [
        ("2026-05-31T20:00:00+00:00", "300.0", "high"),   # 22:00 on 31 May: before
        ("2026-05-31T22:30:00+00:00", "10.0", "low"),     # 00:30 on 1 June
        ("2026-07-10T04:00:00+00:00", "190.0", "high"),
        ("2026-07-10T10:00:00+00:00", "40.0", "low"),
        ("2026-08-31T21:30:00+00:00", "200.0", "high"),   # 23:30 on 31 August
        ("2026-08-31T22:30:00+00:00", "2.0", "low"),      # 00:30 on 1 September: after
    ]
    JULY = date(2026, 7, 15)

    def test_it_spans_the_turns_of_the_three_months(self):
        with kartverket(_location(self.TURNS)):
            low, high = kv.fetch_y_range_kartverket(BERGEN, self.JULY, OSLO)
        assert (low, high) == pytest.approx((10 * CM, 200 * CM), abs=MM)

    def test_it_costs_no_request_once_the_years_turns_are_kept(self):
        with kartverket(_location(self.TURNS)) as service:
            kv.fetch_hilo_range_kartverket(BERGEN, self.JULY, self.JULY, OSLO)
            assert kv.fetch_y_range_kartverket(BERGEN, self.JULY, OSLO) is not None
        assert len(service.asked) == 1

    def test_it_is_kept_for_the_month_longer_than_the_turns_are(self, cache):
        with kartverket(_location(self.TURNS)):
            first = kv.fetch_y_range_kartverket(BERGEN, self.JULY, OSLO)
        _aged(cache, days=6)
        with kartverket(DOWN) as service:
            assert kv.fetch_y_range_kartverket(BERGEN, date(2026, 7, 1), OSLO) == first
            assert kv.fetch_y_range_kartverket(BERGEN, date(2026, 7, 31), OSLO) == first
        assert service.asked == []

    def test_another_month_is_measured_afresh(self):
        with kartverket(_location(self.TURNS)):
            july = kv.fetch_y_range_kartverket(BERGEN, self.JULY, OSLO)
            # May to July: the high of 31 May is in, the one of 31 August out
            june = kv.fetch_y_range_kartverket(BERGEN, date(2026, 6, 15), OSLO)
        assert july == pytest.approx((10 * CM, 200 * CM), abs=MM)
        assert june == pytest.approx((10 * CM, 300 * CM), abs=MM)

    def test_another_point_is_measured_afresh(self):
        answers = {"60.3980": _location(self.TURNS), "58.9743": _location(self.TURNS[2:4])}
        with kartverket(lambda query: answers[query["lat"]]):
            bergen = kv.fetch_y_range_kartverket(BERGEN, self.JULY, OSLO)
            stavanger = kv.fetch_y_range_kartverket("kv:58.9743,5.7301", self.JULY, OSLO)
        assert bergen == pytest.approx((10 * CM, 200 * CM), abs=MM)
        assert stavanger == pytest.approx((40 * CM, 190 * CM), abs=MM)

    def test_with_no_turns_there_is_no_range_and_none_is_kept(self):
        with kartverket(DOWN):
            assert kv.fetch_y_range_kartverket(BERGEN, self.JULY, OSLO) is None
        with kartverket(_location(self.TURNS)):
            assert kv.fetch_y_range_kartverket(BERGEN, self.JULY, OSLO) is not None

    def test_a_point_with_no_water_has_no_range(self):
        with kartverket(NO_WATER):
            assert kv.fetch_y_range_kartverket("kv:61.6363,8.3125", self.JULY, OSLO) is None

    def test_an_id_that_names_no_point_has_no_range_and_no_tides(self):
        with kartverket(_location(self.TURNS)) as service:
            assert kv.fetch_y_range_kartverket("kv:bergen", self.JULY, OSLO) is None
            assert kv.fetch_hilo_range_kartverket("kv:bergen", self.JULY, self.JULY, OSLO) == []
            assert kv.fetch_tides_range_kartverket("kv:bergen", self.JULY, self.JULY, OSLO) == []
        assert service.asked == []


class TestGaugeFor:
    """A gauge's record is the water at a point only where the gauge is
    within five nautical miles and Kartverket predicts the very same
    high and low waters at both."""

    def test_a_point_out_of_every_gauges_reach_has_none_and_asks_nothing(self):
        with kartverket(_a_years_turns) as service:
            # Kristiansand, 16 nautical miles from the gauge at Tregde, and
            # Longyearbyen, 61 from the one at Ny-Ålesund
            assert kv.gauge_for("kv:58.1467,7.9956", 2026) is None
            assert kv.gauge_for("kv:78.2232,15.6267", 2026) is None
        assert service.asked == []

    def test_reach_is_five_nautical_miles(self):
        # a minute of latitude is a nautical mile
        bergen = kv.GAUGE_BY_CODE["BGO"]
        with kartverket(_a_years_turns):
            inside = kv.gauge_for(kv.make_station_id(bergen["lat"] + 4.9 / 60, bergen["lng"]), 2026)
            outside = kv.gauge_for(kv.make_station_id(bergen["lat"] + 5.1 / 60, bergen["lng"]),
                                   2026)
        assert inside is bergen
        assert outside is None

    def test_a_gauges_own_point_takes_it_for_one_year_of_turns(self):
        with kartverket(_a_years_turns) as service:
            assert kv.gauge_for(BERGEN, 2026) is kv.GAUGE_BY_CODE["BGO"]
        assert service.spans("tab") == [("2025-12-31T23:00", "2026-12-31T23:00")]

    def test_a_point_with_the_gauges_very_turns_takes_it_for_one_year_more(self):
        with kartverket(_a_years_turns) as service:
            assert kv.gauge_for(NEAR_BERGEN, 2025) is kv.GAUGE_BY_CODE["BGO"]
        # the point, then the gauge, for the year asked
        assert [(q["lat"], q["lon"]) for q in service.asked] == [
            ("60.4100", "5.3205"), ("60.3980", "5.3205")]
        assert service.spans("tab") == [("2024-12-31T23:00", "2025-12-31T23:00")] * 2

    @pytest.mark.parametrize("at_the_point", [
        _turns(minutes=5), _turns(factor=1.02), _turns(lift=10), BERGEN_TURNS[:3],
    ], ids=["five minutes later", "two per cent higher", "a datum 10 cm lower", "one turn short"])
    def test_a_point_whose_turns_are_not_the_gauges_has_none(self, at_the_point):
        answers = {"60.4100": _location(at_the_point), "60.3980": _location(BERGEN_TURNS)}
        with kartverket(lambda query: answers[query["lat"]]):
            assert kv.gauge_for(NEAR_BERGEN, 2026) is None

    def test_the_nearest_gauge_is_the_one_compared(self):
        # in Oslo harbour, half a mile from Oslo's gauge and 14 from Oscarsborg's
        with kartverket(_a_years_turns) as service:
            assert kv.gauge_for("kv:59.9000,10.7400", 2026)["code"] == "OSL"
        assert (service.asked[-1]["lat"], service.asked[-1]["lon"]) == ("59.9086", "10.7345")

    @pytest.mark.parametrize("answer", [DOWN, NO_WATER, NOT_TIDES["an error element"]],
                             ids=["out of reach", "no water", "an error element"])
    def test_with_no_turns_to_compare_there_is_none(self, answer):
        with kartverket(answer):
            assert kv.gauge_for(BERGEN, 2026) is None
            assert kv.gauge_for(NEAR_BERGEN, 2026) is None

    def test_turns_at_the_point_and_none_at_the_gauge_is_none(self):
        answers = {"60.4100": _location(BERGEN_TURNS), "60.3980": DOWN}
        with kartverket(lambda query: answers[query["lat"]]):
            assert kv.gauge_for(NEAR_BERGEN, 2026) is None

    def test_an_id_that_names_no_point_has_none(self):
        assert kv.gauge_for("kv:bergen", 2026) is None


class TestObservedExtremes:
    """What the water did: each day's lowest and highest reading at the
    gauge that stands for the point, in feet above chart datum, for the
    days of the year before today."""

    def test_a_past_year_is_one_request_for_the_gauges_ten_minute_readings(self):
        with kartverket(_gauge(_the_last_days)) as service:
            days = kv.fetch_observed_extremes_kartverket(BERGEN, 2025, TODAY)
        assert [q["tide_request"] for q in service.asked] == ["locationdata", "stationdata"]
        query = service.asked[-1]
        assert query["stationcode"] == "BGO"
        assert (query["datatype"], query["interval"]) == ("obs", "10")
        assert query["refcode"].upper() == "CD"
        # Norway's 2025, in UTC
        assert (query["fromtime"], query["totime"]) == ("2024-12-31T23:00", "2025-12-31T23:00")
        assert query["tzone"] == "0"
        assert sorted(days) == [date(2025, 12, 30), date(2025, 12, 31)]

    @pytest.mark.parametrize("answer", [
        _tide("<stationdata><nodata/></stationdata>"),
        _station([], "2025-01-01T00:00:00+00:00"),
        _tide('<stationdata><location name="Bergen" code="BGO"/></stationdata>'),
    ], ids=["nodata", "no-readings", "no-data-element"])
    def test_an_answer_with_no_readings_is_the_gauge_down_and_is_not_kept(self, cache, answer):
        """Kept, it would blank the year's pen for a month."""
        with kartverket(_gauge(answer)) as service:
            assert kv.fetch_observed_extremes_kartverket(BERGEN, 2025, TODAY) == {}
            assert kv.fetch_observed_extremes_kartverket(BERGEN, 2025, TODAY) == {}
        assert [q["tide_request"] for q in service.asked].count("stationdata") == 2
        assert not list(cache.glob("kv_obs_*"))

    def test_readings_too_few_to_make_a_day_are_still_an_answer_and_are_kept(self, cache):
        an_hour = _readings(_utc(2025, 6, 30, 22), _utc(2025, 6, 30, 23))
        with kartverket(_gauge(an_hour)) as service:
            assert kv.fetch_observed_extremes_kartverket(BERGEN, 2025, TODAY) == {}
            assert kv.fetch_observed_extremes_kartverket(BERGEN, 2025, TODAY) == {}
        assert [q["tide_request"] for q in service.asked].count("stationdata") == 1

    def test_a_reference_time_with_no_offset_is_read_as_utc(self):
        """The request asks for UTC; the machine's own clock has no say."""
        def rising(moment):
            # a centimetre every ten minutes from 22:00, Norway's midnight
            return (moment - moment.replace(hour=22, minute=0)).total_seconds() / 600 % 144

        stated = _readings(_utc(2025, 6, 30, 22), _utc(2025, 7, 1, 22), rising)
        bare = _readings(datetime(2025, 6, 30, 22), datetime(2025, 7, 1, 22), rising)
        assert b"+00:00" in stated and b"+00:00" not in bare
        with kartverket(_gauge(stated)):
            want = kv.fetch_observed_extremes_kartverket(BERGEN, 2025, TODAY)
        with patch.dict(os.environ, {"LINECAST_CACHE_DIR": os.environ["LINECAST_CACHE_DIR"] + "2"}):
            with kartverket(_gauge(bare)):
                got = kv.fetch_observed_extremes_kartverket(BERGEN, 2025, TODAY)
        assert got == want and list(want) == [date(2025, 7, 1)]

    def test_each_day_is_its_lowest_and_highest_reading_in_feet(self):
        def cm(moment):
            return round(100 + 80 * sin(2 * pi * (moment - _utc(2025, 6, 30, 22)).total_seconds()
                                        / 86400), 1)

        answer = _readings(_utc(2025, 6, 30, 22), _utc(2025, 7, 1, 22), cm)
        with kartverket(_gauge(answer)):
            days = kv.fetch_observed_extremes_kartverket(BERGEN, 2025, TODAY)
        assert list(days) == [date(2025, 7, 1)]
        assert days[date(2025, 7, 1)] == pytest.approx((20 * CM, 180 * CM), abs=MM)
        # 20 and 180 cm above chart datum, in feet
        assert days[date(2025, 7, 1)] == pytest.approx((0.656, 5.906), abs=0.001)

    def test_a_reading_belongs_to_its_day_on_norways_clock(self):
        readings = {
            _utc(2025, 6, 30, 22, 30): 20.0,    # 00:30 on 1 July
            _utc(2025, 7, 1, 21, 50): 180.0,    # 23:50 on 1 July
            _utc(2025, 7, 1, 22, 0): 250.0,     # midnight opening 2 July
        }
        answer = _readings(_utc(2025, 6, 29, 22), _utc(2025, 7, 2, 22),
                           lambda moment: readings.get(moment, 100.0))
        with kartverket(_gauge(answer)):
            days = kv.fetch_observed_extremes_kartverket(BERGEN, 2025, TODAY)
        assert sorted(days) == [date(2025, 6, 30), date(2025, 7, 1), date(2025, 7, 2)]
        assert days[date(2025, 6, 30)] == pytest.approx((100 * CM, 100 * CM), abs=MM)
        assert days[date(2025, 7, 1)] == pytest.approx((20 * CM, 180 * CM), abs=MM)
        assert days[date(2025, 7, 2)] == pytest.approx((100 * CM, 250 * CM), abs=MM)

    def test_the_day_the_clocks_go_forward_ends_an_hour_sooner_by_utc(self):
        # 30 March 2025 is 23 hours long: 23:00 UTC on the 29th to 22:00 on the 30th
        late = {_utc(2025, 3, 30, 22, 30): 180.0}    # 00:30 on the 31st, summer time
        answer = _readings(_utc(2025, 3, 29, 23), _utc(2025, 3, 31, 22),
                           lambda moment: late.get(moment, 100.0))
        with kartverket(_gauge(answer)):
            days = kv.fetch_observed_extremes_kartverket(BERGEN, 2025, TODAY)
        assert sorted(days) == [date(2025, 3, 30), date(2025, 3, 31)]
        assert days[date(2025, 3, 30)] == pytest.approx((100 * CM, 100 * CM), abs=MM)
        assert days[date(2025, 3, 31)] == pytest.approx((100 * CM, 180 * CM), abs=MM)

    def test_the_day_the_clocks_go_back_ends_an_hour_later_by_utc(self):
        # 26 October 2025 is 25 hours long: 22:00 UTC on the 25th to 23:00 on the 26th
        late = {_utc(2025, 10, 26, 22, 30): 180.0}   # 23:30 on the 26th, winter time
        answer = _readings(_utc(2025, 10, 25, 22), _utc(2025, 10, 27, 23),
                           lambda moment: late.get(moment, 100.0))
        with kartverket(_gauge(answer)):
            days = kv.fetch_observed_extremes_kartverket(BERGEN, 2025, TODAY)
        assert sorted(days) == [date(2025, 10, 26), date(2025, 10, 27)]
        assert days[date(2025, 10, 26)] == pytest.approx((100 * CM, 180 * CM), abs=MM)
        assert days[date(2025, 10, 27)] == pytest.approx((100 * CM, 100 * CM), abs=MM)

    def test_readings_from_outside_the_year_are_not_the_years(self):
        def cm(moment):
            # whole days at either end: 31 December 2024 and 1 January 2025,
            # 31 December 2025 and 1 January 2026
            if _utc(2025, 1, 1, 23) <= moment < _utc(2025, 12, 30, 23):
                return None
            return 100.0

        answer = _readings(_utc(2024, 12, 30, 23), _utc(2026, 1, 1, 23), cm)
        with kartverket(_gauge(answer)):
            days = kv.fetch_observed_extremes_kartverket(BERGEN, 2025, TODAY)
        assert sorted(days) == [date(2025, 1, 1), date(2025, 12, 31)]

    def test_a_day_missing_more_than_a_quarter_of_its_readings_is_left_out(self):
        def cm(moment):
            # 1 July loses its last six hours, which leaves 108 of its 144
            # readings: three quarters. 2 July loses ten minutes more.
            if _utc(2025, 7, 1, 16, 0) <= moment < _utc(2025, 7, 1, 22, 0):
                return None
            if _utc(2025, 7, 2, 15, 50) <= moment < _utc(2025, 7, 2, 22, 0):
                return None
            return 100.0

        answer = _readings(_utc(2025, 6, 30, 22), _utc(2025, 7, 3, 22), cm)
        with kartverket(_gauge(answer)):
            days = kv.fetch_observed_extremes_kartverket(BERGEN, 2025, TODAY)
        assert sorted(days) == [date(2025, 7, 1), date(2025, 7, 3)]

    def test_a_reading_tens_of_metres_out_is_a_fault_and_sets_no_days_high_or_low(self):
        faults = {
            _utc(2025, 7, 1, 3, 0): "1.4e+17",
            _utc(2025, 7, 1, 4, 0): "3000.0",
            _utc(2025, 7, 1, 5, 0): "-9999.0",
        }
        answer = _readings(_utc(2025, 6, 30, 22), _utc(2025, 7, 1, 22),
                           lambda moment: faults.get(moment, 100.0))
        with kartverket(_gauge(answer)):
            days = kv.fetch_observed_extremes_kartverket(BERGEN, 2025, TODAY)
        assert days == {date(2025, 7, 1): pytest.approx((100 * CM, 100 * CM), abs=MM)}

    def test_a_reading_missing_its_time_or_its_value_is_left_out_alone(self):
        answer = _readings(_utc(2025, 6, 30, 22), _utc(2025, 7, 1, 22),
                           extra=[(None, "400.0"), (600, None), ("soon", "400.0"),
                                  (1200, "high")])
        with kartverket(_gauge(answer)):
            days = kv.fetch_observed_extremes_kartverket(BERGEN, 2025, TODAY)
        assert days == {date(2025, 7, 1): pytest.approx((100 * CM, 100 * CM), abs=MM)}

    def test_readings_in_metres_are_the_same_water(self):
        start = _utc(2025, 6, 30, 22)
        answer = _station([(600 * n, "1.62") for n in range(144)], start.isoformat(), unit="m")
        with kartverket(_gauge(answer)):
            days = kv.fetch_observed_extremes_kartverket(BERGEN, 2025, TODAY)
        assert days == {date(2025, 7, 1): pytest.approx((162 * CM, 162 * CM), abs=MM)}

    def test_this_year_is_the_months_gone_by_and_this_months_days_before_today(self):
        with kartverket(_gauge(_the_last_days)) as service:
            days = kv.fetch_observed_extremes_kartverket(BERGEN, 2026, TODAY)
        assert service.spans("obs") == [("2025-12-31T23:00", "2026-09-30T22:00"),
                                        ("2026-09-30T22:00", "2026-10-09T22:00")]
        # each answer ran a day past its end: 1 October is the second
        # request's to give, and today is not over
        assert sorted(days) == [date(2026, 9, 29), date(2026, 9, 30),
                                date(2026, 10, 8), date(2026, 10, 9)]

    def test_on_the_first_of_a_month_only_the_months_gone_by_are_asked_for(self):
        with kartverket(_gauge(_the_last_days)) as service:
            days = kv.fetch_observed_extremes_kartverket(BERGEN, 2026, OCT_1)
        assert service.spans("obs") == [("2025-12-31T23:00", "2026-09-30T22:00")]
        assert sorted(days) == [date(2026, 9, 29), date(2026, 9, 30)]

    def test_in_january_only_its_own_days_are_asked_for(self):
        with kartverket(_gauge(_the_last_days)) as service:
            days = kv.fetch_observed_extremes_kartverket(BERGEN, 2026, date(2026, 1, 15))
        assert service.spans("obs") == [("2025-12-31T23:00", "2026-01-14T23:00")]
        assert sorted(days) == [date(2026, 1, 13), date(2026, 1, 14)]

    @pytest.mark.parametrize("year, today", [
        (2026, date(2026, 1, 1)),    # New Year's Day: no day of it is over
        (2027, TODAY),               # a year to come
    ])
    def test_a_year_with_no_day_gone_by_is_empty_and_asks_nothing(self, year, today):
        with kartverket(_gauge(_the_last_days)) as service:
            assert kv.fetch_observed_extremes_kartverket(BERGEN, year, today) == {}
        assert service.asked == []

    def test_a_point_no_gauge_stands_for_is_empty_and_asks_for_no_readings(self):
        answers = {"60.4100": _location(_turns(minutes=5)), "60.3980": _location(BERGEN_TURNS)}
        with kartverket(lambda query: answers[query["lat"]]) as service:
            assert kv.fetch_observed_extremes_kartverket(NEAR_BERGEN, 2025, TODAY) == {}
            assert kv.fetch_observed_extremes_kartverket("kv:58.1467,7.9956", 2025, TODAY) == {}
        assert {q["tide_request"] for q in service.asked} == {"locationdata"}

    def test_a_point_beside_a_gauge_with_its_tide_has_the_gauges_readings(self):
        with kartverket(_gauge(_the_last_days)) as service:
            days = kv.fetch_observed_extremes_kartverket(NEAR_BERGEN, 2025, TODAY)
        assert service.asked[-1]["stationcode"] == "BGO"
        assert sorted(days) == [date(2025, 12, 30), date(2025, 12, 31)]

    def test_kept_readings_are_used_without_a_fetch(self):
        with kartverket(_gauge(_the_last_days)):
            fetched = kv.fetch_observed_extremes_kartverket(BERGEN, 2026, TODAY)
        with kartverket(DOWN) as service:
            kept = kv.fetch_observed_extremes_kartverket(BERGEN, 2026, TODAY)
        assert service.asked == []
        assert fetched and kept == fetched

    def test_a_past_years_readings_are_kept_thirty_days(self, cache):
        with kartverket(_gauge(_the_last_days)):
            kv.fetch_observed_extremes_kartverket(BERGEN, 2025, TODAY)
        _aged(cache, days=29)
        with kartverket(_gauge(_the_last_days)) as service:
            kv.fetch_observed_extremes_kartverket(BERGEN, 2025, TODAY)
        assert service.asked == []
        _aged(cache, days=31)
        with kartverket(_gauge(_the_last_days)) as service:
            kv.fetch_observed_extremes_kartverket(BERGEN, 2025, TODAY)
        assert service.spans("obs") == [("2024-12-31T23:00", "2025-12-31T23:00")]

    def test_this_months_readings_are_kept_three_hours_the_earlier_months_longer(self, cache):
        with kartverket(_gauge(_the_last_days)):
            kv.fetch_observed_extremes_kartverket(BERGEN, 2026, TODAY)
        _aged(cache, hours=2)
        with kartverket(_gauge(_the_last_days)) as service:
            kv.fetch_observed_extremes_kartverket(BERGEN, 2026, TODAY)
        assert service.asked == []
        _aged(cache, hours=4)
        with kartverket(_gauge(_the_last_days)) as service:
            kv.fetch_observed_extremes_kartverket(BERGEN, 2026, TODAY)
        assert service.spans("obs") == [("2026-09-30T22:00", "2026-10-09T22:00")]

    def test_a_new_day_fetches_this_months_readings_again_however_fresh(self):
        with kartverket(_gauge(_the_last_days)) as service:
            kv.fetch_observed_extremes_kartverket(BERGEN, 2026, TODAY)
            days = kv.fetch_observed_extremes_kartverket(BERGEN, 2026, date(2026, 10, 11))
            again = kv.fetch_observed_extremes_kartverket(BERGEN, 2026, date(2026, 10, 11))
        assert service.spans("obs") == [("2025-12-31T23:00", "2026-09-30T22:00"),
                                        ("2026-09-30T22:00", "2026-10-09T22:00"),
                                        ("2026-09-30T22:00", "2026-10-10T22:00")]
        assert date(2026, 10, 10) in days
        assert again == days

    def test_a_new_month_fetches_the_months_gone_by_again(self):
        with kartverket(_gauge(_the_last_days)) as service:
            kv.fetch_observed_extremes_kartverket(BERGEN, 2026, TODAY)
            days = kv.fetch_observed_extremes_kartverket(BERGEN, 2026, date(2026, 11, 2))
        assert service.spans("obs")[2:] == [("2025-12-31T23:00", "2026-10-31T23:00"),
                                            ("2026-10-31T23:00", "2026-11-01T23:00")]
        assert sorted(days) == [date(2026, 10, 30), date(2026, 10, 31), date(2026, 11, 1)]

    def test_a_gauge_out_of_reach_on_a_new_day_leaves_the_days_it_had(self):
        with kartverket(_gauge(_the_last_days)):
            before = kv.fetch_observed_extremes_kartverket(BERGEN, 2026, TODAY)
        with kartverket(_gauge(DOWN)):
            after = kv.fetch_observed_extremes_kartverket(BERGEN, 2026, date(2026, 10, 11))
        assert after == before

    @pytest.mark.parametrize("answer", [
        NOT_TIDES["an error element"],
        b"",
        _tide(""),
        _location(BERGEN_TURNS),
        _readings(_utc(2025, 6, 30, 22), _utc(2025, 7, 1, 22))[:300],
        _station([(600 * n, "100.0") for n in range(144)], "2025-06-30T22:00:00+00:00",
                 reflevel="MSL"),
        _station([(600 * n, "100.0") for n in range(144)], "2025-06-30T22:00:00+00:00",
                 unit="in"),
        _station([(600 * n, "100.0") for n in range(144)], None),
        DOWN,
    ], ids=["an error element", "an empty body", "no stationdata", "a tide table",
            "an answer cut short", "another reference level", "an unknown unit",
            "no reftime", "out of reach"])
    def test_an_answer_that_is_not_readings_is_empty_and_is_asked_for_again(self, answer):
        with kartverket(_gauge(answer)):
            assert kv.fetch_observed_extremes_kartverket(BERGEN, 2025, TODAY) == {}
        with kartverket(_gauge(_the_last_days)) as service:
            days = kv.fetch_observed_extremes_kartverket(BERGEN, 2025, TODAY)
        assert len(service.spans("obs")) == 1
        assert sorted(days) == [date(2025, 12, 30), date(2025, 12, 31)]

    def test_readings_that_are_not_observations_are_not_what_was_measured(self):
        answer = _station([(600 * n, "100.0") for n in range(144)], "2025-06-30T22:00:00+00:00",
                          kind="prediction")
        with kartverket(_gauge(answer)):
            assert kv.fetch_observed_extremes_kartverket(BERGEN, 2025, TODAY) == {}


class TestWhatDebugSays:
    """A failure is absorbed, and --debug names it: the source, what
    failed, and the service's own words where it gave any."""

    @pytest.fixture(autouse=True)
    def debug(self, monkeypatch):
        monkeypatch.setattr(_log, "_DEBUG", True)

    def test_an_error_answer_is_a_failed_fetch_in_kartverkets_words(self, capsys):
        with kartverket(NOT_TIDES["an error element"]):
            kv.fetch_hilo_range_kartverket(BERGEN, OCT_1, OCT_1, OSLO)
        assert ("[linecast] tides/kartverket: fetch failed (vannstand.kartverket.no) -- "
                "ValueError: Missing or wrong parameters.") in capsys.readouterr().err

    def test_a_service_out_of_reach_is_named_by_its_host_and_never_the_place(self, capsys):
        with kartverket(DOWN):
            kv.fetch_tides_range_kartverket(BERGEN, OCT_1, OCT_1, OSLO)
        err = capsys.readouterr().err
        assert ("[linecast] tides/kartverket: fetch failed (vannstand.kartverket.no) -- "
                "OSError: network is unreachable") in err
        assert "60.39" not in err and "5.32" not in err

    def test_no_data_with_no_reason_is_a_failed_parse(self, capsys):
        with kartverket(NOT_TIDES["no data and no reason"]):
            kv.find_point_kartverket(60.398046, 5.320487)
        assert ("[linecast] tides/kartverket: parse failed (vannstand.kartverket.no) -- "
                "ValueError") in capsys.readouterr().err

    def test_no_water_with_its_reason_is_no_failure(self, capsys):
        with kartverket(NO_WATER):
            kv.find_point_kartverket(61.6363, 8.3125)
        assert "failed" not in capsys.readouterr().err

    def test_waterlevels_left_out_are_counted(self, capsys):
        answer = _location([BERGEN_TURNS[0], (None, "43.0", "low"),
                            ("2026-10-01T12:50:00+00:00", None, "high"), BERGEN_TURNS[3]])
        with kartverket(answer):
            kv.fetch_hilo_range_kartverket(BERGEN, OCT_1, OCT_1, OSLO)
        err = capsys.readouterr().err
        assert "[linecast] tides/kartverket: parse of high and low waters failed" in err
        assert "2 of 4 skipped" in err

    def test_an_id_that_names_no_point_is_said_to_be_no_station(self, capsys):
        kv.parse_station_id("kv:bergen")
        err = capsys.readouterr().err
        assert "[linecast] tides/kartverket: parse of station id failed" in err
        assert "no station" in err
