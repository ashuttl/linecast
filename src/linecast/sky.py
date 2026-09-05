"""The night sky from where you stand: stars, planets, the Moon, the Milky Way.

Usage: sky [--print] [--oneline] [--json] [--location PLACE] [--facing DIR]
           [--fov DEG] [--icons SET] [--emoji] [--lang CODE]

You stand at your location and look out: the horizon runs along the
bottom with the compass points under it, and the sky above holds the
real stars for the moment — the Yale Bright Star Catalogue to the
naked-eye limit — with the constellation figures drawn faintly through
them, the planets marked and named, the Moon at its phase and tilt, the
Sun with its glow, and the Milky Way as a pale band once the sky is dark
enough. By day the sky is blue and holds only the Sun, and perhaps
Venus; through dusk it goes through the colours the sunshine view
knows, and the stars come out one by one, brightest first.

The sky is a stereographic projection about the direction faced, which
keeps the constellations their shapes at any width of view. Zoomed in,
fainter stars and more names appear, and the Moon grows to the disc the
moon view draws. Zoomed all the way out while looking up, the horizon
closes into a circle and the view is the whole dome of the sky, the
planisphere of the almanacs.

Live, drag to look around and let go to coast; the wheel and the arrows
move through time; `+` and `-` zoom; `p` plays time at an hour a
second, then a day, then a week; `c` cycles the constellation figures
and names; `1`–`8` face the compass points in turn and `9` looks
straight up; `m` faces the Moon; space returns to now. Point at
anything for its name.

Positions come from `_ephemeris.py` and `_planets.py`, good to a few
arcminutes, which is finer than a cell at the closest zoom.
"""

import math
import sys
from collections import namedtuple
from datetime import datetime, timezone

from linecast._graphics import (
    Framebuffer, RESET, bg, fg, get_terminal_size, interp_stops, lerp,
    visible_len,
)
from linecast import _live, _theme
from linecast._theme import (
    best_contrast, darken, ensure_contrast, is_light_theme, lerp_rgb, lighten,
    neutral_tone, surface_bg, theme_legacy_mode,
)
from linecast._ephemeris import (
    _alt_az_deg, _gmst_deg, _moon_parallactic_deg, _moon_ra_dec, _sun_ra_dec,
    moon_axis_deg, moon_bright_limb_deg, moon_horizontal_parallax_deg,
    moon_illuminated_fraction,
)
from linecast._i18n import lang_of
from linecast._location import (
    country_for_defaults, location_is_pinned, location_tzinfo, resolve_location,
)
from linecast._planets import planet_positions
from linecast._radar_i18n import rs
from linecast._runtime import (
    RuntimeConfig, install_banner, set_current, sky_parser,
)
from linecast._sky_catalogue import (
    EQ_TO_GAL, MILKY_WAY_H, MILKY_WAY_W, constellation_name, constellations,
    milky_way, star_names, star_vectors, stars,
)
from linecast._sky_i18n import NO_CAPITALS, _sk, body_name
from linecast._sunshine_i18n import sky_phase
from linecast._textwidth import char_width
from linecast._tides_i18n import _ts  # shared "space to return to now" hint
from linecast.moon import _draw_moon_disc
from linecast.sunshine import (
    INFO_AMBER_RGB, INFO_DIM_RGB, INFO_TEXT_RGB, SKY_FAR_HORIZON,
    SKY_NEAR_HORIZON, SKY_NIGHT, SKY_ZENITH, SUN_DOT_RGB, SUN_GLOW_RGB,
    moon_phase,
)

_theme.track_imports(globals(), "linecast.sunshine")

# ---------------------------------------------------------------------------
# Palette
# ---------------------------------------------------------------------------
def _rebuild():
    global NIGHT_RGB, HAZE_RGB, GROUND_RGB, MILKY_RGB, FIGURE_RGB
    global STAR_BRIGHT_RGB, STAR_RGB, STAR_DIM_RGB, MOON_LIT_RGB, MOON_GLOW_RGB
    global TEXT_RGB, DIM_RGB, AMBER_RGB, LABEL_RGB, FIGURE_NAME_RGB
    global TIP_BG_RGB, TIP_TEXT_RGB, TIP_DIM_RGB
    NIGHT_RGB = SKY_NIGHT
    if theme_legacy_mode:
        STAR_BRIGHT_RGB = (206, 214, 236)
        STAR_RGB = (150, 158, 180)
        STAR_DIM_RGB = (84, 92, 115)
        MOON_LIT_RGB = (228, 230, 238)
        MOON_GLOW_RGB = (150, 160, 190)
    elif is_light_theme():
        white = (250, 252, 255)
        STAR_BRIGHT_RGB = lerp_rgb(NIGHT_RGB, white, 0.85)
        STAR_RGB = lerp_rgb(NIGHT_RGB, white, 0.60)
        STAR_DIM_RGB = lerp_rgb(NIGHT_RGB, white, 0.38)
        MOON_LIT_RGB = white
        MOON_GLOW_RGB = lerp_rgb(NIGHT_RGB, white, 0.55)
    else:
        STAR_BRIGHT_RGB = ensure_contrast(neutral_tone(0.80), NIGHT_RGB, minimum=3.2)
        STAR_RGB = ensure_contrast(neutral_tone(0.58), NIGHT_RGB, minimum=2.2)
        STAR_DIM_RGB = ensure_contrast(neutral_tone(0.40), NIGHT_RGB, minimum=1.5)
        MOON_LIT_RGB = best_contrast((_theme.theme_ansi[15], _theme.theme_fg), minimum=2.5)
        MOON_GLOW_RGB = ensure_contrast(neutral_tone(0.60), NIGHT_RGB, minimum=1.8)
    # The night sky is lifted a little toward the horizon, as it is in
    # life, and the ground below is darker than any sky.
    HAZE_RGB = lerp_rgb(NIGHT_RGB, STAR_DIM_RGB, 0.55)
    GROUND_RGB = darken(NIGHT_RGB, 0.45)
    # The Milky Way is milk: pale, a touch blue, never bright.
    MILKY_RGB = lerp_rgb(STAR_RGB, (200, 215, 255), 0.25)
    # The figures are drawn a shade above the sky, the names dimmer than
    # any star label, so both stay behind the stars.
    FIGURE_RGB = STAR_DIM_RGB
    TEXT_RGB = ensure_contrast(INFO_TEXT_RGB, NIGHT_RGB, minimum=4.5)
    DIM_RGB = ensure_contrast(INFO_DIM_RGB, NIGHT_RGB, minimum=2.0)
    AMBER_RGB = ensure_contrast(INFO_AMBER_RGB, NIGHT_RGB, minimum=2.3)
    LABEL_RGB = ensure_contrast(neutral_tone(0.62), NIGHT_RGB, minimum=2.4)
    FIGURE_NAME_RGB = lerp_rgb(NIGHT_RGB, LABEL_RGB, 0.62)
    TIP_BG_RGB = darken(surface_bg(0.10), 0.45 if not is_light_theme() else 0.10)
    TIP_TEXT_RGB = ensure_contrast(_theme.theme_fg, TIP_BG_RGB, minimum=4.5)
    TIP_DIM_RGB = ensure_contrast(surface_bg(0.55), TIP_BG_RGB, minimum=2.2)


