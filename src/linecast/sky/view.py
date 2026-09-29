"""The night sky from where you stand: stars, planets, the Moon, the Milky Way.

Usage: sky [--print] [--oneline] [--json] [--location PLACE] [--facing DIR]
           [--at NAME] [--fov DEG] [--culture NAME] [--icons SET] [--emoji]
           [--lang CODE]

You stand at your location and look out: the horizon runs along the
bottom with the compass points under it, and the sky above holds the
real stars for the moment: Yale’s bright stars, with HYG’s fainter stars
revealed as you zoom in. Constellation figures run faintly through
them, beside the planets marked and named, the Moon at its phase and tilt, the
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
anything for its name, or press `/` and type a name or catalogue ID,
including deep-sky objects such as M31. The view flies to it, or says
when it will rise.
`t` opens the traditions: the constellations and star names of
twenty-two cultures besides the IAU's, from the Chinese lunar mansions
to the Hawaiian star lines. The sky draws the one highlighted; Enter
keeps it, Escape puts the sky back. `--culture` or `linecast culture`
picks one to open on, and Chinese brings its own with the language.

Positions come from `astro/ephemeris.py` and `sky/planets.py`, good to a few
arcminutes, which is finer than a cell at the closest zoom.
"""

import math
import sys
from datetime import datetime, timezone

from linecast.terminal.braille import DOT_BITS
from linecast.terminal.color import RESET, bg, fg, interp_stops, lerp
from linecast.terminal.textwidth import visible_len
from linecast.terminal.framebuffer import Framebuffer, cell_aspect, get_terminal_size
from linecast.terminal import live as _live
from linecast.terminal import theme as _theme
from linecast.terminal.theme import (
    best_contrast, darken, ensure_contrast, is_light_theme, lerp_rgb, lighten,
    neutral_tone, surface_bg, theme_legacy_mode,
)
from linecast.astro.ephemeris import mat_apply, mat_mul, mat_transpose
from linecast._i18n import fmt_decimal, fmt_percent, lang_of, setting, upper
from linecast._location import (
    country_for_defaults, location_is_pinned, location_tzinfo, machine_tzinfo,
    resolve_location,
)
from linecast._runtime import RuntimeConfig, install_banner, set_current
from linecast._parsers import sky_parser
from linecast.sky.catalogue import (
    MILKY_WAY_H, MILKY_WAY_W, constellation_name, constellations, culture_title,
    figures_for, milky_way, names_for, resolve_culture, star_names, star_vectors,
    stars,
)
from linecast.sky import deep as _deep
from linecast.sky import objects as _objects
from linecast.sky.scene import (
    FOV_DEFAULT, FOV_MAX, FOV_MIN, Scene, alt_az_of, camera_matrix, compass_marks,
    compass_point, compass_points, default_view, easily_seen, extinction,
    focal_length, horizontal_vector, project, unproject,
)
from linecast.sky.i18n import _sk, body_name
from linecast.sunshine.i18n import clock_label, sky_phase
from linecast.terminal.textwidth import char_width
from linecast.tides.i18n import _ts  # shared "space to return to now" hint
from linecast.moon.disc import _draw_moon_disc
from linecast.sunshine.palette import (
    INFO_AMBER_RGB, INFO_DIM_RGB, INFO_TEXT_RGB, SKY_FAR_HORIZON, SKY_NEAR_HORIZON,
    SKY_NIGHT, SKY_ZENITH, SUN_DOT_RGB, SUN_GLOW_RGB,
)
from linecast.moon.phase import moon_phase

_theme.track_imports(globals(), "linecast.sunshine.palette")

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
    base = None
    for i, ch in enumerate(text):
        w = char_width(ch, text[i + 1] if i + 1 < len(text) else "")
        if w == 0:
            # A combining mark (a Thai vowel or tone mark, say) rides in
            # its base's cell rather than claiming the next one.
            if base is not None:
                c, chars = cells[base]
                cells[base] = (c, chars + ch)
            continue
        base = len(cells)
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


