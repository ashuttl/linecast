"""The ephemeris, checked against published times and positions."""

import math
from datetime import datetime


class TestEphemerisAccuracy:
    """The Moon, checked against published times and positions.

    Reference values are the ones the almanacs print, to the minute. The
    tolerances say what this low-precision ephemeris is for: naming the
    right phase on the right evening, not navigating by it.
    """

    # Principal phases of early 2026, UTC.
    PHASES = [
        (0.0, "2026-01-18 19:51"), (0.0, "2026-02-17 12:01"),
        (0.0, "2026-03-19 01:23"), (0.0, "2026-04-17 11:51"),
        (0.5, "2026-01-03 10:02"), (0.5, "2026-02-01 22:09"),
        (0.5, "2026-03-03 11:37"), (0.5, "2026-04-02 02:11"),
    ]

    def test_principal_phases_land_within_a_quarter_hour(self):
        from datetime import timedelta, timezone
        from linecast.astro.ephemeris import next_moon_phase_utc

        for target, stamp in self.PHASES:
            want = datetime.strptime(stamp, "%Y-%m-%d %H:%M").replace(
                tzinfo=timezone.utc)
            got = next_moon_phase_utc(want - timedelta(days=5), target)
            assert got is not None, stamp
            off = abs((got - want).total_seconds()) / 60.0
            assert off < 15.0, f"{stamp}: off by {off:.0f} min"

    def test_disc_is_full_when_the_almanac_says_full(self):
        from datetime import timezone
        from linecast.astro.ephemeris import moon_illuminated_fraction

        full = datetime(2026, 3, 3, 11, 37, tzinfo=timezone.utc)
        new = datetime(2026, 3, 19, 1, 23, tzinfo=timezone.utc)
        assert moon_illuminated_fraction(full) > 0.999
        assert moon_illuminated_fraction(new) < 0.001

    def test_moon_position_within_a_tenth_of_a_degree(self):
        """Geocentric RA/dec against pyephem, which uses ELP2000."""
        from datetime import timezone
        from linecast.astro.ephemeris import moon_ra_dec

        # (UTC, RA deg, dec deg)
        known = [
            ("2026-01-15 00:00", 249.8438, -27.3160),
            ("2026-03-05 19:30", 190.8829, -7.9009),
            ("2026-06-21 12:00", 174.8110, 0.0488),
            ("2026-11-08 06:00", 209.9764, -17.1436),
        ]
        for stamp, ra, dec in known:
            when = datetime.strptime(stamp, "%Y-%m-%d %H:%M").replace(
                tzinfo=timezone.utc)
            got_ra, got_dec = moon_ra_dec(when)
            d_ra = abs((got_ra - ra + 540.0) % 360.0 - 180.0) * math.cos(
                math.radians(dec))
            assert math.hypot(d_ra, got_dec - dec) < 0.1, stamp

    def test_bright_limb_points_at_the_sun(self):
        """The lit edge must face the Sun, wherever both happen to be."""
        from datetime import timezone
        from linecast.astro.ephemeris import (
            _moon_altitude_deg, moon_parallactic_deg, moon_bright_limb_deg,
        )

        # Bearing from Moon to Sun in the alt/az frame, 0 = up, +90 = right,
        # taken from pyephem at four moments over a year at four sites.
        cases = [
            ("2026-01-24 18:00", 51.5, -0.1, 131.3),
            ("2026-04-22 06:00", -33.9, 151.2, -84.3),
            ("2026-08-02 21:00", 1.3, 36.8, -154.7),
            ("2026-10-30 00:00", 64.1, -21.9, -116.2),
        ]
        for stamp, lat, lng, want in cases:
            when = datetime.strptime(stamp, "%Y-%m-%d %H:%M").replace(
                tzinfo=timezone.utc)
            assert _moon_altitude_deg(when, lat, lng) > 0, stamp
            drawn = (moon_parallactic_deg(when, lat, lng)
                     - moon_bright_limb_deg(when))
            off = abs((drawn - want + 540.0) % 360.0 - 180.0)
            assert off < 3.0, f"{stamp}: off by {off:.1f} deg"


