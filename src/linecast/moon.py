"""Moon phase, illumination, and rise/set times.

Usage: moon [--print] [--oneline] [--json] [--location PLACE] [--icons SET] [--emoji] [--lang CODE]

Renders the Moon itself — a shaded disc with the correct phase terminator,
mare shading, and a soft halo over a star field — plus the current phase and
illuminated fraction, whether the Moon is up right now, the next moonrise
and moonset, and the dates of the next full and new moons. In English the
full moon carries its traditional almanac name (Harvest Moon and the rest),
and a final line gives the day of the year and the next equinox or solstice.
The disc is mirrored for southern-hemisphere observers, who see the Moon
"upside down" relative to the northern view.

Rise/set times use the same low-precision ephemeris as the tides chart's
moon labels (accurate to within a few minutes); phase and illumination come
from the mean synodic cycle, which is what printed almanacs round to as well.
"""

import calendar
import math
import sys
from datetime import datetime, timedelta, timezone

from linecast._framebuffer import fmt_time_dt
from linecast._graphics import (
    fg, RESET, lerp, visible_len, get_terminal_size, Framebuffer, live_loop,
)
from linecast._i18n import lang_of
from linecast._location import (
    location_is_pinned, location_overridden, location_tzinfo, resolve_location,
)
from linecast._moon_i18n import (
    _day_abbrev, _fmt_month_day, _moon_name, _ms, _season_label,
)
from linecast._seasons import full_moon_name, next_season_event
from linecast._textwidth import char_width
from linecast._tides_i18n import _ts  # shared "space to return to now" hint
from linecast._runtime import RuntimeConfig, install_banner, moon_parser, set_current
from linecast import _theme
from linecast._theme import (
    best_contrast,
    darken,
    ensure_contrast,
    neutral_tone,
    surface_bg,
    theme_legacy_mode,
)
from linecast._tides_render import _moon_altitude_deg, _moon_events_for_local_date
from linecast.sunshine import (
    INFO_AMBER_RGB,
    INFO_DIM_RGB,
    INFO_PURPLE_RGB,
    INFO_TEXT_RGB,
    SYNODIC_MONTH,
    moon_cycle_frac,
    moon_phase,
)

# Matches the rise/set threshold in _moon_events_for_local_date: net effect
# of refraction and lunar parallax puts the geometric event at +0.125°.
HORIZON_THRESHOLD_DEG = 0.125

_theme.track_imports(globals(), "linecast.sunshine")

# ---------------------------------------------------------------------------
# Palette
# ---------------------------------------------------------------------------
def _rebuild():
    global MOON_LIT_RGB, MOON_SHADOW_RGB, MOON_GLOW_RGB, STAR_RGB, STAR_DIM_RGB
    if theme_legacy_mode:
        MOON_LIT_RGB = (228, 230, 238)
        MOON_SHADOW_RGB = (36, 40, 56)
        MOON_GLOW_RGB = (150, 160, 190)
        STAR_RGB = (150, 158, 180)
        STAR_DIM_RGB = (84, 92, 115)
    else:
        MOON_LIT_RGB = best_contrast((_theme.theme_ansi[15], _theme.theme_fg), minimum=2.5)
        MOON_SHADOW_RGB = ensure_contrast(surface_bg(0.30), _theme.theme_bg, minimum=1.2)
        MOON_GLOW_RGB = ensure_contrast(neutral_tone(0.60), _theme.theme_bg, minimum=1.8)
        STAR_RGB = ensure_contrast(neutral_tone(0.58), _theme.theme_bg, minimum=2.2)
        STAR_DIM_RGB = ensure_contrast(neutral_tone(0.40), _theme.theme_bg, minimum=1.5)


_rebuild()
_theme.on_reload(_rebuild)

# Near-side maria, in unit-disc coordinates as seen from the northern
# hemisphere (x right/east, y down): (x, y, radius, darkening strength).
# Positions are approximate — this is a portrait, not a chart.
_MARIA = [
    (-0.30, -0.42, 0.26, 0.16),  # Mare Imbrium
    ( 0.08, -0.38, 0.18, 0.15),  # Mare Serenitatis
    ( 0.28, -0.16, 0.20, 0.15),  # Mare Tranquillitatis
    ( 0.62, -0.28, 0.11, 0.14),  # Mare Crisium
    ( 0.48,  0.10, 0.15, 0.12),  # Mare Fecunditatis
    ( 0.32,  0.24, 0.10, 0.10),  # Mare Nectaris
    (-0.55, -0.05, 0.30, 0.13),  # Oceanus Procellarum
    (-0.42,  0.30, 0.11, 0.11),  # Mare Humorum
    (-0.18,  0.32, 0.16, 0.12),  # Mare Nubium
]


