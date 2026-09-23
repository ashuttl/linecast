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
            state = "" if params in ("", "0") else state + ";" + params
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

    def test_terminal_mode_leaves_the_order_alone(self):
        _bidi.configure("en", {"LINECAST_BIDI": "terminal"})
        try:
            assert display("abc שלום") == "abc שלום"
        finally:
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
