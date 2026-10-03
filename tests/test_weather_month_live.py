"""The real weather app's month controls, loading state, and location changes."""
import threading
from datetime import datetime
from unittest.mock import patch

import pytest

from linecast._parsers import weather_parser
from linecast._runtime import WeatherRuntime
from linecast.weather import hourly_history, live, month, year

NOW = datetime(2026, 10, 3, 12)


@pytest.fixture
def app():
    with patch.object(live, 'local_now', return_value=NOW), \
         patch.object(live.WeatherApp, '_start_climate'), \
         patch.object(live, '_t') as clock:
        clock.monotonic.return_value = 1000
        instance = live.WeatherApp({'timezone': 'America/New_York'}, [], None, 43, -70,
                                   WeatherRuntime.defaults(), location_name='Westbrook')
        yield instance
        instance.stop()


def test_v_cycles_forecast_month_year_and_preserves_color_choice(app):
    with patch.object(hourly_history, 'fetch_month', return_value=('series', True)) as fetch, \
         patch.object(year, 'fetch_year', return_value=(None, None)):
        assert app._month_worker is None
        assert app.on_action('v') and app.help_view == 'weather_month'
        app._month_worker.join(1)
        assert app._month[2] == 'series'
        assert app.on_action('c') and app.month_difference
        assert app.on_action('v') and app.help_view == 'weather_year'
        app._year_worker.join(1)
        assert app.on_action('v') and app.help_view == 'weather'
        assert app.on_action('v') and app.month_difference
        assert fetch.call_count == 1


def test_month_navigation_and_reset_do_not_scroll_the_forecast(app):
    app.month_view = True
    assert app.month_first.isoformat() == '2026-09-01'
    assert app.intercept('fwd') and app.month_first.isoformat() == '2026-10-01'
    app.intercept('fwd')
    assert app.month_first.isoformat() == '2026-10-01'
    app.on_wheel(1, 30, 20)
    assert app.month_first.isoformat() == '2026-09-01'
    app.month_first = datetime(2016, 1, 1).date()
    app.intercept('back')
    assert app.month_first.isoformat() == '2016-01-01'
    app.intercept('reset')
    assert app.month_first.isoformat() == '2026-09-01'


def test_slow_request_uses_existing_toast_without_blocking_and_only_in_month(app):
    release = threading.Event()

    def fetch(*args, **kwargs):
        release.wait(2)
        return 'series', True

    with patch.object(hourly_history, 'fetch_month', side_effect=fetch), \
         patch.object(app, 'busy_toast', return_value='spinner') as toast:
        try:
            app.on_action('v')
            assert app._month_busy()
            assert app._month_toast(100, 40) == 'spinner'
            assert toast.call_args.args[0] == 'Loading hourly history…'
            app._start_month()
            app.month_view = False
            assert app._month_toast(100, 40) == ''
        finally:
            release.set()
            app._month_worker.join(1)
        assert not app._month_busy()
        assert app._month_toast(100, 40) == ''


def test_failure_can_retry_and_a_stale_location_cannot_replace_the_new_one(app):
    with patch.object(hourly_history, 'fetch_month', return_value=(None, False)) as fetch:
        app.on_action('v')
        app._month_worker.join(1)
        app._start_month()
        assert fetch.call_count == 1
        fetch.return_value = ('series', True)
        app.on_action('r')
        app._month_worker.join(1)
        assert app._month[2] == 'series'
    release = threading.Event()

    def moved(*args, **kwargs):
        release.wait(2)
        assert kwargs['stale']()
        return 'old place', True

    with patch.object(hourly_history, 'fetch_month', side_effect=moved):
        app.on_action('r')
        old = app._month_worker
        app._generation += 1
        app.lat = 51.5
        with patch.object(hourly_history, 'fetch_month', return_value=('new place', True)):
            app._start_month()
            app._month_worker.join(1)
        release.set()
        old.join(1)
    assert app._month[0] == (51.5, -70)
    assert app._month[2] == 'new place'


def test_pending_location_keeps_its_old_chart_until_commit(app):
    app.month_view = True
    app._month = ((43, -70), NOW.date(), 'old series')
    app._generation += 1
    app._loading = object()
    with patch.object(hourly_history, 'fetch_month') as fetch, \
         patch.object(month, 'render_month', return_value='frame') as draw:
        app._start_month()
        app._render_month(None)
        assert draw.call_args.args[0] == 'old series'
        fetch.assert_not_called()
    app._loading = None
    with patch.object(hourly_history, 'fetch_month', return_value=('new series', True)) as fetch:
        app._commit_place(type('Place', (), {'lat': 51.5, 'lon': -0.1, 'name': 'London'})(),
                          {'data': {'timezone': 'Europe/London'}})
        app._month_worker.join(1)
        assert fetch.call_args.args[:2] == (51.5, -0.1)
        assert app._month[2] == 'new series'


def test_new_local_day_refreshes_the_archive_and_year_boundary_drops_old_baseline(app):
    with patch.object(hourly_history, 'fetch_month', return_value=('series', True)) as fetch:
        app.on_action('v')
        app._month_worker.join(1)
        with patch.object(live, 'local_now', return_value=datetime(2027, 1, 1)), \
             patch.object(month, 'render_month', return_value='frame') as draw:
            app._render_month(None)
            assert draw.call_args.args[0] is None
            app._start_month()
            app._month_worker.join(1)
            assert fetch.call_count == 2


def test_month_refreshes_recent_estimates_after_an_hour(app):
    with patch.object(hourly_history, 'fetch_month', return_value=('series', True)) as fetch:
        app.on_action('v')
        app._month_worker.join(1)
        live._t.monotonic.return_value += 3599
        app._start_month()
        assert fetch.call_count == 1
        live._t.monotonic.return_value += 1
        app._start_month()
        app._month_worker.join(1)
        assert fetch.call_count == 2


@pytest.mark.parametrize('flag,mode', [('--month', 'temperature'),
                                     ('--month-temperature', 'temperature'),
                                     ('--month-departure', 'departure')])
def test_direct_flags_and_one_frame_output(flag, mode, monkeypatch):
    args = weather_parser().parse_args([flag, '--print'])
    assert args.month == mode and not args.year
    monkeypatch.setattr('sys.argv', ['weather', flag, '--print'])
    rt = WeatherRuntime.defaults()
    with patch.object(live, 'place_for', return_value=(43, -70, 'US', 'Westbrook', rt)), \
         patch.object(live, 'gather',
                      return_value={'data': {'timezone': 'UTC'}, 'name': 'Westbrook'}), \
         patch.object(hourly_history, 'fetch_month', return_value=('series', True)), \
         patch.object(month, 'render_month', return_value='frame') as render, \
         patch.object(live._live, 'print_frame') as output:
        live._main()
    assert render.call_args.kwargs['difference'] == (mode == 'departure')
    output.assert_called_once_with('frame')


@pytest.mark.parametrize('flag', ['--month', '--month-temperature', '--month-departure'])
@pytest.mark.parametrize('output', ['--json', '--oneline', '--prose', '--year'])
def test_alternate_flags_reject_incompatible_output_before_any_fetch(flag, output, monkeypatch):
    monkeypatch.setattr('sys.argv', ['weather', flag, output])
    with patch.object(live, 'gather') as gather, pytest.raises(SystemExit) as error:
        live._main()
    assert error.value.code == 2
    gather.assert_not_called()
