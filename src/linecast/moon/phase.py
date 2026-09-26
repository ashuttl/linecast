"""The moon's phase: where it is in its cycle, and its name and icon.

Reference: Meeus, "Astronomical Algorithms" (2nd ed.), ch. 49.
"""

from datetime import timezone

from linecast.astro.ephemeris import moon_phase_frac
from linecast._glyphs import _icon_set
from linecast._runtime import RuntimeConfig, current_runtime


MOON_NAMES = [
    "New Moon", "Waxing Crescent", "First Quarter", "Waxing Gibbous",
    "Full Moon", "Waning Gibbous", "Last Quarter", "Waning Crescent",
]


# Mean length of the synodic month (new moon to new moon) in days.
# Value from the Explanatory Supplement to the Astronomical Almanac (3rd ed.).
SYNODIC_MONTH = 29.53058867

def moon_cycle_frac(dt):
    """Fraction of the synodic cycle elapsed since New Moon, in [0, 1)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return moon_phase_frac(dt.astimezone(timezone.utc))

def moon_phase(dt, runtime=None):
    """Returns (index 0-7, name, nerd_font_icon).

    Uses narrow ~24h windows for principal phases (New, Full, Quarters)
    and wider bins for transitional phases, matching almanac conventions.
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
    return idx, MOON_NAMES[idx], _icon_set(runtime)["moon_icons"][idx]
