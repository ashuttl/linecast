"""The fast carriage of a braille grid says what the plain one would.

`maps.reproject`, `maps.overscan.Resample` and `braille.edge_dots` move
whole grids with gathers and wide ints, for the frame budget.  Each is
held here against the obvious version — a test a dot, in scan order —
over random grids, zooms in and out, pans, a resize and the seam.
"""

import random

from linecast.maps import overscan as over
from linecast.maps import reproject
from linecast.maps import view as maps
from linecast.terminal.braille import DOT_BITS, edge_dots
from linecast._xyz import bbox_for


# ---------------------------------------------------------------------------
# The plain versions
# ---------------------------------------------------------------------------
def _plain_fills(m, pfills, ground):
    out = []
    for r in m.rows:
        if r < 0:
            out.append([ground] * m.gw)
            continue
        out.append([ground if c < 0 else pfills[r][c] for c in m.cols])
    return out


def _plain_dots(m, pdots, pcolor=None):
    gw, hc = m.gw, m.hc
    dots = [[0] * gw for _ in range(hc)]
    color = [[None] * gw for _ in range(hc)]
    if m.grow:
        for cy in range(m.phc):
            for cx in range(m.pgw):
                bits = pdots[cy][cx]
                for sx in (0, 1):
                    nx = m.xs[cx * 2 + sx]
                    if nx < 0:
                        continue
                    for sy in range(4):
                        if not bits & DOT_BITS[sx][sy]:
                            continue
                        ny = m.ys[cy * 4 + sy]
                        if ny < 0:
                            continue
                        dots[ny // 4][nx // 2] |= DOT_BITS[nx % 2][ny % 4]
                        if pcolor is not None:
                            color[ny // 4][nx // 2] = pcolor[cy][cx]
        return dots, color
    for ny, oy in enumerate(m.ys):
        if oy < 0:
            continue
        for nx, ox in enumerate(m.xs):
            if ox < 0:
                continue
            if pdots[oy // 4][ox // 2] & DOT_BITS[ox % 2][oy % 4]:
                dots[ny // 4][nx // 2] |= DOT_BITS[nx % 2][ny % 4]
                if pcolor is not None:
                    color[ny // 4][nx // 2] = pcolor[oy // 4][ox // 2]
    return dots, color


def _plain_edge_dots(is_land, is_water, gw, hc):
    dh, dw = hc * 4, gw * 2
    dots = [[0] * gw for _ in range(hc)]
    for dy in range(dh):
        for dx in range(dw):
            if not is_land[dy][dx]:
                continue
            if ((dx > 0 and is_water[dy][dx - 1])
                    or (dx < dw - 1 and is_water[dy][dx + 1])
                    or (dy > 0 and is_water[dy - 1][dx])
                    or (dy < dh - 1 and is_water[dy + 1][dx])):
                dots[dy // 4][dx // 2] |= DOT_BITS[dx % 2][dy % 4]
    return dots


def _plain_resample_dots(cut, rows):
    """Each window dot from its source dot, by the dot index."""
    index = cut._dot_index()
    sdw = cut.frame.gw * 2
    gw, dw = cut.gw, cut.gw * 2
    dots = [[0] * gw for _ in range(cut.hc)]
    for i, at in enumerate(index):
        if at < 0:
            continue
        sy, sx = divmod(at, sdw)
        if rows[sy // 4][sx // 2] & DOT_BITS[sx % 2][sy % 4]:
            ny, nx = divmod(i, dw)
            dots[ny // 4][nx // 2] |= DOT_BITS[nx % 2][ny % 4]
    return dots


def _plain_ink_source(cut, rows):
    """A lit cell's first lit dot's own source cell, else the cell index."""
    index = cut._dot_index()
    sgw = cut.frame.gw
    sdw = sgw * 2
    gw, dw = cut.gw, cut.gw * 2
    src = list(cut._cell_index())
    for cy in range(cut.hc):
        for cx in range(gw):
            for sy in range(4):
                for sx in (0, 1):
                    at = index[(cy * 4 + sy) * dw + cx * 2 + sx]
                    if at < 0:
                        continue
                    y, x = divmod(at, sdw)
                    if rows[y // 4][x // 2] & DOT_BITS[x % 2][y % 4]:
                        src[cy * gw + cx] = (y // 4) * sgw + x // 2
                        break
                else:
                    continue
                break
    return src


def _grid(rng, gw, hc, density):
    out = []
    for _ in range(hc):
        row = []
        for _ in range(gw):
            v = 0
            for bit in range(8):
                if rng.random() < density:
                    v |= 1 << bit
            row.append(v)
        out.append(row)
    return out


def _ink(rng, dots):
    return [[rng.randrange(100) if d else None for d in row] for row in dots]


class _Layer:
    def __init__(self, dots, color, ribbon=()):
        self.dots, self.color, self.ribbon = dots, color, set(ribbon)


# ---------------------------------------------------------------------------
# The reprojection
# ---------------------------------------------------------------------------
class TestReprojection:
    PGW, PHC = 23, 9
    PBBOX = (-70.5, 43.2, -70.5 + 0.1 * 23, 43.2 + 0.05 * 9)

    def _windows(self):
        """Zooms in and out, pans, a mixture, and another terminal size."""
        minlon, minlat, maxlon, maxlat = self.PBBOX
        pw, ph = maxlon - minlon, maxlat - minlat
        cx, cy = (minlon + maxlon) / 2, (minlat + maxlat) / 2
        for gw, hc in ((self.PGW, self.PHC), (17, 6), (30, 12)):
            for z in (0.4, 0.8, 1.0, 1.2, 1.7, 3.0):
                for fx, fy in ((0, 0), (0.3, -0.2), (1.4, 0.6)):
                    w, h = pw * z * gw / self.PGW, ph * z * hc / self.PHC
                    x, y = cx + fx * pw, cy + fy * ph
                    yield gw, hc, (x - w / 2, y - h / 2, x + w / 2, y + h / 2)

    def test_fills_and_dots_say_what_the_plain_carriage_does(self):
        rng = random.Random(3)
        prev = (self.PBBOX, self.PGW, self.PHC)
        fills = [[(x, y) for x in range(self.PGW)] for y in range(self.PHC * 2)]
        seen = set()
        for gw, hc, bbox in self._windows():
            m = reproject.reprojection(prev, bbox, gw, hc)
            if m is None:
                continue
            seen.add(m.grow)
            assert m.fills(fills, "g") == _plain_fills(m, fills, "g")
            for density in (0.05, 0.5, 1.0):
                dots = _grid(rng, self.PGW, self.PHC, density)
                ink = _ink(rng, dots)
                assert m.dots(dots, ink) == _plain_dots(m, dots, ink)
                assert m.dots(dots) == _plain_dots(m, dots)
        assert seen == {True, False}

    def test_both_carriages_of_a_grown_window_agree_with_the_plain_one(self, monkeypatch):
        # a sparse layer is carried a dot at a time and a dense one
        # through the gathers; the dividing line is a count, so each
        # side is held against the plain carriage with the line moved
        rng = random.Random(4)
        prev = (self.PBBOX, self.PGW, self.PHC)
        grown = 0
        for gw, hc, bbox in self._windows():
            m = reproject.reprojection(prev, bbox, gw, hc)
            if m is None or not m.grow:
                continue
            grown += 1
            for density in (0.1, 0.8):
                dots = _grid(rng, self.PGW, self.PHC, density)
                ink = _ink(rng, dots)
                want = _plain_dots(m, dots, ink)
                for line in (-1, 10 ** 6):
                    monkeypatch.setattr(reproject, "_SPARSE", line)
                    reproject._unpacked.clear()
                    assert m.dots(dots, ink) == want
                    assert m.dots(dots) == (want[0], [[None] * gw for _ in range(hc)])
        assert grown

    def test_the_map_is_kept_between_frames_and_answers_the_same(self):
        prev = (self.PBBOX, self.PGW, self.PHC)
        bbox = (-70.4, 43.25, -68.3, 43.6)
        first = reproject.reprojection(prev, bbox, 17, 6)
        again = reproject.reprojection(prev, list(bbox), 17, 6)
        assert again is first
        dots = _grid(random.Random(1), self.PGW, self.PHC, 0.4)
        assert first.dots(dots) == _plain_dots(first, dots)
        assert first.dots(dots) == first.dots(dots)

    def test_a_one_column_window_still_carries(self):
        prev = (self.PBBOX, self.PGW, self.PHC)
        bbox = (-70.0, 43.3, -69.9, 43.5)
        m = reproject.reprojection(prev, bbox, 1, 1)
        dots = _grid(random.Random(2), self.PGW, self.PHC, 0.7)
        ink = _ink(random.Random(2), dots)
        assert m.dots(dots, ink) == _plain_dots(m, dots, ink)
        fills = [[(x, y) for x in range(self.PGW)] for y in range(self.PHC * 2)]
        assert m.fills(fills, "g") == _plain_fills(m, fills, "g")

    def test_the_view_module_still_names_it(self):
        assert maps._reprojection is reproject.reprojection
        assert maps._Reprojection is reproject.Reprojection
        assert maps._axis_map is reproject.axis_map

    def test_across_the_seam(self):
        rng = random.Random(5)
        gw, hc = 40, 12
        pbbox = bbox_for(-16.8, 179.95, 0.05, gw, hc)
        prev = (pbbox, gw, hc)
        dots = _grid(rng, gw, hc, 0.3)
        ink = _ink(rng, dots)
        for dl, z in ((0.02, 1.0), (-0.03, 0.6), (359.97, 1.4)):
            bbox = bbox_for(-16.8, 179.95 + dl, 0.05 * z, gw, hc)
            m = reproject.reprojection(prev, bbox, gw, hc)
            assert m is not None
            assert any(c >= 0 for c in m.cols)
            assert m.dots(dots, ink) == _plain_dots(m, dots, ink)


# ---------------------------------------------------------------------------
# The resample at rest
# ---------------------------------------------------------------------------
class TestResample:
    def _cuts(self):
        for gw, hc in ((24, 9), (3, 2)):
            for lat, zoom in ((40.7, 10.0), (-41.0, 4.0), (72.0, 0.2)):
                frame, _at = over.plan(bbox_for(lat, 172.0, zoom, gw, hc), gw, hc)
                for dcols in (0, 3, -7):
                    bbox = bbox_for(lat, 172.0 + dcols * frame.cell[0], zoom, gw, hc)
                    yield over.Resample(frame, bbox, gw, hc)

    def test_dots_ink_and_layers_say_what_the_plain_gather_does(self):
        rng = random.Random(11)
        for cut in self._cuts():
            sgw, shc = cut.frame.gw, cut.frame.hc
            for density in (0.05, 0.6):
                dots = _grid(rng, sgw, shc, density)
                ink = _ink(rng, dots)
                assert cut.dots(dots) == _plain_resample_dots(cut, dots)
                src = _plain_ink_source(cut, dots)
                assert cut.ink_source(dots) == src
                ribbon = {(rng.randrange(sgw), rng.randrange(shc)) for _ in range(sgw)}
                got = cut.layer(_Layer(dots, ink, ribbon))
                flat = [v for row in ink for v in row] + [None]
                gw = cut.gw
                assert got.color == [[flat[src[y * gw + x]] for x in range(gw)]
                                     for y in range(cut.hc)]
                want = {r * sgw + c for c, r in ribbon}
                assert got.ribbon == {(i % gw, i // gw) for i, at in enumerate(src)
                                      if at in want}
                # asked again, the held answer is the same answer
                assert cut.dots(dots) == got.dots

    def test_grids_and_bits_are_the_index_read_straight(self):
        rng = random.Random(12)
        for cut in self._cuts():
            sgw, shc = cut.frame.gw, cut.frame.hc
            grid = [[(x, y) for x in range(sgw)] for y in range(shc * 2)]
            got = cut.grid(grid, "f")
            index = cut._sub_index()
            flat = [v for row in grid for v in row] + ["f"]
            assert got == [[flat[index[y * cut.gw + x]] for x in range(cut.gw)]
                           for y in range(cut.hc * 2)]
            shore = [bytes(rng.choice([0, 1, 2, 3]) for _ in range(sgw * 2))
                     for _ in range(shc * 4)]
            index = cut._dot_index()
            packed = b"".join(shore)
            dw = cut.gw * 2
            for mask in (1, 2):
                want = [[(1 if at >= 0 and packed[at] & mask else 0)
                         for at in index[y * dw:(y + 1) * dw]]
                        for y in range(cut.hc * 4)]
                assert [list(r) for r in cut.bits(shore, mask)] == want


# ---------------------------------------------------------------------------
# The shoreline
# ---------------------------------------------------------------------------
class TestEdgeDots:
    def test_strokes_what_the_plain_walk_strokes(self):
        rng = random.Random(21)
        for gw, hc in ((1, 1), (2, 1), (9, 5), (40, 12)):
            dw, dh = gw * 2, hc * 4
            for values in ((0, 1), (False, True), (None, 0, 2, True), (0.0, 1.5), (0, 300)):
                land = [[rng.choice(values) for _ in range(dw)] for _ in range(dh)]
                water = [[rng.choice(values) for _ in range(dw)] for _ in range(dh)]
                assert edge_dots(land, water, gw, hc) == _plain_edge_dots(land, water, gw, hc)

    def test_takes_bytes_rows_too(self):
        rng = random.Random(22)
        gw, hc = 12, 4
        land = [bytearray(rng.randrange(2) for _ in range(gw * 2)) for _ in range(hc * 4)]
        water = [bytes(rng.randrange(2) for _ in range(gw * 2)) for _ in range(hc * 4)]
        assert edge_dots(land, water, gw, hc) == _plain_edge_dots(land, water, gw, hc)
