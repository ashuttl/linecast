"""The climate scale's second chances: a queued, retried archive fetch,
and a live view that fills the scale in when it arrives late."""

import threading
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from linecast._weather import historical as hist
from linecast import weather
from linecast._http import HTTPError
from linecast._maps.search import Result
from linecast._weather.historical import Superseded, _fetch_archive

URL = "https://archive-api.open-meteo.com/v1/archive?x=1"


def refused(code):
    return HTTPError(URL, code, "refused")


@pytest.fixture(autouse=True)
def no_sleep():
    # One mock: the archive's pauses and the view's delay are both time.sleep.
    assert weather._t is hist.time
    with patch.object(hist.time, "sleep") as sleep:
        sleep.view = sleep
        yield sleep


# ---------------------------------------------------------------------------
# _fetch_archive
# ---------------------------------------------------------------------------

def test_a_refusal_is_retried_after_a_pause(no_sleep):
    answers = [refused(429), refused(503), {"daily": {}}]

    def fetch_json(url, timeout):
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    with patch.object(hist, "fetch_json", side_effect=fetch_json) as fj:
        assert _fetch_archive(URL, timeout=15) == {"daily": {}}
    assert fj.call_count == 3
    assert [c.args[0] for c in no_sleep.call_args_list] == [1.0, 2.0]


def test_refusals_give_up_after_the_last_pause():
    with patch.object(hist, "fetch_json", side_effect=refused(429)) as fj, \
         pytest.raises(HTTPError):
        _fetch_archive(URL)
    assert fj.call_count == 3


def test_other_errors_are_not_retried():
    with patch.object(hist, "fetch_json", side_effect=refused(404)) as fj, \
         pytest.raises(HTTPError):
        _fetch_archive(URL)
    assert fj.call_count == 1


def test_a_timeout_is_retried_once_with_less_patience():
    calls = []

    def fetch_json(url, timeout):
        calls.append(timeout)
        if len(calls) == 1:
            raise TimeoutError("timed out")
        return {"daily": {}}

    with patch.object(hist, "fetch_json", side_effect=fetch_json):
        assert _fetch_archive(URL, timeout=15) == {"daily": {}}
    assert calls == [15, 10]

    with patch.object(hist, "fetch_json", side_effect=TimeoutError("still")) as fj, \
         pytest.raises(TimeoutError):
        _fetch_archive(URL, timeout=15)
    assert fj.call_count == 2


def test_a_request_no_one_wants_is_never_sent():
    with patch.object(hist, "fetch_json") as fj, pytest.raises(Superseded):
        _fetch_archive(URL, stale=lambda: True)
    assert not fj.called


def test_requests_take_turns_and_a_superseded_one_yields_its_turn():
    """Two location changes in quick succession: the second waits for the
    first's request, and if the user has moved on again by then it
    steps aside without a request of its own."""
    holding, release = threading.Event(), threading.Event()
    sent = []

    def fetch_json(url, timeout):
        sent.append(url)
        holding.set()
        assert release.wait(2)
        return {"daily": {}}

    with patch.object(hist, "fetch_json", side_effect=fetch_json):
        first = threading.Thread(target=_fetch_archive, args=("first",), daemon=True)
        first.start()
        assert holding.wait(1)
        outcome = {}

        def second():
            try:
                _fetch_archive("second", stale=lambda: True)
            except Superseded as exc:
                outcome["error"] = exc

        waiter = threading.Thread(target=second, daemon=True)
        waiter.start()
        waiter.join(0.2)
        assert waiter.is_alive()          # queued behind the first
        release.set()
        waiter.join(2)
        first.join(2)
    assert isinstance(outcome.get("error"), Superseded)
    assert sent == ["first"]


def test_a_request_queued_behind_one_for_the_same_place_reads_its_cache(tmp_path):
    cache_file = tmp_path / "hist.json"
    with patch.object(hist, "fetch_json") as fj:
        with patch.object(hist, "read_cache", return_value=None):
            assert _fetch_archive(URL, cache_file=cache_file) is fj.return_value
        with patch.object(hist, "read_cache", return_value={"cached": 1}) as rc:
            assert _fetch_archive(URL, cache_file=cache_file) == {"cached": 1}
    assert fj.call_count == 1
    assert rc.call_args.args == (cache_file, hist._CACHE_MAX_AGE)


def test_fetch_historical_passes_the_stale_check_to_the_network_step(tmp_path):
    seen = {}

    def fetch_json_cached(cache_file, max_age, url, timeout, fallback, fetch):
        seen["fetch"] = fetch
        return None

    with patch.object(hist, "fetch_json_cached", side_effect=fetch_json_cached), \
         patch.object(hist, "fetch_json") as fj:
        assert hist.fetch_historical(1, 2, date(2026, 9, 18), stale=lambda: True) is None
        with pytest.raises(Superseded):
            seen["fetch"](URL, timeout=15)
    assert not fj.called


# ---------------------------------------------------------------------------
# gather
# ---------------------------------------------------------------------------

def test_a_missed_second_ask_keeps_the_first_answer():
    """Across the date line the archive is asked again for the local
    day; when that ask fails, the machine-day answer stands."""
    tomorrow = datetime.now() + timedelta(days=1)

    def fetch_historical(lat, lng, day, **kwargs):
        return "history" if day == date.today() else None

    with patch.object(weather, "_reverse_geocode", return_value=("Tokyo", "JP", {})), \
         patch.object(weather, "fetch_forecast", return_value={"v": 1}), \
         patch.object(weather, "fetch_aqi", return_value=None), \
         patch.object(weather, "fetch_alerts", return_value=[]), \
         patch.object(weather, "_local_now_for_data", return_value=tomorrow), \
         patch.object(weather, "fetch_historical", side_effect=fetch_historical) as fh:
        result = weather.gather(35.68, 139.69, "JP", weather.WeatherRuntime.defaults(),
                                geo_label="Tokyo", stale=lambda: False)
    assert result["historical"] == "history"
    assert fh.call_count == 2
    assert all("stale" in c.kwargs for c in fh.call_args_list)


