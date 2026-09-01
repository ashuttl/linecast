"""Tests for the sunshine year view.

The field itself is covered by the snapshots in test_render_snapshots.py.
What is checked here is everything the snapshots cannot see: which clock a
hovered day is reported in, what happens where the sun does not rise, and
that a hover does not rebuild the field it draws over.
"""

import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from linecast import _sunshine_year as year
from linecast import sunshine as sun
from linecast._runtime import RuntimeConfig

TORONTO = ZoneInfo("America/Toronto")
OSLO = ZoneInfo("Europe/Oslo")
KOLKATA = ZoneInfo("Asia/Kolkata")

# Longyearbyen: midnight sun from late April, polar night from late October.
SVALBARD = (78.22, 15.65)
TORONTO_LL = (43.7, -79.4)


def _runtime(**kw):
    kw.setdefault("live", False)
    kw.setdefault("icons", "plain")
    kw.setdefault("lang", "en")
    kw.setdefault("oneline", False)
    return RuntimeConfig(**kw)


def _strip(text):
    return re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", text)


def _render(lat, lng, now, size=(100, 30), **kw):
    with patch.object(year, "get_terminal_size", return_value=size):
        return year.render_year(lat, lng, now, _runtime(), **kw)


def _info_line(output):
    """The last line of the body, before any cursor-addressed tooltip."""
    return _strip(output).split("\x00")[0].rstrip("\n").split("\n")[-1]


def _tooltip(output):
    return _strip(output).split("\x00")[-1]


def _doy(date):
    return date.timetuple().tm_yday


# ---------------------------------------------------------------------------
# Per-day UTC offsets
# ---------------------------------------------------------------------------
class TestDayOffsets:
    def test_dst_shows_as_a_step(self):
        offs = year._day_tz_offsets(2026, 365, TORONTO)
        # 2026: DST runs March 8 to November 1.
        assert offs[_doy(datetime(2026, 1, 15)) - 1] == -5.0
        assert offs[_doy(datetime(2026, 7, 15)) - 1] == -4.0
        assert offs[_doy(datetime(2026, 12, 15)) - 1] == -5.0
        assert offs[_doy(datetime(2026, 3, 7)) - 1] == -5.0
        assert offs[_doy(datetime(2026, 3, 9)) - 1] == -4.0

    def test_a_zone_without_dst_never_steps(self):
        offs = year._day_tz_offsets(2026, 365, KOLKATA)
        assert set(offs) == {5.5}

    def test_leap_year_gets_its_extra_day(self):
        assert len(year._day_tz_offsets(2028, 366, TORONTO)) == 366


class TestZoneName:
    def test_names_the_abbreviation(self):
        assert year._zone_name(datetime(2026, 1, 15), TORONTO) == "EST"
        assert year._zone_name(datetime(2026, 7, 15), TORONTO) == "EDT"

    def test_an_offset_shaped_name_becomes_bare_hhmm(self):
        tz = timezone(timedelta(hours=5, minutes=30))  # tzname 'UTC+05:30'
        assert year._zone_name(datetime(2026, 1, 15), tz) == "+0530"

    def test_a_zone_with_no_abbreviation_keeps_its_offset(self):
        assert year._zone_name(datetime(2026, 1, 15),
                               ZoneInfo("Asia/Kathmandu")) == "+0545"


