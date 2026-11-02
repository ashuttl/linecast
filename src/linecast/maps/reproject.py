"""One flat window resampled into another, axis by axis.

The stand-in frames of a zoom: while the data for a new window is on
its way, each frame is the last real view re-projected into the window
the camera has reached (`maps.view._reproject_street`,
`_reproject_terrain`).  The view is linear in lon/lat, so each axis maps
on its own (`axis_map`) and a pan, a zoom or any mixture of the two is
two lists of indices rather than a per-cell projection.

Built for the frame budget.  A zoom eases over a quarter of a second at
thirty frames a second, and the composer already takes half of each
frame, so the carriage here is gathers and wide-int arithmetic over the
whole grid rather than a test a dot: a braille grid is unpacked to a
byte a dot once per source view (`terminal.braille.dot_rows`), each
frame samples or carries those bytes with `operator.itemgetter` and the
int operators, and packs them back in one pass (`pack_dots`).  Only the
ink is still placed a cell at a time, and only in the cells that have
any.
"""

from itertools import chain, compress
import math

from linecast.maps import overscan as _overscan
from linecast.terminal.braille import (
    CODE_CELL, CODE_LAST, DOT_BITS, dot_rows, pack_dots)
from linecast.terminal.scenes import Memo

# Below this many lit source cells a layer is carried a dot at a time,
# which visits only the dots there are; above it the whole grid goes
# through the gathers, whose cost is the window's size and not the
# ink's.  The two meet at about a thousand cells of a 160x43 window:
# a coastline or a river net is well under, a town's streets well over.
_SPARSE = 1000

# the four dots of a cell's left column, and of its right
_LEFT = DOT_BITS[0][0] | DOT_BITS[0][1] | DOT_BITS[0][2] | DOT_BITS[0][3]
_RIGHT = DOT_BITS[1][0] | DOT_BITS[1][1] | DOT_BITS[1][2] | DOT_BITS[1][3]


def axis_map(n, lo, span, plo, pspan, sub, flip):
    """For each of n sub-cells along one axis of the new view, which old
    sub-cell sits under its centre, or -1 for none. `flip` counts from
    the top, the way rows run."""
    out = []
    for i in range(n):
        f = (i + 0.5) / n
        v = (lo + span * (1.0 - f)) if flip else (lo + span * f)
        g = ((plo + pspan - v) if flip else (v - plo)) / pspan
        j = int(math.floor(g * sub))
        out.append(j if 0 <= j < sub else -1)
    return out


_getter = _overscan.getter


# The source views' braille grids unpacked to a byte a dot, held by the
# grid they came from: every frame of one zoom ease carries the same
# source, and unpacking it is the one pass of the carriage that touches
# every source dot.  Keyed on identity and holding the grid, so the id
# cannot be reused under the entry; a view that landed replaced every
# grid at once, and the bound is there for that.
_unpacked = {}


def _dots_of(cells, gw, hc):
    """(dot rows, their ints, lit cells) of a braille grid: a byte a dot
    and a trailing blank a row, so index -1 reads as no dot."""
    held = _unpacked.get(id(cells))
    if held is None:
        if len(_unpacked) > 8:
            _unpacked.clear()
        rows = [row + b"\x00" for row in dot_rows(cells, gw, hc)]
        ints = [int.from_bytes(row, "big") for row in rows]
        flat = bytes(chain.from_iterable(cells))
        held = _unpacked[id(cells)] = (cells, rows, ints, len(flat) - flat.count(0))
    return held[1], held[2], held[3]


