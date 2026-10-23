from datetime import datetime, timedelta, timezone
import re
from types import SimpleNamespace

import pytest

from linecast.tides.chart import (
    compute_daylight_window,
    compute_moon_labels,
    render_day_label_line,
    render_tide_ticks,
)


_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _canvas(line):
    return _ANSI_RE.sub("", line)


def _first_tick_idx(canvas):
    return next(i for i, ch in enumerate(canvas) if ch in ("\u2502", "\u2575"))


def test_render_tide_ticks_shift_with_scroll():
    runtime = SimpleNamespace(use_24h=False)
    graph_w = 80
    total_hours = 24

    baseline = _canvas(render_tide_ticks(
        datetime(2026, 3, 5, 0, 0),
        total_hours,
        graph_w,
        runtime,
    ))
    shifted = _canvas(render_tide_ticks(
        datetime(2026, 3, 5, 0, 30),
        total_hours,
        graph_w,
        runtime,
    ))

    assert _first_tick_idx(shifted) > _first_tick_idx(baseline)


def test_render_tide_ticks_anchor_to_clock_boundaries():
    runtime = SimpleNamespace(use_24h=True)
    graph_w = 80
    total_hours = 24

    canvas = _canvas(render_tide_ticks(
        datetime(2026, 3, 5, 1, 0),
        total_hours,
        graph_w,
        runtime,
    ))
    first_tick = _first_tick_idx(canvas)

    assert canvas[first_tick:first_tick + 3] == "\u257503"


def test_wider_time_window_keeps_hour_labels_spaced():
    canvas = _canvas(render_tide_ticks(
        datetime(2026, 3, 5, 0, 0), 48, 192,
        SimpleNamespace(use_24h=True),
    ))
    ticks = [i for i, ch in enumerate(canvas) if ch in ("│", "╵")]
    assert len(ticks) == 16
    assert min(b - a for a, b in zip(ticks, ticks[1:])) >= 11
    assert canvas[ticks[1]:ticks[1] + 3] == "╵03"


def test_night_shading_follows_summer_time():
    # Portland, Maine, on 28 September: sunrise 6:34 and sunset 18:27
    # EDT. NOAA's metadata gives the standard offset, -5.
    from zoneinfo import ZoneInfo
    meta = {"lat": 43.658, "lng": -70.244, "timezonecorr": -5}
    start = datetime(2026, 9, 28, tzinfo=ZoneInfo("America/New_York"))
    daylight = compute_daylight_window(24 * 60, start, 24, meta)
    lit = [minute for minute, factor in enumerate(daylight) if factor >= 0.5]
    assert abs(lit[0] - (6 * 60 + 34)) < 25
    assert abs(lit[-1] - (18 * 60 + 27)) < 25


def test_a_window_with_a_zone_needs_no_offset_from_the_metadata():
    # Brest on 23 October: sunrise about 8:50 and sunset 19:14 CEST.
    # TICON's gauges name their zone and gave no offset, and a window
    # in the zone is read on its own clock.
    from zoneinfo import ZoneInfo
    meta = {"lat": 48.383, "lng": -4.5}
    start = datetime(2026, 10, 23, tzinfo=ZoneInfo("Europe/Paris"))
    daylight = compute_daylight_window(24 * 60, start, 24, meta)
    assert daylight == compute_daylight_window(24 * 60, start, 24, {**meta, "timezonecorr": 2})
    lit = [minute for minute, factor in enumerate(daylight) if factor >= 0.5]
    assert abs(lit[0] - (8 * 60 + 50)) < 30
    assert abs(lit[-1] - (19 * 60 + 14)) < 30


def test_night_shading_turns_at_the_apps_sunrise_and_sunset():
    # Portland, Maine, on 3 November, when the Sun runs a quarter of an
    # hour ahead of the clock: the shading turned at 6:44 and 16:37
    # by a formula of its own, 25 minutes after the sunrise the
    # sunshine view gives.
    from zoneinfo import ZoneInfo
    from linecast.astro.ephemeris import sunrise_sunset
    zone = ZoneInfo("America/New_York")
    meta = {"lat": 43.658, "lng": -70.244, "timezonecorr": -5}
    start = datetime(2026, 11, 3, tzinfo=zone)
    rise, sset = sunrise_sunset(start.date(), 43.658, -70.244, zone)
    daylight = compute_daylight_window(24 * 60, start, 24, meta)
    lit = [minute for minute, factor in enumerate(daylight) if factor >= 0.5]
    assert abs(lit[0] - (rise - start).total_seconds() / 60) < 2
    assert abs(lit[-1] - (sset - start).total_seconds() / 60) < 2


