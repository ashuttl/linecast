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


class TestReverseCache:
    """A place's name is kept per place and language, and outlasts a day
    offline."""

    PAYLOAD = {"address": {"city": "Westbrook", "state": "Maine", "country_code": "us"}}

    def _ask(self, lat, lng, fetch, **kw):
        with patch.object(_geocode, "fetch_json", fetch), \
                patch.object(_geocode, "nominatim_throttle", lambda: None):
            return _geocode.reverse_geocode(lat, lng, **kw)

    def test_two_places_are_both_kept(self):
        calls = []

        def fetch(url, **_kw):
            calls.append(url)
            return self.PAYLOAD
        for _ in range(2):
            self._ask(-12.3401, 45.6701, fetch)
            self._ask(-12.3402, 45.6702, fetch)
        assert len(calls) == 2

    def test_offline_a_day_later_the_name_stands(self):
        import os
        import time
        from linecast._cache import location_cache_key
        self._ask(-23.4501, 56.7801, lambda url, **kw: self.PAYLOAD)
        path = _geocode.cache_dir("weather") / f"place_{location_cache_key(-23.4501, 56.7801)}.json"
        old = time.time() - 3 * 86400
        os.utime(path, (old, old))

        def down(url, **_kw):
            raise OSError("offline")
        name, country, addr = self._ask(-23.4501, 56.7801, down)
        assert (name, country) == ("Westbrook, Maine", "US")
        assert addr["city"] == "Westbrook"

    def test_offline_with_nothing_kept_is_unnamed(self):
        def down(url, **_kw):
            raise OSError("offline")
        assert self._ask(-34.5601, 67.8901, down) == ("", "", {})
