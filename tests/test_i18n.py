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

        assert warmer == ("Huomenna on hieman l\u00e4mpim\u00e4mp\u00e4\u00e4 "
                          "kuin t\u00e4n\u00e4\u00e4n")
        assert cooler == "Huomenna on hieman viile\u00e4mp\u00e4\u00e4 kuin t\u00e4n\u00e4\u00e4n"

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

        assert sentence == ("\u4eca\u65e5\u306f\u6628\u65e5\u3088\u308a"
                            "\u6696\u304b\u304f\u306a\u308b")

    def test_partly_cloudy_is_idiomatic(self):
        assert WMO_NAMES_I18N["ja"][2] == "\u6674\u308c\u6642\u3005\u66c7\u308a"

    def test_forecast_phrases_use_japanese_grammar(self):
        runtime = SimpleNamespace(lang="ja")
        assert (_s("ending", runtime, desc="\u96e8", time="\u307e\u3082\u306a\u304f")
                == "\u96e8\u306f\u307e\u3082\u306a\u304f\u3084\u3080\u898b\u8fbc\u307f")
        assert (_s("continuing", runtime, desc="\u96e8")
                == "\u96e8\u306f\u4e00\u65e5\u4e2d\u7d9a\u304f\u898b\u8fbc\u307f")
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
            "precipitation_probability": [0, 0, 0, 0, 0, 80],
            "weather_code": [0, 0, 0, 0, 0, 63],
        }

        line = _precipitation_line(hourly, now, runtime)

        assert "17\u6642\u9803\u306b\u96e8\u306e\u898b\u8fbc\u307f" in line

    def test_past_rain_uses_quantity_term_and_localized_unit(self):
        runtime = SimpleNamespace(lang="ja", metric=False)
        now = datetime(2026, 8, 24, 12)
        hourly = {
            "time": ["2026-08-24T11:00"],
            "precipitation": [0.02],
            "snowfall": [0],
            "weather_code": [63],
        }

        line = _past_precip_line(hourly, now, runtime)

        assert ("\u904e\u53bb24\u6642\u9593\u306e\u964d\u6c34\u91cf\uff1a"
                "0.02\u30a4\u30f3\u30c1") in line


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
