"""Tests for the `moon --json` machine-readable payload."""

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Ensure the worktree src is preferred over any installed version.
# (No sys.modules purge here: this file is collected after other test
# modules that hold references into already-imported linecast modules.)
_src = str(Path(__file__).resolve().parent.parent / "src")
if _src not in sys.path:
    sys.path.insert(0, _src)

from linecast._moon_json import build_payload
from linecast._runtime import RuntimeConfig, moon_parser
from linecast.moon import moon_illumination, upcoming_moon_events
from linecast.sunshine import (
    _EMOJI_ICONS,
    _NERD_ICONS,
    SYNODIC_MONTH,
    moon_cycle_frac,
)

LAT, LNG = 43.68, -70.35  # Portland, Maine-ish
FIXED_NOW = datetime(2026, 8, 14, 12, 0, tzinfo=timezone.utc)

EXPECTED_TOP_KEYS = {
    "schema", "location", "timezone", "fetched_at", "phase", "icon",
    "illumination", "waxing", "age_days", "events", "next_full",
    "next_full_name", "next_new", "day_of_year", "days_in_year",
    "next_season_event", "southern", "altitude_deg", "azimuth_deg",
    "up_now", "calendar",
}


def _runtime(**overrides):
    defaults = dict(live=False, icons="nerd", lang="en", oneline=False)
    defaults.update(overrides)
    return RuntimeConfig(**defaults)


def _payload(**kwargs):
    defaults = dict(
        now_local=FIXED_NOW, lat=LAT, lng=LNG, runtime=_runtime(),
        location="Testville",
    )
    defaults.update(kwargs)
    return build_payload(**defaults)


class TestPayloadShape:
    def test_top_level_keys_exact(self):
        assert set(_payload().keys()) == EXPECTED_TOP_KEYS

    def test_round_trips_through_json(self):
        payload = _payload()
        text = json.dumps(payload, ensure_ascii=False)
        assert json.loads(text) == payload

    def test_schema_and_identity(self):
        p = _payload()
        assert p["schema"] == 1
        assert p["location"] == "Testville"
        assert p["fetched_at"] == "2026-08-14T12:00"


class TestPhase:
    def test_phase_matches_module(self):
        frac = moon_cycle_frac(FIXED_NOW)
        p = _payload()
        assert p["waxing"] == (frac < 0.5)
        assert p["illumination"] == round(moon_illumination(FIXED_NOW) * 100, 1)
        assert 0 <= p["illumination"] <= 100
        # Age is time since the last new moon, not the phase angle scaled
        # by a mean month, so the two agree only to within the Moon's own
        # unevenness — most of a day at the extremes.
        assert abs(p["age_days"] - frac * SYNODIC_MONTH) < 1.0

    def test_age_is_measured_from_the_last_new_moon(self):
        from linecast._ephemeris import next_moon_phase_utc

        last_new = next_moon_phase_utc(FIXED_NOW, 0.0, backwards=True)
        elapsed = (FIXED_NOW - last_new).total_seconds() / 86400.0
        assert _payload()["age_days"] == round(elapsed, 1)

    def test_phase_name_localized(self):
        en = _payload()["phase"]
        fr = _payload(runtime=_runtime(lang="fr"))["phase"]
        assert isinstance(en, str) and en
        assert fr != en  # French names differ from English

    def test_nerd_icon_by_default_emoji_on_request(self):
        assert _payload()["icon"] in _NERD_ICONS["moon_icons"]
        p = _payload(runtime=_runtime(icons="emoji"))
        assert p["icon"] in _EMOJI_ICONS["moon_icons"]


class TestEvents:
    def test_events_chronological(self):
        events = _payload()["events"]
        times = [e["time"] for e in events]
        assert times == sorted(times)
        assert all(e["kind"] in ("rise", "set") for e in events)

    def test_events_match_module_and_are_future(self):
        rise, sset = upcoming_moon_events(FIXED_NOW, LAT, LNG)
        expected = sorted(
            dt.strftime("%Y-%m-%dT%H:%M")
            for dt in (rise, sset) if dt is not None
        )
        events = _payload()["events"]
        assert [e["time"] for e in events] == expected
        for e in events:
            assert datetime.fromisoformat(e["time"]) > FIXED_NOW.replace(tzinfo=None)

    def test_typically_one_rise_and_one_set(self):
        kinds = sorted(e["kind"] for e in _payload()["events"])
        assert kinds == ["rise", "set"]


