"""Tests for weather API response parsing.

These use real API responses saved as fixtures. If an upstream API changes
its response format, these tests will catch the breakage.
"""

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

FIXTURES = Path(__file__).parent / "fixtures"

# Ensure the package is importable
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


def _load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Open-Meteo forecast parsing
# ---------------------------------------------------------------------------

class TestOpenMeteoForecast:
    """Verify we can parse a real Open-Meteo response without errors."""

    def setup_method(self):
        self.data = _load("open_meteo_forecast.json")

    def test_top_level_keys(self):
        for key in ("current", "hourly", "daily", "timezone", "utc_offset_seconds"):
            assert key in self.data, f"Missing top-level key: {key}"

    def test_current_conditions(self):
        current = self.data["current"]
        for key in ("temperature_2m", "apparent_temperature", "weather_code",
                     "wind_speed_10m", "wind_gusts_10m"):
            assert key in current, f"Missing current key: {key}"
            assert isinstance(current[key], (int, float)), f"{key} should be numeric"

    def test_hourly_arrays_aligned(self):
        hourly = self.data["hourly"]
        n = len(hourly["time"])
        assert n > 0, "No hourly time entries"
        for key in ("temperature_2m", "precipitation_probability",
                     "weather_code", "wind_speed_10m"):
            assert key in hourly, f"Missing hourly key: {key}"
            assert len(hourly[key]) == n, f"hourly[{key}] length mismatch"

    def test_daily_arrays_aligned(self):
        daily = self.data["daily"]
        n = len(daily["time"])
        assert n > 0, "No daily time entries"
        for key in ("temperature_2m_max", "temperature_2m_min",
                     "precipitation_sum", "weather_code", "sunrise", "sunset"):
            assert key in daily, f"Missing daily key: {key}"
            assert len(daily[key]) == n, f"daily[{key}] length mismatch"

    def test_hourly_timestamps_parseable(self):
        for t in self.data["hourly"]["time"][:5]:
            dt = datetime.fromisoformat(t)
            assert dt.year >= 2024

    def test_daily_sunrise_sunset_parseable(self):
        daily = self.data["daily"]
        for s in daily["sunrise"]:
            if s:
                dt = datetime.fromisoformat(s)
                assert dt.hour < 12  # sunrise before noon

    def test_render_header_succeeds(self):
        """Smoke test: render_header doesn't crash on real data."""
        import linecast.weather.view as w
        result = w.render_header(self.data, 80, "Test City")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_render_hourly_succeeds(self):
        """Smoke test: render_hourly doesn't crash on real data."""
        import linecast.weather.view as w
        now = datetime.fromisoformat(self.data["hourly"]["time"][24])
        result = w.render_hourly(self.data, 80, now=now)
        assert isinstance(result, list)

    def test_narrative_lines_succeeds(self):
        """Smoke test: narrative_lines doesn't crash on real data."""
        import linecast.weather.view as w
        now = datetime.fromisoformat(self.data["hourly"]["time"][24])
        result = w.narrative_lines(self.data, now, 80)
        assert isinstance(result, list)
        assert all(isinstance(line, str) for line in result)


# ---------------------------------------------------------------------------
# NWS alerts parsing
# ---------------------------------------------------------------------------

class TestNWSAlerts:
    """Verify we can parse a real NWS alerts response."""

    def setup_method(self):
        self.data = _load("nws_alerts.json")

    def test_top_level_structure(self):
        assert "features" in self.data
        assert isinstance(self.data["features"], list)

    def test_alert_properties_shape(self):
        """If there are alerts, each has the fields we extract."""
        for feature in self.data["features"]:
            props = feature["properties"]
            # These are the fields _fetch_alerts_nws extracts
            for key in ("event", "headline", "description", "severity"):
                assert key in props, f"Missing alert property: {key}"


class TestNWSAlertsFilterTestMessages:
    """Verify that NWS test/exercise alerts are filtered out."""

    def setup_method(self):
        self.data = _load("nws_alerts_with_test.json")

    def test_fixture_has_both_test_and_actual(self):
        statuses = [f["properties"]["status"] for f in self.data["features"]]
        assert "Test" in statuses
        assert "Actual" in statuses

    def test_parser_drops_test_alerts(self):
        from linecast.weather.sources import _fetch_alerts_nws
        with patch("linecast.weather.sources.fetch_json_cached", return_value=self.data):
            alerts = _fetch_alerts_nws(40.7, -74.0)
        assert len(alerts) == 1
        assert alerts[0]["event"] == "Heat Advisory"

    def test_parser_drops_exercise_alerts(self):
        """Exercise status should also be filtered."""
        import copy
        data = copy.deepcopy(self.data)
        data["features"][1]["properties"]["status"] = "Exercise"
        from linecast.weather.sources import _fetch_alerts_nws
        with patch("linecast.weather.sources.fetch_json_cached", return_value=data):
            alerts = _fetch_alerts_nws(40.7, -74.0)
        assert len(alerts) == 0


class TestNWSAlertWindow:
    """An NWS alert shows when the hazard is, not when the bulletin is."""

    @staticmethod
    def _parse(**times):
        from linecast.weather.sources import _fetch_alerts_nws
        props = {"status": "Actual", "event": "High Wind Watch",
                 "effective": "2026-09-23T15:33:00-04:00",
                 "expires": "2026-09-24T05:00:00-04:00", **times}
        data = {"features": [{"properties": props}]}
        with patch("linecast.weather.sources.fetch_json_cached", return_value=data):
            return _fetch_alerts_nws(42.05, -70.19)[0]

    def test_onset_and_ends_over_the_bulletin(self):
        alert = self._parse(onset="2026-09-25T20:00:00-04:00",
                            ends="2026-09-27T08:00:00-04:00")
        assert alert["effective"] == "2026-09-25T20:00:00-04:00"
        assert alert["expires"] == "2026-09-27T08:00:00-04:00"

    def test_no_ends_keeps_an_expiry_after_the_onset(self):
        alert = self._parse(onset="2026-09-23T15:33:00-04:00", ends=None)
        assert alert["expires"] == "2026-09-24T05:00:00-04:00"

    def test_no_ends_drops_an_expiry_before_the_onset(self):
        alert = self._parse(onset="2026-09-25T20:00:00-04:00", ends=None)
        assert alert["effective"] == "2026-09-25T20:00:00-04:00"
        assert alert["expires"] == ""

    def test_no_onset_falls_back_to_effective(self):
        alert = self._parse()
        assert alert["effective"] == "2026-09-23T15:33:00-04:00"
        assert alert["expires"] == "2026-09-24T05:00:00-04:00"


# ---------------------------------------------------------------------------
# ECCC alerts parsing
# ---------------------------------------------------------------------------

class TestECCCAlerts:
    """Verify we can parse a real ECCC alerts response."""

    def setup_method(self):
        self.data = _load("eccc_alerts.json")

    def test_top_level_structure(self):
        assert "features" in self.data
        assert isinstance(self.data["features"], list)

    def test_alert_properties_shape(self):
        """If there are alerts, each has the fields we extract."""
        for feature in self.data["features"]:
            props = feature["properties"]
            # At minimum, ECCC features have these
            assert isinstance(props, dict)


# ---------------------------------------------------------------------------
# Bright Sky (DWD/Germany) alerts parsing
# ---------------------------------------------------------------------------

class TestBrightSkyAlerts:
    """Verify we can parse a real Bright Sky alerts response."""

    def setup_method(self):
        self.data = _load("brightsky_alerts.json")

    def test_top_level_structure(self):
        assert "alerts" in self.data
        assert isinstance(self.data["alerts"], list)

    def test_alert_fields(self):
        for alert in self.data["alerts"]:
            for key in ("severity", "event_en", "headline_en", "effective", "expires"):
                assert key in alert, f"Missing Bright Sky alert key: {key}"

    def test_parse_produces_normalized_alerts(self):
        """Smoke test: _fetch_alerts_brightsky parser produces our standard dict."""
        from linecast.weather.sources import _fetch_alerts_brightsky
        with patch("linecast.weather.sources.fetch_json_cached", return_value=self.data):
            alerts = _fetch_alerts_brightsky(52.52, 13.405)
        assert isinstance(alerts, list)
        for a in alerts:
            for key in ("event", "headline", "description", "severity", "effective", "expires",
                        "url"):
                assert key in a, f"Missing normalized key: {key}"

    def test_starts_at_the_onset(self):
        """The frost begins at midnight, not when DWD issued the warning."""
        from linecast.weather.sources import _fetch_alerts_brightsky
        with patch("linecast.weather.sources.fetch_json_cached", return_value=self.data):
            alerts = _fetch_alerts_brightsky(52.52, 13.405)
        assert alerts[0]["effective"] == "2026-03-07T00:00:00+00:00"


# ---------------------------------------------------------------------------
# MET Norway alerts parsing
# ---------------------------------------------------------------------------

class TestMetNoAlerts:
    """Verify we can parse a real MET Norway MetAlerts response."""

    def setup_method(self):
        self.data = _load("metno_alerts.json")

    def test_top_level_structure(self):
        assert "features" in self.data
        assert isinstance(self.data["features"], list)
        assert len(self.data["features"]) > 0

    def test_feature_has_when(self):
        for feature in self.data["features"]:
            assert "when" in feature, "Feature missing 'when'"
            interval = feature["when"].get("interval", [])
            assert len(interval) == 2, "when.interval should have [onset, expires]"

    def test_feature_properties(self):
        for feature in self.data["features"]:
            props = feature["properties"]
            for key in ("event", "severity", "title"):
                assert key in props, f"Missing MetNo property: {key}"

    def test_parse_produces_normalized_alerts(self):
        from linecast.weather.sources import _fetch_alerts_metno
        with patch("linecast.weather.sources.fetch_json_cached", return_value=self.data):
            alerts = _fetch_alerts_metno(59.91, 10.75)
        assert isinstance(alerts, list)
        assert len(alerts) > 0
        for a in alerts:
            for key in ("event", "headline", "severity", "effective", "expires"):
                assert key in a, f"Missing normalized key: {key}"


# ---------------------------------------------------------------------------
# Met Éireann alerts parsing
# ---------------------------------------------------------------------------

class TestMetEireannAlerts:
    """Verify we can parse a real Met Éireann warnings response."""

    def setup_method(self):
        self.data = _load("meteireann_warnings.json")

    def test_top_level_structure(self):
        assert "warnings" in self.data
        warnings = self.data["warnings"]
        for cat in ("national", "marine", "environmental"):
            assert cat in warnings, f"Missing category: {cat}"
            assert isinstance(warnings[cat], list)

    def test_parse_produces_normalized_alerts(self):
        from linecast.weather.sources import _fetch_alerts_meteireann
        with patch("linecast.weather.sources.fetch_json_cached", return_value=self.data):
            alerts = _fetch_alerts_meteireann(53.35, -6.26)
        assert isinstance(alerts, list)
        for a in alerts:
            for key in ("event", "headline", "severity", "effective", "expires"):
                assert key in a, f"Missing normalized key: {key}"


# ---------------------------------------------------------------------------
# MeteoAlarm (pan-European) alerts parsing
# ---------------------------------------------------------------------------

