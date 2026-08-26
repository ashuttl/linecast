"""Tests for Queensland tide data source.

These use fixture data that mirrors the QLD Government Open Data Portal
CKAN API responses: package_search for the "predicted interval data"
gauge packages, datastore_search for a year resource's records.  If the
API changes format, these tests will catch it.
"""

import json
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

FIXTURES = Path(__file__).parent / "fixtures"
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from linecast import _tides_common as common
from linecast import _tides_qld as qld
from linecast._tides_providers import QLD as QLD_PROVIDER


def _load(name):
    return json.loads((FIXTURES / name).read_text())


STATIONS = [
    {"name": "Brisbane Bar", "package": "brisbane-bar-tide-gauge-predicted-interval-data",
     "lat": -27.3667, "lng": 153.1667, "years": {"2026": "bb-2026", "2025": "bb-2025"}},
    {"name": "Cairns", "package": "cairns-tide-gauge-predicted-interval-data",
     "lat": -16.9167, "lng": 145.7667, "years": {"2026": "cairns-2026"}},
    {"name": "Southport", "package": "southport-tide-gauge-predicted-interval-data",
     "lat": -27.9667, "lng": 153.4167, "years": {"2026": "sp-2026"}},
]


# ---------------------------------------------------------------------------
# Station discovery (package_search fixture parsing)
# ---------------------------------------------------------------------------

class TestStationList(unittest.TestCase):
    """The gauge list comes from one package_search response."""

    def _stations(self):
        data = _load("qld_package_search.json")
        with patch.object(qld, "read_cache", return_value=None), \
             patch.object(qld, "write_cache"), \
             patch.object(qld, "fetch_json", return_value=data):
            return qld.fetch_all_stations_qld()

    def test_gauges_parsed_with_display_names(self):
        names = {s["name"] for s in self._stations()}
        self.assertEqual(names, {"Southport", "Shorncliffe", "Brisbane Bar"})

    def test_high_low_packages_are_filtered_out(self):
        packages = {s["package"] for s in self._stations()}
        self.assertNotIn("badu-island-tide-gauge-predicted-high-low-data", packages)

    def test_only_datastore_active_year_resources_kept(self):
        southport = next(s for s in self._stations() if s["name"] == "Southport")
        self.assertEqual(set(southport["years"]), {"2025", "2026"})
        self.assertEqual(southport["years"]["2026"],
                         "e091aba3-bf77-48d9-8d8b-8eed5ac28556")

    def test_year_parsed_from_either_resource_name_spelling(self):
        """Resource names read "2026—..." or "2026 — ..." depending on the
        package; both carry the year."""
        shorncliffe = next(s for s in self._stations() if s["name"] == "Shorncliffe")
        self.assertEqual(set(shorncliffe["years"]), {"2024", "2025", "2026"})

    def test_coordinates_joined_from_baked_table(self):
        southport = next(s for s in self._stations() if s["name"] == "Southport")
        self.assertAlmostEqual(southport["lat"], -27.9667)
        self.assertAlmostEqual(southport["lng"], 153.4167)


# ---------------------------------------------------------------------------
# QLD tide predictions (datastore_search fixture parsing)
# ---------------------------------------------------------------------------

class TestQLDTidePredictions:
    """Verify we can parse a real-shaped QLD datastore_search response."""

    def setup_method(self):
        self.data = _load("qld_tide_predictions.json")

    def test_has_result_records(self):
        assert "result" in self.data
        assert "records" in self.data["result"]
        assert len(self.data["result"]["records"]) > 0

    def test_record_shape(self):
        """Each record has the fields our parser extracts."""
        for rec in self.data["result"]["records"][:5]:
            assert "Date" in rec, "Missing 'Date' field"
            assert "Time" in rec, "Missing 'Time' field"
            assert "Reading" in rec, "Missing 'Reading' field"

    def test_datetime_parseable(self):
        for rec in self.data["result"]["records"][:5]:
            dt = qld._parse_gauge_dt(rec["Date"], rec["Time"])
            assert dt.year >= 2020

    def test_reading_values_numeric(self):
        for rec in self.data["result"]["records"][:5]:
            float(rec["Reading"])  # should not raise

    def test_ten_minute_intervals(self):
        """QLD data comes in 10-minute intervals (fetched newest-first)."""
        records = self.data["result"]["records"]
        dt1 = qld._parse_gauge_dt(records[0]["Date"], records[0]["Time"])
        dt2 = qld._parse_gauge_dt(records[1]["Date"], records[1]["Time"])
        assert (dt1 - dt2).total_seconds() == 600


