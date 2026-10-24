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

    def test_a_failure_holds_the_next_lookups_back_for_a_while(self):
        """On a stalled network each lookup waits out its own timeout,
        and a weather run asked three times, two of them in a row."""
        calls = []

        def down(url, **_kw):
            calls.append(url)
            raise OSError("timed out")
        assert self._ask(-45.6701, 12.3401, down) == ("", "", {})
        assert self._ask(-45.6701, 12.3401, down, lang="fr") == ("", "", {})
        assert self._ask(-56.7801, 23.4501, down) == ("", "", {})
        assert len(calls) == 1
        with patch.object(_geocode, "_failed_at", _geocode._failed_at - _geocode._FAILURE_HOLD_S):
            self._ask(-56.7801, 23.4501, lambda url, **kw: (calls.append(url), self.PAYLOAD)[1])
        assert len(calls) == 2

    def test_an_answer_holds_nothing(self):
        """An error status, or an answer that can't be read, is Nominatim
        answering: the next place is asked, so a tide station is not
        picked for a place left without its country."""
        from linecast._http import HTTPError
        calls = []

        def refused(url, **_kw):
            calls.append(url)
            raise HTTPError(url, 503, "Service Unavailable")
        def unreadable(url, **_kw):
            calls.append(url)
            return []

        def named(url, **_kw):
            calls.append(url)
            return self.PAYLOAD
        assert self._ask(-41.2301, 14.5601, refused) == ("", "", {})
        assert self._ask(-41.2301, 14.5601, unreadable) == ("", "", {})
        assert self._ask(-52.3401, 25.6701, named) == ("Westbrook, Maine", "US",
                                                       self.PAYLOAD["address"])
        assert len(calls) == 3


class TestTrailingCountry:
    """Open-Meteo matches a trailing ISO code or country name, and finds
    nothing for "London, UK"; the everyday forms are asked as ISO codes."""

    def _asked(self, query):
        urls = []

        def fetch(url, **_kw):
            urls.append(url)
            return {"results": []}
        with patch.object(_geocode, "fetch_json", fetch):
            _geocode.geocode(query)
        import urllib.parse
        return urllib.parse.parse_qs(urllib.parse.urlsplit(urls[0]).query)["name"][0]

    def test_uk_is_asked_as_gb(self):
        assert self._asked("London, UK") == "London, GB"
        assert self._asked("Manchester,uk") == "Manchester, GB"
        assert self._asked("Leeds, U.K.") == "Leeds, GB"

    def test_usa_is_asked_as_us(self):
        assert self._asked("Portland, USA") == "Portland, US"
        assert self._asked("Portland, Maine, U.S.A.") == "Portland, Maine, US"

    def test_other_queries_go_as_typed(self):
        assert self._asked("London") == "London"
        assert self._asked("UK") == "UK"
        assert self._asked("London, United Kingdom") == "London, United Kingdom"
        assert self._asked("Ukiah, California") == "Ukiah, California"


