"""The prose lines under the weather graph: what they say, and how they pack."""

import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from linecast._i18n import VARIANTS
from linecast._runtime import WeatherRuntime
from linecast.weather.i18n import _STRINGS, _s
from linecast.weather.sections import feels_sentence, narrative_lines

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
            _s("feels_wind_cold", _runtime())

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

    def test_cold_air_feels_colder_and_mild_air_cooler(self):
        wind = {"relative_humidity_2m": 70, "wind_speed_10m": 18, "weather_code": 3}
        cold = dict(wind, temperature_2m=40, apparent_temperature=30)
        mild = dict(wind, temperature_2m=62, apparent_temperature=55)
        assert feels_sentence(cold, DAILY, NOON, _runtime()) == \
            "The wind is making it feel colder"
        assert feels_sentence(mild, DAILY, NOON, _runtime()) == \
            "The wind is making it feel cooler"
        # Languages whose word for it means cool say cold in cold air too
        assert feels_sentence(cold, DAILY, NOON, _runtime(lang="de")) == \
            "Durch den Wind fühlt es sich kälter an"
        assert feels_sentence(cold, DAILY, NOON, _runtime(lang="ru")) == \
            "Из-за ветра ощущается холоднее"
        assert feels_sentence(mild, DAILY, NOON, _runtime(lang="ru")) == \
            "Из-за ветра ощущается прохладнее"

    def test_cold_damp_air_is_not_called_dry(self):
        # Longyearbyen at 1 C and 91% humidity: the formula's humidity term
        # is negative in any cold air, but no one there calls it dry.  The
        # 10 km/h wind is what there is to say.
        current = {"temperature_2m": 1.0, "apparent_temperature": -2.7,
                   "relative_humidity_2m": 91, "dew_point_2m": -0.4,
                   "wind_speed_10m": 10.0, "weather_code": 3}

        assert feels_sentence(current, DAILY, NOON,
                              _runtime(celsius=True, metric=True)) == \
            _s("feels_wind_cold", _runtime())

    def test_cold_damp_still_air_says_nothing(self):
        # The same air without the wind: nothing is holding a degree of the
        # gap that a person would name.
        current = {"temperature_2m": 1.0, "apparent_temperature": -2.3,
                   "relative_humidity_2m": 91, "dew_point_2m": -0.4,
                   "wind_speed_10m": 2.0, "weather_code": 3}

        assert feels_sentence(current, DAILY, NOON,
                              _runtime(celsius=True, metric=True)) == ""

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
            "The wind is making it feel colder.",
            "Today's high will be about the same",
            "as yesterday's.",
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
                "precipitation_probability": [70, 0, 70, 70],
                "precipitation": [0.3, 0, 0, 0],
                "snowfall": [0, 0, 0, 0],
            },
        }
        expected = (
            "Kiwango cha juu cha joto leo kitakuwa karibu sawa na cha jana. "
            "Manyunyu mepesi yanatarajiwa kuanza baada ya muda mfupi. "
            "Katika saa 24\u00a0zilizopita kumenyesha mvua ya 0.30″."
        )
        for width in (40, 80, 160):
            lines = narrative_lines(data, NOON, width, _runtime(lang="sw"))
            assert " ".join(self._plain(lines)) == expected
            assert all(visible_len(line) <= width for line in lines)

    def test_swahili_sentences_tell_the_hour_in_swahili_time(self):
        # "saa 5pm" would read as eleven in the morning in Swahili time;
        # five in the afternoon is the eleventh hour of the day.
        from linecast.weather.sections import precipitation_sentence
        hours = range(12, 19)
        hourly = {
            "time": [f"2026-07-15T{h:02d}:00" for h in hours],
            "weather_code": [61 if h < 17 else 0 for h in hours],
            "precipitation_probability": [80 if h < 17 else 0 for h in hours],
        }
        runtime = _runtime(lang="sw", use_24h=False)
        assert precipitation_sentence(hourly, NOON, runtime) == (
            "Mvua nyepesi itaisha karibu saa kumi na moja jioni")

    def test_the_present_tense_opens_the_morning(self):
        # After "Today's high", "the wind is making it feel colder" would
        # read as though it were about the high
        prose = self._plain(narrative_lines(self.DATA, NOON, 200, _runtime()))[0]

        assert prose.startswith(_s("feels_wind_cold", _runtime())), prose

    def test_a_comparison_about_tomorrow_follows_the_present_tense(self):
        evening = datetime(2026, 7, 15, 18, 0)
        prose = self._plain(narrative_lines(self.DATA, evening, 200, _runtime()))[0]

        assert prose.startswith(_s("feels_wind_cold", _runtime())), prose
        assert "Tomorrow's high will be" in prose


class TestFeelsStringsAreTranslated:
    def test_every_language_punctuates_its_own_sentences(self):
        for lang, table in _STRINGS.items():
            if lang in VARIANTS:  # a regional variant reads its base's
                continue
            assert "sentence_end" in table, f"{lang} has no sentence_end"
            assert "sentence_join" in table, f"{lang} has no sentence_join"
            # The joiner carries the terminator, whatever mark that is.
            assert table["sentence_join"].startswith(table["sentence_end"])

    def test_every_language_has_its_own_feels_phrases(self):
        keys = ("feels_humid", "feels_sun", "feels_wind", "feels_dry")
        for lang, table in _STRINGS.items():
            if lang in VARIANTS:
                continue
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
        from linecast.weather.sections import precipitation_sentence
        return precipitation_sentence(hourly, self.EVENING, _runtime(**overrides))

    def test_drizzle_now_names_the_heavy_rain_to_come_and_when_it_ends(self):
        # 18:00 light drizzle through heavy rain at 23:00, dry from 02:00
        codes = [51, 51, 53, 61, 63, 65, 63, 61, 0, 0]
        amounts = [0.01, 0.01, 0.02, 0.1, 0.2, 0.34, 0.2, 0.05, 0, 0]
        assert self._sentence(self._hourly(codes, amounts)) == \
            "Light drizzle turning to heavy rain around 23:00 and ending overnight"
        assert self._sentence(self._hourly(codes, amounts), use_24h=False) == \
            "Light drizzle turning to heavy rain around 11pm and ending overnight"

    def test_japanese_says_the_same_rain_gets_harder_and_another_kind_turns(self):
        # Rain at 18:00 turning heavy at 21:00 and over by 02:00 is the
        # rain strengthening, not "rain becoming heavy rain"; drizzle
        # turning to rain is still a turn
        codes = [63, 63, 63, 65, 65, 65, 63, 61, 0, 0]
        amounts = [0.1, 0.1, 0.1, 0.3, 0.34, 0.3, 0.2, 0.05, 0, 0]
        assert self._sentence(self._hourly(codes, amounts), lang="ja") == \
            "雨は数時間後に強まり、夜のうちにやむでしょう"
        codes = [51, 51, 53, 61, 63, 65, 63, 61, 0, 0]
        amounts = [0.01, 0.01, 0.02, 0.1, 0.2, 0.34, 0.2, 0.05, 0, 0]
        assert self._sentence(self._hourly(codes, amounts), lang="ja") == \
            "霧雨は23時頃に強い雨に変わり、夜のうちにやむでしょう"

    def test_rain_that_freezes_has_not_just_turned_heavy(self):
        codes = [61, 61, 61, 67, 67, 67, 61, 61, 0, 0]
        amounts = [0.1, 0.1, 0.1, 0.3, 0.34, 0.3, 0.2, 0.05, 0, 0]
        assert self._sentence(self._hourly(codes, amounts)) == \
            "Light rain turning to freezing rain in a couple hours and ending overnight"

    def test_midday_is_noon(self):
        codes = [0, 0, 0, 0, 0, 61, 61, 61, 0]
        hourly = self._hourly(codes, start=7)
        from linecast.weather.sections import precipitation_sentence
        assert precipitation_sentence(hourly, datetime(2026, 9, 17, 7, 10), _runtime()) == \
            "Light rain starting around noon"

    def test_a_run_that_keeps_its_name_reads_as_before(self):
        codes = [61, 61, 61, 61, 0]
        amounts = [0.05, 0.08, 0.06, 0.04, 0]
        assert self._sentence(self._hourly(codes, amounts)) == \
            "Light rain ending in a couple hours"

    def test_the_peak_is_the_hour_with_the_most_rain_as_the_bar_draws_it(self):
        # Heavy showers at 22:00 carry less water than the heavy rain at 23:00
        codes = [61, 61, 61, 61, 82, 65, 63, 0]
        amounts = [0.05, 0.05, 0.05, 0.05, 0.1, 0.4, 0.2, 0]
        assert self._sentence(self._hourly(codes, amounts)) == \
            "Light rain turning heavy around 23:00 and ending overnight"

    def test_a_shade_of_the_same_thing_is_not_a_turn(self):
        # Light rain to rain, light drizzle to drizzle: nobody says it
        codes = [61, 61, 63, 63, 63, 0]
        amounts = [0.05, 0.05, 0.15, 0.15, 0.15, 0]
        assert self._sentence(self._hourly(codes, amounts)) == \
            "Light rain ending around 23:00"
        codes = [51, 51, 53, 55, 55, 0]
        assert self._sentence(self._hourly(codes)) == \
            "Light drizzle ending around 23:00"

    def test_a_turn_to_another_kind_is_always_a_turn(self):
        # Drizzle to light rain is only one step up, but it is a change
        codes = [51, 51, 61, 61, 61, 0]
        assert self._sentence(self._hourly(codes)) == \
            "Light drizzle turning to light rain in about an hour and ending around 23:00"

    def test_a_turn_the_language_cannot_name_is_not_said(self):
        # Japanese calls every drizzle 霧雨, and thunder is thunder
        codes = [51, 51, 55, 55, 55, 0]
        assert self._sentence(self._hourly(codes), lang="ja") == \
            "霧雨は23時頃にやむでしょう"
        codes = [95, 95, 99, 99, 99, 0]
        assert self._sentence(self._hourly(codes)) == \
            "Thunderstorms ending around 23:00"

    def test_without_amounts_the_heaviest_code_is_the_peak(self):
        codes = [51, 53, 63, 65, 63, 0]
        assert self._sentence(self._hourly(codes)) == \
            "Light drizzle turning to heavy rain in a couple hours and ending around 23:00"

    def test_a_let_up_is_not_called_a_turn(self):
        # More water later, but a lighter code: the run stays "rain"
        codes = [63, 63, 61, 61, 61, 0]
        amounts = [0.1, 0.1, 0.3, 0.3, 0.3, 0]
        assert self._sentence(self._hourly(codes, amounts)) == \
            "Rain ending around 23:00"

    def test_thunder_behind_a_wetter_hour_of_showers_is_still_named(self):
        # Athens: showers from 20:00 with thunder at 23:00, and the
        # wettest hour of the lot a plain shower after midnight
        codes = [0, 0, 80, 80, 80, 95, 80, 95, 0]
        amounts = [0, 0, 0.1, 0.8, 0.6, 1.2, 2.1, 1.2, 0]
        assert self._sentence(self._hourly(codes, amounts)) == \
            "Light showers starting in about an hour, then thunderstorms around 23:00"
        assert self._sentence(self._hourly(codes, amounts), lang="ja") == \
            "約1時間後に弱いにわか雨、23時頃に雷雨となるでしょう"

    def test_thunder_at_the_end_of_a_long_rain_is_named(self):
        # Moscow: light rain all evening, 4.2mm of plain rain at 23:00 --
        # the same rain, harder, and so no turn -- and thunder behind it
        codes = [0, 61, 61, 61, 61, 63, 61, 95, 61, 0]
        amounts = [0, 0.1, 0.1, 0.3, 0.8, 4.2, 2.2, 2.7, 0.8, 0]
        assert self._sentence(self._hourly(codes, amounts)) == \
            "Light rain starting soon, then thunderstorms overnight"

    def test_drizzle_behind_showers_is_a_let_up_not_a_turn(self):
        # Mumbai: showers now, heavy drizzle after them.  Drizzle ranks
        # a step above a light shower and is still the weather easing.
        codes = [80, 81, 55, 53, 55, 51, 0, 0]
        amounts = [1.8, 2.5, 1.1, 0.7, 1.1, 0.1, 0, 0]
        assert self._sentence(self._hourly(codes, amounts)) == "Light showers ending overnight"

    def test_a_run_through_the_day_can_still_turn_heavy(self):
        codes = [61] * 10 + [65] * 10 + [61] * 6
        assert self._sentence(self._hourly(codes)) == \
            "Light rain turning heavy overnight and lasting through the day"

    def test_swahili_drizzle_keeps_its_noun_class_when_it_turns_to_rain(self):
        codes = [51, 53, 63, 65, 63, 0]
        assert self._sentence(self._hourly(codes), lang="sw", use_24h=True) == (
            "Manyunyu mepesi yatageuka kuwa mvua kubwa baada ya muda wa saa mbili au tatu "
            "na kuisha karibu saa tano usiku")

    def test_rain_that_starts_light_says_when_it_turns_heavy(self):
        # Dry now, light rain from 21:00 building to heavy rain at 02:00
        codes = [0, 0, 0, 61, 61, 63, 63, 65, 65, 63, 0]
        amounts = [0, 0, 0, 0.02, 0.05, 0.1, 0.15, 0.3, 0.25, 0.1, 0]
        assert self._sentence(self._hourly(codes, amounts)) == \
            "Light rain starting in a couple hours, turning heavy overnight"

    def test_rain_that_starts_and_stays_light_reads_as_before(self):
        codes = [0, 0, 0, 0, 61, 61, 61, 0]
        amounts = [0, 0, 0, 0, 0.05, 0.05, 0.05, 0]
        assert self._sentence(self._hourly(codes, amounts)) == \
            "Light rain starting in a couple hours"

    def test_swahili_drizzle_that_starts_later_keeps_its_noun_class_when_it_turns(self):
        codes = [0, 0, 0, 0, 51, 53, 65, 0]
        # One hour of heavy rain at the end of the run is not a turn, and
        # eighty percent needs no "huenda"
        assert self._sentence(self._hourly(codes), lang="sw", use_24h=True) == (
            "Manyunyu mepesi yataanza baada ya muda wa saa mbili au tatu")

    def test_a_turn_needs_two_hours_unless_the_day_cuts_it_off(self):
        # Heavy rain for the run's last hour goes unmentioned...
        codes = [61, 61, 61, 65, 0]
        assert self._sentence(self._hourly(codes)) == "Light rain ending in a couple hours"
        # ...unless the run only ends because the window does
        codes = [61] * 23 + [65]
        assert self._sentence(self._hourly(codes)) == \
            "Light rain turning heavy tomorrow evening and lasting through the day"

    def test_a_turn_already_here_is_what_is_falling(self):
        # Santiago: drizzle now, showers from the next hour, dry by three
        codes = [53, 81, 81, 81, 0]
        assert self._sentence(self._hourly(codes)) == "Showers ending in a couple hours"

    def test_an_hour_of_drizzle_at_the_edge_of_a_storm_is_the_storm(self):
        # Lagos: drizzle at eleven, thunder from noon
        codes = [0, 0, 0, 0, 51, 95, 95, 95, 0]
        assert self._sentence(self._hourly(codes)) == "Thunderstorms starting around 23:00"
        assert self._sentence(self._hourly(codes), lang="ja") == "23時頃に雷雨になるでしょう"


