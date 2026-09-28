"""The old Icelandic calendar against the almanac and Janson.

The ground truth is the University of Iceland's almanac (Almanak
Háskóla Íslands): the dates it lists for 2024 through 2027, and its
glossary (almanak.hi.is/rim.html), which gives each month's weekday,
week, and range of dates, and the rules for the leap week and the
rímspillir. The University's Science Web (Vísindavefurinn) names the
last and next leap weeks and rímspillir years. Svante Janson's "The
Icelandic calendar" (2010) tabulates every year's month starts in
28 lines (table 7), and lists the rímspillir years since 1700.

The named moons are checked against Þorsteinn Sæmundsson's "Þorratungl
og páskatungl" (Almanak Þjóðvinafélagsins 1978, almanak.hi.is/thorra.html),
which lists every year from 1878 to 2000 in which the old rhyme about
the þorratungl fails, and against the new moons the almanac's readers
have dated.
"""

import re
from datetime import date, datetime, timedelta, timezone

import pytest

from linecast.astro.calendars.icelandic import (
    NAMED_DAYS,
    SUMMER,
    WINTER,
    _epact,
    _tables_epiphany_moon,
    easter,
    first_day_of_summer,
    first_day_of_winter,
    has_sumarauki,
    icelandic_week,
    lit_moon_key,
    month_key,
    month_starts,
    moon_key,
    named_day_key,
    named_moons,
    next_month_start,
    next_named_day,
    next_named_moon,
)

MON, TUE, WED, THU, FRI, SAT, SUN = range(7)

# From "Dagsetningar á næstu árum" in the Almanak Háskólans 2023.
PUBLISHED = {
    2024: {"bondadagur": date(2024, 1, 26),
           "sumardagurinn_fyrsti": date(2024, 4, 25),
           "fyrsti_vetrardagur": date(2024, 10, 26)},
    2025: {"bondadagur": date(2025, 1, 24),
           "sumardagurinn_fyrsti": date(2025, 4, 24),
           "fyrsti_vetrardagur": date(2025, 10, 25)},
    2026: {"bondadagur": date(2026, 1, 23),
           "sumardagurinn_fyrsti": date(2026, 4, 23),
           "fyrsti_vetrardagur": date(2026, 10, 24)},
    2027: {"bondadagur": date(2027, 1, 22),
           "sumardagurinn_fyrsti": date(2027, 4, 22),
           "fyrsti_vetrardagur": date(2027, 10, 23)},
}

# Janson's table 7: the day each month begins, one line per place in
# the 28-year pattern, Harpa to Haustmánuður in April to September,
# Gormánuður to Mörsugur in October to December, and Þorri to
# Einmánuður in January to March of the next year.
_MONTHS = ("harpa", "skerpla", "solmanudur", "heyannir", "tvimanudur",
           "haustmanudur", "gormanudur", "ylir", "morsugur", "thorri",
           "goa", "einmanudur")
