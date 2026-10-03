"""Hourly archives: cache freshness, UTC boundaries, and graceful degradation."""
from datetime import date, datetime, timezone
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from linecast.weather import hourly_history as history
from linecast._cache import _rolled_over


def payload():
    return {'timezone': 'UTC', 'hourly': {
        'time': [datetime(2025, 12, 31, tzinfo=timezone.utc).timestamp()],
        'temperature_2m': [10]}}


def test_cached_history_is_shared_and_a_failed_refresh_keeps_it(tmp_path):
    with patch.object(history, 'cache_dir', return_value=tmp_path), \
         patch.object(history, '_fetch_archive', return_value=payload()) as fetch:
        first = history.read_archive(43, -70, date(2015, 12, 31), date(2026, 1, 1))
        assert history.read_archive(43, -70, date(2015, 12, 31), date(2026, 1, 1)) == first
        assert fetch.call_count == 1
        with patch.object(history, 'HISTORY_AGE', -1):
            fetch.side_effect = TimeoutError
            assert history.read_archive(43, -70, date(2015, 12, 31), date(2026, 1, 1)) == first
    assert len(list(tmp_path.glob('hourly_*_hist_2016-2025.json'))) == 1


def test_current_year_refreshes_on_a_new_day_and_replaces_one_file(tmp_path):
    with patch.object(history, 'cache_dir', return_value=tmp_path), \
         patch.object(history, '_fetch_archive', return_value=payload()) as fetch:
        for end in [date(2026, 9, 29), date(2026, 9, 30)]:
            result = history.read_archive(43, -70, date(2025, 12, 31), end, year=True)
            assert result['_requested_end'] == end.isoformat()
        assert fetch.call_count == 2
        query = parse_qs(urlparse(fetch.call_args.args[0]).query)
        assert query['timeformat'] == ['unixtime']
        assert query['temperature_unit'] == ['celsius']
    assert len(list(tmp_path.glob('*.json'))) == 1


def test_bad_archive_does_not_poison_the_cache(tmp_path):
    with patch.object(history, 'cache_dir', return_value=tmp_path), \
         patch.object(history, '_fetch_archive', return_value=payload()) as fetch:
        args = 43, -70, date(2025, 12, 31), date(2026, 9, 29)
        saved = history.read_archive(*args, year=True)
        fetch.return_value = {'timezone': 'UTC', 'hourly': {}}
        with patch.object(history, 'YEAR_AGE', -1):
            assert history.read_archive(*args, year=True) == saved


def test_request_spans_pad_local_year_boundaries_and_stop_at_yesterday():
    with patch.object(history, 'read_archive', return_value=None) as read:
        assert history.fetch_month(43, -70, date(2026, 10, 3)) == (None, False)
    assert [call.args[2:] for call in read.call_args_list] == [
        (date(2015, 12, 31), date(2026, 1, 1)),
        (date(2025, 12, 31), date(2026, 10, 2))]
    with patch.object(history, 'read_archive', return_value=None) as read:
        history.fetch_month(43, -70, date(2027, 1, 1))
    assert len(read.call_args_list) == 1
    assert read.call_args.args[2:] == (date(2016, 12, 31), date(2026, 12, 31))


def test_partial_history_still_draws_and_superseded_request_stops():
    p = dict(payload(), _requested_end='2026-01-01')
    with patch.object(history, 'read_archive', side_effect=[p, None]):
        series, complete = history.fetch_month(43, -70, date(2026, 10, 3))
    assert series.days and not complete
    with patch.object(history, 'read_archive') as read:
        assert history.fetch_month(43, -70, date(2026, 10, 3), stale=lambda: True) == (None, False)
    read.assert_not_called()


def test_hourly_cache_sweep_keeps_last_year_for_places_west_of_the_date_line():
    assert not _rolled_over('hourly_abcdef_hist_2016-2025.json', 2027)
    assert _rolled_over('hourly_abcdef_hist_2016-2025.json', 2028)
    assert not _rolled_over('hourly_abcdef_year_2026.json', 2027)
    assert _rolled_over('hourly_abcdef_year_2026.json', 2028)
