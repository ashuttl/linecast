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
        current = {"temperature_2m": 95, "apparent_temperature": 88,
                   "relative_humidity_2m": 8, "wind_speed_10m": 2,
                   "weather_code": 0}

        assert feels_sentence(current, DAILY, NOON, _runtime()) == \
            _s("feels_dry", _runtime())

    def test_a_breeze_outweighs_the_dryness_it_blows(self):
        # Same desert, now with 9 mph of wind: 2.8 C of cooling against the
        # dry air's 0.7, so the wind is what there is to say.
        current = {"temperature_2m": 95, "apparent_temperature": 88,
                   "relative_humidity_2m": 18, "wind_speed_10m": 9,
                   "weather_code": 0}

        assert feels_sentence(current, DAILY, NOON, _runtime()) == \
            _s("feels_wind", _runtime())

    def test_a_small_gap_says_nothing(self):
        # Five degrees is a difference on paper, not one you would feel.
        current = {"temperature_2m": 70, "apparent_temperature": 65,
                   "relative_humidity_2m": 60, "wind_speed_10m": 20,
                   "weather_code": 3}

        assert feels_sentence(current, DAILY, NOON, _runtime()) == ""

    def test_a_forecast_too_old_to_carry_humidity_says_nothing(self):
        # The arithmetic needs it; forecasts cached before it was asked for
        # do not have it.
        current = {"temperature_2m": 40, "apparent_temperature": 30,
                   "wind_speed_10m": 18, "weather_code": 3}

        assert feels_sentence(current, DAILY, NOON, _runtime()) == ""

    def test_a_light_breeze_is_enough_to_name_the_wind(self):
        # Reykjavik on a clear September afternoon: 6 mph carries 2.2 C of
        # the 6 F gap, more than the dry air's 1.5.
        current = {"temperature_2m": 52.2, "apparent_temperature": 46.0,
                   "relative_humidity_2m": 56, "dew_point_2m": 37.4,
                   "wind_speed_10m": 6.9, "weather_code": 0}

        assert feels_sentence(current, DAILY, NOON, _runtime()) == \
            _s("feels_wind", _runtime())

    def test_nothing_worth_a_degree_says_nothing(self):
        current = {"temperature_2m": 52, "apparent_temperature": 46,
                   "relative_humidity_2m": 68, "wind_speed_10m": 1,
                   "weather_code": 0}

        assert feels_sentence(current, DAILY, NOON, _runtime()) == ""

    def test_a_forecast_without_an_apparent_temperature_says_nothing(self):
        assert feels_sentence({"temperature_2m": 55}, DAILY, NOON, _runtime()) == ""

    def test_the_threshold_follows_the_unit(self):
        # Three and a half degrees is worth saying in Celsius, not in Fahrenheit.
        current = {"temperature_2m": 20, "apparent_temperature": 16.5,
                   "relative_humidity_2m": 60, "wind_speed_10m": 25,
                   "weather_code": 3}

        assert feels_sentence(current, DAILY, NOON,
                              _runtime(celsius=True, metric=True)) != ""
        assert feels_sentence(current, DAILY, NOON, _runtime()) == ""


class TestNarrativePacking:
    """Sentences flow together across line breaks."""

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

    def test_the_same_two_flow_as_a_paragraph_when_narrow(self):
        lines = self._plain(narrative_lines(self.DATA, NOON, 40, _runtime()))

        assert lines == [
            "Today will be about the same temperature",
            "as yesterday. The wind is making it",
            "feel cooler.",
        ]

    def test_every_sentence_is_punctuated(self):
        for width in (40, 200):
            prose = " ".join(self._plain(narrative_lines(self.DATA, NOON, width,
                                                         _runtime())))
            assert prose.endswith("."), prose
            assert prose.count(".") == 2, prose

    def test_no_line_ever_overruns_the_terminal(self):
        from linecast._graphics import visible_len
        # A sentence with no room to share a line, and none to sit on one
        # either, wraps here rather than being wrapped by the terminal --
        # which would push the header off the top of the screen.
        for width in range(24, 140, 7):
            lines = narrative_lines(self.DATA, NOON, width, _runtime())
            assert all(visible_len(line) <= width for line in lines)

    def test_nothing_to_say_renders_nothing(self):
        assert narrative_lines({}, NOON, 100, _runtime()) == []

    def test_swahili_prose_keeps_noun_agreement_and_punctuation_when_wrapped(self):
        from linecast._graphics import visible_len
        data = {
            "daily": {"temperature_2m_max": [77, 77, 77]},
            "hourly": {
                "time": [f"2026-07-15T{h:02d}:00" for h in range(11, 15)],
                "weather_code": [63, 0, 51, 51],
                "precipitation_probability": [80, 0, 80, 80],
                "precipitation": [0.03, 0, 0, 0],
                "snowfall": [0, 0, 0, 0],
            },
        }
        expected = (
            "Joto la leo litakuwa karibu sawa na la jana. "
            "Manyunyu mepesi huenda yakaanza hivi karibuni. "
            "Kiasi cha mvua katika saa 24 zilizopita: 0.03″."
        )
        for width in (40, 80, 160):
            lines = narrative_lines(data, NOON, width, _runtime(lang="sw"))
            assert " ".join(self._plain(lines)) == expected
            assert all(visible_len(line) <= width for line in lines)

    def test_swahili_sentences_keep_the_24_hour_clock_on_a_12_hour_setting(self):
        # "saa 5pm" would read as eleven in the morning in Swahili time.
        from linecast._weather_sections import precipitation_sentence
        hours = range(12, 19)
        hourly = {
            "time": [f"2026-07-15T{h:02d}:00" for h in hours],
            "weather_code": [61 if h < 17 else 0 for h in hours],
            "precipitation_probability": [80 if h < 17 else 0 for h in hours],
        }
        runtime = _runtime(lang="sw", use_24h=False)
        assert precipitation_sentence(hourly, NOON, runtime) == (
            "Mvua nyepesi itaisha karibu saa 17:00")
        prose = self._plain(narrative_lines(self.DATA, NOON, 200, _runtime()))[0]

        assert prose.startswith("Today will be"), prose

    def test_a_comparison_about_tomorrow_follows_the_present_tense(self):
        evening = datetime(2026, 7, 15, 18, 0)
        prose = self._plain(narrative_lines(self.DATA, evening, 200, _runtime()))[0]

        assert prose.startswith(_s("feels_wind", _runtime())), prose
        assert "Tomorrow will be" in prose


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

