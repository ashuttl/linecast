"""The Old Farmer's Almanac: the English-language reading of the Moon.

The almanac has no calendar of its own: it reads the month in halves,
the light of the Moon (new to full) and the dark (full to new), each
with its gardening rule, and the day by its solunar periods, the major
ones at the Moon's meridian passes and the minor ones at its rising
and setting. It names the full moons too (astro/seasons.py). The
gardening advice is strings in the locale files' MOON tables.
"""

from datetime import datetime, time

from linecast._timefmt import iso_minutes
from linecast.astro.ephemeris import (
    _moon_events_for_local_date, _moon_transits_for_local_date,
)
from linecast.moon.i18n import _ms
from linecast.moon.phase import moon_cycle_frac
from linecast.moon.readings import Reading


def _half(moment):
    """'light' while the Moon waxes, 'dark' while it wanes."""
    return "light" if moon_cycle_frac(moment) < 0.5 else "dark"


class Almanac(Reading):
    full_moon_names = True

    def json_block(self, ctx):
        upper, lower = _moon_transits_for_local_date(
            ctx.today, ctx.lng, ctx.now_local.tzinfo)
        day_rise, day_set = _moon_events_for_local_date(
            ctx.today, ctx.lat, ctx.lng, ctx.now_local.tzinfo)
        return {
            "name": self.name,
            "gardening": _half(ctx.now_local),
            "solunar_major": sorted(iso_minutes(t) for t in (upper, lower)
                                    if t is not None),
            "solunar_minor": sorted(iso_minutes(t) for t in (day_rise, day_set)
                                    if t is not None),
        }

    def hover(self, day, ctx):
        noon = datetime.combine(day, time(12), tzinfo=ctx.now_local.tzinfo)
        return _ms(f"{_half(noon)}_of_moon", ctx.runtime)
