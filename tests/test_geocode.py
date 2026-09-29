"""The name a view shows for a place (_geocode.place_label)."""

from unittest.mock import patch

from linecast import _geocode


def _label(label, lang, nominatim=("Portland, Maine", "US", {})):
    asked = []

    def reverse(lat, lng, lang=None):
        asked.append(lang)
        return nominatim

    with patch.object(_geocode, "reverse_geocode", reverse):
        return _geocode.place_label(43.66, -70.26, label, lang), asked


def test_a_typed_place_keeps_its_label():
    assert _label("Portland, Oregon", "en") == ("Portland, Oregon", [])


def test_without_a_label_nominatim_names_the_coordinates():
    assert _label("", "fr") == ("Portland, Maine", ["fr"])


def test_in_traditional_chinese_nominatim_names_a_typed_place():
    # Open-Meteo answers zh-Hant in English: its label is the fallback
    assert _label("Portland, Maine", "zh-Hant", ("波特蘭, 緬因州", "US", {})) == (
        "波特蘭, 緬因州", ["zh-Hant"])
    assert _label("Portland, Maine", "zh-HK", ("", "", {})) == ("Portland, Maine", ["zh-HK"])


def test_nothing_to_go_on_is_empty():
    assert _label("", "en", ("", "", {})) == ("", ["en"])
