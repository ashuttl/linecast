"""sunshine --oneline: the day's sunrise, sunset and length in one line."""

from linecast._i18n import fmt_duration_parts, has_duration_words, lang_of
from linecast._timefmt import fmt_time
from linecast.terminal.color import RESET, fg


def sunshine_oneline(lat, lng, doy, runtime, tz_offset_h=None, hours=None, now=None):
    """Return a compact solar summary line.

    Example: ``sunrise 5:42a sunset 7:38p 12h34m +2m waning_crescent_icon``

    With *hours*, the day read in a tradition's hours, the reading of
    *now* follows: ``4:20 · 1h=57m`` for the halachic hours, ``Dhuhr ·
    Asr in 41m`` for the prayer times.
    """
    from linecast.sunshine.i18n import polar_name
    from linecast.sunshine.solar import polar_state, solar_times
    from linecast.moon.phase import moon_phase
    from datetime import datetime

    sunrise, sunset = solar_times(lat, lng, doy, tz_offset_h)
    day_len = sunset - sunrise
    dl_h = int(day_len)
    dl_m = int((day_len - dl_h) * 60)

    # Yesterday's day length for delta
    y_rise, y_set = solar_times(lat, lng, doy - 1, tz_offset_h)
    delta_sec = (day_len - (y_set - y_rise)) * 3600
    d_sign = "+" if delta_sec >= 0 else "−"
    d_abs = abs(delta_sec)
    d_m = int(d_abs) // 60
    d_s = int(d_abs) % 60

    # Moon phase
    now_dt = datetime.now()
    _idx, _name, moon_icon = moon_phase(now_dt, runtime)

    # Format sunrise/sunset times compactly
    def _fmt(h):
        return fmt_time(h, use_24h=runtime.use_24h)

    # Under a minute, the seconds alone: "−15s", not "−0m15s"; under a
    # second, "+0m", never "−0m".
    parts = [("m", d_m), ("s", d_s)] if d_m and d_s else [("s", d_s)] if d_s else [("m", d_m)]
    if not (d_m or d_s):
        d_sign = "+"
    if not has_duration_words(lang_of(runtime)):
        day_len_str = f"{dl_h}h{dl_m:02d}m"
        delta_str = d_sign + "".join(f"{v}{unit}" for unit, v in parts)
    else:
        day_len_str = fmt_duration_parts(lang_of(runtime), ("h", dl_h), ("m", dl_m))
        delta_str = fmt_duration_parts(lang_of(runtime), *parts, sign=d_sign)

    from linecast.sunshine.palette import (
        INFO_AMBER_RGB, INFO_PURPLE_RGB, INFO_TEXT_RGB, INFO_DIM_RGB,
    )
    amber = fg(*INFO_AMBER_RGB)
    purple = fg(*INFO_PURPLE_RGB)
    text = fg(*INFO_TEXT_RGB)
    dim = fg(*INFO_DIM_RGB)

    # Through a polar season there is no sunrise or sunset: dashes, and
    # the season's name in place of a delta that is zero every day of it,
    # as in the day view.
    polar = polar_state(day_len)
    line = (
        f"{amber}↑{text}{'—' if polar else _fmt(sunrise)} "
        f"{purple}↓{text}{'—' if polar else _fmt(sunset)} "
        f"{text}{day_len_str} "
        f"{dim}{polar_name(polar, runtime) if polar else delta_str} "
        f"{text}{moon_icon}"
    )
    if hours is not None and now is not None:
        from linecast.sunshine.hours import corner_reading
        tail = corner_reading(hours, now, runtime).replace(" = ", "=")
        if tail:
            line += f" {text}{tail}"
    return line + RESET