def _plot_arc(dots, a, b, cam, f, cx, cy, graph_w, graph_h, aspect=1.0):
    """A great-circle arc between two camera-frame vectors, as braille
    dots — two across and four down each cell — only above the horizon.
    *dots* maps a cell to its dot bits.

    The camera matrix's third column gives the altitude of a camera-frame
    direction, which is how the arc knows where the ground cuts it.
    """
    ax, ay, az = a
    bx, by, bz = b
    u0, u1, u2 = cam[2], cam[5], cam[8]
    # Normalized interpolation preserves the sign of the horizon's linear
    # dot product. Keep near-tangent arcs: roundoff in the original per-dot
    # check can put a sample just above the horizon even when both ends are
    # just below it.
    if (u0 * ax + u1 * ay + u2 * az < -1e-12
            and u0 * bx + u1 * by + u2 * bz < -1e-12):
        return

    # The shorter great-circle arc lies in the spherical cap centered on
    # normalize(a+b), with half the endpoints' angular separation as its
    # radius. Reject it if that cap misses the cone enclosing the viewport.
    # This avoids sampling long offscreen arcs as their projected lengths
    # grow with zoom. Near-antipodal endpoints keep the original path.
    mx, my, mz = ax + bx, ay + by, az + bz
    size = math.sqrt(mx * mx + my * my + mz * mz)
    if size > 1e-8:
        half_arc = math.acos(max(-1.0, min(1.0, ax * bx + ay * by + az * bz))) * 0.5
        # int() rounds slightly negative screen coordinates into the first
        # cell; a sub-pixel of margin includes those edge samples too.
        view_radius = 2.0 * math.atan(
            math.hypot(cx + 1.0, (cy + 1.0) * aspect) / (2.0 * f))
        separation = math.acos(max(-1.0, min(1.0, mz / size)))
        if separation > view_radius + half_arc + 1e-8:
            return

    pa, pb = project(a, f, cx, cy, aspect), project(b, f, cx, cy, aspect)
    if pa is None or pb is None:
        return
    length = math.hypot(pb[0] - pa[0], pb[1] - pa[1])
    if length > 6.0 * f:
        return   # an arc thrown across the far side of the view
    steps = max(1, int(length * 2.0))
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
        sx, sy = cx + x * k, cy - y * k / aspect
        # Sub-pixels to dots: two dot columns per cell, two dot rows per
        # sub-pixel row.
        dx, dy = int(sx * 2.0), int(sy * 2.0)
        col, row = dx >> 1, dy >> 2
        if 0 <= col < graph_w and 0 <= row < graph_h:
            dots[(col, row)] = dots.get((col, row), 0) | DOT_BITS[dx & 1][dy & 3]


def _glow(fb, x, y, rgb, radius, alpha, cam, f, cx, cy, aspect):
    """A radial glow about (x, y), as the framebuffer's, but only on the
    sky: the ground is not lit by what stands behind it."""
    u0, u1, u2 = cam[2], cam[5], cam[8]
    xi, yi = int(round(x)), int(round(y))
    scan = int(radius) + 2
    scan_y = int(radius / aspect) + 2
    sigma = radius * 0.35
    px = fb.fb
    for dy in range(-scan_y, scan_y + 1):
        sy = yi + dy
        if sy < 0 or sy >= fb.total_spy:
            continue
        for dx in range(-scan, scan + 1):
            sx = xi + dx
            if sx < 0 or sx >= fb.graph_w:
                continue
            dist = math.sqrt(dx * dx + (dy * aspect) ** 2)
            if dist > radius + 1:
                continue
            vx, vy, vz = unproject(sx + 0.5, sy + 0.5, f, cx, cy, aspect)
            if vx * u0 + vy * u1 + vz * u2 < 0.0:
                continue
            px[sy][sx] = lerp(px[sy][sx], rgb, math.exp(-0.5 * (dist / sigma) ** 2) * alpha)