# ---------------------------------------------------------------------------
# Prediction fetching
# ---------------------------------------------------------------------------

class TestPredictionFetch(unittest.TestCase):
    def _chunk(self, day=date(2026, 8, 26)):
        data = _load("qld_tide_predictions.json")
        with patch.object(qld, "read_cache", return_value=None), \
             patch.object(qld, "write_cache"), \
             patch.object(qld, "fetch_all_stations_qld", return_value=STATIONS), \
             patch.object(qld, "fetch_json", return_value=data) as fj:
            points = qld._fetch_pred_chunk("Southport", day, day)
        return points, fj

    def test_chunk_parses_all_records(self):
        points, _ = self._chunk()
        self.assertEqual(len(points), 144)

    def test_heights_converted_to_feet(self):
        points, _ = self._chunk()
        by_time = {dt.strftime("%H:%M"): h for dt, h in points}
        self.assertAlmostEqual(by_time["00:00"], 0.528 * common.M_TO_FT)

    def test_timestamps_are_aest(self):
        points, _ = self._chunk()
        self.assertEqual(points[0][0].utcoffset(), timedelta(hours=10))

    def test_request_filters_on_the_requested_dates(self):
        _, fj = self._chunk()
        url = fj.call_args.args[0]
        self.assertIn("sp-2026", url)
        self.assertIn("26%2F08%2F2026", url)

    def test_year_without_resource_is_skipped(self):
        """A window past the published years fetches nothing and returns
        what there is (nothing)."""
        with patch.object(qld, "read_cache", return_value=None), \
             patch.object(qld, "write_cache"), \
             patch.object(qld, "fetch_all_stations_qld", return_value=STATIONS), \
             patch.object(qld, "fetch_json") as fj:
            points = qld._fetch_pred_chunk("Southport",
                                           date(2027, 3, 1), date(2027, 3, 2))
        self.assertEqual(points, [])
        fj.assert_not_called()

    def test_unknown_station_fetches_nothing(self):
        with patch.object(qld, "read_cache", return_value=None), \
             patch.object(qld, "write_cache") as wc, \
             patch.object(qld, "fetch_all_stations_qld", return_value=[]), \
             patch.object(qld, "fetch_json") as fj:
            points = qld._fetch_pred_chunk("Southport",
                                           date(2026, 8, 26), date(2026, 8, 26))
        self.assertEqual(points, [])
        fj.assert_not_called()
        wc.assert_not_called()

    def test_range_sorts_and_dedups_newest_first(self):
        """Records arrive newest-first with re-uploaded duplicates; the
        range keeps one point per minute, in time order."""
        data = {"result": {"records": [
            {"Date": "26/08/2026", "Time": "00:10", "Reading": "1.100"},
            {"Date": "26/08/2026", "Time": "00:00", "Reading": "1.000"},
            {"Date": "26/08/2026", "Time": "00:10", "Reading": "9.999"},
        ]}}
        with patch.object(qld, "read_cache", return_value=None), \
             patch.object(qld, "write_cache"), \
             patch.object(qld, "fetch_all_stations_qld", return_value=STATIONS), \
             patch.object(qld, "fetch_json", return_value=data):
            points = qld.fetch_tides_range_qld("Southport",
                                               date(2026, 8, 26), date(2026, 8, 26))
        self.assertEqual([dt.strftime("%H:%M") for dt, _ in points],
                         ["00:00", "00:10"])
        self.assertAlmostEqual(points[1][1], 1.100 * common.M_TO_FT)


# ---------------------------------------------------------------------------
# Station discovery (nearest, with mocks)
# ---------------------------------------------------------------------------

