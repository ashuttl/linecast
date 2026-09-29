"""The Roman hours: twelve horae by day, four vigiliae by night.

Rome divided the daylight, sunrise to sunset, into twelve horae, and
the night into four watches, the vigiliae, so an hour ran about
forty-five minutes at the December solstice and seventy-five in June,
and a watch about three hours the year round. The hours are counted
from sunrise: hora prima is the first, hora sexta ends at noon, hora
nona is mid-afternoon, and the church's terce, sext, and none took
their names from the third, sixth, and ninth. The vigiliae run from
sunset, and the third opens at media nox, the middle of the night.

The marks listed are the ones a Roman would have named: sunrise, the
third, sixth, and ninth hours, sunset, and the second, third, and
fourth watches. Latin is Latin in every language.
"""

from functools import lru_cache

from linecast.astro.hours import DayHours, Mark, divide, edges_at, frame

HORIZON_DEG = 0.833

ORDINALS = ("prima", "secunda", "tertia", "quarta", "quinta", "sexta",
            "septima", "octava", "nona", "decima", "undecima", "duodecima")

# The marks that are hours of the day and watches of the night, as
# (key, hours from sunrise) and (key, watches from sunset).
_DAY_MARKS = (("hora_tertia", 3), ("hora_sexta", 6), ("hora_nona", 9))
_NIGHT_MARKS = (("vigilia_secunda", 1), ("vigilia_tertia", 2), ("vigilia_quarta", 3))


@lru_cache(maxsize=64)
def roman_hours(local_date, lat, lng, tzinfo=None):
    """The day's horae and the night's vigiliae at a place."""
    start, end, prev_end, next_start = frame(edges_at(HORIZON_DEG, lat, lng, tzinfo),
                                             local_date)
    marks = []
    if start and end:
        marks.append(Mark("sunrise", start))
        marks += divide(start, end, 12, _DAY_MARKS)
        marks.append(Mark("sunset", end))
    # The watches of the night before that end on this date, and of
    # the night after that begin on it: each is listed on the date it
    # falls on, as the halachic chatzot halayla is.
    marks += divide(prev_end, start, 4, _NIGHT_MARKS, local_date)
    marks += divide(end, next_start, 4, _NIGHT_MARKS, local_date)
    marks.sort(key=lambda m: m.at)
    return DayHours("roman", local_date, start, end, prev_end, next_start,
                    12, marks, None, night_divisions=4)


def hour_name(r, runtime):
    """'hora quarta' by day, 'vigilia secunda' by night."""
    if r.night:
        return f"vigilia {ORDINALS[r.index]}"
    return f"hora {ORDINALS[r.index]}"
