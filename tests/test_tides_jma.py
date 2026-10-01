"""Tests for the Japan Meteorological Agency tide source.

The 2026 lines are cut from JMA's own files for Tokyo (TK): its tide
table for the year, the gauge's final record for January and February,
and January's deviations.  Two lines are made up in the same layout and
say so: the first day of 2027, so a range across New Year has a second
table to ask for, and February's deviations.  Each line is written in
the parts the layout gives it: the 24 hourly heights, the date and the
station's code, then the four high-water slots and the four low-water
ones.
"""

import importlib.util
import os
import time
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from linecast import _runtime
from linecast._http import HTTPError
from linecast.tides import common
from linecast.tides import jma
from linecast.tides.jma import JST

# ---------------------------------------------------------------------------
# JMA's tide table for Tokyo, 2026
# ---------------------------------------------------------------------------
JAN_1 = (
    " 87119145162169166154140128123128140155168175172157130 94 55 22  2  0 17" "26 1 1TK"
    " 4 8169141517699999999999999" " 9 11232135 -299999999999999")
JAN_2 = (
    " 48 86124155175182176160142128122127140158174182179160126 84 42  7-11-10" "26 1 2TK"
    " 458182151418399999999999999" "10 21222225-1399999999999999")
JAN_3 = (
    " 11 47 90133166185188177157137122118125142163182190183159120 74 31 -3-18" "26 1 3TK"
    " 54018816 519099999999999999" "10531182314-1999999999999999")
JAN_31 = (
    " 49 83119149170176171156139124118120131147164174173155124 84 44 13 -4 -2" "26 131TK"
    " 5 0176152317599999999999999" "10131172224 -699999999999999")
FEB_1 = (
    " 18 51 93133165181181167146125109104111129153175187181158120 76 34  3-10" "26 2 1TK"
    " 529183161318799999999999999" "105510423 9-1199999999999999")
SEP_30 = (
    " 28 23 41 75118158185196189170144119101 97108132162188203200181148109 71" "26 930TK"
    " 7 5196182220499999999999999" " 042 221247 9699999999999999")
DEC_31 = (
    "116 99 84 75 74 84102125146161166160146128109 94 83 80 83 92104116124127" "261231TK"
    " 95716623 112799999999999999" " 333 7317 0 8099999999999999")
# Made up: 2027's table was not out when this was written.
JAN_1_2027 = (
    "119103 91 85 86 97114134153165168162149131113 98 88 85 89 98110121129131" "27 1 1TK"
    "1010168233013199999999999999" " 330 851650 8599999999999999")

# What the Tokyo gauge measured on the same days, from JMA's final files:
# the same layout, over the gauge's own datum.
GAUGE_JAN_1 = (
    "157183206224234231219204194192200214228237240235223200165125 88 68 71 94" "26 1 1TK"
    " 418234135524099999999999999" " 8421912122 6699999999999999")
GAUGE_JAN_2 = (
    "127160191220242252246230211198195203218234247254252235200152101 60 45 58" "26 1 2TK"
    " 5 8252151925499999999999999" " 94719422 1 4599999999999999")
GAUGE_JAN_3 = (
    " 90126161194224245249237217196183182192209230248257249223182134 89 56 43" "26 1 3TK"
    " 54525016 525799999999999999" "103418123 8 4399999999999999")
GAUGE_FEB_1 = (
    " 92126164201233252254240217195182181192210231249258252230192146102 69 56" "26 2 1TK"
    " 53625516 825899999999999999" "103417923 3 5699999999999999")

# January's deviations, observed less predicted on the hour: four columns
# to an hour, then the date in full and the code.
DEVIATIONS_JAN = (
    "  -4 -10 -13 -12  -9  -9  -9 -10  -8  -5  -2   0"
    "  -1  -5  -9 -11  -8  -4  -3  -4  -8  -8  -3   3" "20260101TK",
    "   5   0  -7  -9  -7  -4  -4  -4  -5  -4  -1   2"
    "   4   2  -1  -2  -1   1   0  -6 -15 -21 -18  -6" "20260102TK",
    "   5   5  -3 -13 -16 -14 -13 -14 -14 -15 -13 -10"
    "  -7  -7  -7  -8  -7  -8 -10 -12 -14 -16 -15 -13" "20260103TK",
)
# Made up: 1 February's, worked out from the two lines above for that day
# and the 74 cm January's files put between the gauge's datum and the
# table's.
DEVIATIONS_FEB = (
    "   0   1  -3  -6  -6  -3  -1  -1  -3  -4  -1   3"
    "   7   7   4   0  -3  -3  -2  -2  -4  -6  -8  -8" "20260201TK",
)

# At 0h on 1 January the table says 87 cm, the gauge read 157 and the
# deviation is -4: 87 - 4 - 157 = -74, and so at every other hour.
GAUGE_TO_TABLE_CM = -74

BASE = "https://www.data.jma.go.jp/kaiyou/data/db/tide"
TOKYO = "jma:TK"


def table_url(year, code="TK"):
    """Where JMA keeps a station's tide table for a year."""
    return f"{BASE}/suisan/txt/{year}/{code}.txt"


def final_url(kind, month, code="TK"):
    """A month's final file of *kind*: "hry" heights, "dep" deviations."""
    return f"{BASE}/genbo/{month[:4]}/{month}/{kind}{month}{code}.txt"


def preliminary_url(kind, month, code="TK"):
    return f"{BASE}/sokuho/{month}/z_{kind}{month}{code}.txt"


def feet(cm):
    """Centimetres as the feet the tides pipeline works in: 30.48 cm each."""
    return cm / 30.48


def hours_only(line):
    """A line as the preliminary files have it: the hours, date and code."""
    return line[:80]


def without_turns(line):
    """A line whose high and low waters the gauge missed: blank slots."""
    return line[:80] + " " * 56


