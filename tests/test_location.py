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
        saved = {"lat": 44.4293, "lng": -70.0356, "label": "Fayette, Maine, United States", "country": "US"}
        with patch.object(_location, "saved_location", return_value=saved), \
             patch.object(_location, "fetch_json", side_effect=AssertionError("should not hit network")):
            self.assertEqual(_location.get_location(), (44.4293, -70.0356, "US"))

    def test_stale_cache_refreshes_after_one_hour(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_file = Path(tmpdir) / "location.json"
            cache_file.write_text(json.dumps({"lat": 1.0, "lng": 2.0, "country": "US"}))
            stale_at = time.time() - _location._MAX_AGE - 1
            os.utime(cache_file, (stale_at, stale_at))

            payload = {"loc": "3.0,4.0", "country": "CA"}

            with patch.object(_location, "saved_location", return_value=None), \
                 patch.object(_location, "_CACHE_FILE", cache_file), \
                 patch.object(_location, "fetch_json", return_value=payload):
                location = _location.get_location()

        self.assertEqual(location, (3.0, 4.0, "CA"))


class LocationCommandTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        patcher = patch.dict(os.environ, {"XDG_CONFIG_HOME": self._tmpdir.name})
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
