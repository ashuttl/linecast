"""Tests for the tide machine: a tide predicted from its harmonic constants.

The constants used throughout are NOAA's published ones for Bar Harbor,
Maine (station 8413320): the harcon.json listing of its metadata API,
in metres, with Greenwich phase lags and NOAA's own speeds, read on
1 October 2026. Its mean sea level stands 1.728 m above MLLW by the same
station's datums (MSL 2.786, MLLW 1.058, epoch 1983-2001). The fixtures
directory already holds NOAA's predictions for that station on 5 March
2026, so the machine is checked against a table it had no hand in.

Every other tide here is built from constants, sampled, and fitted
again, so the answer is known before the fit is asked.
"""

import cmath
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from linecast.tides import harmonic
from linecast.tides.common import M_TO_FT

UTC = timezone.utc
FIXTURES = Path(__file__).parent / "fixtures"

# (name as NOAA spells it, amplitude in metres, Greenwich lag, degrees an hour)
BAR_HARBOR = (
    ("M2", 1.572, 91.9, 28.984104), ("S2", 0.238, 128.1, 30.0), ("N2", 0.346, 61.4, 28.43973),
    ("K1", 0.141, 193.8, 15.041069), ("M4", 0.008, 92.8, 57.96821),
    ("O1", 0.11, 174.4, 13.943035), ("M6", 0.012, 48.3, 86.95232),
    ("MK3", 0.001, 260.4, 44.025173), ("S4", 0.0, 0.0, 60.0), ("MN4", 0.002, 42.9, 57.423832),
    ("NU2", 0.076, 67.6, 28.512583), ("S6", 0.0, 0.0, 90.0), ("MU2", 0.008, 42.8, 27.968208),
    ("2N2", 0.042, 37.1, 27.895355), ("OO1", 0.006, 231.5, 16.139101),
    ("LAM2", 0.027, 125.3, 29.455626), ("S1", 0.008, 160.4, 15.0),
    ("M1", 0.006, 210.0, 14.496694), ("J1", 0.009, 196.8, 15.5854435),
    ("MM", 0.0, 0.0, 0.5443747), ("SSA", 0.012, 133.7, 0.0821373),
    ("SA", 0.031, 135.8, 0.0410686), ("MSF", 0.012, 86.4, 1.0158958),
    ("MF", 0.0, 0.0, 1.0980331), ("RHO", 0.004, 143.0, 13.471515),
    ("Q1", 0.02, 155.2, 13.398661), ("T2", 0.022, 107.7, 29.958933),
    ("R2", 0.005, 335.2, 30.041067), ("2Q1", 0.002, 174.5, 12.854286),
    ("P1", 0.048, 190.6, 14.958931), ("2SM2", 0.004, 68.4, 31.015896),
    ("M3", 0.001, 141.4, 43.47616), ("L2", 0.08, 135.4, 29.528479),
    ("2MK3", 0.004, 259.9, 42.92714), ("K2", 0.064, 128.7, 30.082138),
    ("M8", 0.001, 329.1, 115.93642), ("MS4", 0.003, 167.0, 58.984104),
)
BAR_HARBOR_Z0 = 2.786 - 1.058
# NOAA's mean range of tide for the station (datum MN), in metres.
BAR_HARBOR_RANGE = 3.22
# The fixtures are in local standard time; 5 March is before the clocks change.
EST = timezone(timedelta(hours=-5))

FIVE = [("M2", 1.5, 100.0), ("S2", 0.25, 130.0), ("N2", 0.35, 70.0),
        ("K1", 0.15, 200.0), ("O1", 0.1, 180.0)]
FIVE_NAMES = [name for name, _amp, _lag in FIVE]
# What fit's docstring says a year of hours cannot separate from S2 and K1.
NOT_IN_A_YEAR = ("S1", "T2", "R2")
# Bar Harbor's constituents of a centimetre and more, less T2.
LARGER = [name for name, amp, _lag, _speed in BAR_HARBOR if amp >= 0.01 and name != "T2"]

Y2026 = datetime(2026, 1, 1, tzinfo=UTC)


def _constants(names=None):
    return [(name, amp, lag) for name, amp, lag, _speed in BAR_HARBOR
            if names is None or name in names]


def _vectors(tide):
    """{name: amplitude and lag as one complex number}."""
    return {name: cmath.rect(amp, math.radians(lag)) for name, amp, lag in tide.constants()}


def _miss(true, fitted, names=None):
    """The farthest any of *true*'s constituents landed from where it
    belongs, in the amplitudes' unit: the distance between the two
    vectors, so a wrong amplitude and a wrong lag both count."""
    want, got = _vectors(true), _vectors(fitted)
    return max(abs(got.get(name, 0) - vector) for name, vector in want.items()
               if names is None or name in names)


def _percent_and_degrees(true, fitted, name):
    """How far *name*'s amplitude is off, as a fraction, and its lag, in degrees."""
    want, got = _vectors(true)[name], _vectors(fitted)[name]
    return abs(got) / abs(want) - 1, math.degrees(cmath.phase(got / want))


def _hourly(tide, start, days, places=None):
    out = []
    for hour in range(days * 24):
        t = start + timedelta(hours=hour)
        height = tide.height(t)
        out.append((t, height if places is None else round(height, places)))
    return out


def _as_a_table_prints_them(turns, places):
    """Turns to the minute and to *places* decimals, as a tide table has them."""
    return [((t + timedelta(seconds=30)).replace(second=0, microsecond=0), round(h, places))
            for t, h, _kind in turns]


def _swing(name, year):
    """How far a constituent of amplitude one swings in *year*: its nodal
    factor. Two heights a quarter of a period apart are the two legs of
    its turning, and the amplitude is their hypotenuse."""
    tide = harmonic.Tide([(name, 1.0, 0.0)])
    t = datetime(year, 3, 1, tzinfo=UTC)
    quarter = timedelta(hours=90 / harmonic.speed(name))
    return math.hypot(tide.height(t), tide.height(t + quarter))


