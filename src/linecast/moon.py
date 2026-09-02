"""Moon phase, illumination, and rise/set times.

Usage: moon [--print] [--oneline] [--json] [--grid] [--location PLACE] [--icons SET] [--emoji]
            [--lang CODE]

Renders the Moon itself — a shaded disc with the correct phase terminator,
mare shading, and a soft halo over a star field — plus the current phase and
illuminated fraction, whether the Moon is up right now, the next moonrise
and moonset, and the dates of the next full and new moons. In English the
full moon carries its traditional almanac name (Harvest Moon and the rest),
and a final line gives the day of the year and the next equinox or solstice.
The disc is drawn as the observer would see it. Its tilt in the sky is the
Moon's parallactic angle — near pole-up from the north, close to "upside
down" from the south, and turning steadily between moonrise and moonset —
and the terminator lies square to the bright limb, which points at the Sun.

Times and positions come from `_ephemeris.py`, which is good to a couple
of arcminutes: the principal phases land within a quarter of an hour of
the published ones, which is the accuracy an almanac is read at.

In live mode `v` flips to a month-calendar view of the phases (see
`_moon_calendar.py`); the wheel or arrows page months there, space
returns to this month, and clicking a day opens it in the disc view.
"""

import calendar
import math
import sys
import textwrap
from datetime import datetime, timedelta, timezone
from pathlib import Path

from linecast._framebuffer import fmt_time_dt
from linecast._graphics import (
    fg, RESET, lerp, visible_len, get_terminal_size, Framebuffer, live_loop,
)
from linecast._i18n import lang_of
from linecast._location import (
    country_for_defaults, location_is_pinned, location_tzinfo, resolve_location,
)
from linecast._lunisolar import (
    CALENDAR_MERIDIAN_HOURS, CALENDAR_NATIVE_LANG, current_term,
    lunisolar_date, next_lunar_event, next_term, resolve_calendar,
)
from linecast._hebrew import hebrew_date, next_holiday
from linecast._hebrew import next_month_start as next_hebrew_month
from linecast._hijri import (
    after_sunset, hijri_date, next_month_start, next_observance,
)
from linecast._moon_i18n import (
    _day_abbrev, _fmt_month_day, _moon_name, _ms, _season_label,
    anahulu_name, festival_table, hebrew_date_label, hebrew_holiday_name,
    hebrew_month_name, hijri_date_label, hijri_month_name,
    hijri_observance_name, ja_night_name, lunar_date_label,
    pacific_night_label, term_label, thai_festival_name, thai_lunar_label,
    thai_year_label, wan_phra_label,
)
from linecast._pacific import (
    ANAHULU_COUNSEL, COUNSEL_SOURCE_LINE, PACIFIC_CALENDARS, night_note,
    pacific_night,
)
from linecast._thai_lunar import (
    is_wan_phra, next_thai_festival, next_wan_phra, thai_lunar_date,
    year_animal_index,
)
from linecast._seasons import full_moon_name, next_season_event
from linecast._textwidth import char_width
from linecast._tides_i18n import _ts  # shared "space to return to now" hint
from linecast._runtime import (
    RuntimeConfig, install_banner, log_failure, moon_parser, set_current,
)
from linecast import _theme
from linecast._theme import (
    best_contrast,
    darken,
    ensure_contrast,
    is_light_theme,
    lerp_rgb,
    neutral_tone,
    surface_bg,
    theme_legacy_mode,
)
from linecast._radar_i18n import rs
from linecast._ephemeris import (
    _moon_altitude_deg, _moon_azimuth_deg, _moon_events_for_local_date,
    _moon_parallactic_deg, _moon_transits_for_local_date, moon_age_days,
    moon_axis_deg, moon_bright_limb_deg, moon_illuminated_fraction,
    next_moon_phase_utc,
)
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
    global MOON_LIT_RGB, MOON_SHADOW_RGB, MOON_GLOW_RGB, SKY_RGB
    global STAR_BRIGHT_RGB, STAR_RGB, STAR_DIM_RGB
    global PANEL_TEXT_RGB, PANEL_DIM_RGB, PANEL_AMBER_RGB, PANEL_PURPLE_RGB
    global PANEL_FAINT_RGB, INFO_FAINT_RGB
    SKY_RGB = _theme.theme_bg
    if theme_legacy_mode:
        MOON_LIT_RGB = (228, 230, 238)
        MOON_SHADOW_RGB = (36, 40, 56)
        MOON_GLOW_RGB = (150, 160, 190)
        STAR_BRIGHT_RGB = (206, 214, 236)
        STAR_RGB = (150, 158, 180)
        STAR_DIM_RGB = (84, 92, 115)
    elif is_light_theme():
        # The night sky is dark whatever the terminal: a navy from the
        # theme's blue, with a white Moon and stars lifted from the sky.
        blue = best_contrast((_theme.theme_ansi[4], _theme.theme_ansi[12]),
                             minimum=1.8)
        SKY_RGB = darken(blue, 0.80)
        white = (250, 252, 255)
        MOON_LIT_RGB = white
        MOON_SHADOW_RGB = lerp_rgb(SKY_RGB, white, 0.10)
        MOON_GLOW_RGB = lerp_rgb(SKY_RGB, white, 0.55)
        STAR_BRIGHT_RGB = lerp_rgb(SKY_RGB, white, 0.85)
        STAR_RGB = lerp_rgb(SKY_RGB, white, 0.60)
        STAR_DIM_RGB = lerp_rgb(SKY_RGB, white, 0.38)
    else:
        MOON_LIT_RGB = best_contrast((_theme.theme_ansi[15], _theme.theme_fg), minimum=2.5)
        MOON_SHADOW_RGB = ensure_contrast(surface_bg(0.30), _theme.theme_bg, minimum=1.2)
        MOON_GLOW_RGB = ensure_contrast(neutral_tone(0.60), _theme.theme_bg, minimum=1.8)
        STAR_BRIGHT_RGB = ensure_contrast(neutral_tone(0.80), _theme.theme_bg, minimum=3.2)
        STAR_RGB = ensure_contrast(neutral_tone(0.58), _theme.theme_bg, minimum=2.2)
        STAR_DIM_RGB = ensure_contrast(neutral_tone(0.40), _theme.theme_bg, minimum=1.5)
    # The wide layout's panel sits in the sky, so its inks contrast with
    # the sky; the stacked layout's lines sit on the page and keep the
    # page inks.
    PANEL_TEXT_RGB = ensure_contrast(INFO_TEXT_RGB, SKY_RGB, minimum=4.5)
    PANEL_DIM_RGB = ensure_contrast(INFO_DIM_RGB, SKY_RGB, minimum=2.0)
    # A shade fainter than dim, for the counsel's source line.
    PANEL_FAINT_RGB = lerp_rgb(SKY_RGB, PANEL_DIM_RGB, 0.62)
    INFO_FAINT_RGB = lerp_rgb(_theme.theme_bg, INFO_DIM_RGB, 0.62)
    PANEL_AMBER_RGB = ensure_contrast(INFO_AMBER_RGB, SKY_RGB, minimum=2.3)
    PANEL_PURPLE_RGB = ensure_contrast(INFO_PURPLE_RGB, SKY_RGB, minimum=2.3)