class TestMeteoAlarmAlerts:
    """Verify we can parse a real MeteoAlarm response."""

    def setup_method(self):
        self.data = _load("meteoalarm_netherlands.json")

    def test_top_level_structure(self):
        assert "warnings" in self.data
        assert isinstance(self.data["warnings"], list)

    def test_warning_has_alert_with_info(self):
        for w in self.data["warnings"]:
            assert "alert" in w
            assert "info" in w["alert"]
            assert isinstance(w["alert"]["info"], list)
            assert len(w["alert"]["info"]) > 0

    def test_info_has_required_fields(self):
        for w in self.data["warnings"]:
            for info in w["alert"]["info"]:
                for key in ("severity", "event", "language"):
                    assert key in info, f"Missing MeteoAlarm info key: {key}"

    def test_parse_with_area_filter(self):
        from linecast.weather.sources import _fetch_alerts_meteoalarm
        address = {"city": "Amsterdam", "state": "Noord-Holland"}
        with patch("linecast.weather.sources.fetch_json_cached", return_value=self.data):
            alerts = _fetch_alerts_meteoalarm(52.37, 4.89, "netherlands", address=address)
        assert isinstance(alerts, list)
        for a in alerts:
            for key in ("event", "headline", "severity", "effective", "expires"):
                assert key in a, f"Missing normalized key: {key}"

    def test_parse_without_address(self):
        """Without address, should still return Severe+ alerts."""
        from linecast.weather.sources import _fetch_alerts_meteoalarm
        with patch("linecast.weather.sources.fetch_json_cached", return_value=self.data):
            alerts = _fetch_alerts_meteoalarm(52.37, 4.89, "netherlands", address=None)
        assert isinstance(alerts, list)


# ---------------------------------------------------------------------------
# JMA alerts parsing
# ---------------------------------------------------------------------------

class TestMeteoAlarmFeedSize:
    """A feed that outlines every warning is bigger than fetch_json allows."""

    def test_the_feed_is_fetched_under_a_wider_cap(self):
        from linecast.weather import sources as ws
        from linecast._http import MAX_JSON_BYTES
        seen = {}

        def miss(cache_file, max_age, url, **kwargs):
            # a cache miss: fetch_json_cached hands the network step to `fetch`
            return kwargs["fetch"](url, timeout=kwargs["timeout"])

        def fetch_json(url, headers=None, timeout=10, limit=MAX_JSON_BYTES):
            seen.update(url=url, limit=limit, accept=(headers or {}).get("Accept"))
            return {"warnings": []}

        with patch.object(ws, "fetch_json_cached", side_effect=miss), \
                patch.object(ws, "fetch_json", fetch_json), \
                patch.object(ws, "write_cache", lambda *a, **k: None):
            ws._fetch_alerts_meteoalarm(46.95, 7.45, "switzerland", address={})
        assert seen["url"].endswith("/feeds-switzerland")
        assert seen["accept"] == "application/json"
        assert seen["limit"] == ws._METEOALARM_FEED_BYTES
        # 9.4 MB on a quiet September day; give a stormy one room
        assert seen["limit"] >= 3 * MAX_JSON_BYTES


class TestJMAAlerts:
    """Verify we can parse a real JMA warning response."""

    def setup_method(self):
        self.data = _load("jma_warning_tokyo.json")

    def test_top_level_structure(self):
        assert "headlineText" in self.data
        assert "reportDatetime" in self.data
        assert "areaTypes" in self.data
        assert isinstance(self.data["areaTypes"], list)

    def test_parse_produces_normalized_alerts_en(self):
        from linecast.weather.sources import _fetch_alerts_jma
        with patch("linecast.weather.sources.fetch_json_cached", return_value=self.data):
            alerts = _fetch_alerts_jma(35.6764, 139.6500, lang="en")
        assert isinstance(alerts, list)
        assert len(alerts) > 0
        for a in alerts:
            for key in ("event", "headline", "description", "severity", "effective", "expires",
                        "url"):
                assert key in a, f"Missing normalized key: {key}"
        # Active warning codes should be deduped across areas.
        assert len(alerts) == 3
        assert alerts[0]["severity"] == "Severe"
        assert alerts[0]["event"] == "Heavy Rain Warning"
        assert alerts[0]["headline"] == "Heavy Rain Warning"
        assert alerts[0]["effective"] == "2026-03-07T09:00:00+09:00"
        assert alerts[0]["expires"] == ""
        assert alerts[0]["url"] == "https://www.jma.go.jp/bosai/warning/"

    def test_parse_produces_normalized_alerts_ja(self):
        from linecast.weather.sources import _fetch_alerts_jma
        with patch("linecast.weather.sources.fetch_json_cached", return_value=self.data):
            alerts = _fetch_alerts_jma(35.6764, 139.6500, lang="ja")
        assert isinstance(alerts, list)
        assert len(alerts) == 3
        # In Japanese mode, event names are localized and headline uses JMA headline text.
        assert alerts[0]["event"] == "大雨警報"
        assert alerts[0]["headline"] == self.data["headlineText"]
        assert alerts[0]["description"] == self.data["headlineText"]


class TestJMAAreaFilter:
    """A reader hears their own municipality's warnings, not the prefecture's.

    The feed is Tokyo's on a day the Izu islands had wind, wave, thunder
    and fog watches and the mainland had nothing; the table is JMA's area
    list cut down to Tokyo, plus Hiroshima's 府中市 as a namesake.
    """

    IZU_SOUTH = "伊豆諸島南部では、強風や高波に注意してください。"
    IZU_BOTH = ("伊豆諸島北部、伊豆諸島南部では、"
                "急な強い雨や落雷、濃霧による視程障害に注意してください。")

    def setup_method(self):
        self.feed = _load("jma_warning_izu.json")
        self.table = _load("jma_area_tokyo.json")

    def _alerts(self, address, lang="ja", table=None):
        from linecast.weather import sources as ws
        urls = []

        def cached(cache_file, max_age, url, **kwargs):
            urls.append(url)
            if url.endswith("area.json"):
                return self.table if table is None else table
            return self.feed

        with patch.object(ws, "fetch_json_cached", side_effect=cached), \
                patch.object(ws, "write_cache"):
            alerts = ws._fetch_alerts_jma(35.61, 139.73, lang=lang, address=address)
        return alerts, urls

    def test_shinagawa_hears_nothing_of_the_izu_islands(self):
        alerts, _urls = self._alerts({"city": "品川区", "ISO3166-2-lvl4": "JP-13"})
        assert alerts == []

    def test_hachijo_gets_the_southern_islands_watches(self):
        alerts, _urls = self._alerts({"town": "八丈町", "ISO3166-2-lvl4": "JP-13"})
        assert {a["event"] for a in alerts} == {
            "雷注意報", "強風注意報", "波浪注意報", "濃霧注意報"}
        assert alerts[0]["description"] == self.IZU_SOUTH + self.IZU_BOTH

    def test_oshima_keeps_only_the_sentence_that_names_it(self):
        # Nominatim files the island town under `town`, with the prefecture as `city`
        address = {"town": "大島町", "county": "大島支庁", "city": "東京都",
                   "ISO3166-2-lvl4": "JP-13"}
        alerts, _urls = self._alerts(address)
        assert {a["event"] for a in alerts} == {"雷注意報", "濃霧注意報"}
        assert alerts[0]["headline"] == self.IZU_BOTH
        assert alerts[0]["description"] == self.IZU_BOTH

    def test_the_english_description_is_filtered_too(self):
        alerts, _urls = self._alerts({"town": "大島町", "ISO3166-2-lvl4": "JP-13"}, lang="en")
        assert {a["event"] for a in alerts} == {"Thunderstorm Watch", "Dense Fog Watch"}
        assert alerts[0]["headline"] == alerts[0]["event"]
        assert alerts[0]["description"] == self.IZU_BOTH

    def test_no_address_pools_the_whole_office(self):
        alerts, urls = self._alerts(None)
        assert len(alerts) == 4
        assert alerts[0]["description"] == self.feed["headlineText"]
        assert not any(u.endswith("area.json") for u in urls)

    def test_an_unlisted_municipality_pools_the_whole_office(self):
        alerts, _urls = self._alerts({"city": "架空市", "ISO3166-2-lvl4": "JP-13"})
        assert len(alerts) == 4

    def test_a_table_that_cannot_be_read_pools_the_whole_office(self):
        alerts, _urls = self._alerts({"city": "品川区", "ISO3166-2-lvl4": "JP-13"}, table=[])
        assert len(alerts) == 4

    def test_the_prefecture_keeps_a_namesake_out(self):
        # Tokyo and Hiroshima each have a 府中市; the address says which
        _alerts, urls = self._alerts({"city": "府中市", "ISO3166-2-lvl4": "JP-34"})
        assert urls[-1].endswith("/340000.json")
        _alerts, urls = self._alerts({"city": "府中市", "ISO3166-2-lvl4": "JP-13"})
        assert urls[-1].endswith("/130000.json")

    def test_without_a_prefecture_the_nearest_office_decides(self):
        from linecast.weather.sources import _jma_area_for_address
        with patch("linecast.weather.sources.fetch_json_cached", return_value=self.table):
            tokyo = _jma_area_for_address({"city": "府中市"}, "130000")
            hiroshima = _jma_area_for_address({"city": "府中市"}, "340000")
        assert tokyo["codes"] == ["1320600"]
        assert hiroshima["codes"] == ["3420800"]

    def test_a_city_split_into_parts_pools_them(self):
        from linecast.weather.sources import _jma_area_for_address
        table = {
            "offices": {"140000": {"name": "神奈川県"}},
            "class10s": {"140010": {"name": "東部", "parent": "140000"}},
            "class15s": {"140011": {"name": "横浜・川崎", "parent": "140010"}},
            "class20s": {"1410011": {"name": "横浜市北部", "parent": "140011"},
                         "1410012": {"name": "横浜市南部", "parent": "140011"},
                         "1413000": {"name": "川崎市", "parent": "140011"}},
        }
        with patch("linecast.weather.sources.fetch_json_cached", return_value=table):
            area = _jma_area_for_address({"city": "横浜市", "ISO3166-2-lvl4": "JP-14"}, "140000")
        assert area["office"] == "140000"
        assert sorted(area["codes"]) == ["1410011", "1410012"]
        assert area["names"] == {"横浜市北部", "横浜市南部", "横浜・川崎", "東部", "神奈川県"}

    def test_a_headline_that_excepts_an_area_counts_its_reader_out(self):
        from linecast.weather.sources import _jma_headline_for
        headline = "小笠原諸島を除く東京都では、乾燥に注意してください。"
        mainland = {"品川区", "２３区西部", "東京地方", "東京都"}
        assert _jma_headline_for(headline, mainland) == headline
        assert _jma_headline_for(headline, {"小笠原村", "小笠原諸島", "東京都"}) == ""

    def test_a_sentence_that_names_no_area_is_for_everyone(self):
        from linecast.weather.sources import _jma_headline_for
        headline = "落雷に注意してください。伊豆諸島南部では、高波に注意してください。"
        assert _jma_headline_for(headline, {"品川区"}) == "落雷に注意してください。"


# ---------------------------------------------------------------------------
# Alert expiry (issue #70)
# ---------------------------------------------------------------------------