class Agency:
    """JMA's file server, as far as a test stocks it: the files by their
    URL, a 404 for any other, and a note of every URL asked for.  A file
    is its lines, or bytes to send as they are, or an exception to
    raise."""

    def __init__(self):
        self.files = {}
        self.asked = []

    def __call__(self, url, timeout=10):
        self.asked.append(url)
        answer = self.files.get(url)
        if answer is None:
            raise HTTPError(url, 404, "Not Found")
        if isinstance(answer, Exception):
            raise answer
        if isinstance(answer, bytes):
            return answer
        return ("\n".join(answer) + "\n").encode("ascii")


@pytest.fixture(autouse=True)
def cache(tmp_path):
    """Every test keeps its files in a directory of its own."""
    with patch.object(jma, "cache_dir", return_value=tmp_path):
        yield tmp_path


@pytest.fixture
def agency():
    served = Agency()
    with patch.object(jma, "fetch_bytes", served):
        yield served


@pytest.fixture
def tokyo_2026(agency):
    """The agency with Tokyo's table for 2026, as far as the lines above."""
    agency.files[table_url(2026)] = [JAN_1, JAN_2, JAN_3, JAN_31, FEB_1, SEP_30, DEC_31]
    return agency


def _reader_of(monkeypatch, lang):
    monkeypatch.setattr(_runtime, "_current",
                        replace(_runtime.RuntimeConfig.defaults(), lang=lang))


def _age(directory, days):
    """Every file in *directory* as it would be *days* from now."""
    then = time.time() - days * 86400
    for path in directory.iterdir():
        os.utime(path, (then, then))


def test_the_lines_above_are_in_the_layout():
    """An editor that trimmed or rewrapped one fails here, not somewhere
    puzzling."""
    tables = (JAN_1, JAN_2, JAN_3, JAN_31, FEB_1, SEP_30, DEC_31, JAN_1_2027,
              GAUGE_JAN_1, GAUGE_JAN_2, GAUGE_JAN_3, GAUGE_FEB_1)
    assert {len(line) for line in tables} == {136}
    assert {len(line) for line in DEVIATIONS_JAN + DEVIATIONS_FEB} == {106}


class TestTable:
    """The parser: a line a day, the hours in columns 1-72, the date and
    code by column 80, then the high waters and the low."""

    def test_the_hourly_heights_land_on_the_hours_of_their_day(self):
        points = jma.parse_hourly([JAN_1])
        assert [dt for dt, _ in points] == [datetime(2026, 1, 1, hour, tzinfo=JST)
                                            for hour in range(24)]
        assert [h for _, h in points] == pytest.approx([feet(cm) for cm in (
            87, 119, 145, 162, 169, 166, 154, 140, 128, 123, 128, 140,
            155, 168, 175, 172, 157, 130, 94, 55, 22, 2, 0, 17)])

    def test_heights_come_out_in_feet(self):
        # 87 cm at midnight: 2 ft 10 in and a bit
        assert jma.parse_hourly([JAN_1])[0][1] == pytest.approx(2.854, abs=0.001)
        assert jma.parse_hilo([JAN_1])[0][1] == pytest.approx(169 / 30.48)

    def test_times_are_japan_standard_time(self):
        midnight = jma.parse_hourly([JAN_1])[0][0]
        assert midnight.utcoffset() == timedelta(hours=9)
        # the first hour of the year in Tokyo is still last year in Greenwich
        assert midnight == datetime(2025, 12, 31, 15, tzinfo=timezone.utc)
        high = jma.parse_hilo([JAN_1])[0][0]
        assert high == datetime(2025, 12, 31, 19, 8, tzinfo=timezone.utc)

    def test_water_below_the_datum_is_negative(self):
        points = jma.parse_hourly([JAN_2])
        assert [h for _, h in points[-3:]] == pytest.approx([feet(7), feet(-11), feet(-10)])
        low = jma.parse_hilo([JAN_2])[-1]
        assert low == (datetime(2026, 1, 2, 22, 25, tzinfo=JST), pytest.approx(feet(-13)), "L")

    def test_the_high_and_low_waters_carry_their_times_and_heights(self):
        assert jma.parse_hilo([JAN_1]) == [
            (datetime(2026, 1, 1, 4, 8, tzinfo=JST), pytest.approx(feet(169)), "H"),
            (datetime(2026, 1, 1, 9, 1, tzinfo=JST), pytest.approx(feet(123)), "L"),
            (datetime(2026, 1, 1, 14, 15, tzinfo=JST), pytest.approx(feet(176)), "H"),
            (datetime(2026, 1, 1, 21, 35, tzinfo=JST), pytest.approx(feet(-2)), "L"),
        ]

    def test_a_low_before_the_days_first_high_comes_first(self):
        # JMA lists the highs, then the lows; 30 September opens with a low
        events = jma.parse_hilo([SEP_30])
        assert [(dt.strftime("%H:%M"), kind) for dt, _, kind in events] == [
            ("00:42", "L"), ("07:05", "H"), ("12:47", "L"), ("18:22", "H")]
        assert events[0][1] == pytest.approx(feet(22))

    def test_an_hour_or_a_minute_under_ten_is_written_with_a_space(self):
        # " 333", "23 1" and "17 0" on 31 December
        assert [dt.strftime("%H:%M") for dt, _, _ in jma.parse_hilo([DEC_31])] == [
            "03:33", "09:57", "17:00", "23:01"]

    def test_days_given_out_of_order_come_back_in_time_order(self):
        events = jma.parse_hilo([JAN_2, JAN_1])
        assert [dt for dt, _, _ in events] == sorted(dt for dt, _, _ in events)
        assert [dt.day for dt, _, _ in events] == [1] * 4 + [2] * 4

    def test_a_slot_reading_9999_is_no_tide(self):
        # each day above has two highs and two lows, and four slots for each
        assert "9999999" * 2 in JAN_1
        assert len(jma.parse_hilo([JAN_1])) == 4

    def test_a_blank_slot_is_no_tide(self):
        assert jma.parse_hilo([without_turns(GAUGE_JAN_1)]) == []
        one_high = JAN_1[:80] + " 4 8169" + " " * 49
        assert [(dt.hour, kind) for dt, _, kind in jma.parse_hilo([one_high])] == [(4, "H")]

    def test_a_blank_hour_is_left_out_and_the_rest_keep_their_hours(self):
        line = JAN_1[:15] + "   " + JAN_1[18:]
        points = jma.parse_hourly([line])
        assert [dt.hour for dt, _ in points] == [h for h in range(24) if h != 5]
        assert points[5] == (datetime(2026, 1, 1, 6, tzinfo=JST), pytest.approx(feet(154)))

    def test_a_day_the_gauge_has_only_begun_gives_the_hours_it_has(self):
        # as the preliminary file has the day still running
        line = hours_only(GAUGE_JAN_1)[:33] + " " * 39 + "26 1 1TK"
        points = jma.parse_hourly([line])
        assert [dt.hour for dt, _ in points] == list(range(11))
        assert jma.parse_hourly([" " * 72 + "26 1 1TK"]) == []

    def test_a_line_with_only_its_hours_has_no_high_or_low(self):
        assert len(jma.parse_hourly([hours_only(JAN_1)])) == 24
        assert jma.parse_hilo([hours_only(JAN_1)]) == []

    def test_a_line_that_stops_after_two_highs_gives_those_two(self):
        events = jma.parse_hilo([JAN_1[:94]])
        assert [(dt.strftime("%H:%M"), kind) for dt, _, kind in events] == [
            ("04:08", "H"), ("14:15", "H")]

    @pytest.mark.parametrize("cut", [85, 86, 92, 93, 113, 114])
    def test_a_line_cut_inside_a_height_does_not_read_a_smaller_one(self, cut):
        whole = {(dt, cm) for dt, cm, _kind in jma.parse_hilo([JAN_1])}
        assert {(dt, cm) for dt, cm, _kind in jma.parse_hilo([JAN_1[:cut]])} <= whole

    @pytest.mark.parametrize("line", [
        "",
        JAN_1[:40],                                   # cut off before the date
        " " * 136,
        JAN_1.replace("26 1 1TK", "26 230TK"),        # 30 February
        JAN_1.replace("26 1 1TK", "2613 1TK"),        # a thirteenth month
        "<html><head><title>503 Service Unavailable</title></head>" + "<p>" * 30,
    ])
    def test_a_line_without_a_date_is_passed_over(self, line):
        assert jma.parse_hourly([line, JAN_2]) == jma.parse_hourly([JAN_2])
        assert jma.parse_hilo([line, JAN_2]) == jma.parse_hilo([JAN_2])

    def test_no_lines_are_no_points(self):
        assert jma.parse_hourly([]) == []
        assert jma.parse_hilo([]) == []


