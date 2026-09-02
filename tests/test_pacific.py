"""The Pacific calendars against the Council's printed tables.

The ground truth is the WPRFMC's printed month spans: every month of
the 2025 and 2026 Hawaiʻi editions (their pages run Nov 2024 - Feb
2027), and every month of the 2021–2026 American Samoa, Guam, and
CNMI editions (Jan 2021 - Feb 2027). The engine derives each first
night from crescent visibility at the calendar's own place, so these
are end-to-end checks that the ephemeris and the calibrated Yallop
cutoff land every month where the printed calendar does — including
the months visibility pushes the start a second day past the
conjunction, and the 29-night months that drop their twenty-ninth
name. The few printed months no cutoff reproduces are pinned as
departures, so a recalibration that starts fitting them is noticed.
"""

from datetime import date, timedelta

import pytest

from linecast._moon_i18n import (
    _ANAHULU,
    _MASINA,
    _PO_MAHINA,
    _PULAN,
    _REFALUWASCH,
    anahulu_name,
    pacific_night_label,
    pacific_night_name,
    po_mahina_name,
    refaluwasch_name,
)
from linecast._pacific import (
    ANAHULU_COUNSEL,
    CALENDARS,
    PACIFIC_CALENDARS,
    _NIGHT_NOTES,
    hawaiian_night,
    night_note,
    pacific_night,
)

# (Hilo, Muku) of every month in the 2025 and 2026 printed editions.
PUBLISHED_MONTHS = [
    (date(2024, 11, 2), date(2024, 12, 1)),
    (date(2024, 12, 2), date(2024, 12, 30)),
    (date(2024, 12, 31), date(2025, 1, 29)),
    (date(2025, 1, 30), date(2025, 2, 27)),
    (date(2025, 2, 28), date(2025, 3, 29)),
    (date(2025, 3, 30), date(2025, 4, 27)),
    (date(2025, 4, 28), date(2025, 5, 26)),
    (date(2025, 5, 27), date(2025, 6, 25)),
    (date(2025, 6, 26), date(2025, 7, 24)),
    (date(2025, 7, 25), date(2025, 8, 23)),
    (date(2025, 8, 24), date(2025, 9, 21)),
    (date(2025, 9, 22), date(2025, 10, 21)),
    (date(2025, 10, 22), date(2025, 11, 20)),
    (date(2025, 11, 21), date(2025, 12, 19)),
    (date(2025, 12, 20), date(2026, 1, 18)),
    (date(2026, 1, 19), date(2026, 2, 17)),
    (date(2026, 2, 18), date(2026, 3, 18)),
    (date(2026, 3, 19), date(2026, 4, 17)),
    (date(2026, 4, 18), date(2026, 5, 16)),
    (date(2026, 5, 17), date(2026, 6, 14)),
    (date(2026, 6, 15), date(2026, 7, 13)),
    (date(2026, 7, 14), date(2026, 8, 12)),
    (date(2026, 8, 13), date(2026, 9, 11)),
    (date(2026, 9, 12), date(2026, 10, 10)),
    (date(2026, 10, 11), date(2026, 11, 9)),
    (date(2026, 11, 10), date(2026, 12, 9)),
    (date(2026, 12, 10), date(2027, 1, 7)),
    (date(2027, 1, 8), date(2027, 2, 6)),
]


class TestPublishedMonths:
    @pytest.mark.parametrize("hilo,muku", PUBLISHED_MONTHS,
                             ids=lambda d: d.isoformat())
    def test_month_matches_the_printed_table(self, hilo, muku):
        nights = (muku - hilo).days + 1
        assert nights in (29, 30)
        assert hawaiian_night(hilo) == (1, nights)
        assert hawaiian_night(muku) == (nights, nights)

    def test_consecutive_days_stay_consecutive(self):
        prev = hawaiian_night(date(2025, 1, 1))
        for offset in range(1, 400):
            cur = hawaiian_night(date(2025, 1, 1) + timedelta(days=offset))
            if cur[0] == 1:
                assert prev[0] == prev[1]
            else:
                assert cur[0] == prev[0] + 1
                assert cur[1] == prev[1]
            prev = cur