@pytest.fixture(scope="module")
def bar_harbor():
    return harmonic.Tide(_constants(), z0=BAR_HARBOR_Z0)


@pytest.fixture(scope="module")
def bar_harbor_turns(bar_harbor):
    """Bar Harbor's highs and lows of 2026."""
    return bar_harbor.extremes(Y2026, Y2026 + timedelta(days=365))


@pytest.fixture(scope="module")
def larger():
    """Bar Harbor with only its larger constituents, all of which a year separates."""
    return harmonic.Tide(_constants(LARGER), z0=BAR_HARBOR_Z0)


@pytest.fixture(scope="module")
def larger_hours(larger):
    """A year of its hourly heights, to the millimetre."""
    return _hourly(larger, Y2026, 365, places=3)


@pytest.fixture(scope="module")
def larger_turns(larger):
    return larger.extremes(Y2026, Y2026 + timedelta(days=365))


@pytest.fixture(scope="module")
def gulf():
    """A once-a-day tide like the Gulf of Mexico's with a little twice-a-day
    tide on it: when the Moon is over the equator the diurnal tide all but
    vanishes, and the small one turns and turns back."""
    return harmonic.Tide([("K1", 0.13, 10.0), ("O1", 0.125, 350.0),
                          ("M2", 0.02, 100.0), ("S2", 0.008, 120.0)])


@pytest.fixture(scope="module")
def gulf_every_turn(gulf):
    """Its turns of 2026 with no stand left out."""
    return gulf.extremes(Y2026, Y2026 + timedelta(days=365), stand=0)


class TestConstituents:
    """The table of constituents: their names and how fast each turns."""

    def test_the_five_main_constituents_have_their_known_periods(self):
        # 360° over NOAA's published speeds
        periods = {"M2": 12.4206012, "S2": 12.0, "N2": 12.6583475,
                   "K1": 23.9344721, "O1": 25.8193387}
        for name, hours in periods.items():
            assert 360 / harmonic.speed(name) == pytest.approx(hours, abs=1e-5), name

    def test_speeds_are_the_ones_noaa_publishes(self):
        # NOAA prints five to seven decimals. A hundred-thousandth of a
        # degree an hour is a tenth of a degree in a year.
        for name, _amp, _lag, noaa in BAR_HARBOR:
            ours = harmonic.speed(harmonic.canonical(name))
            assert ours == pytest.approx(noaa, abs=1e-5), name

    def test_the_suns_own_constituents_keep_the_clock(self):
        for name, per_hour in (("S1", 15), ("S2", 30), ("S3", 45), ("S4", 60), ("S6", 90)):
            assert harmonic.speed(name) == pytest.approx(per_hour, abs=1e-12), name

    def test_a_compound_tide_turns_at_the_sum_of_its_parents_speeds(self):
        s = harmonic.speed
        sums = {
            "M4": s("M2") + s("M2"), "M6": 3 * s("M2"), "M8": 4 * s("M2"),
            "MS4": s("M2") + s("S2"), "MN4": s("M2") + s("N2"), "N4": 2 * s("N2"),
            "MK3": s("M2") + s("K1"), "2MK3": 2 * s("M2") - s("K1"),
            "2MS6": 2 * s("M2") + s("S2"), "2SM2": 2 * s("S2") - s("M2"),
            "2MO5": 2 * s("M2") + s("O1"), "2MK5": 2 * s("M2") + s("K1"),
            "MSF": s("S2") - s("M2"), "MM": s("M2") - s("N2"),
            # and the same sums among the astronomical ones
            "M2": s("K1") + s("O1"), "S2": s("K1") + s("P1"), "K2": 2 * s("K1"),
            "MF": s("K2") - s("M2"), "SSA": s("K2") - s("S2"), "SA": s("K1") - s("S1"),
        }
        for name, total in sums.items():
            assert s(name) == pytest.approx(total, abs=1e-9), name

    def test_the_first_number_is_how_many_times_a_day_it_comes(self):
        for name, (numbers, _recipe) in harmonic.CONSTITUENTS.items():
            assert round(harmonic.speed(name) / 15) == numbers[0], name

    def test_a_name_is_read_in_either_case(self):
        assert harmonic.canonical("m2") == "M2"
        assert harmonic.canonical("Lambda2") == "LAMBDA2"

    def test_noaas_and_ticons_spellings_are_the_same_constituents(self):
        assert harmonic.canonical("LAM2") == "LAMBDA2"
        assert harmonic.canonical("RHO") == "RHO1"
        assert harmonic.canonical("SIG1") == harmonic.canonical("sigma1") == "SGM"
        assert harmonic.canonical("EPS2") == "EP2"
        assert set(harmonic.ALIASES.values()) <= set(harmonic.CONSTITUENTS)

    def test_a_name_the_table_does_not_know_is_none(self):
        assert harmonic.canonical("3N2") is None
        assert harmonic.canonical("") is None

    def test_every_constituent_in_the_table_can_be_predicted(self):
        tide = harmonic.Tide([(name, 0.1, 0.0) for name in harmonic.CONSTITUENTS])
        assert len(tide.constants()) == len(harmonic.CONSTITUENTS)
        height = tide.height(datetime(2026, 6, 1, 12, tzinfo=UTC))
        assert abs(height) <= 0.1 * 1.8 * len(harmonic.CONSTITUENTS)


