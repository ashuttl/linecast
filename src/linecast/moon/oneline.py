"""moon --oneline: the phase, the next rising and setting, and the
calendar's date in one line."""

from linecast._i18n import fmt_percent
from linecast._timefmt import fmt_time_dt
from linecast.terminal.color import RESET, fg


def moon_oneline(now_local, lat, lng, runtime, calendar=None):
    """Return a compact moon summary line.

    Example: ``waxing_gibbous_icon Waxing Gibbous 84% ↓4:12a ↑9:41p``

    Rise/set are the *next* events from now — never today's already-passed
    ones — listed chronologically, so a leading ↓ means the Moon is up.

    With a traditional calendar in effect the line carries what the
    panel's headline carries: the night's name in place of the phase
    name where the calendar names nights, and the lunar date (or the
    anahulu, or the almanac's half of the month) after the events —
    ``… ↓4:12a ↑9:41p · 20 Elul 5786`` — so the line a status bar
    already shows is unchanged up to the new ending.
    """
    from linecast.moon.readings import context, reading
    from linecast.moon.phase import moon_illumination, moon_phase, upcoming_moon_events
    from linecast.sunshine.palette import INFO_AMBER_RGB, INFO_PURPLE_RGB, INFO_TEXT_RGB
    from linecast._i18n import lang_of
    from linecast.astro.calendars.lunisolar import resolve_calendar
    from linecast._i18n import moon_name

    idx, _name, icon = moon_phase(now_local, runtime)
    name = moon_name(idx, runtime)
    illum = moon_illumination(now_local)
    cal, _source = resolve_calendar(calendar, lang_of(runtime))
    found = reading(cal)
    cal_name, aside = (found.headline(context(now_local, lat, lng, runtime, cal))
                       if found else (None, None))
    if cal_name:
        name = cal_name

    amber = fg(*INFO_AMBER_RGB)
    purple = fg(*INFO_PURPLE_RGB)
    text = fg(*INFO_TEXT_RGB)

    parts = [f"{text}{icon} {name} {fmt_percent(illum * 100, runtime)}"]

    rise, sset = upcoming_moon_events(now_local, lat, lng)
    events = sorted(
        (dt, arrow) for dt, arrow in ((rise, "↑"), (sset, "↓")) if dt
    )
    for dt, arrow in events:
        color = amber if arrow == "↑" else purple
        parts.append(f"{color}{arrow}{text}{fmt_time_dt(dt, use_24h=runtime.use_24h)}")
    if aside:
        parts.append(f"{text}· {aside}")

    return " ".join(parts) + RESET