class TestStationDiscovery(unittest.TestCase):
    def test_find_nearest_station_returns_closest(self):
        """Cairns should be found when searching near its coordinates."""
        with patch.object(common, "read_cache", return_value=None), \
             patch.object(qld, "fetch_all_stations_qld", return_value=STATIONS), \
             patch.object(common, "write_cache"):
            station_id, station_name = qld.find_nearest_station_qld(-16.92, 145.78)

        self.assertEqual(station_id, "Cairns")
        self.assertEqual(station_name, "Cairns")

    def test_find_nearest_station_returns_none_when_too_far(self):
        """Stations beyond 100nm should return (None, None)."""
        stations = [s for s in STATIONS if s["name"] == "Cairns"]
        # Sydney is far from Cairns
        with patch.object(common, "read_cache", return_value=None), \
             patch.object(qld, "fetch_all_stations_qld", return_value=stations), \
             patch.object(common, "write_cache"):
            station_id, station_name = qld.find_nearest_station_qld(-33.87, 151.21)

        self.assertIsNone(station_id)
        self.assertIsNone(station_name)

    def test_station_without_coordinates_is_never_nearest(self):
        stations = [
            {"name": "Cairns Beacon C1", "lat": None, "lng": None,
             "years": {"2026": "c1-2026"}},
            {"name": "Cairns", "lat": -16.9167, "lng": 145.7667,
             "years": {"2026": "cairns-2026"}},
        ]
        with patch.object(common, "read_cache", return_value=None), \
             patch.object(qld, "fetch_all_stations_qld", return_value=stations), \
             patch.object(common, "write_cache"):
            station_id, _ = qld.find_nearest_station_qld(-16.92, 145.78)

        self.assertEqual(station_id, "Cairns")

    def test_find_nearest_uses_cache(self):
        """Cached result should be returned without fetching."""
        cached = {"id": "Cairns", "name": "Cairns"}
        with patch.object(common, "read_cache", return_value=cached):
            station_id, station_name = qld.find_nearest_station_qld(-16.92, 145.78)

        self.assertEqual(station_id, "Cairns")
        self.assertEqual(station_name, "Cairns")

    def test_find_nearest_uses_stale_on_error(self):
        """Stale cache should be used when the API fails."""
        stale = {"id": "Cairns", "name": "Cairns"}
        with patch.object(common, "read_cache", return_value=None), \
             patch.object(qld, "fetch_all_stations_qld", side_effect=RuntimeError("boom")), \
             patch.object(common, "read_stale", return_value=stale):
            station_id, station_name = qld.find_nearest_station_qld(-16.92, 145.78)

        self.assertEqual(station_id, "Cairns")
        self.assertEqual(station_name, "Cairns")


# ---------------------------------------------------------------------------
# Legacy monitoring-feed station names
# ---------------------------------------------------------------------------

class TestLegacyMigration(unittest.TestCase):
    def test_old_slug_resolves_to_nearest_gauge(self):
        """"birkdale" was a monitoring-feed site; Brisbane Bar is the
        gauge nearest it."""
        with patch.object(qld, "fetch_all_stations_qld", return_value=STATIONS):
            station = qld.legacy_station_for_slug("birkdale")
        self.assertEqual(station["name"], "Brisbane Bar")

    def test_unknown_slug_resolves_to_nothing(self):
        with patch.object(qld, "fetch_all_stations_qld", return_value=STATIONS):
            self.assertIsNone(qld.legacy_station_for_slug("atlantis"))

    def test_data_flows_under_an_old_name(self):
        """A stale nearest-station cache can still name an old site; the
        data layer follows it to the gauge rather than coming up empty."""
        with patch.object(qld, "fetch_all_stations_qld", return_value=STATIONS):
            record = qld._station_record("birkdale")
        self.assertEqual(record["name"], "Brisbane Bar")

    def test_provider_search_falls_back_to_legacy_slug(self):
        with patch.object(qld, "fetch_all_stations_qld", return_value=STATIONS):
            found = QLD_PROVIDER.search("birkdale", ["birkdale"])
        self.assertEqual([f["id"] for f in found], ["Brisbane Bar"])

    def test_provider_search_prefers_real_matches(self):
        """A query matching a gauge never takes the legacy path, even if
        it also names an old site."""
        with patch.object(qld, "fetch_all_stations_qld", return_value=STATIONS), \
             patch.object(qld, "legacy_station_for_slug") as legacy:
            found = QLD_PROVIDER.search("southport", ["southport"])
        self.assertEqual([f["id"] for f in found], ["Southport"])
        legacy.assert_not_called()


# ---------------------------------------------------------------------------
# Station metadata
# ---------------------------------------------------------------------------

