"""Shared braille drawing: the dot table, lines, edges, and curve graphs.

A braille cell is a 2x4 grid of dots, and each dot is one bit of the
character's offset from U+2800.  DOT_BITS maps a dot's column and row to
its bit; line_dots, edge_dots and fill_spans walk lines, shape edges
and shape interiors at dot resolution for the maps and radar layers;
build_braille_curve draws the
multi-row curve graphs of the weather hourly chart and the tides chart.

The second half is a grid a byte a dot: `dot_rows` unpacks a braille
grid into one bytes a dot row, `pack_dots` packs such rows back into
cells, and both are passes of C over the whole grid — translate, join,
slice and the int operators — for the map code that moves whole grids
at thirty frames a second (`maps.reproject`, `maps.overscan`).
"""

from itertools import chain

# The bit for the dot at (column 0-1, row 0-3) within a cell.
DOT_BITS = ((0x01, 0x02, 0x04, 0x40), (0x08, 0x10, 0x20, 0x80))

# The empty cell: a braille character with no dots raised.
BLANK = "\u2800"


def line_dots(x0, y0, x1, y1):
    """Integer dots from (x0, y0) to (x1, y1), both ends included."""
    dx, dy = abs(x1 - x0), abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx - dy
    while True:
        yield x0, y0
        if x0 == x1 and y0 == y1:
            return
        e2 = 2 * err
        if e2 > -dy:
            err -= dy
            x0 += sx
        if e2 < dx:
            err += dx
            y0 += sy


def fill_spans(rings, dw, dh):
    """(y, xa, xb) for each run of dots inside closed, projected rings.

    An even-odd scanline fill through each dot row's centre, across all
    the rings together: a ring inside another is a hole in it, and an
    island inside that hole is land again.  A run covers dots xa to
    xb - 1 of row y, clipped to a dw by dh grid, and an empty one is
    not given.
    """
    ys = [p[1] for ring in rings for p in ring]
    if not ys:
        return
    y0 = max(0, int(min(ys)))
    y1 = min(dh - 1, int(max(ys)) + 1)
    for y in range(y0, y1 + 1):
        yc = y + 0.5
        xs = []
        for ring in rings:
            for i in range(len(ring) - 1):
                ax, ay = ring[i]
                bx, by = ring[i + 1]
                if (ay <= yc < by) or (by <= yc < ay):
                    xs.append(ax + (yc - ay) / (by - ay) * (bx - ax))
        xs.sort()
        for i in range(0, len(xs) - 1, 2):
            xa = max(0, int(xs[i] + 0.5))
            xb = min(dw, int(xs[i + 1] + 0.5))
            if xb > xa:
                yield y, xa, xb


def edge_dots(is_land, is_water, gw, hc):
    """Braille masks stroking the land/water boundary of dot masks.

    Both masks are (hc*4) x (gw*2) truthy/falsy grids at exactly braille
    dot resolution (2x4 per cell).  A dot is set only where
    ``is_land[dy][dx]`` and a 4-neighbour has ``is_water`` — so the
    stroke and the colour boundary can never disagree, at any zoom, from
    any data source, and *unknown* samples (in neither mask) are never
    stroked from either side.

    Each dot row is one int with a byte a dot, so a row's four
    neighbourhoods are two shifts and two ors rather than a test a dot:
    the whole stroke is a few dozen passes of C over the grid where it
    was a pass of Python over every dot.
    """
    dh, dw = hc * 4, gw * 2
    land = [int.from_bytes(bit_row(row[:dw]), "big") for row in is_land[:dh]]
    water = [int.from_bytes(bit_row(row[:dw]), "big") for row in is_water[:dh]]
    inside = (1 << (8 * dw)) - 1
    rows = []
    for dy in range(dh):
        here = water[dy]
        # a byte a dot: a shift of eight bits is a step of one dot, and
        # the one shifted in from past the east edge is masked off
        near = (here >> 8) | ((here << 8) & inside)
        if dy > 0:
            near |= water[dy - 1]
        if dy < dh - 1:
            near |= water[dy + 1]
        rows.append((land[dy] & near).to_bytes(dw, "big"))
    return cells_of(pack_dots(rows, gw, hc), gw, hc)


# ---------------------------------------------------------------------------
# A braille grid a byte a dot
# ---------------------------------------------------------------------------
# A cell's eight dots are numbered by plane, k = row * 2 + column: the
# order a grid is scanned in, row by row and left to right within a
# cell.  A packed grid here is a bytes a cell whose bit k is plane k —
# the "code" — and CODE_CELL turns a code into the braille cell with the
# same dots raised.  CODE_LAST and CODE_FIRST name the last and the first
# plane set in a code, one-based, with 0 for an empty cell: what a
# caller carrying ink with its dots asks of a cell.

