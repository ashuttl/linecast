"""The old Icelandic calendar (astro/calendars/icelandic.py).

It gives a date by the week of summer or winter, counted from the
first day of summer, and has months of thirty days, the days the
almanac names (the first day of winter, bóndadagur), and the moons it
names, each lit by a new moon found from Epiphany and Easter. The day
turns at midnight: the almanac's calendar is a civil one. The names
are Icelandic in every language; the week is in the UI language.
"""

from linecast.astro.calendars.icelandic import (
    has_sumarauki, icelandic_week, icelandic_year, lit_moon_key, month_key,
    moon_key, named_day_key, next_month_start, next_named_day, next_named_moon,
)
from linecast.moon.i18n import (
    icelandic_day_name, icelandic_month_name, icelandic_moon_name, icelandic_week_label,
)
from linecast.moon.readings import Reading


class Icelandic(Reading):
    def json_block(self, ctx):
        # The misseri and its week (null on the veturnætur, which no
        # week counts), the month, whether the year has its leap week,
        # the named day and moon in progress, and the coming month,
        # named day, and named moon, dated by the day it is lit.
        today = ctx.today
        misseri, week = icelandic_week(today)
        nxt_day, nxt_key = next_month_start(today)
        day_start, day_key = next_named_day(today)
        today_key = named_day_key(today)
        moon = moon_key(ctx.now_local)
        moon_lit, next_moon = next_named_moon(ctx.now_local)
        return {
            "name": self.name,
            "season": misseri,
            "week": week,
            "label": icelandic_week_label(today, ctx.runtime),
            "month_name": icelandic_month_name(month_key(today)),
            "sumarauki": has_sumarauki(icelandic_year(today)),
            "named_day": icelandic_day_name(today_key) if today_key else None,
            "named_moon": icelandic_moon_name(moon) if moon else None,
            "next_month": {
                "name": icelandic_month_name(nxt_key),
                "date": nxt_day.isoformat(),
            },
            "next_named_day": {
                "name": icelandic_day_name(day_key),
                "date": day_start.isoformat(),
            },
            "next_named_moon": {
                "name": icelandic_moon_name(next_moon),
                "date": moon_lit.astimezone(ctx.now_local.tzinfo).date().isoformat(),
            },
        }

    def hover(self, day, ctx):
        line = (f"{icelandic_week_label(day, ctx.runtime)} · "
                f"{icelandic_month_name(month_key(day))}")
        key = named_day_key(day)
        if key and key != "veturnaetur":
            line = f"{icelandic_day_name(key)} · {line}"
        return line

    def new_moon_name(self, at):
        # The almanac prints a named moon's name at the new moon that
        # lights it, as the English almanacs name the full moons.
        key = lit_moon_key(at)
        return icelandic_moon_name(key) if key else None
