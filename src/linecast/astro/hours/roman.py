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

from linecast.astro.ephemeris import sun_depression_utc
from linecast.astro.hours import DayHours, Mark, elapsed, shift

HORIZON_DEG = 0.833

ORDINALS = ("prima", "secunda", "tertia", "quarta", "quinta", "sexta",
            "septima", "octava", "nona", "decima", "undecima", "duodecima")

# The marks that are hours of the day and watches of the night, as
# (key, hours from sunrise) and (key, watches from sunset).
_DAY_MARKS = (("hora_tertia", 3), ("hora_sexta", 6), ("hora_nona", 9))
_NIGHT_MARKS = (("vigilia_secunda", 1), ("vigilia_tertia", 2), ("vigilia_quarta", 3))


def _local(dt_utc, tzinfo):
    if dt_utc is None:
        return None
    return dt_utc.astimezone(tzinfo) if tzinfo else dt_utc.astimezone()


def _edges(local_date, lat, lng, tzinfo):
    rise = _local(sun_depression_utc(local_date, lat, lng, HORIZON_DEG, False, tzinfo), tzinfo)
    set_ = _local(sun_depression_utc(local_date, lat, lng, HORIZON_DEG, True, tzinfo), tzinfo)
    return rise, set_


@lru_cache(maxsize=64)
def roman_hours(local_date, lat, lng, tzinfo=None):
    """The day's horae and the night's vigiliae at a place."""
    from datetime import timedelta
    day = timedelta(days=1)
    start, end = _edges(local_date, lat, lng, tzinfo)
    _prev_start, prev_end = _edges(local_date - day, lat, lng, tzinfo)
    next_start, _next_end = _edges(local_date + day, lat, lng, tzinfo)

    marks = []
    if start and end:
        hour = elapsed(start, end) / 12
        marks.append(Mark("sunrise", start))
        for key, n in _DAY_MARKS:
            marks.append(Mark(key, shift(start, hour * n)))
        marks.append(Mark("sunset", end))
    # The watches of the night before that end on this date, and of
    # the night after that begin on it: each is listed on the date it
    # falls on, as the halachic chatzot halayla is.
    for night_start, night_end in ((prev_end, start), (end, next_start)):
        if night_start and night_end:
            watch = elapsed(night_start, night_end) / 4
            for key, n in _NIGHT_MARKS:
                at = shift(night_start, watch * n)
                if at.date() == local_date:
                    marks.append(Mark(key, at))
    marks.sort(key=lambda m: m.at)
    return DayHours("roman", local_date, start, end, prev_end, next_start,
                    12, marks, None, night_divisions=4)


def hour_name(r, runtime):
    """'hora quarta' by day, 'vigilia secunda' by night."""
    if r.night:
        return f"vigilia {ORDINALS[r.index]}"
    return f"hora {ORDINALS[r.index]}"
