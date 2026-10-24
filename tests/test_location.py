import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from linecast import _config, _location
from linecast._log import UserError
from linecast.settings import location


class GetLocationTests(unittest.TestCase):
    def test_saved_location_overrides_ip_geolocation(self):
        saved = {"lat": 44.4293, "lng": -70.0356, "label": "Fayette, Maine, United States",
                 "country": "US"}
        with patch.object(_location, "saved_location", return_value=saved), \
             patch.object(_location, "fetch_json",
                          side_effect=AssertionError("should not hit network")):
            self.assertEqual(_location.get_location(), (44.4293, -70.0356, "US"))

    def test_stale_cache_refreshes_after_one_hour(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_file = Path(tmpdir) / "location.json"
            cache_file.write_text(json.dumps({"lat": 1.0, "lng": 2.0, "country": "US"}))
            stale_at = time.time() - _location._MAX_AGE - 1
            os.utime(cache_file, (stale_at, stale_at))

            payload = {"loc": "3.0,4.0", "country": "CA"}

            with patch.object(_location, "saved_location", return_value=None), \
                 patch.dict(os.environ, {"LINECAST_CACHE_DIR": tmpdir}), \
                 patch.object(_location, "fetch_json", return_value=payload):
                location = _location.get_location()

        self.assertEqual(location, (3.0, 4.0, "CA"))


class GeolocationProviderChainTests(unittest.TestCase):
    def _get_location(self, fake_fetch):
        with tempfile.TemporaryDirectory() as tmpdir, \
             patch.dict(os.environ, {"LINECAST_CACHE_DIR": tmpdir}), \
             patch.object(_location, "saved_location", return_value=None), \
             patch.object(_location, "fetch_json", side_effect=fake_fetch):
            return _location.get_location()

    def test_second_source_answers_when_the_first_fails(self):
        def fake(url, headers=None, timeout=0):
            if url == "https://ipwho.is/":
                return {"success": True, "latitude": 3.0, "longitude": 4.0,
                        "country_code": "CA"}
            raise OSError("down")

        self.assertEqual(self._get_location(fake), (3.0, 4.0, "CA"))

    def test_geojs_is_the_third_opinion(self):
        def fake(url, headers=None, timeout=0):
            if url == "https://get.geojs.io/v1/ip/geo.json":
                # GeoJS sends coordinates as strings
                return {"latitude": "5.5", "longitude": "-6.5",
                        "country_code": "GB"}
            raise OSError("down")

        self.assertEqual(self._get_location(fake), (5.5, -6.5, "GB"))

    def test_ipwhois_refusal_arrives_as_http_200(self):
        def fake(url, headers=None, timeout=0):
            if url == "https://ipwho.is/":
                return {"success": False, "message": "limit reached"}
            if url == "https://get.geojs.io/v1/ip/geo.json":
                return {"latitude": "5.5", "longitude": "-6.5",
                        "country_code": "GB"}
            raise OSError("down")

        self.assertEqual(self._get_location(fake), (5.5, -6.5, "GB"))

    def test_a_source_that_answers_is_asked_alone(self):
        asked = []

        def fake(url, headers=None, timeout=0):
            asked.append(url)
            return {"loc": "3.0,4.0", "country": "CA"}

        self.assertEqual(self._get_location(fake), (3.0, 4.0, "CA"))
        self.assertEqual(asked, ["https://ipinfo.io/json"])

    def test_a_stalled_source_is_not_waited_out_before_the_next(self):
        # On a stalled network the three timed out one after another:
        # nine seconds before the last location found stood in
        stalled = __import__("threading").Event()
        asked = []

        def fake(url, headers=None, timeout=0):
            asked.append(url)
            if url == "https://ipinfo.io/json":
                stalled.wait(5)
                raise OSError("timed out")
            return {"success": True, "latitude": 3.0, "longitude": 4.0,
                    "country_code": "CA"}

        began = time.monotonic()
        with patch.object(_location, "_HEDGE_S", 0.05):
            self.assertEqual(self._get_location(fake), (3.0, 4.0, "CA"))
        self.assertLess(time.monotonic() - began, 1.0)
        self.assertEqual(asked, ["https://ipinfo.io/json", "https://ipwho.is/"])
        stalled.set()

    def test_every_source_down_is_no_location(self):
        def fake(url, headers=None, timeout=0):
            raise OSError("down")

        self.assertEqual(self._get_location(fake), (None, None, None))

    def test_offline_the_last_location_found_stands(self):
        # A laptop on a train, an hour after the last run: the moon and
        # the sky need no network, so the old answer beats none.
        def fake(url, headers=None, timeout=0):
            raise OSError("Network is unreachable")

        with tempfile.TemporaryDirectory() as tmpdir, \
             patch.dict(os.environ, {"LINECAST_CACHE_DIR": tmpdir}), \
             patch.object(_location, "saved_location", return_value=None), \
             patch.object(_location, "fetch_json", side_effect=fake):
            cache_file = Path(tmpdir) / "location.json"
            cache_file.write_text(json.dumps({"lat": 1.0, "lng": 2.0, "country": "US"}))
            stale_at = time.time() - 3 * 86400
            os.utime(cache_file, (stale_at, stale_at))
            self.assertEqual(_location.get_location(), (1.0, 2.0, "US"))


class MalformedLocationCacheTests(unittest.TestCase):
    """Only linecast writes location.json, but a crash or a hand edit
    can leave anything there: `[]` and a latitude of "x" ended every
    command in a traceback. Anything but a place on the planet is no
    answer, as a missing file is."""

    BAD = ("[]", "null", '"Portland"', '{"lat": "x", "lng": 2}', '{"lat": 1.0}',
           '{"lat": true, "lng": 2}', '{"lat": 1e999, "lng": 0}', '{"lat": 91, "lng": 0}')

    def _with_cache(self, text, fetch):
        with tempfile.TemporaryDirectory() as tmpdir, \
             patch.dict(os.environ, {"LINECAST_CACHE_DIR": tmpdir}), \
             patch.object(_location, "saved_location", return_value=None), \
             patch.object(_location, "fetch_json", side_effect=fetch):
            (Path(tmpdir) / "location.json").write_text(text)
            return _location.get_location(), _location.own_country()

    def test_a_fresh_copy_is_fetched_in_its_place(self):
        def fetch(url, headers=None, timeout=0):
            return {"loc": "3.0,4.0", "country": "CA"}
        for text in self.BAD:
            with self.subTest(text=text):
                self.assertEqual(self._with_cache(text, fetch), ((3.0, 4.0, "CA"), "CA"))

    def test_offline_it_is_no_location(self):
        def fetch(url, headers=None, timeout=0):
            raise OSError("Network is unreachable")
        for text in self.BAD:
            with self.subTest(text=text):
                self.assertEqual(self._with_cache(text, fetch), ((None, None, None), None))

    def test_a_country_that_is_not_a_code_is_no_country(self):
        def fetch(url, headers=None, timeout=0):
            raise AssertionError("the cached place stands")
        self.assertEqual(self._with_cache('{"lat": 1, "lng": 2, "country": 7}', fetch),
                         ((1.0, 2.0, ""), None))


class GeocoderFallbackTests(unittest.TestCase):
    def test_photon_answers_when_open_meteo_fails(self):
        from linecast import _geocode
        feature = {"properties": {"name": "Westbrook", "state": "Maine",
                                  "country": "United States",
                                  "countrycode": "US"},
                   "geometry": {"coordinates": [-70.37, 43.68]}}

        def fake(url, headers=None, timeout=0):
            from urllib.parse import urlsplit
            if urlsplit(url).hostname == "geocoding-api.open-meteo.com":
                raise OSError("down")
            return {"features": [feature]}

        with patch.object(_geocode, "fetch_json", side_effect=fake):
            hit = _geocode.geocode_first("Westbrook")
        self.assertEqual(hit, (43.68, -70.37, "Westbrook, Maine, United States"))

    def test_both_geocoders_down_is_unavailable(self):
        from linecast import _geocode
        with patch.object(_geocode, "fetch_json",
                          side_effect=OSError("down")):
            with self.assertRaises(_geocode.GeocoderUnavailable):
                _geocode.geocode("Westbrook")

    def test_both_geocoders_down_ends_a_named_location_with_a_line(self):
        from linecast import _geocode
        with patch.object(_geocode, "fetch_json", side_effect=OSError("down")), \
                self.assertRaises(UserError) as exit_:
            _location.resolve_location("Westbrook")
        self.assertEqual(str(exit_.exception), "Search failed: down")


class ResolveLocationTests(unittest.TestCase):
    def test_flag_coords_beat_env_and_saved(self):
        with patch.dict(os.environ, {"WEATHER_LOCATION": "1.0,2.0"}), \
             patch.object(_location, "get_location",
                          side_effect=AssertionError("override should win")):
            self.assertEqual(
                _location.resolve_location("43.68,-70.35"),
                (43.68, -70.35, ""))

    def test_env_var_used_when_no_flag(self):
        with patch.dict(os.environ, {"WEATHER_LOCATION": "1.5,-2.5"}), \
             patch.object(_location, "get_location",
                          side_effect=AssertionError("override should win")):
            self.assertEqual(_location.resolve_location(None), (1.5, -2.5, ""))

    def test_falls_through_to_get_location(self):
        with patch.dict(os.environ, {"WEATHER_LOCATION": ""}), \
             patch.object(_location, "get_location",
                          return_value=(3.0, 4.0, "US")):
            self.assertEqual(_location.resolve_location(None), (3.0, 4.0, "US"))

    def test_place_name_geocodes(self):
        with patch("linecast._geocode.geocode_first",
                   return_value=(43.68, -70.35, "Westbrook, Maine")):
            self.assertEqual(
                _location.resolve_location("Westbrook"), (43.68, -70.35, ""))

    def test_unmatched_place_name_is_a_user_error(self):
        with patch("linecast._geocode.geocode_first", return_value=None):
            with self.assertRaises(UserError) as cm:
                _location.resolve_location("Nowhereville Q")
        # the main prints it to stderr and exits 1, once the caller's
        # finally blocks (radar's spinner) have run
        self.assertEqual(str(cm.exception), 'No locations matching "Nowhereville Q".')

    def test_return_label_carries_the_geocoder_hit(self):
        with patch("linecast._geocode.geocode_first",
                   return_value=(43.68, -70.35, "Westbrook, Maine")):
            self.assertEqual(
                _location.resolve_location("Westbrook", return_label=True),
                (43.68, -70.35, "", "Westbrook, Maine"))

    def test_return_label_is_empty_for_coordinates_and_fallback(self):
        with patch.dict(os.environ, {"WEATHER_LOCATION": ""}), \
             patch.object(_location, "get_location",
                          return_value=(3.0, 4.0, "US")):
            self.assertEqual(
                _location.resolve_location(None, return_label=True),
                (3.0, 4.0, "US", ""))
        self.assertEqual(
            _location.resolve_location("43.68,-70.35", return_label=True),
            (43.68, -70.35, "", ""))



class SavedLabelTests(unittest.TestCase):
    SAVED = {"lat": 43.6591, "lng": -70.2568, "label": "Portland, Maine", "country": "US"}

    def _label(self, saved, lat=43.6591, lng=-70.2568, lang="en"):
        with patch.object(_location, "saved_location", return_value=saved):
            return _location.saved_label(lat, lng, lang)

    def test_the_saved_place_has_its_saved_name(self):
        self.assertEqual(self._label(self.SAVED), "Portland, Maine")
        # to four places, about ten metres, as same_place has it
        self.assertEqual(self._label(self.SAVED, 43.65912, -70.25681), "Portland, Maine")

    def test_another_place_has_none(self):
        self.assertEqual(self._label(self.SAVED, 43.68, -70.35), "")
        self.assertEqual(self._label(None), "")

    def test_a_name_in_another_language_is_no_name(self):
        # the geocoder names the place in the language on screen instead:
        # a place saved in English is München under German, not Munich
        self.assertEqual(self._label(self.SAVED, lang="de"), "")
        saved_in_japanese = dict(self.SAVED, label="ポートランド", lang="ja")
        self.assertEqual(self._label(saved_in_japanese, lang="ja"), "ポートランド")
        self.assertEqual(self._label(saved_in_japanese, lang="en"), "")
        # a name in the place's own language, from coordinates, is in none
        self.assertEqual(self._label(dict(self.SAVED, lang=""), lang="en"), "")

    def test_a_name_saved_before_its_language_was_kept_is_english(self):
        self.assertNotIn("lang", self.SAVED)
        self.assertEqual(self._label(self.SAVED, lang="en"), "Portland, Maine")
        self.assertEqual(self._label(self.SAVED, lang="fr"), "")

    def test_coordinates_saved_for_want_of_a_name_are_no_name(self):
        # `linecast location set` saves the coordinates as the label
        # when the geocoder has no name, and a view would show "43.6591"
        unnamed = dict(self.SAVED, label="43.6591,-70.2568")
        self.assertEqual(self._label(unnamed), "")

    def test_a_label_of_the_wrong_shape_is_no_name(self):
        for label in (None, 7, ["Portland"]):
            with self.subTest(label=label):
                self.assertEqual(self._label(dict(self.SAVED, label=label)), "")
        self.assertEqual(self._label({"label": "Portland"}), "")


class CountryForDefaultsTests(unittest.TestCase):
    def test_own_location_uses_the_resolved_country(self):
        self.assertEqual(
            _location.country_for_defaults(None, "US", 43.68, -70.35),
            "US",
        )

    def test_override_keeps_a_known_home_country(self):
        with patch.object(_location, "own_country", return_value="CA"), \
             patch("linecast._geocode.reverse_geocode",
                   side_effect=AssertionError("home country already known")):
            self.assertIsNone(
                _location.country_for_defaults("Portland", "", 43.68, -70.35)
            )

    def test_first_run_override_uses_the_viewed_country_as_a_fallback(self):
        with patch.object(_location, "own_country", return_value=None), \
             patch("linecast._geocode.reverse_geocode",
                   return_value=("Portland, Maine", "US", {})):
            self.assertEqual(
                _location.country_for_defaults("Portland", "", 43.68, -70.35),
                "US",
            )


class LocationPinnedTests(unittest.TestCase):
    def test_pinned_by_flag_env_or_saved(self):
        with patch.dict(os.environ, {"WEATHER_LOCATION": ""}), \
             patch.object(_location, "saved_location", return_value=None):
            self.assertTrue(_location.location_is_pinned("Lisbon"))
            self.assertFalse(_location.location_is_pinned(None))
        with patch.dict(os.environ, {"WEATHER_LOCATION": "1,2"}):
            self.assertTrue(_location.location_is_pinned(None))
        with patch.dict(os.environ, {"WEATHER_LOCATION": ""}), \
             patch.object(_location, "saved_location",
                          return_value={"lat": 1.0, "lng": 2.0}):
            self.assertTrue(_location.location_is_pinned(None))


class LocationTzinfoTests(unittest.TestCase):
    def test_resolves_zone_from_lookup(self):
        from zoneinfo import ZoneInfo
        with patch.object(_location, "fetch_json_cached",
                          return_value={"timezone": "Europe/Lisbon"}):
            self.assertEqual(_location.location_tzinfo(38.72, -9.14),
                             ZoneInfo("Europe/Lisbon"))

    @unittest.skipUnless(hasattr(time, "tzset"), "POSIX time zones")
    def test_the_machine_zone_keeps_its_clock_changes(self):
        # A new moon in November, read in October on the machine's clock,
        # must fall on standard time, not on October's offset
        from datetime import datetime
        from zoneinfo import ZoneInfo
        with patch.dict(os.environ, {"TZ": "America/Los_Angeles"}):
            time.tzset()
            zone = _location.machine_tzinfo()
        time.tzset()
        self.assertEqual(zone, ZoneInfo("America/Los_Angeles"))
        self.assertEqual(datetime(2026, 11, 20, tzinfo=zone).utcoffset().total_seconds(),
                         -8 * 3600)

    @unittest.skipUnless(hasattr(time, "tzset"), "POSIX time zones")
    def test_on_windows_the_zone_comes_by_name_from_icu(self):
        """Windows has no TZ or /etc/localtime to name the zone, and the
        fixed offset puts a date across a clock change an hour out."""
        from datetime import datetime
        from zoneinfo import ZoneInfo
        # the machine's clock is Pacific; TZ itself is no zone's name
        with patch.dict(os.environ, {"TZ": "XST8XDT,M3.2.0,M11.1.0"}):
            time.tzset()
            with patch.object(_location.sys, "platform", "win32"), \
                    patch.object(_location, "_windows_zone_name",
                                 return_value="America/Los_Angeles"):
                zone = _location.machine_tzinfo()
            with patch.object(_location.sys, "platform", "win32"), \
                    patch.object(_location, "_windows_zone_name", return_value=None):
                fixed = _location.machine_tzinfo()
        time.tzset()
        self.assertEqual(zone, ZoneInfo("America/Los_Angeles"))
        self.assertEqual(datetime(2026, 11, 20, tzinfo=zone).utcoffset().total_seconds(),
                         -8 * 3600)
        self.assertNotIsInstance(fixed, ZoneInfo)

    @unittest.skipUnless(sys.platform == "win32", "Windows' own ICU")
    def test_icu_names_a_zone_zoneinfo_knows(self):
        # CI's Windows has ICU (1903 and later do), so a None there is
        # the lookup failing, not an older Windows
        from zoneinfo import ZoneInfo
        system = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32")
        name = _location._windows_zone_name()
        if os.path.exists(os.path.join(system, "icu.dll")):
            self.assertIsNotNone(name)
        if name is not None:
            ZoneInfo(name)

    def test_a_place_is_looked_up_once_a_run(self):
        # place_for asks beside its own wait, and the view asks again:
        # a lookup that failed is not waited out a second time
        with patch.object(_location, "fetch_json_cached", return_value=None) as fetched:
            first = _location.location_tzinfo(38.72, -9.14)
            again = _location.location_tzinfo(38.72, -9.14)
        self.assertEqual(fetched.call_count, 1)
        self.assertEqual(first, again)

    def test_falls_back_to_machine_tz_when_offline(self):
        with patch.object(_location, "fetch_json_cached", return_value=None):
            self.assertEqual(_location.location_tzinfo(38.72, -9.14),
                             _location.machine_tzinfo())

    def test_a_cached_answer_of_the_wrong_shape_is_no_answer(self):
        for answer in ([1], {"timezone": 7}, "Europe/Lisbon"):
            with self.subTest(answer=answer), \
                    patch.object(_location, "fetch_json_cached", return_value=answer):
                self.assertEqual(_location.location_tzinfo(38.72, -9.14),
                                 _location.machine_tzinfo())


class PlaceForTests(unittest.TestCase):
    """What a view looks up next is looked up beside the units default's
    country, not after it: on a network that has stopped answering
    each was a timeout of its own, one after another."""

    def _place_for(self, flags, country_lookup=None, zone_lookup=None, name_lookup=None,
                   saved=None, **kw):
        from linecast import _geocode, _runtime
        from linecast._parsers import moon_parser
        args = moon_parser().parse_args(flags)
        runtime = _runtime.RuntimeConfig.from_sources(args)
        with patch.dict(os.environ, {"WEATHER_LOCATION": ""}), \
             patch.object(_location, "saved_location", return_value=saved), \
             patch.object(_location, "get_location", return_value=(3.0, 4.0, "US")), \
             patch.object(_location, "country_for_defaults",
                          side_effect=country_lookup or (lambda *a: None)), \
             patch.object(_location, "location_tzinfo",
                          side_effect=zone_lookup or (lambda *a: self.unasked.append("zone"))), \
             patch.object(_geocode, "place_label",
                          side_effect=name_lookup or (lambda *a: self.unasked.append("name"))):
            return _runtime.place_for(args, runtime, **kw)

    def setUp(self):
        self.unasked = []   # lookups made that the test did not expect

    def test_the_zone_is_looked_up_while_the_country_is(self):
        started = __import__("threading").Event()

        def country(*args):
            # a first run's units default, on a network slow to answer
            self.assertTrue(started.wait(2), "the zone waited for the country")
            return "US"

        def zone(lat, lng):
            started.set()

        found = self._place_for(["--location", "43.68,-70.35"], country, zone, zone=True)
        self.assertEqual(found[:2], (43.68, -70.35))

    def test_the_name_follows_the_country_and_goes_beside_the_zone(self):
        named, seen, order = __import__("threading").Event(), {}, []

        def zone(lat, lng):
            seen["the name was asked while the zone was"] = named.wait(2)

        def name(lat, lng, label, lang):
            seen["the country was asked first"] = order == ["country"]
            named.set()
            return "Westbrook"

        self._place_for(["--location", "43.68,-70.35"], lambda *a: order.append("country"),
                        zone, name, zone=True, name=True)
        self.assertEqual(seen, {"the name was asked while the zone was": True,
                                "the country was asked first": True})

    def test_a_saved_place_comes_with_the_name_it_was_saved_under(self):
        # sunshine, sky, radar and maps asked the geocoder for a name the
        # user had already given the place: on a stalled network, a wait
        saved = {"lat": 3.0, "lng": 4.0, "label": "Portland, Maine", "country": "US"}
        asked = []

        def name(lat, lng, label, lang):
            asked.append(label)
            return label
        found = self._place_for([], name_lookup=name, saved=saved, name=True)
        self.assertEqual(found[3], "Portland, Maine")
        self.assertEqual(asked, ["Portland, Maine"])
        # somewhere else is not the saved place, whatever was saved
        self.assertEqual(self._place_for(["--location", "43.68,-70.35"], saved=saved)[3], "")

    def test_only_what_the_view_asks_for_and_no_zone_for_where_the_machine_is(self):
        # an IP location is where the machine is, on the machine's clock
        self._place_for([], zone=True)
        self._place_for(["--location", "43.68,-70.35"])
        self.assertEqual(self.unasked, [])
        self._place_for(["--location", "43.68,-70.35"], zone=True, name=True)
        self.assertEqual(sorted(self.unasked), ["name", "zone"])


class LocationCommandTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        patcher = patch.dict(os.environ, {"LINECAST_CONFIG_DIR": self._tmpdir.name})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_set_place_name_geocodes_and_saves(self):
        result = {
            "latitude": 44.4293, "longitude": -70.0356, "name": "Fayette",
            "admin1": "Maine", "country": "United States", "country_code": "us",
        }
        with patch("linecast._geocode.geocode", return_value=[result]):
            location._cmd_set("Fayette, Maine")

        saved = _config.saved_location()
        self.assertEqual(saved["lat"], 44.4293)
        self.assertEqual(saved["lng"], -70.0356)
        self.assertEqual(saved["label"], "Fayette, Maine, United States")
        self.assertEqual(saved["country"], "US")

    def _main(self, *argv):
        asked = []
        result = {"latitude": 35.0116, "longitude": 135.7681, "name": "Kyoto",
                  "admin1": "Kyoto", "country": "Japan", "country_code": "JP"}

        def geocode(query, lang="en"):
            asked.append(query)
            return [result]
        with patch("linecast._geocode.geocode", geocode), \
                patch("linecast._geocode.reverse_geocode", return_value=("Sydney", "AU", {})), \
                patch("sys.stdout"):
            location.main(list(argv))
        return asked

    def test_a_place_by_itself_is_set(self):
        # as `linecast units metric` sets the units
        self.assertEqual(self._main("Kyoto"), ["Kyoto"])
        self.assertEqual(_config.saved_location()["label"], "Kyoto, Japan")
        self._main("-33.87,151.21")
        self.assertEqual(_config.saved_location()["lat"], -33.87)

    def test_a_name_needs_no_quotes(self):
        self.assertEqual(self._main("set", "Kyoto", "Japan"), ["Kyoto Japan"])
        self.assertEqual(self._main("Kyoto", "Japan"), ["Kyoto Japan"])

    def test_the_words_of_the_command_are_still_the_command(self):
        _config.write_config({"location": {"lat": 1.0, "lng": 2.0}})
        self.assertEqual(self._main("auto"), [])
        self.assertIsNone(_config.saved_location())

    def test_set_latlng_reverse_geocodes_for_label(self):
        with patch("linecast._geocode.reverse_geocode",
                   return_value=("Fayette, Maine", "US", {})):
            location._cmd_set("44.4293,-70.0356")

        saved = _config.saved_location()
        self.assertEqual(saved["label"], "Fayette, Maine")
        self.assertEqual(saved["country"], "US")

    def test_auto_clears_saved_location(self):
        _config.write_config({"location": {"lat": 1.0, "lng": 2.0}})
        location._cmd_auto()
        self.assertIsNone(_config.saved_location())

    def test_set_takes_a_southern_latitude(self):
        # argparse before 3.14 read "-33.87,151.21" as an option
        with patch("linecast._geocode.reverse_geocode",
                   return_value=("Sydney", "AU", {})), \
             patch("sys.argv", ["linecast location", "set", "-33.87,151.21"]), \
             patch("sys.stdout"):
            location.main()
        self.assertEqual(_config.saved_location()["lat"], -33.87)


    def test_corrupt_config_reads_as_empty(self):
        path = _config.config_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{not json")
        self.assertEqual(_config.read_config(), {})
        self.assertIsNone(_config.saved_location())

    def test_a_setting_is_not_saved_over_a_config_that_will_not_read(self):
        # A trailing comma from a hand edit: the settings it holds are
        # still the user's, and saving one would have replaced them all
        path = _config.config_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        text = '{"units": "metric", "clock": "24",}'
        path.write_text(text)
        with patch("linecast._geocode.reverse_geocode",
                   return_value=("Fayette, Maine", "US", {})), \
             self.assertRaises(UserError):
            location._cmd_set("44.4293,-70.0356")
        self.assertEqual(path.read_text(), text)

    @unittest.skipIf(os.name == "nt", "symlinks need privileges on Windows")
    def test_a_config_linked_from_dotfiles_stays_linked(self):
        path = _config.config_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        repo = Path(self._tmpdir.name) / "dotfiles" / "config.json"
        repo.parent.mkdir()
        repo.write_text('{"units": "metric"}')
        path.symlink_to(repo)
        _config.write_config({"units": "imperial"})
        self.assertTrue(path.is_symlink())
        self.assertEqual(json.loads(repo.read_text()), {"units": "imperial"})

    def test_config_that_is_not_an_object_reads_as_empty(self):
        # A hand edit can leave a list or a bare string; every reader
        # calls .get on the result.
        path = _config.config_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        for text in ("[]", '"metric"', "null", "42"):
            path.write_text(text)
            self.assertEqual(_config.read_config(), {}, text)
            self.assertIsNone(_config.saved_location(), text)

    def test_config_that_is_not_utf8_reads_as_empty(self):
        path = _config.config_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'{"units": "\xff"}')
        self.assertEqual(_config.read_config(), {})

    def test_saved_location_needs_numeric_coordinates_in_range(self):
        for loc in ({"lat": "abc", "lng": 2.0}, {"lat": 1.0, "lng": None},
                    {"lat": True, "lng": 2.0}, {"lat": 91.0, "lng": 0.0},
                    {"lat": 0.0, "lng": -181.0}, {"lat": 1.0}):
            _config.write_config({"location": loc})
            self.assertIsNone(_config.saved_location(), loc)
        _config.write_config({"location": {"lat": 51, "lng": -0.1}})
        self.assertEqual(_config.saved_location()["lat"], 51)


class NegativeCoordinateFlagTests(unittest.TestCase):
    def test_the_view_flags_take_coordinates_that_start_with_a_minus(self):
        from linecast._parsers import maps_parser, weather_parser
        args = weather_parser().parse_args(["--location", "-33.87,151.21", "--imperial"])
        self.assertEqual(args.location, "-33.87,151.21")
        args = maps_parser().parse_args(["--to", "-.5,-70", "--from", "-33.87,151.21"])
        self.assertEqual((args.to, args.from_), ("-.5,-70", "-33.87,151.21"))


class ParseLatLngTests(unittest.TestCase):
    def test_two_finite_numbers_on_the_planet(self):
        self.assertEqual(_location.parse_latlng("51.5,-0.1"), (51.5, -0.1))
        self.assertEqual(_location.parse_latlng(" -90 , 180 "), (-90.0, 180.0))

    def test_anything_else_is_not_coordinates(self):
        for text in ("91,0", "0,181", "1,2,3", "nan,0", "1e999,0", "Paris, TX",
                     "51.5", "", "abc,def", "inf,-inf"):
            self.assertIsNone(_location.parse_latlng(text), text)

    def test_an_override_off_the_planet_goes_to_the_geocoder(self):
        with patch("linecast._geocode.geocode_first", return_value=None):
            with self.assertRaises(UserError):
                _location.resolve_location("91,0")

    def test_coordinates_off_the_planet_are_called_that(self):
        with patch("linecast._geocode.geocode_first", return_value=None):
            for text in ("100,200", "-91, 0"):
                with self.assertRaises(UserError) as caught:
                    _location.resolve_location(text)
                self.assertIn("not on the planet", str(caught.exception))
            with self.assertRaises(UserError) as caught:
                _location.resolve_location("Atlantis")
            self.assertEqual(str(caught.exception), 'No locations matching "Atlantis".')

    def test_a_third_number_is_not_dropped(self):
        with patch("linecast._geocode.geocode_first",
                   return_value=(1.0, 2.0, "Somewhere")) as geo:
            self.assertEqual(_location.resolve_location("1,2,3")[:2], (1.0, 2.0))
            geo.assert_called_once()

    def test_the_settings_command_refuses_coordinates_off_the_planet(self):
        with patch("linecast._geocode.geocode", return_value=[]), \
             patch("linecast._geocode.reverse_geocode",
                   side_effect=AssertionError("not coordinates")):
            with self.assertRaises(UserError):
                location._cmd_set("91,0")


if __name__ == "__main__":
    unittest.main()
