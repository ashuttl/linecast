"""The Solar Hijri calendar against published tables and instants.

Three kinds of ground truth: the Calendar Center of the University of
Tehran's announced moments of تحویل سال for 1396–1405 SH, to the
second, which check the equinox and its ΔT; the table of Nowruz dates
and leap years for 1354–1419 SH on Wikipedia's "Solar Hijri calendar",
after Borkowski; and Borkowski's leap years for 1300–1502 SH, from the
algorithm in "The Persian calendar for 3000 years" (1996). The years
where the equinox falls near noon, and the years where Birashk's
2820-year arithmetic departs from the equinox, are pinned by name.
"""

from datetime import date, datetime, timedelta, timezone

import pytest

from linecast.astro.calendars.solar_hijri import (
    CHAHARSHANBE_SURI,
    IRST,
    MONTH_NAMES_EN,
    MONTH_NAMES_FA,
    OBSERVANCES,
    _true_noon_utc,
    chaharshanbe_suri,
    days_in_month,
    is_leap_year,
    month_start,
    next_month_start,
    next_observance,
    nowruz_utc,
    observance_key,
    solar_hijri_date,
    to_gregorian,
)

# The moment of تحویل سال as the Calendar Center announced it, in IRST.
PUBLISHED_INSTANTS = {
    1396: datetime(2017, 3, 20, 13, 58, 40, tzinfo=IRST),
    1397: datetime(2018, 3, 20, 19, 45, 28, tzinfo=IRST),
    1398: datetime(2019, 3, 21, 1, 28, 27, tzinfo=IRST),
    1399: datetime(2020, 3, 20, 7, 19, 37, tzinfo=IRST),
    1400: datetime(2021, 3, 20, 13, 7, 28, tzinfo=IRST),
    1401: datetime(2022, 3, 20, 19, 3, 26, tzinfo=IRST),
    1402: datetime(2023, 3, 21, 0, 54, 28, tzinfo=IRST),
    1403: datetime(2024, 3, 20, 6, 36, 26, tzinfo=IRST),
    1404: datetime(2025, 3, 20, 12, 31, 30, tzinfo=IRST),
    1405: datetime(2026, 3, 20, 18, 16, 0, tzinfo=IRST),
}

# The March equinox to the minute, UTC, from the US Naval Observatory.
USNO_EQUINOXES = {
    2000: datetime(2000, 3, 20, 7, 35, tzinfo=timezone.utc),
    2010: datetime(2010, 3, 20, 17, 32, tzinfo=timezone.utc),
    2012: datetime(2012, 3, 20, 5, 14, tzinfo=timezone.utc),
    2016: datetime(2016, 3, 20, 4, 30, tzinfo=timezone.utc),
    2030: datetime(2030, 3, 20, 13, 51, tzinfo=timezone.utc),
    2040: datetime(2040, 3, 20, 0, 11, tzinfo=timezone.utc),
}

# Wikipedia's correspondence table, 1354–1419 SH: the March day of
# Nowruz (the Gregorian year is SH + 621), and whether the year is leap.
WIKIPEDIA_TABLE = (
    (1354, 21, True), (1355, 21, False), (1356, 21, False),
    (1357, 21, False), (1358, 21, True), (1359, 21, False),
    (1360, 21, False), (1361, 21, False), (1362, 21, True),
    (1363, 21, False), (1364, 21, False), (1365, 21, False),
    (1366, 21, True), (1367, 21, False), (1368, 21, False),
    (1369, 21, False), (1370, 21, True), (1371, 21, False),
    (1372, 21, False), (1373, 21, False), (1374, 21, False),
    (1375, 20, True), (1376, 21, False), (1377, 21, False),
    (1378, 21, False), (1379, 20, True), (1380, 21, False),
    (1381, 21, False), (1382, 21, False), (1383, 20, True),
    (1384, 21, False), (1385, 21, False), (1386, 21, False),
    (1387, 20, True), (1388, 21, False), (1389, 21, False),
    (1390, 21, False), (1391, 20, True), (1392, 21, False),
    (1393, 21, False), (1394, 21, False), (1395, 20, True),
    (1396, 21, False), (1397, 21, False), (1398, 21, False),
    (1399, 20, True), (1400, 21, False), (1401, 21, False),
    (1402, 21, False), (1403, 20, True), (1404, 21, False),
    (1405, 21, False), (1406, 21, False), (1407, 20, False),
    (1408, 20, True), (1409, 21, False), (1410, 21, False),
    (1411, 20, False), (1412, 20, True), (1413, 21, False),
    (1414, 21, False), (1415, 20, False), (1416, 20, True),
    (1417, 21, False), (1418, 21, False), (1419, 20, False),
)

