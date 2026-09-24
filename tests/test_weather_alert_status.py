"""Whether the alerts are the provider's answer (issue #122).

An empty list is either a quiet day or a feed that could not be asked;
fetch_alerts says which, and the dashboard and `--json` pass it on.
"""

import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from linecast import _cache, _http
from linecast._runtime import WeatherRuntime
from linecast.weather import sources
from linecast.weather.json import build_payload
from linecast.weather.sources import AlertList, alerts_status, fetch_alerts

FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 3, 5, 14, 30)
PORTLAND = (43.66, -70.25)


@pytest.fixture(autouse=True)
def cache(tmp_path):
    with patch.dict(os.environ, {"LINECAST_CACHE_DIR": str(tmp_path)}):
        yield tmp_path


def _offline():
    return patch.object(_http, "fetch_json", side_effect=OSError("provider offline"))


def _answering(payload):
    return patch.object(_http, "fetch_json", return_value=payload)


def _feature(event, expires):
    return {"properties": {"status": "Actual", "event": event, "headline": event,
                           "description": "", "effective": "", "severity": "Moderate",
                           "expires": expires, "web": ""}}


def _iso(dt):
    return dt.isoformat(timespec="seconds")


def _age_cache(cache, seconds):
    """Make every cached alert file `seconds` old."""
    then = time.time() - seconds
    for path in cache.rglob("alerts_*.json"):
        os.utime(path, (then, then))
    return then


class TestFetchStatus:
    def test_a_cold_cache_failure_is_unavailable(self):
        with _offline():
            got = fetch_alerts(*PORTLAND, "US")
        assert got == []
        assert got.status == "unavailable"
        assert got.fetched_at is None

    def test_an_empty_answer_is_ok(self):
        with _answering({"features": []}):
            got = fetch_alerts(*PORTLAND, "US")
        assert got == []
        assert got.status == "ok"
        fetched = datetime.fromisoformat(got.fetched_at)
        assert abs(fetched - datetime.now(timezone.utc)) < timedelta(minutes=1)

    def test_the_two_are_told_apart(self):
        """The issue's reproduction: both used to come back as a bare []."""
        with _offline():
            unavailable = fetch_alerts(*PORTLAND, "US")
        with _answering({"features": []}):
            quiet = fetch_alerts(*PORTLAND, "US")
        assert unavailable == quiet == []
        assert (unavailable.status, quiet.status) == ("unavailable", "ok")

    def test_a_fresh_cache_hit_is_ok(self):
        later = _iso(datetime.now(timezone.utc) + timedelta(hours=6))
        with _answering({"features": [_feature("Wind Advisory", later)]}):
            fetch_alerts(*PORTLAND, "US")
        with _offline() as fetch:
            got = fetch_alerts(*PORTLAND, "US")
        fetch.assert_not_called()
        assert [a["event"] for a in got] == ["Wind Advisory"]
        assert got.status == "ok"

    def test_a_failure_with_a_cached_copy_is_stale(self, cache):
        later = _iso(datetime.now(timezone.utc) + timedelta(hours=6))
        with _answering({"features": [_feature("Wind Advisory", later)]}):
            fetch_alerts(*PORTLAND, "US")
        then = _age_cache(cache, 3600)
        with _offline():
            got = fetch_alerts(*PORTLAND, "US")
        assert [a["event"] for a in got] == ["Wind Advisory"]
        assert got.status == "stale"
        assert got.fetched_at == _iso(datetime.fromtimestamp(int(then), timezone.utc))

    def test_a_stale_copy_drops_what_has_expired(self, cache):
        now = datetime.now(timezone.utc)
        with _answering({"features": [
                _feature("Wind Advisory", _iso(now - timedelta(minutes=5))),
                _feature("Flood Watch", _iso(now + timedelta(days=2)))]}):
            fetch_alerts(*PORTLAND, "US")
        _age_cache(cache, 3600)
        # The cached copy still holds the advisory that has run out.
        assert len(_cache.read_stale(next(cache.rglob("alerts_*.json")))) == 2
        with _offline():
            got = fetch_alerts(*PORTLAND, "US")
        assert [a["event"] for a in got] == ["Flood Watch"]
        assert got.status == "stale"

    def test_recovery_after_a_failure_is_ok(self):
        with _offline():
            assert fetch_alerts(*PORTLAND, "US").status == "unavailable"
        with _answering({"features": []}):
            assert fetch_alerts(*PORTLAND, "US").status == "ok"

    def test_recovery_from_a_stale_copy_is_ok(self, cache):
        with _answering({"features": []}):
            fetch_alerts(*PORTLAND, "US")
        _age_cache(cache, 3600)
        with _offline():
            assert fetch_alerts(*PORTLAND, "US").status == "stale"
        with _answering({"features": []}):
            got = fetch_alerts(*PORTLAND, "US")
        assert got.status == "ok"
        fetched = datetime.fromisoformat(got.fetched_at)
        assert abs(fetched - datetime.now(timezone.utc)) < timedelta(minutes=1)

    @pytest.mark.parametrize("country", ["IR", "BR", ""])
    def test_a_country_without_a_feed_is_unsupported(self, country):
        with _offline() as fetch:
            got = fetch_alerts(-23.5, -46.6, country)
        fetch.assert_not_called()
        assert got == []
        assert (got.status, got.fetched_at) == ("unsupported", None)

    @pytest.mark.parametrize("country, lat, lng", [
        ("CA", 45.4, -75.7), ("DE", 52.5, 13.4), ("NO", 59.9, 10.7),
        ("IE", 53.3, -6.3), ("HK", 22.3, 114.2), ("CN", 39.9, 116.4),
        ("NL", 52.4, 4.9),
    ])
    def test_every_json_feed_reports_a_cold_failure(self, country, lat, lng):
        with _offline():
            got = fetch_alerts(lat, lng, country, address={})
        assert (got, got.status) == ([], "unavailable")

    def test_the_byte_feeds_report_a_cold_failure(self):
        with patch.object(_http, "fetch_bytes", side_effect=OSError("offline")), _offline():
            nz = fetch_alerts(-41.3, 174.8, "NZ")
            india = fetch_alerts(28.6, 77.2, "IN")
        assert (nz.status, india.status) == ("unavailable", "unavailable")

    def test_an_unwritable_cache_still_reads_as_ok(self):
        with _answering({"features": []}), \
             patch.object(sources, "write_cache"), \
             patch.object(_http, "write_cache"):
            got = fetch_alerts(*PORTLAND, "US")
        assert (got, got.status) == ([], "ok")


