"""Sunshine year view — a column of sky for each day of the year.

x is the day of the year, y is local clock time (midnight at the top,
midnight at the bottom). Every half-block sub-pixel takes a representative
sky color for that day and time from the same elevation-keyed palette the
daily view uses, so sunrise and sunset are never drawn: they emerge as the
boundary where night gives way to the twilight gradient gives way to day.
By default the whole year is plotted in the location's current UTC offset,
so the band stays smooth; with dst=True each day uses its own offset and
the clock changes show as steps.

A hairline marks today, with the sun glyph at (today, now) — a point on
both axes. Hovering the mouse over the chart raises a second hairline and
a tooltip with that day's sunrise, sunset, and day length, tides-style.
"""

import calendar
from datetime import datetime, timedelta

from linecast import _theme
from linecast._graphics import (
    fg, bg, RESET, interp_stops, lerp, visible_len, fmt_time,
    get_terminal_size, Framebuffer, overlay,
)
from linecast._theme import (
    best_contrast, darken, ensure_contrast, is_light_theme, lerp_rgb,
    surface_bg,
)

_theme.track_imports(globals(), "linecast._color")

_MONTH_ABBR = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
               "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _rebuild():
    # Now and hover hairlines and the hover tooltip, tides' recipe.
    global NOW_LINE_RGB, HOVER_RGB, TIP_BG_RGB, TIP_TEXT_RGB, TIP_DIM_RGB
    NOW_LINE_RGB = ensure_contrast(
        lerp_rgb(best_contrast((_theme.theme_ansi[4], _theme.theme_ansi[12]),
                               minimum=2.0),
                 _theme.theme_bg, 0.30),
        minimum=1.8,
    )
    HOVER_RGB = ensure_contrast(surface_bg(0.40), _theme.theme_bg, minimum=1.5)
    TIP_BG_RGB = darken(surface_bg(0.10), 0.45 if not is_light_theme() else 0.10)
    TIP_TEXT_RGB = ensure_contrast(_theme.theme_fg, TIP_BG_RGB, minimum=4.5)
    TIP_DIM_RGB = ensure_contrast(surface_bg(0.55), TIP_BG_RGB, minimum=2.2)


_rebuild()
_theme.on_reload(_rebuild)


def _day_tz_offsets(year, days, tz):
    """Per-day UTC offset in hours, DST-aware.

    tz None means the machine's own zone; astimezone() interprets the
    naive noon with the system rules for that date, so the DST steps
    land on the right days.
    """
    offsets = []
    day = datetime(year, 1, 1, 12)
    for _ in range(days):
        local = day.astimezone() if tz is None else day.replace(tzinfo=tz)
        off = local.utcoffset()
        offsets.append(off.total_seconds() / 3600 if off else 0.0)
        day += timedelta(days=1)
    return offsets


def _sky_color(elev, sun):
    """Representative sky color for a moment with the sun at elev degrees.

    Low sun keeps the near-horizon palette (the warm sunrise band paints
    itself); once the sun is well up the color goes fully to the zenith
    blue — the field shows the sky, not the sun, so daylight reads as a
    light bright blue rather than the near-white the horizon table ends in.
    """
    near = interp_stops(sun.SKY_NEAR_HORIZON, elev)
    zen = interp_stops(sun.SKY_ZENITH, elev)
    w = max(0.0, min(1.0, (elev - 3) / 25))
    return lerp(near, zen, w)


def _day_facts(lat, lng, doy, tz_off, sun):
    """(sunrise, sunset, day length in hours) for one day."""
    sunrise, sunset = sun.solar_times(lat, lng, doy, tz_off)
    return sunrise, sunset, sunset - sunrise


def _fmt_len(hours):
    h = int(hours)
    m = int((hours - h) * 60)
    return f"{h}h {m:02d}m"


def _fmt_len_delta(delta_hours):
    sign = "+" if delta_hours >= 0 else "−"
    total_m = int(round(abs(delta_hours) * 60))
    h, m = divmod(total_m, 60)
    if h:
        return f"{sign}{h}h {m:02d}m"
    return f"{sign}{m}m"