class Reprojection:
    """One flat window resampled into another, axis by axis.

    Fills sample the old grid under each new sub-cell.  Dots go the
    other way, old to new, when the view grew: sampling a zoom-out
    thins a road to specks, where carrying each dot across keeps the
    line.  Zooming in samples, which keeps it solid.

    The two windows need not be the same size in cells: the source is
    an overscan now, a quarter wider and taller than the frame it was
    asked for, so every map here counts the source's own sub-cells
    rather than assuming the target's.

    The index tables derived from the axis maps are built on first use
    and kept with the object, which `reprojection` keeps between
    frames: a window repainted at rest, waiting for its view, pays for
    them once.
    """
    __slots__ = ("gw", "hc", "pgw", "phc", "cols", "rows", "grow", "xs", "ys",
                 "_fill_get", "_sample_get", "_carry", "_ink_maps", "_dot_maps")

    def __init__(self, gw, hc, pgw, phc, cols, rows, grow, xs, ys):
        self.gw, self.hc = gw, hc
        self.pgw, self.phc = pgw, phc
        self.cols, self.rows = cols, rows
        self.grow = grow      # the new window is the wider one
        self.xs, self.ys = xs, ys   # dot maps, whichever way they run
        self._fill_get = self._sample_get = self._carry = None
        self._ink_maps = self._dot_maps = None

    def fills(self, pfills, ground):
        """The old sub-pixel colour grid under the new one's cells."""
        get = self._fill_get
        if get is None:
            # -1, the ground, reads the blank appended to each source row
            pgw = self.pgw
            get = self._fill_get = _getter([pgw if c < 0 else c for c in self.cols])
        blank = [ground] * self.gw
        out = []
        taken = {}
        for r in self.rows:
            if r < 0:
                out.append(blank[:])
                continue
            row = taken.get(r)
            if row is None:
                row = taken[r] = get([*pfills[r], ground])
            out.append(list(row))
        return out

    def dots(self, pdots, pcolor=None):
        """(dots, color) braille grids carried into the new window.

        `pcolor` is None for a layer that has no ink of its own — the
        coastline, whose colour the composer decides.  A cell's ink is
        that of the last source dot drawn into it, in scan order: the
        new grid's when sampling, the old grid's when carrying.
        """
        gw, hc = self.gw, self.hc
        rows, ints, lit = _dots_of(pdots, self.pgw, self.phc)
        color = [[None] * gw for _ in range(hc)]
        if self.grow and lit <= _SPARSE:
            dots = [[0] * gw for _ in range(hc)]
            self._carry_each(pdots, pcolor, dots, color)
            return dots, color
        if self.grow:
            code = self._carried(rows, ints)
        else:
            code = self._sampled(rows)
        cells = code.translate(CODE_CELL)
        dots = [list(cells[y * gw:(y + 1) * gw]) for y in range(hc)]
        if pcolor is not None:
            if self.grow:
                self._carry_ink(pdots, pcolor, color)
            else:
                self._sample_ink(code, pcolor, color)
        return dots, color

    # -- new dot <- old dot -----------------------------------------------
    def _sampled(self, rows):
        """The window's dots gathered from under each: one gather a dot
        row, and the rows packed in one pass."""
        get = self._sample_get
        if get is None:
            pdw = self.pgw * 2
            get = self._sample_get = _getter([pdw if ox < 0 else ox for ox in self.xs])
        zero = bytes(self.gw * 2)
        taken = {}
        out = []
        for oy in self.ys:
            if oy < 0:
                out.append(zero)
                continue
            row = taken.get(oy)
            if row is None:
                row = taken[oy] = bytes(get(rows[oy]))
            out.append(row)
        return pack_dots(out, self.gw, self.hc)

    def _sample_ink(self, code, pcolor, color):
        """Each lit cell takes the ink under its last set dot."""
        gw = self.gw
        xs, ys = self.xs, self.ys
        last = code.translate(CODE_LAST)
        for i in compress(range(len(last)), last):
            k = last[i] - 1
            cy, cx = divmod(i, gw)
            oy = ys[cy * 4 + (k >> 1)]
            ox = xs[cx * 2 + (k & 1)]
            color[cy][cx] = pcolor[oy >> 2][ox >> 1]

    # -- old dot -> new dot -----------------------------------------------
    def _carry_maps(self):
        """The forward maps inverted: for each new dot row the old rows
        that land in it, and gathers taking the j-th old column landing
        in each new one, for as many as any new column gets."""
        maps = self._carry
        if maps is None:
            dw, dh = self.gw * 2, self.hc * 4
            pdw = self.pgw * 2
            yr = [[] for _ in range(dh)]
            for oy, ny in enumerate(self.ys):
                if ny >= 0:
                    yr[ny].append(oy)
            xr = [[] for _ in range(dw)]
            for ox, nx in enumerate(self.xs):
                if nx >= 0:
                    xr[nx].append(ox)
            deep = max(map(len, xr), default=0)
            gets = [_getter([r[j] if len(r) > j else pdw for r in xr])
                    for j in range(deep)]
            maps = self._carry = (yr, gets)
        return maps

    def _carried(self, rows, ints):
        """Every old dot carried into the new grid: the old rows landing
        in a new one or-ed as ints, then gathered into its columns."""
        yr, gets = self._carry_maps()
        pdw1 = self.pgw * 2 + 1
        dw = self.gw * 2
        zero = bytes(dw)
        out = []
        for olds in yr:
            acc = 0
            for oy in olds:
                acc |= ints[oy]
            if not acc:
                out.append(zero)
                continue
            src = acc.to_bytes(pdw1, "big")
            acc = 0
            for get in gets:
                acc |= int.from_bytes(bytes(get(src)), "big")
            out.append(acc.to_bytes(dw, "big"))
        return pack_dots(out, self.gw, self.hc)

    def _carry_each(self, pdots, pcolor, dots, color):
        """A sparse layer carried a dot at a time, in scan order: each
        old dot's new cell and bit are table lookups, and only the old
        cells with ink in them are visited at all."""
        maps = self._dot_maps
        if maps is None:
            xt = [None if nx < 0 else (nx >> 1, nx & 1) for nx in self.xs]
            yt = [None if ny < 0 else (ny >> 2, ny & 3) for ny in self.ys]
            maps = self._dot_maps = (xt, yt)
        xt, yt = maps
        pgw = self.pgw
        for cyo in range(self.phc):
            ys = yt[cyo * 4:cyo * 4 + 4]
            if ys == [None, None, None, None]:
                continue
            prow = pdots[cyo]
            pcrow = pcolor[cyo] if pcolor is not None else None
            for cxo in compress(range(pgw), prow):
                bits = prow[cxo]
                for sx in (0, 1):
                    at = xt[cxo * 2 + sx]
                    if at is None:
                        continue
                    ncx, nsx = at
                    for sy in range(4):
                        if not bits & DOT_BITS[sx][sy]:
                            continue
                        at = ys[sy]
                        if at is None:
                            continue
                        ncy, nsy = at
                        dots[ncy][ncx] |= DOT_BITS[nsx][nsy]
                        if pcrow is not None:
                            color[ncy][ncx] = pcrow[cxo]

    def _carry_ink(self, pdots, pcolor, color):
        """Each old cell's ink written into the new cells its dots land
        in, old cell by old cell in scan order, so the last wins as it
        did when every dot wrote its own.  Most old cells land whole
        in one new cell, and those write once without reading a bit."""
        maps = self._ink_maps
        if maps is None:
            xs, ys = self.xs, self.ys
            ncx = [(xs[2 * c] >> 1 if xs[2 * c] >= 0 else -1,
                    xs[2 * c + 1] >> 1 if xs[2 * c + 1] >= 0 else -1)
                   for c in range(self.pgw)]
            ncy = [tuple(ys[4 * r + s] >> 2 if ys[4 * r + s] >= 0 else -1
                         for s in range(4))
                   for r in range(self.phc)]
            maps = self._ink_maps = (ncx, ncy)
        ncx, ncy = maps
        pgw = self.pgw
        for cyo in range(self.phc):
            ny0, ny1, ny2, ny3 = ncy[cyo]
            if max(ny0, ny1, ny2, ny3) < 0:
                continue
            prow, pcrow = pdots[cyo], pcolor[cyo]
            lit = compress(range(pgw), prow)
            if ny0 == ny1 == ny2 == ny3:
                crow = color[ny0]
                for cxo in lit:
                    a, b = ncx[cxo]
                    if a == b:
                        if a >= 0:
                            crow[a] = pcrow[cxo]
                        continue
                    bits = prow[cxo]
                    if a >= 0 and bits & _LEFT:
                        crow[a] = pcrow[cxo]
                    if b >= 0 and bits & _RIGHT:
                        crow[b] = pcrow[cxo]
                continue
            nys = (ny0, ny1, ny2, ny3)
            for cxo in lit:
                bits, ink = prow[cxo], pcrow[cxo]
                for sx, nx in enumerate(ncx[cxo]):
                    if nx < 0:
                        continue
                    for sy in range(4):
                        if nys[sy] >= 0 and bits & DOT_BITS[sx][sy]:
                            color[nys[sy]][nx] = ink


