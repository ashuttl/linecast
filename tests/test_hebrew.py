"""The Hebrew calendar against Hebcal.

The ground truth is Hebcal's reading of the fixed calendar: the first
day of every month of 5780 through 5790 (September 2019 to September
2030, four of them leap years), and every holiday of 2023 through
2026 as the diaspora keeps it. The engine is pure arithmetic, so
these are checks that the molad, the postponements, and the year
lengths come out where the reference does — each month's start in the
table implies the length of the month before it.
"""

from datetime import date, datetime, timedelta, timezone

import pytest

from linecast._hebrew import (
    HOLIDAYS,
    days_in_month,
    days_in_year,
    hebrew_date,
    holiday_key,
    is_leap_year,
    month_start,
    next_holiday,
    next_month_start,
    rosh_chodesh,
)
from linecast._hijri import after_sunset
from linecast._moon_i18n import (
    hebrew_date_hebrew, hebrew_date_label, hebrew_holiday_name,
    hebrew_month_name, hebrew_numeral, hebrew_year_numeral,
    rosh_chodesh_label,
)

# (year, month) → the civil date of its first day, from Hebcal. Months
# are numbered from Nisan; 12 is Adar, or Adar I when 13 follows.
PUBLISHED_MONTHS = {
    (5780, 7): date(2019, 9, 30),
    (5780, 8): date(2019, 10, 30),
    (5780, 9): date(2019, 11, 29),
    (5780, 10): date(2019, 12, 29),
    (5780, 11): date(2020, 1, 27),
    (5780, 12): date(2020, 2, 26),
    (5780, 1): date(2020, 3, 26),
    (5780, 2): date(2020, 4, 25),
    (5780, 3): date(2020, 5, 24),
    (5780, 4): date(2020, 6, 23),
    (5780, 5): date(2020, 7, 22),
    (5780, 6): date(2020, 8, 21),
    (5781, 7): date(2020, 9, 19),
    (5781, 8): date(2020, 10, 19),
    (5781, 9): date(2020, 11, 17),
    (5781, 10): date(2020, 12, 16),
    (5781, 11): date(2021, 1, 14),
    (5781, 12): date(2021, 2, 13),
    (5781, 1): date(2021, 3, 14),
    (5781, 2): date(2021, 4, 13),
    (5781, 3): date(2021, 5, 12),
    (5781, 4): date(2021, 6, 11),
    (5781, 5): date(2021, 7, 10),
    (5781, 6): date(2021, 8, 9),
    (5782, 7): date(2021, 9, 7),
    (5782, 8): date(2021, 10, 7),
    (5782, 9): date(2021, 11, 5),
    (5782, 10): date(2021, 12, 5),
    (5782, 11): date(2022, 1, 3),
    (5782, 12): date(2022, 2, 2),
    (5782, 13): date(2022, 3, 4),
    (5782, 1): date(2022, 4, 2),
    (5782, 2): date(2022, 5, 2),
    (5782, 3): date(2022, 5, 31),
    (5782, 4): date(2022, 6, 30),
    (5782, 5): date(2022, 7, 29),
    (5782, 6): date(2022, 8, 28),
    (5783, 7): date(2022, 9, 26),
    (5783, 8): date(2022, 10, 26),
    (5783, 9): date(2022, 11, 25),
    (5783, 10): date(2022, 12, 25),
    (5783, 11): date(2023, 1, 23),
    (5783, 12): date(2023, 2, 22),
    (5783, 1): date(2023, 3, 23),
    (5783, 2): date(2023, 4, 22),
    (5783, 3): date(2023, 5, 21),
    (5783, 4): date(2023, 6, 20),
    (5783, 5): date(2023, 7, 19),
    (5783, 6): date(2023, 8, 18),
    (5784, 7): date(2023, 9, 16),
    (5784, 8): date(2023, 10, 16),
    (5784, 9): date(2023, 11, 14),
    (5784, 10): date(2023, 12, 13),
    (5784, 11): date(2024, 1, 11),
    (5784, 12): date(2024, 2, 10),
    (5784, 13): date(2024, 3, 11),
    (5784, 1): date(2024, 4, 9),
    (5784, 2): date(2024, 5, 9),
    (5784, 3): date(2024, 6, 7),
    (5784, 4): date(2024, 7, 7),
    (5784, 5): date(2024, 8, 5),
    (5784, 6): date(2024, 9, 4),
    (5785, 7): date(2024, 10, 3),
    (5785, 8): date(2024, 11, 2),
    (5785, 9): date(2024, 12, 2),
    (5785, 10): date(2025, 1, 1),
    (5785, 11): date(2025, 1, 30),
    (5785, 12): date(2025, 3, 1),
    (5785, 1): date(2025, 3, 30),
    (5785, 2): date(2025, 4, 29),
    (5785, 3): date(2025, 5, 28),
    (5785, 4): date(2025, 6, 27),
    (5785, 5): date(2025, 7, 26),
    (5785, 6): date(2025, 8, 25),
    (5786, 7): date(2025, 9, 23),
    (5786, 8): date(2025, 10, 23),
    (5786, 9): date(2025, 11, 21),
    (5786, 10): date(2025, 12, 21),
    (5786, 11): date(2026, 1, 19),
    (5786, 12): date(2026, 2, 18),
    (5786, 1): date(2026, 3, 19),
    (5786, 2): date(2026, 4, 18),
    (5786, 3): date(2026, 5, 17),
    (5786, 4): date(2026, 6, 16),
    (5786, 5): date(2026, 7, 15),
    (5786, 6): date(2026, 8, 14),
    (5787, 7): date(2026, 9, 12),
    (5787, 8): date(2026, 10, 12),
    (5787, 9): date(2026, 11, 11),
    (5787, 10): date(2026, 12, 11),
    (5787, 11): date(2027, 1, 9),
    (5787, 12): date(2027, 2, 8),
    (5787, 13): date(2027, 3, 10),
    (5787, 1): date(2027, 4, 8),
    (5787, 2): date(2027, 5, 8),
    (5787, 3): date(2027, 6, 6),
    (5787, 4): date(2027, 7, 6),
    (5787, 5): date(2027, 8, 4),
    (5787, 6): date(2027, 9, 3),
    (5788, 7): date(2027, 10, 2),
    (5788, 8): date(2027, 11, 1),
    (5788, 9): date(2027, 12, 1),
    (5788, 10): date(2027, 12, 31),
    (5788, 11): date(2028, 1, 29),
    (5788, 12): date(2028, 2, 28),
    (5788, 1): date(2028, 3, 28),
    (5788, 2): date(2028, 4, 27),
    (5788, 3): date(2028, 5, 26),
    (5788, 4): date(2028, 6, 25),
    (5788, 5): date(2028, 7, 24),
    (5788, 6): date(2028, 8, 23),
    (5789, 7): date(2028, 9, 21),
    (5789, 8): date(2028, 10, 21),
    (5789, 9): date(2028, 11, 19),
    (5789, 10): date(2028, 12, 19),
    (5789, 11): date(2029, 1, 17),
    (5789, 12): date(2029, 2, 16),
    (5789, 1): date(2029, 3, 17),
    (5789, 2): date(2029, 4, 16),
    (5789, 3): date(2029, 5, 15),
    (5789, 4): date(2029, 6, 14),
    (5789, 5): date(2029, 7, 13),
    (5789, 6): date(2029, 8, 12),
    (5790, 7): date(2029, 9, 10),
    (5790, 8): date(2029, 10, 10),
    (5790, 9): date(2029, 11, 8),
    (5790, 10): date(2029, 12, 7),
    (5790, 11): date(2030, 1, 5),
    (5790, 12): date(2030, 2, 4),
    (5790, 13): date(2030, 3, 6),
    (5790, 1): date(2030, 4, 4),
    (5790, 2): date(2030, 5, 4),
    (5790, 3): date(2030, 6, 2),
    (5790, 4): date(2030, 7, 2),
    (5790, 5): date(2030, 7, 31),
    (5790, 6): date(2030, 8, 30),
}