class TestPrecipitationPeak:
    """A run of rain is named by what it is now, and says when it turns heavier."""

    EVENING = datetime(2026, 9, 17, 18, 10)

    @staticmethod
    def _hourly(codes, amounts=None, start=18):
        hours = range(start, start + len(codes))
        hourly = {
            "time": [f"2026-09-1{7 + h // 24}T{h % 24:02d}:00" for h in hours],
            "weather_code": codes,
            "precipitation_probability": [80 if c else 0 for c in codes],
        }
        if amounts is not None:
            hourly["precipitation"] = amounts
        return hourly

    def _sentence(self, hourly, **overrides):
        from linecast._weather_sections import precipitation_sentence
        return precipitation_sentence(hourly, self.EVENING, _runtime(**overrides))

    def test_drizzle_now_names_the_heavy_rain_to_come_and_when_it_ends(self):
        # 18:00 light drizzle through heavy rain at 23:00, dry from 02:00
        codes = [51, 51, 53, 61, 63, 65, 63, 61, 0, 0]
        amounts = [0.01, 0.01, 0.02, 0.1, 0.2, 0.34, 0.2, 0.05, 0, 0]
        assert self._sentence(self._hourly(codes, amounts)) == \
            "Light drizzle becoming heavy rain around 23h, ending overnight"
        assert self._sentence(self._hourly(codes, amounts), use_24h=False) == \
            "Light drizzle becoming heavy rain around 11pm, ending overnight"

    def test_a_run_that_keeps_its_name_reads_as_before(self):
        codes = [61, 61, 61, 61, 0]
        amounts = [0.05, 0.08, 0.06, 0.04, 0]
        assert self._sentence(self._hourly(codes, amounts)) == \
            "Light rain ending in a couple hours"

    def test_the_peak_is_the_hour_with_the_most_rain_as_the_bar_draws_it(self):
        # Heavy showers at 22:00 carry less water than the rain at 23:00
        codes = [61, 61, 61, 61, 82, 63, 63, 0]
        amounts = [0.05, 0.05, 0.05, 0.05, 0.1, 0.4, 0.2, 0]
        assert self._sentence(self._hourly(codes, amounts)) == \
            "Light rain becoming rain around 23h, ending overnight"

    def test_without_amounts_the_heaviest_code_is_the_peak(self):
        codes = [51, 53, 63, 65, 63, 0]
        assert self._sentence(self._hourly(codes)) == \
            "Light drizzle becoming heavy rain in a couple hours, ending around 23h"

    def test_a_let_up_is_not_called_a_turn(self):
        # More water later, but a lighter code: the run stays "rain"
        codes = [63, 63, 61, 61, 61, 0]
        amounts = [0.1, 0.1, 0.3, 0.3, 0.3, 0]
        assert self._sentence(self._hourly(codes, amounts)) == \
            "Rain ending around 23h"

    def test_a_run_through_the_day_can_still_turn_heavy(self):
        codes = [61] * 10 + [65] * 10 + [61] * 6
        assert self._sentence(self._hourly(codes)) == \
            "Light rain becoming heavy rain overnight, continuing through the day"

    def test_swahili_drizzle_keeps_its_noun_class_when_it_turns_to_rain(self):
        codes = [51, 53, 63, 65, 63, 0]
        assert self._sentence(self._hourly(codes), lang="sw", use_24h=True) == (
            "Manyunyu mepesi yatageuka kuwa mvua kubwa baada ya muda wa masaa mawili hivi, "
            "yataisha karibu saa 23:00")

    def test_rain_that_starts_light_says_when_it_turns_heavy(self):
        # Dry now, light rain from 21:00 building to heavy rain at 02:00
        codes = [0, 0, 0, 61, 61, 63, 63, 65, 65, 63, 0]
        amounts = [0, 0, 0, 0.02, 0.05, 0.1, 0.15, 0.3, 0.25, 0.1, 0]
        assert self._sentence(self._hourly(codes, amounts)) == \
            "Light rain likely starting in a couple hours, becoming heavy rain overnight"

    def test_rain_that_starts_and_stays_light_reads_as_before(self):
        codes = [0, 0, 0, 0, 61, 61, 61, 0]
        amounts = [0, 0, 0, 0, 0.05, 0.05, 0.05, 0]
        assert self._sentence(self._hourly(codes, amounts)) == \
            "Light rain likely starting in a couple hours"

    def test_swahili_drizzle_that_starts_later_keeps_its_noun_class_when_it_turns(self):
        codes = [0, 0, 0, 0, 51, 53, 65, 0]
        assert self._sentence(self._hourly(codes), lang="sw", use_24h=True) == (
            "Manyunyu mepesi huenda yakaanza baada ya muda wa masaa mawili hivi "
            "na yatageuka kuwa mvua kubwa usiku")