def test_the_midnight_sun_has_no_night_at_its_midnights():
    from zoneinfo import ZoneInfo
    meta = {"lat": 69.65, "lng": 18.96}
    start = datetime(2026, 6, 20, 12, tzinfo=ZoneInfo("Europe/Oslo"))
    assert set(compute_daylight_window(200, start, 48, meta)) == {1.0}
    start = datetime(2026, 12, 20, 12, tzinfo=ZoneInfo("Europe/Oslo"))
    assert set(compute_daylight_window(200, start, 48, meta)) == {0.0}


def test_a_ticon_gauge_has_night_shading():
    from linecast.tides.providers import TICON
    from linecast.tides.stations import _station_now, _station_tzinfo
    meta = TICON.station_metadata("ticon:brest-822-fra-uhslc_fd")
    start = _station_now(meta).replace(hour=0, minute=0, second=0, microsecond=0)
    assert start.tzinfo == _station_tzinfo(meta)
    assert min(compute_daylight_window(96, start, 24, meta)) < 0.5


def test_aleutian_stations_keep_summer_time():
    from zoneinfo import ZoneInfo
    from linecast.tides.stations import _station_tzinfo
    adak = {"timezone_abbr": "HAST", "timezonecorr": -10, "observedst": True, "state": "AK"}
    assert _station_tzinfo(adak) == ZoneInfo("America/Adak")


def test_compute_moon_labels_contains_rise_and_set_over_two_days():
    runtime = SimpleNamespace(use_24h=False, icons="nerd")
    station_meta = {"lat": "44.3876", "lng": "-68.2039", "timezonecorr": -5}
    window_start = datetime(2026, 3, 5, 0, 0, tzinfo=timezone(timedelta(hours=-5)))
    graph_w = 120

    labels = compute_moon_labels(
        window_start,
        total_hours=48,
        graph_w=graph_w,
        station_meta=station_meta,
        runtime=runtime,
    )

    assert labels
    assert any(is_rise for _label, is_rise in labels.values())
    assert any(not is_rise for _label, is_rise in labels.values())
    assert all(0 < col < graph_w - 1 for col in labels)


def test_render_day_label_line_with_moon_labels():
    line = render_day_label_line(
        {10: "Friday"},
        graph_w=64,
        moon_labels={
            24: ("☽↑6:30a", True),   # ☽↑6:30a
            42: ("☾↓7:10p", False),  # ☾↓7:10p
        },
    )
    canvas = _canvas(line)

    assert "Friday" in canvas
    assert "☽↑6:30a" in canvas
    assert "☾↓7:10p" in canvas


def test_render_day_label_line_shifts_moon_label_when_overlapping_day_name():
    line = render_day_label_line(
        {10: "Friday"},
        graph_w=48,
        moon_labels={
            10: ("☽↑6:30a", True),  # preferred start collides with "Friday"
        },
    )
    canvas = _canvas(line)

    day_start = canvas.index("Friday")
    moon_start = canvas.index("☽↑6:30a")
    assert moon_start >= day_start + len("Friday") + 1


# ---------------------------------------------------------------------------
# The day's chart is drawn by the hours that pass
# ---------------------------------------------------------------------------
def _paris():
    from zoneinfo import ZoneInfo
    return ZoneInfo("Europe/Paris")


def _rising(start_utc, hours, tz, fixed=False):
    """Water rising a foot an hour, every six minutes from *start_utc*,
    in *tz* (TICON's way) or in its fixed offsets (CHS's)."""
    points = []
    for k in range(hours * 10 + 1):
        t = (start_utc + timedelta(minutes=6 * k)).astimezone(tz)
        points.append((datetime.fromisoformat(t.isoformat()) if fixed else t, k / 10))
    return points


