"""Tests for what the charts share: the hour ticks, and a year's columns."""

from linecast.terminal.chart import (
    day_span, month_axis, month_starts, tick_canvas, tick_interval,
)


def test_wider_charts_label_every_few_hours():
    assert [tick_interval(w) for w in (39, 40, 79, 80, 139, 140)] == [6, 4, 4, 3, 3, 2]


def test_ticks_go_left_to_right_and_a_crowded_label_is_left_out():
    items = [(0, "12a", True), (3, "3a", False), (6, "6a", False)]
    # "│12a" ends at column 4, so "╵3a" at 3 is dropped and "╵6a" stands
    assert tick_canvas(items, 10) == "│12a  ╵6a "


def test_a_label_that_would_run_off_the_edge_is_left_out():
    assert tick_canvas([(8, "10p", False)], 10) == " " * 10


def test_the_pointer_wins_the_hairline_over_now_on_an_empty_column():
    assert tick_canvas([], 5, hover_col=1, now_col=3) == " │   "
    assert tick_canvas([], 5, now_col=3) == "   │ "
    assert tick_canvas([(0, "1a", False)], 5, hover_col=1) == "╵1a  "


def test_the_months_start_where_the_calendar_puts_them():
    starts, n = month_starts(2026)
    assert (starts[:3], n) == ([0, 31, 59], 365)
    assert month_starts(2028)[0][2] == 60 and month_starts(2028)[1] == 366


def test_every_day_of_the_year_falls_in_one_column():
    for width in (40, 113, 365, 500):
        days = [k for i in range(width) for k in day_span(i, width, 365)]
        # a chart wider than the year shows a day in more than one column
        assert sorted(set(days)) == list(range(365))
        if width <= 365:
            assert days == list(range(365))


def test_the_month_axis_puts_each_label_at_its_months_start():
    starts, n = month_starts(2026)
    labels = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    axis = month_axis(labels, starts, n, 73, "<", ">", this_month=1)
    plain = axis.replace("<", "").replace(">", "")
    assert plain.index("Feb") == int(31 / 365 * 73)
    # the current month alone is in the first ink
    assert "<F<e<b" in axis and ">J>a>n" in axis


def test_a_whole_label_is_left_out_of_a_month_too_narrow_for_it():
    starts, n = month_starts(2026)
    labels = ["January"] + ["x"] * 11
    assert "January"[:3] in month_axis(labels, starts, n, 48, "", "")
    assert "J" not in month_axis(labels, starts, n, 48, "", "", whole=True)
