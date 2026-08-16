"""Hover — what is under the pointer, and how the map says so.

Street mode rasterises a road into dots and an ink and then forgets it
was ever a road.  Hover needs that identity back, and there is already a
rule in the renderer that decides which feature a cell belongs to: a
braille cell holds exactly one ink, and who wins is settled by `rank`.
So the stroke pass records the *winner* of that contest per cell, beside
the colour it was already storing, and "what you are hovering" becomes,
by construction, "what you can see there".  The highlight and the
readout can never disagree — the same guarantee that keeps the coastline
from disagreeing with the fill it was derived from.

Three lookups, in the order a reader's eye works:

1.  A placed glyph.  It is literally the mark under the pointer, and it
    sits on cells no stroke may own, so it has to be asked first.
2.  The stroke that owns the cell's ink.  OpenMapTiles keeps road names
    in a separate `transportation_name` layer, so the stroke knows its
    class but never its name; the name index below supplies it, matched
    on class so a motorway crossing a lane is still named the motorway.
3.  The area fill.  Ground is nameless and says nothing, but water is a
    thing rather than a surface: a body of water is the connected
    component of the mask a reader would trace with a finger, and it is
    filed against the shore that encloses it.  So the middle of Graham
    Lake and the rim of it answer identically, and what lights is the
    rim — lifting the fill would be lighting the ground rather than a
    thing standing on it.

Naming is what decides how much lights up.  Segments that share a name
merge into one feature, because OpenStreetMap splits a street at every
junction and a reader pointing at Brighton Avenue means the avenue, not
the block.  Nameless geometry stays per-feature: hover a service alley
and exactly that alley glows, never every alley of its class; hover one
pond and the other ponds stay dark, named or not.

The highlight introduces no new colour.  The style spec allows three
accents (the motorway's amber, the marker's yellow, the route's cyan)
and a fourth would compete with all of them, so a hovered feature is
drawn in *its own* ink pushed toward the top of the luminance ladder,
and bold.  Bold is not decoration here: in the 16-colour palette it is
the bright variant of the very same index, which is this same idea one
rung coarser, and it is the only lift available when the ink is already
white.

What lights is split in two, because a cell holds either braille or a
character and those answer to different questions.  A hovered feature
lights the cells that *draw* it, and the cells that *write its name* —
its own label, wherever the page found room for it.  It never lights a
cell merely because it reached it: a road passing behind "Thompson
Hill" shares two cells with that label and means nothing by them, and
lifting them says the road is called "ll".
"""

from collections import namedtuple

from linecast import _maps_labels, _maps_style as style
from linecast._maps_i18n import ms
from linecast._theme import shift_to_pole

# How far a hovered ink travels toward the pole.  Enough that a whole
# road reads as lit at a glance, short of the ladder's top so a hovered
# service road still cannot be mistaken for a hovered motorway.
HOVER_LIFT = 0.45


class Hit(namedtuple("Hit", "name kind cells glyphs")):
    """What the pointer found: a name (often ""), a word for what it is,
    and the cells that belong to it — split by what is written there.

    `kind` is a maps-i18n key rather than a word, so the readout is
    translated at the last possible moment.  `cells` are cells whose
    braille draws the feature and `glyphs` are cells whose *character*
    names it; either may be empty.

    The split is the whole point.  A label crossing a hovered road
    shares cells with it and means nothing by it — the road passes
    behind the writing — so lighting a cell has to ask what is actually
    printed in it rather than which feature reached it.  Bold the ink
    that draws the thing, and the letters that name that same thing;
    never the letters of some other label that happens to be in the way.
    """
    __slots__ = ()