def test_a_moment_in_the_repeated_hour_reads_its_own_pass():
    from linecast.tides.chart import interp_height
    paris = _paris()
    preds = _rising(datetime(2026, 10, 24, 22, tzinfo=timezone.utc), 6, paris)
    first = datetime(2026, 10, 25, 2, 30, tzinfo=paris)          # 00:30 UTC
    second = first.replace(fold=1)                               # 01:30 UTC
    assert interp_height(first, preds) == pytest.approx(2.5)
    assert interp_height(second, preds) == pytest.approx(3.5)


@pytest.mark.parametrize("fixed", [False, True])
def test_the_days_curve_runs_on_through_the_clocks_going_back(monkeypatch, fixed):
    # Brest, 25 October 2026: a chart from midnight across the change
    # draws the water rising a foot an hour all the way, where the clock
    # would have skipped the hour that came round again
    from linecast.tides import view
    from linecast._runtime import TidesRuntime
    paris = _paris()
    preds = _rising(datetime(2026, 10, 24, 20, tzinfo=timezone.utc), 30, paris, fixed)
    now = datetime(2026, 10, 25, 5, 0, tzinfo=paris)              # 04:00 UTC
    drawn = {}
    real = view.build_braille_curve

    def curve(heights, *args, **kwargs):
        drawn["heights"] = heights
        return real(heights, *args, **kwargs)

    monkeypatch.setenv("COLUMNS", "96")
    monkeypatch.setenv("LINES", "20")
    monkeypatch.setattr(view, "_station_now", lambda *a: now)
    monkeypatch.setattr(view, "build_braille_curve", curve)
    runtime = TidesRuntime(live=True, icons="nerd", lang="en", metric=False, oneline=False,
                           use_24h=True)
    view.render("ticon:x", "Brest", station_meta={"lat": 48.38, "lng": -4.5,
                                                  "timeZoneCode": "Europe/Paris"},
                runtime=runtime, fullscreen=False, predictions=preds, hilo=[], y_range=(0, 30))
    heights = drawn["heights"]
    steps = {round(b - a, 6) for a, b in zip(heights, heights[1:])}
    assert steps == {round(24 / 96, 6)}          # a quarter hour of rise to a column


def test_the_ticks_read_the_repeated_hour_twice_and_leave_the_skipped_one_out():
    runtime = SimpleNamespace(use_24h=True)
    paris = _paris()

    def labels(start, elapsed=True):
        canvas = _canvas(render_tide_ticks(start, 8, 96, runtime, elapsed=elapsed))
        return [(i, canvas[i + 1:i + 3]) for i, ch in enumerate(canvas) if ch in ("│", "╵")]

    autumn = labels(datetime(2026, 10, 25, tzinfo=paris))
    assert [text for _i, text in autumn] == ["00", "02", "02", "04", "06"]
    # an hour apart where they repeat, and two from the second to 04
    assert autumn[2][0] - autumn[1][0] == 12 and autumn[3][0] - autumn[2][0] == 24
    spring = labels(datetime(2026, 3, 29, tzinfo=paris))
    assert [text for _i, text in spring] == ["00", "04", "06", "08"]
    assert spring[1][0] - spring[0][0] == 35    # three hours from midnight to 04
    # a month's rows are days on the clock, and so are their ticks
    assert [text for _i, text in labels(datetime(2026, 10, 25, tzinfo=paris), False)] == [
        "00", "02", "04", "06"]


def test_a_turn_after_the_change_is_placed_by_the_hours_that_pass():
    # a low at 04:00 CET is five hours after midnight CEST, whichever way
    # its provider keeps the time
    from linecast.tides.chart import prepare_tide_window
    from linecast.tides.view import _hilo_to_extrema
    paris = _paris()
    low = datetime(2026, 10, 25, 3, tzinfo=timezone.utc)
    runtime = SimpleNamespace(convert_height=lambda h: h)
    for when in (low.astimezone(paris), datetime.fromisoformat(low.astimezone(paris).isoformat())):
        window = prepare_tide_window([], [(when, 0.5, "L")], datetime(2026, 10, 25, tzinfo=paris),
                                     hours_shown=10)
        [(x, *_rest)] = _hilo_to_extrema(window, 101, runtime)
        assert x == 50