# Borkowski's leap years, 1300–1501 SH.
BORKOWSKI_LEAP_YEARS = frozenset((
    1300, 1304, 1309, 1313, 1317, 1321, 1325, 1329, 1333, 1337, 1342,
    1346, 1350, 1354, 1358, 1362, 1366, 1370, 1375, 1379, 1383, 1387,
    1391, 1395, 1399, 1403, 1408, 1412, 1416, 1420, 1424, 1428, 1432,
    1436, 1441, 1445, 1449, 1453, 1457, 1461, 1465, 1469, 1474, 1478,
    1482, 1486, 1490, 1494, 1498,
))


def _birashk_leap(year):
    """Birashk's 2820-year arithmetic, as Calendrical Calculations has it."""
    y = (year - 474) % 2820 + 474
    return (y + 38) * 682 % 2816 < 682


# ── the equinox ──────────────────────────────────────────────────────

@pytest.mark.parametrize("year, published", sorted(PUBLISHED_INSTANTS.items()))
def test_equinox_matches_the_calendar_center(year, published):
    assert abs((nowruz_utc(year) - published).total_seconds()) < 45


@pytest.mark.parametrize("year, published", sorted(USNO_EQUINOXES.items()))
def test_equinox_matches_usno(year, published):
    # USNO rounds to the minute.
    assert abs((nowruz_utc(year - 621) - published).total_seconds()) < 75


def test_nowruz_utc_is_aware_utc():
    t = nowruz_utc(1404)
    assert t.utcoffset() == timedelta(0)
    assert (t.year, t.month, t.day, t.hour, t.minute) == (2025, 3, 20, 9, 1)


# ── the year ─────────────────────────────────────────────────────────

def test_the_brief_cases():
    # 2025: equinox 09:01 UTC, 12:31 IRST, after noon.
    assert month_start(1404, 1) == date(2025, 3, 21)
    assert solar_hijri_date(date(2025, 3, 20)) == (1403, 12, 30)
    assert solar_hijri_date(date(2025, 3, 21)) == (1404, 1, 1)
    # 2026: equinox 14:46 UTC, 18:16 IRST.
    assert month_start(1405, 1) == date(2026, 3, 21)
    assert solar_hijri_date(date(2026, 3, 20)) == (1404, 12, 29)


@pytest.mark.parametrize("year, march_day, leap", WIKIPEDIA_TABLE)
def test_wikipedia_table(year, march_day, leap):
    assert to_gregorian(year, 1, 1) == date(year + 621, 3, march_day)
    assert is_leap_year(year) is leap


def test_borkowski_leap_years_1300_to_1501():
    ours = {y for y in range(1300, 1502) if is_leap_year(y)}
    assert ours == BORKOWSKI_LEAP_YEARS


def test_the_33_year_cycle_holds_1300_to_1501():
    for year in range(1300, 1502):
        assert is_leap_year(year) == (year % 33 in (1, 5, 9, 13, 17, 22, 26, 30))


def test_birashk_departs_where_expected():
    """The arithmetic calendar puts the leap day a year late three times
    between 1300 and 1500; the equinox is what Iran follows."""
    differ = [y for y in range(1300, 1501) if is_leap_year(y) != _birashk_leap(y)]
    assert differ == [1403, 1404, 1436, 1437, 1469, 1470]
    for year in (1403, 1436, 1469):
        assert is_leap_year(year) and not _birashk_leap(year)
    # So Birashk's Nowruz would fall on the 20th in these years.
    assert month_start(1404, 1) == date(2025, 3, 21)
    assert month_start(1437, 1) == date(2058, 3, 21)
    assert month_start(1470, 1) == date(2091, 3, 21)


# ── the noon line ────────────────────────────────────────────────────

def _margin_seconds(year):
    """Seconds from true noon at 52.5° E to the equinox, on its IRST day."""
    eq = nowruz_utc(year)
    return (eq - _true_noon_utc(eq.astimezone(IRST).date())).total_seconds()


def test_true_noon_is_the_transit_not_the_clock():
    noon = _true_noon_utc(date(2025, 3, 20)).astimezone(IRST)
    # The equation of time is about −7½ minutes on 20 March.
    assert (noon.hour, noon.minute) == (12, 7)


def test_1930_falls_before_true_noon():
    """The 1930 equinox came within seconds of 12:00 IRST but seven and
    a half minutes before the Sun's transit; by the true-noon rule the
    equinox day is Nowruz."""
    eq = nowruz_utc(1309).astimezone(IRST)
    assert eq.date() == date(1930, 3, 21)
    assert abs((eq - datetime(1930, 3, 21, 12, tzinfo=IRST)).total_seconds()) < 60
    assert -520 < _margin_seconds(1309) < -400
    assert month_start(1309, 1) == date(1930, 3, 21)


def test_2091_falls_after_true_noon():
    assert 180 < _margin_seconds(1470) < 330
    assert month_start(1470, 1) == date(2091, 3, 21)