_CIVIL_MONTHS = (4, 5, 6, 7, 8, 9, 10, 11, 12, 1, 2, 3)
JANSON_TABLE_7 = (
    (25, 25, 24, 28, 27, 26, 26, 25, 25, 24, 23, 25),
    (24, 24, 23, 27, 26, 25, 25, 24, 24, 23, 22, 24),
    (23, 23, 22, 26, 25, 24, 24, 23, 23, 22, 21, 23),
    (22, 22, 21, 25, 24, 23, 23, 22, 22, 21, 20, 21),
    (20, 20, 19, 23, 22, 21, 21, 20, 20, 19, 18, 20),
    (19, 19, 18, 29, 28, 27, 27, 26, 26, 25, 24, 26),
    (25, 25, 24, 28, 27, 26, 26, 25, 25, 24, 23, 25),
    (24, 24, 23, 27, 26, 25, 25, 24, 24, 23, 22, 23),
    (22, 22, 21, 25, 24, 23, 23, 22, 22, 21, 20, 22),
    (21, 21, 20, 24, 23, 22, 22, 21, 21, 20, 19, 21),
    (20, 20, 19, 23, 22, 21, 21, 20, 20, 19, 18, 20),
    (19, 19, 18, 29, 28, 27, 27, 26, 26, 25, 24, 25),
    (24, 24, 23, 27, 26, 25, 25, 24, 24, 23, 22, 24),
    (23, 23, 22, 26, 25, 24, 24, 23, 23, 22, 21, 23),
    (22, 22, 21, 25, 24, 23, 23, 22, 22, 21, 20, 22),
    (21, 21, 20, 24, 23, 22, 22, 21, 21, 20, 19, 20),
    (19, 19, 18, 29, 28, 27, 27, 26, 26, 25, 24, 26),
    (25, 25, 24, 28, 27, 26, 26, 25, 25, 24, 23, 25),
    (24, 24, 23, 27, 26, 25, 25, 24, 24, 23, 22, 24),
    (23, 23, 22, 26, 25, 24, 24, 23, 23, 22, 21, 22),
    (21, 21, 20, 24, 23, 22, 22, 21, 21, 20, 19, 21),
    (20, 20, 19, 23, 22, 21, 21, 20, 20, 19, 18, 20),
    (19, 19, 18, 29, 28, 27, 27, 26, 26, 25, 24, 26),
    (25, 25, 24, 28, 27, 26, 26, 25, 25, 24, 23, 24),
    (23, 23, 22, 26, 25, 24, 24, 23, 23, 22, 21, 23),
    (22, 22, 21, 25, 24, 23, 23, 22, 22, 21, 20, 22),
    (21, 21, 20, 24, 23, 22, 22, 21, 21, 20, 19, 21),
    (20, 20, 19, 30, 29, 28, 28, 27, 27, 26, 25, 26),
)
# The lines with the leap week, marked * in the table.
JANSON_LEAP_LINES = {6, 12, 17, 23, 28}

# Janson's years in which a rímspillir begins, 1700–2100.
JANSON_RIMSPILLIR = (1719, 1747, 1775, 1815, 1843, 1871, 1911, 1939,
                     1967, 1995, 2023, 2051, 2079)

# The almanac glossary: each month's weekday, its week in the misseri
# (the second number in a year with the leap week), and its range of
# dates — the range's last day only after a rímspillir.
GLOSSARY = {
    "harpa": (THU, SUMMER, 1, 1, (4, 19), (4, 25)),
    "skerpla": (SAT, SUMMER, 5, 5, (5, 19), (5, 25)),
    "solmanudur": (MON, SUMMER, 9, 9, (6, 18), (6, 24)),
    "aukanaetur": (WED, SUMMER, 13, 13, (7, 18), (7, 24)),
    "heyannir": (SUN, SUMMER, 14, 15, (7, 23), (7, 30)),
    "tvimanudur": (TUE, SUMMER, 18, 19, (8, 22), (8, 29)),
    "haustmanudur": (THU, SUMMER, 23, 24, (9, 21), (9, 28)),
    "gormanudur": (SAT, WINTER, 1, 1, (10, 21), (10, 28)),
    "ylir": (MON, WINTER, 5, 5, (11, 20), (11, 27)),
    "morsugur": (WED, WINTER, 9, 9, (12, 20), (12, 27)),
    "thorri": (FRI, WINTER, 13, 13, (1, 19), (1, 26)),
    "goa": (SUN, WINTER, 18, 18, (2, 18), (2, 25)),
    "einmanudur": (TUE, WINTER, 22, 22, (3, 20), (3, 26)),
}

MODERN_YEARS = range(1929, 2400)


def _is_leap(year):
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def _rimspillir(year):
    """The glossary's test: the year begins on a Sunday, and the next
    is a leap year."""
    return date(year, 1, 1).weekday() == SUN and _is_leap(year + 1)


