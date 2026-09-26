"""The traditional hours: the halachic table against Hebcal, and the frame.

The ground truth for the zmanim is Hebcal's zmanim API, read with
seconds on for four places (Jerusalem, Brooklyn, Helsinki at 60°
north, Melbourne) on four dates of 2026 (the March equinox week, both
solstices, and mid-September). Hebcal uses the NOAA sunrise algorithm
and the same angles this table does, 16.1° for alot, 11.5° for
misheyakir, 8.5° for tzeit, so the checks are that the ephemeris,
the crossing solver, and the fractions of the day land within half a
minute of a published table. Hebcal's output is CC BY 4.0.

The rest checks the frame: the reading of a moment, the resolver,
the setting, the corner, and the marks line.
"""

import io
import re
from contextlib import redirect_stdout
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from linecast._hours import (
    DayHours, Mark, day_hours, hours_now, last_mark, next_mark, reading, resolve_hours,
)
from linecast._hours.prayer_times import (
    METHODS, default_method, default_school, prayer_times,
)
from linecast._hours.roman import roman_hours
from linecast._hours.wadokei import wadokei
from linecast._hours.zmanim import zmanim
from linecast._runtime import RuntimeConfig

PLACES = {
    "jerusalem": (31.778, 35.235, "Asia/Jerusalem"),
    "brooklyn": (40.65, -73.95, "America/New_York"),
    "helsinki": (60.17, 24.94, "Europe/Helsinki"),
    "melbourne": (-37.81, 144.96, "Australia/Melbourne"),
}