# A style key is a cartographic class; this is the same class as a
# reader would say it.  Both border classes share one word — the dash
# already says which, and "admin level 4 boundary" is not English.
#
# LINE_STYLES' `route` is deliberately absent: the route is UI rather
# than cartography, it is drawn in its own layer over the view rather
# than into the view's ink contest, and it already names itself in the
# header for as long as it exists.
LINE_WORD = {
    "motorway": "hov_motorway",
    "ramp": "hov_ramp",
    "trunk": "hov_trunk",
    "primary": "hov_primary",
    "secondary": "hov_secondary",
    "minor": "hov_minor",
    "service": "hov_service",
    "path": "hov_path",
    "rail": "hov_rail",
    "transit": "hov_transit",
    "ferry": "hov_ferry",
    "waterway_major": "hov_river",
    "waterway_minor": "hov_stream",
    "aeroway_runway": "hov_runway",
    "aeroway_taxi": "hov_taxiway",
    "border_country": "hov_border",
    "border_state": "hov_border",
    "coast": "hov_coast",
}

# Fill classes are indices into style.FILL_ORDER, so the words come from
# the same order rather than from a second copy of it.  Index 0 is the
# ground, which is not a thing and gets no word.
AREA_WORD = {i: "hov_" + key
             for i, key in enumerate(style.FILL_ORDER) if i}

# A ramp is a class the name layer does not have: OpenMapTiles marks the
# ramp flag on `transportation` and not on `transportation_name`, so a
# slip road's name is filed under the road it leaves.
_SIBLING = {"ramp": ("motorway", "trunk")}


def highlight(color):
    """A hovered ink, one rung further up its own ladder.

    Never a new hue: the feature keeps its identity and simply glows,
    which is the only way to add a fourth emphasis to a palette that has
    already spent its three accents.
    """
    if color is None:
        return None
    return shift_to_pole(color, HOVER_LIFT, lighter=not style._light())


def road_names(view, bbox, graph_w, height_cells, band, lang="en"):
    """{(col, row): {style key: (name, cells)}} for the named road net.

    `transportation_name` carries the names that `transportation` does
    not, over its own copy of the same geometry, so the two are joined
    here the only way a raster can join them: by the cells they share.
    Segments are merged by name first, which is what makes hovering one
    block of a street light the whole street.

    Classes the band does not draw are skipped outright — a name has no
    business claiming a cell where its road is not on screen.
    """
    merged = {}
    for props, parts in _maps_labels._features(
            view, bbox, graph_w, height_cells, "transportation_name",
            dedupe=False):
        key = style.OMT_ROAD_CLASS.get(props.get("class"))
        if key is None or not style.LINE_STYLES[key][1][band]:
            continue
        name = (_maps_labels._name(props, lang)
                or str(props.get("ref") or "").strip())
        if not name:
            continue
        cells = merged.setdefault((key, name), [])
        for part in parts:
            cells.extend(_maps_labels.cell_path(part, graph_w, height_cells))

    index = {}
    for (key, name), cells in merged.items():
        # dict.fromkeys dedupes without disturbing the walk order, so a
        # highlight lights the road end to end rather than in tile order
        frozen = tuple(dict.fromkeys(cells))
        entry = (name, frozen)
        for cell in frozen:
            index.setdefault(cell, {}).setdefault(key, entry)
    return index