class TestAgainstNoaa:
    """Bar Harbor's published constants against NOAA's own predictions
    for 5 March 2026, which are in feet above MLLW and local time."""

    def test_six_minute_heights_agree_to_a_hundredth_of_a_foot(self, bar_harbor):
        rows = json.loads((FIXTURES / "noaa_tide_predictions.json").read_text())["predictions"]
        assert len(rows) == 240
        for row in rows:
            t = datetime.strptime(row["t"], "%Y-%m-%d %H:%M").replace(tzinfo=EST)
            ours = bar_harbor.height(t) * M_TO_FT
            # the constants are printed to the millimetre and the tenth
            # of a degree, which is 3 mm of M2 alone
            assert ours == pytest.approx(float(row["v"]), abs=0.01), row["t"]

    def test_highs_and_lows_agree_to_the_minute(self, bar_harbor):
        rows = json.loads((FIXTURES / "noaa_tide_hilo.json").read_text())["predictions"]
        day = datetime(2026, 3, 5, tzinfo=EST)
        # three turns that day: the high before them came at 23:37 the
        # evening before
        ours = bar_harbor.extremes(day, day + timedelta(days=1))
        assert [kind for _t, _h, kind in ours] == [row["type"] for row in rows]
        for (t, height, _kind), row in zip(ours, rows):
            noaa = datetime.strptime(row["t"], "%Y-%m-%d %H:%M").replace(tzinfo=EST)
            assert abs((t - noaa).total_seconds()) <= 60, row["t"]
            assert height * M_TO_FT == pytest.approx(float(row["v"]), abs=0.01), row["t"]


class TestPhaseAndLevel:
    """What an amplitude, a Greenwich phase lag and a mean level mean."""

    def test_s2_with_no_lag_is_high_at_greenwich_noon_and_midnight(self):
        tide = harmonic.Tide([("S2", 1.0, 0.0)])
        day = datetime(2026, 5, 17, tzinfo=UTC)
        assert tide.height(day) == pytest.approx(1.0, abs=1e-6)
        assert tide.height(day + timedelta(hours=12)) == pytest.approx(1.0, abs=1e-6)
        assert tide.height(day + timedelta(hours=6)) == pytest.approx(-1.0, abs=1e-6)
        assert tide.height(day + timedelta(hours=3)) == pytest.approx(0.0, abs=1e-6)

    def test_a_lag_of_ninety_degrees_puts_s2_three_hours_later(self):
        tide = harmonic.Tide([("S2", 1.0, 90.0)])
        day = datetime(2026, 5, 17, tzinfo=UTC)
        assert tide.height(day + timedelta(hours=3)) == pytest.approx(1.0, abs=1e-6)
        assert tide.height(day + timedelta(hours=15)) == pytest.approx(1.0, abs=1e-6)

    def test_a_lag_of_one_hours_turning_delays_the_tide_an_hour(self):
        early = harmonic.Tide([("M2", 1.0, 40.0)])
        late = harmonic.Tide([("M2", 1.0, 40.0 + harmonic.speed("M2"))])
        start = datetime(2026, 8, 30, 21, 15, tzinfo=UTC)
        for hours in range(6):  # across a midnight
            t = start + timedelta(hours=hours)
            assert late.height(t + timedelta(hours=1)) == pytest.approx(early.height(t), abs=1e-6)

    def test_the_mean_level_lifts_every_height_by_itself(self):
        t = datetime(2026, 3, 5, 9, 30, tzinfo=UTC)
        on_the_mean = harmonic.Tide(_constants())
        on_the_chart = harmonic.Tide(_constants(), z0=BAR_HARBOR_Z0)
        lifted = on_the_mean.height(t) + BAR_HARBOR_Z0
        assert on_the_chart.height(t) == pytest.approx(lifted, abs=1e-12)

    def test_a_tide_with_no_constants_stands_at_its_mean_level(self):
        flat = harmonic.Tide([], z0=1.25)
        day = datetime(2026, 3, 5, tzinfo=UTC)
        assert flat.height(day) == 1.25
        assert {h for _t, h in flat.series(day, day + timedelta(hours=1))} == {1.25}
        assert flat.extremes(day, day + timedelta(days=2)) == []
        assert flat.constants() == []

    def test_constants_come_back_under_the_tables_names(self):
        tide = harmonic.Tide([("m2", 1.0, 10.0), ("LAM2", 0.2, 20.0), ("RHO", 0.1, 30.0)])
        assert tide.constants() == [("M2", 1.0, 10.0), ("LAMBDA2", 0.2, 20.0),
                                    ("RHO1", 0.1, 30.0)]

    def test_a_tide_made_from_its_own_constants_is_the_same_tide(self, bar_harbor):
        again = harmonic.Tide(bar_harbor.constants(), z0=bar_harbor.z0)
        t = datetime(2026, 11, 2, 7, 45, tzinfo=UTC)
        assert again.height(t) == bar_harbor.height(t)

    def test_unknown_names_and_empty_amplitudes_are_left_out(self):
        tide = harmonic.Tide([("M2", 1.0, 10.0), ("3N2", 0.5, 0.0), ("S2", 0.0, 0.0),
                              ("K1", None, 0.0)])
        assert tide.constants() == [("M2", 1.0, 10.0)]
        alone = harmonic.Tide([("M2", 1.0, 10.0)])
        t = datetime(2026, 3, 5, 9, 30, tzinfo=UTC)
        assert tide.height(t) == alone.height(t)