class TestAlmanac:
    def test_next_full_and_new_are_dates_within_a_cycle(self):
        p = _payload()
        for key in ("next_full", "next_new"):
            d = datetime.strptime(p[key], "%Y-%m-%d").date()
            ahead = (d - FIXED_NOW.date()).days
            assert 0 <= ahead <= 31

    def test_full_and_new_ordering_matches_phase(self):
        p = _payload()
        frac = moon_cycle_frac(FIXED_NOW)
        if frac < 0.5:  # waxing: full comes before new
            assert p["next_full"] <= p["next_new"]
        else:
            assert p["next_new"] <= p["next_full"]


class TestHemisphereAndAltitude:
    def test_northern_observer(self):
        assert _payload()["southern"] is False

    def test_southern_observer(self):
        assert _payload(lat=-33.9, lng=151.2)["southern"] is True

    def test_altitude_is_a_number(self):
        p = _payload()
        assert isinstance(p["altitude_deg"], float)
        assert -90 <= p["altitude_deg"] <= 90
        assert isinstance(p["up_now"], bool)

    def test_azimuth_is_a_bearing(self):
        p = _payload()
        assert isinstance(p["azimuth_deg"], float)
        assert 0 <= p["azimuth_deg"] < 360

    def test_azimuth_swings_east_to_west_while_up(self):
        """The Moon crosses the sky one way: rising east, setting west.

        Sampled across a night it should climb to a maximum altitude near
        due south (northern hemisphere) with the bearing increasing
        through it, which is the property a compass hint depends on.
        """
        from linecast._ephemeris import _moon_altitude_deg, _moon_azimuth_deg

        samples = []
        for hour in range(24):
            t = FIXED_NOW.replace(hour=hour)
            alt = _moon_altitude_deg(t, LAT, LNG)
            if alt > 5.0:
                samples.append((hour, _moon_azimuth_deg(t, LAT, LNG)))
        assert len(samples) >= 3, "expected the Moon up for part of the day"
        bearings = [az for _h, az in samples]
        assert bearings == sorted(bearings), bearings
        # Well above the horizon it is south of the observer, never north.
        assert all(45 < az < 315 for az in bearings), bearings


class TestLiveSuppression:
    def test_json_flag_forces_live_off(self):
        args = moon_parser().parse_args(["--json", "--live"])
        runtime = RuntimeConfig.from_sources(namespace=args)
        assert runtime.json_mode is True
        assert runtime.live is False

    def test_json_mode_defaults_false(self):
        args = moon_parser().parse_args(["--print"])
        runtime = RuntimeConfig.from_sources(namespace=args)
        assert runtime.json_mode is False


class TestCalendarBlock:
    """The lunisolar calendar in the payload, resolved like the panel."""

    MOMENT = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)

    def test_null_by_default_in_english(self):
        assert _payload()["calendar"] is None

    def test_native_block_for_chinese(self):
        payload = _payload(now_local=self.MOMENT, runtime=_runtime(lang="zh"))
        cal = payload["calendar"]
        assert cal["name"] == "chinese"
        assert (cal["month"], cal["day"], cal["leap_month"]) == (7, 20, False)
        assert cal["label"] == "农历七月二十"
        assert cal["solar_term"] == "处暑"
        assert cal["next_solar_term"] == {"name": "白露", "date": "2026-09-07"}
        assert cal["next_festival"] == {"name": "中秋节", "date": "2026-09-25"}

    def test_english_names_with_the_flag(self):
        payload = _payload(now_local=self.MOMENT, calendar="chinese")
        cal = payload["calendar"]
        assert cal["label"] == "month 7 day 20"
        assert cal["solar_term"] == "End of Heat"
        assert cal["next_festival"]["name"] == "Mid-Autumn Festival"

    def test_none_flag_wins_over_the_language(self):
        payload = _payload(now_local=self.MOMENT,
                           runtime=_runtime(lang="zh"), calendar="none")
        assert payload["calendar"] is None


