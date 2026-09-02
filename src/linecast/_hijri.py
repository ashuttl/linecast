"""The Islamic calendar by the Umm al-Qura rule, from the ephemeris.

There is no one Islamic calendar in civil use: most countries begin
Ramadan and the Eids on a sighting of the crescent, announced the
evening before, which no program can predict. What can be computed is
the Umm al-Qura calendar, Saudi Arabia's civil calendar, whose rule
has been geometric since 1423 AH (March 2002): on the evening of a
month's 29th day at Mecca, if the geocentric conjunction has already
occurred before sunset and the Moon sets after the Sun, the next day
begins the new month; otherwise the month runs to thirty days. That
is the rule this module evaluates, from the same solar and lunar
positions the rest of the app draws with, and it is what the printed
Umm al-Qura calendar shows — R. H. van Gent's pages on the calendar
are the reference for the rule and its history.

Computed month by month from the conjunction: the new month begins
the day after the first Mecca sunset that follows the conjunction with
the Moon still above the horizon. Over the 936 months the published
tables cover, 1423–1500 AH, that gives only 29- and 30-day months, so
it is the 29th-day rule stated differently. "Still above the horizon"
is calibrated the way the Pacific calendars' visibility cutoff is: the
tables accept an evening with the Moon's geocentric altitude 0.068° at
sunset and reject one at 0.054°, so the line sits midway, at 0.061°,
and every month from 1423 to 1500 AH matches the table but one —
Jumada al-Thani 1427 (June 2006), where the conjunction fell five
minutes before sunset by this ephemeris and after it by the table's.

Before 1423 AH the calendar was regulated differently, and dates fall
back to the tabular Islamic calendar, the 30-year arithmetic cycle of
eleven leap years; 1 Muharram 1423 falls on the same day in both, so
the two join without a seam.

The Hijri day begins at sunset. The panel turns the date with the
reader's own sunset (after_sunset below); the month grid and the
observance dates keep civil days, the way printed calendars do.
Saudi Arabia's religious authorities adjust the announced dates of
Ramadan, Shawwal, and Dhu al-Hijjah after reported sightings, so a
country's announced dates may differ from these by a day.
"""

from datetime import date, datetime, timedelta, timezone
from functools import lru_cache

from linecast._ephemeris import _moon_altitude_deg, next_moon_phase_utc
from linecast._pacific import _Observer, _setting_instant, _sun_alt_az_deg

_SYNODIC_DAYS = 29.530589
# The Great Mosque, Mecca; UTC+3 is Saudi Arabia's one time zone.
_MECCA = _Observer(21.4225, 39.8262, 3, 0.0)
_MOON_UP_DEG = 0.061          # calibrated; see the module docstring
_SUNSET_DEG = -0.833          # the upper limb, refracted

RULE_EPOCH = date(2002, 3, 15)     # 1 Muharram 1423, the rule's first day
_EPOCH_YEAR = 1423
_TABULAR_EPOCH_JDN = 1948440       # 1 Muharram 1 AH, Friday 16 July 622
_ORDINAL_TO_JDN = 1721425

# The observances the panel counts down to, (month, day) → key. Laylat
# al-Qadr is a night, kept by convention on the 27th of Ramadan; the
# night itself begins at sunset the evening before its civil date.
OBSERVANCES = {
    (1, 1): "new_year",
    (1, 10): "ashura",
    (3, 12): "mawlid",
    (9, 1): "ramadan",
    (9, 27): "qadr",
    (10, 1): "eid_fitr",
    (12, 9): "arafah",
    (12, 10): "eid_adha",
}


def _sunset_utc(day):
    """Sunset at Mecca on a civil *day*, in UTC."""
    # 12:00 UTC is mid-afternoon in Mecca; the Sun is down by 18:00 UTC
    # in every season.
    noon = datetime(day.year, day.month, day.day, 12, tzinfo=timezone.utc)
    return _setting_instant(noon, noon + timedelta(hours=6),
                            lambda t: _sun_alt_az_deg(t, _MECCA)[0],
                            _SUNSET_DEG)