_rebuild()
_theme.on_reload(_rebuild)

# The disc's surface comes from NASA's LRO mosaic (see
# scripts/build_moon_albedo.py): a greyscale map of the near side,
# longitude −90…90 left to right, latitude 90…−90 top to bottom, with
# the highlands scaled to white. The view is the mean sub-Earth point
# (librations ignored), north up, east right.
_albedo = None
_albedo_tried = False


def _load_albedo():
    """(width, height, greyscale bytes) of the bundled map, or None."""
    global _albedo, _albedo_tried
    if _albedo_tried:
        return _albedo
    _albedo_tried = True
    try:
        from linecast._png import decode_rgba
        data = (Path(__file__).parent / "data" / "moon_albedo.png").read_bytes()
        w, h, rgba = decode_rgba(data)
        _albedo = (w, h, bytes(rgba[::4]))
    except Exception as exc:
        log_failure("png", "moon albedo load", exc, fallback="plain disc")
        _albedo = None
    return _albedo


def moon_illumination(dt):
    """Illuminated fraction of the lunar disc, in [0, 1]."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return moon_illuminated_fraction(dt.astimezone(timezone.utc))


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


def _fmt_countdown(delta):
    """`48m`, `6h 56m`, `2d 4h` — how long until an event.

    The unit letters are left untranslated, as _fmt_duration does for the
    route readout: they read as symbols rather than words, and a number
    beside a letter survives every layout this has to fit.
    """
    minutes = max(0, int(delta.total_seconds() // 60))
    if minutes < 60:
        return f"{minutes}m"
    if minutes < 60 * 24:
        return f"{minutes // 60}h {minutes % 60:02d}m"
    return f"{minutes // 1440}d {(minutes % 1440) // 60}h"


def _event_phrase(label, dt, now_local, runtime):
    """`Moonrise in 6h 56m (19:48)` — the wait first, the clock time after.

    The countdown is what the question "when does the Moon rise" usually
    means; the absolute time is the check against it.  A later day is
    named inside the parentheses rather than in a second pair.
    """
    if dt is None:
        return f"{label} —"
    when = fmt_time_dt(dt, use_24h=runtime.use_24h)
    days_ahead = (dt.date() - now_local.date()).days
    if days_ahead >= 1:
        when = f"{when} {_day_abbrev(dt, runtime)}"
    ahead = _ms('in_time', runtime, dur=_fmt_countdown(dt - now_local))
    return f"{label} {ahead} ({when})"


def _compass_point(azimuth_deg, runtime):
    """The eight-point compass abbreviation, in the display language."""
    points = rs("compass", lang_of(runtime)).split()
    return points[round(azimuth_deg / 45.0) % 8]


# ---------------------------------------------------------------------------
# Disc rendering
# ---------------------------------------------------------------------------
# Star glyphs by magnitude: (cumulative share of 1000, glyph, brightness,
# bold).  The sky is mostly faint — the pointed glyphs stay rare enough to
# read as individual bright stars rather than as texture.  Brightness runs
# the STAR_DIM → STAR → STAR_BRIGHT ramp.
_STAR_KINDS = (
    (440, "·", 0.00, False),
    (700, "·", 0.42, False),
    (860, "+", 0.62, False),
    (960, "✦", 0.85, True),
    (1000, "✱", 1.00, True),
)

# Cells in a thousand that hold a star at all.
_STAR_DENSITY = 34


def _star_color(t):
    """Colour for a star of brightness *t*, along the three-stop ramp."""
    if t <= 0.5:
        return lerp(STAR_DIM_RGB, STAR_RGB, t * 2.0)
    return lerp(STAR_RGB, STAR_BRIGHT_RGB, (t - 0.5) * 2.0)


def _star_overlays(fb, cx, cy, radius, taken=()):
    """A deterministic star field as character overlays, clear of the Moon.

    Returns {(col, row): (glyph, rgb, bold)}.  Stars are drawn as glyphs
    rather than sub-pixels, so each one claims a whole cell; *taken* is the
    set of cells the info column already owns, which a star must not
    displace.
    """
    keep_out = (radius + 3.0) ** 2
    stars = {}
    for row in range(fb.graph_h):
        dy = (row * 2 + 0.5) - cy   # cell centre, in sub-pixels
        for x in range(fb.graph_w):
            if (x, row) in taken:
                continue
            dx = x - cx
            if dx * dx + dy * dy < keep_out:
                continue
            h = (x * 2654435761 + row * 40503) & 0xFFFFFFFF
            h = ((h ^ (h >> 15)) * 2246822519) & 0xFFFFFFFF
            h ^= h >> 13
            if h % 1000 >= _STAR_DENSITY:
                continue
            # A second, independent draw picks the magnitude, so density
            # and brightness do not vary together across the sky.
            k = ((h >> 10) * 2654435761) & 0xFFFFFFFF
            k ^= k >> 16
            k %= 1000
            for cutoff, glyph, bright, bold in _STAR_KINDS:
                if k < cutoff:
                    stars[(x, row)] = (glyph, _star_color(bright), bold)
                    break
    return stars


def _surface_shade(sx, sy, albedo):
    """Darkening at a unit-disc point, sampled from the albedo map.

    The point is lifted onto the sphere and its latitude and longitude
    looked up in the map with bilinear filtering, so limb foreshortening
    comes out of the projection. Returns 0 for highland-bright, up to 1
    for black.
    """
    w, h, px = albedo
    sz = math.sqrt(max(0.0, 1.0 - sx * sx - sy * sy))
    lat = math.asin(max(-1.0, min(1.0, -sy)))
    lon = math.atan2(sx, sz)                        # −π/2…π/2 on the near side
    u = (lon / math.pi + 0.5) * w - 0.5             # map spans −90…90
    v = (0.5 - lat / math.pi) * h - 0.5
    x0 = int(math.floor(u))
    y0 = int(math.floor(v))
    fx = u - x0
    fy = v - y0
    x0 = max(0, min(w - 1, x0))
    x1 = min(w - 1, x0 + 1)
    y0 = max(0, min(h - 1, y0))
    y1 = min(h - 1, y0 + 1)
    top = px[y0 * w + x0] * (1 - fx) + px[y0 * w + x1] * fx
    bottom = px[y1 * w + x0] * (1 - fx) + px[y1 * w + x1] * fx
    return 1.0 - (top * (1 - fy) + bottom * fy) / 255.0


def _draw_moon_disc(fb, cx, cy, radius, illum, limb_deg, axis_deg):
    """Draw the phase-shaded lunar disc centered at (cx, cy) sub-pixels.

    Two angles set the picture, both screen bearings with 0 straight up
    and 90 to the right. *limb_deg* points at the bright limb, so the
    terminator is drawn square to it; *axis_deg* points at the Moon's
    north pole, so the maria sit the way the observer sees them. They are
    not the same angle and do not move together, which is why they are
    passed separately: the terminator follows the Sun round the Moon over
    a month, while the maria only tilt with the observer.

    The terminator is the standard phase ellipse. For a lit fraction k the
    boundary lies at (1 − 2k)·√(1 − y²) along the bright-limb axis, which
    gives the whole disc at full, a straight edge at the quarters, and
    nothing at new.
    """
    edge = max(1.0 / radius, 0.04)   # anti-aliasing band, in unit radii
    soft = 0.10                       # terminator softness, in unit radii
    scan = int(radius + 2)
    albedo = _load_albedo()

    boundary = 1.0 - 2.0 * illum
    limb = math.radians(limb_deg)
    limb_x, limb_y = math.sin(limb), -math.cos(limb)
    axis = math.radians(axis_deg)
    axis_c, axis_s = math.cos(axis), math.sin(axis)

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

            # Distance past the terminator, along the bright-limb axis.
            along = ux * limb_x + uy * limb_y
            across = ux * -limb_y + uy * limb_x
            d = along - boundary * math.sqrt(max(0.0, 1.0 - across * across))
            lit_alpha = max(0.0, min(1.0, (d + soft) / (2.0 * soft)))

            shade = 0.18 * rr  # limb falloff
            if albedo is not None:
                shade += _surface_shade(ux * axis_c + uy * axis_s,
                                        -ux * axis_s + uy * axis_c, albedo)
            lit_px = darken(MOON_LIT_RGB, min(0.55, shade))
            color = lerp(MOON_SHADOW_RGB, lit_px, lit_alpha)
            fb.set_pixel(cx + dx, cy + dy, color, cover)


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------
def _center(line, width):
    pad = max(0, (width - visible_len(line)) // 2)
    return " " * pad + line


def _wrap(text, width):
    """textwrap.wrap without widows: no lone word on the last line."""
    lines = textwrap.wrap(text, width)
    if len(lines) > 1 and " " not in lines[-1]:
        head, last = lines[-2].rsplit(" ", 1)
        lines[-2:] = [head, f"{last} {lines[-1]}"]
    return lines


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


def _next_phase_local(moment_utc, target_frac, now_local):
    """Next new or full moon, in the observer's timezone.

    Falls back to a mean-synodic estimate if the search comes up empty,
    so the panel still has a date to print.
    """
    found = next_moon_phase_utc(moment_utc, target_frac)
    if found is None:
        frac = moon_cycle_frac(now_local)
        ahead = ((target_frac - frac) % 1.0) * SYNODIC_MONTH
        return now_local + timedelta(days=ahead)
    return found.astimezone(now_local.tzinfo)


def calendar_headline(cal, now_local, lat, lng, runtime, lang):
    """(name, aside) the calendar puts in the headline, either None.

    The Pacific calendars name the night, so the name stands in for the
    phase name; Japanese in Japanese names it too (居待月 on the old
    calendar's 18th, whatever octant the phase rounds to). The aside is
    the lunar date — Chinese, Japanese, Korean, Thai, Hijri (turned at
    the reader's sunset), Hebrew (the same) — or the anahulu, or the
    almanac's half of the month. A calendar shown in its own language
    keeps its own script; any other language gets the English names.
    """
    if cal is None:
        return None, None
    if cal in PACIFIC_CALENDARS:
        night, nights = pacific_night(cal, now_local.date())
        name = pacific_night_label(cal, night, nights)
        aside = f"anahulu {anahulu_name(night)}" if cal == "hawaiian" else None
        return name, aside
    if cal == "almanac":
        half = "light" if moon_cycle_frac(now_local) < 0.5 else "dark"
        return None, _ms(f'{half}_of_moon', runtime)
    if cal in ("islamic", "hebrew"):
        h_day = now_local.date()
        if after_sunset(now_local, lat, lng):
            h_day += timedelta(days=1)
        if cal == "islamic":
            return None, hijri_date_label(*hijri_date(h_day), lang)
        return None, hebrew_date_label(*hebrew_date(h_day))
    if cal == "thai":
        label_lang = "th" if lang == "th" else "en"
        t_month, t_day, t_doubled = thai_lunar_date(now_local.date())
        return None, thai_lunar_label(t_month, t_day, t_doubled, label_lang)
    label_lang = lang if CALENDAR_NATIVE_LANG[cal] == lang else "en"
    lunar = lunisolar_date(now_local.date(), CALENDAR_MERIDIAN_HOURS[cal])
    if lunar is None:
        return None, None
    name = ja_night_name(lunar[1]) if label_lang == "ja" else None
    return name, lunar_date_label(*lunar, label_lang)


def keeps_israel_days(country, lat, lng):
    """Whether the viewed place keeps the Hebrew holidays as Israel does.

    The second day of Yom Tov is a rule about where the reader is, so
    the answer is the country of the location shown, not the user's
    own. resolve_location leaves the country blank for an override, so
    it is reverse geocoded then (cached); still blank, as offline with
    a cold cache, stays diaspora.
    """
    if not country:
        from linecast._weather_sources import _reverse_geocode
        _name, country, _addr = _reverse_geocode(lat, lng)
    return (country or "").upper() == "IL"


def render(now_local, lat, lng, runtime, fullscreen=False, offset_minutes=0,
           calendar_name=None, israel=False):
    """Build the full-screen moon display: disc plus info lines.

    Three layouts, by terminal size: a wide terminal floats the info as
    a left-aligned column in the sky beside a full-height disc; a normal
    one stacks centered lines beneath the disc; a small one shortens or
    sheds lines rather than letting them wrap.
    """
    idx, _name, icon = moon_phase(now_local, runtime)
    name = _moon_name(idx, runtime)
    illum = moon_illumination(now_local)
    moment_utc = now_local.astimezone(timezone.utc)
    age = moon_age_days(moment_utc)
    alt = _moon_altitude_deg(moment_utc, lat, lng)
    up = alt > HORIZON_THRESHOLD_DEG
    bearing = _compass_point(_moon_azimuth_deg(moment_utc, lat, lng), runtime)
    # Where the bright limb and the Moon's north pole fall on screen.
    # Position angles run from celestial north through east, which is
    # anticlockwise with north up; the parallactic angle then says how
    # far celestial north itself is turned from the observer's vertical.
    parallactic = _moon_parallactic_deg(moment_utc, lat, lng)
    limb = parallactic - moon_bright_limb_deg(moment_utc)
    axis = parallactic - moon_axis_deg(moment_utc)
    rise, sset = upcoming_moon_events(now_local, lat, lng)

    full_dt = _next_phase_local(moment_utc, 0.5, now_local)
    new_dt = _next_phase_local(moment_utc, 0.0, now_local)
    days_to_full = (full_dt - now_local).total_seconds() / 86400.0
    days_to_new = (new_dt - now_local).total_seconds() / 86400.0
    event, event_utc = next_season_event(now_local)
    event_local = event_utc.astimezone(now_local.tzinfo)
    days_to_event = (event_utc - now_local).total_seconds() / 86400.0
    year_len = 366 if calendar.isleap(now_local.year) else 365

    # The Old Farmer's Almanac names for the full moon are an English-
    # language tradition: they show in English by default and with the
    # almanac calendar, but a panel reading the moon through another
    # tradition's calendar keeps the plain phase name — Harvest Moon
    # is the almanac's name, not the Kaulana Mahina's or the 农历's.
    lang = lang_of(runtime)
    cal = resolve_calendar(calendar_name, lang)
    # The headline is the calendar's: the night's name where the
    # calendar names nights, and the lunar date or the almanac's half
    # of the month as an aside. The one-line summary shows the same.
    cal_name, lunar_txt = calendar_headline(cal, now_local, lat, lng,
                                            runtime, lang)
    if cal_name:
        name = cal_name
    full_label = _moon_name(4, runtime)
    if lang == "en" and cal in (None, "almanac"):
        moon_name = full_moon_name(full_dt, SYNODIC_MONTH)
        full_label = ("Blue Moon" if moon_name == "Blue"
                      else f"Full {moon_name} Moon")

    # Text pieces shared by every layout.
    def in_days(days):
        return _ms('in_days', runtime, days=f'{days:.1f}')

    illum_txt = _ms('illuminated', runtime, pct=f'{illum * 100:.0f}')
    age_txt = _ms('age', runtime, age=f'{age:.1f}', total=f'{SYNODIC_MONTH:.1f}')
    alt_txt = _ms('above_horizon', runtime, alt=f'{alt:.0f}')
    # After "Up now" the long phrase is redundant — being up is the whole
    # claim — so the altitude goes short and spends the room on where to
    # actually look.
    alt_dir_txt = f"{alt:.0f}° · {bearing}"
    below_txt = _ms('below_horizon', runtime)
    rise_when = _fmt_event(rise, now_local, runtime)
    set_when = _fmt_event(sset, now_local, runtime)
    rise_txt = _event_phrase(_ms('moonrise', runtime), rise, now_local, runtime)
    set_txt = _event_phrase(_ms('moonset', runtime), sset, now_local, runtime)
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

    # The traditional calendar: on by default for the languages whose
    # readers know the moon through it, and available to anyone with
    # --calendar or `linecast calendar`. The Chinese, Japanese, and
    # Korean calendars read the moon as a date — the lunar day beside
    # the phase, the solar term in progress, the coming festival. The
    # Pacific calendars read it as a named night, the Hawaiian one
    # with its counsel, and the almanac is the English-language
    # reading of the same kind: the Old Farmer's gardening rule and
    # the solunar periods.
    # A calendar shown in its own language keeps its own script; any
    # other language gets the customary English names.
    term_txt = term_short = fest_txt = fest_short = None
    good_txt = hold_txt = solunar_txt = attrib_txt = None
    if cal in PACIFIC_CALENDARS:
        # The Pacific calendars name every night, in their own
        # language for every reader — the names have no English
        # renderings — and have no solar terms or lunar-dated
        # festivals: the headline is the night. The name already says
        # which night of the month this is, so "day 20.2 of 29.5"
        # would read as a rival count; the age keeps its astronomical
        # name and shares a line with the illumination.
        night, _nights = pacific_night(cal, now_local.date())
        age_txt = _ms('lunar_age', runtime, age=f'{age:.1f}')
        if cal == "hawaiian":
            # The Kaulana Mahina adds the anahulu beside the name, and
            # the counsel lines below: the night's kapu or ʻole note
            # when it has one, the anahulu's fishing counsel, and the
            # source named plainly.
            note = night_note(name)
            counsel = ANAHULU_COUNSEL[anahulu_name(night)]
            good_txt, hold_txt = (note or counsel), (counsel if note else None)
            attrib_txt = COUNSEL_SOURCE_LINE
    elif cal == "almanac":
        # The Old Farmer's Almanac: the aside names the half of the
        # month, the counsel is the gardening rule for it, and the
        # solunar periods put the majors at the Moon's meridian
        # passes, the minors at moonrise and moonset.
        waxing = moon_cycle_frac(now_local) < 0.5
        half = "light" if waxing else "dark"
        good_txt = _ms('good_for', runtime,
                       things=_ms(f'{half}_good', runtime))
        hold_txt = _ms('hold_off', runtime,
                       things=_ms(f'{half}_hold', runtime))
        upper, lower = _moon_transits_for_local_date(
            now_local.date(), lng, now_local.tzinfo)
        day_rise, day_set = _moon_events_for_local_date(
            now_local.date(), lat, lng, now_local.tzinfo)

        def _times(moments):
            times = sorted(t for t in moments if t is not None)
            return " · ".join(fmt_time_dt(t, use_24h=runtime.use_24h)
                              for t in times) or "—"

        solunar_txt = (f"{_ms('solunar_major', runtime)} "
                       f"{_times((upper, lower))}  "
                       f"{_ms('solunar_minor', runtime)} "
                       f"{_times((day_rise, day_set))}")
    elif cal == "islamic":
        # The Hijri day begins at sunset, and the panel is read in the
        # evening, so the date turns with the reader's own sunset. The
        # calendar keeps no solar terms; the coming month takes the
        # terms' place. The observances keep civil dates, except that
        # one counts as begun once the evening that opens it has come,
        # and the day before, the countdown says so instead of "in
        # 1d" — the same rule as the Hebrew calendar's below.
        h_day = now_local.date()
        if after_sunset(now_local, lat, lng):
            h_day += timedelta(days=1)
        h_year, h_month, h_dom = hijri_date(h_day)
        term_short = hijri_month_name(h_month, lang)
        nxt_day, (_nxt_year, nxt_month) = next_month_start(h_day)
        nxt_gap = (nxt_day - now_local.date()).days
        term_txt = (f"{term_short} · {hijri_month_name(nxt_month, lang)} "
                    f"{_fmt_month_day(nxt_day, runtime)} "
                    f"({_ms('in_days', runtime, days=str(nxt_gap))})")
        fest_day, fest_key = next_observance(h_day)
        fest_gap = (fest_day - now_local.date()).days
        if fest_day <= h_day:
            fest_txt = fest_short = hijri_observance_name(fest_key, lang)
        else:
            fest_short = (f"{hijri_observance_name(fest_key, lang)} "
                          f"{_fmt_month_day(fest_day, runtime)}")
            fest_txt = f"{fest_short} ({_ms('begins_at_sunset', runtime)})" \
                if fest_gap == 1 else (
                    f"{fest_short} "
                    f"({_ms('in_days', runtime, days=str(fest_gap))})")
    elif cal == "hebrew":
        # The Hebrew day begins at sunset too, and the date turns with
        # the reader's own. The coming month takes the terms' place
        # and the holidays are counted down as the observances are
        # above, in progress from the evening that opens them.
        h_day = now_local.date()
        if after_sunset(now_local, lat, lng):
            h_day += timedelta(days=1)
        h_year, h_month, h_dom = hebrew_date(h_day)
        term_short = hebrew_month_name(h_year, h_month)
        nxt_day, (nxt_year, nxt_month) = next_hebrew_month(h_day)
        nxt_gap = (nxt_day - now_local.date()).days
        term_txt = (f"{term_short} · {hebrew_month_name(nxt_year, nxt_month)} "
                    f"{_fmt_month_day(nxt_day, runtime)} "
                    f"({_ms('in_days', runtime, days=str(nxt_gap))})")
        fest_day, fest_key = next_holiday(h_day, israel)
        fest_gap = (fest_day - now_local.date()).days
        if fest_day <= h_day:
            fest_txt = fest_short = hebrew_holiday_name(fest_key)
        else:
            fest_short = (f"{hebrew_holiday_name(fest_key)} "
                          f"{_fmt_month_day(fest_day, runtime)}")
            fest_txt = f"{fest_short} ({_ms('begins_at_sunset', runtime)})" \
                if fest_gap == 1 else (
                    f"{fest_short} "
                    f"({_ms('in_days', runtime, days=str(fest_gap))})")
    elif cal == "thai":
        # The Thai calendar reads the moon as a waxing or waning day —
        # ขึ้น/แรม … ค่ำ — in Thai numerals, as the printed calendars
        # have it. It keeps no solar terms; the recurring observance is
        # the วันพระ, the four holy days of each month, so that line
        # takes the terms' place, led by the year's animal.
        label_lang = "th" if lang == "th" else "en"
        term_short = thai_year_label(year_animal_index(now_local.date()),
                                     label_lang)
        if is_wan_phra(now_local.date()):
            term_txt = f"{term_short} · {wan_phra_label(True, label_lang)}"
        else:
            wp = next_wan_phra(now_local.date())
            wp_gap = (wp - now_local.date()).days
            term_txt = (f"{term_short} · {wan_phra_label(False, label_lang)} "
                        f"{_fmt_month_day(wp, runtime)} "
                        f"({_ms('in_days', runtime, days=str(wp_gap))})")
        fest_day, fest_key = next_thai_festival(now_local.date())
        fest_short = (f"{thai_festival_name(fest_key, label_lang)} "
                      f"{_fmt_month_day(fest_day, runtime)}")
        fest_gap = (fest_day - now_local.date()).days
        fest_txt = fest_short if fest_gap == 0 else (
            f"{fest_short} "
            f"({_ms('in_days', runtime, days=str(fest_gap))})")
    elif cal is not None:
        cal_tz = CALENDAR_MERIDIAN_HOURS[cal]
        label_lang = lang if CALENDAR_NATIVE_LANG[cal] == lang else "en"
        cur_k, _cur_start = current_term(moment_utc)
        nxt_k, nxt_start = next_term(moment_utc)
        nxt_local = nxt_start.astimezone(now_local.tzinfo)
        days_to_term = (nxt_start - moment_utc).total_seconds() / 86400.0
        term_short = term_label(cur_k, label_lang)
        term_txt = (f"{term_short} · {term_label(nxt_k, label_lang)} "
                    f"{_fmt_month_day(nxt_local, runtime)} "
                    f"({in_days(days_to_term)})")
        fest = next_lunar_event(now_local.date(), cal_tz,
                                festival_table(cal, label_lang != "en"))
        if fest is not None:
            fest_day, fest_name = fest
            fest_short = f"{fest_name} {_fmt_month_day(fest_day, runtime)}"
            fest_gap = (fest_day - now_local.date()).days
            fest_txt = fest_short if fest_gap == 0 else (
                f"{fest_short} "
                f"({_ms('in_days', runtime, days=str(fest_gap))})")

    # The headline has room for one aside: the calendar's own — the
    # lunar date, the anahulu, or the almanac's half of the month.
    head_extra = lunar_txt

    cols, rows = get_terminal_size()
    hint = install_banner()
    # Track even a very narrow terminal rather than overflow it; the
    # floor only guards against a degenerate reported size.
    graph_w = max(16, cols - 2)

    # --- wide layout: the info as a column in the sky beside the disc ---
    T, D, A, P = PANEL_TEXT_RGB, PANEL_DIM_RGB, PANEL_AMBER_RGB, PANEL_PURPLE_RGB
    panel = [
        [(f"{icon} {name}", T, True)] + (
            [(f" · {head_extra}", T, False)] if head_extra else []),
    ]
    if cal in PACIFIC_CALENDARS:
        panel.append([(f"{illum_txt} · {age_txt}", D, False)])
    else:
        panel += [[(illum_txt, D, False)], [(age_txt, D, False)]]
    panel.append([])
    # The counsel reads the night the headline names, so it goes right
    # here — inserted once the rest of the panel has fixed the column,
    # so it can wrap against that width instead of setting it.
    counsel_at = len(panel)
    if offset_minutes:
        # Scrubbed away from the present: lead with the simulated moment
        # ("Up now" would lie), and show how to get back.
        panel.append([(when_txt, A, False)])
        panel.append([(f"{alt_txt} · {bearing}", T, False)] if up
                     else [(below_txt, D, False)])
    elif up:
        panel.append([(_ms('up_now', runtime), A, False),
                      (f" · {alt_dir_txt}", T, False)])
    else:
        panel.append([(below_txt, D, False)])
    panel += [
        [("↑", A, False), (rise_txt, T, False)],
        [("↓", P, False), (set_txt, T, False)],
        [],
    ]
    panel += [
        [(full_txt, D, False)],
        [(new_txt, D, False)],
        [],
    ]
    if term_txt:
        panel.append([(term_txt, D, False)])
    if fest_txt:
        panel.append([(fest_txt, T, False)])
    if term_txt or fest_txt:
        panel.append([])
    panel += [
        [(year_txt, D, False)],
        [(season_txt, D, False)],
    ]
    if offset_minutes:
        panel += [[], [(_ts('space_to_now', runtime), D, False)]]

    # A long counsel line breaks rather than dragging the whole column
    # wide: it may run at most a third past the longest other line.
    if good_txt:
        base_w = max(visible_len("".join(t for t, _c, _b in line))
                     for line in panel)
        wrap_w = max(int(base_w * 1.3), 28)
        block = [[(seg, D, False)]
                 for txt in (good_txt, hold_txt, solunar_txt) if txt
                 for seg in _wrap(txt, wrap_w)]
        if attrib_txt:
            # The source rides directly under the counsel it credits,
            # a shade fainter.
            block.append([(attrib_txt, PANEL_FAINT_RGB, False)])
        panel[counsel_at:counsel_at] = block + [[]]

    panel_w = max(visible_len("".join(t for t, _c, _b in line))
                  for line in panel)
    panel_h = len(panel)
    # Fullscreen fills the terminal exactly (plus the install banner,
    # when present); the plain print leaves two rows for the prompt.
    chrome = 1 if hint else 0
    wide_h = max(6, rows - chrome - (0 if fullscreen else 2))
    region_w = graph_w - panel_w - 3   # sky left over for the disc
    # Prefer the column: go wide whenever it fits and costs the disc
    # nothing.  Stacking spends five rows on info, so the sky beside a
    # full-height disc wins well before the terminal is truly wide.
    stacked_h = max(6, rows - 5 - chrome - (0 if fullscreen else 2))
    wide_radius = min(wide_h * 2 * 0.41, region_w * 0.5 - 3.0)
    stacked_radius = min(stacked_h * 2 * 0.41, graph_w * 0.5 - 3.0)
    if wide_radius >= stacked_radius and panel_h + 2 <= wide_h:
        graph_h = wide_h
        total_spy = graph_h * 2
        radius = max(4.0, wide_radius)
        cx = region_w // 2
        cy = total_spy // 2
        overlays = _panel_overlays(
            panel, graph_w - panel_w - 2, (graph_h - panel_h) // 2, graph_w)
        fb = Framebuffer(graph_w, graph_h, bg_color=SKY_RGB)
        fb.draw_radial(cx, cy, MOON_GLOW_RGB, int(radius * 1.7), aspect=1.0,
                       peak_alpha=0.10 + 0.20 * illum)
        _draw_moon_disc(fb, cx, cy, radius, illum, limb, axis)
        stars = _star_overlays(fb, cx, cy, radius, taken=overlays.keys())
        lines = fb.render(overlays={**stars, **overlays})
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
        status = (f"{text}{alt_txt} · {bearing}" if up
                  else f"{dim}{below_txt}")
        status_line = (
            f"{amber}{when_txt}{text} · {status}{text} · "
            f"{dim}{_ts('space_to_now', runtime)}{RESET}",
            f"{amber}{when_txt}{text} · {status}{RESET}",
            f"{amber}{when_txt}{RESET}",
        )
    elif up:
        status_line = (
            f"{amber}{_ms('up_now', runtime)}{text} · {alt_dir_txt}{RESET}",
            f"{amber}{_ms('up_now', runtime)}{text} · {alt:.0f}°{RESET}",
            f"{amber}{_ms('up_now', runtime)}{RESET}",
        )
    else:
        status_line = (f"{dim}{below_txt}{RESET}",)

    if head_extra:
        head_line = (
            f"{text}{icon} {name} · {head_extra}  "
            f"{dim}{illum_txt} · {age_txt}{RESET}",
            f"{text}{icon} {name} · {head_extra}  {dim}{illum_txt}{RESET}",
            f"{text}{icon} {name} · {head_extra}{RESET}",
            f"{text}{icon} {name}{RESET}")
    else:
        head_line = (
            f"{text}{icon} {name}  {dim}{illum_txt} · {age_txt}{RESET}",
            f"{text}{icon} {name}  {dim}{illum_txt}{RESET}",
            f"{text}{icon} {name}{RESET}")

    # Fit against cols - 2 so a line that just fits still gets a column
    # of air at each edge instead of running wall to wall.
    fit_w = max(20, cols - 2)
    candidates = [head_line]
    if good_txt:
        # The counsel follows the name it reads, wrapped to the width
        # rather than shed.
        candidates += [(f"{dim}{seg}{RESET}",)
                       for txt in (good_txt, hold_txt) if txt
                       for seg in _wrap(txt, fit_w)]
        if solunar_txt:
            candidates.append((f"{dim}{solunar_txt}{RESET}",))
        if attrib_txt:
            candidates.append((f"{fg(*INFO_FAINT_RGB)}{attrib_txt}{RESET}",))
    candidates += [
        status_line,
        # The countdown roughly doubles this line's width, so keep the
        # plain labelled time between it and the bare clock times —
        # otherwise a middle-width terminal drops the labels entirely.
        (f"{amber}↑{text}{rise_txt}  {purple}↓{text}{set_txt}{RESET}",
         f"{amber}↑{text}{_ms('moonrise', runtime)} {rise_when}  "
         f"{purple}↓{text}{_ms('moonset', runtime)} {set_when}{RESET}",
         f"{amber}↑{text}{rise_when}  {purple}↓{text}{set_when}{RESET}"),
    ]
    if term_txt:
        # The calendar line, the festival leading since it is the one
        # people wait for.
        candidates.append(
            (f"{dim}{term_txt} · {text}{fest_txt}{RESET}",
             f"{text}{fest_txt}  {dim}{term_short}{RESET}",
             f"{text}{fest_short}{RESET}")
            if fest_txt else
            (f"{dim}{term_txt}{RESET}",
             f"{dim}{term_short}{RESET}"))
    candidates += [
        (f"{dim}{full_txt} · {new_txt}{RESET}",
         f"{dim}{full_label} {_fmt_month_day(full_dt, runtime)} · "
         f"{new_label} {_fmt_month_day(new_dt, runtime)}{RESET}",
         f"{dim}{_moon_name(4, runtime)} {_fmt_month_day(full_dt, runtime)}{RESET}"),
        (f"{dim}{year_txt} · {season_txt}{RESET}",
         f"{dim}{year_txt} · {season_short}{RESET}",
         f"{dim}{year_txt}{RESET}"),
    ]
    info = [line for line in (_first_fit(fit_w, *c) for c in candidates)
            if line is not None]

    # A very short terminal gives up trailing lines (the least essential
    # come last) before squeezing the disc below its minimum height.
    reserve = chrome + (0 if fullscreen else 2)
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

    fb = Framebuffer(graph_w, graph_h, bg_color=SKY_RGB)
    fb.draw_radial(cx, cy, MOON_GLOW_RGB, int(radius * 1.7), aspect=1.0,
                   peak_alpha=0.10 + 0.20 * illum)
    _draw_moon_disc(fb, cx, cy, radius, illum, limb, axis)
    lines = fb.render(overlays=_star_overlays(fb, cx, cy, radius))

    lines.extend(_center(line, cols) for line in info)

    if hint:
        lines.append(hint)

    return "\n".join(lines)


def main():
    parser = moon_parser()
    args = parser.parse_args()
    runtime = RuntimeConfig.from_sources(args)
    set_current(runtime)

    # --grid picks a view, as sunshine's --year does. --json and
    # --oneline describe the moment and have no grid form.
    if args.grid and (runtime.json_mode or runtime.oneline):
        mode = "--json" if runtime.json_mode else "--oneline"
        parser.error(f"--grid has no {mode} output "
                     f"(--grid is a view; {mode} describes now)")

    lat, lng, country = resolve_location(args.location, lang=runtime.lang)
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
    # match the location instead of the machine.
    tz = location_tzinfo(lat, lng) if location_is_pinned(args.location) else None

    def _now():
        return datetime.now(tz) if tz is not None else datetime.now().astimezone()

    # The Hebrew holidays follow the place shown; the check costs a
    # reverse geocode for an override, so only that calendar pays it.
    israel = (resolve_calendar(args.calendar, lang_of(runtime)) == "hebrew"
              and keeps_israel_days(country, lat, lng))

    if runtime.json_mode:
        import json
        from linecast._moon_json import build_payload
        payload = build_payload(_now(), lat, lng, runtime,
                                calendar=args.calendar, israel=israel)
        print(json.dumps(payload, ensure_ascii=False))
        return

    if runtime.oneline:
        from linecast._oneline import moon_oneline
        print(moon_oneline(_now(), lat, lng, runtime, calendar=args.calendar))
        return

    live = runtime.live

    # The disc and the calendar keep separate scrub offsets, so flipping
    # between them returns to where each was left: minutes through the
    # disc's time, whole months through the calendar. --grid opens on
    # the calendar; v flips either way.
    state = {"cal": args.grid, "minutes": 0, "months": 0}

    def _render(offset_minutes=0, mouse_pos=None, active_alert=None, modal_scroll=0):
        # offset_minutes/active_alert/modal_scroll are ignored; scrubbing
        # is handled here (per view) rather than by live_loop.
        if state["cal"]:
            from linecast._moon_calendar import render_calendar
            return render_calendar(_now(), lat, lng, runtime,
                                   month_offset=state["months"],
                                   fullscreen=live, mouse_pos=mouse_pos,
                                   calendar_name=args.calendar, israel=israel)
        moment = _now()
        if state["minutes"]:
            moment += timedelta(minutes=state["minutes"])
        return render(moment, lat, lng, runtime, fullscreen=live,
                      offset_minutes=state["minutes"],
                      calendar_name=args.calendar, israel=israel)

    if not live:
        print(_render())
        return

    # A wheel notch or arrow key scrubs 15 minutes of the disc view or a
    # month of the calendar; space returns each to now. v flips views.
    def _step(n):
        if state["cal"]:
            state["months"] += n
        else:
            state["minutes"] += 15 * n
        return True

    def _intercept(action):
        if action == "fwd":
            return _step(1)
        if action == "back":
            return _step(-1)
        if action == "reset":
            state["months" if state["cal"] else "minutes"] = 0
            return True
        return False

    def _on_wheel(direction, _col, _row):
        return _step(direction)

    def _on_key(key):
        if key == "v":
            state["cal"] = not state["cal"]
            return True
        return False

    def _on_drag(_dcol, _drow, _done):
        # Nothing to drag; the loop only tracks clicks while a drag
        # callback is set, so this no-op is the price of _on_click.
        return False

    def _on_click(col, row):
        # A calendar day is a doorway: click it and the disc view opens
        # on that day, at this hour, with space the way back to now.
        if not state["cal"]:
            return False
        from linecast._moon_calendar import clicked_day
        target = clicked_day(col, row)
        if target is None:
            return False
        state["minutes"] = (target - _now().date()).days * 1440
        state["cal"] = False
        return True

    live_loop(_render, mouse=True, intercept=_intercept,
              on_wheel=_on_wheel, on_action=_on_key,
              on_drag=_on_drag, on_click=_on_click)


if __name__ == "__main__":
    main()
