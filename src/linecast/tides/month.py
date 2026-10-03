"""The tides by the month: a day to a row, the hours across, the water
as a field.

The day's chart follows one tide at a time; a month of them shows how
they keep time.  The tide keeps the Moon's day, about 24 hours 50
minutes, so each day's high and low water come some fifty minutes
later than the day before's, and the month's tides lie across the rows
as slanting stripes.  They are deepest at the new and full Moon, the
springs, and faint at the quarters, the neaps.

The field is the water: dark when it is low, bright when it is high.
How bright says how great the tide is.  A month whose water moves twelve
feet reaches the curve's own ink; a smaller tide stops short of it, down
to a sea with hardly a tide at all, which is drawn faintly but drawn;
and a greater one goes past it, to near white at the Bay of Fundy.
Sunrise and sunset are braille lines down the month, so the low
waters in daylight are the dark stripes between them, which is what a
month of tides is usually wanted for: a morning for the tide pools, a
low enough tide to walk out to the island.  A diamond on today's row
marks the hour it is now.  The column at the right
gives each day's lowest daylight low water, brighter when it falls
below the datum, a minus tide.

A terminal too short for a row a day gives each row two days, one to
each half-block; the right column then names the row's better low,
and the left its first day, or today on the row today is in.  A
month of odd length ends on a day with a row to itself, and it fills
the row.
"""

import calendar
import math
from bisect import bisect_left
from datetime import date, datetime, timedelta, timezone

from linecast._i18n import DAY_NAMES, fmt_decimal, lang_of, table_for
from linecast._timefmt import fmt_time_dt
from linecast.astro.ephemeris import sun_alt_az_deg, sun_depression_utc
from linecast.moon.calendar import _month_title
from linecast.terminal import live as _live
from linecast.terminal import theme as _theme
from linecast.terminal.braille import DOT_BITS
from linecast.terminal.color import RESET, bg, fg
from linecast.terminal.framebuffer import Framebuffer, get_terminal_size
from linecast.terminal.heading import render_heading
from linecast.terminal.textwidth import visible_len
from linecast.terminal.theme import (
    best_contrast,
    contrast_ratio,
    ensure_contrast,
    is_light_theme,
    lerp_rgb,
    shift_to_pole,
    surface_bg,
)
from linecast.tides import palette as _palette
from linecast.tides.chart import render_tide_ticks

# The field's inks: low water, high water where the tide is an ordinary
# one, and high water where it is the greatest there is; then the sunrise
# and sunset lines' ink, and the now mark's
LOW_RGB = HIGH_RGB = PEAK_RGB = SUN_RGB = NOW_RGB = None

# The month's range, in feet, that reaches HIGH_RGB, and the least of
# the way there any water is drawn, so the faintest tide still shows
ORDINARY_RANGE_FT = 12.0
FAINTEST = 0.10

# The footer's key to the Sun's lines, which step a dot aside as the days
# lengthen or shorten, and the mark for now, on the field and in the key
SUN_KEY = "⢣"
NOW_MARK = "◆"


def _rebuild():
    global LOW_RGB, HIGH_RGB, PEAK_RGB, SUN_RGB, NOW_RGB
    LOW_RGB = surface_bg(0.02)
    HIGH_RGB = lerp_rgb(_theme.theme_bg, _palette.CURVE_COLOR, 0.62)
    PEAK_RGB = shift_to_pole(_palette.CURVE_COLOR, 0.80, lighter=not is_light_theme())
    SUN_RGB = ensure_contrast(
        best_contrast((_theme.theme_ansi[3], _theme.theme_ansi[11]), minimum=2.0),
        _theme.theme_bg, minimum=2.5)
    NOW_RGB = shift_to_pole(_palette.TEXT_RGB, 0.85, lighter=not is_light_theme())


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


def reach(range_ft):
    """How far up the inks a month's highest water goes: 1 is HIGH_RGB,
    2 is PEAK_RGB.  It goes as the square root of the range, so a tide
    a quarter the size is half as bright: the Mediterranean's foot of
    water is still plainly there, and four times the ordinary range,
    the Bay of Fundy's, is the brightest there is."""
    return max(FAINTEST, min(2.0, math.sqrt(max(0.0, range_ft) / ORDINARY_RANGE_FT)))


def _water_ink(level):
    """The ink at *level* of the way from low water: LOW_RGB at 0,
    HIGH_RGB at 1, PEAK_RGB at 2."""
    if level <= 1.0:
        return lerp_rgb(LOW_RGB, HIGH_RGB, level)
    return lerp_rgb(HIGH_RGB, PEAK_RGB, level - 1.0)