_rebuild()
_theme.on_reload(_rebuild)

# Star tints by colour index: blue-white for the hot ones, orange for
# Betelgeuse, Antares, Arcturus and their kind. Only the bright stars
# show it; the faint ones are white, as they are to the eye.
_STAR_TINTS = [
    (-0.30, (175, 195, 255)),
    (0.30, (255, 255, 255)),
    (0.80, (255, 240, 205)),
    (1.60, (255, 185, 120)),
]

# The planets' own colours and marks. Uranus and Neptune are faint and
# only ever show close in.
_PLANET_RGB = {
    "mercury": (210, 210, 210), "venus": (255, 250, 225), "mars": (255, 150, 110),
    "jupiter": (255, 232, 195), "saturn": (240, 220, 160),
    "uranus": (175, 225, 225), "neptune": (155, 175, 255),
}
_PLANET_GLYPH = "●"

# How many stars the sky holds, per thousand cells of sky, whatever the
# zoom: the limiting magnitude follows from how much of the sky is on
# screen. A little denser than the moon view, which has a disc to leave
# room for.
_STAR_DENSITY = 46

# The eye's limiting magnitude by the Sun's altitude: the whole
# catalogue at full night, the brightest few stars in civil twilight,
# Venus alone by day.
_LIMIT_BY_SUN = [
    (-18.0, 6.5), (-15.0, 5.8), (-12.0, 4.6), (-9.0, 3.2), (-6.0, 1.6),
    (-3.0, -0.4), (0.0, -2.4), (5.0, -3.9), (90.0, -4.4),
]

View = namedtuple("View", "az alt fov figures")
View.__doc__ = """Where the view looks: azimuth and altitude of its centre
in degrees, the field of view across the screen in degrees, and how much
of the constellations to draw (0 nothing, 1 the figures, 2 the figures
and their names)."""

FOV_MIN, FOV_MAX, FOV_DEFAULT = 6.0, 236.0, 110.0
FIGURES_DEFAULT = 2


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------
def _mat_mul(a, b):
    return tuple(sum(a[i * 3 + k] * b[k * 3 + j] for k in range(3))
                 for i in range(3) for j in range(3))


def _mat_transpose(a):
    return (a[0], a[3], a[6], a[1], a[4], a[7], a[2], a[5], a[8])


def _mat_apply(a, v):
    x, y, z = v
    return (a[0] * x + a[1] * y + a[2] * z,
            a[3] * x + a[4] * y + a[5] * z,
            a[6] * x + a[7] * y + a[8] * z)


def horizontal_matrix(lst_deg, lat_deg):
    """Equatorial (x to the equinox, z to the pole) to the observer's
    frame: x east, y north, z up. The sidereal time turns the sky to
    the meridian, the latitude tips the pole to its altitude."""
    L, phi = math.radians(lst_deg), math.radians(lat_deg)
    cl, sl, cp, sp = math.cos(L), math.sin(L), math.cos(phi), math.sin(phi)
    return (-sl, cl, 0.0,
            -cl * sp, -sl * sp, cp,
            cl * cp, sl * cp, sp)


def horizontal_vector(az_deg, alt_deg):
    """The unit vector, x east, y north, z up, of a direction."""
    az, alt = math.radians(az_deg), math.radians(alt_deg)
    c = math.cos(alt)
    return (c * math.sin(az), c * math.cos(az), math.sin(alt))


def camera_matrix(az_deg, alt_deg):
    """The observer's frame to the screen's: x right, y up, z forward,
    looking along (az, alt). Right is always along the horizon, so the
    zenith, when looked at, has the far side of the horizon at the top of
    the screen and the view is a planisphere."""
    az, alt = math.radians(az_deg), math.radians(alt_deg)
    ca, sa, cl, sl = math.cos(az), math.sin(az), math.cos(alt), math.sin(alt)
    return (ca, -sa, 0.0,
            -sa * sl, -ca * sl, cl,
            cl * sa, cl * ca, sl)


def focal_length(width, fov_deg):
    """Sub-pixels per unit of the stereographic plane, for a field of
    *fov_deg* across *width* sub-pixels."""
    return width / (4.0 * math.tan(math.radians(fov_deg) / 4.0))


def project(v, f, cx, cy):
    """A camera-frame unit vector to (x, y) in sub-pixels, y down, or
    None when it is too far behind the viewer to place."""
    x, y, z = v
    if z < -0.82:
        return None
    k = 2.0 * f / (1.0 + z)
    return cx + x * k, cy - y * k


def unproject(px, py, f, cx, cy):
    """The camera-frame unit vector a sub-pixel looks along."""
    u = (px - cx) / (2.0 * f)
    v = (cy - py) / (2.0 * f)
    rho2 = u * u + v * v
    d = 1.0 + rho2
    return (2.0 * u / d, 2.0 * v / d, (1.0 - rho2) / d)


