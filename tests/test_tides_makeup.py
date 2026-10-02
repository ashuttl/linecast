"""The tides' makeup view: the tide taken apart, and the page it is set on.

The tide here is made up: a harbour with constants near Portland,
Maine's, predicted on the device, so the figures the view should show
are known before it is asked.
"""

import re
from datetime import date, datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from linecast._runtime import TidesRuntime
from linecast.terminal.textwidth import visible_len
from linecast.tides import harmonic, makeup, view
from linecast.tides.common import computed_hilo
from linecast.tides.view import _render_header_line
from linecast.tides.makeup import (
    Makeup, _fitted, _flowed, _placed, _spread, _turns, render_makeup, sky_marks,
)

TZ = ZoneInfo("America/New_York")
FT = 0.3048
# (name, amplitude in metres, phase): near Portland's
HARBOUR = [("M2", 1.40, 100.0), ("S2", 0.21, 135.0), ("N2", 0.28, 70.0),
           ("K1", 0.14, 200.0), ("O1", 0.11, 180.0), ("P1", 0.046, 198.0)]
LAT = 43.66
OCT = date(2026, 10, 1)
NOW = datetime(2026, 10, 1, 9, 0, tzinfo=TZ)
ANSI = re.compile(r"\x1b\[[0-9;]*m")


def _turns_of_the_year():
    return computed_hilo(harmonic.Tide(HARBOUR), date(2026, 1, 1), date(2026, 12, 31), TZ)


@pytest.fixture(scope="module")
def harbour():
    return Makeup(_turns_of_the_year(), LAT)


def _made(tide, first=OCT):
    return (tide, tide.month(first, TZ), tide.year(first.year), tide.long(2026),
            sky_marks(first, TZ), 2026)


def _runtime(lang="en", metric=False):
    return TidesRuntime(live=True, icons="nerd", lang=lang, metric=metric, oneline=False,
                        use_24h=metric)


def _frame(made, cols=110, rows=41, lang="en", metric=False, first=OCT, mouse=None):
    """The view's lines without their inks, and what floats over them."""
    runtime = _runtime(lang, metric)

    def header(right):
        return _render_header_line(cols, "Portland, ME", runtime, location_menu=True, right=right)

    with (patch.object(makeup, "get_terminal_size", return_value=(cols, rows)),
          patch.object(view, "_pill_width")):
        out = render_makeup(first, made, runtime, header=header,
                            footer=" NOAA", station_tz=TZ, now_local=NOW, mouse_pos=mouse)
    body, _, floating = out.partition("\x00")
    return [ANSI.sub("", line) for line in body.split("\n")], ANSI.sub("", floating)


def _row(lines, text):
    """The first line that holds *text*."""
    return next(line for line in lines if text in line)


