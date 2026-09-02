"""The Thai lunar calendar (ปฏิทินจันทรคติไทย), by its own arithmetic.

Unlike the calendars in _lunisolar, which follow the astronomical moon,
the Thai calendar is arithmetic: months run on the mean sun and moon of
the old Suriyayart reckoning, in which 800 solar years are exactly
292207 days. Odd months hold 29 days and even months 30; a year needing
more takes one extra day in month 7 (athikawan) or repeats the whole
eighth month (athikamat, written เดือน ๘๘), and which kind a year is
falls out of the integer bookkeeping below — the horakhun (days since
the Chulasakarat epoch), the avoman (the excess of lunar days over
solar), and the tithi (the moon's age on new year's day).

The rules are J. C. Eade's reconstruction (The Calendrical Systems of
Mainland South-East Asia), following Faraut, ported here from the
pythaidate library (Mark Hollow, MIT). The tests pin the result to the
official Thai calendar — the Buddhist holy days and festivals of
2023-2026 as Thailand published them.
"""

from datetime import timedelta
from functools import lru_cache

_ERA_DAYS = 292207        # days in 800 mean solar years
_ERA_YEARS = 800
_EPOCH_OFFSET = 373       # of the Chulasakarat epoch, in 1/800-day units
_CS_EPOCH_JDN = 1954167   # Julian day number of that epoch (638 CE)
_ORDINAL_TO_JDN = 1721425

# Buddhist Era years run 1181 ahead of Chulasakarat years.
BE_OFFSET = 1181


class _YearShape:
    """CS year *y* as seen on its solar new year's day."""

    def __init__(self, y):
        self.year = y
        units = y * _ERA_DAYS + _EPOCH_OFFSET
        self.horakhun = units // _ERA_YEARS + 1
        kammacapon = _ERA_YEARS - units % _ERA_YEARS
        avo_quot, avoman = divmod(self.horakhun * 11 + 650, 692)
        if avoman == 0:
            avoman = 692
        self.tithi = (avo_quot + self.horakhun) % 30
        if avoman == 692:
            self.tithi -= 1
        self.weekday = self.horakhun % 7

        horakhun1 = ((y + 1) * _ERA_DAYS + _EPOCH_OFFSET) // _ERA_YEARS + 1
        quot1 = (horakhun1 * 11 + 650) // 692
        tithi1 = (quot1 + horakhun1) % 30

        # Where new year's day falls relative to the lunar count (Eade
        # after Faraut), and the weekday it lands on.
        self.offset = False
        self.langsak = max(1, self.tithi)
        nyd = self.langsak
        if nyd < 6:
            nyd += 29
        self.nyd = (self.weekday - nyd + 1 + 35) % 7

        # Does the solar year take a leap day?
        self.leapday = kammacapon <= 207

        # A: 354 days; B: extra day, 355; C: extra month, 384. A raw
        # 'c' marks a leap day and leap month coinciding, resolved
        # against the neighbours in _year_shape below.
        self.cal_type = "A"
        if self.tithi > 24 or self.tithi < 6:
            self.cal_type = "C"
        if self.tithi == 25 and tithi1 == 5:
            self.cal_type = "A"
        if ((self.leapday and avoman <= 126)
                or (not self.leapday and avoman <= 137)):
            self.cal_type = "B" if self.cal_type != "C" else "c"

        step = {"A": 4, "B": 5, "C": 6, "c": 6}[self.cal_type]
        self.next_nyd = (self.nyd + step) % 7


@lru_cache(maxsize=64)
def _year_shape(year):
    """CS year *year* with its calendar type settled.

    A year cannot be read alone: a raw 'c' (leap day meeting leap
    month) moves its day to a neighbour, and the weekday chain from one
    new year to the next decides the stray offsets — so the year is
    worked out in a five-year window, as Eade's tables do.
    """
    y = [_YearShape(year + i) for i in (-2, -1, 0, 1, 2)]

    # A tithi of 24 meeting 6 makes the centre year a leap-month year.
    if y[2].tithi == 24 and y[3].tithi == 6:
        for shape in y:
            shape.cal_type = "C"
            shape.next_nyd = (shape.next_nyd + 2) % 7

    # A leap day cannot share a year with a leap month in the Thai
    # calendar (unlike the Burmese): hand the day to whichever
    # neighbour keeps the weekday chain consistent.
    for i in (1, 2, 3):
        if y[i].cal_type == "c":
            j = 1 if y[i].nyd == y[i - 1].next_nyd else -1
            y[i + j].cal_type = "B"
            y[i + j].next_nyd = (y[i + j].next_nyd + 1) % 7

    # A year adrift from both neighbours slips its new year by a day.
    for i in (1, 2, 3):
        if (y[i - 1].next_nyd != y[i].nyd
                and y[i].next_nyd != y[i + 1].nyd):
            y[i].offset = True
            y[i].langsak += 1
            y[i].nyd = (y[i].nyd + 6) % 7
            y[i].next_nyd = (y[i].next_nyd + 6) % 7

    shape = y[2]
    if shape.cal_type == "c":
        shape.cal_type = "C"

    # Days from the first of the lunar month the solar year opens in
    # (Caitra, month 5) to new year's day itself.
    shape.offset_days = shape.langsak
    if shape.offset_days < 6 + int(shape.offset):
        shape.offset_days += 29
    return shape


