"""The weather view says whose data it shows, without crowding the view."""

import inspect
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from linecast import _help

from linecast.weather import view as weather
from linecast.weather import sources as _weather_sources
from linecast._graphics import visible_len
from linecast._runtime import WeatherRuntime
from linecast.weather.json import build_payload
from linecast._i18n import LANGUAGE_CODES
from linecast.weather.sources import (
    ATTRIBUTION, alert_attribution, alert_source, forecast_attribution,
    _METEOALARM_SLUGS)

FIXTURES = Path(__file__).parent / "fixtures"
FIXED_NOW = datetime(2026, 3, 5, 14, 30)


def plain(text):
    return re.sub(r'\033\[[0-9;]*[a-zA-Z]', '', text)


def lines_of(panel):
    return [re.sub(r'\033\[[^m]*m', '', row)
            for row in re.split(r'\033\[\d+;\d+H', panel)[1:]]


class TestSources:
    def test_every_routed_country_names_its_service(self):
        # the router's explicit branches and the credit table must agree
        routed = set(re.findall(r'country_code == "([A-Z]{2})"',
                                inspect.getsource(_weather_sources._fetch_alerts_routed)))
        assert routed == set(_weather_sources._ALERT_SOURCES)

    def test_ireland_is_met_eireann(self):
        assert alert_source("IE") == "Met Éireann"
        assert alert_attribution("ie") == "Alerts by Met Éireann"

    def test_the_rest_of_europe_is_meteoalarm(self):
        for code in _METEOALARM_SLUGS:
            assert alert_source(code) == "MeteoAlarm"

    def test_no_feed_means_no_credit(self):
        assert alert_source("AR") is None
        assert alert_attribution("") is None

    def test_a_service_is_named_as_it_names_itself(self):
        assert alert_attribution("JP", "ja") == "警報：気象庁"
        assert alert_attribution("JP", "fr") == "Alertes par Japan Meteorological Agency"
        assert alert_attribution("DE", "de") == "Warnungen: Deutscher Wetterdienst"
        assert alert_attribution("CA", "fr") == "Alertes par Environnement Canada"

    @pytest.mark.parametrize("lang", LANGUAGE_CODES)
    def test_every_language_phrases_the_credit(self, lang):
        forecast = forecast_attribution(lang)
        assert "Open-Meteo" in forecast and "{" not in forecast
        alerts = alert_attribution("IE", lang)
        assert "Met Éireann" in alerts and "{" not in alerts
        if lang != "en":
            assert forecast != ATTRIBUTION

    @pytest.mark.parametrize("lang", LANGUAGE_CODES)
    def test_every_language_says_where_the_sky_was_seen(self, lang):
        from linecast.weather.sources import observed_credit
        observed = {"station": "KPWM", "name": "Portland Intl Jetport, ME, US",
                    "distance_km": 6.4, "time": 1790423460}
        seen = observed_credit(observed, lang, tz_name="America/New_York")
        assert "Portland Intl Jetport" in seen and "4 mi" in seen and "{" not in seen
        if lang not in ("en", "zh-HK"):
            assert "Observed" not in seen
    assert forecast_attribution("en") == ATTRIBUTION


class TestCreditRow:
    LONG = 'Open-Meteo & Met Éireann'

    def test_credit_left_and_hint_right(self):
        out = plain(weather.credit_row(120, 'en', 'IE'))
        assert out.startswith(self.LONG)
        assert out.endswith('  ? help') and visible_len(out) == 120

    def test_a_narrower_window_keeps_the_short_credit(self):
        out = plain(weather.credit_row(25, 'en', 'IE'))
        assert out.startswith('Open-Meteo ') and 'Éireann' not in out
        assert out.endswith('  ? help') and visible_len(out) == 25

    def test_a_narrow_window_keeps_the_hint_alone(self):
        out = plain(weather.credit_row(16, 'en', 'IE'))
        assert 'Open-Meteo' not in out and out.strip() == '? help'

    def test_the_credit_never_shortens_the_hint(self):
        # room for the credit and a clipped hint, but not the whole one
        out = plain(weather.credit_row(17, 'en', ''))
        assert 'Open-Meteo' not in out and out.endswith('? help')

    def test_the_credit_is_fainter_than_the_prose(self):
        from linecast.weather.style import DIM_RGB, MUTED_RGB
        from linecast import _theme
        assert (_theme.contrast_ratio(DIM_RGB, _theme.theme_bg)
                <= _theme.contrast_ratio(MUTED_RGB, _theme.theme_bg))
        assert weather.DIM in weather.credit_row(120, 'en', 'IE')


