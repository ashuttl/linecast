"""Retained map layers that follow the displayed camera between detail frames.

Colors and braille dots are sampled as geometry; text remains terminal text.
Always transform the last prepared detail frame, not the previous preview, to
avoid accumulating raster error. Nothing here starts work or owns camera motion.
"""

from dataclasses import dataclass, field
from functools import cached_property
import math
from operator import itemgetter
from types import MappingProxyType

from linecast._textwidth import visible_len


_BITS = ((0, 0, 1), (0, 1, 2), (0, 2, 4), (0, 3, 64),
         (1, 0, 8), (1, 1, 16), (1, 2, 32), (1, 3, 128))


class _FrozenGrid(tuple):
    """Rows already owned by a snapshot; passing them onward needs no copy."""


def _freeze(value):
    return tuple(value) if isinstance(value, (list, bytearray)) else value


def _rows(grid):
    if grid is None or isinstance(grid, _FrozenGrid):
        return grid
    return _FrozenGrid(tuple(_freeze(value) for value in row) for row in grid)


def _crop(grid, x, y, w, h):
    return (_FrozenGrid(row[x:x + w] for row in grid[y:y + h])
            if grid is not None else None)


def _basis(camera):
    phi, lam = math.radians(camera.lat), math.radians(camera.lon)
    sp, cp, sl, cl = math.sin(phi), math.cos(phi), math.sin(lam), math.cos(lam)
    return ((-sl, cl, 0.0), (-sp * cl, -sp * sl, cp), (cp * cl, cp * sl, sp))


def _radii(camera, w, h):
    # The terminal's fill pixels (gw by 2*hc) are physical squares. Other
    # grids, notably the one-row-per-cell text grid, keep that same aspect.
    radius = 180.0 / math.pi / camera.zoom
    return radius * w * (2.0 * camera.hc / camera.gw), radius * h


