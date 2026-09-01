"""The lunisolar calendar against published dates.

Anchors are festival and leap-month dates as the official calendars
print them — the Chinese calendar at UTC+8, the Korean at UTC+9 — plus
solar-term days. The engine derives everything from the ephemeris, so
these are end-to-end checks of the month, day, and leap arithmetic.
"""

from datetime import date, datetime, timezone

from linecast._lunisolar import (
    CALENDAR_MERIDIAN_HOURS,
    CALENDAR_NATIVE_LANG,
    _civil,
    current_term,
    lunisolar_date,
    next_lunar_event,
    next_term,
    sun_crossing_utc,
)
from linecast._moon_i18n import (
    festival_table,
    lunar_date_label,
    term_label,
)


class TestLunisolarDate:
    def test_chinese_new_year_2026(self):
        assert lunisolar_date(date(2026, 2, 17), 8) == (1, 1, False)

    def test_mid_autumn_2026(self):
        assert lunisolar_date(date(2026, 9, 25), 8) == (8, 15, False)

    def test_duanwu_2024(self):
        assert lunisolar_date(date(2024, 6, 10), 8) == (5, 5, False)

    def test_leap_sixth_month_2025(self):
        # 闰六月 began July 25, 2025, after a thirty-day sixth month.
        assert lunisolar_date(date(2025, 7, 24), 8) == (6, 30, False)
        assert lunisolar_date(date(2025, 7, 25), 8) == (6, 1, True)

    def test_leap_second_month_2023(self):
        assert lunisolar_date(date(2023, 3, 22), 8) == (2, 1, True)

    def test_chuseok_2025_at_the_korean_meridian(self):
        assert lunisolar_date(date(2025, 10, 6), 9) == (8, 15, False)

    def test_consecutive_days_stay_consecutive(self):
        prev = lunisolar_date(date(2026, 1, 1), 8)
        for offset in range(1, 400):
            d = date.fromordinal(date(2026, 1, 1).toordinal() + offset)
            cur = lunisolar_date(d, 8)
            if cur[1] == 1:
                assert prev[1] in (29, 30)
            else:
                assert cur[1] == prev[1] + 1
                assert (cur[0], cur[2]) == (prev[0], prev[2])
            prev = cur


class TestSolarTerms:
    def test_terms_around_september_2026(self):
        now = datetime(2026, 9, 1, 4, 0, tzinfo=timezone.utc)
        cur_k, cur_start = current_term(now)
        nxt_k, nxt_start = next_term(now)
        assert term_label(cur_k, "zh") == "处暑"
        assert _civil(cur_start, 8) == date(2026, 8, 23)
        assert term_label(nxt_k, "zh") == "白露"
        assert _civil(nxt_start, 8) == date(2026, 9, 7)

    def test_winter_solstice_2026_day(self):
        ws = sun_crossing_utc(
            datetime(2026, 12, 1, tzinfo=timezone.utc), 270.0)
        assert _civil(ws, 8) == date(2026, 12, 22)

    def test_term_names_line_up_across_languages(self):
        # Index 18 is the December solstice in every table.
        assert term_label(18, "zh") == "冬至"
        assert term_label(18, "ja") == "冬至"
        assert term_label(18, "ko") == "동지"


class TestFestivals:
    def test_next_festival_is_mid_autumn(self):
        got = next_lunar_event(date(2026, 9, 1), 8,
                               festival_table("chinese", native=True))
        assert got == (date(2026, 9, 25), "中秋节")

    def test_english_names_for_other_languages(self):
        got = next_lunar_event(date(2026, 9, 1), 8,
                               festival_table("chinese", native=False))
        assert got == (date(2026, 9, 25), "Mid-Autumn Festival")

    def test_korean_new_year(self):
        got = next_lunar_event(date(2026, 1, 1), 9,
                               festival_table("korean", native=True))
        assert got == (date(2026, 2, 17), "설날")

    def test_a_festival_today_still_shows(self):
        got = next_lunar_event(date(2026, 9, 25), 8,
                               festival_table("chinese", native=True))
        assert got == (date(2026, 9, 25), "中秋节")

    def test_festivals_skip_the_leap_month(self):
        # From July 2025 the nearest first-of-a-sixth-month is 闰六月初一
        # (July 25), but a leap month carries no festivals: the event
        # waits for the real sixth month of the following year.
        got = next_lunar_event(date(2025, 7, 1), 8, {(6, 1): "x"})
        assert got == (date(2026, 7, 14), "x")


class TestLabels:
    def test_chinese_month_and_day_names(self):
        assert lunar_date_label(1, 1, False, "zh") == "农历正月初一"
        assert lunar_date_label(7, 20, False, "zh") == "农历七月二十"
        assert lunar_date_label(6, 5, True, "zh") == "农历闰六月初五"
        assert lunar_date_label(11, 11, False, "zh") == "农历冬月十一"
        assert lunar_date_label(12, 21, False, "zh") == "农历腊月廿一"
        assert lunar_date_label(12, 30, False, "zh") == "农历腊月三十"

    def test_japanese_and_korean_formats(self):
        assert lunar_date_label(7, 20, False, "ja") == "旧暦7月20日"
        assert lunar_date_label(7, 20, True, "ja") == "旧暦閏7月20日"
        assert lunar_date_label(7, 20, False, "ko") == "음력 7월 20일"
        assert lunar_date_label(7, 20, True, "ko") == "음력 윤7월 20일"

    def test_english_serves_every_other_language(self):
        assert lunar_date_label(7, 20, False, "en") == "month 7 day 20"
        assert lunar_date_label(6, 5, True, "fr") == "leap month 6 day 5"
        assert term_label(10, "en") == "End of Heat"
        assert term_label(10, "de") == "End of Heat"

    def test_every_calendar_has_names_and_a_meridian(self):
        for cal, lang in CALENDAR_NATIVE_LANG.items():
            assert cal in CALENDAR_MERIDIAN_HOURS
            assert festival_table(cal, native=True)
            assert festival_table(cal, native=False)
            assert term_label(0, lang)


class TestResolveCalendar:
    def test_flag_beats_saved_beats_language(self):
        from linecast._config import read_config, write_config
        from linecast._lunisolar import resolve_calendar
        original = read_config()
        try:
            assert resolve_calendar(None, "en") is None
            assert resolve_calendar(None, "zh") == "chinese"
            assert resolve_calendar("korean", "zh") == "korean"
            assert resolve_calendar("none", "zh") is None

            saved = dict(original, calendar="japanese")
            write_config(saved)
            assert resolve_calendar(None, "en") == "japanese"
            assert resolve_calendar(None, "zh") == "japanese"
            assert resolve_calendar("chinese", "en") == "chinese"

            write_config(dict(original, calendar="none"))
            assert resolve_calendar(None, "zh") is None
        finally:
            write_config(original)


class TestJapaneseNightNames:
    def test_the_named_nights(self):
        from linecast._moon_i18n import ja_night_name
        assert ja_night_name(3) == "三日月"
        assert ja_night_name(13) == "十三夜"
        assert ja_night_name(15) == "十五夜"
        assert ja_night_name(16) == "十六夜"
        assert [ja_night_name(d) for d in (17, 18, 19, 20)] == [
            "立待月", "居待月", "寝待月", "更待月"]
        assert ja_night_name(23) == "二十三夜"
        assert ja_night_name(26) == "二十六夜"
        assert ja_night_name(30) == "三十日月"

    def test_every_night_of_a_long_month_has_a_name(self):
        from linecast._moon_i18n import ja_night_name
        names = [ja_night_name(d) for d in range(1, 31)]
        assert len(set(names)) == 30
