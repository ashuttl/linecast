"""Tests for weather API response parsing.

These use real API responses saved as fixtures. If an upstream API changes
its response format, these tests will catch the breakage.
"""

import json
import sys
from datetime import datetime
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
        import linecast.weather as w
        result = w.render_header(self.data, 80, "Test City")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_render_hourly_succeeds(self):
        """Smoke test: render_hourly doesn't crash on real data."""
        import linecast.weather as w
        now = datetime.fromisoformat(self.data["hourly"]["time"][24])
        result = w.render_hourly(self.data, 80, now=now)
        assert isinstance(result, list)

    def test_comparative_line_succeeds(self):
        """Smoke test: _comparative_line doesn't crash on real data."""
        import linecast.weather as w
        now = datetime.fromisoformat(self.data["hourly"]["time"][24])
        result = w._comparative_line(self.data["daily"], now)
        assert isinstance(result, str)


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
        from linecast._weather_sources import _fetch_alerts_nws
        with patch("linecast._weather_sources.fetch_json_cached", return_value=self.data):
            alerts = _fetch_alerts_nws(40.7, -74.0)
        assert len(alerts) == 1
        assert alerts[0]["event"] == "Heat Advisory"

    def test_parser_drops_exercise_alerts(self):
        """Exercise status should also be filtered."""
        import copy
        data = copy.deepcopy(self.data)
        data["features"][1]["properties"]["status"] = "Exercise"
        from linecast._weather_sources import _fetch_alerts_nws
        with patch("linecast._weather_sources.fetch_json_cached", return_value=data):
            alerts = _fetch_alerts_nws(40.7, -74.0)
        assert len(alerts) == 0


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
        from linecast._weather_sources import _fetch_alerts_brightsky
        with patch("linecast._weather_sources.fetch_json_cached", return_value=self.data):
            alerts = _fetch_alerts_brightsky(52.52, 13.405)
        assert isinstance(alerts, list)
        for a in alerts:
            for key in ("event", "headline", "description", "severity", "effective", "expires",
                        "url"):
                assert key in a, f"Missing normalized key: {key}"


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
        from linecast._weather_sources import _fetch_alerts_metno
        with patch("linecast._weather_sources.fetch_json_cached", return_value=self.data):
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
        from linecast._weather_sources import _fetch_alerts_meteireann
        with patch("linecast._weather_sources.fetch_json_cached", return_value=self.data):
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
        from linecast._weather_sources import _fetch_alerts_meteoalarm
        address = {"city": "Amsterdam", "state": "Noord-Holland"}
        with patch("linecast._weather_sources.fetch_json_cached", return_value=self.data):
            alerts = _fetch_alerts_meteoalarm(52.37, 4.89, "netherlands", address=address)
        assert isinstance(alerts, list)
        for a in alerts:
            for key in ("event", "headline", "severity", "effective", "expires"):
                assert key in a, f"Missing normalized key: {key}"

    def test_parse_without_address(self):
        """Without address, should still return Severe+ alerts."""
        from linecast._weather_sources import _fetch_alerts_meteoalarm
        with patch("linecast._weather_sources.fetch_json_cached", return_value=self.data):
            alerts = _fetch_alerts_meteoalarm(52.37, 4.89, "netherlands", address=None)
        assert isinstance(alerts, list)


# ---------------------------------------------------------------------------
# JMA alerts parsing
# ---------------------------------------------------------------------------

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
        from linecast._weather_sources import _fetch_alerts_jma
        with patch("linecast._weather_sources.fetch_json_cached", return_value=self.data):
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
        from linecast._weather_sources import _fetch_alerts_jma
        with patch("linecast._weather_sources.fetch_json_cached", return_value=self.data):
            alerts = _fetch_alerts_jma(35.6764, 139.6500, lang="ja")
        assert isinstance(alerts, list)
        assert len(alerts) == 3
        # In Japanese mode, event names are localized and headline uses JMA headline text.
        assert alerts[0]["event"] == "大雨警報"
        assert alerts[0]["headline"] == self.data["headlineText"]
        assert alerts[0]["description"] == self.data["headlineText"]


# ---------------------------------------------------------------------------
# Alert provider dispatch tests
# ---------------------------------------------------------------------------

