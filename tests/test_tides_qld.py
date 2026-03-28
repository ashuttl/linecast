"""Tests for Queensland tide data source.

These use fixture data that mirrors the QLD Government Open Data Portal
CKAN API responses.  If the API changes format, these tests will catch it.
"""

import json
import sys
import unittest
from datetime import date, datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

FIXTURES = Path(__file__).parent / "fixtures"
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from linecast import _tides_qld as qld
from linecast._cache import location_cache_key


def _load(name):
    return json.loads((FIXTURES / name).read_text())


# ---------------------------------------------------------------------------
# QLD tide predictions (fixture parsing)
# ---------------------------------------------------------------------------

class TestQLDTidePredictions:
    """Verify we can parse a real-shaped QLD CKAN API response."""

    def setup_method(self):
        self.data = _load("qld_tide_predictions.json")

    def test_has_result_records(self):
        assert "result" in self.data
        assert "records" in self.data["result"]
        assert len(self.data["result"]["records"]) > 0

    def test_record_shape(self):
        """Each record has the fields our parser extracts."""
        for rec in self.data["result"]["records"][:5]:
            assert "Site" in rec, "Missing 'Site' field"
            assert "DateTime" in rec, "Missing 'DateTime' field"
            assert "Prediction" in rec, "Missing 'Prediction' field"
            assert "Latitude" in rec, "Missing 'Latitude' field"
            assert "Longitude" in rec, "Missing 'Longitude' field"

    def test_datetime_parseable(self):
        """DateTime strings can be parsed as ISO format."""
        for rec in self.data["result"]["records"][:5]:
            dt = datetime.fromisoformat(rec["DateTime"])
            assert dt.year >= 2020

    def test_prediction_values_numeric(self):
        for rec in self.data["result"]["records"][:5]:
            float(rec["Prediction"])  # should not raise

    def test_ten_minute_intervals(self):
        """QLD data comes in 10-minute intervals."""
        records = self.data["result"]["records"]
        if len(records) >= 2:
            dt1 = datetime.fromisoformat(records[0]["DateTime"])
            dt2 = datetime.fromisoformat(records[1]["DateTime"])
            diff = (dt2 - dt1).total_seconds()
            assert diff == 600, f"Expected 10-min interval, got {diff}s"


# ---------------------------------------------------------------------------
# QLD station list (fixture parsing)
# ---------------------------------------------------------------------------

class TestQLDStationList:
    """Verify we can parse and deduplicate the station list."""

    def setup_method(self):
        self.data = _load("qld_station_list.json")

    def test_has_records(self):
        records = self.data["result"]["records"]
        assert len(records) > 0

    def test_station_fields(self):
        rec = self.data["result"]["records"][0]
        assert "Site" in rec
        assert "Latitude" in rec
        assert "Longitude" in rec

    def test_deduplication_logic(self):
        """Our deduplication should produce unique station names."""
        records = self.data["result"]["records"]
        seen = set()
        unique = []
        for rec in records:
            name = rec.get("Site", "")
            if name and name not in seen:
                seen.add(name)
                unique.append(rec)
        # Fixture has 12 unique stations (each appearing twice)
        assert len(unique) == 12
        assert "Cairns" in seen
        assert "Gold Coast" in seen
        assert "Townsville" in seen


# ---------------------------------------------------------------------------
# Station discovery (unit tests with mocks)
# ---------------------------------------------------------------------------

