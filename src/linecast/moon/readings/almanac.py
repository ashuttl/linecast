"""The Old Farmer's Almanac: the English-language reading of the Moon.

The almanac has no calendar of its own: it reads the month in halves,
the light of the Moon (new to full) and the dark (full to new), each
with its gardening rule, and the day by its solunar periods, the major
ones at the Moon's meridian passes and the minor ones at its rising
and setting. It names the full moons too (astro/seasons.py). The
gardening advice is strings in the locale files' MOON tables.
"""

from datetime import datetime, time

from linecast._timefmt import fmt_time_dt, iso_minutes
from linecast.astro.ephemeris import (
    _moon_events_for_local_date, _moon_transits_for_local_date,
)
from linecast.moon.i18n import _ms
from linecast.moon.phase import moon_cycle_frac
from linecast.moon.readings import Panel, Reading


def _half(moment):
    """'light' while the Moon waxes, 'dark' while it wanes."""
    return "light" if moon_cycle_frac(moment) < 0.5 else "dark"


def _solunar(ctx):
    """The day's solunar periods: ((upper, lower) meridian passes, the
    majors; (rise, set), the minors), each None where the Moon makes
    none that day."""
    tzinfo = ctx.now_local.tzinfo
    return (_moon_transits_for_local_date(ctx.today, ctx.lng, tzinfo),
            _moon_events_for_local_date(ctx.today, ctx.lat, ctx.lng, tzinfo))


class Almanac(Reading):
    full_moon_names = True

    def headline(self, ctx):
        return None, _ms(f"{_half(ctx.now_local)}_of_moon", ctx.runtime)

    def panel(self, ctx):
        # The gardening rule for the half of the month, and the day's
        # solunar periods.
        runtime = ctx.runtime
        half = _half(ctx.now_local)
        majors, minors = _solunar(ctx)

        def times(moments):
            moments = sorted(t for t in moments if t is not None)
            return " · ".join(fmt_time_dt(t, use_24h=runtime.use_24h)
                              for t in moments) or "—"

        return Panel(counsel=(
            _ms("good_for", runtime, things=_ms(f"{half}_good", runtime)),
            _ms("hold_off", runtime, things=_ms(f"{half}_hold", runtime)),
            f"{_ms('solunar_major', runtime)} {times(majors)}  "
            f"{_ms('solunar_minor', runtime)} {times(minors)}",
        ))

    def json_block(self, ctx):
        (upper, lower), (day_rise, day_set) = _solunar(ctx)
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
