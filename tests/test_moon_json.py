"""Tests for the `moon --json` machine-readable payload."""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# Ensure the worktree src is preferred over any installed version.
# (No sys.modules purge here: this file is collected after other test
# modules that hold references into already-imported linecast modules.)
_src = str(Path(__file__).resolve().parent.parent / "src")
if _src not in sys.path:
    sys.path.insert(0, _src)

from linecast._moon_json import build_payload
from linecast._runtime import RuntimeConfig, moon_parser
from linecast.moon import moon_illumination, upcoming_moon_events
from linecast.sunshine import (
    _EMOJI_ICONS,
    _NERD_ICONS,
    SYNODIC_MONTH,
    moon_cycle_frac,
)

LAT, LNG = 43.68, -70.35  # Portland, Maine-ish
FIXED_NOW = datetime(2026, 8, 14, 12, 0, tzinfo=timezone.utc)

EXPECTED_TOP_KEYS = {
    "schema", "location", "timezone", "fetched_at", "phase", "icon",
    "illumination", "waxing", "age_days", "events", "next_full",
    "next_full_name", "next_new", "day_of_year", "days_in_year",
    "next_season_event", "southern", "altitude_deg", "azimuth_deg",
    "up_now",
}


def _runtime(**overrides):
    defaults = dict(live=False, icons="nerd", lang="en", oneline=False)
    defaults.update(overrides)
    return RuntimeConfig(**defaults)


def _payload(**kwargs):
    defaults = dict(
        now_local=FIXED_NOW, lat=LAT, lng=LNG, runtime=_runtime(),
        location="Testville",
    )
    defaults.update(kwargs)
    return build_payload(**defaults)


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
        assert p["location"] == "Testville"
        assert p["fetched_at"] == "2026-08-14T12:00"


class TestPhase:
    def test_phase_matches_module(self):
        frac = moon_cycle_frac(FIXED_NOW)
        p = _payload()
        assert p["waxing"] == (frac < 0.5)
        assert p["illumination"] == round(moon_illumination(FIXED_NOW) * 100, 1)
        assert 0 <= p["illumination"] <= 100
        # Age is time since the last new moon, not the phase angle scaled
        # by a mean month, so the two agree only to within the Moon's own
        # unevenness — most of a day at the extremes.
        assert abs(p["age_days"] - frac * SYNODIC_MONTH) < 1.0

    def test_age_is_measured_from_the_last_new_moon(self):
        from linecast._ephemeris import next_moon_phase_utc

        last_new = next_moon_phase_utc(FIXED_NOW, 0.0, backwards=True)
        elapsed = (FIXED_NOW - last_new).total_seconds() / 86400.0
        assert _payload()["age_days"] == round(elapsed, 1)

    def test_phase_name_localized(self):
        en = _payload()["phase"]
        fr = _payload(runtime=_runtime(lang="fr"))["phase"]
        assert isinstance(en, str) and en
        assert fr != en  # French names differ from English

    def test_nerd_icon_by_default_emoji_on_request(self):
        assert _payload()["icon"] in _NERD_ICONS["moon_icons"]
        p = _payload(runtime=_runtime(icons="emoji"))
        assert p["icon"] in _EMOJI_ICONS["moon_icons"]


class TestEvents:
    def test_events_chronological(self):
        events = _payload()["events"]
        times = [e["time"] for e in events]
        assert times == sorted(times)
        assert all(e["kind"] in ("rise", "set") for e in events)

    def test_events_match_module_and_are_future(self):
        rise, sset = upcoming_moon_events(FIXED_NOW, LAT, LNG)
        expected = sorted(
            dt.strftime("%Y-%m-%dT%H:%M")
            for dt in (rise, sset) if dt is not None
        )
        events = _payload()["events"]
        assert [e["time"] for e in events] == expected
        for e in events:
            assert datetime.fromisoformat(e["time"]) > FIXED_NOW.replace(tzinfo=None)

    def test_typically_one_rise_and_one_set(self):
        kinds = sorted(e["kind"] for e in _payload()["events"])
        assert kinds == ["rise", "set"]


class TestAlmanac:
    def test_next_full_and_new_are_dates_within_a_cycle(self):
        p = _payload()
        for key in ("next_full", "next_new"):
            d = datetime.strptime(p[key], "%Y-%m-%d").date()
            ahead = (d - FIXED_NOW.date()).days
            assert 0 <= ahead <= 31

    def test_full_and_new_ordering_matches_phase(self):
        p = _payload()
        frac = moon_cycle_frac(FIXED_NOW)
        if frac < 0.5:  # waxing: full comes before new
            assert p["next_full"] <= p["next_new"]
        else:
            assert p["next_new"] <= p["next_full"]


class TestHemisphereAndAltitude:
    def test_northern_observer(self):
        assert _payload()["southern"] is False

    def test_southern_observer(self):
        assert _payload(lat=-33.9, lng=151.2)["southern"] is True

    def test_altitude_is_a_number(self):
        p = _payload()
        assert isinstance(p["altitude_deg"], float)
        assert -90 <= p["altitude_deg"] <= 90
        assert isinstance(p["up_now"], bool)

    def test_azimuth_is_a_bearing(self):
        p = _payload()
        assert isinstance(p["azimuth_deg"], float)
        assert 0 <= p["azimuth_deg"] < 360

    def test_azimuth_swings_east_to_west_while_up(self):
        """The Moon crosses the sky one way: rising east, setting west.

        Sampled across a night it should climb to a maximum altitude near
        due south (northern hemisphere) with the bearing increasing
        through it, which is the property a compass hint depends on.
        """
        from linecast._ephemeris import _moon_altitude_deg, _moon_azimuth_deg

        samples = []
        for hour in range(24):
            t = FIXED_NOW.replace(hour=hour)
            alt = _moon_altitude_deg(t, LAT, LNG)
            if alt > 5.0:
                samples.append((hour, _moon_azimuth_deg(t, LAT, LNG)))
        assert len(samples) >= 3, "expected the Moon up for part of the day"
        bearings = [az for _h, az in samples]
        assert bearings == sorted(bearings), bearings
        # Well above the horizon it is south of the observer, never north.
        assert all(45 < az < 315 for az in bearings), bearings


class TestLiveSuppression:
    def test_json_flag_forces_live_off(self):
        args = moon_parser().parse_args(["--json", "--live"])
        runtime = RuntimeConfig.from_sources(namespace=args)
        assert runtime.json_mode is True
        assert runtime.live is False

    def test_json_mode_defaults_false(self):
        args = moon_parser().parse_args(["--print"])
        runtime = RuntimeConfig.from_sources(namespace=args)
        assert runtime.json_mode is False