# The window in hand and a few before it: a window repainted at rest
# while its view loads asks for the same map every frame.
_memo = Memo(keep=8)


def reprojection(prev, bbox, graph_w, height_cells):
    """The map from `prev`'s window into `bbox`, or None when there is
    none to make: the very same window, or a degenerate one.

    A source of another size is not one of those any more — an overscan
    is exactly that, and a terminal that has just been resized still has
    the ground its last view covered.
    """
    pbbox, pgw, phc = prev[0], prev[1], prev[2]
    if tuple(pbbox) == tuple(bbox) and (pgw, phc) == (graph_w, height_cells):
        return None
    if min(pgw, phc, graph_w, height_cells) <= 0:
        return None
    key = (tuple(pbbox), pgw, phc, tuple(bbox), graph_w, height_cells)
    return _memo.get(key, lambda: _build(pbbox, pgw, phc, bbox, graph_w,
                                         height_cells))


def _build(pbbox, pgw, phc, bbox, graph_w, height_cells):
    minlon, minlat, maxlon, maxlat = _overscan.unwrap(bbox, pbbox)
    pminlon, pminlat, pmaxlon, pmaxlat = pbbox
    span_x, span_y = maxlon - minlon, maxlat - minlat
    pspan_x, pspan_y = pmaxlon - pminlon, pmaxlat - pminlat
    if min(span_x, span_y, pspan_x, pspan_y) <= 0:
        return None
    fh, pfh = height_cells * 2, phc * 2
    cols = axis_map(graph_w, minlon, span_x, pminlon, pspan_x, pgw, False)
    rows = axis_map(fh, minlat, span_y, pminlat, pspan_y, pfh, True)
    dw, dh = graph_w * 2, height_cells * 4
    pdw, pdh = pgw * 2, phc * 4
    grow = span_x >= pspan_x
    if grow:
        xs = axis_map(pdw, pminlon, pspan_x, minlon, span_x, dw, False)
        ys = axis_map(pdh, pminlat, pspan_y, minlat, span_y, dh, True)
    else:
        xs = axis_map(dw, minlon, span_x, pminlon, pspan_x, pdw, False)
        ys = axis_map(dh, minlat, span_y, pminlat, pspan_y, pdh, True)
    return Reprojection(graph_w, height_cells, pgw, phc, cols, rows, grow,
                        xs, ys)
