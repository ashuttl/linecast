"""The shared string-table lookup behind _s, _ts, _ms, rs and ms."""

from datetime import datetime
from types import SimpleNamespace

from linecast._i18n import lang_of, lookup
from linecast._maps_i18n import ms
from linecast._moon_i18n import _ms
from linecast._radar_i18n import rs
from linecast._tides_i18n import _ts
from linecast._weather_i18n import DAY_NAMES, WMO_NAMES_I18N, _s
from linecast._weather_sections import (
    _past_precip_line,
    _precipitation_line,
    comparative_sentence,
)

TABLE = {
    "en": {"hello": "Hello", "count": "{n} items", "braces": "{literal}"},
    "fr": {"hello": "Bonjour"},
}


class TestLookup:
    def test_language_then_english_then_key(self):
        assert lookup(TABLE, "hello", "fr") == "Bonjour"
        assert lookup(TABLE, "count", "fr", n=2) == "2 items"
        assert lookup(TABLE, "missing", "fr") == "missing"
        assert lookup(TABLE, "hello", "xx") == "Hello"

    def test_formats_only_when_given_kwargs(self):
        assert lookup(TABLE, "braces", "en") == "{literal}"


class TestLangOf:
    def test_runtime_language_or_english(self):
        assert lang_of(SimpleNamespace(lang="de")) == "de"
        assert lang_of(SimpleNamespace()) == "en"
        assert lang_of(None) == "en"


class TestWrappers:
    def test_each_command_helper_reads_its_own_table(self):
        fr = SimpleNamespace(lang="fr")
        assert _s("feels", fr) != _s("feels", None)
        assert _ts("space_to_now", fr) != _ts("space_to_now", None)
        assert _ms("up_now", fr) != _ms("up_now", None)
        assert rs("loading", "fr") != rs("loading", "en")
        assert ms("hint", "fr") != ms("hint", "en")
        assert _s("no_such_key", fr) == "no_such_key"


class TestPolishWeather:
    def test_comparative_sentence_is_idiomatic(self):
        runtime = SimpleNamespace(lang="pl", celsius=True)
        daily = {"temperature_2m_max": [20, 21, 22]}

        sentence = comparative_sentence(daily, datetime(2026, 8, 24, 15), runtime)

        assert sentence == "Jutro b\u0119dzie mniej wi\u0119cej tak samo ciep\u0142o jak dzi\u015b"

    def test_weekdays_use_standard_abbreviations(self):
        assert DAY_NAMES["pl"] == [
            "pon.", "wt.", "\u015br.", "czw.", "pt.", "sob.", "niedz.",
        ]

    def test_historical_comparison_spells_out_average(self):
        runtime = SimpleNamespace(lang="pl")
        assert _s("hist_below_avg", runtime, diff="3\u00b0") == "3\u00b0 poni\u017cej \u015bredniej"

    def test_metric_units_are_separated(self):
        runtime = SimpleNamespace(lang="pl")
        assert _s("metric_unit_sep", runtime) == " "


class TestUkrainianWeather:
    def test_comparative_sentences_are_idiomatic(self):
        runtime = SimpleNamespace(lang="uk", celsius=True)
        now = datetime(2026, 8, 24, 15)
        warmer = comparative_sentence({"temperature_2m_max": [20, 21, 24]}, now, runtime)
        same = comparative_sentence({"temperature_2m_max": [20, 21, 22]}, now, runtime)
        assert warmer == "Завтра буде на 3 градуси тепліше, ніж сьогодні"
        assert same == "Завтра буде приблизно так само тепло, як сьогодні"

    def test_precipitation_phrases_read_as_clock_times(self):
        runtime = SimpleNamespace(lang="uk", use_24h=True)
        now = datetime(2026, 8, 24, 12, 10)
        hourly = {
            "time": [f"2026-08-24T{h:02d}:00" for h in range(12, 18)],
            "precipitation_probability": [0, 0, 0, 0, 0, 70],
            "weather_code": [0, 0, 0, 0, 0, 95],
        }
        line = _precipitation_line(hourly, now, runtime)
        assert "Гроза, ймовірно, почнеться близько 17:00" in line

    def test_past_precipitation_takes_the_genitive(self):
        runtime = SimpleNamespace(lang="uk", metric=True, precip_unit="mm")
        now = datetime(2026, 8, 24, 12)
        hourly = {"time": ["2026-08-24T11:00"], "precipitation": [4.0],
                  "snowfall": [0], "weather_code": [63]}
        assert "4.0 мм дощу за останні 24 год" in _past_precip_line(hourly, now, runtime)

    def test_weekdays_use_standard_abbreviations(self):
        assert DAY_NAMES["uk"] == ["пн", "вт", "ср", "чт", "пт", "сб", "нд"]

    def test_historical_comparison_speaks_of_the_norm(self):
        runtime = SimpleNamespace(lang="uk")
        assert _s("hist_below_avg", runtime, diff="3°") == "3° нижче норми"


