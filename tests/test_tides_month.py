"""The tides' month view: a day to a row, the hours across, the water a field."""

import re
from datetime import date, datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from linecast._runtime import TidesRuntime
from linecast.terminal import color as _color
from linecast.terminal.color import fg
from linecast.terminal.textwidth import visible_len
from linecast.tides import harmonic, month
from linecast.tides import palette as _palette
from linecast.tides.common import computed_hilo, computed_range
from linecast.tides.month import (
    _daylight_lows, _Heights, _sun_times, month_of, reach, render_month,
)

TZ = ZoneInfo("America/New_York")
HARBOUR = harmonic.Tide([("M2", 1.40, 100.0), ("S2", 0.21, 135.0), ("N2", 0.28, 70.0),
                         ("K1", 0.14, 200.0), ("O1", 0.11, 180.0)], z0=1.5)
OCT = date(2026, 10, 1)
NOW = datetime(2026, 10, 14, 9, 0, tzinfo=TZ)
PORTLAND = {"lat": "43.66", "lng": "-70.25"}
ANSI = re.compile(r"\x1b\[[0-9;]*m")


@pytest.fixture
def truecolor(monkeypatch):
    """The tests run with no colour at all; the one that reads an ink asks."""
    monkeypatch.setattr(_color, "_COLOR_MODE", "truecolor")


@pytest.fixture(scope="module")
def water():
    """October's curve and its highs and lows, with a day either side."""
    a, b = OCT - timedelta(days=1), date(2026, 11, 1)
    return computed_range(HARBOUR, a, b, TZ), computed_hilo(HARBOUR, a, b, TZ)


def _runtime(lang="en", metric=False):
    return TidesRuntime(live=True, icons="nerd", lang=lang, metric=metric, oneline=False,
                        use_24h=metric)


def _frame(water, cols=100, rows=40, meta=PORTLAND, mouse=None, first=OCT, raw=False,
           lang="en", metric=False, tz=TZ, now=NOW):
    predictions, hilo = water if water else (None, None)
    with patch.object(month, "get_terminal_size", return_value=(cols, rows)):
        out = render_month(first, predictions, hilo, _runtime(lang, metric),
                           header=" Portland, ME", footer=" NOAA", station_meta=meta,
                           station_tz=tz, now_local=now, mouse_pos=mouse)
    body, _, floating = out.partition("\x00")
    if raw:
        return body.split("\n"), floating
    return [ANSI.sub("", line) for line in body.split("\n")], ANSI.sub("", floating)


def _day_rows(lines):
    """The lines that open with a weekday and a day of the month."""
    return [line for line in lines if re.match(r" \S+ +\d+ ", line)]


class TestTheMonthOnScreen:
    def test_the_offset_counts_months_across_the_years_end(self):
        today = date(2026, 10, 14)
        assert month_of(today, 0) == date(2026, 10, 1)
        assert month_of(today, 3) == date(2027, 1, 1)
        assert month_of(today, -10) == date(2025, 12, 1)
        assert month_of(date(2026, 1, 31), 1) == date(2026, 2, 1)


class TestBrightness:
    """How bright the highest water is says how great the tide is."""

    def test_twelve_feet_reaches_the_curves_own_ink(self):
        assert reach(12.0) == 1.0

    def test_a_quarter_the_range_is_half_as_bright(self):
        assert reach(3.0) == pytest.approx(0.5)

    def test_the_greatest_tides_stop_at_the_brightest_ink(self):
        assert reach(48.0) == reach(60.0) == 2.0

    def test_a_sea_with_hardly_a_tide_is_faint_but_drawn(self):
        assert reach(0.0) == reach(0.06) == month.FAINTEST > 0

    def test_a_greater_tide_is_never_fainter(self):
        steps = [reach(r / 4) for r in range(0, 240)]
        assert steps == sorted(steps)