# ---------------------------------------------------------------------------
# The tide taken apart
# ---------------------------------------------------------------------------
class TestTheTable:
    """The left column's figures come back out of a year of highs and lows."""

    def test_each_cause_has_the_height_the_harbour_was_given(self, harbour):
        amp = dict((name, a) for name, a, _phase in HARBOUR)
        want = {"makeup_moon": amp["M2"], "makeup_sun": amp["S2"],
                "makeup_distance": amp["N2"],
                # the once-a-day rows share K1, 68% of it the Moon's
                "makeup_moon_tilt": amp["O1"] + 0.68 * amp["K1"],
                "makeup_sun_tilt": amp["P1"] + 0.32 * amp["K1"]}
        got = {key: a * FT for key, a, _source in harbour.twice + harbour.once}
        assert list(got) == list(want)
        for key, metres in want.items():
            # a fit to the turns is good to a few percent, or a centimetre
            assert got[key] == pytest.approx(metres, rel=0.04, abs=0.01), key

    def test_the_factor_is_the_height_over_the_ideal_oceans(self, harbour):
        # M2 raises 0.2423 m before the latitude's share, cos² of it
        # for a twice-a-day tide; N2, the Moon's distance, 0.0464 m
        assert harbour.gain["M2"] == pytest.approx(11.0, rel=0.04)
        assert harbour.gain["N2"] == pytest.approx(11.5, rel=0.06)
        assert harbour.gain["S2"] == pytest.approx(3.56, rel=0.06)
        # a once-a-day tide takes sin of twice the latitude, near 1 here
        assert harbour.gain["O1"] == pytest.approx(1.09, rel=0.08)
        assert harbour.gain["P1"] == pytest.approx(0.98, rel=0.12)

    def test_every_row_names_a_constituent_with_an_ideal_height(self, harbour):
        for _key, _amp, source in harbour.twice + harbour.once:
            assert source in makeup.EQUILIBRIUM_M

    def test_a_station_with_no_latitude_has_no_factors(self):
        assert Makeup(_turns_of_the_year(), None).gain == {}

    def test_the_latitude_that_gives_nothing_to_compare_gives_no_factor(self):
        turns = _turns_of_the_year()
        # on the equator the once-a-day pull is nil, at the pole both are
        assert sorted(Makeup(turns, 0.0).gain) == ["M2", "N2", "S2"]
        assert Makeup(turns, 89.0).gain == {}
        # and south of the equator is the same as north of it
        assert Makeup(turns, -LAT).gain.keys() == Makeup(turns, LAT).gain.keys()

    def test_turns_that_will_not_fit_are_refused(self):
        with pytest.raises(ValueError):
            Makeup([], LAT)


class TestTheStrips:
    """What each strip draws: the part's size through the span."""

    def test_the_month_is_four_readings_a_day_for_each_part(self, harbour):
        semi, diur = harbour.month(OCT, TZ)
        assert len(semi) == len(diur) == 31 * 4 + 1
        assert len(harbour.month(date(2027, 2, 1), TZ)[0]) == 28 * 4 + 1

    def test_the_twice_a_day_part_beats_between_springs_and_neaps(self, harbour):
        semi, _diur = harbour.month(OCT, TZ)
        m2, s2, n2 = (a for _key, a, _s in harbour.twice)
        # never more than its causes pulling together, nor less than
        # the Moon's with the other two against it (a few percent's
        # grace: the fit finds a little of the smaller constituents too)
        assert max(semi) <= (m2 + s2 + n2) * 1.03
        assert min(semi) >= (m2 - s2 - n2) * 0.95
        # and from springs to neaps it moves by twice the Sun's part at least
        assert max(semi) - min(semi) > 2 * s2

    def test_the_year_is_a_reading_a_day(self, harbour):
        assert [len(part) for part in harbour.year(2026)] == [365, 365]
        assert [len(part) for part in harbour.year(2028)] == [366, 366]
        assert harbour.year(2026) is harbour.year(2026)   # and kept

    def test_the_nineteen_years_run_from_ten_before(self, harbour):
        semi, diur = harbour.long(2026)
        assert len(semi) == len(diur)
        # a reading every thirty days from 2016 through 2034
        assert len(semi) == pytest.approx(19 * 365.25 / 30, abs=3)
        assert harbour.long(2026) is harbour.long(2026)

    def test_the_once_a_day_part_follows_the_moons_long_swing(self, harbour):
        semi, diur = harbour.long(2026)

        def year_of(values, pick):
            return 2016 + 19 * values.index(pick(values)) / (len(values) - 1)
        # The Moon's swing north and south was widest in 2025: the
        # once-a-day tide is largest then, and the twice-a-day smallest
        assert year_of(diur, max) == pytest.approx(2025.2, abs=1.0)
        assert year_of(semi, min) == pytest.approx(2025.2, abs=1.5)
        # and it moves the once-a-day part far more, as a share
        swing = [(max(part) - min(part)) / min(part) for part in (semi, diur)]
        assert swing[0] == pytest.approx(0.07, abs=0.03)
        assert swing[1] == pytest.approx(0.30, abs=0.08)