class TestPublished:
    @pytest.mark.parametrize("year", sorted(PUBLISHED))
    def test_the_almanacs_dates(self, year):
        days = PUBLISHED[year]
        assert first_day_of_summer(year) == days["sumardagurinn_fyrsti"]
        assert first_day_of_winter(year) == days["fyrsti_vetrardagur"]
        assert dict(month_starts(year - 1))["thorri"] == days["bondadagur"]
        for key, day in days.items():
            assert named_day_key(day) == key

    def test_the_science_webs_leap_weeks(self):
        # "Sumarauka var síðast skotið inn árið 2023 og verður næst
        # gert árið 2029."
        assert [y for y in range(2019, 2035) if has_sumarauki(y)] == [
            2023, 2029]

    @pytest.mark.parametrize("year", [1995, 2023])
    def test_the_science_webs_rimspillir_years(self, year):
        # Góa on 25 February, miðsumar on 30 July, Haustmánuður on
        # 28 September.
        starts = dict(month_starts(year))
        assert starts["heyannir"] == date(year, 7, 30)
        assert starts["haustmanudur"] == date(year, 9, 28)
        assert starts["goa"] == date(year + 1, 2, 25)

    def test_jansons_own_dateline(self):
        # "24 November 2009; Tuesday, 5th week of winter; 2nd day of Ýlir"
        day = date(2009, 11, 24)
        assert day.weekday() == TUE
        assert icelandic_week(day) == (WINTER, 5)
        assert month_key(day) == "ylir"
        assert dict(month_starts(2009))["ylir"] == day - timedelta(days=1)


class TestJansonTable:
    # The lines run on unbroken from 1900 to 2099, but 2099's winter
    # months belong to no line: its line reckons a leap day in 2100,
    # which has none, and the table starts over at 2100 (Janson puts
    # it on line 9).
    @pytest.mark.parametrize("year", range(1929, 2099))
    def test_every_year_to_2098(self, year):
        line = (year - 1900 + 16) % 28 + 1
        row = JANSON_TABLE_7[line - 1]
        starts = dict(month_starts(year))
        for key, civil_month, day in zip(_MONTHS, _CIVIL_MONTHS, row):
            civil_year = year + 1 if civil_month < 4 else year
            assert starts[key] == date(civil_year, civil_month, day), key
        assert has_sumarauki(year) == (line in JANSON_LEAP_LINES)

    def test_the_rimspillir_years(self):
        found = [y for y in range(1700, 2101) if _rimspillir(y)]
        assert tuple(found) == JANSON_RIMSPILLIR


