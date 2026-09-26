"""Swahili time, saa za Kiswahili: twelve hours of day and twelve of night.

Swahili counts the hours of the day from its start and the hours of
the night from theirs. Seven in the morning is saa moja asubuhi, the
first hour of the day, and seven in the evening saa moja usiku, the
first of the night; noon and midnight are saa sita, the sixth. It is
how the time is told in Swahili now, in speech and in print: the
newspapers write "saa 4:00 asubuhi" for ten in the morning.

The count began at sunrise, and near the equator sunrise hardly moves:
in Dar es Salaam, Mombasa, and Nairobi it comes between about 05:55
and 06:45 all year. So the day's edges are the clock's six o'clock, as
everyone who keeps Swahili time keeps them, not the Sun's, and each
hour is an hour of the clock. The reading follows the wall clock of
the place shown, so a clock change moves it as it moves the digits.

`--json` also carries the time as it is said, in words: "saa kumi na
moja na dakika kumi na tatu alfajiri" for 05:13, with robo and nusu for
the quarter and the half, and kasoro robo, a quarter short of the next
hour, for the three-quarter.

The word after the hour says which part of the day it is, and the
parts are the ones CLDR records for Swahili and the textbooks teach:
alfajiri from four to seven in the morning, asubuhi to noon, mchana
to four, jioni to seven, and usiku through the night. The written form
is the newspapers': the Swahili hour, the minutes in two digits, and
the part of the day.
"""

from datetime import datetime, time, timedelta

from linecast.astro.hours import DayHours

# (from hour, name), in order through the civil day: CLDR's dayPeriods
# for sw, which the University of Kansas lesson on saa agrees with hour
# for hour.
PERIODS = ((0, "usiku"), (4, "alfajiri"), (7, "asubuhi"),
           (12, "mchana"), (16, "jioni"), (19, "usiku"))


def _at(local_date, hour, tzinfo):
    dt = datetime.combine(local_date, time(hour))
    return dt.replace(tzinfo=tzinfo) if tzinfo else dt.astimezone()


def swahili_hours(local_date, tzinfo=None):
    """The day from six in the morning to six in the evening, on the
    clock, twelve hours each way. There are no marks: the hours are
    the clock's own, and the line above has sunrise and sunset."""
    day = timedelta(days=1)
    return DayHours("swahili", local_date,
                    _at(local_date, 6, tzinfo), _at(local_date, 18, tzinfo),
                    _at(local_date - day, 18, tzinfo), _at(local_date + day, 6, tzinfo),
                    12, [], None, wall_clock=True)


# The numbers as they are said, one to fifty-nine. Saa and dakika are
# both nouns of the n-class, whose numbers are the counting forms.
_ONES = ("", "moja", "mbili", "tatu", "nne", "tano", "sita", "saba", "nane", "tisa")
_TENS = ("", "kumi", "ishirini", "thelathini", "arobaini", "hamsini")


def number(n):
    """'kumi na moja' for 11, 'arobaini na tano' for 45."""
    tens, ones = divmod(n, 10)
    if not tens:
        return _ONES[ones]
    if not ones:
        return _TENS[tens]
    return f"{_TENS[tens]} na {_ONES[ones]}"


def _hour(civil_hour):
    return (civil_hour - 6) % 12 or 12


def moment(r):
    """The wall-clock time a reading of Swahili time was taken at."""
    return r.start + timedelta(hours=r.fraction)


def period(hour):
    """The part of the day a civil hour falls in: 'asubuhi' at nine."""
    name = PERIODS[0][1]
    for start, word in PERIODS:
        if hour >= start:
            name = word
    return name


def saa(local):
    """A local wall-clock time in Swahili time: 'saa 7:13 usiku' at
    01:13, 'saa 12:14 alfajiri' at 06:14, 'saa 6:00 mchana' at noon."""
    return f"saa {_hour(local.hour)}:{local.minute:02d} {period(local.hour)}"


def spoken(local):
    """The time as it is said: 'saa tisa usiku' at 03:00, 'saa nne na
    robo asubuhi' at 10:15, 'saa kumi na mbili na nusu jioni' at 18:30,
    'saa sita kasoro robo asubuhi' at 11:45, and 'saa saba na dakika
    kumi na tatu usiku' at 01:13. The part of the day is the moment's
    own, so 18:45 is saa moja kasoro robo jioni."""
    hour, minute = _hour(local.hour), local.minute
    if minute == 0:
        said = f"saa {number(hour)}"
    elif minute == 15:
        said = f"saa {number(hour)} na robo"
    elif minute == 30:
        said = f"saa {number(hour)} na nusu"
    elif minute == 45:
        said = f"saa {number(hour % 12 + 1)} kasoro robo"
    else:
        said = f"saa {number(hour)} na dakika {number(minute)}"
    return f"{said} {period(local.hour)}"
