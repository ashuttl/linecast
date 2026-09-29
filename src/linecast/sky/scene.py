"""Where the sky is, apart from how it is drawn.

The geometry under the sky view. `Scene` places the Sun, the Moon, the
planets and the catalogue's frame for one moment and one observer.
The matrices turn the equator to the horizon and the horizon to the
screen, `project` and `unproject` are the stereographic projection
both ways, the compass names the directions along the horizon, and
`default_view` picks where to look first. The drawing is `sky/view.py`;
the `--json`, the one-line summary and the search take what they need
from here without loading it.
"""

import math
from collections import namedtuple

from linecast.astro.ephemeris import (
    _alt_az_deg, _gmst_deg, _moon_parallactic_deg, _moon_ra_dec, _sun_ra_dec,
    mat_mul, moon_axis_deg, moon_bright_limb_deg, moon_horizontal_parallax_deg,
    moon_illuminated_fraction, precession_at,
)
from linecast._geo import angle_delta
from linecast._i18n import lang_of
from linecast.radar.i18n import compass_point as _eight_point
from linecast.radar.i18n import rs
from linecast.sky.planets import planet_positions
from linecast.terminal.framebuffer import cell_aspect

# The eye's limiting magnitude by the Sun's altitude: the whole
# catalogue at full night, the brightest few stars in civil twilight,
# Venus alone by day.
_LIMIT_BY_SUN = [
    (-18.0, 6.5), (-15.0, 5.8), (-12.0, 4.6), (-9.0, 3.2), (-6.0, 1.6),
    (-3.0, -0.4), (0.0, -2.4), (5.0, -3.9), (90.0, -4.4),
]

View = namedtuple("View", "az alt fov figures culture", defaults=(None,))
View.__doc__ = """Where the view looks: azimuth and altitude of its centre
in degrees, the field of view across the screen in degrees, how much of
the constellations to draw (0 nothing, 1 the figures, 2 the figures and
their names), and the sky culture whose constellations and star names
those are, or None for the IAU sky."""

FOV_MIN, FOV_MAX, FOV_DEFAULT = 6.0, 236.0, 110.0
FIGURES_DEFAULT = 2


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------
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


def project(v, f, cx, cy, aspect=1.0):
    """A camera-frame unit vector to (x, y) in sub-pixels, y down, or
    None when it is too far behind the viewer to place.

    *f* is sub-pixels per plane unit across; *aspect* is a sub-pixel's
    height in cell widths (1.0 on the 2:1 cell that makes a half-block's
    two sub-pixels square), so the same plane unit spans f/aspect
    sub-pixels down and the picture is round on the screen rather than
    on the grid.  Every hand-inlined copy of this arithmetic in
    sky/view.py scales y the same way."""
    x, y, z = v
    if z < -0.82:
        return None
    k = 2.0 * f / (1.0 + z)
    return cx + x * k, cy - y * k / aspect


def unproject(px, py, f, cx, cy, aspect=1.0):
    """The camera-frame unit vector a sub-pixel looks along."""
    u = (px - cx) / (2.0 * f)
    v = (cy - py) * aspect / (2.0 * f)
    rho2 = u * u + v * v
    d = 1.0 + rho2
    return (2.0 * u / d, 2.0 * v / d, (1.0 - rho2) / d)


def alt_az_of(v):
    """Altitude and azimuth, degrees, of an observer-frame unit vector."""
    e, n, u = v
    return (math.degrees(math.asin(max(-1.0, min(1.0, u)))),
            math.degrees(math.atan2(e, n)) % 360.0)


# The Hawaiian star compass, Nainoa Thompson's: the horizon in thirty-two
# houses of 11.25°, each point the centre of the house of its name. Four
# cardinal houses — ʻĀkau north, Hikina east, Hema south, Komohana west —
# and, in each quadrant, seven houses named alike from the east or west
# point toward the pole: Lā, ʻĀina, Noio, Manu, Nālani, Nāleo, Haka.
# The quadrants are the winds: Koʻolau northeast, Malanai southeast, Kona
# southwest, Hoʻolua northwest. A star rises in a house and sets in the
# house of the same name on the other side. (Polynesian Voyaging
# Society, hokulea.com, "The Star Compass".)
_STAR_COMPASS_HOUSES = ("Lā", "ʻĀina", "Noio", "Manu", "Nālani", "Nāleo", "Haka")
_STAR_COMPASS_CARDINALS = {0.0: "ʻĀkau", 90.0: "Hikina", 180.0: "Hema", 270.0: "Komohana"}
_STAR_COMPASS_QUADRANTS = ((90.0, -1.0, "Koʻolau"), (90.0, 1.0, "Malanai"),
                           (270.0, -1.0, "Kona"), (270.0, 1.0, "Hoʻolua"))


