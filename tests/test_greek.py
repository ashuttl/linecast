"""Greek sentences at the joins: case, clock times, and whole paragraphs."""

from datetime import datetime, timedelta
from string import Formatter

import pytest

from linecast._framebuffer import fmt_hour_phrase
from linecast._i18n import LANGUAGE_CODES
from linecast._moon_i18n import _ms, _fmt_month_day
from linecast._runtime import WeatherRuntime, language_of, resolve_lang
from linecast._sunshine_i18n import axis_month_labels, relative_day, sky_phase
from linecast._textwidth import visible_len
from linecast._weather.i18n import (
    DAY_NAMES, ON_DAY_FORMS, WMO_NAMES, WMO_NAMES_I18N, _PRECIP_DESCS_I18N, _s,
)
from linecast._weather.sections import (
    _PRECIP_DESCS, comparative_sentence, narrative_lines, past_precip_sentence,
    precipitation_sentence,
)
from linecast.weather import _precip_kind_lower

NOW = datetime(2026, 9, 17, 12)


def runtime(**overrides):
    values = dict(live=False, icons="plain", lang="el", oneline=False,
                  celsius=True, metric=True, shading=False, use_24h=True)
    return WeatherRuntime(**(values | overrides))


def hourly(codes, start=NOW):
    return {"time": [(start + timedelta(hours=i)).isoformat() for i in range(len(codes))],
            "weather_code": codes,
            "precipitation_probability": [70 if c else 0 for c in codes]}


@pytest.mark.parametrize("locale", ["el_GR.UTF-8", "el_CY.UTF-8", "el-GR", "el"])
def test_greek_locale_is_selected(locale, monkeypatch):
    assert "el" in LANGUAGE_CODES
    assert language_of(locale) == "el"
    monkeypatch.setenv("LANG", locale)
    assert resolve_lang()[0] == "el"


def test_greek_tables_keep_format_fields_and_weather_codes():
    # Check actual format fields, beyond the suite's table-key coverage.
    from test_i18n import TestTablesComplete
    formatter = Formatter()

    def fields(text):
        return {f for _, f, _, _ in formatter.parse(text) if f}

    for module, name, table in TestTablesComplete()._tables():
        for key, english in table["en"].items():
            if key in table.get("el", {}):
                assert fields(table["el"][key]) == fields(english), (module, name, key)
    assert set(WMO_NAMES_I18N["el"]) == set(WMO_NAMES)
    assert set(_PRECIP_DESCS_I18N["el"]) == set(_PRECIP_DESCS)


@pytest.mark.parametrize("diff,comparison", [
    (0, "περίπου στα ίδια επίπεδα με"), (2, "κατά 2 βαθμούς υψηλότερη από"),
    (-2, "κατά 2 βαθμούς χαμηλότερη από"), (4, "κατά 4 βαθμούς υψηλότερη από"),
    (-4, "κατά 4 βαθμούς χαμηλότερη από"),
    (8, "κατά 8 βαθμούς υψηλότερη από"), (-8, "κατά 8 βαθμούς χαμηλότερη από"),
])
@pytest.mark.parametrize("hour,subject,reference", [(9, "Σήμερα", "χθες"), (15, "Αύριο", "σήμερα")])
def test_temperature_comparisons_agree_with_temperature(diff, comparison, hour, subject, reference):
    temps = [20, 20 + diff, 20] if hour == 9 else [20, 20, 20 + diff]
    actual = comparative_sentence({"temperature_2m_max": temps}, NOW.replace(hour=hour), runtime())
    assert actual == f"{subject} η θερμοκρασία θα είναι {comparison} {reference}"


@pytest.mark.parametrize("code", sorted(_PRECIP_DESCS))
def test_precipitation_subjects_work_in_all_three_forecast_branches(code):
    desc = _PRECIP_DESCS_I18N["el"][code]
    desc = desc[0].upper() + desc[1:]
    assert precipitation_sentence(hourly([code, 0]), NOW, runtime()) == (
        f"{desc} θα σταματήσουν σύντομα")
    assert precipitation_sentence(hourly([code, code]), NOW, runtime()) == (
        f"{desc} θα συνεχιστούν όλη την ημέρα")
    assert precipitation_sentence(hourly([0, code]), NOW, runtime()) == (
        f"{desc} πιθανότατα θα αρχίσουν σύντομα")


def test_intensifying_rain_crosses_midnight_without_losing_agreement():
    now = NOW.replace(hour=19)
    ending = hourly([61, 61, 61, 61, 65, 65, 0], now)
    assert precipitation_sentence(ending, now, runtime()) == (
        "Ασθενείς βροχές θα εξελιχθούν σε ισχυρές βροχές γύρω στις 23:00 "
        "και τα φαινόμενα θα σταματήσουν μέσα στη νύχτα")
    assert precipitation_sentence(hourly([61, 61, 65], now), now, runtime()) == (
        "Ασθενείς βροχές θα εξελιχθούν σε ισχυρές βροχές σε περίπου μία ώρα "
        "και τα φαινόμενα θα συνεχιστούν όλη την ημέρα")
    # An hour of light rain at the edge of heavy rain is the heavy rain
    assert precipitation_sentence(hourly([0, 61, 65], now), now, runtime()) == (
        "Ισχυρές βροχές πιθανότατα θα αρχίσουν σε περίπου μία ώρα")


