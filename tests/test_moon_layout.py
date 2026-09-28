"""The moon display's layout: the Moon in the middle, the info in the
four corners, and what a small terminal sheds.

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

from linecast.terminal.textwidth import visible_len  # noqa: E402

# A fixed-offset zone keeps rise/set hermetic; 2026-03-05 is waning
# full-ish, so every info line has content.
NOW = datetime(2026, 3, 5, 14, 30, tzinfo=timezone(timedelta(hours=-5)))


def _strip_ansi(text):
    text = re.sub(r"\x1b\][^\x1b]*\x1b\\", "", text)
    text = re.sub(r"\x1b\[[^a-zA-Z]*[a-zA-Z]", "", text)
    return re.sub(r"\x1b[()][0-9A-Za-z]", "", text)


def _render(cols, rows, lang="en", fullscreen=False, offset_minutes=0):
    from linecast.moon.view import render
    from linecast._runtime import RuntimeConfig

    runtime = RuntimeConfig(live=False, icons="emoji", lang=lang,
                            oneline=False)
    with patch("linecast.moon.view.get_terminal_size", return_value=(cols, rows)):
        output = render(NOW, 43.7, -79.4, runtime, fullscreen=fullscreen,
                        offset_minutes=offset_minutes)
    return _strip_ansi(output).split("\n")


def _disc(cols, rows, fullscreen=False):
    """(cx, cy, radius) the view draws the disc at."""
    from linecast.moon import view
    seen = {}
    real = view._draw_moon_disc

    def spy(fb, cx, cy, radius, *args, **kwargs):
        seen.update(cx=cx, cy=cy, radius=radius)
        return real(fb, cx, cy, radius, *args, **kwargs)

    with patch("linecast.moon.view._draw_moon_disc", spy):
        _render(cols, rows, fullscreen=fullscreen)
    return seen["cx"], seen["cy"], seen["radius"]


def _info_row(lines, needle):
    for i, line in enumerate(lines):
        if needle in line:
            return i
    raise AssertionError(f"{needle!r} not found")


class TestCorners:
    def test_the_info_sits_in_the_four_corners(self):
        lines = _render(140, 40, fullscreen=True)
        assert len(lines) == 40
        assert all(visible_len(line) <= 140 for line in lines)
        # What the Moon is, top left; the day, top right; the month,
        # bottom left; the year, bottom right, against the corner.
        assert lines[0].startswith(" 🌖 Waning Gibbous")
        assert lines[1].startswith(" 94% illuminated")
        assert lines[0].rstrip().endswith("Below the horizon")
        assert _info_row(lines, "Moonrise") < 4
        assert _info_row(lines, "Day 16.3 of 29.5") > 30
        assert lines[_info_row(lines, "Full Pink Moon")].startswith(" Full Pink Moon")
        assert lines[-1].rstrip().endswith("in 14.8d")
        assert "Spring equinox" in lines[-1]

    def test_the_moon_is_in_the_middle(self):
        cx, cy, _radius = _disc(140, 40, fullscreen=True)
        assert (cx, cy) == (70, 40)
        cx, cy, _radius = _disc(60, 40, fullscreen=True)
        assert (cx, cy) == (30, 40)

    def test_the_moon_makes_room_for_the_corners(self):
        # In a large terminal the corners cost the disc nothing; in a
        # small one it shrinks clear of them, but keeps most of its size.
        from linecast.terminal.graphics import cell_aspect
        aspect = cell_aspect() / 2.0
        _cx, _cy, radius = _disc(140, 40, fullscreen=True)
        assert radius == min(40 * 2 * 0.41 * aspect, 140 * 0.5 - 3.0)
        _cx, _cy, radius = _disc(80, 24)
        bare = min(22 * 2 * 0.41 * aspect, 80 * 0.5 - 3.0)
        assert 0.7 * bare <= radius < bare

    def test_each_corner_is_a_table(self):
        lines = _render(140, 40, fullscreen=True)
        rows = [lines[_info_row(lines, name)] for name in ("New Moon", "Full Pink Moon")]
        dates = {re.search(r"(Mar|Apr) \d", row).start() for row in rows}
        waits = {row.find(" in ") for row in rows}
        assert len(dates) == 1 and len(waits) == 1, (dates, waits)
        # The rising and setting arrows hang just before their times.
        rise = lines[_info_row(lines, "Moonrise")]
        assert re.search(r"Moonrise +↑\d\d:\d\d", rise), rise

    def test_scrubbed_shows_the_way_back(self):
        lines = _render(140, 40, fullscreen=True, offset_minutes=2880)
        joined = "\n".join(lines)
        assert "space to return to now" in joined
        assert "Up now" not in joined

    def test_a_narrow_pair_stacks_rather_than_overlaps(self):
        # Too narrow for the month and the year side by side, the year
        # goes beneath the month, flush left.
        lines = _render(60, 30)
        assert all(visible_len(line) <= 60 for line in lines)
        month, year = _info_row(lines, "Full Pink Moon"), _info_row(lines, "Day 64 of 365")
        assert year > month
        assert lines[year].startswith(" Day 64 of 365")


class TestCompactLayout:
    def test_narrow_terminal_never_wraps(self):
        for lang in ("en", "fr"):
            lines = _render(46, 18, lang=lang)
            assert all(visible_len(line) <= 46 for line in lines), lang

    def test_narrow_terminal_keeps_the_essentials(self):
        joined = "\n".join(_render(46, 18))
        assert "Waning Gibbous" in joined
        assert "↑" in joined and "↓" in joined

    def test_short_terminal_sheds_the_corners(self):
        lines = _render(40, 10)
        assert len(lines) <= 8  # graph plus info, prompt rows spared
        joined = "\n".join(lines)
        assert "Waning Gibbous" in joined       # the headline survives
        assert "Day 64 of 365" not in joined    # the year's corner goes first

    def test_tiny_terminal_still_renders(self):
        lines = _render(24, 8)
        assert all(visible_len(line) <= 24 for line in lines)
        assert "Waning Gibbous" in "\n".join(lines)


class TestCountdownAndCompass:
    """The rise/set countdown and the compass hint, added for issue #26."""

    def test_rise_row_reads_name_time_wait(self):
        lines = _render(140, 40, fullscreen=True)
        row = lines[_info_row(lines, "Moonrise")]
        # "Moonrise  ↑20:59  in 6h 29m": the clock time in the dates'
        # column, the countdown in the waits'.
        assert re.search(r"Moonrise +↑\d\d:\d\d +in \d+h \d+m", row), row

    def test_countdown_formats_by_magnitude(self):
        from linecast.moon.view import _fmt_countdown

        assert _fmt_countdown(timedelta(minutes=48)) == "48m"
        assert _fmt_countdown(timedelta(hours=6, minutes=56)) == "6h 56m"
        assert _fmt_countdown(timedelta(hours=6, minutes=5)) == "6h 05m"
        assert _fmt_countdown(timedelta(days=2, hours=4)) == "2d 4h"
        # A past event clamps rather than showing a negative wait.
        assert _fmt_countdown(timedelta(minutes=-5)) == "0m"

    def test_a_later_day_follows_the_time(self):
        lines = _render(140, 40, fullscreen=True)
        row = lines[_info_row(lines, "Moonset")]
        assert re.search(r"Moonset +↓07:49 Fri +in 17h 19m", row), row

    def test_compass_point_appears_when_the_moon_is_up(self):
        # 2026-03-06 02:00 local: the Moon is up and near culmination.
        from linecast.moon.view import render
        from linecast._runtime import RuntimeConfig

        runtime = RuntimeConfig(live=False, icons="emoji", lang="en",
                                oneline=False)
        moment = NOW.replace(day=6, hour=2, minute=0)
        with patch("linecast.moon.view.get_terminal_size", return_value=(140, 40)):
            out = _strip_ansi(render(moment, 43.7, -79.4, runtime,
                                     fullscreen=True))
        row = [line for line in out.split("\n") if "Up now" in line]
        assert row, "expected the Moon to be up at this moment"
        # A star may sit in the sky beyond the text on the same row.
        assert re.search(r"Up now · -?\d+° · [NESW]{1,2}(\s|$)", row[0]), row[0]

    def test_compass_point_is_localised(self):
        """French names the western points with O, not W."""
        from linecast.moon.view import _compass_point
        from linecast._runtime import RuntimeConfig

        fr = RuntimeConfig(live=False, icons="emoji", lang="fr", oneline=False)
        en = RuntimeConfig(live=False, icons="emoji", lang="en", oneline=False)
        assert _compass_point(270.0, en) == "W"
        assert _compass_point(270.0, fr) == "O"
        assert _compass_point(0.0, en) == "N"
        # Wraps rather than running off the end of the eight points.
        assert _compass_point(359.0, en) == "N"
