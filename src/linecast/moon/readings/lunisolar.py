"""The lunisolar calendars: Chinese, Japanese, Korean, and Vietnamese.

One arithmetic, from the ephemeris at each calendar's meridian
(astro/calendars/lunisolar.py): the lunar date beside the phase, the
solar term in progress, and the coming festival. Japan names the
nights too (居待月 on the 18th), which stand in for the phase's name
in Japanese. In the calendar's own language (ctx.native) the dates
and festivals keep its script; in any other, the customary English.
"""

from linecast.astro.calendars.lunisolar import (
    CALENDAR_MERIDIAN_HOURS, current_term, lunisolar_date, next_lunar_event, next_term,
)
from linecast.moon.i18n import (
    _zh_day_name, festival_table, ja_night_name, lunar_date_label, term_label,
    vi_month_label, zh_month_label,
)
from linecast.moon.readings import Reading


class Lunisolar(Reading):
    def _label_lang(self, ctx):
        return ctx.lang if ctx.native else "en"

    def _lunar(self, day):
        """(month, day, is_leap) for a civil date, or None."""
        return lunisolar_date(day, CALENDAR_MERIDIAN_HOURS[self.name])

    def festivals(self, ctx):
        """(month, day) → name, in the language the calendar reads in."""
        return festival_table(self.name, self._label_lang(ctx))

    def json_block(self, ctx):
        label_lang = self._label_lang(ctx)
        lunar = self._lunar(ctx.today)
        cur_k, _cur_start = current_term(ctx.moment_utc)
        nxt_k, nxt_start = next_term(ctx.moment_utc)
        fest = next_lunar_event(ctx.today, CALENDAR_MERIDIAN_HOURS[self.name],
                                self.festivals(ctx))
        return {
            "name": self.name,
            "month": lunar[0] if lunar else None,
            "day": lunar[1] if lunar else None,
            "leap_month": lunar[2] if lunar else None,
            "label": (lunar_date_label(*lunar, label_lang)
                      if lunar else None),
            # Japan names the night itself; the other calendars don't.
            "night_name": (ja_night_name(lunar[1])
                           if self.name == "japanese" and lunar else None),
            "solar_term": term_label(cur_k, label_lang),
            "next_solar_term": {
                "name": term_label(nxt_k, label_lang),
                "date": (nxt_start.astimezone(ctx.now_local.tzinfo)
                         .date().isoformat()),
            },
            "next_festival": ({"name": fest[1],
                               "date": fest[0].isoformat()}
                              if fest else None),
        }

    def night_name(self, day, ctx):
        lunar = self._lunar(day)
        if self.name == "japanese" and ctx.native and lunar is not None:
            return ja_night_name(lunar[1])
        return None

    def hover(self, day, ctx):
        # The lunar date, after the day's festival. The phase line
        # already names a Japanese night, so the festival that is the
        # night's own name (十五夜) is not said twice.
        lunar = self._lunar(day)
        if lunar is None:
            return None
        m, day_n, leap = lunar
        festival = self.festivals(ctx).get((m, day_n)) if not leap else None
        parts = [festival] if festival and festival != self.night_name(day, ctx) else []
        return " · ".join([*parts, lunar_date_label(m, day_n, leap, self._label_lang(ctx))])

    def cell_label(self, day, ctx, new_moon=None):
        # The 农历 day names, which are words, and each lunar month's
        # opening day, read at a glance; the festivals in every script.
        lunar = self._lunar(day)
        if lunar is None:
            return None
        m, d, leap = lunar
        fest = self.festivals(ctx)
        if not leap and (m, d) in fest:
            return fest[(m, d)], True
        if self.name == "chinese" and ctx.native:
            if d == 1:
                return zh_month_label(m, leap, ctx.lang), False
            return _zh_day_name(d), False
        if d == 1:
            if self.name == "japanese" and ctx.native:
                return f"{m}月", False
            if self.name == "korean" and ctx.native:
                return f"{m}월", False
            if self.name == "vietnamese" and ctx.native:
                return vi_month_label(m, leap, short=True), False
            return f"m{m}", False
        return None

    def dense(self, ctx):
        # The 农历 names every day.
        return self.name == "chinese" and ctx.native