class TestVietnameseWeather:
    def test_comparative_sentences_are_idiomatic(self):
        runtime = SimpleNamespace(lang="vi", celsius=True)
        now = datetime(2026, 8, 24, 15)
        warmer = comparative_sentence({"temperature_2m_max": [20, 21, 24]}, now, runtime)
        same = comparative_sentence({"temperature_2m_max": [20, 21, 22]}, now, runtime)
        assert warmer == "Ngày mai sẽ ấm hơn hôm nay 3 độ"
        assert same == "Ngày mai sẽ có nhiệt độ gần bằng hôm nay"

    def test_precipitation_phrases_read_as_vietnamese_clock_times(self):
        # 17h is how Vietnamese writes five in the afternoon.
        runtime = SimpleNamespace(lang="vi", use_24h=True)
        now = datetime(2026, 8, 24, 12, 10)
        hourly = {
            "time": [f"2026-08-24T{h:02d}:00" for h in range(12, 18)],
            "precipitation_probability": [0, 0, 0, 0, 0, 70],
            "weather_code": [0, 0, 0, 0, 0, 95],
        }
        assert "Mưa dông có thể bắt đầu vào khoảng 17h" in _precipitation_line(hourly, now, runtime)

    def test_past_precipitation_sets_the_unit_off_with_a_space(self):
        runtime = SimpleNamespace(lang="vi", metric=True, precip_unit="mm")
        now = datetime(2026, 8, 24, 12)
        hourly = {"time": ["2026-08-24T11:00"], "precipitation": [4.0],
                  "snowfall": [0], "weather_code": [63]}
        assert "4.0 mm mưa trong 24 giờ qua" in _past_precip_line(hourly, now, runtime)

    def test_weekdays_are_numbered_from_monday_as_the_second_day(self):
        assert DAY_NAMES["vi"] == ["T2", "T3", "T4", "T5", "T6", "T7", "CN"]


class TestEsperantoWeather:
    def test_comparative_sentences_are_impersonal(self):
        """The weather is an adverb in Esperanto: "estas varme", not "varma"."""
        runtime = SimpleNamespace(lang="eo", celsius=True)
        now = datetime(2026, 8, 24, 15)
        warmer = comparative_sentence({"temperature_2m_max": [20, 21, 24]}, now, runtime)
        same = comparative_sentence({"temperature_2m_max": [20, 21, 22]}, now, runtime)
        assert warmer == "Morgaŭ estos je 3 gradoj pli varme ol hodiaŭ"
        assert same == "Morgaŭ estos proksimume same varme kiel hodiaŭ"

    def test_precipitation_phrases_read_as_clock_times(self):
        runtime = SimpleNamespace(lang="eo", use_24h=True)
        now = datetime(2026, 8, 24, 12, 10)
        hourly = {
            "time": [f"2026-08-24T{h:02d}:00" for h in range(12, 18)],
            "precipitation_probability": [0, 0, 0, 0, 0, 70],
            "weather_code": [0, 0, 0, 0, 0, 95],
        }
        line = _precipitation_line(hourly, now, runtime)
        assert "Fulmotondro verŝajne komenciĝos ĉirkaŭ 17:00" in line

    def test_past_precipitation_takes_da(self):
        runtime = SimpleNamespace(lang="eo", metric=True, precip_unit="mm")
        now = datetime(2026, 8, 24, 12)
        hourly = {"time": ["2026-08-24T11:00"], "precipitation": [4.0],
                  "snowfall": [0], "weather_code": [63]}
        assert "4.0 mm da pluvo en la lastaj 24 h" in _past_precip_line(hourly, now, runtime)

    def test_weekdays_use_standard_abbreviations(self):
        assert DAY_NAMES["eo"] == ["lun", "mar", "mer", "ĵaŭ", "ven", "sab", "dim"]


class TestTurkishWeather:
    def test_comparative_sentences_carry_the_suffix_in_the_template(self):
        """The reference day takes a case suffix, "bugünden", "dünle"."""
        runtime = SimpleNamespace(lang="tr", celsius=True)
        now = datetime(2026, 8, 24, 15)
        warmer = comparative_sentence({"temperature_2m_max": [20, 21, 24]}, now, runtime)
        same = comparative_sentence({"temperature_2m_max": [20, 21, 22]}, now, runtime)
        earlier = comparative_sentence({"temperature_2m_max": [20, 24, 22]},
                                       datetime(2026, 8, 24, 9), runtime)
        assert warmer == "Yarın bugünden 3 derece daha sıcak olacak"
        assert same == "Yarın bugünle yaklaşık aynı sıcaklıkta olacak"
        assert earlier == "Bugün dünden 4 derece daha sıcak olacak"

    def test_precipitation_phrases_read_as_clock_times(self):
        runtime = SimpleNamespace(lang="tr", use_24h=True)
        now = datetime(2026, 8, 24, 12, 10)
        hourly = {
            "time": [f"2026-08-24T{h:02d}:00" for h in range(12, 18)],
            "precipitation_probability": [0, 0, 0, 0, 0, 70],
            "weather_code": [0, 0, 0, 0, 0, 95],
        }
        line = _precipitation_line(hourly, now, runtime)
        assert "Gök gürültülü fırtına muhtemelen 17:00 civarında başlayacak" in line

    def test_past_precipitation_puts_the_span_first(self):
        runtime = SimpleNamespace(lang="tr", metric=True, precip_unit="mm")
        now = datetime(2026, 8, 24, 12)
        hourly = {"time": ["2026-08-24T11:00"], "precipitation": [4.0],
                  "snowfall": [0], "weather_code": [63]}
        assert "Son 24 saatte 4.0 mm yağmur" in _past_precip_line(hourly, now, runtime)

    def test_weekdays_use_standard_abbreviations(self):
        assert DAY_NAMES["tr"] == ["Pzt", "Sal", "Çar", "Per", "Cum", "Cmt", "Paz"]