class TestJson:
    def _payload(self, alerts):
        data = json.loads((FIXTURES / "open_meteo_forecast.json").read_text(encoding="utf-8"))
        runtime = WeatherRuntime(live=False, icons="emoji", lang="en", oneline=False,
                                 celsius=False, metric=False, shading=False)
        return build_payload(data, "Portland", "US", runtime, alerts=alerts, now=NOW)

    def test_alerts_stay_a_list_with_the_status_beside_it(self):
        alerts = AlertList([{"event": "Wind Advisory"}], status="stale",
                           fetched_at="2026-03-05T12:00:00+00:00")
        payload = json.loads(json.dumps(self._payload(alerts)))
        assert payload["alerts"] == [{"event": "Wind Advisory"}]
        assert payload["alerts_status"] == {"status": "stale",
                                            "fetched_at": "2026-03-05T12:00:00+00:00"}

    def test_unavailable_is_reported(self):
        payload = self._payload(AlertList(status="unavailable"))
        assert payload["alerts"] == []
        assert payload["alerts_status"] == {"status": "unavailable", "fetched_at": None}

    def test_a_plain_list_reads_as_ok(self):
        assert self._payload([])["alerts_status"] == {"status": "ok", "fetched_at": None}
        assert alerts_status(None) == {"status": "ok", "fetched_at": None}


class TestView:
    def _render(self, alerts, lang="en", cols=80, rows=40):
        from linecast.weather.view import render_from_data

        data = json.loads((FIXTURES / "open_meteo_forecast.json").read_text(encoding="utf-8"))
        runtime = WeatherRuntime(live=False, icons="emoji", lang=lang, oneline=False,
                                 celsius=False, metric=False, shading=False)
        with patch("linecast.weather.view.get_terminal_size", return_value=(cols, rows)), \
             patch("linecast.weather.view._local_now_for_data", return_value=NOW), \
             patch("linecast.weather.hourly._local_now_for_data", return_value=NOW):
            output, row_map = render_from_data(data, alerts=alerts, runtime=runtime,
                                               location_name="Portland")
        return output.split("\x00", 1)[0], row_map

    def test_unavailable_says_so(self):
        output, row_map = self._render(AlertList(status="unavailable"))
        assert "Alerts could not be checked." in output
        assert row_map == {}

    def test_it_is_translated(self):
        output, _ = self._render(AlertList(status="unavailable"), lang="de")
        assert "Warnungen konnten nicht abgerufen werden." in output

    @pytest.mark.parametrize("alerts", [
        AlertList(status="ok"), AlertList(status="unsupported"), [],
    ])
    def test_ok_and_unsupported_say_nothing(self, alerts):
        output, _ = self._render(alerts)
        assert "Alerts" not in output

    def test_stale_says_when_under_the_alerts(self):
        alerts = AlertList([{"event": "Wind Advisory", "severity": "Moderate",
                             "description": "", "effective": "", "expires": ""}],
                           status="stale", fetched_at="2026-03-05T12:00:00+00:00")
        output, row_map = self._render(alerts)
        lines = output.split("\n")
        note = next(i for i, line in enumerate(lines) if "Alerts as of" in line)
        assert "Wind Advisory" in lines[note - 1]
        assert note - 1 in row_map and note not in row_map

    def test_the_note_never_costs_the_forecast(self):
        full, _ = self._render([], rows=24)
        noted, _ = self._render(AlertList(status="unavailable"), rows=24)
        assert len(noted.split("\n")) <= 24
        assert "Overcast" in noted.split("\n")[0] and "Overcast" in full.split("\n")[0]


class TestGather:
    def test_a_feed_that_raises_is_unavailable(self):
        from linecast.weather import view as weather
        runtime = WeatherRuntime(live=False, icons="emoji", lang="en", oneline=False,
                                 celsius=False, metric=False, shading=False)
        with patch.object(weather, "_reverse_geocode", return_value=("Portland", "US", {})), \
             patch.object(weather, "fetch_forecast", return_value=None), \
             patch.object(weather, "fetch_aqi", return_value=None), \
             patch.object(weather, "fetch_observation", return_value=None), \
             patch.object(weather, "fetch_historical", return_value=None), \
             patch.object(weather, "fetch_alerts", side_effect=TypeError("null")):
            result = weather.gather(*PORTLAND, "US", runtime, geo_label="Portland")
        assert result["alerts"] == []
        assert alerts_status(result["alerts"])["status"] == "unavailable"
