"""Complete world surface colours for motion, prepared by the scene worker.

One fixed geographic resolution covers every hemisphere and zoom. A moving
view samples surface colour, then shades its own disk and atmosphere; an old
limb never travels into the planet's middle. Exact detail stays separate.
"""

from dataclasses import dataclass, field
import math

from linecast import _climate, _globe, _globe_now, _maps_paint, _maps_style, _night_lights, _theme
from linecast._color import color_mode
from linecast._radar_basemap import Basemap, DotLayer, _load_data
from linecast._scenes import Memo


_textures = Memo(keep=2)
_clouds = Memo(keep=1)
_SIZE = (720, 360)


def _lls(w, h):
    return [[(90.0 - (y + .5) * 180.0 / h, (x + .5) * 360.0 / w - 180.0)
             for x in range(w)] for y in range(h)]


def _halo(rows):
    """Periodic longitude and the opposite meridian beyond either pole."""
    if rows is None:
        return None
    half = len(rows[0]) // 2
    north = list(rows[0][half:]) + list(rows[0][:half])
    south = list(rows[-1][half:]) + list(rows[-1][:half])
    return [[row[-1], *row, row[0]] for row in [north, *rows, south]]


def _lake_mask(w, h):
    # Reuse the basemap's scanline fill, without its source loading or disk
    # cache. DotLayer only allocates a projection and its empty grids.
    projection = DotLayer((-180.0, -90.0, 180.0, 90.0), w // 2, h // 4)
    water = [bytearray(w) for _ in range(h)]
    Basemap._fill_polys(projection, water, _load_data().get("lakes", ()), 1)
    return water


@dataclass(frozen=True)
class _Texture:
    width: int
    height: int
    rgb: tuple
    north: tuple = field(init=False)
    south: tuple = field(init=False)

    def __post_init__(self):
        # Every longitude meets at a pole. A virtual pole sample avoids
        # stretching a longitude-varying final texel row into a pinwheel.
        for name, row in (("north", self.rgb[0]), ("south", self.rgb[-1])):
            object.__setattr__(self, name, tuple(sum(row[c::3]) / self.width for c in range(3)))

    def sample(self, lls, background, clouds=None):
        """Bilinear colour and cloud samples, periodic at the antimeridian."""
        w, h, rgb = self.width, self.height, self.rgb
        cloud_poles = ((sum(clouds[0]) / w, sum(clouds[-1]) / w)
                       if clouds is not None else (0, 0))
        fills, opacity = [], [] if clouds is not None else None
        for points in lls:
            row, cloud_row = [], []
            for ll in points:
                if ll is None:
                    row.append(background)
                    if opacity is not None:
                        cloud_row.append(0.0)
                    continue
                lat, lon = ll
                fx = (lon + 180.0) % 360.0 / 360.0 * w - .5
                ix = math.floor(fx)
                x0, x1, tx = ix % w, (ix + 1) % w, fx - ix
                fy = (90.0 - lat) / 180.0 * h - .5
                cap = 0.0
                if fy < 0:
                    cap, fy, pole, cloud_pole = min(1.0, -2 * fy), 0.0, self.north, cloud_poles[0]
                elif fy > h - 1:
                    cap, fy = min(1.0, 2 * (fy - h + 1)), h - 1.0
                    pole, cloud_pole = self.south, cloud_poles[1]
                y0 = int(fy)
                y1, ty = min(h - 1, y0 + 1), fy - y0
                a, b = rgb[y0], rgb[y1]
                j, k = x0 * 3, x1 * 3
                red = ((a[j] + (a[k] - a[j]) * tx) * (1 - ty)
                       + (b[j] + (b[k] - b[j]) * tx) * ty)
                green = ((a[j + 1] + (a[k + 1] - a[j + 1]) * tx) * (1 - ty)
                         + (b[j + 1] + (b[k + 1] - b[j + 1]) * tx) * ty)
                blue = ((a[j + 2] + (a[k + 2] - a[j + 2]) * tx) * (1 - ty)
                        + (b[j + 2] + (b[k + 2] - b[j + 2]) * tx) * ty)
                if cap:
                    red += (pole[0] - red) * cap
                    green += (pole[1] - green) * cap
                    blue += (pole[2] - blue) * cap
                row.append((int(red + .5), int(green + .5), int(blue + .5)))
                if opacity is not None:
                    a, b = clouds[y0], clouds[y1]
                    alpha = ((a[x0] + (a[x1] - a[x0]) * tx) * (1 - ty)
                             + (b[x0] + (b[x1] - b[x0]) * tx) * ty)
                    if cap:
                        alpha += (cloud_pole - alpha) * cap
                    cloud_row.append(alpha / 255.0)
            fills.append(row)
            if opacity is not None:
                opacity.append(cloud_row)
        return fills, opacity


def _build_texture(w, h, street):
    points = _lls(w, h)
    # 720x360 selects the bundled z2 world canvas. Its padded storage width
    # is not a longitude period; elevation() samples world coordinates
    # before this compact periodic texture.
    elev = _globe.elevation(points, 180.0, h * 2)
    water = _lake_mask(w, h)
    bg = _maps_paint.BG_PRIMARY
    if street:
        palette = _maps_style.palette()
        colors = _globe.fill_buffer(elev, palette.get("water"), palette.get("ground"), bg, water)
    else:
        cover = _globe.ice_cover(points, elev, _maps_style.COVER_ORDER.index("ice") + 1)
        climate = _climate.grid_for_lls(points)
        dx, dy = 360.0 / w, 180.0 / h
        metres = [(dx * 111320.0 * abs(math.cos(math.radians(90.0 - (y - .5) * dy))),
                   dy * 110540.0) for y in range(h + 2)]
        padded = _maps_paint.build_terrain_buffer(
            _halo(elev), (-180 - dx, -90 - dy, 180 + dx, 90 + dy), w + 2, h + 2,
            water=_halo(water), cover=_halo(cover),
            climate=_halo(climate) if climate else (), pixel_meters=metres)
        colors = [row[1:-1] for row in padded[1:-1]]
    return _Texture(w, h, tuple(bytes(c for pixel in row for c in pixel) for row in colors))


def _cloud_texture(w, h):
    # Publication updates canvas, polar metadata and revision together. The
    # worker snapshots their result while holding the publication lock; later
    # frames only read the immutable alpha rows, never the source or noise.
    with _globe_now._cloud_lock:
        canvas = _globe_now.peek()
        if canvas is None:
            return None

        def build():
            rows = _globe_now.clouds(_lls(w, h), canvas)
            return tuple(bytes(max(0, min(255, round(a * 255))) for a in row) for row in rows)

        return _clouds.get((id(canvas), _globe_now.revision(), w, h), build)


@dataclass(frozen=True)
class GlobeSurface:
    texture: _Texture
    sun: tuple | None
    clouds: tuple | None
    lights: tuple
    background: tuple
    night: tuple

    def render(self, camera):
        """Paint any hemisphere using prepared data and pure arithmetic."""
        gw, h = camera.gw, camera.hc * 2
        lls, zs, rhos = _globe.geometry(camera.lat, camera.lon, camera.zoom, gw, h)
        fills, clouds = self.texture.sample(lls, self.background, self.clouds)
        atmo = _globe.atmosphere(rhos, camera.zoom, h)
        _globe.shade_buffer(fills, zs, atmo, self.background)
        if self.sun is not None or clouds is not None:
            day = _globe_now.daylight(lls, self.sun) if self.sun is not None else None
            lights = (_night_lights.sample(self.lights, lls, camera.zoom / h, zs)
                      if self.sun is not None else {})
            _globe_now.apply(fills, day, clouds, lights, self.night)
            if self.sun is not None:
                limb = _globe.limb_lls(camera.lat, camera.lon, camera.zoom, gw, h, atmo)
                _globe.gate_glow(fills, atmo, _globe_now.daylight(limb, self.sun), self.background)
        return fills


def prepare_surface(camera, *, street=False, sun=False, clouds=False):
    """Prepare bounded complete-world colour and weather on the caller."""
    w, h = _SIZE
    texture = _textures.get((w, h, street, color_mode(), _theme.generation),
                            lambda: _build_texture(w, h, street))
    lights = _night_lights.load() if sun and not street else ()
    return GlobeSurface(texture, _globe_now.subsolar() if sun else None,
                        _cloud_texture(w, h) if clouds else None, lights,
                        _maps_paint.BG_PRIMARY,
                        _globe_now.NIGHT_STREET if street else _globe_now._NIGHT)