class TestRanges:
    """Days asked for come back whole, on Japan's clock, from as many
    yearly tables as they touch."""

    def test_a_day_is_its_24_hours_from_midnight_in_japan(self, tokyo_2026):
        points = jma.fetch_tides_range_jma(TOKYO, date(2026, 2, 1), date(2026, 2, 1))
        assert len(points) == 24
        assert points[0] == (datetime(2026, 2, 1, 0, tzinfo=JST), pytest.approx(feet(18)))
        assert points[-1] == (datetime(2026, 2, 1, 23, tzinfo=JST), pytest.approx(feet(-10)))

    def test_only_the_days_asked_for_come_back(self, tokyo_2026):
        points = jma.fetch_tides_range_jma(TOKYO, date(2026, 1, 2), date(2026, 1, 2))
        assert {dt.date() for dt, _ in points} == {date(2026, 1, 2)}
        events = jma.fetch_hilo_range_jma(TOKYO, date(2026, 1, 2), date(2026, 1, 3))
        assert [dt.day for dt, _, _ in events] == [2] * 4 + [3] * 4

    def test_a_range_over_a_month_end_has_both_days(self, tokyo_2026):
        points = jma.fetch_tides_range_jma(TOKYO, date(2026, 1, 31), date(2026, 2, 1))
        assert [dt for dt, _ in points] == [
            datetime(2026, 1, 31, tzinfo=JST) + timedelta(hours=h) for h in range(48)]
        # 23h on the 31st, then midnight on the 1st
        assert [h for _, h in points[23:25]] == pytest.approx([feet(-2), feet(18)])
        events = jma.fetch_hilo_range_jma(TOKYO, date(2026, 1, 31), date(2026, 2, 1))
        assert [(dt.month, dt.day) for dt, _, _ in events] == [(1, 31)] * 4 + [(2, 1)] * 4
        assert tokyo_2026.asked == [table_url(2026)]

    def test_a_range_over_new_year_asks_for_two_tables(self, tokyo_2026):
        tokyo_2026.files[table_url(2027)] = [JAN_1_2027]
        points = jma.fetch_tides_range_jma(TOKYO, date(2026, 12, 31), date(2027, 1, 1))
        assert tokyo_2026.asked == [table_url(2026), table_url(2027)]
        assert [dt for dt, _ in points] == [
            datetime(2026, 12, 31, tzinfo=JST) + timedelta(hours=h) for h in range(48)]
        assert [h for _, h in points[23:25]] == pytest.approx([feet(127), feet(119)])

    def test_the_highs_and_lows_over_new_year_run_on_in_order(self, tokyo_2026):
        tokyo_2026.files[table_url(2027)] = [JAN_1_2027]
        events = jma.fetch_hilo_range_jma(TOKYO, date(2026, 12, 31), date(2027, 1, 1))
        assert [(dt.strftime("%y %H:%M"), kind) for dt, _, kind in events] == [
            ("26 03:33", "L"), ("26 09:57", "H"), ("26 17:00", "L"), ("26 23:01", "H"),
            ("27 03:30", "L"), ("27 10:10", "H"), ("27 16:50", "L"), ("27 23:30", "H")]

    def test_new_year_with_next_years_table_not_out_is_the_old_year_alone(self, tokyo_2026):
        points = jma.fetch_tides_range_jma(TOKYO, date(2026, 12, 31), date(2027, 1, 1))
        assert {dt.date() for dt, _ in points} == {date(2026, 12, 31)}
        assert len(points) == 24

    def test_the_stations_zone_is_not_needed(self, tokyo_2026):
        new_york = ZoneInfo("America/New_York")
        days = (date(2026, 1, 1), date(2026, 1, 2))
        points = jma.fetch_tides_range_jma(TOKYO, *days, new_york)
        assert points == jma.fetch_tides_range_jma(TOKYO, *days)
        assert {dt.utcoffset() for dt, _ in points} == {timedelta(hours=9)}
        events = jma.fetch_hilo_range_jma(TOKYO, *days, new_york)
        assert events == jma.fetch_hilo_range_jma(TOKYO, *days)
        assert {dt.utcoffset() for dt, _, _ in events} == {timedelta(hours=9)}

    def test_the_id_is_read_in_any_case(self, tokyo_2026):
        assert len(jma.fetch_tides_range_jma("JMA:tk", date(2026, 1, 1), date(2026, 1, 1))) == 24
        assert tokyo_2026.asked == [table_url(2026)]

    def test_a_station_that_is_not_jmas_is_not_asked_for(self, agency):
        for station in ("jma:XX", "8418150", "TK", ""):
            assert jma.fetch_tides_range_jma(station, date(2026, 1, 1), date(2026, 1, 2)) == []
            assert jma.fetch_hilo_range_jma(station, date(2026, 1, 1), date(2026, 1, 2)) == []
        assert agency.asked == []

    def test_years_before_the_first_table_are_not_asked_for(self, agency):
        assert jma.fetch_tides_range_jma(TOKYO, date(2010, 6, 1), date(2010, 6, 2)) == []
        assert agency.asked == []
        jma.fetch_hilo_range_jma(TOKYO, date(2010, 12, 31), date(2011, 1, 1))
        assert agency.asked == [table_url(2011)]