# (first night, last night) of every month in the 2021–2026 American
# Samoa editions, as their pages title them.
SAMOAN_MONTHS = [
    (date(2021, 1, 13), date(2021, 2, 11)),
    (date(2021, 2, 12), date(2021, 3, 13)),
    (date(2021, 3, 14), date(2021, 4, 11)),
    (date(2021, 4, 12), date(2021, 5, 11)),
    (date(2021, 5, 12), date(2021, 6, 10)),
    (date(2021, 6, 11), date(2021, 7, 9)),
    (date(2021, 7, 10), date(2021, 8, 8)),
    (date(2021, 8, 9), date(2021, 9, 6)),
    (date(2021, 9, 7), date(2021, 10, 6)),
    (date(2021, 10, 7), date(2021, 11, 4)),
    (date(2021, 11, 5), date(2021, 12, 3)),
    (date(2021, 12, 4), date(2022, 1, 2)),
    (date(2022, 1, 3), date(2022, 1, 31)),
    (date(2022, 2, 1), date(2022, 3, 2)),
    (date(2022, 3, 3), date(2022, 3, 31)),
    (date(2022, 4, 1), date(2022, 4, 30)),
    (date(2022, 5, 1), date(2022, 5, 30)),
    (date(2022, 5, 31), date(2022, 6, 28)),
    (date(2022, 6, 29), date(2022, 7, 28)),
    (date(2022, 7, 29), date(2022, 8, 26)),
    (date(2022, 8, 27), date(2022, 9, 25)),
    (date(2022, 9, 26), date(2022, 10, 25)),
    (date(2022, 10, 26), date(2022, 11, 23)),
    (date(2022, 11, 24), date(2022, 12, 22)),
    (date(2022, 12, 23), date(2023, 1, 21)),
    (date(2023, 1, 22), date(2023, 2, 19)),
    (date(2023, 2, 20), date(2023, 3, 21)),
    (date(2023, 3, 22), date(2023, 4, 19)),
    (date(2023, 4, 20), date(2023, 5, 19)),
    (date(2023, 5, 20), date(2023, 6, 17)),
    (date(2023, 6, 18), date(2023, 7, 17)),
    (date(2023, 7, 18), date(2023, 8, 16)),
    (date(2023, 8, 17), date(2023, 9, 14)),
    (date(2023, 9, 15), date(2023, 10, 14)),
    (date(2023, 10, 15), date(2023, 11, 13)),
    (date(2023, 11, 14), date(2023, 12, 12)),
    (date(2023, 12, 13), date(2024, 1, 11)),
    (date(2024, 1, 12), date(2024, 2, 9)),
    (date(2024, 2, 10), date(2024, 3, 10)),
    (date(2024, 3, 11), date(2024, 4, 8)),
    (date(2024, 4, 9), date(2024, 5, 7)),
    (date(2024, 5, 8), date(2024, 6, 6)),
    (date(2024, 6, 7), date(2024, 7, 5)),
    (date(2024, 7, 6), date(2024, 8, 4)),
    (date(2024, 8, 5), date(2024, 9, 2)),
    (date(2024, 9, 3), date(2024, 10, 2)),
    (date(2024, 10, 3), date(2024, 11, 1)),
    (date(2024, 11, 2), date(2024, 11, 30)),
    (date(2024, 12, 1), date(2024, 12, 30)),
    (date(2024, 12, 31), date(2025, 1, 29)),
    (date(2025, 1, 30), date(2025, 2, 27)),
    (date(2025, 2, 28), date(2025, 3, 29)),
    (date(2025, 3, 30), date(2025, 4, 27)),
    (date(2025, 4, 28), date(2025, 5, 26)),
    (date(2025, 5, 27), date(2025, 6, 24)),
    (date(2025, 6, 25), date(2025, 7, 24)),
    (date(2025, 7, 25), date(2025, 8, 22)),
    (date(2025, 8, 23), date(2025, 9, 21)),
    (date(2025, 9, 22), date(2025, 10, 21)),
    (date(2025, 10, 22), date(2025, 11, 20)),
    (date(2025, 11, 21), date(2025, 12, 19)),
    (date(2025, 12, 20), date(2026, 1, 18)),
    (date(2026, 1, 19), date(2026, 2, 17)),
    (date(2026, 2, 18), date(2026, 3, 18)),
    (date(2026, 3, 19), date(2026, 4, 17)),
    (date(2026, 4, 18), date(2026, 5, 16)),
    (date(2026, 5, 17), date(2026, 6, 14)),
    (date(2026, 6, 15), date(2026, 7, 13)),
    (date(2026, 7, 14), date(2026, 8, 12)),
    (date(2026, 8, 13), date(2026, 9, 10)),
    (date(2026, 9, 11), date(2026, 10, 10)),
    (date(2026, 10, 11), date(2026, 11, 8)),
    (date(2026, 11, 9), date(2026, 12, 8)),
    (date(2026, 12, 9), date(2027, 1, 7)),
    (date(2027, 1, 8), date(2027, 2, 6)),
]

