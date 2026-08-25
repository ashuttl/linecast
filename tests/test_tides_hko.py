"""Tests for the Hong Kong Observatory tide data source.

The fixtures are rows cut from real HHOT and HLT responses for Cheung
Chau (CCH): three days in August 2026, the last day of 2026 and the
first two of 2027, so a range across New Year can be tested.
"""

import json
from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from linecast import _tides_hko as hko
from linecast._tides_common import M_TO_FT
from linecast._tides_hko import HKT

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name):
    return json.loads((FIXTURES / name).read_text())


def _fake_fetch_year(data_type, station_id, year):
    assert station_id == "CCH"
    try:
        return _load(f"hko_{data_type.lower()}_cch_{year}.json")["data"]
    except FileNotFoundError:
        return []


@pytest.fixture
def fixture_years():
    with patch.object(hko, "_fetch_year", side_effect=_fake_fetch_year) as f:
        yield f


class TestHHOT:
    def test_row_shape(self):
        data = _load("hko_hhot_cch_2026.json")
        assert data["fields"][:2] == ["MM", "DD"]
        assert data["fields"][2:] == [f"{h:02d}" for h in range(1, 25)]
        assert all(len(row) == 26 for row in data["data"])

    def test_hours_land_on_the_clock_and_24_rolls_over(self):
        rows = _load("hko_hhot_cch_2026.json")["data"]
        points = hko.parse_hhot_rows(rows[:1], 2026)
        assert len(points) == 24
        assert points[0] == (datetime(2026, 8, 24, 1, tzinfo=HKT), pytest.approx(1.63 * M_TO_FT))
        assert points[-1][0] == datetime(2026, 8, 25, 0, tzinfo=HKT)
        assert points[-1][1] == pytest.approx(1.46 * M_TO_FT)

    def test_bad_rows_are_skipped(self):
        rows = [["13", "01"] + ["1.0"] * 24, ["08", "24", "x"] + [""] * 23]
        assert hko.parse_hhot_rows(rows, 2026) == []


class TestHLT:
    def test_events_stop_at_the_first_empty_slot(self):
        rows = _load("hko_hlt_cch_2026.json")["data"]
        by_day = {}
        for dt, _ in hko.parse_hlt_rows(rows, 2026):
            by_day.setdefault(dt.date(), 0)
            by_day[dt.date()] += 1
        assert by_day == {date(2026, 8, 24): 2, date(2026, 8, 25): 3,
                          date(2026, 8, 26): 4, date(2026, 12, 31): 4}

    def test_times_are_hkt(self):
        rows = _load("hko_hlt_cch_2026.json")["data"]
        first = hko.parse_hlt_rows(rows, 2026)[0]
        assert first == (datetime(2026, 8, 24, 5, 38, tzinfo=HKT), pytest.approx(2.18 * M_TO_FT))


class TestRanges:
    def test_tides_range_is_the_days_asked_for(self, fixture_years):
        points = hko.fetch_tides_range_hko("CCH", date(2026, 8, 25), date(2026, 8, 25))
        # Midnight opening the day is the previous row's hour 24.
        assert len(points) == 24
        assert points[0][0] == datetime(2026, 8, 25, 0, tzinfo=HKT)
        assert points[-1][0] == datetime(2026, 8, 25, 23, tzinfo=HKT)
        assert fixture_years.call_args_list[0].args == ("HHOT", "CCH", 2026)

    def test_hilo_labels_alternate(self, fixture_years):
        # The 26th stays out of the range but in the table, so the last
        # event of the 25th has a neighbour to be judged against.
        hilo = hko.fetch_hilo_range_hko("CCH", date(2026, 8, 24), date(2026, 8, 25))
        assert [t for _, _, t in hilo] == ["H", "L", "H", "L", "H"]
        assert hilo[0][0] == datetime(2026, 8, 24, 5, 38, tzinfo=HKT)

    def test_range_across_new_year_joins_both_tables(self, fixture_years):
        hilo = hko.fetch_hilo_range_hko("CCH", date(2026, 12, 31), date(2027, 1, 1))
        years = [c.args[2] for c in fixture_years.call_args_list]
        assert years == [2026, 2027]
        assert [e[0].date() for e in hilo] == [date(2026, 12, 31)] * 4 + [date(2027, 1, 1)] * 4
        # The last low of the year and the first high of the next see each other.
        assert [t for _, _, t in hilo] == ["H", "L", "H", "L", "H", "L", "H", "L"]

    def test_missing_year_gives_nothing(self, fixture_years):
        assert hko.fetch_tides_range_hko("CCH", date(2030, 1, 1), date(2030, 1, 2)) == []


class TestStations:
    def test_codes_match_in_any_case(self):
        assert hko.is_hko_station_id("CCH")
        assert hko.is_hko_station_id("pt1")
        assert not hko.is_hko_station_id("8418150")
        assert not hko.is_hko_station_id("")

    def test_nearest_is_quarry_bay_from_central(self, tmp_path):
        with patch.object(hko, "cache_dir", return_value=tmp_path):
            assert hko.find_nearest_station_hko(22.28, 114.16) == ("QUB", "Quarry Bay")
            assert hko.find_nearest_station_hko(43.68, -70.36) == (None, None)

    def test_metadata_is_hkt(self):
        meta = hko.fetch_station_metadata_hko("cch")
        assert meta["id"] == "CCH"
        assert meta["timeZoneCode"] == "Asia/Hong_Kong"
        assert meta["source"] == "hko"
        assert hko.fetch_station_metadata_hko("XXX") is None


def test_year_cache_ages(tmp_path):
    seen = {}

    def fake_fetch(cache_file, max_age, url, **kw):
        seen[cache_file.name] = (max_age, url)
        return {"fields": [], "data": [["01", "01"]]}

    this_year = datetime.now(HKT).year
    with patch.object(hko, "cache_dir", return_value=tmp_path), \
         patch.object(hko, "fetch_json_cached", side_effect=fake_fetch):
        assert hko._fetch_year("HLT", "cch", this_year - 1) == [["01", "01"]]
        assert hko._fetch_year("HHOT", "CCH", this_year) == [["01", "01"]]
        assert hko._fetch_year("HHOT", "XXX", this_year) == []
    assert seen[f"hko_hlt_CCH_{this_year - 1}.json"][0] == 30 * 86400
    assert seen[f"hko_hhot_CCH_{this_year}.json"][0] == 86400
    assert "station=CCH" in seen[f"hko_hlt_CCH_{this_year - 1}.json"][1]