def _gather_with_a_hung_archive(runtime):
    started = threading.Event()

    def stuck(*args, **kwargs):
        started.set()
        threading.Event().wait()

    with patch.object(weather, "_reverse_geocode", return_value=("Tokyo", "JP", {})), \
         patch.object(weather, "fetch_forecast", return_value={"v": 1}), \
         patch.object(weather, "fetch_aqi", return_value=None), \
         patch.object(weather, "fetch_alerts", return_value=[]), \
         patch.object(weather, "_local_now_for_data", return_value=datetime.now()), \
         patch.object(weather, "fetch_historical", side_effect=stuck), \
         patch.object(weather, "_CLIMATE_PATIENCE", 0.1), \
         patch.object(weather, "_FETCH_CEILING", 1.0):
        began = datetime.now()
        result = weather.gather(35.68, 139.69, "JP", runtime, geo_label="Tokyo")
    assert started.is_set()
    return result, (datetime.now() - began).total_seconds()


def test_the_live_view_does_not_wait_out_a_hung_archive():
    runtime = weather.WeatherRuntime.defaults()
    result, took = _gather_with_a_hung_archive(SimpleNamespace(
        live=True, lang=runtime.lang, celsius=False, metric=False))
    assert result["data"] == {"v": 1} and result["historical"] is None
    assert took < 0.8


def test_a_one_shot_run_waits_the_deadline_for_the_archive():
    result, took = _gather_with_a_hung_archive(weather.WeatherRuntime.defaults())
    assert result["data"] == {"v": 1} and result["historical"] is None
    assert took >= 0.9


# ---------------------------------------------------------------------------
# WeatherApp
# ---------------------------------------------------------------------------

def place(name="Paris", lat=48.85, lon=2.35):
    return Result(name, "France", lat, lon, "city")


def app(historical="old"):
    return weather.WeatherApp({"old": 1}, [], None, 43, -70,
                              SimpleNamespace(lang="en", celsius=False, metric=False),
                              location_name="Portland", country="US", historical=historical)


def join_climate(view):
    worker = view._climate_worker
    assert worker is not None
    worker.join(2)
    assert not worker.is_alive()


def test_a_location_that_arrives_without_its_climate_gets_it_afterwards(no_sleep):
    view = app()
    result = dict(data={"new": 1}, name="Paris", country_code="FR")
    with patch.object(weather, "gather", return_value=result), \
         patch.object(weather, "_local_now_for_data", return_value=datetime(2026, 9, 19, 12)), \
         patch.object(weather, "fetch_historical", return_value="later") as fh, \
         patch.object(weather._live, "nudge") as nudge:
        view._choose_location(place())
        view._location_worker.join(2)
        with view._state_lock:
            view._finish_location()
        assert view.historical is None
        join_climate(view)
    assert view.historical == "later"
    assert fh.call_args.args[:3] == (48.85, 2.35, date(2026, 9, 19))
    assert fh.call_args.kwargs["celsius"] is False
    assert nudge.called
    # A little after, not on the heels of the attempt that just failed.
    no_sleep.view.assert_called_once_with(weather._CLIMATE_RETRY_DELAY)


def test_a_late_climate_for_a_place_the_user_has_left_is_dropped():
    view = app()
    view.historical = None
    entered, release = threading.Event(), threading.Event()

    def fetch_historical(*args, stale, **kwargs):
        entered.set()
        assert release.wait(2)
        assert stale()
        return "stale answer"

    with patch.object(weather, "_local_now_for_data", return_value=datetime(2026, 9, 18)), \
         patch.object(weather, "fetch_historical", side_effect=fetch_historical):
        with view._state_lock:
            view._start_climate()
        assert entered.wait(1)
        view.stop()                       # the user moved on
        release.set()
        join_climate(view)
    assert view.historical is None


def test_the_refresh_asks_again_until_the_climate_arrives(no_sleep):
    view = app()
    view.historical = None
    with patch.object(weather, "fetch_forecast", return_value={"v": 2}), \
         patch.object(weather, "fetch_alerts", return_value=[]), \
         patch.object(weather, "fetch_aqi", return_value=None), \
         patch.object(weather, "_reverse_geocode", return_value=("", "US", {})), \
         patch.object(weather, "forecast_is_todays", return_value=True), \
         patch.object(weather, "_local_now_for_data", return_value=datetime(2026, 9, 18)), \
         patch.object(weather, "fetch_historical", return_value="at last"):
        view._start_refresh()
        view._worker.join(2)
        join_climate(view)
    assert view.data == {"v": 2} and view.historical == "at last"
    assert not no_sleep.view.called   # the refresh interval has spaced it already


def test_a_view_that_starts_without_its_climate_asks_at_once():
    with patch.object(weather, "_local_now_for_data", return_value=datetime(2026, 9, 18)), \
         patch.object(weather, "fetch_historical", return_value="soon"):
        view = app(historical=None)
        join_climate(view)
    assert view.historical == "soon"


def test_a_view_with_its_climate_does_not_ask_the_archive():
    with patch.object(weather, "fetch_historical") as fh:
        view = app(historical="have")
        with view._state_lock:
            view._start_climate()
    assert view._climate_worker is None and not fh.called
