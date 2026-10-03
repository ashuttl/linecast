"""Hourly archives: cache freshness, UTC boundaries, and graceful degradation."""
from datetime import date, datetime, timezone
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import pytest

from linecast import _http
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
    with patch.object(history, 'read_recent', return_value=None), \
         patch.object(history, 'read_archive', return_value=None) as read:
        assert history.fetch_month(43, -70, date(2026, 10, 3)) == (None, False)
    assert [call.args[2:] for call in read.call_args_list] == [
        (date(2015, 12, 31), date(2026, 1, 1)),
        (date(2025, 12, 31), date(2026, 10, 2))]
    with patch.object(history, 'read_recent', return_value=None), \
         patch.object(history, 'read_archive', return_value=None) as read:
        history.fetch_month(43, -70, date(2027, 1, 1))
    assert len(read.call_args_list) == 1
    assert read.call_args.args[2:] == (date(2016, 12, 31), date(2026, 12, 31))


def test_partial_history_still_draws_and_superseded_request_stops():
    p = dict(payload(), _requested_end='2026-01-01')
    with patch.object(history, 'read_recent', return_value=None), \
         patch.object(history, 'read_archive', side_effect=[p, None]):
        series, complete = history.fetch_month(43, -70, date(2026, 10, 3))
    assert series.days and not complete
    with patch.object(history, 'read_archive') as read:
        assert history.fetch_month(43, -70, date(2026, 10, 3), stale=lambda: True) == (None, False)
    read.assert_not_called()


def test_recent_cache_covers_seven_days_and_midnight_and_refreshes_hourly(tmp_path):
    with patch.object(history, 'cache_dir', return_value=tmp_path), \
         patch.object(_http, 'fetch_json', return_value=payload()) as fetch:
        args = 43, -70, date(2026, 10, 3)
        saved = history.read_recent(*args)
        assert history.read_recent(*args) == saved
        assert fetch.call_count == 1
        query = parse_qs(urlparse(fetch.call_args.args[0]).query)
        assert urlparse(fetch.call_args.args[0]).netloc == 'api.open-meteo.com'
        assert query['start_date'] == ['2026-09-26']
        assert query['end_date'] == ['2026-10-04']
        assert query['timeformat'] == ['unixtime']
        assert query['temperature_unit'] == ['celsius']
        assert query['hourly'] == ['temperature_2m']
        with patch.object(history, 'RECENT_AGE', -1):
            history.read_recent(*args)
        assert fetch.call_count == 2
        history.read_recent(43, -70, date(2026, 10, 4))
        assert fetch.call_count == 3
    assert len(list(tmp_path.glob('hourly_*_recent.json'))) == 1


@pytest.mark.parametrize('bad', [None, {'timezone': 'UTC', 'hourly': {}},
                                {'timezone': 'Unknown', 'hourly': payload()['hourly']},
                                {'timezone': 'UTC', 'hourly': {
                                    'time': [1], 'temperature_2m': [None]}}])
def test_recent_failure_or_bad_response_keeps_the_last_good_cache(tmp_path, bad):
    with patch.object(history, 'cache_dir', return_value=tmp_path), \
         patch.object(_http, 'fetch_json', return_value=payload()) as fetch:
        args = 43, -70, date(2026, 10, 3)
        saved = history.read_recent(*args)
        fetch.return_value = bad
        if bad is None:
            fetch.side_effect = TimeoutError
        with patch.object(history, 'RECENT_AGE', -1):
            assert history.read_recent(*args) == saved


def test_recent_only_still_draws_when_archive_is_unavailable():
    recent = dict(payload(), _requested_day='2026-01-01')
    with patch.object(history, 'read_archive', return_value=None), \
         patch.object(history, 'read_recent', return_value=recent):
        series, complete = history.fetch_month(43, -70, date(2026, 1, 1))
    assert not complete
    assert series.with_recent(datetime(2026, 1, 1, tzinfo=timezone.utc)).days
    assert all(v is None for row in series.normals for v in row)


def test_all_requests_must_cover_the_requested_day_to_be_complete():
    def archive(lat, lng, first, last, **kwargs):
        return dict(payload(), _requested_end=last.isoformat())

    with patch.object(history, 'read_archive', side_effect=archive), \
         patch.object(history, 'read_recent') as recent:
        recent.return_value = dict(payload(), _requested_day='2026-10-03')
        assert history.fetch_month(43, -70, date(2026, 10, 3))[1]
        recent.return_value = dict(payload(), _requested_day='2026-10-02')
        assert not history.fetch_month(43, -70, date(2026, 10, 3))[1]


def test_superseded_archive_request_does_not_start_recent_fetch():
    cancelled = False

    def archive(*args, **kwargs):
        nonlocal cancelled
        cancelled = True
        return payload()

    with patch.object(history, 'read_archive', side_effect=archive), \
         patch.object(history, 'read_recent') as recent:
        assert history.fetch_month(43, -70, date(2026, 1, 1),
                                   stale=lambda: cancelled) == (None, False)
    recent.assert_not_called()


def test_hourly_cache_sweep_keeps_last_year_for_places_west_of_the_date_line():
    assert not _rolled_over('hourly_abcdef_hist_2016-2025.json', 2027)
    assert _rolled_over('hourly_abcdef_hist_2016-2025.json', 2028)
    assert not _rolled_over('hourly_abcdef_year_2026.json', 2027)
    assert _rolled_over('hourly_abcdef_year_2026.json', 2028)