# Days-in-year boundaries to (position in the month chain), widest
# first; the chain runs 5..12, 1..4 within a CS year, the doubled
# eighth (88) after 8 in a C year, and 15/16 are months 5 and 6 spilling
# past a year's own count. Derived from the cumulative month lengths:
# odd months 29 days, even months 30, month 7 taking B's extra day.
_MONTH_CHAIN = (0, 5, 6, 7, 8, 9, 10, 11, 12, 1, 2, 3, 4, 8, 88, 15, 16)
_FIND_DATE = {
    "A": ((383, 16), (354, 15), (324, 12), (295, 11), (265, 10), (236, 9),
          (206, 8), (177, 7), (147, 6), (118, 5), (88, 4), (59, 3), (29, 2)),
    "B": ((384, 16), (355, 15), (325, 12), (296, 11), (266, 10), (237, 9),
          (207, 8), (178, 7), (148, 6), (119, 5), (89, 4), (59, 3), (29, 2)),
    "C": ((384, 15), (354, 12), (325, 11), (295, 10), (266, 9), (236, 8),
          (207, 7), (177, 6), (148, 5), (118, 14), (88, 13), (59, 3), (29, 2)),
}


def _find_month_day(cal_type, days):
    """(chain position, day of month) for *days* since Caitra 1st."""
    for boundary, pos in _FIND_DATE[cal_type]:
        if days > boundary:
            return pos, days - boundary
    return 1, days


@lru_cache(maxsize=512)
def _thai_date(local_date):
    """(cs_year, month, day, doubled) for a Gregorian date.

    *month* is 1-12 (the doubled eighth keeps 8, with *doubled* set),
    *day* is 1-30: 1-15 the waxing days (ขึ้น), 16 on the waning
    (แรม day - 15). The Thai calendar keeps one civil day everywhere,
    so no meridian is involved.
    """
    horakhun = local_date.toordinal() + _ORDINAL_TO_JDN - _CS_EPOCH_JDN
    year = (horakhun * _ERA_YEARS - _EPOCH_OFFSET) // _ERA_DAYS
    if horakhun % _ERA_DAYS == 95333:
        # Once in 800 years the estimate lands a year forward: the last
        # day of a solar leap year meeting a leap-month lunar year.
        year -= 1
        days = 365
    else:
        days = horakhun - _year_shape(year).horakhun
    shape = _year_shape(year)
    year_days = 365 + int(shape.leapday)
    while days > year_days:
        days -= year_days
        year += 1
        shape = _year_shape(year)
        year_days = 365 + int(shape.leapday)
    pos, day = _find_month_day(shape.cal_type, shape.offset_days + days)
    raw = _MONTH_CHAIN[pos]
    month = {88: 8, 15: 5, 16: 6}.get(raw, raw)
    return year, month, day, raw == 88


def thai_lunar_date(local_date):
    """(month, day, doubled) — see _thai_date."""
    _year, month, day, doubled = _thai_date(local_date)
    return month, day, doubled


def cs_year(local_date):
    """The Chulasakarat year the date falls in."""
    return _thai_date(local_date)[0]


def year_animal_index(local_date):
    """0-11 into the twelve-animal cycle (0 = ชวด, the rat).

    The animal follows the Chulasakarat year, turning at Songkran — the
    horoscope-calendar convention. Popular calendars that turn it on
    January 1st will disagree between New Year and mid-April.
    """
    return (cs_year(local_date) + 10) % 12


def is_wan_phra(local_date):
    """Whether the date is a Buddhist holy day (วันพระ).

    The four each month: the 8th and 15th waxing days, the 8th waning
    day, and the last day of the month — the 14th waning day of a
    29-day month, the 15th of a 30-day month.
    """
    _year, _month, day, _doubled = _thai_date(local_date)
    if day in (8, 15, 23):
        return True
    return _thai_date(local_date + timedelta(days=1))[2] == 1


def next_wan_phra(local_date):
    """The first วันพระ at or after *local_date*."""
    day = local_date
    for _ in range(9):
        if is_wan_phra(day):
            return day
        day += timedelta(days=1)
    raise AssertionError("no wan phra within nine days")


def _festival_key(local_date):
    """The lunar-dated festival falling on a date, or None.

    Day 15 is the full moon, 16 the first waning day. In a year of two
    eighth months Visakha moves from month 6 to 7 and Asalha and the
    entry to Phansa to the doubled eighth; Makha — whose months 3-4
    sit at a CS year's far end, before Songkran — defers to month 4
    when the FOLLOWING CS year is the one doubling its eighth.
    """
    if (local_date.month, local_date.day) == (4, 13):
        # The civil holiday, fixed at 13 April since 1948; the computed
        # Maha Songkran of the old solar reckoning still drifts.
        return "songkran"
    year, month, day, doubled = _thai_date(local_date)
    athikamat = _year_shape(year).cal_type == "C"
    if day == 15:
        deferred = _year_shape(year + 1).cal_type == "C"
        if month == (4 if deferred else 3):
            return "makha"
        if month == (7 if athikamat else 6):
            return "visakha"
        if month == 8 and doubled == athikamat:
            return "asalha"
        if month == 11:
            return "ok_phansa"
        if month == 12:
            return "loy_krathong"
    elif day == 16 and month == 8 and doubled == athikamat:
        return "khao_phansa"
    return None


def next_thai_festival(local_date):
    """(gregorian_date, key) of the next festival at or after the date."""
    day = local_date
    for _ in range(400):
        key = _festival_key(day)
        if key is not None:
            return day, key
        day += timedelta(days=1)
    raise AssertionError("no festival within four hundred days")
