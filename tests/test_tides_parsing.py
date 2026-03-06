"""Tests for tides API response parsing.

These use real API responses saved as fixtures. If NOAA changes their
response format, these tests will catch the breakage.
"""

import json
import sys
from datetime import datetime
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


def _load(name):
    return json.loads((FIXTURES / name).read_text())


# ---------------------------------------------------------------------------
# NOAA tide predictions
# ---------------------------------------------------------------------------

class TestNOAATidePredictions:
    """Verify we can parse a real NOAA tide predictions response."""

    def setup_method(self):
        self.data = _load("noaa_tide_predictions.json")

    def test_has_predictions(self):
        assert "predictions" in self.data
        assert len(self.data["predictions"]) > 0

    def test_prediction_shape(self):
        """Each prediction has a timestamp and value."""
        for p in self.data["predictions"][:5]:
            assert "t" in p, "Missing 't' (timestamp) field"
            assert "v" in p, "Missing 'v' (value) field"

    def test_timestamp_parseable(self):
        """Timestamps match the format our parser expects: 'YYYY-MM-DD HH:MM'."""
        for p in self.data["predictions"][:5]:
            parts = p["t"].split(" ")
            assert len(parts) == 2, f"Unexpected timestamp format: {p['t']}"
            time_parts = parts[1].split(":")
            assert len(time_parts) == 2, f"Unexpected time format: {parts[1]}"
            hour = int(time_parts[0])
            minute = int(time_parts[1])
            assert 0 <= hour <= 23
            assert 0 <= minute <= 59

    def test_values_are_numeric(self):
        for p in self.data["predictions"][:5]:
            float(p["v"])  # should not raise

    def test_full_day_coverage(self):
        """A day's predictions should have ~240 entries (every 6 min)."""
        assert len(self.data["predictions"]) >= 200

    def test_inline_parsing_logic(self):
        """Test the exact parsing logic from tides.fetch_tides."""
        results = []
        for p in self.data["predictions"]:
            t_str = p.get("t", "")
            v = float(p.get("v", 0))
            parts = t_str.split(" ")
            time_parts = parts[1].split(":")
            hour = int(time_parts[0]) + int(time_parts[1]) / 60
            results.append((hour, v))

        assert len(results) > 200
        # Hours should span 0-24
        assert results[0][0] < 1.0
        assert results[-1][0] > 23.0


# ---------------------------------------------------------------------------
# NOAA hi/lo predictions
# ---------------------------------------------------------------------------

class TestNOAATideHiLo:
    """Verify we can parse a real NOAA hi/lo response."""

    def setup_method(self):
        self.data = _load("noaa_tide_hilo.json")

    def test_has_predictions(self):
        assert "predictions" in self.data
        assert len(self.data["predictions"]) > 0

    def test_hilo_shape(self):
        for p in self.data["predictions"]:
            assert "t" in p
            assert "v" in p
            assert "type" in p
            assert p["type"] in ("H", "L"), f"Unexpected type: {p['type']}"

    def test_reasonable_count(self):
        """A day typically has 2 highs and 2 lows (semi-diurnal)."""
        count = len(self.data["predictions"])
        assert 2 <= count <= 6, f"Unexpected hi/lo count: {count}"


# ---------------------------------------------------------------------------
# NOAA station metadata
# ---------------------------------------------------------------------------

class TestNOAAStationMetadata:
    """Verify we can parse a real NOAA station metadata response."""

    def setup_method(self):
        self.data = _load("noaa_station_metadata.json")

    def test_has_stations(self):
        assert "stations" in self.data
        assert len(self.data["stations"]) > 0

    def test_station_fields(self):
        """The first station has the fields our parser extracts."""
        s = self.data["stations"][0]
        assert "id" in s
        assert "name" in s
        assert "timezone" in s

    def test_metadata_extraction_logic(self):
        """Test the exact extraction logic from _fetch_station_metadata."""
        s = self.data["stations"][0]
        details = s.get("details", {})
        meta = {
            "id": str(s.get("id", "")),
            "name": s.get("name", ""),
            "state": s.get("state", ""),
            "timezone_abbr": str(s.get("timezone", "")).upper(),
            "timezonecorr": s.get("timezonecorr", details.get("timezone")),
            "observedst": bool(s.get("observedst", False)),
        }
        assert meta["id"], "Station ID should not be empty"
        assert meta["name"], "Station name should not be empty"
        assert meta["timezone_abbr"], "Timezone should not be empty"
