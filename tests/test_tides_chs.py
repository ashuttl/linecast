import json
import math
import os
import time
import unittest
from collections import deque
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

import pytest

from linecast import _http
from linecast.tides import chs
from linecast.tides import common


class YRangeTests(unittest.TestCase):
    def test_cache_key_is_month_anchored_and_window_covers_30_days(self):
        seen = []

        def fake_read_cache(path, max_age):
            seen.append(path.name)
            return None

        data = [{"eventDate": "2026-08-01T05:00:00Z", "value": "3.0"},
                {"eventDate": "2026-08-01T11:00:00Z", "value": "0.5"}]
        with patch.object(common, "read_cache", side_effect=fake_read_cache), \
             patch.object(chs, "fetch_json", return_value=data) as fj, \
             patch.object(common, "write_cache"):
            for day in (date(2026, 8, 23), date(2026, 8, 24)):
                lo, hi = chs.fetch_y_range_chs("05320", day, None)

        self.assertAlmostEqual(lo, 0.5 * chs.M_TO_FT)
        self.assertAlmostEqual(hi, 3.0 * chs.M_TO_FT)
        self.assertEqual(seen, ["chs_yrange_05320_202608.json"] * 2)
        # July 1 through September 30, in UTC because no station tz was given
        self.assertIn("from=2026-07-01T00:00:00Z&to=2026-10-01T00:00:00Z",
                      fj.call_args.args[0])

    def test_returns_cached_y_range(self):
        with patch.object(common, "read_cache", return_value={"min": -0.5, "max": 3.0}):
            self.assertEqual(chs.fetch_y_range_chs("05320", date(2026, 3, 27), None),
                             (-0.5, 3.0))


class NearestStationTests(unittest.TestCase):
    STATIONS = [
        # a current station, nearer the place than any tide station
        {"id": "a" * 24, "officialName": "Second Narrows", "operating": True,
         "latitude": 49.2947, "longitude": -123.0245,
         "timeSeries": [{"code": "wcp1-events"}, {"code": "wcsp1"}]},
        {"id": "b" * 24, "officialName": "Vancouver", "operating": True,
         "latitude": 49.287, "longitude": -123.11,
         "timeSeries": [{"code": "wlo"}, {"code": "wlp"}, {"code": "wlp-hilo"}]},
    ]

    def test_a_station_with_no_water_levels_is_not_picked(self):
        with patch.object(chs, "fetch_all_stations_chs", return_value=self.STATIONS), \
             patch.object(common, "read_cache", return_value=None), \
             patch.object(common, "write_cache"):
            self.assertEqual(chs.find_nearest_station_chs(49.30, -123.02),
                             ("b" * 24, "Vancouver"))


class TestOffline:
    """With CHS out of reach (the tests have no network), an expired
    file's rows stand in for the answer: the file holds rows parsed from
    CHS's list, never the list."""

    ROWS = [{"dt": "2026-09-01T00:00:00+00:00", "v": 1.0, "t": "H"},
            {"dt": "2026-09-01T06:05:00+00:00", "v": 0.1, "t": "L"}]

    @pytest.fixture(autouse=True)
    def cache(self, tmp_path):
        with patch.dict(os.environ, {"LINECAST_CACHE_DIR": str(tmp_path)}):
            yield tmp_path

    def _expired(self, kind):
        path = common.cache_dir() / f"chs_{kind}_X_20260901_20260902.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.ROWS))
        then = time.time() - 3 * 86400
        os.utime(path, (then, then))
        return path

    def test_predictions_keep_the_last_rows(self):
        path = self._expired("pred")
        points = chs._fetch_pred_chunk("X", date(2026, 9, 1), date(2026, 9, 2), timezone.utc)
        assert points == [(datetime(2026, 9, 1, 0, 0, tzinfo=timezone.utc), 1.0),
                          (datetime(2026, 9, 1, 6, 5, tzinfo=timezone.utc), 0.1)]
        # and the stale copy is left as it was, not written over as fresh
        assert json.loads(path.read_text()) == self.ROWS
        assert time.time() - path.stat().st_mtime > 86400

    def test_extremes_keep_the_last_rows(self):
        path = self._expired("hilo")
        points = chs.fetch_hilo_range_chs("X", date(2026, 9, 1), date(2026, 9, 2), timezone.utc)
        assert points == [(datetime(2026, 9, 1, 0, 0, tzinfo=timezone.utc), 1.0, "H"),
                          (datetime(2026, 9, 1, 6, 5, tzinfo=timezone.utc), 0.1, "L")]
        assert json.loads(path.read_text()) == self.ROWS

    def test_nothing_cached_is_nothing(self):
        assert chs._fetch_pred_chunk("X", date(2026, 9, 1), date(2026, 9, 2), timezone.utc) == []


