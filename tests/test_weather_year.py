"""The weather year view: the ten years' climate, this year's days, the
chart drawn from them, and the live view's v."""

import re
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from linecast._runtime import WeatherRuntime
from linecast.weather import historical as hist
from linecast.weather import year
from linecast.weather.view import WeatherApp

TODAY = date(2026, 9, 26)
SPAN = (2016, 2025)


def _runtime(**overrides):
    values = dict(live=False, icons="plain", lang="en", oneline=False,
                  celsius=False, metric=False, shading=False, use_24h=False)
    return WeatherRuntime(**(values | overrides))


def _strip(text):
    return re.sub(r"\x1b\[[0-9;]*[A-Za-z]|\x1b\[\d+;\d+H", "", text)


def _archive(first, last, high=lambda d: 60.0, low=lambda d: 40.0,
             precip=lambda d: 0.1, code=None):
    days = [first + timedelta(days=k) for k in range((last - first).days + 1)]
    daily = {"time": [d.isoformat() for d in days],
             "temperature_2m_max": [high(d) for d in days],
             "temperature_2m_min": [low(d) for d in days],
             "precipitation_sum": [precip(d) for d in days]}
    if code is not None:
        daily["weather_code"] = [code(d) for d in days]
    return {"daily": daily}


def _ten_years(**kw):
    return _archive(date(2016, 1, 1), date(2025, 12, 31), **kw)


def _slot(month, day):
    return year._slot(date(2000, month, day))


# ---------------------------------------------------------------------------
# The ten years
# ---------------------------------------------------------------------------
class TestClimate:
    def test_the_average_is_smoothed_across_a_fortnight(self):
        # One hot date a year: its average is spread over the fifteen
        # days around it, its extreme is not.
        climate = year.climate_from_archive(
            _ten_years(high=lambda d: 80.0 if (d.month, d.day) == (7, 1) else 50.0),
            SPAN)
        assert climate.normal_high[_slot(7, 1)] == 52.0
        assert climate.normal_high[_slot(7, 8)] == 52.0
        assert climate.normal_high[_slot(7, 9)] == 50.0
        assert climate.top[_slot(7, 1)] == 80.0
        assert climate.top[_slot(7, 2)] == 50.0

    def test_the_average_wraps_the_new_year(self):
        climate = year.climate_from_archive(
            _ten_years(high=lambda d: 80.0 if (d.month, d.day) == (12, 31) else 50.0),
            SPAN)
        assert climate.normal_high[_slot(1, 3)] > 50.0

    def test_feb_29_takes_its_neighbours_extremes(self):
        # Three leap days in ten years would pinch the band.
        climate = year.climate_from_archive(
            _ten_years(high=lambda d: 90.0 if (d.month, d.day) == (2, 28) else 50.0,
                       low=lambda d: -20.0 if (d.month, d.day) == (3, 1) else 30.0),
            SPAN)
        assert climate.top[_slot(2, 29)] == 90.0
        assert climate.bottom[_slot(2, 29)] == -20.0

    def test_a_month_short_of_days_stays_out_of_its_average(self):
        full = _archive(date(2016, 1, 1), date(2016, 1, 31), precip=lambda d: 1.0)
        short = _archive(date(2017, 1, 1), date(2017, 1, 31),
                         precip=lambda d: 10.0 if d.day <= 10 else None)
        both = {"daily": {k: full["daily"][k] + short["daily"][k]
                          for k in full["daily"]}}
        climate = year.climate_from_archive(both, SPAN)
        assert climate.month_precip[0] == 31.0
        assert climate.month_precip[1] is None

    def test_no_temperatures_no_climate(self):
        assert year.climate_from_archive(None, SPAN) is None
        assert year.climate_from_archive({"daily": {}}, SPAN) is None
        assert year.climate_from_archive(
            _ten_years(high=lambda d: None), SPAN) is None


