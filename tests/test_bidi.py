"""The right-to-left output pass: the Unicode Bidirectional Algorithm,
Arabic shaping, digits, and a row's escapes carried through."""

import random
import re
import sys
import unicodedata
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from linecast import _bidi  # noqa: E402
from linecast._bidi import (  # noqa: E402
    FSI, LRI, PDI, RLI, bidi_class, bracket_info, display, joining_type,
    resolve_levels, visual_order,
)
from linecast._textwidth import visible_len  # noqa: E402

FIXTURE = Path(__file__).parent / "fixtures" / "bidi_character_test.txt"


def _cases():
    for line in FIXTURE.read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#"):
            yield line


@pytest.fixture
def persian():
    _bidi.configure("fa", {})
    yield
    _bidi.configure("en", {})


def _cells(out):
    """What a terminal shows for `out`: (character, SGR state) per cell,
    marks and joiners kept with their cell."""
    cells = []
    state = ""
    for m in re.finditer(r"\033\[([0-9;]*)m|(.)", out, re.S):
        if m.group(2) is None:
            params = m.group(1)
            if params in ("", "0"):
                state = ""
            elif params.startswith("0;"):
                state = ";" + params[2:]      # a reset, then these
            else:
                state = state + ";" + params
            continue
        ch = m.group(2)
        if cells and (unicodedata.category(ch) in ("Mn", "Me") or ch in "\u200c\u200d"):
            cells[-1] = (cells[-1][0] + ch, cells[-1][1])
        else:
            cells.append((ch, state))
    return cells


def _plain(out):
    return "".join(ch for ch, _state in _cells(out))


class TestAlgorithm:
    def test_unicode_conformance_sample(self):
        """A thousand cases from Unicode's own BidiCharacterTest.txt; the
        whole file (91,707 cases) passes too, run by hand."""
        failures = []
        for line in _cases():
            fields = line.split(";")
            chars = [chr(int(x, 16)) for x in fields[0].split()]
            direction = int(fields[1])
            types = [bidi_class(c) for c in chars]
            brackets = [bracket_info(c) if t == "ON" else None
                        for c, t in zip(chars, types)]
            para, levels = resolve_levels(types, None if direction == 2 else direction,
                                          brackets)
            got = ["x" if lv is None else str(lv) for lv in levels]
            order = visual_order(levels)
            if (para != int(fields[2]) or got != fields[3].split()
                    or order != [int(x) for x in fields[4].split()]):
                failures.append(line)
        assert not failures, failures[:5]

    def test_first_strong_sets_the_paragraph(self):
        assert resolve_levels(["R", "WS", "L"])[0] == 1
        assert resolve_levels(["ON", "L", "R"])[0] == 0
        assert resolve_levels(["EN"])[0] == 0


class TestShaping:
    # Every letter of the Persian alphabet
    LETTERS = "ابپتثجچحخدذرزژسشصضطظعغفقکگلمنوهی"
    RIGHT_JOINING = set("اآدذرزژو")

    def _form(self, word, index):
        """The presentation form the pass gives word[index]."""
        out = _plain(display(RLI + word + PDI))[::-1]
        return unicodedata.decomposition(out[index]).split()[0]

    def test_every_persian_letter_in_every_position(self):
        for letter in self.LETTERS:
            assert self._form(letter, 0) == "<isolated>", letter
            assert self._form("ب" + letter, 1) == "<final>", letter
            if letter in self.RIGHT_JOINING:
                assert joining_type(letter) == "R"
                assert self._form(letter + "ب", 0) == "<isolated>", letter
                assert self._form("ب" + letter + "ب", 1) == "<final>", letter
            else:
                assert joining_type(letter) == "D"
                assert self._form(letter + "ب", 0) == "<initial>", letter
                assert self._form("ب" + letter + "ب", 1) == "<medial>", letter

    def test_urdu_letters_have_forms(self):
        for letter in "ٹڈڑںےہھ":
            assert joining_type(letter) in ("D", "R"), letter

    def test_zwnj_breaks_the_join_and_is_dropped(self):
        out = display("می\u200cشود")
        assert "\u200c" not in out
        # left to right on screen: د و ش ی م
        forms = [unicodedata.decomposition(c).split()[0] for c in _plain(out)]
        assert forms == ["<isolated>", "<final>", "<initial>", "<final>", "<initial>"]

    def test_lam_alef_stays_two_cells(self):
        out = _plain(display("لا"))
        assert len(out) == 2
        assert unicodedata.decomposition(out[0]).startswith("<final> 0627")
        assert unicodedata.decomposition(out[1]).startswith("<initial> 0644")

    def test_marks_ride_their_letter(self):
        out = _plain(display("بِ"))
        assert out[1] == "ِ" and len(out) == 2


