import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from linecast import _config, _location, location


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

    def test_every_source_down_is_no_location(self):
        def fake(url, headers=None, timeout=0):
            raise OSError("down")

        self.assertEqual(self._get_location(fake), (None, None, None))


class GeocoderFallbackTests(unittest.TestCase):
    def test_photon_answers_when_open_meteo_fails(self):
        from linecast import _weather_sources
        feature = {"properties": {"name": "Westbrook", "state": "Maine",
                                  "country": "United States",
                                  "countrycode": "US"},
                   "geometry": {"coordinates": [-70.37, 43.68]}}

        def fake(url, headers=None, timeout=0):
            from urllib.parse import urlsplit
            if urlsplit(url).hostname == "geocoding-api.open-meteo.com":
                raise OSError("down")
            return {"features": [feature]}

        with patch.object(_weather_sources, "fetch_json", side_effect=fake):
            hit = _weather_sources.geocode_first("Westbrook")
        self.assertEqual(hit, (43.68, -70.37, "Westbrook, Maine, United States"))

    def test_both_geocoders_down_exits(self):
        from linecast import _weather_sources
        with patch.object(_weather_sources, "fetch_json",
                          side_effect=OSError("down")):
            with self.assertRaises(SystemExit):
                _weather_sources._geocode_query("Westbrook")


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
        with patch("linecast._weather_sources.geocode_first",
                   return_value=(43.68, -70.35, "Westbrook, Maine")):
            self.assertEqual(
                _location.resolve_location("Westbrook"), (43.68, -70.35, ""))

    def test_unmatched_place_name_exits(self):
        with patch("linecast._weather_sources.geocode_first", return_value=None):
            with self.assertRaises(SystemExit) as cm:
                _location.resolve_location("Nowhereville Q")
        # a string code prints to stderr and exits 1, once the caller's
        # finally blocks (radar's spinner) have run
        self.assertEqual(cm.exception.code, 'No locations matching "Nowhereville Q".')

    def test_return_label_carries_the_geocoder_hit(self):
        with patch("linecast._weather_sources.geocode_first",
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

    def test_need_country_reverse_geocodes_override(self):
        with patch("linecast._weather_sources._reverse_geocode",
                   return_value=("Saint John", "CA", {})):
            self.assertEqual(
                _location.resolve_location("45.25,-66.06", need_country=True),
                (45.25, -66.06, "CA"))


class CountryForDefaultsTests(unittest.TestCase):
    def test_own_location_uses_the_resolved_country(self):
        self.assertEqual(
            _location.country_for_defaults(None, "US", 43.68, -70.35),
            "US",
        )

    def test_override_keeps_a_known_home_country(self):
        with patch.object(_location, "own_country", return_value="CA"), \
             patch("linecast._weather_sources._reverse_geocode",
                   side_effect=AssertionError("home country already known")):
            self.assertIsNone(
                _location.country_for_defaults("Portland", "", 43.68, -70.35)
            )

    def test_first_run_override_uses_the_viewed_country_as_a_fallback(self):
        with patch.object(_location, "own_country", return_value=None), \
             patch("linecast._weather_sources._reverse_geocode",
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

    def test_falls_back_to_machine_tz_when_offline(self):
        from datetime import datetime
        machine = datetime.now().astimezone().tzinfo
        with patch.object(_location, "fetch_json_cached", return_value=None):
            self.assertEqual(_location.location_tzinfo(38.72, -9.14), machine)


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
        with patch("linecast._weather_sources._geocode_query", return_value=[result]):
            location._cmd_set("Fayette, Maine")

        saved = _config.saved_location()
        self.assertEqual(saved["lat"], 44.4293)
        self.assertEqual(saved["lng"], -70.0356)
        self.assertEqual(saved["label"], "Fayette, Maine, United States")
        self.assertEqual(saved["country"], "US")

    def test_set_latlng_reverse_geocodes_for_label(self):
        with patch("linecast._weather_sources._reverse_geocode",
                   return_value=("Fayette, Maine", "US", {})):
            location._cmd_set("44.4293,-70.0356")

        saved = _config.saved_location()
        self.assertEqual(saved["label"], "Fayette, Maine")
        self.assertEqual(saved["country"], "US")

    def test_auto_clears_saved_location(self):
        _config.write_config({"location": {"lat": 1.0, "lng": 2.0}})
        location._cmd_auto()
        self.assertIsNone(_config.saved_location())

    def test_corrupt_config_reads_as_empty(self):
        path = _config.config_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{not json")
        self.assertEqual(_config.read_config(), {})
        self.assertIsNone(_config.saved_location())


if __name__ == "__main__":
    unittest.main()