# ---------------------------------------------------------------------------
# This year
# ---------------------------------------------------------------------------
class TestYearDays:
    def test_the_archive_before_today_the_forecast_from_it(self):
        archive = _archive(date(2026, 1, 1), TODAY, high=lambda d: 70.0,
                           precip=lambda d: 0.5)
        forecast = _archive(TODAY - timedelta(days=1), TODAY + timedelta(days=6),
                            high=lambda d: 80.0, precip=lambda d: 1.0)
        days = year.year_days(archive, forecast, TODAY)
        t = days.today
        assert (date(2026, 1, 1) + timedelta(days=t)) == TODAY
        assert days.highs[t - 1] == 70.0
        assert days.highs[t] == 80.0
        assert days.highs[t + 6] == 80.0
        assert days.highs[t + 7] is None
        # The running totals are of the days gone by.
        assert days.precip[t - 1] == 0.5
        assert days.precip[t] is None

    def test_the_forecast_fills_a_day_the_archive_has_not_reached(self):
        archive = _archive(date(2026, 1, 1), TODAY - timedelta(days=3),
                           high=lambda d: 70.0)
        forecast = _archive(TODAY - timedelta(days=1), TODAY, high=lambda d: 80.0,
                            precip=lambda d: 0.2)
        days = year.year_days(archive, forecast, TODAY)
        assert days.highs[days.today - 1] == 80.0
        assert days.precip[days.today - 1] == 0.2
        assert days.highs[days.today - 2] is None

    def test_days_outside_the_year_are_left_out(self):
        dec31 = date(2026, 12, 31)
        forecast = _archive(dec31 - timedelta(days=1), dec31 + timedelta(days=5))
        days = year.year_days(None, forecast, dec31)
        assert len(days.highs) == 365
        assert days.highs[-1] == 60.0

    def test_a_leap_year_has_its_extra_day(self):
        days = year.year_days(None, None, date(2028, 3, 1))
        assert len(days.highs) == 366
        assert days.today == 60


# ---------------------------------------------------------------------------
# The chart
# ---------------------------------------------------------------------------
def _render(climate=None, days=None, size=(120, 34), **kw):
    kw.setdefault("location_name", "Westbrook")
    with patch.object(year, "get_terminal_size", return_value=size):
        return year.render_year(climate, days, kw.pop("runtime", _runtime()), **kw)


def _climate():
    return year.climate_from_archive(
        _ten_years(high=lambda d: 50.0 + 30 * (d.month in (6, 7, 8)),
                   low=lambda d: 30.0 + 30 * (d.month in (6, 7, 8)),
                   precip=lambda d: 0.1), SPAN)


def _days(high=lambda d: 52.0, low=lambda d: 32.0, **kw):
    return year.year_days(_archive(date(2026, 1, 1), TODAY - timedelta(days=1),
                                   high=high, low=low, **kw), None, TODAY)


class TestChart:
    def test_the_header_names_the_year_and_its_departure(self):
        # Two degrees above the average every day.
        head = _strip(_render(_climate(), _days(
            high=lambda d: 52.0 + 30 * (d.month in (6, 7, 8)),
            low=lambda d: 32.0 + 30 * (d.month in (6, 7, 8))))).split("\n")[0]
        assert head.startswith("2026")
        assert "2.0° above avg" in head
        assert head.rstrip().endswith("Westbrook")

    def test_the_header_gives_the_precipitation_against_its_average(self):
        head = _strip(_render(_climate(), _days(precip=lambda d: 0.2))).split("\n")[0]
        # 268 days at 0.2 against 268 days' share of 36.5 a year
        assert "53.6″ · avg 26.8″" in head

    def test_the_view_fills_the_window_and_no_more(self):
        lines = _render(_climate(), _days(), size=(120, 34)).split("\n")
        assert len(lines) == 33   # one row left for the prompt
        assert all(len(_strip(line)) <= 120 for line in lines)

    def test_the_month_axis_runs_the_year(self):
        axis = [line for line in _strip(_render(_climate(), _days())).split("\n")
                if line.lstrip().startswith("Jan")]
        assert axis and "Dec" in axis[0]

    def test_the_years_hottest_and_coldest_days_are_labelled(self):
        hot = date(2026, 7, 4)
        cold = date(2026, 2, 1)
        text = _strip(_render(_climate(), _days(
            high=lambda d: 99.0 if d == hot else 52.0,
            low=lambda d: -12.0 if d == cold else 32.0), size=(140, 40)))
        assert "99°" in text and "-12°" in text

    def test_a_hover_names_the_day_and_its_climate(self):
        # Early March: out of the synthetic summer
        text = _strip(_render(_climate(), _days(), mouse_pos=(28, 10)))
        assert "Mar" in text and "days ago" in text
        assert "52° / 32°" in text
        assert "avg 50° / 30°" in text
        assert "2016–2025 50° / 30°" in text

    def test_a_hover_on_a_day_to_come_has_its_climate_alone(self):
        text = _strip(_render(_climate(), _days(), mouse_pos=(110, 10)))
        assert "in " in text and "avg" in text and "2016–2025" in text

    def test_it_draws_before_the_archive_answers(self):
        forecast = _archive(TODAY, TODAY + timedelta(days=6))
        text = _strip(_render(None, year.year_days(None, forecast, TODAY)))
        assert text.split("\n")[0].startswith("2026")
        assert "Jan" in text

    def test_it_draws_with_nothing_at_all(self):
        assert "Jan" in _strip(_render(None, None))

    def test_metric_units_label_in_millimetres(self):
        rt = _runtime(celsius=True, metric=True)
        climate = year.climate_from_archive(_ten_years(precip=lambda d: 2.0), SPAN)
        days = _days(precip=lambda d: 3.0)
        head = _strip(_render(climate, days, runtime=rt)).split("\n")[0]
        # English sets no space before mm; Sep 1-25 is 25/30 of its month
        assert "804mm · avg 537mm" in head


