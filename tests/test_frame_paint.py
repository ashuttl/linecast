"""Painting a frame: rows land where they belong whatever their width."""

import io

import pytest

from linecast.terminal.live import (_AUTOWRAP_OFF, _AUTOWRAP_ON, _SYNC_BEGIN, _SYNC_END,
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
        from linecast.terminal import bidi as _bidi
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

    def test_the_clear_below_comes_before_the_body(self, monkeypatch):
        # A row that reaches the last column leaves the cursor on that
        # cell, and a clear-to-end-of-screen from there would take the
        # cell's glyph: the last letter of "? help".  So the space below
        # the frame is cleared first, from the row after the last, and
        # the body is drawn after it.
        monkeypatch.setenv("LINES", "4")
        out = frame_paint("a\nb\nc")
        assert "\033[4;1H\033[J" in out
        assert out.index("\033[J") < out.index(frame_body("a\nb\nc"))
        assert out.count("\033[J") == 1
        assert "\033[J" not in out[out.index(frame_body("a\nb\nc")):]

    @pytest.mark.parametrize("height", [2, 3])
    def test_a_full_frame_does_not_erase_the_footer_before_repainting(self, monkeypatch,
                                                                    height):
        # CUP beyond the bottom clamps to the bottom row. An erase there
        # would blank the old footer while all the rows above are painted.
        # Include a frame taller than the terminal, as during a resize.
        monkeypatch.setenv("LINES", str(height))
        out = frame_paint("header\nchart\n? help")
        assert "\033[J" not in out
        assert "\033[3;1H\033[K? help" in out

    def test_a_shorter_frame_erases_the_previous_frames_leftover_rows(self, monkeypatch):
        from test_maps_color_runs import painted

        monkeypatch.setenv("LINES", "4")
        first = frame_paint("header\nchart\nchart\n? help")
        second = frame_paint("header\n? help")
        grid = painted(first + second, cols=6, rows=4)
        assert [''.join(cell[0] for cell in row) for row in grid] == [
            "header", "? help", "      ", "      "]


class TestFramePainter:
    """The live loop writes the rows that changed, and whole frames
    only where a part would not be the screen."""

    def _painter(self, monkeypatch, lines=6):
        from linecast.terminal.live import FramePainter
        monkeypatch.setenv("COLUMNS", "20")
        monkeypatch.setenv("LINES", str(lines))
        return FramePainter()

    def test_the_first_frame_is_written_whole(self, monkeypatch):
        p = self._painter(monkeypatch)
        assert p.paint("a\nb\nc") == frame_paint("a\nb\nc")

    def test_an_unchanged_frame_writes_no_rows(self, monkeypatch):
        p = self._painter(monkeypatch)
        p.paint("a\nb\nc")
        out = p.paint("a\nb\nc")
        assert "\033[K" not in out
        assert out.startswith(_SYNC_BEGIN) and out.endswith(_SYNC_END)

    def test_only_the_changed_row_is_written(self, monkeypatch):
        p = self._painter(monkeypatch)
        p.paint("a\nb\nc")
        out = p.paint("a\nB\nc")
        assert "\033[2;1H\033[KB" in out
        assert "\033[1;1H" not in out and "\033[3;1H" not in out
        # from a reset, the state the row starts from in a whole frame
        assert out.index("\033[0m") < out.index("\033[2;1H")

    def test_rows_that_carry_a_colour_are_written_together(self, monkeypatch):
        # the second row sets a colour it never resets, so the rows
        # under it inherit it: a change to the third repaints the second
        # with it, and the fourth, which inherits it too
        p = self._painter(monkeypatch)
        p.paint("a\n\033[31mb\nc\nd")
        out = p.paint("a\n\033[31mb\nC\nd")
        assert "\033[2;1H\033[K\033[31mb" in out
        assert "\033[3;1H\033[KC" in out
        assert "\033[4;1H\033[Kd" in out
        assert "\033[1;1H" not in out

    def test_a_row_that_ends_reset_stands_alone(self, monkeypatch):
        p = self._painter(monkeypatch)
        p.paint("a\n\033[31mb\033[0m\nc")
        out = p.paint("a\n\033[31mb\033[0m\nC")
        assert "\033[3;1H\033[KC" in out
        assert "\033[2;1H" not in out

    def test_a_resized_terminal_gets_the_whole_frame(self, monkeypatch):
        p = self._painter(monkeypatch)
        p.paint("a\nb\nc")
        monkeypatch.setenv("COLUMNS", "30")
        assert p.paint("a\nb\nc") == frame_paint("a\nb\nc")

    def test_a_frame_of_another_height_is_written_whole(self, monkeypatch):
        p = self._painter(monkeypatch)
        p.paint("a\nb\nc\nd")
        out = p.paint("a\nb")
        assert out == frame_paint("a\nb")
        assert "\033[3;1H\033[J" in out   # and the rows below are erased

    def test_the_frame_after_an_overlay_is_written_whole(self, monkeypatch):
        p = self._painter(monkeypatch)
        p.paint("a\nb\nc")
        with_chip = p.paint("a\nb\nc", "\033[2;3Hchip")
        assert "\033[2;3Hchip" in with_chip
        assert "\033[1;1H" not in with_chip    # the body was unchanged
        after = p.paint("a\nb\nc")
        assert frame_body("a\nb\nc") in after    # the rows under it come back

    def test_a_mode_switch_alone_is_not_an_overlay(self, monkeypatch):
        p = self._painter(monkeypatch)
        p.paint("a\nb\nc", "\033[?1003h")
        out = p.paint("a\nb\nc", "\033[?1003h")
        assert "\033[K" not in out

    def test_forget_writes_the_next_frame_whole(self, monkeypatch):
        p = self._painter(monkeypatch)
        p.paint("a\nb\nc")
        p.forget()
        assert p.paint("a\nb\nc") == frame_paint("a\nb\nc")

    def test_the_screen_matches_a_whole_repaint(self, monkeypatch):
        from test_maps_color_runs import painted
        p = self._painter(monkeypatch, lines=4)
        first = p.paint("header\nchart\nchart\n? help")
        second = p.paint("header\nchart\nCHART\n? help")
        grid = painted(first + second, cols=6, rows=4)
        assert [''.join(cell[0] for cell in row) for row in grid] == [
            "header", "chart ", "CHART ", "? help"]
