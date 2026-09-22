"""City names, one label system for both registers at every zoom.

Natural Earth's 5,227 populated places are the only settlement list
linecast carries offline, and it is now the only one either map
register names a city from while the window is wider than a county.
Terrain draws it at every zoom; street draws it below
`style.GAZETTEER_BAND`, which is where the vector tiles' own place
layer is the coarser of the two.  Past `globe.local_tiles` there are no
tiles at all, so both registers are on this list on both sides of the
hand-off — which is the point: crossing it changes the detail of the
ground and nothing about the names.

The placement is the planet's, unchanged.  The list is walked
biggest-first with its trigonometry hoisted (`_city_trig`), a dot
product against the view centre drops the far hemisphere before any
trig is spent on a city, every candidate is put on the screen by the
window's own camera, and a name that crowds one already written is
dropped rather than nudged or shrunk.  Nothing here consults the cells
any other label class has taken: a city set that depended on what the
tiles happened to carry could not be the same set the planet draws, and
the same set either side of the hand-off is the whole of this module's
job.  The other classes route around the cities instead
(`labels.label_overlays`).

What this adds to the planet's rule is the budget.  The planet's was
one cell in four hundred, clamped to between six and twenty-four names,
and at planet scale that is right — but it is a rule about the size of
the terminal and not about the size of the world on it, so a regional
view got the same two dozen names as a hemisphere and stopped.  The
rule here spends cells faster the closer in the window is: the area a
name is given falls a step per band and the clamp rises a step with it,
so a 2 degree view carries every town the crowding rule will let it
while a planet carries the majors it always did.  Band 0 is the old
rule to the number, which is where every hand-off sits.
"""

import math
import threading

from linecast._maps import globe as _globe
from linecast._maps import style
from linecast._radar.basemap import _load_data, _localized
from linecast._scenes import Memo
from linecast._textwidth import char_width

# The window a name is written into is this many columns wide and this
# many rows tall: the planet's crowding rule, unchanged, and the reason
# a close view saturates long before its budget does.
CROWD_COLS = 16
CROWD_ROWS = 3


