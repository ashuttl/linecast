"""The halachic hours: the zmanim, by the Gr"a and the Magen Avraham.

An hour in halacha is a twelfth of the day, a sha'ah zmanit, and the
day is measured two ways. The Gr"a (the Vilna Gaon) counts sunrise to
sunset. The Magen Avraham counts alot hashachar to tzeit hakochavim,
dawn to nightfall, and the common reckoning of those is seventy-two
minutes before sunrise and after sunset, the time to walk four mil.
The night is divided into twelve the same way, sunset to sunrise.

The marks are fractions of that day. The latest Shema is three hours
in, the latest Tefillah four, chatzot six, mincha gedola six and a
half, mincha ketana nine and a half, plag hamincha ten and three
quarters. Around them sit the moments read off the Sun's depression:
alot hashachar at 16.1°, misheyakir at 11.5°, tzeit at 8.5° (three
small stars), and candle lighting eighteen minutes before sunset on
Friday, forty in Jerusalem, whose custom it is and which Hebcal keeps
for the city. Chatzot halayla is the middle of the night. The angles are the
ones Hebcal and the KosherJava library publish, and the tests pin four
places and four dates against Hebcal's zmanim API to the minute.

Sea-level sunrise and sunset throughout, as the published tables
keep them; the Hijri module uses the same horizon at Mecca.
"""

from datetime import timedelta
from functools import lru_cache

from linecast.astro.ephemeris import sun_depression_utc
from linecast.astro.hours import DayHours, Mark, elapsed, shift, utc

OPINIONS = ("gra", "mga")
OPINION_NAMES = {"gra": "Gr\"a", "mga": "Magen Avraham"}

HORIZON_DEG = 0.833       # the upper limb, refracted
ALOT_DEG = 16.1
MISHEYAKIR_DEG = 11.5
TZEIT_DEG = 8.5
MGA_MINUTES = 72
CANDLES_MINUTES = 18
CANDLES_MINUTES_JERUSALEM = 40
# The city: its centre, and a radius that takes in the municipality
# and no neighbour that keeps eighteen.
_JERUSALEM = (31.778, 35.225)
_JERUSALEM_KM = 12.0
FRIDAY = 4

# The marks that are fractions of the day, in sha'ot zmaniyot from its
# start, in order.
_DAY_FRACTIONS = (
    ("shema", 3.0),
    ("tefillah", 4.0),
    ("chatzot", 6.0),
    ("mincha_gedola", 6.5),
    ("mincha_ketana", 9.5),
    ("plag", 10.75),
)


def candles_minutes(lat, lng):
    """Minutes before sunset the candles are lit: eighteen, or forty
    in Jerusalem."""
    from math import cos, radians
    dlat = (lat - _JERUSALEM[0]) * 111.2
    dlng = (lng - _JERUSALEM[1]) * 111.2 * cos(radians(_JERUSALEM[0]))
    return (CANDLES_MINUTES_JERUSALEM if dlat * dlat + dlng * dlng <= _JERUSALEM_KM ** 2
            else CANDLES_MINUTES)


def _local(dt_utc, tzinfo):
    if dt_utc is None:
        return None
    return dt_utc.astimezone(tzinfo) if tzinfo else dt_utc.astimezone()


def _edges(local_date, lat, lng, tzinfo, opinion):
    """(day_start, day_end) for the opinion, either None."""
    rise = _local(sun_depression_utc(local_date, lat, lng, HORIZON_DEG, False, tzinfo), tzinfo)
    set_ = _local(sun_depression_utc(local_date, lat, lng, HORIZON_DEG, True, tzinfo), tzinfo)
    if opinion == "mga":
        pad = timedelta(minutes=MGA_MINUTES)
        return (shift(rise, -pad) if rise else None), (shift(set_, pad) if set_ else None)
    return rise, set_


@lru_cache(maxsize=64)
def zmanim(local_date, lat, lng, tzinfo=None, opinion=None):
    """The day's zmanim at a place, by *opinion* ('gra' by default)."""
    opinion = opinion if opinion in OPINIONS else "gra"
    day = timedelta(days=1)
    start, end = _edges(local_date, lat, lng, tzinfo, opinion)
    _prev_start, prev_end = _edges(local_date - day, lat, lng, tzinfo, opinion)
    next_start, _next_end = _edges(local_date + day, lat, lng, tzinfo, opinion)

    def depression(deg, evening):
        return _local(sun_depression_utc(local_date, lat, lng, deg, evening, tzinfo), tzinfo)

    marks = []

    def add(key, at):
        if at is not None:
            marks.append(Mark(key, at))

    # The night before ends on this civil date when its middle falls
    # after midnight, which is most places; the night after, when the
    # zone runs ahead of its meridian. Each is listed on the date it
    # falls on. By the Magen Avraham a short polar night can be eaten
    # by the padding, dawn before the last dusk; that night has no
    # middle.
    if prev_end and start and utc(prev_end) < utc(start):
        add("chatzot_halayla", shift(prev_end, elapsed(prev_end, start) / 2))
    sunrise = depression(HORIZON_DEG, False)
    sunset = depression(HORIZON_DEG, True)
    add("alot", start if opinion == "mga" else depression(ALOT_DEG, False))
    add("misheyakir", depression(MISHEYAKIR_DEG, False))
    add("sunrise", sunrise)
    if start and end:
        hour = elapsed(start, end) / 12
        for key, n in _DAY_FRACTIONS:
            add(key, shift(start, hour * n))
    if sunset and local_date.weekday() == FRIDAY:
        add("candles", shift(sunset, -timedelta(minutes=candles_minutes(lat, lng))))
    add("sunset", sunset)
    add("tzeit", end if opinion == "mga" else depression(TZEIT_DEG, True))
    if end and next_start and utc(end) < utc(next_start):
        add("chatzot_halayla", shift(end, elapsed(end, next_start) / 2))
    marks.sort(key=lambda m: m.at)
    marks = [m for m in marks
             if m.key != "chatzot_halayla" or m.at.date() == local_date]

    return DayHours("halachic", local_date, start, end, prev_end, next_start,
                    12, marks, opinion)