class TestPanel:
    def test_credits_follow_the_controls_after_a_spacer(self):
        rows = _help.entries('weather', 'en',
                             credits=(ATTRIBUTION, alert_attribution('IE')))
        assert rows[-3] is None
        assert rows[-2:] == [('', ATTRIBUTION), ('', 'Alerts by Met Éireann')]

    def test_no_alerts_feed_adds_no_row(self):
        rows = _help.entries('weather', 'en', credits=(ATTRIBUTION, alert_attribution('AR')))
        assert rows[-1] == ('', ATTRIBUTION) and rows[-2] is None

    def test_live_weather_panel_shows_the_credits(self):
        app = WeatherApp = weather.WeatherApp
        with patch("time.monotonic", return_value=0.0):
            app = WeatherApp({"v": 1}, [], None, 53.3, -6.3, SimpleNamespace(lang="en"),
                             location_name="Dublin", country="IE")
        panel = plain(app.help_panel().render(160, 50))
        assert ATTRIBUTION in panel and 'Alerts by Met Éireann' in panel

    def test_the_panel_speaks_the_display_language_in_both_columns(self):
        with patch("time.monotonic", return_value=0.0):
            app = weather.WeatherApp({"v": 1}, [], None, 35.7, 139.7, SimpleNamespace(lang="ja"),
                                     location_name="新宿区", country="JP")
        rows = lines_of(app.help_panel().render(160, 50))
        assert any(row.startswith('│ ホイール / ←→  ') for row in rows)
        assert any('クリック' in row for row in rows)
        assert not any('wheel' in row or 'click' in row for row in rows)
        assert any('気象データ提供：Open-Meteo' in row for row in rows)
        assert any('警報：気象庁' in row for row in rows)

    @pytest.mark.parametrize("lang", LANGUAGE_CODES)
    def test_the_key_column_fits_its_widest_gesture(self, lang):
        # the key and its description never run together; read from the
        # right, the description comes first and the key after it
        from linecast._i18n import is_rtl
        for view in _help.CONTROLS:
            rows = [re.sub("[\u2066-\u2069]", "", row)
                    for row in lines_of(_help.HelpPanel(view, lang).render(160, 50))]
            for key, text in _help.entries(view, lang):
                shown = _help.mark(key, lang)
                row = next(r for r in rows if shown in r and text in r)
                first, second = (text, shown) if is_rtl(lang) else (shown, text)
                assert re.search(re.escape(first) + r' {2,}' + re.escape(second), row), row


def _render(cols, rows, live=True, country_code="IE"):
    data = json.loads((FIXTURES / "open_meteo_forecast.json").read_text(encoding="utf-8"))
    runtime = WeatherRuntime(live=live, icons="emoji", lang="en", oneline=False,
                             celsius=False, metric=False)
    with patch("linecast.weather.view.get_terminal_size", return_value=(cols, rows)), \
         patch("linecast.weather.view._local_now_for_data", return_value=FIXED_NOW), \
         patch("linecast.weather.hourly._local_now_for_data", return_value=FIXED_NOW):
        output, _ = weather.render_from_data(data, alerts=[], runtime=runtime,
                                             location_name="Dublin",
                                             country_code=country_code)
    return plain(output).split("\n")


class TestLiveView:
    def test_the_last_row_credits_the_data_and_offers_help(self):
        lines = _render(160, 40)
        assert lines[-1].startswith('Open-Meteo & Met Éireann  ')
        assert lines[-1].endswith('  ? help') and visible_len(lines[-1]) == 160
        assert sum('? help' in line for line in lines) == 1
        assert len(lines) == 40

    def test_no_alerts_feed_credits_the_forecast_alone(self):
        lines = _render(160, 40, country_code="AR")
        assert lines[-1].startswith('Open-Meteo  ')
        assert 'Alerts' not in lines[-1]

    def test_a_narrow_window_keeps_the_forecast_name(self):
        lines = _render(30, 24)
        assert lines[-1].startswith('Open-Meteo  ') and 'Éireann' not in lines[-1]
        assert lines[-1].endswith('? help') and len(lines) == 24

    def test_the_row_is_in_the_display_language(self):
        data = json.loads((FIXTURES / "open_meteo_forecast.json").read_text(encoding="utf-8"))
        runtime = WeatherRuntime(live=True, icons="emoji", lang="ja", oneline=False,
                                 celsius=True, metric=True)
        with patch("linecast.weather.view.get_terminal_size", return_value=(120, 40)), \
             patch("linecast.weather.view._local_now_for_data", return_value=FIXED_NOW), \
             patch("linecast.weather.hourly._local_now_for_data", return_value=FIXED_NOW):
            output, _ = weather.render_from_data(data, alerts=[], runtime=runtime,
                                                 location_name="新宿区", country_code="JP")
        last = plain(output).split("\n")[-1]
        assert last.startswith('Open-Meteo & 気象庁')
        assert last.endswith('  ? ヘルプ')

    def test_print_output_has_no_credit_row(self):
        lines = _render(160, 40, live=False)
        assert not any('Open-Meteo' in line or '? help' in line for line in lines)


class TestJson:
    def test_sources_name_the_forecast_and_the_alerts_service(self):
        data = json.loads((FIXTURES / "open_meteo_forecast.json").read_text(encoding="utf-8"))
        runtime = WeatherRuntime(live=False, icons="emoji", lang="en", oneline=False,
                                 celsius=False, metric=False, shading=False)
        payload = build_payload(data, "Dublin", "IE", runtime, now=FIXED_NOW)
        assert payload["sources"] == {"forecast": "Open-Meteo", "air_quality": "Open-Meteo",
                                      "alerts": "Met Éireann"}
        payload = build_payload(data, "Buenos Aires", "AR", runtime, now=FIXED_NOW)
        assert payload["sources"]["alerts"] is None