class TestAlmanacCalendarBlock:
    def test_gardening_half_matches_the_phase(self):
        payload = _payload(calendar="almanac")
        block = payload["calendar"]
        assert block["name"] == "almanac"
        assert block["gardening"] == ("light" if payload["waxing"] else "dark")

    def test_solunar_periods_are_todays_times(self):
        block = _payload(calendar="almanac")["calendar"]
        for key in ("solunar_major", "solunar_minor"):
            times = block[key]
            assert 1 <= len(times) <= 2
            assert times == sorted(times)
            for stamp in times:
                dt = datetime.fromisoformat(stamp)
                assert dt.date() == FIXED_NOW.date()


class TestMoonTransits:
    def test_upper_transit_crosses_the_meridian(self):
        from linecast._ephemeris import (
            _moon_azimuth_deg, _moon_altitude_deg,
            _moon_transits_for_local_date,
        )
        upper, lower = _moon_transits_for_local_date(
            FIXED_NOW.date(), LNG, timezone.utc)
        assert upper is not None
        azimuth = _moon_azimuth_deg(upper.astimezone(timezone.utc), LAT, LNG)
        assert min(azimuth, 360 - azimuth) > 90  # southern half of the sky
        assert abs(((azimuth - 180) + 180) % 360 - 180) < 2.0
        if lower is not None:
            up_alt = _moon_altitude_deg(upper.astimezone(timezone.utc), LAT, LNG)
            low_alt = _moon_altitude_deg(lower.astimezone(timezone.utc), LAT, LNG)
            assert up_alt > low_alt


class TestJapaneseNightName:
    def test_the_night_follows_the_old_calendars_day(self):
        moment = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
        payload = _payload(now_local=moment, runtime=_runtime(lang="ja"))
        cal = payload["calendar"]
        assert cal["day"] == 20
        assert cal["night_name"] == "更待月"

    def test_other_calendars_have_no_night_name(self):
        moment = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
        payload = _payload(now_local=moment, runtime=_runtime(lang="zh"))
        assert payload["calendar"]["night_name"] is None


class TestOtherPacificBlocks:
    def test_the_samoan_block_names_the_night(self):
        # Sep 1 2026 is the twentieth night of the month begun Aug 13,
        # per the printed 2026 American Samoa calendar.
        moment = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
        payload = _payload(now_local=moment, calendar="samoan")
        assert payload["calendar"] == {
            "name": "samoan",
            "night": 20,
            "nights_in_month": 29,
            "night_name": "Masina Sulutele",
        }

    def test_the_cnmi_block_carries_the_refaluwasch_name(self):
        # Aug 31 2026 is the eighteenth night of the month begun Aug 14,
        # Ketai’ Empe’ / Ara on the printed CNMI page.
        moment = datetime(2026, 8, 31, 12, 0, tzinfo=timezone.utc)
        payload = _payload(now_local=moment, calendar="refaluwasch")
        block = payload["calendar"]
        assert block["night_name"] == "Ketai’ Empe’"
        assert block["refaluwasch_name"] == "Ara"
        payload = _payload(now_local=moment, calendar="chamorro")
        assert "refaluwasch_name" not in payload["calendar"]
        assert payload["calendar"]["night_name"] == "Ketai’ Empe’"


class TestIslamicCalendarBlock:
    def test_the_block_reads_the_umm_al_qura_date(self):
        # Midday on 13 March 2026 is 24 Ramadan 1447; the next
        # observance is Laylat al-Qadr on the 16th, and Shawwal begins
        # on the 20th, Eid al-Fitr.
        moment = datetime(2026, 3, 13, 16, 0, tzinfo=timezone.utc)
        payload = _payload(now_local=moment, calendar="islamic")
        assert payload["calendar"] == {
            "name": "islamic",
            "year": 1447,
            "month": 9,
            "month_name": "Ramadan",
            "day": 24,
            "days_in_month": 30,
            "label": "24 Ramadan 1447 AH",
            "after_sunset": False,
            "next_month": {"name": "Shawwal", "date": "2026-03-20"},
            "next_observance": {"name": "Laylat al-Qadr",
                                "date": "2026-03-16"},
        }

    def test_the_date_turns_at_sunset(self):
        # Half past eight in the evening in Maine, 19 March: the Hijri
        # day is already 1 Shawwal, while Eid's civil date is tomorrow.
        eastern = timezone(timedelta(hours=-4))
        moment = datetime(2026, 3, 19, 20, 30, tzinfo=eastern)
        payload = _payload(now_local=moment, calendar="islamic")
        block = payload["calendar"]
        assert block["after_sunset"] is True
        assert block["label"] == "1 Shawwal 1447 AH"
        assert block["next_observance"] == {"name": "Eid al-Fitr",
                                            "date": "2026-03-20"}
        assert block["next_month"]["name"] == "Dhu al-Qaʻdah"

    def test_indonesian_names(self):
        moment = datetime(2026, 3, 13, 16, 0, tzinfo=timezone.utc)
        payload = _payload(now_local=moment, calendar="islamic",
                           runtime=_runtime(lang="id"))
        block = payload["calendar"]
        assert block["label"] == "24 Ramadan 1447 H"
        assert block["next_observance"]["name"] == "Lailatulqadar"


