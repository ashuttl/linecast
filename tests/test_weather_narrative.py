"""The prose lines under the weather graph: what they say, and how they pack."""

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from linecast._runtime import WeatherRuntime
from linecast._weather_i18n import _STRINGS, _s
from linecast._weather_sections import feels_sentence, narrative_lines

NOON = datetime(2026, 7, 15, 12, 0)

# One day of sun events, so the sunshine reading has something to check.
DAILY = {
    "sunrise": ["2026-07-15T05:40"],
    "sunset": ["2026-07-15T20:55"],
    "temperature_2m_max": [86],
}


def _runtime(**overrides):
    defaults = dict(live=False, icons="plain", lang="en", oneline=False,
                    celsius=False, metric=False, shading=False)
    defaults.update(overrides)
    return WeatherRuntime(**defaults)


class TestFeelsSentence:
    """Which of humidity, wind and sunshine gets the blame."""

    def test_wind_explains_a_colder_apparent_temperature(self):
        current = {"temperature_2m": 40, "apparent_temperature": 30,
                   "wind_speed_10m": 18, "relative_humidity_2m": 70,
                   "weather_code": 3}

        assert feels_sentence(current, DAILY, NOON, _runtime()) == \
            _s("feels_wind", _runtime())

    def test_muggy_air_explains_a_warmer_apparent_temperature(self):
        current = {"temperature_2m": 88, "apparent_temperature": 96,
                   "dew_point_2m": 72, "relative_humidity_2m": 60,
                   "wind_speed_10m": 3, "weather_code": 2}

        assert feels_sentence(current, DAILY, NOON, _runtime()) == \
            _s("feels_humid", _runtime())

    def test_sunshine_explains_the_rest_of_a_warmer_reading(self):
        current = {"temperature_2m": 55, "apparent_temperature": 61,
                   "dew_point_2m": 35, "relative_humidity_2m": 45,
                   "wind_speed_10m": 3, "weather_code": 0}

        assert feels_sentence(current, DAILY, NOON, _runtime()) == \
            _s("feels_sun", _runtime())

    def test_the_sun_is_not_blamed_after_dark(self):
        current = {"temperature_2m": 55, "apparent_temperature": 61,
                   "dew_point_2m": 35, "wind_speed_10m": 3, "weather_code": 0}
        midnight = datetime(2026, 7, 15, 23, 30)

        assert feels_sentence(current, DAILY, midnight, _runtime()) == ""

    def test_dry_air_explains_a_cooler_reading_when_the_air_is_still(self):
        current = {"temperature_2m": 95, "apparent_temperature": 90,
                   "relative_humidity_2m": 8, "wind_speed_10m": 2,
                   "weather_code": 0}

        assert feels_sentence(current, DAILY, NOON, _runtime()) == \
            _s("feels_dry", _runtime())

    def test_a_breeze_outweighs_the_dryness_it_blows(self):
        # Same desert, now with 9 mph of wind: 2.8 C of cooling against the
        # dry air's 0.7, so the wind is what there is to say.
        current = {"temperature_2m": 95, "apparent_temperature": 90,
                   "relative_humidity_2m": 18, "wind_speed_10m": 9,
                   "weather_code": 0}

        assert feels_sentence(current, DAILY, NOON, _runtime()) == \
            _s("feels_wind", _runtime())

    def test_a_small_gap_says_nothing(self):
        current = {"temperature_2m": 70, "apparent_temperature": 68,
                   "wind_speed_10m": 20, "weather_code": 3}

        assert feels_sentence(current, DAILY, NOON, _runtime()) == ""

    def test_a_forecast_too_old_to_carry_humidity_says_nothing(self):
        # The arithmetic needs it; forecasts cached before it was asked for
        # do not have it.
        current = {"temperature_2m": 40, "apparent_temperature": 30,
                   "wind_speed_10m": 18, "weather_code": 3}

        assert feels_sentence(current, DAILY, NOON, _runtime()) == ""

    def test_a_light_breeze_is_enough_to_name_the_wind(self):
        # Reykjavik on a clear September afternoon: 6 mph carries 1.9 C of
        # the 5 F gap, more than the dry air's 1.5.
        current = {"temperature_2m": 52.2, "apparent_temperature": 46.7,
                   "relative_humidity_2m": 56, "dew_point_2m": 37.4,
                   "wind_speed_10m": 6.9, "weather_code": 0}

        assert feels_sentence(current, DAILY, NOON, _runtime()) == \
            _s("feels_wind", _runtime())

    def test_nothing_worth_a_degree_says_nothing(self):
        current = {"temperature_2m": 52, "apparent_temperature": 47,
                   "relative_humidity_2m": 68, "wind_speed_10m": 1,
                   "weather_code": 0}

        assert feels_sentence(current, DAILY, NOON, _runtime()) == ""

    def test_a_forecast_without_an_apparent_temperature_says_nothing(self):
        assert feels_sentence({"temperature_2m": 55}, DAILY, NOON, _runtime()) == ""

    def test_the_threshold_follows_the_unit(self):
        # Two and a half degrees is worth saying in Celsius, not in Fahrenheit.
        current = {"temperature_2m": 20, "apparent_temperature": 17.5,
                   "relative_humidity_2m": 60, "wind_speed_10m": 25,
                   "weather_code": 3}

        assert feels_sentence(current, DAILY, NOON,
                              _runtime(celsius=True, metric=True)) != ""
        assert feels_sentence(current, DAILY, NOON, _runtime()) == ""