class TestHedges:
    """The word before "starting" follows the odds."""

    EVENING = datetime(2026, 9, 17, 18, 10)

    def _sentence(self, prob, **overrides):
        from linecast.weather.sections import precipitation_sentence
        hours = range(18, 24)
        hourly = {
            "time": [f"2026-09-17T{h:02d}:00" for h in hours],
            "weather_code": [0, 0, 0, 61, 61, 61],
            "precipitation_probability": [0, 0, 0, prob, prob, prob],
        }
        return precipitation_sentence(hourly, self.EVENING, _runtime(**overrides))

    def test_a_chance_is_a_chance(self):
        assert self._sentence(40) == "A chance of light rain in a couple hours"
        assert (self._sentence(40, lang="ja", use_24h=True)
                == "数時間後に弱い雨になる可能性があります")

    def test_likely_is_likely(self):
        assert self._sentence(70) == "Light rain likely starting in a couple hours"
        assert self._sentence(70, lang="ja", use_24h=True) == "数時間後に弱い雨となる見込みです"

    def test_eighty_percent_needs_no_hedge(self):
        assert self._sentence(90) == "Light rain starting in a couple hours"
        assert self._sentence(90, lang="ja", use_24h=True) == "数時間後に弱い雨になるでしょう"

    def test_a_language_without_the_forms_keeps_its_one_hedge(self, monkeypatch):
        # A language whose table has not been given the graded forms
        # says its one hedge for every grade, never English
        import linecast.weather.i18n as i18n
        bare = {k: v for k, v in _STRINGS["sw"].items()
                if not k.startswith(("starting_chance", "starting_sure"))}
        monkeypatch.setitem(i18n._STRINGS, "sw", bare)
        for prob in (40, 70, 90):
            assert self._sentence(prob, lang="sw", use_24h=True) == \
                "Mvua nyepesi inatarajiwa kuanza baada ya muda wa saa mbili au tatu"

    def test_the_hedge_follows_the_best_hour_of_the_run(self):
        from linecast.weather.sections import precipitation_sentence
        hourly = {
            "time": [f"2026-09-17T{h:02d}:00" for h in range(18, 24)],
            "weather_code": [0, 0, 0, 61, 61, 61],
            "precipitation_probability": [0, 0, 0, 35, 60, 85],
        }
        assert precipitation_sentence(hourly, self.EVENING, _runtime()) == \
            "Light rain starting in a couple hours"


class TestWhichRunLeads:
    """Only rain worth planning for leads: an early chance waits its turn."""

    MORNING = datetime(2026, 9, 22, 9, 26)

    # Bangkok: one 44% hour of drizzle before lunch, and the storm the
    # day is really about at five
    CHANCE_THEN_STORM = ([3, 3, 51, 3, 3, 3, 3, 3, 95, 95, 95, 3],
                         [10, 10, 44, 10, 10, 10, 10, 10, 84, 84, 82, 10])

    def _sentence(self, codes, probs, **overrides):
        from linecast.weather.sections import precipitation_sentence
        hours = [self.MORNING.replace(minute=0) + timedelta(hours=k)
                 for k in range(len(codes))]
        hourly = {"time": [h.isoformat(timespec="minutes") for h in hours],
                  "weather_code": codes, "precipitation_probability": probs}
        return precipitation_sentence(hourly, self.MORNING, _runtime(**overrides))

    def test_a_chance_waits_when_the_real_weather_comes_later(self):
        codes, probs = self.CHANCE_THEN_STORM
        assert self._sentence(codes, probs) == "Thunderstorms starting around 17:00"
        assert self._sentence(codes, probs, lang="ja") == "17時頃に雷雨になるでしょう"

    def test_a_chance_leads_when_nothing_surer_follows_it(self):
        codes, probs = self.CHANCE_THEN_STORM
        assert self._sentence(codes, probs[:8] + [50, 50, 50, 10]) == \
            "A chance of light drizzle in about an hour"

    def test_the_first_run_worth_planning_for_leads(self):
        # Not the wettest, not the surest: the first one a person would
        # take an umbrella for
        codes = [3, 3, 61, 61, 3, 3, 3, 3, 63, 63, 63, 3]
        probs = [10, 10, 65, 65, 10, 10, 10, 10, 90, 90, 90, 10]
        assert self._sentence(codes, probs) == "Light rain likely starting in about an hour"


class TestWhatIsFallingNow:
    """The prose cannot say rain has yet to start when the header says it has."""

    HONG_KONG = datetime(2026, 9, 22, 10, 26)
    # Drizzle into the afternoon, at odds that open at exactly thirty percent
    CODES = [51, 51, 51, 51, 51, 51, 51, 2, 2]
    PROBS = [30, 35, 47, 63, 71, 64, 50, 35, 22]

    def _hourly(self, codes, probs, start=None):
        start = start or self.HONG_KONG.replace(minute=0)
        hours = [start + timedelta(hours=k) for k in range(len(codes))]
        return {"time": [h.isoformat(timespec="minutes") for h in hours],
                "weather_code": codes, "precipitation_probability": probs}

    def _sentence(self, hourly, now=None, current=None, **overrides):
        from linecast.weather.sections import precipitation_sentence
        return precipitation_sentence(hourly, now or self.HONG_KONG,
                                      _runtime(**overrides), current=current)

    def test_drizzle_falling_now_is_drizzle_ending(self):
        hourly = self._hourly(self.CODES, self.PROBS)
        assert self._sentence(hourly, current={"weather_code": 51}) == \
            "Light drizzle ending around 17:00"
        assert self._sentence(hourly, current={"weather_code": 51}, lang="ja") == \
            "霧雨は17時頃にやむでしょう"

    def test_the_hours_own_odds_rule_when_nothing_is_falling(self):
        hourly = self._hourly(self.CODES, self.PROBS)
        assert self._sentence(hourly) == "Light drizzle likely starting soon"
        assert self._sentence(hourly, current={"weather_code": 3}) == \
            "Light drizzle likely starting soon"

    def test_drizzle_the_hours_have_all_but_given_up_on(self):
        # Cape Town before dawn: five percent, and it is falling
        cape_town = datetime(2026, 9, 22, 4, 26)
        hourly = self._hourly([51, 51, 1, 1, 0, 0], [5, 6, 5, 2, 0, 0],
                              start=cape_town.replace(minute=0))
        assert self._sentence(hourly, now=cape_town, current={"weather_code": 51}) == \
            "Light drizzle ending soon"
        assert self._sentence(hourly, now=cape_town) == ""

    def test_the_paragraph_is_told_what_is_falling(self):
        import re
        hourly = self._hourly(self.CODES + [2] * 16, self.PROBS + [0] * 16)
        data = {"hourly": hourly, "daily": DAILY, "current": {"weather_code": 51}}
        prose = " ".join(re.sub(r"\x1b\[[0-9;]*m", "", row)
                         for row in narrative_lines(data, self.HONG_KONG, 200, _runtime()))
        assert prose == "Light drizzle ending around 17:00."


