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
        from linecast.astro.ephemeris import _moon_ra_dec

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
            got_ra, got_dec = _moon_ra_dec(when)
            d_ra = abs((got_ra - ra + 540.0) % 360.0 - 180.0) * math.cos(
                math.radians(dec))
            assert math.hypot(d_ra, got_dec - dec) < 0.1, stamp

    def test_bright_limb_points_at_the_sun(self):
        """The lit edge must face the Sun, wherever both happen to be."""
        from datetime import timezone
        from linecast.astro.ephemeris import (
            _moon_altitude_deg, _moon_parallactic_deg, moon_bright_limb_deg,
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
            drawn = (_moon_parallactic_deg(when, lat, lng)
                     - moon_bright_limb_deg(when))
            off = abs((drawn - want + 540.0) % 360.0 - 180.0)
            assert off < 3.0, f"{stamp}: off by {off:.1f} deg"
