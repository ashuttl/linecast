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
    return json.loads((FIXTURES / name).read_text())


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
            for key in ("event", "headline", "description", "severity", "effective", "expires", "url"):
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
            for key in ("event", "headline", "description", "severity", "effective", "expires", "url"):
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
        with patch("linecast._weather_sources._fetch_alerts_nws", return_value=[{"event": "x"}]) as mock_fn:
            result = fetch_alerts(40.7, -74.0, country_code="US")
        mock_fn.assert_called_once_with(40.7, -74.0)
        assert result == [{"event": "x"}]

    def test_routes_ca_to_eccc(self):
        from linecast._weather_sources import fetch_alerts
        with patch("linecast._weather_sources._fetch_alerts_eccc", return_value=[{"event": "x"}]) as mock_fn:
            result = fetch_alerts(45.4, -75.7, country_code="CA", lang="fr")
        mock_fn.assert_called_once_with(45.4, -75.7, lang="fr")
        assert result == [{"event": "x"}]

    def test_routes_de_to_brightsky(self):
        from linecast._weather_sources import fetch_alerts
        with patch("linecast._weather_sources._fetch_alerts_brightsky", return_value=[{"event": "x"}]) as mock_fn:
            result = fetch_alerts(52.52, 13.405, country_code="DE", lang="de")
        mock_fn.assert_called_once_with(52.52, 13.405, lang="de")
        assert result == [{"event": "x"}]

    def test_routes_no_to_metno(self):
        from linecast._weather_sources import fetch_alerts
        with patch("linecast._weather_sources._fetch_alerts_metno", return_value=[{"event": "x"}]) as mock_fn:
            result = fetch_alerts(59.91, 10.75, country_code="NO")
        mock_fn.assert_called_once_with(59.91, 10.75)
        assert result == [{"event": "x"}]

    def test_routes_ie_to_meteireann(self):
        from linecast._weather_sources import fetch_alerts
        with patch("linecast._weather_sources._fetch_alerts_meteireann", return_value=[{"event": "x"}]) as mock_fn:
            result = fetch_alerts(53.35, -6.26, country_code="IE")
        mock_fn.assert_called_once_with(53.35, -6.26)
        assert result == [{"event": "x"}]

    def test_routes_jp_to_jma(self):
        from linecast._weather_sources import fetch_alerts
        with patch("linecast._weather_sources._fetch_alerts_jma", return_value=[{"event": "x"}]) as mock_fn:
            result = fetch_alerts(35.68, 139.76, country_code="JP", lang="ja")
        mock_fn.assert_called_once_with(35.68, 139.76, lang="ja")
        assert result == [{"event": "x"}]

    def test_routes_meteoalarm_country(self):
        from linecast._weather_sources import fetch_alerts
        address = {"city": "Amsterdam", "state": "Noord-Holland"}
        with patch("linecast._weather_sources._fetch_alerts_meteoalarm", return_value=[{"event": "x"}]) as mock_fn:
            result = fetch_alerts(52.37, 4.89, country_code="NL", lang="en", address=address)
        mock_fn.assert_called_once_with(52.37, 4.89, "netherlands", lang="en", address=address)
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
        assert "comunidad" in words
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
