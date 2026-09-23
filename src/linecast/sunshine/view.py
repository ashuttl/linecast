#!/usr/bin/env python3
"""Solar arc — terminal visualization of the sun's daily journey.

Renders a multi-line graphical display inspired by the Apple Watch Solar
face. Shows the sun's sinusoidal arc above and below the horizon with a
warm glow centered on the sun's current position, seasonal scaling, and day
length with daily delta.

The arc itself is drawn in braille — it is the data. The sky glow renders
in half-block characters with ANSI color at 2x vertical sub-pixel
resolution (true color when available). Location is cached from IP
geolocation (~1 network call per week).

Usage: sunshine [--print] [--oneline] [--json] [--year] [--location PLACE]
                [--icons SET] [--emoji] [--classic-colors]
"""

import math
import sys
from datetime import datetime

from linecast._braille import braille_rows_from_ys
from linecast._graphics import (
    fg, RESET, lerp, interp_stops, visible_len,
    fmt_time, fmt_time_dt, get_terminal_size, Framebuffer, live_loop,
)
from linecast import _theme
from linecast._theme import darken, lighten
from linecast._i18n import table_for
from linecast._location import (
    country_for_defaults, location_is_pinned, location_tzinfo, resolve_location,
)
from linecast._runtime import (
    RuntimeConfig, current_runtime, install_banner, set_current, sunshine_parser,
)
from linecast._glyphs import _icon_set
from linecast.sunshine import solar
from linecast.sunshine.palette import (
    CURVE_COLOR, HORIZON_COLOR, INFO_AMBER_RGB, INFO_DIM_RGB, INFO_PURPLE_RGB,
    INFO_TEXT_RGB, SKY_FAR_HORIZON, SKY_NEAR_HORIZON, SKY_NIGHT, SKY_ZENITH,
    SUN_DOT_RGB, SUN_GLOW_RGB, SUN_GLOW_TWILIGHT_RGB,
)
from linecast.sunshine.solar import polar_state, solar_times, sun_elevation

_theme.track_imports(globals(), "linecast._color")
_theme.track_imports(globals(), "linecast.sunshine.palette")


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------
def corner_label_ink(cell):
    """A dim ink for the corner label over a sky cell, light or dark."""
    luma = 0.30 * cell[0] + 0.59 * cell[1] + 0.11 * cell[2]
    return lighten(cell, 0.45) if luma < 130 else darken(cell, 0.55)


