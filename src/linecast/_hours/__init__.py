"""The day read in a tradition's hours: the frame the tables fill in.

The moon reads the Moon through a tradition's calendar; sunshine reads
the Sun through a tradition's hours. Every system worth having is one
shape. A day has two edges set by the Sun, the time between them is
divided into a fixed number of equal parts, and named marks fall along
it. The night, from one day's end to the next day's start, is divided
the same way. Only the edges, the count, and the names differ:

- halachic (zmanim): twelve sha'ot zmaniyot, sunrise to sunset by
  the Gr"a, seventy-two minutes either side by the Magen Avraham;
- roman (roman): twelve horae by day, four vigiliae by night;
- japanese (wadokei): six koku each, the edges at the Sun 7°21′40″
  below the horizon;
- islamic (prayer_times): no equal hours at all, only the marks, by
  a method that follows the country, and the fast in Ramadan;
- swahili (swahili): twelve hours each way from the clock's six
  o'clock, read off the wall clock.

Each tradition is a module beside this one, and answers `day_hours`
for a civil date at a place with a DayHours: the edges, the count, and
the marks. This module holds the model, the reading of a moment
against it (which hour, how far in, how long the hour is), and the
resolver that picks a system from the flag, the saved setting, or the
language.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

HOURS_SYSTEMS = ("halachic", "roman", "japanese", "islamic", "swahili")

# The system a language tells the time in. Swahili says the hour in
# its own count, so `auto` reads the day in it for a Swahili reader.
HOURS_OF_LANG = {"sw": "swahili"}


@dataclass(frozen=True)
class Mark:
    """A named moment of the day: alot hashachar, hora tertia, Asr."""
    key: str
    at: datetime          # aware, in the place's own zone


@dataclass
class DayHours:
    """One civil date read in one system.

    The edges are aware local datetimes, or None where the Sun never
    gets there: a polar season at the horizon, a Nordic June at 16.1°.
    `divisions` is the number of equal hours between the day's edges,
    or None for a system that keeps marks only; the night has its own
    count, `night_divisions`, where it differs (Rome's four vigiliae
    against twelve horae). `variant` names the opinion or method the
    table used. `fast` is (start, end) on a day of fasting, Fajr to
    Maghrib in Ramadan, or None. `after` is the first mark of the next
    day where the table names one, so a night with no hours of its own
    still counts down to the dawn. `wall_clock` marks hours that are the
    civil clock's own, read off the local time rather than measured
    between the edges, so a night with a clock change still runs twelve.
    """
    system: str
    date: date
    day_start: datetime | None
    day_end: datetime | None
    prev_day_end: datetime | None     # yesterday's, for the night before
    next_day_start: datetime | None   # tomorrow's, for the night after
    divisions: int | None
    marks: list = field(default_factory=list)
    variant: str | None = None
    night_divisions: int | None = None
    fast: tuple | None = None
    after: Mark | None = None
    wall_clock: bool = False

    def __post_init__(self):
        if self.night_divisions is None:
            self.night_divisions = self.divisions


@dataclass(frozen=True)
class Reading:
    """Where a moment falls: hour *index* (from 0) of the day or the
    night, *fraction* of the way through it, and the hour's length."""
    night: bool
    index: int
    fraction: float
    hour_seconds: float
    start: datetime
    end: datetime


def resolve_hours(flag, lang=None):
    """(system, variant) in force: the --hours flag, else the saved
    setting, else the language's own, else (None, None). The calendars
    follow the language because their readers know the Moon through
    them; the hours follow it only where the language tells the time
    in them, as Swahili does, and the traditions of observance stay a
    choice. A hyphen in the name separates the tradition from an
    opinion or method within it: halachic-mga is the halachic hours by
    the Magen Avraham."""
    name = flag
    if name is None:
        from linecast._config import saved_hours
        name = saved_hours()
    if name is None:
        name = HOURS_OF_LANG.get(lang)
    if name is None or name == "none":
        return None, None
    system, _hyphen, variant = name.partition("-")
    return system, (variant or None)


def _aware(now, tzinfo):
    """*now* as an aware datetime, in *tzinfo* or the machine's zone."""
    if now.tzinfo is None:
        return now.astimezone(tzinfo) if tzinfo else now.astimezone()
    return now


# The arithmetic on the day's moments runs in UTC. Two aware datetimes
# that share a ZoneInfo subtract and compare as wall-clock time, and a
# timedelta added to one moves the wall clock, so a night that crosses
# a clock change would come out an hour short or long, and a mark
# placed a fraction of the way through it would land an hour off.
# Everything here goes through these three, and the tables do too.

def utc(dt):
    """*dt* as the instant it is, for a difference or a comparison."""
    return dt.astimezone(timezone.utc)


def elapsed(start, end):
    """The time from *start* to *end*, as it passes, not as the clock reads."""
    return utc(end) - utc(start)