# ---------------------------------------------------------------------------
# The sky field and its cache
# ---------------------------------------------------------------------------
class TestFieldCache:
    def setup_method(self):
        year._FIELD_CACHE.clear()

    def test_a_hover_does_not_rebuild_the_field(self):
        now = datetime(2026, 3, 5, 14, 30, tzinfo=TORONTO)
        _render(*TORONTO_LL, now, tz=TORONTO)
        with patch.object(sun, "sun_elevation",
                          wraps=sun.sun_elevation) as elev:
            _render(*TORONTO_LL, now, tz=TORONTO, mouse_pos=(40, 10))
            _render(*TORONTO_LL, now, tz=TORONTO, mouse_pos=(41, 10))
        # Only the sun's own elevation and the hovered moments, never the
        # tens of thousands the field costs.
        assert elev.call_count < 20

    def test_a_resize_rebuilds_the_field(self):
        now = datetime(2026, 3, 5, 14, 30, tzinfo=TORONTO)
        _render(*TORONTO_LL, now, tz=TORONTO, size=(100, 30))
        with patch.object(sun, "sun_elevation",
                          wraps=sun.sun_elevation) as elev:
            _render(*TORONTO_LL, now, tz=TORONTO, size=(120, 30))
        assert elev.call_count > 1000

    def test_a_theme_reload_clears_the_field(self):
        now = datetime(2026, 3, 5, 14, 30, tzinfo=TORONTO)
        _render(*TORONTO_LL, now, tz=TORONTO)
        assert year._FIELD_CACHE
        year._rebuild()
        assert not year._FIELD_CACHE

    def test_the_cache_holds_one_field(self):
        now = datetime(2026, 3, 5, 14, 30, tzinfo=TORONTO)
        _render(*TORONTO_LL, now, tz=TORONTO, size=(100, 30))
        _render(*TORONTO_LL, now, tz=TORONTO, size=(120, 30))
        assert len(year._FIELD_CACHE) == 1

    def test_the_caller_cannot_scribble_on_the_cached_field(self):
        now = datetime(2026, 3, 5, 14, 30, tzinfo=TORONTO)
        first = _render(*TORONTO_LL, now, tz=TORONTO)
        # The sun and its glow are drawn into the copy every frame; a
        # shared field would accumulate them.
        assert _render(*TORONTO_LL, now, tz=TORONTO) == first


class TestChartClock:
    def test_the_field_uses_one_offset_unless_dst_is_asked_for(self):
        now = datetime(2026, 3, 5, 14, 30, tzinfo=TORONTO)  # EST, -5
        with patch.object(year, "_sky_field", wraps=year._sky_field) as field:
            _render(*TORONTO_LL, now, tz=TORONTO)
        assert set(field.call_args.args[5]) == {-5.0}

    def test_dst_plots_each_day_in_its_own_offset(self):
        now = datetime(2026, 3, 5, 14, 30, tzinfo=TORONTO)
        with patch.object(year, "_sky_field", wraps=year._sky_field) as field:
            _render(*TORONTO_LL, now, tz=TORONTO, dst=True)
        assert set(field.call_args.args[5]) == {-5.0, -4.0}


# ---------------------------------------------------------------------------
# Hovering a day
# ---------------------------------------------------------------------------
class TestHoverMoment:
    def _moment(self, lat, lng, doy, row, graph_h=28, **kw):
        return year._hover_moment(lat, lng, doy, -5.0, row, graph_h,
                                  sun, _runtime(), **kw)

    def test_a_row_reads_as_its_middle(self):
        hour, _ = self._moment(*TORONTO_LL, 64, 1, graph_h=24)
        assert hour == 0.5  # first row of 24: midnight to 1am

    def test_it_snaps_to_sunrise(self):
        doy = 64
        sunrise, _ = sun.solar_times(*TORONTO_LL, doy, -5.0)
        graph_h = 28
        row = int(sunrise / 24 * graph_h) + 1
        hour, label = self._moment(*TORONTO_LL, doy, row, graph_h)
        assert label == "sunrise"
        assert hour == sunrise

    def test_it_names_the_phase_away_from_an_event(self):
        _, label = self._moment(*TORONTO_LL, 64, 14, graph_h=28)
        assert label == "daylight"
        _, label = self._moment(*TORONTO_LL, 64, 1, graph_h=28)
        assert label == "night"

    def test_a_polar_day_has_no_sunrise_to_snap_to(self):
        """Midnight sun still has a solar noon; it has no rise or set."""
        doy = _doy(datetime(2026, 6, 21))
        labels = {self._moment(*SVALBARD, doy, row, graph_h=28)[1]
                  for row in range(1, 29)}
        assert labels == {"daylight", "solar noon"}

    def test_a_row_near_the_sun_glyph_reads_as_now(self):
        hour, _ = self._moment(*TORONTO_LL, 64, 17, graph_h=28,
                               now_hour=14.5)
        assert hour == 14.5

    def test_the_shift_moves_the_row_into_the_days_own_clock(self):
        # A row clear of sunrise, sunset and noon, so neither reading snaps.
        plain, _ = self._moment(*TORONTO_LL, 200, 10, graph_h=24)
        shifted, _ = self._moment(*TORONTO_LL, 200, 10, graph_h=24, shift=1.0)
        assert shifted == plain + 1.0


