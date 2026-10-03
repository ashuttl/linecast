"""The tides' year view: each day's predicted range, and the gauge's pen."""

import re
from datetime import date, datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from linecast._runtime import TidesRuntime
from linecast.terminal import color as _color
from linecast.terminal.color import fg
from linecast.terminal.textwidth import visible_len
from linecast.tides import harmonic, year as year_view
from linecast.tides.common import computed_hilo
from linecast.tides.year import _ticks, daily_ranges, render_year, summary

TZ = ZoneInfo("America/New_York")
HARBOUR = harmonic.Tide([("M2", 1.40, 100.0), ("S2", 0.21, 135.0), ("N2", 0.28, 70.0),
                         ("K1", 0.14, 200.0), ("O1", 0.11, 180.0)], z0=1.5)
TODAY = date(2026, 10, 1)
ANSI = re.compile(r"\x1b\[[0-9;]*m")
BRAILLE = re.compile("[⠁-⣿]")


@pytest.fixture
def truecolor(monkeypatch):
    """The tests run with no colour at all; these few read the inks."""
    monkeypatch.setattr(_color, "_COLOR_MODE", "truecolor")


@pytest.fixture(scope="module")
def predicted():
    return daily_ranges(computed_hilo(HARBOUR, date(2026, 1, 1), date(2026, 12, 31), TZ))


def _observed(predicted, through=TODAY, lift=0.4):
    """What a gauge might have measured: the tables, a little higher."""
    return {day: (lo + lift, hi + lift) for day, (lo, hi) in predicted.items() if day < through}


def _runtime(lang="en", metric=False):
    return TidesRuntime(live=True, icons="nerd", lang=lang, metric=metric, oneline=False,
                        use_24h=metric)


def _frame(predicted, observed=None, flood=None, cols=110, rows=40, lang="en", metric=False,
           mouse=None, raw=False, year=2026, observed_name="measured"):
    with patch.object(year_view, "get_terminal_size", return_value=(cols, rows)):
        out = render_year(year, predicted, observed, flood, _runtime(lang, metric),
                          header=" Portland, ME", footer=" NOAA", today=TODAY, tzinfo=TZ,
                          mouse_pos=mouse, observed_name=observed_name)
    body, _, floating = out.partition("\x00")
    if raw:
        return body.split("\n"), floating
    return [ANSI.sub("", line) for line in body.split("\n")], ANSI.sub("", floating)


class TestDailyRanges:
    def test_each_day_runs_from_its_lowest_water_to_its_highest(self):
        def at(day, hour, height, kind):
            return datetime(2026, 10, day, hour, tzinfo=TZ), height, kind
        hilo = [at(1, 2, 0.3, "L"), at(1, 8, 9.1, "H"), at(1, 14, -0.2, "L"),
                at(1, 20, 9.6, "H"), at(2, 3, 0.5, "L")]
        assert daily_ranges(hilo) == {date(2026, 10, 1): (-0.2, 9.6),
                                      date(2026, 10, 2): (0.5, 0.5)}

    def test_nothing_fetched_is_no_days(self):
        assert daily_ranges(None) == {} and daily_ranges([]) == {}


class TestTheScalesLabels:
    def test_feet_are_labelled_by_whole_steps_three_rows_apart_or_more(self):
        ticks = _ticks(-1.2, 11.4, 30, _runtime())
        values = [v for _feet, v in ticks]
        assert values == sorted(values) and all(v == int(v) for v in values)
        step = values[1] - values[0]
        assert 30 * step / (11.4 + 1.2) >= 3
        assert values[0] >= -1.2 and values[-1] <= 11.4

    def test_metres_are_labelled_in_the_readers_unit_and_placed_in_feet(self):
        ticks = _ticks(-1.0, 12.0, 30, _runtime(metric=True))
        for feet, metres in ticks:
            assert feet * 0.3048 == pytest.approx(metres)
        assert all(metres * 2 == int(metres * 2) for _feet, metres in ticks)

    def test_a_short_chart_takes_a_coarser_step(self):
        tall = _ticks(0, 12, 40, _runtime())
        short = _ticks(0, 12, 8, _runtime())
        assert len(short) < len(tall)