def test_2124_departs_from_borkowski():
    """The first year the true noon at 52.5° E and Borkowski's mean
    noon at Tehran disagree: the equinox falls between them."""
    assert -200 < _margin_seconds(1503) < 0
    assert month_start(1503, 1) == date(2124, 3, 20)


def test_no_year_1300_to_1500_is_within_three_minutes_of_noon():
    closest = min(range(1300, 1501), key=lambda y: abs(_margin_seconds(y)))
    assert closest == 1470
    assert abs(_margin_seconds(closest)) > 180


# ── months and days ──────────────────────────────────────────────────

def test_month_lengths_sum_to_the_year():
    for year in range(1250, 1650):
        total = sum(days_in_month(year, m) for m in range(1, 13))
        assert total == (366 if is_leap_year(year) else 365)
        assert total == (month_start(year + 1, 1) - month_start(year, 1)).days


def test_fixed_months():
    for month in range(1, 7):
        assert days_in_month(1404, month) == 31
    for month in range(7, 12):
        assert days_in_month(1404, month) == 30
    assert days_in_month(1403, 12) == 30
    assert days_in_month(1404, 12) == 29


def test_round_trip_every_day_1300_to_1500():
    day = to_gregorian(1300, 1, 1)
    end = to_gregorian(1500, 12, days_in_month(1500, 12))
    expect = (1300, 1, 1)
    while day <= end:
        got = solar_hijri_date(day)
        assert got == expect
        assert to_gregorian(*got) == day
        y, m, d = got
        if d < days_in_month(y, m):
            expect = (y, m, d + 1)
        elif m < 12:
            expect = (y, m + 1, 1)
        else:
            expect = (y + 1, 1, 1)
        day += timedelta(days=1)


def test_round_trip_sampled_far_years():
    for year in range(900, 2400, 7):
        for month in (1, 6, 7, 12):
            for d in (1, days_in_month(year, month)):
                assert solar_hijri_date(to_gregorian(year, month, d)) == (year, month, d)


def test_to_gregorian_rejects_impossible_dates():
    with pytest.raises(ValueError):
        to_gregorian(1404, 12, 30)
    with pytest.raises(ValueError):
        to_gregorian(1404, 7, 31)
    with pytest.raises(ValueError):
        to_gregorian(1404, 13, 1)
    assert to_gregorian(1403, 12, 30) == date(2025, 3, 20)


def test_next_month_start():
    assert next_month_start(date(2025, 9, 23)) == (date(2025, 10, 23), (1404, 8))
    assert next_month_start(date(2026, 3, 1)) == (date(2026, 3, 21), (1405, 1))


def test_month_names():
    assert len(MONTH_NAMES_FA) == len(MONTH_NAMES_EN) == 12
    assert MONTH_NAMES_FA[0] == "فروردین" and MONTH_NAMES_FA[11] == "اسفند"
    assert MONTH_NAMES_EN[6] == "Mehr" and MONTH_NAMES_EN[9] == "Dey"


# ── observances ──────────────────────────────────────────────────────

OBSERVANCES_1404 = (
    (date(2025, 3, 21), "nowruz"),
    (date(2025, 4, 2), "sizdah_bedar"),
    (date(2025, 7, 4), "tirgan"),
    (date(2025, 10, 2), "mehregan"),
    (date(2025, 12, 21), "yalda"),
    (date(2026, 1, 30), "sadeh"),
    (date(2026, 3, 17), CHAHARSHANBE_SURI),
    (date(2026, 3, 21), "nowruz"),
)


def test_observance_keys():
    for day, key in OBSERVANCES_1404:
        assert observance_key(day) == key
    assert observance_key(date(2025, 3, 22)) is None
    assert set(OBSERVANCES.values()) == {
        "nowruz", "sizdah_bedar", "tirgan", "mehregan", "yalda", "sadeh"}


def test_next_observance_walks_the_year():
    day = date(2025, 3, 21)
    for expected in OBSERVANCES_1404:
        got = next_observance(day)
        assert got == expected
        day = got[0] + timedelta(days=1)


def test_yalda_follows_the_leap_year():
    # 1403 is leap, so 30 Azar fell a day earlier in the Gregorian year.
    assert observance_key(date(2024, 12, 20)) == "yalda"


def test_chaharshanbe_suri_is_the_tuesday_before_the_last_wednesday():
    assert chaharshanbe_suri(1403) == date(2025, 3, 18)
    assert chaharshanbe_suri(1404) == date(2026, 3, 17)
    for year in range(1380, 1450):
        tuesday = chaharshanbe_suri(year)
        wednesday = tuesday + timedelta(days=1)
        assert tuesday.weekday() == 1
        assert solar_hijri_date(wednesday)[:2] == (year, 12)
        # No later Wednesday in the year.
        assert solar_hijri_date(wednesday + timedelta(days=7))[0] == year + 1