class TestTheClockInTheSentence:
    """Night is night, tomorrow is said once, and a lull is not an ending."""

    def _hourly(self, codes, start):
        hours = [start + timedelta(hours=k) for k in range(len(codes))]
        return {
            "time": [h.isoformat(timespec="minutes") for h in hours],
            "weather_code": codes,
            "precipitation_probability": [90 if c else 0 for c in codes],
        }

    def test_rain_at_night_continues_through_the_night(self):
        from linecast.weather.sections import precipitation_sentence
        late = datetime(2026, 7, 15, 22, 5)
        hourly = self._hourly([63] * 26, late.replace(minute=0))
        assert precipitation_sentence(hourly, late, _runtime(), daily=DAILY) == \
            "Rain continuing through the night"
        assert precipitation_sentence(hourly, late, _runtime(lang="ja"), daily=DAILY) == \
            "雨は一晩中続くでしょう"
        hourly = self._hourly([63] * 26, NOON)
        assert precipitation_sentence(hourly, NOON, _runtime(), daily=DAILY) == \
            "Rain continuing through the day"

    def test_tomorrow_is_said_once(self):
        from linecast.weather.sections import precipitation_sentence
        late = datetime(2026, 7, 15, 21, 0)
        codes = [0] * 17 + [61, 61, 61, 61, 65, 65, 65, 0]
        hourly = self._hourly(codes, late)
        assert precipitation_sentence(hourly, late, _runtime()) == \
            "Light rain starting tomorrow afternoon, turning heavy in the evening"
        # The same rain, harder, is said as such in Japanese; a turn to
        # another kind (drizzle to rain, below) keeps "となり"
        assert precipitation_sentence(hourly, late, _runtime(lang="ja")) == \
            "明日の午後に弱い雨になり、夕方に強まるでしょう"

    def test_early_tomorrow_morning_is_followed_by_later_in_the_morning(self):
        # Chicago at nine at night: drizzle turning to rain before dawn,
        # over by mid-morning
        from linecast.weather.sections import precipitation_sentence
        night = datetime(2026, 7, 15, 21, 0)
        codes = [51, 51, 51, 51, 51, 51, 51, 51, 51, 63, 63, 63, 63, 0, 0]
        hourly = self._hourly(codes, night)
        hourly["precipitation"] = [0.01] * 9 + [0.1, 0.15, 0.15, 0.1, 0, 0]
        assert precipitation_sentence(hourly, night, _runtime()) == \
            "Light drizzle turning to rain early tomorrow morning and ending later in the morning"
        assert precipitation_sentence(hourly, night, _runtime(lang="ja")) == \
            "霧雨は明日の早朝に雨に変わり、午前中にやむでしょう"

    def test_a_turn_inside_the_morning_is_later_in_the_morning(self):
        # Miami at half past ten at night: drizzle at eight tomorrow,
        # showers from eleven.  Both are before noon, so the turn is
        # later in that morning, not the morning over again.
        from linecast.weather.sections import precipitation_sentence
        night = datetime(2026, 7, 15, 22, 26)
        codes = [0] * 10 + [51, 51, 51, 80, 80, 80, 0]
        hourly = self._hourly(codes, night.replace(minute=0))
        hourly["precipitation"] = [0] * 10 + [0.01, 0.01, 0.01, 0.2, 0.25, 0.15, 0]
        assert precipitation_sentence(hourly, night, _runtime()) == \
            "Light drizzle starting tomorrow morning, then light showers later in the morning"
        assert precipitation_sentence(hourly, night, _runtime(lang="ja")) == \
            "明日の朝に霧雨、午前中に弱いにわか雨となるでしょう"

    def test_a_turn_inside_the_afternoon_is_later_in_the_afternoon(self):
        # The same again after noon: drizzle at one tomorrow, rain from
        # four
        from linecast.weather.sections import precipitation_sentence
        night = datetime(2026, 7, 15, 22, 26)
        codes = [0] * 15 + [51, 51, 51, 63, 63, 0]
        hourly = self._hourly(codes, night.replace(minute=0))
        hourly["precipitation"] = [0] * 15 + [0.01, 0.01, 0.01, 0.2, 0.25, 0]
        assert precipitation_sentence(hourly, night, _runtime()) == \
            "Light drizzle starting tomorrow afternoon, then rain later in the afternoon"
        assert precipitation_sentence(hourly, night, _runtime(lang="de")) == \
            "Morgen Nachmittag leichter Nieselregen, im Laufe des Nachmittags Regen"

    def test_in_the_small_hours_the_coming_night_is_tonight(self):
        # Reykjavík at two in the morning: drizzle due at one the next
        # night.  A forecast read before dawn calls the night this
        # evening leads into "tonight", the way one issued at four does;
        # "tomorrow night" would be the night after it, a day late.
        from linecast.weather.sections import precipitation_sentence
        small = datetime(2026, 7, 15, 2, 30)
        codes = [0] * 23 + [51, 51]
        assert precipitation_sentence(self._hourly(codes, small), small, _runtime()) == \
            "Light drizzle starting tonight"
        assert precipitation_sentence(self._hourly(codes, small), small, _runtime(lang="ja")) == \
            "今夜霧雨になるでしょう"

    def test_the_freeze_and_the_snow_are_one_night(self):
        # Longyearbyen at half past four in the morning: the freeze at
        # ten tonight and the snow at one are three hours of the same
        # night, and the paragraph calls them by the same name
        import re
        dawn = datetime(2026, 9, 22, 4, 26)
        codes = [0] * 21 + [71, 71, 71, 0]
        hourly = self._hourly(codes, dawn.replace(minute=0))
        hourly["temperature_2m"] = [35] * 16 + [33] * 2 + [30] * 2 + [31] * 5
        data = {"hourly": hourly, "current": {"temperature_2m": 36},
                "daily": {"sunrise": ["2026-09-22T05:40"], "sunset": ["2026-09-22T19:55"],
                          "temperature_2m_max": [40]}}
        prose = " ".join(re.sub(r"\x1b\[[0-9;]*m", "", row)
                         for row in narrative_lines(data, dawn, 200, _runtime()))
        assert prose == "Below freezing tonight, down to 30°. Light snow starting then."

    def test_the_second_sentence_about_the_night_says_so_in_its_own_words(self):
        # The same night again, in languages that put the time in
        # different places: first in German and Polish, after the verb in
        # Russian, last in French, before the verb in Japanese.  Each
        # says "at that time" its own way rather than "tonight" twice.
        import re
        dawn = datetime(2026, 9, 22, 4, 26)
        codes = [0] * 21 + [71, 71, 71, 0]
        hourly = self._hourly(codes, dawn.replace(minute=0))
        hourly["temperature_2m"] = [2] * 16 + [1] * 2 + [-2] * 2 + [-1] * 5
        hourly["precipitation_probability"] = [70 if c else 0 for c in codes]
        data = {"hourly": hourly, "current": {"temperature_2m": 2},
                "daily": {"sunrise": ["2026-09-22T05:40"], "sunset": ["2026-09-22T19:55"],
                          "temperature_2m_max": [4]}}

        def prose(lang):
            rt = _runtime(lang=lang, celsius=True, metric=True)
            return " ".join(re.sub(r"\x1b\[[0-9;]*m", "", row)
                            for row in narrative_lines(data, dawn, 400, rt))

        assert prose("en") == "Below freezing tonight, down to −2°. Light snow likely then."
        assert prose("de") == ("Heute Nacht Frost bis −2\u00a0Grad. "
                               "Dabei wahrscheinlich leichter Schneefall.")
        assert prose("pl") == ("Dziś w nocy temperatura spadnie poniżej zera, do −2\u00a0stopni. "
                               "Wtedy też prawdopodobnie pojawi się słaby śnieg.")
        assert prose("ru") == ("Сегодня ночью температура опустится ниже нуля, "
                               "до −2\u00a0градусов. "
                               "Небольшой снег, вероятно, начнётся тогда же.")
        assert prose("fr") == "Gelées cette nuit, jusqu'à −2°. Neige légère probable également."
        assert prose("ja") == ("今夜は氷点下まで冷え込み、最低−2度となるでしょう。"
                               "同じ頃弱い雪となる見込みです。")
        # A language without the word names the night again
        assert "คืนนี้" in prose("th").rsplit("คาดว่า", 1)[-1]

        # Snow that turns heavy later in the same night says the word once
        codes[21:25] = [71, 71, 71, 75]
        hourly["weather_code"] = codes + [0]
        hourly["time"].append((dawn.replace(minute=0) + timedelta(hours=25))
                              .isoformat(timespec="minutes"))
        hourly["precipitation_probability"] = [70 if c else 0 for c in hourly["weather_code"]]
        assert prose("en") == ("Below freezing tonight, down to −2°. "
                               "Light snow likely then, turning heavy later.")
        assert prose("de").count("abei") == 1, prose("de")

    def test_a_dry_hour_inside_rain_is_a_lull(self):
        from linecast.weather.sections import precipitation_sentence
        hourly = self._hourly([63, 0, 63, 63, 0, 0], NOON)
        assert precipitation_sentence(hourly, NOON, _runtime()) == \
            "Rain ending around 16:00"

    def test_more_rain_after_a_break(self):
        import re
        hourly = self._hourly([63, 63, 0, 0, 0, 0, 0, 63, 63, 0], NOON)
        data = {"daily": DAILY, "hourly": hourly}
        prose = " ".join(re.sub(r"\x1b\[[0-9;]*m", "", row)
                         for row in narrative_lines(data, NOON, 200, _runtime()))
        assert prose == "Rain ending in about an hour. More rain around 19:00."
        prose = " ".join(re.sub(r"\x1b\[[0-9;]*m", "", row)
                         for row in narrative_lines(data, NOON, 200, _runtime(lang="ja")))
        assert prose == "雨は約1時間後にやむでしょう。19時頃には再び雨となる見込みです。"