def alt_az_of(v):
    """Altitude and azimuth, degrees, of an observer-frame unit vector."""
    e, n, u = v
    return (math.degrees(math.asin(max(-1.0, min(1.0, u)))),
            math.degrees(math.atan2(e, n)) % 360.0)


def compass_point(az_deg, runtime):
    """The eight-point compass abbreviation, in the display language."""
    points = rs("compass", lang_of(runtime)).split()
    return points[round(az_deg / 45.0) % 8]


def compass_points(runtime):
    return rs("compass", lang_of(runtime)).split()


# ---------------------------------------------------------------------------
# The moment's sky
# ---------------------------------------------------------------------------
class Scene:
    """Where everything is at one moment, for one observer.

    Built once per frame and handed to the drawing passes: the frame
    matrix, the Sun, the Moon and the planets as observer-frame vectors
    with their altitudes and azimuths, and the limiting magnitude the
    sky's brightness allows.
    """

    def __init__(self, moment_utc, lat, lng):
        self.moment_utc = moment_utc
        self.lat, self.lng = lat, lng
        lst = (_gmst_deg(moment_utc) + lng) % 360.0
        self.horizontal = horizontal_matrix(lst, lat)

        sun_ra, sun_dec = _sun_ra_dec(moment_utc)
        self.sun_alt, self.sun_az = _alt_az_deg(sun_ra, sun_dec, moment_utc, lat, lng)
        self.sun = horizontal_vector(self.sun_az, self.sun_alt)

        # The Moon is close enough that where you stand moves it: the
        # topocentric altitude is the geocentric one less the parallax.
        moon_ra, moon_dec = _moon_ra_dec(moment_utc)
        alt, az = _alt_az_deg(moon_ra, moon_dec, moment_utc, lat, lng)
        alt -= moon_horizontal_parallax_deg(moment_utc) * math.cos(math.radians(alt))
        self.moon_alt, self.moon_az = alt, az
        self.moon = horizontal_vector(az, alt)
        self.moon_illum = moon_illuminated_fraction(moment_utc)
        parallactic = _moon_parallactic_deg(moment_utc, lat, lng)
        self.moon_limb = parallactic - moon_bright_limb_deg(moment_utc)
        self.moon_axis = parallactic - moon_axis_deg(moment_utc)

        self.planets = []   # (key, vector, alt, az, mag), brightest first
        for key, (ra, dec, mag, _dist) in planet_positions(moment_utc).items():
            alt, az = _alt_az_deg(ra, dec, moment_utc, lat, lng)
            self.planets.append((key, horizontal_vector(az, alt), alt, az, mag))
        self.planets.sort(key=lambda p: p[4])

        self.eye_limit = _interp(_LIMIT_BY_SUN, self.sun_alt)
        # How dark the sky is, 0 by day to 1 at full night, for the things
        # that only show against a dark sky.
        self.darkness = max(0.0, min(1.0, (-self.sun_alt - 12.0) / 6.0))

    def morning(self):
        """Whether the shown moment is before local solar noon."""
        return self.sun_az < 180.0 if self.lat >= 0 else self.sun_az >= 180.0


def _interp(stops, value):
    """Linear interpolation through [(x, y), …] stops, clamped at the ends."""
    if value <= stops[0][0]:
        return stops[0][1]
    for (x0, y0), (x1, y1) in zip(stops, stops[1:]):
        if value <= x1:
            return y0 + (y1 - y0) * (value - x0) / (x1 - x0)
    return stops[-1][1]


def _extinction(alt_deg):
    """Magnitudes lost to the air at an altitude: nothing overhead, a
    magnitude or two near the horizon (Rozenberg's airmass)."""
    if alt_deg <= 0.0:
        return 3.0
    s = math.sin(math.radians(alt_deg))
    airmass = 1.0 / (s + 0.025 * math.exp(-11.0 * s))
    return min(3.0, 0.25 * (airmass - 1.0))


def _star_tint(bv):
    return interp_stops(_STAR_TINTS, bv)


# ---------------------------------------------------------------------------
# Drawing
# ---------------------------------------------------------------------------
def _put_text(overlays, taken, text, x, row, rgb, bold, graph_w, graph_h,
              pad=1):
    """Lay *text* as overlay cells at (x, row), or return False if it would
    leave the screen or touch a cell already taken. The taken set gains
    the text's cells and a column of air either side."""
    if row < 0 or row >= graph_h or x < 0:
        return False
    cells = []
    col = x
    for i, ch in enumerate(text):
        w = char_width(ch, text[i + 1] if i + 1 < len(text) else "")
        cells.append((col, ch))
        if w == 2:
            cells.append((col + 1, ""))
        col += w
    if col > graph_w:
        return False
    span = range(max(0, x - pad), min(graph_w, col + pad))
    if any((c, row) in taken for c in span):
        return False
    for c, ch in cells:
        overlays[(c, row)] = (ch, rgb, bold)
    for c in span:
        taken.add((c, row))
    return True


# Braille dot bits: _BRAILLE[dot column 0-1][dot row 0-3].
_BRAILLE = ((0x01, 0x02, 0x04, 0x40), (0x08, 0x10, 0x20, 0x80))


