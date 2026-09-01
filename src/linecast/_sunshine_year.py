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

from linecast import _live, _theme
from linecast._graphics import (
    fg, bg, interp_stops, lerp, fmt_time,
    get_terminal_size, Framebuffer, overlay,
)
from linecast._sunshine_i18n import (
    _fmt_month_day, axis_month_labels, polar_name, relative_day, sky_event,
    sky_phase,
)
from linecast._textwidth import char_width
from linecast._theme import (
    best_contrast, darken, ensure_contrast, is_light_theme, lerp_rgb,
    surface_bg,
)

_theme.track_imports(globals(), "linecast._color")

# The last sky field built, by the things that shape it. Everything the
# mouse moves — the hover hairline, the tooltip — is drawn over the
# field, not into it, so a hover would otherwise pay for a quarter of a
# million elevations again on a large terminal. Cleared on theme reload,
# where the palette itself changes.
_FIELD_CACHE = {}

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
    _FIELD_CACHE.clear()


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
    """The day view's own sky, keyed by elevation alone.

    Low sun keeps the near-horizon palette (the warm sunrise band paints
    itself); high sun blends toward the zenith blue so midday doesn't
    wash out to the near-white the horizon table ends in.
    """
    near = interp_stops(sun.SKY_NEAR_HORIZON, elev)
    zen = interp_stops(sun.SKY_ZENITH, elev)
    w = max(0.0, min(0.85, (elev - 3) / 30))
    return lerp(near, zen, w)


def _dial_stops(sun):
    """A ramp after the Apple Watch Solar Dial face.

    The day view's sky is built around a warm horizon; here the warm
    stop is a narrow seam at 0° and everything else is blue. Night is
    navy rather than the bare background, twilight is slate, and full
    day settles on a mid sky blue that never reaches white, so a long
    polar summer reads as a calm field rather than a glare.
    """
    if sun.theme_legacy_mode:
        return [
            (-18, (12, 16, 40)),
            (-12, (22, 30, 68)),
            ( -8, (48, 62, 112)),
            ( -5, (96, 82, 132)),
            ( -2, (172, 118, 130)),
            (  0, (208, 154, 140)),
            (  2, (236, 190, 150)),
            (  5, (190, 180, 178)),
            (  8, (140, 170, 206)),
            ( 12, (108, 160, 224)),
            ( 18, (100, 156, 224)),
            ( 30, (84, 144, 220)),
            ( 90, (70, 132, 214)),
        ]
    # The day view's blue may settle on ANSI cyan; the dial wants a blue.
    sky = best_contrast((_theme.theme_ansi[4], _theme.theme_ansi[12]),
                        minimum=1.8)
    red, magenta, yellow = sun._SKY_RED, sun._SKY_MAGENTA, sun._SKY_YELLOW
    white = sun._SKY_WHITE
    if is_light_theme():
        # Night dark and day light whatever the page: the night is the
        # day view's navy, the day the theme's blue lifted toward white.
        night = sun.SKY_NIGHT
        day = lerp_rgb(sky, white, 0.50)
    else:
        night = lerp_rgb(_theme.theme_bg, sky, 0.10)
        day = lerp_rgb(sky, white, 0.18)
    slate = lerp_rgb(night, sky, 0.40)
    rose = lerp_rgb(lerp_rgb(magenta, red, 0.30), slate, 0.25)
    peach = lerp_rgb(lerp_rgb(yellow, red, 0.30), white, 0.35)
    # The low sky is hazy — whiter near the horizon, as on a clear day —
    # and settles into the blue as the sun climbs. A soft edge for the
    # day region, not information.
    haze = lerp_rgb(day, white, 0.22)
    return [
        (-18, night),
        (-12, lerp_rgb(night, sky, 0.17)),
        ( -8, slate),
        ( -5, lerp_rgb(slate, magenta, 0.35)),
        ( -2, rose),
        (  0, lerp_rgb(rose, peach, 0.55)),
        (  2, peach),
        (  5, lerp_rgb(peach, haze, 0.45)),
        (  8, lerp_rgb(peach, haze, 0.80)),
        ( 12, haze),
        ( 22, lerp_rgb(haze, day, 0.65)),
        ( 35, lerp_rgb(day, sky, 0.40)),
        ( 90, lerp_rgb(day, sky, 0.60)),
    ]