class _October2026(datetime):
    """The module's clock, stopped at noon on 1 October 2026."""

    @classmethod
    def now(cls, tz=None):
        return datetime(2026, 10, 1, 12, tzinfo=tz)


class TestFetching:
    """A year's table is one file, kept once fetched; what goes wrong on
    the way is nothing to show, reported as the other sources report
    theirs."""

    JAN_1 = (date(2026, 1, 1), date(2026, 1, 1))

    def test_a_cached_table_is_used_without_a_fetch(self, tokyo_2026):
        first = jma.fetch_tides_range_jma(TOKYO, *self.JAN_1)
        assert jma.fetch_tides_range_jma(TOKYO, *self.JAN_1) == first
        # the highs and lows are in the same table
        assert len(jma.fetch_hilo_range_jma(TOKYO, *self.JAN_1)) == 4
        assert tokyo_2026.asked == [table_url(2026)]

    def test_a_table_is_kept_by_station_and_year(self, tokyo_2026):
        tokyo_2026.files[table_url(2026, "OS")] = [JAN_1.replace("TK", "OS")]
        jma.fetch_tides_range_jma(TOKYO, *self.JAN_1)
        jma.fetch_tides_range_jma("jma:OS", *self.JAN_1)
        assert tokyo_2026.asked == [table_url(2026), table_url(2026, "OS")]

    def test_a_past_years_table_is_kept_a_month_and_a_newer_one_a_day(self, cache, tokyo_2026):
        years = (date(2025, 12, 31), date(2027, 1, 1))
        with patch.object(jma, "datetime", _October2026):
            jma.fetch_tides_range_jma(TOKYO, *years)
            assert tokyo_2026.asked == [table_url(y) for y in (2025, 2026, 2027)]
            _age(cache, days=2)
            jma.fetch_tides_range_jma(TOKYO, *years)
            # this year's and next year's may be revised; last year's cannot
            assert tokyo_2026.asked[3:] == [table_url(2026), table_url(2027)]
            _age(cache, days=31)
            jma.fetch_tides_range_jma(TOKYO, *years)
            assert tokyo_2026.asked[5:] == [table_url(y) for y in (2025, 2026, 2027)]

    def test_a_year_not_published_yet_is_an_answer_and_is_kept(self, agency):
        days = (date(2027, 1, 1), date(2027, 1, 2))
        with patch("linecast._http.log_failure") as logged:
            assert jma.fetch_tides_range_jma(TOKYO, *days) == []
            assert jma.fetch_hilo_range_jma(TOKYO, *days) == []
        # one 404, and no asking again while that answer is fresh
        assert agency.asked == [table_url(2027)]
        logged.assert_not_called()

    @pytest.mark.parametrize("failure", [
        OSError("timed out"),
        HTTPError(table_url(2026), 503, "Service Unavailable"),
    ])
    def test_a_failed_fetch_is_no_points_and_is_reported(self, agency, failure):
        agency.files[table_url(2026)] = failure
        with patch("linecast._http.log_failure") as logged:
            assert jma.fetch_tides_range_jma(TOKYO, *self.JAN_1) == []
        logged.assert_called_once()
        assert logged.call_args.args == ("tides/jma", "fetch", failure)
        assert logged.call_args.kwargs == {"url": table_url(2026), "fallback": "fallback value"}

    def test_a_failure_is_not_kept_as_the_years_table(self, agency):
        agency.files[table_url(2026)] = OSError("timed out")
        assert jma.fetch_hilo_range_jma(TOKYO, *self.JAN_1) == []
        agency.files[table_url(2026)] = [JAN_1]
        assert len(jma.fetch_hilo_range_jma(TOKYO, *self.JAN_1)) == 4
        assert agency.asked == [table_url(2026)] * 2

    def test_an_answer_that_is_not_a_table_is_a_failed_fetch_and_is_not_kept(self, cache,
                                                                              agency):
        page = (b"<html><head><title>Maintenance</title></head><body>"
                + b"<p>The service is down for maintenance.</p>" * 3 + b"</body></html>\n")
        agency.files[table_url(2026)] = page
        with patch("linecast._http.log_failure") as logged:
            assert jma.fetch_tides_range_jma(TOKYO, *self.JAN_1) == []
        assert logged.call_args.args[:2] == ("tides/jma", "parse")
        assert not list(cache.glob("jma_pred_*"))
        # so the table is asked for again, and read, once the service is back
        agency.files[table_url(2026)] = [JAN_1]
        assert len(jma.fetch_tides_range_jma(TOKYO, *self.JAN_1)) == 24

    def test_a_failed_fetch_leaves_the_last_table_standing(self, cache, tokyo_2026):
        fetched = jma.fetch_tides_range_jma(TOKYO, *self.JAN_1)
        _age(cache, days=40)
        tokyo_2026.files[table_url(2026)] = OSError("no route to host")
        with patch("linecast._http.log_failure") as logged:
            assert jma.fetch_tides_range_jma(TOKYO, *self.JAN_1) == fetched
        assert len(fetched) == 24
        assert logged.call_args.kwargs["fallback"].startswith("stale cache ")
        # and the old copy is not written over as if it were new
        assert all(time.time() - path.stat().st_mtime > 39 * 86400 for path in cache.iterdir())

    def test_a_line_cut_short_on_the_way_is_dropped(self, agency):
        agency.files[table_url(2026)] = (JAN_1 + "\n" + JAN_2[:60]).encode("ascii")
        points = jma.fetch_tides_range_jma(TOKYO, date(2026, 1, 1), date(2026, 1, 2))
        assert [dt for dt, _ in points] == [datetime(2026, 1, 1, h, tzinfo=JST)
                                            for h in range(24)]

    @pytest.mark.parametrize("body", [
        b"",
        b"\n\n",
        b"<html><head><title>Maintenance</title></head><body>" + b"<p>back soon</p>" * 12
        + b"</body></html>\n",
        b"\xff\xfe\x00\x81" * 60,
    ])
    def test_an_answer_that_is_no_table_is_no_points(self, agency, body):
        agency.files[table_url(2026)] = body
        assert jma.fetch_tides_range_jma(TOKYO, date(2026, 1, 1), date(2026, 12, 31)) == []
        assert jma.fetch_hilo_range_jma(TOKYO, date(2026, 1, 1), date(2026, 12, 31)) == []

    def test_a_table_for_another_year_has_none_of_the_days_asked_for(self, agency):
        agency.files[table_url(2026)] = [JAN_1.replace("26 1 1TK", "25 1 1TK")]
        assert jma.fetch_tides_range_jma(TOKYO, date(2026, 1, 1), date(2026, 12, 31)) == []
        assert jma.fetch_hilo_range_jma(TOKYO, date(2026, 1, 1), date(2026, 12, 31)) == []


