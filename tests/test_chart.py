"""Tests for the hour ticks the time charts share."""

from linecast.terminal.chart import tick_canvas, tick_interval


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