def moon_illumination(dt):
    """Illuminated fraction of the lunar disc, in [0, 1].

    For a uniformly lit sphere the fraction is (1 − cos elongation) / 2;
    the mean synodic cycle position stands in for elongation, consistent
    with the accuracy of moon_phase().
    """
    return (1.0 - math.cos(2.0 * math.pi * moon_cycle_frac(dt))) / 2.0


def upcoming_moon_events(now_local, lat, lng):
    """Next (moonrise, moonset) datetimes strictly after *now_local*.

    Scans up to three local calendar days. At high latitudes the Moon can
    stay up (or down) for days, so either value may still be None.
    """
    tzinfo = now_local.tzinfo
    next_rise = None
    next_set = None
    for offset in range(3):
        day = now_local.date() + timedelta(days=offset)
        rise, sset = _moon_events_for_local_date(day, lat, lng, tzinfo)
        if next_rise is None and rise is not None and rise > now_local:
            next_rise = rise
        if next_set is None and sset is not None and sset > now_local:
            next_set = sset
        if next_rise is not None and next_set is not None:
            break
    return next_rise, next_set


def _fmt_event(dt, now_local, runtime):
    """Format an event time, marking events that fall on a later day."""
    if dt is None:
        return "—"
    time_str = fmt_time_dt(dt, use_24h=runtime.use_24h)
    days_ahead = (dt.date() - now_local.date()).days
    if days_ahead == 1:
        return f"{time_str} ({_day_abbrev(dt, runtime)})"
    if days_ahead > 1:
        return f"{time_str} ({_day_abbrev(dt, runtime)}, +{days_ahead}d)"
    return time_str


# ---------------------------------------------------------------------------
# Disc rendering
# ---------------------------------------------------------------------------
def _draw_stars(fb, cx, cy, radius):
    """Sprinkle a deterministic star field, keeping clear of the Moon."""
    keep_out = (radius + 3.0) ** 2
    for spy in range(fb.total_spy):
        dy = spy - cy
        for x in range(fb.graph_w):
            dx = x - cx
            if dx * dx + dy * dy < keep_out:
                continue
            h = (x * 2654435761 + spy * 40503) & 0xFFFFFFFF
            h = ((h ^ (h >> 15)) * 2246822519) & 0xFFFFFFFF
            h ^= h >> 13
            v = h % 1000
            if v < 4:
                fb.set_pixel(x, spy, STAR_RGB, 0.9)
            elif v < 12:
                fb.set_pixel(x, spy, STAR_DIM_RGB, 0.7)


def _maria_shade(sx, sy):
    """Total mare darkening at a unit-disc point, capped for subtlety."""
    m = 0.0
    for bx, by, br, bs in _MARIA:
        dd = ((sx - bx) ** 2 + (sy - by) ** 2) / (br * br)
        if dd < 4.0:
            m += bs * math.exp(-dd)
    return min(0.30, m)


