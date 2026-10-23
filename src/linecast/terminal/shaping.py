"""Arabic shaping: each Arabic-script letter in the form its neighbours
give it.

A terminal draws each character on its own, so a word in Arabic,
Persian or Urdu sent as it is stored comes out as a row of isolated
letters.  shape gives each letter of a row its initial, medial, final
or isolated presentation form, by whether its neighbours join it
(joining_type).  The forms come from unicodedata alone (every
presentation form decomposes as <initial>, <medial>, <final> or
<isolated> of its letter), so there is no table to keep.  لا stays two
cells, lam and alef, rather than the one-glyph ligature: terminal/bidi.py,
which calls this, may move cells but never add or remove one.
"""

import unicodedata

_FORMS = {}       # letter -> {"isolated": ch, "final": ch, ...}


def _build_forms():
    for block in ((0xFB50, 0xFDFF), (0xFE70, 0xFEFF)):
        for o in range(block[0], block[1] + 1):
            ch = chr(o)
            d = unicodedata.decomposition(ch)
            if not d.startswith("<"):
                continue
            tag, _sep, rest = d.partition(" ")
            codes = rest.split()
            if len(codes) != 1 or tag not in ("<isolated>", "<final>",
                                               "<initial>", "<medial>"):
                continue
            base = chr(int(codes[0], 16))
            # The first form listed for a letter is its own; later ones
            # are compatibility duplicates.
            _FORMS.setdefault(base, {}).setdefault(tag[1:-1], ch)


_build_forms()

ZWNJ, ZWJ, _TATWEEL = "\u200c", "\u200d", "\u0640"
_HEH_HAMZA = "\u0647\u0654"


def joining_type(ch):
    """D (dual), R (right, to the letter before only), C (join causing),
    T (transparent), or U (non-joining), from the presentation forms."""
    forms = _FORMS.get(ch)
    if forms:
        if "initial" in forms or "medial" in forms:
            return "D"
        if "final" in forms:
            return "R"
        return "U"
    if ch in (ZWJ, _TATWEEL):
        return "C"
    if unicodedata.category(ch) in ("Mn", "Me") or ch == "\u200b":
        return "T"
    return "U"


def is_arabic_letter(ch):
    """Whether `ch` is a letter of the Arabic script: one with
    presentation forms, or in the Arabic block's runs of letters."""
    return ch in _FORMS or "\u0620" <= ch <= "\u064a" or "\u066e" <= ch <= "\u06d3"


def shape(cells):
    """Replace each Arabic-script letter's base character in `cells`
    (lists of [text, ...]) with its contextual presentation form."""
    for cell in cells:
        if cell[0].startswith(_HEH_HAMZA):
            # The ezafe after a silent he, as the Academy spells it, is
            # drawn as the one letter that has forms of its own: a mark
            # over a presentation form sits badly in a terminal's cell
            cell[0] = "\u06c0" + cell[0][2:]
    n = len(cells)
    kinds = []
    for cell in cells:
        text = cell[0]
        jt = joining_type(text[0])
        forward = jt in ("D", "C") or (ZWJ in text[1:] and jt != "U")
        if ZWNJ in text[1:]:
            forward = False
        kinds.append((jt, forward))
    for i in range(n):
        jt, forward = kinds[i]
        if jt not in ("D", "R"):
            continue
        # The neighbours, skipping transparent cells
        p = i - 1
        while p >= 0 and kinds[p][0] == "T":
            p -= 1
        q = i + 1
        while q < n and kinds[q][0] == "T":
            q += 1
        joins_prev = p >= 0 and kinds[p][1]
        joins_next = (forward and jt == "D" and q < n
                      and kinds[q][0] in ("D", "R", "C"))
        form = ("medial" if joins_prev and joins_next else
                "final" if joins_prev else
                "initial" if joins_next else "isolated")
        forms = _FORMS.get(cells[i][0][0], {})
        glyph = (forms.get(form)
                 or (forms.get("final") if form == "medial" else None)
                 or (forms.get("isolated") if form in ("initial", "final") else None))
        if glyph:
            cells[i][0] = glyph + cells[i][0][1:]


# Every presentation form: a letter already shaped
FORM_CHARS = frozenset(f for forms in _FORMS.values() for f in forms.values())
