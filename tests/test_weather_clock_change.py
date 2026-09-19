"""The hourly chart across a clock change (issue #110).

Open-Meteo stamps a whole response with the zone's UTC offset at the
moment of the request, so a forecast that spans a clock change labels
every hour after it in the offset of the day it was fetched.  wall_clock
reads the stamps back through the zone, which gives the day of the
change 23 or 25 samples, and the chart then lays its markers out among
the samples, where the curve draws them, rather than by counting clock
hours from the first.
"""

import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from linecast import weather
from linecast._graphics import fmt_hour
from linecast._runtime import WeatherRuntime
from linecast._weather_historical import HistoricalAverages
from linecast._weather_hourly import (
    _column_of,
    _compute_sun_labels,
    _compute_time_markers,
    _prepare_hourly_window,
    render_hourly,
)
from linecast._weather_sources import wall_clock

TORONTO = ZoneInfo("America/Toronto")
WIDTH = 97  # 48 hours shown


def _stamped(first, hours, offset_seconds, sunrise=(), sunset=(), current=None):
    """A response as Open-Meteo sends it: every stamp in one offset."""
    times = [(first + timedelta(hours=i)).isoformat(timespec="minutes") for i in range(hours)]
    return {
        "timezone": "America/Toronto",
        "utc_offset_seconds": offset_seconds,
        "hourly": {"time": times, "temperature_2m": [float(i) for i in range(hours)]},
        "daily": {"time": sorted({t[:10] for t in times}),
                  "sunrise": list(sunrise), "sunset": list(sunset)},
        "current": {"time": current} if current else {},
    }


def _wall_clock_series(first_utc, hours):
    """Hourly wall-clock times in Toronto for `hours` instants from `first_utc`."""
    return [(first_utc + timedelta(hours=i)).astimezone(TORONTO).replace(tzinfo=None)
            for i in range(hours)]


def _forecast(dts, sun=()):
    n = len(dts)
    return {
        "timezone": "America/Toronto",
        "hourly": {
            "time": [dt.isoformat(timespec="minutes") for dt in dts],
            "temperature_2m": [10.0 + (i % 24) for i in range(n)],
            "precipitation_probability": [0] * n,
            "precipitation": [0.0] * n,
            "weather_code": [1] * n,
        },
        "daily": {"time": [], "sunrise": [r for r, _ in sun], "sunset": [s for _, s in sun]},
    }


def _runtime():
    return WeatherRuntime(live=False, icons="emoji", lang="en", oneline=False, use_24h=True)


def _col(i, n):
    """Where the chart draws the i-th of n samples."""
    return int(i / (n - 1) * (WIDTH - 1))


class TestWallClock:
    def test_the_hours_after_the_clocks_go_back_read_an_hour_earlier(self):
        # Stamped GMT-4 throughout, as a request made before the change is.
        data = _stamped(datetime(2025, 11, 1), 72, -14400,
                        sunrise=["2025-11-01T07:53", "2025-11-02T07:55", "2025-11-03T07:56"],
                        sunset=["2025-11-01T18:07", "2025-11-02T18:06", "2025-11-03T18:05"],
                        current="2025-11-03T12:00")
        wall_clock(data)
        times = data["hourly"]["time"]
        assert len(times) == 72
        assert times.count("2025-11-02T01:00") == 2
        assert sum(t.startswith("2025-11-02T") for t in times) == 25
        assert times[-1] == "2025-11-03T22:00"
        assert data["daily"]["sunrise"] == ["2025-11-01T07:53", "2025-11-02T06:55",
                                            "2025-11-03T06:56"]
        assert data["daily"]["sunset"][2] == "2025-11-03T17:05"
        assert data["current"]["time"] == "2025-11-03T11:00"

    def test_the_hour_the_clocks_skip_is_not_in_the_series(self):
        data = _stamped(datetime(2026, 3, 7), 72, -18000)
        wall_clock(data)
        times = data["hourly"]["time"]
        assert "2026-03-08T02:00" not in times
        assert sum(t.startswith("2026-03-08T") for t in times) == 23
        assert times[-1] == "2026-03-10T00:00"

    def test_a_span_with_no_change_is_left_as_it_came(self):
        data = _stamped(datetime(2026, 9, 14), 72, -14400, sunrise=["2026-09-14T06:56"])
        before = list(data["hourly"]["time"])
        wall_clock(data)
        assert data["hourly"]["time"] == before
        assert data["daily"]["sunrise"] == ["2026-09-14T06:56"]

    def test_without_a_zone_the_machine_knows_nothing_moves(self):
        data = _stamped(datetime(2025, 11, 1), 72, -14400)
        before = list(data["hourly"]["time"])
        data["timezone"] = "Mars/Olympus"
        wall_clock(data)
        assert data["hourly"]["time"] == before
        del data["timezone"]
        assert wall_clock(data)["hourly"]["time"] == before
        assert wall_clock(None) is None

    def test_a_null_stamp_is_left_alone(self):
        data = _stamped(datetime(2025, 11, 1), 72, -14400)
        data["hourly"]["time"][5] = None
        data["daily"]["sunrise"] = [None]
        wall_clock(data)
        assert data["hourly"]["time"][5] is None
        assert data["daily"]["sunrise"] == [None]