class TestTime:
    """A prediction is for an instant, whatever clock the instant is told on."""

    def test_the_same_instant_in_any_zone_gives_the_same_height(self, bar_harbor):
        instant = datetime(2026, 3, 5, 16, 58, tzinfo=UTC)
        # the 6th already in Tokyo and Chatham, and odd quarter hours off UTC
        for zone in ("America/New_York", "Asia/Tokyo", "Asia/Kolkata", "Pacific/Chatham"):
            local = instant.astimezone(ZoneInfo(zone))
            assert bar_harbor.height(local) == bar_harbor.height(instant), zone

    def test_a_naive_time_is_taken_as_utc(self, bar_harbor):
        naive = datetime(2026, 3, 5, 16, 58)
        assert bar_harbor.height(naive) == bar_harbor.height(naive.replace(tzinfo=UTC))

    def test_the_hour_the_clocks_repeat_is_two_instants(self, bar_harbor):
        new_york = ZoneInfo("America/New_York")
        first = datetime(2026, 11, 1, 1, 30, tzinfo=new_york)
        second = first.replace(fold=1)
        assert bar_harbor.height(first) == bar_harbor.height(datetime(2026, 11, 1, 5, 30,
                                                                      tzinfo=UTC))
        assert bar_harbor.height(second) == bar_harbor.height(datetime(2026, 11, 1, 6, 30,
                                                                       tzinfo=UTC))
        assert abs(bar_harbor.height(first) - bar_harbor.height(second)) > 0.1

    def test_a_series_comes_back_in_utc_whatever_zone_asked_for_it(self, bar_harbor):
        new_york = ZoneInfo("America/New_York")
        start = datetime(2026, 3, 5, tzinfo=new_york)
        local = bar_harbor.series(start, start + timedelta(hours=1))
        utc = bar_harbor.series(start.astimezone(UTC), start.astimezone(UTC) + timedelta(hours=1))
        assert local == utc
        assert local[0][0] == datetime(2026, 3, 5, 5, tzinfo=UTC)
        assert all(t.utcoffset() == timedelta(0) for t, _h in local)

    def test_turns_are_the_same_whatever_zone_the_window_is_given_in(self, bar_harbor):
        tokyo = ZoneInfo("Asia/Tokyo")
        start = datetime(2026, 3, 5, tzinfo=UTC)
        end = start + timedelta(days=2)
        assert (bar_harbor.extremes(start.astimezone(tokyo), end.astimezone(tokyo))
                == bar_harbor.extremes(start, end))


class TestSeries:
    """Heights on a grid of minutes."""

    def test_a_day_of_six_minutes_has_both_its_midnights(self, bar_harbor):
        day = datetime(2026, 3, 5, tzinfo=UTC)
        points = bar_harbor.series(day, day + timedelta(days=1))
        assert len(points) == 241
        assert points[0][0] == day
        assert points[-1][0] == day + timedelta(days=1)
        assert {b[0] - a[0] for a, b in zip(points, points[1:])} == {timedelta(minutes=6)}

    def test_a_start_off_the_grid_waits_for_the_next_step(self, bar_harbor):
        start = datetime(2026, 3, 5, 0, 2, tzinfo=UTC)
        points = bar_harbor.series(start, start + timedelta(minutes=28))
        assert [t.strftime("%H:%M") for t, _h in points] == ["00:06", "00:12", "00:18",
                                                             "00:24", "00:30"]

    def test_the_step_can_be_any_number_of_minutes(self, bar_harbor):
        day = datetime(2026, 3, 5, tzinfo=UTC)
        points = bar_harbor.series(day, day + timedelta(hours=2), 20)
        assert [t.strftime("%H:%M") for t, _h in points] == ["00:00", "00:20", "00:40", "01:00",
                                                             "01:20", "01:40", "02:00"]

    def test_each_height_is_the_height_at_its_instant(self, bar_harbor):
        # across the New Year, where the year's nodal factors change
        start = datetime(2026, 12, 31, 22, tzinfo=UTC)
        points = bar_harbor.series(start, start + timedelta(hours=4), 30)
        assert len(points) == 9
        for t, height in points:
            assert height == pytest.approx(bar_harbor.height(t), abs=1e-12)

    def test_a_single_instant_is_a_series_of_one(self, bar_harbor):
        noon = datetime(2026, 3, 5, 12, tzinfo=UTC)
        assert bar_harbor.series(noon, noon) == [(noon, bar_harbor.height(noon))]

    def test_an_end_before_the_start_is_empty(self, bar_harbor):
        noon = datetime(2026, 3, 5, 12, tzinfo=UTC)
        assert bar_harbor.series(noon, noon - timedelta(hours=1)) == []


class TestSteadiness:
    """The curve has no steps in it, however the sums are kept."""

    def test_no_midnight_of_the_year_has_a_step_in_it(self, bar_harbor):
        # The water moves 1.4 m an hour at most here, which is under a
        # thousandth of a millimetre in the microsecond before midnight.
        for day in range(1, 365):
            midnight = Y2026 + timedelta(days=day)
            before = bar_harbor.height(midnight - timedelta(microseconds=1))
            assert bar_harbor.height(midnight) == pytest.approx(before, abs=1e-6), midnight

    def test_six_minutes_never_move_the_water_farther_than_the_constants_can(self, bar_harbor):
        # every constituent rising at its fastest at once, with the
        # largest nodal factors the diurnal ones reach
        fastest = sum(amp * math.radians(harmonic.speed(name))
                      for name, amp, _lag in bar_harbor.constants())
        points = bar_harbor.series(datetime(2026, 2, 20, tzinfo=UTC),
                                   datetime(2026, 3, 20, tzinfo=UTC))
        steps = [abs(b[1] - a[1]) for a, b in zip(points, points[1:])]
        assert max(steps) <= 1.2 * fastest / 10
        assert max(steps) > 0.05  # and it does move

    def test_the_new_years_change_of_factors_moves_the_water_a_few_centimetres(self, bar_harbor):
        # The nodal factors are each year's own, so the curve steps at
        # 00:00 UTC on 1 January: by 48 mm at most in these years, which
        # is under two percent of the mean range.
        for year in range(2020, 2036):
            new_year = datetime(year + 1, 1, 1, tzinfo=UTC)
            before = bar_harbor.height(new_year - timedelta(microseconds=1))
            step = abs(bar_harbor.height(new_year) - before)
            assert step < 0.02 * BAR_HARBOR_RANGE, year

    def test_three_years_of_days_leave_the_first_day_as_it_was(self, bar_harbor):
        tide = harmonic.Tide(bar_harbor.constants(), z0=bar_harbor.z0)
        first = datetime(2026, 1, 1, 6, tzinfo=UTC)
        height = tide.height(first)
        for day in range(1, 1100):
            tide.height(first + timedelta(days=day))
        assert tide.height(first) == height

    def test_a_century_either_way_is_still_a_tide(self, bar_harbor):
        reach = sum(amp for _name, amp, _lag in bar_harbor.constants())
        for year in (1900, 2040, 2126):
            day = datetime(year, 6, 1, tzinfo=UTC)
            heights = [h for _t, h in bar_harbor.series(day, day + timedelta(days=1), 60)]
            assert max(heights) - min(heights) > 2.0, year
            assert all(abs(h - BAR_HARBOR_Z0) < 1.2 * reach for h in heights), year