class TestRussianWeather:
    def test_comparative_sentences_are_idiomatic(self):
        runtime = SimpleNamespace(lang="ru", celsius=True)
        now = datetime(2026, 8, 24, 15)
        warmer = comparative_sentence({"temperature_2m_max": [20, 21, 24]}, now, runtime)
        same = comparative_sentence({"temperature_2m_max": [20, 21, 22]}, now, runtime)
        assert warmer == "Завтра будет на 3 градуса теплее, чем сегодня"
        assert same == "Завтра будет примерно так же тепло, как сегодня"

    def test_precipitation_phrases_read_as_clock_times(self):
        runtime = SimpleNamespace(lang="ru", use_24h=True)
        now = datetime(2026, 8, 24, 12, 10)
        hourly = {
            "time": [f"2026-08-24T{h:02d}:00" for h in range(12, 18)],
            "precipitation_probability": [0, 0, 0, 0, 0, 70],
            "weather_code": [0, 0, 0, 0, 0, 95],
        }
        line = _precipitation_line(hourly, now, runtime)
        assert "Гроза, вероятно, начнётся около 17:00" in line

    def test_the_preposition_changes_shape_before_tuesday(self):
        """"в пн" but "во вт", as Russian writes it before вт."""
        from linecast._weather_i18n import ON_DAY_FORMS
        days = DAY_NAMES["ru"]
        phrases = [ON_DAY_FORMS["ru"].get(i, _s("on_day", SimpleNamespace(lang="ru")))
                   .format(day=days[i]) for i in range(7)]
        assert phrases == ["в пн", "во вт", "в ср", "в чт", "в пт", "в сб", "в вс"]

    def test_past_precipitation_takes_the_genitive(self):
        runtime = SimpleNamespace(lang="ru", metric=True, precip_unit="mm")
        now = datetime(2026, 8, 24, 12)
        hourly = {"time": ["2026-08-24T11:00"], "precipitation": [4.0],
                  "snowfall": [0], "weather_code": [63]}
        assert "4.0 мм дождя за последние 24 ч" in _past_precip_line(hourly, now, runtime)

    def test_weekdays_use_standard_abbreviations(self):
        assert DAY_NAMES["ru"] == ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]


class TestRomanianWeather:
    def test_comparative_sentences_are_idiomatic(self):
        runtime = SimpleNamespace(lang="ro", celsius=True)
        now = datetime(2026, 8, 24, 15)
        warmer = comparative_sentence({"temperature_2m_max": [20, 21, 24]}, now, runtime)
        same = comparative_sentence({"temperature_2m_max": [20, 21, 22]}, now, runtime)
        assert warmer == "Mâine va fi cu 3 grade mai cald decât azi"
        assert same == "Mâine va fi cam la fel de cald ca azi"

    def test_precipitation_phrases_are_notes_on_the_kind(self):
        """"Ploaie" is indefinite, so the line is a note, not a clause."""
        runtime = SimpleNamespace(lang="ro", use_24h=True)
        now = datetime(2026, 8, 24, 12, 10)
        hourly = {
            "time": [f"2026-08-24T{h:02d}:00" for h in range(12, 18)],
            "precipitation_probability": [0, 0, 0, 0, 0, 70],
            "weather_code": [0, 0, 0, 0, 0, 95],
        }
        assert "Furtună probabil în jur de 17:00" in _precipitation_line(hourly, now, runtime)
        hourly["weather_code"] = [63, 63, 63, 63, 63, 0]
        hourly["precipitation_probability"] = [80, 80, 80, 80, 80, 0]
        assert "Ploaie, încetează în jur de 17:00" in _precipitation_line(hourly, now, runtime)

    def test_past_precipitation_takes_de(self):
        runtime = SimpleNamespace(lang="ro", metric=True, precip_unit="mm")
        now = datetime(2026, 8, 24, 12)
        hourly = {"time": ["2026-08-24T11:00"], "precipitation": [4.0],
                  "snowfall": [0], "weather_code": [63]}
        assert "4.0 mm de ploaie în ultimele 24 h" in _past_precip_line(hourly, now, runtime)

    def test_weekdays_use_standard_abbreviations(self):
        assert DAY_NAMES["ro"] == ["lun", "mar", "mie", "joi", "vin", "sâm", "dum"]


class TestCzechWeather:
    def test_comparative_sentences_are_idiomatic(self):
        runtime = SimpleNamespace(lang="cs", celsius=True)
        now = datetime(2026, 8, 24, 15)
        warmer = comparative_sentence({"temperature_2m_max": [20, 21, 24]}, now, runtime)
        same = comparative_sentence({"temperature_2m_max": [20, 21, 22]}, now, runtime)
        assert warmer == "Zítra bude o 3 stupně tepleji než dnes"
        assert same == "Zítra bude přibližně stejně teplo jako dnes"

    def test_precipitation_phrases_read_as_clock_times(self):
        runtime = SimpleNamespace(lang="cs", use_24h=True)
        now = datetime(2026, 8, 24, 12, 10)
        hourly = {
            "time": [f"2026-08-24T{h:02d}:00" for h in range(12, 18)],
            "precipitation_probability": [0, 0, 0, 0, 0, 70],
            "weather_code": [0, 0, 0, 0, 0, 95],
        }
        assert "Bouřka pravděpodobně začne kolem 17:00" in _precipitation_line(hourly, now, runtime)

    def test_the_preposition_changes_shape_before_wednesday_and_thursday(self):
        """"v po" but "ve st" and "ve čt", as Czech writes it."""
        from linecast._weather_i18n import ON_DAY_FORMS
        days = DAY_NAMES["cs"]
        phrases = [ON_DAY_FORMS["cs"].get(i, _s("on_day", SimpleNamespace(lang="cs")))
                   .format(day=days[i]) for i in range(7)]
        assert phrases == ["v po", "v út", "ve st", "ve čt", "v pá", "v so", "v ne"]

    def test_past_precipitation_takes_the_genitive(self):
        runtime = SimpleNamespace(lang="cs", metric=True, precip_unit="mm")
        now = datetime(2026, 8, 24, 12)
        hourly = {"time": ["2026-08-24T11:00"], "precipitation": [4.0],
                  "snowfall": [0], "weather_code": [63]}
        assert "4.0 mm deště za posledních 24 h" in _past_precip_line(hourly, now, runtime)

    def test_the_percent_sign_is_set_off_with_a_space(self):
        from linecast._i18n import fmt_percent
        assert fmt_percent(40, SimpleNamespace(lang="cs")) == "40 %"
        assert fmt_percent(40, SimpleNamespace(lang="ru")) == "40%"
        assert fmt_percent(40, SimpleNamespace(lang="ro")) == "40%"

    def test_weekdays_use_standard_abbreviations(self):
        assert DAY_NAMES["cs"] == ["po", "út", "st", "čt", "pá", "so", "ne"]


