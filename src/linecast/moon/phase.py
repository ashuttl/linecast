"""The Moon's facts: where it is in its cycle, its name and icon, how
much of it is lit, when it next rises and sets, and when it is next new
or full.

Reference: Meeus, "Astronomical Algorithms" (2nd ed.), ch. 49.
"""

from datetime import timedelta, timezone

from linecast.astro.ephemeris import (
    _moon_events_for_local_date, moon_illuminated_fraction, moon_phase_frac,
    next_moon_phase_utc,
)
from linecast.terminal.glyphs import moon_icon
from linecast._runtime import RuntimeConfig, current_runtime


MOON_NAMES = [
    "New Moon", "Waxing Crescent", "First Quarter", "Waxing Gibbous",
    "Full Moon", "Waning Gibbous", "Last Quarter", "Waning Crescent",
]


# Mean length of the synodic month (new moon to new moon) in days.
# Value from the Explanatory Supplement to the Astronomical Almanac (3rd ed.).
SYNODIC_MONTH = 29.53058867

# Matches the rise/set threshold in _moon_events_for_local_date: net effect
# of refraction and lunar parallax puts the geometric event at +0.125°.
HORIZON_THRESHOLD_DEG = 0.125

def moon_cycle_frac(dt):
    """Fraction of the synodic cycle elapsed since New Moon, in [0, 1)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return moon_phase_frac(dt.astimezone(timezone.utc))

def moon_phase(dt, runtime=None, *, bg_color=None):
    """Returns (index 0-7, name, icon).

    Uses narrow ~24h windows for principal phases (New, Full, Quarters)
    and wider bins for transitional phases, matching almanac conventions.
    Renderers pass their background to adapt Nerd Font moon shapes;
    without one, the icon keeps its named phase, as in JSON output.
    """
    frac = moon_cycle_frac(dt)

    # ±0.017 of the synodic cycle ≈ ±12 hours around each principal phase.
    # This window width was chosen to match the ~1-day labeling convention
    # used in printed almanacs (e.g. the USNO Astronomical Almanac).
    T = 0.017
    if frac < T or frac > 1 - T:
        idx = 0   # New Moon
    elif abs(frac - 0.25) < T:
        idx = 2   # First Quarter
    elif abs(frac - 0.5) < T:
        idx = 4   # Full Moon
    elif abs(frac - 0.75) < T:
        idx = 6   # Last Quarter
    elif frac < 0.25:
        idx = 1   # Waxing Crescent
    elif frac < 0.5:
        idx = 3   # Waxing Gibbous
    elif frac < 0.75:
        idx = 5   # Waning Gibbous
    else:
        idx = 7   # Waning Crescent
    if runtime is None:
        runtime = current_runtime(RuntimeConfig)
    return idx, MOON_NAMES[idx], moon_icon(idx, runtime, bg_color=bg_color)


def moon_illumination(dt):
    """Illuminated fraction of the lunar disc, in [0, 1]."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return moon_illuminated_fraction(dt.astimezone(timezone.utc))


def upcoming_moon_events(now_local, lat, lng):
    """Next (moonrise, moonset) datetimes strictly after *now_local*.

    Scans up to three local calendar days. At high latitudes the Moon can
    stay up (or down) for days, so either value may still be None, and
    a date can hold two moonrises, so today's are searched from now on.
    """
    tzinfo = now_local.tzinfo
    next_rise = None
    next_set = None
    for offset in range(3):
        day = now_local.date() + timedelta(days=offset)
        rise, sset = _moon_events_for_local_date(day, lat, lng, tzinfo,
                                                 since=now_local)
        if next_rise is None and rise is not None:
            next_rise = rise
        if next_set is None and sset is not None:
            next_set = sset
        if next_rise is not None and next_set is not None:
            break
    return next_rise, next_set


def next_phase_local(moment_utc, target_frac, now_local):
    """Next new or full moon, in the observer's timezone.

    Falls back to a mean-synodic estimate if the search comes up empty,
    so the panel still has a date to print.
    """
    found = next_moon_phase_utc(moment_utc, target_frac)
    if found is None:
        frac = moon_cycle_frac(now_local)
        ahead = ((target_frac - frac) % 1.0) * SYNODIC_MONTH
        return now_local + timedelta(days=ahead)
    return found.astimezone(now_local.tzinfo)
