"""Property sweeps over the solar and lunar ephemeris.

The pinned tests elsewhere — the published phase times in
test_render_snapshots, the almanac dates in test_moon_calendar — check
the days they name and no others. These check the ground between them:
the same handful of invariants over every day of a year, or every
lunation of two, on the theory that a regression which keeps the pinned
days right and breaks the rest is the one nothing else would catch.

Everything here is computed locally, so the whole file runs in about a
second. Where an invariant has a numeric bound, the bound is loose
enough to be a statement about the sky rather than about this
ephemeris's current answer.
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from linecast._ephemeris import (  # noqa: E402
    moon_illuminated_fraction,
    moon_phase_frac,
    next_moon_phase_utc,
)
from linecast.sunshine import polar_state, solar_times  # noqa: E402

UTC = timezone.utc

# Latitudes from the tropics to inside both polar circles, and a few
# real places whose zone sits well off its solar meridian: Iceland on
# UTC, western China on Beijing time, and the UTC+13 and +14 zones east
# of the date line, which are more than twelve hours from their own
# meridian and so the sharpest test of the local-day arithmetic.
LATITUDES = [-70, -60, -45, -30, -15, 0, 15, 30, 45, 60, 66, 70]
PLACES = [
    ("Reykjavik", 64.13, -21.90, 0),
    ("Kashgar", 39.47, 75.99, 8),
    ("Kiritimati", 1.87, -157.40, 14),
    ("Apia", -13.83, -171.77, 13),
    ("Nuku'alofa", -21.14, -175.20, 13),
    ("Honolulu", 21.31, -157.86, -10),
    ("Tromso", 69.65, 18.96, 2),
    ("Ushuaia", -54.80, -68.30, -3),
]


class TestSolarDay:
    """Sunrise, solar noon and sunset, over a year at every latitude."""

    def test_sunrise_precedes_noon_precedes_sunset(self):
        for lat in LATITUDES:
            for doy in range(1, 366):
                rise, set_ = solar_times(lat, 0.0, doy, 0.0)
                if polar_state(set_ - rise):
                    continue  # noon twice over; nothing to order
                assert rise < (rise + set_) / 2 < set_, (lat, doy)

    def test_solar_noon_falls_within_the_local_day(self):
        """Noon belongs to the date asked for, however skewed the zone.

        A rise or set may fall the other side of midnight — Reykjavik
        sets after midnight in late May, and callers spill that into the
        next date on purpose — but the noon between them cannot: it is
        what makes the date a day. The UTC+13 and +14 zones are where
        this last failed, their clocks running more than twelve hours
        ahead of their own sun.
        """
        for name, lat, lng, tz in PLACES:
            for doy in range(1, 366):
                rise, set_ = solar_times(lat, lng, doy, tz)
                noon = (rise + set_) / 2
                assert 0.0 <= noon < 24.0, (name, doy, noon)

    def test_rise_and_set_stay_within_half_a_day_of_noon(self):
        # Through a polar season the hour angle is clamped and the two
        # are noon exactly twelve hours apart, which says nothing.
        for name, lat, lng, tz in PLACES:
            for doy in range(1, 366):
                rise, set_ = solar_times(lat, lng, doy, tz)
                if polar_state(set_ - rise):
                    continue
                noon = (rise + set_) / 2
                assert -12.0 < rise - noon < 0.0, (name, doy)
                assert 0.0 < set_ - noon < 12.0, (name, doy)


class TestLunations:
    """Two years of principal phases, as the ephemeris itself finds them."""

    @staticmethod
    def _phases(target, count=26):
        t = datetime(2026, 1, 1, tzinfo=UTC)
        found = []
        for _ in range(count):
            t = next_moon_phase_utc(t + timedelta(hours=1), target)
            assert t is not None
            found.append(t)
        return found

    def test_the_disc_is_full_at_every_full_moon(self):
        # Not 99.9%: the Moon rides up to five degrees off the ecliptic,
        # and a full moon at the far edge of that leaves a sliver dark.
        # The lowest over two years is a shade under 99.9%.
        for full in self._phases(0.5):
            assert moon_illuminated_fraction(full) >= 0.99, full

    def test_the_disc_is_dark_at_every_new_moon(self):
        for new in self._phases(0.0):
            assert moon_illuminated_fraction(new) <= 0.01, new

    def test_consecutive_phases_are_a_synodic_month_apart(self):
        # The synodic month runs from about 29.27 to 29.83 days; an
        # eccentric orbit is what spreads it. A phase search that
        # skipped a cycle, or found the wrong one, lands outside.
        for target in (0.0, 0.5):
            times = self._phases(target)
            for earlier, later in zip(times, times[1:]):
                gap = (later - earlier).total_seconds() / 86400.0
                assert 29.2 <= gap <= 29.9, (target, earlier, gap)

    def test_the_phase_fraction_only_advances(self):
        """The Moon gains on the Sun in longitude every hour of the year.

        It never truly retrogrades against the Sun, so the fraction runs
        forward through the cycle and wraps once a month. A step that
        went backwards would mean the longitudes had come apart.
        """
        t = datetime(2026, 1, 1, tzinfo=UTC)
        prev = moon_phase_frac(t)
        for _ in range(24 * 400):
            t += timedelta(hours=1)
            cur = moon_phase_frac(t)
            assert (cur - prev) % 1.0 < 0.5, t  # forward, wrap allowed
            prev = cur
