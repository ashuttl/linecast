import json
import os
import time
import unittest
from datetime import date, datetime, timezone
from unittest.mock import patch

import pytest

from linecast.tides import chs
from linecast.tides import common


class YRangeTests(unittest.TestCase):
    def test_cache_key_is_month_anchored_and_window_covers_30_days(self):
        seen = []

        def fake_read_cache(path, max_age):
            seen.append(path.name)
            return None

        data = [{"eventDate": "2026-08-01T05:00:00Z", "value": "3.0"},
                {"eventDate": "2026-08-01T11:00:00Z", "value": "0.5"}]
        with patch.object(common, "read_cache", side_effect=fake_read_cache), \
             patch.object(chs, "fetch_json", return_value=data) as fj, \
             patch.object(common, "write_cache"):
            for day in (date(2026, 8, 23), date(2026, 8, 24)):
                lo, hi = chs.fetch_y_range_chs("05320", day, None)

        self.assertAlmostEqual(lo, 0.5 * chs.M_TO_FT)
        self.assertAlmostEqual(hi, 3.0 * chs.M_TO_FT)
        self.assertEqual(seen, ["chs_yrange_05320_202608.json"] * 2)
        # July 1 through September 30, in UTC because no station tz was given
        self.assertIn("from=2026-07-01T00:00:00Z&to=2026-10-01T00:00:00Z",
                      fj.call_args.args[0])

    def test_returns_cached_y_range(self):
        with patch.object(common, "read_cache", return_value={"min": -0.5, "max": 3.0}):
            self.assertEqual(chs.fetch_y_range_chs("05320", date(2026, 3, 27), None),
                             (-0.5, 3.0))


class NearestStationTests(unittest.TestCase):
    STATIONS = [
        # a current station, nearer the place than any tide station
        {"id": "a" * 24, "officialName": "Second Narrows", "operating": True,
         "latitude": 49.2947, "longitude": -123.0245,
         "timeSeries": [{"code": "wcp1-events"}, {"code": "wcsp1"}]},
        {"id": "b" * 24, "officialName": "Vancouver", "operating": True,
         "latitude": 49.287, "longitude": -123.11,
         "timeSeries": [{"code": "wlo"}, {"code": "wlp"}, {"code": "wlp-hilo"}]},
    ]

    def test_a_station_with_no_water_levels_is_not_picked(self):
        with patch.object(chs, "fetch_all_stations_chs", return_value=self.STATIONS), \
             patch.object(common, "read_cache", return_value=None), \
             patch.object(common, "write_cache"):
            self.assertEqual(chs.find_nearest_station_chs(49.30, -123.02),
                             ("b" * 24, "Vancouver"))


class TestOffline:
    """With CHS out of reach (the tests have no network), an expired
    file's rows stand in for the answer: the file holds rows parsed from
    CHS's list, never the list."""

    ROWS = [{"dt": "2026-09-01T00:00:00+00:00", "v": 1.0, "t": "H"},
            {"dt": "2026-09-01T06:05:00+00:00", "v": 0.1, "t": "L"}]

    @pytest.fixture(autouse=True)
    def cache(self, tmp_path):
        with patch.dict(os.environ, {"LINECAST_CACHE_DIR": str(tmp_path)}):
            yield tmp_path

    def _expired(self, kind):
        path = common.cache_dir() / f"chs_{kind}_X_20260901_20260902.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.ROWS))
        then = time.time() - 3 * 86400
        os.utime(path, (then, then))
        return path

    def test_predictions_keep_the_last_rows(self):
        path = self._expired("pred")
        points = chs._fetch_pred_chunk("X", date(2026, 9, 1), date(2026, 9, 2), timezone.utc)
        assert points == [(datetime(2026, 9, 1, 0, 0, tzinfo=timezone.utc), 1.0),
                          (datetime(2026, 9, 1, 6, 5, tzinfo=timezone.utc), 0.1)]
        # and the stale copy is left as it was, not written over as fresh
        assert json.loads(path.read_text()) == self.ROWS
        assert time.time() - path.stat().st_mtime > 86400

    def test_extremes_keep_the_last_rows(self):
        path = self._expired("hilo")
        points = chs.fetch_hilo_range_chs("X", date(2026, 9, 1), date(2026, 9, 2), timezone.utc)
        assert points == [(datetime(2026, 9, 1, 0, 0, tzinfo=timezone.utc), 1.0, "H"),
                          (datetime(2026, 9, 1, 6, 5, tzinfo=timezone.utc), 0.1, "L")]
        assert json.loads(path.read_text()) == self.ROWS

    def test_nothing_cached_is_nothing(self):
        assert chs._fetch_pred_chunk("X", date(2026, 9, 1), date(2026, 9, 2), timezone.utc) == []


class TestFetchedAsCached:
    """A run that fetches reads its points back from the rows it keeps,
    as a run that finds them cached does: aware in a fixed offset, so a
    time past a change of clock is placed by the hours that have passed."""

    PAYLOAD = [{"eventDate": "2026-10-31T15:00:00Z", "value": "1.0"},
               {"eventDate": "2026-11-01T18:00:00Z", "value": "0.2"}]

    @pytest.fixture(autouse=True)
    def cache(self, tmp_path):
        with patch.dict(os.environ, {"LINECAST_CACHE_DIR": str(tmp_path)}):
            yield tmp_path

    @pytest.mark.parametrize("fetch", [chs._fetch_pred_chunk, chs.fetch_hilo_range_chs])
    def test_the_same_points_either_way(self, fetch):
        from zoneinfo import ZoneInfo
        from linecast import _http
        halifax = ZoneInfo("America/Halifax")
        args = ("X", date(2026, 10, 31), date(2026, 11, 1), halifax)
        with patch.object(_http, "fetch_json", return_value=self.PAYLOAD):
            fetched = fetch(*args)
        cached = fetch(*args)  # the network is off: this is the file
        assert fetched == cached
        # Halifax's clocks go back at 2am on 1 November: 27 hours pass
        start = datetime(2026, 10, 31, 12, 0, tzinfo=halifax)
        assert [(p[0] - start).total_seconds() / 3600 for p in fetched] == [0, 27]


if __name__ == "__main__":
    unittest.main()