def _stops_shader(build):
    def shader(sun):
        stops = build(sun)
        return lambda elev: interp_stops(stops, elev)
    return shader


# Named year palettes: each entry takes the sunshine module (whose colors
# are rebuilt on theme reload) and returns elevation → RGB. "dial" is the
# Solar Dial ramp the view is drawn for; "graph" is the day view's own
# sky folded onto elevation, kept because it is the honest answer to
# "what does the day view look like all year". LINECAST_SUNSHINE_YEAR_PALETTE
# picks one.
PALETTES = {
    "graph": lambda sun: (lambda elev: _sky_color(elev, sun)),
    "dial": _stops_shader(_dial_stops),
}
DEFAULT_PALETTE = "dial"


def palette_name(name=None):
    """Resolve a palette name: the argument, the environment, the default."""
    import os
    name = name or os.environ.get("LINECAST_SUNSHINE_YEAR_PALETTE", "")
    return name if name in PALETTES else DEFAULT_PALETTE


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


def _sky_field(lat, lng, graph_w, graph_h, days, tz_offs, palette, sun):
    """Sub-pixel sky rows for the whole year, [spy][x], memoized.

    The field depends on the place, the size, the palette and each day's
    offset, and on nothing that changes between frames. One size and
    palette are on screen at a time, so the cache holds the last field
    and no more; the caller gets a copy to draw the sun into.
    """
    key = (lat, lng, graph_w, graph_h, days, palette, tuple(tz_offs))
    rows = _FIELD_CACHE.get(key)
    if rows is None:
        shader = PALETTES[palette](sun)
        total_spy = graph_h * 2
        rows = [[None] * graph_w for _ in range(total_spy)]
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
                    c = shade[e] = shader(e)
                rows[spy][x] = c
        _FIELD_CACHE.clear()
        _FIELD_CACHE[key] = rows
    return [row[:] for row in rows]


