"""Experimental RTL locales: grammar, mixed numbers, and calendar integration."""

from datetime import date
from string import Formatter
from types import SimpleNamespace

import pytest

from linecast._i18n import _locale, canonical_language, plural_category, setting
from linecast.moon.i18n import _ms, hebrew_date_label, hebrew_holiday_name
from linecast.sunshine.i18n import relative_day
from linecast.terminal import bidi
from linecast.terminal.textwidth import visible_len


@pytest.mark.parametrize("code,expected", [
    ("he_IL.UTF-8", "he"), ("iw_IL", "he"), ("ar_EG.UTF-8", "ar"), ("ar_MA", "ar"),
])
def test_locale_selection(code, expected):
    assert canonical_language(code) == expected
    assert setting(expected, "rtl")


@pytest.mark.parametrize("n,category", [
    (0, "zero"), (1, "one"), (2, "two"), (3, "few"), (10, "few"),
    (11, "many"), (99, "many"), (100, "other"), (102, "other"),
    (103, "few"), (111, "many"), (1.5, "other"),
])
def test_arabic_plural_boundaries(n, category):
    assert plural_category("ar", n) == category


@pytest.mark.parametrize("lang,n,future,past", [
    ("ar", 1, "بعد يوم", "قبل يوم"),
    ("ar", 2, "بعد يومين", "قبل يومين"),
    ("ar", 3, "بعد 3 أيام", "قبل 3 أيام"),
    ("ar", 11, "بعد 11 يوما", "قبل 11 يوما"),
    ("ar", 100, "بعد 100 يوم", "قبل 100 يوم"),
    ("he", 1, "בעוד יום", "לפני יום"),
    ("he", 2, "בעוד יומיים", "לפני יומיים"),
    ("he", 3, "בעוד 3 ימים", "לפני 3 ימים"),
])
def test_relative_days(lang, n, future, past):
    runtime = SimpleNamespace(lang=lang)
    assert relative_day(n, runtime) == future
    assert relative_day(-n, runtime) == past
    if n != 1:
        assert _ms("in_days", runtime, days=str(n)) == future


def test_arabic_decimal_countdown():
    assert _ms("in_days", SimpleNamespace(lang="ar"), days="2٫5") == "بعد 2٫5 يوم"


@pytest.mark.parametrize("lang,digits", [("he", "12:30"), ("ar", "١٢:٣٠")])
def test_mixed_text_keeps_numbers_identifiers_and_width(lang, digits):
    try:
        bidi.configure(lang, {})
        row = f"{bidi.RLI}{'ירושלים' if lang == 'he' else 'القاهرة'} 12:30 −3°{bidi.PDI}"
        output = bidi.display(row)
        assert digits in output
        assert visible_len(output) == visible_len(row)
        assert "v2.6.1" in bidi.display(bidi.identifier("v2.6.1"))
        bidi.configure(lang, {"LINECAST_DIGITS": "latin"})
        assert "12:30" in bidi.display(row)
    finally:
        bidi.configure("en", {})


@pytest.mark.parametrize("lang", ["he", "ar"])
def test_templates_accept_reference_placeholders(lang):
    fields = Formatter()
    english = _locale("en")
    for name, table in vars(_locale(lang)).items():
        reference = getattr(english, name, None)
        if not isinstance(table, dict) or not isinstance(reference, dict) or name == "SETTINGS":
            continue
        for key, value in table.items():
            if key in reference and isinstance(value, str):
                names = {field for _, field, _, _ in fields.parse(reference[key]) if field}
                # A singular/dual may express the count in its word instead.
                value.format(**dict.fromkeys(names, "12"))


@pytest.mark.parametrize("lang,cal", [("he", "hebrew"), ("ar", "islamic")])
def test_native_calendar_reading(lang, cal):
    from test_moon_readings import _ctx
    from linecast.moon.readings import reading

    assert setting(lang, "calendar") == cal
    ctx = _ctx(cal, lang)
    view = reading(cal)
    for text in (view.headline(ctx)[1], view.hover(date(2026, 9, 12), ctx),
                 view.span(date(2026, 9, 1), date(2026, 10, 1), ctx)):
        assert any('\u0590' <= ch <= '\u06ff' for ch in text)
    assert view.panel(ctx).year
    assert view.json_block(ctx)["name"] == cal


def test_hebrew_calendar_keeps_other_languages_transliterated():
    assert hebrew_holiday_name("pesach", "he") == "פסח"
    assert hebrew_holiday_name("pesach") == "Pesach"
    assert "תשרי" in hebrew_date_label(5787, 7, 1, "he")
    assert hebrew_date_label(5787, 7, 1) == "1 Tishrei 5787"