# The same for the Guam and CNMI editions, which print identical
# spans; the 2025 edition covered the Marianas as one.
MARIANAS_MONTHS = [
    (date(2021, 1, 14), date(2021, 2, 12)),
    (date(2021, 2, 13), date(2021, 3, 13)),
    (date(2021, 3, 14), date(2021, 4, 12)),
    (date(2021, 4, 13), date(2021, 5, 12)),
    (date(2021, 5, 13), date(2021, 6, 11)),
    (date(2021, 6, 12), date(2021, 7, 10)),
    (date(2021, 7, 11), date(2021, 8, 9)),
    (date(2021, 8, 10), date(2021, 9, 7)),
    (date(2021, 9, 8), date(2021, 10, 7)),
    (date(2021, 10, 8), date(2021, 11, 5)),
    (date(2021, 11, 6), date(2021, 12, 4)),
    (date(2021, 12, 5), date(2022, 1, 3)),
    (date(2022, 1, 4), date(2022, 2, 1)),
    (date(2022, 2, 2), date(2022, 3, 3)),
    (date(2022, 3, 4), date(2022, 4, 1)),
    (date(2022, 4, 2), date(2022, 5, 1)),
    (date(2022, 5, 2), date(2022, 5, 31)),
    (date(2022, 6, 1), date(2022, 6, 29)),
    (date(2022, 6, 30), date(2022, 7, 29)),
    (date(2022, 7, 30), date(2022, 8, 27)),
    (date(2022, 8, 28), date(2022, 9, 26)),
    (date(2022, 9, 27), date(2022, 10, 26)),
    (date(2022, 10, 27), date(2022, 11, 24)),
    (date(2022, 11, 25), date(2022, 12, 23)),
    (date(2022, 12, 24), date(2023, 1, 22)),
    (date(2023, 1, 23), date(2023, 2, 20)),
    (date(2023, 2, 21), date(2023, 3, 22)),
    (date(2023, 3, 23), date(2023, 4, 20)),
    (date(2023, 4, 21), date(2023, 5, 20)),
    (date(2023, 5, 21), date(2023, 6, 18)),
    (date(2023, 6, 19), date(2023, 7, 18)),
    (date(2023, 7, 19), date(2023, 8, 16)),
    (date(2023, 8, 17), date(2023, 9, 15)),
    (date(2023, 9, 16), date(2023, 10, 15)),
    (date(2023, 10, 16), date(2023, 11, 14)),
    (date(2023, 11, 15), date(2023, 12, 13)),
    (date(2023, 12, 14), date(2024, 1, 12)),
    (date(2024, 1, 13), date(2024, 2, 10)),
    (date(2024, 2, 11), date(2024, 3, 10)),
    (date(2024, 3, 11), date(2024, 4, 9)),
    (date(2024, 4, 10), date(2024, 5, 8)),
    (date(2024, 5, 9), date(2024, 6, 7)),
    (date(2024, 6, 8), date(2024, 7, 6)),
    (date(2024, 7, 7), date(2024, 8, 5)),
    (date(2024, 8, 6), date(2024, 9, 3)),
    (date(2024, 9, 4), date(2024, 10, 3)),
    (date(2024, 10, 4), date(2024, 11, 2)),
    (date(2024, 11, 3), date(2024, 12, 1)),
    (date(2024, 12, 2), date(2024, 12, 31)),
    (date(2025, 1, 1), date(2025, 1, 30)),
    (date(2025, 1, 31), date(2025, 2, 28)),
    (date(2025, 3, 1), date(2025, 3, 29)),
    (date(2025, 3, 30), date(2025, 4, 28)),
    (date(2025, 4, 29), date(2025, 5, 27)),
    (date(2025, 5, 28), date(2025, 6, 25)),
    (date(2025, 6, 26), date(2025, 7, 25)),
    (date(2025, 7, 26), date(2025, 8, 23)),
    (date(2025, 8, 24), date(2025, 9, 22)),
    (date(2025, 9, 23), date(2025, 10, 22)),
    (date(2025, 10, 23), date(2025, 11, 21)),
    (date(2025, 11, 22), date(2025, 12, 20)),
    (date(2025, 12, 21), date(2026, 1, 19)),
    (date(2026, 1, 20), date(2026, 2, 18)),
    (date(2026, 2, 19), date(2026, 3, 19)),
    (date(2026, 3, 20), date(2026, 4, 17)),
    (date(2026, 4, 18), date(2026, 5, 17)),
    (date(2026, 5, 18), date(2026, 6, 15)),
    (date(2026, 6, 16), date(2026, 7, 14)),
    (date(2026, 7, 15), date(2026, 8, 13)),
    (date(2026, 8, 14), date(2026, 9, 11)),
    (date(2026, 9, 12), date(2026, 10, 11)),
    (date(2026, 10, 12), date(2026, 11, 10)),
    (date(2026, 11, 11), date(2026, 12, 9)),
    (date(2026, 12, 10), date(2027, 1, 8)),
    (date(2027, 1, 9), date(2027, 2, 7)),
]

