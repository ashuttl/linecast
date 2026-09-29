"""The stars about the Moon, for the moon view's sky.

The moon view (moon/view.py) draws the Moon large in the middle of its
sky and asks here for the stars around it, as character overlays clear
of the disc and of the panel's text.
"""

import math

from linecast.terminal import theme as _theme
from linecast.terminal.color import lerp
from linecast.astro.ephemeris import mat_apply
from linecast.moon.palette import STAR_BRIGHT_RGB, STAR_DIM_RGB, STAR_RGB

_theme.track_imports(globals(), "linecast.moon.palette")


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
# Catalogue (see scripts/build_sky_catalogue.py and sky.catalogue),
# placed about the Moon's true position for the moment, with celestial
# north turned by the parallactic angle the disc already follows. So
# scrolling through time wheels the sky with the night and walks the
# Moon through its constellations. The catalogue is J2000 and the Moon
# is of date, so the Moon's place is turned back into the catalogue's
# frame before the distances and position angles are taken: one vector
# rotated rather than every star. The disc is drawn far larger than
# scale; the sky is projected as an equidistant fisheye, screen centre
# looking away from the viewer, whose focal length is the disc's radius
# and a half — the screen's corner is about ninety degrees from the
# Moon — which keeps the resting sky evenly sown out to the corners and
# lets a drag carry the sky round the other way, as the background does
# when you walk round a statue, at about half again the surface's pace.
_STAR_FOCAL = 1.5


def _load_stars():
    """[(ra_rad, dec_rad)] brightest first, from the bundled catalogue."""
    from linecast.sky.catalogue import star_positions
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


def _project_star(d, turn, cx, cy, radius, aspect=1.0):
    """The cell a star in direction *d* lands on, or None if it is behind
    the viewer. *turn* is the disc's rotation, or None at rest; *aspect*
    is a sub-pixel's height in cell widths (see moon.view.render)."""
    if turn is not None:
        d = mat_apply(turn, d)
    x, y, z = d
    sin_t = math.sqrt(x * x + y * y)
    if sin_t < 1e-9:
        if z > 0.0:
            return None      # straight behind the viewer
        dx = dy = 0.0
    else:
        t = math.atan2(sin_t, -z) * _STAR_FOCAL * radius / sin_t
        dx, dy = x * t, y * t
    return int(round(cx + dx)), int((cy + dy / aspect) // 2)


def star_overlays(fb, cx, cy, radius, sky, taken=(), turn=None, aspect=1.0):
    """The stars as character overlays, clear of the Moon.

    Returns {(col, row): (glyph, rgb, bold)}.  Stars are drawn as glyphs
    rather than sub-pixels, so each one claims a whole cell; *taken* is the
    set of cells the corners' text already owns, which a star must not
    displace. *sky* places the Moon among the stars (see _star_direction);
    *turn* is the disc's rotation, which carries the sky round.
    """
    # Show the brightest stars down to the magnitude that puts about
    # _STAR_DENSITY per thousand cells on screen: the screen's solid
    # angle, cell by cell, says how much of the sky it holds.
    focal = _STAR_FOCAL * radius
    seen = 0.0
    for row in range(fb.graph_h):
        dy = ((row * 2 + 0.5) - cy) * aspect
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
        cell = _project_star(_star_direction(ra, dec, sky), turn, cx, cy, radius,
                             aspect)
        if cell is None:
            continue
        x, row = cell
        if not (0 <= x < fb.graph_w and 0 <= row < fb.graph_h) or (x, row) in taken:
            continue
        dx, dy = x - cx, ((row * 2 + 0.5) - cy) * aspect
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