class TestNarrativePacking:
    """Sentences share a line while there is room for them."""

    DATA = {
        "current": {"temperature_2m": 40, "apparent_temperature": 30,
                    "relative_humidity_2m": 70, "wind_speed_10m": 18,
                    "weather_code": 3},
        "daily": dict(DAILY, temperature_2m_max=[60, 62, 63]),
        "hourly": {},
    }

    def _plain(self, lines):
        import re
        return [re.sub(r"\x1b\[[0-9;]*m", "", line).strip() for line in lines]

    def test_two_sentences_share_one_wide_line(self):
        lines = narrative_lines(self.DATA, NOON, 200, _runtime())

        assert len(lines) == 1
        assert ". " in self._plain(lines)[0]

    def test_the_same_two_take_a_line_each_when_narrow(self):
        lines = narrative_lines(self.DATA, NOON, 40, _runtime())

        assert len(lines) == 2
        assert all(". " not in line for line in self._plain(lines))

    def test_every_line_is_punctuated_as_a_sentence(self):
        for width in (40, 200):
            for line in self._plain(narrative_lines(self.DATA, NOON, width,
                                                    _runtime())):
                assert line.endswith("."), line

    def test_a_shared_line_never_overruns_the_terminal(self):
        from linecast._graphics import visible_len
        for width in range(30, 140, 7):
            lines = narrative_lines(self.DATA, NOON, width, _runtime())
            shared = [line for line, text in zip(lines, self._plain(lines))
                      if text.count(".") > 1]
            assert all(visible_len(line) <= width for line in shared)

    def test_nothing_to_say_renders_nothing(self):
        assert narrative_lines({}, NOON, 100, _runtime()) == []


class TestFeelsStringsAreTranslated:
    def test_every_language_punctuates_its_own_sentences(self):
        for lang, table in _STRINGS.items():
            assert "sentence_end" in table, f"{lang} has no sentence_end"
            assert "sentence_join" in table, f"{lang} has no sentence_join"
            # The joiner carries the terminator, whatever mark that is.
            assert table["sentence_join"].startswith(table["sentence_end"])

    def test_every_language_has_its_own_feels_phrases(self):
        keys = ("feels_humid", "feels_sun", "feels_wind", "feels_dry")
        for lang, table in _STRINGS.items():
            for key in keys:
                assert key in table, f"{lang} is missing {key}"
                if lang != "en":
                    assert table[key] != _STRINGS["en"][key], \
                        f"{lang}/{key} is still English"