def _plot_arc(dots, a, b, cam, f, cx, cy, graph_w, graph_h):
    """A great-circle arc between two camera-frame vectors, as braille
    dots — two across and four down each cell — only above the horizon.
    *dots* maps a cell to its dot bits.

    The camera matrix's third column gives the altitude of a camera-frame
    direction, which is how the arc knows where the ground cuts it.
    """
    pa, pb = project(a, f, cx, cy), project(b, f, cx, cy)
    if pa is None or pb is None:
        return
    length = math.hypot(pb[0] - pa[0], pb[1] - pa[1])
    if length > 6.0 * f:
        return   # an arc thrown across the far side of the view
    steps = max(1, int(length * 2.0))
    u0, u1, u2 = cam[2], cam[5], cam[8]
    ax, ay, az = a
    bx, by, bz = b
    for i in range(steps + 1):
        t = i / steps
        x, y, z = ax + (bx - ax) * t, ay + (by - ay) * t, az + (bz - az) * t
        n = math.sqrt(x * x + y * y + z * z)
        if n < 1e-9:
            continue
        x, y, z = x / n, y / n, z / n
        if u0 * x + u1 * y + u2 * z < 0.0:
            continue   # below the horizon
        k = 2.0 * f / (1.0 + z)
        sx, sy = cx + x * k, cy - y * k
        # Sub-pixels to dots: two dot columns per cell, two dot rows per
        # sub-pixel row.
        dx, dy = int(sx * 2.0), int(sy * 2.0)
        col, row = dx >> 1, dy >> 2
        if 0 <= col < graph_w and 0 <= row < graph_h:
            dots[(col, row)] = dots.get((col, row), 0) | _BRAILLE[dx & 1][dy & 3]


def _draw_disc(fb, x, y, radius, rgb):
    """A filled, anti-aliased disc of *radius* sub-pixels at (x, y)."""
    edge = 0.6
    scan = int(radius + 1.5)
    xi, yi = int(round(x)), int(round(y))
    for dy in range(-scan, scan + 1):
        for dx in range(-scan, scan + 1):
            r = math.hypot(xi + dx - x, yi + dy - y)
            cover = min(1.0, max(0.0, (radius + edge - r) / (2.0 * edge)))
            if cover > 0.02:
                fb.set_pixel(xi + dx, yi + dy, rgb, cover)


def _sky_table(scene):
    """Colour lookups for the moment: the sky by altitude and by how far
    round from the Sun, and the ground by depth, so the per-sub-pixel
    pass indexes instead of blending.

    Returns (sky, ground): sky[k][a] for altitude step a (half degrees,
    0–90) and Sun-proximity step k (0 far, 11 toward); ground[d] for
    depth step d (degrees, 0–30).
    """
    s = scene.sun_alt
    night = NIGHT_RGB
    alts = [a * 0.5 for a in range(181)]
    # Twilight and day: the sunshine view's stops for the zenith and for
    # the horizon near and far from the Sun, blended down the sky, with
    # the glow toward the Sun kept low while the Sun is.
    if s > -18.0:
        zenith = interp_stops(SKY_ZENITH, s)
        near = interp_stops(SKY_NEAR_HORIZON, s)
        far = interp_stops(SKY_FAR_HORIZON, s)
        height = 8.0 + 40.0 * max(0.0, min(1.0, (s + 12.0) / 16.0))
        brightness = max(0.0, min(1.0, (s + 18.0) / 18.0))
    murk = 1.0 - max(0.0, min(1.0, (s + 18.0) / 12.0))
    sky = []
    for k in range(12):
        w = k / 11.0
        column = []
        for alt in alts:
            if s > -18.0:
                horizon = lerp(far, near, w)
                v = math.exp(-alt / height)
                color = lerp(zenith, horizon, v)
                # Toward the zenith the twilight sky keeps some night.
                color = lerp(night, color, brightness + (1.0 - brightness) * v)
            else:
                color = night
            if murk > 0.0:
                color = lerp(color, HAZE_RGB, 0.24 * murk * math.exp(-alt / 9.0))
            column.append(color)
        sky.append(column)
    # The ground: darker than the sky at its horizon, darker still
    # further down, and by day a dark cast of the horizon's colour.
    ground = []
    for d in range(31):
        color = GROUND_RGB
        if s > -18.0:
            color = lerp(color, darken(lerp(far, near, 0.5), 0.6), brightness)
        ground.append(darken(color, 0.35 * min(1.0, d / 25.0)))
    return sky, ground


def _paint_sky(fb, scene, cam, f, cx, cy):
    """The background: sky and ground by direction, the Milky Way where
    the sky is dark. Returns the solid angle of sky on screen, in
    steradians, for the star count."""
    sky, ground = _sky_table(scene)
    # Rows of the camera matrix are the screen axes in the observer's
    # frame, so the observer-frame vector of a camera vector (x, y, z) is
    # x*right + y*up + z*forward.
    r0, r1, r2, u0, u1, u2, f0, f1, f2 = cam
    # Toward the Sun along the horizon: the glow follows its azimuth.
    se, sn = math.sin(math.radians(scene.sun_az)), math.cos(math.radians(scene.sun_az))
    twilight = scene.sun_alt > -18.0
    # Camera to galactic, for the Milky Way: the frame's transpose, then
    # the equatorial-to-galactic rotation.
    to_gal = _mat_mul(EQ_TO_GAL, _mat_transpose(_mat_mul(cam, scene.horizontal)))
    g0, g1, g2, g3, g4, g5, g6, g7, g8 = to_gal
    milk = milky_way() if scene.darkness > 0.0 else b""
    milk_alpha = 0.42 * scene.darkness
    milky = MILKY_RGB
    mw_w, mw_h = MILKY_WAY_W, MILKY_WAY_H
    px = fb.fb
    inv2f = 1.0 / (2.0 * f)
    asin, atan2, degrees, sqrt = math.asin, math.atan2, math.degrees, math.sqrt
    omega = 0.0
    cell_omega = inv2f * inv2f * 4.0
    for spy in range(fb.total_spy):
        v = (cy - (spy + 0.5)) * inv2f
        row = px[spy]
        for x in range(fb.graph_w):
            u = (x + 0.5 - cx) * inv2f
            rho2 = u * u + v * v
            d = 1.0 + rho2
            cx_, cy_, cz_ = 2.0 * u / d, 2.0 * v / d, (1.0 - rho2) / d
            up = cx_ * r2 + cy_ * u2 + cz_ * f2
            if up < 0.0:
                depth = min(30, int(-up * 57.3))
                row[x] = ground[depth]
                continue
            omega += cell_omega / (d * d)
            alt = degrees(asin(up if up < 1.0 else 1.0))
            a = int(alt * 2.0 + 0.5)
            if twilight:
                e = cx_ * r0 + cy_ * u0 + cz_ * f0
                n = cx_ * r1 + cy_ * u1 + cz_ * f1
                h = sqrt(e * e + n * n)
                # Nearness to the Sun's azimuth, 0 opposite to 1 toward,
                # bell-shaped about it.
                c = (e * se + n * sn) / h if h > 1e-6 else 1.0
                k = int(((1.0 + c) * 0.5) ** 4 * 11.0 + 0.5)
                color = sky[k][a]
            else:
                color = sky[0][a]
            if milk:
                gx = g0 * cx_ + g1 * cy_ + g2 * cz_
                gy = g3 * cx_ + g4 * cy_ + g5 * cz_
                gz = g6 * cx_ + g7 * cy_ + g8 * cz_
                lon = degrees(atan2(gy, gx))
                mc = int((180.0 - lon) * 2.0) % mw_w
                gz = gz if -1.0 < gz < 1.0 else (1.0 if gz > 0 else -1.0)
                mr = int((90.0 - degrees(asin(gz))) * 2.0)
                b = milk[min(mw_h - 1, mr) * mw_w + mc]
                if b > 6:
                    # Thinner near the horizon, where the air takes it.
                    color = lerp(color, milky, milk_alpha * b / 255.0
                                 * min(1.0, alt / 14.0))
            row[x] = color
    return omega