# (civil date, key): the first day of every holiday of 2023 through
# 2026 as Hebcal lists it — Hanukkah by its second candle, which is
# lit on the first day's evening; the first is lit the evening before.
PUBLISHED_HOLIDAYS = [
    (date(2023, 2, 6), "tu_bishvat"),
    (date(2023, 3, 7), "purim"),
    (date(2023, 4, 6), "pesach"),
    (date(2023, 5, 26), "shavuot"),
    (date(2023, 7, 27), "tisha_bav"),
    (date(2023, 9, 16), "rosh_hashanah"),
    (date(2023, 9, 25), "yom_kippur"),
    (date(2023, 9, 30), "sukkot"),
    (date(2023, 10, 7), "shemini_atzeret"),
    (date(2023, 10, 8), "simchat_torah"),
    (date(2023, 12, 8), "hanukkah"),
    (date(2024, 1, 25), "tu_bishvat"),
    (date(2024, 3, 24), "purim"),
    (date(2024, 4, 23), "pesach"),
    (date(2024, 6, 12), "shavuot"),
    (date(2024, 8, 13), "tisha_bav"),
    (date(2024, 10, 3), "rosh_hashanah"),
    (date(2024, 10, 12), "yom_kippur"),
    (date(2024, 10, 17), "sukkot"),
    (date(2024, 10, 24), "shemini_atzeret"),
    (date(2024, 10, 25), "simchat_torah"),
    (date(2024, 12, 26), "hanukkah"),
    (date(2025, 2, 13), "tu_bishvat"),
    (date(2025, 3, 14), "purim"),
    (date(2025, 4, 13), "pesach"),
    (date(2025, 6, 2), "shavuot"),
    (date(2025, 8, 3), "tisha_bav"),
    (date(2025, 9, 23), "rosh_hashanah"),
    (date(2025, 10, 2), "yom_kippur"),
    (date(2025, 10, 7), "sukkot"),
    (date(2025, 10, 14), "shemini_atzeret"),
    (date(2025, 10, 15), "simchat_torah"),
    (date(2025, 12, 15), "hanukkah"),
    (date(2026, 2, 2), "tu_bishvat"),
    (date(2026, 3, 3), "purim"),
    (date(2026, 4, 2), "pesach"),
    (date(2026, 5, 22), "shavuot"),
    (date(2026, 7, 23), "tisha_bav"),
    (date(2026, 9, 12), "rosh_hashanah"),
    (date(2026, 9, 21), "yom_kippur"),
    (date(2026, 9, 26), "sukkot"),
    (date(2026, 10, 3), "shemini_atzeret"),
    (date(2026, 10, 4), "simchat_torah"),
    (date(2026, 12, 5), "hanukkah"),
]

