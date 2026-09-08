"""Clock-based map motion, separate from input targets and detail replies."""

from dataclasses import replace
import math
import time

from linecast._geo import wrap_lon


COAST_HALF_LIFE = 0.18   # seconds for release speed to halve
# Speed is measured in shorter viewport dimensions per second. A terminal
# row is two physical pixels, so that dimension is min(columns, 2 * rows).
# This keeps the travel bounded even when a narrow view fits a small globe.
COAST_FLOOR = 0.03
COAST_CEILING = 1.0


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
        self._coast = None    # (duration, fraction of launch speed lost)

    def sample(self, now=None):
        if self._start is None:
            return self.target
        now = time.monotonic() if now is None else now
        if now <= self._start:
            return self._from
        # Compare the deadline directly: subtracting two clock readings can
        # round the elapsed duration down and leave a finished motion active.
        duration = self.duration if self._coast is None else self._coast[0]
        if now >= self._start + duration:
            self._start = None
            self._coast = None
            return self.target
        if self._coast is None:
            s = (now - self._start) / duration
            e = s * s * (3.0 - 2.0 * s)
        else:
            # Integrated exponential speed, measured from release rather
            # than the previous frame so skipped frames do not alter travel.
            elapsed = (now - self._start) / COAST_HALF_LIFE
            e = -math.expm1(-math.log(2.0) * elapsed) / self._coast[1]
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
        self._coast = None
        self._start = (now if animate and current.key != camera.key else None)

    def coast(self, vcol, vrow, *, now=None):
        """Release with a velocity in terminal cells per second.

        Limit speed relative to the shorter physical viewport dimension,
        min(columns, twice the rows), so the same flick stays restrained at
        street and globe scales. Fix its destination once; only the display
        advances along the short surface path while detail catches up.
        """
        now = time.monotonic() if now is None else now
        current = self.cancel(now)
        speed = math.hypot(vcol, 2 * vrow) / min(current.gw, 2 * current.hc)
        if not math.isfinite(speed) or speed <= COAST_FLOOR:
            return False
        if speed > COAST_CEILING:
            scale = COAST_CEILING / speed
            vcol, vrow = vcol * scale, vrow * scale
            speed = COAST_CEILING
        lost = 1.0 - COAST_FLOOR / speed
        travel = COAST_HALF_LIFE / math.log(2.0) * lost
        target = current.pan(vcol * travel, vrow * travel)
        if target.key == current.key:
            return False
        self.target = target
        self._start = now
        self._coast = (COAST_HALF_LIFE * math.log2(speed / COAST_FLOOR), lost)
        return True

    def cancel(self, now=None):
        """Freeze the displayed camera, with no remaining ease or coast."""
        current = self.sample(now)
        self.target = self._from = current
        self._start = self._anchor = self._coast = None
        return current

    @property
    def moving(self):
        return self._start is not None

    @property
    def coasting(self):
        """Whether release inertia is active, independently of other easing."""
        return self._coast is not None