def _star_limit(scene, omega, cells):
    """The limiting magnitude for this view: enough stars for the screen's
    share of the sky at the chosen density, but never more than the eye
    would see under this sky."""
    if omega <= 0.0:
        return -10.0
    wanted = _STAR_DENSITY / 1000.0 * cells * 4.0 * math.pi / omega
    catalogue = stars()
    rank = min(len(catalogue) - 1, int(wanted))
    by_zoom = catalogue[rank][2] if rank >= 0 else -10.0
    return min(by_zoom, scene.eye_limit)


def _label_limit(fov):
    """The magnitude down to which named stars carry their names: the
    brightest handful at a wide view, all of them close in."""
    return 3.3 - 1.1 * math.log2(max(fov, 1.0) / 20.0)


def _screen_up_deg(v_cam, cam, f, cx, cy):
    """The screen bearing (0 up, 90 right) of the local vertical at a
    camera-frame point: which way is 'up' there in the projection."""
    e, n, u = _mat_apply(_mat_transpose(cam), v_cam)
    alt, az = alt_az_of((e, n, u))
    higher = _mat_apply(cam, horizontal_vector(az, min(89.9, alt + 0.5)))
    p0, p1 = project(v_cam, f, cx, cy), project(higher, f, cx, cy)
    if p0 is None or p1 is None:
        return 0.0
    return math.degrees(math.atan2(p1[0] - p0[0], -(p1[1] - p0[1])))