class TestTheSkysMarks:
    def test_the_suns_year_turns_at_the_equinoxes_and_solstices(self):
        marks = sky_marks(OCT, TZ)["sun"]
        assert [kind for _f, kind in marks] == ["0", "N", "0", "S"]
        days = [date(2026, 1, 1) + timedelta(days=round(f * 365)) for f, _kind in marks]
        wanted = [date(2026, 3, 20), date(2026, 6, 21), date(2026, 9, 23), date(2026, 12, 21)]
        for day, want in zip(days, wanted):
            assert abs((day - want).days) <= 1

    def test_the_moon_goes_north_and_south_about_twice_a_month(self):
        marks = sky_marks(OCT, TZ)["moon"]
        kinds = [kind for _f, kind in marks]
        # north, the equator, south, the equator, in turn
        assert 4 <= len(kinds) <= 6
        for a, b in zip(kinds, kinds[1:]):
            assert (a == "0") != (b == "0")
        assert all(0 <= f < 1 for f, _kind in marks)

    def test_the_month_has_its_four_phases_and_its_perigees(self):
        marks = sky_marks(OCT, TZ)
        assert 4 <= len(marks["phases"]) <= 5
        assert all(0 <= f < 1 for f, _when in marks["phases"])
        # The Moon is nearest twice this month, an anomalistic month
        # apart: counted back from the perigee of 24 December 2026, on
        # about the 2nd and the 30th
        first, second = (f * 31 for f in marks["near"])
        assert first == pytest.approx(1.3, abs=1.0)
        assert second - first == pytest.approx(27.55, abs=1.0)

    def test_turns_are_read_from_a_declination(self):
        # a swing up through nothing to the north, back, and to the south
        dec = [-1, 0.5, 2, 3, 2, 0.5, -1, -2, -3, -2]
        assert [kind for _f, kind in _turns(dec, 8)] == ["0", "N", "0", "S"]
        assert _turns([1, 1, 1, 1], 2) == []


# ---------------------------------------------------------------------------
# Setting marks on a line
# ---------------------------------------------------------------------------
class TestPlacing:
    def test_a_mark_is_centred_on_its_place(self):
        assert _placed(11, [(0.5, "x")]) == "     x     "
        assert _placed(10, [(0.0, "ab"), (1.0, "cd")]) == "ab      cd"

    def test_a_mark_that_would_touch_another_is_left_out(self):
        assert _placed(10, [(0.3, "aa"), (0.45, "bb")]).split() == ["aa"]
        assert _placed(10, [(0.3, "aa"), (0.8, "bb")]).split() == ["aa", "bb"]

    def test_a_mark_set_beside_goes_in_the_nearest_free_cell(self):
        # the Moon's nearest approach on the day of a phase is worth both
        line = _placed(11, [(0.5, "O")], [(0.5, "p")])
        assert line.strip() in ("Op", "pO")

    def test_a_wide_glyph_takes_two_columns_and_moves_nothing_after_it(self):
        plain = _placed(20, [(0.2, "N"), (0.8, "0")])
        wide = _placed(20, [(0.2, "北"), (0.8, "0")])
        assert visible_len(wide) == 20
        assert wide.index("0") + 1 == plain.index("0")   # one glyph, two columns

    def test_a_mark_with_combining_letters_moves_nothing_after_it(self):
        # Thai's north has a vowel that rides over its consonant
        line = _placed(30, [(0.2, "เหนือ"), (0.8, "0")])
        assert visible_len(line) == 30
        assert visible_len(line[:line.index("0")]) == _placed(30, [(0.8, "0")]).index("0")

    def test_two_marks_that_would_touch_are_moved_apart(self):
        assert _spread(16, [(0.45, "▼ 4.5′"), (0.95, "▲ 4.9′")]) == "   ▼ 4.5′ ▲ 4.9′"
        # with room, each stays where it falls
        line = _spread(40, [(0.25, "aa"), (0.75, "bb")])
        assert (line.index("aa"), line.index("bb")) == (9, 29)

    def test_marks_keep_their_order_however_they_are_given(self):
        assert _spread(16, [(0.9, "bb"), (0.1, "aa")]).split() == ["aa", "bb"]

    def test_a_line_too_short_for_its_marks_holds_none(self):
        assert _spread(12, [(0.4, "▼ 1.38m"), (0.9, "▲ 1.49m")]) is None
        assert _spread(15, [(0.4, "▼ 1.38m"), (0.9, "▲ 1.49m")]) == "▼ 1.38m ▲ 1.49m"

    def test_the_legend_flows_to_the_width(self):
        items = ["one two", "three", "four five six"]
        assert _flowed(items, 40) == ["one two   three   four five six"]
        assert _flowed(items, 20) == ["one two   three", "four five six"]
        # and an entry wider than the window is left out
        assert _flowed(items, 8) == ["one two", "three"]


