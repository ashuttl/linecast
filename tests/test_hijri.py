"""The Islamic calendar against the published Umm al-Qura tables.

The ground truth is the Umm al-Qura calendar as Saudi Arabia prints
it: every month start of 1440 through 1449 AH (September 2018 to
April 2028), and the observances of 2023 through 2026 as that calendar
places them — not as the religious authorities later announced them,
which sometimes differs by a day after a reported sighting. The
engine evaluates the calendar's rule at Mecca from the ephemeris, so
these are end-to-end checks that the conjunction times, the Mecca
sunsets, and the calibrated moonset cutoff land every month where the
printed table does. The one month the rule and the table disagree on
is pinned as a departure.
"""

from datetime import date, datetime, timedelta, timezone

import pytest

from linecast._hijri import (
    OBSERVANCES,
    RULE_EPOCH,
    _tabular_start,
    after_sunset,
    days_in_month,
    hijri_date,
    month_start,
    next_month_start,
    next_observance,
    observance_key,
)
from linecast._moon_i18n import (
    hijri_date_label, hijri_month_name, hijri_observance_name,
)

# (year, month) AH → the civil date of its first day, from the
# published Umm al-Qura calendar.
PUBLISHED_MONTHS = {
    (1440, 1): date(2018, 9, 11),
    (1440, 2): date(2018, 10, 10),
    (1440, 3): date(2018, 11, 9),
    (1440, 4): date(2018, 12, 8),
    (1440, 5): date(2019, 1, 7),
    (1440, 6): date(2019, 2, 6),
    (1440, 7): date(2019, 3, 8),
    (1440, 8): date(2019, 4, 6),
    (1440, 9): date(2019, 5, 6),
    (1440, 10): date(2019, 6, 4),
    (1440, 11): date(2019, 7, 4),
    (1440, 12): date(2019, 8, 2),
    (1441, 1): date(2019, 8, 31),
    (1441, 2): date(2019, 9, 30),
    (1441, 3): date(2019, 10, 29),
    (1441, 4): date(2019, 11, 28),
    (1441, 5): date(2019, 12, 27),
    (1441, 6): date(2020, 1, 26),
    (1441, 7): date(2020, 2, 25),
    (1441, 8): date(2020, 3, 25),
    (1441, 9): date(2020, 4, 24),
    (1441, 10): date(2020, 5, 24),
    (1441, 11): date(2020, 6, 22),
    (1441, 12): date(2020, 7, 22),
    (1442, 1): date(2020, 8, 20),
    (1442, 2): date(2020, 9, 18),
    (1442, 3): date(2020, 10, 18),
    (1442, 4): date(2020, 11, 16),
    (1442, 5): date(2020, 12, 16),
    (1442, 6): date(2021, 1, 14),
    (1442, 7): date(2021, 2, 13),
    (1442, 8): date(2021, 3, 14),
    (1442, 9): date(2021, 4, 13),
    (1442, 10): date(2021, 5, 13),
    (1442, 11): date(2021, 6, 11),
    (1442, 12): date(2021, 7, 11),
    (1443, 1): date(2021, 8, 9),
    (1443, 2): date(2021, 9, 8),
    (1443, 3): date(2021, 10, 7),
    (1443, 4): date(2021, 11, 6),
    (1443, 5): date(2021, 12, 5),
    (1443, 6): date(2022, 1, 4),
    (1443, 7): date(2022, 2, 2),
    (1443, 8): date(2022, 3, 4),
    (1443, 9): date(2022, 4, 2),
    (1443, 10): date(2022, 5, 2),
    (1443, 11): date(2022, 5, 31),
    (1443, 12): date(2022, 6, 30),
    (1444, 1): date(2022, 7, 30),
    (1444, 2): date(2022, 8, 28),
    (1444, 3): date(2022, 9, 27),
    (1444, 4): date(2022, 10, 26),
    (1444, 5): date(2022, 11, 25),
    (1444, 6): date(2022, 12, 25),
    (1444, 7): date(2023, 1, 23),
    (1444, 8): date(2023, 2, 21),
    (1444, 9): date(2023, 3, 23),
    (1444, 10): date(2023, 4, 21),
    (1444, 11): date(2023, 5, 21),
    (1444, 12): date(2023, 6, 19),
    (1445, 1): date(2023, 7, 19),
    (1445, 2): date(2023, 8, 17),
    (1445, 3): date(2023, 9, 16),
    (1445, 4): date(2023, 10, 16),
    (1445, 5): date(2023, 11, 15),
    (1445, 6): date(2023, 12, 14),
    (1445, 7): date(2024, 1, 13),
    (1445, 8): date(2024, 2, 11),
    (1445, 9): date(2024, 3, 11),
    (1445, 10): date(2024, 4, 10),
    (1445, 11): date(2024, 5, 9),
    (1445, 12): date(2024, 6, 7),
    (1446, 1): date(2024, 7, 7),
    (1446, 2): date(2024, 8, 5),
    (1446, 3): date(2024, 9, 4),
    (1446, 4): date(2024, 10, 4),
    (1446, 5): date(2024, 11, 3),
    (1446, 6): date(2024, 12, 2),
    (1446, 7): date(2025, 1, 1),
    (1446, 8): date(2025, 1, 31),
    (1446, 9): date(2025, 3, 1),
    (1446, 10): date(2025, 3, 30),
    (1446, 11): date(2025, 4, 29),
    (1446, 12): date(2025, 5, 28),
    (1447, 1): date(2025, 6, 26),
    (1447, 2): date(2025, 7, 26),
    (1447, 3): date(2025, 8, 24),
    (1447, 4): date(2025, 9, 23),
    (1447, 5): date(2025, 10, 23),
    (1447, 6): date(2025, 11, 22),
    (1447, 7): date(2025, 12, 21),
    (1447, 8): date(2026, 1, 20),
    (1447, 9): date(2026, 2, 18),
    (1447, 10): date(2026, 3, 20),
    (1447, 11): date(2026, 4, 18),
    (1447, 12): date(2026, 5, 18),
    (1448, 1): date(2026, 6, 16),
    (1448, 2): date(2026, 7, 15),
    (1448, 3): date(2026, 8, 14),
    (1448, 4): date(2026, 9, 12),
    (1448, 5): date(2026, 10, 12),
    (1448, 6): date(2026, 11, 11),
    (1448, 7): date(2026, 12, 10),
    (1448, 8): date(2027, 1, 9),
    (1448, 9): date(2027, 2, 8),
    (1448, 10): date(2027, 3, 9),
    (1448, 11): date(2027, 4, 8),
    (1448, 12): date(2027, 5, 7),
    (1449, 1): date(2027, 6, 6),
    (1449, 2): date(2027, 7, 5),
    (1449, 3): date(2027, 8, 3),
    (1449, 4): date(2027, 9, 2),
    (1449, 5): date(2027, 10, 1),
    (1449, 6): date(2027, 10, 31),
    (1449, 7): date(2027, 11, 29),
    (1449, 8): date(2027, 12, 29),
    (1449, 9): date(2028, 1, 28),
    (1449, 10): date(2028, 2, 26),
    (1449, 11): date(2028, 3, 27),
    (1449, 12): date(2028, 4, 26),
}