class TestSwahili:
    def test_comparative_sentences_and_precipitation(self):
        runtime = SimpleNamespace(lang="sw", celsius=True, use_24h=True,
                                  metric=True, precip_unit="mm")
        now = datetime(2026, 8, 24, 15)
        assert comparative_sentence({"temperature_2m_max": [20, 21, 24]}, now, runtime) == (
            "Joto la kesho litakuwa nyuzi 3 juu kuliko la leo")
        assert comparative_sentence({"temperature_2m_max": [20, 21, 22]}, now, runtime) == (
            "Joto la kesho litakuwa karibu sawa na la leo")
        assert comparative_sentence({"temperature_2m_max": [20, 21, 22]},
                                    now.replace(hour=9), runtime) == (
            "Joto la leo litakuwa karibu sawa na la jana")
        assert comparative_sentence({"temperature_2m_max": [20, 21, 18]}, now, runtime) == (
            "Joto la kesho litakuwa nyuzi 3 chini kuliko la leo")
        hourly = {"time": [f"2026-08-24T{h:02d}:00" for h in range(12, 18)],
                  "precipitation_probability": [0, 0, 0, 0, 0, 70],
                  "weather_code": [0, 0, 0, 0, 0, 95]}
        assert "Mvua ya radi huenda ikaanza karibu saa 17:00" in _precipitation_line(
            hourly, now.replace(hour=12, minute=10), runtime)
        hourly = {"time": ["2026-08-24T14:00"], "precipitation": [4.0],
                  "snowfall": [0], "weather_code": [63]}
        assert "Kiasi cha mvua katika saa 24 zilizopita: 4.0 mm" in _past_precip_line(
            hourly, now, runtime)

    def test_precipitation_verbs_agree_when_starting_ending_or_continuing(self):
        from linecast._weather_sections import precipitation_sentence
        runtime = SimpleNamespace(lang="sw", use_24h=True)
        now = datetime(2026, 8, 24, 12, 10)
        times = [f"2026-08-24T{h:02d}:00" for h in range(12, 15)]
        for code in (51, 53, 55, 56, 57, 61, 73, 95):
            drizzle = code in (51, 53, 55, 56, 57)
            desc = WMO_NAMES_I18N["sw"][code]
            for codes, suffix in (
                ([0, code, code], "huenda yakaanza" if drizzle else "huenda ikaanza"),
                ([code, 0, 0], "yataisha" if drizzle else "itaisha"),
                ([code] * 3, "yataendelea" if drizzle else "itaendelea"),
            ):
                hourly = {"time": times, "weather_code": codes,
                          "precipitation_probability": [70 if c else 0 for c in codes]}
                when = "siku nzima" if codes == [code] * 3 else "hivi karibuni"
                assert precipitation_sentence(hourly, now, runtime) == f"{desc} {suffix} {when}"

    def test_calendar_labels_remain_distinct_in_narrow_columns(self):
        from linecast._moon_i18n import _fmt_month_day
        from linecast._sunshine_i18n import axis_month_labels, relative_day
        runtime = SimpleNamespace(lang="sw")
        assert DAY_NAMES["sw"] == ["J3", "J4", "J5", "Alh", "Ij", "J1", "J2"]
        assert len({name[:2] for name in DAY_NAMES["sw"]}) == 7
        assert _fmt_month_day(datetime(2026, 8, 24), runtime) == "24 Ago"
        assert axis_month_labels(runtime)[2] == "Mac"
        assert relative_day(-1, runtime) == "siku 1 iliyopita"
        assert relative_day(-2, runtime) == "siku 2 zilizopita"

    def test_season_events_name_the_month_in_both_hemispheres(self):
        from linecast._moon_i18n import _season_label
        runtime = SimpleNamespace(lang="sw")
        for event, month in enumerate(("Machi", "Juni", "Septemba", "Desemba")):
            assert _season_label(event, -6.8, runtime).endswith(month)
            assert _season_label(event, 51.5, runtime).endswith(month)


class TestTurkishPercentAndUnits:
    def test_the_percent_sign_leads_in_turkish(self):
        from linecast._i18n import fmt_percent
        assert fmt_percent(40, SimpleNamespace(lang="tr")) == "%40"
        assert fmt_percent(40.4, SimpleNamespace(lang="en")) == "40%"
        assert fmt_percent(40, None) == "40%"

    def test_the_wind_reads_km_sa_on_screen_and_km_h_in_json(self):
        from linecast._runtime import WeatherRuntime
        defaults = dict(live=False, icons="emoji", oneline=False, celsius=True,
                        metric=True, shading=False)
        turkish = WeatherRuntime(lang="tr", **defaults)
        english = WeatherRuntime(lang="en", **defaults)
        assert turkish.wind_unit_label == "km/sa"
        assert turkish.wind_unit == "km/h"
        assert english.wind_unit_label == "km/h"
        imperial = WeatherRuntime(lang="tr", **{**defaults, "metric": False})
        assert imperial.wind_unit_label == "mph"


