"""The Hijri calendar, by the Umm al-Qura rule (astro/calendars/hijri.py).

The Hijri day begins at sunset, so the date turns with the reader's
own sunset (readings.evening). The months follow the Moon, and the
observances keep their Hijri dates. Where the months are begun by a
sighting instead, as in Iran, the dates may differ by a day, and the
hover chip says so.
"""

from linecast.astro.calendars.hijri import (
    days_in_month, hijri_date, next_month_start, next_observance, observance_key,
)
from linecast.moon.i18n import (
    hijri_date_label, hijri_era, hijri_month_name, hijri_observance_name,
    hijri_sighting_note,
)
from linecast.moon.readings import Day, Panel, Reading, begun_at_sunset, evening, month_span


class Hijri(Reading):
    def headline(self, ctx):
        _turned, h_day = evening(ctx)
        return None, hijri_date_label(*hijri_date(h_day), ctx.lang)

    def panel(self, ctx):
        # No solar terms. The coming month follows the Moon, so it joins
        # the month's table, a day or two after the new moon; the next
        # observance is the year's.
        _turned, h_day = evening(ctx)
        nxt_day, (_nxt_year, nxt_month) = next_month_start(h_day)
        fest_day, fest_key = next_observance(h_day)
        return Panel(
            month=(Day(hijri_month_name(nxt_month, ctx.lang), nxt_day),),
            year=(begun_at_sunset(hijri_observance_name(fest_key, ctx.lang),
                                  fest_day, h_day, ctx),))

    def json_block(self, ctx):
        # The Hijri date, turned with the reader's sunset as the panel
        # turns it, the month's length, the coming month, and the next
        # observance -- today's, once the evening that opens it has come.
        lang = ctx.lang
        turned, h_day = evening(ctx)
        h_year, h_month, h_dom = hijri_date(h_day)
        nxt_day, (_nxt_year, nxt_month) = next_month_start(h_day)
        obs_day, obs_key = next_observance(h_day)
        return {
            "name": self.name,
            "year": h_year,
            "month": h_month,
            "month_name": hijri_month_name(h_month, lang),
            "day": h_dom,
            "days_in_month": days_in_month(h_day),
            "label": hijri_date_label(h_year, h_month, h_dom, lang),
            "after_sunset": turned,
            "next_month": {
                "name": hijri_month_name(nxt_month, lang),
                "date": nxt_day.isoformat(),
            },
            "next_observance": {
                "name": hijri_observance_name(obs_key, lang),
                "date": obs_day.isoformat(),
            },
        }

    def hover(self, day, ctx):
        line = hijri_date_label(*hijri_date(day), ctx.lang)
        key = observance_key(day)
        if key:
            line = f"{hijri_observance_name(key, ctx.lang)} · {line}"
        return line

    def hover_note(self, ctx):
        return hijri_sighting_note(ctx.lang)

    def cell_label(self, day, ctx, new_moon=None):
        # The month starts ride in the corner with the Hijri day.
        key = observance_key(day)
        return (hijri_observance_name(key, ctx.lang), True) if key else None

    def corner(self, day, ctx):
        _year, month, dom = hijri_date(day)
        return dom, hijri_month_name(month, ctx.lang)

    def span(self, first, last, ctx):
        (y1, m1, _), (y2, m2, _) = hijri_date(first), hijri_date(last)
        return month_span((y1, m1, hijri_month_name(m1, ctx.lang)),
                          (y2, m2, hijri_month_name(m2, ctx.lang)),
                          f" {hijri_era(ctx.lang)}")