class TestGlossary:
    @pytest.mark.parametrize("key", sorted(GLOSSARY))
    def test_each_months_weekday_week_and_dates(self, key):
        weekday, misseri, week, leap_week, first, last = GLOSSARY[key]
        for year in MODERN_YEARS:
            start = dict(month_starts(year))[key]
            leap = has_sumarauki(year)
            assert start.weekday() == weekday
            assert icelandic_week(start) == (
                misseri, leap_week if leap else week)
            lo = date(start.year, *first)
            hi = date(start.year, *last)
            assert lo <= start <= hi
            # From midsummer to Góa the range runs eight days, and its
            # last is the rímspillir's alone. The other months' ranges
            # run seven.
            if (hi - lo).days == 7:
                assert (start == hi) == _rimspillir(year), (key, year)

    def test_the_first_day_of_winter(self):
        for year in MODERN_YEARS:
            winter = first_day_of_winter(year)
            assert winter.weekday() == SAT
            assert date(year, 10, 21) <= winter <= date(year, 10, 28)
            weeks = 27 if has_sumarauki(year) else 26
            assert winter == first_day_of_summer(year) + timedelta(
                days=7 * weeks + 2)

    def test_the_leap_week_rule(self):
        # "Sumaraukaár verða öll ár sem enda á mánudegi, svo og ár sem
        # enda á sunnudegi ef hlaupár fer í hönd."
        for year in MODERN_YEARS:
            ends = date(year, 12, 31).weekday()
            expected = ends == MON or (ends == SUN and _is_leap(year + 1))
            assert has_sumarauki(year) == expected, year

    def test_the_leap_week_begins(self):
        # "Sumarauki hefst alltaf 22. júlí ef sá dagur er sunnudagur,
        # en 23. júlí ef sá dagur er sunnudagur og hlaupár fer í hönd."
        for year in MODERN_YEARS:
            if not has_sumarauki(year):
                continue
            start = dict(month_starts(year))["sumarauki"]
            assert start.weekday() == SUN
            if date(year, 7, 22).weekday() == SUN:
                assert start == date(year, 7, 22)
            else:
                assert start == date(year, 7, 23)
                assert _is_leap(year + 1) and _rimspillir(year)

    def test_bondadagur_and_konudagur(self):
        for year in MODERN_YEARS:
            starts = dict(month_starts(year))
            assert named_day_key(starts["thorri"]) == "bondadagur"
            assert named_day_key(starts["goa"]) == "konudagur"
            assert date(year + 1, 1, 19) <= starts["thorri"] <= date(year + 1, 1, 26)
            assert date(year + 1, 2, 18) <= starts["goa"] <= date(year + 1, 2, 25)

    def test_the_named_spans(self):
        # Fardagar: the first four days of the 7th week of summer.
        # Veturnætur: the Thursday and Friday after the 26th (27th)
        # week of summer. Sumarmál: Saturday to Wednesday in the 26th
        # week of winter. The þrælar: the last days of Þorri and Góa.
        for year in (2023, 2026, 2029):
            spans = {key: (first, last)
                     for first, last, key in _spans(year)}
            first, last = spans["fardagar"]
            assert icelandic_week(first) == (SUMMER, 7)
            assert (first.weekday(), (last - first).days) == (THU, 3)
            first, last = spans["veturnaetur"]
            assert (first.weekday(), last.weekday()) == (THU, FRI)
            assert last + timedelta(days=1) == first_day_of_winter(year)
            assert icelandic_week(first) == (SUMMER, None)
            first, last = spans["sumarmal"]
            assert icelandic_week(first) == (WINTER, 26)
            assert (first.weekday(), last.weekday()) == (SAT, WED)
            assert last + timedelta(days=1) == first_day_of_summer(year + 1)
            starts = dict(month_starts(year))
            assert spans["thorrathraell"][0] == starts["goa"] - timedelta(days=1)
            assert spans["thorrathraell"][0].weekday() == SAT
            assert spans["gouthraell"][0] == starts["einmanudur"] - timedelta(days=1)
            assert spans["gouthraell"][0].weekday() == MON
            assert spans["midsumar"][0] == starts["heyannir"]


def _spans(year):
    from linecast.astro.calendars.icelandic import _named_days_of_year
    return _named_days_of_year(year)


class TestCycle:
    def test_71_leap_weeks_in_400_years(self):
        assert sum(has_sumarauki(y) for y in range(2000, 2400)) == 71

    def test_the_gaps(self):
        years = [y for y in range(1929, 2400) if has_sumarauki(y)]
        gaps = [b - a for a, b in zip(years, years[1:])]
        assert set(gaps) == {5, 6, 7}
        assert [a for a, b in zip(years, years[1:]) if b - a == 7] == [2096]


