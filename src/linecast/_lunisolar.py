"""The traditional lunisolar calendar, worked out from the ephemeris.

The rules are the Chinese ones, which the Korean and Japanese
traditional calendars also follow, each at its own meridian: a month
runs new moon to new moon and begins on the civil day of the new moon
at the calendar's meridian — UTC+8 for China, UTC+9 for Korea and
Japan, which is why 설날 or the kyūreki occasionally sit a day or a
month from the Chinese date. Month numbers anchor at the December
solstice, whose month is month 11; a suì (solstice to solstice) of
thirteen months takes its leap month at the first one containing no
major solar term — the no-zhōngqì rule.

The solar terms are the 24 points where the Sun's ecliptic longitude
is a multiple of 15°, the even multiples of 30° being the major terms.
Instants come from the same solar position the rest of the app draws
with, good to a couple of hundredths of a degree — tens of minutes of
time. A term or new moon falling within that of the meridian's
midnight could land a boundary a day off, which at almanac reading
distance is the accuracy such tables have always been read at.
"""

import math
from datetime import datetime, timedelta, timezone
from functools import lru_cache

from linecast._ephemeris import _sun_ecliptic, next_moon_phase_utc

# The three calendars, each computed at its own meridian (hours east
# of UTC), and the language each is native to. Any UI language can ask
# for any of them with --calendar; these defaults just pick the natural
# one for readers who already live on it.
CALENDAR_MERIDIAN_HOURS = {"chinese": 8, "japanese": 9, "korean": 9}
CALENDAR_OF_LANG = {"zh": "chinese", "ja": "japanese", "ko": "korean"}
CALENDAR_NATIVE_LANG = {cal: lang for lang, cal in CALENDAR_OF_LANG.items()}


def resolve_calendar(flag, lang):
    """The calendar the moon command should show, or None for none.

    Precedence: the --calendar flag > the `linecast calendar` setting >
    the calendar native to the UI language > none. 'none' anywhere in
    that chain stops it.
    """
    from linecast._config import saved_calendar
    choice = flag or saved_calendar() or CALENDAR_OF_LANG.get(lang)
    return None if choice in (None, "none") else choice

_MEAN_DEG_PER_DAY = 360.0 / 365.2422


def _sun_lon_deg(dt_utc):
    lon, _dist = _sun_ecliptic(dt_utc)
    return math.degrees(lon) % 360.0


def sun_crossing_utc(start_utc, target_deg, backwards=False):
    """When the Sun's ecliptic longitude reaches *target_deg*.

    The first crossing after *start_utc*, or the last before it going
    backwards. Newton's method on the mean rate: the true rate stays
    within a few percent of it, so each round shrinks the error by
    thirty-fold and five rounds land within a second.
    """
    lon = _sun_lon_deg(start_utc)
    if backwards:
        delta = -((lon - target_deg) % 360.0)
    else:
        delta = (target_deg - lon) % 360.0
    t = start_utc + timedelta(days=delta / _MEAN_DEG_PER_DAY)
    for _ in range(5):
        err = (target_deg - _sun_lon_deg(t) + 180.0) % 360.0 - 180.0
        t += timedelta(days=err / _MEAN_DEG_PER_DAY)
    return t


# Solar term k begins where the Sun's longitude crosses 15k°: k = 0 is
# the March equinox (春分), and the localized name tables share this
# indexing.