class TestTheHeadersWords:
    def test_the_highest_water_measured_so_far_is_named_with_its_day(self, predicted):
        observed = _observed(predicted)
        day = max(observed, key=lambda d: observed[d][1])
        words = summary(2026, predicted, observed, _runtime(), TODAY)
        assert words.startswith("highest ")
        assert f"{observed[day][1]:.1f}′" in words
        assert words.endswith(f"{day:%b} {day.day}")

    def test_a_year_with_nothing_measured_gives_the_highest_predicted(self, predicted):
        day = max(predicted, key=lambda d: predicted[d][1])
        assert f"{predicted[day][1]:.1f}′" in summary(2026, predicted, {}, _runtime(), TODAY)

    def test_another_years_measurements_do_not_count(self, predicted):
        last_year = {date(2025, 3, 3): (0.0, 99.0)}
        assert "99.0" not in summary(2026, predicted, last_year, _runtime(), TODAY)

    def test_nothing_known_is_no_words(self):
        assert summary(2026, {}, {}, _runtime(), TODAY) == ""


class TestThePage:
    def test_the_frame_fills_the_window(self, predicted):
        for cols, rows in ((110, 40), (80, 24), (60, 16), (200, 60)):
            lines, _ = _frame(predicted, _observed(predicted), 12.0, cols, rows)
            assert len(lines) == rows, (cols, rows)
            assert max(visible_len(line) for line in lines) <= cols, (cols, rows)

    def test_the_months_run_under_the_chart_and_the_heights_down_its_side(self, predicted):
        lines, _ = _frame(predicted)
        assert [m for m in ("Jan", "Apr", "Jul", "Oct", "Dec") if m in lines[-2]] == [
            "Jan", "Apr", "Jul", "Oct", "Dec"]
        labels = [m.group(1) for line in lines[2:-2] if (m := re.match(r" *(-?\d+)′ ", line))]
        assert len(labels) >= 3 and labels == sorted(labels, key=int, reverse=True)

    def test_the_new_and_full_moons_are_marked_above_it(self, predicted):
        lines, _ = _frame(predicted)
        marks = lines[1].split()
        assert 24 <= len(marks) <= 26          # twelve or thirteen of each

    def test_the_frame_is_drawn_empty_while_the_year_loads(self, predicted):
        loaded, _ = _frame(predicted)
        loading, _ = _frame({})
        assert len(loading) == len(loaded)
        assert loading[-2].split() == loaded[-2].split()       # the months

    def test_the_gauges_pen_stops_at_yesterday(self, predicted):
        # a gauge that measured just what was predicted leaves the scale alone
        lines, _ = _frame(predicted, _observed(predicted, lift=0.0))
        without, _ = _frame(predicted)
        # the field is half-blocks and the datum a dotted line; the pen
        # is braille over them, two traces the chart's width so far
        pen = len(BRAILLE.findall("\n".join(lines[2:-2])))
        assert pen > len(BRAILLE.findall("\n".join(without[2:-2]))) + 50
        # and November and December are as they would be with no gauge
        assert [line[-12:] for line in lines[2:-2]] == [line[-12:] for line in without[2:-2]]
        assert [line[:60] for line in lines[2:-2]] != [line[:60] for line in without[2:-2]]

    def test_a_metric_reader_has_metres_down_the_side(self, predicted):
        lines, _ = _frame(predicted, metric=True)
        assert any(re.match(r" *-?\d+(\.\d)?m ", line) for line in lines[2:-2])


class TestTheFloodStage:
    def test_the_stage_is_a_dotted_line_named_at_its_right_end(self, predicted):
        lines, _ = _frame(predicted, flood=12.0)
        named = [line for line in lines if "flood stage" in line]
        assert len(named) == 1
        assert named[0].rstrip().endswith("flood stage") or named[0].rstrip()[-1] != "e"
        assert BRAILLE.search(named[0])

    def test_no_stage_is_no_line(self, predicted):
        lines, _ = _frame(predicted)
        assert "flood stage" not in "\n".join(lines)

    def test_a_stage_far_above_the_water_is_left_off_the_chart(self, predicted):
        lines, _ = _frame(predicted, flood=40.0)
        assert "flood stage" not in "\n".join(lines)
        # and the scale is not stretched to reach it
        assert not any(re.match(r" *[34]\d′ ", line) for line in lines)

    def test_a_name_in_a_wide_script_keeps_its_row_the_charts_width(self, predicted):
        lines, _ = _frame(predicted, flood=12.0, lang="ja", metric=True)
        named = next(line for line in lines if "浸水が始まる潮位" in line)
        widths = {visible_len(line) for line in lines[2:-2]}
        assert widths == {visible_len(named)}

    def test_a_name_with_combining_marks_keeps_its_row_the_charts_width(self, predicted):
        lines, _ = _frame(predicted, flood=12.0, lang="th", metric=True)
        assert len({visible_len(line) for line in lines[2:-2]}) == 1

    def test_water_over_the_stage_is_in_the_alert_ink(self, predicted, truecolor):
        observed = _observed(predicted, lift=3.0)              # a year of flooding
        raw, _ = _frame(predicted, observed, flood=12.0, raw=True)
        assert fg(*year_view.FLOOD_RGB) in "\n".join(raw)
        calm, _ = _frame(predicted, _observed(predicted, lift=0.0), flood=20.0, raw=True)
        assert fg(*year_view.FLOOD_RGB) not in "\n".join(calm)


