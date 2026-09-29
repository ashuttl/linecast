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
    hijri_date_label, hijri_month_name, hijri_observance_name, hijri_sighting_note,
)
from linecast.moon.readings import Reading, evening


class Hijri(Reading):
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
