"""The Thai lunar calendar, by the Suriyayart arithmetic
(astro/calendars/thai_lunar.py).

It reads the Moon as a waxing or waning day -- ขึ้น/แรม … ค่ำ -- in
Thai numerals, as the printed calendars have it, and keeps no solar
terms: the year is named by its animal, and the recurring observance
is the วันพระ, the four holy days of each month, which follow the
phases. In Thai it reads in Thai; in any other language, in English.
"""

from linecast.astro.calendars.thai_lunar import (
    _festival_key as festival_key, cs_year, is_wan_phra, next_thai_festival,
    next_wan_phra, thai_lunar_date, year_animal_index,
)
from linecast.moon.i18n import (
    thai_festival_name, thai_lunar_label, thai_month_label, thai_year_label,
    wan_phra_label,
)
from linecast.moon.readings import Day, Now, Panel, Reading, kept_or_coming


def _label_lang(ctx):
    return "th" if ctx.native else "en"


class Thai(Reading):
    def headline(self, ctx):
        return None, thai_lunar_label(*thai_lunar_date(ctx.today), _label_lang(ctx))

    def panel(self, ctx):
        # The year's animal is where the year stands; the วันพระ is the
        # month's, kept today or the next of them; the coming festival
        # is the year's.
        today, label_lang = ctx.today, _label_lang(ctx)
        if is_wan_phra(today):
            holy = Now(wan_phra_label(True, label_lang), today=True)
        else:
            holy = Day(wan_phra_label(False, label_lang), next_wan_phra(today))
        fest_day, fest_key = next_thai_festival(today)
        return Panel(month=(holy,), year=(
            Now(thai_year_label(year_animal_index(today), label_lang)),
            kept_or_coming(thai_festival_name(fest_key, label_lang), fest_day, today),
        ))

    def json_block(self, ctx):
        today = ctx.today
        t_month, t_day, t_doubled = thai_lunar_date(today)
        label_lang = _label_lang(ctx)
        fest_day, fest_key = next_thai_festival(today)
        return {
            "name": self.name,
            "month": t_month,
            "doubled_eighth": t_doubled,
            "day": t_day,
            "phase": "waxing" if t_day <= 15 else "waning",
            "phase_day": t_day if t_day <= 15 else t_day - 15,
            "label": thai_lunar_label(t_month, t_day, t_doubled, label_lang),
            "year_cs": cs_year(today),
            "year_be": today.year + 543,
            "year_animal": thai_year_label(year_animal_index(today), label_lang),
            "wan_phra": is_wan_phra(today),
            "next_wan_phra": next_wan_phra(today).isoformat(),
            "next_festival": {
                "name": thai_festival_name(fest_key, label_lang),
                "date": fest_day.isoformat(),
            },
        }

    def hover(self, day, ctx):
        m, day_n, doubled = thai_lunar_date(day)
        label_lang = _label_lang(ctx)
        line = thai_lunar_label(m, day_n, doubled, label_lang)
        key = festival_key(day)
        if key:
            line = f"{thai_festival_name(key, label_lang)} · {line}"
        elif is_wan_phra(day):
            line = f"{wan_phra_label(False, label_lang)} · {line}"
        return line

    def cell_label(self, day, ctx, new_moon=None):
        # Festivals and month starts as the other calendars have them,
        # plus the วันพระ -- the printed Thai calendars mark all four
        # holy days in every month's grid.
        label_lang = _label_lang(ctx)
        key = festival_key(day)
        if key:
            return thai_festival_name(key, label_lang), True
        m, d, doubled = thai_lunar_date(day)
        if d == 1:
            return thai_month_label(m, doubled, label_lang), False
        if ctx.native and is_wan_phra(day):
            return wan_phra_label(False, label_lang), False
        return None
