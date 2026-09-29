"""The Hebrew calendar, by the fixed arithmetic (astro/calendars/hebrew.py).

The Hebrew day begins at the same sunset as the Hijri day, and turns
with the reader's own (readings.evening). The holidays follow the
place shown: in Israel one day of Yom Tov, elsewhere two (ctx.israel).
The panel keeps to transliteration, since terminals lay Hebrew out
unreliably; the --json block carries the date in Hebrew letters too.
"""

from linecast.astro.calendars.hebrew import (
    days_in_month, days_in_year, hebrew_date, holiday_key, is_leap_year,
    next_holiday, rosh_chodesh,
)
from linecast.astro.calendars.hebrew import next_month_start as next_hebrew_month
from linecast.moon.i18n import (
    hebrew_date_hebrew, hebrew_date_label, hebrew_holiday_name, hebrew_month_name,
    rosh_chodesh_label,
)
from linecast.moon.readings import Day, Panel, Reading, begun_at_sunset, evening, month_span


class Hebrew(Reading):
    def headline(self, ctx):
        _turned, h_day = evening(ctx)
        return None, hebrew_date_label(*hebrew_date(h_day))

    def panel(self, ctx):
        # As the Hijri calendar's: the coming month in the month's table,
        # the next holiday in the year's.
        _turned, h_day = evening(ctx)
        nxt_day, (nxt_year, nxt_month) = next_hebrew_month(h_day)
        fest_day, fest_key = next_holiday(h_day, ctx.israel)
        return Panel(
            month=(Day(hebrew_month_name(nxt_year, nxt_month), nxt_day),),
            year=(begun_at_sunset(hebrew_holiday_name(fest_key), fest_day, h_day, ctx),))

    def json_block(self, ctx):
        # The Hebrew date, turned with the reader's sunset as the panel
        # turns it, in letters too (a JSON consumer can lay Hebrew out
        # better than a terminal), the year's shape, the coming month,
        # the holiday in progress, and the next holiday, by the scheme
        # of the place.
        turned, h_day = evening(ctx)
        h_year, h_month, h_dom = hebrew_date(h_day)
        nxt_day, (nxt_year, nxt_month) = next_hebrew_month(h_day)
        hol_day, hol_key = next_holiday(h_day, ctx.israel)
        today_key = holiday_key(h_day, ctx.israel)
        return {
            "name": self.name,
            "year": h_year,
            "leap_year": is_leap_year(h_year),
            "days_in_year": days_in_year(h_year),
            "month": h_month,
            "month_name": hebrew_month_name(h_year, h_month),
            "day": h_dom,
            "days_in_month": days_in_month(h_year, h_month),
            "label": hebrew_date_label(h_year, h_month, h_dom),
            "hebrew_label": hebrew_date_hebrew(h_year, h_month, h_dom),
            "after_sunset": turned,
            "holiday": hebrew_holiday_name(today_key) if today_key else None,
            "next_month": {
                "name": hebrew_month_name(nxt_year, nxt_month),
                "date": nxt_day.isoformat(),
            },
            "next_holiday": {
                "name": hebrew_holiday_name(hol_key),
                "date": hol_day.isoformat(),
            },
        }

    def hover(self, day, ctx):
        line = hebrew_date_label(*hebrew_date(day))
        key = holiday_key(day, ctx.israel)
        if key:
            line = f"{hebrew_holiday_name(key)} · {line}"
        elif rosh_chodesh(day):
            line = f"{rosh_chodesh_label(*rosh_chodesh(day))} · {line}"
        return line

    def cell_label(self, day, ctx, new_moon=None):
        # A holiday names every day it runs, Sukkot's seven and
        # Hanukkah's eight included, the way a printed calendar does.
        # The month starts ride in the corner with the Hebrew day.
        key = holiday_key(day, ctx.israel)
        return (hebrew_holiday_name(key), True) if key else None

    def corner(self, day, ctx):
        year, month, dom = hebrew_date(day)
        return dom, hebrew_month_name(year, month)

    def span(self, first, last, ctx):
        (y1, m1, _), (y2, m2, _) = hebrew_date(first), hebrew_date(last)
        return month_span((y1, m1, hebrew_month_name(y1, m1)),
                          (y2, m2, hebrew_month_name(y2, m2)))