class TestYRange:
    """The y-axis range: the lowest low and the highest high of the
    months either side, measured once a month."""

    def test_it_spans_the_highs_and_lows(self, tokyo_2026):
        tokyo_2026.files[table_url(2026)] = [JAN_1, JAN_2, JAN_3]
        lo, hi = jma.fetch_y_range_jma(TOKYO, date(2026, 1, 2))
        # the low of -19 and the high of 190, both on the 3rd
        assert lo == pytest.approx(feet(-19))
        assert hi == pytest.approx(feet(190))

    def test_the_months_either_side_are_read_across_new_year(self, tokyo_2026):
        tokyo_2026.files[table_url(2027)] = [JAN_1_2027]
        lo, hi = jma.fetch_y_range_jma(TOKYO, date(2026, 12, 15))
        assert tokyo_2026.asked == [table_url(2026), table_url(2027)]
        # November to January: the low of 22 on 30 September is outside
        assert lo == pytest.approx(feet(73))
        assert hi == pytest.approx(feet(168))

    def test_every_day_of_a_month_shares_one_kept_range(self, cache, tokyo_2026):
        first = jma.fetch_y_range_jma(TOKYO, date(2026, 1, 2))
        assert jma.fetch_y_range_jma(TOKYO, date(2026, 1, 28)) == pytest.approx(first)
        assert [p.name for p in cache.glob("*yrange*")] == ["jma_yrange_TK_202601.json"]

    def test_a_kept_range_is_returned_as_it_is(self, agency):
        with patch.object(common, "read_cache", return_value={"min": -0.5, "max": 6.0}):
            assert jma.fetch_y_range_jma(TOKYO, date(2026, 1, 2)) == (-0.5, 6.0)
        assert agency.asked == []

    def test_no_table_is_no_range_and_nothing_is_kept(self, cache, agency):
        assert jma.fetch_y_range_jma(TOKYO, date(2026, 1, 2)) is None
        assert list(cache.glob("*yrange*")) == []

    def test_a_station_that_is_not_jmas_has_no_range(self, agency):
        assert jma.fetch_y_range_jma("jma:XX", date(2026, 1, 2)) is None
        assert jma.fetch_y_range_jma("8418150", date(2026, 1, 2)) is None
        assert agency.asked == []


class TestStationIds:
    """An ID is "jma:" and a station's two-character code."""

    @pytest.mark.parametrize("text", ["jma:TK", "JMA:TK", "jma:tk", "Jma:Tk", "jma:A0", "jma:q0"])
    def test_the_prefix_and_a_code_in_any_case_is_an_id(self, text):
        assert jma.is_jma_station_id(text)

    @pytest.mark.parametrize("text", [
        "",
        "jma",
        "jma:",
        "TK",                    # a code without the prefix
        "jma:XX",                # no such station
        "jma:T",
        "jma:TKO",
        "jma-TK",
        "jma:Tokyo",
        "jma:東京",
        "Tokyo",
        "東京",
        "8418150",               # NOAA
        "CCH",                   # the Hong Kong Observatory
        "om:35.6500,139.7667",   # Open-Meteo
        "kv:59.9000,10.7000",    # Kartverket
        "ticon:tokyo",
    ])
    def test_nothing_else_is(self, text):
        assert not jma.is_jma_station_id(text)

    def test_the_code_is_read_out_in_capitals(self):
        assert jma.station_code("jma:TK") == "TK"
        assert jma.station_code("JMA:tk") == "TK"
        assert jma.station_code("jma:XX") is None
        assert jma.station_code("TK") is None


