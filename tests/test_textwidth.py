"""Tests for terminal display width, the single source of truth."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from linecast._textwidth import char_width, visible_len


class TestCharWidth:
    def test_nonspacing_marks_are_zero(self):
        # Devanagari vowel sign U, virama, anusvara
        assert char_width("ु") == 0
        assert char_width("्") == 0
        assert char_width("ं") == 0
        # Thai MAI HAN-AKAT, Arabic fatha, combining acute
        assert char_width("ั") == 0
        assert char_width("َ") == 0
        assert char_width("́") == 0

    def test_spacing_marks_keep_their_cell(self):
        # Devanagari vowel signs AA and I are spacing (Mc), width 1
        assert char_width("ा") == 1
        assert char_width("ि") == 1

    def test_zero_width_joiners(self):
        assert char_width("\u200b") == 0  # zero-width space
        assert char_width("\u200c") == 0  # ZWNJ
        assert char_width("\u200d") == 0  # ZWJ

    def test_existing_rules_unchanged(self):
        assert char_width("\ufe0f") == 0        # VS16
        assert char_width("") == 1        # PUA (Nerd Font)
        assert char_width("中") == 2        # CJK
        assert char_width("\U0001f327") == 2    # emoji
        assert char_width("a") == 1

    def test_devanagari_visible_len(self):
        # बिजली: three consonants and two spacing vowel signs = 5 columns
        assert visible_len("बिजली") == 5
        # वर्षा: the virama takes no column = 4
        assert visible_len("वर्षा") == 4

    def test_decomposed_latin_visible_len(self):
        assert visible_len("é") == 1  # é as base + combining acute


class TestWrappingRespectsMarks:
    HINDI = "आपके क्षेत्र में बिजली गिरने की संभावना है। सुरक्षित भवनों में शरण लें।"

    def test_hindi_wrap_lines_fit(self):
        from linecast._textwidth import wrap_display_width
        for width in (10, 24, 40):
            for line in wrap_display_width(self.HINDI, width):
                assert visible_len(line) <= width

    def test_hindi_wrap_loses_nothing(self):
        from linecast._textwidth import wrap_display_width
        lines = wrap_display_width(self.HINDI, 24)
        assert "".join(lines).replace(" ", "") == self.HINDI.replace(" ", "")

    def test_truncation_keeps_trailing_marks_with_their_base(self):
        from linecast._textwidth import truncate_display_width, visible_len
        out = truncate_display_width("वर्षा" * 4, 11)
        # The cut falls before a column-bearing character, so a virama
        # never strands: the tail keeps its consonant's marks.
        assert out.endswith("र्…")
        # The ellipsis is part of the width it was given, not an extra
        # column past the edge of the line.
        assert visible_len(out) <= 11


class TestClusterCappedModel:
    def setup_method(self):
        from linecast import _textwidth
        _textwidth.set_cluster_capped(True)

    def teardown_method(self):
        from linecast import _textwidth
        _textwidth.set_cluster_capped(False)

    def test_conjunct_with_matra_caps_at_two(self):
        # वर्षा: व + the र्षा cluster, which sums to 3 but draws in 2
        assert visible_len("वर्षा") == 3
        # क्षेत्र: two conjunct clusters of 2 each
        assert visible_len("क्षेत्र") == 4

    def test_plain_syllables_unchanged(self):
        assert visible_len("बिजली") == 5
        assert visible_len("हैं") == 1
        assert visible_len("तथा") == 3

    def test_ascii_and_cjk_unchanged(self):
        assert visible_len("hello") == 5
        assert visible_len("中文") == 4
        assert visible_len("\U0001f327") == 2

    def test_default_model_adds_characters_up(self):
        from linecast import _textwidth
        _textwidth.set_cluster_capped(False)
        assert visible_len("वर्षा") == 4
        assert visible_len("क्षेत्र") == 4  # same either way: े is nonspacing


class TestMeasuredWidths:
    """What the terminal answers overrides what the table assumes."""

    def _measured(self, **widths):
        from linecast import _textwidth
        before = dict(_textwidth._MEASURED)
        _textwidth._MEASURED.clear()
        _textwidth._MEASURED.update(widths)
        return before

    def _restore(self, before):
        from linecast import _textwidth
        _textwidth._MEASURED.clear()
        _textwidth._MEASURED.update(before)

    def test_a_terminal_that_draws_the_selector_its_own_cell(self):
        # ☁️ is a base and a variation selector; a terminal that gives the
        # selector a cell of its own draws the pair in three columns, and
        # a row laid out for two runs off the edge.
        before = self._measured(bmp_vs16=3, smp_vs16=3)
        try:
            assert char_width("\u2601", "\ufe0f") == 3
            assert visible_len("\u2601\ufe0f") == 3
            assert visible_len("\U0001f327\ufe0f") == 3
        finally:
            self._restore(before)

    def test_a_terminal_that_draws_emoji_in_one_column(self):
        before = self._measured(smp_bare=1)
        try:
            assert visible_len("\U0001f311") == 1
        finally:
            self._restore(before)

    def test_a_font_that_draws_nerd_glyphs_double_width(self):
        before = self._measured(pua=2)
        try:
            assert visible_len("\U000f0590") == 2
        finally:
            self._restore(before)

    def test_a_measured_emoji_does_not_speak_for_cjk(self):
        # A terminal that draws emoji in one column still draws an
        # ideograph in two: the answer covers the emoji blocks, not
        # everything above the basic plane.
        before = self._measured(smp_bare=1)
        try:
            assert char_width("\U00020000") == 2   # CJK extension B
            assert char_width("中") == 2
        finally:
            self._restore(before)

    def test_nothing_measured_leaves_the_table_alone(self):
        before = self._measured()
        try:
            assert visible_len("\u2601\ufe0f") == 2
            assert visible_len("\U0001f311") == 2
            assert visible_len("\U000f0590") == 1
        finally:
            self._restore(before)


class TestProbeTimeout:
    """How long to wait for the terminal to answer, and who says so."""

    def _timeout(self, **env):
        from linecast._runtime import probe_timeout_s
        return probe_timeout_s("LINECAST_WIDTH_TIMEOUT_MS", 150, ssh_ms=600,
                               environ=env)

    def test_a_local_terminal_answers_at_once(self):
        assert self._timeout() == 0.15

    def test_ssh_waits_for_the_link(self):
        assert self._timeout(SSH_CONNECTION="10.0.0.1 22 10.0.0.2 22") == 0.6
        assert self._timeout(SSH_TTY="/dev/pts/3") == 0.6

    def test_an_empty_ssh_variable_is_not_ssh(self):
        assert self._timeout(SSH_CONNECTION="") == 0.15

    def test_the_environment_overrides_both(self):
        assert self._timeout(LINECAST_WIDTH_TIMEOUT_MS="900") == 0.9
        assert self._timeout(LINECAST_WIDTH_TIMEOUT_MS="900",
                             SSH_TTY="/dev/pts/3") == 0.9

    def test_nonsense_falls_back_and_absurd_values_are_capped(self):
        assert self._timeout(LINECAST_WIDTH_TIMEOUT_MS="soon") == 0.15
        assert self._timeout(LINECAST_WIDTH_TIMEOUT_MS="99999") == 2.0
        assert self._timeout(LINECAST_WIDTH_TIMEOUT_MS="1") == 0.01


class TestCalibration:
    def test_cpr_parsing(self):
        from linecast._textwidth import _cpr_widths
        assert _cpr_widths("\033[12;3R") == [2]
        assert _cpr_widths("garbage\033[7;3Rtrailing\033[7;5R") == [2, 4]
        assert _cpr_widths("\033[12R") == []
        assert _cpr_widths("") == []

    def test_probe_is_a_noop_without_a_tty(self):
        from linecast import _textwidth
        _textwidth.calibrate_from_terminal(timeout_s=0.01)
        assert _textwidth._CLUSTER_CAPPED is False
        assert _textwidth.measured_widths() == {}
