"""The tides by the year: each day's range, predicted and measured.

The weather's year is known behind today and guessed ahead of it; the
tide's is the other way about.  The astronomical tide is known for
every day of the year in advance, and what the harbour did besides is
in the past: the surge a storm pushes in, the water an offshore wind
holds out.  So the prediction is the preprinted paper here, a
half-block field from each day's lowest low water to its highest high,
and the gauge is the pen: two braille traces, the highest and lowest
water it measured each day, drawn through yesterday.  Where the pen
runs above the paper it is tinted warm, below it cool.

The field swells and shrinks twice a month, springs and neaps, and the
largest swells come where the full or new Moon falls near perigee; the
Moon's new and full phases are marked above the chart.  NOAA stations
also have a flood stage, drawn as a dotted line, and any water, predicted
or measured, above it is in the alert ink.  Other providers predict
without measuring, so their year is the field alone.
"""

from datetime import date, timedelta

from linecast._i18n import fmt_decimal
from linecast.terminal import live as _live
from linecast.terminal import theme as _theme
from linecast.terminal.braille import DOT_BITS, line_dots
from linecast.terminal.color import RESET, bg, fg
from linecast.terminal.framebuffer import Framebuffer, get_terminal_size
from linecast.terminal.textwidth import visible_len
from linecast.terminal.theme import ensure_contrast, lerp_rgb, surface_bg
from linecast.tides import palette as _palette
from linecast.tides.i18n import _ts
from linecast.weather.year import _month_axis, _month_starts, _on_the_page, _span

BAND_RGB = BAND_FLOOD_RGB = PEN_RGB = WARM_RGB = COOL_RGB = FLOOD_RGB = GUIDE_RGB = None


def _rebuild():
    global BAND_RGB, BAND_FLOOD_RGB, PEN_RGB, WARM_RGB, COOL_RGB, FLOOD_RGB, GUIDE_RGB
    from linecast.weather import style as _style
    BAND_RGB = lerp_rgb(surface_bg(0.10), _palette.CURVE_COLOR, 0.10)
    FLOOD_RGB = ensure_contrast(_style.RED_RGB, _theme.theme_bg, minimum=3.0)
    BAND_FLOOD_RGB = lerp_rgb(BAND_RGB, FLOOD_RGB, 0.45)
    PEN_RGB = _palette.TEXT_RGB
    WARM_RGB = _style.YELLOW_RGB
    COOL_RGB = _style.BLUE_RGB
    GUIDE_RGB = surface_bg(0.22)


_rebuild()
_theme.on_reload(_rebuild)


def daily_ranges(hilo):
    """{day: (lowest, highest)} of the predicted high and low waters."""
    out = {}
    for moment, height, _kind in hilo or []:
        day = moment.date()
        lo, hi = out.get(day, (height, height))
        out[day] = (min(lo, height), max(hi, height))
    return out