class TestHebrewCalendarBlock:
    def test_the_block_reads_the_hebrew_date(self):
        # Midday on 2 September 2026 is 20 Elul 5786; Tishrei and Rosh
        # Hashanah come on the 12th.
        moment = datetime(2026, 9, 2, 16, 0, tzinfo=timezone.utc)
        payload = _payload(now_local=moment, calendar="hebrew")
        assert payload["calendar"] == {
            "name": "hebrew",
            "year": 5786,
            "leap_year": False,
            "days_in_year": 354,
            "month": 6,
            "month_name": "Elul",
            "day": 20,
            "days_in_month": 29,
            "label": "20 Elul 5786",
            "hebrew_label": "כ׳ אלול תשפ״ו",
            "after_sunset": False,
            "holiday": None,
            "next_month": {"name": "Tishrei", "date": "2026-09-12"},
            "next_holiday": {"name": "Rosh Hashanah",
                             "date": "2026-09-12"},
        }

    def test_the_date_turns_at_sunset(self):
        # Half past eight on the evening of 11 September in Maine: the
        # year has turned, and Rosh Hashanah has begun, while its
        # civil date is tomorrow.
        eastern = timezone(timedelta(hours=-4))
        moment = datetime(2026, 9, 11, 20, 30, tzinfo=eastern)
        payload = _payload(now_local=moment, calendar="hebrew")
        block = payload["calendar"]
        assert block["after_sunset"] is True
        assert block["label"] == "1 Tishrei 5787"
        assert block["leap_year"] is True
        assert block["holiday"] == "Rosh Hashanah"
        assert block["next_holiday"] == {"name": "Rosh Hashanah",
                                         "date": "2026-09-12"}
        assert block["next_month"] == {"name": "Cheshvan",
                                       "date": "2026-10-12"}

    def test_a_holiday_in_progress(self):
        moment = datetime(2026, 12, 7, 16, 0, tzinfo=timezone.utc)
        block = _payload(now_local=moment, calendar="hebrew")["calendar"]
        assert block["label"] == "27 Kislev 5787"
        assert block["holiday"] == "Hanukkah"
        assert block["next_holiday"] == {"name": "Hanukkah",
                                         "date": "2026-12-05"}


class TestHawaiianCalendarBlock:
    def test_the_calendar_carries_the_councils_counsel(self):
        # The 20th night, Lāʻaupau, has no kapu note; the poepoe
        # counsel and the attribution carry the block.
        moment = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
        payload = _payload(now_local=moment, calendar="hawaiian")
        counsel = payload["calendar"]["counsel"]
        assert counsel["night_note"] is None
        assert counsel["anahulu"].startswith("Poepoe nights")
        assert counsel["source"] == (
            "Western Pacific Regional Fishery Management Council")

    def test_the_kaulana_mahina_names_the_night(self):
        # Sep 1 2026 is the twentieth night of the month begun Aug 13,
        # per the printed 2026 Kaulana Mahina.
        moment = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
        payload = _payload(now_local=moment, calendar="hawaiian")
        block = dict(payload["calendar"])
        assert block.pop("counsel")["anahulu"].startswith("Poepoe nights")
        assert block == {
            "name": "hawaiian",
            "night": 20,
            "nights_in_month": 30,
            "night_name": "Lāʻaupau",
            "anahulu": "poepoe",
        }
