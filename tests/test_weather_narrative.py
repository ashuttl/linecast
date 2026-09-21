"""The prose lines under the weather graph: what they say, and how they pack."""

import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from linecast._i18n import VARIANTS
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
                "precipitation_probability": [70, 0, 70, 70],
                "precipitation": [0.3, 0, 0, 0],
                "snowfall": [0, 0, 0, 0],
            },
        }
        expected = (
            "Joto la leo litakuwa karibu sawa na la jana. "
            "Manyunyu mepesi huenda yakaanza hivi karibuni. "
            "Kiasi cha mvua katika saa 24 zilizopita: 0.30″."
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
        from linecast._weather_sections import precipitation_sentence
        return precipitation_sentence(hourly, self.EVENING, _runtime(**overrides))

    def test_drizzle_now_names_the_heavy_rain_to_come_and_when_it_ends(self):
        # 18:00 light drizzle through heavy rain at 23:00, dry from 02:00
        codes = [51, 51, 53, 61, 63, 65, 63, 61, 0, 0]
        amounts = [0.01, 0.01, 0.02, 0.1, 0.2, 0.34, 0.2, 0.05, 0, 0]
        assert self._sentence(self._hourly(codes, amounts)) == \
            "Light drizzle becoming heavy rain around 23:00, ending overnight"
        assert self._sentence(self._hourly(codes, amounts), use_24h=False) == \
            "Light drizzle becoming heavy rain around 11pm, ending overnight"

    def test_japanese_says_the_same_rain_gets_harder_and_another_kind_turns(self):
        # Rain at 18:00 turning heavy at 21:00 and over by 02:00 is the
        # rain strengthening, not "rain becoming heavy rain"; drizzle
        # turning to rain is still a turn
        codes = [63, 63, 63, 65, 65, 65, 63, 61, 0, 0]
        amounts = [0.1, 0.1, 0.1, 0.3, 0.34, 0.3, 0.2, 0.05, 0, 0]
        assert self._sentence(self._hourly(codes, amounts), lang="ja") == \
            "数時間後に雨が強まり、夜のうちにやむ見込み"
        codes = [51, 51, 53, 61, 63, 65, 63, 61, 0, 0]
        amounts = [0.01, 0.01, 0.02, 0.1, 0.2, 0.34, 0.2, 0.05, 0, 0]
        assert self._sentence(self._hourly(codes, amounts), lang="ja") == \
            "霧雨が23時頃に強い雨となり、夜のうちにやむ見込み"

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
            "Light rain becoming heavy rain around 23:00, ending overnight"

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
            "Light drizzle becoming light rain in about an hour, ending around 23:00"

    def test_a_turn_the_language_cannot_name_is_not_said(self):
        # Japanese calls every drizzle 霧雨, and thunder is thunder
        codes = [51, 51, 55, 55, 55, 0]
        assert self._sentence(self._hourly(codes), lang="ja") == \
            "霧雨が23時頃にやむ見込み"
        codes = [95, 95, 99, 99, 99, 0]
        assert self._sentence(self._hourly(codes)) == \
            "Thunderstorms ending around 23:00"

    def test_without_amounts_the_heaviest_code_is_the_peak(self):
        codes = [51, 53, 63, 65, 63, 0]
        assert self._sentence(self._hourly(codes)) == \
            "Light drizzle becoming heavy rain in a couple hours, ending around 23:00"

    def test_a_let_up_is_not_called_a_turn(self):
        # More water later, but a lighter code: the run stays "rain"
        codes = [63, 63, 61, 61, 61, 0]
        amounts = [0.1, 0.1, 0.3, 0.3, 0.3, 0]
        assert self._sentence(self._hourly(codes, amounts)) == \
            "Rain ending around 23:00"

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
            "Light rain starting in a couple hours, becoming heavy rain overnight"

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
            "Manyunyu mepesi yataanza baada ya muda wa masaa mawili hivi")

    def test_a_turn_needs_two_hours_unless_the_day_cuts_it_off(self):
        # Heavy rain for the run's last hour goes unmentioned...
        codes = [61, 61, 61, 65, 0]
        assert self._sentence(self._hourly(codes)) == "Light rain ending in a couple hours"
        # ...unless the run only ends because the window does
        codes = [61] * 23 + [65]
        assert self._sentence(self._hourly(codes)) == \
            "Light rain becoming heavy rain tomorrow evening, continuing through the day"

    def test_a_turn_already_here_is_what_is_falling(self):
        # Santiago: drizzle now, showers from the next hour, dry by three
        codes = [53, 81, 81, 81, 0]
        assert self._sentence(self._hourly(codes)) == "Showers ending in a couple hours"

    def test_an_hour_of_drizzle_at_the_edge_of_a_storm_is_the_storm(self):
        # Lagos: drizzle at eleven, thunder from noon
        codes = [0, 0, 0, 0, 51, 95, 95, 95, 0]
        assert self._sentence(self._hourly(codes)) == "Thunderstorms starting around 23:00"
        assert self._sentence(self._hourly(codes), lang="ja") == "23時頃に雷雨となる"