def budget(gw, hc, band):
    """How many names a gw by hc window may carry at `band`.

    One rule, read as a sentence: a name is given a patch of the screen
    to itself, the patch shrinks as the view closes in, and the answer
    is held between a floor and a ceiling that both rise with the band.

    At band 0 this is `max(6, min(24, gw * hc // 400))` to the number —
    the planet's own rule — because band 0 is where every tile-to-planet
    hand-off sits and a count that moved across it would be the flip
    this module exists to remove.  Deeper in, the patch falls from 400
    cells to 145 and the clamp walks from [6, 24] to [20, 45].

    Measured at 160x43 over the Alps: the crowding rule alone would
    place 23 names at 2 degrees, 66 at 10 and 60 at 30.  The old flat
    24 cut the 2 degree view — a regional map where every one of the 23
    is a town a reader is looking for — by a quarter, and let the 10
    and 30 degree views off lightly by accident.  The new rule carries
    25 at 2 degrees (so the crowding rule is the only limit there, as
    it should be), 21 at 10 and 17 at 30.  At 80x22 the same three
    views land a band lower and come to 8, 6 and 6, against a flat 6.
    """
    return max(6 + 2 * band,
               min(24 + 3 * band, gw * hc // (1600 // (4 + band))))


# _city_trig() memo: (cities list identity, its trig form).  Keyed to
# the list object itself so a test swapping the basemap data gets
# fresh trig.
_CITY_TRIG = (None, None)


def _city_trig(cities):
    """Every city as (entry, sin lat, cos lat, lon, x, y), biggest first.

    The per-vertex hoist `globe._border_trig` gets, and two additions.
    The city's place in space, so one dot product against the view
    centre drops the far hemisphere before any trig is spent on it —
    the cap test `globe.lake_mask` makes, one city wide.  And the whole
    list ordered by population once, so placement can walk it
    biggest-first and stop the moment the screen is full: a frame then
    looks at a few hundred cities rather than at every one of the five
    thousand.  The unit vector's third component is sin lat, already
    there.
    """
    global _CITY_TRIG
    if _CITY_TRIG[0] is not cities:
        radians, sin, cos = math.radians, math.sin, math.cos
        out = []
        for entry in cities:
            phi, lam = radians(entry[1]), radians(entry[0])
            cos_phi = cos(phi)
            out.append((entry, sin(phi), cos_phi, lam,
                        cos_phi * cos(lam), cos_phi * sin(lam)))
        # stable, so this order restricted to the cities in view is the
        # order the in-view list would sort itself into
        out.sort(key=lambda c: c[0][2], reverse=True)
        _CITY_TRIG = (cities, out)
    return _CITY_TRIG[1]


# The layout memo: where the names go depends on the view, the band,
# the language (a longer name blocks a later city's cell) and the case
# the register writes in — and on nothing else.  Every repaint asks for
# it, hover included, and a drag asks thirty times a second.
_layout_cache = Memo(keep=4)
_layout_lock = threading.Lock()


def layout(cam, band, lang="en", upper_pop=None, window=None):
    """[(col, row, text, entry)] — the names a window carries, in order.

    `col, row` is the cell the settlement dot goes in and `text` is
    written from the cell after it, already cut where the writing ran
    into something (the screen's right edge, or a name written before
    it).  Biggest first, so a caller may read the list as a ranking.

    `upper_pop` is the population from which the register writes a name
    in caps; None writes every name as the gazetteer spells it.  It is
    here rather than in the caller because upper-casing can change a
    name's width, and the width is what decides which of two crowded
    cities keeps its cell — so the register that draws the caps has to
    be the one that lays them out.

    `window` is (gw, hc) of the window `cam` is the overscan of, sitting
    at the overscan's middle (`overscan.window_hint`).  The window's
    names are then laid out first, by the window's own camera and
    against its own budget, and the margin is named around them: so
    what the window crops out of the overscan is the very set it would
    carry built alone — which is what the planet on the far side of
    `globe.local_tiles` does build, with no margin at all.

    Memoised per view: the list is shared between calls, so read it.
    """
    cities = _load_data()["cities"]
    key = (cam.lat, cam.lon, cam.zoom, cam.gw, cam.hc, cam.aspect,
           band, lang, upper_pop, window, id(cities))
    with _layout_lock:
        hit = _layout_cache.get(key)
    if hit is not None:
        return hit
    hit = _layout(cities, cam, band, lang, upper_pop, window)
    with _layout_lock:
        _layout_cache.put(key, hit)
    return hit


def _layout(cities, cam, band, lang, upper_pop, window=None):
    """`layout` without the memo."""
    taken, placed, out = set(), [], []
    skip, inside = (), None
    if window is not None and tuple(window) != (cam.gw, cam.hc):
        # The window first, as the planet would place it.  One row at
        # the centre spans the same arc in both cameras (`_radius`), so
        # a window cell is an overscan cell less the even margin
        # around it, and the window's own placement carries across
        # whole: its cells, its cut names, its budget.
        wgw, whc = window
        dx, dy = (cam.gw - wgw) // 2, (cam.hc - whc) // 2
        wcam = _globe.Camera(cam.lat, cam.lon, cam.zoom * whc / cam.hc,
                             wgw, whc)
        for col, row, text, entry in _layout(cities, wcam, band, lang,
                                             upper_pop):
            col, row = col + dx, row + dy
            out.append((col, row, text, entry))
            placed.append((col, row))
            _claim(taken, col, row, text)
        skip = {id(entry) for _c, _r, _t, entry in out}
        # a city the window's own walk passed over is not placed by
        # the margin's walk either, or the crop would carry one more
        # name than the window built alone
        inside = (dx, dy, dx + wgw, dy + whc)
    _walk(cities, cam, band, lang, upper_pop, taken, placed, out, skip,
          inside)
    return out


def _walk(cities, cam, band, lang, upper_pop, taken, placed, out, skip,
          inside):
    """The biggest-first walk, continued from what is already placed."""
    gw, hc, zoom = cam.gw, cam.hc, cam.zoom
    most = budget(gw, hc, band)
    r = _globe._radius(zoom, hc * 2)
    rx = r * cam.aspect
    phi0, lam0 = math.radians(cam.lat), math.radians(cam.lon)
    sin0, cos0 = math.sin(phi0), math.cos(phi0)
    vx, vy, vz = cos0 * math.cos(lam0), cos0 * math.sin(lam0), sin0
    # The farthest from the view centre a placed city can lie: the
    # screen's own corner, or the visibility gate below, whichever
    # binds first.  A cell over-generous on purpose — the cap only has
    # to pass a city on, never to decide about one.
    rho2 = ((gw / 2.0 + 1.0) / rx) ** 2 + ((hc + 2.0) / r) ** 2
    cap = (math.sqrt(1.0 - rho2) if rho2 < 0.96 else 0.2) - 1e-9
    sin, cos = math.sin, math.cos
    half_w, half_h = gw / 2.0, hc * 2 / 2.0

    for entry, sin_phi, cos_phi, lam, px, py in _city_trig(cities):
        if len(placed) >= most:
            break
        if id(entry) in skip:
            continue
        if px * vx + py * vy + sin_phi * vz < cap:
            continue  # nowhere the screen reaches
        d = lam - lam0
        cos_d = cos(d)
        if sin0 * sin_phi + cos0 * cos_phi * cos_d < 0.2:
            continue  # globe.forward()'s cos_c, with the trig hoisted
        ux = cos_phi * sin(d)
        uy = cos0 * sin_phi - sin0 * cos_phi * cos_d
        col = int(half_w + ux * rx)
        row = int((half_h - uy * r) / 2.0)
        if not (0 <= col < gw and 0 <= row < hc):
            continue
        if inside is not None and (inside[0] <= col < inside[2]
                                   and inside[1] <= row < inside[3]):
            continue  # the window's own walk has had its say
        if (col, row) in taken:
            continue
        # keep labels breathable: skip anything crowding a placed marker
        if any(abs(col - pc) < CROWD_COLS and abs(row - pr) < CROWD_ROWS
               for pc, pr in placed):
            continue
        placed.append((col, row))
        taken.add((col, row))
        name = _localized(entry, lang)
        if upper_pop is not None and entry[2] >= upper_pop:
            # cased before the cut, never after: the caps are what the
            # register draws, so they are what the cells are measured
            # against
            name = name.upper()
        out.append((col, row, _write(taken, col, row, name, gw), entry))


def _claim(taken, col, row, text):
    """Claim the cells a name already cut by `_write` stands in."""
    taken.add((col, row))
    c = col + 1
    for ch in text:
        w = char_width(ch)
        if w == 0:
            continue
        taken.add((c, row))
        if w == 2:
            taken.add((c + 1, row))
        c += w


def _write(taken, col, row, name, gw):
    """The part of `name` that fits to the right of (col, row).

    Claims the cells it uses in `taken` and hands back the text a
    caller may lay down from `col + 1` without checking anything: the
    cut has already been made, and a combining mark rides in its base's
    cell rather than taking one of its own.
    """
    c = col + 1
    kept = []
    prev = None
    for ch in name:
        w = char_width(ch)
        if w == 0 and prev is not None:
            kept.append(ch)   # a combining mark rides in its base's cell
            continue
        if c + w > gw:
            break
        if (c, row) in taken or (w == 2 and (c + 1, row) in taken):
            break
        taken.add((c, row))
        kept.append(ch)
        prev = ch
        if w == 2:
            taken.add((c + 1, row))
        c += w
    return "".join(kept)


def _emit(entries, ink_of, gw, wide_fill):
    """{(col, row): tuple} for a laid-out list, in a caller's own ink.

    `ink_of(entry)` gives (dot ink, label ink, bold) for one city;
    `wide_fill(ink, bold)` gives the sentinel a double-width glyph puts
    in the column it swallows, so the renderer emits nothing there and
    the row stays aligned.  Re-walking `layout`'s text cannot collide:
    the cut was made while the cells were being claimed.
    """
    overlays = {}
    for col, row, text, entry in entries:
        dot_ink, label_ink, bold = ink_of(entry)
        overlays[(col, row)] = (style.GLYPH_GENERIC, dot_ink, bold)
        c = col + 1
        prev = None
        for ch in text:
            w = char_width(ch)
            if w == 0 and prev is not None:
                kept = overlays[prev]
                overlays[prev] = (kept[0] + ch,) + kept[1:]
                continue
            overlays[(c, row)] = (ch, label_ink, bold)
            prev = (c, row)
            if w == 2:
                overlays[(c + 1, row)] = wide_fill(label_ink, bold)
            c += w          # `_write`'s own step, so the two agree
    return overlays


def terrain_overlays(cam, band, lang="en"):
    """{(col, row): (char, None, False)} — the terrain register's names.

    Ink None is the composer's per-cell contrast pick, which is what
    terrain has always done with a city name: the ground under it is a
    hypsometric ramp and no fixed ink reads on all of it.
    """
    return _emit(layout(cam, band, lang),
                 lambda _entry: (None, None, False), cam.gw,
                 lambda ink, bold: ("", ink, False))


def street_overlays(cam, band, palette, lang="en", window=None):
    """{(col, row): (char, ink, bold)} — the street register's names.

    The street map has a ladder of emphasis where terrain has none, and
    it keeps it out here: a city of a million takes the caps register,
    everything else the title case under it, both in `lbl_city` and
    both bold (`style.LABEL_STYLES`).  That is the ladder the tiles'
    own settlements are drawn in at the bands below, so a reader
    zooming out through `GAZETTEER_BAND` and on past the tiles
    altogether sees one register's one convention throughout.

    `window` is `layout`'s: the street build is an overscan live, and
    the window cropped out of it has to carry the planet's own set.
    """
    major = _style(palette, "city_major")
    minor = _style(palette, "city")
    return _emit(
        layout(cam, band, lang, upper_pop=style.CITY_CAPS_POP,
               window=window),
        lambda entry: major if entry[2] >= style.CITY_CAPS_POP else minor,
        cam.gw, lambda ink, bold: ("", ink, False))


def _style(palette, kind):
    """(dot ink, label ink, bold) for one LABEL_STYLES register."""
    ink_key, _case, bold = style.LABEL_STYLES[kind]
    ink = palette.get(ink_key, style._PALETTE_16_DEFAULT)
    return (ink, ink, bold)