class TestStationList:
    """The list baked into the module holds together."""

    def test_every_code_is_two_characters_and_belongs_to_one_station(self):
        codes = [s["id"] for s in jma.STATIONS]
        assert all(len(code) == 2 and code.isalnum() and code == code.upper()
                   for code in codes)
        assert len(set(codes)) == len(codes)
        assert all(jma.is_jma_station_id(f"jma:{code}") for code in codes)

    def test_every_station_has_a_japanese_name_and_a_romanized_one(self):
        for s in jma.STATIONS:
            assert s["name"] and s["name"].isascii(), s
            assert s["name_ja"] and not s["name_ja"].isascii(), s
        # two stations may be romanized alike (Sakai, Kure, Esashi); no
        # two are written alike
        assert len({s["name_ja"] for s in jma.STATIONS}) == len(jma.STATIONS)

    def test_every_station_is_in_japans_waters(self):
        # Yonaguni in the west to Minamitorishima in the east
        for s in jma.STATIONS:
            assert 20 < s["lat"] < 46 and 122 < s["lng"] < 154, s

    def test_every_gauge_is_a_station(self):
        assert jma.GAUGES <= set(jma.STATION_BY_CODE)


class TestNames:
    """A reader in Japanese sees the Japanese name, everyone else the
    romanized one."""

    def test_the_name_follows_the_readers_language(self, monkeypatch):
        tokyo = jma.STATION_BY_CODE["TK"]
        assert jma.display_name(tokyo) == "Tokyo"
        _reader_of(monkeypatch, "ja")
        assert jma.display_name(tokyo) == "東京"
        _reader_of(monkeypatch, "fr")
        assert jma.display_name(tokyo) == "Tokyo"

    def test_metadata_is_in_the_shape_the_pipeline_reads(self):
        meta = jma.fetch_station_metadata_jma("JMA:tk")
        assert meta["id"] == "jma:TK"
        assert meta["name"] == "Tokyo"
        assert (meta["lat"], meta["lng"]) == (35.65, 139.7667)
        assert meta["source"] == "jma"
        assert meta["state"] == "JP"

    def test_metadata_puts_the_station_on_japans_clock(self):
        meta = jma.fetch_station_metadata_jma("jma:NH")
        assert meta["timeZoneCode"] == "Asia/Tokyo"
        assert meta["timezone_abbr"] == "JST"
        assert meta["timezonecorr"] == 9
        assert meta["observedst"] is False

    def test_metadata_names_the_station_in_japanese_for_a_reader_in_japanese(self, monkeypatch):
        _reader_of(monkeypatch, "ja")
        assert jma.fetch_station_metadata_jma("jma:NH")["name"] == "那覇"

    def test_a_station_that_is_not_jmas_has_no_metadata(self):
        assert jma.fetch_station_metadata_jma("jma:XX") is None
        assert jma.fetch_station_metadata_jma("8418150") is None


class TestNearest:
    """The closest station within 100 nautical miles, from the list in
    the module: no fetch."""

    def test_a_point_in_tokyo_finds_the_tokyo_station(self, agency):
        # Tokyo Station, two miles north of where the list puts the gauge
        assert jma.find_nearest_station_jma(35.681, 139.767) == ("jma:TK", "Tokyo")
        assert agency.asked == []

    def test_a_point_far_from_japan_finds_none(self):
        assert jma.find_nearest_station_jma(43.68, -70.36) == (None, None)   # Maine
        assert jma.find_nearest_station_jma(37.57, 126.98) == (None, None)   # Seoul
        assert jma.find_nearest_station_jma(-90.0, 0.0) == (None, None)

    def test_the_reach_is_a_hundred_nautical_miles(self):
        # Minamitorishima has no neighbour for a thousand kilometres, and
        # a minute of latitude is a nautical mile
        lat, lng = 24.2833, 153.9833
        assert jma.find_nearest_station_jma(lat + 90 / 60, lng) == ("jma:MC", "Minamitorishima")
        assert jma.find_nearest_station_jma(lat + 110 / 60, lng) == (None, None)

    def test_a_reader_in_japanese_gets_the_japanese_name(self, monkeypatch):
        _reader_of(monkeypatch, "ja")
        assert jma.find_nearest_station_jma(35.681, 139.767) == ("jma:TK", "東京")

    def test_a_kept_pick_is_named_afresh_when_the_language_changes(self, cache, monkeypatch):
        assert jma.find_nearest_station_jma(35.681, 139.767) == ("jma:TK", "Tokyo")
        assert list(cache.iterdir())   # the pick is kept
        _reader_of(monkeypatch, "ja")
        assert jma.find_nearest_station_jma(35.681, 139.767) == ("jma:TK", "東京")
        _reader_of(monkeypatch, "en")
        assert jma.find_nearest_station_jma(35.681, 139.767) == ("jma:TK", "Tokyo")


def _in_cm(ranges):
    return {day: (lo * 30.48, hi * 30.48) for day, (lo, hi) in ranges.items()}