class TestExtremes:
    """The highs and lows."""

    def test_a_turn_by_the_windows_edge_is_found(self):
        # S2 alone is high at 03:02 UTC each day; a window opening a
        # minute before it, off the scan's twenty-minute grid, had no
        # point of the scan on the turn's far side
        tide = harmonic.Tide([("S2", 1.0, 91.0)])
        day = datetime(2026, 3, 5, tzinfo=UTC)
        for minute in (0, 1, 2):
            turns = tide.extremes(day + timedelta(hours=3, minutes=minute),
                                  day + timedelta(hours=6))
            assert [(t.strftime("%H:%M"), kind) for t, _h, kind in turns] == [("03:02", "H")]
        # and one that opens after it does not have it
        assert tide.extremes(day + timedelta(hours=3, minutes=3),
                             day + timedelta(hours=6)) == []

    def test_a_window_cut_anywhere_has_the_turns_that_fall_in_it(self, bar_harbor,
                                                                bar_harbor_turns):
        """The year's turns are the reference; any window of it, on or
        off the scan's grid, holds exactly those of them inside it."""
        start = datetime(2026, 2, 1, tzinfo=UTC)
        for k in range(60):
            a = start + timedelta(hours=5 * k, minutes=7 * k + 3)
            b = a + timedelta(hours=9, minutes=11 * k % 60)
            want = [t for t, _h, _kind in bar_harbor_turns if a <= t <= b]
            got = [t for t, _h, _kind in bar_harbor.extremes(a, b)]
            assert len(got) == len(want), (a, b)
            for one, other in zip(got, want):
                assert abs((one - other).total_seconds()) < 1

    def test_a_year_has_two_highs_and_two_lows_each_lunar_day(self, bar_harbor_turns):
        # 365 days of 24 h 50.5 min lunar days, four turns in each
        assert 1410 <= len(bar_harbor_turns) <= 1412

    def test_highs_and_lows_take_turns(self, bar_harbor_turns):
        kinds = [kind for _t, _h, kind in bar_harbor_turns]
        assert set(kinds) == {"H", "L"}
        assert all(a != b for a, b in zip(kinds, kinds[1:]))

    def test_times_run_forward_inside_the_window(self, bar_harbor_turns):
        times = [t for t, _h, _kind in bar_harbor_turns]
        assert times == sorted(times)
        assert Y2026 <= times[0] and times[-1] <= Y2026 + timedelta(days=365)
        assert all(t.utcoffset() == timedelta(0) for t in times)

    def test_each_turn_is_the_top_or_bottom_to_the_minute(self, bar_harbor, bar_harbor_turns):
        minute = timedelta(minutes=1)
        for t, height, kind in bar_harbor_turns[:120]:
            beside = (bar_harbor.height(t - minute), bar_harbor.height(t + minute))
            assert height == pytest.approx(bar_harbor.height(t), abs=1e-12)
            if kind == "H":
                assert height > max(beside), t
            else:
                assert height < min(beside), t

    def test_a_year_a_day_at_a_time_is_the_same_turns(self, bar_harbor, bar_harbor_turns):
        by_day = []
        for day in range(365):
            start = Y2026 + timedelta(days=day)
            by_day += bar_harbor.extremes(start, start + timedelta(days=1))
        assert by_day == bar_harbor_turns

    def test_a_window_between_two_turns_is_empty(self, bar_harbor):
        # the low at 10:50 UTC and the high at 16:58 on 5 March
        start = datetime(2026, 3, 5, 12, tzinfo=UTC)
        assert bar_harbor.extremes(start, start + timedelta(hours=4)) == []

    def test_an_end_before_the_start_is_empty(self, bar_harbor):
        start = datetime(2026, 3, 5, 12, tzinfo=UTC)
        assert bar_harbor.extremes(start, start - timedelta(days=1)) == []


class TestStands:
    """A high and a low a millimetre or two apart are one stand of the water."""

    END = Y2026 + timedelta(days=365)

    @staticmethod
    def _closest(turns):
        return min(abs(a[1] - b[1]) for a, b in zip(turns, turns[1:]))

    def test_the_bare_scan_finds_turns_under_a_millimetre_apart(self, gulf_every_turn):
        assert self._closest(gulf_every_turn) < 0.001

    def test_no_neighbours_closer_than_two_millimetres_are_kept(self, gulf, gulf_every_turn):
        kept = gulf.extremes(Y2026, self.END)
        assert self._closest(kept) >= 0.002
        assert len(kept) < len(gulf_every_turn)

    def test_a_stand_goes_as_a_pair_so_highs_and_lows_still_take_turns(
            self, gulf, gulf_every_turn):
        kept = gulf.extremes(Y2026, self.END)
        assert (len(gulf_every_turn) - len(kept)) % 2 == 0
        kinds = [kind for _t, _h, kind in kept]
        assert all(a != b for a, b in zip(kinds, kinds[1:]))
        assert set(kept) <= set(gulf_every_turn)

    def test_a_wider_stand_leaves_out_more(self, gulf):
        kept = gulf.extremes(Y2026, self.END)
        fewer = gulf.extremes(Y2026, self.END, stand=0.01)
        assert len(fewer) < len(kept)
        assert self._closest(fewer) >= 0.01
        assert set(fewer) <= set(kept)