class TestStationDiscovery(unittest.TestCase):
    def test_find_nearest_station_returns_closest(self):
        """Cairns should be found when searching near its coordinates."""
        stations = [
            {"name": "Cairns", "lat": -16.9186, "lng": 145.7781},
            {"name": "Townsville", "lat": -19.2553, "lng": 146.8283},
            {"name": "Gold Coast", "lat": -27.9422, "lng": 153.4286},
        ]
        with patch.object(qld, "read_cache", return_value=None), \
             patch.object(qld, "_fetch_all_stations_qld", return_value=stations), \
             patch.object(qld, "write_cache"):
            station_id, station_name = qld.find_nearest_station_qld(-16.92, 145.78)

        self.assertEqual(station_id, "Cairns")
        self.assertEqual(station_name, "Cairns")

    def test_find_nearest_station_returns_none_when_too_far(self):
        """Stations beyond 100nm should return (None, None)."""
        stations = [
            {"name": "Cairns", "lat": -16.9186, "lng": 145.7781},
        ]
        # Sydney is far from Cairns
        with patch.object(qld, "read_cache", return_value=None), \
             patch.object(qld, "_fetch_all_stations_qld", return_value=stations), \
             patch.object(qld, "write_cache"):
            station_id, station_name = qld.find_nearest_station_qld(-33.87, 151.21)

        self.assertIsNone(station_id)
        self.assertIsNone(station_name)

    def test_find_nearest_uses_cache(self):
        """Cached result should be returned without fetching."""
        cached = {"id": "Cairns", "name": "Cairns"}
        with patch.object(qld, "read_cache", return_value=cached):
            station_id, station_name = qld.find_nearest_station_qld(-16.92, 145.78)

        self.assertEqual(station_id, "Cairns")
        self.assertEqual(station_name, "Cairns")

    def test_find_nearest_uses_stale_on_error(self):
        """Stale cache should be used when the API fails."""
        stale = {"id": "Cairns", "name": "Cairns"}
        with patch.object(qld, "read_cache", return_value=None), \
             patch.object(qld, "_fetch_all_stations_qld", side_effect=RuntimeError("boom")), \
             patch.object(qld, "read_stale", return_value=stale):
            station_id, station_name = qld.find_nearest_station_qld(-16.92, 145.78)

        self.assertEqual(station_id, "Cairns")
        self.assertEqual(station_name, "Cairns")


# ---------------------------------------------------------------------------
# Station metadata
# ---------------------------------------------------------------------------

class TestStationMetadata(unittest.TestCase):
    def test_metadata_shape(self):
        """Metadata should match the normalized shape expected by tides.py."""
        with patch.object(qld, "read_cache", return_value=None), \
             patch.object(qld, "_fetch_all_stations_qld", return_value=[
                 {"name": "Cairns", "lat": -16.9186, "lng": 145.7781},
             ]), \
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
        self.assertAlmostEqual(meta["lat"], -16.9186)
        self.assertAlmostEqual(meta["lng"], 145.7781)


# ---------------------------------------------------------------------------
# Datetime parsing
# ---------------------------------------------------------------------------

class TestDatetimeParsing(unittest.TestCase):
    def test_parse_qld_dt_basic(self):
        dt = qld._parse_qld_dt("2026-03-27T10:00:00")
        self.assertEqual(dt.year, 2026)
        self.assertEqual(dt.month, 3)
        self.assertEqual(dt.day, 27)
        self.assertEqual(dt.hour, 10)
        self.assertEqual(dt.minute, 0)
        self.assertIsNotNone(dt.tzinfo)
        # Should be AEST (UTC+10)
        self.assertEqual(dt.utcoffset(), timedelta(hours=10))

    def test_parse_qld_dt_with_fractional(self):
        dt = qld._parse_qld_dt("2026-03-27T10:00:00.123")
        self.assertEqual(dt.hour, 10)

    def test_parse_qld_dt_with_z_suffix(self):
        dt = qld._parse_qld_dt("2026-03-27T10:00:00Z")
        self.assertEqual(dt.hour, 10)


# ---------------------------------------------------------------------------
# High/low labeling
# ---------------------------------------------------------------------------

class TestHiLoLabeling(unittest.TestCase):
    def test_label_hilo_basic(self):
        """Alternating peaks and troughs should be labeled correctly."""
        AEST = timezone(timedelta(hours=10))
        values = [
            (datetime(2026, 3, 27, 2, 0, tzinfo=AEST), 0.5),
            (datetime(2026, 3, 27, 8, 0, tzinfo=AEST), 2.5),
            (datetime(2026, 3, 27, 14, 0, tzinfo=AEST), 0.3),
            (datetime(2026, 3, 27, 20, 0, tzinfo=AEST), 2.8),
        ]
        labeled = qld._label_hilo(values)
        self.assertEqual(len(labeled), 4)
        # First value (0.5) < next (2.5) -> L
        self.assertEqual(labeled[0][2], "L")
        # Second value (2.5) > both neighbors -> H
        self.assertEqual(labeled[1][2], "H")
        # Third value (0.3) < both neighbors -> L
        self.assertEqual(labeled[2][2], "L")
        # Last value (2.8) > prev (0.3) -> H
        self.assertEqual(labeled[3][2], "H")

    def test_label_hilo_single(self):
        AEST = timezone(timedelta(hours=10))
        values = [(datetime(2026, 3, 27, 8, 0, tzinfo=AEST), 2.5)]
        labeled = qld._label_hilo(values)
        self.assertEqual(len(labeled), 1)
        self.assertEqual(labeled[0][2], "H")

    def test_label_hilo_empty(self):
        self.assertEqual(qld._label_hilo([]), [])


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