class _Warp:
    """Source indices shared by fill, elevation, stroke, and overlay layers."""

    def __init__(self, source, target):
        self.source = source
        self.target = target
        delta_lon = (source.lon - target.lon + 180.0) % 360.0 - 180.0
        self.centered = source.lat == target.lat and abs(delta_lon) < 1e-12
        self._axes = {}
        self._maps = {}
        self.affine = None
        if not self.centered:
            src, dst = _basis(source), _basis(target)
            self.matrix = tuple(tuple(sum(a * b for a, b in zip(s, d)) for d in dst)
                                for s in src)
            self.affine = self._local_affine()

    def _local_affine(self):
        """Separable scale/translation with <.05 dot registration error.

        For target coordinates u,v, the exact source x is
        m00*u + m01*v + m02*sqrt(1-u*u-v*v), and y is analogous.
        Drop the cross-axis term and replace sqrt by 1. Over the entire
        viewport rectangle |u|<=U, |v|<=V, their combined omitted error is
        bounded by |m01|*V + |m02|*(1-sqrt(1-U*U-V*V)). The y bound swaps
        the axes. These are inequalities over every point, not a sparse
        sample test. The threshold applies in both source and target dots.
        """
        source, target = self.source, self.target
        if not (source.local_tiles and target.local_tiles):
            return None
        m0, m1, m2 = self.matrix
        if min(m0[0], m1[1], m2[2]) <= 0:
            return None
        tr_x, tr_y = _radii(target, target.gw * 2, target.hc * 4)
        u, v = target.gw / tr_x, target.hc * 2 / tr_y
        rho2 = u * u + v * v
        if rho2 >= 1:
            return None
        zmin = math.sqrt(1 - rho2)
        if m2[2] * zmin <= abs(m2[0]) * u + abs(m2[1]) * v:
            return None  # some target samples could be behind the source
        # This form avoids losing the curvature term at street-sized angles.
        curve = rho2 / (1 + zmin)
        sr_x, sr_y = _radii(source, source.gw * 2, source.hc * 4)
        dx = (abs(m0[1]) * v + abs(m0[2]) * curve)
        dy = (abs(m1[0]) * u + abs(m1[2]) * curve)
        error = math.hypot(dx * max(sr_x, tr_x / m0[0]),
                           dy * max(sr_y, tr_y / m1[1]))
        if error >= .05:
            return None
        return m0[0], m1[1], m0[2], m1[2]

    def axes(self, sw, sh, w, h):
        key = sw, sh, w, h
        if key not in self._axes:
            sr_x, sr_y = _radii(self.source, sw, sh)
            tr_x, tr_y = _radii(self.target, w, h)
            ax, ay, du, dv = self.affine or (1.0, 1.0, 0.0, 0.0)
            scale_x, scale_y = ax * sr_x / tr_x, ay * sr_y / tr_y
            offset_x, offset_y = sw / 2.0 + du * sr_x, sh / 2.0 - dv * sr_y
            self._axes[key] = (
                tuple(math.floor(offset_x + (x + .5 - w / 2.0) * scale_x)
                      for x in range(w)),
                tuple(math.floor(offset_y + (y + .5 - h / 2.0) * scale_y)
                      for y in range(h)),
            )
        return self._axes[key]

    def mapping(self, sw, sh, w, h):
        key = sw, sh, w, h
        if key in self._maps:
            return self._maps[key]
        sr_x, sr_y = _radii(self.source, sw, sh)
        tr_x, tr_y = _radii(self.target, w, h)
        xs = tuple((x + .5 - w / 2.0) / tr_x for x in range(w))
        x2s = tuple(x * x for x in xs)
        m0, m1, m2 = self.matrix
        background_xs, background_ys = self.axes(sw, sh, w, h)
        rows = []
        for y in range(h):
            v = (h / 2.0 - y - .5) / tr_y
            v2 = v * v
            # Space and atmosphere retain their camera-space radial scale.
            # Only the disk needs a spherical transform, a substantial saving
            # when most of a large terminal is background around the globe.
            sy = background_ys[y]
            row = ([sy * sw + x if 0 <= x < sw else -1 for x in background_xs]
                   if 0 <= sy < sh else [-1] * w)
            if v2 <= 1.0:
                reach = math.sqrt(max(0.0, 1.0 - v2)) * tr_x
                left = max(0, math.ceil(w / 2.0 - reach - .5))
                right = min(w, math.floor(w / 2.0 + reach - .5) + 1)
                r0, r1, r2 = m0[1] * v, m1[1] * v, m2[1] * v
                for x in range(left, right):
                    u = xs[x]
                    z = math.sqrt(max(0.0, 1.0 - v2 - x2s[x]))
                    if m2[0] * u + r2 + m2[2] * z <= 0.0:
                        row[x] = -1  # the retained frame never saw this side
                        continue
                    su = m0[0] * u + r0 + m0[2] * z
                    sv = m1[0] * u + r1 + m1[2] * z
                    sx = math.floor(sw / 2.0 + su * sr_x)
                    sy = math.floor(sh / 2.0 - sv * sr_y)
                    row[x] = sy * sw + sx if 0 <= sx < sw and 0 <= sy < sh else -1
            rows.append(tuple(row))
        result = tuple(rows)
        self._maps[key] = result
        return result

    def sample(self, grid, w, h, empty=None):
        if grid is None:
            return None
        sh, sw = len(grid), len(grid[0])
        if self.centered or self.affine is not None:
            xs, ys = self.axes(sw, sh, w, h)
            outside = any(x < 0 or x >= sw for x in xs)
            get_row = itemgetter(*(x if 0 <= x < sw else sw for x in xs))
            blank = (empty,) * w
            # itemgetter samples a complete row in C; enlarged views also
            # reuse sampled source rows instead of repeating their work.
            sampled = {}
            result = []
            for y in ys:
                if not 0 <= y < sh:
                    result.append(blank)
                    continue
                if y not in sampled:
                    row = grid[y] + (empty,) if outside else grid[y]
                    values = get_row(row)
                    sampled[y] = (values,) if w == 1 else values
                result.append(sampled[y])
            return _FrozenGrid(result)
        # -1 in the mapping is the appended empty sample.
        flattened = tuple(value for row in grid for value in row) + (empty,)
        result = []
        for row in self.mapping(sw, sh, w, h):
            values = itemgetter(*row)(flattened)
            result.append((values,) if w == 1 else values)
        return _FrozenGrid(result)