def _alert(expires, event="Wind Advisory", severity="Minor"):
    return {"event": event, "headline": event, "description": "",
            "effective": "", "expires": expires, "severity": severity, "url": ""}


class TestAlertExpiry:
    """An alert past its own expiry is dropped, however it reached us."""

    NOW = datetime(2026, 9, 3, 12, 0, tzinfo=timezone.utc)

    def test_expiry_reads_each_provider_format(self):
        from linecast.weather.sources import _alert_expiry
        # NWS, Bright Sky, MET Norway, MeteoAlarm, HKO: an offset
        assert (_alert_expiry(_alert("2026-09-03T18:00:00-04:00"))
                == datetime(2026, 9, 3, 22, 0, tzinfo=timezone.utc))
        # ECCC: milliseconds and a Z, which Python 3.10 cannot read as-is
        assert (_alert_expiry(_alert("2026-03-06T06:00:00.000Z"))
                == datetime(2026, 3, 6, 6, 0, tzinfo=timezone.utc))
        # No offset at all is taken as UTC rather than never expiring
        assert (_alert_expiry(_alert("2026-03-07T18:00:00"))
                == datetime(2026, 3, 7, 18, 0, tzinfo=timezone.utc))

    def test_no_expiry_is_none(self):
        from linecast.weather.sources import _alert_expiry
        assert _alert_expiry(_alert("")) is None
        assert _alert_expiry(_alert(None)) is None
        assert _alert_expiry(_alert("next Tuesday")) is None
        assert _alert_expiry({"event": "x"}) is None
        assert _alert_expiry("not an alert") is None

    def test_lapsed_alerts_are_dropped_and_the_rest_kept(self):
        from linecast.weather.sources import _drop_expired
        lapsed = _alert("2026-09-01T18:00:00+00:00")
        current = _alert("2026-09-03T18:00:00+00:00")
        open_ended = _alert("")
        assert _drop_expired([lapsed, current, open_ended], now=self.NOW) == [
            current, open_ended]

    def test_fetch_alerts_drops_a_lapsed_alert_from_any_provider(self):
        from linecast.weather.sources import fetch_alerts
        lapsed = _alert("2026-01-01T00:00:00+00:00", event="Old")
        current = _alert("2035-01-01T00:00:00+00:00", event="New")
        with patch("linecast.weather.sources._fetch_alerts_nws",
                   return_value=[lapsed, current]):
            assert fetch_alerts(40.7, -74.0, country_code="US") == [current]

    def test_lapsed_alerts_do_not_count_against_the_cap(self):
        from linecast.weather.sources import MAX_ALERTS, fetch_alerts
        lapsed = [_alert("2026-01-01T00:00:00+00:00", event=f"Old {i}",
                         severity="Extreme") for i in range(MAX_ALERTS + 1)]
        current = _alert("2035-01-01T00:00:00+00:00", event="New")
        with patch("linecast.weather.sources._fetch_alerts_nws",
                   return_value=lapsed + [current]):
            assert fetch_alerts(40.7, -74.0, country_code="US") == [current]

    def test_a_stale_copy_kept_through_an_outage_does_not_outlive_its_alert(self):
        """The cached list stands in when the provider is unreachable; an
        alert that lapsed in the meantime must not come back with it."""
        from linecast._cache import location_cache_key
        from linecast._paths import cache_dir
        from linecast.weather.sources import fetch_alerts
        cache_file = cache_dir("weather") / f"alerts_{location_cache_key(40.7, -74.0)}.json"
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        lapsed = _alert("2026-01-01T00:00:00+00:00", event="Old")
        current = _alert("2035-01-01T00:00:00+00:00", event="New")
        cache_file.write_text(json.dumps([lapsed, current]), encoding="utf-8")
        an_hour_ago = time.time() - 3600  # past the fifteen-minute cache
        os.utime(cache_file, (an_hour_ago, an_hour_ago))
        with patch("linecast._http.fetch_json", side_effect=OSError("down")) as net:
            assert fetch_alerts(40.7, -74.0, country_code="US") == [current]
        assert net.called


# ---------------------------------------------------------------------------
# Alert provider dispatch tests
# ---------------------------------------------------------------------------

class TestAlertProviderRouting:
    """Ensure fetch_alerts routes to the expected provider for each country."""

    def test_routes_us_to_nws(self):
        from linecast.weather.sources import fetch_alerts
        with patch("linecast.weather.sources._fetch_alerts_nws",
                   return_value=[{"event": "x"}]) as mock_fn:
            result = fetch_alerts(40.7, -74.0, country_code="US")
        mock_fn.assert_called_once_with(40.7, -74.0)
        assert result == [{"event": "x"}]

    def test_routes_ca_to_eccc(self):
        from linecast.weather.sources import fetch_alerts
        with patch("linecast.weather.sources._fetch_alerts_eccc",
                   return_value=[{"event": "x"}]) as mock_fn:
            result = fetch_alerts(45.4, -75.7, country_code="CA", lang="fr")
        mock_fn.assert_called_once_with(45.4, -75.7, lang="fr")
        assert result == [{"event": "x"}]

    def test_routes_de_to_brightsky(self):
        from linecast.weather.sources import fetch_alerts
        with patch("linecast.weather.sources._fetch_alerts_brightsky",
                   return_value=[{"event": "x"}]) as mock_fn:
            result = fetch_alerts(52.52, 13.405, country_code="DE", lang="de")
        mock_fn.assert_called_once_with(52.52, 13.405, lang="de")
        assert result == [{"event": "x"}]

    def test_routes_no_to_metno(self):
        from linecast.weather.sources import fetch_alerts
        with patch("linecast.weather.sources._fetch_alerts_metno",
                   return_value=[{"event": "x"}]) as mock_fn:
            result = fetch_alerts(59.91, 10.75, country_code="NO")
        mock_fn.assert_called_once_with(59.91, 10.75)
        assert result == [{"event": "x"}]

    def test_routes_ie_to_meteireann(self):
        from linecast.weather.sources import fetch_alerts
        with patch("linecast.weather.sources._fetch_alerts_meteireann",
                   return_value=[{"event": "x"}]) as mock_fn:
            result = fetch_alerts(53.35, -6.26, country_code="IE")
        mock_fn.assert_called_once_with(53.35, -6.26)
        assert result == [{"event": "x"}]

    def test_routes_jp_to_jma(self):
        from linecast.weather.sources import fetch_alerts
        with patch("linecast.weather.sources._fetch_alerts_jma",
                   return_value=[{"event": "x"}]) as mock_fn:
            result = fetch_alerts(35.68, 139.76, country_code="JP", lang="ja")
        mock_fn.assert_called_once_with(35.68, 139.76, lang="ja", address=None)
        assert result == [{"event": "x"}]

    def test_routes_meteoalarm_country(self):
        from linecast.weather.sources import fetch_alerts
        address = {"city": "Amsterdam", "state": "Noord-Holland"}
        with patch("linecast.weather.sources._fetch_alerts_meteoalarm",
                   return_value=[{"event": "x"}]) as mock_fn:
            result = fetch_alerts(52.37, 4.89, country_code="NL", lang="en", address=address)
        mock_fn.assert_called_once_with(52.37, 4.89, "netherlands", lang="en", address=address)
        assert result == [{"event": "x"}]

    def test_routes_in_to_sachet(self):
        from linecast.weather.sources import fetch_alerts
        with patch("linecast.weather.sources._fetch_alerts_sachet",
                   return_value=[{"event": "x"}]) as mock_fn:
            result = fetch_alerts(28.61, 77.21, country_code="IN")
        mock_fn.assert_called_once_with(28.61, 77.21, lang="en")
        assert result == [{"event": "x"}]

    def test_routes_nz_to_metservice(self):
        from linecast.weather.sources import fetch_alerts
        with patch("linecast.weather.sources._fetch_alerts_metservice",
                   return_value=[{"event": "x"}]) as mock_fn:
            result = fetch_alerts(-41.29, 174.78, country_code="NZ")
        mock_fn.assert_called_once_with(-41.29, 174.78)
        assert result == [{"event": "x"}]

    def test_routes_newer_meteoalarm_members(self):
        from linecast.weather.sources import fetch_alerts
        for code, slug, lat, lng in (
                ("UA", "ukraine", 50.45, 30.52),
                ("BA", "bosnia-herzegovina", 43.86, 18.41),
                ("MK", "republic-of-north-macedonia", 41.99, 21.43)):
            with patch("linecast.weather.sources._fetch_alerts_meteoalarm",
                       return_value=[{"event": "x"}]) as mock_fn:
                result = fetch_alerts(lat, lng, country_code=code)
            mock_fn.assert_called_once_with(lat, lng, slug, lang="en",
                                            address=None)
            assert result == [{"event": "x"}]

    def test_unknown_country_returns_empty(self):
        from linecast.weather.sources import fetch_alerts
        assert fetch_alerts(0, 0, country_code="XX") == []


# ---------------------------------------------------------------------------
# Helper unit tests
# ---------------------------------------------------------------------------

class TestLocationMatching:
    """Test MeteoAlarm area matching helpers."""

    def test_extract_location_words(self):
        from linecast.weather.sources import _extract_location_words
        address = {"city": "Madrid", "state": "Comunidad de Madrid"}
        words = _extract_location_words(address)
        assert "madrid" in words
        assert "comunidad" not in words  # a tier, and Valencia's too
        assert "de" not in words  # too short

    def test_area_matches_positive(self):
        from linecast.weather.sources import _area_matches
        words = {"madrid", "comunidad"}
        assert _area_matches("Sierra de Madrid", words)

    def test_area_matches_negative(self):
        from linecast.weather.sources import _area_matches
        words = {"madrid", "comunidad"}
        assert not _area_matches("Bizkaia interior", words)

    def test_area_matches_empty(self):
        from linecast.weather.sources import _area_matches
        assert not _area_matches("", {"madrid"})
        assert not _area_matches("Madrid", set())

    def test_meteireann_severity(self):
        from linecast.weather.sources import _meteireann_severity
        assert _meteireann_severity("red") == "Extreme"
        assert _meteireann_severity("orange") == "Severe"
        assert _meteireann_severity("yellow") == "Moderate"
        assert _meteireann_severity("green") == "Minor"

    def test_parse_meteireann_dt(self):
        from linecast.weather.sources import _parse_meteireann_dt
        # Irish local time, with the offset of the day: GMT in winter, IST in summer
        assert _parse_meteireann_dt("00:00 Saturday 07/03/2026") == "2026-03-07T00:00:00+00:00"
        assert _parse_meteireann_dt("14:30 Monday 15/12/2025") == "2025-12-15T14:30:00+00:00"
        assert _parse_meteireann_dt("14:30 Monday 15/06/2026") == "2026-06-15T14:30:00+01:00"
        assert _parse_meteireann_dt("14:30 Monday 31/02/2026") == ""
        assert _parse_meteireann_dt("") == ""
        assert _parse_meteireann_dt(None) == ""

    def test_cma_severity_from_pic(self):
        from linecast.weather.sources import _cma_severity_from_pic
        assert (_cma_severity_from_pic("https://image.nmc.cn/assets/img/alarm/p0005001.png")
                == "Extreme")
        assert (_cma_severity_from_pic("https://image.nmc.cn/assets/img/alarm/p0007002.png")
                == "Severe")
        assert (_cma_severity_from_pic("https://image.nmc.cn/assets/img/alarm/p0007003.png")
                == "Moderate")
        assert (_cma_severity_from_pic("https://image.nmc.cn/assets/img/alarm/p0007004.png")
                == "Minor")
        assert _cma_severity_from_pic("") == "Moderate"

    def test_parse_cma_issuetime(self):
        from linecast.weather.sources import _parse_cma_issuetime
        assert _parse_cma_issuetime("2026/03/07 22:39") == "2026-03-07T22:39:00"
        assert _parse_cma_issuetime("2026/03/07 06:00") == "2026-03-07T06:00:00"
        assert _parse_cma_issuetime("") == ""
        assert _parse_cma_issuetime(None) == ""

    def test_cma_provinces_for_coords(self):
        from linecast.weather.sources import _cma_provinces_for_coords
        # Beijing is unambiguous
        codes = _cma_provinces_for_coords(39.9, 116.4)
        assert codes[0] == "11"
        # Jincheng is a Shanxi border city — "14" must be in the top 3
        codes = _cma_provinces_for_coords(35.5, 112.8)
        assert "14" in codes
        # Shanghai
        codes = _cma_provinces_for_coords(31.2, 121.5)
        assert codes[0] == "31"
        # Xinjiang
        codes = _cma_provinces_for_coords(43.8, 87.6)
        assert codes[0] == "65"


