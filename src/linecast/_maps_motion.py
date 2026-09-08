"""Clock-based map motion, separate from input targets and detail replies."""

from dataclasses import replace
import math
import time

from linecast._geo import wrap_lon


def _centre(a, b, fraction):
    """The short great-circle path, expressed in the starting camera's basis.

    Interpolating latitude/longitude can circle around a pole or follow a
    parallel instead of moving across the surface. atan2 of the tangent
    length remains accurate for both street-sized and near-antipodal moves.
    """
    if a.lat == b.lat and wrap_lon(b.lon - a.lon) == 0:
        return a.lat, a.lon
    u, v, z = a._vector(b.lon, b.lat)
    tangent = math.hypot(u, v)
    angle = math.atan2(tangent, z)
    if tangent < 1e-12 and z < 0:
        # An exact antipode has no unique shortest path. Pick a stable east
        # or west great circle instead of amplifying floating-point noise.
        u = 1.0 if wrap_lon(b.lon - a.lon) >= 0 else -1.0
        v, tangent = 0.0, 1.0
    scale = math.sin(angle * fraction) / tangent if tangent else 0.0
    u, v, z = u * scale, v * scale, math.cos(angle * fraction)
    s0, c0 = a._trig
    north = v * c0 + z * s0
    equator = z * c0 - v * s0
    lat = math.degrees(math.atan2(north, math.hypot(u, equator)))
    lon = a.lon + math.degrees(math.atan2(u, equator))
    return lat, lon


class CameraMotion:
    duration = 0.28

    def __init__(self, camera):
        self.target = camera
        self._from = camera
        self._start = None
        self._anchor = None

    def sample(self, now=None):
        if self._start is None:
            return self.target
        now = time.monotonic() if now is None else now
        if now <= self._start:
            return self._from
        # Compare the deadline directly: subtracting two clock readings can
        # round the elapsed duration down and leave a finished motion active.
        if now >= self._start + self.duration:
            self._start = None
            return self.target
        s = max(0.0, min(1.0, (now - self._start) / self.duration))
        e = s * s * (3.0 - 2.0 * s)
        a, b = self._from, self.target
        zoom = (a.zoom if a.zoom == b.zoom else
                math.exp(math.log(a.zoom) + math.log(b.zoom / a.zoom) * e))
        if self._anchor is not None:
            return a.zoom_at(zoom, *self._anchor)
        lat, lon = _centre(a, b, e)
        return replace(b, lat=lat, lon=lon, zoom=zoom)

    def move(self, camera, *, anchor=None, animate=True, now=None):
        now = time.monotonic() if now is None else now
        current = self.sample(now)
        self.target = camera
        self._from = current
        self._anchor = anchor
        self._start = (now if animate and current.key != camera.key else None)

    @property
    def moving(self):
        return self._start is not None