# Months whose printed start no visibility cutoff reproduces (the
# module docstring in _pacific has the numbers): printed first night
# -> the first night the engine finds, a day to either side. The
# 2026 editions have none.
PRINT_DEPARTS = {
    "samoan": {
        date(2024, 3, 11): date(2024, 3, 10),
        date(2025, 6, 25): date(2025, 6, 26),
        date(2025, 11, 21): date(2025, 11, 20),
    },
    "chamorro": {
        date(2021, 10, 8): date(2021, 10, 7),
        date(2023, 8, 17): date(2023, 8, 18),
        date(2024, 1, 13): date(2024, 1, 12),
        date(2024, 6, 8): date(2024, 6, 7),
        date(2024, 12, 2): date(2024, 12, 3),
    },
}


def _check_printed_month(cal, first, last):
    nights = (last - first).days + 1
    assert nights in (29, 30)
    departs = PRINT_DEPARTS[cal]
    if first in departs:
        # The print departs from its data here; the engine keeps to the
        # data, one day off, and that is pinned too.
        assert pacific_night(cal, departs[first])[0] == 1
        assert pacific_night(cal, first)[0] != 1
    else:
        assert pacific_night(cal, first)[0] == 1
    if first not in departs and last + timedelta(days=1) not in departs:
        assert pacific_night(cal, last) == (nights, nights)


class TestSamoanMonths:
    @pytest.mark.parametrize("first,last", SAMOAN_MONTHS,
                             ids=lambda d: d.isoformat())
    def test_month_matches_the_printed_table(self, first, last):
        _check_printed_month("samoan", first, last)

    def test_departures_are_the_only_misses(self):
        misses = {f for f, _l in SAMOAN_MONTHS
                  if pacific_night("samoan", f)[0] != 1}
        assert misses == set(PRINT_DEPARTS["samoan"])

    def test_consecutive_days_stay_consecutive(self):
        _walk("samoan", date(2022, 1, 1), 800)


class TestMarianasMonths:
    @pytest.mark.parametrize("first,last", MARIANAS_MONTHS,
                             ids=lambda d: d.isoformat())
    def test_month_matches_the_printed_table(self, first, last):
        _check_printed_month("chamorro", first, last)

    def test_departures_are_the_only_misses(self):
        misses = {f for f, _l in MARIANAS_MONTHS
                  if pacific_night("chamorro", f)[0] != 1}
        assert misses == set(PRINT_DEPARTS["chamorro"])

    def test_the_cnmi_calendar_reads_the_same_table(self):
        assert CALENDARS["refaluwasch"] is CALENDARS["chamorro"]
        for d in (date(2026, 1, 20), date(2026, 9, 12), date(2027, 2, 7)):
            assert pacific_night("refaluwasch", d) == pacific_night("chamorro", d)

    def test_consecutive_days_stay_consecutive(self):
        _walk("chamorro", date(2022, 1, 1), 800)