# The observances of 2023–2026 by the published calendar.
PUBLISHED_OBSERVANCES = {
    date(2023, 3, 23): "ramadan",   # 1444 AH
    date(2023, 4, 18): "qadr",   # 1444 AH
    date(2023, 4, 21): "eid_fitr",   # 1444 AH
    date(2023, 6, 27): "arafah",   # 1444 AH
    date(2023, 6, 28): "eid_adha",   # 1444 AH
    date(2023, 7, 19): "new_year",   # 1445 AH
    date(2023, 7, 28): "ashura",   # 1445 AH
    date(2023, 9, 27): "mawlid",   # 1445 AH
    date(2024, 3, 11): "ramadan",   # 1445 AH
    date(2024, 4, 6): "qadr",   # 1445 AH
    date(2024, 4, 10): "eid_fitr",   # 1445 AH
    date(2024, 6, 15): "arafah",   # 1445 AH
    date(2024, 6, 16): "eid_adha",   # 1445 AH
    date(2024, 7, 7): "new_year",   # 1446 AH
    date(2024, 7, 16): "ashura",   # 1446 AH
    date(2024, 9, 15): "mawlid",   # 1446 AH
    date(2025, 3, 1): "ramadan",   # 1446 AH
    date(2025, 3, 27): "qadr",   # 1446 AH
    date(2025, 3, 30): "eid_fitr",   # 1446 AH
    date(2025, 6, 5): "arafah",   # 1446 AH
    date(2025, 6, 6): "eid_adha",   # 1446 AH
    date(2025, 6, 26): "new_year",   # 1447 AH
    date(2025, 7, 5): "ashura",   # 1447 AH
    date(2025, 9, 4): "mawlid",   # 1447 AH
    date(2026, 2, 18): "ramadan",   # 1447 AH
    date(2026, 3, 16): "qadr",   # 1447 AH
    date(2026, 3, 20): "eid_fitr",   # 1447 AH
    date(2026, 5, 26): "arafah",   # 1447 AH
    date(2026, 5, 27): "eid_adha",   # 1447 AH
    date(2026, 6, 16): "new_year",   # 1448 AH
    date(2026, 6, 25): "ashura",   # 1448 AH
    date(2026, 8, 25): "mawlid",   # 1448 AH
}