class TestWhatTheGaugeMeasured:
    """The water JMA's own gauges measured, day by day, moved from the
    gauge's datum onto the tide table's.

    Tokyo's gauge sits 74 cm off the table (GAUGE_TO_TABLE_CM), so the
    low of 66 cm it recorded on 1 January is 8 cm below the table's
    datum and the high of 240 is 166 above it.
    """

    @pytest.fixture
    def january(self, agency):
        """January 2026 over and settled: the table, the gauge's final
        file and the month's deviations."""
        agency.files[table_url(2026)] = [JAN_1, JAN_2, JAN_3, FEB_1]
        agency.files[final_url("hry", "202601")] = [GAUGE_JAN_1, GAUGE_JAN_2, GAUGE_JAN_3]
        agency.files[final_url("dep", "202601")] = list(DEVIATIONS_JAN)
        return agency

    @pytest.fixture
    def january_running(self, agency):
        """January 2026 still running: the preliminary files, which have
        the hours and no highs or lows.  Made from the final ones."""
        agency.files[table_url(2026)] = [JAN_1, JAN_2, JAN_3]
        agency.files[preliminary_url("hry", "202601")] = [
            hours_only(GAUGE_JAN_1), hours_only(GAUGE_JAN_2), hours_only(GAUGE_JAN_3)]
        agency.files[preliminary_url("dep", "202601")] = list(DEVIATIONS_JAN)
        return agency

    def test_a_days_lowest_and_highest_are_put_on_the_tables_datum(self, january):
        days = _in_cm(jma.fetch_observed_extremes_jma(TOKYO, 2026, date(2026, 3, 15)))
        assert sorted(days) == [date(2026, 1, 1), date(2026, 1, 2), date(2026, 1, 3)]
        # the gauge's lowest low and highest high each day, less 74
        assert days[date(2026, 1, 1)] == pytest.approx((66 - 74, 240 - 74))
        assert days[date(2026, 1, 2)] == pytest.approx((45 - 74, 254 - 74))
        assert days[date(2026, 1, 3)] == pytest.approx((43 - 74, 257 - 74))

    def test_the_heights_are_feet(self, january):
        days = jma.fetch_observed_extremes_jma(TOKYO, 2026, date(2026, 3, 15))
        lo, hi = days[date(2026, 1, 1)]
        assert lo == pytest.approx(-8 / 30.48)
        assert hi == pytest.approx(166 / 30.48)

    def test_which_file_is_asked_for_follows_how_long_ago_the_month_ended(self, january):
        jma.fetch_observed_extremes_jma(TOKYO, 2026, date(2026, 3, 15))
        asked = [url for url in january.asked if "hry" in url]
        assert asked == [
            final_url("hry", "202601"),         # long over: the final file
            final_url("hry", "202602"),         # just over: the final file if it is out,
            preliminary_url("hry", "202602"),   # and the preliminary one until then
            preliminary_url("hry", "202603"),   # still running: preliminary alone
        ]

    def test_the_deviations_are_asked_for_once(self, january):
        january.files[final_url("hry", "202602")] = [GAUGE_FEB_1]
        january.files[final_url("dep", "202602")] = list(DEVIATIONS_FEB)
        days = jma.fetch_observed_extremes_jma(TOKYO, 2026, date(2026, 6, 1))
        assert date(2026, 2, 1) in days
        # one month's give the datum, which does for the year
        assert [url for url in january.asked if "dep" in url] == [final_url("dep", "202601")]

    def test_a_second_asking_fetches_nothing(self, january):
        first = jma.fetch_observed_extremes_jma(TOKYO, 2026, date(2026, 3, 15))
        asked = list(january.asked)
        assert jma.fetch_observed_extremes_jma(TOKYO, 2026, date(2026, 3, 15)) == first
        # the months with no file yet were answers too, and are kept
        assert january.asked == asked

    def test_a_running_month_is_measured_from_its_hours(self, january_running):
        days = _in_cm(jma.fetch_observed_extremes_jma(TOKYO, 2026, date(2026, 1, 4)))
        assert sorted(days) == [date(2026, 1, 1), date(2026, 1, 2), date(2026, 1, 3)]
        # within a centimetre of the highs and lows the final file gave
        # for the same days, which fell between the hours
        assert days[date(2026, 1, 1)] == pytest.approx((66 - 74, 240 - 74), abs=1)
        assert days[date(2026, 1, 2)] == pytest.approx((45 - 74, 254 - 74), abs=1)
        assert days[date(2026, 1, 3)] == pytest.approx((43 - 74, 257 - 74), abs=1)
        assert [url for url in january_running.asked if "hry" in url] == [
            preliminary_url("hry", "202601")]

    def test_only_the_days_before_today_are_given(self, january_running):
        days = jma.fetch_observed_extremes_jma(TOKYO, 2026, date(2026, 1, 3))
        assert sorted(days) == [date(2026, 1, 1), date(2026, 1, 2)]

    def test_a_day_with_an_hour_missing_is_left_out(self, january_running):
        day_2 = hours_only(GAUGE_JAN_2)
        january_running.files[preliminary_url("hry", "202601")] = [
            hours_only(GAUGE_JAN_1), day_2[:30] + "   " + day_2[33:], hours_only(GAUGE_JAN_3)]
        days = _in_cm(jma.fetch_observed_extremes_jma(TOKYO, 2026, date(2026, 1, 4)))
        assert sorted(days) == [date(2026, 1, 1), date(2026, 1, 3)]
        # and the days either side are measured as they were
        assert days[date(2026, 1, 1)] == pytest.approx((66 - 74, 240 - 74), abs=1)
        assert days[date(2026, 1, 3)] == pytest.approx((43 - 74, 257 - 74), abs=1)

    def test_a_final_day_without_its_turns_is_measured_from_its_hours(self, january):
        january.files[final_url("hry", "202601")] = [
            GAUGE_JAN_1, without_turns(GAUGE_JAN_2), GAUGE_JAN_3]
        days = _in_cm(jma.fetch_observed_extremes_jma(TOKYO, 2026, date(2026, 3, 15)))
        assert days[date(2026, 1, 1)] == pytest.approx((66 - 74, 240 - 74))
        assert days[date(2026, 1, 2)] == pytest.approx((45 - 74, 254 - 74), abs=1)

    def test_a_final_day_missing_some_turns_still_spans_its_water(self, january):
        # the gauge caught the day's highs and missed its lows: the
        # hours on either side of each low stand in for it
        no_lows = GAUGE_JAN_1[:108] + " " * 28
        january.files[final_url("hry", "202601")] = [no_lows, GAUGE_JAN_2, GAUGE_JAN_3]
        days = _in_cm(jma.fetch_observed_extremes_jma(TOKYO, 2026, date(2026, 3, 15)))
        low, high = days[date(2026, 1, 1)]
        assert high == pytest.approx(240 - 74)
        assert low == pytest.approx(66 - 74, abs=4)

    def test_a_final_day_with_hours_missing_and_no_low_is_left_out(self, january):
        # nothing to say how far the water fell: no range is better than
        # one narrower than the water's
        line = GAUGE_JAN_1[:15] + "   " + GAUGE_JAN_1[18:108] + " " * 28
        january.files[final_url("hry", "202601")] = [line, GAUGE_JAN_2, GAUGE_JAN_3]
        days = _in_cm(jma.fetch_observed_extremes_jma(TOKYO, 2026, date(2026, 3, 15)))
        assert sorted(days) == [date(2026, 1, 2), date(2026, 1, 3)]

    def test_a_month_the_gauge_was_down_is_passed_over(self, january):
        blank = [" " * 72 + f"26 1{day:2d}TK" + " " * 56 for day in (1, 2, 3)]
        january.files[final_url("hry", "202601")] = blank
        january.files[final_url("hry", "202602")] = [GAUGE_FEB_1]
        january.files[final_url("dep", "202602")] = list(DEVIATIONS_FEB)
        days = _in_cm(jma.fetch_observed_extremes_jma(TOKYO, 2026, date(2026, 4, 10)))
        # February gives the datum, and its day is the only one measured
        assert sorted(days) == [date(2026, 2, 1)]
        assert days[date(2026, 2, 1)] == pytest.approx((56 - 74, 258 - 74))
        assert [url for url in january.asked if "dep" in url] == [final_url("dep", "202602")]

    def test_without_the_deviations_there_is_no_datum_and_nothing_is_given(self, january):
        del january.files[final_url("dep", "202601")]
        assert jma.fetch_observed_extremes_jma(TOKYO, 2026, date(2026, 3, 15)) == {}

    def test_without_the_years_table_nothing_is_given(self, january):
        del january.files[table_url(2026)]
        assert jma.fetch_observed_extremes_jma(TOKYO, 2026, date(2026, 3, 15)) == {}
        assert january.asked == [table_url(2026)]

    def test_a_year_with_no_day_before_today_is_empty(self, january):
        assert jma.fetch_observed_extremes_jma(TOKYO, 2026, date(2026, 1, 1)) == {}
        assert jma.fetch_observed_extremes_jma(TOKYO, 2027, date(2026, 3, 15)) == {}
        assert january.asked == []

    def test_a_station_jma_does_not_measure_at_is_empty(self, agency):
        # Yokohama has a tide table and no JMA gauge
        assert "QS" in jma.STATION_BY_CODE and "QS" not in jma.GAUGES
        assert jma.fetch_observed_extremes_jma("jma:QS", 2026, date(2026, 3, 15)) == {}
        assert jma.fetch_observed_extremes_jma("jma:XX", 2026, date(2026, 3, 15)) == {}
        assert jma.fetch_observed_extremes_jma("8418150", 2026, date(2026, 3, 15)) == {}
        assert agency.asked == []


