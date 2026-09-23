"""The margin a flat view is built beyond the window that shows it.

A street or terrain view used to be built for exactly the window's
bbox, which made every pan a new view and a new fetch: a drag showed
the last view shifted, with bare ground along the edge the window had
moved onto, and the frame it came to rest on went back to the network
for a picture that overlapped the one already in hand by nine parts in
ten.

So a view is built a margin wider than the window and the frame is a
crop of it.  The margin is an eighth of the window on each side, which
makes the built view a quarter wider and a quarter taller (`padding`);
measured at 160x45 that is 1.3x a plain street build and 1.5x a plain
terrain build, and the next size up — a quarter each side — is 5.6x,
because the padded bbox crosses into three times as many vector tiles.
A pan inside the margin is then free and exact: the same data, cropped
at a different offset, fully painted to every edge.  What the margin
cannot cover is asked for centred *ahead* (`plan`'s `ahead`), so the
depth is where the reader is going and the shallow side is the ground
behind them.

Nothing here fetches or decides when to build.  `plan` says which
window to build, `locate` says whether a window is inside one already
built, and the rest is the crop: grids by rows and columns, braille
layers with their ribbons, label runs kept whole or dropped whole, and
the hover index read through the offset.
"""

from collections import namedtuple
from operator import itemgetter, or_

from linecast._maps import globe as _globe
from linecast._maps.hover import HoverIndex
from linecast.radar.basemap import _BITS
from linecast._scenes import Memo

# The margin is a MARGIN'th of the window on each side.  Measured at
# 160x45 with tiles on disk: an eighth each side (1.25x in each
# dimension, 1.54x the area) costs 1.30x a plain street build and 1.50x
# a plain terrain build; a quarter each side costs 5.6x and 1.9x, the
# street jump being the padded bbox reaching 24 vector tiles where the
# window needs 8.  An eighth is the largest margin that stays inside
# half again the plain build for both registers.
MARGIN = 8

# How far from a cell boundary a window may sit and still be a crop: an
# eighth of a cell is a quarter of a braille dot, under anything drawn.
SLACK = 0.125

# How far out of register a *slice* of a built view may be and still be
# taken, in braille dots (`_globe.crop_dots`).  A window at rest is
# resampled and is out by nothing whatever its offset, so what this
# bounds is the frames in between, where the crop is sliced and the
# picture swims against the ground it is cut from.  A cell and a half:
# measured at 160x45 with real tiles, a twenty column pan at the Alps
# is 1.6 dots out at 2 degrees and 8.5 at 10, and the second is where
# a reader can see a coastline sitting off its own shore.  The
# alternative to taking it is not a better picture but a build of
# several seconds, with the last view translated — by more — until it
# lands, so the bound is deliberately loose.
MAX_SHEAR = 6.0