# ---------------------------------------------------------------------------
# What a window keeps
# ---------------------------------------------------------------------------
class TestWhatFits:
    KEY = 4   # three sentences and a line of marks

    @staticmethod
    def _rows_needed(strip_rows, air, key, open_line):
        return (1 + 2 * (strip_rows + 2) + 1 + (key + 1 + open_line if key else 0)
                + (0 if air is None else 2 + air))

    def test_what_is_kept_always_fits(self):
        for room in range(12, 60):
            assert self._rows_needed(*_fitted(room, self.KEY)) <= room, room

    def test_a_taller_window_takes_nothing_away_but_a_strip_row_for_the_headline(self):
        before = _fitted(12, self.KEY)
        for room in range(13, 60):
            strip_rows, air, key, open_line = now = _fitted(room, self.KEY)
            assert key >= before[2], room
            assert open_line >= before[3], room
            assert (air is not None) >= (before[1] is not None), room
            if (air is None) == (before[1] is None):
                assert strip_rows >= before[0] or (air or 0) > (before[1] or 0), room
            before = now

    def test_the_ladder(self):
        assert _fitted(8, self.KEY) == (2, None, 0, False)     # not even the key
        assert _fitted(15, self.KEY) == (3, None, 2, False)    # the marks' line first
        assert _fitted(18, self.KEY) == (3, None, 4, False)    # then the whole key
        assert _fitted(23, self.KEY) == (6, None, 4, False)    # then the strips grow
        assert _fitted(24, self.KEY) == (6, None, 4, True)     # then the key's open line
        assert _fitted(25, self.KEY) == (5, 0, 4, True)        # the headline, closed up
        assert _fitted(27, self.KEY) == (5, 1, 4, True)
        assert _fitted(30, self.KEY) == (6, 2, 4, True)        # and everything
        assert _fitted(80, self.KEY) == (6, 2, 4, True)

    def test_a_key_cut_short_has_no_open_line(self):
        assert _fitted(16, self.KEY)[2:] == (3, False)


# ---------------------------------------------------------------------------
# The page
# ---------------------------------------------------------------------------
SIZES = [(110, 41), (94, 28), (80, 24), (72, 22), (60, 20), (140, 50)]