def _behind_the_horizon(fb, x, y, radius, cam, f, cx, cy, aspect, draw):
    """Run *draw*, then give the ground back wherever it looks below the
    horizon within *radius* of (x, y): a rising Sun or Moon is cut by
    the skyline, blended across the sub-pixel the horizon crosses as
    the sky pass blends it."""
    u0, u1, u2 = cam[2], cam[5], cam[8]
    scan = int(radius) + 3
    scan_y = int(radius / aspect) + 3
    x0, x1 = max(0, int(x) - scan), min(fb.graph_w, int(x) + scan + 1)
    y0, y1 = max(0, int(y) - scan_y), min(fb.total_spy, int(y) + scan_y + 1)
    px = fb.fb
    saved = [row[x0:x1] for row in px[y0:y1]]
    draw()
    inv2f = 1.0 / (2.0 * f)
    for sy in range(y0, y1):
        v = (cy - (sy + 0.5)) * inv2f * aspect
        row, before = px[sy], saved[sy - y0]
        for sx in range(x0, x1):
            u = (sx + 0.5 - cx) * inv2f
            d = 1.0 + u * u + v * v
            vx, vy, vz = 2.0 * u / d, 2.0 * v / d, (2.0 - d) / d
            edge = (vx * u0 + vy * u1 + vz * u2) * f * d / aspect
            if edge < -0.5:
                row[sx] = before[sx - x0]
            elif edge < 0.5:
                row[sx] = lerp(before[sx - x0], row[sx], edge + 0.5)


def _draw_disc(fb, x, y, radius, rgb, aspect=1.0):
    """A filled, anti-aliased disc of *radius* sub-pixels across at (x, y)."""
    edge = 0.6
    scan = int(radius + 1.5)
    scan_y = int(radius / aspect + 1.5)
    xi, yi = int(round(x)), int(round(y))
    for dy in range(-scan_y, scan_y + 1):
        for dx in range(-scan, scan + 1):
            r = math.hypot(xi + dx - x, (yi + dy - y) * aspect)
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


def _paint_sky(fb, scene, cam, f, cx, cy, aspect):
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
    # Camera to the J2000 catalogue frame, for the Milky Way raster:
    # the frame's transpose.
    g0, g1, g2, g3, g4, g5, g6, g7, g8 = mat_transpose(mat_mul(cam, scene.catalogue))
    milk = milky_way() if scene.darkness > 0.0 else b""
    milk_alpha = 0.48 * scene.darkness
    milky = MILKY_RGB
    mw_w, mw_h = MILKY_WAY_W, MILKY_WAY_H
    mw_ra, mw_dec = mw_w / 360.0, mw_h / 180.0
    px = fb.fb
    inv2f = 1.0 / (2.0 * f)
    asin, atan2, degrees, sqrt = math.asin, math.atan2, math.degrees, math.sqrt
    omega = 0.0
    cell_omega = inv2f * inv2f * 4.0 * aspect
    for spy in range(fb.total_spy):
        v = (cy - (spy + 0.5)) * inv2f * aspect
        row = px[spy]
        for x in range(fb.graph_w):
            u = (x + 0.5 - cx) * inv2f
            rho2 = u * u + v * v
            d = 1.0 + rho2
            cx_, cy_, cz_ = 2.0 * u / d, 2.0 * v / d, (1.0 - rho2) / d
            up = cx_ * r2 + cy_ * u2 + cz_ * f2
            # A sub-pixel spans aspect/(f·d) radians down here, so
            # up·f·d/aspect is the horizon's distance in sub-pixels: the
            # one it crosses takes a share of each side, and the edge is
            # a line, not a stair.
            edge = up * f * d / aspect
            if edge < -0.5:
                depth = min(30, int(-up * 57.3))
                row[x] = ground[depth]
                continue
            omega += cell_omega / (d * d)
            alt = degrees(asin(up)) if 0.0 < up < 1.0 else (90.0 if up >= 1.0 else 0.0)
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
                # Right ascension runs leftward across the raster, as the
                # sky does from inside; 0h is the middle column.
                mc = int(mw_w / 2.0 - degrees(atan2(gy, gx)) * mw_ra) % mw_w
                gz = gz if -1.0 < gz < 1.0 else (1.0 if gz > 0 else -1.0)
                mr = int((90.0 - degrees(asin(gz))) * mw_dec)
                b = milk[min(mw_h - 1, mr) * mw_w + mc]
                if b > 6:
                    # Thinner near the horizon, where the air takes it.
                    color = lerp(color, milky, milk_alpha * b / 255.0
                                 * min(1.0, alt / 14.0))
            if edge < 0.5:
                color = lerp(ground[0], color, edge + 0.5)
            row[x] = color
    return omega