class TestTablesComplete:
    """Every language table carries every English key, so nothing falls
    back to English unnoticed (issue #111). The exceptions are keys whose
    English text is the default the other languages share by design."""

    # A unit that reads the same in most languages is written once, in
    # English, and only the languages that spell it differently carry it.
    # The Canadian index is named AQHI in English and CAS (cote air
    # santé) in French, and by its English name elsewhere.
    DEFAULTS = {
        "linecast._weather_i18n": {"unit_kmh", "unit_mm", "unit_cm", "aqhi"},
        "linecast._radar_i18n": {"unit_km"},
    }
    # Keys a language needs that English does not: the Slavic few-form,
    # Romanian's one and its "de" form for a count of days, and a dawn
    # and a dusk word where one twilight word will not do.
    EXTRAS = {"linecast._sunshine_i18n": {"in_days_few", "days_ago_few"},
              "linecast._moon_i18n": {"in_days_one", "in_days_many"}}
    # Variants of an English key: Greek's one o'clock, the precipitation
    # noun classes (Swahili ma-, the French, Finnish and Czech plurals),
    # and the dative "by" a time of day in Russian and Ukrainian.
    VARIANTS = {"linecast._sunshine_i18n": ("_dawn", "_dusk"),
                "linecast._weather_i18n": ("_one", "_ma", "_pl", "_by", "_few", "_many", "_diff",
                                           "_diff_one", "_diff_few", "_then")}

    def _tables(self):
        import importlib
        import pkgutil
        import linecast
        for info in pkgutil.walk_packages(linecast.__path__, "linecast."):
            if "i18n" not in info.name:
                continue
            module = importlib.import_module(info.name)
            for name, obj in vars(module).items():
                if isinstance(obj, dict) and isinstance(obj.get("en"), dict):
                    yield info.name, name, obj

    def test_every_language_has_every_english_key(self):
        from linecast._i18n import LANGUAGE_CODES
        gaps = []
        for module, name, table in self._tables():
            # A variant English happens to carry is optional elsewhere too
            suffixes = self.VARIANTS.get(module, ())
            english = {key for key in table["en"]
                       if not any(key.endswith(end) and key[:-len(end)] in table["en"]
                                  for end in suffixes)} - self.DEFAULTS.get(module, set())
            for lang in LANGUAGE_CODES:
                missing = sorted(english - set(table.get(lang, {})))
                if missing:
                    gaps.append(f"{module}.{name} {lang}: {missing}")
        assert not gaps, "\n".join(gaps)

    def test_no_language_carries_a_key_english_does_not(self):
        dead = []
        for module, name, table in self._tables():
            english = set(table["en"]) | self.EXTRAS.get(module, set())
            suffixes = self.VARIANTS.get(module, ())
            for lang, strings in table.items():
                extra = sorted(
                    key for key in set(strings) - english
                    if not any(key.endswith(end) and key[:-len(end)] in table["en"]
                               for end in suffixes))
                if extra:
                    dead.append(f"{module}.{name} {lang}: {extra}")
        assert not dead, "\n".join(dead)