class TestFetchedAsCached:
    """A run that fetches reads its points back from the rows it keeps,
    as a run that finds them cached does: aware in a fixed offset, so a
    time past a change of clock is placed by the hours that have passed."""

    PAYLOAD = [{"eventDate": "2026-10-31T15:00:00Z", "value": "1.0"},
               {"eventDate": "2026-11-01T18:00:00Z", "value": "0.2"}]

    @pytest.fixture(autouse=True)
    def cache(self, tmp_path):
        with patch.dict(os.environ, {"LINECAST_CACHE_DIR": str(tmp_path)}):
            yield tmp_path

    @pytest.mark.parametrize("fetch", [chs._fetch_pred_chunk, chs.fetch_hilo_range_chs])
    def test_the_same_points_either_way(self, fetch):
        from zoneinfo import ZoneInfo
        from linecast import _http
        halifax = ZoneInfo("America/Halifax")
        args = ("X", date(2026, 10, 31), date(2026, 11, 1), halifax)
        with patch.object(_http, "fetch_json", return_value=self.PAYLOAD):
            fetched = fetch(*args)
        cached = fetch(*args)  # the network is off: this is the file
        assert fetched == cached
        # Halifax's clocks go back at 2am on 1 November: 27 hours pass
        start = datetime(2026, 10, 31, 12, 0, tzinfo=halifax)
        assert [(p[0] - start).total_seconds() / 3600 for p in fetched] == [0, 27]


STATION = "5cebf1e23d0f4a073c4bbfac"
WLO = "5cebf1e23d0f4a073c4bbfaa"      # the id of the station's wlo series
HALIFAX = ZoneInfo("America/Halifax")
FEET = 1 / 0.3048
# A quarter of an inch: more than a fifteen-minute sample can miss the
# top of the tide below by, and far less than a wrong day would be out
QUARTER_INCH = 0.02

# The tide the stand-in station predicts, in metres above chart datum:
# 1.8 m at high water and 0.2 m at low, 6 h 12 min apart.
A_HIGH_WATER = datetime(2025, 12, 31, 1, 7, tzinfo=timezone.utc)
HALF_TIDE = timedelta(minutes=372)


def _predicted(t):
    return 1.0 + 0.8 * math.cos(math.pi * ((t - A_HIGH_WATER) / HALF_TIDE))


def _weather(t):
    """What the gauge reads over the prediction: a surge of 30 cm that
    comes and goes over nine days, so no two days measure alike."""
    return 0.3 * math.sin(2 * math.pi * ((t - A_HIGH_WATER) / timedelta(days=9)))


def _measured(t):
    return _predicted(t) + _weather(t)


def _predicted_turns(lo, hi):
    """[(instant, metres)] of the stand-in tide's highs and lows in a span."""
    k = math.ceil((lo - A_HIGH_WATER) / HALF_TIDE)
    turns = []
    while A_HIGH_WATER + k * HALF_TIDE <= hi:
        turns.append((A_HIGH_WATER + k * HALF_TIDE, 0.2 if k % 2 else 1.8))
        k += 1
    return turns


def _between(turns):
    """A water level that swings smoothly from each of *turns* to the
    next, and stands at the first one's height before it."""
    def level(t):
        for (t1, h1), (t2, h2) in zip(turns, turns[1:]):
            if t1 <= t <= t2:
                return h1 + (h2 - h1) * (1 - math.cos(math.pi * ((t - t1) / (t2 - t1)))) / 2
        return turns[0][1]
    return level