def _view_eye_limit(scene, fov):
    """Zoom acts like optical magnification at night; daylight stays unchanged.

    Start gaining depth below 60 degrees, reaching five extra magnitudes
    at the closest (6 degree) view. Twilight reduces the gain smoothly.
    """
    gain = max(0.0, 5.0 * math.log10(60.0 / max(fov, FOV_MIN)))
    return scene.eye_limit + gain * scene.darkness


def _star_limit(scene, omega, cells, fov=FOV_DEFAULT):
    """The limiting magnitude for this view: enough stars for the screen's
    share of the sky at the chosen density, allowing fainter stars as
    the view magnifies under a dark sky."""
    if omega <= 0.0:
        return -10.0
    wanted = _STAR_DENSITY / 1000.0 * cells * 4.0 * math.pi / omega
    catalogue = stars()
    eye = _view_eye_limit(scene, fov)
    if int(wanted) >= len(catalogue) and eye > 6.5:
        by_zoom = _deep.magnitude_at(int(wanted) - len(catalogue))
    else:
        rank = min(len(catalogue) - 1, int(wanted))
        by_zoom = catalogue[rank][2] if rank >= 0 else -10.0
    return min(by_zoom, eye)


def _star_candidates(frame, f, cx, cy, aspect, limit, deep=True):
    """Bright Yale stars followed by HYG stars in the screen's sky cone.

    Negative indices identify the separate supplement, leaving every
    existing name/culture index stable. The cone encloses all four
    corners; *frame* carries the catalogue's own J2000 frame, which is
    the frame the supplement's zones are divided in.
    """
    vectors = star_vectors()
    for i, (_ra, _dec, mag, bv) in enumerate(stars()):
        if mag > limit:
            break
        yield i, mag, bv, vectors[i]
    if deep:
        radius = 2.0 * math.atan(math.hypot(cx, cy * aspect) / (2.0 * f))
        for i, mag, bv, vector in _deep.candidates(frame[6:9], radius, limit):
            yield -i - 1, mag, bv, vector


def _label_limit(fov):
    """The magnitude down to which named stars carry their names: the
    brightest handful at a wide view, all of them close in."""
    return 3.3 - 1.1 * math.log2(max(fov, 1.0) / 20.0)