# ---------------------------------------------------------------------------
# CMA alerts parsing
# ---------------------------------------------------------------------------

class TestCMAAlerts:
    """Verify we can parse CMA findAlarm response."""

    def setup_method(self):
        self.data = _load("cma_warnings.json")

    def test_fixture_structure(self):
        assert isinstance(self.data, dict)
        assert "data" in self.data
        page = self.data["data"]["page"]
        assert isinstance(page["list"], list)
        assert len(page["list"]) == 5

    def test_parse_shanxi_en(self):
        """Parse alerts for Shanxi province (14) in English."""
        from linecast.weather.sources import _parse_cma_data
        alerts = _parse_cma_data(self.data, "14", lang="en")
        assert isinstance(alerts, list)
        assert len(alerts) == 2  # Dense Fog + Road Icing (deduped across county/province)
        types = {a["event"] for a in alerts}
        assert "Yellow Dense Fog Warning" in types
        assert "Yellow Road Icing Warning" in types
        for a in alerts:
            assert a["severity"] == "Moderate"
            assert a["effective"]  # non-empty
            assert "nmc.cn" in a["url"]
            for key in ("event", "headline", "description", "severity", "effective", "expires",
                        "url"):
                assert key in a

    def test_parse_shanxi_zh(self):
        """Parse alerts for Shanxi province in Chinese."""
        from linecast.weather.sources import _parse_cma_data
        alerts = _parse_cma_data(self.data, "14", lang="zh")
        assert len(alerts) == 2
        # Events should be in Chinese
        events = " ".join(a["event"] for a in alerts)
        assert "大雾" in events or "道路结冰" in events

    def test_parse_beijing_en(self):
        """Parse alerts for Beijing (11) — red fog warning."""
        from linecast.weather.sources import _parse_cma_data
        alerts = _parse_cma_data(self.data, "11", lang="en")
        assert len(alerts) == 1
        a = alerts[0]
        assert a["event"] == "Red Dense Fog Warning"
        assert a["severity"] == "Extreme"
        assert a["effective"] == "2026-03-07T06:00:00"

    def test_parse_other_province_returns_empty(self):
        """Province with no alerts in fixture returns empty list."""
        from linecast.weather.sources import _parse_cma_data
        alerts = _parse_cma_data(self.data, "65", lang="en")  # Xinjiang
        assert alerts == []

    def test_parse_with_fetch_mock(self):
        """Smoke test: _fetch_alerts_cma parser produces our standard dict."""
        from linecast.weather.sources import _fetch_alerts_cma
        with patch("linecast.weather.sources.fetch_json_cached", return_value=self.data):
            alerts = _fetch_alerts_cma(35.5, 112.8, lang="en")  # Jincheng, Shanxi
        assert isinstance(alerts, list)
        # Jincheng is a Shanxi border city — must find Shanxi alerts via multi-province match
        assert len(alerts) >= 2
        events = {a["event"] for a in alerts}
        assert "Yellow Dense Fog Warning" in events
        for a in alerts:
            for key in ("event", "headline", "description", "severity", "effective", "expires",
                        "url"):
                assert key in a

    def test_routing_cn_to_cma(self):
        """fetch_alerts routes CN to _fetch_alerts_cma."""
        from linecast.weather.sources import fetch_alerts
        with patch("linecast.weather.sources._fetch_alerts_cma",
                   return_value=[{"event": "x"}]) as mock_fn:
            result = fetch_alerts(39.9, 116.4, country_code="CN", lang="zh")
        mock_fn.assert_called_once_with(39.9, 116.4, lang="zh")
        assert result == [{"event": "x"}]


# ---------------------------------------------------------------------------
# HKO warnings (Hong Kong)
# ---------------------------------------------------------------------------

class TestHKOAlerts:
    """The warnsum feed is a dict keyed by warning type."""

    def setup_method(self):
        self.data = _load("hko_warnsum.json")

    def test_parse_orders_by_severity_and_drops_cancelled(self):
        from linecast.weather.sources import _parse_hko_warnsum
        alerts = _parse_hko_warnsum(self.data)
        assert [a["event"] for a in alerts] == [
            "Black Rainstorm Warning Signal",
            "Tropical Cyclone Warning Signal",
            "Thunderstorm Warning",
        ]
        assert [a["severity"] for a in alerts] == ["Severe", "Severe", "Minor"]
        assert alerts[2]["effective"] == "2026-08-25T15:35:00+08:00"
        assert alerts[2]["expires"] == "2026-08-25T20:30:00+08:00"
        for a in alerts:
            for key in ("event", "headline", "description", "severity", "effective",
                        "expires", "url"):
                assert key in a

    def test_parse_empty_feed(self):
        from linecast.weather.sources import _parse_hko_warnsum
        assert _parse_hko_warnsum({}) == []

    def test_routing_hk_to_hko(self):
        from linecast.weather.sources import fetch_alerts
        with patch("linecast.weather.sources._fetch_alerts_hko",
                   return_value=[{"event": "x"}]) as mock_fn:
            result = fetch_alerts(22.3, 114.2, country_code="HK", lang="zh-Hant")
        mock_fn.assert_called_once_with(lang="zh-Hant")
        assert result == [{"event": "x"}]

    def test_the_feed_and_the_links_follow_the_script(self):
        # The Observatory publishes the feed in English and both Chinese
        # scripts; the reader's language picks the one to ask for, and
        # the detail page to link.
        from linecast.weather.sources import HKO_WARNINGS_URL, _HKO_LANG, _parse_hko_warnsum
        assert _HKO_LANG == {"zh": "sc", "zh-Hant": "tc"}
        assert HKO_WARNINGS_URL.format(lang="tc").endswith("lang=tc")
        assert _parse_hko_warnsum(self.data, "zh-Hant")[0]["url"] == "https://www.hko.gov.hk/tc/detail.htm"
        assert _parse_hko_warnsum(self.data, "zh")[0]["url"] == "https://www.hko.gov.hk/sc/detail.htm"
        assert _parse_hko_warnsum(self.data)[0]["url"] == "https://www.hko.gov.hk/en/detail.htm"


class TestReverseGeocodeCountry:
    """Nominatim files Hong Kong and Macau under China."""

    def test_hong_kong_and_macau_get_their_own_codes(self):
        from linecast.weather.sources import _country_code
        assert _country_code({"country_code": "cn", "ISO3166-2-lvl3": "CN-HK"}) == "HK"
        assert _country_code({"country_code": "cn", "ISO3166-2-lvl3": "CN-MO"}) == "MO"
        assert _country_code({"country_code": "cn", "ISO3166-2-lvl3": "CN-GD"}) == "CN"
        assert _country_code({"country_code": "us"}) == "US"
        assert _country_code({}) == ""


class TestReverseGeocodeName:
    """Nominatim names small places under keys down to hamlet (issue #50)."""

    def _name(self, address):
        from linecast.weather import sources as ws
        with patch.object(ws, "read_cache", return_value=None), \
                patch.object(ws, "write_cache", lambda *a, **k: None), \
                patch("linecast.maps.search._throttle", lambda: None), \
                patch.object(ws, "fetch_json", return_value={"address": address}):
            name, _cc, _addr = ws._reverse_geocode(44.4, -70.0)
        return name

    def test_hamlet_names_the_place(self):
        assert self._name({"hamlet": "Fayette", "county": "Kennebec County",
                           "state": "Maine", "country_code": "us"}) == "Fayette, Maine"

    def test_city_outranks_smaller_keys(self):
        assert self._name({"city": "Portland", "hamlet": "Stroudwater",
                           "state": "Maine", "country_code": "us"}) == "Portland, Maine"

    def test_no_name_stays_empty(self):
        assert self._name({"county": "Kennebec County", "state": "Maine",
                           "country_code": "us"}) == ""


class TestResultLabel:
    """A region named for its city is not repeated."""

    def test_name_admin1_country(self):
        from linecast.weather.sources import result_label
        assert result_label({"name": "Osaka", "admin1": "Osaka Prefecture",
                             "country": "Japan"}) == "Osaka, Osaka Prefecture, Japan"

    def test_a_region_named_for_its_city_is_left_out(self):
        from linecast.weather.sources import result_label
        assert result_label({"name": "Busan", "admin1": "Busan",
                             "country": "South Korea"}) == "Busan, South Korea"

    def test_missing_parts(self):
        from linecast.weather.sources import result_label
        assert result_label({"name": "Nuuk", "admin1": "Sermersooq"}) == "Nuuk, Sermersooq"


class TestReverseGeocodeLanguage:
    """Asked without a language, Nominatim answers in the country's own,
    which the alert feeds are matched against; asked with one, in the
    user's. A command may want both, so neither evicts the other."""

    def _ask(self, lang):
        from linecast.weather import sources as ws
        seen = {}

        def fetch(url, **_kw):
            seen["url"] = url
            return {"address": {"city": "Osaka", "country_code": "jp"}}

        with patch.object(ws, "read_cache", return_value=None) as read, \
                patch.object(ws, "write_cache", lambda *a, **k: None), \
                patch("linecast.maps.search._throttle", lambda: None), \
                patch.object(ws, "fetch_json", fetch):
            ws._reverse_geocode(34.69, 135.50, lang=lang)
        return seen["url"], read.call_args[0][0].name

    def test_no_language_asks_for_the_local_names(self):
        url, cache_name = self._ask(None)
        assert "accept-language" not in url
        assert cache_name == "location.json"

    def test_a_language_is_passed_on_and_cached_apart(self):
        url, cache_name = self._ask("fr")
        assert url.endswith("&accept-language=fr")
        assert cache_name == "location_fr.json"


# ---------------------------------------------------------------------------
# MeteoAlarm area filtering: a country-wide feed narrowed to one user
# ---------------------------------------------------------------------------