def _at_the_turns(turns, level, first, last, zone):
    """{day: (lowest, highest)} in feet of *level* at the turns that fall
    on each of the zone's days from *first* through *last*."""
    days = {}
    for t, _metres in turns:
        day = t.astimezone(zone).date()
        if first <= day <= last:
            days.setdefault(day, []).append(level(t) * FEET)
    return {day: (min(heights), max(heights)) for day, heights in days.items()}


def _stamp(t):
    """An instant as IWLS writes it: UTC, to the second."""
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class _IWLS:
    """IWLS with one station in it: the station list, the station's
    metadata and holdings, its predicted turns, and what its gauge
    measured every fifteen minutes, each in the shape IWLS answers in.

    *level* gives the gauge's metres at an instant, or None where it
    sent nothing; *turns* stands in for the cosine tide above. The URLs
    asked are kept, and for the gauge's requests the clock's time too.
    """

    def __init__(self, level=_measured, turns=None, zone="America/Halifax",
                 series=("wlo", "wlp", "wlp-hilo"), clock=None):
        self.level, self.turns, self.zone, self.clock = level, turns, zone, clock
        self.station = {
            "id": STATION, "code": "00490", "officialName": "Halifax", "operating": True,
            "latitude": 44.666667, "longitude": -63.583333, "type": "PERMANENT",
            "timeSeries": [{"id": WLO if code == "wlo" else f"{n:024x}", "code": code,
                            "nameEn": code, "nameFr": code, "owner": "CHS-SHC"}
                           for n, code in enumerate(series)]}
        self.holdings = [{"timeSeriesId": WLO, "dataHoldings": [
            {"dateStart": "2019-09-01T00:00:00Z", "dateEnd": "2029-09-30T00:00:00Z"}]}]
        self.urls, self.asked_at = [], []
        self.fails = lambda url: False
        self.answers = lambda url: None

    def __call__(self, url, headers=None, timeout=10):
        self.urls.append(url)
        parts = urlsplit(url)
        query = {k: v[0] for k, v in parse_qs(parts.query).items()}
        code = query.get("time-series-code")
        if parts.path.endswith("/holdings") or code == "wlo":
            self.asked_at.append(self.clock.now if self.clock else None)
        if self.fails(url):
            raise OSError("IWLS did not answer")
        if self.answers(url) is not None:
            return self.answers(url)
        if parts.path.endswith("/stations"):
            return [self.station]
        if parts.path.endswith("/metadata"):
            return {"id": STATION, "code": "00490", "officialName": "Halifax",
                    "provinceCode": "NS", "latitude": 44.666667, "longitude": -63.583333,
                    "timeZoneCode": self.zone, "operating": True}
        if parts.path.endswith("/holdings"):
            return self.holdings
        lo, hi = (datetime.strptime(query[k], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                  for k in ("from", "to"))
        if code == "wlp-hilo":
            turns = (_predicted_turns(lo, hi) if self.turns is None
                     else [turn for turn in self.turns if lo <= turn[0] <= hi])
            return [{"eventDate": _stamp(t), "qcFlagCode": "2", "value": metres,
                     "timeSeriesId": "5d9dd7cf33a9f593161c4055"} for t, metres in turns]
        assert code == "wlo" and query["resolution"] == "FIFTEEN_MINUTES", url
        assert hi - lo <= timedelta(days=31), url
        rows, t = [], lo
        while t <= hi:
            metres = self.level(t)
            if metres is not None:
                rows.append({"eventDate": _stamp(t), "qcFlagCode": "1",
                             "value": round(metres, 3), "timeSeriesId": WLO})
            t += timedelta(minutes=15)
        return rows

    @property
    def months_asked(self):
        """(from, to) of each request for the gauge's levels, in order."""
        return [(url.split("from=")[1][:20], url.split("to=")[1][:20])
                for url in self.urls if "time-series-code=wlo" in url]

    @property
    def holdings_asked(self):
        return sum(url.endswith("/holdings") for url in self.urls)


class _Clock:
    """The clock the rate limit reads: a sleep moves it on and takes no time."""

    def __init__(self):
        self.now = 1000.0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


@pytest.fixture
def clock():
    """The module's clock held still, and no request remembered."""
    held = _Clock()
    with patch.object(chs, "time", held), patch.object(chs, "_obs_sent", deque()):
        yield held


@pytest.fixture
def iwls(tmp_path, clock):
    """A stand-in IWLS behind every fetch, and a cache of the test's own."""
    service = _IWLS(clock=clock)
    with patch.dict(os.environ, {"LINECAST_CACHE_DIR": str(tmp_path)}), \
         patch.object(_http, "fetch_json", side_effect=service), \
         patch.object(chs, "fetch_json", side_effect=service):
        yield service


def _aged(seconds):
    """Every file in the cache was written *seconds* ago."""
    for path in common.cache_dir().iterdir():
        then = time.time() - seconds
        os.utime(path, (then, then))


class TestObservedYear:
    """What the gauge measured in a year, as the lowest and highest
    water of each day: read a month at a time, and reckoned at the
    predicted turns of the tide."""

    TODAY = date(2026, 4, 10)
    FIRST, YESTERDAY = date(2026, 1, 1), date(2026, 4, 9)

    def _expected(self, first=FIRST, last=YESTERDAY, level=_measured):
        lo = datetime(first.year, 1, 1, tzinfo=HALIFAX)
        turns = _predicted_turns(lo, datetime(first.year + 1, 1, 1, tzinfo=HALIFAX))
        return _at_the_turns(turns, level, first, last, HALIFAX)

    def test_every_day_before_today_has_its_lowest_and_highest_in_feet(self, iwls):
        days = chs.fetch_observed_extremes_chs(STATION, 2026, self.TODAY)
        expected = self._expected()
        assert sorted(days) == sorted(expected)
        assert (min(days), max(days), len(days)) == (self.FIRST, self.YESTERDAY, 99)
        for day, (low, high) in expected.items():
            assert days[day] == pytest.approx((low, high), abs=QUARTER_INCH), day
        # feet above chart datum, as the predictions are: the gauge read
        # between about -0.1 m and 2.1 m
        assert -0.1 * FEET - QUARTER_INCH < min(low for low, _high in days.values())
        assert max(high for _low, high in days.values()) < 2.1 * FEET + QUARTER_INCH

    def test_the_gauge_is_asked_for_a_month_at_a_time_by_the_stations_own_days(self, iwls):
        chs.fetch_observed_extremes_chs(STATION, 2026, self.TODAY)
        # Halifax is four hours behind UTC until its clocks go forward
        # on 8 March, and three after; April stops at yesterday's end
        assert iwls.months_asked == [
            ("2026-01-01T04:00:00Z", "2026-02-01T04:00:00Z"),
            ("2026-02-01T04:00:00Z", "2026-03-01T04:00:00Z"),
            ("2026-03-01T04:00:00Z", "2026-04-01T03:00:00Z"),
            ("2026-04-01T03:00:00Z", "2026-04-10T03:00:00Z")]
        asked = [url for url in iwls.urls if "time-series-code=wlo" in url]
        assert all(f"/stations/{STATION}/data?" in url
                   and "resolution=FIFTEEN_MINUTES" in url for url in asked)
        assert iwls.holdings_asked == 1

    def test_the_requests_wait_their_turn_half_a_second_apart(self, iwls):
        chs.fetch_observed_extremes_chs(STATION, 2026, self.TODAY)
        assert len(iwls.asked_at) == 5      # the holdings and four months
        waits = [b - a for a, b in zip(iwls.asked_at, iwls.asked_at[1:])]
        assert waits == pytest.approx([0.5] * 4)

    def test_a_past_year_runs_to_its_last_day(self, iwls):
        days = chs.fetch_observed_extremes_chs(STATION, 2025, self.TODAY)
        assert (min(days), max(days), len(days)) == (date(2025, 1, 1), date(2025, 12, 31), 365)
        assert len(iwls.months_asked) == 12
        assert iwls.months_asked[-1] == ("2025-12-01T04:00:00Z", "2026-01-01T04:00:00Z")
        expected = self._expected(date(2025, 1, 1), date(2025, 12, 31))
        for day in (date(2025, 1, 1), date(2025, 7, 1), date(2025, 12, 31)):
            assert days[day] == pytest.approx(expected[day], abs=QUARTER_INCH)

    def test_a_year_with_no_day_behind_it_is_nothing_and_asks_nothing(self, iwls):
        assert chs.fetch_observed_extremes_chs(STATION, 2027, self.TODAY) == {}
        assert chs.fetch_observed_extremes_chs(STATION, 2026, date(2026, 1, 1)) == {}
        assert iwls.urls == []

    def test_a_station_without_a_gauge_is_nothing_and_no_levels_are_asked_for(self, tmp_path,
                                                                           clock):
        service = _IWLS(series=("wlp", "wlp-hilo"), clock=clock)
        with patch.dict(os.environ, {"LINECAST_CACHE_DIR": str(tmp_path)}), \
             patch.object(_http, "fetch_json", side_effect=service), \
             patch.object(chs, "fetch_json", side_effect=service):
            assert chs.fetch_observed_extremes_chs(STATION, 2026, self.TODAY) == {}
            # nor is a station the list does not have
            assert chs.fetch_observed_extremes_chs("0" * 24, 2026, self.TODAY) == {}
        assert [urlsplit(url).path.rsplit("/", 1)[-1] for url in service.urls] == ["stations"]

    def test_a_station_with_no_predicted_turns_is_nothing(self, iwls):
        iwls.turns = []
        assert chs.fetch_observed_extremes_chs(STATION, 2026, self.TODAY) == {}
        assert iwls.months_asked == []

    def test_a_station_naming_no_zone_is_read_in_utc_days(self, iwls):
        iwls.zone = ""
        days = chs.fetch_observed_extremes_chs(STATION, 2026, date(2026, 2, 3))
        assert iwls.months_asked == [("2026-01-01T00:00:00Z", "2026-02-01T00:00:00Z"),
                                     ("2026-02-01T00:00:00Z", "2026-02-03T00:00:00Z")]
        expected = _at_the_turns(
            _predicted_turns(datetime(2026, 1, 1, tzinfo=timezone.utc),
                             datetime(2026, 2, 3, tzinfo=timezone.utc)),
            _measured, date(2026, 1, 1), date(2026, 2, 2), timezone.utc)
        assert sorted(days) == sorted(expected)
        for day, pair in expected.items():
            assert days[day] == pytest.approx(pair, abs=QUARTER_INCH), day


class TestMeasuredAtTheTurns:
    """A day's range is the water at its predicted turns, not its plain
    highest and lowest samples; and a turn the gauge may have missed
    leaves its day out."""

    VANCOUVER = ZoneInfo("America/Vancouver")

    def _local(self, day, hour, minute, metres):
        return (datetime(2026, 1, day, hour, minute, tzinfo=self.VANCOUVER), metres)

    def test_a_high_water_near_midnight_is_not_read_into_the_day_after(self, iwls):
        # A mixed tide, the higher high water late in the evening. At
        # midnight opening the 2nd the water is still within inches of
        # the 4.8 m it reached at 23:30, a metre and a half over
        # anything the 2nd's own tides come to.
        turns = [self._local(*turn) for turn in (
            (1, 5, 0, 1.0), (1, 11, 0, 3.0), (1, 17, 0, 2.5), (1, 23, 30, 4.8),
            (2, 6, 0, 0.8), (2, 12, 0, 3.2), (2, 18, 0, 2.6),
            (3, 0, 15, 4.7), (3, 6, 45, 0.9), (3, 12, 45, 3.1), (3, 18, 45, 2.7),
            (4, 1, 0, 4.6))]
        iwls.turns, iwls.level, iwls.zone = turns, _between(turns), "America/Vancouver"
        assert _between(turns)(datetime(2026, 1, 2, tzinfo=self.VANCOUVER)) > 4.7
        days = chs.fetch_observed_extremes_chs(STATION, 2026, date(2026, 1, 4))
        assert sorted(days) == [date(2026, 1, 1), date(2026, 1, 2), date(2026, 1, 3)]
        for day, (low, high) in zip(sorted(days), ((1.0, 4.8), (0.8, 3.2), (0.9, 4.7))):
            assert days[day] == pytest.approx((low * FEET, high * FEET), abs=QUARTER_INCH), day

    def _with_samples_missing(self, iwls, count):
        """The year to 5 January with *count* samples running missing
        from the top of the first high water of the 3rd."""
        lo = datetime(2026, 1, 3, tzinfo=HALIFAX)
        high = next(t for t, metres in _predicted_turns(lo, lo + timedelta(days=1))
                    if metres > 1)
        first = datetime.fromtimestamp(high.timestamp() // 900 * 900, timezone.utc)
        missing = {first + timedelta(minutes=15 * i) for i in range(count)}
        iwls.level = lambda t: None if t in missing else _measured(t)
        return chs.fetch_observed_extremes_chs(STATION, 2026, date(2026, 1, 6)), high

    def test_a_sample_or_two_missing_cost_the_day_a_few_inches_at_most(self, iwls):
        days, high = self._with_samples_missing(iwls, 2)
        assert sorted(days) == [date(2026, 1, n) for n in range(1, 6)]
        assert days[date(2026, 1, 3)][1] == pytest.approx(_measured(high) * FEET, abs=0.25)

    def test_three_samples_missing_together_leave_the_day_out(self, iwls):
        days, _high = self._with_samples_missing(iwls, 3)
        assert sorted(days) == [date(2026, 1, n) for n in (1, 2, 4, 5)]

    def test_rows_that_cannot_be_read_are_samples_missing(self, iwls):
        lo = datetime(2026, 1, 3, tzinfo=HALIFAX)
        low_water = next(t for t, metres in _predicted_turns(lo, lo + timedelta(days=1))
                         if metres < 1)
        whole = iwls.__call__

        def spoiled(url, headers=None, timeout=10):
            rows = whole(url, headers, timeout)
            if "time-series-code=wlo" in url:
                for row in rows:
                    at = datetime.strptime(row["eventDate"], "%Y-%m-%dT%H:%M:%SZ")
                    if abs(at.replace(tzinfo=timezone.utc) - low_water) < timedelta(hours=1):
                        row["value"] = None
                rows += [{"eventDate": "not a time", "value": 99.0}, {"value": 99.0}, None]
            return rows

        with patch.object(chs, "fetch_json", side_effect=spoiled):
            days = chs.fetch_observed_extremes_chs(STATION, 2026, date(2026, 1, 6))
        assert sorted(days) == [date(2026, 1, n) for n in (1, 2, 4, 5)]
        assert max(high for _low, high in days.values()) < 2.2 * FEET


class TestHoldings:
    """The station's holdings say which months its gauge has anything
    for, and the months it was silent are not asked for."""

    TODAY = date(2026, 10, 1)

    def test_months_after_the_gauge_stopped_are_not_asked_for(self, iwls):
        # a gauge that stopped on 10 March 2025, as the holdings say
        stopped = datetime(2025, 3, 10, 12, tzinfo=timezone.utc)
        iwls.level = lambda t: _measured(t) if t <= stopped else None
        iwls.holdings = [
            {"timeSeriesId": "5cebf1e23d0f4a073c4bbfa8", "dataHoldings": [
                {"dateStart": "2017-12-15T00:00:00Z", "dateEnd": "2029-09-30T00:00:00Z"}]},
            {"timeSeriesId": WLO, "dataHoldings": [
                {"dateStart": "2019-09-01T00:00:00Z", "dateEnd": "2019-12-10T00:00:00Z"},
                {"dateStart": "2020-03-26T00:00:00Z", "dateEnd": "2025-03-10T00:00:00Z"}]}]
        days = chs.fetch_observed_extremes_chs(STATION, 2025, self.TODAY)
        assert [lo[:7] for lo, _hi in iwls.months_asked] == ["2025-01", "2025-02", "2025-03"]
        assert (min(days), max(days)) == (date(2025, 1, 1), date(2025, 3, 9))
        assert len(days) == 31 + 28 + 9

    def test_a_year_the_gauge_held_nothing_in_asks_for_no_month(self, iwls):
        iwls.holdings = [{"timeSeriesId": WLO, "dataHoldings": [
            {"dateStart": "2019-09-01T00:00:00Z", "dateEnd": "2019-12-10T00:00:00Z"}]}]
        assert chs.fetch_observed_extremes_chs(STATION, 2025, self.TODAY) == {}
        assert iwls.months_asked == []

    def test_a_month_the_holdings_only_touch_is_asked_for(self, iwls):
        # the gauge began on 1 July, UTC's: the last evening of June in Halifax
        iwls.holdings = [{"timeSeriesId": WLO, "dataHoldings": [
            {"dateStart": "2025-07-01T00:00:00Z", "dateEnd": "2029-09-30T00:00:00Z"}]}]
        chs.fetch_observed_extremes_chs(STATION, 2025, self.TODAY)
        assert [lo[:7] for lo, _hi in iwls.months_asked] == [
            f"2025-{month:02d}" for month in range(6, 13)]

    def test_holdings_that_do_not_name_the_gauge_ask_for_no_month(self, iwls):
        iwls.holdings = [{"timeSeriesId": "5cebf1e23d0f4a073c4bbfa8", "dataHoldings": []}]
        assert chs.fetch_observed_extremes_chs(STATION, 2025, self.TODAY) == {}
        assert iwls.months_asked == []

    @pytest.mark.parametrize("answer", [{"code": "NOT_FOUND"}, [{"dataHoldings": []}]],
                             ids=["not a list", "no series named"])
    def test_holdings_that_cannot_be_read_ask_for_every_month(self, iwls, answer):
        iwls.holdings = answer
        days = chs.fetch_observed_extremes_chs(STATION, 2025, self.TODAY)
        assert len(iwls.months_asked) == 12
        assert len(days) == 365
        # and they are not kept: the next run asks for them again
        chs.fetch_observed_extremes_chs(STATION, 2025, self.TODAY)
        assert iwls.holdings_asked == 2


class TestObservedCache:
    """What is kept of the gauge's months, and for how long."""

    TODAY = date(2026, 4, 10)

    def test_a_year_on_file_asks_nothing_and_waits_for_nothing(self, iwls, clock):
        first = chs.fetch_observed_extremes_chs(STATION, 2026, self.TODAY)
        asked, then = len(iwls.urls), clock.now
        assert chs.fetch_observed_extremes_chs(STATION, 2026, self.TODAY) == first
        assert (len(iwls.urls), clock.now) == (asked, then)
        assert sorted(p.name for p in common.cache_dir().glob("chs_obs_*")) == [
            f"chs_obs_{STATION}_2026{month:02d}.json" for month in (1, 2, 3, 4)]

    def test_the_month_under_way_is_asked_again_once_a_day_is_added(self, iwls):
        chs.fetch_observed_extremes_chs(STATION, 2026, self.TODAY)
        days = chs.fetch_observed_extremes_chs(STATION, 2026, date(2026, 4, 11))
        # however young the file: April alone, now through the 10th
        assert iwls.months_asked[4:] == [("2026-04-01T03:00:00Z", "2026-04-11T03:00:00Z")]
        assert max(days) == date(2026, 4, 10)

    def test_the_month_under_way_is_kept_three_hours_and_a_settled_one_a_month(self, iwls):
        chs.fetch_observed_extremes_chs(STATION, 2026, self.TODAY)
        _aged(2 * 3600)
        chs.fetch_observed_extremes_chs(STATION, 2026, self.TODAY)
        assert len(iwls.months_asked) == 4
        _aged(4 * 3600)
        chs.fetch_observed_extremes_chs(STATION, 2026, self.TODAY)
        assert [lo[:7] for lo, _hi in iwls.months_asked[4:]] == ["2026-04"]
        # twenty days on, the first three months are still on file
        _aged(20 * 86400)
        chs.fetch_observed_extremes_chs(STATION, 2026, self.TODAY)
        assert [lo[:7] for lo, _hi in iwls.months_asked[5:]] == ["2026-04"]
        _aged(31 * 86400)
        chs.fetch_observed_extremes_chs(STATION, 2026, self.TODAY)
        assert [lo[:7] for lo, _hi in iwls.months_asked[6:]] == [
            "2026-01", "2026-02", "2026-03", "2026-04"]

    def test_a_month_the_gauge_sent_nothing_in_is_an_answer_and_is_kept(self, iwls):
        february = (datetime(2026, 2, 1, 4, tzinfo=timezone.utc),
                    datetime(2026, 3, 1, 4, tzinfo=timezone.utc))
        iwls.level = lambda t: None if february[0] <= t <= february[1] else _measured(t)
        days = chs.fetch_observed_extremes_chs(STATION, 2026, self.TODAY)
        assert not [day for day in days if day.month == 2]
        assert {date(2026, 1, 30), date(2026, 3, 2), date(2026, 4, 9)} <= set(days)
        chs.fetch_observed_extremes_chs(STATION, 2026, self.TODAY)
        assert len(iwls.months_asked) == 4

    def test_an_answer_that_is_not_a_list_of_levels_is_not_kept(self, iwls):
        iwls.answers = lambda url: ({"code": "INTERNAL_SERVER_ERROR"}
                                    if "wlo&from=2026-02-01" in url else None)
        days = chs.fetch_observed_extremes_chs(STATION, 2026, self.TODAY)
        assert not [day for day in days if day.month == 2]
        assert {date(2026, 1, 30), date(2026, 3, 2), date(2026, 4, 9)} <= set(days)
        assert not (common.cache_dir() / f"chs_obs_{STATION}_202602.json").exists()
        # so February is asked for again, and this time it is there
        iwls.answers = lambda url: None
        days = chs.fetch_observed_extremes_chs(STATION, 2026, self.TODAY)
        assert [lo[:7] for lo, _hi in iwls.months_asked[4:]] == ["2026-02"]
        assert len(days) == 99

    def test_once_iwls_fails_the_months_after_are_not_waited_on(self, iwls):
        iwls.fails = lambda url: "time-series-code=wlo" in url
        days = chs.fetch_observed_extremes_chs(STATION, 2026, self.TODAY)
        assert days == {}
        # January did not answer, and the three months after were not asked
        assert [lo[:7] for lo, _hi in iwls.months_asked] == ["2026-01"]

    def test_with_iwls_down_the_year_comes_from_the_files_it_has(self, iwls):
        first = chs.fetch_observed_extremes_chs(STATION, 2026, self.TODAY)
        asked = len(iwls.asked_at)
        # every file long past its keeping, and no answer from IWLS
        _aged(40 * 86400)
        iwls.fails = lambda url: True
        assert chs.fetch_observed_extremes_chs(STATION, 2026, self.TODAY) == first
        # one request for the gauge went unanswered, and no more were tried
        assert len(iwls.asked_at) == asked + 1


class TestRateLimit:
    """IWLS allows three requests a second and thirty a minute; the
    gauge's requests keep to two a second and twenty-four a minute."""

    def test_a_run_of_requests_keeps_within_both_limits(self, clock):
        granted = []
        for _ in range(60):
            chs._obs_turn()
            granted.append(clock.now)
        assert min(b - a for a, b in zip(granted, granted[1:])) >= 0.5
        for i, start in enumerate(granted):
            assert sum(start <= t < start + 60 for t in granted[i:]) <= 24
        # the first twenty-four go half a second apart, and the next
        # waits for the minute to pass
        assert granted[23] - granted[0] == pytest.approx(11.5)
        assert granted[24] - granted[0] == pytest.approx(60)

    def test_the_first_request_and_one_long_after_wait_for_nothing(self, clock):
        start = clock.now
        chs._obs_turn()
        assert clock.now == start
        clock.now += 90
        chs._obs_turn()
        assert clock.now == start + 90


if __name__ == "__main__":
    unittest.main()