def current_term(dt_utc):
    """(term index, start instant) of the solar term in progress."""
    k = int(_sun_lon_deg(dt_utc) // 15.0) % 24
    return k, sun_crossing_utc(dt_utc, k * 15.0, backwards=True)


def next_term(dt_utc):
    """(term index, start instant) of the following solar term."""
    k = (int(_sun_lon_deg(dt_utc) // 15.0) + 1) % 24
    return k, sun_crossing_utc(dt_utc, (k * 15.0) % 360.0)


def _civil(dt_utc, tz_hours):
    """The calendar's civil date containing a UTC instant."""
    return (dt_utc + timedelta(hours=tz_hours)).date()


def _day_start_utc(day, tz_hours):
    """The UTC instant the calendar's civil *day* begins."""
    return (datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
            - timedelta(hours=tz_hours))


def _month_start(dt_utc, tz_hours):
    """The new moon starting the month whose days contain *dt_utc*'s.

    Usually the last new moon at or before the instant — but a month
    begins on the whole civil day of its new moon, so a new moon later
    on the same day claims the day, and the search looks ahead first.
    """
    ahead = next_moon_phase_utc(dt_utc, 0.0)
    if ahead is not None and _civil(ahead, tz_hours) == _civil(dt_utc, tz_hours):
        return ahead
    return next_moon_phase_utc(dt_utc, 0.0, backwards=True)


def _has_major_term(first_day, next_first_day, tz_hours):
    """Whether a major solar term falls on one of this month's days."""
    t0 = _day_start_utc(first_day, tz_hours)
    target = ((math.floor(_sun_lon_deg(t0) / 30.0) + 1) * 30.0) % 360.0
    z = sun_crossing_utc(t0, target)
    return _civil(z, tz_hours) < next_first_day


@lru_cache(maxsize=32)
def _sui_months(year, tz_hours):
    """The months of the suì anchored at *year*'s December solstice.

    ((first_day, next_first_day, number, is_leap), ...) — the month
    containing the solstice is number 11, and the days are civil dates
    at the calendar's meridian. Twelve months in an ordinary suì,
    thirteen with the leap.
    """
    ws1 = sun_crossing_utc(
        datetime(year, 12, 15, tzinfo=timezone.utc), 270.0)
    ws2 = sun_crossing_utc(ws1 + timedelta(days=180), 270.0)
    m11 = _month_start(ws1, tz_hours)
    end_day = _civil(_month_start(ws2, tz_hours), tz_hours)
    starts = [m11]
    for _ in range(14):
        nxt = next_moon_phase_utc(starts[-1] + timedelta(days=1), 0.0)
        if nxt is None or _civil(nxt, tz_hours) >= end_day:
            break
        starts.append(nxt)
    days = [_civil(s, tz_hours) for s in starts] + [end_day]
    leap_sui = len(starts) == 13
    months, num, leap_seen = [], 11, False
    for i in range(len(starts)):
        is_leap = False
        if (leap_sui and not leap_seen and i > 0
                and not _has_major_term(days[i], days[i + 1], tz_hours)):
            is_leap = leap_seen = True
        elif i > 0:
            num = num % 12 + 1
        months.append((days[i], days[i + 1], num, is_leap))
    return tuple(months)


@lru_cache(maxsize=128)
def lunisolar_date(local_date, tz_hours):
    """(month, day, is_leap) for a Gregorian date, or None.

    The mapping from Gregorian days to lunar days is fixed by the
    calendar's meridian; a user anywhere looks their own civil date up
    in it, which is what every published calendar table does.
    """
    for year in (local_date.year - 1, local_date.year):
        for first, nxt, num, leap in _sui_months(year, tz_hours):
            if first <= local_date < nxt:
                return num, (local_date - first).days + 1, leap
    return None


def next_lunar_event(local_date, tz_hours, table):
    """The next (gregorian_date, name) among lunar-dated events.

    *table* maps (month, day) to a name. Events skip leap months, as
    the festivals do, and a day-30 event skips 29-day months.
    """
    best = None
    for year in (local_date.year - 1, local_date.year, local_date.year + 1):
        for first, nxt, num, leap in _sui_months(year, tz_hours):
            if leap:
                continue
            for (month, day), name in table.items():
                if month != num or day > (nxt - first).days:
                    continue
                when = first + timedelta(days=day - 1)
                if when >= local_date and (best is None or when < best[0]):
                    best = (when, name)
    return best