class TestHedges:
    """The word before "starting" follows the odds."""

    EVENING = datetime(2026, 9, 17, 18, 10)

    def _sentence(self, prob, **overrides):
        from linecast._weather_sections import precipitation_sentence
        hours = range(18, 24)
        hourly = {
            "time": [f"2026-09-17T{h:02d}:00" for h in hours],
            "weather_code": [0, 0, 0, 61, 61, 61],
            "precipitation_probability": [0, 0, 0, prob, prob, prob],
        }
        return precipitation_sentence(hourly, self.EVENING, _runtime(**overrides))

    def test_a_chance_is_a_chance(self):
        assert self._sentence(40) == "A chance of light rain in a couple hours"
        assert self._sentence(40, lang="ja", use_24h=True) == "数時間後に弱い雨の可能性"

    def test_likely_is_likely(self):
        assert self._sentence(70) == "Light rain likely starting in a couple hours"
        assert self._sentence(70, lang="ja", use_24h=True) == "数時間後に弱い雨の見込み"

    def test_eighty_percent_needs_no_hedge(self):
        assert self._sentence(90) == "Light rain starting in a couple hours"
        assert self._sentence(90, lang="ja", use_24h=True) == "数時間後に弱い雨となる"

    def test_a_language_without_the_forms_keeps_its_one_hedge(self, monkeypatch):
        # A language whose table has not been given the graded forms
        # says its one hedge for every grade, never English
        import linecast._weather_i18n as i18n
        bare = {k: v for k, v in _STRINGS["sw"].items()
                if not k.startswith(("starting_chance", "starting_sure"))}
        monkeypatch.setitem(i18n._STRINGS, "sw", bare)
        for prob in (40, 70, 90):
            assert self._sentence(prob, lang="sw", use_24h=True) == \
                "Mvua nyepesi huenda ikaanza baada ya muda wa masaa mawili hivi"

    def test_the_hedge_follows_the_best_hour_of_the_run(self):
        from linecast._weather_sections import precipitation_sentence
        hourly = {
            "time": [f"2026-09-17T{h:02d}:00" for h in range(18, 24)],
            "weather_code": [0, 0, 0, 61, 61, 61],
            "precipitation_probability": [0, 0, 0, 35, 60, 85],
        }
        assert precipitation_sentence(hourly, self.EVENING, _runtime()) == \
            "Light rain starting in a couple hours"


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
        from linecast._weather_sections import precipitation_sentence
        late = datetime(2026, 7, 15, 22, 5)
        hourly = self._hourly([63] * 26, late.replace(minute=0))
        assert precipitation_sentence(hourly, late, _runtime(), daily=DAILY) == \
            "Rain continuing through the night"
        assert precipitation_sentence(hourly, late, _runtime(lang="ja"), daily=DAILY) == \
            "雨が夜通し続く見込み"
        hourly = self._hourly([63] * 26, NOON)
        assert precipitation_sentence(hourly, NOON, _runtime(), daily=DAILY) == \
            "Rain continuing through the day"

    def test_tomorrow_is_said_once(self):
        from linecast._weather_sections import precipitation_sentence
        late = datetime(2026, 7, 15, 21, 0)
        codes = [0] * 17 + [61, 61, 61, 61, 65, 65, 65, 0]
        hourly = self._hourly(codes, late)
        assert precipitation_sentence(hourly, late, _runtime()) == \
            "Light rain starting tomorrow afternoon, becoming heavy rain in the evening"
        # The same rain, harder, is said as such in Japanese; a turn to
        # another kind (drizzle to rain, below) keeps "となり"
        assert precipitation_sentence(hourly, late, _runtime(lang="ja")) == \
            "明日の午後に弱い雨、夕方に強まる"

    def test_early_tomorrow_morning_is_followed_by_later_in_the_morning(self):
        # Chicago at nine at night: drizzle turning to rain before dawn,
        # over by mid-morning
        from linecast._weather_sections import precipitation_sentence
        night = datetime(2026, 7, 15, 21, 0)
        codes = [51, 51, 51, 51, 51, 51, 51, 51, 51, 63, 63, 63, 63, 0, 0]
        hourly = self._hourly(codes, night)
        hourly["precipitation"] = [0.01] * 9 + [0.1, 0.15, 0.15, 0.1, 0, 0]
        assert precipitation_sentence(hourly, night, _runtime()) == \
            "Light drizzle becoming rain early tomorrow morning, ending later in the morning"
        assert precipitation_sentence(hourly, night, _runtime(lang="ja")) == \
            "霧雨が明日の早朝に雨となり、午前中にやむ見込み"

    def test_in_the_small_hours_the_next_small_hours_are_tomorrow_night(self):
        # Reykjavík at two in the morning: drizzle due at one the next night
        from linecast._weather_sections import precipitation_sentence
        small = datetime(2026, 7, 15, 2, 30)
        codes = [0] * 23 + [51, 51]
        assert precipitation_sentence(self._hourly(codes, small), small, _runtime()) == \
            "Light drizzle starting tomorrow night"
        assert precipitation_sentence(self._hourly(codes, small), small, _runtime(lang="ja")) == \
            "明日の夜に霧雨となる"

    def test_a_dry_hour_inside_rain_is_a_lull(self):
        from linecast._weather_sections import precipitation_sentence
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
        assert prose == "雨が約1時間後にやむ見込み。19時頃に再び雨の見込み。"


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
        from linecast._weather_sections import snow_total_sentence
        evening = datetime(2026, 7, 15, 20, 0)
        codes = [0, 0, 71, 73, 73, 73, 71, 0, 0]
        hourly = self._hourly(evening, len(codes), weather_code=codes,
                              precipitation_probability=[90 if c else 0 for c in codes],
                              snowfall=[0, 0, 1.0, 2.0, 2.5, 1.5, 0.6, 0, 0])
        assert snow_total_sentence(hourly, evening, _runtime()) == \
            "About 3″ of snow by tomorrow morning"
        assert snow_total_sentence(hourly, evening, _runtime(metric=True, celsius=True)) == \
            "About 8cm of snow by tomorrow morning"
        assert snow_total_sentence(hourly, evening, _runtime(lang="ja", metric=True)) == \
            "明日の朝には約8cmの積雪の見込み"
        hourly["snowfall"] = [0, 0, 0.3, 0.4, 0.3, 0.2, 0.1, 0, 0]
        # "About" and a decimal do not go together
        assert snow_total_sentence(hourly, evening, _runtime(metric=True, celsius=True)) == \
            "About 1cm of snow by tomorrow morning"

    def test_a_dusting_is_not_worth_a_sentence(self):
        from linecast._weather_sections import snow_total_sentence
        codes = [71, 71, 0]
        hourly = self._hourly(NOON, 3, weather_code=codes,
                              precipitation_probability=[90, 90, 0], snowfall=[0.3, 0.4, 0])
        assert snow_total_sentence(hourly, NOON, _runtime()) == ""

    def test_the_sky_clears(self):
        from linecast._weather_sections import sky_sentence
        cover = [90, 90, 90, 90, 10, 10, 10, 10, 10, 10, 10, 10]
        hourly = self._hourly(NOON, len(cover), cloud_cover=cover)
        assert sky_sentence(hourly, DAILY, NOON, _runtime()) == "Clearing around 16:00"
        assert sky_sentence(hourly, DAILY, NOON, _runtime(lang="ja")) == "16時頃に晴れてくる見込み"

    def test_a_brief_clearing_is_not_clearing(self):
        # Los Angeles: the marine layer lifts for the evening and rolls
        # back in at night
        from linecast._weather_sections import sky_sentence
        cover = [90, 90, 90, 90, 90, 90, 10, 10, 10, 90, 90, 90, 90, 90]
        hourly = self._hourly(NOON, len(cover), cloud_cover=cover)
        assert sky_sentence(hourly, DAILY, NOON, _runtime()) == ""

    def test_the_sky_clouds_over_unless_rain_already_says_so(self):
        from linecast._weather_sections import sky_sentence
        cover = [10, 10, 10, 10, 90, 90, 90, 90, 90, 90, 90, 90]
        hourly = self._hourly(NOON, len(cover), cloud_cover=cover)
        assert sky_sentence(hourly, DAILY, NOON, _runtime()) == "Clouding over around 16:00"
        assert sky_sentence(hourly, DAILY, NOON, _runtime(), precip_kind="starting") == ""

    def test_a_mixed_sky_says_nothing(self):
        from linecast._weather_sections import sky_sentence
        cover = [50, 50, 50, 50, 90, 90, 90, 90, 90, 90, 90, 90]
        hourly = self._hourly(NOON, len(cover), cloud_cover=cover)
        assert sky_sentence(hourly, DAILY, NOON, _runtime()) == ""

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
        from linecast._weather_sections import next_rain_sentence
        sunday = datetime(2026, 9, 20, 5, 30)
        daily = self._week(sunday, [0, 0, 0, 3.6, 0, 0, 0, 0], [0, 0, 5, 74, 0, 0, 0, 0])
        hourly = self._day_of(sunday.date() + timedelta(days=2), [0] * 9 + [61] * 8 + [0] * 7, 74)
        assert next_rain_sentence(daily, sunday, _runtime(celsius=True, metric=True), hourly) == \
            "Light rain likely on Tuesday"
        assert next_rain_sentence(daily, sunday, _runtime(lang="ja", celsius=True, metric=True),
                                  hourly) == "火曜日に弱い雨の見込み"

    def test_a_chance_of_rain_is_not_worth_the_week_sentence(self):
        from linecast._weather_sections import next_rain_sentence
        sunday = datetime(2026, 9, 20, 5, 30)
        daily = self._week(sunday, [0, 0, 0, 3.6, 0, 0, 0, 0], [0, 0, 5, 74, 0, 0, 0, 0])
        hourly = self._day_of(sunday.date() + timedelta(days=2), [0] * 9 + [61] * 8 + [0] * 7, 45)
        assert next_rain_sentence(daily, sunday, _runtime(celsius=True, metric=True), hourly) == ""

    def test_a_sliver_of_drizzle_is_not_a_wet_day(self):
        # Moscow on a Sunday: a 60% chance of a trace on Monday, real rain
        # on Tuesday
        from linecast._weather_sections import next_rain_sentence
        sunday = datetime(2026, 9, 20, 12, 0)
        daily = self._week(sunday, [0, 0, 0.01, 0.14, 0.26, 0.14, 0, 0],
                           [0, 0, 60, 74, 60, 75, 26, 0])
        hourly = self._day_of(sunday.date() + timedelta(days=2), [0] * 9 + [61] * 8 + [0] * 7, 74)
        assert next_rain_sentence(daily, sunday, _runtime(), hourly) == \
            "Light rain likely on Tuesday"

    def test_the_further_off_the_surer_and_the_wetter_it_must_be(self):
        # Without the hours, the day's own code and odds name it
        from linecast._weather_sections import next_rain_sentence
        daily = self._week(NOON, [0, 0, 0, 0, 0, 0.12, 0, 0], [0, 0, 0, 0, 0, 85, 0, 0],
                           codes=[0, 0, 0, 0, 0, 63, 0, 0])
        assert next_rain_sentence(daily, NOON, _runtime()) == ""
        daily["precipitation_sum"][5] = 0.3
        assert next_rain_sentence(daily, NOON, _runtime()) == "Rain on Sunday"

    def test_drizzle_far_off_is_not_news(self):
        from linecast._weather_sections import next_rain_sentence
        daily = self._week(NOON, [0, 0, 0, 0, 0, 0.3, 0, 0], [0, 0, 0, 0, 0, 90, 0, 0])
        hourly = self._day_of(NOON.date() + timedelta(days=4), [0] * 6 + [53] * 12 + [0] * 6, 90)
        assert next_rain_sentence(daily, NOON, _runtime(), hourly) == ""

    def test_dryness_goes_unremarked(self):
        from linecast._weather_sections import next_rain_sentence
        daily = self._week(NOON, [0] * 8, [0, 0, 0, 20, 0, 0, 0, 0])
        assert next_rain_sentence(daily, NOON, _runtime()) == ""

    def test_gusts_this_afternoon(self):
        from linecast._weather_sections import gusts_sentence
        gusts = [20, 25, 30, 45, 40, 30, 20, 15]
        hourly = self._hourly(NOON, len(gusts), wind_gusts_10m=gusts)
        assert gusts_sentence(hourly, NOON, _runtime()) == "Gusts to 45mph this afternoon"
        hourly = self._hourly(NOON, len(gusts), wind_gusts_10m=[g * 1.6 for g in gusts])
        assert gusts_sentence(hourly, NOON, _runtime(lang="de", metric=True)) == \
            "Böen bis 72 km/h heute Nachmittag"
        # Japanese reads the wind in m/s, and the data comes that way too
        hourly = self._hourly(NOON, len(gusts), wind_gusts_10m=[g * 1.6 / 3.6 for g in gusts])
        assert gusts_sentence(hourly, NOON, _runtime(lang="ja", metric=True)) == \
            "午後に最大20m/sの突風の見込み"

    def test_a_breeze_is_not_worth_a_sentence(self):
        from linecast._weather_sections import gusts_sentence
        hourly = self._hourly(NOON, 6, wind_gusts_10m=[10, 12, 15, 20, 18, 10])
        assert gusts_sentence(hourly, NOON, _runtime()) == ""

    def test_below_freezing_tonight(self):
        from linecast._weather_sections import freeze_sentence
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
            "明日の早朝に氷点下となり、最低−2度の見込み"

    def test_already_freezing_says_nothing(self):
        from linecast._weather_sections import freeze_sentence
        hourly = self._hourly(NOON, 6, temperature_2m=[30, 28, 26, 25, 25, 26])
        assert freeze_sentence(hourly, {"temperature_2m": 30}, NOON, _runtime()) == ""

    def test_the_heat_ahead_names_its_cause(self):
        from linecast._weather_sections import feels_ahead_sentence
        temps = [82, 85, 88, 90, 90, 88, 85]
        feels = [84, 89, 95, 98, 97, 93, 88]
        # 98°F feels like 36.7°C: past the mark; 89 and 95 are not
        hourly = self._hourly(NOON, len(temps), temperature_2m=temps, apparent_temperature=feels)
        assert feels_ahead_sentence(hourly, NOON, _runtime()) == \
            "It will feel as high as 98° this afternoon"
        hourly.update(relative_humidity_2m=[70] * 7, wind_speed_10m=[3] * 7)
        assert feels_ahead_sentence(hourly, NOON, _runtime()) == \
            "High humidity will make it feel as high as 98° this afternoon"

        def to_c(t):
            return (t - 32) * 5 / 9

        hourly.update(temperature_2m=[to_c(t) for t in temps],
                      apparent_temperature=[to_c(t) for t in feels])
        assert feels_ahead_sentence(hourly, NOON, _runtime(lang="ja", celsius=True)) == \
            "湿度が高く、午後には体感温度が37度まで上がる見込み"

    def test_the_cold_ahead_names_the_wind(self):
        from linecast._weather_sections import feels_ahead_sentence
        hourly = self._hourly(NOON, 6, temperature_2m=[-5, -6, -8, -9, -9, -8],
                              apparent_temperature=[-12, -14, -17, -19, -18, -16],
                              relative_humidity_2m=[70] * 6, wind_speed_10m=[35] * 6)
        assert feels_ahead_sentence(hourly, NOON, _runtime(celsius=True, metric=True)) == \
            "The wind will make it feel as low as −19° this afternoon"

    def test_what_the_place_is_used_to_is_not_news(self):
        # Hong Kong in September: every afternoon feels five degrees hotter
        from linecast._weather_sections import feels_ahead_sentence
        day = [28, 29, 31, 32, 32, 31, 29] + [28] * 17
        felt = [31, 33, 36, 37, 37, 36, 33] + [31] * 17
        hourly = self._hourly(NOON, 24 * 4, temperature_2m=day * 4, apparent_temperature=felt * 4)
        assert feels_ahead_sentence(hourly, NOON, _runtime(celsius=True, metric=True)) == ""
        # ...until a day stands out from the others
        hourly["apparent_temperature"] = felt[:4] + [40, 36, 33] + [31] * 17 + felt * 3
        assert feels_ahead_sentence(hourly, NOON, _runtime(celsius=True, metric=True)) == \
            "It will feel as high as 40° this afternoon"

    def test_dangerous_heat_is_said_regardless(self):
        from linecast._weather_sections import feels_ahead_sentence
        day = [38, 40, 42, 43, 43, 42, 40] + [36] * 17
        felt = [42, 44, 46, 47, 47, 46, 44] + [39] * 17
        hourly = self._hourly(NOON, 24 * 4, temperature_2m=day * 4, apparent_temperature=felt * 4)
        assert feels_ahead_sentence(hourly, NOON, _runtime(celsius=True, metric=True)) == \
            "It will feel as high as 47° this afternoon"

    def test_warm_but_not_extreme_says_nothing(self):
        from linecast._weather_sections import feels_ahead_sentence
        hourly = self._hourly(NOON, 4, temperature_2m=[80, 82, 82, 80],
                              apparent_temperature=[84, 88, 88, 84])
        assert feels_ahead_sentence(hourly, NOON, _runtime()) == ""

    def test_the_comparison_carries_the_number(self):
        from linecast._weather_sections import comparative_sentence
        daily = {"temperature_2m_max": [60, 68, 55]}
        assert comparative_sentence(daily, NOON, _runtime()) == \
            "Today will be 8° warmer than yesterday"
        assert comparative_sentence(daily, NOON.replace(hour=16), _runtime()) == \
            "Tomorrow will be 13° cooler than today"
        assert comparative_sentence(daily, NOON, _runtime(lang="ja")) == \
            "今日は昨日より8度暖かくなる"
        assert comparative_sentence({"temperature_2m_max": [60, 61, 55]}, NOON, _runtime()) == \
            "Today will be about the same temperature as yesterday"


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
            "Today will be about the same temperature as yesterday. "
            "The wind is making it feel cooler. "
            "Rain starting in a couple hours, with gusts to 30mph. "
            "1.50″ of rain in the last 24h.")

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
        assert "Rain ending shortly." in prose
        assert "Gusts to 45mph this afternoon." in prose
        assert "with gusts" not in prose

    def test_a_quiet_day_keeps_the_old_order(self):
        data = {"current": self._busy_day()["current"],
                "daily": dict(DAILY, temperature_2m_max=[60, 61, 63]), "hourly": {}}
        assert self._prose(data) == (
            "Today will be about the same temperature as yesterday. "
            "The wind is making it feel cooler.")

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
            "Tomorrow will be about the same temperature as today. "
            "High humidity will make it feel as high as 96° in the afternoon.")

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
            "Tomorrow will be about the same temperature as today. "
            "Drizzle starting in the afternoon, with gusts to 26mph.")
        assert self._prose(data, night, lang="ja") == (
            "明日は今日とほぼ同じ気温になる。"
            "午後に霧雨となる。風も強まり、最大26mphの突風。")