class TestMoreToSay:
    """The sentences drawn from the rest of the forecast."""

    @staticmethod
    def _hours(start, n):
        return [start + timedelta(hours=k) for k in range(n)]

    def _hourly(self, start, n, **series):
        hourly = {"time": [h.isoformat(timespec="minutes") for h in self._hours(start, n)]}
        hourly.update(series)
        return hourly

    def test_snow_on_the_ground_by_morning(self):
        from linecast.weather.sections import snow_total_sentence
        evening = datetime(2026, 7, 15, 20, 0)
        codes = [0, 0, 71, 73, 73, 73, 71, 0, 0]
        hourly = self._hourly(evening, len(codes), weather_code=codes,
                              precipitation_probability=[90 if c else 0 for c in codes],
                              snowfall=[0, 0, 1.0, 2.0, 2.5, 1.5, 0.6, 0, 0])
        assert snow_total_sentence(hourly, evening, _runtime()) == \
            "About 3\u00a0inches of snow by tomorrow morning"
        assert snow_total_sentence(hourly, evening, _runtime(metric=True, celsius=True)) == \
            "About 8\u00a0cm of snow by tomorrow morning"
        assert snow_total_sentence(hourly, evening, _runtime(lang="ja", metric=True)) == \
            "明日の朝には約8cmの積雪となる見込みです"
        hourly["snowfall"] = [0, 0, 0.3, 0.4, 0.3, 0.2, 0.1, 0, 0]
        # "About" and a decimal do not go together
        assert snow_total_sentence(hourly, evening, _runtime(metric=True, celsius=True)) == \
            "About 1\u00a0cm of snow by tomorrow morning"

    def test_a_dusting_is_not_worth_a_sentence(self):
        from linecast.weather.sections import snow_total_sentence
        codes = [71, 71, 0]
        hourly = self._hourly(NOON, 3, weather_code=codes,
                              precipitation_probability=[90, 90, 0], snowfall=[0.3, 0.4, 0])
        assert snow_total_sentence(hourly, NOON, _runtime()) == ""

    def test_the_sky_clears(self):
        from linecast.weather.sections import sky_sentence
        cover = [90, 90, 90, 90, 10, 10, 10, 10, 10, 10, 10, 10]
        hourly = self._hourly(NOON, len(cover), cloud_cover=cover)
        assert sky_sentence(hourly, DAILY, NOON, _runtime()) == "Clearing around 16:00"
        assert (sky_sentence(hourly, DAILY, NOON, _runtime(lang="ja"))
                == "16時頃に晴れてくる見込みです")

    def test_a_brief_clearing_is_not_clearing(self):
        # Los Angeles: the marine layer lifts for the evening and rolls
        # back in at night
        from linecast.weather.sections import sky_sentence
        cover = [90, 90, 90, 90, 90, 90, 10, 10, 10, 90, 90, 90, 90, 90]
        hourly = self._hourly(NOON, len(cover), cloud_cover=cover)
        assert sky_sentence(hourly, DAILY, NOON, _runtime()) == ""

    def test_the_sky_clouds_over_unless_rain_already_says_so(self):
        from linecast.weather.sections import sky_sentence
        cover = [10, 10, 10, 10, 90, 90, 90, 90, 90, 90, 90, 90]
        hourly = self._hourly(NOON, len(cover), cloud_cover=cover)
        assert sky_sentence(hourly, DAILY, NOON, _runtime()) == "Clouding over around 16:00"
        assert sky_sentence(hourly, DAILY, NOON, _runtime(), precip_kind="starting") == ""

    def test_a_mixed_sky_says_nothing(self):
        from linecast.weather.sections import sky_sentence
        cover = [50, 50, 50, 50, 90, 90, 90, 90, 90, 90, 90, 90]
        hourly = self._hourly(NOON, len(cover), cloud_cover=cover)
        assert sky_sentence(hourly, DAILY, NOON, _runtime()) == ""

    def test_a_change_after_dark_is_named_at_the_hour_it_happens(self):
        # Seattle at five: a clear evening, and the sky shuts at ten.
        # Someone hoping to see stars is owed that hour, not the morning.
        from linecast.weather.sections import sky_sentence
        evening = datetime(2026, 7, 15, 17, 0)
        cover = [0, 0, 0, 0, 20] + [100] * 20
        hourly = self._hourly(evening, len(cover), cloud_cover=cover)
        assert sky_sentence(hourly, DAILY, evening, _runtime()) == "Clouding over around 22:00"

    def test_a_night_change_that_is_gone_by_morning_says_nothing(self):
        # Cloud that rolls in after dark and burns off at breakfast is
        # not clouding over: the lasting rule catches it.
        from linecast.weather.sections import sky_sentence
        evening = datetime(2026, 7, 15, 17, 0)
        cover = [0] * 5 + [100] * 8 + [0] * 12
        hourly = self._hourly(evening, len(cover), cloud_cover=cover)
        assert sky_sentence(hourly, DAILY, evening, _runtime()) == ""

    def test_the_hour_named_is_the_hour_the_sky_turns(self):
        # Rome at dusk: half cloud at six, the sky properly open at
        # seven.  The three-hour mean has turned by six; the sky has not.
        from linecast.weather.sections import sky_sentence
        afternoon = datetime(2026, 7, 15, 14, 0)
        cover = [100, 100, 100, 100, 52, 11, 36, 13, 19] + [10] * 16
        hourly = self._hourly(afternoon, len(cover), cloud_cover=cover)
        assert sky_sentence(hourly, DAILY, afternoon, _runtime()) == "Clearing around 19:00"

    def test_noon_is_named_in_words(self):
        # London at eight: the sky shuts at twelve, which every language
        # says as noon rather than as a time on the clock
        from linecast.weather.sections import sky_sentence
        morning = datetime(2026, 7, 15, 8, 0)
        cover = [10] * 4 + [90] * 12
        hourly = self._hourly(morning, len(cover), cloud_cover=cover)
        for lang, said in (("en", "Clouding over around noon"),
                           ("de", "Es zieht gegen Mittag zu"),
                           ("fr", "Le ciel se couvrira vers midi"),
                           ("ja", "昼頃に曇ってくる見込みです"),
                           ("uk", "Близько полудня стане похмуро"),
                           ("tr", "Öğle saatlerinde hava kapanacak")):
            assert sky_sentence(hourly, DAILY, morning, _runtime(lang=lang)) == said, lang

    def _week(self, now, sums, probs, codes=None):
        days = [(now + timedelta(days=k)).date().isoformat() for k in range(-1, 7)]
        daily = {"time": days, "precipitation_sum": sums, "precipitation_probability_max": probs}
        if codes:
            daily["weather_code"] = codes
        return daily

    def _day_of(self, day, codes, prob):
        hours = [datetime.combine(day, datetime.min.time()) + timedelta(hours=h)
                 for h in range(24)]
        return {"time": [h.isoformat(timespec="minutes") for h in hours],
                "weather_code": codes,
                "precipitation_probability": [prob if c else 0 for c in codes]}

    def test_rain_later_in_the_week_is_named_when_it_is_worth_it(self):
        # Istanbul on a Sunday: light rain most of Tuesday
        from linecast.weather.sections import next_rain_sentence
        sunday = datetime(2026, 9, 20, 5, 30)
        daily = self._week(sunday, [0, 0, 0, 3.6, 0, 0, 0, 0], [0, 0, 5, 74, 0, 0, 0, 0])
        hourly = self._day_of(sunday.date() + timedelta(days=2), [0] * 9 + [61] * 8 + [0] * 7, 74)
        assert next_rain_sentence(daily, sunday, _runtime(celsius=True, metric=True), hourly) == \
            "Light rain likely on Tuesday"
        assert next_rain_sentence(daily, sunday, _runtime(lang="ja", celsius=True, metric=True),
                                  hourly) == "火曜日は弱い雨となる見込みです"

    def test_a_chance_of_rain_is_not_worth_the_week_sentence(self):
        from linecast.weather.sections import next_rain_sentence
        sunday = datetime(2026, 9, 20, 5, 30)
        daily = self._week(sunday, [0, 0, 0, 3.6, 0, 0, 0, 0], [0, 0, 5, 74, 0, 0, 0, 0])
        hourly = self._day_of(sunday.date() + timedelta(days=2), [0] * 9 + [61] * 8 + [0] * 7, 45)
        assert next_rain_sentence(daily, sunday, _runtime(celsius=True, metric=True), hourly) == ""

    def test_a_sliver_of_drizzle_is_not_a_wet_day(self):
        # Moscow on a Sunday: a 60% chance of a trace on Monday, real rain
        # on Tuesday
        from linecast.weather.sections import next_rain_sentence
        sunday = datetime(2026, 9, 20, 12, 0)
        daily = self._week(sunday, [0, 0, 0.01, 0.14, 0.26, 0.14, 0, 0],
                           [0, 0, 60, 74, 60, 75, 26, 0])
        hourly = self._day_of(sunday.date() + timedelta(days=2), [0] * 9 + [61] * 8 + [0] * 7, 74)
        assert next_rain_sentence(daily, sunday, _runtime(), hourly) == \
            "Light rain likely on Tuesday"

    def test_the_day_is_named_by_the_hour_that_holds_most_of_its_rain(self):
        # Helsinki: Thursday opens with an hour of drizzle and holds
        # 12mm of rain
        from linecast.weather.sections import next_rain_sentence
        sunday = datetime(2026, 9, 20, 5, 30)
        daily = self._week(sunday, [0, 0, 0, 12.2, 0, 0, 0, 0], [0, 0, 5, 81, 0, 0, 0, 0])
        codes = [0] * 7 + [51, 53, 61, 61, 61, 61, 51] + [0] * 10
        hourly = self._day_of(sunday.date() + timedelta(days=2), codes, 81)
        hourly["precipitation"] = [0] * 7 + [0.2, 0.6, 1.47, 1.65, 1.5, 2.4, 0.1] + [0] * 10
        assert next_rain_sentence(daily, sunday, _runtime(celsius=True, metric=True),
                                  hourly) == "Light rain on Tuesday"
        assert next_rain_sentence(daily, sunday, _runtime(lang="ja", celsius=True, metric=True),
                                  hourly) == "火曜日は弱い雨になるでしょう"

    def test_without_amounts_the_heaviest_hour_names_the_day(self):
        from linecast.weather.sections import next_rain_sentence
        sunday = datetime(2026, 9, 20, 5, 30)
        daily = self._week(sunday, [0, 0, 0, 12.2, 0, 0, 0, 0], [0, 0, 5, 81, 0, 0, 0, 0])
        codes = [0] * 7 + [51, 53, 61, 63, 61, 61, 51] + [0] * 10
        hourly = self._day_of(sunday.date() + timedelta(days=2), codes, 81)
        assert next_rain_sentence(daily, sunday, _runtime(celsius=True, metric=True),
                                  hourly) == "Rain on Tuesday"

    def test_a_far_off_day_of_drizzle_is_not_news_whatever_it_opens_with(self):
        # An hour of light rain at dawn does not make a drizzly Sunday
        # worth a sentence four days out
        from linecast.weather.sections import next_rain_sentence
        daily = self._week(NOON, [0, 0, 0, 0, 0, 5.0, 0, 0], [0, 0, 0, 0, 0, 90, 0, 0])
        codes = [0] * 6 + [61] + [53] * 11 + [0] * 6
        hourly = self._day_of(NOON.date() + timedelta(days=4), codes, 90)
        hourly["precipitation"] = [0] * 6 + [0.1] + [0.4] * 11 + [0] * 6
        assert next_rain_sentence(daily, NOON, _runtime(), hourly) == ""

    def test_the_further_off_the_surer_and_the_wetter_it_must_be(self):
        # Without the hours, the day's own code and odds name it
        from linecast.weather.sections import next_rain_sentence
        daily = self._week(NOON, [0, 0, 0, 0, 0, 0.12, 0, 0], [0, 0, 0, 0, 0, 85, 0, 0],
                           codes=[0, 0, 0, 0, 0, 63, 0, 0])
        assert next_rain_sentence(daily, NOON, _runtime()) == ""
        daily["precipitation_sum"][5] = 0.3
        assert next_rain_sentence(daily, NOON, _runtime()) == "Rain on Sunday"

    def test_drizzle_far_off_is_not_news(self):
        from linecast.weather.sections import next_rain_sentence
        daily = self._week(NOON, [0, 0, 0, 0, 0, 0.3, 0, 0], [0, 0, 0, 0, 0, 90, 0, 0])
        hourly = self._day_of(NOON.date() + timedelta(days=4), [0] * 6 + [53] * 12 + [0] * 6, 90)
        assert next_rain_sentence(daily, NOON, _runtime(), hourly) == ""

    def test_dryness_goes_unremarked(self):
        from linecast.weather.sections import next_rain_sentence
        daily = self._week(NOON, [0] * 8, [0, 0, 0, 20, 0, 0, 0, 0])
        assert next_rain_sentence(daily, NOON, _runtime()) == ""

    def test_gusts_this_afternoon(self):
        from linecast.weather.sections import gusts_sentence
        gusts = [20, 25, 30, 45, 40, 30, 20, 15]
        hourly = self._hourly(NOON, len(gusts), wind_gusts_10m=gusts)
        assert gusts_sentence(hourly, NOON, _runtime()) == "Gusts to 45\u00a0mph this afternoon"
        hourly = self._hourly(NOON, len(gusts), wind_gusts_10m=[g * 1.6 for g in gusts])
        assert gusts_sentence(hourly, NOON, _runtime(lang="de", metric=True)) == \
            "Heute Nachmittag Böen bis 72\u00a0km/h"
        # Japanese reads the wind in m/s, and the data comes that way too
        hourly = self._hourly(NOON, len(gusts), wind_gusts_10m=[g * 1.6 / 3.6 for g in gusts])
        assert gusts_sentence(hourly, NOON, _runtime(lang="ja", metric=True)) == \
            "午後に最大20m/sの突風が吹くでしょう"

    def test_a_breeze_is_not_worth_a_sentence(self):
        from linecast.weather.sections import gusts_sentence
        hourly = self._hourly(NOON, 6, wind_gusts_10m=[10, 12, 15, 20, 18, 10])
        assert gusts_sentence(hourly, NOON, _runtime()) == ""

    def test_gusts_the_place_is_used_to_are_not_worth_a_sentence(self):
        # Honolulu: the same afternoon trade wind every day of the week
        from linecast.weather.sections import gusts_sentence
        hourly = self._hourly(NOON, 6, wind_gusts_10m=[20, 25, 30, 32, 28, 20])
        days = [(NOON.date() + timedelta(days=d)).isoformat() for d in range(-1, 7)]

        def week(maxima):
            return {"time": days, "wind_gusts_10m_max": maxima}

        usual = week([31, 32, 30, 33, 29, 31, 32, 30])
        assert gusts_sentence(hourly, NOON, _runtime(), daily=usual) == ""
        # The same wind after a calm week is news
        calm = week([15, 32, 14, 16, 12, 15, 13, 17])
        assert gusts_sentence(hourly, NOON, _runtime(), daily=calm) == \
            "Gusts to 32 mph this afternoon"
        # And a gale is news in any week
        gale = [g * 1.5 for g in [20, 25, 30, 32, 28, 20]]
        hourly = self._hourly(NOON, 6, wind_gusts_10m=gale)
        assert gusts_sentence(hourly, NOON, _runtime(), daily=week([50] * 8)) == \
            "Gusts to 48 mph this afternoon"

    def test_below_freezing_tonight(self):
        from linecast.weather.sections import freeze_sentence
        temps = [40, 38, 36, 35, 34, 33, 32, 31, 29, 28, 28, 30, 34, 38]
        hourly = self._hourly(datetime(2026, 7, 15, 20), len(temps), temperature_2m=temps)
        now = datetime(2026, 7, 15, 20, 10)
        assert freeze_sentence(hourly, {"temperature_2m": 41}, now, _runtime()) == \
            "Below freezing early tomorrow morning, down to 28°"
        # A proper minus sign, not a hyphen
        below = [t - 40 for t in temps]
        hourly = self._hourly(datetime(2026, 7, 15, 20), len(temps), temperature_2m=below)
        assert freeze_sentence(hourly, {"temperature_2m": 1}, now,
                               _runtime(celsius=True, metric=True)) == \
            "Below freezing early tomorrow morning, down to −12°"
        celsius = [(t - 32) * 5 / 9 for t in temps]
        hourly = self._hourly(datetime(2026, 7, 15, 20), len(temps), temperature_2m=celsius)
        assert freeze_sentence(hourly, {"temperature_2m": 5}, now,
                               _runtime(lang="ja", celsius=True, metric=True)) == \
            "明日の早朝には氷点下まで冷え込み、最低−2度となるでしょう"

    def test_already_freezing_says_nothing(self):
        from linecast.weather.sections import freeze_sentence
        hourly = self._hourly(NOON, 6, temperature_2m=[30, 28, 26, 25, 25, 26])
        assert freeze_sentence(hourly, {"temperature_2m": 30}, NOON, _runtime()) == ""

    def test_the_heat_ahead_names_its_cause(self):
        from linecast.weather.sections import feels_ahead_sentence
        temps = [82, 85, 88, 90, 90, 88, 85]
        feels = [84, 89, 95, 98, 97, 93, 88]
        # 98°F feels like 36.7°C: past the mark; 89 and 95 are not
        hourly = self._hourly(NOON, len(temps), temperature_2m=temps, apparent_temperature=feels)
        assert feels_ahead_sentence(hourly, NOON, _runtime()) == \
            "It will feel as hot as 98° this afternoon"
        hourly.update(relative_humidity_2m=[70] * 7, wind_speed_10m=[3] * 7)
        assert feels_ahead_sentence(hourly, NOON, _runtime()) == \
            "The humidity will make it feel as hot as 98° this afternoon"

        def to_c(t):
            return (t - 32) * 5 / 9

        hourly.update(temperature_2m=[to_c(t) for t in temps],
                      apparent_temperature=[to_c(t) for t in feels])
        assert feels_ahead_sentence(hourly, NOON, _runtime(lang="ja", celsius=True)) == \
            "湿度が高く、午後には体感温度が37度まで上がる見込みです"

    def test_the_cold_ahead_names_the_wind(self):
        from linecast.weather.sections import feels_ahead_sentence
        hourly = self._hourly(NOON, 6, temperature_2m=[-5, -6, -8, -9, -9, -8],
                              apparent_temperature=[-12, -14, -17, -19, -18, -16],
                              relative_humidity_2m=[70] * 6, wind_speed_10m=[35] * 6)
        assert feels_ahead_sentence(hourly, NOON, _runtime(celsius=True, metric=True)) == \
            "The wind will make it feel as cold as −19° this afternoon"

    def test_what_the_place_is_used_to_is_not_news(self):
        # Hong Kong in September: every afternoon feels five degrees hotter
        from linecast.weather.sections import feels_ahead_sentence
        day = [28, 29, 31, 32, 32, 31, 29] + [28] * 17
        felt = [31, 33, 36, 37, 37, 36, 33] + [31] * 17
        hourly = self._hourly(NOON, 24 * 4, temperature_2m=day * 4, apparent_temperature=felt * 4)
        assert feels_ahead_sentence(hourly, NOON, _runtime(celsius=True, metric=True)) == ""
        # ...until a day stands out from the others
        hourly["apparent_temperature"] = felt[:4] + [40, 36, 33] + [31] * 17 + felt * 3
        assert feels_ahead_sentence(hourly, NOON, _runtime(celsius=True, metric=True)) == \
            "It will feel as hot as 40° this afternoon"

    def test_dangerous_heat_is_said_regardless(self):
        from linecast.weather.sections import feels_ahead_sentence
        day = [38, 40, 42, 43, 43, 42, 40] + [36] * 17
        felt = [42, 44, 46, 47, 47, 46, 44] + [39] * 17
        hourly = self._hourly(NOON, 24 * 4, temperature_2m=day * 4, apparent_temperature=felt * 4)
        assert feels_ahead_sentence(hourly, NOON, _runtime(celsius=True, metric=True)) == \
            "It will feel as hot as 47° this afternoon"

    def test_warm_but_not_extreme_says_nothing(self):
        from linecast.weather.sections import feels_ahead_sentence
        hourly = self._hourly(NOON, 4, temperature_2m=[80, 82, 82, 80],
                              apparent_temperature=[84, 88, 88, 84])
        assert feels_ahead_sentence(hourly, NOON, _runtime()) == ""

    def test_heat_that_is_already_here_is_not_news(self):
        # Singapore at half past ten: it feels 34° now and the hottest
        # hour ahead feels 34° too, so there is nothing to plan around
        from linecast.weather.sections import feels_ahead_sentence
        hourly = self._hourly(NOON, 6, temperature_2m=[29.5] * 6,
                              apparent_temperature=[33.5, 33.6, 34.1, 33.8, 33.6, 33.4],
                              relative_humidity_2m=[67] * 6, wind_speed_10m=[8] * 6)
        metric = _runtime(celsius=True, metric=True)
        assert feels_ahead_sentence(hourly, NOON, metric,
                                    current={"apparent_temperature": 33.7}) == ""
        # ...but a morning that has a long way to climb keeps its sentence
        assert feels_ahead_sentence(hourly, NOON, metric,
                                    current={"apparent_temperature": 25.0}) == \
            "The humidity will make it feel as hot as 34° this afternoon"

    def test_a_wind_chill_no_worse_than_the_present_one_says_nothing(self):
        from linecast.weather.sections import feels_ahead_sentence
        hourly = self._hourly(NOON, 6, temperature_2m=[-5, -6, -8, -9, -9, -8],
                              apparent_temperature=[-12, -14, -17, -19, -18, -16],
                              relative_humidity_2m=[70] * 6, wind_speed_10m=[35] * 6)
        metric = _runtime(celsius=True, metric=True)
        assert feels_ahead_sentence(hourly, NOON, metric,
                                    current={"apparent_temperature": -18}) == ""
        assert feels_ahead_sentence(hourly, NOON, metric,
                                    current={"apparent_temperature": -12}) == \
            "The wind will make it feel as cold as −19° this afternoon"

    def test_the_margin_over_the_present_follows_the_unit(self):
        # Three degrees Fahrenheit is not the two Celsius the sentence asks for
        from linecast.weather.sections import feels_ahead_sentence
        hourly = self._hourly(NOON, 6, temperature_2m=[85] * 6,
                              apparent_temperature=[92, 93, 95, 94, 93, 92])
        assert feels_ahead_sentence(hourly, NOON, _runtime(),
                                    current={"apparent_temperature": 92}) == ""
        assert feels_ahead_sentence(hourly, NOON, _runtime(),
                                    current={"apparent_temperature": 91}) == \
            "It will feel as hot as 95° this afternoon"

    def test_the_comparison_carries_the_number(self):
        from linecast.weather.sections import comparative_sentence
        daily = {"temperature_2m_max": [60, 68, 55]}
        assert comparative_sentence(daily, NOON, _runtime()) == \
            "Today's high will be 8° warmer than yesterday's"
        assert comparative_sentence(daily, NOON.replace(hour=16), _runtime()) == \
            "Tomorrow's high will be 13° cooler than today's"
        assert comparative_sentence(daily, NOON, _runtime(lang="ja")) == \
            "今日の最高気温は昨日より8度高いでしょう"
        assert comparative_sentence({"temperature_2m_max": [60, 61, 55]}, NOON, _runtime()) == \
            "Today's high will be about the same as yesterday's"