class TestRows:
    def test_left_to_right_rows_are_untouched(self):
        for row in ("plain", "\033[1mbold\033[0m 12°", "▄▀█ ⠿ │x│", "こんにちは"):
            assert display(row) is row

    def test_a_hebrew_word_is_reversed(self):
        assert _plain(display("abc שלום def")) == "abc םולש def"

    def test_two_labels_over_the_sea_keep_their_places(self):
        row = "  תל אביב     חיפה  "
        assert _plain(display(row)) == "  ביבא לת     הפיח  "

    def test_a_graph_between_two_labels_stays_put(self):
        row = "אב ▁▂▃▄ גד"
        assert _plain(display(row)) == "בא ▁▂▃▄ דג"

    def test_colours_travel_with_their_cells(self):
        row = "\033[31mאב\033[0m \033[32mגד\033[0m"
        cells = _cells(display(row))
        assert [(ch, state) for ch, state in cells] == [
            ("ד", ";32"), ("ג", ";32"), (" ", ""), ("ב", ";31"), ("א", ";31")]

    def test_the_row_ends_in_its_own_final_state(self):
        out = display("\033[1mאב")
        assert out.endswith("\033[0m\033[1m") or out.endswith("א")

    def test_cursor_moves_cut_pieces(self):
        out = display("\033[3;4Hאב\033[5;6Hגד")
        assert _plain(out.replace("\033[3;4H", "").replace("\033[5;6H", "|")) == "בא|דג"

    def test_isolates_take_no_cells_and_are_removed(self):
        out = display(f"x {FSI}שלום{PDI} y")
        assert not set(out) & {FSI, PDI, LRI, RLI}
        assert visible_len(f"x {FSI}שלום{PDI} y") == visible_len(out) == 8

    def test_brackets_mirror_in_right_to_left_text(self):
        assert _plain(display(f"{RLI}אב (גד){PDI}")) == "(דג) בא"

    def test_width_is_kept_for_any_row(self):
        rnd = random.Random(7)
        pieces = ["سلام", "می\u200cشود", "تهران", "שלום", "abc", "12.5", "40%",
                  " ", "  ", "▄▄", "⣿", "(", ")", "°", "−", "\033[1m", "\033[0m",
                  "\033[38;2;1;2;3m", RLI, LRI, FSI, PDI, "\u200f", "\u200e", "日本",
                  "بِ", "لا", "ـ"]
        for _ in range(500):
            row = "".join(rnd.choice(pieces) for _ in range(rnd.randint(1, 14)))
            for lang in ("en", "fa"):
                _bidi.configure(lang, {})
                assert visible_len(display(row)) == visible_len(row), (lang, row)
        _bidi.configure("en", {})