# ---------------------------------------------------------------------------
# The archive
# ---------------------------------------------------------------------------
class TestArchive:
    def test_this_years_request_runs_to_today_with_weather_codes(self):
        with patch.object(hist, "fetch_json_cached", return_value=None) as fetch:
            hist.fetch_year_to_date(43.68, -70.37, TODAY, celsius=True, metric=True)
        cache_file, max_age, url = fetch.call_args[0][:3]
        assert "start_date=2026-01-01&end_date=2026-09-26" in url
        assert "weather_code" in url and "temperature_unit=celsius" in url
        assert cache_file.name.startswith("year_") and "_2026_Cmm" in cache_file.name
        assert max_age == 3 * 3600

    def test_the_ten_years_are_the_dashboards_download(self):
        with patch.object(hist, "fetch_json_cached", return_value=None) as fetch:
            hist.fetch_history(43.68, -70.37, 2026)
            hist.fetch_historical(43.68, -70.37, TODAY)
        (a, *_), (b, *_) = (c[0] for c in fetch.call_args_list)
        assert a == b and "2016-2025" in a.name
        assert "weather_code" not in fetch.call_args_list[0][0][2]


# ---------------------------------------------------------------------------
# The live view
# ---------------------------------------------------------------------------
def _app(**kw):
    runtime = SimpleNamespace(lang="en", celsius=False, metric=False)
    with patch("time.monotonic", return_value=1000.0):
        return WeatherApp({"timezone": "America/New_York"}, [], None, 43.0, -70.0,
                          runtime, location_name="Westbrook", historical=None,
                          country="US", **kw)


class TestLive:
    def test_v_flips_to_the_year_and_fetches_it(self):
        app = _app()
        assert not app.year_view and app._year_worker is None
        with patch.object(year, "fetch_year", return_value=("climate", "archive")) as fetch:
            assert app.on_action("v")
            app._year_worker.join(1.0)
        assert app.year_view
        fetch.assert_called_once()
        assert app._year[2:] == ("climate", "archive")
        assert app._year_asked[3]   # came back whole: no quick retry
        assert app.on_action("v") and not app.year_view

    def test_y_flips_it_too(self):
        app = _app()
        with patch.object(year, "fetch_year", return_value=("climate", "archive")):
            assert app.on_action("y")
            app._year_worker.join(1.0)
        assert app.year_view
        assert app.on_action("y") and not app.year_view

    def test_a_year_fetched_for_a_place_left_behind_is_dropped(self):
        app = _app()

        def moved_on(*a, **k):
            app._generation += 1
            return ("climate", "archive")

        with patch.object(year, "fetch_year", side_effect=moved_on):
            app.on_action("v")
            app._year_worker.join(1.0)
        assert app._year is None

    def test_one_fetch_until_a_short_answer_is_old_enough_to_retry(self):
        app = _app()
        with patch.object(year, "fetch_year", return_value=("climate", None)) as fetch, \
             patch("time.monotonic", return_value=1000.0):
            app.on_action("v")
            app._year_worker.join(1.0)
            with app._state_lock:
                app._start_year()
        assert fetch.call_count == 1
        with patch.object(year, "fetch_year", return_value=("climate", "archive")) as fetch, \
             patch("time.monotonic", return_value=1000.0 + 21):
            with app._state_lock:
                app._start_year()
            app._year_worker.join(1.0)
        assert fetch.call_count == 1

    def test_the_year_view_scrubs_nothing(self):
        app = _app(year_view=False)
        assert app.on_wheel(1, 5, 5) is NotImplemented
        assert not app.intercept("fwd")
        app.year_view = True
        assert app.on_wheel(1, 5, 5) is True
        assert app.intercept("fwd") and app.intercept("back")
        assert not app.intercept("reset")


# ---------------------------------------------------------------------------
# Flags
# ---------------------------------------------------------------------------
class TestFlags:
    def _run(self, *flags):
        return subprocess.run(
            [sys.executable, "-m", "linecast", "weather", *flags],
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