def render(now_local, lat, lng, runtime, view, fullscreen=False,
           offset_minutes=0, mouse_pos=None, location_label="", speed=None,
           today=None):
    """One frame of the sky.

    *view* says where the observer looks; *speed* is the live view's
    play rate in seconds per second, or None; *today* is the user's own
    date, for the clock's weekday. Returns the frame, with the pointer's
    chip floating over it when the pointer rests on something.
    """
    cols, rows = get_terminal_size()
    hint = install_banner()
    graph_w = max(20, cols - 2)
    reserve = 1 + (1 if hint else 0) + (0 if fullscreen else 2)
    graph_h = max(6, rows - reserve)
    total_spy = graph_h * 2

    moment_utc = now_local.astimezone(timezone.utc)
    scene = Scene(moment_utc, lat, lng)
    cam = camera_matrix(view.az, view.alt)
    f = focal_length(graph_w, view.fov)
    cx, cy = graph_w / 2.0, total_spy / 2.0
    frame = _mat_mul(cam, scene.horizontal)   # equatorial to camera
    lang = lang_of(runtime)

    fb = Framebuffer(graph_w, graph_h, bg_color=NIGHT_RGB)
    omega = _paint_sky(fb, scene, cam, f, cx, cy)
    limit = _star_limit(scene, omega, graph_w * graph_h)
    overlays = {}
    taken = set()
    hits = []   # (col, row, kind, payload) for the pointer

    # --- the Sun ---
    sun_cam = _mat_apply(cam, scene.sun)
    sun_at = project(sun_cam, f, cx, cy) if scene.sun_alt > -3.0 else None
    if sun_at is not None:
        sx, sy = sun_at
        radius = max(2.0, f * math.tan(math.radians(0.267)) * 2.0)
        glow = max(10.0, radius * 6.0)
        lift = max(0.0, min(1.0, (scene.sun_alt + 3.0) / 6.0))
        fb.draw_radial(int(round(sx)), sy, SUN_GLOW_RGB, int(glow), aspect=1.0,
                       peak_alpha=0.9 * lift)
        if scene.sun_alt > -0.9:
            _draw_disc(fb, sx, sy, radius, SUN_DOT_RGB)
        hits.append((sx, sy, "sun", None))

    # --- the Moon ---
    moon_cam = _mat_apply(cam, scene.moon)
    moon_at = project(moon_cam, f, cx, cy) if scene.moon_alt > -1.0 else None
    if moon_at is not None:
        mx, my = moon_at
        radius = max(2.2, f * math.tan(math.radians(0.26)) * 2.0)
        illum = scene.moon_illum
        # Against a bright sky the Moon is a pale thing without a halo and
        # its night side is the sky; at night it owns its patch of sky.
        fb.draw_radial(int(round(mx)), my, MOON_GLOW_RGB,
                       int(max(3.0, radius * 1.8)), aspect=1.0,
                       peak_alpha=(0.12 + 0.28 * illum) * scene.darkness)
        cell = fb.cell_bg(max(0, min(graph_w - 1, int(mx))),
                          max(0, min(graph_h - 1, int(my) // 2)))
        up = _screen_up_deg(moon_cam, cam, f, cx, cy)
        _draw_moon_disc(fb, int(round(mx)), int(round(my)), radius, illum, up + scene.moon_limb,
                        up + scene.moon_axis, None,
                        night=lerp(cell, darken(NIGHT_RGB, 0.5), scene.darkness))
        hits.append((mx, my, "moon", None))

    # --- the stars, gathered ---
    # Everything with a cell is gathered first and laid down in order of
    # its claim: planets and the bright stars, then the names, then the
    # faint stars, then the constellation figures in whatever cells are
    # left, so a name never covers a bright star and a figure never
    # covers a name.
    catalogue = stars()
    vectors = star_vectors()
    names = star_names()
    label_limit = _label_limit(view.fov)
    dim, mid, bright = STAR_DIM_RGB, STAR_RGB, STAR_BRIGHT_RGB
    m0, m1, m2, m3, m4, m5, m6, m7, m8 = frame
    u0, u1, u2 = cam[2], cam[5], cam[8]
    # The stars fade in at the edge of what the eye can see; where the
    # zoom sets the limit there is nothing to fade toward.
    fading = scene.eye_limit < limit + 0.7
    gathered = []   # (above, sx, sy, col, row, glyph, color, bold, i, alt, mag)
    seen_cells = set()
    for i, (_ra, _dec, mag, bv) in enumerate(catalogue):
        if mag > limit + 0.5:
            break
        x, y, z = vectors[i]
        cxv = m0 * x + m1 * y + m2 * z
        cyv = m3 * x + m4 * y + m5 * z
        czv = m6 * x + m7 * y + m8 * z
        if czv < -0.82:
            continue
        k = 2.0 * f / (1.0 + czv)
        sx, sy = cx + cxv * k, cy - cyv * k
        if not (0.0 <= sx < graph_w and 0.0 <= sy < total_spy):
            continue
        up = u0 * cxv + u1 * cyv + u2 * czv
        if up <= 0.0:
            continue
        alt = math.degrees(math.asin(min(1.0, up)))
        seen = mag + _extinction(alt)
        above = limit - seen
        if above < (-0.5 if fading else 0.0):
            continue
        col, row = int(sx), int(sy) // 2
        if (col, row) in seen_cells:
            continue
        seen_cells.add((col, row))
        # The glyph by how far the star stands above the limit: most are
        # dots, a few are pointed, the brightest on screen are bold.
        if above < 1.0:
            glyph, tone, bold = "·", 0.0, False
        elif above < 2.0:
            glyph, tone, bold = "·", 0.45, False
        elif above < 3.0:
            glyph, tone, bold = "+", 0.65, False
        elif above < 4.3:
            glyph, tone, bold = "✦", 0.85, True
        else:
            glyph, tone, bold = "✱", 1.0, True
        color = (lerp(dim, mid, tone * 2.0) if tone <= 0.5
                 else lerp(mid, bright, (tone - 0.5) * 2.0))
        if tone > 0.4:
            color = lerp(color, _star_tint(bv), 0.35 * tone)
        if fading and above < 0.5:
            color = lerp(fb.cell_bg(col, row), color, (above + 0.5) / 1.0)
        gathered.append((above, sx, sy, col, row, glyph, color, bold, i, alt, mag))

    def place_star(entry):
        _above, sx, sy, col, row, glyph, color, bold, i, alt, mag = entry
        if (col, row) in taken:
            return
        overlays[(col, row)] = (glyph, color, bold)
        taken.add((col, row))
        hits.append((sx, sy, "star", (i, alt, mag)))

    # --- the planets, and the bright stars ---
    label_ink = LABEL_RGB
    planet_labels = []
    for key, vec, alt, az, mag in scene.planets:
        if alt < -0.5:
            continue
        fade = (scene.eye_limit + 0.8 - (mag + _extinction(alt))) / 1.0
        if fade <= 0.0 or mag > limit + 0.8:
            continue
        p = project(_mat_apply(cam, vec), f, cx, cy)
        if p is None:
            continue
        col, row = int(p[0]), int(p[1]) // 2
        if not (0 <= col < graph_w and 0 <= row < graph_h) or (col, row) in taken:
            continue
        cell = fb.cell_bg(col, row)
        overlays[(col, row)] = (_PLANET_GLYPH, lerp(cell, _PLANET_RGB[key], min(1.0, fade)),
                                True)
        taken.add((col, row))
        hits.append((p[0], p[1], "planet", (key, alt, az, mag)))
        planet_labels.append((body_name(key, runtime), col, row,
                              lerp(cell, label_ink, min(1.0, fade))))
    for entry in gathered:
        if entry[0] >= 3.0:
            place_star(entry)

    # --- the compass, along the horizon ---
    for i, label in enumerate(compass_points(runtime)):
        p = project(_mat_apply(cam, horizontal_vector(i * 45.0, 0.0)), f, cx, cy)
        if p is None:
            continue
        # The label sits on the row under the horizon, or on the edge row
        # when the horizon runs off the screen, as the dome's does.
        col = int(round(p[0] - visible_len(label) / 2.0))
        row = max(0, min(graph_h - 1, int(math.floor(p[1] / 2.0)) + 1))
        cell = fb.cell_bg(max(0, min(graph_w - 1, col)), row)
        _put_text(overlays, taken, label, col, row, lighten(cell, 0.45),
                  i % 2 == 0, graph_w, graph_h, pad=0)

    # --- the names ---
    def beside(text, col, row, ink):
        if not _put_text(overlays, taken, text, col + 2, row, ink, False, graph_w, graph_h):
            _put_text(overlays, taken, text, col - 1 - visible_len(text), row, ink,
                      False, graph_w, graph_h)

    for name, col, row, ink in planet_labels:
        beside(name, col, row, ink)
    for entry in sorted(gathered, key=lambda e: e[10]):
        _above, sx, sy, col, row, glyph, color, bold, i, alt, mag = entry
        if mag > label_limit:
            break
        if i in names and names[i][0] and (col, row) in taken:
            beside(names[i][0], col, row, lerp(fb.cell_bg(col, row), label_ink, 0.85))
    if view.figures >= 2 and scene.darkness > 0.25:
        name_ink = lerp(NIGHT_RGB, FIGURE_NAME_RGB, scene.darkness)
        for record in constellations():
            if not record["lines"]:
                continue
            at = _mat_apply(frame, record["at"])
            if at[2] < 0.0:
                continue
            p = project(at, f, cx, cy)
            if p is None:
                continue
            e, n, u = _mat_apply(_mat_transpose(cam), at)
            if u < 0.02:
                continue
            # Only a constellation with room on screen is named: its
            # figure's spread, projected, must be several cells.
            spread = 0.0
            px0, py0 = p
            for line in record["lines"]:
                for v in line:
                    q = project(_mat_apply(frame, v), f, cx, cy)
                    if q is not None:
                        spread = max(spread, math.hypot(q[0] - px0, q[1] - py0))
            if spread < 10.0:
                continue
            name = constellation_name(record, lang)
            if lang not in NO_CAPITALS:
                name = name.upper()
            col = int(round(px0 - visible_len(name) / 2.0))
            row = int(py0) // 2
            cell = fb.cell_bg(max(0, min(graph_w - 1, col)), max(0, min(graph_h - 1, row)))
            _put_text(overlays, taken, name, col, row, lerp(cell, name_ink, 0.9), False,
                      graph_w, graph_h)

    # --- the faint stars ---
    for entry in gathered:
        if entry[0] < 3.0:
            place_star(entry)

    # --- the constellation figures, in the cells left over ---
    if view.figures and scene.darkness > 0.05:
        dots = {}
        for record in constellations():
            for line in record["lines"]:
                pts = [_mat_apply(frame, v) for v in line]
                for a, b in zip(pts, pts[1:]):
                    _plot_arc(dots, a, b, cam, f, cx, cy, graph_w, graph_h)
        strength = 0.6 * scene.darkness
        for (col, row), bits in dots.items():
            if (col, row) in taken:
                continue
            cell = fb.cell_bg(col, row)
            overlays[(col, row)] = (chr(0x2800 + bits), lerp(cell, FIGURE_RGB, strength),
                                    False)

    # --- the pointer ---
    floating = ""
    if mouse_pos is not None:
        floating = _chip(mouse_pos, hits, scene, runtime, cols, rows, graph_w,
                         graph_h, view)

    lines = fb.render(overlays=overlays)
    lines.append(_status_line(scene, now_local, runtime, view, cols, location_label,
                              offset_minutes, speed, today, limit))
    if hint:
        lines.append(hint)
    return _live.overlay("\n".join(lines), floating)


def _status_line(scene, now_local, runtime, view, width, location_label,
                 offset_minutes, speed, today, limit):
    """Place and clock; where the view faces and how wide; the sky's name
    and what is up. Parts drop from the right as the width runs out."""
    from linecast.sunshine import clock_label
    text, dim, amber = fg(*TEXT_RGB), fg(*DIM_RGB), fg(*AMBER_RGB)
    clock = clock_label(now_local, runtime, today)
    left = f"{text}{location_label} {dim}· {text}{clock}" if location_label else f"{text}{clock}"
    facing = _sk("facing", runtime, dir=compass_point(view.az, runtime))
    if view.alt >= 75.0:
        facing = _sk("overhead", runtime)
    center = f"{dim}{facing} · {_sk('field_of_view', runtime, deg=f'{view.fov:.0f}')}"
    if speed:
        rate = "1h/s" if speed < 20000 else ("1d/s" if speed < 200000 else "1w/s")
        center += f"  {amber}▶ {rate}"
    elif offset_minutes:
        center += f"  {dim}{_ts('space_to_now', runtime)}"
    sky = sky_phase(scene.sun_alt, runtime, morning=scene.morning())
    up = _whats_up(scene, runtime, limit)
    right_full = f"{dim}{sky} · {text}{up}" if up else f"{dim}{sky}"
    right_short = f"{dim}{sky}"

    def fit(*parts):
        used = sum(visible_len(p) for p in parts) + 2 * (len(parts) - 1) + 2
        return used <= width

    for candidate in ((left, center, right_full), (left, center, right_short),
                      (left, center), (left,), ()):
        if fit(*candidate):
            break
    if len(candidate) == 3:
        left, mid, right = candidate
        gap = width - 2 - visible_len(left) - visible_len(mid) - visible_len(right)
        line = (f" {left}{' ' * max(1, gap // 2)}{mid}"
                f"{' ' * max(1, gap - gap // 2)}{right} ")
    elif len(candidate) == 2:
        left, mid = candidate
        gap = width - 2 - visible_len(left) - visible_len(mid)
        line = f" {left}{' ' * max(1, gap)}{mid} "
    elif candidate:
        line = f" {candidate[0]} "
    else:
        line = ""
    return f"{RESET}{line}{RESET}"


def _whats_up(scene, runtime, limit):
    """The Moon and the planets above the horizon, brightest first, each
    with the way to look: '🌖 84% W · Jupiter SE · Saturn S'."""
    parts = []
    if scene.moon_alt > 0.0:
        _idx, _name, icon = moon_phase(scene.moment_utc, runtime)
        parts.append(f"{icon} {scene.moon_illum * 100:.0f}% "
                     f"{compass_point(scene.moon_az, runtime)}")
    for key, _vec, alt, az, mag in scene.planets:
        if alt > 0.0 and easily_seen(mag, alt, scene):
            where = (_sk("overhead", runtime) if alt > 80.0
                     else compass_point(az, runtime))
            parts.append(f"{body_name(key, runtime)} {where}")
    return " · ".join(parts)


def easily_seen(mag, alt, scene):
    """Whether a planet of this magnitude at this altitude is plainly
    visible under the sky as it is: a magnitude inside the eye's limit,
    so the list of what is up names the five classical planets and never
    Uranus, which the chart still draws when the zoom allows."""
    return mag + _extinction(alt) <= scene.eye_limit - 1.0


def _chip(mouse_pos, hits, scene, runtime, cols, rows, graph_w, graph_h, view):
    """The name of what the pointer rests on, floating beside it."""
    mcol, mrow = mouse_pos
    px, prow = mcol - 2, mrow - 1   # the frame has a one-column margin
    if not (0 <= px < graph_w and 0 <= prow < graph_h):
        return ""
    best = None
    for sx, sy, kind, payload in hits:
        dc, dr = int(sx) - px, int(sy) // 2 - prow
        if abs(dc) <= 1 and abs(dr) <= 1:
            score = (abs(dc) + abs(dr), 0 if kind in ("sun", "moon", "planet") else 1)
            if best is None or score < best[0]:
                best = (score, kind, payload)
    if best is None:
        return ""
    _score, kind, payload = best
    tip_bg, tip_fg, tip_dim = bg(*TIP_BG_RGB), fg(*TIP_TEXT_RGB), fg(*TIP_DIM_RGB)
    if kind == "sun":
        title, detail = body_name("sun", runtime), sky_phase(scene.sun_alt, runtime,
                                                              morning=scene.morning())
        alt, az = scene.sun_alt, scene.sun_az
    elif kind == "moon":
        idx, _name, icon = moon_phase(scene.moment_utc, runtime)
        from linecast._tides_i18n import _moon_name
        title = f"{icon} {body_name('moon', runtime)}"
        detail = f"{_moon_name(idx, runtime)} · {scene.moon_illum * 100:.0f}%"
        alt, az = scene.moon_alt, scene.moon_az
    elif kind == "planet":
        key, alt, az, mag = payload
        title, detail = body_name(key, runtime), f"mag {mag:+.1f}"
    else:
        i, alt, mag = payload
        proper, desig = star_names().get(i, ("", ""))
        title = proper or desig or _sk("star", runtime)
        detail = f"{desig} · mag {mag:.1f}" if proper and desig else f"mag {mag:.1f}"
        _alt, az = alt_az_of(_mat_apply(scene.horizontal, star_vectors()[i]))
    where = f"{alt:.0f}° · {compass_point(az, runtime)}"
    lines = [f"{tip_bg}{tip_fg} {title} ",
             f"{tip_bg}{tip_dim} {detail} ",
             f"{tip_bg}{tip_dim} {where} "]
    return _live.pointer_chip(lines, mcol + 2, mrow, cols, rows, pad_bg=tip_bg,
                              flip_at=mcol + 1)


# ---------------------------------------------------------------------------
# Choosing where to look
# ---------------------------------------------------------------------------
def default_view(scene, cols, rows, facing=None, fov=FOV_DEFAULT):
    """Where to look first: the Moon if it is up, else the brightest planet
    up in a dark sky, else south (north below the equator), with the
    horizon just above the bottom of the screen."""
    graph_w, graph_h = max(20, cols - 2), max(6, rows - 3)
    f = focal_length(graph_w, fov)
    # The altitude at the top and bottom edges, looking level.
    half_v = math.degrees(2.0 * math.atan(graph_h / (2.0 * f)))
    alt = max(8.0, min(45.0, half_v - 7.0))
    target_alt = None
    if facing is not None:
        az = facing
    elif scene.moon_alt > 5.0:
        az, target_alt = scene.moon_az, scene.moon_alt
    else:
        az = 180.0 if scene.lat >= 0 else 0.0
        if scene.darkness > 0.3:
            for _key, _vec, p_alt, p_az, mag in scene.planets:
                if p_alt > 8.0 and mag < 1.5:
                    az, target_alt = p_az, p_alt
                    break
    if target_alt is not None and target_alt > alt + half_v * 0.7:
        alt = min(89.0, target_alt - half_v * 0.4)
    return View(az % 360.0, alt, fov, FIGURES_DEFAULT)


def parse_facing(text, runtime=None):
    """A compass point (N, NE, …, in English or the display language) or a
    bearing in degrees, as an azimuth; None for nothing."""
    if text is None:
        return None
    t = text.strip()
    try:
        return float(t) % 360.0
    except ValueError:
        pass
    english = "N NE E SE S SW W NW".split()
    for points in (english, compass_points(runtime) if runtime else english):
        for i, p in enumerate(points):
            if t.upper() == p.upper():
                return i * 45.0
    raise ValueError(f"not a direction: {text!r}")


def main():
    parser = sky_parser()
    args = parser.parse_args()
    runtime = RuntimeConfig.from_sources(args)
    set_current(runtime)

    lat, lng, country = resolve_location(args.location, lang=runtime.lang)
    if lat is None:
        print("Could not determine location.", file=sys.stderr)
        sys.exit(1)
    own = country_for_defaults(args.location, country, lat, lng)
    if own:
        runtime = RuntimeConfig.from_sources(args, country=own)
        set_current(runtime)

    tz = location_tzinfo(lat, lng) if location_is_pinned(args.location) else None

    def _now():
        return datetime.now(tz) if tz is not None else datetime.now().astimezone()

    try:
        facing = parse_facing(args.facing, runtime)
    except ValueError as exc:
        parser.error(str(exc))
    fov = max(FOV_MIN, min(FOV_MAX, args.fov)) if args.fov else FOV_DEFAULT

    if runtime.json_mode:
        import json
        from linecast._sky_json import build_payload
        print(json.dumps(build_payload(_now(), lat, lng, runtime, facing=facing,
                                       fov=fov), ensure_ascii=False))
        return
    if runtime.oneline:
        from linecast._oneline import sky_oneline
        print(sky_oneline(_now(), lat, lng, runtime))
        return

    from linecast._sky_live import SkyApp, place_name
    label = place_name(lat, lng, args.location)
    if not runtime.live:
        now = _now()
        cols, rows = get_terminal_size()
        view = default_view(Scene(now.astimezone(timezone.utc), lat, lng),
                            cols, rows, facing, fov)
        print(render(now, lat, lng, runtime, view, location_label=label))
        return
    SkyApp(_now, lat, lng, runtime, facing=facing, fov=fov, location_label=label).run()


if __name__ == "__main__":
    main()