PLANE_BITS = tuple(DOT_BITS[k % 2][k // 2] for k in range(8))
CODE_CELL = bytes(sum(PLANE_BITS[k] for k in range(8) if code >> k & 1)
                  for code in range(256))
CODE_LAST = bytes(code.bit_length() for code in range(256))
CODE_FIRST = bytes((code & -code).bit_length() for code in range(256))

# a truthy byte -> 1; a cell -> 1 where plane k is set; 1 -> 1 << k
_ANY = bytes(1 if v else 0 for v in range(256))
_PLANE = tuple(bytes(1 if v & bit else 0 for v in range(256)) for bit in PLANE_BITS)
_WEIGHT = tuple(bytes((0, 1 << k)) + bytes(254) for k in range(8))


def bit_row(row):
    """A truthy/falsy row as bytes of 0 and 1.

    Ints and bools pass through `bytes` in C; anything else — None for
    an unknown sample, a float — goes the long way round.
    """
    try:
        return bytes(row).translate(_ANY)
    except (TypeError, ValueError):
        return bytes(1 if v else 0 for v in row)


def dot_rows(cells, gw, hc):
    """A braille grid unpacked: hc*4 bytes, one a dot row, a byte a dot."""
    flat = bytes(chain.from_iterable(cells))
    dw = gw * 2
    out = []
    for sy in range(4):
        # the two columns of this dot row across every cell, interleaved
        row = bytearray(hc * dw)
        row[0::2] = flat.translate(_PLANE[sy * 2])
        row[1::2] = flat.translate(_PLANE[sy * 2 + 1])
        out.append(bytes(row))
    return [out[sy][cy * dw:(cy + 1) * dw] for cy in range(hc) for sy in range(4)]


def pack_dots(rows, gw, hc):
    """Dot rows (hc*4 bytes of gw*2, a byte a dot, 1 where set) packed
    to a code a cell: the planes or-ed together as one wide int."""
    acc = 0
    for sy in range(4):
        plane = b"".join(rows[sy::4])
        for sx in (0, 1):
            k = sy * 2 + sx
            acc |= int.from_bytes(plane[sx::2].translate(_WEIGHT[k]), "big")
    return acc.to_bytes(gw * hc, "big")


def pack_planes(planes, n):
    """Eight planes (bytes of n, 0/1, in plane order) packed to a code a cell."""
    acc = 0
    for k, plane in enumerate(planes):
        acc |= int.from_bytes(plane.translate(_WEIGHT[k]), "big")
    return acc.to_bytes(n, "big")


def cells_of(code, gw, hc):
    """A code a cell, flat, as the braille grid: hc rows of gw ints."""
    cells = code.translate(CODE_CELL)
    return [list(cells[y * gw:(y + 1) * gw]) for y in range(hc)]


def interpolate(values, n):
    """Linearly interpolate *values* to *n* evenly spaced samples."""
    result = []
    for i in range(n):
        t = i / max(1, n - 1) * max(0, len(values) - 1)
        lo_i = int(t)
        hi_i = min(lo_i + 1, len(values) - 1)
        frac = t - lo_i
        result.append(values[lo_i] + (values[hi_i] - values[lo_i]) * frac)
    return result


def braille_rows_from_ys(ys_i, graph_w, n_rows):
    """Place a connected curve of dot positions into braille bit patterns.

    ys_i: 2*graph_w integer dot rows (0=top), one per braille dot column.
    Returns an n_rows x graph_w grid of bit patterns (0 = empty cell);
    chr(0x2800 + bits) is the character. Uses proper column assignment
    for thin diagonal lines.
    """
    total_dots = n_rows * 4

    bits = DOT_BITS

    # Bit storage per (braille_row, char_col)
    rows_bits = [[0] * graph_w for _ in range(n_rows)]

    def _set_dot(ci, y, col):
        """Set a single braille dot at char index ci, dot row y, column col."""
        if ci < 0 or ci >= graph_w or y < 0 or y >= total_dots:
            return
        rows_bits[y // 4][ci] |= bits[col][y % 4]

    for i in range(graph_w):
        left_y = ys_i[2 * i]
        right_y = ys_i[2 * i + 1]

        # Place endpoint dots
        _set_dot(i, left_y, 0)
        _set_dot(i, right_y, 1)

        # Connect left->right: assign intermediate dots to correct column
        if left_y != right_y:
            y_lo, y_hi = min(left_y, right_y), max(left_y, right_y)
            for y in range(y_lo, y_hi + 1):
                x_frac = (y - left_y) / (right_y - left_y)
                col = 0 if abs(x_frac) < 0.5 else 1
                _set_dot(i, y, col)

        # Cross-char continuity: bridge from previous char's right col
        if i > 0:
            prev_y = ys_i[2 * i - 1]
            if prev_y != left_y:
                y_lo, y_hi = min(prev_y, left_y), max(prev_y, left_y)
                for y in range(y_lo, y_hi + 1):
                    _set_dot(i, y, 0)

    return rows_bits


def build_braille_curve(values, graph_w, n_rows=2, pad_frac=0.0, value_range=None):
    """Build an n_rows-high braille line graph from numeric data.

    Returns list of n_rows rows, each a list of (char, avg_value) tuples.
    Together the rows form a (n_rows*4)-dot-high graph spanning graph_w chars.

    pad_frac: fraction of value range to pad above/below (0.0 = no padding).
              Useful for curves that need room for overlay labels.
    value_range: optional (min, max) to fix the y-axis scale.
    """
    n = 2 * graph_w  # samples: 2 per braille char (left col, right col)
    total_dots = n_rows * 4

    # Interpolate values to n evenly spaced samples
    samples = interpolate(values, n)

    if value_range is not None:
        s_min, s_max = value_range
    else:
        s_min, s_max = min(samples), max(samples)
    if pad_frac > 0:
        pad = max(0.3, (s_max - s_min) * pad_frac)
        s_min -= pad
        s_max += pad

    # Map to float y: 0=top(max), total_dots-1=bottom(min)
    if s_max == s_min:
        ys = [total_dots / 2] * n
    else:
        s_range = s_max - s_min
        ys = [(total_dots - 1) * (1 - (s - s_min) / s_range) for s in samples]

    # Round to integer dot positions
    ys_i = [max(0, min(total_dots - 1, int(round(y)))) for y in ys]

    rows_bits = braille_rows_from_ys(ys_i, graph_w, n_rows)

    # Convert to (char, avg_value) tuples per row
    result = []
    for r in range(n_rows):
        row = []
        for ci in range(graph_w):
            avg_val = (samples[2 * ci] + samples[2 * ci + 1]) / 2
            row.append((chr(0x2800 + rows_bits[r][ci]), avg_val))
        result.append(row)

    return result