def _named(cal, day):
    return pacific_night_name(cal, *pacific_night(cal, day))


def _walk(cal, start, days):
    prev = pacific_night(cal, start)
    for offset in range(1, days):
        cur = pacific_night(cal, start + timedelta(days=offset))
        if cur[0] == 1:
            assert prev[0] == prev[1]
        else:
            assert cur[0] == prev[0] + 1
            assert cur[1] == prev[1]
        prev = cur


class TestSamoanNames:
    def test_the_thirty_masina_as_printed(self):
        # Utuvāmua, Jan 19 - Feb 17 2026, thirty nights, as the page
        # runs them ten to a row.
        start = date(2026, 1, 19)
        got = [_named("samoan", start + timedelta(days=i))
               for i in range(30)]
        assert got == list(_MASINA)
        assert got[0] == "Masina Fou/Faatoavaaia"
        assert got[14] == "Masina Atoa/Atoa Liʻo le Masina"     # the full moon
        assert got[29] == "Masina Maunā"

    def test_the_29_night_month_drops_fanoloa(self):
        # Toeutuvā, Feb 18 - Mar 18 2026, as printed: Mitiloa then Maunā.
        assert _named("samoan", date(2026, 3, 17)) == "Masina Mitiloa"
        assert _named("samoan", date(2026, 3, 18)) == "Masina Maunā"
        assert _named("samoan", date(2026, 3, 19)) == "Masina Fou/Faatoavaaia"


class TestChamorroNames:
    def test_the_thirty_pulan_as_printed(self):
        # Tumaiguini, Jan 20 - Feb 18 2026, thirty nights.
        start = date(2026, 1, 20)
        got = [_named("chamorro", start + timedelta(days=i))
               for i in range(30)]
        assert got == list(_PULAN)
        assert got[15] == "Pulan Gualåffon"                    # the full moon
        assert got[28] == "Kumaninifes" and got[29] == "Sinahi"

    def test_the_29_night_month_drops_kumaninifes(self):
        # Feb 19 - Mar 19 2026, as printed: Dalalai Pulan then Sinahi.
        assert _named("chamorro", date(2026, 3, 18)) == "Dalalai Pulan"
        assert _named("chamorro", date(2026, 3, 19)) == "Sinahi"

    def test_refaluwasch_names_sit_where_the_cnmi_page_puts_them(self):
        # Tumaiguini / Mááischigh 2026, per the printed page.
        printed = {
            date(2026, 1, 20): "Sighauru", date(2026, 1, 21): "Eling",
            date(2026, 1, 22): "Meseling", date(2026, 1, 23): None,
            date(2026, 1, 28): "Eschúw", date(2026, 2, 2): "Emmasch",
            date(2026, 2, 3): "Úúr", date(2026, 2, 4): "Letiw",
            date(2026, 2, 5): "Ghiney", date(2026, 2, 6): "Ara",
            date(2026, 2, 9): "Arosan Efnágh", date(2026, 2, 15): "Arofú",
            date(2026, 2, 18): None,
        }
        for day, name in printed.items():
            assert refaluwasch_name(*pacific_night("refaluwasch", day)) == name
        assert len(_REFALUWASCH) == 11

    def test_the_cnmi_headline_carries_both_names(self):
        night = pacific_night("refaluwasch", date(2026, 2, 4))
        assert pacific_night_label("refaluwasch", *night) == "Pulan Gualåffon · Letiw"
        assert pacific_night_label("chamorro", *night) == "Pulan Gualåffon"
        night = pacific_night("refaluwasch", date(2026, 1, 23))
        assert pacific_night_label("refaluwasch", *night) == "Sumahi I Pilan"

    def test_the_drop_never_takes_a_refaluwasch_night(self):
        assert max(_REFALUWASCH) < 29