class TestDates:
    def test_every_day_has_one_month_and_a_contiguous_week(self):
        day = date(1929, 4, 25)
        prev = icelandic_week(day)
        while day < date(2101, 1, 1):
            day += timedelta(days=1)
            misseri, week = icelandic_week(day)
            assert month_key(day) is not None
            if week is not None and prev[1] is not None and misseri == prev[0]:
                assert week - prev[1] == (1 if day.weekday() == (
                    THU if misseri == SUMMER else SAT) else 0)
            prev = (misseri, week)

    def test_the_summer_weeks(self):
        for year in (2026, 2029):
            last = first_day_of_winter(year) - timedelta(days=3)
            assert icelandic_week(last) == (
                SUMMER, 27 if has_sumarauki(year) else 26)

    def test_months_follow_each_other(self):
        for year in (1928, 2023, 2026):
            starts = month_starts(year)
            for (key, start), (nxt_key, nxt) in zip(starts, starts[1:]):
                assert month_key(nxt - timedelta(days=1)) == key
                assert next_month_start(start) == (nxt, nxt_key)

    def test_next_month_across_the_year(self):
        day = date(2027, 4, 20)
        assert month_key(day) == "einmanudur"
        assert next_month_start(day) == (date(2027, 4, 22), "harpa")

    def test_a_named_day_in_progress_is_the_next(self):
        assert next_named_day(date(2026, 10, 23)) == (
            date(2026, 10, 22), "veturnaetur")
        assert next_named_day(date(2026, 10, 24)) == (
            date(2026, 10, 24), "fyrsti_vetrardagur")
        assert next_named_day(date(2026, 10, 25)) == (
            date(2027, 1, 22), "bondadagur")

    def test_named_days_across_the_year(self):
        assert next_named_day(date(2027, 4, 15)) == (
            date(2027, 4, 17), "sumarmal")
        assert next_named_day(date(2027, 4, 21)) == (
            date(2027, 4, 17), "sumarmal")
        assert next_named_day(date(2027, 4, 22)) == (
            date(2027, 4, 22), "sumardagurinn_fyrsti")


class TestBefore1929:
    """Until 1928 the printed almanacs put the leap week at the end of
    summer, which moved Heyannir, Tvímánuður, and Haustmánuður a week
    earlier (22–28 July, 21–27 August, 20–26 September)."""

    def test_the_leap_week_comes_last(self):
        years = [y for y in range(1901, 1929) if has_sumarauki(y)]
        assert years
        for year in years:
            starts = dict(month_starts(year))
            assert date(year, 7, 22) <= starts["heyannir"] <= date(year, 7, 28)
            assert date(year, 8, 21) <= starts["tvimanudur"] <= date(year, 8, 27)
            assert date(year, 9, 20) <= starts["haustmanudur"] <= date(year, 9, 26)
            assert starts["sumarauki"] == first_day_of_winter(year) - timedelta(days=7)

    def test_the_weeks_are_unchanged(self):
        for year in range(1901, 1929):
            assert first_day_of_winter(year).weekday() == SAT
            assert icelandic_week(first_day_of_winter(year)) == (WINTER, 1)


class TestNames:
    def test_every_month_named_day_and_moon_has_a_name(self):
        from linecast.moon.i18n import (
            icelandic_day_name, icelandic_month_name, icelandic_moon_name,
        )
        for key, _start in month_starts(2023):
            assert icelandic_month_name(key)
        for key, *_rest in NAMED_DAYS:
            assert icelandic_day_name(key)
        for _new_moon, key in named_moons(2019):
            assert icelandic_moon_name(key)


def _moons(year):
    return {key: new_moon for new_moon, key in named_moons(year)}


def _almanac_clock(moment):
    """*moment* as the almanac of its day kept time: Reykjavík mean time
    until 1907, Icelandic mean time (an hour behind Greenwich) until
    1968, and Greenwich since."""
    if moment.year < 1908:
        return moment - timedelta(hours=1, minutes=27, seconds=43)
    if moment.year < 1969:
        return moment - timedelta(hours=1)
    return moment