class TestTheWaterBetweenSamples:
    T0 = datetime(2026, 10, 1, 0, 0, tzinfo=TZ)

    def test_a_moment_between_two_samples_is_between_their_heights(self):
        heights = _Heights([(self.T0, 2.0), (self.T0 + timedelta(minutes=6), 3.0)])
        assert heights.at(self.T0 + timedelta(minutes=3)) == pytest.approx(2.5)

    def test_outside_what_was_fetched_there_is_no_water(self):
        heights = _Heights([(self.T0, 2.0), (self.T0 + timedelta(minutes=6), 3.0)])
        assert heights.at(self.T0 - timedelta(minutes=1)) is None
        assert heights.at(self.T0 + timedelta(minutes=7)) is None
        assert _Heights([]).at(self.T0) is None

    def test_a_gap_in_the_series_is_not_drawn_across(self):
        heights = _Heights([(self.T0, 2.0), (self.T0 + timedelta(hours=7), 3.0)])
        assert heights.at(self.T0 + timedelta(hours=3)) is None


class TestTheSun:
    def test_an_ordinary_day_has_a_sunrise_and_a_sunset_on_the_stations_clock(self):
        rise, set_ = _sun_times(date(2026, 10, 1), 43.66, -70.25, TZ)
        # Portland, 1 October: up about 6:38 and down about 6:22
        assert (rise.hour, set_.hour) == (6, 18)
        assert rise.tzinfo is not None and rise.utcoffset() == timedelta(hours=-4)

    def test_the_polar_night_has_no_daylight(self):
        tromso = ZoneInfo("Europe/Oslo")
        assert _sun_times(date(2026, 12, 21), 69.65, 18.96, tromso) == (None, None)

    def test_the_midnight_sun_is_up_from_midnight_to_midnight(self):
        tromso = ZoneInfo("Europe/Oslo")
        rise, set_ = _sun_times(date(2026, 6, 21), 69.65, 18.96, tromso)
        assert set_ - rise == timedelta(days=1)
        assert (rise.hour, rise.minute) == (0, 0)


class TestDaylightLows:
    DAY = date(2026, 10, 5)
    SUN = (datetime(2026, 10, 5, 6, 40, tzinfo=TZ), datetime(2026, 10, 5, 18, 15, tzinfo=TZ))

    def _at(self, hour, height, kind="L", day=5):
        return datetime(2026, 10, day, hour, 0, tzinfo=TZ), height, kind

    def test_only_the_days_low_waters_between_sunrise_and_sunset_count(self):
        hilo = [self._at(2, -1.0), self._at(8, 9.0, "H"), self._at(14, 0.5),
                self._at(20, 8.5, "H"), self._at(14, 0.2, day=6)]
        assert _daylight_lows(hilo, self.DAY, self.SUN) == [self._at(14, 0.5)[:2]]

    def test_a_day_without_a_sunrise_has_none(self):
        assert _daylight_lows([self._at(14, 0.5)], self.DAY, (None, None)) == []


class TestThePage:
    def test_a_tall_window_gives_each_day_a_row(self, water):
        lines, _ = _frame(water, rows=40)
        rows = _day_rows(lines)
        assert len(rows) == 31
        assert rows[0].startswith(" Thu  1 ") and rows[-1].startswith(" Sat 31 ")
        assert len(lines) == 40

    def test_the_header_and_footer_keep_the_windows_edges_and_the_field_sits_midway(self, water):
        lines, _ = _frame(water, rows=44)
        assert lines[0] == " Portland, ME" and lines[-1] == " NOAA"
        first = lines.index(_day_rows(lines)[0])
        last = lines.index(_day_rows(lines)[-1]) + 1      # the hours' axis
        above, below = first - 1, len(lines) - 2 - last
        assert above > 0 and abs(above - below) <= 1
        assert all(line == "" for line in lines[1:first])

    def test_a_short_window_gives_each_row_two_days(self, water):
        lines, _ = _frame(water, rows=24)
        rows = _day_rows(lines)
        assert len(rows) == 16
        assert [row.split()[1] for row in rows[:3]] == ["1", "3", "5"]
        assert len(lines) == 24

    def test_the_hours_run_under_the_field(self, water):
        lines, _ = _frame(water)
        axis = lines[lines.index(_day_rows(lines)[-1]) + 1]
        assert re.search(r"\d", axis) and not re.match(r" \S+ +\d+ ", axis)

    def test_no_line_is_wider_than_the_window(self, water):
        for cols in (60, 80, 100, 140):
            lines, _ = _frame(water, cols=cols)
            assert max(visible_len(line) for line in lines) <= cols, cols

    def test_the_frame_is_drawn_empty_while_the_month_loads(self, water):
        loaded, _ = _frame(water)
        loading, _ = _frame(None)
        assert len(loading) == len(loaded)
        assert [row[:8] for row in _day_rows(loading)] == [row[:8] for row in _day_rows(loaded)]

    def test_a_station_with_no_coordinates_still_has_its_month(self, water):
        lines, _ = _frame(water, meta={})
        assert len(_day_rows(lines)) == 31

    def test_a_february_has_its_own_number_of_rows(self):
        feb = date(2027, 2, 1)
        lines, _ = _frame(None, first=feb)
        assert len(_day_rows(lines)) == 28


