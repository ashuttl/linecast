"""Tests for the `sunshine --json` machine-readable payload."""

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Ensure the worktree src is preferred over any installed version.
# (No sys.modules purge here: this file is collected after other test
# modules that hold references into already-imported linecast modules.)
_src = str(Path(__file__).resolve().parent.parent / "src")
if _src not in sys.path:
    sys.path.insert(0, _src)

from linecast._runtime import RuntimeConfig, sunshine_parser
from linecast._sunshine_json import build_payload
from linecast.sunshine import polar_state
from linecast.sunshine import _tz_offset_hours, solar_times


class TestTzOffsetThreading:
    def test_explicit_offset_shifts_local_times_by_offset_delta(self):
        r1, s1 = solar_times(43.68, -70.35, 200, tz_offset_h=-4)
        r2, s2 = solar_times(43.68, -70.35, 200, tz_offset_h=-5)
        assert abs((r1 - r2) - 1.0) < 1e-9
        assert abs((s1 - s2) - 1.0) < 1e-9

    def test_aware_now_pins_payload_to_its_zone(self):
        from zoneinfo import ZoneInfo
        now = datetime(2026, 8, 20, 12, 0, tzinfo=ZoneInfo("Europe/Lisbon"))
        payload = build_payload(38.72, -9.14, now=now, location="Lisbon")
        assert payload["timezone"] == "Europe/Lisbon"
        # Lisbon sunrise in late August is ~06:50 local (WEST). With the
        # machine-timezone bug this would be hours off on a US machine.
        rise_hour = int(payload["sunrise"].split("T")[1].split(":")[0])
        assert rise_hour in (6, 7)

# Solar math resolves local clock time through the machine's UTC offset, so
# pin a longitude whose mean solar noon lands at 12:00 on any machine.
LAT = 45.0
LNG = _tz_offset_hours() * 15

FIXED_NOW = datetime(2026, 8, 14, 12, 0)

EXPECTED_TOP_KEYS = {
    "schema", "location", "timezone", "fetched_at", "sunrise", "sunset",
    "tomorrow_sunrise", "tomorrow_sunset", "solar_noon",
    "day_length_seconds", "day_length_delta_seconds", "next_event",
    "elevation_deg", "polar",
}


def _payload(**kwargs):
    defaults = dict(lat=LAT, lng=LNG, now=FIXED_NOW, location="Testville")
    defaults.update(kwargs)
    return build_payload(**defaults)


def _dt(iso):
    return datetime.fromisoformat(iso)


def _polar_on(lat, doy):
    rise_h, set_h = solar_times(lat, LNG, doy)
    return polar_state(set_h - rise_h)


def _boundary_doy(lat, today_state, tomorrow_state):
    """First day of 2026 whose polar state flips to *tomorrow_state*.

    Searched rather than hardcoded: the exact date drifts with latitude
    and the solar model, but the transition always exists above the
    Arctic Circle.
    """
    for doy in range(2, 364):
        if (_polar_on(lat, doy) == today_state
                and _polar_on(lat, doy + 1) == tomorrow_state):
            return doy
    raise AssertionError(f"no {today_state}->{tomorrow_state} day at {lat}")


def _date_for_doy(doy, year=2026):
    return datetime(year, 1, 1) + timedelta(days=doy - 1)


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

    def test_times_are_minute_precision_iso(self):
        p = _payload()
        for key in ("sunrise", "sunset", "tomorrow_sunrise",
                    "tomorrow_sunset", "solar_noon"):
            assert len(p[key]) == 16  # YYYY-MM-DDTHH:MM
            _dt(p[key])  # parseable


class TestSolarValues:
    def test_rise_noon_set_ordered(self):
        p = _payload()
        assert _dt(p["sunrise"]) < _dt(p["solar_noon"]) < _dt(p["sunset"])

    def test_day_length_matches_rise_set(self):
        p = _payload()
        span = (_dt(p["sunset"]) - _dt(p["sunrise"])).total_seconds()
        assert abs(span - p["day_length_seconds"]) <= 60  # minute rounding

    def test_matches_module_solar_times(self):
        rise_h, set_h = solar_times(LAT, LNG, FIXED_NOW.timetuple().tm_yday)
        p = _payload()
        assert abs(round(set_h - rise_h, 4) * 3600
                   - p["day_length_seconds"]) < 1

    def test_days_shrink_in_august(self):
        assert _payload()["day_length_delta_seconds"] < 0

    def test_days_grow_in_may(self):
        p = _payload(now=datetime(2026, 5, 10, 12, 0))
        assert p["day_length_delta_seconds"] > 0

    def test_elevation_positive_at_noon_negative_at_night(self):
        assert _payload()["elevation_deg"] > 0
        night = _payload(now=FIXED_NOW.replace(hour=1))
        assert night["elevation_deg"] < 0