def _expanded(dots, colors=None):
    h, w = len(dots), len(dots[0])
    result = [[None] * (w * 2) for _ in range(h * 4)]
    for cy, row in enumerate(dots):
        for cx, mask in enumerate(row):
            if not mask:
                continue
            # A one-tuple distinguishes an uncolored dot from an empty sample.
            sample = (colors[cy][cx] if colors is not None else None,)
            for dx, dy, bit in _BITS:
                if mask & bit:
                    result[cy * 4 + dy][cx * 2 + dx] = sample
    return tuple(tuple(row) for row in result)


def _packed(samples, w, h, colored=True):
    dots, colors = [], []
    for cy in range(h):
        r0, r1, r2, r3 = samples[cy * 4:cy * 4 + 4]
        dot_row, color_row = [], []
        for cx in range(w):
            x = cx * 2
            a, b, c, d = r0[x], r1[x], r2[x], r3[x]
            e, f, g, j = r0[x + 1], r1[x + 1], r2[x + 1], r3[x + 1]
            mask = ((a is not None) | ((b is not None) << 1) | ((c is not None) << 2) |
                    ((d is not None) << 6) | ((e is not None) << 3) | ((f is not None) << 4) |
                    ((g is not None) << 5) | ((j is not None) << 7))
            dot_row.append(mask)
            if colored:
                color_row.append(next((s[0] for s in (j, g, f, e, d, c, b, a)
                                       if s is not None and s[0] is not None), None)
                                 if mask else None)
        dots.append(tuple(dot_row))
        if colored:
            colors.append(tuple(color_row))
    return _FrozenGrid(dots), _FrozenGrid(colors) if colored else None


@dataclass(frozen=True)
class _Layer:
    dots: tuple
    color: tuple
    ribbon: frozenset = frozenset()
    hover: object = None

    @classmethod
    def snapshot(cls, layer):
        if layer is None or isinstance(layer, cls):
            return layer
        return cls(_rows(layer.dots), _rows(layer.color),
                   frozenset(getattr(layer, 'ribbon', ())), getattr(layer, 'hover', None))

    @cached_property
    def samples(self):
        return _expanded(self.dots, self.color)

    @cached_property
    def ribbons(self):
        return tuple(tuple((x, y) in self.ribbon for x in range(len(self.dots[0])))
                     for y in range(len(self.dots)))

    def transformed(self, warp, w, h):
        dots, colors = _packed(warp.sample(self.samples, w * 2, h * 4), w, h)
        ribbon = frozenset()
        if self.ribbon:
            ribbon = frozenset((x, y) for y, row in enumerate(warp.sample(self.ribbons, w, h,
                                                                        False))
                               for x, value in enumerate(row) if value)
        return _Layer(dots, colors, ribbon)


def _style(entry):
    return entry[1], bool(len(entry) > 2 and entry[2])


def _label_runs(overlays):
    """Keep each contiguous text run intact, including wide continuation cells."""
    runs = []
    entries = []
    start = row = previous = style = None
    for (col, cy), entry in sorted(overlays.items(), key=lambda item: (item[0][1], item[0][0])):
        continuation = not entry[0]
        if (entries and (cy != row or col != previous + 1 or
                         (not continuation and _style(entry) != style))):
            runs.append((start, row, tuple(entries)))
            entries = []
        if not entries:
            # A detached continuation has no printable character to retain.
            if continuation:
                continue
            start, row, style = col, cy, _style(entry)
        entries.append((col - start, entry))
        previous = col
    if entries:
        runs.append((start, row, tuple(entries)))
    return tuple(runs)


