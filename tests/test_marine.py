import unittest
from datetime import datetime
from unittest.mock import patch

from linecast import _marine as marine
from linecast._runtime import TidesRuntime


class CompassDirectionTests(unittest.TestCase):
    def test_cardinal_directions(self):
        self.assertEqual(marine._compass_direction(0), "N")
        self.assertEqual(marine._compass_direction(90), "E")
        self.assertEqual(marine._compass_direction(180), "S")
        self.assertEqual(marine._compass_direction(270), "W")
        self.assertEqual(marine._compass_direction(360), "N")

    def test_intercardinal_directions(self):
        self.assertEqual(marine._compass_direction(45), "NE")
        self.assertEqual(marine._compass_direction(135), "SE")
        self.assertEqual(marine._compass_direction(225), "SW")
        self.assertEqual(marine._compass_direction(315), "NW")

    def test_none_returns_empty(self):
        self.assertEqual(marine._compass_direction(None), "")


class FetchMarineTests(unittest.TestCase):
    def test_fetch_marine_calls_fetch_json_cached(self):
        fake_data = {"hourly": {"time": ["2026-03-27T12:00"], "wave_height": [1.5]}}

        with patch.object(marine, "fetch_json_cached", return_value=fake_data) as mock_fetch:
            result = marine.fetch_marine(43.66, -70.25)

        self.assertEqual(result, fake_data)
        mock_fetch.assert_called_once()
        call_args = mock_fetch.call_args
        self.assertIn("marine-api.open-meteo.com", call_args.args[2])
        self.assertIn("wave_height", call_args.args[2])
        self.assertEqual(call_args.args[1], 3600)

    def test_fetch_marine_returns_none_on_failure(self):
        with patch.object(marine, "fetch_json_cached", return_value=None):
            result = marine.fetch_marine(43.66, -70.25)

        self.assertIsNone(result)


class ParseMarineCurrentTests(unittest.TestCase):
    def _make_data(self, times, **hourly_fields):
        return {"hourly": {"time": times, **hourly_fields}}

    def test_parses_current_conditions(self):
        data = self._make_data(
            ["2026-03-27T11:00", "2026-03-27T12:00", "2026-03-27T13:00"],
            wave_height=[1.0, 1.5, 2.0],
            wave_period=[7, 8, 9],
            wave_direction=[180, 200, 220],
            swell_wave_height=[0.5, 0.8, 1.0],
            swell_wave_period=[10, 12, 14],
            swell_wave_direction=[250, 260, 270],
        )
        target = datetime(2026, 3, 27, 12, 15)
        result = marine.parse_marine_current(data, target)

        self.assertIsNotNone(result)
        self.assertEqual(result["wave_height"], 1.5)
        self.assertEqual(result["wave_period"], 8)
        self.assertEqual(result["wave_direction"], 200)
        self.assertEqual(result["swell_height"], 0.8)
        self.assertEqual(result["swell_period"], 12)
        self.assertEqual(result["swell_direction"], 260)

    def test_picks_closest_hour(self):
        data = self._make_data(
            ["2026-03-27T11:00", "2026-03-27T12:00"],
            wave_height=[1.0, 2.0],
        )
        # 11:20 is closer to 11:00
        result = marine.parse_marine_current(data, datetime(2026, 3, 27, 11, 20))
        self.assertEqual(result["wave_height"], 1.0)

        # 11:40 is closer to 12:00
        result = marine.parse_marine_current(data, datetime(2026, 3, 27, 11, 40))
        self.assertEqual(result["wave_height"], 2.0)

    def test_returns_none_for_empty_data(self):
        self.assertIsNone(marine.parse_marine_current(None))
        self.assertIsNone(marine.parse_marine_current({}))
        self.assertIsNone(marine.parse_marine_current({"hourly": {}}))
        self.assertIsNone(marine.parse_marine_current({"hourly": {"time": []}}))

    def test_returns_none_when_all_values_none(self):
        data = self._make_data(
            ["2026-03-27T12:00"],
            wave_height=[None],
            swell_wave_height=[None],
        )
        result = marine.parse_marine_current(data, datetime(2026, 3, 27, 12, 0))
        self.assertIsNone(result)

    def test_handles_missing_swell_data(self):
        data = self._make_data(
            ["2026-03-27T12:00"],
            wave_height=[1.5],
            wave_period=[8],
            wave_direction=[180],
        )
        result = marine.parse_marine_current(data, datetime(2026, 3, 27, 12, 0))
        self.assertIsNotNone(result)
        self.assertEqual(result["wave_height"], 1.5)
        self.assertIsNone(result["swell_height"])


class FormatMarineLineTests(unittest.TestCase):
    def _runtime(self, metric=False, lang="en"):
        return TidesRuntime(live=False, emoji=False, lang=lang, metric=metric)

    def test_format_waves_and_swell_metric(self):
        marine_info = {
            "wave_height": 1.5,
            "wave_period": 8,
            "wave_direction": 200,
            "swell_height": 0.8,
            "swell_period": 12,
            "swell_direction": 270,
        }
        line = marine.format_marine_line(marine_info, self._runtime(metric=True))
        self.assertIn("Waves", line)
        self.assertIn("1.5m", line)
        self.assertIn("8s", line)
        self.assertIn("SSW", line)
        self.assertIn("Swell", line)
        self.assertIn("0.8m", line)
        self.assertIn("12s", line)
        self.assertIn("W", line)

    def test_format_waves_imperial(self):
        marine_info = {
            "wave_height": 1.0,
            "wave_period": 7,
            "wave_direction": 90,
            "swell_height": None,
            "swell_period": None,
            "swell_direction": None,
        }
        line = marine.format_marine_line(marine_info, self._runtime(metric=False))
        self.assertIn("Waves", line)
        # 1.0m = 3.3ft
        self.assertIn("\u2032", line)  # prime (foot symbol)
        self.assertNotIn("Swell", line)

    def test_format_returns_empty_for_none(self):
        self.assertEqual(marine.format_marine_line(None, self._runtime()), "")

    def test_format_respects_language(self):
        marine_info = {
            "wave_height": 1.5,
            "wave_period": 8,
            "wave_direction": 180,
            "swell_height": None,
            "swell_period": None,
            "swell_direction": None,
        }
        line = marine.format_marine_line(marine_info, self._runtime(lang="fr", metric=True))
        self.assertIn("Vagues", line)

        line = marine.format_marine_line(marine_info, self._runtime(lang="ja", metric=True))
        self.assertIn("\u6ce2", line)

    def test_zero_swell_height_omitted(self):
        marine_info = {
            "wave_height": 1.0,
            "wave_period": 7,
            "wave_direction": 90,
            "swell_height": 0,
            "swell_period": 10,
            "swell_direction": 270,
        }
        line = marine.format_marine_line(marine_info, self._runtime())
        self.assertNotIn("Swell", line)


class FormatHeightTests(unittest.TestCase):
    def _runtime(self, metric=False):
        return TidesRuntime(live=False, emoji=False, lang="en", metric=metric)

    def test_metric_height(self):
        self.assertEqual(marine._format_height(1.5, self._runtime(metric=True)), "1.5m")

    def test_imperial_height(self):
        result = marine._format_height(1.0, self._runtime(metric=False))
        self.assertIn("3.3", result)
        self.assertIn("\u2032", result)


if __name__ == "__main__":
    unittest.main()
