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
        from linecast._weather_alerts import _wrap_display_width
        for width in (10, 24, 40):
            for line in _wrap_display_width(self.HINDI, width):
                assert visible_len(line) <= width

    def test_hindi_wrap_loses_nothing(self):
        from linecast._weather_alerts import _wrap_display_width
        lines = _wrap_display_width(self.HINDI, 24)
        assert "".join(lines).replace(" ", "") == self.HINDI.replace(" ", "")

    def test_truncation_keeps_trailing_marks_with_their_base(self):
        from linecast._weather_alerts import _truncate_display_width
        out = _truncate_display_width("वर्षा" * 4, 10)
        # The cut falls before a column-bearing character, so a virama
        # never strands: the tail keeps its consonant's marks.
        assert out.endswith("र्…")


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


class TestCalibration:
    def test_cpr_parsing(self):
        from linecast._textwidth import _cpr_width
        assert _cpr_width("\033[12;3R") == 2
        assert _cpr_width("\033[1;4R") == 3
        assert _cpr_width("garbage\033[7;3Rtrailing") == 2
        assert _cpr_width("\033[12R") is None
        assert _cpr_width("") is None

    def test_probe_is_a_noop_without_a_tty(self):
        from linecast import _textwidth
        _textwidth.calibrate_from_terminal(timeout_s=0.01)
        assert _textwidth._CLUSTER_CAPPED is False