class TestPublishedMonths:
    @pytest.mark.parametrize("ym,start", sorted(PUBLISHED_MONTHS.items()),
                             ids=lambda v: f"{v[0]}-{v[1]:02d}"
                             if isinstance(v, tuple) else v.isoformat())
    def test_month_starts_where_the_table_does(self, ym, start):
        year, month = ym
        assert month_start(year, month) == start
        assert hijri_date(start) == (year, month, 1)
        assert hijri_date(start - timedelta(days=1))[2] in (29, 30)

    def test_the_one_known_departure(self):
        # Jumada al-Thani 1427: the conjunction of 25 June 2006 fell five
        # minutes before Mecca's sunset by this ephemeris and after it
        # by the table's, so the table gives Jumada al-Ula thirty days
        # and the engine twenty-nine. A finer ephemeris would move this
        # month, and nothing else, onto the table.
        assert month_start(1427, 6) == date(2006, 6, 26)

    def test_consecutive_days_stay_consecutive(self):
        # Across the seam between the tabular calendar and the rule.
        first = date(2001, 6, 1)
        prev = hijri_date(first)
        for offset in range(1, 800):
            cur = hijri_date(first + timedelta(days=offset))
            if cur[2] != 1:
                assert cur == (prev[0], prev[1], prev[2] + 1), first + timedelta(days=offset)
            else:
                assert prev[2] in (29, 30)
                assert (cur[0], cur[1]) == (
                    (prev[0], prev[1] + 1) if prev[1] < 12 else (prev[0] + 1, 1))
            prev = cur

    def test_the_rule_begins_at_muharram_1423(self):
        assert hijri_date(RULE_EPOCH) == (1423, 1, 1)
        assert hijri_date(RULE_EPOCH - timedelta(days=1)) == (1422, 12, 29)

    def test_the_tabular_calendar_before_the_rule(self):
        # 1 Muharram 1 AH is Friday 16 July 622 (Julian), and the
        # tabular 1 Muharram 1423 is the rule's own first day.
        assert _tabular_start(-1422 * 12) == date(622, 7, 19)
        assert _tabular_start(0) == RULE_EPOCH
        # Eleven leap years of 355 days in each thirty-year cycle.
        lengths = [(_tabular_start((y + 1) * 12 - 1422 * 12)
                    - _tabular_start(y * 12 - 1422 * 12)).days
                   for y in range(1, 31)]
        assert sorted(set(lengths)) == [354, 355]
        assert lengths.count(355) == 11

    def test_month_lengths_and_the_next_month(self):
        # Ramadan 1447 runs thirty days, Shawwal twenty-nine.
        assert days_in_month(date(2026, 3, 1)) == 30
        assert next_month_start(date(2026, 3, 1)) == (date(2026, 3, 20), (1447, 10))
        assert days_in_month(date(2026, 3, 20)) == 29