def render_year(lat, lng, now, runtime, tz=None, fullscreen=False,
                dst=False, location_label="", mouse_pos=None,
                palette=None):
    """Build the year-scale sky field display."""
    from linecast import sunshine as sun  # palettes, rebuilt on theme reload

    icons = sun._icon_set(runtime)
    cols, rows = get_terminal_size()

    # The field fills the window; the month labels overlay its bottom
    # row rather than taking a row of their own, so the view ends where
    # the day view (field plus info line) does.
    graph_w = max(30, cols - 2)
    graph_h = max(6, rows - (0 if fullscreen else 5))
    total_spy = graph_h * 2

    year = now.year
    days = 366 if calendar.isleap(year) else 365
    # Each day's own offset is always known: the tooltip speaks the zone
    # a day will be in, even when the field is drawn in one offset.
    day_offs = _day_tz_offsets(year, days, tz)
    if dst:
        tz_offs = day_offs
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
    fb.fb = _sky_field(lat, lng, graph_w, graph_h, days, tz_offs,
                       palette_name(palette), sun)

    # --- today's sun: a point on both axes ---
    x_today = max(0, min(graph_w - 1, int((today_doy - 0.5) / days * graph_w)))
    # The glyph and its glow share a sub-pixel, so the glow cannot round
    # into the cell below the dot.
    spy_now = min(total_spy - 1, int(now_hour / 24 * total_spy))
    e_now = sun.sun_elevation(lat, lng, now_hour, today_doy,
                              tz_offs[today_doy - 1])
    sun_warm = sun.SUN_GLOW_RGB if e_now > -2 else sun.SUN_GLOW_TWILIGHT_RGB
    fb.draw_radial(x_today, spy_now, sun_warm, 5, peak_alpha=0.85)

    # --- hover: which day is the mouse over? ---
    hover_x = None
    if mouse_pos:
        mcol, mrow = mouse_pos
        gx, gy = mcol - 2, mrow - 1  # 1-based terminal → 0-based chart cell
        if 0 <= gx < graph_w and 0 <= gy < graph_h:
            hover_x = gx
            # A column is two or three days wide, so a pointer on the
            # today hairline can land a day off. Within a cell of it,
            # the hover is today.
            if abs(hover_x - x_today) <= 1:
                hover_x = x_today

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
        for x, ch in sun.corner_label_cells(location_label, graph_w):
            overlays[(x, 0)] = (ch, sun.corner_label_ink(fb.cell_bg(x, 0)),
                                False)

    # Month labels, dim, along the bottom row — midnight at every
    # latitude, so the ink darkens only against a polar-summer sky.
    for x, ch in _month_axis_cells(year, days, graph_w, runtime):
        overlays[(x, graph_h - 1)] = (
            ch, sun.corner_label_ink(fb.cell_bg(x, graph_h - 1)), False)

    sun_row = spy_now // 2
    overlays[(x_today, sun_row)] = (icons["sun_char"], sun.SUN_DOT_RGB)

    lines = fb.render(overlays)

    hint = sun.install_banner()
    if hint:
        lines.append(hint)

    tooltip = ""
    if hover_x is not None:
        tooltip = _hover_tooltip(lat, lng, hover_x, mouse_pos[1], graph_w,
                                 graph_h, cols, rows, year, days, tz_offs,
                                 today_doy, runtime, sun, icons,
                                 today=(x_today, now_hour),
                                 day_offs=day_offs, tz=tz)
    # overlay() keeps the cursor-addressed tooltip apart from the body so
    # live_loop draws it after its end-of-screen clear, not before.
    return overlay("\n".join(lines), tooltip)


def _hover_moment(lat, lng, doy, tz_off, mouse_row, graph_h, sun, runtime,
                  now_hour=None, shift=0.0):
    """(hour, label) for the hovered row of a day.

    A row is a coarse slice of the day — forty minutes on a typical
    screen — so the hour is the row's middle, and the label names the
    sky there. When the row lands on solar noon, sunrise or sunset the
    moment snaps to the event and the tooltip says the event's own
    time: the marks worth pointing at are otherwise unhittable.
    """
    row = max(0, min(graph_h - 1, mouse_row - 1))
    hour = (row + 0.5) / graph_h * 24
    reach = 24 / graph_h * 0.6
    # On today's column, a row near the sun glyph is now itself.
    if now_hour is not None and abs(hour - now_hour) <= reach:
        hour = now_hour
    # The axis is the chart's clock; shift moves it into the day's own.
    hour += shift
    sunrise, sunset = sun.solar_times(lat, lng, doy, tz_off)
    noon = (sunrise + sunset) / 2
    events = [("solar_noon", noon)]
    if 0.05 < sunset - sunrise < 23.95:   # the sun does rise and set
        events += [("sunrise", sunrise), ("sunset", sunset)]
    for key, at in events:
        if abs(hour - at) <= reach and 0 <= at < 24:
            return at, sky_event(key, runtime)
    elev = sun.sun_elevation(lat, lng, hour, doy, tz_off)
    return hour, sky_phase(elev, runtime, morning=hour < noon)


def _zone_name(date, tz):
    """The zone's abbreviation at noon on a date: 'EST', 'GMT', '+0530'."""
    noon = date.replace(hour=12)
    local = noon.astimezone() if tz is None else noon.replace(tzinfo=tz)
    name = local.tzname() or ""
    # 'EST', 'CET' — an abbreviation stands as it is. A name with an
    # offset in it ('+05:30', 'UTC+05:30') is shorter as bare %z.
    if not name or any(ch.isdigit() for ch in name):
        name = local.strftime("%z")
    return name


