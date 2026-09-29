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
from linecast.moon.readings import Reading, evening


class Hebrew(Reading):
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