class TestWhatIsSaidAndInWhatOrder:
    """Four sentences at most, in the order of the things they describe,
    and filler only on a quiet day."""

    def _prose(self, data, now=NOON, **overrides):
        import re
        return " ".join(re.sub(r"\x1b\[[0-9;]*m", "", row)
                        for row in narrative_lines(data, now, 400, _runtime(**overrides)))

    def _busy_day(self):
        # Rain this morning, more this afternoon with a stiff breeze, a
        # day like yesterday, and a wind that bites: five things to say.
        hours = [NOON + timedelta(hours=k) for k in range(-6, 26)]
        codes = [63, 63, 63, 0, 0, 0] + [0, 0, 0, 63, 63, 63, 0, 0] + [0] * 18
        return {
            "current": {"temperature_2m": 40, "apparent_temperature": 30,
                        "relative_humidity_2m": 70, "wind_speed_10m": 18,
                        "weather_code": 3},
            "daily": dict(DAILY, temperature_2m_max=[60, 61, 63]),
            "hourly": {
                "time": [h.isoformat(timespec="minutes") for h in hours],
                "weather_code": codes,
                "precipitation_probability": [90 if c else 0 for c in codes],
                "precipitation": [0.5 if c else 0 for c in codes],
                "wind_gusts_10m": [20] * 6 + [20, 30, 30, 28, 20] + [20] * 21,
                "cloud_cover": [90] * 14 + [10] * 18,
                "temperature_2m": [40] * 32,
            },
        }

    def test_now_comes_before_later_and_the_past_comes_last(self):
        assert self._prose(self._busy_day()) == (
            "The wind is making it feel colder. "
            "Today's high will be about the same as yesterday's. "
            "Rain starting in a couple hours, with gusts to 30\u00a0mph. "
            "1.50\u00a0inches of rain in the last 24 hours.")

    def test_the_comparison_is_what_people_open_the_app_for(self):
        # Five things to say and room for four: "about the same" stays
        assert "about the same" in self._prose(self._busy_day())

    def test_wind_does_not_ride_on_rain_that_is_ending(self):
        # Helsinki: drizzle stopping, a gale building through the morning
        data = self._busy_day()
        codes = [63] * 7 + [0] * 25
        data["hourly"]["weather_code"] = codes
        data["hourly"]["precipitation_probability"] = [90 if c else 0 for c in codes]
        data["hourly"]["wind_gusts_10m"] = [20] * 6 + [20, 45, 40] + [20] * 23
        prose = self._prose(data)
        assert "Rain ending soon." in prose
        assert "Gusts to 45\u00a0mph this afternoon." in prose
        assert "with gusts" not in prose

    def test_a_quiet_day_keeps_the_old_order(self):
        data = {"current": self._busy_day()["current"],
                "daily": dict(DAILY, temperature_2m_max=[60, 61, 63]), "hourly": {}}
        assert self._prose(data) == (
            "The wind is making it feel colder. "
            "Today's high will be about the same as yesterday's.")

    def test_tomorrow_follows_now(self):
        # Miami at ten at night: muggy now, hotter tomorrow afternoon
        night = datetime(2026, 7, 15, 22, 0)
        hours = [night + timedelta(hours=k) for k in range(26)]
        temps = [76] * 10 + [78, 80, 83, 85, 86, 86, 85, 84] + [80] * 8
        feels = [79] * 10 + [86, 88, 92, 95, 96, 96, 94, 92] + [83] * 8
        data = {
            "current": {"temperature_2m": 76, "apparent_temperature": 84,
                        "relative_humidity_2m": 90, "wind_speed_10m": 3,
                        "weather_code": 3},
            "daily": {"sunrise": ["2026-07-15T07:08", "2026-07-16T07:09"],
                      "sunset": ["2026-07-15T19:19", "2026-07-16T19:19"],
                      "temperature_2m_max": [84, 84, 83]},
            "hourly": {"time": [h.isoformat(timespec="minutes") for h in hours],
                       "temperature_2m": temps, "apparent_temperature": feels,
                       "relative_humidity_2m": [85] * 26, "wind_speed_10m": [3] * 26},
        }
        # One sentence about the felt temperature, the one that looks ahead
        assert self._prose(data, night) == (
            "Tomorrow's high will be about the same as today's. "
            "The humidity will make it feel as hot as 96° in the afternoon.")

    def test_the_sentence_that_looks_ahead_gives_way_when_it_says_nothing_new(self):
        # The same night, but it already feels 95°: the sentence about
        # tomorrow has nothing to add, so the one that says why comes back
        night = datetime(2026, 7, 15, 22, 0)
        hours = [night + timedelta(hours=k) for k in range(26)]
        temps = [76] * 10 + [78, 80, 83, 85, 86, 86, 85, 84] + [80] * 8
        feels = [79] * 10 + [86, 88, 92, 95, 96, 96, 94, 92] + [83] * 8
        data = {
            "current": {"temperature_2m": 87, "apparent_temperature": 95,
                        "relative_humidity_2m": 90, "wind_speed_10m": 3,
                        "weather_code": 3},
            "daily": {"sunrise": ["2026-07-15T07:08", "2026-07-16T07:09"],
                      "sunset": ["2026-07-15T19:19", "2026-07-16T19:19"],
                      "temperature_2m_max": [84, 84, 83]},
            "hourly": {"time": [h.isoformat(timespec="minutes") for h in hours],
                       "temperature_2m": temps, "apparent_temperature": feels,
                       "relative_humidity_2m": [85] * 26, "wind_speed_10m": [3] * 26},
        }
        assert self._prose(data, night) == (
            "The humidity is making it feel warmer. "
            "Tomorrow's high will be about the same as today's.")

    def test_wind_in_the_same_part_of_the_day_rides_on_the_rain(self):
        # Quito: drizzle and a stiff wind, both tomorrow afternoon
        night = datetime(2026, 7, 15, 21, 0)
        hours = [night + timedelta(hours=k) for k in range(26)]
        codes = [0] * 17 + [53, 53, 53, 53, 0, 0, 0, 0, 0]
        data = {
            "daily": dict(DAILY, temperature_2m_max=[72, 72, 74]),
            "hourly": {"time": [h.isoformat(timespec="minutes") for h in hours],
                       "weather_code": codes,
                       "precipitation_probability": [92 if c else 0 for c in codes],
                       "wind_gusts_10m": [10] * 16 + [22, 26, 24, 20] + [10] * 6},
        }
        assert self._prose(data, night) == (
            "Tomorrow's high will be about the same as today's. "
            "Drizzle starting in the afternoon, with gusts to 26\u00a0mph.")
        assert self._prose(data, night, lang="ja") == (
            "明日の最高気温は今日と同じくらいでしょう。"
            "午後に霧雨になるでしょう。風も強まり、最大26mphの突風が吹くでしょう。")