def _ticks(lo, hi, rows, runtime):
    """Heights to label, in feet, at the finest step (in the reader's
    unit) that leaves three rows between labels."""
    a, b = runtime.convert_height(lo), runtime.convert_height(hi)
    steps = (0.5, 1, 2, 5, 10) if runtime.metric else (1, 2, 3, 5, 10, 20)
    for step in steps:
        if rows * step / max(1e-9, b - a) >= 3:
            break
    first = -(-a // step) * step
    shown, v = [], first
    while v <= b + 1e-9:
        shown.append(v)
        v += step
    per_foot = runtime.convert_height(1.0)
    return [(v / per_foot, v) for v in shown]


def render_year(year, predicted, observed, flood, runtime, *, header, footer, today,
                tzinfo=None, mouse_pos=None):
    """The year view of the tides, sized to the terminal.

    *predicted* and *observed* are {day: (lowest, highest)} in feet
    above the datum; *flood* is the flood stage, or None.  Any of them
    may be empty while the year loads.  *header* and *footer* are the
    lines the live view puts above and below it.
    """
    cols, rows = get_terminal_size()
    starts, n = _month_starts(year)
    jan1 = date(year, 1, 1)
    days = [jan1 + timedelta(days=k) for k in range(n)]
    predicted = predicted or {}
    observed = {d: v for d, v in (observed or {}).items() if d.year == year}

    # --- the scale ---
    values = [v for pair in list(predicted.values()) + list(observed.values()) for v in pair]
    if flood is not None and values and flood < max(values) + 0.5 * (max(values) - min(values)):
        values.append(flood)
    if not values:
        values = [0.0, 10.0]
    lo, hi = min(values), max(values)
    pad = (hi - lo) * 0.06 + 0.1
    lo, hi = lo - pad, hi + pad

    n_footer = footer.count("\n") + 1
    n_chart = max(4, rows - 3 - n_footer)
    ticks = _ticks(lo, hi, n_chart, runtime)
    tick_text = [f"{fmt_decimal(v, 1 if v % 1 else 0, runtime)}{runtime.height_unit}"
                 for _, v in ticks]
    gutter = max(visible_len(t) for t in tick_text) + 2
    width = max(20, cols - gutter - 1)
    dots = n_chart * 4

    def ydot(v):
        return round((hi - v) / (hi - lo) * (dots - 1))

    # --- the field: each column's predicted range ---
    field = Framebuffer(width, n_chart)
    tops = [None] * width
    for x in range(width):
        span = [days[k] for k in _span(x, width, n) if days[k] in predicted]
        if not span:
            continue
        low = min(predicted[d][0] for d in span)
        high = max(predicted[d][1] for d in span)
        tops[x] = (ydot(high), ydot(low))
        y0, y1 = (hi - high) / (hi - lo) * dots, (hi - low) / (hi - lo) * dots
        for spy in range(n_chart * 2):
            a, b = spy * 2, spy * 2 + 2
            cover = max(0.0, min(b, y1) - max(a, y0)) / 2
            if cover <= 0:
                continue
            level = hi - (spy + 0.5) / (n_chart * 2) * (hi - lo)
            ink = BAND_FLOOD_RGB if flood is not None and level >= flood else BAND_RGB
            field.set_pixel(x, spy, ink, cover)

    # --- the braille: the datum and flood lines, then the gauge's pen ---
    bits, inks, data = {}, {}, set()

    def dot(i, y, ink, guide=False):
        cell = (i // 2, y // 4)
        if not (0 <= cell[0] < width and 0 <= cell[1] < n_chart):
            return
        if guide and cell in data:
            return
        if not guide and cell not in data:
            bits.pop(cell, None)   # data takes a guide's cell
            data.add(cell)
        bits[cell] = bits.get(cell, 0) | DOT_BITS[i % 2][y % 4]
        inks[cell] = ink

    datum_y = ydot(0.0)
    if 0 <= datum_y < dots:
        for i in range(0, width * 2, 4):
            dot(i, datum_y, GUIDE_RGB, guide=True)
    flood_y = ydot(flood) if flood is not None else None
    if flood_y is not None and 0 <= flood_y < dots:
        for i in range(0, width * 2, 3):
            dot(i, flood_y, lerp_rgb(FLOOD_RGB, _theme.theme_bg, 0.35), guide=True)

    top_trace, bottom_trace = [], []
    for i in range(width * 2):
        span = [days[k] for k in _span(i, width * 2, n) if days[k] in observed]
        if not span:
            top_trace.append(None)
            bottom_trace.append(None)
            continue
        high = max(observed[d][1] for d in span)
        low = min(observed[d][0] for d in span)
        p_high = max((predicted[d][1] for d in span if d in predicted), default=None)
        p_low = min((predicted[d][0] for d in span if d in predicted), default=None)
        top_trace.append((ydot(high), p_high))
        bottom_trace.append((ydot(low), p_low))

    def pen_ink(y, p_high, p_low):
        """The pen's ink: the alert's over the flood stage; tinted warm
        where it ran above the prediction and cool below, from a hint at
        half a foot out to the full color at two.  The gauge rides a few
        tenths over the tables all year -- the sea has risen since the
        datum's epoch -- and a tint for that would tint everything."""
        level = hi - y / max(1, dots - 1) * (hi - lo)
        if flood is not None and level >= flood:
            return FLOOD_RGB
        if p_high is not None and level > p_high + 0.5:
            toward, reach = WARM_RGB, level - p_high - 0.5
        elif p_low is not None and level < p_low - 0.5:
            toward, reach = COOL_RGB, p_low - 0.5 - level
        else:
            return PEN_RGB
        return lerp_rgb(PEN_RGB, toward, 0.3 + 0.7 * min(1.0, reach / 1.5))

    for trace in (top_trace, bottom_trace):
        for i in range(len(trace)):
            if trace[i] is None:
                continue
            y1, _ = trace[i]
            if i > 0 and trace[i - 1] is not None:
                y0 = trace[i - 1][0]
                points = list(line_dots(i - 1, y0, i, y1))[1:]
            else:
                points = [(i, y1)]
            _, p = trace[i]
            p_high = p if trace is top_trace else None
            p_low = p if trace is bottom_trace else None
            for x, y in points:
                dot(x, y, pen_ink(y, p_high, p_low))

    # --- hairlines for today and the pointer, where the cell is free ---
    over = {}
    x_today = int((today - jan1).days * width / n) if jan1 <= today < jan1 + timedelta(days=n) else None
    hover_x = None
    if mouse_pos:
        gx, gy = mouse_pos[0] - 1 - gutter, mouse_pos[1] - 3
        if 0 <= gx < width and 0 <= gy < n_chart:
            hover_x = gx
    for x, ink in ((x_today, _palette.NOW_LINE_COLOR), (hover_x, _palette.HOVER_COLOR)):
        if x is None:
            continue
        for row in range(n_chart):
            if (x, row) not in data and (x, row) not in over:
                over[(x, row)] = ("│", ink, False)
    for cell, b in bits.items():
        if cell not in over or cell in data:
            over[cell] = (chr(0x2800 + b), inks[cell], False)

    # The flood stage's name, at the line's right end where it is clear
    if flood_y is not None and 0 <= flood_y < dots:
        label = _ts("flood_stage", runtime)
        row, x0 = flood_y // 4, width - visible_len(label) - 1
        cells = range(x0 - 1, width)
        if x0 > 0 and not any((c, row) in data for c in cells):
            for j, ch in enumerate(label):
                over[(x0 + j, row)] = (ch, lerp_rgb(FLOOD_RGB, _theme.theme_bg, 0.15), False)

    # --- assemble ---
    dim = fg(*_palette.DIM_RGB)
    label_at = {}
    for (feet, _v), text in zip(ticks, tick_text):
        label_at.setdefault(ydot(feet) // 4, text)
    lines = [header, " " * gutter + _moon_row(year, width, n, tzinfo, runtime)]
    for row, body in enumerate(field.render(over)):
        text = label_at.get(row, "")
        lines.append(f"{dim}{' ' * (gutter - 1 - visible_len(text))}{text} {RESET}{body}")
    lines.append(" " * gutter + _month_axis(
        starts, n, width, runtime,
        this_month=today.month - 1 if today.year == year else None))
    lines.append(footer)

    tip = ""
    if hover_x is not None:
        span = [days[k] for k in _span(hover_x, width, n)]
        tip = _tooltip(span, predicted, observed, runtime, hover_x + gutter, mouse_pos[1],
                       cols, rows)
    return _live.overlay(_on_the_page(lines, cols), tip)


def summary(year, predicted, observed, runtime, today):
    """The header's words: the year's highest water so far, measured,
    or for a year not yet begun, predicted; with its day."""
    from linecast.moon.i18n import _fmt_month_day
    source = {d: v for d, v in (observed or {}).items() if d.year == year} or predicted
    if not source:
        return ""
    day, (_lo, high) = max(source.items(), key=lambda kv: kv[1][1])
    return _ts("highest_on", runtime,
               h=f"{fmt_decimal(runtime.convert_height(high), 1, runtime)}{runtime.height_unit}",
               date=_fmt_month_day(day, runtime))


def _moon_row(year, width, n, tzinfo, runtime):
    """The new and full Moons above the chart, at their days' columns."""
    from linecast.moon.calendar import principal_phase_days
    from linecast.moon.phase import moon_phase
    cells = [" "] * width
    jan1 = date(year, 1, 1)
    ink = fg(*_palette.MUTED_RGB)
    for month in range(1, 13):
        for day, (idx, moment) in principal_phase_days(year, month, tzinfo).items():
            if idx not in (0, 4):
                continue
            x = min(width - 1, int((day - jan1).days * width / n))
            cells[x] = f"{ink}{moon_phase(moment, runtime)[2]}{RESET}"
    return "".join(cells)


def _tooltip(span, predicted, observed, runtime, col, mouse_row, cols, rows):
    """The chip for the hovered column's days: the predicted and the
    measured highest and lowest water."""
    from linecast.moon.i18n import _fmt_month_day
    tbg = bg(*_palette.TIP_BG_RGB)
    tfg = fg(*_palette.TIP_TEXT_RGB)
    tdim = fg(*_palette.DIM_RGB)
    unit = runtime.height_unit

    def fmt(v):
        return f"{fmt_decimal(runtime.convert_height(v), 1, runtime)}{unit}"

    when = _fmt_month_day(span[0], runtime)
    if span[-1] != span[0]:
        when += f" – {_fmt_month_day(span[-1], runtime)}"
    lines = [f"{tbg}{tdim} {when} "]
    for name, table in (("predicted", predicted), ("measured", observed)):
        known = [table[d] for d in span if d in table]
        if not known:
            continue
        high = max(v[1] for v in known)
        low = min(v[0] for v in known)
        lines.append(f"{tbg}{tdim} {_ts(name, runtime)} {tfg}▲ {fmt(high)}  ▼ {fmt(low)} ")
    return _live.pointer_chip(lines, col + 3, mouse_row, cols, rows, pad_bg=tbg,
                              flip_at=col + 2)
