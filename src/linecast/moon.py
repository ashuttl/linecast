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
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from linecast._framebuffer import fmt_time_dt
from linecast._graphics import (
    lerp, visible_len, get_terminal_size, Framebuffer, live_loop,
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
from linecast import _live, _theme
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
    _moon_parallactic_deg, _moon_ra_dec, _moon_transits_for_local_date,
    moon_age_days,
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
    global MOON_LIT_RGB, MOON_SHADOW_RGB, MOON_NIGHT_RGB, MOON_GLOW_RGB, SKY_RGB
    global STAR_BRIGHT_RGB, STAR_RGB, STAR_DIM_RGB
    global PANEL_TEXT_RGB, PANEL_DIM_RGB, PANEL_AMBER_RGB, PANEL_PURPLE_RGB
    global PANEL_FAINT_RGB
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
    # The disc's night is darker than the sky around it, as it looks in
    # life, where the sky near the Moon is lit by the Moon and the night
    # side is lit by nothing but Earth; the halo outlines the disc. The
    # calendar's small discs have no halo and keep the lighter shadow.
    MOON_NIGHT_RGB = darken(SKY_RGB, 0.5)
    # The info sits in the sky in every layout, so its inks contrast
    # with the sky rather than the page.
    PANEL_TEXT_RGB = ensure_contrast(INFO_TEXT_RGB, SKY_RGB, minimum=4.5)
    PANEL_DIM_RGB = ensure_contrast(INFO_DIM_RGB, SKY_RGB, minimum=2.0)
    # A shade fainter than dim, for the counsel's source line.
    PANEL_FAINT_RGB = lerp_rgb(SKY_RGB, PANEL_DIM_RGB, 0.62)
    PANEL_AMBER_RGB = ensure_contrast(INFO_AMBER_RGB, SKY_RGB, minimum=2.3)
    PANEL_PURPLE_RGB = ensure_contrast(INFO_PURPLE_RGB, SKY_RGB, minimum=2.3)


_rebuild()
_theme.on_reload(_rebuild)

# The disc's surface comes from NASA's LRO mosaic (see
# scripts/build_moon_albedo.py): a greyscale map of the whole Moon,
# longitude −180…180 left to right with the near side in the middle,
# latitude 90…−90 top to bottom, with the highlands scaled to white.
# The view is the mean sub-Earth point (librations ignored), north up,
# east right; the far side only shows when the disc is dragged round.
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


# The stars are the real sky around the Moon: the Yale Bright Star
# Catalogue to magnitude 5.5 (see scripts/build_star_catalogue.py),
# placed about the Moon's true position for the moment, with celestial
# north turned by the parallactic angle the disc already follows. So
# scrolling through time wheels the sky with the night and walks the
# Moon through its constellations. The disc is drawn far larger than
# scale; the sky is projected as an equidistant fisheye, screen centre
# looking away from the viewer, whose focal length is the disc's radius
# and a half — the screen's corner is about ninety degrees from the
# Moon — which keeps the resting sky evenly sown out to the corners and
# lets a drag carry the sky round the other way, as the background does
# when you walk round a statue, at about half again the surface's pace.
_STAR_FOCAL = 1.5


def _load_stars():
    """[(ra_rad, dec_rad)] brightest first, from the bundled catalogue."""
    from linecast._sky_catalogue import star_positions
    return star_positions()


def _star_direction(ra, dec, sky):
    """A star's direction in the resting screen frame.

    *sky* is (moon_ra_deg, moon_dec_deg, parallactic_deg): where the Moon
    is and how far celestial north is turned from the screen's up. The
    frame is x right, y down, z toward the viewer, the Moon at −z.
    """
    moon_ra, moon_dec, parallactic = sky
    ra0, dec0 = math.radians(moon_ra), math.radians(moon_dec)
    d_ra = ra - ra0
    # Angular distance and position angle (north through east) of the
    # star from the Moon, then the screen bearing: position angles run
    # anticlockwise from north on the sky, bearings clockwise from up.
    cos_rho = (math.sin(dec0) * math.sin(dec)
               + math.cos(dec0) * math.cos(dec) * math.cos(d_ra))
    sin_rho = math.sqrt(max(0.0, 1.0 - cos_rho * cos_rho))
    pa = math.atan2(math.cos(dec) * math.sin(d_ra),
                    math.sin(dec) * math.cos(dec0)
                    - math.cos(dec) * math.sin(dec0) * math.cos(d_ra))
    bearing = math.radians(parallactic) - pa
    return (sin_rho * math.sin(bearing), -sin_rho * math.cos(bearing), -cos_rho)


def _project_star(d, turn, cx, cy, radius):
    """The cell a star in direction *d* lands on, or None if it is behind
    the viewer. *turn* is the disc's rotation, or None at rest."""
    if turn is not None:
        d = _mat_apply(turn, d)
    x, y, z = d
    sin_t = math.sqrt(x * x + y * y)
    if sin_t < 1e-9:
        if z > 0.0:
            return None      # straight behind the viewer
        dx = dy = 0.0
    else:
        t = math.atan2(sin_t, -z) * _STAR_FOCAL * radius / sin_t
        dx, dy = x * t, y * t
    return int(round(cx + dx)), int((cy + dy) // 2)


def _star_overlays(fb, cx, cy, radius, sky, taken=(), turn=None):
    """The stars as character overlays, clear of the Moon.

    Returns {(col, row): (glyph, rgb, bold)}.  Stars are drawn as glyphs
    rather than sub-pixels, so each one claims a whole cell; *taken* is the
    set of cells the info column already owns, which a star must not
    displace. *sky* places the Moon among the stars (see _star_direction);
    *turn* is the disc's rotation, which carries the sky round.
    """
    # Show the brightest stars down to the magnitude that puts about
    # _STAR_DENSITY per thousand cells on screen: the screen's solid
    # angle, cell by cell, says how much of the sky it holds.
    focal = _STAR_FOCAL * radius
    seen = 0.0
    for row in range(fb.graph_h):
        dy = (row * 2 + 0.5) - cy
        for x in range(fb.graph_w):
            dx = x - cx
            t = math.hypot(dx, dy) / focal
            if t < math.pi:
                seen += (math.sin(t) / t if t > 1e-9 else 1.0) * 2.0 / (focal * focal)
    wanted = _STAR_DENSITY / 1000.0 * fb.graph_w * fb.graph_h
    catalogue = _load_stars()
    count = min(len(catalogue),
                int(round(wanted * 4.0 * math.pi / max(seen, 1e-9))))

    keep_out = (radius + 3.0) ** 2
    stars = {}
    for i, (ra, dec) in enumerate(catalogue[:count]):
        cell = _project_star(_star_direction(ra, dec, sky), turn, cx, cy, radius)
        if cell is None:
            continue
        x, row = cell
        if not (0 <= x < fb.graph_w and 0 <= row < fb.graph_h) or (x, row) in taken:
            continue
        dx, dy = x - cx, (row * 2 + 0.5) - cy
        if dx * dx + dy * dy < keep_out:
            continue
        # The glyph goes by rank among those shown, so the brightest few
        # on screen get the pointed glyphs whatever the magnitude cut.
        share = min(999, (count - i) * 1000 // count)
        for cutoff, glyph, bright, bold in _STAR_KINDS:
            if share < cutoff:
                stars[(x, row)] = (glyph, _star_color(bright), bold)
                break
    return stars


def _surface_shade(sx, sy, sz, albedo):
    """Darkening at a unit-sphere point, sampled from the albedo map.

    The point is in the Moon's own frame — north up, the near side's
    centre toward the viewer — and its latitude and longitude are looked
    up in the map with bilinear filtering, so limb foreshortening comes
    out of the projection. Returns 0 for highland-bright, up to 1 for
    black.
    """
    w, h, px = albedo
    lat = math.asin(max(-1.0, min(1.0, -sy)))
    lon = math.atan2(sx, sz)                        # −π…π, 0 facing Earth
    u = (lon / (2.0 * math.pi) + 0.5) * w - 0.5     # map spans −180…180
    v = (0.5 - lat / math.pi) * h - 0.5
    x0 = int(math.floor(u))
    y0 = int(math.floor(v))
    fx = u - x0
    fy = v - y0
    x0 %= w                                         # the seam is the far side's middle
    x1 = (x0 + 1) % w
    y0 = max(0, min(h - 1, y0))
    y1 = min(h - 1, y0 + 1)
    top = px[y0 * w + x0] * (1 - fx) + px[y0 * w + x1] * fx
    bottom = px[y1 * w + x0] * (1 - fx) + px[y1 * w + x1] * fx
    return 1.0 - (top * (1 - fy) + bottom * fy) / 255.0


def _mat_mul(a, b):
    """Product of two 3×3 matrices, each nine floats row-major."""
    return tuple(sum(a[i * 3 + k] * b[k * 3 + j] for k in range(3))
                 for i in range(3) for j in range(3))


def _mat_transpose(a):
    return (a[0], a[3], a[6], a[1], a[4], a[7], a[2], a[5], a[8])


def _mat_apply(a, v):
    x, y, z = v
    return (a[0] * x + a[1] * y + a[2] * z,
            a[3] * x + a[4] * y + a[5] * z,
            a[6] * x + a[7] * y + a[8] * z)


def _rotation(axis, angle):
    """Rotation by *angle* radians about the unit vector *axis*."""
    x, y, z = axis
    c, s = math.cos(angle), math.sin(angle)
    t = 1.0 - c
    return (t * x * x + c, t * x * y - s * z, t * x * z + s * y,
            t * x * y + s * z, t * y * y + c, t * y * z - s * x,
            t * x * z - s * y, t * y * z + s * x, t * z * z + c)


def _axis_angle(m):
    """The unit axis and angle (0…π) of a rotation matrix."""
    angle = math.acos(max(-1.0, min(1.0, (m[0] + m[4] + m[8] - 1.0) / 2.0)))
    s = math.sin(angle)
    if s > 1e-6:
        axis = ((m[7] - m[5]) / (2 * s), (m[2] - m[6]) / (2 * s),
                (m[3] - m[1]) / (2 * s))
    elif angle < 1e-6:
        axis = (0.0, 1.0, 0.0)
    else:
        # A half turn: M + I is twice the axis's outer product with
        # itself, so its longest column points along the axis.
        cols = [(m[i] + (i == 0), m[3 + i] + (i == 1), m[6 + i] + (i == 2))
                for i in range(3)]
        cx, cy, cz = max(cols, key=lambda c: c[0] ** 2 + c[1] ** 2 + c[2] ** 2)
        n = math.sqrt(cx * cx + cy * cy + cz * cz)
        axis = (cx / n, cy / n, cz / n)
    return axis, angle


class Turn:
    """The disc as the user has turned it.

    A drag rolls the Moon under the pointer, trackball fashion: the
    surface follows the pointer, so a drag the length of the radius is
    about a radian, and the far side comes round the limb. Letting go
    eases it back to the face it really shows, with a small overshoot.
    While it settles, a thread wakes the live loop for the frames; the
    frames themselves are timed, so a slow terminal drops some rather
    than dragging the settle out.
    """

    SETTLE = 0.7   # seconds from release to rest
    TICK = 1 / 30  # wakeups per second while settling

    def __init__(self):
        self.radius = 40.0    # the disc's radius in sub-pixels, from the last render
        self._base = None     # orientation when the drag began
        self._held = None     # orientation under the pointer, mid-drag
        self._settle = None   # (axis, angle, started) after a release
        self._ticker = None

    def drag(self, dcol, drow):
        """The pointer has moved this far, in cells, since the press."""
        if self._base is None:
            self._base = self.matrix() or _IDENTITY  # mid-settle: pick it up
            self._settle = None
        dx, dy = float(dcol), 2.0 * drow   # a cell is two sub-pixels tall
        dist = math.hypot(dx, dy)
        if dist == 0.0:
            self._held = self._base
        else:
            # Rolling the surface along the drag is a turn about the axis
            # square to it in the screen plane.
            self._held = _mat_mul(_rotation((-dy / dist, dx / dist, 0.0),
                                            dist / self.radius), self._base)
        return True

    def release(self):
        """The button is up; ease back to rest from wherever the disc is."""
        if self._base is None:
            return False
        axis, angle = _axis_angle(self._held)
        self._base = self._held = None
        if angle < 1e-3:
            return True
        self._settle = (axis, angle, time.monotonic())
        if self._ticker is None or not self._ticker.is_alive():
            self._ticker = threading.Thread(target=self._tick, daemon=True)
            self._ticker.start()
        return True

    def matrix(self):
        """The rotation to draw now, or None at rest."""
        if self._held is not None:
            return self._held
        if self._settle is None:
            return None
        axis, angle, started = self._settle
        s = (time.monotonic() - started) / self.SETTLE
        if s >= 1.0:
            self._settle = None
            return None
        return _rotation(axis, angle * (1.0 - _ease_out_back(s)))

    def _tick(self):
        while True:
            settle = self._settle
            if settle is None:
                return
            time.sleep(self.TICK)
            _live.nudge()
            if time.monotonic() >= settle[2] + self.SETTLE:
                return   # that wakeup draws the disc at rest


_IDENTITY = (1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0)


def _ease_out_back(s):
    """0→1 with a small overshoot near the end, so the settle bounces."""
    c1 = 1.2
    return 1.0 + (c1 + 1.0) * (s - 1.0) ** 3 + c1 * (s - 1.0) ** 2


def _draw_moon_disc(fb, cx, cy, radius, illum, limb_deg, axis_deg,
                    turn=None, night=None):
    """Draw the phase-shaded lunar disc centered at (cx, cy) sub-pixels.

    Two angles set the picture, both screen bearings with 0 straight up
    and 90 to the right. *limb_deg* points at the bright limb, so the
    terminator is drawn square to it; *axis_deg* points at the Moon's
    north pole, so the maria sit the way the observer sees them. They are
    not the same angle and do not move together, which is why they are
    passed separately: the terminator follows the Sun round the Moon over
    a month, while the maria only tilt with the observer.

    *turn* is a rotation (a 3×3 matrix as nine floats, row-major, in the
    screen frame: x right, y down, z toward the viewer) the user has put
    on the Moon by dragging it. The whole Moon turns, light and dark with
    the surface: the Sun's direction turns with the map, so the far side
    comes round the limb in the daylight or the night it is really in.

    The terminator is the great circle square to the Sun. A point is lit
    by the cosine of the Sun's elevation over it, softened across the
    line; seen from the front that is the standard phase ellipse, the
    whole disc at full, a straight edge at the quarters, nothing at new.

    The night side facing Earth is not quite black: earthshine lifts it
    by the Earth's own phase, which is the complement of the Moon's, so
    the maria show faintly in the old Moon in the new Moon's arms and
    not at all near full. The far side's night gets none. *night* is
    the colour of that unlit ground; the shadow colour when not given.
    """
    if night is None:
        night = MOON_SHADOW_RGB
    edge = max(1.0 / radius, 0.04)   # anti-aliasing band, in unit radii
    soft = 0.10                       # terminator softness, in unit radii
    earthshine = 0.20 * (1.0 - illum)  # night-side lift, facing Earth square on
    scan = int(radius + 2)
    albedo = _load_albedo()

    # The Sun's direction, from the phase: behind the viewer at full,
    # along the bright limb at the quarters, behind the Moon at new.
    limb = math.radians(limb_deg)
    limb_x, limb_y = math.sin(limb), -math.cos(limb)
    sun_z = 2.0 * illum - 1.0
    sun_r = math.sqrt(max(0.0, 1.0 - sun_z * sun_z))
    sun = (sun_r * limb_x, sun_r * limb_y, sun_z)
    earth = (0.0, 0.0, 1.0)
    if turn is not None:
        sun = _mat_apply(turn, sun)   # the light turns with the surface
        earth = _mat_apply(turn, earth)
    sun_x, sun_y, sun_z = sun
    earth_x, earth_y, earth_z = earth
    # Screen point to surface point: undo the user's turn (a rotation's
    # inverse is its transpose), then the tilt that put the pole where
    # the observer sees it, so the map is read north up.
    axis = math.radians(axis_deg)
    axis_c, axis_s = math.cos(axis), math.sin(axis)
    tilt = (axis_c, axis_s, 0.0, -axis_s, axis_c, 0.0, 0.0, 0.0, 1.0)
    m = _mat_mul(tilt, _mat_transpose(turn)) if turn is not None else tilt
    m00, m01, m02, m10, m11, m12, m20, m21, m22 = m

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

            # How far into daylight: the cosine of the Sun's elevation
            # over this point, softened across the terminator.
            uz = math.sqrt(1.0 - rr) if rr < 1.0 else 0.0
            d = ux * sun_x + uy * sun_y + uz * sun_z
            lit_alpha = max(0.0, min(1.0, (d + soft) / (2.0 * soft)))

            shade = 0.18 * rr  # limb falloff
            if albedo is not None:
                shade += _surface_shade(m00 * ux + m01 * uy + m02 * uz,
                                        m10 * ux + m11 * uy + m12 * uz,
                                        m20 * ux + m21 * uy + m22 * uz,
                                        albedo)
            lit_px = darken(MOON_LIT_RGB, min(0.55, shade))
            # Earthshine: the shaded surface, faintly, where Earth is up.
            glow = earthshine * (ux * earth_x + uy * earth_y + uz * earth_z)
            night_px = lerp(night, lit_px, glow) if glow > 0.0 else night
            color = lerp(night_px, lit_px, lit_alpha)
            fb.set_pixel(cx + dx, cy + dy, color, cover)


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------
def _wrap(text, width):
    """textwrap.wrap without widows: no lone word on the last line."""
    lines = textwrap.wrap(text, width)
    if len(lines) > 1 and " " not in lines[-1]:
        head, last = lines[-2].rsplit(" ", 1)
        lines[-2:] = [head, f"{last} {lines[-1]}"]
    return lines


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
           calendar_name=None, israel=False, turn=None):
    """Build the full-screen moon display: disc plus info lines.

    Three layouts, by terminal size: a wide terminal floats the info as
    a left-aligned column in the sky beside a full-height disc; a normal
    one puts the phase line and the status in the sky's top corners and
    the rest along the bottom; a small one shortens or sheds lines
    rather than letting them wrap. *turn* is the live view's
    Turn, the way the user has dragged the disc round, or None.
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
    sky = (*_moon_ra_dec(moment_utc), parallactic)   # the stars about the Moon
    rise, sset = upcoming_moon_events(now_local, lat, lng)

    rotation = turn.matrix() if turn is not None else None

    def paint_disc(fb, cx, cy, radius):
        if turn is not None:
            turn.radius = radius   # so a drag knows how far a radian is
        fb.draw_radial(cx, cy, MOON_GLOW_RGB, int(radius * 1.7), aspect=1.0,
                       peak_alpha=0.10 + 0.20 * illum)
        _draw_moon_disc(fb, cx, cy, radius, illum, limb, axis, rotation,
                        night=MOON_NIGHT_RGB)

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
        panel.append([(f"{age_txt} · {illum_txt}", D, False)])
    else:
        panel += [[(age_txt, D, False)], [(illum_txt, D, False)]]
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

    # --- stacked layout: the info in the corners of the sky ---
    # The phase line sits top left and the status top right; the rest
    # runs along the bottom, centered, and the disc takes the sky
    # between. Every line has renderings widest first: a small terminal
    # takes the first that fits, and a line whose narrowest form still
    # overflows is dropped rather than left to wrap.
    def seg_w(segments):
        return sum(visible_len(t) for t, _c, _b in segments)

    def first_fit(width, *variants):
        for variant in variants:
            if seg_w(variant) <= width:
                return variant
        return None

    if offset_minutes:
        status = ([(f"{alt_txt} · {bearing}", T, False)] if up
                  else [(below_txt, D, False)])
        status_line = (
            [(when_txt, A, False), (" · ", T, False)] + status
            + [(" · ", T, False), (_ts('space_to_now', runtime), D, False)],
            [(when_txt, A, False), (" · ", T, False)] + status,
            [(when_txt, A, False)],
        )
    elif up:
        status_line = (
            [(_ms('up_now', runtime), A, False), (f" · {alt_dir_txt}", T, False)],
            [(_ms('up_now', runtime), A, False), (f" · {alt:.0f}°", T, False)],
            [(_ms('up_now', runtime), A, False)],
        )
    else:
        status_line = ([(below_txt, D, False)],)

    # The aside — the age and the illumination — rides on the phase
    # line when the row has room, and otherwise takes the row beneath,
    # where it is dim enough to sit against the sky without the disc
    # making way for it.
    head = f"{icon} {name}" + (f" · {head_extra}" if head_extra else "")
    aside_line = (
        [(f"{age_txt} · {illum_txt}", D, False)],
        [(age_txt, D, False)],
    )
    head_line = (
        [(head, T, True), (f"  {age_txt} · {illum_txt}", D, False)],
        [(head, T, True)],
    )
    if head_extra:
        head_line += ([(f"{icon} {name}", T, True)],)

    candidates = []
    if good_txt:
        # The counsel leads the bottom lines, wrapped to the width
        # rather than shed.
        candidates += [([(seg, D, False)],)
                       for txt in (good_txt, hold_txt) if txt
                       for seg in _wrap(txt, graph_w)]
        if solunar_txt:
            candidates.append(([(solunar_txt, D, False)],))
        if attrib_txt:
            candidates.append(([(attrib_txt, PANEL_FAINT_RGB, False)],))
    candidates.append((
        # The countdown roughly doubles this line's width, so keep the
        # plain labelled time between it and the bare clock times —
        # otherwise a middle-width terminal drops the labels entirely.
        [("↑", A, False), (f"{rise_txt}  ", T, False),
         ("↓", P, False), (set_txt, T, False)],
        [("↑", A, False), (f"{_ms('moonrise', runtime)} {rise_when}  ", T, False),
         ("↓", P, False), (f"{_ms('moonset', runtime)} {set_when}", T, False)],
        [("↑", A, False), (f"{rise_when}  ", T, False),
         ("↓", P, False), (set_when, T, False)],
    ))
    if term_txt:
        # The calendar line, the festival leading since it is the one
        # people wait for.
        candidates.append(
            ([(f"{term_txt} · ", D, False), (fest_txt, T, False)],
             [(fest_txt, T, False), (f"  {term_short}", D, False)],
             [(fest_short, T, False)])
            if fest_txt else
            ([(term_txt, D, False)],
             [(term_short, D, False)]))
    candidates += [
        ([(f"{full_txt} · {new_txt}", D, False)],
         [(f"{full_label} {_fmt_month_day(full_dt, runtime)} · "
           f"{new_label} {_fmt_month_day(new_dt, runtime)}", D, False)],
         [(f"{_moon_name(4, runtime)} {_fmt_month_day(full_dt, runtime)}",
           D, False)]),
        ([(f"{year_txt} · {season_txt}", D, False)],
         [(f"{year_txt} · {season_short}", D, False)],
         [(year_txt, D, False)]),
    ]
    bottom = [line for line in (first_fit(graph_w, *c) for c in candidates)
              if line is not None]

    # The top row holds the phase line and the status together, a
    # column of air at each edge and two between. When both must give
    # something up they give it up evenly, the status keeping a little
    # more: scrubbed away from now it is the line that says when this
    # is and how to get back. When no renderings of the two share the
    # row, the status takes the row beneath.
    room = graph_w - 2
    pairs = sorted(((ih + i_s, i_s, ih) for ih in range(len(head_line))
                    for i_s in range(len(status_line))))
    fit = next(((head_line[ih], status_line[i_s]) for _n, i_s, ih in pairs
                if seg_w(head_line[ih]) + 2 + seg_w(status_line[i_s]) <= room),
               None)
    if fit:
        head_fit, status_fit = fit
        top_rows = 1
    else:
        head_fit = first_fit(room, *head_line)
        status_fit = first_fit(room, *status_line)
        top_rows = 2 if status_fit else 1
    aside_fit = aside_at = None
    if head_fit is not head_line[0]:
        # The aside goes under the name: on the row after the status
        # when the status took the second row and will not share it.
        aside_at = 1
        if top_rows > 1:
            aside_fit = first_fit(room - 2 - seg_w(status_fit), *aside_line)
            if aside_fit is None:
                aside_at = 2
        if aside_fit is None:
            aside_fit = first_fit(room, *aside_line)

    # Fullscreen fills the terminal exactly (plus the install banner,
    # when present); the plain print leaves two rows for the prompt.
    reserve = (1 if hint else 0) + (0 if fullscreen else 2)
    graph_h = max(6, rows - reserve)
    region_w = graph_w - panel_w - 3   # sky left over for the disc
    # Prefer the column: go wide whenever it fits and costs the disc
    # nothing.  Stacking spends a row at the top and several at the
    # bottom, so the sky beside a full-height disc wins well before
    # the terminal is truly wide.
    stacked_h = max(6, graph_h - top_rows - len(bottom))
    wide_radius = min(graph_h * 2 * 0.41, region_w * 0.5 - 3.0)
    stacked_radius = min(stacked_h * 2 * 0.41, graph_w * 0.5 - 3.0)
    if wide_radius >= stacked_radius and panel_h + 2 <= graph_h:
        total_spy = graph_h * 2
        radius = max(4.0, wide_radius)
        cx = region_w // 2
        cy = total_spy // 2
        overlays = _panel_overlays(
            panel, graph_w - panel_w - 2, (graph_h - panel_h) // 2, graph_w)
    else:
        # A short terminal gives up bottom lines (the least essential
        # come last) before squeezing the disc below six rows of sky.
        while bottom and graph_h - top_rows - len(bottom) < 6:
            bottom.pop()
        band_h = max(1, graph_h - top_rows - len(bottom))
        band_spy = band_h * 2
        # Half-block sub-pixels are roughly square, so one radius
        # serves both axes; the vertical extent is what binds on normal
        # terminals.  The disc takes ~82% of the band between the top
        # row and the bottom lines, leaving sky above and below.
        radius = max(4.0, min(band_spy * 0.41, graph_w * 0.5 - 3.0))
        cx = graph_w // 2
        cy = top_rows * 2 + band_spy // 2
        overlays = {}
        if head_fit:
            overlays.update(_panel_overlays([head_fit], 1, 0, graph_w))
        if aside_fit:
            overlays.update(_panel_overlays([aside_fit], 1, aside_at, graph_w))
        if status_fit:
            overlays.update(_panel_overlays(
                [status_fit], graph_w - 1 - seg_w(status_fit), top_rows - 1,
                graph_w))
        for i, line in enumerate(bottom):
            overlays.update(_panel_overlays(
                [line], (graph_w - seg_w(line)) // 2,
                graph_h - len(bottom) + i, graph_w))

    fb = Framebuffer(graph_w, graph_h, bg_color=SKY_RGB)
    paint_disc(fb, cx, cy, radius)
    stars = _star_overlays(fb, cx, cy, radius, sky, taken=overlays.keys(),
                           turn=rotation)
    lines = fb.render(overlays={**stars, **overlays})
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
    turn = Turn()

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
                      calendar_name=args.calendar, israel=israel, turn=turn)

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

    def _on_drag(dcol, drow, done):
        # Drag the disc to turn the Moon; let go and it settles back.
        # The calendar has nothing to drag, but the loop only tracks
        # clicks while a drag callback is set, so it answers here too.
        if state["cal"]:
            return False
        return turn.release() if done else turn.drag(dcol, drow)

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