class TestEveryCalendar:
    def test_thirty_distinct_names_each(self):
        for cal in PACIFIC_CALENDARS:
            names = [pacific_night_name(cal, n, 30) for n in range(1, 31)]
            assert len(names) == 30
            # The Hawaiian ʻOle names repeat by design (two runs).
            if cal != "hawaiian":
                assert len(set(names)) == 30

    def test_the_hawaiian_wrapper_is_the_engine(self):
        assert hawaiian_night(date(2026, 9, 1)) == pacific_night("hawaiian", date(2026, 9, 1))


class TestNightNames:
    def test_the_thirty_night_month_keeps_mauli(self):
        # Nana, Feb 28 - Mar 29 2025, as printed: thirty nights.
        assert po_mahina_name(*hawaiian_night(date(2025, 3, 28))) == "Mauli"
        assert po_mahina_name(*hawaiian_night(date(2025, 3, 29))) == "Muku"

    def test_the_29_night_month_drops_mauli(self):
        # Kaulua, Jan 30 - Feb 27 2025, as printed: Lono then Muku.
        assert po_mahina_name(*hawaiian_night(date(2025, 2, 26))) == "Lono"
        assert po_mahina_name(*hawaiian_night(date(2025, 2, 27))) == "Muku"

    def test_nights_from_the_printed_2026_pages(self):
        # Hinaiaʻeleʻele, Jun 15 - Jul 13 2026, spot checks per the page.
        cases = {
            date(2026, 6, 15): "Hilo",
            date(2026, 6, 24): "ʻOlepau",
            date(2026, 6, 29): "Hoku",
            date(2026, 7, 4): "Lāʻaupau",
            date(2026, 7, 8): "Kāloakūkahi",
            date(2026, 7, 13): "Muku",
        }
        for day, name in cases.items():
            assert po_mahina_name(*hawaiian_night(day)) == name

    def test_full_sequence_of_a_thirty_night_month(self):
        # Nana 2025 as printed, both ʻOle runs and all three Kū names.
        printed = [
            "Hilo", "Hoaka", "Kūkahi", "Kūlua", "Kūkolu",
            "Kūpau", "ʻOlekūkahi", "ʻOlekūlua", "ʻOlekūkolu", "ʻOlepau",
            "Huna", "Mōhalu", "Hua", "Akua", "Hoku",
            "Māhealani", "Kulu", "Lāʻaukūkahi", "Lāʻaukūlua", "Lāʻaupau",
            "ʻOlekūkahi", "ʻOlekūlua", "ʻOlepau", "Kāloakūkahi",
            "Kāloakūlua", "Kāloapau", "Kāne", "Lono", "Mauli", "Muku",
        ]
        start = date(2025, 2, 28)
        got = [po_mahina_name(*hawaiian_night(start + timedelta(days=i)))
               for i in range(30)]
        assert got == printed


class TestAnahulu:
    def test_boundaries(self):
        assert anahulu_name(1) == "hoʻonui"
        assert anahulu_name(10) == "hoʻonui"
        assert anahulu_name(11) == "poepoe"
        assert anahulu_name(20) == "poepoe"
        assert anahulu_name(21) == "hōʻemi"
        assert anahulu_name(30) == "hōʻemi"


class TestCounsel:
    """The vendored WPRFMC counsel stays keyed to real names."""

    def test_every_anahulu_has_counsel(self):
        assert set(ANAHULU_COUNSEL) == set(_ANAHULU)

    def test_every_note_names_a_real_night(self):
        assert set(_NIGHT_NOTES) <= set(_PO_MAHINA)

    def test_the_kapu_nights_as_the_display_draws_them(self):
        # Kapu Kū over Hilo..Kūlua, Hua over Mōhalu..Hua, Kāloa over
        # the first two Kāloa nights, Kāne over Kāne and Lono.
        assert night_note("Hilo").startswith("Kapu Kū")
        assert night_note("Kūlua").startswith("Kapu Kū")
        assert night_note("Kūkolu") is None
        assert night_note("Hua").startswith("Kapu Hua")
        assert night_note("Kāloakūlua").startswith("Kapu Kāloa")
        assert night_note("Kāloapau") is None
        assert night_note("Lono").startswith("Kapu Kāne")
        assert night_note("Mauli") is None
        assert night_note("ʻOlepau").startswith("ʻOle night")