class TestRegionalVariants:
    """pt-PT, es-ES, and fr-CA are overlays: a block holds only the keys
    it changes, and a lookup reads through to the base, then English."""

    def _tables(self):
        return TestTablesComplete()._tables()

    def test_a_variant_changes_only_keys_its_base_has(self):
        import re
        from linecast._i18n import VARIANTS
        wrong = []
        for module, name, table in self._tables():
            for variant, base in VARIANTS.items():
                for key, text in table.get(variant, {}).items():
                    if key not in table.get(base, {}):
                        wrong.append(f"{module}.{name} {variant}: {key} is not in {base}")
                        continue
                    if text == table[base][key]:
                        wrong.append(f"{module}.{name} {variant}: {key} is the same as {base}")
                    fields = set(re.findall(r"{\w+}", text))
                    if fields != set(re.findall(r"{\w+}", table[base][key])):
                        wrong.append(f"{module}.{name} {variant}: {key} placeholders differ")
        assert not wrong, "\n".join(wrong)

    def test_a_lookup_reads_the_variant_then_the_base_then_english(self):
        from linecast._i18n import lookup, table_for, has_text
        table = {"en": {"a": "A", "b": "B", "c": "C"}, "pt": {"a": "pt a", "b": "pt b"},
                 "pt-PT": {"a": "PT a"}}
        assert lookup(table, "a", "pt-PT") == "PT a"
        assert lookup(table, "b", "pt-PT") == "pt b"
        assert lookup(table, "c", "pt-PT") == "C"
        assert lookup(table, "d", "pt-PT") == "d"
        assert lookup(table, "a", "pt") == "pt a"
        assert lookup(table, "a", "xx") == "A"
        assert table_for({"en": [1], "pt": [2]}, "pt-PT") == [2]
        assert table_for({"en": [1], "pt": [2], "pt-PT": [3]}, "pt-PT") == [3]
        assert table_for({"en": [1]}, "pt-PT") == [1]
        assert has_text(table, "a", "pt-PT") and has_text(table, "b", "pt-PT")
        assert not has_text(table, "c", "pt-PT") and not has_text(table, "c", "pt")
        assert has_text(table, "c", "en") and has_text(table, "c", "xx")

    def test_the_words_that_differ(self):
        from linecast._weather_i18n import _s, wmo_label
        from linecast._maps_i18n import ms
        from linecast._weather_sections import _precip_descs
        from types import SimpleNamespace as runtime
        pt, pt_pt = runtime(lang="pt"), runtime(lang="pt-PT")
        assert _s("humidity", pt) == "Umidade" and _s("humidity", pt_pt) == "Humidade"
        assert _s("ending", pt, desc="chuva", time="logo") == "chuva terminando logo"
        assert _s("ending", pt_pt, desc="chuva", time="logo") == "chuva a terminar logo"
        assert _s("rain", pt_pt) == "chuva"
        assert wmo_label(81, "pt") == "Pancadas de chuva" and wmo_label(81, "pt-PT") == "Aguaceiros"
        assert wmo_label(63, "pt-PT") == "Chuva"
        assert _precip_descs("pt-PT")[81] == "aguaceiros" and _precip_descs("pt-PT")[63] == "chuva"
        assert _s("retry_key", runtime(lang="es")).startswith("Presione")
        assert _s("retry_key", runtime(lang="es-ES")).startswith("Pulse")
        assert wmo_label(3, "es") == "Nublado" and wmo_label(3, "es-ES") == "Cubierto"
        assert ms("hov_ferry", "fr") == "ferry" and ms("hov_ferry", "fr-CA") == "traversier"
        assert ms("hov_river", "fr-CA") == "rivière"

    def test_canada_spaces_the_hour(self):
        from linecast._framebuffer import fmt_hour_phrase
        assert fmt_hour_phrase(18, True, "fr") == "18h"
        assert fmt_hour_phrase(18, True, "fr-CA") == "18 h"
        assert fmt_hour_phrase(18, True, "es-ES") == "18:00"
        assert fmt_hour_phrase(18, True, "pt-PT") == "18h"

    def test_providers_take_the_base_language(self):
        from linecast._i18n import accept_language, base_language, geocoder_language
        from linecast._weather_sources import alert_source
        assert base_language("pt-PT") == "pt" and base_language("pt") == "pt"
        assert geocoder_language("pt-PT") == "pt" and geocoder_language("es") == "es"
        assert accept_language("fr-CA") == "fr-CA,fr" and accept_language("fr") == "fr"
        assert alert_source("CA", "fr-CA") == alert_source("CA", "fr") == "Environnement Canada"


class TestUnitLabels:
    def _runtime(self, lang, metric=True):
        from linecast._runtime import WeatherRuntime
        return WeatherRuntime(live=False, icons="emoji", oneline=False, celsius=metric,
                              metric=metric, shading=False, lang=lang)

    def test_the_wind_reads_as_the_language_writes_it(self):
        from linecast._weather_i18n import fmt_wind
        assert fmt_wind(12, self._runtime("en")) == "12km/h"
        assert fmt_wind(12, self._runtime("nl")) == "12 km/u"
        assert fmt_wind(12, self._runtime("da")) == "12 km/t"
        assert fmt_wind(12, self._runtime("de")) == "12 km/h"
        assert fmt_wind(12, self._runtime("ja")) == "12km/h"
        assert fmt_wind(12, self._runtime("tr")) == "12 km/sa"
        assert fmt_wind(12, self._runtime("eo")) == "12 km/h"
        assert fmt_wind(12, self._runtime("uk")) == "12 км/год"
        assert fmt_wind(12, self._runtime("th")) == "12 กม./ชม."
        assert fmt_wind(12, self._runtime("tr", metric=False)) == "12mph"

    def test_the_rain_and_the_radar_distance_follow(self):
        from linecast._radar_i18n import rs
        assert self._runtime("uk").precip_unit_label == "мм"
        assert self._runtime("uk").precip_unit == "mm"
        assert self._runtime("fr").precip_unit_label == "mm"
        assert rs("unit_km", "uk") == "км" and rs("unit_km", "fr") == "km"
        near = rs("near", "uk", dist=12, unit=rs("unit_km", "uk"), dir="ПнС", name="Київ")
        assert near == "12 км на ПнС від Київ"


