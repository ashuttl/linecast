import unittest
from datetime import date
from unittest.mock import patch

from linecast import _tides_chs as chs


class YRangeTests(unittest.TestCase):
    def test_cache_key_is_month_anchored_and_window_covers_30_days(self):
        seen = []

        def fake_read_cache(path, max_age):
            seen.append(path.name)
            return None

        data = [{"eventDate": "2026-08-01T05:00:00Z", "value": "3.0"},
                {"eventDate": "2026-08-01T11:00:00Z", "value": "0.5"}]
        with patch.object(chs, "read_cache", side_effect=fake_read_cache), \
             patch.object(chs, "fetch_json", return_value=data) as fj, \
             patch.object(chs, "write_cache"):
            for day in (date(2026, 8, 23), date(2026, 8, 24)):
                lo, hi = chs.fetch_y_range_chs("05320", day, None)

        self.assertAlmostEqual(lo, 0.5 * chs.M_TO_FT)
        self.assertAlmostEqual(hi, 3.0 * chs.M_TO_FT)
        self.assertEqual(seen, ["chs_yrange_05320_202608.json"] * 2)
        # July 1 through September 30, in UTC because no station tz was given
        self.assertIn("from=2026-07-01T00:00:00Z&to=2026-10-01T00:00:00Z",
                      fj.call_args.args[0])

    def test_returns_cached_y_range(self):
        with patch.object(chs, "read_cache", return_value={"min": -0.5, "max": 3.0}):
            self.assertEqual(chs.fetch_y_range_chs("05320", date(2026, 3, 27), None),
                             (-0.5, 3.0))


if __name__ == "__main__":
    unittest.main()
