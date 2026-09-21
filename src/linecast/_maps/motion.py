"""The arithmetic of a map in motion: easing, and the flight path.

The camera in live is the thing that moves; this is what it moves
along.  Two ideas and no state.

`ease_in_out` is the shape every short motion takes — a zoom step, a
keyboard pan — so that a step starts and ends at rest and the eye is
never handed a jolt.  `Flight` is the long one: van Wijk and Nuij's
path, which answers the question a jump cannot.  Sliding straight from
London to Tokyo at street zoom is a smear of unreadable ground; cutting
there is a reader lost.  Rising until both ends are in frame, crossing,
and descending is what a person would do with a map on a table, and the
paper it is drawn on appears to move at one steady speed throughout.

Both work in the map's own units: `zoom` is degrees of latitude top to
bottom, the same number everywhere else in maps, and a distance is
degrees along the ground.  Nothing here reads the clock — the caller
says how far in it is — so a test can walk a flight a step at a time.
"""

import math

from linecast._radar_render import bbox_for

RHO = 1.42          # van Wijk's trade-off between zooming and panning
SPEED = 3.0         # path units per second
FLIGHT_MIN = 0.45   # seconds, so a short hop still reads as motion
FLIGHT_MAX = 2.8    # seconds, so a long one does not outstay itself


def ease_in_out(s):
    """Smoothstep: 0 at 0, 1 at 1, and flat at both ends."""
    return s * s * (3.0 - 2.0 * s)


def lon_delta(a, b):
    """The signed shortest turn from longitude a to b, in (-180, 180].

    Every longitude the camera interpolates goes through here, so a
    pan from 170 to -170 crosses the antimeridian rather than taking
    the long way round the planet.
    """
    return (b - a + 180.0) % 360.0 - 180.0


def lon_span(lat, zoom, gw, hc):
    """Degrees of longitude a gw by hc map shows at this centre and zoom.

    Asked of bbox_for itself rather than rederived: the width of the
    window depends on the terminal's cell shape, and a camera that
    assumed a 2:1 cell would move the ground a different distance than
    the renderer draws it — the map would slide out from under the
    hand on any font that is not exactly twice as tall as it is wide.
    """
    minlon, _minlat, maxlon, _maxlat = bbox_for(lat, 0.0, zoom, gw, hc)
    return maxlon - minlon


class Flight:
    """A smooth flight from one view to another.

    Van Wijk and Nuij, "Smooth and efficient zooming and panning"
    (2003): the camera rises just high enough to see both ends, crosses,
    and descends, along the path on which the picture appears to move
    at a constant speed.  `w` is the visible height in degrees (the
    zoom), `u` the distance along the ground in the same units.

    The duration is the path's own length at a fixed speed, bounded at
    both ends: a hop across town still takes long enough to read as
    motion, and a hop across the planet still ends before the reader
    wonders whether the key worked.
    """
    __slots__ = ("lat0", "lon0", "w0", "lat1", "lon1", "w1", "u1", "r0",
                 "S", "k", "duration")

    def __init__(self, lat0, lon0, w0, lat1, lon1, w1, speed=SPEED):
        self.lat0, self.lon0, self.w0 = lat0, lon0, w0
        self.lat1, self.lon1, self.w1 = lat1, lon1, w1
        dlat = lat1 - lat0
        dlon = lon_delta(lon0, lon1) * math.cos(math.radians((lat0 + lat1) / 2))
        self.u1 = math.hypot(dlat, dlon)
        rho = RHO
        if self.u1 < 1e-6:
            # a pure zoom: exponential in the height
            self.k = 1.0 if w1 > w0 else -1.0
            self.r0 = None
            self.S = abs(math.log(w1 / w0)) / rho
        else:
            u1 = self.u1
            b0 = (w1 * w1 - w0 * w0 + rho ** 4 * u1 * u1) / (2 * w0 * rho * rho * u1)
            b1 = (w1 * w1 - w0 * w0 - rho ** 4 * u1 * u1) / (2 * w1 * rho * rho * u1)
            r0 = math.log(-b0 + math.sqrt(b0 * b0 + 1.0))
            r1 = math.log(-b1 + math.sqrt(b1 * b1 + 1.0))
            self.r0 = r0
            self.k = None
            self.S = (r1 - r0) / rho
        self.duration = max(FLIGHT_MIN, min(FLIGHT_MAX, self.S / speed))

    def at(self, t):
        """(lat, lon, zoom) `t` seconds in; the end past the duration.

        Exactly the end, not a value that rounds to it: the view the
        flight lands on is the one that reaches the network, and a
        last hundredth of a degree would be a second fetch.
        """
        if t >= self.duration:
            return self.lat1, self.lon1, self.w1
        s = max(0.0, t / self.duration) * self.S
        rho = RHO
        if self.r0 is None:
            frac = 0.0
            w = self.w0 * math.exp(self.k * rho * s)
        else:
            r0 = self.r0
            u = (self.w0 / (rho * rho) * math.cosh(r0) * math.tanh(rho * s + r0)
                 - self.w0 / (rho * rho) * math.sinh(r0))
            w = self.w0 * math.cosh(r0) / math.cosh(rho * s + r0)
            frac = max(0.0, min(1.0, u / self.u1))
        lat = self.lat0 + (self.lat1 - self.lat0) * frac
        lon = self.lon0 + lon_delta(self.lon0, self.lon1) * frac
        return lat, (lon + 180.0) % 360.0 - 180.0, w