class TestNodalCycle:
    """The Moon's node goes round in 18.6 years, and the lunar constituents
    grow and shrink with the swing of its orbit: widest in 2006 and 2025,
    narrowest in 2015 and 2034."""

    def test_o1_is_a_fifth_larger_at_the_widest_swing_and_a_fifth_smaller_at_the_narrowest(self):
        # by Schureman's formula O1's factor runs from 0.806 to 1.183
        assert _swing("O1", 2025) == pytest.approx(1.18, abs=0.005)
        assert _swing("O1", 2015) == pytest.approx(0.81, abs=0.005)
        assert _swing("O1", 2034) == pytest.approx(0.81, abs=0.005)

    def test_m2_goes_the_other_way_by_under_four_percent(self):
        # and M2's from 1.038 down to 0.963
        assert _swing("M2", 2025) == pytest.approx(0.964, abs=0.002)
        assert _swing("M2", 2015) == pytest.approx(1.037, abs=0.002)
        assert _swing("M2", 2034) == pytest.approx(1.037, abs=0.002)

    def test_the_swing_comes_round_every_eighteen_or_nineteen_years(self):
        o1 = {year: _swing("O1", year) for year in range(2006, 2044)}
        peaks = [y for y in range(2007, 2043) if o1[y - 1] < o1[y] > o1[y + 1]]
        troughs = [y for y in range(2007, 2043) if o1[y - 1] > o1[y] < o1[y + 1]]
        assert peaks == [2025]
        assert troughs == [2015, 2034]
        assert o1[2006] > o1[2007] and o1[2043] > o1[2042]

    def test_each_year_follows_the_first_order_series_in_the_nodes_longitude(self):
        # f = a + b cos N, the series tide texts give for these factors
        # (Pugh, "Tides, Surges and Mean Sea-Level", 1987, chapter 4). It
        # stops at its first term, and Schureman's formulas part from it
        # by 0.016 at most (O1).
        series = {"MM": (1.000, -0.130), "MF": (1.043, 0.414), "Q1": (1.009, 0.187),
                  "O1": (1.009, 0.187), "K1": (1.006, 0.115), "N2": (1.000, -0.037),
                  "M2": (1.000, -0.037), "K2": (1.024, 0.286)}
        for year in range(2006, 2044):
            # the node's mean longitude at mid-year, after Meeus
            node = math.radians(125.0445 - 1934.1363 * (year + 0.5 - 2000) / 100)
            for name, (a, b) in series.items():
                assert _swing(name, year) == pytest.approx(a + b * math.cos(node), abs=0.02), \
                    (name, year)

    def test_the_suns_constituents_are_the_same_every_year(self):
        for name in ("S2", "P1", "SA", "SSA", "T2", "S1"):
            for year in (2015, 2025):
                assert _swing(name, year) == pytest.approx(1.0, abs=1e-6), (name, year)

    def test_an_overtide_swings_as_its_parents_multiplied(self):
        for year in (2015, 2025):
            m2, k1, o1 = _swing("M2", year), _swing("K1", year), _swing("O1", year)
            assert _swing("M4", year) == pytest.approx(m2 ** 2, abs=1e-4)
            assert _swing("M6", year) == pytest.approx(m2 ** 3, abs=1e-4)
            assert _swing("MS4", year) == pytest.approx(m2, abs=1e-4)
            assert _swing("MK3", year) == pytest.approx(m2 * k1, abs=1e-4)
            assert _swing("2MO5", year) == pytest.approx(m2 ** 2 * o1, abs=1e-4)