class TestDegreesAsWords:
    """Where the language counts its degrees in words, the word agrees
    with the number and the case."""

    def _diff(self, lang, diff):
        from linecast.weather.sections import comparative_sentence
        rt = _runtime(lang=lang, celsius=True, metric=True)
        return comparative_sentence({"temperature_2m_max": [10, 10 + diff, 10]}, NOON, rt)

    def _low(self, lang, low):
        from linecast.weather.sections import freeze_sentence
        rt = _runtime(lang=lang, celsius=True, metric=True)
        temps = [3, 2, 1, low, low, 1]
        hourly = {"time": [(NOON + timedelta(hours=k)).isoformat(timespec="minutes")
                           for k in range(len(temps))], "temperature_2m": temps}
        return freeze_sentence(hourly, {"temperature_2m": 3}, NOON, rt)

    def test_slavic_counting_forms_after_the_difference(self):
        assert self._diff("ru", 4) == (
            "Сегодня максимальная температура будет на 4\u00a0градуса выше, чем вчера")
        assert self._diff("ru", 5) == (
            "Сегодня максимальная температура будет на 5\u00a0градусов выше, чем вчера")
        assert self._diff("ru", 21) == (
            "Сегодня максимальная температура будет на 21\u00a0градус выше, чем вчера")
        assert self._diff("pl", 4) == (
            "Dzisiejsza temperatura maksymalna będzie o 4\u00a0stopnie wyższa niż wczorajsza")
        assert self._diff("pl", 5) == (
            "Dzisiejsza temperatura maksymalna będzie o 5\u00a0stopni wyższa niż wczorajsza")
        assert self._diff("cs", 4) == (
            "Dnešní nejvyšší teplota bude o 4\u00a0stupně vyšší než včerejší")
        assert self._diff("cs", 5) == (
            "Dnešní nejvyšší teplota bude o 5\u00a0stupňů vyšší než včerejší")

    def test_slavic_genitive_after_down_to(self):
        # "Down to" takes the genitive: one degree, and two and up
        assert self._low("ru", -2).endswith(", до −2\u00a0градусов")
        assert self._low("ru", -1) == (
            "Сегодня днём температура опустится ниже нуля, до −1\u00a0градуса")
        assert self._low("uk", -2) == (
            "Сьогодні вдень температура опуститься нижче нуля, до −2\u00a0градусів")
        assert self._low("pl", -2).endswith(", do −2\u00a0stopni")
        assert self._low("pl", -1) == (
            "Dziś po południu temperatura spadnie poniżej zera, do −1\u00a0stopnia")

    def test_icelandic_dative_for_the_difference_only(self):
        assert self._diff("is", 4) == "Í dag verður hámarkshitinn 4\u00a0stigum hærri en í gær"
        # Every number ending in 1 but 11 takes the singular
        assert self._diff("is", 21) == "Í dag verður hámarkshitinn 21\u00a0stigi hærri en í gær"
        assert self._diff("is", 11) == "Í dag verður hámarkshitinn 11\u00a0stigum hærri en í gær"
        assert self._low("is", -2) == "Frost í dag eftir hádegi, niður í −2\u00a0stig"

    def test_one_degree_and_twenty_degrees(self):
        assert self._low("fi", -1) == "Tänä iltapäivänä pakkasta, alimmillaan −1\u00a0aste"
        assert self._low("da", -1) == "Frost i eftermiddag, ned til −1\u00a0grad"
        assert self._diff("ro", 20) == (
            "Maxima de azi va fi cu 20\u00a0de grade mai ridicată decât cea de ieri")
        assert self._diff("ro", 4) == (
            "Maxima de azi va fi cu 4\u00a0grade mai ridicată decât cea de ieri")