YEARS = sorted({y for y, _m in PUBLISHED_MONTHS})


class TestMonthStarts:
    @pytest.mark.parametrize("ym", sorted(PUBLISHED_MONTHS))
    def test_every_month_of_5780_through_5790(self, ym):
        assert month_start(*ym) == PUBLISHED_MONTHS[ym]

    @pytest.mark.parametrize("ym", sorted(PUBLISHED_MONTHS))
    def test_the_first_reads_back_as_the_first(self, ym):
        assert hebrew_date(PUBLISHED_MONTHS[ym]) == (*ym, 1)

    def test_the_table_has_every_month(self):
        for year in YEARS:
            months = {m for y, m in PUBLISHED_MONTHS if y == year}
            assert months == set(range(1, 14 if is_leap_year(year) else 13))

    def test_leap_years(self):
        assert [y for y in YEARS if is_leap_year(y)] == [5782, 5784, 5787, 5790]

    def test_month_lengths_follow_the_table(self):
        # Each month runs to the day before the next one starts.
        ordered = sorted(PUBLISHED_MONTHS.items(),
                         key=lambda item: item[1])
        for (ym, start), (_nxt, nxt_start) in zip(ordered, ordered[1:]):
            assert days_in_month(*ym) == (nxt_start - start).days

    def test_year_lengths(self):
        # Six lengths are possible, 353 to 385; these eleven years
        # show every one of them.
        assert [days_in_year(y) for y in YEARS] == [
            355, 353, 384, 355, 383, 355, 354, 385, 355, 354, 383]
        for y in YEARS:
            assert days_in_year(y) == (
                month_start(y + 1, 7) - month_start(y, 7)).days