# (place, date) → Hebcal's zmanim, local time to the second; None where
# the Sun never reaches the angle that day.
PUBLISHED = {
    ("brooklyn", "2026-03-05"): {
        "chatzotNight": "2026-03-05T00:06:58",
        "alotHaShachar": "2026-03-05T05:02:47",
        "misheyakir": "2026-03-05T05:27:04",
        "sunrise": "2026-03-05T06:23:21",
        "sofZmanShmaMGA": "2026-03-05T08:39:26",
        "sofZmanShma": "2026-03-05T09:15:26",
        "sofZmanTfillaMGA": "2026-03-05T09:48:48",
        "sofZmanTfilla": "2026-03-05T10:12:48",
        "chatzot": "2026-03-05T12:07:31",
        "minchaGedola": "2026-03-05T12:36:12",
        "minchaGedolaMGA": "2026-03-05T12:42:12",
        "minchaKetana": "2026-03-05T15:28:17",
        "minchaKetanaMGA": "2026-03-05T16:10:17",
        "plagHaMincha": "2026-03-05T16:39:59",
        "sunset": "2026-03-05T17:51:42",
        "tzeit85deg": "2026-03-05T18:32:15",
        "tzeit72min": "2026-03-05T19:03:42",
    },
    ("brooklyn", "2026-06-21"): {
        "chatzotNight": "2026-06-21T00:57:33",
        "alotHaShachar": "2026-06-21T03:35:56",
        "misheyakir": "2026-06-21T04:12:48",
        "sunrise": "2026-06-21T05:25:01",
        "sofZmanShmaMGA": "2026-06-21T08:35:20",
        "sofZmanShma": "2026-06-21T09:11:20",
        "sofZmanTfillaMGA": "2026-06-21T10:02:46",
        "sofZmanTfilla": "2026-06-21T10:26:46",
        "chatzot": "2026-06-21T12:57:39",
        "minchaGedola": "2026-06-21T13:35:22",
        "minchaGedolaMGA": "2026-06-21T13:41:22",
        "minchaKetana": "2026-06-21T17:21:41",
        "minchaKetanaMGA": "2026-06-21T18:03:41",
        "plagHaMincha": "2026-06-21T18:55:59",
        "sunset": "2026-06-21T20:30:18",
        "tzeit85deg": "2026-06-21T21:20:49",
        "tzeit72min": "2026-06-21T21:42:18",
    },
    ("brooklyn", "2026-09-15"): {
        "chatzotNight": "2026-09-15T00:51:27",
        "alotHaShachar": "2026-09-15T05:14:10",
        "misheyakir": "2026-09-15T05:39:28",
        "sunrise": "2026-09-15T06:36:34",
        "sofZmanShmaMGA": "2026-09-15T09:07:35",
        "sofZmanShma": "2026-09-15T09:43:35",
        "sofZmanTfillaMGA": "2026-09-15T10:21:55",
        "sofZmanTfilla": "2026-09-15T10:45:55",
        "chatzot": "2026-09-15T12:50:36",
        "minchaGedola": "2026-09-15T13:21:46",
        "minchaGedolaMGA": "2026-09-15T13:27:46",
        "minchaKetana": "2026-09-15T16:28:47",
        "minchaKetanaMGA": "2026-09-15T17:10:47",
        "plagHaMincha": "2026-09-15T17:46:43",
        "sunset": "2026-09-15T19:04:39",
        "tzeit85deg": "2026-09-15T19:45:25",
        "tzeit72min": "2026-09-15T20:16:39",
    },
    ("brooklyn", "2026-12-21"): {
        "chatzotNight": "2026-12-20T23:53:44",
        "alotHaShachar": "2026-12-21T05:47:51",
        "misheyakir": "2026-12-21T06:13:33",
        "sunrise": "2026-12-21T07:16:07",
        "sofZmanShmaMGA": "2026-12-21T08:59:02",
        "sofZmanShma": "2026-12-21T09:35:02",
        "sofZmanTfillaMGA": "2026-12-21T09:57:21",
        "sofZmanTfilla": "2026-12-21T10:21:21",
        "chatzot": "2026-12-21T11:53:58",
        "minchaGedola": "2026-12-21T12:17:07",
        "minchaGedolaMGA": "2026-12-21T12:23:07",
        "minchaKetana": "2026-12-21T14:36:02",
        "minchaKetanaMGA": "2026-12-21T15:18:02",
        "plagHaMincha": "2026-12-21T15:33:55",
        "sunset": "2026-12-21T16:31:49",
        "tzeit85deg": "2026-12-21T17:17:17",
        "tzeit72min": "2026-12-21T17:43:49",
    },
    ("helsinki", "2026-03-05"): {
        "chatzotNight": "2026-03-05T00:31:04",
        "alotHaShachar": "2026-03-05T05:03:44",
        "misheyakir": "2026-03-05T05:41:31",
        "sunrise": "2026-03-05T07:07:30",
        "sofZmanShmaMGA": "2026-03-05T09:13:54",
        "sofZmanShma": "2026-03-05T09:49:54",
        "sofZmanTfillaMGA": "2026-03-05T10:20:03",
        "sofZmanTfilla": "2026-03-05T10:44:03",
        "chatzot": "2026-03-05T12:32:19",
        "minchaGedola": "2026-03-05T12:59:23",
        "minchaGedolaMGA": "2026-03-05T13:05:23",
        "minchaKetana": "2026-03-05T15:41:48",
        "minchaKetanaMGA": "2026-03-05T16:23:48",
        "plagHaMincha": "2026-03-05T16:49:28",
        "sunset": "2026-03-05T17:57:09",
        "tzeit85deg": "2026-03-05T18:59:10",
        "tzeit72min": "2026-03-05T19:09:09",
    },
    ("helsinki", "2026-06-21"): {
        "chatzotNight": "2026-06-21T01:21:56",
        "alotHaShachar": None,
        "misheyakir": None,
        "sunrise": "2026-06-21T03:54:03",
        "sofZmanShmaMGA": "2026-06-21T08:02:02",
        "sofZmanShma": "2026-06-21T08:38:02",
        "sofZmanTfillaMGA": "2026-06-21T09:48:42",
        "sofZmanTfilla": "2026-06-21T10:12:42",
        "chatzot": "2026-06-21T13:22:02",
        "minchaGedola": "2026-06-21T14:09:22",
        "minchaGedolaMGA": "2026-06-21T14:15:22",
        "minchaKetana": "2026-06-21T18:53:22",
        "minchaKetanaMGA": "2026-06-21T19:35:22",
        "plagHaMincha": "2026-06-21T20:51:42",
        "sunset": "2026-06-21T22:50:02",
        "tzeit85deg": None,
        "tzeit72min": "2026-06-22T00:02:02",
    },
    ("helsinki", "2026-09-15"): {
        "chatzotNight": "2026-09-15T01:16:18",
        "alotHaShachar": "2026-09-15T04:32:51",
        "misheyakir": "2026-09-15T05:17:00",
        "sunrise": "2026-09-15T06:47:35",
        "sofZmanShmaMGA": "2026-09-15T09:25:10",
        "sofZmanShma": "2026-09-15T10:01:10",
        "sofZmanTfillaMGA": "2026-09-15T10:41:42",
        "sofZmanTfilla": "2026-09-15T11:05:42",
        "chatzot": "2026-09-15T13:14:45",
        "minchaGedola": "2026-09-15T13:47:01",
        "minchaGedolaMGA": "2026-09-15T13:53:01",
        "minchaKetana": "2026-09-15T17:00:36",
        "minchaKetanaMGA": "2026-09-15T17:42:36",
        "plagHaMincha": "2026-09-15T18:21:16",
        "sunset": "2026-09-15T19:41:56",
        "tzeit85deg": "2026-09-15T20:45:32",
        "tzeit72min": "2026-09-15T20:53:56",
    },
    ("helsinki", "2026-12-21"): {
        "chatzotNight": "2026-12-21T00:18:04",
        "alotHaShachar": "2026-12-21T06:52:17",
        "misheyakir": "2026-12-21T07:32:37",
        "sunrise": "2026-12-21T09:23:45",
        "sofZmanShmaMGA": "2026-12-21T10:15:00",
        "sofZmanShma": "2026-12-21T10:51:00",
        "sofZmanTfillaMGA": "2026-12-21T10:56:05",
        "sofZmanTfilla": "2026-12-21T11:20:05",
        "chatzot": "2026-12-21T12:18:16",
        "minchaGedola": "2026-12-21T12:32:48",
        "minchaGedolaMGA": "2026-12-21T12:38:48",
        "minchaKetana": "2026-12-21T14:00:04",
        "minchaKetanaMGA": "2026-12-21T14:42:04",
        "plagHaMincha": "2026-12-21T14:36:25",
        "sunset": "2026-12-21T15:12:47",
        "tzeit85deg": "2026-12-21T16:35:56",
        "tzeit72min": "2026-12-21T16:24:47",
    },
    ("jerusalem", "2026-03-05"): {
        "chatzotNight": "2026-03-04T23:50:24",
        "alotHaShachar": "2026-03-05T04:49:50",
        "misheyakir": "2026-03-05T05:11:29",
        "sunrise": "2026-03-05T06:01:44",
        "sofZmanShmaMGA": "2026-03-05T08:20:15",
        "sofZmanShma": "2026-03-05T08:56:15",
        "sofZmanTfillaMGA": "2026-03-05T09:30:25",
        "sofZmanTfilla": "2026-03-05T09:54:25",
        "chatzot": "2026-03-05T11:50:46",
        "minchaGedola": "2026-03-05T12:19:51",
        "minchaGedolaMGA": "2026-03-05T12:25:51",
        "minchaKetana": "2026-03-05T15:14:22",
        "minchaKetanaMGA": "2026-03-05T15:56:22",
        "plagHaMincha": "2026-03-05T16:27:05",
        "sunset": "2026-03-05T17:39:48",
        "tzeit85deg": "2026-03-05T18:15:59",
        "tzeit72min": "2026-03-05T18:51:48",
    },
    ("jerusalem", "2026-06-21"): {
        "chatzotNight": "2026-06-21T00:40:45",
        "alotHaShachar": "2026-06-21T04:06:18",
        "misheyakir": "2026-06-21T04:34:20",
        "sunrise": "2026-06-21T05:34:03",
        "sofZmanShmaMGA": "2026-06-21T08:31:27",
        "sofZmanShma": "2026-06-21T09:07:27",
        "sofZmanTfillaMGA": "2026-06-21T09:54:35",
        "sofZmanTfilla": "2026-06-21T10:18:35",
        "chatzot": "2026-06-21T12:40:51",
        "minchaGedola": "2026-06-21T13:16:25",
        "minchaGedolaMGA": "2026-06-21T13:22:25",
        "minchaKetana": "2026-06-21T16:49:49",
        "minchaKetanaMGA": "2026-06-21T17:31:49",
        "plagHaMincha": "2026-06-21T18:18:44",
        "sunset": "2026-06-21T19:47:40",
        "tzeit85deg": "2026-06-21T20:29:59",
        "tzeit72min": "2026-06-21T20:59:40",
    },
    ("jerusalem", "2026-09-15"): {
        "chatzotNight": "2026-09-15T00:34:44",
        "alotHaShachar": "2026-09-15T05:10:04",
        "misheyakir": "2026-09-15T05:32:15",
        "sunrise": "2026-09-15T06:22:56",
        "sofZmanShmaMGA": "2026-09-15T08:52:30",
        "sofZmanShma": "2026-09-15T09:28:30",
        "sofZmanTfillaMGA": "2026-09-15T10:06:21",
        "sofZmanTfilla": "2026-09-15T10:30:21",
        "chatzot": "2026-09-15T12:34:04",
        "minchaGedola": "2026-09-15T13:05:00",
        "minchaGedolaMGA": "2026-09-15T13:11:00",
        "minchaKetana": "2026-09-15T16:10:34",
        "minchaKetanaMGA": "2026-09-15T16:52:34",
        "plagHaMincha": "2026-09-15T17:27:53",
        "sunset": "2026-09-15T18:45:13",
        "tzeit85deg": "2026-09-15T19:21:30",
        "tzeit72min": "2026-09-15T19:57:13",
    },
    ("jerusalem", "2026-12-21"): {
        "chatzotNight": "2026-12-20T23:36:50",
        "alotHaShachar": "2026-12-21T05:16:59",
        "misheyakir": "2026-12-21T05:39:55",
        "sunrise": "2026-12-21T06:34:50",
        "sofZmanShmaMGA": "2026-12-21T08:29:57",
        "sofZmanShma": "2026-12-21T09:05:57",
        "sofZmanTfillaMGA": "2026-12-21T09:32:19",
        "sofZmanTfilla": "2026-12-21T09:56:19",
        "chatzot": "2026-12-21T11:37:04",
        "minchaGedola": "2026-12-21T12:02:15",
        "minchaGedolaMGA": "2026-12-21T12:08:15",
        "minchaKetana": "2026-12-21T14:33:22",
        "minchaKetanaMGA": "2026-12-21T15:15:22",
        "plagHaMincha": "2026-12-21T15:36:20",
        "sunset": "2026-12-21T16:39:19",
        "tzeit85deg": "2026-12-21T17:19:04",
        "tzeit72min": "2026-12-21T17:51:19",
    },
    ("melbourne", "2026-03-05"): {
        "chatzotNight": "2026-03-05T01:32:06",
        "alotHaShachar": "2026-03-05T05:47:58",
        "misheyakir": "2026-03-05T06:12:41",
        "sunrise": "2026-03-05T07:08:10",
        "sofZmanShmaMGA": "2026-03-05T09:43:46",
        "sofZmanShma": "2026-03-05T10:19:46",
        "sofZmanTfillaMGA": "2026-03-05T10:59:38",
        "sofZmanTfilla": "2026-03-05T11:23:38",
        "chatzot": "2026-03-05T13:31:22",
        "minchaGedola": "2026-03-05T14:03:18",
        "minchaGedolaMGA": "2026-03-05T14:09:18",
        "minchaKetana": "2026-03-05T17:14:54",
        "minchaKetanaMGA": "2026-03-05T17:56:54",
        "plagHaMincha": "2026-03-05T18:34:44",
        "sunset": "2026-03-05T19:54:35",
        "tzeit85deg": "2026-03-05T20:34:08",
        "tzeit72min": "2026-03-05T21:06:35",
    },
    ("melbourne", "2026-06-21"): {
        "chatzotNight": "2026-06-21T00:21:47",
        "alotHaShachar": "2026-06-21T06:11:15",
        "misheyakir": "2026-06-21T06:35:54",
        "sunrise": "2026-06-21T07:35:38",
        "sofZmanShmaMGA": "2026-06-21T09:22:45",
        "sofZmanShma": "2026-06-21T09:58:45",
        "sofZmanTfillaMGA": "2026-06-21T10:22:28",
        "sofZmanTfilla": "2026-06-21T10:46:28",
        "chatzot": "2026-06-21T12:21:53",
        "minchaGedola": "2026-06-21T12:45:44",
        "minchaGedolaMGA": "2026-06-21T12:51:44",
        "minchaKetana": "2026-06-21T15:08:51",
        "minchaKetanaMGA": "2026-06-21T15:50:51",
        "plagHaMincha": "2026-06-21T16:08:29",
        "sunset": "2026-06-21T17:08:08",
        "tzeit85deg": "2026-06-21T17:51:29",
        "tzeit72min": "2026-06-21T18:20:08",
    },
    ("melbourne", "2026-09-15"): {
        "chatzotNight": "2026-09-15T00:15:24",
        "alotHaShachar": "2026-09-15T05:03:47",
        "misheyakir": "2026-09-15T05:27:13",
        "sunrise": "2026-09-15T06:21:13",
        "sofZmanShmaMGA": "2026-09-15T08:42:31",
        "sofZmanShma": "2026-09-15T09:18:31",
        "sofZmanTfillaMGA": "2026-09-15T09:53:37",
        "sofZmanTfilla": "2026-09-15T10:17:37",
        "chatzot": "2026-09-15T12:15:49",
        "minchaGedola": "2026-09-15T12:45:22",
        "minchaGedolaMGA": "2026-09-15T12:51:22",
        "minchaKetana": "2026-09-15T15:42:40",
        "minchaKetanaMGA": "2026-09-15T16:24:40",
        "plagHaMincha": "2026-09-15T16:56:33",
        "sunset": "2026-09-15T18:10:26",
        "tzeit85deg": "2026-09-15T18:49:18",
        "tzeit72min": "2026-09-15T19:22:26",
    },
    ("melbourne", "2026-12-21"): {
        "chatzotNight": "2026-12-21T01:17:47",
        "alotHaShachar": "2026-12-21T04:14:00",
        "misheyakir": "2026-12-21T04:47:06",
        "sunrise": "2026-12-21T05:54:20",
        "sofZmanShmaMGA": "2026-12-21T09:00:11",
        "sofZmanShma": "2026-12-21T09:36:11",
        "sofZmanTfillaMGA": "2026-12-21T10:26:08",
        "sofZmanTfilla": "2026-12-21T10:50:08",
        "chatzot": "2026-12-21T13:18:02",
        "minchaGedola": "2026-12-21T13:55:00",
        "minchaGedolaMGA": "2026-12-21T14:01:00",
        "minchaKetana": "2026-12-21T17:36:51",
        "minchaKetanaMGA": "2026-12-21T18:18:51",
        "plagHaMincha": "2026-12-21T19:09:17",
        "sunset": "2026-12-21T20:41:44",
        "tzeit85deg": "2026-12-21T21:29:01",
        "tzeit72min": "2026-12-21T21:53:44",
    },
}

# This table's mark → Hebcal's key, by opinion.
GRA_KEYS = {
    "alot": "alotHaShachar", "misheyakir": "misheyakir", "sunrise": "sunrise",
    "shema": "sofZmanShma", "tefillah": "sofZmanTfilla", "chatzot": "chatzot",
    "mincha_gedola": "minchaGedola", "mincha_ketana": "minchaKetana",
    "plag": "plagHaMincha", "sunset": "sunset", "tzeit": "tzeit85deg",
}
MGA_KEYS = {
    "shema": "sofZmanShmaMGA", "tefillah": "sofZmanTfillaMGA",
    "mincha_gedola": "minchaGedolaMGA", "mincha_ketana": "minchaKetanaMGA",
    "tzeit": "tzeit72min",
}
TOLERANCE = timedelta(seconds=30)

_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def _plain(text):
    return _ANSI.sub("", text)


def _runtime(**kw):
    args = dict(live=False, icons="emoji", lang="en", oneline=False, use_24h=False)
    args.update(kw)
    return RuntimeConfig(**args)