class TestReadings:
    """A query typed without commas is read again as a name and where it
    is, which is how the geocoder takes a state or a country."""

    PLACES = {
        "Portland": [{"name": "Portland", "admin1": "Oregon", "country": "United States"},
                     {"name": "Portland", "admin1": "Maine", "country": "United States"}],
        "Portland ME": [{"name": "Portland Meadows", "admin1": "Oregon",
                         "country": "United States"}],
        "Portland, ME": [{"name": "Portland", "admin1": "Maine", "country": "United States"}],
        "Portland, Maine": [{"name": "Portland", "admin1": "Maine",
                             "country": "United States"}],
        "Portland, Oregon, US": [{"name": "Portland", "admin1": "Oregon",
                                  "country": "United States"}],
        "Sao Paulo, Brazil": [{"name": "São Paulo", "admin1": "São Paulo", "country": "Brazil"}],
        "New York City": [{"name": "New York", "admin1": "New York",
                           "country": "United States"}],
        "St Johns, Newfoundland": [{"name": "St Johns Island",
                                    "admin1": "Newfoundland and Labrador", "country": "Canada"}],
    }

    def _geocode(self, query, photon=()):
        import urllib.parse
        asked = []

        def fetch(url, **_kw):
            parts = urllib.parse.urlsplit(url)
            params = urllib.parse.parse_qs(parts.query)
            if parts.hostname == "photon.komoot.io":
                asked.append(("photon", params["q"][0]))
                return {"features": list(photon)}
            asked.append(params["name"][0])
            # the geocoder takes a name in any case, as the table doesn't
            places = {name.casefold(): found for name, found in self.PLACES.items()}
            return {"results": places.get(params["name"][0].casefold(), [])}
        with patch.object(_geocode, "fetch_json", fetch):
            results = _geocode.geocode(query)
        return [_geocode.result_label(r) for r in results][:1], asked

    def test_a_name_found_as_typed_is_asked_once(self):
        assert self._geocode("Portland") == (["Portland, Oregon, United States"], ["Portland"])

    def test_a_state_after_a_space_is_read_as_one(self):
        assert self._geocode("Portland ME") == (
            ["Portland, Maine, United States"], ["Portland ME", "Portland, ME"])
        assert self._geocode("portland maine")[0] == ["Portland, Maine, United States"]

    def test_a_name_is_matched_without_its_accents(self):
        assert self._geocode("Sao Paulo Brazil")[0] == ["São Paulo, Brazil"]

    def test_a_state_and_a_country_are_read_as_two(self):
        label, asked = self._geocode("Portland Oregon USA")
        assert label == ["Portland, Oregon, United States"]
        assert asked == ["Portland Oregon USA", "Portland Oregon, US", "Portland, Oregon USA",
                         "Portland, Oregon, US"]

    def test_with_no_reading_named_so_the_query_as_typed_stands(self):
        label, asked = self._geocode("New York City")
        assert label == ["New York, United States"]
        assert asked == ["New York City", "New York, City", "New, York City", "New, York, City"]

    def test_a_place_found_only_by_a_reading_is_better_than_none(self):
        assert self._geocode("St Johns Newfoundland")[0] == [
            "St Johns Island, Newfoundland and Labrador, Canada"]

    def test_a_query_with_a_comma_is_read_as_typed(self):
        assert self._geocode("Portland, ME")[1] == ["Portland, ME"]

    def test_the_readings_stop_at_a_few(self):
        _label, asked = self._geocode("one two three four five six")
        assert len([a for a in asked if isinstance(a, str)]) == 1 + _geocode._QUALIFIED_TRIES

    def test_what_open_meteo_does_not_know_photon_is_asked(self):
        def feature(name, kind):
            return {"properties": {"name": name, "state": "Maine",
                                   "country": "United States", "type": kind},
                    "geometry": {"coordinates": [-70.26, 43.66]}}
        label, asked = self._geocode("Portand, Maine", photon=[
            feature("University of Southern Maine Portland Campus", "house"),
            feature("Portland", "city")])
        assert label == ["Portland, Maine, United States"]
        assert asked[-1] == ("photon", "Portand, Maine")

    def test_numbers_are_not_asked_of_photon(self):
        # which found "Isar Flusskilometer 91,0" in Bavaria for 91,0
        assert self._geocode("91,0") == ([], ["91,0"])

    def test_nothing_anywhere_is_no_match(self):
        assert self._geocode("Xyzzy") == ([], ["Xyzzy", ("photon", "Xyzzy")])


def test_a_country_found_as_itself_is_named_once():
    assert _geocode.result_label({"name": "Poland", "admin1": "", "country": "Poland"}) == "Poland"
    assert _geocode.result_label({"name": "Mexico City", "admin1": "Mexico City",
                                  "country": "Mexico"}) == "Mexico City, Mexico"


def test_places_come_before_the_things_in_them():
    kinds = ["house", "city", "other", "town", "street", "country"]
    assert _geocode.places_first(kinds, lambda kind: kind) == [
        "city", "town", "country", "house", "other", "street"]