class TestMarkersFollowTheSamples:
    """Every marker sits on the column of the sample it names."""

    def _window(self, dts, now):
        window = _prepare_hourly_window(_forecast(dts)["hourly"], now, WIDTH,
                                        offset_minutes=-12 * 60)
        assert window is not None
        return window

    def _check(self, dts, now, sunrise, skipped_hour=None, tick_hour=3):
        window = self._window(dts, now)
        wdts = window["dts"]
        n = len(wdts)
        assert window["total_hours"] == n - 1
        if skipped_hour:
            assert skipped_hour not in wdts

        # The now line
        assert int(_column_of(now, wdts, WIDTH)) == _col(wdts.index(now), n)

        # The midnight dividers, each on a sample whose hour is 0
        midnights, _noons, _names = _compute_time_markers(wdts, n - 1, WIDTH, _runtime())
        expected = {_col(i, n) for i, dt in enumerate(wdts) if dt.hour == 0}
        expected = {x for x in expected if 0 < x < WIDTH - 1}
        assert midnights == expected

        # The sunrise, forty minutes past the hour it follows
        labels = _compute_sun_labels(wdts, [(sunrise, None)], n - 1, WIDTH, _runtime())
        on_the_hour = sunrise.replace(minute=0)
        i = wdts.index(on_the_hour)
        assert list(labels) == [int((i + sunrise.minute / 60) / (n - 1) * (WIDTH - 1))]

        # The tick labels, read off the rendered line
        lines = render_hourly(_forecast(dts, sun=[(sunrise.isoformat(timespec="minutes"),
                                                   None)]),
                              WIDTH, now=now, runtime=_runtime(), offset_minutes=-12 * 60)
        import re
        tick = re.sub(r"\x1b\[[0-9;]*m", "", lines[1])
        first_tick = next(dt for dt in wdts if dt.hour == tick_hour and dt > wdts[7])
        x = _col(wdts.index(first_tick), n)
        label = "╵" + fmt_hour(tick_hour, True)
        assert tick[x:x + len(label)] == label, tick
        now_x = _col(wdts.index(now), n)
        assert tick[now_x] == "│" and tick[now_x + 1] == " ", tick

    def test_the_night_the_clocks_go_forward(self):
        # 2026-03-08 02:00 EST becomes 03:00 EDT: the day has 23 samples.
        dts = _wall_clock_series(datetime(2026, 3, 6, 5, tzinfo=timezone.utc), 96)
        now = datetime(2026, 3, 8, 5, 0)
        self._check(dts, now, sunrise=datetime(2026, 3, 8, 6, 40),
                    skipped_hour=datetime(2026, 3, 8, 2, 0))

    def test_the_night_the_clocks_go_back(self):
        # 2025-11-02 01:00 comes twice: the day has 25 samples.
        dts = _wall_clock_series(datetime(2025, 10, 31, 4, tzinfo=timezone.utc), 96)
        now = datetime(2025, 11, 2, 5, 0)
        window = self._window(dts, now)
        assert window["dts"].count(datetime(2025, 11, 2, 1, 0)) == 2
        self._check(dts, now, sunrise=datetime(2025, 11, 2, 6, 40))

    def test_an_ordinary_night_is_laid_out_as_before(self):
        # No change in the span: the sample axis and the clock agree, and
        # the now line sits where the old clock-hour formula put it.
        dts = _wall_clock_series(datetime(2026, 9, 14, 4, tzinfo=timezone.utc), 96)
        now = datetime(2026, 9, 16, 5, 0)
        window = self._window(dts, now)
        assert int(_column_of(now, window["dts"], WIDTH)) == int(12 / 48 * (WIDTH - 1))
        self._check(dts, now, sunrise=datetime(2026, 9, 16, 6, 40))

    def test_the_hover_reads_the_sample_under_the_now_line(self):
        dts = _wall_clock_series(datetime(2026, 3, 6, 5, tzinfo=timezone.utc), 96)
        now = datetime(2026, 3, 8, 5, 0)
        window = self._window(dts, now)
        col = int(_column_of(now, window["dts"], WIDTH))
        # The hover chip's column-to-sample formula, from weather.py
        idx = int(col / (WIDTH - 1) * window["total_hours"] + 0.5)
        assert window["dts"][idx] == now

    def test_a_moment_outside_the_window_has_no_column(self):
        dts = _wall_clock_series(datetime(2026, 9, 14, 4, tzinfo=timezone.utc), 96)
        assert _column_of(dts[0] - timedelta(hours=1), dts, WIDTH) is None
        assert _column_of(dts[-1] + timedelta(minutes=1), dts, WIDTH) is None
        assert _column_of(dts[-1], dts, WIDTH) == WIDTH - 1
        assert _column_of(dts[0], dts, WIDTH) == 0


HIST = HistoricalAverages(avg_high=40.0, avg_low=25.0, avg_precip=0.1, years=10)


class TestArchiveDay:
    """The climate archive is read for the day it is at the location."""

    def _gather(self, there):
        with patch.object(weather, "_reverse_geocode", return_value=("Kiritimati", "KI", {})), \
             patch.object(weather, "fetch_forecast",
                          return_value={"timezone": "Pacific/Kiritimati"}), \
             patch.object(weather, "fetch_aqi", return_value=None), \
             patch.object(weather, "fetch_alerts", return_value=[]), \
             patch.object(weather, "_local_now_for_data", return_value=there), \
             patch.object(weather, "fetch_historical", return_value=HIST) as hist:
            runtime = WeatherRuntime(live=False, icons="emoji", lang="en", oneline=False)
            result = weather.gather(1.87, -157.4, "KI", runtime)
        return result, hist

    def test_across_the_date_line_the_archive_is_asked_for_the_day_there(self):
        result, hist = self._gather(datetime(2030, 1, 1, 12, 0))
        assert result["historical"] is HIST
        assert hist.call_count == 2
        assert hist.call_args_list[-1].args[2] == date(2030, 1, 1)

    def test_on_the_same_day_one_answer_serves(self):
        _result, hist = self._gather(datetime.combine(date.today(), datetime.min.time()))
        assert hist.call_count == 1