def _box(south, north, west, east):
    """A CAP polygon ring around a lat/lng box, closed."""
    corners = [(south, west), (south, east), (north, east), (north, west),
               (south, west)]
    return [" ".join(f"{lat},{lng}" for lat, lng in corners)]


def _feed(*warnings):
    return {"warnings": [{"alert": {"info": [info]}} for info in warnings]}


def _warning(event, severity, area_desc, polygon=None, description=None):
    area = {"areaDesc": area_desc}
    if polygon is not None:
        area["polygon"] = polygon
    info = {"language": "en-GB", "severity": severity, "event": event,
            "headline": f"{event} for {area_desc}", "area": [area]}
    if description is not None:
        info["description"] = description
    return info


def _alerts(data, lat, lng, address):
    from linecast.weather import sources as ws
    with patch.object(ws, "fetch_json_cached", return_value=data), \
            patch.object(ws, "write_cache", lambda *a, **k: None):
        return ws._fetch_alerts_meteoalarm(lat, lng, "united-kingdom",
                                           address=address)


EDINBURGH = (55.95, -3.19, {"city": "City of Edinburgh",
                            "state": "Alba / Scotland"})


class TestMeteoAlarmGeometry:
    """A CAP polygon says where a warning applies, so it settles the matter."""

    def test_a_gauge_in_another_city_does_not_reach_edinburgh(self):
        # The bug this fixes: the Environment Agency posts per-gauge flood
        # warnings as Severe, and every one of them reached every user in
        # the country.
        lat, lng, address = EDINBURGH
        data = _feed(_warning("Flood Warning: Perry Brook at Perry Barr",
                              "Severe", "Perry Brook at Perry Barr",
                              _box(52.533, 52.548, -1.919, -1.902)))
        assert _alerts(data, lat, lng, address) == []

    def test_the_same_warning_reaches_the_brook(self):
        data = _feed(_warning("Flood Warning: Perry Brook at Perry Barr",
                              "Severe", "Perry Brook at Perry Barr",
                              _box(52.533, 52.548, -1.919, -1.902)))
        got = _alerts(data, 52.54, -1.91, {"city": "Birmingham"})
        assert [a["event"] for a in got] == [
            "Flood Warning: Perry Brook at Perry Barr"]

    def test_a_national_warning_still_lands(self):
        lat, lng, address = EDINBURGH
        data = _feed(_warning("Red wind warning", "Severe",
                              "United Kingdom", _box(49, 61, -9, 2)))
        # the colour prefix is stripped: the pill already carries severity
        assert [a["event"] for a in _alerts(data, lat, lng, address)] == [
            "wind warning"]

    def test_geometry_outranks_a_matching_areadesc(self):
        # "Scotland" is one of Edinburgh's words, but the polygon is over
        # Shetland; the polygon is the warning's own account of itself.
        lat, lng, address = EDINBURGH
        data = _feed(_warning("Yellow wind warning", "Moderate",
                              "Scotland", _box(60.0, 60.9, -1.6, -0.7)))
        assert _alerts(data, lat, lng, address) == []

    def test_geometry_outranks_severity(self):
        # Being outside an Extreme warning's polygon means being outside it.
        lat, lng, address = EDINBURGH
        data = _feed(_warning("Red rain warning", "Extreme", "Cornwall",
                              _box(50.0, 50.9, -5.7, -4.2)))
        assert _alerts(data, lat, lng, address) == []

    def test_an_unparseable_polygon_falls_back_to_the_areadesc(self):
        lat, lng, address = EDINBURGH
        data = _feed(_warning("Yellow wind warning", "Moderate",
                              "Alba / Scotland", ["nonsense"]))
        assert [a["event"] for a in _alerts(data, lat, lng, address)] == [
            "wind warning"]


class TestMeteoAlarmWithoutGeometry:
    """Feeds carrying no polygon fall back to reading the areaDesc."""

    def test_a_matching_areadesc_is_kept(self):
        lat, lng, address = EDINBURGH
        data = _feed(_warning("Yellow wind warning", "Moderate",
                              "Alba / Scotland"))
        assert [a["event"] for a in _alerts(data, lat, lng, address)] == [
            "wind warning"]

    def test_an_unmatched_severe_lands_only_on_an_empty_board(self):
        lat, lng, address = EDINBURGH
        data = _feed(_warning("Flood Warning", "Severe", "Perry Brook"))
        assert [a["event"] for a in _alerts(data, lat, lng, address)] == [
            "Flood Warning"]

    def test_a_local_alert_outranks_an_unmatched_severe(self):
        lat, lng, address = EDINBURGH
        data = _feed(_warning("Flood Warning", "Severe", "Perry Brook"),
                     _warning("Yellow wind warning", "Moderate",
                              "Alba / Scotland"))
        assert [a["event"] for a in _alerts(data, lat, lng, address)] == [
            "wind warning"]

    def test_an_unmatched_moderate_is_dropped_outright(self):
        lat, lng, address = EDINBURGH
        data = _feed(_warning("Yellow thunderstorm warning", "Moderate",
                              "East Midlands | London & South East England"))
        assert _alerts(data, lat, lng, address) == []

    def test_everything_lands_when_the_address_is_unknown(self):
        data = _feed(_warning("Yellow wind warning", "Moderate", "Wales"))
        assert len(_alerts(data, 55.95, -3.19, None)) == 1


class TestMeteoAlarmLocationWords:
    """Words that name a tier rather than a place match far too much."""

    def test_administrative_words_are_dropped(self):
        from linecast.weather.sources import _extract_location_words
        words = _extract_location_words({"city": "City of Edinburgh",
                                         "state": "Alba / Scotland"})
        assert "city" not in words
        assert {"edinburgh", "scotland"} <= words

    def test_a_place_survives_its_tier_word(self):
        from linecast.weather.sources import _extract_location_words
        words = _extract_location_words({"state": "Auvergne-Rhône-Alpes Region"})
        assert words == {"auvergne-rhône-alpes"}

    def test_tier_words_are_dropped_in_the_countrys_own_language(self):
        # Issue #57: Nominatim names Warsaw in Polish, and "województwo"
        # begins every Polish areaDesc in the country.
        from linecast.weather.sources import _extract_location_words
        words = _extract_location_words({"city": "Warszawa",
                                         "state": "województwo mazowieckie"})
        assert words == {"warszawa", "mazowieckie"}
        words = _extract_location_words({"city": "Brno",
                                         "state": "Jihomoravský kraj",
                                         "county": "okres Brno-město"})
        assert words == {"brno", "jihomoravský", "brno-město"}


class TestMeteoAlarmFeedWideWords:
    """A word found across most of the feed names no single place."""

    def _descs(self, n, word):
        return [[f"{word} district {i}"] for i in range(n)]

    def test_a_word_across_the_whole_feed_is_dropped(self):
        from linecast.weather.sources import _drop_feed_wide_words
        descs = self._descs(30, "zork")
        assert _drop_feed_wide_words({"zork", "york"}, descs) == {"york"}

    def test_a_word_in_a_few_warnings_is_kept(self):
        from linecast.weather.sources import _drop_feed_wide_words
        descs = self._descs(30, "zork") + [["york"]] * 3
        assert "york" in _drop_feed_wide_words({"york"}, descs)

    def test_a_small_feed_is_not_judged(self):
        # Three warnings, all in one province: the province is not generic.
        from linecast.weather.sources import _drop_feed_wide_words
        descs = self._descs(3, "masovia")
        assert _drop_feed_wide_words({"masovia"}, descs) == {"masovia"}

    def test_an_unlisted_tier_word_is_learned_from_the_feed(self):
        # The tier-word list cannot know every language; the feed can.
        data = _feed(*[_warning("Wind warning", "Moderate",
                                f"zorkland zone {i}", description="Gusts.")
                       for i in range(25)])
        got = _alerts(data, 54.0, -1.1, {"city": "York", "state": "Zorkland"})
        assert got == []


class TestMeteoAlarmPerCountyFeeds:
    """Poland files one warning per county; a province's worth read as one."""

    def _poland(self):
        storm = "Thunderstorms with hail."
        masovia = [_warning("Thunderstorm warning", "Moderate",
                            f"województwo mazowieckie powiat {name}",
                            description=storm)
                   for name in ("ciechanowski", "płocki", "Warszawa",
                                "wołomiński", "żyrardowski")]
        elsewhere = [_warning("Thunderstorm warning", "Moderate",
                              f"województwo wielkopolskie powiat {i}",
                              description=storm)
                     for i in range(20)]
        return _feed(*masovia, *elsewhere)

    WARSAW = {"city": "Warszawa", "state": "województwo mazowieckie"}

    def test_a_province_word_does_not_match_the_country(self):
        got = _alerts(self._poland(), 52.23, 21.01, self.WARSAW)
        assert len(got) == 1

    def test_the_copy_kept_names_the_users_own_county(self):
        got = _alerts(self._poland(), 52.23, 21.01, self.WARSAW)
        assert "Warszawa" in got[0]["headline"]

    def test_warnings_that_read_differently_stay_apart(self):
        data = _feed(_warning("Rain warning", "Moderate",
                              "województwo mazowieckie powiat płocki",
                              description="30 to 40 mm."),
                     _warning("Rain warning", "Moderate",
                              "województwo mazowieckie powiat Warszawa",
                              description="50 to 70 mm."))
        got = _alerts(data, 52.23, 21.01, self.WARSAW)
        assert len(got) == 2


def _coded(event, severity, area_desc, codes, description=None,
           value_name="EMMA_ID"):
    """A warning naming its ground by geocode: EMMA_ID for most feeds."""
    info = _warning(event, severity, area_desc, description=description)
    info["area"][0]["geocode"] = [{"valueName": value_name, "value": c} for c in codes]
    return info


def _ring(lat0, lat1, lng0, lng1):
    return [(lat0, lng0), (lat0, lng1), (lat1, lng1), (lat1, lng0)]


FAKE_REGIONS = [
    ("XX001", (50.0, 51.0, 10.0, 11.0), [(_ring(50.0, 51.0, 10.0, 11.0), [])]),
    ("XX002", (52.0, 53.0, 10.0, 11.0), [(_ring(52.0, 53.0, 10.0, 11.0), [])]),
    # a province holding XX001, with a hole where a lake is
    ("XX100", (49.0, 53.5, 9.0, 12.0),
     [(_ring(49.0, 53.5, 9.0, 12.0), [_ring(49.2, 49.4, 9.2, 9.4)])]),
    # a NUTS3 code spelled like XX002, over XX001's ground, not XX002's
    ("NUTS3/XX002", (50.0, 51.0, 10.0, 11.0), [(_ring(50.0, 51.0, 10.0, 11.0), [])]),
    # two Czech-style ORPs, one on XX001's ground
    ("CISORP/0001", (50.0, 51.0, 10.0, 11.0), [(_ring(50.0, 51.0, 10.0, 11.0), [])]),
    ("CISORP/0002", (50.0, 51.0, 11.0, 12.0), [(_ring(50.0, 51.0, 11.0, 12.0), [])]),
]