class TestFit:
    """Constants from hourly heights: a tide built from known constants,
    sampled and fitted again, should give them back."""

    def test_a_month_of_exact_heights_gives_five_constituents_back_exactly(self):
        tide = harmonic.Tide(FIVE, z0=2.0)
        fitted = harmonic.fit(_hourly(tide, Y2026, 30), FIVE_NAMES)
        assert _miss(tide, fitted) < 1e-9
        assert fitted.z0 == pytest.approx(2.0, abs=1e-9)

    def test_a_year_to_the_millimetre_gives_sixteen_back_to_a_twentieth_of_one(
            self, larger, larger_hours):
        fitted = harmonic.fit(larger_hours, LARGER)
        assert len(fitted.constants()) == len(LARGER) == 16
        assert _miss(larger, fitted) < 0.00005
        assert fitted.z0 == pytest.approx(BAR_HARBOR_Z0, abs=0.00005)

    def test_half_a_year_is_still_enough_for_all_of_them(self, larger, larger_hours):
        fitted = harmonic.fit(larger_hours[:183 * 24], LARGER)
        assert _miss(larger, fitted) < 0.0001
        assert fitted.z0 == pytest.approx(BAR_HARBOR_Z0, abs=0.0001)

    def test_two_months_begin_to_lose_the_yearly_constituent(self, larger, larger_hours):
        # 3.4 mm of SA's 31, where half a year missed by 0.03 mm
        fitted = harmonic.fit(larger_hours[:60 * 24], LARGER)
        assert 0.001 < _miss(larger, fitted, {"SA"}) < 0.01
        the_rest = set(LARGER) - {"SA", "SSA"}
        assert _miss(larger, fitted, the_rest) < 0.0001

    def test_a_month_cannot_tell_the_yearly_swing_from_the_mean_level(
            self, larger, larger_hours):
        # One month is a twelfth of SA's turn, which looks like a level
        # that is merely somewhere else: SA lands half a metre off and
        # the mean level a third of one, from heights good to half a
        # millimetre. Everything but SA and SSA is still within 2 mm.
        fitted = harmonic.fit(larger_hours[:30 * 24], LARGER)
        assert _miss(larger, fitted, {"SA"}) > 0.05
        assert abs(fitted.z0 - BAR_HARBOR_Z0) > 0.05
        the_rest = set(LARGER) - {"SA", "SSA"}
        assert _miss(larger, fitted, the_rest) < 0.002

    def test_five_days_to_the_centimetre_place_the_five_main_within_half_of_one(self):
        tide = harmonic.Tide(FIVE, z0=2.0)
        fitted = harmonic.fit(_hourly(tide, Y2026, 5, places=2), FIVE_NAMES)
        assert _miss(tide, fitted) < 0.005

    def test_one_day_cannot_tell_m2_from_s2_and_n2(self):
        # M2 and S2 are 1° an hour apart and M2 and N2 half of one, so in
        # a day they hardly part, and the rounding decides the answer.
        tide = harmonic.Tide(FIVE, z0=2.0)
        fitted = harmonic.fit(_hourly(tide, Y2026, 1, places=2), FIVE_NAMES)
        assert fitted is None or _miss(tide, fitted) > 0.5

    def test_what_a_years_fit_leaves_out_barely_moves_what_it_keeps(self, bar_harbor):
        # All of Bar Harbor's 33 constituents in the water, five asked
        # for. K2 and T2 lean on S2 and NU2 on N2; M2 has no close
        # neighbour of any size.
        fitted = harmonic.fit(_hourly(bar_harbor, Y2026, 365), FIVE_NAMES)
        amplitude, lag = _percent_and_degrees(bar_harbor, fitted, "M2")
        assert abs(amplitude) < 0.001 and abs(lag) < 0.1
        for name in ("S2", "N2", "K1", "O1"):
            amplitude, lag = _percent_and_degrees(bar_harbor, fitted, name)
            assert abs(amplitude) < 0.03 and abs(lag) < 1.5, name
        assert fitted.z0 == pytest.approx(BAR_HARBOR_Z0, abs=0.001)

    def test_the_same_constants_come_back_from_any_year_of_the_nodal_cycle(self):
        tide = harmonic.Tide(FIVE, z0=2.0)
        for year in (2015, 2025):
            start = datetime(year, 3, 1, tzinfo=UTC)
            fitted = harmonic.fit(_hourly(tide, start, 30), FIVE_NAMES)
            assert _miss(tide, fitted) < 1e-9, year
        # though the water itself differed by half as much again
        assert _swing("O1", 2025) / _swing("O1", 2015) > 1.4

    def test_a_record_across_the_new_year_fits_as_well(self):
        tide = harmonic.Tide(FIVE, z0=2.0)
        fitted = harmonic.fit(_hourly(tide, datetime(2025, 12, 17, tzinfo=UTC), 30), FIVE_NAMES)
        assert _miss(tide, fitted) < 1e-9

    def test_samples_in_another_zone_or_in_naive_utc_fit_the_same(self):
        tide = harmonic.Tide(FIVE, z0=2.0)
        samples = _hourly(tide, Y2026, 20)
        tokyo = ZoneInfo("Asia/Tokyo")
        want = harmonic.fit(samples, FIVE_NAMES).constants()
        assert harmonic.fit([(t.astimezone(tokyo), h) for t, h in samples],
                            FIVE_NAMES).constants() == want
        assert harmonic.fit([(t.replace(tzinfo=None), h) for t, h in samples],
                            FIVE_NAMES).constants() == want

    def test_lags_come_back_between_0_and_360(self):
        tide = harmonic.Tide([("M2", 1.0, 359.5), ("K1", 0.3, 0.5)])
        fitted = harmonic.fit(_hourly(tide, Y2026, 30), ["M2", "K1"])
        lags = {name: lag for name, _amp, lag in fitted.constants()}
        assert lags["M2"] == pytest.approx(359.5, abs=1e-6)
        assert lags["K1"] == pytest.approx(0.5, abs=1e-6)

    def test_the_mean_level_is_solved_for_unless_it_is_given(self):
        tide = harmonic.Tide(FIVE, z0=2.0)
        samples = _hourly(tide, Y2026, 30)
        assert harmonic.fit(samples, FIVE_NAMES).z0 == pytest.approx(2.0, abs=1e-9)
        pinned = harmonic.fit(samples, FIVE_NAMES, z0=2.0)
        assert pinned.z0 == 2.0
        assert _miss(tide, pinned) < 1e-9
        # a wrong level stays as given, and the constants bend to it
        wrong = harmonic.fit(samples, FIVE_NAMES, z0=2.5)
        assert wrong.z0 == 2.5
        assert _miss(tide, wrong) > 0.001

    def test_with_no_names_it_finds_the_mean_level_alone(self):
        samples = [(Y2026 + timedelta(hours=h), height)
                   for h, height in enumerate((1.0, 2.0, 4.0, 5.0))]
        fitted = harmonic.fit(samples, [])
        assert fitted.constants() == []
        assert fitted.z0 == pytest.approx(3.0)

    def test_names_the_table_does_not_know_are_left_out_of_the_fit(self):
        tide = harmonic.Tide(FIVE, z0=2.0)
        fitted = harmonic.fit(_hourly(tide, Y2026, 30), FIVE_NAMES + ["3N2", "MTM"])
        assert [name for name, _amp, _lag in fitted.constants()] == FIVE_NAMES
        assert _miss(tide, fitted) < 1e-9

    def test_another_spelling_is_fitted_under_the_tables_name(self):
        tide = harmonic.Tide([("M2", 1.0, 30.0), ("LAMBDA2", 0.2, 60.0)])
        fitted = harmonic.fit(_hourly(tide, Y2026, 60), ["m2", "LAM2"])
        assert [name for name, _amp, _lag in fitted.constants()] == ["M2", "LAMBDA2"]
        assert _miss(tide, fitted) < 1e-9

    def test_no_samples_fit_nothing(self):
        assert harmonic.fit([], FIVE_NAMES) is None

    def test_fewer_samples_than_unknowns_fit_nothing(self):
        tide = harmonic.Tide(FIVE, z0=2.0)
        assert harmonic.fit(_hourly(tide, Y2026, 1)[:3], FIVE_NAMES) is None

    def test_a_constituent_named_twice_cannot_be_split_with_itself(self):
        tide = harmonic.Tide(FIVE, z0=2.0)
        samples = _hourly(tide, Y2026, 30)
        assert harmonic.fit(samples, ["M2", "LAM2", "LAMBDA2"]) is None


