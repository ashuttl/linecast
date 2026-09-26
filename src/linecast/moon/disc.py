"""The Moon's disc: its surface, its terminator, and a turn to drag it by.

The moon view draws it large, the month calendar small for each day,
and the sky view where the Moon stands.
"""

import math
import threading
import time

from linecast.terminal import live as _live
from linecast.terminal import theme as _theme
from linecast.terminal.graphics import lerp
from linecast._runtime import log_failure
from linecast.terminal.theme import darken
from linecast.moon.palette import MOON_LIT_RGB, MOON_SHADOW_RGB

_theme.track_imports(globals(), "linecast.moon.palette")

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
        from linecast._paths import data_path
        from linecast._png import decode_rgba
        data = data_path("moon_albedo.png").read_bytes()
        w, h, rgba = decode_rgba(data)
        _albedo = (w, h, bytes(rgba[::4]))
    except Exception as exc:
        log_failure("png", "moon albedo load", exc, fallback="plain disc")
        _albedo = None
    return _albedo


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
        self.radius = 40.0    # the disc's radius in cells, from the last render
        self.aspect = 1.0     # a sub-pixel's height in cell widths, likewise
        self._base = None     # orientation when the drag began
        self._held = None     # orientation under the pointer, mid-drag
        self._settle = None   # (axis, angle, started) after a release
        self._ticker = None

    def drag(self, dcol, drow):
        """The pointer has moved this far, in cells, since the press."""
        if self._base is None:
            self._base = self.matrix() or _IDENTITY  # mid-settle: pick it up
            self._settle = None
        dx, dy = float(dcol), 2.0 * drow * self.aspect   # a cell is two sub-pixels tall
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
# The daylit ground's brightness, from the photometric law in
# _draw_moon_disc, is raised to this before it colours a pixel: the eye
# and a camera compress the Moon's range, and the terminator of a
# quarter Moon in a photograph is a grade over the last fifth or so of
# the daylit ground, not the half that the law alone would make it.
SUNLIT_GAMMA = 0.65


def _ease_out_back(s):
    """0→1 with a small overshoot near the end, so the settle bounces."""
    c1 = 1.2
    return 1.0 + (c1 + 1.0) * (s - 1.0) ** 3 + c1 * (s - 1.0) ** 2


def _lit_fraction(ux, uy, uz, d, radius, sun):
    """How much of the pixel at a unit-sphere point is in daylight.

    *d* is the cosine of the Sun's elevation there. Its gradient across
    the screen says how many pixels away the terminator is, and the
    pixel is blended across that one-pixel band. Measured on the screen
    rather than in the cosine, the band stays a pixel wide however
    foreshortened the ground: softening the cosine itself lit half of
    every limb pixel at new and full, a rim the Moon does not have.
    """
    sun_x, sun_y, sun_z = sun
    gx = sun_x - sun_z * ux / uz
    gy = sun_y - sun_z * uy / uz
    grad = math.sqrt(gx * gx + gy * gy)
    dist = d * radius / grad if grad > 1e-9 else (2.0 if d > 0.0 else -2.0)
    return max(0.0, min(1.0, 0.5 + dist))


def _lit_fraction_at_limb(ux, uy, r, radius, sun):
    """The daylit share of a pixel at the limb.

    At the limb the ground is seen edge-on and a straight-line estimate
    fails: the terminator runs into the limb at a tangent, so a thin
    crescent is a sliver a fraction of a pixel deep and a new Moon's is
    nothing at all. Measured along the radius through the pixel, the
    Sun's elevation is A*rho + B*sqrt(1 - rho^2) -- A the Sun's pull
    along the radius, B its height over the disc -- which changes sign
    at most once, so the lit length of the pixel's radial span is exact.
    A span that overhangs the limb slides inside it, keeping its width:
    the anti-aliased edge already thins those pixels, and a sliver of
    lit ground should not fill the sliver of span that is left.

    The pixel has width across the radius too, over which A changes by
    the Sun's pull across the radius times the angle the pixel subtends.
    Four spans across the pixel are averaged, so where the terminator
    runs along a radius -- the equator of a quarter Moon meeting the
    limb -- the pixel comes out half lit, and not wholly lit or dark on
    the sign of a rounding error.

    The Sun's elevation and the viewer's, at the middle of the lit part
    of the span, come back with the share: they are what the lit
    ground's brightness is read from, and at the limb the pixel's
    centre may lie in the dark of a sliver that is lit.
    """
    sun_x, sun_y, sun_z = sun
    if r <= 0.0:
        return (1.0, sun_z, 1.0) if sun_z > 0.0 else (0.0, 0.0, 1.0)
    a = (ux * sun_x + uy * sun_y) / r
    t = (ux * sun_y - uy * sun_x) / r
    half = 0.5 / radius
    hi = min(1.0, r + half)
    lo = max(0.0, hi - 2.0 * half)
    step = t * half / r
    share = sum(_radial_lit(a + s * step, sun_z, lo, hi)[0]
                for s in (-0.75, -0.25, 0.25, 0.75)) / 4.0
    _, lit_lo, lit_hi = _radial_lit(a, sun_z, lo, hi)
    rho = 0.5 * (lit_lo + lit_hi)
    up = math.sqrt(max(0.0, 1.0 - rho * rho))
    return share, a * rho + sun_z * up, up


