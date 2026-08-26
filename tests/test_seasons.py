"""Equinox/solstice instants and traditional full moon names."""

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from linecast._seasons import (  # noqa: E402
    DECEMBER_SOLSTICE,
    JUNE_SOLSTICE,
    MARCH_EQUINOX,
    SEPTEMBER_EQUINOX,
    full_moon_name,
    next_season_event,
    season_event_utc,
)

SYNODIC = 29.530588  # matches linecast.sunshine.SYNODIC_MONTH closely enough


def _utc(*args):
    return datetime(*args, tzinfo=timezone.utc)


class TestSeasonEvents:
    # Published almanac times (UTC); the series should land within a few
    # minutes, which the display rounds away entirely.
    KNOWN = [
        (2000, MARCH_EQUINOX, _utc(2000, 3, 20, 7, 35)),
        (2000, JUNE_SOLSTICE, _utc(2000, 6, 21, 1, 48)),
        (2000, SEPTEMBER_EQUINOX, _utc(2000, 9, 22, 17, 28)),
        (2000, DECEMBER_SOLSTICE, _utc(2000, 12, 21, 13, 37)),
        (2024, MARCH_EQUINOX, _utc(2024, 3, 20, 3, 6)),
        (2024, JUNE_SOLSTICE, _utc(2024, 6, 20, 20, 51)),
        (2024, SEPTEMBER_EQUINOX, _utc(2024, 9, 22, 12, 44)),
        (2024, DECEMBER_SOLSTICE, _utc(2024, 12, 21, 9, 20)),
    ]

    def test_known_instants(self, subtests):
        for year, event, expected in self.KNOWN:
            with subtests.test(year=year, event=event):
                got = season_event_utc(year, event)
                assert abs((got - expected).total_seconds()) < 15 * 60

    def test_next_event_walks_the_year(self):
        event, when = next_season_event(_utc(2026, 8, 25))
        assert event == SEPTEMBER_EQUINOX
        assert when.date().isoformat() == "2026-09-23"

    def test_next_event_wraps_to_next_year(self):
        event, when = next_season_event(_utc(2026, 12, 25))
        assert event == MARCH_EQUINOX
        assert when.year == 2027


class TestFullMoonNames:
    def test_month_names(self):
        assert full_moon_name(_utc(2026, 1, 3), SYNODIC) == "Wolf"
        assert full_moon_name(_utc(2026, 8, 28), SYNODIC) == "Sturgeon"

    def test_harvest_is_nearest_the_september_equinox(self):
        # 2026: full moon Sep 26 is 3 days from the Sep 23 equinox.
        assert full_moon_name(_utc(2026, 9, 26, 16), SYNODIC) == "Harvest"
        # 2020: the Oct 1 full moon was nearer the equinox than Sep 2's.
        assert full_moon_name(_utc(2020, 10, 1, 21), SYNODIC) == "Harvest"
        assert full_moon_name(_utc(2020, 9, 2, 5), SYNODIC) == "Corn"

    def test_hunters_follows_harvest(self):
        assert full_moon_name(_utc(2026, 10, 26, 4), SYNODIC) == "Hunter's"
        # 2020's Blue Moon on Halloween was also the Hunter's Moon;
        # the seasonal name wins.
        assert full_moon_name(_utc(2020, 10, 31, 14), SYNODIC) == "Hunter's"

    def test_blue_moon_is_second_in_a_month(self):
        # 2023: full moons Aug 1 and Aug 31 — the second is Blue.
        assert full_moon_name(_utc(2023, 8, 31, 1), SYNODIC) == "Blue"
        assert full_moon_name(_utc(2023, 8, 1, 18), SYNODIC) == "Sturgeon"