class TestObservances:
    @pytest.mark.parametrize("day,key", sorted(PUBLISHED_OBSERVANCES.items()),
                             ids=lambda v: v.isoformat() if isinstance(v, date) else v)
    def test_published_dates(self, day, key):
        assert observance_key(day) == key
        assert next_observance(day) == (day, key)

    def test_every_observance_is_reached(self):
        seen = set()
        day = date(2025, 6, 26)
        for _ in range(8):
            day, key = next_observance(day)
            seen.add(key)
            day += timedelta(days=1)
        assert seen == set(OBSERVANCES.values())

    def test_next_observance_walks_to_the_right_day(self):
        assert next_observance(date(2026, 9, 2)) == (date(2027, 2, 8), "ramadan")
        assert next_observance(date(2026, 3, 21)) == (date(2026, 5, 26), "arafah")


class TestAfterSunset:
    ET = timezone(timedelta(hours=-4))

    def test_the_day_turns_at_sunset(self):
        # Portland, Maine, mid-March: sunset a little before 19:00.
        assert not after_sunset(datetime(2026, 3, 19, 14, 0, tzinfo=self.ET), 43.7, -70.3)
        assert after_sunset(datetime(2026, 3, 19, 20, 30, tzinfo=self.ET), 43.7, -70.3)

    def test_the_small_hours_are_still_last_nights_day(self):
        assert not after_sunset(datetime(2026, 3, 19, 3, 0, tzinfo=self.ET), 43.7, -70.3)

    def test_no_location_keeps_the_civil_date(self):
        assert not after_sunset(datetime(2026, 3, 19, 20, 30, tzinfo=self.ET), None, None)


class TestLabels:
    def test_the_date_as_customarily_written(self):
        assert hijri_date_label(1447, 9, 23, "en") == "23 Ramadan 1447 AH"
        assert hijri_date_label(1447, 12, 10, "fr") == "10 Dhu al-Hijjah 1447 AH"

    def test_indonesian_spellings(self):
        assert hijri_date_label(1447, 10, 1, "id") == "1 Syawal 1447 H"
        assert hijri_month_name(3, "id") == "Rabiulawal"
        assert hijri_observance_name("eid_adha", "id") == "Iduladha"

    def test_observance_names(self):
        assert hijri_observance_name("qadr", "en") == "Laylat al-Qadr"
        assert hijri_observance_name("ramadan", "de") == "Ramadan begins"


class TestPanel:
    """The moon panel's observance line around Eid al-Fitr 1447."""

    def _text(self, now):
        import re
        from unittest.mock import patch

        from linecast._runtime import RuntimeConfig
        from linecast.moon import render
        runtime = RuntimeConfig(live=False, icons="emoji", lang="en",
                                oneline=False)
        with patch("linecast.moon.get_terminal_size",
                   return_value=(100, 30)):
            out = render(now, 43.68, -70.37, runtime, fullscreen=True,
                         calendar_name="islamic")
        return re.sub(r"\x1b\[[0-9;]*m", "", out)

    def test_the_eve_says_begins_at_sunset(self):
        eastern = timezone(timedelta(hours=-4))
        text = self._text(datetime(2026, 3, 19, 12, 0, tzinfo=eastern))
        assert "30 Ramadan 1447 AH" in text
        assert "Ramadan · Shawwal Mar 20 (in 1d)" in text
        assert "Eid al-Fitr Mar 20 (begins at sunset)" in text

    def test_the_evening_is_already_the_observance(self):
        eastern = timezone(timedelta(hours=-4))
        text = self._text(datetime(2026, 3, 19, 20, 30, tzinfo=eastern))
        assert "1 Shawwal 1447 AH" in text
        assert "Eid al-Fitr" in text and "Eid al-Fitr Mar 20" not in text

    def test_the_next_evening_has_moved_on(self):
        eastern = timezone(timedelta(hours=-4))
        text = self._text(datetime(2026, 3, 20, 20, 30, tzinfo=eastern))
        assert "2 Shawwal 1447 AH" in text
        assert "Day of Arafah May 26 (in 67d)" in text