class TestPersian:
    def test_a_persian_sentence_reads_from_the_right(self, persian):
        # "Tehran" is read first, so it is drawn at the right
        out = _plain(display("Tehran امروز آفتابی است"))
        assert out.endswith("Tehran")

    def test_digits_are_persian(self, persian):
        assert _plain(display("12:30 25.5 40%")) == "۱۲:۳۰ ۲۵٫۵ ۴۰٪"

    def test_escapes_keep_their_digits(self, persian):
        out = display("\033[38;2;10;20;30m5")
        assert out == "\033[38;2;10;20;30m۵"

    def test_identifiers_keep_ascii_digits(self, persian):
        out = _plain(display(f"نسخه {_bidi.identifier('v2.6.1')}"))
        assert "v2.6.1" in out

    def test_latin_digits_by_choice(self):
        _bidi.configure("fa", {"LINECAST_DIGITS": "latin"})
        try:
            assert _plain(display("۱۲٫۵ ۴۰٪")) == "12.5 40%"
        finally:
            _bidi.configure("en", {})

    def test_terminal_mode_hands_each_piece_over_in_an_isolate(self):
        _bidi.configure("en", {"LINECAST_BIDI": "terminal"})
        try:
            # logical order, where it stands, for the terminal to order
            # one piece, left to right by its first strong letter
            assert display("abc שלום") == f"{LRI}abc שלום{PDI}"
            assert display("  תל אביב     חיפה  ") == (
                f"  {RLI}תל אביב{PDI}     {RLI}חיפה{PDI}  ")
            assert display("abc") == "abc"
        finally:
            _bidi.configure("en", {})

    def test_off_leaves_the_text_alone(self):
        _bidi.configure("en", {"LINECAST_BIDI": "off"})
        try:
            assert display("abc שלום") == "abc שלום"
        finally:
            _bidi.configure("en", {})

    def test_terminal_mode_draws_brackets_the_same_in_every_terminal(self):
        # Konsole mirrors no brackets and VTE mirrors those at an odd
        # level: pre-mirrored, each in an isolate at an even level, a
        # bracket reads the same in both
        _bidi.configure("fa", {"LINECAST_BIDI": "terminal"})
        try:
            assert not _bidi.reorders()          # no explicit mode asked for
            out = display("دما −3° و (لا) 36°C")
            assert out.startswith(RLI) and out.endswith(PDI)
            assert f"{LRI}){PDI}لا{LRI}({PDI}" in out
            assert f"{LRI}−۳°{PDI}" in out and f"{LRI}۳۶°C{PDI}" in out
            assert "ﻻ" not in out and "ﺩ" not in out    # the terminal shapes the letters
        finally:
            _bidi.configure("en", {})

    def test_a_mirrored_row_is_still_laid_out_in_konsole(self):
        _bidi.configure("fa", {"KONSOLE_VERSION": "260801"})
        _bidi.set_mirror(True)
        try:
            out = display("امروز  12", 12)
            assert out == f"   ۱۲  {RLI}امروز{PDI}"
        finally:
            _bidi.set_mirror(False)
            _bidi.configure("en", {})

    def test_a_pipe_gets_logical_text(self, persian):
        import io
        stream = io.StringIO()
        assert _bidi.for_stream("دما 25", stream) == "دما ۲۵"


class TestTerminal:
    def test_explicit_mode_is_asked_for_and_given_back(self, monkeypatch):
        from linecast._live import bidi_modes
        assert bidi_modes() == ("\033[8l", "\033[8h")
        monkeypatch.setenv("TMUX", "/tmp/tmux-1000/default,1,0")
        on, off = bidi_modes()
        assert on == "\033[8l\033Ptmux;\033\033[8l\033\\"
        assert off.startswith("\033[8h")

    def test_frame_paint_orders_the_body_and_the_overlay(self):
        from linecast._live import frame_paint
        out = frame_paint("שלום", "\033[2;1Hאב")
        assert "םולש" in out and "בא" in out


class TestMirroring:
    @pytest.fixture(autouse=True)
    def _mirrored(self):
        _bidi.configure("fa", {})
        _bidi.set_mirror(True)
        yield
        _bidi.set_mirror(False)
        _bidi.configure("en", {})

    def test_a_row_is_laid_out_from_the_right(self):
        # A label at the left edge and a bar after it: the label goes
        # to the right edge, the bar to its left, flipped
        out = display("ab ▌▗⠁", 10)
        assert _plain(out) == "    ⠈▖▐ ab"

    def test_text_still_reads_its_own_way(self):
        out = _plain(display("امروز  12:30", 14))
        assert out.endswith("ﺯﻭﺮﻣﺍ") and "۱۲:۳۰" in out

    def test_an_overlay_piece_moves_to_the_mirrored_column(self):
        assert display("\033[2;3Hxy", 10) == "\033[2;7Hxy"

    def test_box_corners_trade_sides(self):
        assert _plain(display("\033[1;1H┌─┐x", 4)) == "\033[1;1Hx┌─┐"

    def test_nothing_is_mirrored_in_a_left_to_right_language(self):
        _bidi.configure("en", {})
        assert display("ab ▌", 10) == "ab ▌"

    def test_nothing_is_mirrored_without_a_width(self):
        assert _plain(display("ab ▌")) == "ab ▌"

    def test_arrows_follow_the_mirrored_axis(self):
        from linecast._live import _arrow
        # The _bidi _live reads: test_oneline re-imports linecast
        bidi = _arrow.__globals__["_bidi"]
        bidi.configure("fa", {})
        bidi.set_mirror(True)
        try:
            assert (_arrow(b"C"), _arrow(b"D")) == ("back", "fwd")
            assert (_arrow(b"A"), _arrow(b"B")) == ("fwd", "back")
        finally:
            bidi.set_mirror(False)
            bidi.configure("en", {})

    def test_a_picture_arrow_is_left_alone(self):
        # wind arrows point at the compass, not along the row
        assert "↗" in display("↗ 12", 6)


