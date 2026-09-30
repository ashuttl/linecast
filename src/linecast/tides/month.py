"""The tides by the month: a day to a row, the hours across, the water
as a field.

The day's chart follows one tide at a time; a month of them shows how
they keep time.  The tide keeps the Moon's day, about 24 hours 50
minutes, so each day's high and low water come some fifty minutes
later than the day before's, and the month's tides lie across the rows
as slanting stripes.  They are deepest at the new and full Moon, the
springs, and faint at the quarters, the neaps.

The field is the water: dark when it is low, full ink when it is high.
Sunrise and sunset are braille lines down the month, so the low
waters in daylight are the dark stripes between them, which is what a
month of tides is usually wanted for: a morning for the tide pools, a
low enough tide to walk out to the island.  The column at the right
gives each day's lowest daylight low water, brighter when it falls
below the datum, a minus tide.

A terminal too short for a row a day gives each row two days, one to
each half-block; the right column then names the row's better low.
"""

import calendar
from bisect import bisect_left
from datetime import date, datetime, timedelta, timezone

from linecast._i18n import DAY_NAMES, fmt_decimal, lang_of, table_for
from linecast._timefmt import fmt_time_dt
from linecast.astro.ephemeris import sun_alt_az_deg, sun_depression_utc
from linecast.terminal import live as _live
from linecast.terminal import theme as _theme
from linecast.terminal.braille import DOT_BITS
from linecast.terminal.color import RESET, bg, fg
from linecast.terminal.framebuffer import Framebuffer, get_terminal_size
from linecast.terminal.textwidth import visible_len
from linecast.terminal.theme import best_contrast, ensure_contrast, lerp_rgb, surface_bg
from linecast.tides import palette as _palette
from linecast.tides.chart import render_tide_ticks

# The field's two ends, and the sunrise and sunset lines' ink
LOW_RGB = HIGH_RGB = SUN_RGB = None


def _rebuild():
    global LOW_RGB, HIGH_RGB, SUN_RGB
    LOW_RGB = surface_bg(0.02)
    HIGH_RGB = lerp_rgb(_theme.theme_bg, _palette.CURVE_COLOR, 0.62)
    SUN_RGB = ensure_contrast(
        best_contrast((_theme.theme_ansi[3], _theme.theme_ansi[11]), minimum=2.0),
        _theme.theme_bg, minimum=2.5)


_rebuild()
_theme.on_reload(_rebuild)