def _published(place, day, key):
    text = PUBLISHED[(place, day)][key]
    if text is None:
        return None
    return datetime.fromisoformat(text).replace(tzinfo=ZoneInfo(PLACES[place][2]))


@pytest.mark.parametrize("place,day", sorted(PUBLISHED))
@pytest.mark.parametrize("opinion,keys", [("gra", GRA_KEYS), ("mga", MGA_KEYS)])
def test_zmanim_match_hebcal(place, day, opinion, keys):
    lat, lng, tz = PLACES[place]
    hours = zmanim(date.fromisoformat(day), lat, lng, ZoneInfo(tz), opinion)
    marks = {m.key: m.at for m in hours.marks}
    for key, hebcal_key in keys.items():
        expected = _published(place, day, hebcal_key)
        if expected is None:
            assert key not in marks, f"{key} listed where Hebcal has none"
            continue
        assert key in marks, f"{key} missing"
        assert abs(marks[key] - expected) <= TOLERANCE, (
            f"{key}: {marks[key]:%H:%M:%S} against Hebcal {expected:%H:%M:%S}")


@pytest.mark.parametrize("place,day", sorted(PUBLISHED))
def test_chatzot_halayla_is_listed_on_the_date_it_falls_on(place, day):
    """Hebcal lists the middle of the night leading into the date; the
    table lists whichever middle falls on the date, which is that one
    wherever the zone runs behind its meridian, and the next night's
    where it runs ahead."""
    lat, lng, tz = PLACES[place]
    hours = zmanim(date.fromisoformat(day), lat, lng, ZoneInfo(tz))
    listed = [m.at for m in hours.marks if m.key == "chatzot_halayla"]
    assert len(listed) == 1
    assert listed[0].date() == date.fromisoformat(day)
    expected = _published(place, day, "chatzotNight")
    if expected.date() == date.fromisoformat(day):
        assert abs(listed[0] - expected) <= TOLERANCE


def test_helsinki_in_june_has_no_dawn_or_nightfall():
    """At 60° north in June the Sun never gets 16.1° down, so alot,
    misheyakir, and tzeit are absent; the day's fractions stand."""
    hours = zmanim(date(2026, 6, 21), 60.17, 24.94, ZoneInfo("Europe/Helsinki"))
    keys = [m.key for m in hours.marks]
    assert "alot" not in keys and "misheyakir" not in keys and "tzeit" not in keys
    assert "shema" in keys and "plag" in keys


def test_magen_avraham_pads_the_day_by_seventy_two_minutes():
    tz = ZoneInfo("Asia/Jerusalem")
    gra = zmanim(date(2026, 9, 15), 31.778, 35.235, tz)
    mga = zmanim(date(2026, 9, 15), 31.778, 35.235, tz, "mga")
    assert mga.day_start == gra.day_start - timedelta(minutes=72)
    assert mga.day_end == gra.day_end + timedelta(minutes=72)
    assert mga.variant == "mga"
    marks = {m.key: m.at for m in mga.marks}
    assert marks["alot"] == mga.day_start
    assert marks["tzeit"] == mga.day_end


def test_candle_lighting_on_friday_only():
    tz = ZoneInfo("Asia/Jerusalem")
    friday = zmanim(date(2026, 9, 18), 32.07, 34.78, tz)       # Tel Aviv
    marks = {m.key: m.at for m in friday.marks}
    assert marks["candles"] == marks["sunset"] - timedelta(minutes=18)
    thursday = zmanim(date(2026, 9, 17), 32.07, 34.78, tz)
    assert "candles" not in {m.key for m in thursday.marks}


def test_jerusalem_lights_candles_forty_minutes_before_sunset():
    """The city's custom, and Hebcal's default for it; Tel Aviv and
    Beit Shemesh keep eighteen."""
    from linecast._hours.zmanim import candles_minutes
    tz = ZoneInfo("Asia/Jerusalem")
    friday = zmanim(date(2026, 9, 18), 31.778, 35.235, tz)
    marks = {m.key: m.at for m in friday.marks}
    assert marks["candles"] == marks["sunset"] - timedelta(minutes=40)
    assert candles_minutes(31.778, 35.235) == 40
    assert candles_minutes(31.75, 35.0) == 18          # Beit Shemesh
    assert candles_minutes(32.07, 34.78) == 18         # Tel Aviv
    assert candles_minutes(40.65, -73.95) == 18


def test_polar_night_keeps_no_hours():
    """Longyearbyen in December: no sunrise, so no edges and no marks
    but the night's middle, and the reading is None."""
    tz = ZoneInfo("Arctic/Longyearbyen")
    hours = zmanim(date(2026, 12, 21), 78.22, 15.63, tz)
    assert hours.day_start is None and hours.day_end is None
    assert reading(hours, datetime(2026, 12, 21, 12, tzinfo=tz)) is None


class TestReading:
    TZ = ZoneInfo("Asia/Jerusalem")

    def _hours(self):
        return zmanim(date(2026, 9, 15), 31.778, 35.235, self.TZ)

    def test_an_afternoon_hour(self):
        """Sunrise 6:22:56, sunset 18:45:13: 2:30pm is 8h 07m into a
        day of twelve 61m 51s hours, so the eighth hour, 52/60 through."""
        r = reading(self._hours(), datetime(2026, 9, 15, 14, 30, tzinfo=self.TZ))
        assert not r.night
        assert r.index == 7
        assert int(r.fraction * 60) == 52
        assert round(r.hour_seconds) == 3711

    def test_the_night_after_sunset(self):
        r = reading(self._hours(), datetime(2026, 9, 15, 23, 12, tzinfo=self.TZ))
        assert r.night
        assert r.index == 4
        assert r.end == self._hours().next_day_start

    def test_the_night_before_dawn(self):
        r = reading(self._hours(), datetime(2026, 9, 15, 5, 0, tzinfo=self.TZ))
        assert r.night
        assert r.index == 10
        assert r.start == self._hours().prev_day_end

    def test_a_naive_now_is_the_machines_own_time(self):
        """sunshine passes a naive now for an unpinned location, which
        is the machine's own zone; the reading takes it as such."""
        naive = datetime(2026, 9, 15, 14, 30)
        assert reading(self._hours(), naive) == reading(self._hours(), naive.astimezone())

    def test_next_and_last_marks(self):
        now = datetime(2026, 9, 15, 14, 30, tzinfo=self.TZ)
        assert next_mark(self._hours(), now).key == "mincha_ketana"
        assert last_mark(self._hours(), now).key == "mincha_gedola"
        late = datetime(2026, 9, 15, 23, 59, tzinfo=self.TZ)
        assert next_mark(self._hours(), late) is None

    def test_hours_now_builds_the_table_for_the_moment(self):
        hours, now = hours_now("halachic", datetime(2026, 9, 15, 14, 30),
                               31.778, 35.235, self.TZ, "mga")
        assert hours.date == date(2026, 9, 15)
        assert hours.variant == "mga"
        assert now.tzinfo is not None


class TestResolver:
    def test_flag_beats_everything(self, tmp_path, monkeypatch):
        monkeypatch.setenv("LINECAST_CONFIG_DIR", str(tmp_path))
        assert resolve_hours("halachic-mga") == ("halachic", "mga")
        assert resolve_hours("roman") == ("roman", None)
        assert resolve_hours("none") == (None, None)

    def test_saved_setting_stands_in_for_the_flag(self, tmp_path, monkeypatch):
        monkeypatch.setenv("LINECAST_CONFIG_DIR", str(tmp_path))
        from linecast._config import write_config
        assert resolve_hours(None) == (None, None)
        write_config({"hours": "halachic"})
        assert resolve_hours(None) == ("halachic", None)
        write_config({"hours": "none"})
        assert resolve_hours(None) == (None, None)
        write_config({"hours": "mayan"})
        assert resolve_hours(None) == (None, None)

    def test_swahili_brings_its_own_hours_and_the_rest_bring_none(self, tmp_path, monkeypatch):
        monkeypatch.setenv("LINECAST_CONFIG_DIR", str(tmp_path))
        from linecast._config import write_config
        assert resolve_hours(None, "sw") == ("swahili", None)
        assert resolve_hours(None, "en") == (None, None)
        assert resolve_hours("roman", "sw") == ("roman", None)
        write_config({"hours": "none"})
        assert resolve_hours(None, "sw") == (None, None)
        write_config({"hours": "halachic"})
        assert resolve_hours(None, "sw") == ("halachic", None)


class TestCommand:
    def test_set_show_and_auto(self, tmp_path, monkeypatch):
        monkeypatch.setenv("LINECAST_CONFIG_DIR", str(tmp_path))
        from linecast.settings import hours
        from linecast._config import saved_hours
        out = io.StringIO()
        with redirect_stdout(out):
            hours._cmd_set("halachic")
            hours._cmd_show()
        assert saved_hours() == "halachic"
        assert "halachic  [fixed]" in out.getvalue()
        with redirect_stdout(io.StringIO()):
            hours._cmd_set("none")
        assert saved_hours() == "none"
        out = io.StringIO()
        with redirect_stdout(out):
            hours._cmd_auto()
            hours._cmd_show()
        assert saved_hours() is None
        assert out.getvalue().startswith("Hours set to auto")
        assert "auto  [swahili with --lang sw, else none]" in out.getvalue()

    def test_every_choice_has_a_confirmation(self, tmp_path, monkeypatch):
        monkeypatch.setenv("LINECAST_CONFIG_DIR", str(tmp_path))
        from linecast.settings import hours
        from linecast._runtime import HOURS_CHOICES
        for choice in HOURS_CHOICES:
            out = io.StringIO()
            with redirect_stdout(out):
                hours._cmd_set(choice)
            assert ("turned off" if choice == "none" else choice) in out.getvalue()