class TestFitTurns:
    """Constants from a year's highs and lows alone."""

    def test_a_tides_own_turns_give_its_constants_back(self):
        tide = harmonic.Tide(FIVE, z0=2.0)
        turns = tide.extremes(Y2026, Y2026 + timedelta(days=365))
        fitted = harmonic.fit_turns([(t, h) for t, h, _kind in turns], FIVE_NAMES)
        assert _miss(tide, fitted) < 1e-6
        assert fitted.z0 == pytest.approx(2.0, abs=1e-6)

    def test_turns_as_a_table_prints_them_give_sixteen_back_within_a_millimetre(
            self, larger, larger_turns):
        # to the minute and the millimetre, as NOAA's tables have them
        fitted = harmonic.fit_turns(_as_a_table_prints_them(larger_turns, 3), LARGER)
        assert _miss(larger, fitted) < 0.001
        assert fitted.z0 == pytest.approx(BAR_HARBOR_Z0, abs=0.001)

    def test_a_month_of_turns_to_the_centimetre_is_enough_for_five(self):
        tide = harmonic.Tide(FIVE, z0=2.0)
        turns = tide.extremes(Y2026, Y2026 + timedelta(days=30))
        fitted = harmonic.fit_turns(_as_a_table_prints_them(turns, 2), FIVE_NAMES)
        assert _miss(tide, fitted) < 0.002

    def test_heights_alone_leave_the_whole_tide_free_to_slide_in_time(
            self, larger, larger_turns):
        # With no weight on the slope the amplitudes still come back, but
        # every lag is off by the same few minutes: the tide slid whole.
        turns = _as_a_table_prints_them(larger_turns, 2)
        loose = harmonic.fit_turns(turns, LARGER, hours=0.0)
        slid = {}
        for name in FIVE_NAMES:
            amplitude, lag = _percent_and_degrees(larger, loose, name)
            assert abs(amplitude) < 0.01, name
            slid[name] = 60 * lag / harmonic.speed(name)  # minutes
        assert abs(slid["M2"]) > 2
        assert max(slid.values()) - min(slid.values()) < 1
        # and the slope pins it
        pinned = harmonic.fit_turns(turns, LARGER)
        for name in FIVE_NAMES:
            _amplitude, lag = _percent_and_degrees(larger, pinned, name)
            assert abs(60 * lag / harmonic.speed(name)) < 0.5, name

    def test_the_slope_holds_m2_within_two_percent_on_a_real_tides_turns(
            self, bar_harbor, bar_harbor_turns):
        # Every constituent Bar Harbor has is in the water, and the fit
        # is asked for all that a year separates: thirty names from 1,411
        # turns. M2 comes back 1.6% large and N2 6% small.
        names = [name for name, _amp, _lag in bar_harbor.constants()
                 if name not in NOT_IN_A_YEAR]
        fitted = harmonic.fit_turns(_as_a_table_prints_them(bar_harbor_turns, 3), names)
        amplitude, lag = _percent_and_degrees(bar_harbor, fitted, "M2")
        assert abs(amplitude) < 0.02
        assert abs(lag) < 0.5
        for name in ("S2", "N2", "K1", "O1"):
            amplitude, lag = _percent_and_degrees(bar_harbor, fitted, name)
            assert abs(amplitude) < 0.08 and abs(lag) < 0.5, name
        assert fitted.z0 == pytest.approx(BAR_HARBOR_Z0, abs=0.005)

    def test_without_the_slope_the_same_turns_put_m2_over_five_percent_out(
            self, bar_harbor, bar_harbor_turns):
        names = [name for name, _amp, _lag in bar_harbor.constants()
                 if name not in NOT_IN_A_YEAR]
        loose = harmonic.fit_turns(_as_a_table_prints_them(bar_harbor_turns, 3), names,
                                   hours=0.0)
        amplitude, _lag = _percent_and_degrees(bar_harbor, loose, "M2")
        assert abs(amplitude) > 0.05

    def test_turns_in_another_zone_or_in_naive_utc_fit_the_same(self):
        tide = harmonic.Tide(FIVE, z0=2.0)
        turns = [(t, h) for t, h, _kind in tide.extremes(Y2026, Y2026 + timedelta(days=30))]
        chatham = ZoneInfo("Pacific/Chatham")
        want = harmonic.fit_turns(turns, FIVE_NAMES).constants()
        assert harmonic.fit_turns([(t.astimezone(chatham), h) for t, h in turns],
                                  FIVE_NAMES).constants() == want
        assert harmonic.fit_turns([(t.replace(tzinfo=None), h) for t, h in turns],
                                  FIVE_NAMES).constants() == want

    def test_the_same_constants_come_back_from_either_end_of_the_nodal_cycle(self):
        tide = harmonic.Tide(FIVE, z0=2.0)
        for year in (2015, 2025):
            start = datetime(year, 3, 1, tzinfo=UTC)
            turns = tide.extremes(start, start + timedelta(days=60))
            fitted = harmonic.fit_turns([(t, h) for t, h, _kind in turns], FIVE_NAMES)
            assert _miss(tide, fitted) < 1e-6, year

    def test_names_the_table_does_not_know_are_left_out(self):
        tide = harmonic.Tide(FIVE, z0=2.0)
        turns = [(t, h) for t, h, _kind in tide.extremes(Y2026, Y2026 + timedelta(days=30))]
        fitted = harmonic.fit_turns(turns, FIVE_NAMES + ["MTM"])
        assert [name for name, _amp, _lag in fitted.constants()] == FIVE_NAMES

    def test_no_turns_fit_nothing(self):
        assert harmonic.fit_turns([], FIVE_NAMES) is None