class TestMorningIsSolarNoon:
    """The dawn/dusk split turns on solar noon, not on 12:00.

    Utqiaġvik sits far west in its zone, so solar noon falls near 13:30;
    through the polar-night twilight, half past noon on the clock is still
    morning. Swedish tells dawn from dusk, so a clock-noon comparison
    would name the wrong one.
    """

    UTQIAGVIK = (71.29, -156.79, -9.0)
    DOY = _doy(datetime(2026, 12, 21))

    def test_the_hovered_row_reads_the_solar_clock(self):
        lat, lng, tz_off = self.UTQIAGVIK
        runtime = _runtime(lang="sv")
        # graph_h 24: a mouse row reads as the middle of its hour.
        _, before = year._hover_moment(lat, lng, self.DOY, tz_off, 13, 24,
                                       sun, runtime)  # 12:30
        _, after = year._hover_moment(lat, lng, self.DOY, tz_off, 15, 24,
                                      sun, runtime)   # 14:30
        assert before == "borgerlig gryning"
        assert after == "borgerlig skymning"

    def test_the_day_views_sky_name_agrees(self):
        lat, lng, tz_off = self.UTQIAGVIK
        sunrise, sunset = sun.solar_times(lat, lng, self.DOY, tz_off)
        label = sun._sky_name(lat, lng, self.DOY, 12.5, sunrise, sunset,
                              tz_off, _runtime(lang="sv"))
        assert label == "borgerlig gryning"


class TestTooltip:
    def _tip(self, lat, lng, now, mouse_pos, **kw):
        return _tooltip(_render(lat, lng, now, mouse_pos=mouse_pos, **kw))

    def test_it_names_the_day_and_its_distance_from_today(self):
        now = datetime(2026, 3, 5, 14, 30, tzinfo=TORONTO)
        x_today = int((_doy(now) - 0.5) / 365 * 98)
        tip = self._tip(*TORONTO_LL, now, (x_today + 2, 10), tz=TORONTO)
        assert "Mar 5" in tip and "today" in tip

    def test_a_summer_day_is_reported_in_its_own_clock_and_named(self):
        """The chart is drawn in EST; a July day's times are EDT, and say so."""
        now = datetime(2026, 3, 5, 14, 30, tzinfo=TORONTO)
        july_x = int(_doy(datetime(2026, 7, 15)) / 365 * 98)
        tip = self._tip(*TORONTO_LL, now, (july_x + 2, 14), tz=TORONTO)
        assert "EDT" in tip

    def test_a_day_in_todays_own_zone_is_not_labelled(self):
        now = datetime(2026, 3, 5, 14, 30, tzinfo=TORONTO)
        tip = self._tip(*TORONTO_LL, now, (20, 14), tz=TORONTO)
        assert "EST" not in tip and "EDT" not in tip

    def test_a_polar_day_replaces_the_rise_and_set_line(self):
        now = datetime(2026, 3, 5, 14, 30, tzinfo=OSLO)
        june_x = int(_doy(datetime(2026, 6, 21)) / 365 * 98)
        tip = self._tip(*SVALBARD, now, (june_x + 2, 14), tz=OSLO)
        assert "midnight sun" in tip
        assert "24h 00m" in tip

    def test_a_polar_night_says_so(self):
        now = datetime(2026, 3, 5, 14, 30, tzinfo=OSLO)
        dec_x = int(_doy(datetime(2026, 12, 15)) / 365 * 98)
        tip = self._tip(*SVALBARD, now, (dec_x + 2, 14), tz=OSLO)
        assert "polar night" in tip
        assert "0h 00m" in tip

    def test_an_ordinary_day_keeps_its_times(self):
        now = datetime(2026, 3, 5, 14, 30, tzinfo=TORONTO)
        tip = self._tip(*TORONTO_LL, now, (20, 14), tz=TORONTO)
        assert "midnight sun" not in tip and "polar night" not in tip
        assert re.search(r"\d{2}:\d{2}", tip)