class TestPainting:
    TZ = ZoneInfo("Asia/Jerusalem")

    def _hours(self, opinion=None):
        return zmanim(date(2026, 9, 15), 31.778, 35.235, self.TZ, opinion)

    def test_corner_reads_the_hour_and_its_length(self):
        from linecast.sunshine.hours import corner_reading
        now = datetime(2026, 9, 15, 14, 30, tzinfo=self.TZ)
        assert corner_reading(self._hours(), now, _runtime()) == "7:52 · 1h = 62m"
        night = datetime(2026, 9, 15, 23, 12, tzinfo=self.TZ)
        assert corner_reading(self._hours(), night, _runtime()) == "night 4:35 · 1h = 58m"
        assert corner_reading(self._hours(), night, _runtime(lang="fr")).startswith("nuit ")

    def test_line_keeps_the_next_mark_and_fills_in_order(self):
        from linecast.sunshine.hours import hours_line
        now = datetime(2026, 9, 15, 14, 30, tzinfo=self.TZ)
        wide = _plain(hours_line(self._hours(), now, 300, _runtime()))
        assert wide.startswith(
            "chatzot halayla 12:34a · alot 5:10a · misheyakir 5:32a · sunrise 6:22a")
        assert "mincha ketana 4:10p (in 1h 41m)" in wide
        assert wide.endswith('tzeit 7:21p · Gr"a')
        narrow = _plain(hours_line(self._hours(), now, 46, _runtime()))
        assert narrow == "mincha ketana 4:10p (in 1h 41m) · plag 5:27p"
        # Too narrow for plag, but the opinion fits in its place.
        narrower = _plain(hours_line(self._hours(), now, 40, _runtime()))
        assert narrower == 'mincha ketana 4:10p (in 1h 41m) · Gr"a'
        tiny = _plain(hours_line(self._hours(), now, 20, _runtime()))
        assert tiny == ""

    def test_sunrise_and_sunset_yield_to_the_marks(self):
        """The line above names them, so they are the first dropped."""
        from linecast.sunshine.hours import hours_line
        now = datetime(2026, 9, 15, 14, 30, tzinfo=self.TZ)
        line = _plain(hours_line(self._hours(), now, 110, _runtime()))
        assert "sunrise" not in line and "sunset" not in line
        assert "chatzot 12:34p" in line

    def test_the_opinion_is_named_when_it_fits(self):
        from linecast.sunshine.hours import hours_line
        now = datetime(2026, 9, 15, 14, 30, tzinfo=self.TZ)
        assert _plain(hours_line(self._hours("mga"), now, 300, _runtime())).endswith(
            "Magen Avraham")

    def test_the_day_view_paints_both_corners_and_the_line(self):
        from unittest.mock import patch
        from linecast.sunshine.view import render
        now = datetime(2026, 9, 15, 14, 30, tzinfo=self.TZ)
        with patch("linecast.sunshine.view.get_terminal_size", return_value=(80, 24)), \
             patch("linecast.sunshine.solar._local_today", return_value=now.date()):
            out = _plain(render(31.778, 35.235, now.timetuple().tm_yday, 14.5,
                                fullscreen=True, runtime=_runtime(), tz_offset_h=3,
                                location_label="Jerusalem", now=now,
                                hours=self._hours()))
        lines = out.split("\n")
        # Each corner label sits one cell in from its edge of the sky.
        assert lines[0][1:].startswith("7:52 · 1h = 62m")
        assert lines[0][:-1].endswith("Jerusalem · 2:30p")
        assert "mincha ketana 4:10p (in 1h 41m)" in lines[-1]
        assert lines[-1].endswith("? help")
        # The chart gave up a row for the line: 24 rows, two of text.
        assert len(lines) == 24

    def test_the_corners_yield_to_each_other_in_a_narrow_window(self, monkeypatch):
        """At 44 columns a Ramadan reading and the place with its clock
        would meet: the place goes first, then the reading's second
        part, and nothing is cut mid-word."""
        from linecast.sunshine import view as sunshine
        from linecast.sunshine import solar
        from linecast.sunshine.view import render
        tz = ZoneInfo("Asia/Riyadh")
        now = datetime(2026, 3, 5, 12, 0, tzinfo=tz)
        hours, now = hours_now("islamic", now, 21.4225, 39.8262, tz, None, "SA")
        monkeypatch.setattr(solar, "_local_today", lambda: date(2026, 3, 5))
        for cols, expect_place in ((44, False), (80, True)):
            monkeypatch.setattr(sunshine, "get_terminal_size", lambda c=cols: (c, 14))
            out = render(21.4225, 39.8262, 64, 12.0, fullscreen=True,
                         runtime=_runtime(use_24h=True), tz_offset_h=3.0,
                         location_label="Makkah", now=now, hours=hours)
            top = _plain(out.split("\n")[0] if isinstance(out, str) else out[0])
            assert "fast 6h 38m" in top
            assert ("Makkah" in top) == expect_place
            assert "iftar in" not in top or "iftar in 6h 26m" in top

    def test_the_oneline_keeps_the_reading_whole(self):
        from linecast._oneline import sunshine_oneline
        tz = ZoneInfo("Asia/Riyadh")
        now = datetime(2026, 9, 16, 15, 0, tzinfo=tz)
        hours, now = hours_now("islamic", now, 21.4225, 39.8262, tz, None, "SA")
        line = _plain(sunshine_oneline(21.4225, 39.8262, 259, 15.0, _runtime(use_24h=True),
                                       3.0, hours, now))
        assert line.endswith("Dhuhr · Asr in 41m")

    def test_a_marks_only_day_reads_the_interval(self):
        """With no divisions the corner names the marks either side."""
        from linecast.sunshine.hours import corner_reading
        marks = [Mark("sunrise", datetime(2026, 9, 15, 6, 22, tzinfo=self.TZ)),
                 Mark("sunset", datetime(2026, 9, 15, 18, 45, tzinfo=self.TZ))]
        hours = DayHours("halachic", date(2026, 9, 15), None, None, None, None,
                         None, marks, "gra")
        now = datetime(2026, 9, 15, 14, 30, tzinfo=self.TZ)
        assert corner_reading(hours, now, _runtime()) == "sunrise · sunset in 4h 15m"


class TestRoman:
    ROME = ZoneInfo("Europe/Rome")

    def test_the_hour_runs_from_forty_five_to_seventy_five_minutes(self):
        """In Rome an hour was about 45 minutes at the December
        solstice and 75 at the June one."""
        june = reading(roman_hours(date(2026, 6, 21), 41.9, 12.5, self.ROME),
                       datetime(2026, 6, 21, 14, 30, tzinfo=self.ROME))
        december = reading(roman_hours(date(2026, 12, 21), 41.9, 12.5, self.ROME),
                           datetime(2026, 12, 21, 14, 30, tzinfo=self.ROME))
        assert abs(june.hour_seconds / 60 - 75) < 3
        assert abs(december.hour_seconds / 60 - 45) < 3

    def test_the_night_has_four_watches(self):
        hours = roman_hours(date(2026, 6, 21), 41.9, 12.5, self.ROME)
        assert hours.divisions == 12 and hours.night_divisions == 4
        r = reading(hours, datetime(2026, 6, 21, 23, 30, tzinfo=self.ROME))
        assert r.night and r.index == 1
        assert abs(r.hour_seconds - (hours.next_day_start - hours.day_end).total_seconds() / 4) < 1

    def test_names_and_marks(self):
        from linecast.sunshine.hours import corner_reading, hours_line
        hours = roman_hours(date(2026, 6, 21), 41.9, 12.5, self.ROME)
        day = datetime(2026, 6, 21, 14, 30, tzinfo=self.ROME)
        assert corner_reading(hours, day, _runtime()) == "hora octava · 1h = 76m"
        night = datetime(2026, 6, 21, 23, 30, tzinfo=self.ROME)
        assert corner_reading(hours, night, _runtime()) == "vigilia secunda · 1 vigilia = 132m"
        keys = [m.key for m in hours.marks]
        assert keys == ["vigilia_tertia", "vigilia_quarta", "sunrise", "hora_tertia",
                        "hora_sexta", "hora_nona", "sunset", "vigilia_secunda"]
        line = _plain(hours_line(hours, day, 300, _runtime()))
        assert "sexta 1:11p" in line and "nona 5:00p (in 2h 30m)" in line
        assert line.endswith("vigilia II 11:00p")

    def test_hora_sexta_is_the_middle_of_the_day(self):
        hours = roman_hours(date(2026, 6, 21), 41.9, 12.5, self.ROME)
        marks = {m.key: m.at for m in hours.marks}
        middle = hours.day_start + (hours.day_end - hours.day_start) / 2
        assert abs(marks["hora_sexta"] - middle) < timedelta(seconds=1)


