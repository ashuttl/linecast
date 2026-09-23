"""The day view's reading of the traditional hours: the corner and the line.

Two things are painted when a system of hours is on. The top-left
corner, which the day view leaves empty, takes the reading of the
shown moment: "4:20 · 1h = 57m" for the halachic hours, "hora nona"
for the Roman, "昼八つ半" for the Edo, "Asr · Maghrib in 1h 12m" for
the prayer times, "saa 7:13 usiku" for Swahili time. A line under
the sunrise and sunset lists the day's marks in order: the ones
already past dim, the next in the text colour with a countdown, the
rest muted. The line keeps as many marks as fit, the next one first,
then those still to come, then the ones gone by, most recent first;
sunrise and sunset go last, since the line above names them already.
"""

from linecast._graphics import RESET, fg, fmt_time_dt, visible_len
from linecast._i18n import lang_of
from linecast._hours import elapsed, fmt_duration, last_mark, next_mark, reading, utc
from linecast._hours.i18n import hs, mark_name, reading_name, unit_name, variant_name

_SEP = " · "


def _inks():
    from linecast.sunshine import palette
    return (fg(*palette.INFO_TEXT_RGB), fg(*palette.INFO_MUTED_RGB),
            fg(*palette.INFO_DIM_RGB))


def corner_reading(hours, now, runtime):
    """The reading of *now* for the top-left corner, or ''."""
    if hours is None:
        return ""
    r = reading(hours, now)
    if r is not None:
        name = reading_name(hours.system, r, runtime)
        # A clock's own hours are sixty minutes long, so there is no
        # length to give.
        if hours.wall_clock:
            return name
        # The hour's length in minutes, 43m in a December night and
        # 74m on a June day, since "1h = 1h 14m" reads as a riddle.
        unit = unit_name(hours.system, runtime, r.night)
        return f"{name}{_SEP}{unit} = {int(round(r.hour_seconds / 60))}m"
    # A day of fasting, while it runs: how far in, and how long to
    # iftar, the meal at Maghrib.
    if hours.fast:
        start, end = hours.fast
        at = _aware_like(now, start)
        if utc(start) <= utc(at) < utc(end):
            lang = lang_of(runtime)
            left = hs('in_time', runtime,
                      dur=fmt_duration(elapsed(at, end).total_seconds(), lang))
            fasted = fmt_duration(elapsed(start, at).total_seconds(), lang)
            return f"{hs('fast', runtime)} {fasted}{_SEP}{hs('iftar', runtime)} {left}"
    # A system of marks alone, or a day the Sun never made the edges
    # of: the interval the moment falls in, and how long it has left.
    before, after = last_mark(hours, now), next_mark(hours, now)
    parts = []
    if before is not None:
        parts.append(mark_name(hours.system, before.key, runtime, short=True, hours=hours))
    if after is not None:
        left = fmt_duration(elapsed(_aware_like(now, after.at), after.at).total_seconds(),
                            lang_of(runtime))
        parts.append(f"{mark_name(hours.system, after.key, runtime, short=True, hours=hours)} "
                     f"{hs('in_time', runtime, dur=left)}")
    return _SEP.join(parts)


def _aware_like(now, other):
    if now.tzinfo is None:
        return now.astimezone(other.tzinfo)
    return now


def hours_line(hours, now, width, runtime):
    """The marks line, as many as fit in *width*, or '' with nothing to say."""
    if hours is None or not hours.marks:
        return ""
    text, muted, dim = _inks()
    now = _aware_like(now, hours.marks[0].at)
    coming = next_mark(hours, now)

    # The next day's first mark joins the line once it is the one to
    # come, so the night after the last mark counts down to the dawn.
    listed = list(hours.marks)
    if coming is not None and coming is hours.after:
        listed.append(coming)
    items = []
    for mark in listed:
        label = (f"{mark_name(hours.system, mark.key, runtime, short=True, hours=hours)} "
                 f"{fmt_time_dt(mark.at, runtime.use_24h)}")
        if mark is coming:
            left = fmt_duration(elapsed(now, mark.at).total_seconds(), lang_of(runtime))
            label += f" {dim}({hs('in_time', runtime, dur=left)})"
            ink = text
        elif utc(mark.at) <= utc(now):
            ink = dim
        else:
            ink = muted
        items.append((mark, label, ink))

    # Priority: the next mark, then those still to come in order, then
    # those past, most recent first. Sunrise and sunset after all of
    # them: the line above has them.
    first = [i for i, (m, _l, _k) in enumerate(items) if m is coming]
    later = [i for i, (m, _l, _k) in enumerate(items)
             if utc(m.at) > utc(now) and m is not coming]
    passed = [i for i, (m, _l, _k) in enumerate(items) if utc(m.at) <= utc(now)][::-1]
    order = first + later + passed
    sun = [i for i in order if items[i][0].key in ("sunrise", "sunset")]
    order = [i for i in order if i not in sun] + sun

    note = variant_name(hours.system, hours.variant) or ""
    chosen = []
    used = 0
    for i in order:
        w = visible_len(items[i][1]) + (len(_SEP) if chosen else 0)
        if used + w > width:
            break
        chosen.append(i)
        used += w
    if not chosen:
        return ""
    parts = [f"{ink}{label}" for _m, label, ink in (items[i] for i in sorted(chosen))]
    line = f"{dim}{_SEP}".join(parts)
    if note and used + len(_SEP) + visible_len(note) <= width:
        line += f"{dim}{_SEP}{note}"
    return f"{RESET}{line}{RESET}"