class TestSunriseSunset:
    """The app's one sunrise, astro.ephemeris.sunrise_sunset."""

    def test_an_ordinary_day_has_a_sunrise_and_a_sunset_on_the_places_clock(self):
        from datetime import date, timedelta
        from zoneinfo import ZoneInfo
        from linecast.astro.ephemeris import sunrise_sunset
        rise, set_ = sunrise_sunset(date(2026, 10, 1), 43.66, -70.25,
                                    ZoneInfo("America/New_York"))
        # Portland, 1 October: up about 6:38 and down about 6:22
        assert (rise.hour, set_.hour) == (6, 18)
        assert rise.tzinfo is not None and rise.utcoffset() == timedelta(hours=-4)

    def test_the_polar_night_has_no_daylight(self):
        from datetime import date
        from zoneinfo import ZoneInfo
        from linecast.astro.ephemeris import sunrise_sunset
        tromso = ZoneInfo("Europe/Oslo")
        assert sunrise_sunset(date(2026, 12, 21), 69.65, 18.96, tromso) == (None, None)

    def test_the_midnight_sun_is_up_from_midnight_to_midnight(self):
        from datetime import date, timedelta
        from zoneinfo import ZoneInfo
        from linecast.astro.ephemeris import sunrise_sunset
        tromso = ZoneInfo("Europe/Oslo")
        # Midsummer, and the two days at the season's edges on which
        # the Sun only rises (18 May) or only sets (25 July)
        for day in (date(2026, 6, 21), date(2026, 5, 18), date(2026, 7, 25)):
            rise, set_ = sunrise_sunset(day, 69.65, 18.96, tromso)
            assert set_ - rise == timedelta(days=1), day
            assert (rise.date(), rise.hour, rise.minute) == (day, 0, 0), day

    def test_crossings_leave_out_the_midnight_suns_whole_day(self):
        from datetime import date
        from zoneinfo import ZoneInfo
        from linecast.astro.ephemeris import sun_crossings, sunrise_sunset
        tromso = ZoneInfo("Europe/Oslo")
        for day in (date(2026, 6, 21), date(2026, 12, 21)):
            assert sun_crossings(day, 69.65, 18.96, tromso) == (None, None), day
        # an ordinary day, and a sunset after midnight, are crossings
        portland = ZoneInfo("America/New_York")
        assert (sun_crossings(date(2026, 10, 1), 43.66, -70.25, portland)
                == sunrise_sunset(date(2026, 10, 1), 43.66, -70.25, portland))
        reykjavik = ZoneInfo("Atlantic/Reykjavik")
        rise, set_ = sun_crossings(date(2026, 6, 21), 64.15, -21.94, reykjavik)
        assert (rise.hour, set_.date(), set_.hour) == (2, date(2026, 6, 22), 0)

    def test_without_a_zone_the_times_are_the_machines(self):
        from datetime import date
        from linecast.astro.ephemeris import sun_depression_utc, sunrise_sunset
        rise, set_ = sunrise_sunset(date(2026, 10, 1), 43.66, -70.25)
        assert rise.utcoffset() == rise.astimezone().utcoffset()
        assert rise == sun_depression_utc(date(2026, 10, 1), 43.66, -70.25, 0.833, False)

    # PyEphem 4.2.1, the Sun's centre 50′ below a sea-level horizon and
    # no refraction of its own, worked out once and written down here.
    # Reykjavik sets after midnight at midsummer; Longyearbyen's is one
    # of the last days the Sun rises before the polar night.
    PYEPHEM = [
        (43.70, -79.40, "America/Toronto", "2026-03-05 06:47:14", "2026-03-05 18:11:26"),
        (-42.88, 147.33, "Australia/Hobart", "2026-10-23 06:07:47", "2026-10-23 19:43:08"),
        (64.15, -21.94, "Atlantic/Reykjavik", "2026-06-21 02:55:06", "2026-06-22 00:04:02"),
        (78.22, 15.65, "Arctic/Longyearbyen", "2026-10-23 10:58:15", "2026-10-23 14:22:56"),
        (1.87, -157.40, "Pacific/Kiritimati", "2026-09-06 06:24:01", "2026-09-06 18:32:15"),
    ]

    def test_within_a_quarter_minute_of_pyephem(self):
        from zoneinfo import ZoneInfo
        from linecast.astro.ephemeris import sunrise_sunset
        for lat, lng, zone, rise_at, set_at in self.PYEPHEM:
            tz = ZoneInfo(zone)
            want = [datetime.strptime(t, "%Y-%m-%d %H:%M:%S").replace(tzinfo=tz)
                    for t in (rise_at, set_at)]
            got = sunrise_sunset(want[0].date(), lat, lng, tz)
            for g, w in zip(got, want):
                assert abs((g - w).total_seconds()) < 15, (zone, g, w)