class TestWadokei:
    """The National Astronomical Observatory's calculator gives 夜明 and
    日暮 for Tokyo by the 7°21′40″ rule, to the minute."""
    TOKYO = ZoneInfo("Asia/Tokyo")
    LAT, LNG = 35.6895, 139.6917
    PUBLISHED = {
        date(2026, 3, 20): ("05:13", "18:25"),
        date(2026, 6, 21): ("03:47", "19:38"),
        date(2026, 12, 22): ("06:11", "17:08"),
    }

    @pytest.mark.parametrize("day", sorted(PUBLISHED))
    def test_dawn_and_dusk_match_the_observatory(self, day):
        """The observatory prints whole minutes, and its Tokyo is not
        quite this one, so within a minute is the check."""
        hours = wadokei(day, self.LAT, self.LNG, self.TOKYO)
        for at, published in zip((hours.day_start, hours.day_end), self.PUBLISHED[day]):
            h, m = (int(x) for x in published.split(":"))
            expected = datetime(day.year, day.month, day.day, h, m, tzinfo=self.TOKYO)
            assert abs(at - expected) < timedelta(seconds=90), (at, published)

    def test_six_koku_each_way_named_by_their_bells(self):
        hours = wadokei(date(2026, 6, 21), self.LAT, self.LNG, self.TOKYO)
        assert hours.divisions == 6 and hours.night_divisions == 6
        keys = [m.key for m in hours.marks]
        assert keys == ["yoru_yatsu", "akatsuki_nanatsu", "ake_mutsu", "asa_itsutsu",
                        "asa_yotsu", "hiru_kokonotsu", "hiru_yatsu", "yuu_nanatsu",
                        "kure_mutsu", "yoru_itsutsu", "yoru_yotsu", "yoru_kokonotsu"]
        marks = {m.key: m.at for m in hours.marks}
        assert marks["ake_mutsu"] == hours.day_start
        assert marks["kure_mutsu"] == hours.day_end
        noon = hours.day_start + (hours.day_end - hours.day_start) / 2
        assert abs(marks["hiru_kokonotsu"] - noon) < timedelta(seconds=1)

    def test_the_corner_in_japanese_and_english(self):
        from linecast.sunshine.hours import corner_reading
        hours = wadokei(date(2026, 6, 21), self.LAT, self.LNG, self.TOKYO)
        now = datetime(2026, 6, 21, 10, 40, tzinfo=self.TOKYO)
        assert corner_reading(hours, now, _runtime(lang="ja")) == "朝四つ半 · 1刻 = 159m"
        assert corner_reading(hours, now, _runtime()) == "morning four ½ · 1 koku = 159m"
        early = datetime(2026, 6, 21, 9, 30, tzinfo=self.TOKYO)
        assert corner_reading(hours, early, _runtime(lang="ja")) == "朝四つ · 1刻 = 159m"
        night = datetime(2026, 6, 21, 23, 50, tzinfo=self.TOKYO)
        assert corner_reading(hours, night, _runtime(lang="ja")).startswith("夜九つ")

    def test_the_line_keeps_kanji_in_japanese_and_words_elsewhere(self):
        from linecast.sunshine.hours import hours_line
        hours = wadokei(date(2026, 6, 21), self.LAT, self.LNG, self.TOKYO)
        now = datetime(2026, 6, 21, 10, 40, tzinfo=self.TOKYO)
        ja = _plain(hours_line(hours, now, 300, _runtime(lang="ja", use_24h=True)))
        assert ja.startswith("夜八つ 01:04 · 暁七つ 02:25 · 明六つ 03:47")
        assert "昼九つ 11:43 (1h 03m後)" in ja
        en = _plain(hours_line(hours, now, 300, _runtime()))
        assert "noon nine 11:43a (in 1h 03m)" in en
        assert en.endswith("midnight nine 11:43p")

    def test_json_carries_the_kanji_beside_the_english(self):
        from linecast.sunshine.json import build_payload
        hours = wadokei(date(2026, 6, 21), self.LAT, self.LNG, self.TOKYO)
        now = datetime(2026, 6, 21, 10, 40, tzinfo=self.TOKYO)
        block = build_payload(self.LAT, self.LNG, now=now, location="Tokyo", hours=hours)["hours"]
        assert block["divisions"] == 6 and block["night_divisions"] == 6
        noon = next(m for m in block["marks"] if m["key"] == "hiru_kokonotsu")
        assert noon == {"key": "hiru_kokonotsu", "name": "noon nine, the hour of the Horse",
                        "native": "昼九つ", "time": "2026-06-21T11:43"}
        assert block["now"]["label"] == "morning four ½"


# (place, date) → Aladhan's timings by the place's method, to the
# minute. Karachi is read with the Hanafi Asr, as Pakistan prints it.
ALADHAN_PLACES = {
    "mecca": (21.4225, 39.8262, "Asia/Riyadh", "makkah", None),
    "cairo": (30.0444, 31.2357, "Africa/Cairo", "egypt", None),
    "dearborn": (42.32, -83.18, "America/Detroit", "isna", None),
    "london": (51.5074, -0.1278, "Europe/London", "mwl", None),
    "karachi": (24.86, 67.01, "Asia/Karachi", "karachi", 'PK'),
    "jakarta": (-6.2, 106.8, "Asia/Jakarta", "kemenag", None),
    "istanbul": (41.01, 28.98, "Europe/Istanbul", "turkey", None),
    "oslo": (59.91, 10.75, "Europe/Oslo", "mwl", None),
}
ALADHAN = {
    ("cairo", "2026-03-05"): {
        "imsak": "04:40",
        "fajr": "04:50",
        "sunrise": "06:17",
        "dhuhr": "12:07",
        "asr": "15:26",
        "maghrib": "17:57",
        "isha": "19:14",
    },
    ("cairo", "2026-09-15"): {
        "imsak": "05:02",
        "fajr": "05:12",
        "sunrise": "06:39",
        "dhuhr": "12:50",
        "asr": "16:21",
        "maghrib": "19:01",
        "isha": "20:19",
    },
    ("cairo", "2026-06-21"): {
        "imsak": "03:58",
        "fajr": "04:08",
        "sunrise": "05:54",
        "dhuhr": "12:57",
        "asr": "16:32",
        "maghrib": "19:59",
        "isha": "21:33",
    },
    ("cairo", "2026-12-21"): {
        "imsak": "05:04",
        "fajr": "05:14",
        "sunrise": "06:47",
        "dhuhr": "11:53",
        "asr": "14:41",
        "maghrib": "16:59",
        "isha": "18:23",
    },
    ("dearborn", "2026-03-05"): {
        "imsak": "05:35",
        "fajr": "05:45",
        "sunrise": "07:01",
        "dhuhr": "12:44",
        "asr": "15:54",
        "maghrib": "18:28",
        "isha": "19:44",
    },
    ("dearborn", "2026-09-15"): {
        "imsak": "05:44",
        "fajr": "05:54",
        "sunrise": "07:13",
        "dhuhr": "13:28",
        "asr": "16:59",
        "maghrib": "19:42",
        "isha": "21:01",
    },
    ("dearborn", "2026-06-21"): {
        "imsak": "04:01",
        "fajr": "04:11",
        "sunrise": "05:56",
        "dhuhr": "13:35",
        "asr": "17:38",
        "maghrib": "21:13",
        "isha": "22:58",
    },
    ("dearborn", "2026-12-21"): {
        "imsak": "06:24",
        "fajr": "06:34",
        "sunrise": "07:58",
        "dhuhr": "12:31",
        "asr": "14:46",
        "maghrib": "17:03",
        "isha": "18:28",
    },
    ("istanbul", "2026-03-05"): {
        "imsak": "05:51",
        "fajr": "06:01",
        "sunrise": "07:25",
        "dhuhr": "13:21",
        "asr": "16:30",
        "maghrib": "19:06",
        "isha": "20:25",
    },
    ("istanbul", "2026-09-15"): {
        "imsak": "05:01",
        "fajr": "05:11",
        "sunrise": "06:37",
        "dhuhr": "13:04",
        "asr": "16:35",
        "maghrib": "19:21",
        "isha": "20:41",
    },
    ("istanbul", "2026-06-21"): {
        "imsak": "03:14",
        "fajr": "03:24",
        "sunrise": "05:25",
        "dhuhr": "13:11",
        "asr": "17:11",
        "maghrib": "20:47",
        "isha": "22:38",
    },
    ("istanbul", "2026-12-21"): {
        "imsak": "06:36",
        "fajr": "06:46",
        "sunrise": "08:18",
        "dhuhr": "13:07",
        "asr": "15:25",
        "maghrib": "17:46",
        "isha": "19:13",
    },
    ("jakarta", "2026-03-05"): {
        "imsak": "04:31",
        "fajr": "04:41",
        "sunrise": "05:58",
        "dhuhr": "12:04",
        "asr": "15:07",
        "maghrib": "18:10",
        "isha": "19:20",
    },
    ("jakarta", "2026-09-15"): {
        "imsak": "04:19",
        "fajr": "04:29",
        "sunrise": "05:46",
        "dhuhr": "11:48",
        "asr": "15:01",
        "maghrib": "17:50",
        "isha": "18:59",
    },
    ("jakarta", "2026-06-21"): {
        "imsak": "04:28",
        "fajr": "04:38",
        "sunrise": "06:02",
        "dhuhr": "11:55",
        "asr": "15:16",
        "maghrib": "17:47",
        "isha": "19:02",
    },
    ("jakarta", "2026-12-21"): {
        "imsak": "04:01",
        "fajr": "04:11",
        "sunrise": "05:36",
        "dhuhr": "11:51",
        "asr": "15:18",
        "maghrib": "18:05",
        "isha": "19:22",
    },
    ("karachi", "2026-03-05"): {
        "imsak": "05:25",
        "fajr": "05:35",
        "sunrise": "06:51",
        "dhuhr": "12:43",
        "asr": "16:57",
        "maghrib": "18:36",
        "isha": "19:52",
    },
    ("karachi", "2026-09-15"): {
        "imsak": "04:51",
        "fajr": "05:01",
        "sunrise": "06:18",
        "dhuhr": "12:27",
        "asr": "16:53",
        "maghrib": "18:36",
        "isha": "19:53",
    },
    ("karachi", "2026-06-21"): {
        "imsak": "04:04",
        "fajr": "04:14",
        "sunrise": "05:43",
        "dhuhr": "12:34",
        "asr": "17:16",
        "maghrib": "19:24",
        "isha": "20:53",
    },
    ("karachi", "2026-12-21"): {
        "imsak": "05:41",
        "fajr": "05:51",
        "sunrise": "07:12",
        "dhuhr": "12:30",
        "asr": "16:12",
        "maghrib": "17:48",
        "isha": "19:09",
    },
    ("london", "2026-03-05"): {
        "imsak": "04:36",
        "fajr": "04:46",
        "sunrise": "06:37",
        "dhuhr": "12:12",
        "asr": "15:07",
        "maghrib": "17:48",
        "isha": "19:32",
    },
    ("london", "2026-09-15"): {
        "imsak": "04:29",
        "fajr": "04:39",
        "sunrise": "06:35",
        "dhuhr": "12:56",
        "asr": "16:24",
        "maghrib": "19:15",
        "isha": "21:04",
    },
    ("london", "2026-06-21"): {
        "imsak": "02:21",
        "fajr": "02:31",
        "sunrise": "04:43",
        "dhuhr": "13:02",
        "asr": "17:25",
        "maghrib": "21:22",
        "isha": "23:27",
    },
    ("london", "2026-12-21"): {
        "imsak": "05:49",
        "fajr": "05:59",
        "sunrise": "08:04",
        "dhuhr": "11:59",
        "asr": "13:38",
        "maghrib": "15:53",
        "isha": "17:51",
    },
    ("mecca", "2026-03-05"): {
        "imsak": "05:12",
        "fajr": "05:22",
        "sunrise": "06:38",
        "dhuhr": "12:32",
        "asr": "15:54",
        "maghrib": "18:26",
        "isha": "20:26",
    },
    ("mecca", "2026-09-15"): {
        "imsak": "04:41",
        "fajr": "04:51",
        "sunrise": "06:08",
        "dhuhr": "12:16",
        "asr": "15:42",
        "maghrib": "18:24",
        "isha": "19:54",
    },
    ("mecca", "2026-06-21"): {
        "imsak": "04:01",
        "fajr": "04:11",
        "sunrise": "05:39",
        "dhuhr": "12:22",
        "asr": "15:42",
        "maghrib": "19:06",
        "isha": "20:36",
    },
    ("mecca", "2026-12-21"): {
        "imsak": "05:22",
        "fajr": "05:32",
        "sunrise": "06:54",
        "dhuhr": "12:19",
        "asr": "15:23",
        "maghrib": "17:44",
        "isha": "19:14",
    },
    ("oslo", "2026-03-05"): {
        "imsak": "04:35",
        "fajr": "04:45",
        "sunrise": "07:04",
        "dhuhr": "12:28",
        "asr": "15:03",
        "maghrib": "17:54",
        "isha": "20:05",
    },
    ("oslo", "2026-09-15"): {
        "imsak": "04:02",
        "fajr": "04:12",
        "sunrise": "06:45",
        "dhuhr": "13:12",
        "asr": "16:34",
        "maghrib": "19:38",
        "isha": "22:00",
    },
    ("oslo", "2026-06-21"): {
        "imsak": "02:11",
        "fajr": "02:21",
        "sunrise": "03:54",
        "dhuhr": "13:19",
        "asr": "18:00",
        "maghrib": "22:44",
        "isha": "00:12",
    },
    ("oslo", "2026-12-21"): {
        "imsak": "06:22",
        "fajr": "06:32",
        "sunrise": "09:18",
        "dhuhr": "12:15",
        "asr": "13:07",
        "maghrib": "15:12",
        "isha": "17:49",
    },
}