def render_year(lat, lng, now, runtime, tz=None, fullscreen=False,
                dst=False, location_label="", mouse_pos=None):
    """Build the year-scale sky field display."""
    from linecast import sunshine as sun  # palettes, rebuilt on theme reload

    icons = sun._icon_set(runtime)
    cols, rows = get_terminal_size()

    graph_w = max(30, cols - 2)
    graph_h = max(6, rows - (3 if fullscreen else 6))
    total_spy = graph_h * 2

    year = now.year
    days = 366 if calendar.isleap(year) else 365
    if dst:
        tz_offs = _day_tz_offsets(year, days, tz)
    else:
        off = now.utcoffset()
        if off is None:
            off = datetime.now().astimezone().utcoffset()
        off_h = off.total_seconds() / 3600 if off else 0.0
        tz_offs = [off_h] * days

    today_doy = now.timetuple().tm_yday
    now_hour = now.hour + now.minute / 60 + now.second / 3600

    # --- the sky field ---
    fb = Framebuffer(graph_w, graph_h)
    shade = {}
    for x in range(graph_w):
        day = min(days - 1, int((x + 0.5) / graph_w * days))
        doy = day + 1
        tzoff = tz_offs[day]
        for spy in range(total_spy):
            hour = (spy + 0.5) / total_spy * 24
            # Color depends only on elevation; quantize to 0.25° and memo.
            e = round(sun.sun_elevation(lat, lng, hour, doy, tzoff) * 4) / 4
            c = shade.get(e)
            if c is None:
                c = shade[e] = _sky_color(e, sun)
            fb.fb[spy][x] = c

    # --- today's sun: a point on both axes ---
    x_today = max(0, min(graph_w - 1, int((today_doy - 0.5) / days * graph_w)))
    spy_now = now_hour / 24 * total_spy
    e_now = sun.sun_elevation(lat, lng, now_hour, today_doy,
                              tz_offs[today_doy - 1])
    # A warm halo rather than the daily view's near-white one: over the
    # bright midday field a white glow vanishes, an amber one reads.
    sun_warm = (sun.INFO_AMBER_RGB if e_now > -2
                else sun.SUN_GLOW_TWILIGHT_RGB)
    fb.draw_radial(x_today, spy_now, sun_warm, 5, peak_alpha=0.85)

    # --- hover: which day is the mouse over? ---
    hover_x = None
    if mouse_pos:
        mcol, mrow = mouse_pos
        gx, gy = mcol - 2, mrow - 1  # 1-based terminal → 0-based chart cell
        if 0 <= gx < graph_w and 0 <= gy < graph_h:
            hover_x = gx

    # --- overlays: hairlines, location hint, sun glyph ---
    overlays = {}

    # Today — the now hairline, as in tides.
    for row in range(graph_h):
        overlays[(x_today, row)] = ("│", NOW_LINE_RGB, False)
    if hover_x is not None and hover_x != x_today:
        for row in range(graph_h):
            overlays[(hover_x, row)] = ("│", HOVER_RGB, False)

    # Location hint, dim, in the top-right corner (December midnight — dark
    # sky at every latitude short of a polar summer, where it darkens
    # against the lit cell instead).
    if location_label:
        label = location_label[:max(0, graph_w // 3)]
        x0 = graph_w - len(label) - 1
        for i, ch in enumerate(label):
            x = x0 + i
            if 0 <= x < graph_w:
                cell = fb.cell_bg(x, 0)
                luma = 0.30 * cell[0] + 0.59 * cell[1] + 0.11 * cell[2]
                color = (sun.INFO_DIM_RGB if luma < 130
                         else darken(cell, 0.55))
                overlays[(x, 0)] = (ch, color, False)

    sun_row = max(0, min(graph_h - 1, int(spy_now) // 2))
    overlays[(x_today, sun_row)] = (icons["sun_char"], sun.SUN_CORE_RGB)

    lines = fb.render(overlays)

    # --- month labels ---
    lines.append(_month_line(year, days, graph_w))

    # --- info line for today ---
    lines.append(_info_line(lat, lng, today_doy, tz_offs[today_doy - 1],
                            cols, runtime))

    hint = sun.install_banner()
    if hint:
        lines.append(hint)

    tooltip = ""
    if hover_x is not None:
        tooltip = _hover_tooltip(lat, lng, hover_x, mouse_pos[1], graph_w,
                                 cols, rows, year, days, tz_offs, today_doy,
                                 runtime, sun, icons)
    # overlay() keeps the cursor-addressed tooltip apart from the body so
    # live_loop draws it after its end-of-screen clear, not before.
    return overlay("\n".join(lines), tooltip)


def _hover_tooltip(lat, lng, hover_x, mouse_row, graph_w, cols, rows,
                   year, days, tz_offs, today_doy, runtime, sun, icons):
    """Cursor-positioned tooltip for the hovered day, tides-style."""
    doy = max(1, min(days, int((hover_x + 0.5) / graph_w * days) + 1))
    date = datetime(year, 1, 1) + timedelta(days=doy - 1)
    sunrise, sunset, day_len = _day_facts(lat, lng, doy, tz_offs[doy - 1], sun)
    _, _, today_len = _day_facts(lat, lng, today_doy,
                                 tz_offs[today_doy - 1], sun)

    diff = doy - today_doy
    if diff == 0:
        rel = "today"
    elif diff > 0:
        rel = f"in {diff} day" + ("s" if diff > 1 else "")
    else:
        rel = f"{-diff} day" + ("s" if diff < -1 else "") + " ago"

    tip_bg = bg(*TIP_BG_RGB)
    tip_fg = fg(*TIP_TEXT_RGB)
    tip_dim = fg(*TIP_DIM_RGB)

    tip_lines = [
        f"{tip_bg}{tip_fg} {_MONTH_ABBR[date.month - 1]} {date.day} "
        f"{tip_dim}· {rel} ",
        f"{tip_bg}{tip_fg} {icons['sun_icon']} "
        f"{fmt_time(sunrise, runtime.use_24h)}  "
        f"{fmt_time(sunset, runtime.use_24h)} {icons['sunset_icon']} ",
        f"{tip_bg}{tip_fg} {_fmt_len(day_len)} "
        f"{tip_dim}({_fmt_len_delta(day_len - today_len)}) ",
    ]

    max_w = max(visible_len(line) for line in tip_lines)
    padded = [f"{line}{tip_bg}{' ' * (max_w - visible_len(line))}{RESET}"
              for line in tip_lines]

    tooltip_col = hover_x + 3  # right of the hover hairline, 1-based + margin
    tooltip_row = mouse_row
    if tooltip_col + max_w - 1 > cols:
        tooltip_col = max(1, hover_x + 2 - max_w)
    if tooltip_row + len(padded) - 1 > rows:
        tooltip_row = max(1, rows - len(padded) + 1)

    return "".join(f"\033[{tooltip_row + i};{tooltip_col}H{line}"
                   for i, line in enumerate(padded))


def _month_line(year, days, graph_w):
    from linecast import sunshine as sun

    label_w = 3 if graph_w >= 72 else 1
    chars = [" "] * graph_w
    doy = 0
    for m in range(12):
        x = int(doy / days * graph_w)
        for i, ch in enumerate(_MONTH_ABBR[m][:label_w]):
            if x + i < graph_w:
                chars[x + i] = ch
        doy += calendar.monthrange(year, m + 1)[1]
    dim = fg(*sun.INFO_MUTED_RGB)
    return f"{RESET} {dim}{''.join(chars)}{RESET}"


def _info_line(lat, lng, doy, tz_off, width, runtime):
    """Sunrise — day length (delta vs yesterday) — sunset, for today."""
    from linecast import sunshine as sun

    icons = sun._icon_set(runtime)
    sunrise, sunset, day_len = _day_facts(lat, lng, doy, tz_off, sun)

    y_rise, y_set = sun.solar_times(lat, lng, doy - 1, tz_off)
    delta_sec = (day_len - (y_set - y_rise)) * 3600
    d_sign = "+" if delta_sec >= 0 else "−"
    d_m = int(abs(delta_sec)) // 60
    d_s = int(abs(delta_sec)) % 60
    delta_str = f"{d_sign}{d_m}m {d_s}s" if d_s > 0 else f"{d_sign}{d_m}m"

    amber = fg(*sun.INFO_AMBER_RGB)
    purple = fg(*sun.INFO_PURPLE_RGB)
    dim = fg(*sun.INFO_DIM_RGB)
    text = fg(*sun.INFO_TEXT_RGB)

    dl_h = int(day_len)
    dl_m = int((day_len - dl_h) * 60)
    center = f"{text}{dl_h}h {dl_m:02d}m {dim}({delta_str})"
    left = f"{amber}{icons['sun_icon']} {text}{fmt_time(sunrise, runtime.use_24h)}"
    right = f"{text}{fmt_time(sunset, runtime.use_24h)} {purple}{icons['sunset_icon']}"

    lw, cw, rw = visible_len(left), visible_len(center), visible_len(right)
    total_gap = max(0, width - lw - cw - rw - 2)
    left_gap = max(1, total_gap // 2)
    right_gap = max(1, total_gap - left_gap)
    return f"{RESET} {left}{' ' * left_gap}{center}{' ' * right_gap}{right} {RESET}"