class TestThePointer:
    def test_hover_reuses_lunar_dates_without_changing_the_frame(self, predicted):
        from linecast.moon import calendar

        year_view._moon_phases.cache_clear()
        with patch.object(calendar, "principal_phase_days",
                          wraps=calendar.principal_phase_days) as phases:
            _frame(predicted, mouse=(30, 10))
            assert phases.call_count == 12
            cached = _frame(predicted, mouse=(40, 12), raw=True)
            assert phases.call_count == 12
            year_view._moon_phases.cache_clear()
            assert _frame(predicted, mouse=(40, 12), raw=True) == cached

    def _column(self, lines, day_of_year, cols=110):
        # January's name starts where the chart does
        gutter = len(lines[-2]) - len(lines[-2].lstrip())
        width = cols - gutter - 1
        return gutter + 1 + int(day_of_year * width / 365)

    def test_the_chip_gives_the_predicted_and_the_measured_water(self, predicted):
        observed = _observed(predicted)
        lines, _ = _frame(predicted, observed)
        _lines, chip = _frame(predicted, observed, mouse=(self._column(lines, 100), 10))
        assert re.search(r"Apr \d+", chip)
        assert re.search(r"predicted ▲ \d+\.\d′  ▼ -?\d+\.\d′", chip)
        assert re.search(r"measured ▲ \d+\.\d′  ▼ -?\d+\.\d′", chip)

    def test_a_day_not_yet_measured_has_the_prediction_alone(self, predicted):
        observed = _observed(predicted)
        lines, _ = _frame(predicted, observed)
        _lines, chip = _frame(predicted, observed, mouse=(self._column(lines, 330), 10))
        assert "predicted" in chip and "measured" not in chip

    def test_a_models_water_is_called_modeled(self, predicted):
        observed = _observed(predicted)
        lines, _ = _frame(predicted, observed)
        _lines, chip = _frame(predicted, observed, mouse=(self._column(lines, 100), 10),
                              observed_name="modeled")
        assert "modeled ▲" in chip and "measured" not in chip

    def test_a_column_of_several_days_names_its_span(self, predicted):
        lines, _ = _frame(predicted, cols=60)
        _lines, chip = _frame(predicted, cols=60, mouse=(self._column(lines, 100, 60), 10))
        assert " – " in chip

    def test_nothing_floats_when_the_pointer_is_off_the_chart(self, predicted):
        assert _frame(predicted, mouse=(2, 10))[1] == ""       # over the heights
        assert _frame(predicted, mouse=(50, 1))[1] == ""       # over the header


class TestAnotherYear:
    def test_lunar_dates_follow_the_year_and_station_time_zone(self):
        from linecast.moon import calendar

        year_view._moon_phases.cache_clear()
        with patch.object(calendar, "principal_phase_days",
                          wraps=calendar.principal_phase_days) as phases:
            for year, zone in ((2026, TZ), (2027, TZ),
                               (2026, ZoneInfo("Pacific/Auckland"))):
                cached = year_view._moon_phases(year, zone)
                assert cached == year_view._moon_phases.__wrapped__(year, zone)
            assert phases.call_count == 72

    def test_a_year_that_is_not_this_one_has_no_line_for_today(self, predicted):
        shifted = {day.replace(year=2027) if (day.month, day.day) != (2, 29) else day: v
                   for day, v in predicted.items()}
        this, _ = _frame(predicted, raw=True)
        other, _ = _frame(shifted, raw=True, year=2027)
        assert "│" in "\n".join(this) and "│" not in "\n".join(other)

    def test_a_leap_year_has_its_extra_day(self):
        leap = {date(2028, 1, 1) + timedelta(days=k): (0.0, 9.0) for k in range(366)}
        lines, _ = _frame(leap, year=2028)
        assert len(lines) == 40 and "Dec" in lines[-2]