def star_compass():
    """The thirty-two houses as (azimuth, house, quadrant or "", cardinal)."""
    houses = [(az, name, "", True) for az, name in _STAR_COMPASS_CARDINALS.items()]
    for start, direction, quadrant in _STAR_COMPASS_QUADRANTS:
        for k, name in enumerate(_STAR_COMPASS_HOUSES, 1):
            houses.append(((start + direction * 11.25 * k) % 360.0, name, quadrant, False))
    return sorted(houses)


def compass_marks(runtime, culture=None):
    """What to write along the horizon: (azimuth, label, bold) for the
    eight compass points, or for the Hawaiian culture's star compass."""
    if culture == "hawaiian":
        return [(az, name, cardinal) for az, name, _q, cardinal in star_compass()]
    return [(i * 45.0, label, i % 2 == 0)
            for i, label in enumerate(rs("compass", lang_of(runtime)).split())]


def compass_point(az_deg, runtime, culture=None, quadrant=False):
    """The direction as words: the eight-point abbreviation in the display
    language, or with the Hawaiian culture the house of the star compass,
    with its quadrant when *quadrant* is asked for ("Manu Koʻolau")."""
    if culture == "hawaiian":
        az, name, quad, _cardinal = min(star_compass(),
                                        key=lambda h: abs(angle_delta(h[0], az_deg)))
        return f"{name} {quad}" if quadrant and quad else name
    return _eight_point(az_deg, lang_of(runtime))


def compass_points(runtime):
    return rs("compass", lang_of(runtime)).split()


# ---------------------------------------------------------------------------
# The moment's sky
# ---------------------------------------------------------------------------
class Scene:
    """Where everything is at one moment, for one observer.

    Built once per frame and handed to the drawing passes: the two frame
    matrices, the Sun, the Moon and the planets as observer-frame vectors
    with their altitudes and azimuths, and the limiting magnitude the
    sky's brightness allows.

    `horizontal` turns the equinox of date to the observer's frame, for
    the Sun, the Moon and the planets, which are computed there.
    `catalogue` turns the bundled J2000 sky to the same place, precession
    folded in, for the stars, the figures, the Milky Way and the Messier
    objects. Anything drawn from the catalogue goes through `catalogue`,
    or it lands a third of a degree off the bodies beside it.
    """

    def __init__(self, moment_utc, lat, lng):
        self.moment_utc = moment_utc
        self.lat, self.lng = lat, lng
        lst = (_gmst_deg(moment_utc) + lng) % 360.0
        self.horizontal = horizontal_matrix(lst, lat)
        self.catalogue = mat_mul(self.horizontal, precession_at(moment_utc))

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
        """Whether the shown moment is before local solar noon: the Sun
        is in the east half of the sky, north or south of the equator."""
        return self.sun_az < 180.0


def _interp(stops, value):
    """Linear interpolation through [(x, y), …] stops, clamped at the ends."""
    if value <= stops[0][0]:
        return stops[0][1]
    for (x0, y0), (x1, y1) in zip(stops, stops[1:]):
        if value <= x1:
            return y0 + (y1 - y0) * (value - x0) / (x1 - x0)
    return stops[-1][1]


def extinction(alt_deg):
    """Magnitudes lost to the air at an altitude: nothing overhead, a
    magnitude or two near the horizon (Rozenberg's airmass)."""
    if alt_deg <= 0.0:
        return 3.0
    s = math.sin(math.radians(alt_deg))
    airmass = 1.0 / (s + 0.025 * math.exp(-11.0 * s))
    return min(3.0, 0.25 * (airmass - 1.0))


def easily_seen(mag, alt, scene):
    """Whether a planet of this magnitude at this altitude is plainly
    visible under the sky as it is: a magnitude inside the eye's limit,
    so the list of what is up names the five classical planets and never
    Uranus, which the chart still draws when the zoom allows."""
    return mag + extinction(alt) <= scene.eye_limit - 1.0


# ---------------------------------------------------------------------------
# Choosing where to look
# ---------------------------------------------------------------------------
def default_view(scene, cols, rows, facing=None, fov=FOV_DEFAULT, aim=None):
    """Where to look first: the thing `aim` names as (alt, az) if given,
    else the Moon if it is up, else the brightest planet up in a dark
    sky, else south (north below the equator), with the horizon just
    above the bottom of the screen."""
    graph_w, graph_h = max(20, cols), max(6, rows - 3)
    f = focal_length(graph_w, fov)
    # The altitude at the top and bottom edges, looking level: graph_h
    # sub-pixels up from the centre, each cell_aspect/2 cell widths tall.
    half_v = math.degrees(2.0 * math.atan(graph_h * cell_aspect() / 2.0 / (2.0 * f)))
    alt = max(8.0, min(45.0, half_v - 7.0))
    target_alt = None
    if aim is not None:
        target_alt, az = aim
        if target_alt < alt:
            alt = max(8.0, target_alt + half_v * 0.3)
    elif facing is not None:
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