class TestTheLowsAtTheRight:
    def _hilo(self):
        def at(day, hour, height, kind="L"):
            return datetime(2026, 10, day, hour, 0, tzinfo=TZ), height, kind
        # the 5th: a lower low in the dark and a low at two in the
        # afternoon; the 6th: a minus tide at noon; the 7th: lows in the
        # dark alone
        return [at(5, 2, -1.0), at(5, 14, 0.5), at(6, 12, -0.4), at(7, 3, 0.1), at(7, 21, 0.3)]

    def _rows(self, raw=False, **size):
        predictions = [(datetime(2026, 10, 1, tzinfo=TZ) + timedelta(hours=h), h % 9)
                       for h in range(31 * 24)]
        lines, _ = _frame((predictions, self._hilo()), raw=raw, **size)
        plain = [ANSI.sub("", line) for line in lines]
        return {int(m.group(1)): lines[n] for n, line in enumerate(plain)
                if (m := re.match(r" \S+ +(\d+) ", line))}

    def test_each_day_shows_its_lowest_low_water_in_daylight(self):
        rows = self._rows()
        assert rows[5].rstrip().endswith("2:00p  0.5′")       # not the lower one at 2 a.m.
        assert rows[6].rstrip().endswith("12:00p −0.4′")

    def test_a_day_whose_lows_fall_in_the_dark_shows_none(self):
        rows = self._rows()
        assert "′" not in rows[7] and "′" not in rows[8]

    def test_a_minus_tide_is_in_the_brighter_ink(self, truecolor):
        rows = self._rows(raw=True)
        assert f"{fg(*_palette.TEXT_RGB)}12:00p −0.4′" in rows[6]
        assert f"{fg(*_palette.MUTED_RGB)} 2:00p  0.5′" in rows[5]

    def test_two_days_to_a_row_names_the_day_of_the_better_low(self):
        rows = self._rows(rows=24)
        assert rows[5].rstrip().endswith(" 6  12:00p −0.4′")  # the 5th and 6th share a row

    def test_a_narrow_window_gives_the_column_up(self):
        rows = self._rows(cols=40)
        assert "′" not in rows[5]


class TestThePointer:
    GUTTER = len("Thu  1") + 4

    def test_the_chip_names_the_hour_and_the_water_on_that_rows_day(self, water):
        # a tall window: three blank rows above the field, a day to a row
        lines, _ = _frame(water, rows=40)
        row = lines.index(_day_rows(lines)[9]) + 1            # the 10th, 1-based
        _lines, chip = _frame(water, rows=40, mouse=(self.GUTTER + 1 + 30, row))
        assert "Sat Oct 10" in chip
        assert re.search(r"\d+:\d\d[ap]", chip) and re.search(r"\d\.\d′", chip)

    def test_a_row_of_two_days_gives_the_water_on_both(self, water):
        lines, _ = _frame(water, rows=24)
        row = lines.index(_day_rows(lines)[2]) + 1            # the 5th and 6th
        _lines, chip = _frame(water, rows=24, mouse=(self.GUTTER + 1 + 30, row))
        assert "Mon Oct 5" in chip and "Tue Oct 6" in chip

    def test_nothing_floats_when_the_pointer_is_off_the_field(self, water):
        lines, _ = _frame(water)
        row = lines.index(_day_rows(lines)[9]) + 1
        assert _frame(water, mouse=(3, row))[1] == ""         # over the day's name
        assert _frame(water, mouse=(40, 1))[1] == ""          # over the header

    def test_an_hour_with_no_water_fetched_says_so(self):
        lines, _ = _frame(None)
        row = lines.index(_day_rows(lines)[9]) + 1
        _lines, chip = _frame(None, mouse=(self.GUTTER + 1 + 30, row))
        assert "Sat Oct 10  –" in chip