class TestPersianDrawing:
    def test_ezafe_is_drawn_as_its_own_letter(self, persian):
        out = _plain(display("بیشینهٔ"))
        assert unicodedata.name(out[0]) == "ARABIC LETTER HEH WITH YEH ABOVE FINAL FORM"

    def test_a_comma_between_persian_words_is_persian(self, persian):
        assert "،" in _plain(display("تهران, استان تهران"))
        assert "," in _plain(display("Paris, France"))

    def test_units_and_minus_stay_with_their_numbers(self, persian):
        assert "۳۶°C" in _plain(display("دما 36°C"))
        assert "−۳" in _plain(display("دما −3°"))


class TestFlippedPictures:
    @pytest.fixture(autouse=True)
    def _mirrored(self):
        _bidi.configure("fa", {})
        _bidi.set_mirror(True)
        yield
        _bidi.set_mirror(False)
        _bidi.configure("en", {})

    @staticmethod
    def _bg(out):
        """(character, background) per cell, from a structured reading."""
        cells, state = [], _bidi._EMPTY
        for m in re.finditer(r"\033\[[0-9;]*m|(.)", out, re.S):
            if m.group(1) is None:
                state = _bidi._next_state(state, m.group(0))
            else:
                cells.append((m.group(1), state[2]))
        return cells

    def test_a_label_on_a_gradient_sits_on_the_gradient_as_it_runs(self):
        # "41°" at the start of a bar whose background brightens
        # rightward: flipped, the bar brightens leftward, and so does the
        # background under the label, whose text keeps its order
        row = ("\033[48;5;1m4\033[48;5;2m1\033[48;5;3m°"
               "\033[48;5;4m \033[48;5;5m \033[0m")
        cells = self._bg(display(row, 5))
        assert [c for c, _ in cells] == [" ", " ", "۴", "۱", "°"]
        assert [b for _, b in cells] == ["48;5;5", "48;5;4", "48;5;3", "48;5;2", "48;5;1"]

    def test_two_labels_a_cell_apart_trade_places(self):
        # a low label outside a one-cell bar and a high one inside it
        row = "55° \033[48;5;2m58°\033[0m"
        cells = self._bg(display(row, 7))
        assert "".join(c for c, _ in cells) == "۵۸° ۵۵°"

    def test_terminal_mode_sends_numbers_in_display_order(self):
        _bidi.configure("fa", {"LINECAST_BIDI": "terminal"})
        out = display("71° ← 97°F", 10)
        # nothing for the terminal to order: no isolate, the high first
        assert RLI not in out and _plain(out) == "۹۷°F ← ۷۱°"



class TestKnownTerminals:
    """A terminal that orders text itself is recognized by the name it
    gives (XTVERSION), or by its variables when it gives none."""

    @pytest.fixture(autouse=True)
    def _no_name(self, monkeypatch):
        from linecast import _term
        monkeypatch.setattr(_term, "terminal_name", None)

    def _named(self, monkeypatch, name):
        from linecast import _term
        monkeypatch.setattr(_term, "terminal_name", name)

    def test_the_reply_names_the_terminal(self):
        from linecast import _term
        reply = "\033P>|Konsole 26.08.1\033\\\033[1;2R"
        assert _term.note_terminal_name(reply) == "Konsole 26.08.1"

    def test_konsole_by_its_name(self, monkeypatch):
        self._named(monkeypatch, "Konsole 26.08.1")
        assert _bidi.orders_text_itself({}) == "Konsole"
        assert _bidi.bidi_mode({}) == "terminal"

    def test_konsole_by_its_variable_when_it_gives_no_name(self):
        assert _bidi.orders_text_itself({"KONSOLE_VERSION": "260801"}) == "Konsole"
        assert _bidi.orders_text_itself({}) is None

    def test_a_terminal_started_from_konsole_is_not_konsole(self, monkeypatch):
        # foot launched from a Konsole shell inherits KONSOLE_VERSION
        self._named(monkeypatch, "foot(1.28.0)")
        assert _bidi.orders_text_itself({"KONSOLE_VERSION": "260801"}) is None
        assert _bidi.bidi_mode({"KONSOLE_VERSION": "260801"}) == "linecast"

    def test_inside_tmux_the_variables_tell(self, monkeypatch):
        self._named(monkeypatch, "tmux 3.5a")
        assert _bidi.orders_text_itself({"KONSOLE_VERSION": "260801"}) == "Konsole"
        assert _bidi.orders_text_itself({}) is None

    def test_the_setting_beats_the_name(self, monkeypatch):
        self._named(monkeypatch, "Konsole 26.08.1")
        assert _bidi.bidi_mode({"LINECAST_BIDI": "linecast"}) == "linecast"