def _anonymous_easter(year):
    """The anonymous Gregorian computus (Meeus, Astronomical Algorithms,
    chapter 8), to check easter() by other arithmetic."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    ell = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * ell) // 451
    month, day = divmod(h + ell - 7 * m + 114, 31)
    return date(year, month, day + 1)


class TestMoons:
    """Þá þorratunglið tínætt er / tel ég það lítinn háska: / næsta
    sunnudag nefna ber / níu vikur til páska. When the þorratungl is ten
    nights old, the next Sunday is nine weeks before Easter; Sæmundsson
    counts the ten nights as ten days from the new moon the almanac
    prints. The rhyme holds for the church's tables, which it was made
    from, but the true moon runs ahead of them, and Sæmundsson lists
    the years it fails: in all of them the ten nights end on the 11th
    Saturday before Easter, but for 1896 and 1994, when they end on the
    11th Friday."""

    RHYME_FAILS = {1879: SAT, 1896: FRI, 1899: SAT, 1906: SAT, 1930: SAT,
                   1933: SAT, 1950: SAT, 1957: SAT, 1970: SAT, 1974: SAT,
                   1977: SAT, 1984: SAT, 1994: FRI}

    def test_the_rhyme_fails_when_saemundsson_says(self):
        fails = {}
        for year in range(1878, 2001):
            lit = _almanac_clock(_moons(year)["thorratungl"]).date()
            tenth = lit + timedelta(days=10)
            sunday = tenth + timedelta(days=(SUN - tenth.weekday()) % 7 or 7)
            if (easter(year) - sunday).days != 63:
                fails[year] = tenth.weekday()
                assert (easter(year) - tenth).days == 71 + (tenth.weekday() == FRI)
        assert fails == self.RHYME_FAILS

    def test_the_new_moons_saemundsson_dates(self):
        # 1977's þorratungl on 19 January; 1889's on the 31st, which
        # the almanac misprinted as the 30th.
        assert _moons(1977)["thorratungl"].date() == date(1977, 1, 19)
        assert (_almanac_clock(_moons(1889)["thorratungl"]).date()
                == date(1889, 1, 31))

    def test_his_tables_for_1978(self):
        # The epact is 21, the tables' paschal moon full on 23 March,
        # and their þorratungl new on 10 January, ten nights old on the
        # 19th.
        assert _epact(1978) == 21
        assert easter(1978) == date(1978, 3, 26)
        assert _tables_epiphany_moon(1978) + timedelta(days=30) == date(1978, 1, 10)

    def test_the_readers_dates(self):
        # islensktalmanak.is, from the almanac: the vetrartungl lit on
        # 25 October 2022 and 14 October 2023, the jólatungl on 26
        # December 2019, and the þorratungl on bóndadagur 2020.
        assert _moons(2023)["vetrartungl"].date() == date(2022, 10, 25)
        assert _moons(2024)["vetrartungl"].date() == date(2023, 10, 14)
        assert _moons(2020)["jolatungl"].date() == date(2019, 12, 26)
        assert _moons(2020)["thorratungl"].date() == date(2020, 1, 24)

    def test_a_moon_new_on_epiphany_is_not_the_jolatungl(self):
        # The glossary: the moon is new a day or two before the tables
        # have it, so one new on Epiphany itself is usually not new by
        # the tables until after it. In 2019 the tables' January moon
        # was new on the 7th and Easter was late, 21 April: the true new
        # moon of 6 January was the aukatungl, and the jólatungl the
        # moon of 7 December.
        moons = _moons(2019)
        assert moons["jolatungl"].date() == date(2018, 12, 7)
        assert moons["aukatungl"].date() == date(2019, 1, 6)
        assert moons["thorratungl"].date() == date(2019, 2, 4)
        assert moons["paskatungl"].date() == date(2019, 4, 5)
        assert easter(2019) == date(2019, 4, 21)

    def test_easter(self):
        for year in range(1583, 4100):
            assert easter(year) == _anonymous_easter(year), year

    def test_the_rules(self):
        for year in range(2000, 2060):
            moons = _moons(year)
            keys = [key for _moon, key in named_moons(year)]
            # Each is the new moon after the one before it, but for the
            # unnamed moon between the vetrartungl and the jólatungl.
            gaps = [(b - a).days for a, b in zip(moons.values(),
                                                 list(moons.values())[1:])]
            assert 58 <= gaps[0] <= 60 and all(29 <= g <= 30 for g in gaps[1:])
            tables = _tables_epiphany_moon(year)
            assert 0 <= (tables - moons["jolatungl"].date()).days <= 3
            paska = moons["paskatungl"].date()
            assert paska < easter(year) < moons["sumartungl"].date()
            # The aukatungl in the years of epact 24, and only in them.
            assert ("aukatungl" in keys) == (_epact(year) == 24)
            assert keys[-4:] == ["thorratungl", "goutungl", "paskatungl",
                                 "sumartungl"]

    def test_the_aukatungl_years(self):
        years = [y for y in range(1900, 2101) if "aukatungl" in _moons(y)]
        assert years == [1905, 1924, 1943, 1962, 1981, 2000, 2019, 2038,
                         2057, 2076, 2095]

    def test_the_moon_in_progress(self):
        utc = timezone.utc
        lit = _moons(2027)["vetrartungl"]
        assert moon_key(datetime(2026, 9, 27, 12, tzinfo=utc)) is None
        assert moon_key(lit - timedelta(minutes=1)) is None
        assert moon_key(lit + timedelta(minutes=1)) == "vetrartungl"
        assert moon_key(datetime(2026, 11, 20, tzinfo=utc)) is None
        assert moon_key(datetime(2026, 12, 24, 18, tzinfo=utc)) == "jolatungl"
        assert moon_key(datetime(2027, 6, 1, tzinfo=utc)) is None

    def test_the_next_named_moon(self):
        utc = timezone.utc
        lit, key = next_named_moon(datetime(2026, 9, 27, 12, tzinfo=utc))
        assert (lit.date(), key) == (date(2026, 10, 10), "vetrartungl")
        lit, key = next_named_moon(lit)
        assert (lit.date(), key) == (date(2026, 12, 9), "jolatungl")
        lit, key = next_named_moon(datetime(2027, 4, 7, tzinfo=utc))
        assert (lit.date(), key) == (date(2027, 10, 29), "vetrartungl")

    def test_a_new_moon_found_another_way(self):
        # The grid finds its own new moons; a few seconds either way
        # still names the moon.
        lit = _moons(2027)["thorratungl"]
        eastern = timezone(timedelta(hours=-5))
        assert lit_moon_key((lit + timedelta(seconds=3)).astimezone(eastern)) == "thorratungl"
        assert lit_moon_key(lit + timedelta(days=15)) is None


class TestPanel:
    """The named moon beside the week while it is up, and in place of
    "New Moon" before it is lit."""

    def _text(self, now):
        import re
        from unittest.mock import patch

        from linecast._runtime import RuntimeConfig
        from linecast.moon.view import render
        runtime = RuntimeConfig(live=False, icons="emoji", lang="en",
                                oneline=False)
        with patch("linecast.moon.view.get_terminal_size",
                   return_value=(100, 30)):
            out = render(now, 64.15, -21.94, runtime, fullscreen=True,
                         calendar_name="icelandic")
        return re.sub(r"\x1b\[[0-9;]*m", "", out)

    def test_a_named_moon_up_and_the_next_to_come(self):
        # 24 December 2026: the jólatungl, lit on the 9th, is full; the
        # þorratungl is lit on 7 January.
        text = self._text(datetime(2026, 12, 24, 18, tzinfo=timezone.utc))
        assert "Waning Gibbous · Jólatungl · week 9 of winter" in text
        assert re.search(r"Þorratungl +Jan 7 +in 14\.1d", text)

    def test_an_unnamed_moon(self):
        # The moon between the vetrartungl and the jólatungl has no
        # name; the jólatungl is the next new moon.
        text = self._text(datetime(2026, 11, 20, 20, tzinfo=timezone.utc))
        assert "Waxing Gibbous · week 4 of winter" in text
        assert re.search(r"Jólatungl +Dec 9 +in 18\.2d", text)
        assert "New Moon" not in text