# ---------------------------------------------------------------------------
# The bottom row
# ---------------------------------------------------------------------------
class TestBottomRow:
    """The month labels overlay the field's last row; no info line follows."""

    def test_the_last_line_carries_the_month_labels(self):
        now = datetime(2026, 3, 5, 14, 30, tzinfo=TORONTO)
        line = _info_line(_render(*TORONTO_LL, now, tz=TORONTO))
        assert "Jan" in line
        assert "Dec" in line

    def test_no_sunrise_or_sunset_times_below_the_field(self):
        now = datetime(2026, 3, 5, 14, 30, tzinfo=TORONTO)
        line = _info_line(_render(*TORONTO_LL, now, tz=TORONTO))
        assert not re.search(r"\d{1,2}:\d{2}", line)


class TestDayViewInfoLine:
    """The same polar rule, in the view the year view toggles with."""

    def _line(self, lat, lng, doy, tz_off):
        with patch("linecast.sunshine.get_terminal_size", return_value=(100, 30)):
            out = sun.render(lat, lng, doy, 12.0, runtime=_runtime(),
                             tz_offset_h=tz_off)
        return _strip(out).rstrip("\n").split("\n")[-1]

    def test_midnight_sun_invents_no_times(self):
        line = self._line(*SVALBARD, _doy(datetime(2026, 6, 21)), 2.0)
        assert "midnight sun" in line
        assert not re.search(r"\d{1,2}:\d{2}", line)

    def test_polar_night_invents_no_times(self):
        line = self._line(*SVALBARD, _doy(datetime(2026, 12, 21)), 1.0)
        assert "polar night" in line
        assert not re.search(r"\d{1,2}:\d{2}", line)

    def test_an_ordinary_day_is_unchanged(self):
        line = self._line(*TORONTO_LL, 64, -5.0)
        assert len(re.findall(r"\d{2}:\d{2}", line)) == 2
        assert "daylight" in line  # the sky is still named


class TestPolarState:
    def test_a_midlatitude_day_is_not_polar(self):
        rise, set_ = sun.solar_times(*TORONTO_LL, 64, -5.0)
        assert sun.polar_state(set_ - rise) is None

    def test_a_clamped_long_day_is_polar_day(self):
        assert sun.polar_state(24.0) == "day"

    def test_a_clamped_short_day_is_polar_night(self):
        assert sun.polar_state(0.0) == "night"


# ---------------------------------------------------------------------------
# The month axis
# ---------------------------------------------------------------------------
class TestMonthAxis:
    def _labels(self, graph_w):
        chars = [" "] * graph_w
        for x, ch in year._month_axis_cells(2026, 365, graph_w, _runtime()):
            chars[x] = ch
        return "".join(chars)

    def test_wide_labels_are_abbreviations(self):
        line = self._labels(98)
        assert line.strip().startswith("Jan")
        assert "Dec" in line

    def test_narrow_labels_are_single_letters(self):
        line = self._labels(40)
        assert "Jan" not in line
        assert line.strip().startswith("J")

    def test_the_axis_never_runs_past_the_field(self):
        for graph_w in (30, 40, 71, 72, 98, 200):
            cells = year._month_axis_cells(2026, 365, graph_w, _runtime())
            assert all(0 <= x < graph_w for x, _ in cells), graph_w


# ---------------------------------------------------------------------------
# Flags
# ---------------------------------------------------------------------------
class TestFlags:
    def _run(self, *flags):
        return subprocess.run(
            [sys.executable, "-m", "linecast", "sunshine", *flags],
            capture_output=True, text=True,
            cwd=Path(__file__).parent.parent,
            env={**__import__("os").environ,
                 "PYTHONPATH": str(Path(__file__).parent.parent / "src")},
        )

    def test_year_has_no_json_output(self):
        done = self._run("--year", "--json")
        assert done.returncode == 2
        assert "--year has no --json output" in done.stderr

    def test_year_has_no_oneline_output(self):
        done = self._run("--year", "--oneline")
        assert done.returncode == 2
        assert "--year has no --oneline output" in done.stderr