class TestThePage:
    @pytest.mark.parametrize("cols, rows", SIZES)
    @pytest.mark.parametrize("lang, metric", [("en", False), ("ja", True), ("fi", True),
                                              ("fa", True), ("th", True)])
    def test_the_frame_fills_the_window_and_no_more(self, harbour, cols, rows, lang, metric):
        lines, _floating = _frame(_made(harbour), cols, rows, lang, metric)
        assert len(lines) == rows
        assert max(visible_len(line) for line in lines) <= cols

    @pytest.mark.parametrize("cols, rows", SIZES)
    @pytest.mark.parametrize("lang, metric", [("en", False), ("ja", True), ("de", True)])
    def test_nothing_moves_when_the_figures_come(self, harbour, cols, rows, lang, metric):
        """While the tide is fetched the view draws the frame it will
        have: everything in the loading frame is where the loaded one
        has it."""
        loaded, _ = _frame(_made(harbour), cols, rows, lang, metric)
        loading, _ = _frame(None, cols, rows, lang, metric)
        assert len(loading) == len(loaded)
        for n, (full, empty) in enumerate(zip(loaded, loading)):
            for k, ch in enumerate(empty):
                assert ch == " " or full[k] == ch, (n, k, empty)

    def test_the_loading_frame_has_the_names_the_axes_and_the_key(self):
        lines, _ = _frame(None)
        text = "\n".join(lines)
        for wanted in ("What moves the tide here", "Twice a day", "The Moon's distance",
                       "Once a day", "The Sun's declination", "Oct 2026", "2016–2034",
                       "Each height is half", "over the equator"):
            assert wanted in text
        assert "×" not in text.replace("× compares", "")   # and no figures yet

    def test_a_roomy_window_has_everything(self, harbour):
        lines, _ = _frame(_made(harbour), 110, 41)
        head = lines.index(" What moves the tide here")
        assert lines[head + 1].strip() == "─" * len("What moves the tide here")
        assert lines[head + 2] == lines[head + 3] == ""       # two rows of air
        titles = lines[head + 4]
        assert [t for t in ("Oct 2026", "2026", "2016–2034") if t in titles] == [
            "Oct 2026", "2026", "2016–2034"]
        # the header keeps the top of the window and the footer the bottom
        assert "Portland, ME" in lines[0] and lines[-1] == " NOAA"
        assert "What moves the tide here" not in lines[0]

    def test_a_smaller_window_closes_the_headline_up_and_keeps_three_strips(self, harbour):
        lines, _ = _frame(_made(harbour), 94, 28)
        head = lines.index(" What moves the tide here")
        assert lines[head - 1] == ""                           # clear of the station
        assert "2016–2034" in lines[head + 2]                  # no air under the rule
        strip_rows = lines.index(_row(lines, "Once a day")) - lines.index(
            _row(lines, "Twice a day")) - 3
        assert strip_rows == 5

    def test_a_standard_terminal_keeps_two_strips_and_the_headline_in_the_header(self, harbour):
        lines, _ = _frame(_made(harbour), 80, 24)
        text = "\n".join(lines)
        assert "Portland, ME" in lines[0] and "What moves the tide here" in lines[0]
        assert text.count("What moves the tide here") == 1
        assert "Oct 2026" in text and "2016–2034" not in text
        assert "Each height is half" in text and "over the equator" in text

    def test_a_narrow_window_keeps_the_month_alone(self, harbour):
        lines, _ = _frame(_made(harbour), 60, 24)
        titles = _row(lines, "Oct 2026")
        assert titles.split() == ["Oct", "2026"]

    def test_the_two_tables_share_their_columns(self, harbour):
        lines, _ = _frame(_made(harbour))
        rows = [_row(lines, name) for name in ("The Moon ", "The Sun ", "The Moon's distance",
                                               "The Moon's declination", "The Sun's declination")]
        heights = [re.search(r"\d+\.\d′", row) for row in rows]
        assert len({m.end() for m in heights}) == 1            # set flush right, one column
        assert len({row.index("×") for row in rows}) == 1
        assert [m.group() for m in heights] == ["4.6′", "0.7′", "0.9′", "0.7′", "0.3′"]

    def test_every_cause_has_its_factor(self, harbour):
        lines, _ = _frame(_made(harbour))
        factors = [re.search(r"×[\d.]+", _row(lines, name)).group()
                   for name in ("The Moon ", "The Sun ", "The Moon's distance",
                                "The Moon's declination", "The Sun's declination")]
        # whole above three, a decimal place below
        assert factors[0] == "×11" and factors[2] in ("×11", "×12")
        assert all(re.fullmatch(r"×\d\.\d", f) for f in factors[3:])

    def test_a_station_with_no_latitude_has_a_table_without_factors(self):
        lines, _ = _frame(_made(Makeup(_turns_of_the_year(), None)))
        assert "×" not in _row(lines, "The Moon ")
        assert "4.6′" in _row(lines, "The Moon ")

    def test_metric_heights_are_metres_to_the_centimetre(self, harbour):
        lines, _ = _frame(_made(harbour), metric=True)
        assert re.search(r"1\.[34]\dm\s+×11", _row(lines, "The Moon "))

    def test_the_key_is_a_sentence_to_a_line_where_they_fit(self, harbour):
        lines, _ = _frame(_made(harbour))
        at = lines.index(" Each height is half the low-to-high swing from that cause.")
        assert lines[at + 1].startswith(" × compares it with")
        assert lines[at + 2].startswith(" The sea's shape and depth")
        assert lines[at + 3] == ""                             # the open line
        assert lines[at + 4].endswith("0 over the equator")

    def test_in_a_narrow_window_the_sentences_wrap_as_one_paragraph(self, harbour):
        lines, _ = _frame(_made(harbour), 56, 40)
        at = next(n for n, line in enumerate(lines) if line.startswith(" Each height"))
        paragraph = []
        while lines[at]:
            paragraph.append(lines[at].strip())
            at += 1
        assert len(paragraph) == 4
        assert " ".join(paragraph).endswith("how large it becomes here.")
        assert "× compares" in " ".join(paragraph)

    def test_the_nineteen_years_are_marked_with_their_least_and_most(self, harbour):
        lines, _ = _frame(_made(harbour))
        twice, once = [line for line in lines if "▼" in line and "▲" in line]
        # the twice-a-day part was least about 2024 and is most in 2033;
        # the once-a-day part the other way about
        assert twice.index("▼") < twice.index("▲")
        assert once.index("▲") < once.index("▼")
        assert re.search(r"▼ \d\.\d′\s+▲ \d\.\d′", twice)

    def test_the_axes_carry_the_skys_marks(self, harbour):
        lines, _ = _frame(_made(harbour))
        twice_marks, once_marks = [line for line in lines if "▼" in line and "▲" in line]
        assert " p" in twice_marks or "p " in twice_marks      # the Moon's nearest approach
        for letter in ("N", "S", "0"):
            assert letter in once_marks.split("▲")[0]

    def test_persian_names_the_gregorian_months(self, harbour):
        lines, _ = _frame(_made(harbour), lang="fa", metric=True)
        assert "ژانویه" in "\n".join(lines)

    def test_another_month_is_another_strip(self, harbour):
        lines, _ = _frame(_made(harbour, date(2027, 2, 1)), first=date(2027, 2, 1))
        titles = _row(lines, "Feb 2027")
        assert "2027" in titles.replace("Feb 2027", "") and "2016–2034" in titles
        assert "22" in _row(lines, " 15 ") and "29" not in _row(lines, " 15 ")