class TestAgreementAndTheClock:
    """Templates agree with their nouns in every language that inflects,
    and only English and Greek carry a 12-hour time in a sentence."""

    def _later(self, lang, code, prob=70, **overrides):
        from linecast.weather.sections import precipitation_sentence
        codes = [0, 0, 0, 0, code, code, code, 0]
        hourly = {"time": [(NOON + timedelta(hours=k)).isoformat(timespec="minutes")
                           for k in range(len(codes))],
                  "weather_code": codes,
                  "precipitation_probability": [prob if c else 0 for c in codes]}
        return precipitation_sentence(hourly, NOON, _runtime(lang=lang, celsius=True, metric=True,
                                                             **overrides))

    def test_romance_plurals_and_french_elision(self):
        assert self._later("fr", 81) == "Averses probables vers 16\u00a0h"
        assert self._later("fr", 81, 40) == "Risque d'averses vers 16\u00a0h"
        assert self._later("fr", 61, 40) == "Risque de pluie légère vers 16\u00a0h"
        assert self._later("es", 95) == "Probables tormentas hacia las 16:00"
        assert self._later("es", 63) == "Probable lluvia hacia las 16:00"
        assert self._later("pt", 81) == "Deve haver pancadas de chuva por volta das 16h"
        assert self._later("it", 81) == "Probabili rovesci verso le 16"
        assert self._later("it", 63, 40) == "Possibile pioggia verso le 16"
        assert self._later("ro", 81, 90) == "Averse în jurul orei 16:00"
        assert self._later("ro", 63, 90) == "Ploaie în jurul orei 16:00"

    def test_french_takes_the_article_and_canada_elides_too(self):
        from linecast.weather.sections import precipitation_sentence
        codes = [81, 81, 81, 0]
        hourly = {"time": [(NOON + timedelta(hours=k)).isoformat(timespec="minutes")
                           for k in range(len(codes))],
                  "weather_code": codes, "precipitation_probability": [90, 90, 90, 0]}

        def ending(lang):
            return precipitation_sentence(hourly, NOON, _runtime(lang=lang, metric=True))

        assert ending("fr") == "Les averses cesseront dans quelques heures"
        assert ending("fr-CA") == "Averses cessant dans quelques heures"
        assert ending("ro") == "Aversele încetează peste câteva ore"
        assert self._later("fr-CA", 81, 40) == "Risque d'averses vers 16\u00a0h"
        assert self._later("fr-CA", 81, 90) == "Averses débutant vers 16\u00a0h"

    def test_finnish_and_czech_plural_verbs(self):
        from linecast.weather.sections import precipitation_sentence
        codes = [81, 81, 81, 0]
        hourly = {"time": [(NOON + timedelta(hours=k)).isoformat(timespec="minutes")
                           for k in range(len(codes))],
                  "weather_code": codes, "precipitation_probability": [90, 90, 90, 0]}
        assert precipitation_sentence(hourly, NOON, _runtime(lang="fi", metric=True)) == \
            "Sadekuurot loppuvat parin tunnin kuluttua"
        assert precipitation_sentence(hourly, NOON, _runtime(lang="cs", metric=True)) == \
            "Přeháňky skončí za pár hodin"
        assert self._later("cs", 81) == "Přeháňky pravděpodobně začnou kolem 16:00"
        assert self._later("cs", 63) == "Déšť pravděpodobně začne kolem 16:00"
        assert self._later("da", 81) == "Sandsynligvis byger omkring kl.\u00a016"

    def test_likely_starts_at_an_hour_and_falls_in_a_part_of_the_day(self):
        # Before an hour, "likely" keeps "starting", or the rain would seem
        # to fall in that hour alone; a part of the day needs no "starting"
        assert self._later("en", 63) == "Rain likely starting around 16:00"
        from linecast.weather.sections import precipitation_sentence
        evening = NOON.replace(hour=20)
        codes = [0] * 20 + [63] * 3 + [0]
        hourly = {"time": [(evening + timedelta(hours=k)).isoformat(timespec="minutes")
                           for k in range(len(codes))],
                  "weather_code": codes,
                  "precipitation_probability": [70 if c else 0 for c in codes]}
        assert precipitation_sentence(hourly, evening, _runtime(use_24h=True)) == (
            "Rain likely tomorrow afternoon")

    def test_german_rain_that_is_ending_dies_away(self):
        from linecast.weather.sections import precipitation_sentence

        def ending(codes):
            hourly = {"time": [(NOON + timedelta(hours=k)).isoformat(timespec="minutes")
                               for k in range(len(codes))],
                      "weather_code": codes,
                      "precipitation_probability": [90 if c else 0 for c in codes]}
            return precipitation_sentence(hourly, NOON, _runtime(lang="de", metric=True))

        # As the DWD writes it, "abklingend": no verb to agree with
        # Schauer and Gewitter, and no "bis es aufhört"
        assert ending([80, 80, 80, 0]) == "Leichte Schauer, in ein paar Stunden abklingend"
        assert ending([95, 95, 95, 0]) == "Gewitter, in ein paar Stunden abklingend"
        assert ending([63, 63, 63, 0]) == "Regen, in ein paar Stunden abklingend"
        # Drizzle that is all but showers already is said as the showers
        assert ending([51, 80, 80, 0]) == "Leichte Schauer, in ein paar Stunden abklingend"
        assert ending([51, 51, 51, 51, 95, 95, 0]) == (
            "Leichter Nieselregen, gegen 16\u00a0Uhr Gewitter, gegen 18\u00a0Uhr abklingend")
        # Rain that only turns heavier is the same rain, harder
        assert ending([61, 61, 61, 61, 65, 65, 0]) == (
            "Leichter Regen, gegen 16\u00a0Uhr stärker, gegen 18\u00a0Uhr abklingend")
        # but rain that turns to ice is named as ice
        assert ending([61, 61, 61, 61, 67, 67, 0]) == (
            "Leichter Regen, gegen 16\u00a0Uhr gefrierender Regen, gegen 18\u00a0Uhr abklingend")

    def test_french_turns_take_then_and_an_article(self):
        from linecast.weather.sections import precipitation_sentence

        def sentence(codes):
            hourly = {"time": [(NOON + timedelta(hours=k)).isoformat(timespec="minutes")
                               for k in range(len(codes))],
                      "weather_code": codes,
                      "precipitation_probability": [90 if c else 0 for c in codes]}
            return precipitation_sentence(hourly, NOON, _runtime(lang="fr", metric=True))

        assert sentence([51, 51, 51, 51, 95, 95, 0]) == (
            "Bruine légère, puis des orages vers 16\u00a0h, avant de cesser vers 18\u00a0h")
        assert sentence([51] * 4 + [95] * 22) == (
            "Bruine légère toute la journée, avec des orages vers 16\u00a0h")
        assert sentence([51, 51, 51, 51, 65, 65, 0]) == (
            "Bruine légère, puis de fortes pluies vers 16\u00a0h, avant de cesser vers 18\u00a0h")

    def test_only_english_and_greek_take_the_twelve_hour_clock_in_a_sentence(self):
        # A French reader looking at Montréal, where the clock is 12-hour
        assert self._later("fr", 63, 90, use_24h=False) == "Pluie vers 16\u00a0h"
        assert self._later("en", 63, 90, use_24h=False) == "Rain starting around 4pm"
        assert self._later("el", 63, 90, use_24h=False) == \
            "Γύρω στις 4 το απόγευμα θα αρχίσουν βροχές"
        assert self._later("es", 63, 90, use_24h=False) == "Lluvia hacia las 16:00"


