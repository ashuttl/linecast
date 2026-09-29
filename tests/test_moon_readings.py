"""moon/readings: one reading per calendar, found by name."""

from datetime import date, datetime, timedelta, timezone

import pytest

from linecast._config import CALENDAR_CHOICES
from linecast._runtime import RuntimeConfig
from linecast.moon.readings import (
    Day, Now, Panel, Reading, begun_at_sunset, context, kept_or_coming, month_span, reading,
)

ET = timezone(timedelta(hours=-4))
NOW = datetime(2026, 9, 1, 14, 30, tzinfo=ET)


def _ctx(cal, lang="en", now=NOW):
    runtime = RuntimeConfig(live=False, icons="emoji", lang=lang, oneline=False)
    return context(now, 43.7, -70.3, runtime, cal)


class TestRegistry:
    def test_no_calendar_has_no_reading(self):
        assert reading(None) is None

    @pytest.mark.parametrize("cal", [c for c in CALENDAR_CHOICES if c != "none"])
    def test_every_calendar_has_its_own(self, cal):
        found = reading(cal)
        assert isinstance(found, Reading) and type(found) is not Reading
        assert found.name == cal
        assert found.json_block(_ctx(cal))["name"] == cal
        assert isinstance(found.panel(_ctx(cal)), Panel)

    @pytest.mark.parametrize("cal,family", [
        ("chinese", "Lunisolar"), ("vietnamese", "Lunisolar"), ("hawaiian", "Pacific"),
        ("refaluwasch", "Pacific"), ("islamic", "Hijri"), ("hebrew", "Hebrew"),
        ("icelandic", "Icelandic"), ("thai", "Thai"), ("almanac", "Almanac"),
    ])
    def test_families(self, cal, family):
        assert type(reading(cal)).__name__ == family

    def test_only_the_almanac_names_the_full_moons(self):
        named = [c for c in CALENDAR_CHOICES if c != "none" and reading(c).full_moon_names]
        assert named == ["almanac"]

    def test_the_night_naming_calendars_give_the_age_plainly(self):
        plain = {c for c in CALENDAR_CHOICES if c != "none" and reading(c).plain_age}
        assert plain == {"hawaiian", "samoan", "chamorro", "refaluwasch"}


class TestContext:
    def test_native_follows_the_language(self):
        assert _ctx("chinese", "zh").native
        assert not _ctx("chinese", "en").native
        assert not _ctx(None, "zh").native

    def test_the_moment_in_utc_and_the_civil_date(self):
        ctx = _ctx("hebrew", now=datetime(2026, 9, 1, 23, 30, tzinfo=ET))
        assert ctx.today == date(2026, 9, 1)
        assert ctx.moment_utc == datetime(2026, 9, 2, 3, 30, tzinfo=timezone.utc)


class TestItems:
    def test_kept_today_or_coming(self):
        today = date(2026, 9, 1)
        assert kept_or_coming("Fest", today, today) == Now("Fest", today=True)
        assert kept_or_coming("Fest", today + timedelta(days=3), today) == \
            Day("Fest", today + timedelta(days=3))

    def test_begun_at_sunset(self):
        ctx = _ctx("hebrew")
        tomorrow = ctx.today + timedelta(days=1)
        # the evening has come: tomorrow's holiday is kept
        assert begun_at_sunset("Rosh Hashanah", tomorrow, tomorrow, ctx) == \
            Now("Rosh Hashanah", today=True)
        # the day before, the wait says it begins at sunset
        eve = begun_at_sunset("Rosh Hashanah", tomorrow, ctx.today, ctx)
        assert eve.day == tomorrow and eve.wait == "begins at sunset"
        later = begun_at_sunset("Sukkot", ctx.today + timedelta(days=5), ctx.today, ctx)
        assert later.wait is None

    def test_month_span(self):
        assert month_span((5786, 12, "Elul"), (5787, 1, "Tishrei")) == "Elul 5786 – Tishrei 5787"
        assert month_span((5787, 1, "Tishrei"), (5787, 2, "Cheshvan")) == "Tishrei – Cheshvan 5787"
        assert month_span((5787, 5, "Shevat"), (5787, 5, "Shevat"), " AH") == "Shevat 5787 AH"
