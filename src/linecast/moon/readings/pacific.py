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
    ANAHULU_COUNSEL, COUNSEL_ATTRIBUTION, COUNSEL_URL, night_note, pacific_night,
)
from linecast.moon.i18n import (
    anahulu_name, pacific_night_label, pacific_night_name, refaluwasch_name,
)
from linecast.moon.readings import Reading


class Pacific(Reading):
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