class TestTomorrowIsSaidOnce:
    """A sentence about the same later day as the one before it inherits
    the day rather than naming it again."""

    def _prose(self, data, now, **overrides):
        import re
        return " ".join(re.sub(r"\x1b\[[0-9;]*m", "", row)
                        for row in narrative_lines(data, now, 400, _runtime(**overrides)))

    def test_the_comparison_inherits_tomorrow(self):
        night = datetime(2026, 7, 15, 21, 0)
        hours = [night + timedelta(hours=k) for k in range(26)]
        data = {"daily": dict(DAILY, temperature_2m_max=[70, 72, 67]),
                "hourly": {"time": [h.isoformat(timespec="minutes") for h in hours],
                           "wind_gusts_10m": [10] * 11 + [40, 42, 38] + [10] * 12}}
        assert self._prose(data, night) == (
            "Gusts to 42\u00a0mph tomorrow morning. The high will be a bit cooler than today's.")
        assert self._prose(data, night, lang="ja") == (
            "明日の朝に最大42mphの突風が吹くでしょう。最高気温は今日よりやや低いでしょう。")

    def test_rain_after_the_comparison_inherits_tomorrow(self):
        night = datetime(2026, 7, 15, 21, 0)
        hours = [night + timedelta(hours=k) for k in range(26)]
        codes = [0] * 17 + [61] * 4 + [0] * 5
        data = {"daily": dict(DAILY, temperature_2m_max=[70, 72, 67]),
                "hourly": {"time": [h.isoformat(timespec="minutes") for h in hours],
                           "weather_code": codes,
                           "precipitation_probability": [90 if c else 0 for c in codes]}}
        assert self._prose(data, night) == (
            "Tomorrow's high will be a bit cooler than today's. Light rain starting in the afternoon.")

    def test_today_is_never_repeated_so_never_elided(self):
        data = {"daily": dict(DAILY, temperature_2m_max=[70, 75, 67]), "hourly": {}}
        assert self._prose(data, NOON) == "Today's high will be a bit warmer than yesterday's."

    def test_an_hour_after_midnight_does_not_establish_tomorrow(self):
        # Havana at half past ten: thunder in about an hour is not "tomorrow"
        late = datetime(2026, 7, 15, 22, 36)
        hours = [late.replace(minute=0) + timedelta(hours=k) for k in range(26)]
        codes = [0, 0, 0, 95, 95, 95] + [0] * 20
        data = {"daily": dict(DAILY, temperature_2m_max=[88, 88, 88]),
                "hourly": {"time": [h.isoformat(timespec="minutes") for h in hours],
                           "weather_code": codes,
                           "precipitation_probability": [70 if c else 0 for c in codes]}}
        assert self._prose(data, late) == (
            "Thunderstorms likely starting in about an hour. "
            "Tomorrow's high will be about the same as today's.")


class TestFog:
    """Fog is worth saying whenever there is fog: when it lifts if it is
    already out there, and when it closes in if it is not."""

    @staticmethod
    def _hourly(start, codes):
        hours = [start + timedelta(hours=k) for k in range(len(codes))]
        return {"time": [h.isoformat(timespec="minutes") for h in hours],
                "weather_code": codes}

    def _sentence(self, hourly, now=NOON, current=None, **overrides):
        from linecast.weather.sections import fog_sentence
        return fog_sentence(hourly, current or {}, now, _runtime(**overrides), daily=DAILY)

    def _prose(self, data, now=NOON, **overrides):
        import re
        return " ".join(re.sub(r"\x1b\[[0-9;]*m", "", row)
                        for row in narrative_lines(data, now, 400, _runtime(**overrides)))

    def test_fog_now_says_when_it_lifts(self):
        hourly = self._hourly(NOON, [45, 45, 45, 45, 3, 3, 3, 3])
        assert self._sentence(hourly) == "Fog clearing around 16:00"
        # Freezing fog is fog; the rime it leaves is the icon's business
        hourly = self._hourly(NOON, [48, 48, 48, 3, 3, 3])
        assert self._sentence(hourly) == "Fog clearing in a couple hours"

    def test_the_reading_on_the_screen_wins(self):
        # The header says fog and the model's hour says cloud: the
        # paragraph may not read as though the air were clear
        hourly = self._hourly(NOON, [3, 3, 3, 3, 3, 3])
        assert self._sentence(hourly) == ""
        assert self._sentence(hourly, current={"weather_code": 45}) == \
            "Fog clearing soon"
        # The hour the model disagrees about is read as a thinning
        hourly = self._hourly(NOON, [3, 45, 3, 3, 3, 3])
        assert self._sentence(hourly) == ""
        assert self._sentence(hourly, current={"weather_code": 45}) == \
            "Fog clearing in about an hour"

    def test_fog_that_outlasts_the_day_holds_through_it(self):
        assert self._sentence(self._hourly(NOON, [45] * 26)) == "Fog through the day"
        late = datetime(2026, 7, 15, 22, 5)
        hourly = self._hourly(late.replace(minute=0), [45] * 26)
        assert self._sentence(hourly, late) == "Fog through the night"

    def test_fog_later_names_the_night_and_the_morning_after_it(self):
        # Fog forming after midnight and burning off by nine: "tomorrow"
        # belongs to the morning, and is said once
        night = datetime(2026, 7, 15, 21, 0)
        codes = [3] * 4 + [45] * 7 + [3] * 15
        assert self._sentence(self._hourly(night, codes), night) == \
            "Fog overnight, clearing tomorrow morning"
        codes = [3] * 12 + [45] * 5 + [3] * 8
        assert self._sentence(self._hourly(night, codes), night) == \
            "Fog tomorrow morning, clearing in the afternoon"

    def test_an_hour_of_fog_is_a_patch_and_not_a_sentence(self):
        assert self._sentence(self._hourly(NOON, [3, 3, 45, 3, 3, 3])) == ""
        # ...and fog further on is still found
        assert self._sentence(self._hourly(NOON, [3, 3, 45, 3, 3, 45, 45, 45, 3, 3])) == \
            "Fog this evening"

    def test_a_clear_hour_inside_fog_is_a_thinning(self):
        hourly = self._hourly(NOON, [3, 3, 45, 45, 3, 45, 45, 3, 3, 3])
        assert self._sentence(hourly) == "Fog this afternoon, clearing around 19:00"
        # Without the thinning the fog would read as over at four
        hourly = self._hourly(NOON, [3, 3, 45, 45, 3, 3, 3, 3, 3, 3])
        assert self._sentence(hourly) == "Fog this afternoon"

    def test_fog_inside_one_stretch_of_the_day_names_the_stretch(self):
        # Fog that comes and goes inside the one evening is the evening's
        # fog; "clearing overnight" after "fog tonight" says it worse
        evening = datetime(2026, 7, 15, 17, 0)
        codes = [3] * 5 + [45] * 4 + [3] * 16
        assert self._sentence(self._hourly(evening, codes), evening) == "Fog tonight"

    def test_the_fog_reads_in_the_words_a_language_names_the_day_in(self):
        # The phrase for a stretch of the day carries its own case or
        # particle -- the Russian instrumental, the Finnish essive, the
        # Japanese に, the Icelandic dative -- so it reads in the fog
        # sentence as it does in the gusty afternoon and the freezing night.
        evening = datetime(2026, 7, 15, 20, 0)
        clearing = self._hourly(NOON, [45, 45, 45, 45, 3, 3, 3, 3])
        tonight = self._hourly(evening, [3, 3] + [45] * 11 + [3] * 12)
        for lang, lifting, coming in (
            ("ja", "霧は16時頃に晴れる見込みです", "今夜霧が出て、明日の朝に晴れる見込みです"),
            ("ko", "안개는 16시경 걷히겠습니다", "오늘 밤 안개가 끼었다가 내일 아침 걷히겠습니다"),
            ("ru", "Туман рассеется около 16:00",
             "Сегодня ночью туман, завтра утром рассеется"),
            ("fi", "Sumu hälvenee noin klo\u00a016",
             "Tänä yönä sumua, joka hälvenee huomenna aamulla"),
            ("el", "Η ομίχλη θα διαλυθεί γύρω στις 16:00",
             "Ομίχλη απόψε, που θα διαλυθεί αύριο το πρωί"),
            ("tr", "Sis saat 16:00 civarında dağılacak",
             "Bu gece sis bekleniyor, yarın sabah dağılacak"),
            ("is", "Þokunni léttir um kl.\u00a016",
             "Þoka í nótt, léttir til á morgun fyrir hádegi"),
            ("zh", "雾16时左右消散", "今晚有雾，明天早上消散"),
        ):
            assert self._sentence(clearing, lang=lang) == lifting, lang
            assert self._sentence(tonight, evening, lang=lang) == coming, lang

    def test_a_language_without_the_words_says_nothing(self, monkeypatch):
        # A language whose table has not been given the fog sentences
        # leaves them unsaid rather than saying them in English
        import linecast.weather.i18n as i18n
        bare = {k: v for k, v in _STRINGS["sw"].items() if not k.startswith("fog_")}
        monkeypatch.setitem(i18n._STRINGS, "sw", bare)
        assert self._sentence(self._hourly(NOON, [45, 45, 3, 3]), lang="sw") == ""
        assert self._sentence(self._hourly(NOON, [45] * 26), lang="sw") == ""
        assert self._sentence(self._hourly(NOON, [3, 3, 45, 45, 3, 3]), lang="sw") == ""

    def test_the_sky_does_not_lift_the_fog_a_second_time(self):
        from linecast.weather.sections import sky_sentence
        codes = [45] * 5 + [0] * 20
        hourly = dict(self._hourly(NOON, codes), cloud_cover=[100] * 5 + [10] * 20)
        # The cloud clears when the fog does, and the sky sentence says
        # so on its own
        assert sky_sentence(hourly, DAILY, NOON, _runtime()) == "Clearing around 17:00"
        data = {"daily": dict(DAILY, temperature_2m_max=[70, 75, 67]), "hourly": hourly,
                "current": {"weather_code": 45}}
        assert self._prose(data) == (
            "Fog clearing around 17:00. Today's high will be a bit warmer than yesterday's.")


class TestPastPrecipitation:
    """What fell in the last day."""

    def test_the_decimal_mark_is_the_languages(self):
        from linecast.weather.sections import past_precip_sentence
        hourly = {"time": [(NOON - timedelta(hours=1)).isoformat(timespec="minutes")],
                  "precipitation": [4.0], "snowfall": [0], "weather_code": [63]}

        def said(lang):
            return past_precip_sentence(hourly, NOON, _runtime(lang=lang, metric=True))

        assert said("de") == "In den letzten 24\u00a0Stunden fielen 4,0\u00a0mm Regen"
        # Latin American Spanish writes a point, Spain a comma
        assert said("es") == "4.0\u00a0mm de lluvia en las últimas 24\u00a0h"
        assert said("es-ES") == "4,0\u00a0mm de lluvia en las últimas 24\u00a0h"
        assert said("ja") == "過去24時間の降水量は4.0mmでした"

    def test_the_last_day_is_twenty_four_hours(self):
        from linecast.weather.sections import past_precip_sentence
        # A millimetre stamped at every hour from a day ago to now.  Each
        # stamp holds the hour before it, so the one a day ago fell 25
        # hours back and is not part of the last day.
        hours = [NOON - timedelta(hours=k) for k in range(24, -1, -1)]
        hourly = {"time": [h.isoformat(timespec="minutes") for h in hours],
                  "precipitation": [1.0] * 25, "snowfall": [0] * 25,
                  "weather_code": [61] * 25}
        runtime = _runtime(celsius=True, metric=True)
        assert past_precip_sentence(hourly, NOON + timedelta(minutes=26), runtime) == (
            "24.0\u00a0mm of rain in the last 24 hours")