def shift(dt, delta):
    """*dt* moved by *delta* of real time, read in *dt*'s own zone."""
    return (utc(dt) + delta).astimezone(dt.tzinfo)


def day_hours(system, local_date, lat, lng, tzinfo=None, variant=None,
              country=None):
    """The table's answer for a civil date at a place, or None for a
    system this build does not know."""
    if system == "halachic":
        from linecast._hours.zmanim import zmanim
        return zmanim(local_date, lat, lng, tzinfo, opinion=variant)
    if system == "roman":
        from linecast._hours.roman import roman_hours
        return roman_hours(local_date, lat, lng, tzinfo)
    if system == "japanese":
        from linecast._hours.wadokei import wadokei
        return wadokei(local_date, lat, lng, tzinfo)
    if system == "islamic":
        from linecast._hours.prayer_times import prayer_times
        return prayer_times(local_date, lat, lng, tzinfo, method=variant,
                            country=country)
    if system == "swahili":
        from linecast._hours.swahili import swahili_hours
        return swahili_hours(local_date, tzinfo)
    return None


def hours_now(system, now, lat, lng, tzinfo=None, variant=None, country=None):
    """The DayHours whose day *now* falls in, and *now* made aware.

    That is the civil date's table nearly always. At a high latitude in
    summer the Sun can set after midnight, so the day that began on the
    date before is still running in the small hours of this one, and a
    moment before that sunset belongs to it: the sunset to count down
    to is the one an hour away, not tomorrow's. The mirror case, a day
    that begins before midnight, belongs to the date after.
    """
    now = _aware(now, tzinfo)
    hours = day_hours(system, now.date(), lat, lng, tzinfo, variant, country)
    if hours is not None:
        if hours.prev_day_end is not None and utc(now) < utc(hours.prev_day_end):
            hours = day_hours(system, now.date() - timedelta(days=1), lat, lng,
                              tzinfo, variant, country)
        elif hours.next_day_start is not None and utc(now) >= utc(hours.next_day_start):
            hours = day_hours(system, now.date() + timedelta(days=1), lat, lng,
                              tzinfo, variant, country)
    return hours, now


def reading(hours, now):
    """Where *now* falls in the system's hours, or None when the system
    keeps no hours or the Sun never made the edges that day."""
    if hours is None or not hours.divisions:
        return None
    now = _aware(now, hours.day_start.tzinfo if hours.day_start else None)
    if hours.wall_clock:
        return _wall_reading(hours, now)
    spans = (
        (False, hours.day_start, hours.day_end),
        (True, hours.day_end, hours.next_day_start),
        (True, hours.prev_day_end, hours.day_start),
    )
    for night, start, end in spans:
        if start is None or end is None or not utc(start) <= utc(now) < utc(end):
            continue
        count = hours.night_divisions if night else hours.divisions
        hour = elapsed(start, end) / count
        through = elapsed(start, now) / hour
        index = min(count - 1, int(through))
        return Reading(night, index, through - index, hour.total_seconds(),
                       start, end)
    return None


def _wall_reading(hours, now):
    """The reading of a clock's own hours, off *now*'s wall clock: the
    hours since the day's or the night's edge at its hour, and the
    minutes into this one."""
    edge = hours.day_start.hour
    night = not edge <= now.hour < hours.day_end.hour
    index = (now.hour - edge) % hours.divisions
    top = now.replace(minute=0, second=0, microsecond=0)
    through = (now - top).total_seconds() / 3600
    return Reading(night, index, through, 3600.0, top, shift(top, timedelta(hours=1)))


def next_mark(hours, now):
    """The first mark still to come; once the day's are past, the next
    day's first where the table names it, else None."""
    if hours is None:
        return None
    now = _aware(now, hours.day_start.tzinfo if hours.day_start else None)
    for mark in hours.marks:
        if utc(mark.at) > utc(now):
            return mark
    if hours.after is not None and utc(hours.after.at) > utc(now):
        return hours.after
    return None


def fmt_duration(seconds, lang="en"):
    """'1h 12m', '22m', '1h': the plain form the countdowns use, in the
    language's own form (_i18n.fmt_duration_parts)."""
    from linecast._i18n import fmt_duration_parts
    minutes = int(round(seconds / 60))
    h, m = divmod(minutes, 60)
    if h and m:
        return fmt_duration_parts(lang, ("h", h), ("m", m))
    if h:
        return fmt_duration_parts(lang, ("h", h))
    return fmt_duration_parts(lang, ("m", m))


def last_mark(hours, now):
    """The latest mark already past, or None before the day's first."""
    if hours is None:
        return None
    now = _aware(now, hours.day_start.tzinfo if hours.day_start else None)
    passed = [m for m in hours.marks if utc(m.at) <= utc(now)]
    return passed[-1] if passed else None
