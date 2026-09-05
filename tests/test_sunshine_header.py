"""The sunshine corner label: the place, and the clock it keeps (issue #66)."""

import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from linecast._runtime import RuntimeConfig  # noqa: E402

_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]|\x1b\][^\x07]*\x07")


def _plain(text):
    return _ANSI.sub("", text)


def _runtime(**kw):
    args = dict(live=False, icons="emoji", lang="en", oneline=False, use_24h=False)
    args.update(kw)
    return RuntimeConfig(**args)


TORONTO = ZoneInfo("America/Toronto")
NOW = datetime(2026, 3, 5, 14, 30, tzinfo=TORONTO)  # a Thursday
TODAY = NOW.date()
YESTERDAY = TODAY - timedelta(days=1)


class TestClockLabel:
    def test_the_time_alone_on_the_users_own_day(self):
        from linecast.sunshine import clock_label
        assert clock_label(NOW, _runtime(), today=TODAY) == "2:30p"

    def test_the_weekday_joins_on_another_day(self):
        from linecast.sunshine import clock_label
        assert clock_label(NOW, _runtime(), today=YESTERDAY) == "Thu 2:30p"

    def test_twenty_four_hour_clock(self):
        from linecast.sunshine import clock_label
        assert clock_label(NOW, _runtime(use_24h=True), today=TODAY) == "14:30"
        assert clock_label(NOW, _runtime(use_24h=True), today=YESTERDAY) == "Thu 14:30"

    def test_weekday_in_the_interface_language(self):
        from linecast.sunshine import clock_label
        assert (clock_label(NOW, _runtime(lang="fr", use_24h=True), today=YESTERDAY)
                == "jeu 14:30")
        assert (clock_label(NOW, _runtime(lang="de", use_24h=True), today=YESTERDAY)
                == "Do 14:30")

    def test_the_users_day_is_the_machines_by_default(self):
        from linecast.sunshine import clock_label
        with patch("linecast.sunshine._local_today", return_value=TODAY):
            assert clock_label(NOW, _runtime()) == "2:30p"
        with patch("linecast.sunshine._local_today", return_value=YESTERDAY):
            assert clock_label(NOW, _runtime()) == "Thu 2:30p"


class TestCornerLabel:
    def test_place_and_clock_when_both_fit(self):
        from linecast.sunshine import corner_label
        assert corner_label("Westbrook", "Thu 2:30p", 78) == "Westbrook · Thu 2:30p"

    def test_clock_alone_when_the_place_would_crowd_it_out(self):
        from linecast.sunshine import corner_label
        assert corner_label("Saint-Jean-sur-Richelieu", "Thu 2:30p", 30) == "Thu 2:30p"

    def test_clock_alone_when_there_is_no_place(self):
        from linecast.sunshine import corner_label
        assert corner_label("", "Thu 2:30p", 78) == "Thu 2:30p"


def _day_view(at, **kw):
    from linecast.sunshine import render
    with patch("linecast.sunshine.get_terminal_size", return_value=(80, 24)):
        out = render(43.7, -79.4, at.timetuple().tm_yday,
                     at.hour + at.minute / 60, runtime=_runtime(),
                     tz_offset_h=-5, location_label="Toronto", **kw)
    return _plain(out).split("\n")[0]


class TestHeaderInTheViews:
    def test_day_view_names_the_time_beside_the_place(self):
        with patch("linecast.sunshine._local_today", return_value=TODAY):
            top = _day_view(NOW, now=NOW)
        assert "Toronto · 2:30p" in top and "Thu" not in top

    def test_day_view_scrubbed_past_midnight_names_the_next_day(self):
        later = NOW + timedelta(hours=10)  # Friday, 00:30
        with patch("linecast.sunshine._local_today", return_value=TODAY):
            top = _day_view(later, now=later, offset_minutes=600)
        assert "Toronto · Fri 12:30a" in top

    def test_day_view_without_a_moment_keeps_the_place_alone(self):
        top = _day_view(NOW)
        assert "Toronto" in top and ":" not in top

    def test_year_view_names_the_time_beside_the_place(self):
        from linecast._sunshine_year import render_year
        with patch("linecast._sunshine_year.get_terminal_size", return_value=(80, 24)), \
             patch("linecast.sunshine._local_today", return_value=TODAY):
            out = render_year(43.7, -79.4, NOW, _runtime(), tz=TORONTO,
                              location_label="Toronto")
        assert "Toronto · 2:30p" in _plain(out).split("\n")[0]

    def test_year_view_across_the_date_line_names_the_day(self):
        """Auckland, from a machine still on the previous day."""
        from linecast._sunshine_year import render_year
        auckland = ZoneInfo("Pacific/Auckland")
        now = datetime(2026, 3, 6, 8, 30, tzinfo=auckland)  # Friday morning there
        with patch("linecast._sunshine_year.get_terminal_size", return_value=(80, 24)), \
             patch("linecast.sunshine._local_today", return_value=date(2026, 3, 5)):
            out = render_year(-36.85, 174.76, now, _runtime(), tz=auckland,
                              location_label="Auckland")
        assert "Auckland · Fri 8:30a" in _plain(out).split("\n")[0]