class TestWeatherLocaleImprovements:
    def test_same_temperature_sentences_are_idiomatic(self):
        expected = {
            "fr": "Il fera \u00e0 peu pr\u00e8s aussi chaud demain qu'aujourd'hui",
            "es": "Ma\u00f1ana har\u00e1 una temperatura muy parecida a la de hoy",
            "da": "I morgen bliver det omtrent lige s\u00e5 varmt som i dag",
            "it": "Domani far\u00e0 pi\u00f9 o meno caldo come oggi",
            "nl": "Morgen wordt het ongeveer even warm als vandaag",
            "pt": "Amanh\u00e3 estar\u00e1 aproximadamente t\u00e3o quente quanto hoje",
            "sv": "I morgon blir det ungef\u00e4r lika varmt som i dag",
            "fi": "Huomenna on suunnilleen yht\u00e4 l\u00e4mmint\u00e4 kuin t\u00e4n\u00e4\u00e4n",
            "ko": "\ub0b4\uc77c\uc740 \uc624\ub298 \uc218\uc900\uc758 \uae30\uc628",
        }
        daily = {"temperature_2m_max": [20, 21, 22]}
        now = datetime(2026, 8, 24, 15)

        for lang, sentence in expected.items():
            runtime = SimpleNamespace(lang=lang, celsius=True)
            assert comparative_sentence(daily, now, runtime) == sentence

    def test_finnish_comparatives_use_the_weather_case(self):
        runtime = SimpleNamespace(lang="fi", celsius=True)
        now = datetime(2026, 8, 24, 15)

        warmer = comparative_sentence(
            {"temperature_2m_max": [20, 21, 24]}, now, runtime
        )
        cooler = comparative_sentence(
            {"temperature_2m_max": [20, 21, 18]}, now, runtime
        )

        assert warmer == ("Huomenna on 3 astetta l\u00e4mpim\u00e4mp\u00e4\u00e4 "
                          "kuin t\u00e4n\u00e4\u00e4n")
        assert cooler == ("Huomenna on 3 astetta viile\u00e4mp\u00e4\u00e4 "
                          "kuin t\u00e4n\u00e4\u00e4n")

    def test_standard_german_and_dutch_weekday_abbreviations(self):
        assert DAY_NAMES["de"] == ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
        assert DAY_NAMES["nl"] == ["ma", "di", "wo", "do", "vr", "za", "zo"]

    def test_indonesian_historical_comparison_no_longer_falls_back_to_english(self):
        runtime = SimpleNamespace(lang="id")
        assert _s("hist_near_avg", runtime) == "mendekati rata-rata"
        assert _s("hist_above_avg", runtime, diff="3\u00b0") == "3\u00b0 di atas rata-rata"
        assert _s("hist_below_avg", runtime, diff="3\u00b0") == "3\u00b0 di bawah rata-rata"


class TestJapaneseWeather:
    def test_comparative_sentence_has_no_word_spaces(self):
        runtime = SimpleNamespace(lang="ja", celsius=False)
        daily = {"temperature_2m_max": [70, 80, 80]}

        sentence = comparative_sentence(daily, datetime(2026, 8, 24, 10), runtime)

        assert sentence == "今日は昨日より10度暖かくなる"

    def test_partly_cloudy_is_idiomatic(self):
        assert WMO_NAMES_I18N["ja"][2] == "\u6674\u308c\u6642\u3005\u66c7\u308a"

    def test_forecast_phrases_use_japanese_grammar(self):
        runtime = SimpleNamespace(lang="ja")
        assert (_s("ending", runtime, desc="\u96e8", time="\u307e\u3082\u306a\u304f")
                == "\u96e8\u304c\u307e\u3082\u306a\u304f\u3084\u3080\u898b\u8fbc\u307f")
        assert (_s("continuing", runtime, desc="\u96e8")
                == "\u96e8\u304c\u4e00\u65e5\u4e2d\u7d9a\u304f\u898b\u8fbc\u307f")
        assert _s("on_day", runtime, day="\u706b") == "\u706b\u66dc\u65e5\u306b"

    def test_same_day_forecast_uses_japanese_hour_suffix(self):
        runtime = SimpleNamespace(lang="ja", use_24h=True)
        now = datetime(2026, 8, 24, 12, 10)
        hourly = {
            "time": [
                "2026-08-24T12:00",
                "2026-08-24T13:00",
                "2026-08-24T14:00",
                "2026-08-24T15:00",
                "2026-08-24T16:00",
                "2026-08-24T17:00",
            ],
            "precipitation_probability": [0, 0, 0, 0, 0, 70],
            "weather_code": [0, 0, 0, 0, 0, 63],
        }

        line = _precipitation_line(hourly, now, runtime)

        # Seventy percent is "likely"; eighty and up would drop the hedge
        assert "17時頃に雨の見込み" in line

    def test_past_rain_uses_quantity_term_and_localized_unit(self):
        runtime = SimpleNamespace(lang="ja", metric=False)
        now = datetime(2026, 8, 24, 12)
        hourly = {
            "time": ["2026-08-24T11:00"],
            "precipitation": [0.22],
            "snowfall": [0],
            "weather_code": [63],
        }

        line = _past_precip_line(hourly, now, runtime)

        assert "過去24時間の降水量：0.22インチ" in line


class TestTwilightDirection:
    """Languages with separate dawn and dusk words get the right one."""

    def test_dawn_and_dusk_words_differ_where_the_language_splits(self):
        from linecast._sunshine_i18n import sky_phase
        expected = {
            "pl": ("świt cywilny", "zmierzch cywilny"),
            "id": ("fajar sipil", "senja sipil"),
            "sv": ("borgerlig gryning", "borgerlig skymning"),
            "fr": ("aube civile", "crépuscule civil"),
            "it": ("alba civile", "crepuscolo civile"),
            "de": ("bürgerliche Morgendämmerung",
                   "bürgerliche Abenddämmerung"),
            "zh": ("民用晨光", "民用昏影"),
            "zh-Hant": ("民用晨光", "民用昏影"),
            "uk": ("цивільний світанок", "цивільні сутінки"),
            "vi": ("bình minh dân dụng", "hoàng hôn dân dụng"),
        }
        for lang, (dawn, dusk) in expected.items():
            runtime = SimpleNamespace(lang=lang)
            assert sky_phase(-4, runtime, morning=True) == dawn
            assert sky_phase(-4, runtime, morning=False) == dusk

    def test_generic_words_stay_put_where_the_language_does_not_split(self):
        from linecast._sunshine_i18n import sky_phase
        for lang in ("en", "fi", "ja", "ko", "no", "da", "is"):
            runtime = SimpleNamespace(lang=lang)
            generic = sky_phase(-4, runtime)
            assert sky_phase(-4, runtime, morning=True) == generic
            assert sky_phase(-4, runtime, morning=False) == generic

    def test_no_direction_keeps_the_generic_name(self):
        from linecast._sunshine_i18n import sky_phase
        assert sky_phase(-4, SimpleNamespace(lang="pl")) == "zmierzch cywilny"
        assert sky_phase(-10, SimpleNamespace(lang="pl"),
                         morning=True) == "świt żeglarski"

    def test_day_and_night_ignore_the_direction(self):
        from linecast._sunshine_i18n import sky_phase
        runtime = SimpleNamespace(lang="pl")
        assert sky_phase(10, runtime, morning=True) == sky_phase(10, runtime)
        assert sky_phase(-30, runtime, morning=False) == sky_phase(-30, runtime)

    def test_polish_and_finnish_nautical_terms_are_standard(self):
        from linecast._sunshine_i18n import sky_phase
        assert (sky_phase(-10, SimpleNamespace(lang="pl"), morning=False)
                == "zmierzch żeglarski")
        assert (sky_phase(-10, SimpleNamespace(lang="fi"))
                == "nauttinen hämärä")