class TestStationMetadata(unittest.TestCase):
    def test_metadata_shape(self):
        """Metadata should match the normalized shape expected by tides.py."""
        with patch.object(qld, "read_cache", return_value=None), \
             patch.object(qld, "fetch_all_stations_qld", return_value=STATIONS), \
             patch.object(qld, "write_cache"):
            meta = qld.fetch_station_metadata_qld("Cairns")

        self.assertEqual(meta["id"], "Cairns")
        self.assertEqual(meta["name"], "Cairns")
        self.assertEqual(meta["state"], "QLD")
        self.assertEqual(meta["timezone_abbr"], "AEST")
        self.assertEqual(meta["timezonecorr"], 10)
        self.assertEqual(meta["timeZoneCode"], "Australia/Brisbane")
        self.assertFalse(meta["observedst"])
        self.assertEqual(meta["source"], "qld")
        self.assertAlmostEqual(meta["lat"], -16.9167)
        self.assertAlmostEqual(meta["lng"], 145.7667)


# ---------------------------------------------------------------------------
# Datetime parsing
# ---------------------------------------------------------------------------

class TestDatetimeParsing(unittest.TestCase):
    def test_parse_gauge_dt(self):
        dt = qld._parse_gauge_dt("27/03/2026", "10:40")
        self.assertEqual(dt.year, 2026)
        self.assertEqual(dt.month, 3)
        self.assertEqual(dt.day, 27)
        self.assertEqual(dt.hour, 10)
        self.assertEqual(dt.minute, 40)
        self.assertIsNotNone(dt.tzinfo)
        # Should be AEST (UTC+10)
        self.assertEqual(dt.utcoffset(), timedelta(hours=10))


# ---------------------------------------------------------------------------
# Y-axis range
# ---------------------------------------------------------------------------

class TestYRange(unittest.TestCase):
    def test_cache_key_is_month_anchored(self):
        seen = []

        def fake_read_cache(path, max_age):
            seen.append(path.name)
            return {"min": 0.0, "max": 1.0}

        with patch.object(common, "read_cache", side_effect=fake_read_cache):
            qld.fetch_y_range_qld("Southport", date(2026, 3, 27))
            qld.fetch_y_range_qld("Southport", date(2026, 3, 28))

        self.assertEqual(seen, ["qld_yrange_Southport_202603.json"] * 2)

    def test_range_spans_the_month_window_in_one_request(self):
        """The window is the same three calendar months the other
        providers measure, fetched as readings alone."""
        data = {"result": {"records": [{"Reading": "0.5"}, {"Reading": "3.0"}]}}
        with patch.object(common, "read_cache", return_value=None), \
             patch.object(common, "write_cache"), \
             patch.object(qld, "fetch_all_stations_qld", return_value=STATIONS), \
             patch.object(qld, "fetch_json", return_value=data) as fj:
            got = qld.fetch_y_range_qld("Cairns", date(2026, 3, 27))

        self.assertAlmostEqual(got[0], 0.5 * common.M_TO_FT)
        self.assertAlmostEqual(got[1], 3.0 * common.M_TO_FT)
        fj.assert_called_once()
        url = fj.call_args.args[0]
        self.assertIn("cairns-2026", url)
        self.assertIn("01%2F02%2F2026", url)
        self.assertIn("30%2F04%2F2026", url)


# ---------------------------------------------------------------------------
# QLD geo-detection helper (in tides.py)
# ---------------------------------------------------------------------------

class TestQLDBoundaryDetection(unittest.TestCase):
    def test_cairns_is_qld(self):
        from linecast.tides import _is_qld_lat_lng
        self.assertTrue(_is_qld_lat_lng(-16.92, 145.78))

    def test_sydney_is_not_qld(self):
        from linecast.tides import _is_qld_lat_lng
        self.assertFalse(_is_qld_lat_lng(-33.87, 151.21))

    def test_brisbane_is_qld(self):
        from linecast.tides import _is_qld_lat_lng
        self.assertTrue(_is_qld_lat_lng(-27.47, 153.03))

    def test_darwin_is_not_qld(self):
        from linecast.tides import _is_qld_lat_lng
        self.assertFalse(_is_qld_lat_lng(-12.46, 130.84))


if __name__ == "__main__":
    unittest.main()
