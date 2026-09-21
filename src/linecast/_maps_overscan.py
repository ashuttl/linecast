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

from linecast._maps_hover import HoverIndex

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


def locate(frame, bbox, gw, hc, inside=True):
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
        index = self._filtered
        if index is None:
            kept = self._glyphs
            index = HoverIndex(
                self._index.owner, self._index.feats, self._index.names,
                {p: v for p, v in self._index.marks.items() if p in kept},
                self._index.area,
                texts={p: t for p, t in self._index.texts.items()
                       if p in kept},
                shore=self._index.shore)
            self._filtered = index
        return index

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