def _radial_lit(a, b, lo, hi):
    """The lit part of the radial span [lo, hi].

    Returns its length as a share of the span, and where it starts and
    ends along the radius.
    """
    if a >= 0.0 and b >= 0.0:
        return 1.0, lo, hi
    if a <= 0.0 and b <= 0.0:
        return 0.0, lo, lo
    # Opposite signs: the elevation crosses zero once, at rho_t.
    rho_t = math.sqrt(b * b / (a * a + b * b))
    if a > 0.0:                       # lit beyond rho_t, toward the limb
        lit_lo, lit_hi = min(hi, max(lo, rho_t)), hi
    else:                             # lit inside rho_t, toward the centre
        lit_lo, lit_hi = lo, max(lo, min(hi, rho_t))
    return (lit_hi - lit_lo) / (hi - lo), lit_lo, lit_hi


def _draw_moon_disc(fb, cx, cy, radius, illum, limb_deg, axis_deg,
                    turn=None, night=None, lit=None, contrast=1.0,
                    earthshine=1.0, dusk=0.0, aspect=1.0):
    """Draw the phase-shaded lunar disc centered at (cx, cy) sub-pixels.

    *radius* is in cells across; *aspect* is a sub-pixel's height in cell
    widths, so the disc stands radius/aspect sub-pixels tall and comes
    out round on the screen rather than on the grid (see render).

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
    when the Sun is above its horizon; seen from the front that is the
    standard phase ellipse, the whole disc at full, a straight edge at
    the quarters, nothing at new. The edge is anti-aliased in screen
    space, over one pixel, so a thin crescent tapers to nothing at the
    poles and a new Moon shows no rim at all. The daylit ground is not
    one brightness, though: it fades toward the terminator, where the
    Sun is low over it, so the edge itself is the dark end of a
    gradient, as it is in a photograph.

    The night side facing Earth is not quite black: earthshine lifts it
    by the Earth's own phase, which is the complement of the Moon's, so
    the maria show faintly in the old Moon in the new Moon's arms and
    not at all near full. The far side's night gets none. *night* is
    the colour of that unlit ground; the shadow colour when not given.

    The last four are for a Moon in a lit sky, where it looks nothing
    like it does at night: *lit* is the colour of the sunlit surface
    (the palette's white when not given), *contrast* scales the maria
    and the limb's darkening, *earthshine* scales the night side's lift
    (none by day, when the sky outshines it), and *dusk* darkens the lit
    surface toward the terminator, where the Sun is low over the ground
    and the relief throws shadows -- the grey zone a daytime Moon shows
    beside a limb that has vanished into the sky.
    """
    if night is None:
        night = MOON_SHADOW_RGB
    if lit is None:
        lit = MOON_LIT_RGB
    edge = max(1.0 / radius, 0.04)   # anti-aliasing band, in unit radii
    # Pixels this close to the limb see the ground edge-on, where the
    # Sun's elevation changes too fast across a pixel for a straight-line
    # estimate; they are measured along the radius instead.
    band = (1.0 - 1.5 / radius) ** 2 if radius > 1.5 else 0.0
    earthshine = 0.20 * (1.0 - illum) * earthshine  # night-side lift, facing Earth square on
    scan = int(radius + 2)
    scan_y = int(radius / aspect + 2)
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

    for dy in range(-scan_y, scan_y + 1):
        uy = dy * aspect / radius
        for dx in range(-scan, scan + 1):
            ux = dx / radius
            rr = ux * ux + uy * uy
            r = math.sqrt(rr)
            if r > 1.0 + edge:
                continue
            cover = min(1.0, ((1.0 + edge) - r) / (2.0 * edge))
            if cover <= 0.02:
                continue

            # The cosine of the Sun's elevation over this point, and how
            # much of the pixel is in daylight.
            uz = math.sqrt(1.0 - rr) if rr < 1.0 else 0.0
            d = ux * sun_x + uy * sun_y + uz * sun_z
            if rr < band:
                lit_alpha = _lit_fraction(ux, uy, uz, d, radius, sun)
                sun_up, view_up = d, uz
            else:
                lit_alpha, sun_up, view_up = _lit_fraction_at_limb(
                    ux, uy, r, radius, sun)
            # How bright the daylit ground is. Moon dust throws light
            # back the way it came, so the surface brightens not with
            # the Sun's elevation alone but with its share of the Sun's
            # and the viewer's together (Lommel-Seeliger): the full Moon
            # is flat to the limb, while a quarter fades from its bright
            # limb to darkness at the terminator, where the Sun is on
            # the horizon and every crater is in its own shadow. The
            # root is the eye's compression of the range.
            if lit_alpha > 0.0 and sun_up > 0.0:
                lit_alpha *= min(1.0, 2.0 * sun_up / (sun_up + view_up)) ** SUNLIT_GAMMA
            else:
                lit_alpha = 0.0

            shade = 0.18 * rr  # limb falloff
            if albedo is not None:
                shade += _surface_shade(m00 * ux + m01 * uy + m02 * uz,
                                        m10 * ux + m11 * uy + m12 * uz,
                                        m20 * ux + m21 * uy + m22 * uz,
                                        albedo)
            lit_px = darken(lit, min(0.55, shade * contrast))
            if dusk > 0.0 and d < 0.6:
                lit_px = darken(lit_px, dusk * math.exp(-max(0.0, d) / 0.12))
            # Earthshine: the shaded surface, faintly, where Earth is up.
            glow = earthshine * (ux * earth_x + uy * earth_y + uz * earth_z)
            night_px = lerp(night, lit_px, glow) if glow > 0.0 else night
            color = lerp(night_px, lit_px, lit_alpha)
            fb.set_pixel(cx + dx, cy + dy, color, cover)