class TestDates:
    def test_a_day_in_elul(self):
        assert hebrew_date(date(2026, 9, 2)) == (5786, 6, 20)
        assert hebrew_date_label(5786, 6, 20) == "20 Elul 5786"

    def test_the_last_day_of_the_year(self):
        assert hebrew_date(date(2026, 9, 11)) == (5786, 6, 29)
        assert hebrew_date(date(2026, 9, 12)) == (5787, 7, 1)

    def test_every_day_of_a_decade_round_trips(self):
        day = date(2019, 9, 30)
        while day < date(2030, 9, 28):
            y, m, d = hebrew_date(day)
            assert 1 <= d <= days_in_month(y, m)
            assert month_start(y, m) + timedelta(days=d - 1) == day
            day += timedelta(days=1)

    def test_the_two_adars(self):
        # 5787 is a leap year: Adar I then Adar II; 5786 has one Adar.
        assert hebrew_month_name(5787, 12) == "Adar I"
        assert hebrew_month_name(5787, 13) == "Adar II"
        assert hebrew_month_name(5786, 12) == "Adar"
        assert hebrew_date_label(5787, 13, 14) == "14 Adar II 5787"

    def test_next_month(self):
        assert next_month_start(date(2026, 9, 2)) == (date(2026, 9, 12),
                                                       (5787, 7))
        # Adar I is followed by Adar II, and Adar II by Nisan.
        assert next_month_start(date(2027, 3, 1)) == (date(2027, 3, 10),
                                                       (5787, 13))
        assert next_month_start(date(2027, 3, 10)) == (date(2027, 4, 8),
                                                       (5787, 1))

    def test_rosh_chodesh(self):
        # Tishrei 5787 has thirty days, so Rosh Chodesh Cheshvan is
        # two days, 30 Tishrei and 1 Cheshvan; Tishrei itself has none.
        assert rosh_chodesh(date(2026, 10, 11)) == (5787, 8)
        assert rosh_chodesh(date(2026, 10, 12)) == (5787, 8)
        assert rosh_chodesh(date(2026, 10, 13)) is None
        assert rosh_chodesh(date(2026, 9, 12)) is None
        assert rosh_chodesh_label(5787, 8) == "Rosh Chodesh Cheshvan"


class TestHebrewLetters:
    """The date in letters, as Hebcal writes it."""

    @pytest.mark.parametrize("n,letters", [
        (1, "א׳"), (9, "ט׳"), (10, "י׳"), (11, "י״א"), (14, "י״ד"),
        (15, "ט״ו"), (16, "ט״ז"), (17, "י״ז"), (20, "כ׳"), (23, "כ״ג"),
        (29, "כ״ט"), (30, "ל׳"),
    ])
    def test_the_days_of_a_month(self, n, letters):
        assert hebrew_numeral(n) == letters

    @pytest.mark.parametrize("year,letters", [
        (5780, "תש״פ"), (5781, "תשפ״א"), (5786, "תשפ״ו"), (5787, "תשפ״ז"),
        (5790, "תש״צ"), (5700, "ת״ש"), (5800, "ת״ת"), (5900, "תת״ק"),
        (5500, "ת״ק"), (6000, "ו׳"),
    ])
    def test_the_years(self, year, letters):
        assert hebrew_year_numeral(year) == letters

    def test_the_date(self):
        assert hebrew_date_hebrew(5786, 6, 20) == "כ׳ אלול תשפ״ו"
        assert hebrew_date_hebrew(5787, 7, 23) == "כ״ג תשרי תשפ״ז"
        assert hebrew_date_hebrew(5787, 12, 1) == "א׳ אדר א׳ תשפ״ז"
        assert hebrew_date_hebrew(5787, 13, 14) == "י״ד אדר ב׳ תשפ״ז"
        assert hebrew_date_hebrew(5786, 12, 15) == "ט״ו אדר תשפ״ו"

    def test_every_month_has_its_name(self):
        # The first of each month of a leap year, month and year.
        names = {hebrew_date_hebrew(5787, m, 1).split(" ", 1)[1]
                 for m in range(1, 14)}
        assert names == {
            "ניסן תשפ״ז", "אייר תשפ״ז", "סיון תשפ״ז", "תמוז תשפ״ז", "אב תשפ״ז",
            "אלול תשפ״ז", "תשרי תשפ״ז", "חשון תשפ״ז", "כסלו תשפ״ז", "טבת תשפ״ז",
            "שבט תשפ״ז", "אדר א׳ תשפ״ז", "אדר ב׳ תשפ״ז",
        }