class TestAlertProviderRouting:
    """Ensure fetch_alerts routes to the expected provider for each country."""

    def test_routes_us_to_nws(self):
        from linecast._weather_sources import fetch_alerts
        with patch("linecast._weather_sources._fetch_alerts_nws",
                   return_value=[{"event": "x"}]) as mock_fn:
            result = fetch_alerts(40.7, -74.0, country_code="US")
        mock_fn.assert_called_once_with(40.7, -74.0)
        assert result == [{"event": "x"}]

    def test_routes_ca_to_eccc(self):
        from linecast._weather_sources import fetch_alerts
        with patch("linecast._weather_sources._fetch_alerts_eccc",
                   return_value=[{"event": "x"}]) as mock_fn:
            result = fetch_alerts(45.4, -75.7, country_code="CA", lang="fr")
        mock_fn.assert_called_once_with(45.4, -75.7, lang="fr")
        assert result == [{"event": "x"}]

    def test_routes_de_to_brightsky(self):
        from linecast._weather_sources import fetch_alerts
        with patch("linecast._weather_sources._fetch_alerts_brightsky",
                   return_value=[{"event": "x"}]) as mock_fn:
            result = fetch_alerts(52.52, 13.405, country_code="DE", lang="de")
        mock_fn.assert_called_once_with(52.52, 13.405, lang="de")
        assert result == [{"event": "x"}]

    def test_routes_no_to_metno(self):
        from linecast._weather_sources import fetch_alerts
        with patch("linecast._weather_sources._fetch_alerts_metno",
                   return_value=[{"event": "x"}]) as mock_fn:
            result = fetch_alerts(59.91, 10.75, country_code="NO")
        mock_fn.assert_called_once_with(59.91, 10.75)
        assert result == [{"event": "x"}]

    def test_routes_ie_to_meteireann(self):
        from linecast._weather_sources import fetch_alerts
        with patch("linecast._weather_sources._fetch_alerts_meteireann",
                   return_value=[{"event": "x"}]) as mock_fn:
            result = fetch_alerts(53.35, -6.26, country_code="IE")
        mock_fn.assert_called_once_with(53.35, -6.26)
        assert result == [{"event": "x"}]

    def test_routes_jp_to_jma(self):
        from linecast._weather_sources import fetch_alerts
        with patch("linecast._weather_sources._fetch_alerts_jma",
                   return_value=[{"event": "x"}]) as mock_fn:
            result = fetch_alerts(35.68, 139.76, country_code="JP", lang="ja")
        mock_fn.assert_called_once_with(35.68, 139.76, lang="ja")
        assert result == [{"event": "x"}]

    def test_routes_meteoalarm_country(self):
        from linecast._weather_sources import fetch_alerts
        address = {"city": "Amsterdam", "state": "Noord-Holland"}
        with patch("linecast._weather_sources._fetch_alerts_meteoalarm",
                   return_value=[{"event": "x"}]) as mock_fn:
            result = fetch_alerts(52.37, 4.89, country_code="NL", lang="en", address=address)
        mock_fn.assert_called_once_with(52.37, 4.89, "netherlands", lang="en", address=address)
        assert result == [{"event": "x"}]

    def test_routes_in_to_sachet(self):
        from linecast._weather_sources import fetch_alerts
        with patch("linecast._weather_sources._fetch_alerts_sachet",
                   return_value=[{"event": "x"}]) as mock_fn:
            result = fetch_alerts(28.61, 77.21, country_code="IN")
        mock_fn.assert_called_once_with(28.61, 77.21, lang="en")
        assert result == [{"event": "x"}]

    def test_routes_nz_to_metservice(self):
        from linecast._weather_sources import fetch_alerts
        with patch("linecast._weather_sources._fetch_alerts_metservice",
                   return_value=[{"event": "x"}]) as mock_fn:
            result = fetch_alerts(-41.29, 174.78, country_code="NZ")
        mock_fn.assert_called_once_with(-41.29, 174.78)
        assert result == [{"event": "x"}]

    def test_routes_newer_meteoalarm_members(self):
        from linecast._weather_sources import fetch_alerts
        for code, slug, lat, lng in (
                ("UA", "ukraine", 50.45, 30.52),
                ("BA", "bosnia-herzegovina", 43.86, 18.41),
                ("MK", "republic-of-north-macedonia", 41.99, 21.43)):
            with patch("linecast._weather_sources._fetch_alerts_meteoalarm",
                       return_value=[{"event": "x"}]) as mock_fn:
                result = fetch_alerts(lat, lng, country_code=code)
            mock_fn.assert_called_once_with(lat, lng, slug, lang="en",
                                            address=None)
            assert result == [{"event": "x"}]

    def test_unknown_country_returns_empty(self):
        from linecast._weather_sources import fetch_alerts
        assert fetch_alerts(0, 0, country_code="XX") == []