class TestMeteoAlarmRegions:
    """An EMMA_ID names ground; the baked geometry says whose."""

    def setup_method(self):
        from linecast import _meteoalarm_regions as mr
        self._saved = (mr._REGIONS, mr._CODES)
        mr._REGIONS, mr._CODES = FAKE_REGIONS, None

    def teardown_method(self):
        from linecast import _meteoalarm_regions as mr
        mr._REGIONS, mr._CODES = self._saved

    def test_a_point_is_in_its_region_and_the_province_around_it(self):
        from linecast._meteoalarm_regions import regions_at
        assert regions_at(50.5, 10.5) == {"XX001", "XX100", "NUTS3/XX002", "CISORP/0001"}

    def test_a_hole_is_outside(self):
        from linecast._meteoalarm_regions import regions_at
        assert regions_at(49.3, 9.3) == set()

    def test_a_warning_for_the_users_county_reaches_them(self):
        data = _feed(_coded("Storm", "Moderate", "somewhere", ["XX001"]))
        assert len(_alerts(data, 50.5, 10.5, {"city": "Elsewhere"})) == 1

    def test_a_warning_for_the_next_county_does_not(self):
        # Even a Severe one, and even though the areaDesc names the
        # user's city: the code says where it applies.
        data = _feed(_coded("Storm", "Severe", "Elsewhere", ["XX002"]))
        assert _alerts(data, 50.5, 10.5, {"city": "Elsewhere"}) == []

    def test_a_warning_for_the_province_reaches_everyone_in_it(self):
        data = _feed(_coded("Heat", "Moderate", "the province", ["XX100"]))
        assert len(_alerts(data, 50.5, 10.5, {"city": "Nowhere"})) == 1

    def test_a_code_the_data_lacks_falls_back_to_the_area_name(self):
        data = _feed(_coded("Storm", "Moderate", "Elsewhere", ["ZZ999"]),
                     _coded("Storm", "Moderate", "Otherplace", ["ZZ998"]))
        got = _alerts(data, 50.5, 10.5, {"city": "Elsewhere"})
        assert [a["headline"] for a in got] == ["Storm for Elsewhere"]

    def test_a_point_no_region_covers_falls_back_to_the_area_name(self):
        data = _feed(_coded("Storm", "Moderate", "Elsewhere", ["XX001"]))
        got = _alerts(data, 60.0, 30.0, {"city": "Elsewhere"})
        assert len(got) == 1

    def test_a_code_is_looked_up_under_its_type(self):
        # France's NUTS3 codes share their form with EMMA_IDs for other
        # ground: XX002 the EMMA_ID is the next county over, XX002 the
        # NUTS3 code is here. Each warning lands where its own type says.
        here = (50.5, 10.5)
        nuts = _feed(_coded("Storm", "Moderate", "Elsewhere", ["XX002"],
                            value_name="NUTS3"))
        assert len(_alerts(nuts, *here, {"city": "Nowhere"})) == 1
        emma = _feed(_coded("Storm", "Moderate", "Elsewhere", ["XX002"]))
        assert _alerts(emma, *here, {"city": "Nowhere"}) == []

    def test_a_typed_code_the_data_lacks_falls_back_to_the_area_name(self):
        # XX001 is known as an EMMA_ID, not as a NUTS3 code.
        data = _feed(_coded("Storm", "Moderate", "Elsewhere", ["XX001"],
                            value_name="NUTS3"))
        got = _alerts(data, 52.5, 10.5, {"city": "Elsewhere"})
        assert len(got) == 1  # matched on the areaDesc, not excluded by XX001

    def test_a_czech_warning_lands_in_one_of_its_orps(self):
        # ČHMÚ files one area for several ORPs, a CISORP per ORP, and
        # beside each an EMMA_ID the data lacks. The CISORPs place it.
        info = _warning("Storm", "Moderate", "Some kraj (Here, There)")
        info["area"][0]["geocode"] = [
            {"valueName": "CISORP", "value": "0001"},
            {"valueName": "EMMA_ID", "value": "CZ00001"},
            {"valueName": "CISORP", "value": "0002"},
            {"valueName": "EMMA_ID", "value": "CZ00002"},
        ]
        assert len(_alerts(_feed(info), 50.5, 10.5, {"city": "Nowhere"})) == 1
        assert _alerts(_feed(info), 52.5, 10.5, {"city": "Nowhere"}) == []

    def test_keys_are_spelled_by_type(self):
        from linecast._meteoalarm_regions import key_for
        assert key_for("EMMA_ID", "PL3001") == "PL3001"
        assert key_for("NUTS3", "FR101") == "NUTS3/FR101"
        assert key_for("NUTS2", "HU10") == "NUTS2/HU10"
        assert key_for("CISORP", "2101") == "CISORP/2101"


class TestMeteoAlarmRegionsData:
    """The shipped file answers for real places."""

    def setup_method(self):
        from linecast import _meteoalarm_regions as mr
        mr._REGIONS, mr._CODES = None, None

    def test_warsaw_is_in_one_polish_county(self):
        from linecast._meteoalarm_regions import regions_at
        assert regions_at(52.23, 21.01) == {"PL1465"}

    def test_issue_57s_county_is_where_the_feed_says(self):
        from linecast._meteoalarm_regions import regions_at, known
        assert known("PL3001")
        assert "PL3001" in regions_at(52.995, 16.92)  # Chodzież
        assert "PL3001" not in regions_at(52.23, 21.01)

    def test_a_district_sits_inside_its_state(self):
        from linecast._meteoalarm_regions import regions_at
        assert regions_at(48.209, 16.372) == {"AT901"}  # Vienna, its own district

    def test_the_atlantic_is_nowhere(self):
        from linecast._meteoalarm_regions import regions_at
        assert regions_at(43.66, -70.26) == set()

    # The NUTS-coded feeds (issue #59): each capital in its own region,
    # under the type its country files.

    def test_paris_is_in_its_departement_by_either_spelling(self):
        # FR101 is Paris both as an EMMA_ID and as a NUTS3 code; the two
        # are separate entries, and only the NUTS3 one answers for NUTS3.
        from linecast._meteoalarm_regions import regions_at
        got = regions_at(48.8566, 2.3522)
        assert "FR101" in got
        assert {k for k in got if k.startswith("NUTS")} == {"NUTS3/FR101"}

    def test_cayenne_is_in_overseas_france(self):
        from linecast._meteoalarm_regions import regions_at
        assert "NUTS3/FRA30" in regions_at(4.9224, -52.3135)

    def test_budapest_is_in_central_hungary_as_2013_spelled_it(self):
        from linecast._meteoalarm_regions import regions_at
        got = regions_at(47.4979, 19.0402)
        assert {k for k in got if k.startswith("NUTS")} == {"NUTS2/HU10"}

    def test_sofia_is_in_its_oblast(self):
        from linecast._meteoalarm_regions import regions_at
        got = regions_at(42.6977, 23.3219)
        assert {k for k in got if k.startswith("NUTS")} == {"NUTS3/BG411"}

    def test_bucharest_is_in_its_judet(self):
        from linecast._meteoalarm_regions import regions_at
        got = regions_at(44.4268, 26.1025)
        assert {k for k in got if k.startswith("NUTS")} == {"NUTS3/RO321"}

    def test_antwerp_is_in_its_province(self):
        from linecast._meteoalarm_regions import regions_at
        got = regions_at(51.2194, 4.4025)
        assert {k for k in got if k.startswith("NUTS")} == {"NUTS2/BE21"}

    def test_skopje_answers_under_the_label_its_feed_uses(self):
        # North Macedonia files its EMMA_IDs typed NUTS3.
        from linecast._meteoalarm_regions import regions_at
        assert regions_at(41.9973, 21.4280) == {"MK008", "NUTS3/MK008"}

    def test_split_is_in_its_county_beside_its_region(self):
        # Croatia files a county warning under an EMMA_ID no geocodes
        # edition carries, with the 2013 NUTS3 code beside it (#127).
        from linecast._meteoalarm_regions import regions_at
        assert regions_at(43.508, 16.44) == {"HR008", "NUTS3/HR035"}

    def test_prague_is_its_own_orp_by_both_spellings(self):
        # The statistical office codes Prague 1000; the feed files 1100.
        from linecast._meteoalarm_regions import regions_at
        got = regions_at(50.0755, 14.4378)
        assert {k for k in got if k.startswith("CISORP")} == {"CISORP/1000", "CISORP/1100"}
        assert "CZ01100" in got  # and the EMMA_ID the feed files beside it

    def test_brno_is_in_its_orp_and_not_the_next(self):
        from linecast._meteoalarm_regions import regions_at, known
        assert "CISORP/6203" in regions_at(49.1951, 16.6068)
        assert known("CISORP/6217")  # Tišnov, one ORP over
        assert "CISORP/6217" not in regions_at(49.1951, 16.6068)


class TestAlertCap:
    """However many a feed sends, the board shows the gravest few."""

    def test_the_gravest_come_first_and_the_rest_are_cut(self):
        from linecast.weather.sources import _trim_alerts, MAX_ALERTS
        alerts = ([{"event": f"m{i}", "severity": "Moderate"} for i in range(6)]
                  + [{"event": "x", "severity": "Extreme"}]
                  + [{"event": f"s{i}", "severity": "Severe"} for i in range(6)])
        got = _trim_alerts(alerts)
        assert len(got) == MAX_ALERTS
        assert got[0]["event"] == "x"
        assert [a["severity"] for a in got[1:7]] == ["Severe"] * 6
        assert got[7]["event"] == "m0"

    def test_the_cap_applies_to_every_provider(self):
        from linecast.weather import sources as ws
        many = [{"event": f"a{i}", "severity": "Moderate"} for i in range(40)]
        with patch.object(ws, "_fetch_alerts_nws", return_value=many):
            got = ws.fetch_alerts(43.6, -70.3, "US")
        assert len(got) == ws.MAX_ALERTS


class TestMeteoAlarmDedup:
    """Two warnings of one kind stay distinguishable by the ground they cover."""

    def test_distinct_areas_are_kept_apart(self):
        data = _feed(_warning("Flood Warning", "Severe", "River Ouse",
                              _box(53.9, 54.1, -1.2, -1.0)),
                     _warning("Flood Warning", "Severe", "River Foss",
                              _box(53.9, 54.1, -1.2, -1.0)))
        got = _alerts(data, 54.0, -1.1, {"city": "York"})
        assert len(got) == 2

    def test_a_repeated_warning_is_collapsed(self):
        data = _feed(_warning("Flood Warning", "Severe", "River Ouse",
                              _box(53.9, 54.1, -1.2, -1.0)),
                     _warning("Flood Warning", "Severe", "River Ouse",
                              _box(53.9, 54.1, -1.2, -1.0)))
        got = _alerts(data, 54.0, -1.1, {"city": "York"})
        assert len(got) == 1


