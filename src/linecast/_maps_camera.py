"""One orthographic camera from the planet to the street.

Coordinates passed to project/unproject are grid edges: pixel (x, y) is
sampled at (x + .5, y + .5). The terminal's cell aspect belongs to the
camera, so fills, braille, labels and pointer probes share one geography.
"""

from dataclasses import dataclass, replace
from functools import cached_property
import math

from linecast._geo import wrap_lon


@dataclass(frozen=True)
class MapCamera:
    lat: float
    lon: float
    zoom: float
    gw: int
    hc: int

    def __post_init__(self):
        if not all(math.isfinite(v) for v in (self.lat, self.lon, self.zoom)):
            raise ValueError("camera coordinates and zoom must be finite")
        if not -90 <= self.lat <= 90 or self.zoom <= 0 or self.gw <= 0 or self.hc <= 0:
            raise ValueError("camera latitude, zoom or dimensions out of range")
        # A suspended foreground spinner can advance more than one turn;
        # preserve already-canonical floats for stable exact camera keys.
        lon = self.lon
        if not -180 <= lon <= 180:
            lon = (lon + 180) % 360 - 180
        object.__setattr__(self, "lon", lon)

    @cached_property
    def key(self):
        # Street movement is much finer than the old globe's 2 dp keys.
        return (self.lat, self.lon, self.zoom, self.gw, self.hc)

    @cached_property
    def _trig(self):
        phi = math.radians(self.lat)
        return math.sin(phi), math.cos(phi)

    def _vector(self, lon, lat):
        phi, delta = math.radians(lat), math.radians(lon - self.lon)
        sp, cp = math.sin(phi), math.cos(phi)
        sd, cd = math.sin(delta), math.cos(delta)
        s0, c0 = self._trig
        return cp * sd, c0 * sp - s0 * cp * cd, s0 * sp + c0 * cp * cd

    def visible(self, lon, lat):
        return self._vector(lon, lat)[2] > 0.0

    def project(self, lon, lat, w, h):
        """Lon/lat to grid edges; use visible() to reject the far hemisphere."""
        u, v, _z = self._vector(lon, lat)
        scale = 180.0 / math.pi / self.zoom
        return (w / 2 + u * scale * (2 * self.hc / self.gw) * w,
                h / 2 - v * scale * h)

    def _ray(self, x, y, w, h):
        scale = math.radians(self.zoom)
        u = (x / w - 0.5) * scale * self.gw / (2 * self.hc)
        v = (0.5 - y / h) * scale
        rho2 = u * u + v * v
        if rho2 > 1.0:
            return None
        return u, v, math.sqrt(max(0.0, 1.0 - rho2))

    def unproject(self, x, y, w, h):
        """Grid edges to (latitude, longitude), or None outside the disk."""
        ray = self._ray(x, y, w, h)
        if ray is None:
            return None
        u, v, z = ray
        s0, c0 = self._trig
        north = v * c0 + z * s0
        equator = z * c0 - v * s0
        # atan2 remains well-conditioned near a pole, unlike asin(north).
        lat = math.degrees(math.atan2(north, math.hypot(u, equator)))
        lon = wrap_lon(self.lon + math.degrees(math.atan2(u, equator)))
        return lat, lon

    def lls(self, w, h):
        """Lat/lon at each sample centre, including None in space."""
        return [[self.unproject(x + 0.5, y + 0.5, w, h)
                 for x in range(w)] for y in range(h)]

    @cached_property
    def _cap(self):
        # A spherical cap enclosing the viewport is conservative even when
        # extrema fall between its corners. It also covers a visible limb.
        rho = math.radians(self.zoom) * math.hypot(
            self.gw / (4 * self.hc), 0.5)
        return math.asin(min(1.0, rho))

    @cached_property
    def bounds(self):
        """Conservative source bounds, longitude unwrapped around the centre."""
        arc = math.degrees(self._cap)
        minlat, maxlat = max(-90.0, self.lat - arc), min(90.0, self.lat + arc)
        if abs(self.lat) + arc >= 90.0:
            half_lon = 180.0
        else:
            half_lon = math.degrees(math.asin(min(
                1.0, math.sin(self._cap) / self._trig[1])))
        return self.lon - half_lon, minlat, self.lon + half_lon, maxlat

    @cached_property
    def local_tiles(self):
        """Whether local tile polygons are safely inside a front-facing cap.

        Coarse world data remains available outside this region, under the
        same camera. Local sources must not be stretched across a limb or
        beyond their Mercator coverage.
        """
        # The vector source looks two tile levels beyond screen detail.
        # Requiring at least z1 screen detail keeps its z3-or-finer tile
        # footprints, including buffers, away from the far hemisphere.
        # This matters on very small terminals near the Mercator limit.
        mercator_degrees_per_dot = self.zoom / (self.hc * 4) / max(1e-12, self._trig[1])
        return (self._cap <= math.radians(15.0)
                and mercator_degrees_per_dot <= 360.0 / (256 * 2)
                and self.bounds[1] > -85.05 and self.bounds[3] < 85.05)

    @cached_property
    def scale_bbox(self):
        """The former centre-scale bbox, for detail and hillshade only."""
        half_lat = self.zoom / 2
        span = self.zoom * self.gw / (self.hc * 2) / max(1e-12, self._trig[1])
        return (self.lon - span / 2, self.lat - half_lat,
                self.lon + span / 2, self.lat + half_lat)

    def _place(self, lat, lon, col, row):
        """A north-up camera placing a geographic anchor at a cell position."""
        ray = self._ray(col, row, self.gw, self.hc)
        if ray is None:
            return self
        u, v, z = ray
        length = math.hypot(v, z)
        target = math.sin(math.radians(lat))
        if length < 1e-12 or abs(target) > length + 1e-12:
            return self  # no north-up solution at this screen position
        angle = math.asin(max(-1.0, min(1.0, target / length)))
        offset = math.atan2(v, z)
        candidates = [phi for phi in (angle - offset, math.pi - angle - offset,
                                     -math.pi - angle - offset)
                      if -math.pi / 2 <= phi <= math.pi / 2]
        if not candidates:
            return self
        phi = min(candidates, key=lambda p: abs(p - math.radians(self.lat)))
        delta = math.atan2(u, z * math.cos(phi) - v * math.sin(phi))
        return replace(self, lat=math.degrees(phi), lon=lon - math.degrees(delta))

    def pan(self, dcol, drow):
        """Move the centre over the sphere, including drags past the disk.

        Inside the disk this picks the old surface at centre minus the
        displacement. Beyond the limb the same great-circle direction
        continues, so a large gesture never freezes or snaps backwards.
        A centre motion also remains possible where exact north-up
        placement of an arbitrary screen anchor would not.
        """
        if not (dcol or drow):
            return self
        scale = math.radians(self.zoom)
        u, v = -dcol * scale / (2 * self.hc), drow * scale / self.hc
        rho = math.hypot(u, v)
        arc = math.asin(rho) if rho <= 1 else math.pi / 2 + rho - 1
        factor = math.sin(arc) / rho
        u, v, z = u * factor, v * factor, math.cos(arc)
        s0, c0 = self._trig
        north, equator = v * c0 + z * s0, z * c0 - v * s0
        lat = math.degrees(math.atan2(north, math.hypot(u, equator)))
        lon = self.lon + math.degrees(math.atan2(u, equator))
        return replace(self, lat=lat, lon=lon)

    def zoom_at(self, new_zoom, col=None, row=None):
        """Change scale while holding the geographic point under the pointer."""
        if new_zoom == self.zoom:
            return self
        camera = replace(self, zoom=new_zoom)
        if col is None or row is None:
            return camera
        anchor = self.unproject(col, row, self.gw, self.hc)
        if anchor is None:
            return camera
        return camera._place(*anchor, col, row)