class TestPrayerTimes:
    """Eight places on four dates against the Aladhan API, each by its
    own country's method. Fajr, sunrise, Dhuhr, Maghrib, and Isha land
    within a minute. Asr is held to four: Aladhan's port of the
    PrayTimes formula drifts two or three minutes at high latitude
    near the equinoxes, while PrayTimes' own formula and this table
    agree within twenty seconds."""

    @pytest.mark.parametrize("place,day", sorted(ALADHAN))
    def test_match_aladhan(self, place, day):
        lat, lng, tz, method, country = ALADHAN_PLACES[place]
        tzinfo = ZoneInfo(tz)
        hours = prayer_times(date.fromisoformat(day), lat, lng, tzinfo, method, country)
        marks = {m.key: m.at for m in hours.marks}
        for key, published in ALADHAN[(place, day)].items():
            if key == "imsak" and key not in marks:
                continue          # listed in Ramadan only
            h, m = (int(x) for x in published.split(":"))
            expected = datetime.fromisoformat(day).replace(hour=h, minute=m, tzinfo=tzinfo)
            if expected < marks[key] - timedelta(hours=12):
                expected += timedelta(days=1)      # Isha past midnight
            limit = timedelta(minutes=4) if key == "asr" else timedelta(seconds=75)
            assert abs(marks[key] - expected) < limit, (
                f"{key}: {marks[key]:%H:%M:%S} against Aladhan {published}")

    def test_ramadan_lists_imsak_and_the_fast(self):
        """5 March 2026 is 16 Ramadan 1447: Imsak ten minutes before
        Fajr, Isha two hours after Maghrib by Umm al-Qura, and the
        fast from Fajr to Maghrib."""
        tz = ZoneInfo("Asia/Riyadh")
        hours = prayer_times(date(2026, 3, 5), 21.4225, 39.8262, tz, None, "SA")
        marks = {m.key: m.at for m in hours.marks}
        assert marks["imsak"] == marks["fajr"] - timedelta(minutes=10)
        assert marks["isha"] == marks["maghrib"] + timedelta(minutes=120)
        assert hours.fast == (marks["fajr"], marks["maghrib"])
        assert hours.variant == "makkah"
        later = prayer_times(date(2026, 9, 15), 21.4225, 39.8262, tz, None, "SA")
        later_marks = {m.key: m.at for m in later.marks}
        assert "imsak" not in later_marks and later.fast is None
        assert later_marks["isha"] == later_marks["maghrib"] + timedelta(minutes=90)

    def test_the_method_and_school_follow_the_country(self):
        assert default_method("US") == "isna"
        assert default_method("eg") == "egypt"
        assert default_method("TR") == "turkey"
        assert default_method(None) == "mwl"
        assert default_method("BR") == "mwl"
        assert default_school("PK") == "hanafi"
        assert default_school("CN") == "hanafi"
        assert default_school("SA") == "shafii"
        # Hanafi countries whose timetables print the one-shadow Asr
        for country in ("TR", "BA", "AL", "XK", "MK", "RU"):
            assert default_school(country) == "shafii", country
        tz = ZoneInfo("Asia/Karachi")
        by_country = prayer_times(date(2026, 9, 15), 24.86, 67.01, tz, None, "PK")
        assert by_country.variant == "karachi"
        shafii = prayer_times(date(2026, 9, 15), 24.86, 67.01, tz, "shafii", "PK")
        assert shafii.variant == "karachi-shafii"
        asr = {m.key: m.at for m in by_country.marks}["asr"]
        asr_shafii = {m.key: m.at for m in shafii.marks}["asr"]
        assert asr - asr_shafii > timedelta(minutes=40)
        pinned = prayer_times(date(2026, 9, 15), 24.86, 67.01, tz, "mwl", "PK")
        assert pinned.variant == "mwl"
        assert all(key in METHODS or key in ("hanafi", "shafii")
                   for key in ("mwl", "isna", "egypt", "makkah", "karachi", "tehran",
                               "turkey", "singapore", "jakim", "kemenag", "france", "russia"))

    def test_a_nordic_june_takes_the_angle_based_share(self):
        """Oslo, 21 June: the Sun never gets 18° down, so Fajr is
        18/60 of the night before sunrise and Isha 17/60 after sunset."""
        tz = ZoneInfo("Europe/Oslo")
        hours = prayer_times(date(2026, 6, 21), 59.91, 10.75, tz, "mwl", None)
        marks = {m.key: m.at for m in hours.marks}
        night = hours.next_day_start - marks["sunset"] if "sunset" in marks else None
        assert night is None
        assert marks["isha"] > marks["maghrib"]
        assert marks["fajr"] < marks["sunrise"]
        assert marks["isha"].date() == date(2026, 6, 22)

    def test_names_and_the_corner(self):
        from linecast.sunshine.hours import corner_reading, hours_line
        from linecast._hours.i18n import mark_name, mark_native, variant_name
        tz = ZoneInfo("Asia/Riyadh")
        hours = prayer_times(date(2026, 3, 5), 21.4225, 39.8262, tz, None, "SA")
        noon = datetime(2026, 3, 5, 12, 0, tzinfo=tz)
        assert corner_reading(hours, noon, _runtime()) == "fast 6h 38m · iftar in 6h 26m"
        assert (corner_reading(hours, noon, _runtime(lang="id"))
                == "puasa 6h 38m · berbuka dalam 6h 26m")
        evening = datetime(2026, 3, 5, 19, 0, tzinfo=tz)
        assert corner_reading(hours, evening, _runtime()) == "Maghrib · Isha in 1h 26m"
        assert corner_reading(hours, evening, _runtime(lang="id")) == "Magrib · Isya dalam 1h 26m"
        assert mark_name("islamic", "sunrise", _runtime(lang="id"), short=True) == "Terbit"
        assert mark_native("islamic", "fajr") == "الفجر"
        assert variant_name("islamic", "makkah") == "Umm al-Qura"
        assert variant_name("islamic", "karachi-shafii") == "Karachi · Shafii"
        line = _plain(hours_line(hours, noon, 300, _runtime()))
        assert line.startswith("Imsak 5:12a · Fajr 5:22a · sunrise 6:38a · Dhuhr 12:32p")
        assert line.endswith("Isha 8:26p · Umm al-Qura")

    def test_sunrise_reads_in_the_languages_own_word(self):
        """The prayer names are transliterated but sunrise is not a
        name: French reads it as the line above does. Indonesian and
        Turkish cards have a word of their own for it."""
        from linecast._hours.i18n import mark_name
        assert mark_name("islamic", "sunrise", _runtime(lang="fr")) == "lever du soleil"
        assert mark_name("islamic", "sunrise", _runtime(lang="de")) == "Sonnenaufgang"
        assert mark_name("islamic", "sunrise", _runtime(lang="id")) == "Terbit"
        assert mark_name("islamic", "sunrise", _runtime(lang="tr")) == "Güneş"
        assert mark_name("islamic", "fajr", _runtime(lang="fr")) == "Fajr"

    def test_turkish_reads_the_diyanets_names(self):
        """İmsak, Güneş, Öğle, İkindi, Akşam, Yatsı: the Diyanet's
        İmsak is the Fajr time, and Fajr reads as Sabah only where a
        separate Imsak is listed before it."""
        from linecast.sunshine.hours import hours_line
        tz = ZoneInfo("Europe/Istanbul")
        hours = prayer_times(date(2026, 3, 5), 41.01, 28.98, tz, None, "TR")   # Ramadan
        noon = datetime(2026, 3, 5, 12, 0, tzinfo=tz)
        line = _plain(hours_line(hours, noon, 300, _runtime(lang="tr", use_24h=True)))
        assert line.startswith("İmsak 06:01 · Güneş 07:25 · Öğle 13:20")
        assert " · İkindi " in line and " · Akşam " in line and " · Yatsı " in line
        assert "Imsak" not in line
        # By another method a Turkish reader sees the ten-minute Imsak
        # and the morning prayer after it.
        mwl = prayer_times(date(2026, 3, 5), 41.01, 28.98, tz, "mwl", "TR")
        line = _plain(hours_line(mwl, noon, 300, _runtime(lang="tr", use_24h=True)))
        assert line.startswith("İmsak ") and " · Sabah " in line

    def test_turkey_prints_the_one_shadow_asr(self):
        """The Diyanet's Istanbul table for the week of 16 September
        2026, read from namazvakitleri.diyanet.gov.tr: İmsak, Güneş,
        Öğle, İkindi, Akşam, Yatsı. Turkey is Hanafi, but the İkindi
        printed is asr-ı evvel, the one-shadow time; the Hanafi Asr
        would be fifty minutes later. Three minutes' tolerance: the
        Diyanet's coordinates for the city are its own."""
        published = {
            "2026-09-16": ("05:12", "06:38", "13:04", "16:34", "19:20", "20:41"),
            "2026-09-19": ("05:15", "06:41", "13:03", "16:31", "19:15", "20:35"),
            "2026-09-22": ("05:19", "06:44", "13:02", "16:27", "19:10", "20:30"),
        }
        tz = ZoneInfo("Europe/Istanbul")
        for day, times in published.items():
            hours = prayer_times(date.fromisoformat(day), 41.01, 28.98, tz, None, "TR")
            assert hours.variant == "turkey"
            marks = {m.key: m.at for m in hours.marks}
            assert "imsak" not in marks
            for key, text in zip(("fajr", "sunrise", "dhuhr", "asr", "maghrib", "isha"), times):
                h, m = (int(x) for x in text.split(":"))
                expected = datetime.fromisoformat(day).replace(hour=h, minute=m, tzinfo=tz)
                assert abs(marks[key] - expected) <= timedelta(minutes=3), (
                    f"{day} {key}: {marks[key]:%H:%M} against the Diyanet's {text}")
        assert default_school("TR") == "shafii"

    # Tehran's اوقات شرعی on four dates of 2026, as bahesab.ir serves
    # them for the city (its /mdn/time/Dazanv1/ endpoint, read on 23
    # September 2026) by the Institute of Geophysics, University of
    # Tehran's rules: اذان صبح, طلوع آفتاب, اذان ظهر, غروب آفتاب,
    # اذان مغرب, and the midnight, نیمه\u200cشب شرعی. 1 March is 11
    # Ramadan 1447.
    TEHRAN = {
        "2026-03-01": ("05:11", "06:35", "12:17", "17:59", "18:17", "23:35"),
        "2026-06-21": ("03:02", "04:49", "12:06", "19:23", "19:45", "23:13"),
        "2026-09-23": ("04:29", "05:53", "11:57", "18:00", "18:18", "23:14"),
        "2026-12-22": ("05:41", "07:11", "12:03", "16:55", "17:15", "23:18"),
    }

    def test_tehran_prints_the_iranian_table(self):
        """Sunset beside Maghrib, the Ja'fari midnight, and no Asr, Isha,
        or separate Imsak, even in Ramadan, where the fast still runs
        from اذان صبح to اذان مغرب. Within a minute and a quarter: the
        site's coordinates for the city are its own."""
        tz = ZoneInfo("Asia/Tehran")
        keys = ("fajr", "sunrise", "dhuhr", "sunset", "maghrib", "midnight")
        for day, times in self.TEHRAN.items():
            hours = prayer_times(date.fromisoformat(day), 35.6892, 51.3890, tz, None, "IR")
            assert hours.variant == "tehran"
            assert [m.key for m in hours.marks] == list(keys)
            marks = {m.key: m.at for m in hours.marks}
            for key, text in zip(keys, times):
                h, m = (int(x) for x in text.split(":"))
                expected = datetime.fromisoformat(day).replace(hour=h, minute=m, tzinfo=tz)
                assert abs(marks[key] - expected) < timedelta(seconds=75), (
                    f"{day} {key}: {marks[key]:%H:%M:%S} against {text}")
            assert hours.after.key == "fajr"
        ramadan = prayer_times(date(2026, 3, 1), 35.6892, 51.3890, tz, None, "IR")
        marks = {m.key: m.at for m in ramadan.marks}
        assert ramadan.fast == (marks["fajr"], marks["maghrib"])

    def test_the_jafari_midnight_is_halfway_from_sunset_to_fajr(self):
        """Not to sunrise: on 21 June in Tehran that would be 00:06, and
        the table prints 23:13."""
        tz = ZoneInfo("Asia/Tehran")
        hours = prayer_times(date(2026, 6, 21), 35.6892, 51.3890, tz, None, "IR")
        marks = {m.key: m.at for m in hours.marks}
        next_fajr = hours.after.at
        assert abs((marks["midnight"] - marks["sunset"]) - (next_fajr - marks["midnight"])
                   ) < timedelta(seconds=1)
        by_sunrise = marks["sunset"] + (hours.next_day_start - marks["sunset"]) / 2
        assert by_sunrise - marks["midnight"] > timedelta(minutes=45)

    def test_the_iranian_set_follows_the_method(self):
        """The Tehran method prints the Iranian set wherever it is read;
        another method in Iran prints the five prayers, and so does
        Afghanistan, Hanafi and on the Karachi method, whatever the
        language. A school asked for by name brings Asr and Isha back."""
        iranian = ["fajr", "sunrise", "dhuhr", "sunset", "maghrib", "midnight"]
        standard = ["fajr", "sunrise", "dhuhr", "asr", "maghrib", "isha"]
        day = date(2026, 9, 23)
        tehran = ZoneInfo("Asia/Tehran")
        london = ZoneInfo("Europe/London")
        kabul = ZoneInfo("Asia/Kabul")

        def keys(*args):
            return [m.key for m in prayer_times(day, *args).marks]

        assert keys(35.6892, 51.3890, tehran, None, "IR") == iranian
        assert keys(51.5074, -0.1278, london, "tehran", "GB") == iranian
        assert keys(35.6892, 51.3890, tehran, "mwl", "IR") == standard
        assert keys(34.53, 69.17, kabul, None, "AF") == standard
        hanafi = prayer_times(day, 35.6892, 51.3890, tehran, "hanafi", "IR")
        assert hanafi.variant == "tehran-hanafi"
        assert [m.key for m in hanafi.marks] == standard

    def test_a_jafari_midnight_past_twelve_is_listed_on_the_date_it_falls_on(self):
        """Oslo, 21 June by the Tehran method: the Ja'fari midnight is
        at 00:33 on the 22nd, and the 22nd lists it first, as it does a
        late Isha."""
        tz = ZoneInfo("Europe/Oslo")
        hours, now = hours_now("islamic", datetime(2026, 6, 22, 0, 5, tzinfo=tz),
                               59.91, 10.75, tz, "tehran", None)
        assert hours.date == date(2026, 6, 22)
        assert hours.marks[0].key == "midnight"
        assert hours.marks[0].at.date() == date(2026, 6, 22)
        assert next_mark(hours, now) is hours.marks[0]
        assert [m.key for m in hours.marks].count("midnight") == 2

    def test_the_iranian_marks_are_named(self):
        """Persian reads the Iranian timetable's own names; Turkish and
        Indonesian have their own words; elsewhere sunset and midnight
        read in the language's own word, as sunrise does."""
        from linecast._hours.i18n import mark_name, mark_native
        from linecast.sunshine.hours import hours_line
        fa, en, fr = _runtime(lang="fa"), _runtime(), _runtime(lang="fr")
        assert mark_name("islamic", "sunset", fa) == "غروب آفتاب"
        assert mark_name("islamic", "midnight", fa) == "نیمه\u200cشب شرعی"
        assert mark_name("islamic", "sunset", en) == "sunset"
        assert mark_name("islamic", "midnight", en) == "midnight"
        assert mark_name("islamic", "sunset", fr) == "coucher du soleil"
        assert mark_name("islamic", "midnight", fr) == "minuit"
        assert mark_name("islamic", "midnight", _runtime(lang="tr")) == "Gece yarısı"
        assert mark_name("islamic", "sunset", _runtime(lang="id")) == "Terbenam"
        assert mark_name("islamic", "midnight", _runtime(lang="pt-PT")) == "meia-noite"
        assert mark_native("islamic", "midnight") == "منتصف الليل"
        assert mark_native("islamic", "sunset") == "الغروب"
        # The halachic chatzot halayla is its own mark, and unchanged
        assert mark_name("halachic", "chatzot_halayla", fr) == "chatzot halayla"
        tz = ZoneInfo("Asia/Tehran")
        hours = prayer_times(date(2026, 9, 23), 35.6892, 51.3890, tz, None, "IR")
        noon = datetime(2026, 9, 23, 12, 0, tzinfo=tz)
        line = _plain(hours_line(hours, noon, 300, _runtime(use_24h=True)))
        assert "Asr" not in line and "Isha" not in line
        assert " · Maghrib 18:18 · midnight 23:15 " in line

    def test_the_night_after_isha_counts_down_to_fajr(self):
        """Once the day's marks are past, the next day's first is the
        one to come: Fajr, or Imsak in Ramadan, on the corner and at
        the end of the line."""
        from linecast.sunshine.hours import corner_reading, hours_line
        tz = ZoneInfo("Asia/Riyadh")
        night = datetime(2026, 9, 16, 23, 30, tzinfo=tz)
        hours, now = hours_now("islamic", night, 21.4225, 39.8262, tz, None, "SA")
        assert hours.date == date(2026, 9, 16)
        coming = next_mark(hours, now)
        assert coming is hours.after and coming.key == "fajr"
        assert coming.at.date() == date(2026, 9, 17)
        assert corner_reading(hours, now, _runtime()) == "Isha · Fajr in 5h 22m"
        line = _plain(hours_line(hours, now, 300, _runtime()))
        assert line.endswith("Isha 7:52p · Fajr 4:51a (in 5h 22m) · Umm al-Qura")
        assert [m.key for m in hours.marks].count("fajr") == 1
        ramadan = prayer_times(date(2026, 3, 5), 21.4225, 39.8262, tz, None, "SA")
        assert ramadan.after.key == "imsak"

    def test_an_isha_past_midnight_is_listed_on_the_date_it_falls_on(self):
        """Oslo, 21 June by the Muslim World League: Isha at 00:12 on
        the 22nd. The 21st lists it as its own, and the 22nd lists it
        first, so at 00:05 the countdown is seven minutes, not two
        hours to Fajr."""
        from linecast.sunshine.hours import corner_reading
        tz = ZoneInfo("Europe/Oslo")
        hours, now = hours_now("islamic", datetime(2026, 6, 22, 0, 5, tzinfo=tz),
                               59.91, 10.75, tz, "mwl", None)
        assert hours.date == date(2026, 6, 22)
        assert hours.marks[0].key == "isha"
        assert hours.marks[0].at.date() == date(2026, 6, 22)
        assert corner_reading(hours, now, _runtime()).startswith("Isha in ")
        assert [m.key for m in hours.marks].count("isha") == 2
        before = prayer_times(date(2026, 6, 21), 59.91, 10.75, tz, "mwl", None)
        assert before.marks[-1].key == "isha"
        assert before.marks[-1].at.date() == date(2026, 6, 22)

    def test_every_named_convention_is_a_choice(self):
        from linecast._runtime import HOURS_CHOICES
        for key in METHODS:
            assert f"islamic-{key}" in HOURS_CHOICES
        assert default_method("KW") == "kuwait" and default_method("AE") == "dubai"
        assert default_method("QA") == "qatar" and default_method("JO") == "jordan"
        assert default_method("MA") == "morocco" and default_method("OM") == "oman"
        tz = ZoneInfo("Asia/Amman")
        amman = prayer_times(date(2026, 9, 16), 31.95, 35.93, tz, None, "JO")
        marks = {m.key: m.at for m in amman.marks}
        assert amman.day_end == marks["maghrib"]
        # Jordan's Maghrib is five minutes after sunset
        plain = prayer_times(date(2026, 9, 16), 31.95, 35.93, tz, "mwl", None)
        sunset = {m.key: m.at for m in plain.marks}["maghrib"]
        assert marks["maghrib"] - sunset == timedelta(minutes=5)

    def test_json_carries_the_fast_and_the_arabic(self):
        from linecast.sunshine.json import build_payload
        tz = ZoneInfo("Asia/Riyadh")
        hours = prayer_times(date(2026, 3, 5), 21.4225, 39.8262, tz, None, "SA")
        now = datetime(2026, 3, 5, 12, 0, tzinfo=tz)
        block = build_payload(21.4225, 39.8262, now=now, location="Makkah", hours=hours)["hours"]
        assert block["divisions"] is None and block["now"] is None
        assert block["fast"] == {"start": "2026-03-05T05:22", "end": "2026-03-05T18:26"}
        fajr = next(m for m in block["marks"] if m["key"] == "fajr")
        assert fajr == {"key": "fajr", "name": "Fajr", "native": "الفجر",
                        "time": "2026-03-05T05:22"}
        assert block["next"]["key"] == "dhuhr"