class _CroppedHover:
    """An exact translated viewport onto an existing hover index."""

    def __init__(self, index, dx, dy, w, h, glyphs):
        from linecast._maps_hover import HoverIndex

        self.dx, self.dy, self.w, self.h = dx, dy, w, h
        self.glyphs = frozenset(glyphs)
        if isinstance(index, HoverIndex):
            # Dropped label runs must not intercept queries over the geometry
            # underneath them. Rebuild only the index's text bookkeeping;
            # ownership, features, areas and roads remain shared read-only.
            retained = {(x + dx, y + dy) for x, y in glyphs}
            index = HoverIndex(index.owner, index.feats, index.names,
                               {p: value for p, value in index.marks.items() if p in retained},
                               index.area,
                               texts={p: text for p, text in index.texts.items() if p in retained},
                               shore=index.shore)
        self.index = index

    def at(self, col, row):
        if not (0 <= col < self.w and 0 <= row < self.h):
            return None
        hit = self.index.at(col + self.dx, row + self.dy)
        if hit is None:
            return None
        cells = tuple((x - self.dx, y - self.dy) for x, y in hit.cells
                      if self.dx <= x < self.dx + self.w and self.dy <= y < self.dy + self.h)
        glyphs = tuple((x - self.dx, y - self.dy) for x, y in hit.glyphs
                       if (x - self.dx, y - self.dy) in self.glyphs)
        return hit._replace(cells=cells, glyphs=glyphs)


