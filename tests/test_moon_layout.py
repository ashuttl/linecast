"""The moon display's three layouts: wide, stacked, and compact.

These assert structure — where the info lands, that nothing overflows —
rather than exact text, so they hold regardless of clock or locale
settings.
"""

import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from linecast._textwidth import visible_len  # noqa: E402

# A fixed-offset zone keeps rise/set hermetic; 2026-03-05 is waning
# full-ish, so every info line has content.
NOW = datetime(2026, 3, 5, 14, 30, tzinfo=timezone(timedelta(hours=-5)))


def _strip_ansi(text):
    text = re.sub(r"\x1b\][^\x1b]*\x1b\\", "", text)
    text = re.sub(r"\x1b\[[^a-zA-Z]*[a-zA-Z]", "", text)
    return re.sub(r"\x1b[()][0-9A-Za-z]", "", text)


def _render(cols, rows, lang="en", fullscreen=False, offset_minutes=0):
    from linecast.moon import render
    from linecast._runtime import RuntimeConfig

    runtime = RuntimeConfig(live=False, icons="emoji", lang=lang,
                            oneline=False)
    with patch("linecast.moon.get_terminal_size", return_value=(cols, rows)):
        output = render(NOW, 43.7, -79.4, runtime, fullscreen=fullscreen,
                        offset_minutes=offset_minutes)
    return _strip_ansi(output).split("\n")


def _info_row(lines, needle):
    for i, line in enumerate(lines):
        if needle in line:
            return i
    raise AssertionError(f"{needle!r} not found")


class TestWideLayout:
    def test_fills_the_terminal_and_floats_the_info(self):
        lines = _render(140, 40, fullscreen=True)
        assert len(lines) == 40
        assert all(visible_len(line) <= 140 for line in lines)
        # The info column floats in the sky, well above the bottom rows,
        # and keeps its stanza order.
        phase_row = _info_row(lines, "Waning Gibbous")
        assert phase_row < 40 - 8
        assert phase_row < _info_row(lines, "Moonrise")
        assert _info_row(lines, "Full Pink Moon") < _info_row(lines, "Day 64 of 365")

    def test_column_is_left_aligned(self):
        lines = _render(140, 40, fullscreen=True)
        starts = {line.index(needle) - visible_len(line[:line.index(needle)])
                  for line in lines for needle in ("Full Pink Moon", "New Moon")
                  if needle in line}
        cols = [line.find("Full Pink Moon") for line in lines
                if "Full Pink Moon" in line]
        cols += [line.find("New Moon") for line in lines if "New Moon" in line]
        assert len(set(cols)) == 1, starts

    def test_scrubbed_shows_the_way_back(self):
        lines = _render(140, 40, fullscreen=True, offset_minutes=2880)
        joined = "\n".join(lines)
        assert "space to return to now" in joined
        assert "Up now" not in joined


class TestStackedLayout:
    def test_info_sits_beneath_the_disc(self):
        lines = _render(60, 24)
        assert _info_row(lines, "Waning Gibbous") == len(lines) - 5
        assert "Day 64 of 365" in lines[-1]

    def test_80x24_prefers_two_columns(self):
        # Stacking spends five rows on info; here the column beside a
        # full-height disc gives a bigger moon, so the layout goes wide.
        lines = _render(80, 24)
        assert _info_row(lines, "Waning Gibbous") < len(lines) - 8


class TestCompactLayout:
    def test_narrow_terminal_never_wraps(self):
        for lang in ("en", "fr"):
            lines = _render(46, 18, lang=lang)
            assert all(visible_len(line) <= 46 for line in lines), lang

    def test_narrow_terminal_keeps_the_essentials(self):
        joined = "\n".join(_render(46, 18))
        assert "Waning Gibbous" in joined
        assert "↑" in joined and "↓" in joined

    def test_short_terminal_sheds_trailing_lines(self):
        lines = _render(40, 10)
        assert len(lines) <= 8  # graph plus info, prompt rows spared
        joined = "\n".join(lines)
        assert "Waning Gibbous" in joined       # the headline survives
        assert "Day 64 of 365" not in joined    # the season line goes first

    def test_tiny_terminal_still_renders(self):
        lines = _render(24, 8)
        assert all(visible_len(line) <= 24 for line in lines)
        assert "Waning Gibbous" in "\n".join(lines)


class TestCountdownAndCompass:
    """The rise/set countdown and the compass hint, added for issue #26."""

    def test_rise_line_leads_with_the_wait(self):
        lines = _render(140, 40, fullscreen=True)
        row = lines[_info_row(lines, "Moonrise")]
        # "Moonrise in 6h 29m (20:59)": the countdown precedes the clock
        # time, and the clock time is the parenthesised one.
        assert re.search(r"Moonrise in \d+[dhm][^()]*\(\d", row), row

    def test_countdown_formats_by_magnitude(self):
        from linecast.moon import _fmt_countdown

        assert _fmt_countdown(timedelta(minutes=48)) == "48m"
        assert _fmt_countdown(timedelta(hours=6, minutes=56)) == "6h 56m"
        assert _fmt_countdown(timedelta(hours=6, minutes=5)) == "6h 05m"
        assert _fmt_countdown(timedelta(days=2, hours=4)) == "2d 4h"
        # A past event clamps rather than showing a negative wait.
        assert _fmt_countdown(timedelta(minutes=-5)) == "0m"

    def test_a_later_day_is_named_inside_the_parentheses(self):
        lines = _render(140, 40, fullscreen=True)
        row = lines[_info_row(lines, "Moonset")]
        assert re.search(r"\(\d[^()]*\)", row), row
        assert "))" not in row and "((" not in row

    def test_compass_point_appears_when_the_moon_is_up(self):
        # 2026-03-06 02:00 local: the Moon is up and near culmination.
        from linecast.moon import render
        from linecast._runtime import RuntimeConfig

        runtime = RuntimeConfig(live=False, icons="emoji", lang="en",
                                oneline=False)
        moment = NOW.replace(day=6, hour=2, minute=0)
        with patch("linecast.moon.get_terminal_size", return_value=(140, 40)):
            out = _strip_ansi(render(moment, 43.7, -79.4, runtime,
                                     fullscreen=True))
        row = [l for l in out.split("\n") if "Up now" in l]
        assert row, "expected the Moon to be up at this moment"
        assert re.search(r"Up now · -?\d+° · [NESW]{1,2}$", row[0].rstrip()), row[0]

    def test_compass_point_is_localised(self):
        """French names the western points with O, not W."""
        from linecast.moon import _compass_point
        from linecast._runtime import RuntimeConfig

        fr = RuntimeConfig(live=False, icons="emoji", lang="fr", oneline=False)
        en = RuntimeConfig(live=False, icons="emoji", lang="en", oneline=False)
        assert _compass_point(270.0, en) == "W"
        assert _compass_point(270.0, fr) == "O"
        assert _compass_point(0.0, en) == "N"
        # Wraps rather than running off the end of the eight points.
        assert _compass_point(359.0, en) == "N"
