"""The Thai lunar calendar against published dates.

Anchors are the Buddhist holy days (วันพระ) and festivals of 2023-2026
as Thailand published them — official public holidays and the printed
วันพระ calendars. The engine is pure arithmetic, so these pin the whole
chain: year type (normal, extra-day, extra-month), month numbering, and
the waxing/waning day count.
"""

from datetime import date

from linecast._moon_i18n import (
    thai_festival_name, thai_lunar_label, thai_year_label, wan_phra_label,
)
from linecast._thai_lunar import (
    _festival_key, cs_year, is_wan_phra, next_thai_festival, next_wan_phra,
    thai_lunar_date, year_animal_index,
)


class TestThaiLunarDate:
    def test_wan_phra_of_january_2026(self):
        # The printed calendar: ขึ้น 15 and แรม 8, 15 of month 2, then
        # ขึ้น 8 of month 3.
        assert thai_lunar_date(date(2026, 1, 3)) == (2, 15, False)
        assert thai_lunar_date(date(2026, 1, 11)) == (2, 23, False)
        assert thai_lunar_date(date(2026, 1, 18)) == (2, 30, False)
        assert thai_lunar_date(date(2026, 1, 26)) == (3, 8, False)

    def test_athikamat_year_2569_doubles_the_eighth_month(self):
        # Visakha moved to month 7, and Asalha to the doubled eighth.
        assert thai_lunar_date(date(2026, 5, 31)) == (7, 15, False)
        assert thai_lunar_date(date(2026, 7, 29)) == (8, 15, True)

    def test_athikawan_year_2568_keeps_single_months(self):
        assert thai_lunar_date(date(2025, 5, 11)) == (6, 15, False)
        assert thai_lunar_date(date(2025, 7, 10)) == (8, 15, False)
        assert thai_lunar_date(date(2025, 11, 5)) == (12, 15, False)

    def test_athikamat_year_2566(self):
        assert thai_lunar_date(date(2023, 6, 3)) == (7, 15, False)
        assert thai_lunar_date(date(2023, 8, 1)) == (8, 15, True)
        assert thai_lunar_date(date(2023, 11, 27)) == (12, 15, False)

    def test_normal_year_2567(self):
        assert thai_lunar_date(date(2024, 5, 22)) == (6, 15, False)
        assert thai_lunar_date(date(2024, 7, 20)) == (8, 15, False)
        assert thai_lunar_date(date(2024, 11, 15)) == (12, 15, False)

    def test_consecutive_days_stay_consecutive(self):
        prev = thai_lunar_date(date(2026, 1, 1))
        for offset in range(1, 800):
            day = date(2026, 1, 1).fromordinal(
                date(2026, 1, 1).toordinal() + offset)
            cur = thai_lunar_date(day)
            if cur[1] != 1:
                assert cur[1] == prev[1] + 1, day
            else:
                assert prev[1] in (29, 30), day
            prev = cur

    def test_cs_year_turns_at_songkran(self):
        assert cs_year(date(2026, 3, 3)) == 1387
        assert cs_year(date(2026, 9, 1)) == 1388


class TestWanPhra:
    def test_the_four_days_of_a_month(self):
        days = [d for d in range(1, 32) if is_wan_phra(date(2026, 1, d))]
        assert days == [3, 11, 18, 26]

    def test_next_wan_phra_lands_on_one(self):
        found = next_wan_phra(date(2026, 1, 4))
        assert found == date(2026, 1, 11)
        assert next_wan_phra(found) == found


class TestFestivals:
    # Official public-holiday dates as Thailand announced them.
    ANCHORS = {
        date(2023, 3, 6): "makha",       # deferred to month 4 by 2566's ๘๘
        date(2024, 2, 24): "makha",      # month 3 again in a normal year
        date(2025, 2, 12): "makha",
        date(2026, 3, 3): "makha",       # deferred again by 2569's ๘๘
        date(2026, 5, 31): "visakha",
        date(2026, 7, 29): "asalha",
        date(2026, 7, 30): "khao_phansa",
        date(2025, 10, 7): "ok_phansa",
        date(2026, 10, 26): "ok_phansa",
        date(2025, 11, 5): "loy_krathong",
        date(2026, 11, 24): "loy_krathong",
        date(2026, 4, 13): "songkran",
    }

    def test_published_dates(self):
        for day, key in self.ANCHORS.items():
            assert _festival_key(day) == key, day

    def test_a_deferred_makha_leaves_month_three_bare(self):
        # 2569's month-3 full moon (February 2nd) holds no festival;
        # Makha waits for month 4.
        assert thai_lunar_date(date(2026, 2, 2))[1:] == (15, False)
        assert _festival_key(date(2026, 2, 2)) is None

    def test_next_festival_walks_to_the_right_day(self):
        assert next_thai_festival(date(2026, 9, 1)) == \
            (date(2026, 10, 26), "ok_phansa")
        assert next_thai_festival(date(2026, 10, 27)) == \
            (date(2026, 11, 24), "loy_krathong")


class TestLabels:
    def test_native_labels_keep_thai_numerals(self):
        assert thai_lunar_label(9, 19, False, "th") == "แรม ๔ ค่ำ เดือน ๙"
        assert thai_lunar_label(8, 16, True, "th") == "แรม ๑ ค่ำ เดือน ๘๘"

    def test_first_two_months_keep_their_archaic_names(self):
        # เดือนอ้าย and เดือนยี่, as the printed calendars have them.
        assert thai_lunar_label(1, 1, False, "th") == "ขึ้น ๑ ค่ำ เดือนอ้าย"
        assert thai_lunar_label(2, 15, False, "th") == "ขึ้น ๑๕ ค่ำ เดือนยี่"

    def test_english_serves_every_other_language(self):
        assert thai_lunar_label(9, 19, False, "en") == "month 9 · waning 4"
        assert thai_lunar_label(8, 15, True, "en") == "month 8/8 · waxing 15"

    def test_year_animal(self):
        # 2569 (CS 1388) is ปีมะเมีย, the horse.
        idx = year_animal_index(date(2026, 9, 1))
        assert thai_year_label(idx, "th") == "ปีมะเมีย"
        assert thai_year_label(idx, "en") == "Year of the Horse"

    def test_festival_and_wan_phra_names(self):
        assert thai_festival_name("loy_krathong", "th") == "ลอยกระทง"
        assert thai_festival_name("loy_krathong", "en") == "Loy Krathong"
        assert wan_phra_label(False, "th") == "วันพระ"
        assert wan_phra_label(True, "en") == "Wan Phra today"
