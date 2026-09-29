"""The Moon read through a traditional calendar: one reading per calendar.

The moon command can read the Moon through a calendar as well as show
it: the Chinese, Japanese, Korean, and Vietnamese lunisolar calendars,
the Thai, the Pacific calendars that name each night, the Hijri, the
Hebrew, the old Icelandic, or the Old Farmer's Almanac. Every calendar
is asked the same questions by every part of the command -- what goes
in the --json block, and what a day says in its cell of the month grid
and in its hover chip -- and answers them in its own way.

The calendars' arithmetic is astro/calendars/, one module each, and
their words are moon/i18n.py. Here each calendar is a Reading, in a
module of its own beside this one, and `reading` finds the one for the
name astro.calendars.lunisolar.resolve_calendar gives. This module
holds the base class, whose answers are the ones a calendar with
nothing to say gives, and Ctx, the moment and place each question is
asked about.
"""

from datetime import date, datetime, timedelta, timezone
from typing import NamedTuple

from linecast._i18n import lang_of
from linecast.astro.calendars.lunisolar import calendar_is_native
from linecast.astro.calendars.pacific import PACIFIC_CALENDARS


class Ctx(NamedTuple):
    """The moment and place a calendar is read at, and how to say it."""
    now_local: datetime   # aware, in the place's own zone
    today: date
    moment_utc: datetime
    lat: float
    lng: float
    runtime: object
    lang: str
    native: bool          # the calendar reads in the language's own script
    israel: bool          # the place keeps the Hebrew holidays as Israel does


def context(now_local, lat, lng, runtime, cal=None, israel=False):
    """The Ctx for reading calendar *cal* at *now_local*. A calendar shown
    in its own language keeps its own script; any other language gets
    the customary English names."""
    lang = lang_of(runtime)
    return Ctx(now_local, now_local.date(), now_local.astimezone(timezone.utc),
               lat, lng, runtime, lang,
               cal is not None and calendar_is_native(cal, lang), israel)


def evening(ctx):
    """(whether the reader's sunset has come, the day it makes it).

    The Hijri and Hebrew days begin at sunset, and the panel is read in
    the evening, so the date turns with the reader's own sunset."""
    from linecast.astro.calendars.hijri import after_sunset
    turned = after_sunset(ctx.now_local, ctx.lat, ctx.lng)
    return turned, ctx.today + timedelta(days=1 if turned else 0)


class Reading:
    """A calendar with nothing to say: every answer is empty. Each
    calendar's module subclasses it and answers what it can."""

    # The Old Farmer's Almanac names the full moons (Harvest Moon and
    # the rest). They are an English-language tradition: they show in
    # English with no calendar and with the almanac, but a reading
    # through another tradition's calendar keeps the plain phase name.
    full_moon_names = False

    def __init__(self, name):
        self.name = name   # as resolve_calendar names it

    def json_block(self, ctx):
        """The --json "calendar" block."""
        return {"name": self.name}

    def hover(self, day, ctx):
        """The calendar's line in the month grid's hover chip for *day*,
        or None."""
        return None

    def hover_note(self, ctx):
        """A line set dim under the calendar's in the hover chip, or None."""
        return None

    def night_name(self, day, ctx):
        """The name the calendar gives *day*'s night, which stands in for
        the phase's in the hover chip, or None."""
        return None

    def new_moon_name(self, at):
        """The name of the moon a new moon at *at* lights, or None."""
        return None

    def cell_label(self, day, ctx, new_moon=None):
        """(text, is_festival) for the calendar's line in *day*'s cell of
        the month grid, or None.

        A festival names its day in every script. Beyond that only the
        labels that read at a glance appear: the 农历 day names, which
        are words, and each lunar month's opening day. The Hijri and
        Hebrew calendars count their days in the cell's corner instead
        (corner), and name the month there. The full date lives in the
        hover chip. *new_moon* is the moment of a new moon that falls on
        *day*, for the calendars that name it."""
        return None

    def dense(self, ctx):
        """Whether the calendar labels every day, and so writes along the
        cells' bottom edges, where the every-cell rhythm says whose row
        it is, rather than after the day's number."""
        return False

    def corner(self, day, ctx):
        """(day number, month name) for the grid cell's far corner, for a
        calendar that counts its own days there, or None."""
        return None

    def span(self, first, last, ctx):
        """The calendar's months the civil month *first*..*last* runs
        through, for the grid's title, or None.

        The printed wall calendars set this under the civil month; here
        it also covers the month starts the cells cannot show, since
        Tishrei and Muharram both open on a holiday that takes the cell,
        as Harpa, Heyannir, Gormánuður, Þorri, and Góa do."""
        return None


def month_span(first, last, era=""):
    """A title's span of months from (year, month, name) *first* to
    *last*: `Elul 5786 – Tishrei 5787`, `Tishrei – Cheshvan 5787`, or a
    lone `Shevat 5787` for a civil month that fits inside one."""
    y1, m1, n1 = first
    y2, m2, n2 = last
    if (y1, m1) == (y2, m2):
        return f"{n1} {y1}{era}"
    if y1 == y2:
        return f"{n1} – {n2} {y1}{era}"
    return f"{n1} {y1}{era} – {n2} {y2}{era}"


def reading(cal):
    """The Reading for calendar *cal*, or None for none.

    Each calendar's module is loaded when it is first asked for, as
    astro.hours loads a tradition's; whatever is not one of the others
    is lunisolar."""
    if cal is None:
        return None
    if cal in PACIFIC_CALENDARS:
        from linecast.moon.readings.pacific import Pacific
        return Pacific(cal)
    if cal == "almanac":
        from linecast.moon.readings.almanac import Almanac
        return Almanac(cal)
    if cal == "islamic":
        from linecast.moon.readings.hijri import Hijri
        return Hijri(cal)
    if cal == "hebrew":
        from linecast.moon.readings.hebrew import Hebrew
        return Hebrew(cal)
    if cal == "icelandic":
        from linecast.moon.readings.icelandic import Icelandic
        return Icelandic(cal)
    if cal == "thai":
        from linecast.moon.readings.thai import Thai
        return Thai(cal)
    from linecast.moon.readings.lunisolar import Lunisolar
    return Lunisolar(cal)