def padding(gw, hc):
    """(columns, rows) of margin on each side of a gw by hc window."""
    return (max(1, (gw + MARGIN - 1) // MARGIN),
            max(1, (hc + MARGIN - 1) // MARGIN))


class Frame(namedtuple("Frame", "bbox gw hc")):
    """One built view: the bbox it was built for and its size in cells.

    A window is a crop of a Frame, never the other way round, so every
    Frame a renderer is handed contains the window it is drawing.
    """
    __slots__ = ()

    @property
    def cell(self):
        """(degrees of longitude per column, of latitude per row)."""
        minlon, minlat, maxlon, maxlat = self.bbox
        return (maxlon - minlon) / self.gw, (maxlat - minlat) / self.hc


def window_frame(bbox, gw, hc):
    """The Frame that is the window itself — no margin at all.

    `--print` builds this and nothing else, so a printed frame is the
    same bytes it has always been.
    """
    return Frame(tuple(bbox), gw, hc)


def plan(bbox, gw, hc, ahead=(0, 0), pad=None):
    """(the Frame to build for a gw by hc window, where the window sits).

    `ahead` is (east, south), each between -1 and 1: which way the
    window is travelling.  The margin's *size* does not change with it,
    only where it sits — at rest it is half on each side, and under a
    drag or a coast the whole of it goes in front, so the ground the
    reader is moving onto is twice as deep and the ground behind them
    is not built at all.  Either way the window is inside the Frame,
    which is what lets every layer be cropped rather than reprojected —
    and the offset comes back from here rather than being measured off
    the bboxes afterwards, so the crop is the one that was planned.
    """
    minlon, minlat, maxlon, maxlat = bbox
    colw, rowh = (maxlon - minlon) / gw, (maxlat - minlat) / hc
    pw, ph = pad if pad is not None else padding(gw, hc)
    ax = max(-1.0, min(1.0, ahead[0]))
    ay = max(-1.0, min(1.0, ahead[1]))
    # the two halves always add to the whole margin, so the built view
    # is the same size and the same cost whichever way the view is going
    left = int(round(pw * (1.0 - ax)))
    top = int(round(ph * (1.0 - ay)))
    right, bottom = 2 * pw - left, 2 * ph - top
    return (Frame((minlon - left * colw, minlat - bottom * rowh,
                   maxlon + right * colw, maxlat + top * rowh),
                  gw + left + right, hc + top + bottom),
            (left, top))


def locate(frame, bbox, gw, hc, inside=True, cap=None):
    """Where a gw by hc window at `bbox` sits in `frame`, or None.

    (column, row) of the window's top-left cell, and None whenever the
    window is not a whole-cell crop of the frame: another scale,
    another cell size, or ground the frame does not cover.  The margin
    is only ever built to be cropped at cell boundaries, so a fraction
    of a cell out is a miss rather than something to round into place.

    Whole-cell to within SLACK, that is.  A flat window's columns are
    not quite the frame's: its longitude span follows the cosine of its
    own centre latitude (_radar_render.bbox_for), so a window dragged
    one row north is a hair narrower than the view it was cut from —
    at street zoom a few thousandths of a cell across the whole width,
    at a terrain zoom a few hundredths a row.  The offset is taken at
    the window's centre so the drift splits evenly to either edge, and
    the window is a crop for as long as no cell of it is more than
    SLACK from where the frame drew that ground; past that it is the
    reprojection it would otherwise have been.

    `inside` off asks only whether the two grids line up, and lets the
    window reach past the frame's edges: a pan at the same scale is a
    translation whether or not the margin covers all of it, and
    `shift_crop` fills in what it does not.

    `cap` is the window's reach over the sphere in radians, for a
    register drawn by the camera.  Two orthographic views of the same
    ground at the same scale and different centres are not a
    translation of one another at all: shift the centre east and the
    picture turns with the meridians, by an angle that depends on the
    offset and the latitude (`_globe.crop_dots`).  A window at the
    built view's own centre is a crop exactly; one off it is a crop of
    the same *ground* — the samples are there, at somewhere other than
    the offset — and `Resample` is how a frame at rest takes them.
    What is decided here is only the far end of that: a window so far
    off the built view's centre that the slice a moving frame takes
    would visibly swim is left to be built for itself.
    """
    fminlon, fminlat, fmaxlon, fmaxlat = frame.bbox
    minlon, minlat, maxlon, maxlat = bbox
    colw, rowh = frame.cell
    if colw <= 0 or rowh <= 0 or gw <= 0 or hc <= 0:
        return None
    wcolw, wrowh = (maxlon - minlon) / gw, (maxlat - minlat) / hc
    if (abs(wcolw - colw) * gw / 2 > SLACK * colw
            or abs(wrowh - rowh) * hc / 2 > SLACK * rowh):
        return None
    fx = ((minlon + maxlon) / 2 - fminlon) / colw - gw / 2
    fy = (fmaxlat - (minlat + maxlat) / 2) / rowh - hc / 2
    dx, dy = int(round(fx)), int(round(fy))
    if abs(fx - dx) > SLACK or abs(fy - dy) > SLACK:
        return None
    if cap is not None:
        # the window's own reach and the window's own corner, measured
        # about the built view's centre latitude
        off = _globe.crop_dots((fminlat + fmaxlat) / 2, cap, gw, hc,
                               dx + gw / 2 - frame.gw / 2,
                               dy + hc / 2 - frame.hc / 2)
        if off > MAX_SHEAR:
            return None
    if inside and not (0 <= dx and dx + gw <= frame.gw
                       and 0 <= dy and dy + hc <= frame.hc):
        return None
    return dx, dy


def window_hint(frame, gw, hc):
    """((bbox, height_cells) of a window in `frame`), or None for one
    that *is* the window.

    What the source zoom and the band are chosen for, whatever the
    margin around them (_maps_streets.view_tiles): a crop has to be the
    map the window itself would draw, and a wider bbox left to settle
    its own source zoom can land on a finer one.

    The window taken is the frame's own middle rather than whichever
    window is asking, so two crops of one built view ask for it under
    the same key however far apart they sit.
    """
    if (frame.gw, frame.hc) == (gw, hc):
        return None
    colw, rowh = frame.cell
    dx, dy = (frame.gw - gw) // 2, (frame.hc - hc) // 2
    minlon = frame.bbox[0] + dx * colw
    maxlat = frame.bbox[3] - dy * rowh
    return ((minlon, maxlat - hc * rowh, minlon + gw * colw, maxlat), hc)


def crop_grid(rows, dx, dy, w, h):
    """A rectangle of a row-major grid, or None for a grid that is None."""
    if rows is None:
        return None
    return [row[dx:dx + w] for row in rows[dy:dy + h]]


def shift_crop(rows, dx, dy, w, h, fill):
    """A rectangle that may reach past the grid, padded with `fill`.

    The crop's poorer cousin, for a window that has outrun the margin.
    Two grids at the same scale differ by a translation and nothing
    else, so what is shared is sliced across and what is not is bare
    ground — a great deal less work than resampling every sub-cell of
    the one into the other, which at thirty frames a second against a
    build holding the interpreter lock is the difference between a pan
    that follows the hand and one that lurches after it.
    """
    if rows is None:
        return None
    sh = len(rows)
    sw = len(rows[0]) if sh else 0
    blank = [fill] * w
    lo, hi = max(0, dx), min(sw, dx + w)
    lead = [fill] * (lo - dx) if dx < 0 else []
    out = []
    for y in range(dy, dy + h):
        if not (0 <= y < sh) or lo >= hi:
            out.append(blank[:])
            continue
        row = lead + list(rows[y][lo:hi])
        row.extend(blank[len(row):])
        out.append(row)
    return out


class CroppedLayer:
    """A braille layer seen through the crop: the window's cells only.

    Duck-typed for the composers exactly as maps._ShiftedLayer is, with
    the hover index carried through so a pointer over the crop still
    answers about what is drawn under it.
    """
    __slots__ = ("dots", "color", "ribbon", "hover")

    def __init__(self, dots, color, ribbon=(), hover=None):
        self.dots = dots
        self.color = color
        self.ribbon = set(ribbon)
        self.hover = hover


def crop_layer(layer, dx, dy, w, h, hover=None):
    """A ranked braille layer cropped to the window, or None."""
    if layer is None:
        return None
    ribbon = {(c - dx, r - dy) for c, r in getattr(layer, "ribbon", ())
              if dx <= c < dx + w and dy <= r < dy + h}
    return CroppedLayer(crop_grid(layer.dots, dx, dy, w, h),
                        crop_grid(layer.color, dx, dy, w, h), ribbon, hover)


# A braille cell's eight dots, one byte each, by sub-row: unpacking a
# grid is then a table lookup a cell and a join a dot row.
_DOT_TABLE = tuple(
    tuple(bytes(1 if v & _BITS[sx][sy] else 0 for sx in (0, 1))
          for v in range(256))
    for sy in range(4))


# 1 -> the braille bit, and a packed land/water byte -> one of its two
# bits: a pass of C over a whole grid where a comprehension would be a
# pass of Python.
_WEIGHTS = {bit: bytes((0, bit)) + bytes(254)
            for col in _BITS for bit in col}
_MASKS = {}


def _mask_table(mask):
    table = _MASKS.get(mask)
    if table is None:
        table = _MASKS[mask] = bytes(1 if v & mask else 0
                                     for v in range(256))
    return table


def _dot_bytes(rows):
    """A braille grid as one byte a dot, row after row, and a blank.

    The blank is the last byte, so index -1 — what `crop_index` gives
    for a sample the built view does not hold — reads as no dot.
    """
    out = bytearray()
    for row in rows:
        for table in _DOT_TABLE:
            out += b"".join([table[v] for v in row])
    out.append(0)
    return bytes(out)


class Resample:
    """The crop's exact cousin, for a window off the built view's centre.

    A crop takes the samples the built view holds at an offset, which
    is the window's own picture only when the two share a centre.  Off
    it, under one camera, the built view has turned with the meridians
    (`_globe.crop_dots`), and the samples the window wants are there
    but not at the offset.  So they are fetched rather than sliced:
    every sample of the window is placed in the built view's grid by
    the rotation between the two cameras, once per pair, and each
    frame after that is a gather.

    Nearest sample, as every crop here has been.  The fill and the
    elevation are taken at sub-pixel pitch, the land and water at dot
    pitch, and a layer's ink at cell pitch, because that is the grid
    each of them is written on.

    Not cheap enough for a frame in motion, and not needed there: a
    moving picture is a preview of the one it stands in for, which
    lands at rest.  Measured at 160x45 nine columns off the built
    view's centre: a slice is under a millisecond, the first resample
    is 35 and most of that is the index maps, and every resting frame
    after it is 10, because the maps are kept (`resample`).  The
    street register's own grids come to 29 and 3 at the same size,
    the whole of the 3 being its one dense braille layer.
    """

    __slots__ = ("frame", "gw", "hc", "src", "dst", "_sub", "_dot", "_cell",
                 "_planes", "_bits", "_ink")

    def __init__(self, frame, bbox, gw, hc):
        self.frame, self.gw, self.hc = frame, gw, hc
        self.src = _globe.Camera.for_bbox(frame.bbox, frame.gw, frame.hc)
        self.dst = _globe.Camera.for_bbox(bbox, gw, hc)
        self._sub = self._dot = self._cell = self._planes = None
        # unpacked dot grids and the ink maps taken from them, held by
        # the grid they came from so the identity they are keyed on
        # cannot be reused under them
        self._bits = {}
        self._ink = {}

    # -- the index maps, each built on the first ask ---------------------
    def _sub_index(self):
        if self._sub is None:
            self._sub = _globe.crop_index(
                self.src, self.dst, self.gw, self.hc * 2,
                self.frame.gw, self.frame.hc * 2)
        return self._sub

    def _cell_index(self):
        if self._cell is None:
            self._cell = _globe.crop_index(
                self.src, self.dst, self.gw, self.hc,
                self.frame.gw, self.frame.hc)
        return self._cell

    def _dot_index(self):
        """Each window dot's source dot — for the masks, which are areas."""
        if self._dot is None:
            self._dot = _globe.crop_index(
                self.src, self.dst, self.gw * 2, self.hc * 4,
                self.frame.gw * 2, self.frame.hc * 4)
        return self._dot

    def _dot_planes(self):
        """[(bit, [source dot per window cell])] — a cell's eight dots.

        The dot index regrouped by where a dot sits inside its cell, so
        a whole plane of the window comes back from one gather and the
        eight are or-ed together — rather than a bit being tested and
        set a dot at a time, which is the one place this would cost
        more than the crop it replaces.
        """
        if self._planes is None:
            flat = self._dot_index()
            dw, hc = self.gw * 2, self.hc
            planes = []
            for sy in range(4):
                for sx in (0, 1):
                    idx = []
                    for cy in range(hc):
                        base = (4 * cy + sy) * dw
                        idx.extend(flat[base + sx:base + dw:2])
                    planes.append((_BITS[sx][sy], idx))
            self._planes = planes
        return self._planes

    # -- the gathers -----------------------------------------------------
    def _gather(self, rows, index, w, fill):
        flat = [v for row in rows for v in row]
        flat.append(fill)
        return [list(itemgetter(*index[i:i + w])(flat))
                for i in range(0, len(index), w)]

    def grid(self, rows, fill):
        """A sub-pixel grid — the shaded fill, the elevation — or None."""
        if rows is None:
            return None
        return self._gather(rows, self._sub_index(), self.gw, fill)

    def bits(self, rows, mask):
        """One mask of a dot-pitch packed grid, gathered into the window.

        The land and the water the shoreline is cut from
        (`_maps_views.shore_bits`), which are areas: nearest sampling
        moves an area only at its own edge, and cutting the stroke
        again from what comes back gives the shore the window would
        have drawn.
        """
        if rows is None:
            return None
        flat = b"".join(rows).translate(_mask_table(mask)) + b"\x00"
        index, dw = self._dot_index(), self.gw * 2
        return [list(itemgetter(*index[i:i + dw])(flat))
                for i in range(0, len(index), dw)]

    def _dot_acc(self, rows):
        """The window's braille, a byte a cell, flat: the eight planes
        gathered and or-ed together."""
        raw = self._raw(rows)
        acc = None
        for bit, index in self._dot_planes():
            # 0 or the bit, in one pass of C over the whole grid
            plane = itemgetter(*index)(raw.translate(_WEIGHTS[bit]))
            acc = plane if acc is None else bytes(map(or_, acc, plane))
        return acc

    def ink_source(self, rows):
        """Per window cell, the built cell whose ink its braille is.

        A cell's ink belongs to the dot drawn in it.  Taken from the
        cell index instead it answers what is under the middle of the
        cell, and a line one dot wide crosses into a cell well before
        the ground under that cell's middle does: measured on a road
        net seven columns off the built view's centre at ten degrees,
        a quarter of the cells holding road dots were inked from the
        empty cell beside them, which in a composer is no ink at all.
        So a lit cell takes the ink of its first lit dot's own cell,
        and only a cell with nothing drawn in it falls back to the
        index.

        Kept while the grid it was taken from is, as the unpacked
        dots are: a window at rest repaints without moving.
        """
        held = self._ink.get(id(rows))
        if held is None:
            if len(self._ink) > 8:
                self._ink.clear()
            held = (rows, self._ink_source(rows))
            self._ink[id(rows)] = held
        return held[1]

    def _ink_source(self, rows):
        acc = self._dot_acc(rows)
        planes = self._dot_planes()
        sgw = self.frame.gw
        sdw = sgw * 2
        src = list(self._cell_index())
        for i, bits in enumerate(acc):
            if not bits:
                continue
            for bit, index in planes:
                if bits & bit:
                    at = index[i]
                    src[i] = (at // sdw) // 4 * sgw + (at % sdw) // 2
                    break
        return src

    def dots(self, rows):
        """A braille dot grid carried into the window, or None.

        The rivers and the borders, which are strokes: lines one dot
        wide, where nearest sampling is usually the wrong tool — ask a
        line what is under each new dot and most new dots have nothing
        under them, and the line comes back as specks.  It is the right
        tool here because the two grids are the same pitch and the
        turn between them is under a degree, so the map from one to the
        other is very nearly a bijection and the line very nearly
        survives it dot for dot.  Measured on the Natural Earth borders
        of a 160x45 window nine columns off the built view's centre at
        ten degrees: 1729 dots against 1728 for the map taken the other
        way round, and one isolated dot either way, which is what the
        view built fresh at that centre has too.

        The shoreline is not carried this way, because a shore has to
        agree with the fill beside it: it is cut again from the land
        and water instead (`bits`).
        """
        if rows is None:
            return None
        acc = self._dot_acc(rows)
        gw = self.gw
        return [list(acc[y * gw:(y + 1) * gw]) for y in range(self.hc)]

    def _raw(self, rows):
        """A braille grid unpacked to a byte a dot, kept while it is used."""
        held = self._bits.get(id(rows))
        if held is None:
            if len(self._bits) > 8:
                # a view that landed replaced every grid at once; the
                # old ones are held only to keep their ids from coming
                # back under this dict, and that is over
                self._bits.clear()
            held = (rows, _dot_bytes(rows))
            self._bits[id(rows)] = held
        return held[1]

    def layer(self, layer, hover=None):
        """A ranked braille layer through the resample, or None.

        The ink and the ribbon follow the dots rather than the cell
        index (`ink_source`), so a cell showing a road shows it in the
        road's own colour and a cell the motorway ribbon tints is one
        the motorway is drawn in.
        """
        if layer is None:
            return None
        src = self.ink_source(layer.dots)
        gw = self.gw
        ribbon = ()
        source = getattr(layer, "ribbon", ())
        if source:
            sgw = self.frame.gw
            want = {r * sgw + c for c, r in source}
            ribbon = {(i % gw, i // gw) for i, at in enumerate(src)
                      if at in want}
        flat = [v for row in layer.color for v in row]
        flat.append(None)
        color = [list(itemgetter(*src[i:i + gw])(flat))
                 for i in range(0, len(src), gw)]
        return CroppedLayer(self.dots(layer.dots), color, ribbon, hover)

    # -- the placements ---------------------------------------------------
    def relocate(self, col, row):
        """The window cell a built view's cell lands on, or None.

        The index maps every window sample to a source; this maps a
        source the other way, to wherever the window's own camera puts
        the ground under it.  Taken through the sphere rather than by
        inverting the index, so it can never come back empty —
        inverting a gather leaves holes wherever two window cells
        landed on one source, and a name or a lit road with holes in
        it is worse than either.
        """
        at = self.src.ground(col, row)
        if at is None:
            return None
        return self.dst.screen_cell(at[1], at[0])

    def overlays(self, labels):
        """(the window's label runs, where each kept cell of writing went).

        `crop_overlays` through the resample.  A name is written across
        the very feature it names, and the built view has turned with
        the meridians since — so a run is moved by where its own ground
        now is rather than by the crop's offset, and laid out from
        there the way it was written, horizontally.  Kept or dropped
        whole, as a crop keeps it: half a name at an edge is a
        different word — and so is a name another run has since been
        written over, so a run whose cells are already taken is dropped
        whole too, rather than overwriting the letters under it.

        The second value is what the hover index needs: for each of the
        built view's cells that still has its writing on screen, the
        window cell that writing is in now.
        """
        kept, moved = {}, {}
        for col, row, entries in label_runs(labels):
            at = self.relocate(col, row)
            if at is None:
                continue
            c0, r0 = at
            if any(not (0 <= c0 + off < self.gw) or (c0 + off, r0) in kept
                   for off, _e in entries):
                continue
            for off, entry in entries:
                kept[(c0 + off, r0)] = entry
                moved[(col + off, row)] = (c0 + off, r0)
        return kept, moved


# Two: the window in hand and the one a pan is coming back from.
_resample_cache = Memo(keep=2)


def resample(frame, bbox, gw, hc):
    """The Resample for a window in a built view, kept between frames.

    A view at rest repaints for a pointer, a clock or a cloud without
    moving at all, and the index maps are the whole of the cost — so
    the first resting frame pays for them and the ones after it do
    not.
    """
    key = (frame, tuple(bbox), gw, hc)
    return _resample_cache.get(key, lambda: Resample(frame, bbox, gw, hc))


def label_runs(overlays):
    """[(col, row, [(offset, entry), ...])] — the overlays as written runs.

    A label is a row of consecutive cells laid down together, and it is
    kept or dropped as one thing: half a name straddling the window's
    edge is not a shorter name, it is a different word.  Cells run
    together while they are adjacent, on the same row and in the same
    ink, which is also what keeps a city's dot attached to the name
    beside it.  A double-width glyph's ("", None) continuation belongs
    to the run it continues, so it can never be left behind alone.
    """
    runs = []
    start = row = None
    prev = None
    style = None
    entries = []
    for (col, r), entry in sorted(overlays.items(), key=lambda kv: kv[0][::-1]):
        here = entry[1:]
        cont = entry[0] == ""
        if (prev is not None and r == row and col == prev + 1
                and (cont or here == style)):
            entries.append((col - start, entry))
            prev = col
            if not cont:
                style = here
            continue
        if entries:
            runs.append((start, row, tuple(entries)))
        start, row, prev, style = col, r, col, here
        entries = [(0, entry)]
    if entries:
        runs.append((start, row, tuple(entries)))
    return runs


def crop_overlays(overlays, dx, dy, w, h):
    """The overlays a window keeps, moved into its own coordinates.

    A run entirely inside the window comes across whole; one that
    reaches past an edge is dropped whole, since half a name straddling
    an edge is a different word.  A run under the crosshair or a marker
    is kept: the built view reserved its own centre, not this window's,
    and the mark is drawn over the one letter, as it always was on a
    view in motion — a name blinking out as it passes the centre is
    worse than a letter under a cross.
    """
    kept = {}
    for col, row, entries in label_runs(overlays):
        if not (dy <= row < dy + h):
            continue
        cells = [(col + off, row) for off, _entry in entries]
        if any(not (dx <= c < dx + w) for c, _r in cells):
            continue
        kept.update({(col + off - dx, row - dy): entry
                     for off, entry in entries})
    return kept


def _without_dropped_labels(index, kept):
    """`index` with the writing the window did not keep taken out.

    A label the window dropped must not answer for the ground it was
    covering, and a feature whose name went with it must not light
    letters that are no longer on the page.  Both halves are a filter
    on the built view's own index, by the built view's own cells —
    which is the same filter however the window was taken out of it.
    """
    return HoverIndex(
        index.owner, index.feats, index.names,
        {p: v for p, v in index.marks.items() if p in kept},
        index.area,
        texts={p: t for p, t in index.texts.items() if p in kept},
        shore=index.shore)


class CroppedHover:
    """A hover index read through the crop.

    The index belongs to the built view and is shared by every window
    cut from it — building one per crop would cost a walk of the whole
    grid for a pointer that has not moved.  So the lookup is offset and
    the answer is clipped: a feature's lit cells are the ones inside
    the window, and its lit letters are the ones the crop actually
    kept.  A label the crop dropped must not answer for the ground it
    was covering either, so the marks and the written names are
    filtered — lazily, because a moving view never asks.
    """
    __slots__ = ("_index", "_dx", "_dy", "_w", "_h", "_glyphs", "_filtered")

    def __init__(self, index, dx, dy, w, h, glyphs):
        self._index = index
        self._dx, self._dy, self._w, self._h = dx, dy, w, h
        self._glyphs = {(c + dx, r + dy) for c, r in glyphs}
        self._filtered = None

    def _view(self):
        if self._filtered is None:
            self._filtered = _without_dropped_labels(self._index,
                                                     self._glyphs)
        return self._filtered

    def at(self, col, row):
        if not (0 <= col < self._w and 0 <= row < self._h):
            return None
        dx, dy = self._dx, self._dy
        hit = self._view().at(col + dx, row + dy)
        if hit is None:
            return None
        cells = tuple((c - dx, r - dy) for c, r in hit.cells
                      if dx <= c < dx + self._w and dy <= r < dy + self._h)
        glyphs = tuple((c - dx, r - dy) for c, r in hit.glyphs
                       if (c, r) in self._glyphs)
        return hit._replace(cells=cells, glyphs=glyphs)


class ResampledHover:
    """A hover index read through the resample.

    `CroppedHover`'s twin for a window off the built view's centre.
    What is under a pointer is whatever the window *drew* there, and
    the window drew two kinds of thing by two different maps: the ink,
    gathered a cell at a time by the resample's index (`ink_source`),
    and the writing, moved a run at a time by where its ground went
    (`overlays`).  So a mark or a name is looked up by the window cell
    its letters are in now, and a stroke by the built cell its ink was
    taken from — and what lights comes back the same two ways, the
    letters by where they were written and the stroke's cells as the
    window cells drawn from that stroke.  A road named after a
    resampled crop is therefore the road under the pointer and not the
    one an offset would have named, which at ten degrees is a cell and
    a half away.
    """

    __slots__ = ("_index", "_cut", "_moved", "_source", "_dots", "_ground",
                 "_written", "_drawn")

    def __init__(self, index, cut, moved, source, dots):
        self._index = index
        self._cut = cut
        # built cell -> window cell, for the writing the window kept
        # (`Resample.overlays`)
        self._moved = dict(moved)
        # the same map the ink came off (`Resample.ink_source`), so the
        # feature a cell names is the feature the cell is drawn in
        self._source = source
        # the window's own dots: a cell with nothing drawn in it took
        # its ink from the ground under its middle, and lights nothing
        self._dots = dots
        self._ground = self._written = self._drawn = None

    def _views(self):
        """(the strokes and fills by built cell, the writing by window cell).

        Both filtered to the writing the window kept, and the strokes'
        index keeps that writing under the window's cells too, so a
        feature can find its own label where it is now written.
        """
        if self._ground is None:
            index, moved = self._index, self._moved
            marks = {moved[p]: v for p, v in index.marks.items()
                     if p in moved}
            texts = {moved[p]: t for p, t in index.texts.items()
                     if p in moved}
            self._ground = HoverIndex(index.owner, index.feats, index.names,
                                      {}, index.area, texts=texts,
                                      shore=index.shore)
            cut = self._cut
            blank = [[None] * cut.gw for _ in range(cut.hc)]
            self._written = HoverIndex(blank, index.feats, {}, marks, blank,
                                       texts=texts)
        return self._ground, self._written

    def _cells_drawn_from(self, cells):
        """The window cells whose ink came from these built cells."""
        if self._drawn is None:
            drawn = {}
            gw, dots = self._cut.gw, self._dots
            for i, at in enumerate(self._source):
                if at >= 0 and dots[i // gw][i % gw]:
                    drawn.setdefault(at, []).append((i % gw, i // gw))
            self._drawn = drawn
        sgw = self._cut.frame.gw
        return tuple(p for c, r in cells
                     for p in self._drawn.get(r * sgw + c, ()))

    def at(self, col, row):
        cut = self._cut
        if not (0 <= col < cut.gw and 0 <= row < cut.hc):
            return None
        ground, written = self._views()
        hit = written.at(col, row)
        if hit is not None:
            return hit   # a mark: its cells are the letters, already here
        at = self._source[row * cut.gw + col]
        if at < 0:
            return None
        hit = ground.at(at % cut.frame.gw, at // cut.frame.gw)
        if hit is None:
            return None
        return hit._replace(cells=self._cells_drawn_from(hit.cells))