class TestDegreesAsWords:
    """Where the language counts its degrees in words, the word agrees
    with the number and the case."""

    def _diff(self, lang, diff):
        from linecast._weather_sections import comparative_sentence
        rt = _runtime(lang=lang, celsius=True, metric=True)
        return comparative_sentence({"temperature_2m_max": [10, 10 + diff, 10]}, NOON, rt)

    def _low(self, lang, low):
        from linecast._weather_sections import freeze_sentence
        rt = _runtime(lang=lang, celsius=True, metric=True)
        temps = [3, 2, 1, low, low, 1]
        hourly = {"time": [(NOON + timedelta(hours=k)).isoformat(timespec="minutes")
                           for k in range(len(temps))], "temperature_2m": temps}
        return freeze_sentence(hourly, {"temperature_2m": 3}, NOON, rt)

    def test_slavic_counting_forms_after_the_difference(self):
        assert self._diff("ru", 3) == "Сегодня будет на 3 градуса теплее, чем вчера"
        assert self._diff("ru", 5) == "Сегодня будет на 5 градусов теплее, чем вчера"
        assert self._diff("ru", 21) == "Сегодня будет на 21 градус теплее, чем вчера"
        assert self._diff("pl", 3) == "Dziś będzie o 3 stopnie cieplej niż wczoraj"
        assert self._diff("pl", 5) == "Dziś będzie o 5 stopni cieplej niż wczoraj"
        assert self._diff("cs", 3) == "Dnes bude o 3 stupně tepleji než včera"
        assert self._diff("cs", 5) == "Dnes bude o 5 stupňů tepleji než včera"

    def test_slavic_genitive_after_down_to(self):
        assert self._low("ru", -2) == "Сегодня днём мороз, до −2 градусов"
        assert self._low("ru", -1) == "Сегодня днём мороз, до −1 градуса"
        assert self._low("uk", -2) == "Сьогодні вдень мороз, до −2 градусів"
        assert self._low("pl", -2) == "Mróz dziś po południu, do −2 stopni"
        assert self._low("pl", -1) == "Mróz dziś po południu, do −1 stopnia"

    def test_icelandic_dative_for_the_difference_only(self):
        assert self._diff("is", 3) == "Í dag verður 3 stigum hlýrra en í gær"
        assert self._low("is", -2) == "Frost í dag eftir hádegi, niður í −2 stig"

    def test_one_degree_and_twenty_degrees(self):
        assert self._low("fi", -1) == "Pakkasta tänä iltapäivänä, alimmillaan −1 aste"
        assert self._low("da", -1) == "Frost i eftermiddag, ned til −1 grad"
        assert self._diff("ro", 20) == "Azi va fi cu 20 de grade mai cald decât ieri"
        assert self._diff("ro", 3) == "Azi va fi cu 3 grade mai cald decât ieri"