def _tabular_start(k):
    """The first day of month *k* by the tabular calendar."""
    year, month = _EPOCH_YEAR + k // 12, k % 12 + 1
    jdn = (_TABULAR_EPOCH_JDN - 1 + (year - 1) * 354 + (11 * year + 3) // 30
           + 29 * (month - 1) + month // 2 + 1)
    return date.fromordinal(jdn - _ORDINAL_TO_JDN)


@lru_cache(maxsize=1)
def _epoch_conjunction():
    return next_moon_phase_utc(
        datetime(RULE_EPOCH.year, RULE_EPOCH.month, RULE_EPOCH.day,
                 tzinfo=timezone.utc), 0.0, backwards=True)


@lru_cache(maxsize=None)
def _month_start(k):
    """The civil date beginning month *k*, counted from Muharram 1423."""
    if k < 0:
        return _tabular_start(k)
    guess = _epoch_conjunction() + timedelta(days=k * _SYNODIC_DAYS - 2)
    conj = next_moon_phase_utc(guess, 0.0)
    day = (conj + timedelta(hours=_MECCA.meridian_hours)).date()
    for _ in range(3):
        sunset = _sunset_utc(day)
        if (sunset > conj
                and _moon_altitude_deg(sunset, _MECCA.lat, _MECCA.lng)
                > _MOON_UP_DEG):
            return day + timedelta(days=1)
        day += timedelta(days=1)
    return day        # three evenings on is beyond doubt


@lru_cache(maxsize=512)
def _month_index(local_date):
    k = int((local_date - RULE_EPOCH).days // _SYNODIC_DAYS)
    while _month_start(k + 1) <= local_date:
        k += 1
    while _month_start(k) > local_date:
        k -= 1
    return k


def hijri_date(local_date):
    """(year, month, day) of the Hijri date whose daylight is *local_date*."""
    k = _month_index(local_date)
    return (_EPOCH_YEAR + k // 12, k % 12 + 1,
            (local_date - _month_start(k)).days + 1)


def month_start(year, month):
    """The civil date of 1 *month* *year* AH."""
    return _month_start((year - _EPOCH_YEAR) * 12 + month - 1)


def days_in_month(local_date):
    """How many days the Hijri month containing *local_date* runs."""
    k = _month_index(local_date)
    return (_month_start(k + 1) - _month_start(k)).days


def next_month_start(local_date):
    """(civil date, (year, month)) of the Hijri month after *local_date*'s."""
    k = _month_index(local_date) + 1
    return _month_start(k), (_EPOCH_YEAR + k // 12, k % 12 + 1)


def observance_key(local_date):
    """The observance falling on *local_date*, or None."""
    _year, month, day = hijri_date(local_date)
    return OBSERVANCES.get((month, day))


def next_observance(local_date):
    """(civil date, key) of the first observance at or after *local_date*."""
    k = _month_index(local_date)
    for kk in range(k, k + 13):
        month, start = kk % 12 + 1, _month_start(kk)
        for (o_month, o_day), key in sorted(OBSERVANCES.items()):
            day = start + timedelta(days=o_day - 1)
            if o_month == month and day >= local_date:
                return day, key
    raise AssertionError("no observance within thirteen months")


def after_sunset(now_local, lat, lng):
    """Whether the Hijri day has turned at the reader's place.

    The day begins at sunset, so an evening reader is already in the
    next one: the Sun is down and it is evening rather than the small
    hours. Where the Sun does not set the day keeps to the civil date.
    """
    if lat is None or lng is None:
        return False
    obs = _Observer(lat, lng, 0, 0.0)
    alt = _sun_alt_az_deg(now_local.astimezone(timezone.utc), obs)[0]
    return alt < _SUNSET_DEG and now_local.hour >= 12