def _corner_limit(graph_w):
    """How much of the top row the corner label may take: half the chart."""
    return max(0, graph_w // 2)


def clock_label(now, runtime, today=None):
    """'2:14p': the time of the shown moment on the location's own clock,
    so a pinned place reads as a world clock. The weekday is added only
    when that moment falls on a different day from the user's own --
    a place across the date line, or the day view scrubbed past
    midnight -- as 'Fri 3:14a'. `today` is the user's date, the
    machine's by default.
    """
    from linecast._i18n import lang_of
    from linecast.weather.i18n import DAY_NAMES
    if today is None:
        today = solar._local_today()
    clock = fmt_time_dt(now, runtime.use_24h)
    if now.date() == today:
        return clock
    day = table_for(DAY_NAMES, lang_of(runtime))[now.weekday()]
    return f"{day} {clock}"


def corner_label(location_label, clock, graph_w):
    """The top-right label: the place and the clock, joined by a middle
    dot, when the corner has room for both; the clock alone when it does
    not, since a truncated place name would cost the time (issue #66).
    """
    if not location_label:
        return clock
    joined = f"{location_label} · {clock}"
    if visible_len(joined) <= _corner_limit(graph_w):
        return joined
    return clock


def corner_label_cells(label, graph_w, left=False):
    """(x, char) overlay cells for a label right-aligned in the top row,
    or left-aligned with *left*, one cell in from the edge.

    Laid out by cell width, so a double-width glyph takes two columns:
    its own, and an empty one after it that the framebuffer skips.
    Truncated to half the chart.
    """
    from linecast._textwidth import char_width
    cells = []
    used = 0
    last_base = None
    limit = _corner_limit(graph_w)
    for ch in label:
        w = char_width(ch)
        if w == 0:
            # A combining mark (a Thai vowel sign, say) rides in its
            # base's cell rather than claiming the next one.
            if last_base is not None:
                x, base = cells[last_base]
                cells[last_base] = (x, base + ch)
            continue
        if used + w > limit:
            break
        cells.append((used, ch))
        last_base = len(cells) - 1
        cells.extend((used + k, "") for k in range(1, w))
        used += w
    x0 = 1 if left else graph_w - used - 1
    return [(x0 + off, ch) for off, ch in cells if 0 <= x0 + off < graph_w]


def render(lat, lng, doy, now_hour, fullscreen=False, offset_minutes=0, runtime=None,
           tz_offset_h=None, location_label="", now=None, hours=None):
    """Build the complete multi-line solar arc display.

    `now` is the shown moment as a datetime, scrubbing included; when
    given, the corner names its time beside the place, and its weekday
    when that is not the user's own. `hours` is the day read in a
    tradition's hours (a _hours.DayHours) for the top-left corner and
    the marks line under the chart, which costs the chart a row.
    """
    if runtime is None:
        runtime = current_runtime(RuntimeConfig)
    icons = _icon_set(runtime)
    cols, rows = get_terminal_size()
    if now is None:
        hours = None

    # --- dimensions: fill the terminal ---
    graph_w = max(30, cols)
    graph_h = max(6, rows - ((2 if hours else 1) if fullscreen else 6))
    total_spy = graph_h * 2

    # --- elevation curve for today ---
    elevations = []
    for x in range(graph_w):
        h = (x + 0.5) / graph_w * 24
        elevations.append(sun_elevation(lat, lng, h, doy, tz_offset_h))

    # --- seasonal vertical scale ---
    summer_peak = sun_elevation(lat, lng, 12, 172, tz_offset_h)
    winter_trough = sun_elevation(lat, lng, 0, 355, tz_offset_h)
    annual_max = max(summer_peak, max(elevations), 5)
    annual_min = min(winter_trough, min(elevations), -5)

    # Horizon placement — proportional to annual range
    horizon_frac = annual_max / (annual_max - annual_min)
    horizon_spy = int(total_spy * horizon_frac)
    horizon_spy = max(2, min(total_spy - 2, horizon_spy))
    # Even, so the horizon hairline's braille cell is entirely sky — its
    # overlay background blends to pure sky and the edge stays crisp.
    horizon_spy -= horizon_spy % 2

    def elev_to_spy(elev):
        """Elevation → sub-pixel row (float). 0=top, total_spy-1=bottom."""
        if elev >= 0:
            return horizon_spy * (1 - elev / annual_max)
        else:
            below = total_spy - horizon_spy
            return horizon_spy + abs(elev) / abs(annual_min) * below

    # Current sun position
    now_x = max(0, min(graph_w - 1, int(now_hour / 24 * graph_w)))
    now_elev = sun_elevation(lat, lng, now_hour, doy, tz_offset_h)
    now_spy = max(0.0, min(total_spy - 1.0, elev_to_spy(now_elev)))

    sunrise, sunset = solar_times(lat, lng, doy, tz_offset_h)

    # --- build framebuffer ---
    fb = Framebuffer(graph_w, graph_h, bg_color=SKY_NIGHT)

    # 1. Sky glow — above horizon, centered on sun, irrespective of arc
    if now_elev > -18:
        sky_near_h = interp_stops(SKY_NEAR_HORIZON, now_elev)
        sky_far_h  = interp_stops(SKY_FAR_HORIZON, now_elev)
        sky_z      = interp_stops(SKY_ZENITH, now_elev)

        # Overall brightness: ramps from 0 at -18° to 1 around +2°
        brightness = max(0, min(1, (now_elev + 18) / 20))

        # Horizontal Gaussian spread: narrow twilight glow → wide daylight fill
        t_sigma = max(0, min(1, (now_elev + 6) / 30))
        glow_sigma = graph_w * (0.12 + 0.30 * t_sigma)

        # Ambient sky floor: even far from sun, some blue during day
        ambient = 0.15 * max(0, min(1, now_elev / 25))

        # Vertical focus: once the sun is up, the glow centers on its plotted
        # height; below the horizon it stays at the horizon, where the light
        # is. Continuous through sunrise since now_spy == horizon_spy there.
        focal_spy = min(now_spy, float(horizon_spy))

        # Vertical spread: concentrated in twilight, fills the sky midday
        t_height = max(0, min(1, (now_elev + 6) / 36))
        v_sigma = max(1.0, horizon_spy * (0.25 + 0.95 * t_height))

        for x in range(graph_w):
            dx = x - now_x
            h_gauss = math.exp(-0.5 * (dx / max(glow_sigma, 1)) ** 2)
            h_intensity = max(ambient, h_gauss)

            # Horizon color blends near↔far based on proximity to sun
            horizon_color = lerp(sky_far_h, sky_near_h, h_gauss)

            for spy in range(0, horizon_spy):
                vert_frac = (horizon_spy - spy) / max(1, horizon_spy)

                # Vertical blend: horizon → zenith color
                sky_color = lerp(horizon_color, sky_z, vert_frac ** 0.65)

                # Vertical intensity falloff around the focal point
                v_factor = math.exp(-0.5 * ((spy - focal_spy) / v_sigma) ** 2)

                intensity = brightness * h_intensity * v_factor
                if intensity > 0.01:
                    fb.set_pixel(x, spy, sky_color, intensity)

    # 2. Curve line — braille, at 2x horizontal / 4x vertical dot resolution.
    # The arc is the data here; it gets the fine-grained rendering, while the
    # glow stays in half-block sub-pixels (like terrain shading on maps).
    total_dots = graph_h * 4
    dot_ys = []
    for i in range(graph_w * 2):
        h = (i + 0.5) / (graph_w * 2) * 24
        e = sun_elevation(lat, lng, h, doy, tz_offset_h)
        dot_ys.append(max(0, min(total_dots - 1, int(round(elev_to_spy(e) * 2)))))
    curve_bits = braille_rows_from_ys(dot_ys, graph_w, graph_h)

    # 3. Sun — radial glow
    sun_spy_i = int(round(now_spy))
    sun_spy_i = max(0, min(total_spy - 1, sun_spy_i))
    sun_r = max(5, int(min(graph_w, total_spy) * 0.04))
    sun_warm = SUN_GLOW_RGB if now_elev > -2 else SUN_GLOW_TWILIGHT_RGB

    fb.draw_radial(now_x, now_spy, sun_warm, sun_r)

    # Sun core — bright center
    for dy in range(-1, 2):
        for dx in range(-1, 2):
            sx, sy = now_x + dx, sun_spy_i + dy
            if 0 <= sx < graph_w and 0 <= sy < total_spy:
                d = math.sqrt(dx * dx + (dy * 1.5) ** 2)
                fb.set_pixel(sx, sy, SUN_DOT_RGB, max(0, 1 - d * 0.5))

    # --- render framebuffer with braille horizon, curve, and sun overlays ---
    overlays = {}
    # Horizon — a dotted hairline (every third braille dot) on the sky side
    # of the boundary. Each dot fades toward the lit sky behind it, so the
    # line dissolves into daylight and only reads where the sky is dark.
    # Yields where the arc passes.
    hz_row = horizon_spy // 2 - 1
    for dot_x in range(0, graph_w * 2, 3):
        ci = dot_x // 2
        if curve_bits[hz_row][ci]:
            continue
        cell = fb.cell_bg(ci, hz_row)
        lit = min(1.0, max(abs(a - b) for a, b in zip(cell, fb.bg)) / 40)
        if lit >= 1.0:
            continue
        dot = 0x40 if dot_x % 2 == 0 else 0x80
        overlays[(ci, hz_row)] = (chr(0x2800 + dot), lerp(HORIZON_COLOR, cell, lit))
    for row in range(graph_h):
        for ci in range(graph_w):
            if curve_bits[row][ci]:
                overlays[(ci, row)] = (chr(0x2800 + curve_bits[row][ci]), CURVE_COLOR)
    # Location and clock, dim, in the top-right corner. The sky there can
    # be anything from night to full daylight, so the hint darkens against
    # a lit cell rather than disappearing into it.
    label = location_label
    if now is not None:
        label = corner_label(location_label, clock_label(now, runtime), graph_w)
    # The tradition's reading of the moment in the other corner, the
    # same dim ink: the halachic hour, the Roman hora, the Edo koku.
    # Where the two would meet, or the reading would run past its half
    # of the row, the place yields first, as it does to a long name,
    # then the reading's second part, then the reading.
    left = ""
    if hours is not None:
        from linecast.sunshine.hours import corner_reading
        left = corner_reading(hours, now, runtime)
        while left and (visible_len(left) > _corner_limit(graph_w)
                        or visible_len(left) + visible_len(label) + 3 > graph_w):
            if label != clock_label(now, runtime):
                label = clock_label(now, runtime)
            elif " · " in left:
                left = left.split(" · ")[0]
            else:
                left = ""
    if label:
        for x, ch in corner_label_cells(label, graph_w):
            cell = fb.cell_bg(x, 0)
            overlays[(x, 0)] = (ch, corner_label_ink(cell), False)
    if left:
        for x, ch in corner_label_cells(left, graph_w, left=True):
            cell = fb.cell_bg(x, 0)
            overlays[(x, 0)] = (ch, corner_label_ink(cell), False)
    sun_cell_row = sun_spy_i // 2
    overlays[(now_x, sun_cell_row)] = (icons["sun_char"], SUN_DOT_RGB)
    # The help hint takes the top-left corner, as in the year view, so
    # the info line stays balanced: sunrise at one end, sunset at the
    # other. With a tradition's reading in that corner, or the sun
    # itself, it falls back to the last line instead.
    from linecast import _help
    from linecast._i18n import lang_of
    lang = lang_of(runtime)
    painted = fullscreen and _help.paint_hint(fb, overlays, lang, rows=(0,))
    lines = fb.render(overlays)

    # --- info line ---
    # With a marks line under the info line, the last line is the marks
    # line.
    hint_w = visible_len(_help.hint(lang, cols)) + 2 if fullscreen and not painted else 0
    info_width = cols if hours else cols - hint_w
    lines.append(
        _info_line(
            lat,
            lng,
            doy,
            sunrise,
            sunset,
            info_width,
            runtime,
            now_hour,
            offset_minutes,
            tz_offset_h,
        )
    )
    if hours is not None:
        from linecast.sunshine.hours import hours_line
        lines.append(hours_line(hours, now, cols - hint_w, runtime))
    if fullscreen and not painted:
        lines[-1] = _help.footer(lines[-1], cols, lang)

    hint = install_banner()
    if hint:
        lines.append(hint)

    return "\n".join(lines)

def _info_line(lat, lng, doy, sunrise, sunset, width, runtime, now_hour=None, offset_minutes=0,
               tz_offset_h=None):
    """Sunrise — day length (delta) — sunset."""
    from linecast.sunshine.i18n import polar_name

    icons = _icon_set(runtime)
    day_len = sunset - sunrise
    dl_h = int(day_len)
    dl_m = int((day_len - dl_h) * 60)

    y_rise, y_set = solar_times(lat, lng, doy - 1, tz_offset_h)
    delta_sec = (day_len - (y_set - y_rise)) * 3600
    d_sign = "+" if delta_sec >= 0 else "−"
    d_abs = abs(delta_sec)
    d_m = int(d_abs) // 60
    d_s = int(d_abs) % 60

    amber = fg(*INFO_AMBER_RGB)
    purple = fg(*INFO_PURPLE_RGB)
    dim = fg(*INFO_DIM_RGB)
    text = fg(*INFO_TEXT_RGB)

    delta_str = f"{d_sign}{d_m}m {d_s}s" if d_s > 0 else f"{d_sign}{d_m}m"

    # Through a polar season there is no sunrise or sunset to print: the
    # dashes stand where the times would, and the phrase takes the place
    # of a day-length delta that is zero every day of it.
    polar = polar_state(day_len)
    rise_txt = "—" if polar else fmt_time(sunrise, runtime.use_24h)
    set_txt = "—" if polar else fmt_time(sunset, runtime.use_24h)

    left = f"{amber}{icons['sun_icon']} {text}{rise_txt}"
    if offset_minutes:
        center = f"{text}{fmt_time(now_hour, runtime.use_24h)}"
    elif polar:
        center = (f"{text}{dl_h}h {dl_m:02d}m "
                  f"{dim}· {polar_name(polar, runtime)}")
    else:
        center = f"{text}{dl_h}h {dl_m:02d}m {dim}({delta_str})"
    right = f"{text}{set_txt} {purple}{icons['sunset_icon']}"

    lw = visible_len(left)
    cw = visible_len(center)
    rw = visible_len(right)

    # The sky at the shown moment, dim, after the center — when it fits.
    # A polar center already names the sky for the whole day.
    if now_hour is not None and not polar:
        sky = _sky_name(lat, lng, doy, now_hour, sunrise, sunset,
                        tz_offset_h, runtime)
        if lw + cw + len(sky) + 3 + rw + 2 <= width:
            center += f" {dim}· {sky}"
            cw = visible_len(center)

    total_gap = max(0, width - lw - cw - rw)
    left_gap = max(1, total_gap // 2)
    right_gap = max(1, total_gap - left_gap)
    line = f"{left}{' ' * left_gap}{center}{' ' * right_gap}{right}"

    return f"{RESET}{line}{RESET}"

def _sky_name(lat, lng, doy, hour, sunrise, sunset, tz_offset_h, runtime):
    """Name the sky at a moment: an event within five minutes, else the phase."""
    from linecast.sunshine.i18n import sky_event, sky_phase
    events = [("solar_noon", (sunrise + sunset) / 2)]
    if 0.05 < sunset - sunrise < 23.95:
        events += [("sunrise", sunrise), ("sunset", sunset)]
    for key, at in events:
        if abs(hour - at) <= 5 / 60:
            return sky_event(key, runtime)
    return sky_phase(sun_elevation(lat, lng, hour, doy, tz_offset_h), runtime,
                     morning=hour < (sunrise + sunset) / 2)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = sunshine_parser()
    args = parser.parse_args()
    runtime = RuntimeConfig.from_sources(args)
    set_current(runtime)

    # --year picks a view. --json and --oneline describe today and have
    # no year form, so the combination is a mistake worth naming rather
    # than a flag to drop on the floor.
    if getattr(args, "year", False) and (runtime.json_mode or runtime.oneline):
        mode = "--json" if runtime.json_mode else "--oneline"
        parser.error(f"--year has no {mode} output "
                     f"(--year is a view; {mode} describes today)")

    lat, lng, country, label = resolve_location(
        args.location, lang=runtime.lang, return_label=True)
    if lat is None:
        print("Could not determine location.", file=sys.stderr)
        sys.exit(1)

    # With no override the resolved location is the user's own; let the
    # units default follow its country (a cold cache resolved without one)
    own = country_for_defaults(args.location, country, lat, lng)
    if own:
        runtime = RuntimeConfig.from_sources(args, country=own)
        set_current(runtime)

    # A pinned location may sit in another time zone; resolve it so times
    # match the location. None (IP-derived location) means machine-local
    # time already is the location's local time.
    tz = location_tzinfo(lat, lng) if location_is_pinned(args.location) else None

    def _now():
        # datetime.now(None) is naive machine-local, matching old behavior.
        return datetime.now(tz)

    def _offset_hours(dt):
        off = dt.utcoffset()
        return None if off is None else off.total_seconds() / 3600

    # The day read in a tradition's hours, from the flag, the saved
    # setting, or the language; None keeps the civil clock alone. The
    # table is built for the shown moment's date, cached by date, so
    # scrubbing pays for it once a day.
    from linecast._hours import hours_now, resolve_hours
    hours_system, hours_variant = resolve_hours(args.hours, runtime.lang)
    # The prayer-time method follows the country of the place shown.
    # resolve_location leaves the country blank for an override, so
    # it is reverse geocoded then (cached), as the moon does for the
    # Hebrew holidays; still blank, the Muslim World League's angles.
    hours_country = country
    if hours_system == "islamic" and not hours_country:
        try:
            from linecast.weather.sources import _reverse_geocode
            hours_country = _reverse_geocode(lat, lng)[1]
        except Exception:
            hours_country = None

    def _hours(now):
        if hours_system is None:
            return None
        return hours_now(hours_system, now, lat, lng, tz, hours_variant,
                         country=hours_country)[0]

    if runtime.json_mode:
        import json
        from linecast.sunshine.json import build_payload
        now = _now()
        print(json.dumps(build_payload(lat, lng, now=now, hours=_hours(now)),
                         ensure_ascii=False))
        return

    if runtime.oneline:
        from linecast._oneline import emit, sunshine_oneline
        now = _now()
        doy = now.timetuple().tm_yday
        now_hour = now.hour + now.minute / 60 + now.second / 3600
        emit(sunshine_oneline(lat, lng, doy, now_hour, runtime,
                              tz_offset_h=_offset_hours(now),
                              hours=_hours(now), now=now))
        return

    live = runtime.live
    year_mode = getattr(args, "year", False)
    dst = getattr(args, "dst", False)

    # Both views name the place in a corner. The forward geocoder already
    # labeled a place-name override; otherwise the (cached) reverse
    # geocoder names the coordinates, as radar does.
    location_label = label
    if not location_label:
        try:
            from linecast.weather.sources import _reverse_geocode
            location_label = _reverse_geocode(
                lat, lng, lang=runtime.lang)[0] or ""
        except Exception:
            location_label = ""
    location_label = (location_label.split(",")[0].strip()
                      or f"{lat:.2f},{lng:.2f}")

    # Day and year keep separate scrub offsets, so flipping between them
    # returns to where each was left. The year view scrubs nothing: the
    # mouse hovers it instead.
    state = {"year": year_mode, "minutes": 0}

    def _render_view(offset_minutes=0, mouse_pos=None, active_alert=None,
                     modal_scroll=0):
        # offset_minutes/active_alert/modal_scroll are ignored; scrubbing
        # is handled here (day view only) rather than by live_loop.
        # The year runs from the right in a right-to-left language; the
        # day's arc is the sky facing the equator, and keeps east where
        # it is.
        from linecast import _bidi
        _bidi.set_mirror(state["year"])
        if state["year"]:
            from linecast.sunshine.year import render_year
            return render_year(
                lat, lng, _now(), runtime, tz=tz, fullscreen=live,
                dst=dst, location_label=location_label,
                mouse_pos=mouse_pos,
            )
        now = _now()
        if state["minutes"]:
            from datetime import timedelta
            now = now + timedelta(minutes=state["minutes"])
        doy = now.timetuple().tm_yday
        now_hour = now.hour + now.minute / 60 + now.second / 3600
        return render(
            lat,
            lng,
            doy,
            now_hour,
            fullscreen=live,
            offset_minutes=state["minutes"],
            runtime=runtime,
            tz_offset_h=_offset_hours(now),
            location_label=location_label,
            now=now,
            hours=_hours(now),
        )

    if not live:
        from linecast._live import print_frame
        from linecast._textwidth import calibrate_from_terminal
        calibrate_from_terminal()
        print_frame(_render_view())
        return

    # A wheel notch or arrow key scrubs 15 minutes of the day view; the
    # year view consumes them without moving. v flips between the two
    # (y still works: the view is --year's).
    def _step(n):
        if not state["year"]:
            state["minutes"] += 15 * n
        return True

    def _intercept(action):
        if action == "fwd":
            return _step(1)
        if action == "back":
            return _step(-1)
        if action == "reset":
            state["minutes"] = 0
            return True
        return False

    def _on_wheel(direction, _col, _row):
        return _step(direction)

    def _on_key(key):
        if key in ("v", "y"):
            state["year"] = not state["year"]
            return True
        return False

    from linecast._help import HelpPanel
    help_panel = HelpPanel(lambda: 'sunshine_year' if state['year'] else 'sunshine',
                           runtime.lang)
    live_loop(_render_view, mouse=True, intercept=_intercept, help_panel=help_panel,
              on_wheel=_on_wheel, on_action=_on_key)