class HoverIndex:
    """One view's answer to "what is under (col, row)?".

    Built once with the view and cached with it, so a pointer moving
    across a static map costs a dict lookup and nothing else.
    """

    __slots__ = ("owner", "feats", "names", "marks", "area", "texts",
                 "shore", "_owner_cells", "_mark_cells", "_text_cells")

    def __init__(self, owner, feats, names, marks, area, texts=None,
                 shore=None):
        self.owner = owner      # per-cell ink-contest winner, or None
        self.feats = feats      # owner index -> (style key, name)
        self.names = names      # cell -> {style key: (name, cells)}
        self.marks = marks      # cell -> (i18n key, name, seq)
        self.area = area        # per-cell fill class
        self.texts = texts or {}   # cell -> the name written in it
        self.shore = shore      # water cell -> the feature of its rim

        self._owner_cells = {}
        for row, line in enumerate(owner):
            for col, idx in enumerate(line):
                if idx is not None:
                    self._owner_cells.setdefault(idx, []).append((col, row))
        # A label spans several cells and every one of them should light
        # the whole label, so the marks map is inverted once here.
        self._mark_cells = {}
        for cell, entry in marks.items():
            self._mark_cells.setdefault(entry, []).append(cell)
        # And the written names, so a named feature can find its label.
        self._text_cells = {}
        for cell, name in self.texts.items():
            self._text_cells.setdefault(name, []).append(cell)

    def at(self, col, row):
        """The Hit under a cell, or None where there is nothing to say."""
        if not (0 <= row < len(self.owner)
                and 0 <= col < len(self.owner[0])):
            return None
        cell = (col, row)

        entry = self.marks.get(cell)
        if entry is not None:
            # A glyph is drawn, not stroked: it has no ink of its own to
            # light, and the mark's cells are exactly its characters.
            kind, name, _seq = entry
            return Hit(name, kind, (), tuple(self._mark_cells[entry]))

        idx = self.owner[row][col]
        if idx is not None:
            key, name = self.feats[idx]
            word = LINE_WORD.get(key, "")
            if key == "coast" and name:
                # The edge of a named body is that body, not "coastline".
                # A reader pointing at the rim of Graham Lake has pointed
                # at Graham Lake, and gets the same answer the middle of
                # it gives — one thing cannot have two readouts.
                word = AREA_WORD[style.FILL_ORDER.index("water")]
            found = self._named(cell, key)
            if found is not None:
                return Hit(found[0], word, found[1], self._written(found[0]))
            return Hit(name, word, tuple(self._owner_cells.get(idx, ())),
                       self._written(name))

        word = AREA_WORD.get(self.area[row][col])
        if not word:
            return None
        # A body of water answers for the fill it paints: the same
        # feature its rim answers for, so the middle of a lake and the
        # edge of it can never say different things.  What lights is
        # that rim and never the fill — a fill is painted behind
        # everything, and lifting it would light the ground rather than
        # a thing standing on it.  Ground that is only ground stays
        # nameless and lights nothing, as it always did.
        idx = self.shore[row][col] if self.shore is not None else None
        if idx is None:
            return Hit("", word, (), ())
        name = self.feats[idx][1]
        return Hit(name, word, tuple(self._owner_cells.get(idx, ())),
                   self._written(name))

    def _written(self, name):
        """The cells where this feature's own name is written, if any.

        A road label is not a mark — it is laid across the road it names
        rather than anchored to a point — so the link back is the name
        itself.  A nameless feature has no label to light, and a name
        the page had no room for simply is not in the index.
        """
        return tuple(self._text_cells.get(name, ())) if name else ()

    def _named(self, cell, key):
        """The name filed against a cell for a stroke's class, or None.

        Exact class, then the class a ramp's name is filed under, and
        then nothing.  Taking the only name at a cell when no class
        matches was measured over downtown Portland: it names 13% more
        cells and every one of them is a class disagreement, which is
        how the shoreline ends up labelled after the trail beside it.
        A road that reports its class and not its name has told the
        truth; the house rule is to drop rather than guess.
        """
        at = self.names.get(cell)
        if not at:
            return None
        found = at.get(key)
        if found is not None:
            return found
        for sibling in _SIBLING.get(key, ()):
            if sibling in at:
                return at[sibling]
        return None


def readout(hit, lang="en"):
    """`Brighton Avenue · street`, or just one half of it.

    Placenames are the data's own and are never translated; the class
    word always is.  A feature with neither is not worth a readout, and
    `at` will not have returned one.

    A legend gloss lists alternatives — "civic · school", "museum ·
    sight" — because a legend row has to cover the glyph's whole range.
    A pointer is over one thing, so it takes the general term, which is
    the first by construction of that table; the alternatives would
    otherwise arrive wearing the readout's own separator and read as
    three facts rather than two.
    """
    word = ms(hit.kind, lang).split(" · ")[0] if hit.kind else ""
    if hit.name and word:
        return f"{hit.name} · {word}"
    return hit.name or word
