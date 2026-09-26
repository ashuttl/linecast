"""Canada's humidex and wind chill in place of feels-like."""

import re
from datetime import datetime, timedelta

from linecast._runtime import WeatherRuntime
from linecast.weather.humidex import apply_canadian_indices, humidex, wind_chill

NOON = datetime(2026, 7, 15, 12, 0)


def _runtime(lang="en", celsius=True):
    return WeatherRuntime(live=False, icons="plain", lang=lang, oneline=False,
                          celsius=celsius, metric=celsius, shading=False)


def _plain(text):
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def _forecast(temp, dew, wind, feels, hours=None):
    """A forecast whose current hour and hourly rows are the given
    readings; `hours` is a list of (temp, dew, wind, feels) from noon."""
    hours = hours or [(temp, dew, wind, feels)]
    return {
        "current": {"temperature_2m": temp, "dew_point_2m": dew, "wind_speed_10m": wind,
                    "apparent_temperature": feels, "relative_humidity_2m": 60,
                    "weather_code": 1, "wind_gusts_10m": wind, "time": "2026-07-15T12:00"},
        "hourly": {
            "time": [(NOON + timedelta(hours=k)).isoformat(timespec="minutes")
                     for k in range(len(hours))],
            "temperature_2m": [h[0] for h in hours],
            "dew_point_2m": [h[1] for h in hours],
            "wind_speed_10m": [h[2] for h in hours],
            "apparent_temperature": [h[3] for h in hours],
            "relative_humidity_2m": [60] * len(hours),
        },
        "daily": {},
    }


class TestFormulas:
    def test_the_worked_examples(self):
        # Wikipedia's: 30 °C with a dew point of 15 °C is humidex 34, and
        # -20 °C in a 5 km/h wind is a wind chill of -24
        assert round(humidex(30, 15)) == 34
        assert round(wind_chill(-20, 5)) == -24

    def test_the_light_wind_formula(self):
        # Under 5 km/h the glossary's second formula: T + (-1.59 + 0.1345 T) / 5 * V
        assert wind_chill(-10, 4) == -10 + (-1.59 + 0.1345 * -10) / 5 * 4

    def test_reported_only_as_environment_canada_reports_them(self):
        assert humidex(19.9, 18) is None            # below 20 °C
        assert humidex(22, 0) is None               # less than a degree above the air
        assert wind_chill(0.5, 30) is None          # above freezing
        assert wind_chill(-5, 0) is None            # no wind
        assert wind_chill(-1, 1) is None            # less than a degree below the air


class TestAttached:
    def test_in_canada_on_celsius_only(self):
        for country, runtime, attached in (("CA", _runtime(), True),
                                           ("US", _runtime(), False),
                                           ("CA", _runtime(celsius=False), False)):
            data = apply_canadian_indices(_forecast(30, 20, 10, 33), country, runtime)
            assert ("humidex" in data["current"]) == attached, country
            assert ("wind_chill" in data["hourly"]) == attached, country

    def test_the_wind_is_read_in_kmh(self):
        # Celsius with imperial units otherwise: the wind comes in mph
        runtime = WeatherRuntime(live=False, icons="plain", lang="en", oneline=False,
                                 celsius=True, metric=False, shading=False)
        data = apply_canadian_indices(_forecast(-20, -25, 10 / 1.609344, -30), "CA", runtime)
        assert round(data["current"]["wind_chill"]) == round(wind_chill(-20, 10))


class TestHeader:
    def _header(self, forecast, lang="en"):
        from linecast.weather.sections import render_header
        runtime = _runtime(lang)
        data = apply_canadian_indices(forecast, "CA", runtime)
        return _plain(render_header(data, 120, "Montréal", runtime))

    def test_humidex_in_place_of_feels(self):
        header = self._header(_forecast(30, 15, 5, 31))
        assert "humidex 34" in header
        assert "feels" not in header

    def test_wind_chill_in_french(self):
        header = self._header(_forecast(-20, -25, 5, -27), lang="fr-CA")
        assert "refroidissement éolien -24" in header
        assert "ressenti" not in header

    def test_neither_on_a_mild_day(self):
        header = self._header(_forecast(12, 5, 10, 10))
        assert "feels" not in header and "humidex" not in header

    def test_other_languages_keep_feels(self):
        header = self._header(_forecast(30, 15, 5, 31), lang="de")
        assert "humidex" not in header
        assert "31" in header


class TestSentences:
    def _data(self, hours, lang="en"):
        return apply_canadian_indices(_forecast(*hours[0], hours=hours), "CA", _runtime(lang))

    def test_the_heat_ahead_is_the_humidex(self):
        from linecast.weather.sections import feels_ahead_sentence
        # The afternoon peaks at 32 °C with a dew point of 22: humidex 41
        hours = [(26, 16, 5, 27), (28, 18, 5, 29), (30, 20, 5, 32), (32, 22, 5, 35),
                 (32, 22, 5, 35), (30, 20, 5, 32), (27, 17, 5, 28)]
        data = self._data(hours)
        expected = round(humidex(32, 22))
        assert feels_ahead_sentence(data["hourly"], NOON, _runtime(),
                                    current=data["current"]) == \
            f"Humidex {expected} this afternoon"
        data = self._data(hours, "fr-CA")
        assert feels_ahead_sentence(data["hourly"], NOON, _runtime("fr-CA"),
                                    current=data["current"]) == \
            f"Humidex {expected} cet après-midi"

    def test_the_cold_ahead_is_the_wind_chill(self):
        from linecast.weather.sections import feels_ahead_sentence
        hours = [(-12, -18, 10, -18), (-15, -20, 20, -24), (-20, -25, 30, -31),
                 (-24, -28, 30, -36), (-24, -28, 30, -36), (-20, -25, 20, -29)]
        data = self._data(hours)
        expected = round(wind_chill(-24, 30))
        assert feels_ahead_sentence(data["hourly"], NOON, _runtime(),
                                    current=data["current"]) == \
            f"Wind chill −{abs(expected)} this afternoon"

    def test_the_label_names_the_cause_so_no_sentence_does(self):
        from linecast.weather.sections import feels_sentence
        data = self._data([(30, 22, 5, 36)])
        assert feels_sentence(data["current"], {}, NOON, _runtime()) == ""


class TestJson:
    def test_the_indices_beside_feels_like(self):
        from linecast.weather.json import build_payload
        data = apply_canadian_indices(
            _forecast(30, 15, 5, 31, hours=[(30, 15, 5, 31), (18, 10, 5, 18)]), "CA", _runtime())
        payload = build_payload(data, "Montréal", "CA", _runtime(), now=NOON)
        assert round(payload["current"]["humidex"]) == 34
        assert payload["current"]["wind_chill"] is None
        assert [h["humidex"] is None for h in payload["hourly"]] == [False, True]
        plain = build_payload(_forecast(30, 15, 5, 31), "Portland", "US", _runtime(), now=NOON)
        assert "humidex" not in plain["current"]
