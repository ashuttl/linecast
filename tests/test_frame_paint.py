"""Painting a frame: rows land where they belong whatever their width."""

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from linecast._live import _AUTOWRAP_OFF, _AUTOWRAP_ON, frame_body, print_frame


class _Stream(io.StringIO):
    def __init__(self, tty):
        super().__init__()
        self._tty = tty

    def isatty(self):
        return self._tty


class TestFrameBody:
    def test_every_row_is_addressed_and_cleared(self):
        assert frame_body("a\nb") == "\033[1;1Ha\033[K\033[2;1Hb\033[K"

    def test_a_row_too_wide_cannot_move_the_row_below_it(self):
        # The row below names its own line, so wherever the terminal left
        # the cursor after an over-wide row, the next row still lands on
        # the line it belongs to.
        body = frame_body("x" * 200 + "\nunder")
        assert "\033[2;1Hunder" in body

    def test_a_blank_frame_still_clears_its_row(self):
        assert frame_body("") == "\033[1;1H\033[K"


class TestPrintFrame:
    def test_a_terminal_gets_the_frame_with_autowrap_off(self):
        out = _Stream(tty=True)
        print_frame("frame", stream=out)
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