def _clear_of(ink, water):
    """*ink* for a line's dots over *water*.  The brightest water would
    swallow the line, so there the ink goes toward the background until
    it stands clear."""
    for step in range(11):
        shade = lerp_rgb(ink, _theme.theme_bg, step / 10)
        if contrast_ratio(shade, water) >= 2.0:
            return shade
    return ink


def _now_ink(water):
    """The now mark's ink over *water*: the brightest there is, or the
    background's where the water is nearly as bright."""
    return NOW_RGB if contrast_ratio(NOW_RGB, water) >= 2.0 else _theme.theme_bg


def _daylight_lows(hilo, day, sun):
    """The day's low waters between sunrise and sunset, as (time, height)."""
    rise, set_ = sun
    if rise is None:
        return []
    return [(t, h) for t, h, kind in hilo
            if t.date() == day and kind.upper().startswith("L") and rise <= t <= set_]


def _day_label(day, runtime):
    return f"{table_for(DAY_NAMES, lang_of(runtime))[day.weekday()]} {day.day:>2}"


def sun_legend(runtime, width, *, now=False, sun_rgb=None, now_rgb=None, text_rgb=None):
    """The key to a month's Sun lines and, when shown, its now marker."""
    from linecast.radar.i18n import rs
    from linecast.sunshine.i18n import _ss
    from linecast.terminal.textwidth import clip_styled
    dim = fg(*(text_rgb or _palette.DIM_RGB))
    legend = (f"{fg(*(sun_rgb or SUN_RGB))}{SUN_KEY}{RESET} {dim}"
              f"{_ss('sunrise', runtime)} / {_ss('sunset', runtime)}{RESET}")
    if now:
        mark = (f"   {fg(*(now_rgb or NOW_RGB))}{NOW_MARK}{RESET} "
                f"{dim}{rs('now', lang_of(runtime))}{RESET}")
        if visible_len(legend + mark) <= width:
            legend += mark
    return clip_styled(legend, width) + RESET


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
    # The axis and its legend belong to the field. Leave a blank row
    # between them, while the source and help keep the window's footer.
    n_footer = footer.count("\n") + 1
    ruled = rows >= 6 + n_footer + (ndays + 1) // 2
    avail = max(4, rows - 5 - int(ruled) - n_footer)
    per_row = 1 if avail >= ndays else 2
    n_rows = min(avail, -(-ndays // per_row))
    shown = days[:n_rows * per_row]
    row_days = [shown[r * per_row:(r + 1) * per_row] for r in range(n_rows)]
    # A day cannot be stretched, so a taller terminal has rows to spare:
    # the header and footer keep the top and bottom of the window, and
    # the field sits midway between them.
    spare = avail - n_rows
    title_gap = int(spare > 0)
    spare -= title_gap
    above = spare // 2
    field_top = 2 + int(ruled) + above + title_gap

    # --- the columns: the day labels, the field, the daylight lows ---
    sun = {d: _sun_times(d, lat, lng, tz) if lat is not None else (None, None)
           for d in shown}
    lows = {d: _daylight_lows(hilo, d, sun[d]) for d in shown}
    unit = runtime.height_unit

    found = []
    for group in row_days:
        best = [(d, *min(lows[d], key=lambda p: p[1])) for d in group if lows[d]]
        if not best:
            found.append(None)
            continue
        d, t, h = min(best, key=lambda p: p[2])
        found.append((d, fmt_time_dt(t, use_24h=runtime.use_24h),
                      f"{fmt_decimal(runtime.convert_height(h), 1, runtime)}{unit}"))
    # The times and the heights are each set flush right, so a minus or
    # a second figure stands out to the left and the rest keep their
    # columns
    time_w = max([visible_len(f[1]) for f in found if f] + [0])
    height_w = max([visible_len(f[2]) for f in found if f] + [0])
    right = []
    for f in found:
        if f is None:
            right.append(None)
            continue
        d, when, height = f
        text = (" " * (time_w - visible_len(when)) + when + " "
                + " " * (height_w - visible_len(height)) + height)
        if per_row > 1:
            text = f"{d.day:>2}  {text}"
        right.append((text, height.startswith("−")))
    # A row is named for its first day, but today's row for today: the
    # bright label is the one read as the date
    labels = [_day_label(today if today in group else group[0], runtime)
              for group in row_days]
    gutter = max(visible_len(s) for s in labels) + 4
    right_w = max([visible_len(r[0]) for r in right if r] + [0]) + 2
    if cols - gutter - right_w < 24:
        right_w = 0
    width = max(8, cols - gutter - right_w)

    # --- the field: the water's height, a half-block to a day or a row ---
    heights = _Heights(predictions)
    values = [h for _, h in predictions] or [0.0, 1.0]
    lo, hi = min(values), max(values)
    top = reach(hi - lo) if predictions else 1.0
    field = Framebuffer(width, n_rows)
    sub = 2 // per_row   # sub-pixel rows to a day
    # The last day of an odd month has its row to itself and takes all
    # of it: a mark over a cell half water and half empty would stand on
    # a box of the two blended
    alone = len(shown) - 1 if len(shown) % per_row else None
    for k, day in enumerate(shown):
        midnight = datetime(day.year, day.month, day.day, tzinfo=tz)
        for x in range(width):
            h = heights.at(midnight + timedelta(minutes=(x + 0.5) * 1440 / width))
            if h is None:
                continue
            t = max(0.0, min(1.0, (h - lo) / max(1e-9, hi - lo)))
            ink = _water_ink(t ** 1.2 * top)
            for s in range(2 if k == alone else sub):
                field.set_pixel(x, k * sub + s, ink)

    # --- braille over it: sunrise and sunset, and the hovered hour ---
    bits, inks = {}, {}
    dots_per_day = 4 // per_row
    now_cell = None

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
        whole = range(4) if k == alone else None
        if rise is not None and rise.date() == day:
            mark(k, rise, SUN_RGB, whole)
        if set_ is not None and set_.date() == day:
            mark(k, set_, SUN_RGB, whole)
        if day == today:
            minutes = now_local.hour * 60 + now_local.minute
            now_cell = (min(width - 1, minutes * width // 1440), k // per_row)

    hover = None
    if mouse_pos:
        mcol, mrow = mouse_pos
        r, x = mrow - 1 - field_top, mcol - 1 - gutter
        if 0 <= r < n_rows and 0 <= x < width:
            hover = (r, x)
            for rr in range(n_rows):
                cell = (x, rr)
                if cell not in bits:
                    bits[cell] = DOT_BITS[0][1] | DOT_BITS[0][3]
                    inks[cell] = _palette.HOVER_COLOR

    overlays = {cell: (chr(0x2800 + b), _clear_of(inks[cell], field.cell_bg(*cell)), False)
                for cell, b in bits.items()}
    # Now is a diamond, not dots: it is one place, and has to be found
    if now_cell is not None:
        overlays[now_cell] = (NOW_MARK, _now_ink(field.cell_bg(*now_cell)), False)
    phases = _phase_marks(first, tz, runtime)

    # --- assemble ---
    lines = [header] + [""] * above
    title = _month_title(first.year, first.month, lang_of(runtime), full=True)
    lines += [" " * gutter + line for line in render_heading(
        title, width, text_rgb=_palette.TEXT_RGB, dim_rgb=_palette.DIM_RGB, ruled=ruled)]
    lines += [""] * title_gap
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
            text, minus = right[r]
            rink = _palette.TEXT_RGB if minus else _palette.MUTED_RGB
            line += f"  {fg(*rink)}{text}{RESET}"
        lines.append(line)
    ticks = render_tide_ticks(datetime(first.year, first.month, first.day, tzinfo=tz),
                              24, width, runtime)
    lines.append(" " * gutter + ticks)
    lines.append("")
    lines.append(" " * gutter + sun_legend(runtime, cols - gutter, now=today in shown))
    lines.extend([""] * (spare - above))
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
    return {day: moon_phase(moment, runtime, bg_color=_theme.theme_bg)[2]
            for day, (_idx, moment) in principal_phase_days(first.year, first.month, tz).items()}


def _hover_chip(hover, row_days, heights, gutter, width, mouse_pos, runtime, tz):
    """The chip for the hovered hour: the water at that time on the
    row's day, or on each of its two."""
    from linecast.moon.i18n import _fmt_month_day
    r, x = hover
    minutes = round((x + 0.5) * 1440 / width)
    tip_bg = bg(*_palette.TIP_BG_RGB)
    tip_fg = fg(*_palette.TIP_TEXT_RGB)
    dim = fg(*_palette.TIP_DIM_RGB)
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
