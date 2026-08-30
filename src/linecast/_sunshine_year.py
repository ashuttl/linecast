"""Sunshine year view — a column of sky for each day of the year.

x is the day of the year, y is local clock time (midnight at the top,
midnight at the bottom). Every half-block sub-pixel takes a representative
sky color for that day and time from the same elevation-keyed palette the
daily view uses, so sunrise and sunset are never drawn: they emerge as the
boundary where night gives way to the twilight gradient gives way to day.
By default the whole year is plotted in the location's current UTC offset,
so the band stays smooth; with dst=True each day uses its own offset and
the clock changes show as steps.

A dashed hairline marks the day under the cursor (today until scrubbed);
the sun glyph sits at (today, now) — a point on both axes.
"""

import calendar
from datetime import datetime, timedelta

from linecast import _theme
from linecast._graphics import (
    fg, RESET, interp_stops, lerp, visible_len, fmt_time,
    get_terminal_size, Framebuffer,
)
from linecast._theme import darken

_theme.track_imports(globals(), "linecast._color")

_MONTH_ABBR = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
               "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


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


def render_year(lat, lng, now, runtime, tz=None, fullscreen=False,
                cursor_day_offset=0, dst=False, location_label=""):
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
    cursor_doy = max(1, min(days, today_doy + cursor_day_offset))
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

    # --- overlays: cursor hairline, location hint, sun glyph ---
    overlays = {}

    # Cursor day hairline — a braille stitch, one dash per cell, so it
    # stays sharp. Light thread over night, dark thread over day. An
    # overlay char flattens its cell to one color, so in gradient cells
    # (the twilight band) the dash is drawn in the sub-pixel buffer
    # instead, keeping the sunrise colors intact.
    x_cursor = max(0, min(graph_w - 1,
                          int((cursor_doy - 0.5) / days * graph_w)))
    for row in range(graph_h):
        top, bot = fb.fb[row * 2][x_cursor], fb.fb[row * 2 + 1][x_cursor]
        cell = fb.cell_bg(x_cursor, row)
        luma = 0.30 * cell[0] + 0.59 * cell[1] + 0.11 * cell[2]
        color = sun.CURVE_COLOR if luma < 130 else darken(cell, 0.5)
        if max(abs(a - b) for a, b in zip(top, bot)) <= 12:
            overlays[(x_cursor, row)] = (chr(0x2800 + 0x02 + 0x10), color, False)
        else:
            spy = row * 2
            fb.fb[spy][x_cursor] = lerp(fb.fb[spy][x_cursor], color, 0.6)

    # Location hint, dim, in the top-right corner (December midnight — the
    # darkest patch of sky the chart has).
    if location_label:
        label = location_label[:max(0, graph_w // 3)]
        x0 = graph_w - len(label) - 1
        for i, ch in enumerate(label):
            if 0 <= x0 + i < graph_w:
                overlays[(x0 + i, 0)] = (ch, sun.INFO_DIM_RGB, False)

    sun_row = max(0, min(graph_h - 1, int(spy_now) // 2))
    overlays[(x_today, sun_row)] = (icons["sun_char"], sun.SUN_CORE_RGB)

    lines = fb.render(overlays)

    # --- month labels ---
    lines.append(_month_line(year, days, graph_w))

    # --- info line for the day under the cursor ---
    lines.append(_info_line(lat, lng, cursor_doy, tz_offs[cursor_doy - 1],
                            year, days, cols, runtime,
                            scrubbed=cursor_doy != today_doy))

    hint = sun.install_banner()
    if hint:
        lines.append(hint)

    return "\n".join(lines)


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


def _info_line(lat, lng, doy, tz_off, year, days, width, runtime, scrubbed):
    """Sunrise — [date ·] day length (delta) — sunset, for the cursor day."""
    from linecast import sunshine as sun

    icons = sun._icon_set(runtime)
    sunrise, sunset = sun.solar_times(lat, lng, doy, tz_off)
    day_len = sunset - sunrise
    dl_h = int(day_len)
    dl_m = int((day_len - dl_h) * 60)

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

    length = f"{dl_h}h {dl_m:02d}m {dim}({delta_str})"
    if scrubbed:
        date = datetime(year, 1, 1) + timedelta(days=doy - 1)
        label = f"{_MONTH_ABBR[date.month - 1]} {date.day}"
        center = f"{text}{label} · {length}"
    else:
        center = f"{text}{length}"

    left = f"{amber}{icons['sun_icon']} {text}{fmt_time(sunrise, runtime.use_24h)}"
    right = f"{text}{fmt_time(sunset, runtime.use_24h)} {purple}{icons['sunset_icon']}"

    lw, cw, rw = visible_len(left), visible_len(center), visible_len(right)
    total_gap = max(0, width - lw - cw - rw - 2)
    left_gap = max(1, total_gap // 2)
    right_gap = max(1, total_gap - left_gap)
    return f"{RESET} {left}{' ' * left_gap}{center}{' ' * right_gap}{right} {RESET}"