class TestAgreementAndTheClock:
    """Templates agree with their nouns in every language that inflects,
    and only English and Greek carry a 12-hour time in a sentence."""

    def _later(self, lang, code, prob=70, **overrides):
        from linecast._weather_sections import precipitation_sentence
        codes = [0, 0, 0, 0, code, code, code, 0]
        hourly = {"time": [(NOON + timedelta(hours=k)).isoformat(timespec="minutes")
                           for k in range(len(codes))],
                  "weather_code": codes,
                  "precipitation_probability": [prob if c else 0 for c in codes]}
        return precipitation_sentence(hourly, NOON, _runtime(lang=lang, celsius=True, metric=True,
                                                             **overrides))

    def test_romance_plurals_and_french_elision(self):
        assert self._later("fr", 81) == "Averses probables vers 16h"
        assert self._later("fr", 81, 40) == "Risque d'averses vers 16h"
        assert self._later("fr", 61, 40) == "Risque de pluie légère vers 16h"
        assert self._later("es", 95) == "Tormentas probables hacia las 16:00"
        assert self._later("es", 63) == "Lluvia probable hacia las 16:00"
        assert self._later("pt", 81) == "Pancadas de chuva prováveis por volta das 16h"
        assert self._later("it", 81) == "Rovesci probabili verso le 16"
        assert self._later("ro", 81, 90) == "Averse, încep în jur de 16:00"
        assert self._later("ro", 63, 90) == "Ploaie, începe în jur de 16:00"

    def test_finnish_and_czech_plural_verbs(self):
        from linecast._weather_sections import precipitation_sentence
        codes = [81, 81, 81, 0]
        hourly = {"time": [(NOON + timedelta(hours=k)).isoformat(timespec="minutes")
                           for k in range(len(codes))],
                  "weather_code": codes, "precipitation_probability": [90, 90, 90, 0]}
        assert precipitation_sentence(hourly, NOON, _runtime(lang="fi", metric=True)) == \
            "Kuurot loppuvat parin tunnin kuluttua"
        assert precipitation_sentence(hourly, NOON, _runtime(lang="cs", metric=True)) == \
            "Přeháňky skončí za pár hodin"
        assert self._later("cs", 81) == "Přeháňky pravděpodobně začnou kolem 16:00"
        assert self._later("cs", 63) == "Déšť pravděpodobně začne kolem 16:00"
        assert self._later("da", 81) == "Sandsynligvis byger omkring kl. 16"

    def test_only_english_and_greek_take_the_twelve_hour_clock_in_a_sentence(self):
        # A French reader looking at Montréal, where the clock is 12-hour
        assert self._later("fr", 63, 90, use_24h=False) == "Pluie débutant vers 16h"
        assert self._later("en", 63, 90, use_24h=False) == "Rain starting around 4pm"
        assert self._later("el", 63, 90, use_24h=False) == \
            "Βροχές θα αρχίσουν γύρω στις 4 το απόγευμα"
        assert self._later("es", 63, 90, use_24h=False) == "Lluvia comenzando hacia las 16:00"


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
            "Gusts to 42mph tomorrow morning. It will be 5° cooler than today.")
        assert self._prose(data, night, lang="ja") == (
            "明日の朝に最大42mphの突風の見込み。今日より5度涼しくなる。")

    def test_rain_after_the_comparison_inherits_tomorrow(self):
        night = datetime(2026, 7, 15, 21, 0)
        hours = [night + timedelta(hours=k) for k in range(26)]
        codes = [0] * 17 + [61] * 4 + [0] * 5
        data = {"daily": dict(DAILY, temperature_2m_max=[70, 72, 67]),
                "hourly": {"time": [h.isoformat(timespec="minutes") for h in hours],
                           "weather_code": codes,
                           "precipitation_probability": [90 if c else 0 for c in codes]}}
        assert self._prose(data, night) == (
            "Tomorrow will be 5° cooler than today. Light rain starting in the afternoon.")

    def test_today_is_never_repeated_so_never_elided(self):
        data = {"daily": dict(DAILY, temperature_2m_max=[70, 75, 67]), "hourly": {}}
        assert self._prose(data, NOON) == "Today will be 5° warmer than yesterday."

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
            "Tomorrow will be about the same temperature as today.")
