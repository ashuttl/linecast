"""The lunisolar calendar against published dates.

Anchors are festival and leap-month dates as the official calendars
print them — the Chinese calendar at UTC+8, the Korean at UTC+9, the
Vietnamese at UTC+7 — plus solar-term days. The engine derives everything from the ephemeris, so
these are end-to-end checks of the month, day, and leap arithmetic.
"""

from datetime import date, datetime, timedelta, timezone

from linecast._ephemeris import next_moon_phase_utc
from linecast._calendars.lunisolar import (
    CALENDAR_MERIDIAN_HOURS,
    CALENDAR_OF_LANG,
    calendar_is_native,
    _civil,
    current_term,
    lunisolar_date,
    next_lunar_event,
    next_term,
    sun_crossing_utc,
)
from linecast._moon.i18n import (
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

    def test_tet_2007_came_a_day_before_the_chinese_new_year(self):
        # The new moon of 17 February 2007 fell at 16:14 UTC: 23:14 in
        # Hanoi, 00:14 the next day in Beijing.
        assert lunisolar_date(date(2007, 2, 17), 7) == (1, 1, False)
        assert lunisolar_date(date(2007, 2, 17), 8) == (12, 30, False)
        assert lunisolar_date(date(2007, 2, 18), 8) == (1, 1, False)

    def test_tet_1985_came_a_month_before_the_chinese_new_year(self):
        # The December 1984 solstice fell at 16:23 UTC, on the 21st in
        # Hanoi and the 22nd in Beijing, the day of a new moon: the
        # month that began that day held the solstice at UTC+8 and
        # was month 11 there, and month 12 at UTC+7.
        assert lunisolar_date(date(1985, 1, 21), 7) == (1, 1, False)
        assert lunisolar_date(date(1985, 1, 21), 8) == (12, 1, False)
        assert lunisolar_date(date(1985, 2, 20), 8) == (1, 1, False)

    def test_hung_kings_day_2026(self):
        assert lunisolar_date(date(2026, 4, 26), 7) == (3, 10, False)

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

    def test_every_month_begins_on_the_day_of_a_new_moon(self):
        # The whole calendar rests on this: a month starts on the civil
        # day that holds the conjunction at the calendar's own meridian.
        # The consecutive-days sweep above would not notice a month
        # starting a day either side of one.
        for meridian in (7, 8, 9):
            tz = timezone(timedelta(hours=meridian))
            first = date(2020, 1, 1)
            for offset in range(1100):
                day = first + timedelta(days=offset)
                if lunisolar_date(day, meridian)[1] != 1:
                    continue
                midnight = datetime(day.year, day.month, day.day, tzinfo=tz)
                new_moon = next_moon_phase_utc(
                    midnight - timedelta(days=2), 0.0)
                assert midnight <= new_moon.astimezone(tz) < (
                    midnight + timedelta(days=1)), (meridian, day)


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
        assert term_label(18, "vi") == "Đông chí"


class TestFestivals:
    def test_next_festival_is_mid_autumn(self):
        got = next_lunar_event(date(2026, 9, 1), 8,
                               festival_table("chinese", "zh"))
        assert got == (date(2026, 9, 25), "中秋节")

    def test_english_names_for_other_languages(self):
        got = next_lunar_event(date(2026, 9, 1), 8,
                               festival_table("chinese", "en"))
        assert got == (date(2026, 9, 25), "Mid-Autumn Festival")

    def test_korean_new_year(self):
        got = next_lunar_event(date(2026, 1, 1), 9,
                               festival_table("korean", "ko"))
        assert got == (date(2026, 2, 17), "설날")

    def test_vietnamese_festivals(self):
        # A week before Tết the Kitchen Gods leave for heaven.
        got = next_lunar_event(date(2026, 1, 1), 7,
                               festival_table("vietnamese", "vi"))
        assert got == (date(2026, 2, 10), "Ông Táo về trời")
        got = next_lunar_event(date(2026, 2, 11), 7,
                               festival_table("vietnamese", "vi"))
        assert got == (date(2026, 2, 17), "Tết Nguyên Đán")
        got = next_lunar_event(date(2026, 4, 1), 7,
                               festival_table("vietnamese", "en"))
        assert got == (date(2026, 4, 26), "Hùng Kings' Day")

    def test_a_festival_today_still_shows(self):
        got = next_lunar_event(date(2026, 9, 25), 8,
                               festival_table("chinese", "zh"))
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

    def test_vietnamese_reads_as_the_wall_calendars_print_it(self):
        assert lunar_date_label(1, 1, False, "vi") == "mùng 1 tháng Giêng âm lịch"
        assert lunar_date_label(8, 15, False, "vi") == "rằm tháng 8 âm lịch"
        assert lunar_date_label(7, 20, False, "vi") == "ngày 20 tháng 7 âm lịch"
        assert lunar_date_label(6, 5, True, "vi") == "mùng 5 tháng 6 nhuận âm lịch"
        assert lunar_date_label(12, 23, False, "vi") == "ngày 23 tháng Chạp âm lịch"

    def test_vietnamese_month_marks_for_the_grid(self):
        from linecast._moon.i18n import vi_month_label
        assert vi_month_label(1, False, short=True) == "Giêng"
        assert vi_month_label(8, False, short=True) == "thg 8"
        assert vi_month_label(6, True, short=True) == "thg 6 nhuận"
        assert vi_month_label(12, False, short=True) == "Chạp"

    def test_english_serves_every_other_language(self):
        assert lunar_date_label(7, 20, False, "en") == "month 7 day 20"
        assert lunar_date_label(6, 5, True, "fr") == "leap month 6 day 5"
        assert term_label(10, "en") == "End of Heat"
        assert term_label(10, "de") == "End of Heat"

    def test_every_calendar_has_names_and_a_meridian(self):
        # The Thai calendar is arithmetic (see _calendars.thai_lunar and
        # test_thai_lunar), so it carries no meridian or solar terms.
        for lang, cal in CALENDAR_OF_LANG.items():
            if cal == "thai":
                continue
            assert cal in CALENDAR_MERIDIAN_HOURS
            assert calendar_is_native(cal, lang)
            native = festival_table(cal, lang)
            english = festival_table(cal, "en")
            assert native and set(native) == set(english)
            assert all(not name.isascii() for name in native.values()) or lang == "vi"
            assert term_label(0, lang)
        assert not calendar_is_native("chinese", "ja")
        assert not calendar_is_native("japanese", "zh-Hant")

    def test_the_chinese_calendar_reads_in_either_script(self):
        assert calendar_is_native("chinese", "zh") and calendar_is_native("chinese", "zh-Hant")
        assert lunar_date_label(1, 1, False, "zh-Hant") == "農曆正月初一"
        assert lunar_date_label(6, 5, True, "zh-Hant") == "農曆閏六月初五"
        assert lunar_date_label(12, 21, False, "zh-Hant") == "農曆臘月廿一"
        assert lunar_date_label(11, 11, False, "zh-Hant") == "農曆冬月十一"
        assert term_label(2, "zh") == "谷雨" and term_label(2, "zh-Hant") == "穀雨"
        assert term_label(23, "zh-Hant") == "驚蟄"
        assert festival_table("chinese", "zh-Hant")[(8, 15)] == "中秋節"
        assert festival_table("chinese", "zh")[(8, 15)] == "中秋节"
        assert festival_table("chinese", "en")[(8, 15)] == "Mid-Autumn Festival"
        assert festival_table("chinese", "fr")[(8, 15)] == "Mid-Autumn Festival"


class TestResolveCalendar:
    def test_flag_beats_saved_beats_language(self):
        from linecast._config import read_config, write_config
        from linecast._calendars.lunisolar import resolve_calendar
        original = read_config()
        try:
            assert resolve_calendar(None, "en") is None
            assert resolve_calendar(None, "zh") == "chinese"
            assert resolve_calendar(None, "zh-Hant") == "chinese"
            assert resolve_calendar(None, "vi") == "vietnamese"
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
        from linecast._moon.i18n import ja_night_name
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
        from linecast._moon.i18n import ja_night_name
        names = [ja_night_name(d) for d in range(1, 31)]
        assert len(set(names)) == 30