def month_of(today, offset):
    """The first of the month *offset* months from *today*'s."""
    k = today.year * 12 + today.month - 1 + offset
    return date(k // 12, k % 12 + 1, 1)


def _sun_times(day, lat, lng, tz):
    """(sunrise, sunset) as local datetimes; (None, None) for a day the
    Sun never rises, and midnight to midnight for one it never sets."""
    rise = sun_depression_utc(day, lat, lng, 0.833, evening=False, tzinfo=tz)
    set_ = sun_depression_utc(day, lat, lng, 0.833, evening=True, tzinfo=tz)
    if rise is None or set_ is None:
        noon = datetime(day.year, day.month, day.day, 12, tzinfo=tz).astimezone(timezone.utc)
        if sun_alt_az_deg(noon, lat, lng)[0] <= 0:
            return None, None
        start = datetime(day.year, day.month, day.day, tzinfo=tz)
        return start, start + timedelta(days=1)
    return rise.astimezone(tz), set_.astimezone(tz)


class _Heights:
    """The water's height at any moment, from the samples by bisection."""

    def __init__(self, predictions):
        self.times = [t for t, _ in predictions]
        self.values = [h for _, h in predictions]

    def at(self, moment):
        i = bisect_left(self.times, moment)
        if i <= 0 or i >= len(self.times):
            return None   # outside what was fetched: no water drawn
        t0, t1 = self.times[i - 1], self.times[i]
        span = (t1 - t0).total_seconds()
        if span <= 0 or span > 6 * 3600:
            return None   # a gap in the series
        frac = (moment - t0).total_seconds() / span
        return self.values[i - 1] + (self.values[i] - self.values[i - 1]) * frac


def _daylight_lows(hilo, day, sun):
    """The day's low waters between sunrise and sunset, as (time, height)."""
    rise, set_ = sun
    if rise is None:
        return []
    return [(t, h) for t, h, kind in hilo
            if t.date() == day and kind.upper().startswith("L") and rise <= t <= set_]


def _day_label(day, runtime):
    return f"{table_for(DAY_NAMES, lang_of(runtime))[day.weekday()]} {day.day:>2}"


def render_month(first, predictions, hilo, runtime, *, header, footer, station_meta,
                 station_tz, now_local, mouse_pos=None):
    """The month view of the tides, sized to the terminal.

    *first* is the month's first day; *predictions* and *hilo* are what
    has been fetched for it (None while it loads, when the view draws
    its frame empty).  *header* and *footer* are the lines the live
    view puts above and below it: the station pill, and the source.
    """
    cols, rows = get_terminal_size()
    ndays = calendar.monthrange(first.year, first.month)[1]
    days = [first + timedelta(days=k) for k in range(ndays)]
    today = now_local.date()
    meta = station_meta or {}
    try:
        lat, lng = float(meta.get("lat")), float(meta.get("lng"))
    except (TypeError, ValueError):
        lat = lng = None
    tz = station_tz or now_local.tzinfo
    predictions = predictions or []
    hilo = hilo or []

    # --- the rows: a day to a row, or two when the month will not fit ---
    avail = max(4, rows - 2 - (footer.count("\n") + 1))
    per_row = 1 if avail >= ndays else 2
    n_rows = min(avail, -(-ndays // per_row))
    shown = days[:n_rows * per_row]
    row_days = [shown[r * per_row:(r + 1) * per_row] for r in range(n_rows)]

    # --- the columns: the day labels, the field, the daylight lows ---
    sun = {d: _sun_times(d, lat, lng, tz) if lat is not None else (None, None)
           for d in shown}
    lows = {d: _daylight_lows(hilo, d, sun[d]) for d in shown}
    unit = runtime.height_unit

    def low_text(t, h):
        return (f"{fmt_time_dt(t, use_24h=runtime.use_24h)} "
                f"{fmt_decimal(runtime.convert_height(h), 1, runtime)}{unit}")

    right = []
    for group in row_days:
        found = [(d, *min(lows[d], key=lambda p: p[1])) for d in group if lows[d]]
        if not found:
            right.append(None)
            continue
        d, t, h = min(found, key=lambda p: p[2])
        text = low_text(t, h)
        if per_row > 1:
            text = f"{d.day:>2}  {text}"
        right.append((text, h))
    labels = [_day_label(group[0], runtime) for group in row_days]
    gutter = max(visible_len(s) for s in labels) + 4
    right_w = max([visible_len(r[0]) for r in right if r] + [0]) + 3
    if cols - gutter - right_w < 24:
        right_w = 0
    width = max(8, cols - gutter - right_w)

    # --- the field: the water's height, a half-block to a day or a row ---
    heights = _Heights(predictions)
    values = [h for _, h in predictions] or [0.0, 1.0]
    lo, hi = min(values), max(values)
    field = Framebuffer(width, n_rows)
    sub = 2 // per_row   # sub-pixel rows to a day
    for k, day in enumerate(shown):
        midnight = datetime(day.year, day.month, day.day, tzinfo=tz)
        for x in range(width):
            h = heights.at(midnight + timedelta(minutes=(x + 0.5) * 1440 / width))
            if h is None:
                continue
            t = max(0.0, min(1.0, (h - lo) / max(1e-9, hi - lo)))
            ink = lerp_rgb(LOW_RGB, HIGH_RGB, t ** 1.2)
            for s in range(sub):
                field.set_pixel(x, k * sub + s, ink)

    # --- braille over it: sunrise and sunset, now, and the hovered hour ---
    bits, inks = {}, {}
    dots_per_day = 4 // per_row

    def mark(k, moment, ink, rows_of_day=None):
        """Dot the day k's own dot rows at *moment*'s place across."""
        minutes = (moment - datetime(moment.year, moment.month, moment.day,
                                     tzinfo=moment.tzinfo)).total_seconds() / 60
        i = min(width * 2 - 1, int(minutes * width * 2 / 1440))
        row, y0 = divmod(k * dots_per_day, 4)
        cell = (i // 2, row)
        for y in rows_of_day or range(y0, y0 + dots_per_day):
            bits[cell] = bits.get(cell, 0) | DOT_BITS[i % 2][y]
        inks[cell] = ink

    for k, day in enumerate(shown):
        rise, set_ = sun[day]
        if rise is not None and rise.date() == day:
            mark(k, rise, SUN_RGB)
        if set_ is not None and set_.date() == day:
            mark(k, set_, SUN_RGB)
        if day == today:
            mark(k, now_local, _palette.NOW_LINE_COLOR)

    hover = None
    if mouse_pos:
        mcol, mrow = mouse_pos
        r, x = mrow - 2, mcol - 1 - gutter
        if 0 <= r < n_rows and 0 <= x < width:
            hover = (r, x)
            for rr in range(n_rows):
                cell = (x, rr)
                if cell not in bits:
                    bits[cell] = DOT_BITS[0][1] | DOT_BITS[0][3]
                    inks[cell] = _palette.HOVER_COLOR

    overlays = {cell: (chr(0x2800 + b), inks[cell], False) for cell, b in bits.items()}
    phases = _phase_marks(first, tz, runtime)

    # --- assemble ---
    lines = [header]
    for r, body in enumerate(field.render(overlays)):
        group = row_days[r]
        is_today = today in group
        ink = _palette.TEXT_RGB if is_today else (
            _palette.MUTED_RGB if group[0].weekday() >= 5 else _palette.DIM_RGB)
        label = labels[r]
        phase = next((phases[d] for d in group if d in phases), "")
        left = (f"{fg(*ink)} {label}{RESET} {fg(*_palette.MUTED_RGB)}{phase}{RESET}")
        left += " " * max(0, gutter - 2 - visible_len(label) - visible_len(phase))
        line = left + body
        if right_w and right[r]:
            text, h = right[r]
            rink = _palette.TEXT_RGB if h < 0 else _palette.MUTED_RGB
            line += f"  {fg(*rink)}{text}{RESET}"
        lines.append(line)
    ticks = render_tide_ticks(datetime(first.year, first.month, first.day, tzinfo=tz),
                              24, width, runtime)
    lines.append(" " * gutter + ticks)
    lines.append(footer)
    output = "\n".join(lines)

    if hover is not None:
        output = _live.overlay(output, _hover_chip(hover, row_days, heights, gutter,
                                                   width, mouse_pos, runtime, tz))
    return output


def _phase_marks(first, tz, runtime):
    """{day: icon} for the month's principal phases of the Moon."""
    from linecast.moon.calendar import principal_phase_days
    from linecast.moon.phase import moon_phase
    return {day: moon_phase(moment, runtime)[2]
            for day, (_idx, moment) in principal_phase_days(first.year, first.month, tz).items()}


def _hover_chip(hover, row_days, heights, gutter, width, mouse_pos, runtime, tz):
    """The chip for the hovered hour: the water at that time on the
    row's day, or on each of its two."""
    from linecast.moon.i18n import _fmt_month_day
    r, x = hover
    minutes = round((x + 0.5) * 1440 / width)
    tip_bg = bg(*_palette.TIP_BG_RGB)
    tip_fg = fg(*_palette.TIP_TEXT_RGB)
    dim = fg(*_palette.DIM_RGB)
    lines = []
    for day in row_days[r]:
        moment = datetime(day.year, day.month, day.day, tzinfo=tz) + timedelta(minutes=minutes)
        h = heights.at(moment)
        when = (f"{table_for(DAY_NAMES, lang_of(runtime))[day.weekday()]} "
                f"{_fmt_month_day(day, runtime)}")
        if not lines:
            lines.append(f"{tip_bg}{dim} {fmt_time_dt(moment, use_24h=runtime.use_24h)} ")
        value = ("–" if h is None else
                 f"{fmt_decimal(runtime.convert_height(h), 1, runtime)}{runtime.height_unit}")
        lines.append(f"{tip_bg}{tip_fg} {when}  {value} ")
    cols, rows = get_terminal_size()
    return _live.pointer_chip(lines, mouse_pos[0], mouse_pos[1], cols, rows, pad_bg=tip_bg)