class TestCapPolygons:
    """Parsing and point-in-ring, the pieces the filtering rests on."""

    def test_parses_a_closed_ring(self):
        from linecast.weather.sources import _cap_polygons
        rings = _cap_polygons({"polygon": _box(0, 1, 0, 1)})
        assert len(rings) == 1
        assert rings[0][0] == (0.0, 0.0)

    def test_a_bare_string_is_accepted(self):
        from linecast.weather.sources import _cap_polygons
        assert len(_cap_polygons({"polygon": _box(0, 1, 0, 1)[0]})) == 1

    def test_no_polygon_is_no_rings(self):
        from linecast.weather.sources import _cap_polygons
        assert _cap_polygons({"areaDesc": "somewhere"}) == []

    def test_a_ring_too_short_to_enclose_anything_is_skipped(self):
        from linecast.weather.sources import _cap_polygons
        assert _cap_polygons({"polygon": ["1,1 2,2"]}) == []

    def test_inside_and_outside(self):
        from linecast.weather.sources import _cap_polygons, _point_in_ring
        ring = _cap_polygons({"polygon": _box(50, 52, -2, 0)})[0]
        assert _point_in_ring(51, -1, ring)
        assert not _point_in_ring(55, -1, ring)
        assert not _point_in_ring(51, 3, ring)

    def test_a_concave_ring_excludes_its_notch(self):
        # A C-shape: the middle of the opening is outside, though it sits
        # within the bounding box.
        from linecast.weather.sources import _point_in_ring
        ring = [(0, 0), (0, 3), (1, 3), (1, 1), (2, 1), (2, 3), (3, 3),
                (3, 0), (0, 0)]
        assert _point_in_ring(1.5, 0.5, ring)
        assert not _point_in_ring(1.5, 2.0, ring)


# ---------------------------------------------------------------------------
# SACHET alerts (India)
# ---------------------------------------------------------------------------

def _sachet_cap_from_fixtures(cache_file, max_age, url, **kwargs):
    """Serve the CAP fixtures the way fetch_bytes_cached would."""
    for identifier in ("2026081001", "2026081002"):
        if identifier in url:
            return (FIXTURES / f"sachet_cap_{identifier}.xml").read_bytes()
    return None


class TestSachetAlerts:
    """Parse a SACHET feed snapshot with its CAP files."""

    def setup_method(self):
        self.feed = _load("sachet_alerts.json")

    def _alerts(self, lat, lng, lang="en"):
        from linecast.weather.sources import _fetch_alerts_sachet
        with patch("linecast.weather.sources.fetch_json_cached",
                   return_value=self.feed), \
             patch("linecast._http.fetch_bytes_cached",
                   side_effect=_sachet_cap_from_fixtures):
            return _fetch_alerts_sachet(lat, lng, lang=lang)

    def test_feed_entry_shape(self):
        for entry in self.feed:
            assert "identifier" in entry
            assert "centroid" in entry
            assert "area_covered" in entry
            assert "severity_color" in entry

    def test_delhi_gets_nearby_and_statewide_alerts(self):
        alerts = self._alerts(28.61, 77.21)
        events = [a["event"] for a in alerts]
        # Two nowcasts over Delhi, plus the state-wide rain warning whose
        # disc covers the city from 120km out; Assam's flood is not here.
        assert "Thunderstorm with Lightning" in events
        assert "Lightning" in events
        assert "Very Heavy Rain" in events
        assert len(alerts) == 3

    def test_most_severe_first(self):
        alerts = self._alerts(28.61, 77.21)
        assert alerts[0]["severity"] == "Extreme"
        severities = [a["severity"] for a in alerts]
        assert severities == sorted(
            severities, key=("Extreme", "Severe", "Moderate", "Minor").index)

    def test_regional_language_alert_shown_in_english(self):
        alerts = self._alerts(28.61, 77.21)
        lightning = next(a for a in alerts if a["event"] == "Lightning")
        assert lightning["headline"].startswith("There is a possibility of lightning")

    def test_user_language_block_preferred_when_present(self):
        alerts = self._alerts(28.61, 77.21, lang="hi")
        lightning = next(a for a in alerts if a["event"] == "Lightning")
        assert "बिजली" in lightning["headline"]

    def test_cap_severity_beats_feed_color(self):
        # The feed says orange (Severe) and the CAP file agrees; the
        # yellow one's CAP file says Moderate.
        alerts = self._alerts(28.61, 77.21)
        thunder = next(a for a in alerts
                       if a["event"] == "Thunderstorm with Lightning")
        assert thunder["severity"] == "Severe"

    def test_alert_without_cap_file_falls_back_to_feed(self):
        alerts = self._alerts(27.49, 94.91)  # Dibrugarh, Assam
        assert len(alerts) == 1
        flood = alerts[0]
        assert flood["event"] == "Flood"
        assert flood["severity"] == "Moderate"  # yellow
        assert flood["headline"].startswith("River Brahmaputra")
        assert flood["effective"] == "2035-01-01T09:00:00+05:30"

    def test_expired_alert_dropped(self):
        alerts = self._alerts(28.61, 77.21)
        assert all(a["event"] != "Dust Storm" for a in alerts)

    def test_far_away_user_gets_nothing(self):
        assert self._alerts(8.5, 76.9) == []  # Thiruvananthapuram

    def test_normalized_fields_present(self):
        for alert in self._alerts(28.61, 77.21):
            for key in ("event", "headline", "description", "effective",
                        "expires", "severity", "url"):
                assert key in alert

    def test_unusable_feed_is_no_alerts(self):
        from linecast.weather.sources import _fetch_alerts_sachet
        with patch("linecast.weather.sources.fetch_json_cached",
                   return_value=None):
            assert _fetch_alerts_sachet(28.61, 77.21) == []

    def test_feed_datetime_parsing(self):
        from linecast.weather.sources import _sachet_datetime
        assert (_sachet_datetime("Sun Aug 30 21:00:00 IST 2026")
                == "2026-08-30T21:00:00+05:30")
        assert _sachet_datetime("nonsense") == ""
        assert _sachet_datetime(None) == ""

    def test_cap_language_codes_normalize_to_iso(self):
        # SACHET's own coinages ("OD" for Odia, "TL" for Telugu) beside
        # the upcased ISO codes it uses for most languages.
        from linecast.weather.sources import _sachet_cap_lang
        assert _sachet_cap_lang("en-IN") == "en"
        assert _sachet_cap_lang("HI") == "hi"
        assert _sachet_cap_lang("MR") == "mr"
        assert _sachet_cap_lang("OD") == "or"
        assert _sachet_cap_lang("TL") == "te"


# ---------------------------------------------------------------------------
# CPCB National AQI (India)
# ---------------------------------------------------------------------------

def _india_aqi_response(current_time="2026-01-02T05:00", **series):
    """A minimal Open-Meteo air quality response for india_aqi."""
    times = ([f"2026-01-01T{h:02d}:00" for h in range(24)]
             + [f"2026-01-02T{h:02d}:00" for h in range(24)])
    hourly = {"time": times}
    defaults = {
        "pm2_5": 60.0, "pm10": 100.0, "nitrogen_dioxide": 40.0,
        "sulphur_dioxide": 40.0, "ozone": 50.0, "carbon_monoxide": 1000.0,
    }
    defaults.update(series)
    for key, value in defaults.items():
        hourly[key] = [value] * len(times) if not isinstance(value, list) else value
    return {"current": {"time": current_time, "us_aqi": 150}, "hourly": hourly}


def _feature(lng, lat, **props):
    return {"geometry": {"type": "Point", "coordinates": [lng, lat]}, "properties": props}


