"""Painting a frame: rows land where they belong whatever their width."""

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from linecast._live import (_AUTOWRAP_OFF, _AUTOWRAP_ON, _SYNC_BEGIN, _SYNC_END,
                            frame_body, frame_paint, print_frame)


class _Stream(io.StringIO):
    def __init__(self, tty):
        super().__init__()
        self._tty = tty

    def isatty(self):
        return self._tty


class TestFrameBody:
    def test_every_row_is_addressed_and_cleared(self):
        assert frame_body("a\nb") == "\033[1;1H\033[Ka\033[2;1H\033[Kb"

    def test_a_row_too_wide_cannot_move_the_row_below_it(self):
        # The row below names its own line, so wherever the terminal left
        # the cursor after an over-wide row, the next row still lands on
        # the line it belongs to.
        body = frame_body("x" * 200 + "\nunder")
        assert "\033[2;1H\033[Kunder" in body

    def test_a_blank_frame_still_clears_its_row(self):
        assert frame_body("") == "\033[1;1H\033[K"

    def test_a_row_may_use_the_last_column(self):
        # The clear precedes the row, so a row drawn to the terminal's edge
        # keeps its final cell.
        body = frame_body("x" * 80)
        assert body.endswith("x" * 80)


class TestPrintFrame:
    def test_a_terminal_gets_the_frame_with_autowrap_off(self):
        # and in bidi explicit mode, so it draws cells as linecast ordered them
        out = _Stream(tty=True)
        print_frame("frame", stream=out)
        assert out.getvalue() == f"\033[8l{_AUTOWRAP_OFF}frame{_AUTOWRAP_ON}\033[8h\n"

    def test_a_terminal_that_orders_text_itself_is_not_told_how(self):
        # The _bidi print_frame reads: test_oneline re-imports linecast
        _bidi = print_frame.__globals__["_bidi"]
        _bidi.configure("en", {"LINECAST_BIDI": "terminal"})
        try:
            out = _Stream(tty=True)
            print_frame("frame", stream=out)
        finally:
            _bidi.configure("en", {})
        assert out.getvalue() == f"{_AUTOWRAP_OFF}frame{_AUTOWRAP_ON}\n"

    def test_a_pipe_gets_the_frame_and_nothing_else(self):
        out = _Stream(tty=False)
        print_frame("frame", stream=out)
        assert out.getvalue() == "frame\n"

    def test_a_stream_that_cannot_say_is_treated_as_a_pipe(self):
        class Mute(io.StringIO):
            def isatty(self):
                raise OSError("gone")

        out = Mute()
        print_frame("frame", stream=out)
        assert out.getvalue() == "frame\n"


class TestFramePaint:
    def test_the_frame_is_one_synchronized_update(self):
        # A terminal that honours mode 2026 holds the screen between the
        # two sequences, so it never shows a half-written frame: rows from
        # two frames at once, or a row cleared and drawn only partway.
        out = frame_paint("a\nb")
        assert out.startswith(_SYNC_BEGIN)
        assert out.endswith(_SYNC_END)

    def test_body_then_overlay_with_autowrap_off(self):
        out = frame_paint("a", "\033[3;4Hchip")
        inner = out[len(_SYNC_BEGIN):-len(_SYNC_END)]
        assert inner.startswith(_AUTOWRAP_OFF)
        assert frame_body("a") in inner
        assert inner.endswith(_AUTOWRAP_ON)
        assert inner.index(frame_body("a")) < inner.index("\033[3;4Hchip")

    def test_the_clear_below_comes_before_the_body(self):
        # A row that reaches the last column leaves the cursor on that
        # cell, and a clear-to-end-of-screen from there would take the
        # cell's glyph: the last letter of "? help".  So the space below
        # the frame is cleared first, from the row after the last, and
        # the body is drawn after it.
        out = frame_paint("a\nb\nc")
        assert "\033[4;1H\033[J" in out
        assert out.index("\033[J") < out.index(frame_body("a\nb\nc"))
        assert out.count("\033[J") == 1
        assert "\033[J" not in out[out.index(frame_body("a\nb\nc")):]