# ---------------------------------------------------------------------------
# Helper unit tests
# ---------------------------------------------------------------------------

class TestLocationMatching:
    """Test MeteoAlarm area matching helpers."""

    def test_extract_location_words(self):
        from linecast._weather_sources import _extract_location_words
        address = {"city": "Madrid", "state": "Comunidad de Madrid"}
        words = _extract_location_words(address)
        assert "madrid" in words
        assert "comunidad" not in words  # a tier, and Valencia's too
        assert "de" not in words  # too short

    def test_area_matches_positive(self):
        from linecast._weather_sources import _area_matches
        words = {"madrid", "comunidad"}
        assert _area_matches("Sierra de Madrid", words)

    def test_area_matches_negative(self):
        from linecast._weather_sources import _area_matches
        words = {"madrid", "comunidad"}
        assert not _area_matches("Bizkaia interior", words)

    def test_area_matches_empty(self):
        from linecast._weather_sources import _area_matches
        assert not _area_matches("", {"madrid"})
        assert not _area_matches("Madrid", set())

    def test_meteireann_severity(self):
        from linecast._weather_sources import _meteireann_severity
        assert _meteireann_severity("red") == "Extreme"
        assert _meteireann_severity("orange") == "Severe"
        assert _meteireann_severity("yellow") == "Moderate"
        assert _meteireann_severity("green") == "Minor"

    def test_parse_meteireann_dt(self):
        from linecast._weather_sources import _parse_meteireann_dt
        assert _parse_meteireann_dt("00:00 Saturday 07/03/2026") == "2026-03-07T00:00:00"
        assert _parse_meteireann_dt("14:30 Monday 15/12/2025") == "2025-12-15T14:30:00"
        assert _parse_meteireann_dt("") == ""
        assert _parse_meteireann_dt(None) == ""

    def test_cma_severity_from_pic(self):
        from linecast._weather_sources import _cma_severity_from_pic
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
        from linecast._weather_sources import _parse_cma_issuetime
        assert _parse_cma_issuetime("2026/03/07 22:39") == "2026-03-07T22:39:00"
        assert _parse_cma_issuetime("2026/03/07 06:00") == "2026-03-07T06:00:00"
        assert _parse_cma_issuetime("") == ""
        assert _parse_cma_issuetime(None) == ""

    def test_cma_provinces_for_coords(self):
        from linecast._weather_sources import _cma_provinces_for_coords
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
        from linecast._weather_sources import _parse_cma_data
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
        from linecast._weather_sources import _parse_cma_data
        alerts = _parse_cma_data(self.data, "14", lang="zh")
        assert len(alerts) == 2
        # Events should be in Chinese
        events = " ".join(a["event"] for a in alerts)
        assert "\u5927\u96fe" in events or "\u9053\u8def\u7ed3\u51b0" in events

    def test_parse_beijing_en(self):
        """Parse alerts for Beijing (11) — red fog warning."""
        from linecast._weather_sources import _parse_cma_data
        alerts = _parse_cma_data(self.data, "11", lang="en")
        assert len(alerts) == 1
        a = alerts[0]
        assert a["event"] == "Red Dense Fog Warning"
        assert a["severity"] == "Extreme"
        assert a["effective"] == "2026-03-07T06:00:00"

    def test_parse_other_province_returns_empty(self):
        """Province with no alerts in fixture returns empty list."""
        from linecast._weather_sources import _parse_cma_data
        alerts = _parse_cma_data(self.data, "65", lang="en")  # Xinjiang
        assert alerts == []

    def test_parse_with_fetch_mock(self):
        """Smoke test: _fetch_alerts_cma parser produces our standard dict."""
        from linecast._weather_sources import _fetch_alerts_cma
        with patch("linecast._weather_sources.fetch_json_cached", return_value=self.data):
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
        from linecast._weather_sources import fetch_alerts
        with patch("linecast._weather_sources._fetch_alerts_cma",
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
        from linecast._weather_sources import _parse_hko_warnsum
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
        from linecast._weather_sources import _parse_hko_warnsum
        assert _parse_hko_warnsum({}) == []

    def test_routing_hk_to_hko(self):
        from linecast._weather_sources import fetch_alerts
        with patch("linecast._weather_sources._fetch_alerts_hko",
                   return_value=[{"event": "x"}]) as mock_fn:
            result = fetch_alerts(22.3, 114.2, country_code="HK")
        mock_fn.assert_called_once_with()
        assert result == [{"event": "x"}]


class TestReverseGeocodeCountry:
    """Nominatim files Hong Kong and Macau under China."""

    def test_hong_kong_and_macau_get_their_own_codes(self):
        from linecast._weather_sources import _country_code
        assert _country_code({"country_code": "cn", "ISO3166-2-lvl3": "CN-HK"}) == "HK"
        assert _country_code({"country_code": "cn", "ISO3166-2-lvl3": "CN-MO"}) == "MO"
        assert _country_code({"country_code": "cn", "ISO3166-2-lvl3": "CN-GD"}) == "CN"
        assert _country_code({"country_code": "us"}) == "US"
        assert _country_code({}) == ""


class TestReverseGeocodeName:
    """Nominatim names small places under keys down to hamlet (issue #50)."""

    def _name(self, address):
        from linecast import _weather_sources as ws
        with patch.object(ws, "read_cache", return_value=None), \
                patch.object(ws, "write_cache", lambda *a, **k: None), \
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
    from linecast import _weather_sources as ws
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
        from linecast._weather_sources import _extract_location_words
        words = _extract_location_words({"city": "City of Edinburgh",
                                         "state": "Alba / Scotland"})
        assert "city" not in words
        assert {"edinburgh", "scotland"} <= words

    def test_a_place_survives_its_tier_word(self):
        from linecast._weather_sources import _extract_location_words
        words = _extract_location_words({"state": "Auvergne-Rhône-Alpes Region"})
        assert words == {"auvergne-rhône-alpes"}

    def test_tier_words_are_dropped_in_the_countrys_own_language(self):
        # Issue #57: Nominatim names Warsaw in Polish, and "województwo"
        # begins every Polish areaDesc in the country.
        from linecast._weather_sources import _extract_location_words
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
        from linecast._weather_sources import _drop_feed_wide_words
        descs = self._descs(30, "zork")
        assert _drop_feed_wide_words({"zork", "york"}, descs) == {"york"}

    def test_a_word_in_a_few_warnings_is_kept(self):
        from linecast._weather_sources import _drop_feed_wide_words
        descs = self._descs(30, "zork") + [["york"]] * 3
        assert "york" in _drop_feed_wide_words({"york"}, descs)

    def test_a_small_feed_is_not_judged(self):
        # Three warnings, all in one province: the province is not generic.
        from linecast._weather_sources import _drop_feed_wide_words
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
        assert regions_at(50.5, 10.5) == {"XX001", "XX100", "NUTS3/XX002"}

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

    def test_keys_are_spelled_by_type(self):
        from linecast._meteoalarm_regions import key_for
        assert key_for("EMMA_ID", "PL3001") == "PL3001"
        assert key_for("NUTS3", "FR101") == "NUTS3/FR101"
        assert key_for("NUTS2", "HU10") == "NUTS2/HU10"


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
        assert regions_at(48.209, 16.372) == {"AT010", "AT901"}  # Vienna

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


class TestAlertCap:
    """However many a feed sends, the board shows the gravest few."""

    def test_the_gravest_come_first_and_the_rest_are_cut(self):
        from linecast._weather_sources import _trim_alerts, MAX_ALERTS
        alerts = ([{"event": f"m{i}", "severity": "Moderate"} for i in range(6)]
                  + [{"event": "x", "severity": "Extreme"}]
                  + [{"event": f"s{i}", "severity": "Severe"} for i in range(6)])
        got = _trim_alerts(alerts)
        assert len(got) == MAX_ALERTS
        assert got[0]["event"] == "x"
        assert [a["severity"] for a in got[1:7]] == ["Severe"] * 6
        assert got[7]["event"] == "m0"

    def test_the_cap_applies_to_every_provider(self):
        from linecast import _weather_sources as ws
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
        from linecast._weather_sources import _cap_polygons
        rings = _cap_polygons({"polygon": _box(0, 1, 0, 1)})
        assert len(rings) == 1
        assert rings[0][0] == (0.0, 0.0)

    def test_a_bare_string_is_accepted(self):
        from linecast._weather_sources import _cap_polygons
        assert len(_cap_polygons({"polygon": _box(0, 1, 0, 1)[0]})) == 1

    def test_no_polygon_is_no_rings(self):
        from linecast._weather_sources import _cap_polygons
        assert _cap_polygons({"areaDesc": "somewhere"}) == []

    def test_a_ring_too_short_to_enclose_anything_is_skipped(self):
        from linecast._weather_sources import _cap_polygons
        assert _cap_polygons({"polygon": ["1,1 2,2"]}) == []

    def test_inside_and_outside(self):
        from linecast._weather_sources import _cap_polygons, _point_in_ring
        ring = _cap_polygons({"polygon": _box(50, 52, -2, 0)})[0]
        assert _point_in_ring(51, -1, ring)
        assert not _point_in_ring(55, -1, ring)
        assert not _point_in_ring(51, 3, ring)

    def test_a_concave_ring_excludes_its_notch(self):
        # A C-shape: the middle of the opening is outside, though it sits
        # within the bounding box.
        from linecast._weather_sources import _point_in_ring
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
        from linecast._weather_sources import _fetch_alerts_sachet
        with patch("linecast._weather_sources.fetch_json_cached",
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
        from linecast._weather_sources import _fetch_alerts_sachet
        with patch("linecast._weather_sources.fetch_json_cached",
                   return_value=None):
            assert _fetch_alerts_sachet(28.61, 77.21) == []

    def test_feed_datetime_parsing(self):
        from linecast._weather_sources import _sachet_datetime
        assert (_sachet_datetime("Sun Aug 30 21:00:00 IST 2026")
                == "2026-08-30T21:00:00+05:30")
        assert _sachet_datetime("nonsense") == ""
        assert _sachet_datetime(None) == ""

    def test_cap_language_codes_normalize_to_iso(self):
        # SACHET's own coinages ("OD" for Odia, "TL" for Telugu) beside
        # the upcased ISO codes it uses for most languages.
        from linecast._weather_sources import _sachet_cap_lang
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


class TestIndiaAqi:
    def test_sub_index_band_edges(self):
        from linecast._weather_sources import _india_sub_index
        assert _india_sub_index("pm2_5", 0) == 0
        assert _india_sub_index("pm2_5", 30) == 50
        assert _india_sub_index("pm2_5", 45) == 75
        assert _india_sub_index("pm2_5", 90) == 200
        assert _india_sub_index("pm10", 365) == 318.75

    def test_sub_index_severe_band_caps_at_500(self):
        from linecast._weather_sources import _india_sub_index
        assert round(_india_sub_index("pm2_5", 300), 1) == 438.5
        assert _india_sub_index("pm2_5", 380) == 500
        assert _india_sub_index("pm2_5", 9999) == 500

    def test_sub_index_co_in_micrograms(self):
        from linecast._weather_sources import _india_sub_index
        assert _india_sub_index("carbon_monoxide", 2000) == 100  # 2 mg/m³

    def test_worst_sub_index_wins(self):
        from linecast._weather_sources import india_aqi
        assert india_aqi(_india_aqi_response()) == 100  # pm2_5 60 / pm10 100
        assert india_aqi(_india_aqi_response(pm2_5=90.0)) == 200

    def test_forecast_hours_are_ignored(self):
        from linecast._weather_sources import india_aqi
        # 60 up to the current hour (index 29), absurd afterwards
        series = [60.0] * 30 + [999.0] * 18
        assert india_aqi(_india_aqi_response(pm2_5=series)) == 100

    def test_no_particulates_no_index(self):
        from linecast._weather_sources import india_aqi
        none = [None] * 48
        assert india_aqi(_india_aqi_response(pm2_5=none, pm10=none)) is None

    def test_old_cached_response_without_hourly_is_none(self):
        from linecast._weather_sources import india_aqi
        assert india_aqi({"current": {"us_aqi": 150}}) is None
        assert india_aqi(None) is None

    def test_apply_only_in_india(self):
        from linecast._weather_sources import apply_india_aqi
        data = _india_aqi_response()
        apply_india_aqi(data, "US")
        assert "india_aqi" not in data["current"]
        apply_india_aqi(data, "IN")
        assert data["current"]["india_aqi"] == 100

    def test_categories(self):
        from linecast._weather_sources import india_aqi_category
        assert india_aqi_category(40) == "Good"
        assert india_aqi_category(100) == "Satisfactory"
        assert india_aqi_category(150) == "Moderate"
        assert india_aqi_category(250) == "Poor"
        assert india_aqi_category(350) == "Very Poor"
        assert india_aqi_category(450) == "Severe"

    def test_header_shows_cpcb_number(self):
        from linecast._weather_sections import render_header
        forecast = _load("open_meteo_forecast.json")
        aqi_data = _india_aqi_response(pm2_5=300.0)
        from linecast._weather_sources import apply_india_aqi
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
        from linecast._weather_sources import _fetch_alerts_metservice
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