class TestRelativeDays:
    def test_scandinavian_ago_keeps_its_preposition(self):
        """'för … sedan' and 'for … siden' wrap the count on both sides."""
        from linecast._sunshine_i18n import relative_day
        expected = {
            "sv": ("för 1 dag sedan", "för 3 dagar sedan"),
            "da": ("for 1 dag siden", "for 3 dage siden"),
            "no": ("for 1 dag siden", "for 3 dager siden"),
        }
        for lang, (one, three) in expected.items():
            runtime = SimpleNamespace(lang=lang)
            assert relative_day(-1, runtime) == one
            assert relative_day(-3, runtime) == three


    def test_ukrainian_counts_days_in_three_forms(self):
        """1, 21 take one form; 2–4, 22–24 another; 5–20 and 11–14 a third."""
        from linecast._sunshine_i18n import relative_day
        runtime = SimpleNamespace(lang="uk")
        expected = {1: "через 1 день", 2: "через 2 дні", 5: "через 5 днів",
                    11: "через 11 днів", 21: "через 21 день", 24: "через 24 дні",
                    -1: "1 день тому", -3: "3 дні тому", -12: "12 днів тому"}
        for diff, text in expected.items():
            assert relative_day(diff, runtime) == text, diff


    def test_russian_counts_days_in_three_forms(self):
        from linecast._sunshine_i18n import relative_day
        runtime = SimpleNamespace(lang="ru")
        expected = {1: "через 1 день", 2: "через 2 дня", 5: "через 5 дней",
                    11: "через 11 дней", 21: "через 21 день", 24: "через 24 дня",
                    -1: "1 день назад", -3: "3 дня назад", -12: "12 дней назад"}
        for diff, text in expected.items():
            assert relative_day(diff, runtime) == text, diff

    def test_czech_counts_one_then_two_to_four_then_the_rest(self):
        """Unlike Russian, 21 and 22 take the plural of five."""
        from linecast._sunshine_i18n import relative_day
        runtime = SimpleNamespace(lang="cs")
        expected = {1: "za 1 den", 2: "za 2 dny", 4: "za 4 dny", 5: "za 5 dní",
                    21: "za 21 dní", 22: "za 22 dní",
                    -1: "před 1 dnem", -3: "před 3 dny", -12: "před 12 dny"}
        for diff, text in expected.items():
            assert relative_day(diff, runtime) == text, diff

    def test_romanian_puts_de_before_the_noun_from_twenty(self):
        from linecast._sunshine_i18n import relative_day
        runtime = SimpleNamespace(lang="ro")
        expected = {1: "peste 1 zi", 2: "peste 2 zile", 19: "peste 19 zile",
                    20: "peste 20 de zile", 21: "peste 21 de zile", 101: "peste 101 zile",
                    -1: "acum 1 zi", -3: "acum 3 zile", -30: "acum 30 de zile"}
        for diff, text in expected.items():
            assert relative_day(diff, runtime) == text, diff

    def test_the_moon_counts_romanian_days_the_same_way(self):
        from linecast._moon_i18n import _ms
        runtime = SimpleNamespace(lang="ro")
        assert _ms("in_days", runtime, days="1") == "peste 1 zi"
        assert _ms("in_days", runtime, days="3") == "peste 3 zile"
        assert _ms("in_days", runtime, days="25") == "peste 25 de zile"
        assert _ms("in_days", runtime, days="3.5") == "peste 3.5 zile"
        assert _ms("in_days", runtime=SimpleNamespace(lang="ru"), days="25") == "через 25 д"


class TestMonthAxisLabels:
    def test_french_june_and_july_are_distinct(self):
        from linecast._sunshine_i18n import axis_month_labels
        labels = axis_month_labels(SimpleNamespace(lang="fr"))
        assert labels[5] == "jun"
        assert labels[6] == "jul"

    def test_wide_labels_are_distinct_in_every_language(self):
        """No two months may truncate to the same axis label."""
        from linecast._moon_i18n import MONTHS_I18N
        from linecast._sunshine_i18n import _AXIS_MONTHS, axis_month_labels
        for lang in set(MONTHS_I18N) | set(_AXIS_MONTHS):
            labels = axis_month_labels(SimpleNamespace(lang=lang))
            assert len(set(labels)) == 12, lang


class TestKoreanMoonNames:
    def test_everyday_phase_words(self):
        from linecast._tides_i18n import MOON_NAMES_I18N
        assert MOON_NAMES_I18N["ko"] == [
            "삭", "초승달", "상현달",
            "차오르는 달", "보름달",
            "기우는 달", "하현달",
            "그믐달",
        ]