class TestHolidays:
    @pytest.mark.parametrize("day,key", PUBLISHED_HOLIDAYS)
    def test_every_holiday_of_2023_through_2026(self, day, key):
        assert holiday_key(day) == key
        assert next_holiday(day) == (day, key)
        # From the day before, unless that day is a holiday itself:
        # Simchat Torah follows Shemini Atzeret follows Sukkot.
        if holiday_key(day - timedelta(days=1)) is None:
            assert next_holiday(day - timedelta(days=1)) == (day, key)

    def test_the_table_is_complete(self):
        keys = [key for _day, key in PUBLISHED_HOLIDAYS]
        assert len(keys) == 4 * len(HOLIDAYS)
        for key, *_rest in HOLIDAYS:
            assert keys.count(key) == 4

    def test_the_holidays_run_their_length(self):
        # Sukkot's seven days, then Shemini Atzeret and Simchat Torah;
        # Hanukkah's eight, across the turn of Kislev.
        assert [holiday_key(date(2026, 9, 26) + timedelta(days=n))
                for n in range(9)] == (["sukkot"] * 7
                                       + ["shemini_atzeret", "simchat_torah"])
        assert holiday_key(date(2026, 12, 4)) is None
        assert all(holiday_key(date(2026, 12, 5) + timedelta(days=n))
                   == "hanukkah" for n in range(8))
        assert holiday_key(date(2026, 12, 13)) is None
        # Pesach's eight and Shavuot's two, the diaspora count.
        assert holiday_key(date(2026, 4, 9)) == "pesach"
        assert holiday_key(date(2026, 4, 10)) is None
        assert holiday_key(date(2026, 5, 23)) == "shavuot"
        assert holiday_key(date(2026, 5, 24)) is None

    def test_a_holiday_in_progress_is_the_next(self):
        assert next_holiday(date(2026, 12, 7)) == (date(2026, 12, 5),
                                                    "hanukkah")
        assert next_holiday(date(2026, 12, 13)) == (date(2027, 1, 23),
                                                     "tu_bishvat")

    def test_purim_keeps_to_adar_ii(self):
        assert next_holiday(date(2027, 2, 1)) == (date(2027, 3, 23), "purim")
        assert hebrew_date(date(2027, 3, 23)) == (5787, 13, 14)

    def test_tisha_bav_is_postponed_off_shabbat(self):
        # 9 Av 5782 was Saturday 6 August 2022; the fast was kept on
        # the Sunday.
        assert hebrew_date(date(2022, 8, 6)) == (5782, 5, 9)
        assert holiday_key(date(2022, 8, 6)) is None
        assert holiday_key(date(2022, 8, 7)) == "tisha_bav"

    def test_the_holidays_across_the_new_year(self):
        # From Tisha B'Av the next is Rosh Hashanah, in the year to come.
        assert next_holiday(date(2026, 7, 24)) == (date(2026, 9, 12),
                                                    "rosh_hashanah")

    def test_every_holiday_has_a_name(self):
        assert hebrew_holiday_name("rosh_hashanah") == "Rosh Hashanah"
        assert hebrew_holiday_name("tisha_bav") == "Tisha B'Av"
        for key, *_rest in HOLIDAYS:
            assert hebrew_holiday_name(key)


class TestAfterSunset:
    # The Hebrew day turns at the same sunset the Hijri day does; the
    # helper is _hijri's, and its own tests cover the edges.
    def test_an_evening_in_maine(self):
        eastern = timezone(timedelta(hours=-4))
        assert after_sunset(datetime(2026, 9, 11, 20, 30, tzinfo=eastern),
                            43.68, -70.37)
        assert not after_sunset(datetime(2026, 9, 11, 12, 0, tzinfo=eastern),
                                43.68, -70.37)


class TestPanel:
    """The moon panel's three lines: date, coming month, next holiday."""

    def _lines(self, now):
        from unittest.mock import patch

        from linecast._runtime import RuntimeConfig
        from linecast.moon import render
        runtime = RuntimeConfig(live=False, icons="emoji", lang="en",
                                oneline=False)
        with patch("linecast.moon.get_terminal_size",
                   return_value=(100, 30)):
            out = render(now, 43.68, -70.37, runtime, fullscreen=True,
                         calendar_name="hebrew")
        import re
        return re.sub(r"\x1b\[[0-9;]*m", "", out)

    def test_the_eve_says_begins_at_sunset(self):
        eastern = timezone(timedelta(hours=-4))
        text = self._lines(datetime(2026, 9, 11, 12, 0, tzinfo=eastern))
        assert "29 Elul 5786" in text
        assert "Elul · Tishrei Sep 12 (in 1d)" in text
        assert "Rosh Hashanah Sep 12 (begins at sunset)" in text

    def test_the_evening_is_already_the_holiday(self):
        eastern = timezone(timedelta(hours=-4))
        text = self._lines(datetime(2026, 9, 11, 20, 30, tzinfo=eastern))
        assert "1 Tishrei 5787" in text
        assert "Tishrei · Cheshvan Oct 12 (in 31d)" in text
        assert "Rosh Hashanah" in text and "Sep 12" not in text

    def test_a_week_out_counts_the_days(self):
        eastern = timezone(timedelta(hours=-4))
        text = self._lines(datetime(2026, 9, 13, 20, 30, tzinfo=eastern))
        assert "3 Tishrei 5787" in text
        assert "Yom Kippur Sep 21 (in 8d)" in text