def _screen_up_deg(v_cam, cam, f, cx, cy, aspect):
    """The screen bearing (0 up, 90 right) of the local vertical at a
    camera-frame point: which way is 'up' there in the projection, as
    the eye sees it rather than as the grid counts it."""
    e, n, u = mat_apply(mat_transpose(cam), v_cam)
    alt, az = alt_az_of((e, n, u))
    higher = mat_apply(cam, horizontal_vector(az, min(89.9, alt + 0.5)))
    p0, p1 = project(v_cam, f, cx, cy, aspect), project(higher, f, cx, cy, aspect)
    if p0 is None or p1 is None:
        return 0.0
    return math.degrees(math.atan2(p1[0] - p0[0], -(p1[1] - p0[1]) * aspect))


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
    graph_w = max(20, cols)
    reserve = (1 if hint else 0) + (0 if fullscreen else 3)
    graph_h = max(6, rows - reserve)
    total_spy = graph_h * 2

    moment_utc = now_local.astimezone(timezone.utc)
    scene = Scene(moment_utc, lat, lng)
    cam = camera_matrix(view.az, view.alt)
    f = focal_length(graph_w, view.fov)
    cx, cy = graph_w / 2.0, total_spy / 2.0
    # A sub-pixel's height in cell widths: 1.0 on the 2:1 cell that
    # makes a half-block's two sub-pixels square, and whatever the font
    # really has where the terminal says.  The field of view is set
    # across the width; the height follows the screen's true shape.
    aspect = cell_aspect() / 2.0
    frame = mat_mul(cam, scene.catalogue)   # the J2000 catalogue to camera
    lang = lang_of(runtime)

    figures = figures_for(view.culture, lang) if view.culture else constellations()
    names = names_for(view.culture, lang) if view.culture else star_names(lang)

    fb = Framebuffer(graph_w, graph_h, bg_color=NIGHT_RGB)
    omega = _paint_sky(fb, scene, cam, f, cx, cy, aspect)
    limit = _star_limit(scene, omega, graph_w * graph_h, view.fov)
    eye_limit = _view_eye_limit(scene, view.fov)
    overlays = {}
    taken = set()
    status_labels = []
    if fullscreen:
        from linecast.terminal.help import hint as help_hint, paint_text
        help_label = help_hint(lang, graph_w)
        room = max(0, graph_w - visible_len(help_label) - 2)
        status_labels = _status_line(scene, now_local, runtime, view, room, location_label,
                                     offset_minutes, speed, today, layout=True)
        status_labels.append((graph_w - visible_len(help_label), help_label))
        for x, text in status_labels:
            paint_text(fb, overlays, text, x, graph_h - 1, TEXT_RGB)
        taken.update(overlays)
        # A cell of air beside the labels; the rest of the row remains sky.
        for x, row in tuple(taken):
            taken.update((c, row) for c in (x - 1, x + 1) if 0 <= c < graph_w)
    # Extended light is behind the foreground stars, Moon and planets.
    object_labels, hits = _objects.paint(
        fb, scene, cam, frame, f, cx, cy, eye_limit, STAR_RGB, aspect)

    # --- the Sun ---
    sun_cam = mat_apply(cam, scene.sun)
    sun_at = project(sun_cam, f, cx, cy, aspect) if scene.sun_alt > -3.0 else None
    if sun_at is not None:
        sx, sy = sun_at
        radius = max(2.0, f * math.tan(math.radians(0.267)) * 2.0)
        glow = max(10.0, radius * 6.0)
        lift = max(0.0, min(1.0, (scene.sun_alt + 3.0) / 6.0))
        _glow(fb, sx, sy, SUN_GLOW_RGB, glow, 0.9 * lift, cam, f, cx, cy, aspect)
        if scene.sun_alt > -0.9:
            _behind_the_horizon(fb, sx, sy, radius, cam, f, cx, cy, aspect,
                                lambda: _draw_disc(fb, sx, sy, radius, SUN_DOT_RGB,
                                                   aspect))
        hits.append((sx, sy, "sun", None))

    # --- the Moon ---
    moon_cam = mat_apply(cam, scene.moon)
    moon_at = project(moon_cam, f, cx, cy, aspect) if scene.moon_alt > -1.0 else None
    if moon_at is not None:
        mx, my = moon_at
        radius = max(2.2, f * math.tan(math.radians(0.26)) * 2.0)
        illum = scene.moon_illum
        # At night the Moon owns its patch of sky, with a halo, its maria,
        # and earthshine on the night side. By day it is washed out: the
        # sunlit surface near white with the maria faint, the night side
        # the sky itself, and a grey zone along the terminator the only
        # sign of the dark half.
        dark = scene.darkness
        if dark > 0.0:
            _glow(fb, mx, my, MOON_GLOW_RGB, max(3.0, radius * 1.8),
                  (0.12 + 0.28 * illum) * dark, cam, f, cx, cy, aspect)
        cell = fb.cell_bg(max(0, min(graph_w - 1, int(mx))),
                          max(0, min(graph_h - 1, int(my) // 2)))
        up = _screen_up_deg(moon_cam, cam, f, cx, cy, aspect)
        _behind_the_horizon(fb, mx, my, radius, cam, f, cx, cy, aspect, lambda: _draw_moon_disc(
            fb, int(round(mx)), int(round(my)), radius, illum,
            up + scene.moon_limb, up + scene.moon_axis, None,
            night=lerp(cell, darken(NIGHT_RGB, 0.5), dark),
            lit=lerp((253, 253, 255), MOON_LIT_RGB, dark),
            contrast=0.35 + 0.65 * dark, earthshine=dark,
            dusk=0.4 * (1.0 - dark), aspect=aspect))
        hits.append((mx, my, "moon", None))

    # --- the stars, gathered ---
    # Everything with a cell is gathered first and laid down in order of
    # its claim: planets and the bright stars, then the names, then the
    # faint stars, then the constellation figures in whatever cells are
    # left, so a name never covers a bright star and a figure never
    # covers a name.
    label_limit = _label_limit(view.fov)
    dim, mid, bright = STAR_DIM_RGB, STAR_RGB, STAR_BRIGHT_RGB
    m0, m1, m2, m3, m4, m5, m6, m7, m8 = frame
    u0, u1, u2 = cam[2], cam[5], cam[8]
    # The stars fade in at the edge of what the eye can see; where the
    # zoom sets the limit there is nothing to fade toward.
    fading = eye_limit < limit + 0.7
    gathered = []   # (above, sx, sy, col, row, glyph, color, bold, i, alt, mag)
    seen_cells = set()
    candidates = _star_candidates(frame, f, cx, cy, aspect, limit + 0.5,
                                  deep=eye_limit > scene.eye_limit)
    for i, mag, bv, (x, y, z) in candidates:
        cxv = m0 * x + m1 * y + m2 * z
        cyv = m3 * x + m4 * y + m5 * z
        czv = m6 * x + m7 * y + m8 * z
        if czv < -0.82:
            continue
        k = 2.0 * f / (1.0 + czv)
        sx, sy = cx + cxv * k, cy - cyv * k / aspect
        if not (0.0 <= sx < graph_w and 0.0 <= sy < total_spy):
            continue
        up = u0 * cxv + u1 * cyv + u2 * czv
        if up <= 0.0:
            continue
        alt = math.degrees(math.asin(min(1.0, up)))
        seen = mag + extinction(alt)
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
        fade = (eye_limit + 0.8 - (mag + extinction(alt))) / 1.0
        if fade <= 0.0 or mag > limit + 0.8:
            continue
        p = project(mat_apply(cam, vec), f, cx, cy, aspect)
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
    # The cardinal points first, so they win the room from the others.
    marks = sorted(compass_marks(runtime, view.culture), key=lambda m: not m[2])
    for az, label, bold in marks:
        p = project(mat_apply(cam, horizontal_vector(az, 0.0)), f, cx, cy, aspect)
        if p is None:
            continue
        # The label sits on the row under the horizon, or on the edge row
        # when the horizon runs off the screen, as the dome's does.
        col = int(round(p[0] - visible_len(label) / 2.0))
        row = max(0, min(graph_h - 1, int(math.floor(p[1] / 2.0)) + 1))
        cell = fb.cell_bg(max(0, min(graph_w - 1, col)), row)
        _put_text(overlays, taken, label, col, row, lighten(cell, 0.45),
                  bold, graph_w, graph_h, pad=1)

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
    for record, col, row, strength in object_labels:
        if strength < 0.15 or (view.fov > 60 and record['mag'] > 4.5):
            continue
        name = (_objects.object_name(record, lang) if view.fov <= 60 else record['id'])
        beside(name, col, row, lerp(fb.cell_bg(col, row), label_ink, 0.65 * strength))
    if view.figures >= 2 and scene.darkness > 0.25:
        name_ink = lerp(NIGHT_RGB, FIGURE_NAME_RGB, scene.darkness)
        for record in figures:
            if not record["lines"]:
                continue
            at = mat_apply(frame, record["at"])
            if at[2] < 0.0:
                continue
            p = project(at, f, cx, cy, aspect)
            if p is None:
                continue
            e, n, u = mat_apply(mat_transpose(cam), at)
            if u < 0.02:
                continue
            # Only a constellation with room on screen is named: its
            # figure's spread, projected, must be several cells.
            spread = 0.0
            px0, py0 = p
            for line in record["lines"]:
                for v in line:
                    q = project(mat_apply(frame, v), f, cx, cy, aspect)
                    if q is not None:
                        spread = max(spread, math.hypot(q[0] - px0, q[1] - py0))
            if spread < 10.0:
                continue
            name = record["name"] if view.culture else constellation_name(record, lang)
            if setting(lang, "capitals"):
                name = upper(name, lang)
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
        for record in figures:
            for line in record["lines"]:
                pts = [mat_apply(frame, v) for v in line]
                for a, b in zip(pts, pts[1:]):
                    _plot_arc(dots, a, b, cam, f, cx, cy, graph_w, graph_h, aspect)
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

    # The Moon and extended objects may have painted under a label after
    # its space was reserved. Pick its final ink from the finished image.
    for x, text in status_labels:
        paint_text(fb, overlays, text, x, graph_h - 1,
                   None if text == help_label else TEXT_RGB)
    lines = fb.render(overlays=overlays)
    if not fullscreen:
        lines.append(_status_line(scene, now_local, runtime, view, cols, location_label,
                                  offset_minutes, speed, today))
    if hint:
        lines.append(hint)
    return _live.overlay("\n".join(lines), floating)


def _status_line(scene, now_local, runtime, view, width, location_label,
                 offset_minutes, speed, today, layout=False):
    """Place and clock; where the view faces and how wide; the sky's name
    and what is up. Parts drop from the right as the width runs out.
    With layout=True, return positioned plain labels for the image."""
    text, dim, amber = fg(*TEXT_RGB), fg(*DIM_RGB), fg(*AMBER_RGB)
    clock = clock_label(now_local, runtime, today)
    if layout:
        text = dim = amber = ''
        if visible_len(location_label) + visible_len(clock) + 3 > max(20, width // 2):
            location_label = ''
    left = f"{text}{location_label} {dim}· {text}{clock}" if location_label else f"{text}{clock}"
    facing = _sk("facing", runtime, dir=compass_point(view.az, runtime, view.culture,
                                                      quadrant=True))
    if view.alt >= 75.0:
        facing = _sk("overhead", runtime)
    center = f"{dim}{facing} · {_sk('field_of_view', runtime, deg=f'{view.fov:.0f}')}"
    if view.culture:
        center += f" · {culture_title(view.culture, lang_of(runtime))}"
    if speed:
        rate = "1h/s" if speed < 20000 else ("1d/s" if speed < 200000 else "1w/s")
        center += f"  {amber}▶ {rate}"
    elif offset_minutes:
        center += f"  {dim}{_ts('space_to_now', runtime)}"
    sky = sky_phase(scene.sun_alt, runtime, morning=scene.morning())
    up = _whats_up(scene, runtime, view.culture)
    right_full = f"{dim}{sky} · {text}{up}" if up else f"{dim}{sky}"
    right_short = f"{dim}{sky}"

    def fit(*parts):
        used = sum(visible_len(p) for p in parts) + 2 * (len(parts) - 1)
        return used <= width

    for candidate in ((left, center, right_full), (left, center, right_short),
                      (left, center), (left,), ()):
        if fit(*candidate):
            break
    if len(candidate) == 3:
        left, mid, right = candidate
        gap = width - visible_len(left) - visible_len(mid) - visible_len(right)
        line = (f"{left}{' ' * max(1, gap // 2)}{mid}"
                f"{' ' * max(1, gap - gap // 2)}{right}")
        positions = [(0, left), (visible_len(left) + max(1, gap // 2), mid),
                     (width - visible_len(right), right)]
    elif len(candidate) == 2:
        left, mid = candidate
        gap = width - visible_len(left) - visible_len(mid)
        line = f"{left}{' ' * max(1, gap)}{mid}"
        positions = [(0, left), (width - visible_len(mid), mid)]
    elif candidate:
        line = candidate[0]
        positions = [(0, candidate[0])]
    else:
        line = ""
        positions = []
    if layout:
        return positions
    return f"{RESET}{line}{RESET}"


def _whats_up(scene, runtime, culture=None):
    """The Moon and the planets above the horizon, brightest first, each
    with the way to look: '🌖 84% W · Jupiter SE · Saturn S'."""
    parts = []
    if scene.moon_alt > 0.0:
        _idx, _name, icon = moon_phase(scene.moment_utc, runtime)
        parts.append(f"{icon} {fmt_percent(scene.moon_illum * 100, runtime)} "
                     f"{compass_point(scene.moon_az, runtime, culture)}")
    for key, _vec, alt, az, mag in scene.planets:
        if alt > 0.0 and easily_seen(mag, alt, scene):
            where = (_sk("overhead", runtime) if alt > 80.0
                     else compass_point(az, runtime, culture))
            parts.append(f"{body_name(key, runtime)} {where}")
    return " · ".join(parts)


def _chip(mouse_pos, hits, scene, runtime, cols, rows, graph_w, graph_h, view):
    """The name of what the pointer rests on, floating beside it."""
    mcol, mrow = mouse_pos
    px, prow = mcol - 1, mrow - 1   # 1-based terminal cell to 0-based image cell
    if not (0 <= px < graph_w and 0 <= prow < graph_h):
        return ""
    best = None
    for sx, sy, kind, payload in hits:
        dc, dr = int(sx) - px, int(sy) // 2 - prow
        if abs(dc) <= 1 and abs(dr) <= 1:
            priority = 0 if kind in ("sun", "moon", "planet") else (2 if kind == 'deep_sky' else 1)
            score = (abs(dc) + abs(dr), priority)
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
        from linecast.tides.i18n import _moon_name
        title = f"{icon} {body_name('moon', runtime)}"
        detail = f"{_moon_name(idx, runtime)} · {fmt_percent(scene.moon_illum * 100, runtime)}"
        alt, az = scene.moon_alt, scene.moon_az
    elif kind == 'deep_sky':
        record, alt, az = payload
        title = _objects.object_name(record, lang_of(runtime))
        major, minor = record['size']
        size = f"{major:g}′" if major == minor else f"{major:g}′ × {minor:g}′"
        size = size.replace(".", setting(lang_of(runtime), "decimal"))
        detail = f"{record['id']} · mag {fmt_decimal(record['mag'], 1, runtime)} · {size}"
    elif kind == "planet":
        key, alt, az, mag = payload
        sign = "+" if mag >= 0 else ""
        title, detail = body_name(key, runtime), f"mag {sign}{fmt_decimal(mag, 1, runtime)}"
    else:
        i, alt, mag = payload
        lang = lang_of(runtime)
        proper, desig = (names_for(view.culture, lang) if view.culture
                         else star_names(lang)).get(i, ("", ""))
        iau_name = star_names().get(i, ("", ""))[0]
        title = proper or desig or _sk("star", runtime)
        mag_txt = f"mag {fmt_decimal(mag, 1, runtime)}"
        detail = f"{desig} · {mag_txt}" if proper and desig else mag_txt
        if iau_name and iau_name != proper:
            # A culture's name, or the language's own, with the IAU's beside it.
            detail = f"{iau_name} · {detail}"
        if i < 0:
            _mag, _bv, vector, title = _deep.star(-i - 1)
        else:
            vector = star_vectors()[i]
        _alt, az = alt_az_of(mat_apply(scene.catalogue, vector))
    where = f"{alt:.0f}° · {compass_point(az, runtime, view.culture)}"
    lines = [f"{tip_bg}{tip_fg} {title} ",
             f"{tip_bg}{tip_dim} {detail} ",
             f"{tip_bg}{tip_dim} {where} "]
    return _live.pointer_chip(lines, mcol + 2, mrow, cols, rows, pad_bg=tip_bg,
                              flip_at=mcol + 1)


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

    tz = location_tzinfo(lat, lng) if location_is_pinned(args.location) else machine_tzinfo()

    def _now():
        return datetime.now(tz)

    try:
        facing = parse_facing(args.facing, runtime)
    except ValueError as exc:
        parser.error(str(exc))
    fov = max(FOV_MIN, min(FOV_MAX, args.fov)) if args.fov else FOV_DEFAULT
    culture = resolve_culture(args.culture, lang_of(runtime))
    aim = None
    if args.at:
        from linecast.sky.search import search, targets
        found = search(args.at, targets(runtime, culture), limit=1)
        if not found:
            parser.error(f"nothing in the sky called {args.at!r}")
        target = found[0]
        aim = target.place(Scene(_now().astimezone(timezone.utc), lat, lng))
        if not args.fov:
            fov = target.fov(FOV_DEFAULT)

    if runtime.json_mode:
        import json
        from linecast.sky.json import build_payload
        print(json.dumps(build_payload(_now(), lat, lng, runtime, facing=facing,
                                       fov=fov), ensure_ascii=False))
        return
    if runtime.oneline:
        from linecast.terminal.oneline import emit, sky_oneline
        emit(sky_oneline(_now(), lat, lng, runtime))
        return

    from linecast.sky.live import SkyApp, place_name
    label = place_name(lat, lng, args.location, lang=runtime.lang)
    if not runtime.live:
        now = _now()
        cols, rows = get_terminal_size()
        view = default_view(Scene(now.astimezone(timezone.utc), lat, lng),
                            cols, rows, facing, fov, aim=aim)._replace(culture=culture)
        from linecast.terminal.live import print_frame
        print_frame(render(now, lat, lng, runtime, view, location_label=label))
        return
    SkyApp(_now, lat, lng, runtime, facing=facing, fov=fov, location_label=label,
           aim=aim, culture=culture).run()

