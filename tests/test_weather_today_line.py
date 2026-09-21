"""The hourly chart's header row: day names and sun times keep clear of the labels at its ends."""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from linecast._runtime import WeatherRuntime
from linecast._weather.hourly import _render_today_line

_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_WIDTH = 60


def _runtime(lang="en"):
    return WeatherRuntime(live=False, icons="emoji", lang=lang, oneline=False,
                          celsius=True, metric=True, shading=False)


def _row(midnight_day_names, sun_labels, lang="en"):
    line = _render_today_line(_WIDTH, 10, 20, midnight_day_names, sun_labels, _runtime(lang))
    return _ANSI.sub("", line)


class TestTodayLine:
    def test_a_sun_time_at_the_start_keeps_a_space_after_today(self):
        row = _row({}, {5: ("\u219318:11", False)})
        assert row.startswith("Today \u2193")
        assert len(row) == _WIDTH

    def test_a_sun_time_at_the_end_keeps_a_space_before_the_range(self):
        # The sunrise falls on the columns the range occupies; it moves
        # nowhere, so it is left out rather than run into the range.
        row = _row({}, {50: ("\u219106:45", True)})
        assert "06:45" not in row
        row = _row({}, {43: ("\u219106:45", True)})
        assert row.endswith("\u219106:45 10\u00b0 \u2192 20\u00b0C")

    def test_a_day_name_at_the_end_keeps_a_space_before_the_range(self):
        row = _row({42: "Saturday"}, {})
        assert "Saturday" not in row
        row = _row({41: "Saturday"}, {})
        assert row.endswith("Saturday 10\u00b0 \u2192 20\u00b0C")

    def test_a_day_name_never_touches_today(self):
        row = _row({6: "Friday"}, {})
        assert row.startswith("Today Friday")
        # On the column right after "Today" the name wins and "Today" goes.
        row = _row({5: "Friday"}, {})
        assert row.startswith("     Friday")