def _hover_tooltip(lat, lng, hover_x, mouse_row, graph_w, graph_h, cols, rows,
                   year, days, tz_offs, today_doy, runtime, sun, icons,
                   today=None, day_offs=None, tz=None):
    """Cursor-positioned tooltip for the hovered day and time, tides-style.

    today is (x_today, now_hour): on that column the day is today and a
    row near the sun glyph reads as now. Times are in the day's own
    offset (day_offs), not the chart's, and carry the zone's name when
    it differs from today's.
    """
    now_hour = None
    if today and hover_x == today[0]:
        doy, now_hour = today_doy, today[1]
    else:
        doy = max(1, min(days, int((hover_x + 0.5) / graph_w * days) + 1))
    date = datetime(year, 1, 1) + timedelta(days=doy - 1)
    day_off = (day_offs or tz_offs)[doy - 1]
    shift = day_off - tz_offs[doy - 1]
    sunrise, sunset, day_len = _day_facts(lat, lng, doy, day_off, sun)
    hour, sky = _hover_moment(lat, lng, doy, day_off, mouse_row,
                              graph_h, sun, runtime, now_hour, shift)
    zone = ""
    if day_offs and day_off != day_offs[today_doy - 1]:
        zone = _zone_name(date, tz)
    _, _, today_len = _day_facts(lat, lng, today_doy,
                                 tz_offs[today_doy - 1], sun)

    rel = relative_day(doy - today_doy, runtime)

    tip_bg = bg(*TIP_BG_RGB)
    tip_fg = fg(*TIP_TEXT_RGB)
    tip_dim = fg(*TIP_DIM_RGB)

    # Through a polar season the rise and set line has nothing to say —
    # solar_times() gives solar noon twice — so the phrase stands in its
    # place. The length and its delta from today stay: they are what
    # makes a polar day worth pointing at.
    polar = sun.polar_state(day_len)
    if polar:
        times = f"{tip_bg}{tip_fg} {polar_name(polar, runtime)} "
    else:
        times = (f"{tip_bg}{tip_fg} {icons['sun_icon']} "
                 f"{fmt_time(sunrise, runtime.use_24h)}  "
                 f"{fmt_time(sunset, runtime.use_24h)} "
                 f"{icons['sunset_icon']} ")

    tip_lines = [
        f"{tip_bg}{tip_fg} {_fmt_month_day(date, runtime)} "
        f"{tip_dim}· {rel} ",
        f"{tip_bg}{tip_fg} {fmt_time(hour % 24, runtime.use_24h)}"
        f"{tip_dim}{' ' + zone if zone else ''} · {sky} ",
        times,
        f"{tip_bg}{tip_fg} {_fmt_len(day_len)} "
        f"{tip_dim}({_fmt_len_delta(day_len - today_len)}) ",
    ]

    # right of the hover hairline, or ending just left of it at the edge
    return _live.pointer_chip(tip_lines, hover_x + 3, mouse_row, cols, rows,
                              pad_bg=tip_bg, flip_at=hover_x + 2)


def _month_axis_cells(year, days, graph_w, runtime):
    """(x, char) overlay cells for the month labels, one per month start.

    Cells, not characters: a wide (CJK) glyph takes two columns — its
    own, and an empty slot after it that the framebuffer skips.
    """
    labels = axis_month_labels(runtime, narrow=graph_w < 72)
    cells = []
    doy = 0
    for m in range(12):
        x = int(doy / days * graph_w)
        for ch in labels[m]:
            w = char_width(ch)
            if x + w > graph_w:
                break
            cells.append((x, ch))
            cells.extend((x + k, "") for k in range(1, w))
            x += w
        doy += calendar.monthrange(year, m + 1)[1]
    return cells