@pytest.mark.parametrize("hour,phrase", [
    (0, "12 τα μεσάνυχτα"), (1, "1 τη νύχτα"), (8, "8 το πρωί"),
    (12, "12 το μεσημέρι"), (13, "1 το μεσημέρι"),
    (17, "5 το απόγευμα"), (21, "9 το βράδυ"),
])
def test_clock_phrases_honor_both_clock_formats(hour, phrase):
    assert fmt_hour_phrase(hour, False, "el") == phrase
    assert fmt_hour_phrase(hour, True, "el") == f"{hour:02d}:00"


@pytest.mark.parametrize("time,preposition", [
    ("1 το μεσημέρι", "στη"), ("01:00", "στη"), ("1:30p", "στη"),
    ("11:00", "στις"), ("12:00", "στις"), ("13:00", "στις"), ("21:00", "στις"),
])
def test_one_oclock_takes_the_singular_article(time, preposition):
    assert _s("around", runtime(), time=time) == f"γύρω {preposition} {time}"
    assert f"γύρω {preposition} {time}" in _s("heaviest_around", runtime(), time=time)
    assert f"{preposition} {time}" in _s("forecast_stale_at", runtime(), day="16/9", time=time)


@pytest.mark.parametrize("code,snow,expected", [
    (63, 0, "4.0 mm βροχής"), (73, 2, "2.0 cm χιονιού"),
    (66, 0, "4.0 mm μεικτών κατακρημνισμάτων"),
])
def test_amounts_and_probability_take_the_genitive(code, snow, expected):
    data = hourly([code], NOW - timedelta(hours=1))
    data.update(precipitation=[4.0], snowfall=[snow])
    assert past_precip_sentence(data, NOW, runtime()) == (
        f"Το τελευταίο 24ωρο καταγράφηκαν {expected}")
    kind = _precip_kind_lower(code, runtime())
    assert _s("chance_of", runtime(), p="80%", what=kind) == (
        "πιθανότητα " + expected.split(" ", 2)[2] + " 80%")


def test_dates_day_counts_and_dawn_are_greek():
    assert _fmt_month_day(NOW, runtime()) == "17 Σεπ"
    for narrow in (False, True):
        assert axis_month_labels(runtime(), narrow=narrow) == [str(m) for m in range(1, 13)]
    assert relative_day(1, runtime()) == "σε 1 ημέρα"
    assert relative_day(-2, runtime()) == "πριν από 2 ημέρες"
    assert _ms("in_days", runtime(), days="1") == "σε 1 ημέρα"
    assert _ms("in_days", runtime(), days="2.5") == "σε 2.5 ημέρες"
    assert sky_phase(-4, runtime(), morning=True) == "πολιτικό λυκαυγές"
    assert sky_phase(-4, runtime(), morning=False) == "πολιτικό λυκόφως"
    assert ON_DAY_FORMS["el"][5].format(day=DAY_NAMES["el"][5]) == "το Σάβ"


@pytest.mark.parametrize("width", [20, 40, 80, 120])
@pytest.mark.parametrize("use_24h", [False, True])
def test_complete_paragraph_wraps_without_losing_text_or_doubling_punctuation(width, use_24h):
    import re
    data = {"daily": {"temperature_2m_max": [20, 22, 25]},
            "current": {"temperature_2m": 30, "apparent_temperature": 35,
                        "relative_humidity_2m": 80, "wind_speed_10m": 3},
            "hourly": hourly([0, 0, 0, 0, 0, 63])}
    rt = runtime(use_24h=use_24h)
    rows = [re.sub(r"\x1b\[[0-9;]*m", "", row)
            for row in narrative_lines(data, NOW, width, rt)]
    expected = (
        "Σήμερα η θερμοκρασία θα είναι κατά 2 βαθμούς υψηλότερη από χθες. "
        "Η υψηλή υγρασία αυξάνει την αισθητή θερμοκρασία. "
        "Βροχές πιθανότατα θα αρχίσουν γύρω στις "
        + ("17:00" if use_24h else "5 το απόγευμα") + ".")
    assert " ".join(rows) == expected
    assert all(visible_len(row) <= width for row in rows)


def test_sky_names_and_defaults_are_localization_only():
    from linecast import sky
    from linecast._calendars.lunisolar import resolve_calendar
    from linecast._hours import resolve_hours
    records = sky.constellations()
    assert all(record["names"].get("el") for record in records)
    ursa = next(record for record in records if record["id"] == "UMa")
    assert sky.constellation_name(ursa, "el") == "Μεγάλη Άρκτος"
    assert sky.star_names("el")[0] == ("Σείριος", "α CMa")
    assert resolve_calendar(None, "el") is None
    assert resolve_hours(None, "el") == (None, None)