class TestNextEvent:
    def test_before_sunrise_is_sunrise(self):
        p = _payload(now=FIXED_NOW.replace(hour=3))
        assert p["next_event"]["kind"] == "sunrise"
        assert p["next_event"]["time"] == p["sunrise"]

    def test_daytime_flips_to_sunset(self):
        p = _payload()  # noon
        assert p["next_event"]["kind"] == "sunset"
        assert p["next_event"]["time"] == p["sunset"]

    def test_after_sunset_flips_to_tomorrow_sunrise(self):
        p = _payload(now=FIXED_NOW.replace(hour=23))
        assert p["next_event"]["kind"] == "sunrise"
        assert p["next_event"]["time"] == p["tomorrow_sunrise"]
        assert _dt(p["next_event"]["time"]).date() == (
            FIXED_NOW + timedelta(days=1)).date()

    def test_next_event_always_in_future(self):
        for hour in (0, 6, 12, 18, 23):
            p = _payload(now=FIXED_NOW.replace(hour=hour))
            assert _dt(p["next_event"]["time"]) > FIXED_NOW.replace(hour=hour)


class TestPolar:
    def test_arctic_summer_is_polar_day(self):
        p = _payload(lat=89.5)
        assert p["polar"] == "day"
        assert p["sunrise"] is None and p["sunset"] is None
        assert p["tomorrow_sunrise"] is None and p["tomorrow_sunset"] is None
        assert p["next_event"] is None
        assert p["day_length_seconds"] == 86400

    def test_arctic_winter_is_polar_night(self):
        p = _payload(lat=89.5, now=datetime(2026, 12, 20, 12, 0))
        assert p["polar"] == "night"
        assert p["sunrise"] is None and p["sunset"] is None
        assert p["day_length_seconds"] == 0

    def test_midlatitude_polar_is_null(self):
        assert _payload()["polar"] is None

    def test_eve_of_polar_night_invents_no_sunrise(self):
        # solar_times() clamps on a polar day and returns rise == set ==
        # solar noon; reported raw, that reads as a crossing that never
        # happens. Tomorrow gets its own polar test, not today's.
        lat = 70.0
        day = _date_for_doy(_boundary_doy(lat, None, "night"))
        p = _payload(lat=lat, now=day.replace(hour=23))
        assert p["polar"] is None
        assert p["sunrise"] is not None and p["sunset"] is not None
        assert p["tomorrow_sunrise"] is None
        assert p["tomorrow_sunset"] is None
        assert p["next_event"] is None  # today's crossings are already past

    def test_last_polar_night_day_reports_tomorrow_sunrise(self):
        # The mirror case: the sun does rise tomorrow, so a null next
        # event would hide a real one.
        lat = 70.0
        day = _date_for_doy(_boundary_doy(lat, "night", None))
        p = _payload(lat=lat, now=day.replace(hour=12))
        assert p["polar"] == "night"
        assert p["sunrise"] is None and p["sunset"] is None
        assert p["tomorrow_sunrise"] is not None
        assert p["next_event"] == {"kind": "sunrise",
                                   "time": p["tomorrow_sunrise"]}


class TestFarEasternZones:
    """UTC+13 and +14, whose clocks run ahead of their own sun by more
    than twelve hours.

    Kiritimati keeps UTC+14 at 157°W. Its solar noon is a day and a half
    after midnight UTC, and the local hours it comes back in used to run
    past 24 — which dated every event in the payload to tomorrow, and
    made the next event a sunrise twenty-one hours off when it was a
    sunset nine hours off. The same point on Hawai'i's UTC-10 was always
    right, which is what named the cause.
    """

    KIRITIMATI = dict(lat=1.87, lng=-157.40)

    def _at(self, place, offset_h):
        zone = timezone(timedelta(hours=offset_h))
        now = datetime(2026, 9, 6, 9, 0, tzinfo=zone)
        return build_payload(now=now, location="Testville", **place)

    def test_the_day_events_carry_the_day_asked_for(self):
        p = self._at(self.KIRITIMATI, 14)
        for key in ("sunrise", "solar_noon", "sunset"):
            assert p[key].startswith("2026-09-06"), (key, p[key])
        assert p["tomorrow_sunrise"].startswith("2026-09-07")

    def test_the_next_event_at_nine_in_the_morning_is_the_sunset(self):
        p = self._at(self.KIRITIMATI, 14)
        assert p["next_event"] == {"kind": "sunset", "time": p["sunset"]}

    def test_the_clock_time_of_noon_ignores_which_side_of_the_line(self):
        # One point, put in the zone Kiritimati keeps and in the one
        # Hawai'i keeps on the same meridian: the two are a day apart on
        # the calendar and see the same sun at the same clock time.
        east = self._at(self.KIRITIMATI, 14)
        west = self._at(self.KIRITIMATI, -10)
        assert east["solar_noon"][11:] == west["solar_noon"][11:]

    def test_samoa_and_tonga_keep_their_own_date(self):
        for place, offset in ((dict(lat=-13.83, lng=-171.77), 13),
                              (dict(lat=-21.14, lng=-175.20), 13)):
            p = self._at(place, offset)
            assert p["sunrise"].startswith("2026-09-06"), p["sunrise"]
            assert p["sunset"].startswith("2026-09-06"), p["sunset"]


class TestLiveSuppression:
    def test_json_flag_forces_live_off(self):
        args = sunshine_parser().parse_args(["--json", "--live"])
        runtime = RuntimeConfig.from_sources(namespace=args)
        assert runtime.json_mode is True
        assert runtime.live is False

    def test_json_mode_defaults_false(self):
        args = sunshine_parser().parse_args(["--print"])
        runtime = RuntimeConfig.from_sources(namespace=args)
        assert runtime.json_mode is False