class TestClockChanges:
    """The arithmetic on the day's moments runs in UTC: two datetimes in
    one ZoneInfo subtract as wall-clock time, and a night that crosses
    a clock change would come out an hour short or long."""

    NY = ZoneInfo("America/New_York")
    BROOKLYN = (40.68, -73.94)

    def test_the_night_of_the_fall_back_is_an_hour_longer_than_the_clock_says(self):
        hours = zmanim(date(2026, 11, 1), *self.BROOKLYN, self.NY)
        from linecast._hours import elapsed
        night = elapsed(hours.prev_day_end, hours.day_start)
        assert timedelta(hours=13, minutes=32) < night < timedelta(hours=13, minutes=34)
        chatzot = [m.at for m in hours.marks if m.key == "chatzot_halayla"][0]
        # The middle of that night, an hour later than the wall clocks
        # would put it; still EDT, the clocks go back at 02:00.
        assert (chatzot.hour, chatzot.minute, chatzot.tzname()) == (0, 39, "EDT")
        r = reading(hours, datetime(2026, 11, 1, 1, 30, tzinfo=self.NY, fold=0))
        assert r.night and r.index == 6
        assert 4060 < r.hour_seconds < 4070

    def test_a_countdown_across_the_change_counts_real_time(self):
        hours = zmanim(date(2026, 11, 1), *self.BROOKLYN, self.NY)
        now = datetime(2026, 11, 1, 1, 0, tzinfo=self.NY, fold=0)
        coming = next_mark(hours, now)
        assert coming.key == "alot"
        from linecast._hours import elapsed
        left = elapsed(now, coming.at)
        assert timedelta(hours=5, minutes=3) < left < timedelta(hours=5, minutes=4)

    def test_the_spring_forward_night_is_an_hour_shorter(self):
        hours = zmanim(date(2026, 3, 8), *self.BROOKLYN, self.NY)
        r = reading(hours, datetime(2026, 3, 8, 1, 30, tzinfo=self.NY))
        assert 3720 < r.hour_seconds < 3730

    def test_every_system_places_its_night_marks_by_real_time(self):
        from linecast._hours import elapsed
        from linecast._hours.roman import roman_hours
        from linecast._hours.wadokei import wadokei
        for build in (roman_hours, wadokei):
            hours = build(date(2026, 11, 1), *self.BROOKLYN, self.NY)
            night = elapsed(hours.prev_day_end, hours.day_start)
            assert night > timedelta(hours=12)
            r = reading(hours, datetime(2026, 11, 1, 1, 30, tzinfo=self.NY, fold=0))
            assert abs(r.hour_seconds * hours.night_divisions - night.total_seconds()) < 1