def _draw_moon_disc(fb, cx, cy, radius, frac, southern):
    """Draw the phase-shaded lunar disc centered at (cx, cy) sub-pixels.

    The terminator is the standard phase ellipse: for a chord at height y
    the lit/dark boundary sits at x = cos(2π·frac)·√(1−y²). Waxing phases
    light the right (east) limb in the northern view; the whole view is
    rotated 180° for southern observers.
    """
    theta = 2.0 * math.pi * frac
    c = math.cos(theta)
    waxing = frac < 0.5
    edge = max(1.0 / radius, 0.04)   # anti-aliasing band, in unit radii
    soft = 0.10                       # terminator softness, in unit radii
    scan = int(radius + 2)
    for dy in range(-scan, scan + 1):
        uy = dy / radius
        for dx in range(-scan, scan + 1):
            ux = dx / radius
            rr = ux * ux + uy * uy
            r = math.sqrt(rr)
            if r > 1.0 + edge:
                continue
            cover = min(1.0, ((1.0 + edge) - r) / (2.0 * edge))
            if cover <= 0.02:
                continue

            sx = -ux if southern else ux
            sy = -uy if southern else uy
            chord = math.sqrt(max(0.0, 1.0 - sy * sy))
            d = (sx - c * chord) if waxing else (-c * chord - sx)
            lit_alpha = max(0.0, min(1.0, (d + soft) / (2.0 * soft)))

            shade = _maria_shade(sx, sy) + 0.18 * rr  # maria + limb falloff
            lit_px = darken(MOON_LIT_RGB, min(0.45, shade))
            color = lerp(MOON_SHADOW_RGB, lit_px, lit_alpha)
            fb.set_pixel(cx + dx, cy + dy, color, cover)


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------
def _center(line, width):
    pad = max(0, (width - visible_len(line)) // 2)
    return " " * pad + line


def _first_fit(width, *variants):
    """The widest variant that fits, or None when even the last overflows."""
    for variant in variants:
        if visible_len(variant) <= width:
            return variant
    return None


def _panel_overlays(panel, x0, row0, graph_w):
    """Character overlays for the wide layout's info column.

    *panel* is a list of lines, each a list of (text, rgb, bold)
    segments.  A wide character claims a second, empty cell so the row
    keeps its width; a zero-width character (the emoji variation
    selector) rides along in the cell before it.  Each line also claims
    a clear cell at either end, so no star touches the text.
    """
    overlays = {}
    for i, segments in enumerate(panel):
        x = x0
        prev = None
        if segments and x0 > 0:
            overlays[(x0 - 1, row0 + i)] = (" ", segments[0][1], False)
        for text, color, bold in segments:
            for j, ch in enumerate(text):
                w = char_width(ch, text[j + 1:j + 2])
                if w == 0 and prev is not None:
                    kept, c, b = overlays[prev]
                    overlays[prev] = (kept + ch, c, b)
                    continue
                if x + w > graph_w:
                    break
                overlays[(x, row0 + i)] = (ch, color, bold)
                prev = (x, row0 + i)
                if w == 2:
                    overlays[(x + 1, row0 + i)] = ("", color, bold)
                x += w
        if segments and x < graph_w:
            overlays[(x, row0 + i)] = (" ", segments[-1][1], False)
    return overlays


def render(now_local, lat, lng, runtime, fullscreen=False, offset_minutes=0):
    """Build the full-screen moon display: disc plus info lines.

    Three layouts, by terminal size: a wide terminal floats the info as
    a left-aligned column in the sky beside a full-height disc; a normal
    one stacks centered lines beneath the disc; a small one shortens or
    sheds lines rather than letting them wrap.
    """
    idx, _name, icon = moon_phase(now_local, runtime)
    name = _moon_name(idx, runtime)
    frac = moon_cycle_frac(now_local)
    illum = moon_illumination(now_local)
    age = frac * SYNODIC_MONTH
    alt = _moon_altitude_deg(now_local.astimezone(timezone.utc), lat, lng)
    up = alt > HORIZON_THRESHOLD_DEG
    rise, sset = upcoming_moon_events(now_local, lat, lng)

    days_to_full = ((0.5 - frac) % 1.0) * SYNODIC_MONTH
    days_to_new = ((1.0 - frac) % 1.0) * SYNODIC_MONTH
    full_dt = now_local + timedelta(days=days_to_full)
    new_dt = now_local + timedelta(days=days_to_new)
    event, event_utc = next_season_event(now_local)
    event_local = event_utc.astimezone(now_local.tzinfo)
    days_to_event = (event_utc - now_local).total_seconds() / 86400.0
    year_len = 366 if calendar.isleap(now_local.year) else 365

    # The Old Farmer's Almanac names for the full moon are an English-
    # language tradition; other languages keep the plain phase name.
    full_label = _moon_name(4, runtime)
    if lang_of(runtime) == "en":
        moon_name = full_moon_name(full_dt, SYNODIC_MONTH)
        full_label = ("Blue Moon" if moon_name == "Blue"
                      else f"Full {moon_name} Moon")

    # Text pieces shared by every layout.
    def in_days(days):
        return _ms('in_days', runtime, days=f'{days:.1f}')

    illum_txt = _ms('illuminated', runtime, pct=f'{illum * 100:.0f}')
    age_txt = _ms('age', runtime, age=f'{age:.1f}', total=f'{SYNODIC_MONTH:.1f}')
    alt_txt = _ms('above_horizon', runtime, alt=f'{alt:.0f}')
    below_txt = _ms('below_horizon', runtime)
    rise_when = _fmt_event(rise, now_local, runtime)
    set_when = _fmt_event(sset, now_local, runtime)
    rise_txt = f"{_ms('moonrise', runtime)} {rise_when}"
    set_txt = f"{_ms('moonset', runtime)} {set_when}"
    full_txt = (f"{full_label} {_fmt_month_day(full_dt, runtime)} "
                f"({in_days(days_to_full)})")
    new_label = _moon_name(0, runtime)
    new_txt = (f"{new_label} {_fmt_month_day(new_dt, runtime)} "
               f"({in_days(days_to_new)})")
    year_txt = _ms('year_day', runtime,
                   n=now_local.timetuple().tm_yday, total=year_len)
    season_short = (f"{_season_label(event, lat, runtime)} "
                    f"{_fmt_month_day(event_local, runtime)}")
    season_txt = f"{season_short} ({in_days(days_to_event)})"
    when_txt = (f"{_day_abbrev(now_local, runtime)} "
                f"{_fmt_month_day(now_local, runtime)} "
                f"{fmt_time_dt(now_local, use_24h=runtime.use_24h)}")

    cols, rows = get_terminal_size()
    hint = install_banner()
    # Track even a very narrow terminal rather than overflow it; the
    # floor only guards against a degenerate reported size.
    graph_w = max(16, cols - 2)

    # --- wide layout: the info as a column in the sky beside the disc ---
    T, D, A, P = INFO_TEXT_RGB, INFO_DIM_RGB, INFO_AMBER_RGB, INFO_PURPLE_RGB
    panel = [
        [(f"{icon} {name}", T, True)],
        [(illum_txt, D, False)],
        [(age_txt, D, False)],
        [],
    ]
    if offset_minutes:
        # Scrubbed away from the present: lead with the simulated moment
        # ("Up now" would lie), and show how to get back.
        panel.append([(when_txt, A, False)])
        panel.append([(alt_txt, T, False)] if up else [(below_txt, D, False)])
    elif up:
        panel.append([(_ms('up_now', runtime), A, False),
                      (f" · {alt_txt}", T, False)])
    else:
        panel.append([(below_txt, D, False)])
    panel += [
        [("↑", A, False), (rise_txt, T, False)],
        [("↓", P, False), (set_txt, T, False)],
        [],
        [(full_txt, D, False)],
        [(new_txt, D, False)],
        [],
        [(year_txt, D, False)],
        [(season_txt, D, False)],
    ]
    if offset_minutes:
        panel += [[], [(_ts('space_to_now', runtime), D, False)]]

    panel_w = max(visible_len("".join(t for t, _c, _b in line))
                  for line in panel)
    panel_h = len(panel)
    # Fullscreen fills the terminal exactly (plus the install banner,
    # when present); the plain print leaves two rows for the prompt.
    wide_h = max(6, rows - (1 if hint else 0) - (0 if fullscreen else 2))
    region_w = graph_w - panel_w - 3   # sky left over for the disc
    # Prefer the column: go wide whenever it fits and costs the disc
    # nothing.  Stacking spends five rows on info, so the sky beside a
    # full-height disc wins well before the terminal is truly wide.
    stacked_h = max(6, rows - 5 - (1 if hint else 0) - (0 if fullscreen else 2))
    wide_radius = min(wide_h * 2 * 0.41, region_w * 0.5 - 3.0)
    stacked_radius = min(stacked_h * 2 * 0.41, graph_w * 0.5 - 3.0)
    if wide_radius >= stacked_radius and panel_h + 2 <= wide_h:
        graph_h = wide_h
        total_spy = graph_h * 2
        radius = max(4.0, wide_radius)
        cx = region_w // 2
        cy = total_spy // 2
        fb = Framebuffer(graph_w, graph_h)
        _draw_stars(fb, cx, cy, radius)
        fb.draw_radial(cx, cy, MOON_GLOW_RGB, int(radius * 1.7), aspect=1.0,
                       peak_alpha=0.10 + 0.20 * illum)
        _draw_moon_disc(fb, cx, cy, radius, frac, southern=(lat < 0))
        lines = fb.render(overlays=_panel_overlays(
            panel, graph_w - panel_w - 2, (graph_h - panel_h) // 2, graph_w))
        if hint:
            lines.append(hint)
        return "\n".join(lines)

    # --- stacked layout: centered lines beneath the disc ---
    amber = fg(*INFO_AMBER_RGB)
    purple = fg(*INFO_PURPLE_RGB)
    text = fg(*INFO_TEXT_RGB)
    dim = fg(*INFO_DIM_RGB)

    # Candidate renderings per line, widest first; a small terminal takes
    # the first that fits, and a line whose narrowest form still
    # overflows is dropped rather than left to wrap.
    if offset_minutes:
        status = f"{text}{alt_txt}" if up else f"{dim}{below_txt}"
        status_line = (
            f"{amber}{when_txt}{text} · {status}{text} · "
            f"{dim}{_ts('space_to_now', runtime)}{RESET}",
            f"{amber}{when_txt}{text} · {status}{RESET}",
            f"{amber}{when_txt}{RESET}",
        )
    elif up:
        status_line = (
            f"{amber}{_ms('up_now', runtime)}{text} · {alt_txt}{RESET}",
            f"{amber}{_ms('up_now', runtime)}{text} · {alt:.0f}°{RESET}",
            f"{amber}{_ms('up_now', runtime)}{RESET}",
        )
    else:
        status_line = (f"{dim}{below_txt}{RESET}",)

    candidates = [
        (f"{text}{icon} {name}  {dim}{illum_txt} · {age_txt}{RESET}",
         f"{text}{icon} {name}  {dim}{illum_txt}{RESET}",
         f"{text}{icon} {name}{RESET}"),
        status_line,
        (f"{amber}↑{text}{rise_txt}  {purple}↓{text}{set_txt}{RESET}",
         f"{amber}↑{text}{rise_when}  {purple}↓{text}{set_when}{RESET}"),
        (f"{dim}{full_txt} · {new_txt}{RESET}",
         f"{dim}{_moon_name(4, runtime)} {_fmt_month_day(full_dt, runtime)} · "
         f"{new_label} {_fmt_month_day(new_dt, runtime)}{RESET}",
         f"{dim}{_moon_name(4, runtime)} {_fmt_month_day(full_dt, runtime)}{RESET}"),
        (f"{dim}{year_txt} · {season_txt}{RESET}",
         f"{dim}{year_txt} · {season_short}{RESET}",
         f"{dim}{year_txt}{RESET}"),
    ]
    # Fit against cols - 2 so a line that just fits still gets a column
    # of air at each edge instead of running wall to wall.
    fit_w = max(20, cols - 2)
    info = [line for line in (_first_fit(fit_w, *c) for c in candidates)
            if line is not None]

    # A very short terminal gives up trailing lines (the least essential
    # come last) before squeezing the disc below its minimum height.
    reserve = (1 if hint else 0) + (0 if fullscreen else 2)
    while len(info) > 1 and rows - len(info) - reserve < 6:
        info.pop()

    graph_h = max(6, rows - len(info) - reserve)
    total_spy = graph_h * 2

    # Half-block sub-pixels are roughly square, so one radius serves both
    # axes; the vertical extent is what binds on normal terminals.  The
    # disc takes ~82% of the graph height, leaving sky above and below.
    radius = max(4.0, min(total_spy * 0.41, graph_w * 0.5 - 3.0))
    cx = graph_w // 2
    cy = total_spy // 2

    fb = Framebuffer(graph_w, graph_h)
    _draw_stars(fb, cx, cy, radius)
    fb.draw_radial(cx, cy, MOON_GLOW_RGB, int(radius * 1.7), aspect=1.0,
                   peak_alpha=0.10 + 0.20 * illum)
    _draw_moon_disc(fb, cx, cy, radius, frac, southern=(lat < 0))
    lines = fb.render()

    lines.extend(_center(line, cols) for line in info)

    if hint:
        lines.append(hint)

    return "\n".join(lines)


def main():
    args = moon_parser().parse_args()
    runtime = RuntimeConfig.from_sources(args)
    set_current(runtime)

    lat, lng, country = resolve_location(args.location, lang=runtime.lang)
    if lat is None:
        print("Could not determine location.", file=sys.stderr)
        sys.exit(1)

    # With no override the resolved location is the user's own; let the
    # units default follow its country (a cold cache resolved without one)
    if country and not location_overridden(args.location):
        runtime = RuntimeConfig.from_sources(args, country=country)
        set_current(runtime)

    # A pinned location may sit in another time zone; resolve it so times
    # match the location instead of the machine.
    tz = location_tzinfo(lat, lng) if location_is_pinned(args.location) else None

    def _now():
        return datetime.now(tz) if tz is not None else datetime.now().astimezone()

    if runtime.json_mode:
        import json
        from linecast._moon_json import build_payload
        payload = build_payload(_now(), lat, lng, runtime)
        print(json.dumps(payload, ensure_ascii=False))
        return

    if runtime.oneline:
        from linecast._oneline import moon_oneline
        print(moon_oneline(_now(), lat, lng, runtime))
        return

    live = runtime.live

    def _render(offset_minutes=0, mouse_pos=None, active_alert=None, modal_scroll=0):
        # Extra args are ignored; accepted so moon can use shared live_loop
        # mouse-wheel scrubbing support.
        moment = _now()
        if offset_minutes:
            moment += timedelta(minutes=offset_minutes)
        return render(moment, lat, lng, runtime, fullscreen=live,
                      offset_minutes=offset_minutes)

    if live:
        live_loop(_render, mouse=True)
    else:
        print(_render())


if __name__ == "__main__":
    main()
