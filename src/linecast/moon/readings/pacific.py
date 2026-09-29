"""The Pacific calendars: Hawaiʻi's, American Samoa's, and the Marianas'.

They read the Moon as a named night, counted from the first visible
crescent (astro/calendars/pacific.py), in their own language for every
reader, since the names have no English renderings. They have no
months by number, solar terms, or festivals. The Kaulana Mahina adds
the anahulu, the ten-night span a night falls in, and the fishing
counsel for it; the CNMI calendar prints the Refaluwasch name beside
the CHamoru one where it has one.
"""

from linecast.astro.calendars.pacific import (
    ANAHULU_COUNSEL, COUNSEL_ATTRIBUTION, COUNSEL_SOURCE_LINE, COUNSEL_URL, night_note,
    pacific_night,
)
from linecast.moon.i18n import (
    anahulu_name, pacific_night_label, pacific_night_name, refaluwasch_name,
)
from linecast.moon.readings import Panel, Reading


class Pacific(Reading):
    plain_age = True

    def headline(self, ctx):
        # The night's name, and the Kaulana Mahina's anahulu beside it
        night, nights = pacific_night(self.name, ctx.today)
        aside = f"anahulu {anahulu_name(night)}" if self.name == "hawaiian" else None
        return pacific_night_label(self.name, night, nights), aside

    def panel(self, ctx):
        # The Kaulana Mahina sets its counsel under the phase: the night's
        # kapu or ʻole note when it has one, the anahulu's fishing counsel,
        # and the source named plainly. The other calendars add nothing
        # beyond the night.
        if self.name != "hawaiian":
            return Panel()
        night, nights = pacific_night(self.name, ctx.today)
        note = night_note(pacific_night_label(self.name, night, nights))
        counsel = ANAHULU_COUNSEL[anahulu_name(night)]
        return Panel(counsel=(note, counsel) if note else (counsel,),
                     source=COUNSEL_SOURCE_LINE)

    def json_block(self, ctx):
        night, nights = pacific_night(self.name, ctx.today)
        name = pacific_night_name(self.name, night, nights)
        block = {
            "name": self.name,
            "night": night,
            "nights_in_month": nights,
            "night_name": name,
        }
        if self.name == "hawaiian":
            block["anahulu"] = anahulu_name(night)
            block["counsel"] = {
                "night_note": night_note(name),
                "anahulu": ANAHULU_COUNSEL[anahulu_name(night)],
                "source": COUNSEL_ATTRIBUTION,
                "url": COUNSEL_URL,
            }
        elif self.name == "refaluwasch":
            block["refaluwasch_name"] = refaluwasch_name(night, nights)
        return block

    def hover(self, day, ctx):
        night, nights = pacific_night(self.name, day)
        line = pacific_night_label(self.name, night, nights)
        if self.name == "hawaiian":
            line += f" · anahulu {anahulu_name(night)}"
        return line

    def cell_label(self, day, ctx, new_moon=None):
        night, nights = pacific_night(self.name, day)
        return pacific_night_name(self.name, night, nights), False

    def dense(self, ctx):
        return True