class TestADayThatStraddlesMidnight:
    """At Nuuk in June the Sun sets after midnight, so the small hours
    of a date belong to the day that began the date before."""

    TZ = ZoneInfo("America/Nuuk")
    NUUK = (64.18, -51.7)

    def test_the_moment_before_that_sunset_reads_in_the_day_before(self):
        now = datetime(2026, 6, 20, 0, 10, tzinfo=self.TZ)
        hours, now = hours_now("halachic", now, *self.NUUK, self.TZ)
        assert hours.date == date(2026, 6, 19)
        r = reading(hours, now)
        assert not r.night and r.index == 11
        coming = next_mark(hours, now)
        assert coming.key in ("candles", "sunset")
        assert coming.at - now < timedelta(hours=1)

    def test_after_that_sunset_the_date_is_its_own(self):
        now = datetime(2026, 6, 20, 2, 0, tzinfo=self.TZ)
        hours, now = hours_now("halachic", now, *self.NUUK, self.TZ)
        assert hours.date == date(2026, 6, 20)
        assert reading(hours, now).night


def test_magen_avraham_keeps_no_midnight_when_the_padding_eats_the_night():
    """Tromsø in May: seventy-two minutes either side leaves dawn before
    the last dusk, so that night has no middle to mark."""
    hours = zmanim(date(2026, 5, 17), 69.65, 18.96, ZoneInfo("Europe/Oslo"), "mga")
    keys = [m.key for m in hours.marks]
    assert "chatzot_halayla" not in keys
    assert keys[:2] == ["alot", "sunrise"]


class TestSwahili:
    DAR = ZoneInfo("Africa/Dar_es_Salaam")

    def _corner(self, now, lat=-6.792, lng=39.208, lang="sw"):
        from linecast.sunshine.hours import corner_reading
        hours, now = hours_now("swahili", now, lat, lng, now.tzinfo)
        return corner_reading(hours, now, _runtime(lang=lang, use_24h=True))

    def test_the_hours_count_from_six_on_the_clock(self):
        # The University of Kansas table, hour for hour.
        expected = {
            (0, 0): "saa 6:00 usiku", (1, 13): "saa 7:13 usiku",
            (4, 0): "saa 10:00 alfajiri", (6, 14): "saa 12:14 alfajiri",
            (7, 0): "saa 1:00 asubuhi", (11, 59): "saa 5:59 asubuhi",
            (12, 0): "saa 6:00 mchana", (15, 30): "saa 9:30 mchana",
            (16, 10): "saa 10:10 jioni", (18, 19): "saa 12:19 jioni",
            (19, 0): "saa 1:00 usiku", (23, 59): "saa 5:59 usiku",
        }
        for (h, m), reading_text in expected.items():
            assert self._corner(datetime(2026, 9, 17, h, m, tzinfo=self.DAR)) == reading_text

    def test_the_night_and_day_split_at_six(self):
        hours = day_hours("swahili", date(2026, 9, 17), -6.792, 39.208, self.DAR)
        assert reading(hours, datetime(2026, 9, 17, 17, 59, tzinfo=self.DAR)).night is False
        assert reading(hours, datetime(2026, 9, 17, 18, 0, tzinfo=self.DAR)).night is True
        assert reading(hours, datetime(2026, 9, 17, 5, 59, tzinfo=self.DAR)).night is True
        assert hours.marks == []

    def test_a_clock_change_moves_the_reading_with_the_clock(self):
        london = ZoneInfo("Europe/London")
        # The clocks go back at 02:00 on 25 October 2026, but the hours
        # still follow the clock through the long night.
        assert self._corner(datetime(2026, 10, 25, 3, 0, tzinfo=london),
                            51.5, -0.13) == "saa 9:00 usiku"
        assert self._corner(datetime(2026, 3, 29, 3, 30, tzinfo=london),
                            51.5, -0.13) == "saa 9:30 usiku"

    def test_it_reads_in_swahili_whatever_the_language(self):
        now = datetime(2026, 9, 17, 9, 5, tzinfo=self.DAR)
        assert self._corner(now, lang="en") == "saa 3:05 asubuhi"

    def test_there_is_no_marks_line(self):
        from linecast.sunshine.hours import hours_line
        now = datetime(2026, 9, 17, 9, 5, tzinfo=self.DAR)
        hours, now = hours_now("swahili", now, -6.792, 39.208, self.DAR)
        assert hours_line(hours, now, 120, _runtime(lang="sw")) == ""

    def test_json_says_the_time_as_it_is_spoken(self):
        from linecast.sunshine.json import _hours_block
        expected = {
            (3, 0): "saa tisa usiku",
            (10, 15): "saa nne na robo asubuhi",
            (18, 30): "saa kumi na mbili na nusu jioni",
            (11, 45): "saa sita kasoro robo asubuhi",
            (5, 13): "saa kumi na moja na dakika kumi na tatu alfajiri",
        }
        for (h, m), said in expected.items():
            now = datetime(2026, 9, 17, h, m, tzinfo=self.DAR)
            hours, now = hours_now("swahili", now, -6.792, 39.208, self.DAR)
            block = _hours_block(hours, now)
            assert block["now"]["spoken"] == said
            assert block["now"]["label"].startswith("saa ")