class TestCanadaAqhi:
    """Health Canada's index: the formula, the AQHI-Plus override, the
    published rounding, the words, and the choice among the feeds."""

    def test_formula_and_rounding(self):
        from linecast.weather.sources import aqhi_published, canada_aqhi
        assert canada_aqhi(0, 0, 0) == 0
        assert aqhi_published(canada_aqhi(0, 0, 0)) == 1
        # 20 ppb NO2, 30 ppb O3, 10 µg/m³ PM2.5: 3.72 on the scale
        assert round(canada_aqhi(20, 30, 10), 2) == 3.72
        assert aqhi_published(3.72) == 4
        assert aqhi_published(3.49) == 3 and aqhi_published(3.5) == 4
        assert aqhi_published(12.3) == 12

    def test_computed_from_three_hour_means_in_ppb(self):
        from linecast.weather.sources import canada_aqhi_computed
        # 40 µg/m³ NO2 is 21.3 ppb, 50 µg/m³ O3 is 25.5 ppb: with 5 µg/m³
        # of PM2.5 the index is 3.36, published 3.
        assert canada_aqhi_computed(_india_aqi_response(pm2_5=5.0)) == 3
        # The mean is over the last three hours only: the current hour
        # is index 29 of the fixture's two days.
        series = [5.0] * 27 + [40.0, 40.0, 40.0] + [5.0] * 18
        assert canada_aqhi_computed(_india_aqi_response(pm2_5=series)) == 5

    def test_aqhi_plus_takes_the_hour_s_pm25_over_ten_when_greater(self):
        from linecast.weather.sources import canada_aqhi_computed
        # Two clean hours then a smoke plume: the three-hour mean gives
        # 5, the hour's 85 µg/m³ over ten rounded up gives 9.
        series = [5.0] * 29 + [85.0] + [5.0] * 18
        assert canada_aqhi_computed(_india_aqi_response(pm2_5=series)) == 9
        # A plume of 101 is 11: printed "10+".
        series = [5.0] * 29 + [101.0] + [5.0] * 18
        assert canada_aqhi_computed(_india_aqi_response(pm2_5=series)) == 11

    def test_no_index_without_the_pollutants_for_the_hour(self):
        from linecast.weather.sources import canada_aqhi_computed
        assert canada_aqhi_computed(None) is None
        assert canada_aqhi_computed({"current": {"time": "2026-01-02T05:00"}}) is None
        assert canada_aqhi_computed(_india_aqi_response(current_time="2027-01-01T00:00")) is None
        series = [5.0] * 29 + [None] + [5.0] * 18
        assert canada_aqhi_computed(_india_aqi_response(pm2_5=series)) is None

    def test_words_and_printing(self):
        from linecast.weather.sources import aqhi_category, fmt_aqhi
        assert [aqhi_category(v) for v in (1, 3, 4, 6, 7, 10, 11)] == [
            "Low risk", "Low risk", "Moderate risk", "Moderate risk",
            "High risk", "High risk", "Very high risk"]
        assert aqhi_category(4, "fr") == "Risque modéré"
        assert aqhi_category(4, "fr-CA") == "Risque modéré"
        assert aqhi_category(11, "fr") == "Risque très élevé"
        assert aqhi_category(4, "de") == "Moderate risk"
        assert fmt_aqhi(4) == "4" and fmt_aqhi(10) == "10" and fmt_aqhi(11) == "10+"

    NOW = datetime(2026, 9, 20, 18, 30, tzinfo=timezone.utc)

    def test_the_nearest_community_s_fresh_observation_wins(self):
        from linecast.weather.sources import pick_aqhi
        far = _feature(-79.38, 43.65, aqhi_type="AQHI-Observation", aqhi=6.4,
                       location_name_en="Toronto", observation_datetime="2026-09-20T18:00:00Z")
        near = _feature(-79.87, 43.26, aqhi_type="AQHI-Observation", aqhi=2.6,
                        location_name_en="Hamilton", observation_datetime="2026-09-20T18:00:00Z")
        report = pick_aqhi([far, near], [], 43.30, -79.80, self.NOW)
        assert report == {"aqhi": 3, "place": "Hamilton", "kind": "observed",
                          "time": "2026-09-20T18:00:00+00:00"}

    def test_a_stale_or_distant_observation_is_passed_over(self):
        from linecast.weather.sources import pick_aqhi
        stale = _feature(-79.87, 43.26, aqhi_type="AQHI-Observation", aqhi=9.0,
                         location_name_en="Hamilton", observation_datetime="2026-09-20T15:00:00Z")
        fresh = _feature(-79.38, 43.65, aqhi_type="AQHI-Observation", aqhi=2.0,
                         location_name_en="Toronto", observation_datetime="2026-09-20T18:00:00Z")
        assert pick_aqhi([stale, fresh], [], 43.30, -79.80, self.NOW)["place"] == "Toronto"
        distant = _feature(-75.70, 45.42, aqhi_type="AQHI-Observation", aqhi=2.0,
                           location_name_en="Ottawa", observation_datetime="2026-09-20T18:00:00Z")
        assert pick_aqhi([stale, distant], [], 43.30, -79.80, self.NOW) is None

    def test_the_latest_forecast_for_the_nearest_hour_stands_in(self):
        from linecast.weather.sources import pick_aqhi
        def fc(published, hour, value):
            return _feature(-73.57, 45.50, aqhi_type="AQHI-Forecast", aqhi=value,
                            location_id="EHHUN", location_name_en="Montréal",
                            publication_datetime=published,
                            forecast_datetime=f"2026-09-20T{hour:02d}:00:00Z")
        period = {"geometry": {"type": "Point", "coordinates": [-73.57, 45.50]},
                  "properties": {"aqhi_type": "AQHI-Forecast-Period", "location_id": "EHHUN",
                                 "publication_datetime": "2026-09-20T10:00:00Z"}}
        feats = [fc("2026-09-19T21:00:00Z", 18, 7), fc("2026-09-20T10:00:00Z", 17, 2),
                 fc("2026-09-20T10:00:00Z", 19, 3), fc("2026-09-20T10:00:00Z", 12, 1), period]
        # 19:00 is the hour nearest 18:30, from the latest issue only.
        report = pick_aqhi([], feats, 45.52, -73.60, self.NOW)
        assert report == {"aqhi": 3, "place": "Montréal", "kind": "forecast",
                          "time": "2026-09-20T19:00:00+00:00"}
        # Hours away from now are no answer.
        assert pick_aqhi([], [fc("2026-09-20T10:00:00Z", 10, 5)], 45.52, -73.60, self.NOW) is None

    def test_apply_attaches_the_report_or_computes(self):
        from linecast.weather.sources import apply_national_index
        data = _india_aqi_response(pm2_5=5.0)
        out = apply_national_index(data, "CA", 45.5, -73.6,
                                   canada={"aqhi": 4, "kind": "observed", "place": "Montréal"})
        assert out is data
        assert out["current"]["aqhi"] == 4 and out["current"]["aqhi_source"] == "observed"
        assert out["current"]["aqhi_place"] == "Montréal"
        out = apply_national_index(_india_aqi_response(pm2_5=5.0), "CA", 45.5, -73.6, canada=None)
        assert out["current"]["aqhi"] == 3 and out["current"]["aqhi_source"] == "computed"
        # The report stands on its own when Open-Meteo gave nothing.
        out = apply_national_index(None, "CA", 45.5, -73.6,
                                   canada={"aqhi": 2, "kind": "forecast", "place": "Montréal"})
        assert out == {"current": {"aqhi": 2, "aqhi_source": "forecast", "aqhi_place": "Montréal"}}
        assert apply_national_index(None, "CA", 45.5, -73.6, canada=None) is None
        # Elsewhere the response passes through; India keeps its scale.
        assert apply_national_index(None, "US", 40.0, -74.0) is None
        data = _india_aqi_response()
        assert apply_national_index(data, "IN", 28.6, 77.2) is data
        assert data["current"]["india_aqi"] == 100 and "aqhi" not in data["current"]

    def test_apply_fetches_when_the_caller_did_not(self, monkeypatch):
        from linecast.weather import sources as _weather_sources
        calls = []
        monkeypatch.setattr(_weather_sources, "fetch_canada_aqhi",
                            lambda lat, lng, now=None: calls.append((lat, lng)) or
                            {"aqhi": 5, "kind": "observed", "place": "Calgary"})
        out = _weather_sources.apply_national_index(None, "CA", 51.05, -114.07)
        assert calls == [(51.05, -114.07)] and out["current"]["aqhi"] == 5

    def test_header_prints_the_index_with_its_words(self):
        import re
        from linecast._runtime import WeatherRuntime
        from linecast.weather.sections import render_header
        data = _india_aqi_response(pm2_5=5.0)
        data["current"].update({"aqhi": 4, "aqhi_source": "observed"})
        forecast = {"current": {"temperature_2m": 20.0, "apparent_temperature": 20.0,
                                "weather_code": 1, "relative_humidity_2m": 50,
                                "wind_speed_10m": 5.0, "wind_gusts_10m": 8.0,
                                "time": "2026-09-20T14:00"},
                    "hourly": {"time": [], "temperature_2m": []}, "daily": {}}
        for lang, words in (("en", "AQHI 4 Moderate risk"), ("fr", "CAS 4 Risque modéré"),
                            ("fr-CA", "CAS 4 Risque modéré"), ("de", "AQHI 4 Moderate risk")):
            runtime = WeatherRuntime(live=False, icons="plain", lang=lang, celsius=True,
                                     metric=True, shading=True, oneline=False)
            header = render_header(forecast, 120, "Montréal", runtime, aqi_data=data)
            text = re.sub(r"\x1b\[[0-9;]*m", "", header)
            assert words in text, (lang, text)


class TestIndiaAqi:
    def test_sub_index_band_edges(self):
        from linecast.weather.sources import _india_sub_index
        assert _india_sub_index("pm2_5", 0) == 0
        assert _india_sub_index("pm2_5", 30) == 50
        assert _india_sub_index("pm2_5", 45) == 75
        assert _india_sub_index("pm2_5", 90) == 200
        assert _india_sub_index("pm10", 365) == 318.75

    def test_sub_index_severe_band_caps_at_500(self):
        from linecast.weather.sources import _india_sub_index
        assert round(_india_sub_index("pm2_5", 300), 1) == 438.5
        assert _india_sub_index("pm2_5", 380) == 500
        assert _india_sub_index("pm2_5", 9999) == 500

    def test_sub_index_co_in_micrograms(self):
        from linecast.weather.sources import _india_sub_index
        assert _india_sub_index("carbon_monoxide", 2000) == 100  # 2 mg/m³

    def test_worst_sub_index_wins(self):
        from linecast.weather.sources import india_aqi
        assert india_aqi(_india_aqi_response()) == 100  # pm2_5 60 / pm10 100
        assert india_aqi(_india_aqi_response(pm2_5=90.0)) == 200

    def test_forecast_hours_are_ignored(self):
        from linecast.weather.sources import india_aqi
        # 60 up to the current hour (index 29), absurd afterwards
        series = [60.0] * 30 + [999.0] * 18
        assert india_aqi(_india_aqi_response(pm2_5=series)) == 100

    def test_no_particulates_no_index(self):
        from linecast.weather.sources import india_aqi
        none = [None] * 48
        assert india_aqi(_india_aqi_response(pm2_5=none, pm10=none)) is None

    def test_old_cached_response_without_hourly_is_none(self):
        from linecast.weather.sources import india_aqi
        assert india_aqi({"current": {"us_aqi": 150}}) is None
        assert india_aqi(None) is None

    def test_apply_only_in_india(self):
        from linecast.weather.sources import apply_india_aqi
        data = _india_aqi_response()
        apply_india_aqi(data, "US")
        assert "india_aqi" not in data["current"]
        apply_india_aqi(data, "IN")
        assert data["current"]["india_aqi"] == 100

    def test_categories(self):
        from linecast.weather.sources import india_aqi_category
        assert india_aqi_category(40) == "Good"
        assert india_aqi_category(100) == "Satisfactory"
        assert india_aqi_category(150) == "Moderate"
        assert india_aqi_category(250) == "Poor"
        assert india_aqi_category(350) == "Very Poor"
        assert india_aqi_category(450) == "Severe"

    def test_header_shows_cpcb_number(self):
        from linecast.weather.sections import render_header
        forecast = _load("open_meteo_forecast.json")
        aqi_data = _india_aqi_response(pm2_5=300.0)
        from linecast.weather.sources import apply_india_aqi
        apply_india_aqi(aqi_data, "IN")
        header = render_header(forecast, 120, "Delhi", aqi_data=aqi_data)
        assert "438" in header  # the CPCB number, not us_aqi's 150
        assert "Severe" in header  # the CPCB category, marking the scale


# ---------------------------------------------------------------------------
# MetService alerts (New Zealand)
# ---------------------------------------------------------------------------

def _metservice_from_fixtures(cache_file, max_age, url, **kwargs):
    """Serve the feed and CAP fixtures the way fetch_bytes_cached would."""
    if url.endswith("/cap/rss"):
        return (FIXTURES / "metservice_rss.xml").read_bytes()
    for name in ("desertroad", "dunedintowaitatihighway"):
        if name in url:
            return (FIXTURES / f"metservice_cap_{name}.xml").read_bytes()
    return None


class TestMetServiceAlerts:
    """Parse a MetService CAP feed snapshot with its CAP files."""

    def _alerts(self, lat, lng, side_effect=_metservice_from_fixtures):
        from linecast.weather.sources import _fetch_alerts_metservice
        with patch("linecast._http.fetch_bytes_cached",
                   side_effect=side_effect):
            return _fetch_alerts_metservice(lat, lng)

    def test_desert_road_gets_its_warning(self):
        alerts = self._alerts(-39.379, 175.709)
        assert len(alerts) == 1
        a = alerts[0]
        assert a["event"] == "Road Snowfall Warning"
        assert a["severity"] == "Severe"  # ColourCode Orange
        assert "Snow showers are expected" in a["description"]
        for key in ("event", "headline", "description", "effective",
                    "expires", "severity", "url"):
            assert key in a

    def test_dunedin_gets_the_other_warning(self):
        alerts = self._alerts(-45.765, 170.56)
        assert len(alerts) == 1
        assert "Snow showers may continue" in alerts[0]["description"]

    def test_auckland_is_outside_both_polygons(self):
        assert self._alerts(-36.85, 174.76) == []

    def test_expired_alert_dropped(self):
        def expired(cache_file, max_age, url, **kwargs):
            raw = _metservice_from_fixtures(cache_file, max_age, url)
            return raw and raw.replace(b"2035-01-01", b"2020-01-01")
        assert self._alerts(-39.379, 175.709, side_effect=expired) == []

    def test_cancelled_alert_dropped(self):
        def cancelled(cache_file, max_age, url, **kwargs):
            raw = _metservice_from_fixtures(cache_file, max_age, url)
            return raw and raw.replace(b"<msgType>Update</msgType>",
                                       b"<msgType>Cancel</msgType>")
        assert self._alerts(-39.379, 175.709, side_effect=cancelled) == []

    def test_unreachable_feed_is_no_alerts(self):
        assert self._alerts(-39.379, 175.709,
                            side_effect=lambda *a, **k: None) == []