class TestThePointer:
    def _strip_cell(self, lines, title, part=0, row=1):
        """A terminal cell (1-based) inside the strip under *title*."""
        col = _row(lines, "Oct 2026").index(title) + 4
        top = lines.index(_row(lines, ("Twice a day", "Once a day")[part]))
        return col + 1, top + 1 + row

    def test_a_month_strip_names_the_day_and_the_parts_size(self, harbour):
        made = _made(harbour)
        lines, _ = _frame(made)
        _lines, chip = _frame(made, mouse=self._strip_cell(lines, "Oct 2026"))
        assert "Twice a day" in chip and re.search(r"Oct \d+", chip)
        assert re.search(r"\d\.\d′", chip)

    def test_the_lower_strips_speak_for_the_once_a_day_part(self, harbour):
        made = _made(harbour)
        lines, _ = _frame(made)
        _lines, chip = _frame(made, mouse=self._strip_cell(lines, "Oct 2026", part=1))
        assert "Once a day" in chip

    def test_the_nineteen_years_name_the_year(self, harbour):
        made = _made(harbour)
        lines, _ = _frame(made)
        _lines, chip = _frame(made, mouse=self._strip_cell(lines, "2016–2034"))
        assert re.search(r"20[12]\d", chip)

    def test_nothing_floats_over_the_table_or_an_empty_frame(self, harbour):
        made = _made(harbour)
        lines, _ = _frame(made)
        top = lines.index(_row(lines, "Twice a day"))
        assert _frame(made, mouse=(5, top + 2))[1] == ""
        assert _frame(None, mouse=self._strip_cell(lines, "Oct 2026"))[1] == ""