@dataclass(frozen=True)
class PreparedMap:
    """An immutable prepared camera frame, ready for either map compositor.

    ``overlays`` contains cartographic text only. The caller draws markers and
    interaction chrome fresh after transforming this frame. ``hover`` is coherent
    only for the original camera and is cleared on transformed frames.
    """

    camera: object
    fills: object
    layer: object = None
    coast: object = None
    strokes: tuple = ()
    overlays: object = field(default_factory=dict)
    elev: object = None
    hover: object = None
    street: bool = False
    world: bool = False
    coast_ink: object = None
    ink_dusk: object = None

    def __post_init__(self):
        for name in ('fills', 'coast', 'elev', 'ink_dusk'):
            object.__setattr__(self, name, _rows(getattr(self, name)))
        object.__setattr__(self, 'layer', _Layer.snapshot(self.layer))
        object.__setattr__(self, 'strokes', tuple(_Layer.snapshot(s) for s in self.strokes
                                                if s is not None))
        object.__setattr__(self, 'overlays', MappingProxyType({
            pos: tuple(_freeze(value) for value in entry)
            for pos, entry in self.overlays.items()
        }))
        object.__setattr__(self, 'coast_ink', _freeze(self.coast_ink))

    @cached_property
    def _coast_samples(self):
        return _expanded(self.coast) if self.coast is not None else None

    @cached_property
    def _labels(self):
        return _label_runs(self.overlays)

    def prime(self):
        """Build reusable raster/text indexes before publishing a detail frame."""
        _ = self._coast_samples, self._labels
        for layer in (self.layer, *self.strokes):
            if layer is not None:
                _ = layer.samples
                if layer.ribbon:
                    _ = layer.ribbons
        return self

    def _transformed_labels(self, camera):
        result = {}
        for col, row, entries in self._labels:
            width = max(offset + max(1, visible_len(entry[0])) for offset, entry in entries)
            # Globe labels start with a city dot. Its point, rather than the
            # middle of its name, must stay attached to the geography.
            anchor_offset = .5 if entries[0][1][0] == '•' else width / 2.0
            anchor = self.camera.unproject(col + anchor_offset, row + .5,
                                           self.camera.gw, self.camera.hc)
            if anchor is None:
                continue
            lat, lon = anchor
            if not camera.visible(lon, lat):
                continue
            point = camera.project(lon, lat, camera.gw, camera.hc)
            if point is None:
                continue
            x, y = point
            new_col, new_row = math.floor(x - anchor_offset + .5), math.floor(y)
            if not 0 <= new_row < camera.hc:
                continue
            placed = {}
            for offset, entry in entries:
                if not entry[0]:
                    continue
                cell = new_col + offset
                glyph_width = max(1, visible_len(entry[0]))
                if 0 <= cell and cell + glyph_width <= camera.gw:
                    placed[(cell, new_row)] = entry
                    for extra in range(1, glyph_width):
                        # Match existing wide-cell ownership without scaling
                        # the glyph or leaving a detached continuation behind.
                        continuation = next((e for o, e in entries if o == offset + extra),
                                            ('', entry[1], False))
                        placed[(cell + extra, new_row)] = continuation
            if not any(pos in result for pos in placed):
                result.update(placed)
        return result

    def cropped(self, camera):
        """Crop integer padding at unchanged physical scale, preserving hover.

        Build overscan with larger gw/hc and zoom multiplied by source_hc /
        target_hc. The settled crop then has exactly the same cell and dot
        samples as its padded source; no reprojection or label layout occurs.
        """
        if camera.key == self.camera.key:
            return self
        source = self.camera
        delta_lon = (source.lon - camera.lon + 180.0) % 360.0 - 180.0
        dw, dh = source.gw - camera.gw, source.hc - camera.hc
        if (source.lat != camera.lat or abs(delta_lon) >= 1e-12 or
                not math.isclose(source.hc / source.zoom, camera.hc / camera.zoom,
                                 rel_tol=1e-12) or dw < 0 or dh < 0 or dw % 2 or dh % 2):
            raise ValueError('crop requires the same center, pixel scale, and even source padding')
        dx, dy, w, h = dw // 2, dh // 2, camera.gw, camera.hc
        overlays = {}
        for col, row, entries in self._labels:
            width = max(offset + max(1, visible_len(entry[0])) for offset, entry in entries)
            if dx <= col and col + width <= dx + w and dy <= row < dy + h:
                overlays.update({(col + offset - dx, row - dy): entry
                                 for offset, entry in entries})
        indexes = {}

        def crop_hover(index):
            if index is not None and id(index) not in indexes:
                indexes[id(index)] = _CroppedHover(index, dx, dy, w, h, overlays)
            return indexes.get(id(index))

        def crop_layer(layer):
            if layer is None:
                return None
            ribbon = frozenset((x - dx, y - dy) for x, y in layer.ribbon
                               if dx <= x < dx + w and dy <= y < dy + h)
            return _Layer(_crop(layer.dots, dx, dy, w, h),
                          _crop(layer.color, dx, dy, w, h), ribbon, crop_hover(layer.hover))

        return PreparedMap(
            camera=camera,
            fills=_crop(self.fills, dx, dy * 2, w, h * 2),
            layer=crop_layer(self.layer),
            coast=_crop(self.coast, dx, dy, w, h),
            strokes=tuple(crop_layer(layer) for layer in self.strokes),
            overlays=overlays,
            elev=_crop(self.elev, dx, dy * 2, w, h * 2),
            hover=crop_hover(self.hover),
            street=self.street,
            world=self.world,
            coast_ink=self.coast_ink,
            ink_dusk=_crop(self.ink_dusk, dx, dy, w, h),
        )

    def transformed(self, camera):
        if camera.key == self.camera.key:
            return self
        warp = _Warp(self.camera, camera)
        w, h = camera.gw, camera.hc
        coast = None
        if self.coast is not None:
            coast, _ = _packed(warp.sample(self._coast_samples, w * 2, h * 4), w, h,
                               colored=False)
        return PreparedMap(
            camera=camera,
            fills=warp.sample(self.fills, w, h * 2),
            layer=self.layer.transformed(warp, w, h) if self.layer is not None else None,
            coast=coast,
            strokes=tuple(layer.transformed(warp, w, h) for layer in self.strokes),
            overlays=self._transformed_labels(camera),
            elev=warp.sample(self.elev, w, h * 2),
            hover=None,
            street=self.street,
            world=self.world,
            coast_ink=self.coast_ink,
            ink_dusk=warp.sample(self.ink_dusk, w, h),
        )
