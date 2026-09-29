"""Tests for the floating chrome's placing and centring."""

from linecast.terminal import box


class TestPlace:
    def test_each_line_goes_on_its_own_row_from_the_same_column(self):
        assert box.place(["ab", "cd"], 3, 7) == "\033[3;7Hab\033[4;7Hcd"

    def test_the_address_is_the_form_bidi_looks_for(self):
        from linecast.terminal.bidi import _CUP
        assert _CUP.match(box.at(12, 40))


class TestCentre:
    def test_the_odd_row_and_column_go_below_and_right(self):
        assert box.centre(11, 11, 4, 4) == (4, 4)
        assert box.centre(10, 10, 4, 4) == (4, 4)

    def test_a_box_bigger_than_the_screen_starts_at_the_first(self):
        assert box.centre(10, 5, 40, 20) == (1, 1)
