"""The Edo hours, 不定時法: six koku of day and six of night.

Until 1873 Japan kept the day in twelve koku of unequal length, six
from dawn to dusk and six from dusk to dawn, each named by the number
of bells the temples struck for it and by the earthly branch of the
hour: 明六つ at dawn, 朝五つ, 朝四つ, 昼九つ at noon, 昼八つ, 夕七つ, then
暮六つ at dusk, 夜五つ, 夜四つ, 夜九つ at midnight, 夜八つ, and 暁七つ before
dawn. The count runs down from nine because nine was the auspicious
number and each bell after it dropped one; the wadokei, the Japanese
clocks, were built to follow it.

The day's edges are not sunrise and sunset but 明六つ and 暮六つ, dawn
and dusk. The Jōkyō calendar fixed them at two and a half koku,
thirty-six minutes, either side of sunrise and sunset; the Kansei
calendar of 1798 replaced that with the Sun's centre 7°21′40″ below
the horizon, the depression reached at Kyoto thirty-six minutes
before sunrise at the equinoxes, and the Tenpō calendar kept it. The
National Astronomical Observatory's almanac still prints dawn and
dusk by that angle, with a note that they answer to the old 明六つ and
暮六つ, and that is the definition here.

Each koku is named for the bell that opens it, and the second half
of one is 半: 昼四つ半 is the second half of the fourth bell of the
morning. Japanese keeps its own words; the other languages get the
count and the time of day, 'morning four', and the animal's hour.
"""

from functools import lru_cache

from linecast.astro.hours import DayHours, divide, edges_at, frame

# 7°21′40″: the Sun's centre, below the horizon, at 明六つ and 暮六つ.
DAWN_DEG = 7 + 21 / 60 + 40 / 3600

# The six koku of the day from 明六つ and of the night from 暮六つ, each
# with its bells and its earthly branch.
DAY_KOKU = (
    ("ake_mutsu", 6, "卯"),
    ("asa_itsutsu", 5, "辰"),
    ("asa_yotsu", 4, "巳"),
    ("hiru_kokonotsu", 9, "午"),
    ("hiru_yatsu", 8, "未"),
    ("yuu_nanatsu", 7, "申"),
)
NIGHT_KOKU = (
    ("kure_mutsu", 6, "酉"),
    ("yoru_itsutsu", 5, "戌"),
    ("yoru_yotsu", 4, "亥"),
    ("yoru_kokonotsu", 9, "子"),
    ("yoru_yatsu", 8, "丑"),
    ("akatsuki_nanatsu", 7, "寅"),
)
# Each koku's bell as divide() takes it: its key, and the koku from
# the edge it is counted from.
_DAY_BELLS = tuple((key, n) for n, (key, _bells, _branch) in enumerate(DAY_KOKU))
_NIGHT_BELLS = tuple((key, n) for n, (key, _bells, _branch) in enumerate(NIGHT_KOKU))


@lru_cache(maxsize=64)
def wadokei(local_date, lat, lng, tzinfo=None):
    """The day's twelve koku at a place, each listed at its bell."""
    start, end, prev_end, next_start = frame(edges_at(DAWN_DEG, lat, lng, tzinfo),
                                             local_date)
    marks = divide(start, end, 6, _DAY_BELLS)
    # The night's bells fall on this date from the night before
    # (夜九つ onward, after midnight) and the night after (暮六つ to
    # 夜九つ, before it); each is listed on the date it falls on.
    marks += divide(prev_end, start, 6, _NIGHT_BELLS, local_date)
    marks += divide(end, next_start, 6, _NIGHT_BELLS, local_date)
    marks.sort(key=lambda m: m.at)
    return DayHours("japanese", local_date, start, end, prev_end, next_start,
                    6, marks, None)


def koku_name(r, runtime):
    """The koku a moment falls in, with 半 for its second half: 昼四つ半
    in Japanese, 'morning four ½' elsewhere."""
    from linecast.astro.hours.i18n import mark_name
    key = (NIGHT_KOKU if r.night else DAY_KOKU)[r.index][0]
    name = mark_name("japanese", key, runtime, short=True)
    if r.fraction < 0.5:
        return name
    return f"{name}半" if getattr(runtime, "lang", "en") == "ja" else f"{name} ½"
