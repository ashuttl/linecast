"""Tests for the `tides --json` machine-readable payload."""

import json
import math
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Ensure the worktree src is preferred over any installed version.
# (No sys.modules purge here: this file is collected after other test
# modules that hold references into already-imported linecast modules.)
_src = str(Path(__file__).resolve().parent.parent / "src")
if _src not in sys.path:
    sys.path.insert(0, _src)

from linecast._runtime import TidesRuntime, tides_parser
from linecast._tides_json import build_payload
from linecast._tides_render import interp_height

FIXED_NOW = datetime(2026, 8, 14, 12, 0)

EXPECTED_TOP_KEYS = {
    "schema", "location", "timezone", "fetched_at", "station", "units",
    "events", "series", "now_height", "station_id", "source",
}

# Semidiurnal-ish synthetic tide: period ~12.4h, range 0..9 ft, high at now-3h.
_PERIOD_H = 12.4


def _height_ft(dt):
    hours = (dt - FIXED_NOW).total_seconds() / 3600
    return 4.5 + 4.5 * math.cos(2 * math.pi * (hours + 3) / _PERIOD_H)


def _predictions(start_h=-12, end_h=30, step_min=6):
    out = []
    t = FIXED_NOW + timedelta(hours=start_h)
    end = FIXED_NOW + timedelta(hours=end_h)
    while t <= end:
        out.append((t, round(_height_ft(t), 3)))
        t += timedelta(minutes=step_min)
    return out


def _hilo():
    """Alternating extremes: one past high, then seven future events."""
    events = []
    t = FIXED_NOW - timedelta(hours=3)  # a high crest
    kind = "H"
    for _ in range(8):
        events.append((t, round(_height_ft(t), 3), kind))
        t += timedelta(hours=_PERIOD_H / 2)
        kind = "L" if kind == "H" else "H"
    return events


def _runtime(**overrides):
    defaults = dict(live=False, icons="nerd", lang="en", oneline=False,
                    metric=False)
    defaults.update(overrides)
    return TidesRuntime(**defaults)


def _payload(**kwargs):
    defaults = dict(
        station_name="Portland, ME",
        runtime=_runtime(),
        now_local=FIXED_NOW,
        predictions=_predictions(),
        hilo=_hilo(),
        station_id="8418150",
        source="noaa",
        tz_name="America/New_York",
    )
    defaults.update(kwargs)
    return build_payload(**defaults)


def _dt(iso):
    return datetime.fromisoformat(iso)


class TestPayloadShape:
    def test_top_level_keys_exact(self):
        assert set(_payload().keys()) == EXPECTED_TOP_KEYS

    def test_round_trips_through_json(self):
        payload = _payload()
        text = json.dumps(payload, ensure_ascii=False)
        assert json.loads(text) == payload

    def test_schema_and_identity(self):
        p = _payload()
        assert p["schema"] == 1
        assert p["location"] == "Portland, ME"
        assert p["station"] == "Portland, ME"
        assert p["station_id"] == "8418150"
        assert p["source"] == "noaa"
        assert p["timezone"] == "America/New_York"
        assert p["fetched_at"] == "2026-08-14T12:00"

    def test_units_feet_default_meters_metric(self):
        assert _payload()["units"] == {"height": "ft"}
        assert _payload(runtime=_runtime(metric=True))["units"] == {"height": "m"}


class TestEvents:
    def test_events_upcoming_chronological_capped_at_six(self):
        events = _payload()["events"]
        assert len(events) == 6  # seven future extremes, capped
        times = [e["time"] for e in events]
        assert times == sorted(times)
        for e in events:
            assert _dt(e["time"]) >= FIXED_NOW

    def test_past_events_excluded(self):
        events = _payload()["events"]
        assert "2026-08-14T09:00" not in [e["time"] for e in events]

    def test_kinds_alternate_high_low(self):
        kinds = [e["kind"] for e in _payload()["events"]]
        assert set(kinds) <= {"high", "low"}
        for a, b in zip(kinds, kinds[1:]):
            assert a != b

    def test_heights_converted_to_meters(self):
        ft = _payload()["events"][0]["height"]
        m = _payload(runtime=_runtime(metric=True))["events"][0]["height"]
        assert abs(m - ft * 0.3048) < 0.02


class TestSeries:
    def test_series_spans_past_six_to_future_24_hours(self):
        series = _payload()["series"]
        assert series
        assert _dt(series[0]["time"]) >= FIXED_NOW - timedelta(hours=6)
        assert _dt(series[-1]["time"]) <= FIXED_NOW + timedelta(hours=24)
        # Both edges of the window are actually reached (data covers it).
        assert _dt(series[0]["time"]) == FIXED_NOW - timedelta(hours=6)
        assert _dt(series[-1]["time"]) == FIXED_NOW + timedelta(hours=24)

    def test_series_step_at_most_60_minutes(self):
        series = _payload()["series"]
        for a, b in zip(series, series[1:]):
            gap = (_dt(b["time"]) - _dt(a["time"])).total_seconds()
            assert 0 < gap <= 3600

    def test_series_heights_match_interpolation(self):
        preds = _predictions()
        for point in _payload()["series"][::7]:
            expected = interp_height(_dt(point["time"]), preds)
            assert abs(point["height"] - expected) < 0.01

    def test_series_clipped_to_available_data(self):
        # Predictions ending at +2h: no series points invented beyond them.
        preds = _predictions(start_h=-12, end_h=2)
        series = _payload(predictions=preds)["series"]
        assert series
        assert _dt(series[-1]["time"]) <= FIXED_NOW + timedelta(hours=2)

    def test_now_height_matches_interpolation(self):
        p = _payload()
        assert abs(p["now_height"] - interp_height(FIXED_NOW, _predictions())) < 0.01


class TestNoStation:
    def test_empty_inputs_yield_nulls_not_errors(self):
        p = build_payload(None, _runtime(), FIXED_NOW, None, None)
        assert p["station"] is None
        assert p["station_id"] is None
        assert p["source"] is None
        assert p["timezone"] is None
        assert p["events"] == []
        assert p["series"] == []
        assert p["now_height"] is None
        assert set(p.keys()) == EXPECTED_TOP_KEYS
        assert json.loads(json.dumps(p, ensure_ascii=False)) == p

    def test_location_fallback_when_no_station(self):
        p = build_payload(None, _runtime(), FIXED_NOW, [], [],
                          location="Westbrook, Maine")
        assert p["location"] == "Westbrook, Maine"
        assert p["station"] is None


class TestLiveSuppression:
    def test_json_flag_forces_live_off(self):
        args = tides_parser().parse_args(["--json", "--live"])
        runtime = TidesRuntime.from_sources(namespace=args)
        assert runtime.json_mode is True
        assert runtime.live is False

    def test_json_mode_defaults_false(self):
        args = tides_parser().parse_args(["--print"])
        runtime = TidesRuntime.from_sources(namespace=args)
        assert runtime.json_mode is False