# ---------------------------------------------------------------------------
# scripts/build_jma_tide_stations.py
# ---------------------------------------------------------------------------
BUILD_SCRIPT = Path(__file__).parent.parent / "scripts" / "build_jma_tide_stations.py"


@pytest.fixture(scope="module")
def build():
    """The build script as a module. The sdist leaves scripts/ out."""
    if not BUILD_SCRIPT.exists():
        pytest.skip("scripts/build_jma_tide_stations.py is not in this tree")
    spec = importlib.util.spec_from_file_location("build_jma_tide_stations", BUILD_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestBuildScript:
    """The pieces of the build script that turn JMA's pages into the
    module's table."""

    def test_degrees_and_minutes_become_the_tables_decimal_degrees(self, build):
        # Wakkanai, the first station in the list
        wakkanai = jma.STATION_BY_CODE["WN"]
        lat, lng = build.degrees("45゜24'"), build.degrees("141゜41'")
        assert f"{lat:.4f}" == f"{wakkanai['lat']:.4f}" == "45.4000"
        assert f"{lng:.4f}" == f"{wakkanai['lng']:.4f}" == "141.6833"

    def test_a_cell_that_is_no_position_is_none(self, build):
        assert build.degrees("") is None
        assert build.degrees("稚内") is None

    def test_a_station_row_is_its_cells_as_plain_text(self, build):
        page = """
            <table>
            <tr><th>番号</th><th>地点記号</th><th>地点名</th><th>緯度</th><th>経度</th></tr>
            <tr class="a"><td>1</td><td>WN</td><td><a href="suisan.php?stn=WN">稚内</a></td>
                <td>45゜24'</td><td> 141゜41'</td></tr>
            <tr><td colspan="5">北海道 &amp; 東北</td></tr>
            </table>"""
        assert build.rows(page) == [["1", "WN", "稚内", "45゜24'", "141゜41'"]]

    @pytest.mark.parametrize("heading, name", [
        ("潮位表 東京（TOKYO）", "Tokyo"),
        ("潮位表 苫小牧東（TOMAKOMAIHIGASHI）", "Tomakomaihigashi"),
        ("潮位表 三宅島（坪田）（MIYAKEJIMA(TSUBOTA)）", "Miyakejima (Tsubota)"),
    ])
    def test_the_headings_capitals_become_the_tables_name(self, build, heading, name):
        with patch.object(build, "fetch", return_value=f"<html><h1>{heading}</h1></html>"):
            assert build.romanized("XX") == name
        assert name in {s["name"] for s in jma.STATIONS}

    @pytest.mark.parametrize("page", [
        "<html><h1>潮位表 東京</h1></html>",
        "<html><h1>潮位表 三宅島（坪田）</h1></html>",   # the Japanese name's own parenthesis
        "<html><p>503</p></html>",
    ])
    def test_a_page_with_no_romanized_name_gives_none(self, build, page):
        with patch.object(build, "fetch", return_value=page):
            assert build.romanized("XX") is None
