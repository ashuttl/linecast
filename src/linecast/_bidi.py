"""Right-to-left text on a terminal: the output pass that puts each row
in display order.

Strings stay in logical order everywhere in linecast, first letter
first, and the views lay a frame out in columns from them.  Most
terminals draw cells exactly as they are sent: they neither reorder
right-to-left text nor join Arabic letters, so a Persian or Hebrew word
sent as it is stored comes out backwards, and Arabic-script letters
each in their isolated form.  The terminals that do reorder (VTE, and
Konsole) do it per line, treating a whole row as one paragraph, which
scrambles a row that holds a graph, a column of numbers, and a label.
So linecast does the work itself, as Egmont Koblinger's "BiDi in
Terminal Emulators" recommends for full-screen programs: it reorders
and shapes each row here, and asks the terminal to draw cells as sent
(explicit mode, CSI 8 l; see TERMINAL_EXPLICIT).

A row goes through these steps, all of them skipped for a row with no
right-to-left character and no bidi control, which is almost every row
of a map or a radar frame:

1. The row is split into cells -- a character with the marks and
   joiners that ride on it -- each carrying the SGR state it was drawn
   in.
2. Arabic-script letters are shaped: each becomes its initial, medial,
   final or isolated presentation form by whether its neighbours join
   it.  The forms come from unicodedata alone (every presentation form
   decomposes as <initial>, <medial>, <final> or <isolated> of its
   letter), so there is no table to keep.  لا stays two cells, lam and
   alef, rather than the one-glyph ligature: a frame is laid out in
   cells before this pass runs, and the pass may move cells but never
   add or remove one.
3. The row is cut into segments: stretches of text between graphics
   (block elements, braille, box drawing, the icon fonts' private use
   area) and gaps of two or more spaces.  Each segment is its own
   paragraph, so two place names over the sea keep their places, and a
   graph between two labels never reverses.  A segment reads right to
   left if the interface language does and it holds right-to-left
   text, else by its first strong character, as an HTML dir="auto"
   element does.  A view can say more with Unicode isolates (RLI, LRI,
   FSI ... PDI), which take no cells and which this pass removes.
4. Each segment is ordered by the Unicode Bidirectional Algorithm
   (UAX #9, checked against Unicode's BidiCharacterTest.txt), and
   brackets and other mirrored characters in right-to-left runs are
   drawn mirrored.
5. Digits are written in the reader's digit set (Persian ۰-۹), except
   inside an LRI isolate, which is how a view marks an identifier.
6. The cells go out in display order, each in its own SGR state.
"""

import os
import re
import unicodedata

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Explicit mode: the terminal draws cells in the order they are sent and
# leaves shaping to the program (Koblinger's BDSM, reset).  A terminal
# that does not know the mode ignores it, as it does any unknown mode.
TERMINAL_EXPLICIT = "\033[8l"
TERMINAL_IMPLICIT = "\033[8h"

# The digit sets, by language.  Persian and Urdu write the extended
# Arabic-Indic digits, U+06F0-06F9; the decimal separator is U+066B and
# the percent sign U+066A.
_DIGIT_SETS = {"fa": "۰۱۲۳۴۵۶۷۸۹"}
_DECIMAL_MARK = "٫"
_PERCENT_SIGN = "٪"

_ui_rtl = False
_digits = None        # the digits to write, or None to leave them be
_to_latin = False     # write native digits back as ASCII (LINECAST_DIGITS=latin)
_reorder = True       # False: the terminal orders the text itself


def configure(lang="en", environ=None):
    """Set the pass up for the interface language `lang`.

    LINECAST_BIDI=terminal leaves the text in logical order for a
    terminal that reorders and shapes by itself and cannot be told not
    to; LINECAST_DIGITS=latin keeps ASCII digits in a language that has
    its own."""
    global _ui_rtl, _digits, _to_latin, _reorder
    from linecast._i18n import base_language, is_rtl
    env = os.environ if environ is None else environ
    lang = base_language(lang or "en")
    _ui_rtl = is_rtl(lang)
    choice = str(env.get("LINECAST_DIGITS", "")).strip().lower()
    if not choice:
        try:
            from linecast._config import load_config
            choice = str(load_config().get("digits", "")).strip().lower()
        except Exception:
            choice = ""
    native = _DIGIT_SETS.get(lang)
    _to_latin = choice == "latin"
    _digits = None if (_to_latin or native is None) else native
    _reorder = bidi_mode(env) == "linecast"


def bidi_mode(environ=None):
    """Who puts right-to-left text in order: "linecast" (this pass, the
    default) or "terminal"."""
    env = os.environ if environ is None else environ
    value = str(env.get("LINECAST_BIDI", "")).strip().lower()
    if value in ("terminal", "off", "0", "no", "false"):
        return "terminal"
    return "linecast"


def reorders():
    """Whether this pass puts rows in display order (and explicit mode
    should be asked of the terminal)."""
    return _reorder


def ui_rtl():
    """Whether the interface language reads right to left."""
    return _ui_rtl


def active():
    """Whether display() can change anything at all."""
    return _reorder or _digits is not None or _to_latin


# ---------------------------------------------------------------------------
# Marking text
# ---------------------------------------------------------------------------
LRI, RLI, FSI, PDI = "\u2066", "\u2067", "\u2068", "\u2069"


def isolate(text, direction="auto"):
    """`text` as its own paragraph: "rtl", "ltr", or "auto" (by its
    first strong character).  The isolate characters take no cells."""
    if not text:
        return text
    mark = {"rtl": RLI, "ltr": LRI}.get(direction, FSI)
    return f"{mark}{text}{PDI}"


def ui_text(text):
    """Interface text in the interface language's direction: a Persian
    sentence that opens with a Latin place name still reads from the
    right.  Unchanged in a left-to-right language."""
    return isolate(text, "rtl") if _ui_rtl and text else text


def identifier(text):
    """Text that keeps its own order and its ASCII digits in any
    language: a version, a station id, a key, a URL."""
    return isolate(text, "ltr") if text else text


# ---------------------------------------------------------------------------
# Character data
# ---------------------------------------------------------------------------

# Everything the pass has to look at a row for: the right-to-left
# blocks (Hebrew through Arabic Extended, the presentation forms, and
# the historic scripts of the SMP) and the bidi controls.
_RTL_OR_CONTROL = re.compile(
    "[\u0590-\u08ff\ufb1d-\ufdff\ufe70-\ufeff\U00010800-\U00010fff"
    "\U0001e800-\U0001efff\u200e\u200f\u061c\u202a-\u202e\u2066-\u2069]")

# Bracket pairs (BidiBrackets.txt), opening then closing.  U+2329/232A
# are canonically U+3008/3009 and are folded to them.
_BRACKETS = ("()[]{}༺༻༼༽᚛᚜⁅⁆⁽⁾₍₎⌈⌉⌊⌋\u3008\u3009❨❩❪❫❬❭❮❯❰❱❲❳❴❵⟅⟆⟦⟧⟨⟩⟪⟫⟬⟭⟮⟯⦃⦄⦅⦆"
             "⦇⦈⦉⦊⦋⦌⦍⦐⦏⦎⦑⦒⦓⦔⦕⦖⦗⦘⧘⧙⧚⧛⧼⧽⸢⸣⸤⸥⸦⸧⸨⸩⹕⹖⹗⹘⹙⹚⹛⹜\u3008\u3009《》「」『』"
             "【】〔〕〖〗〘〙〚〛﹙﹚﹛﹜﹝﹞（）［］｛｝｟｠｢｣")
_OPENING = {_BRACKETS[i]: _BRACKETS[i + 1] for i in range(0, len(_BRACKETS), 2)}
_CLOSING = {close: opening for opening, close in _OPENING.items()}
_BRACKET_FOLD = {"\u2329": "\u3008", "\u232a": "\u3009"}

# Characters drawn mirrored in a right-to-left run (BidiMirroring.txt,
# the pairs that mirror each other), paired up.
_MIRROR_PAIRS = (
    "()<>[]{}«»༺༻༼༽᚛᚜‹›⁅⁆⁽⁾₍₎∈∋∉∌∊∍∕⧵∟⯾∠⦣∡⦛∢⦠∤⫮∼∽≃⋍≅≌≒≓≔≕≤≥≦≧≨≩≪≫≮≯≰≱≲≳≴≵≶≷"
    "≸≹≺≻≼≽≾≿⊀⊁⊂⊃⊄⊅⊆⊇⊈⊉⊊⊋⊏⊐⊑⊒⊘⦸⊢⊣⊦⫞⊨⫤⊩⫣⊫⫥⊰⊱⊲⊳⊴⊵⊶⊷⊸⟜⋉⋊⋋⋌⋐⋑⋖⋗⋘⋙⋚⋛⋜⋝⋞⋟⋠⋡⋢⋣⋤⋥⋦⋧"
    "⋨⋩⋪⋫⋬⋭⋰⋱⋲⋺⋳⋻⋴⋼⋶⋽⋷⋾⌈⌉⌊⌋\u3008\u3009❨❩❪❫❬❭❮❯❰❱❲❳❴❵⟃⟄⟅⟆⟈⟉⟋⟍⟓⟔⟕⟖⟝⟞⟢⟣⟤⟥⟦⟧⟨⟩⟪⟫⟬⟭⟮⟯"
    "⦃⦄⦅⦆⦇⦈⦉⦊⦋⦌⦍⦐⦎⦏⦑⦒⦓⦔⦕⦖⦗⦘⦤⦥⦨⦩⦪⦫⦬⦭⦮⦯⧀⧁⧄⧅⧏⧐⧑⧒⧔⧕⧘⧙⧚⧛⧨⧩⧸⧹⧼⧽⨫⨬⨭⨮⨴⨵⨼⨽"
    "⩤⩥⩹⩺⩻⩼⩽⩾⩿⪀⪁⪂⪃⪄⪅⪆⪇⪈⪉⪊⪋⪌⪍⪎⪏⪐⪑⪒⪓⪔⪕⪖⪗⪘⪙⪚⪛⪜⪝⪞⪟⪠⪡⪢⪦⪧⪨⪩⪪⪫⪬⪭⪯⪰⪱⪲⪳⪴⪵⪶"
    "⪷⪸⪹⪺⪻⪼⪽⪾⪿⫀⫁⫂⫃⫄⫅⫆⫇⫈⫉⫊⫋⫌⫍⫎⫏⫐⫑⫒⫓⫔⫕⫖⫬⫭⫷⫸⫹⫺⸂⸃⸄⸅⸉⸊⸌⸍⸜⸝⸠⸡⸢⸣⸤⸥⸦⸧⸨⸩⹕⹖⹗⹘"
    "⹙⹚⹛⹜\u3008\u3009《》「」『』【】〔〕〖〗〘〙〚〛﹙﹚﹛﹜﹝﹞﹤﹥（）＜＞［］｛｝｟｠｢｣")
_MIRROR = {}
for _i in range(0, len(_MIRROR_PAIRS), 2):
    _a, _b = _MIRROR_PAIRS[_i], _MIRROR_PAIRS[_i + 1]
    _MIRROR[_a], _MIRROR[_b] = _b, _a
del _i, _a, _b

_STRONG_R = frozenset(("R", "AL"))
_ISOLATE_INITIATORS = frozenset(("LRI", "RLI", "FSI"))
_EMBEDDINGS = frozenset(("LRE", "RLE", "LRO", "RLO"))
_REMOVED = frozenset(("LRE", "RLE", "LRO", "RLO", "PDF", "BN"))
_NEUTRAL_OR_ISOLATE = frozenset(("B", "S", "WS", "ON", "LRI", "RLI", "FSI", "PDI"))
_MAX_DEPTH = 125


def _is_graphic(ch):
    """A character that draws a picture, not text: it separates the
    segments of a row and never moves."""
    o = ord(ch)
    return (0x2500 <= o <= 0x259F        # box drawing, block elements
            or 0x2800 <= o <= 0x28FF     # braille
            or 0xE000 <= o <= 0xF8FF     # the icon fonts' private use area
            or 0xF0000 <= o <= 0x10FFFD
            or 0x1FB00 <= o <= 0x1FBFF)  # legacy computing: sextants


def bidi_class(ch):
    """The UAX #9 class of one character, with unassigned code points in
    the right-to-left blocks defaulting to R as the standard has it."""
    cls = unicodedata.bidirectional(ch)
    if cls:
        return cls
    o = ord(ch)
    if 0x0600 <= o <= 0x08FF or 0xFB50 <= o <= 0xFDFF or 0xFE70 <= o <= 0xFEFF:
        return "AL"
    if 0x0590 <= o <= 0x05FF or 0x07C0 <= o <= 0x085F or 0x10800 <= o <= 0x10FFF:
        return "R"
    return "L"


# ---------------------------------------------------------------------------
# The Unicode Bidirectional Algorithm
# ---------------------------------------------------------------------------
def _first_strong(types, start, end, matching_pdi):
    """P2/P3 over types[start:end]: 0 for L, 1 for R/AL, None for
    neither, skipping what lies inside isolates."""
    i = start
    while i < end:
        t = types[i]
        if t == "L":
            return 0
        if t in _STRONG_R:
            return 1
        if t in _ISOLATE_INITIATORS:
            j = matching_pdi.get(i)
            if j is None:
                return None
            i = j
        i += 1
    return None


def _match_isolates(types):
    """BD9: the PDI that closes each isolate initiator, by index."""
    matching = {}
    stack = []
    for i, t in enumerate(types):
        if t in _ISOLATE_INITIATORS:
            stack.append(i)
        elif t == "PDI" and stack:
            matching[stack.pop()] = i
        elif t == "B":
            stack.clear()
    return matching


def resolve_levels(types, base=None, brackets=None):
    """Embedding levels for a paragraph of bidi classes, per UAX #9.

    `base` is 0 or 1, or None to take it from the first strong
    character (P2, P3).  `brackets` gives, per position, the opening
    bracket a character pairs as and whether it opens (``(ch, True)``),
    or None.  Returns (paragraph level, levels), with None for the
    characters X9 removes.  Rule L1 is applied; the reordering is
    visual_order's."""
    n = len(types)
    types = list(types)
    original = list(types)
    matching_pdi = _match_isolates(types)
    matched_pdis = set(matching_pdi.values())
    if base is None:
        base = _first_strong(types, 0, n, matching_pdi) or 0
    levels = [base] * n

    # X1-X8: explicit levels and directions
    stack = [(base, None, False)]    # (level, override, isolate)
    overflow_isolate = overflow_embedding = valid_isolate = 0
    for i, t in enumerate(types):
        level, override, _iso = stack[-1]
        if t in _EMBEDDINGS:
            rtl = t in ("RLE", "RLO")
            new = (level + 1) | 1 if rtl else (level + 2) & ~1
            if new <= _MAX_DEPTH and not overflow_isolate and not overflow_embedding:
                ovr = {"LRO": "L", "RLO": "R"}.get(t)
                stack.append((new, ovr, False))
            elif not overflow_isolate:
                overflow_embedding += 1
            levels[i] = level
        elif t in _ISOLATE_INITIATORS:
            levels[i] = level
            if override:
                types[i] = override
            if t == "FSI":
                end = matching_pdi.get(i, n)
                rtl = _first_strong(original, i + 1, end, matching_pdi) == 1
            else:
                rtl = t == "RLI"
            new = (level + 1) | 1 if rtl else (level + 2) & ~1
            if new <= _MAX_DEPTH and not overflow_isolate and not overflow_embedding:
                valid_isolate += 1
                stack.append((new, None, True))
            else:
                overflow_isolate += 1
        elif t == "PDI":
            if overflow_isolate:
                overflow_isolate -= 1
            elif valid_isolate:
                overflow_embedding = 0
                while not stack[-1][2]:
                    stack.pop()
                stack.pop()
                valid_isolate -= 1
            level, override, _iso = stack[-1]
            levels[i] = level
            if override:
                types[i] = override
        elif t == "PDF":
            if overflow_isolate:
                pass
            elif overflow_embedding:
                overflow_embedding -= 1
            elif not stack[-1][2] and len(stack) >= 2:
                stack.pop()
            levels[i] = level
        elif t == "B":
            levels[i] = base
        else:
            levels[i] = level
            if override and t != "BN":
                types[i] = override

    # X9: the removed characters take no part from here
    kept = [i for i in range(n) if original[i] not in _REMOVED]

    # X10: level runs, chained into isolating run sequences
    runs = []
    for i in kept:
        if runs and levels[runs[-1][-1]] == levels[i]:
            runs[-1].append(i)
        else:
            runs.append([i])
    run_of_start = {run[0]: k for k, run in enumerate(runs)}
    sequences = []
    for run in runs:
        first = run[0]
        if original[first] == "PDI" and first in matched_pdis:
            continue           # carried on from its initiator's sequence
        seq = list(run)
        while True:
            last = seq[-1]
            if original[last] in _ISOLATE_INITIATORS and last in matching_pdi:
                k = run_of_start.get(matching_pdi[last])
                if k is None:
                    break
                seq.extend(runs[k])
            else:
                break
        sequences.append(seq)

    position = {i: p for p, i in enumerate(kept)}
    embedding = list(levels)       # sos and eos read these, not resolved ones
    for seq in sequences:
        _resolve_sequence(seq, types, original, levels, embedding, kept,
                          position, base, matching_pdi, brackets)

    # L1: separators and trailing whitespace back to the paragraph level
    trailing = True
    for i in range(n - 1, -1, -1):
        t = original[i]
        if t in ("S", "B"):
            levels[i] = base
            trailing = True
        elif t in ("WS", "LRI", "RLI", "FSI", "PDI") or t in _REMOVED:
            if trailing:
                levels[i] = base
        else:
            trailing = False
    for i in range(n):
        if original[i] in _REMOVED:
            levels[i] = None
    return base, levels


def _resolve_sequence(seq, types, original, levels, embedding, kept, position,
                      base, matching_pdi, brackets):
    """W1-W7, N0-N2, and I1-I2 for one isolating run sequence."""
    level = embedding[seq[0]]
    first, last = seq[0], seq[-1]
    p = position[first]
    before = embedding[kept[p - 1]] if p > 0 else base
    p = position[last]
    if original[last] in _ISOLATE_INITIATORS:
        after = base       # an isolate the paragraph ends inside
    else:
        after = embedding[kept[p + 1]] if p + 1 < len(kept) else base
    sos = "R" if max(before, level) % 2 else "L"
    eos = "R" if max(after, level) % 2 else "L"
    e = "R" if level % 2 else "L"
    t = [types[i] for i in seq]
    m = len(t)

    # W1
    prev = sos
    for k in range(m):
        if t[k] == "NSM":
            t[k] = "ON" if prev in ("LRI", "RLI", "FSI", "PDI") else prev
        prev = t[k]
    # W2, W3
    strong = sos
    for k in range(m):
        if t[k] in ("L", "R", "AL"):
            strong = t[k]
        elif t[k] == "EN" and strong == "AL":
            t[k] = "AN"
    for k in range(m):
        if t[k] == "AL":
            t[k] = "R"
    # W4
    for k in range(1, m - 1):
        if t[k] == "ES" and t[k - 1] == "EN" and t[k + 1] == "EN":
            t[k] = "EN"
        elif t[k] == "CS" and t[k - 1] == t[k + 1] and t[k - 1] in ("EN", "AN"):
            t[k] = t[k - 1]
    # W5
    k = 0
    while k < m:
        if t[k] == "ET":
            j = k
            while j < m and t[j] == "ET":
                j += 1
            if (k > 0 and t[k - 1] == "EN") or (j < m and t[j] == "EN"):
                for q in range(k, j):
                    t[q] = "EN"
            k = j
        else:
            k += 1
    # W6
    for k in range(m):
        if t[k] in ("ES", "ET", "CS"):
            t[k] = "ON"
    # W7
    strong = sos
    for k in range(m):
        if t[k] in ("L", "R"):
            strong = t[k]
        elif t[k] == "EN" and strong == "L":
            t[k] = "L"

    # N0: bracket pairs
    if brackets is not None:
        pairs = []
        stack = []
        for k in range(m):
            b = brackets[seq[k]]
            if b is None or t[k] != "ON":
                continue
            ch, opens = b
            if opens:
                if len(stack) == 63:
                    break
                stack.append((ch, k))
            else:
                for s in range(len(stack) - 1, -1, -1):
                    if stack[s][0] == ch:
                        pairs.append((stack[s][1], k))
                        del stack[s:]
                        break
        pairs.sort()

        def _dir(x):
            return "L" if x == "L" else "R" if x in ("R", "EN", "AN") else None

        for open_k, close_k in pairs:
            found_e = found_other = False
            for q in range(open_k + 1, close_k):
                d = _dir(t[q])
                if d == e:
                    found_e = True
                    break
                if d is not None:
                    found_other = True
            if found_e:
                new = e
            elif found_other:
                ctx = sos
                for q in range(open_k - 1, -1, -1):
                    d = _dir(t[q])
                    if d is not None:
                        ctx = d
                        break
                new = ctx if ctx != e else e
            else:
                continue
            for q in (open_k, close_k):
                t[q] = new
                # NSMs after a bracket follow its new direction
                r = q + 1
                while r < m and original[seq[r]] == "NSM":
                    t[r] = new
                    r += 1

    # N1, N2
    k = 0
    while k < m:
        if t[k] in _NEUTRAL_OR_ISOLATE or t[k] == "BN":
            j = k
            while j < m and (t[j] in _NEUTRAL_OR_ISOLATE or t[j] == "BN"):
                j += 1
            lead = sos if k == 0 else t[k - 1]
            trail = eos if j == m else t[j]
            lead = "R" if lead in ("R", "EN", "AN") else lead
            trail = "R" if trail in ("R", "EN", "AN") else trail
            fill = lead if lead == trail and lead in ("L", "R") else e
            for q in range(k, j):
                t[q] = fill
            k = j
        else:
            k += 1

    # I1, I2
    for k in range(m):
        i = seq[k]
        x = t[k]
        if level % 2 == 0:
            if x == "R":
                levels[i] = level + 1
            elif x in ("AN", "EN"):
                levels[i] = level + 2
        elif x in ("L", "EN", "AN"):
            levels[i] = level + 1


def visual_order(levels):
    """L2: the logical indices in display order, left to right, leaving
    out the characters whose level is None."""
    order = [i for i, lv in enumerate(levels) if lv is not None]
    if not order:
        return order
    lv = [levels[i] for i in order]
    high = max(lv)
    low_odd = min(x for x in lv) | 1
    if low_odd > high:
        return order
    for level in range(high, low_odd - 1, -1):
        k = 0
        while k < len(order):
            if lv[k] >= level:
                j = k
                while j < len(order) and lv[j] >= level:
                    j += 1
                order[k:j] = order[k:j][::-1]
                lv[k:j] = lv[k:j][::-1]
                k = j
            else:
                k += 1
    return order


def bracket_info(ch):
    """(opening bracket, opens?) for a paired bracket, else None."""
    ch = _BRACKET_FOLD.get(ch, ch)
    if ch in _OPENING:
        return (ch, True)
    if ch in _CLOSING:
        return (_CLOSING[ch], False)
    return None


# ---------------------------------------------------------------------------
# Arabic shaping
# ---------------------------------------------------------------------------
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

_ZWNJ, _ZWJ, _TATWEEL = "\u200c", "\u200d", "\u0640"


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
    if ch in (_ZWJ, _TATWEEL):
        return "C"
    if unicodedata.category(ch) in ("Mn", "Me") or ch == "\u200b":
        return "T"
    return "U"


def _shape(cells):
    """Replace each Arabic-script letter's base character in `cells`
    (lists of [text, ...]) with its contextual presentation form."""
    n = len(cells)
    kinds = []
    for cell in cells:
        text = cell[0]
        jt = joining_type(text[0])
        forward = jt in ("D", "C") or (_ZWJ in text[1:] and jt != "U")
        if _ZWNJ in text[1:]:
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


# ---------------------------------------------------------------------------
# The pass
# ---------------------------------------------------------------------------
# Escapes: SGR, which is carried with each cell; OSC 8, a hyperlink,
# carried the same way; any other CSI (a cursor move) cuts the text into
# pieces that are ordered apart.
_ESCAPE = re.compile(r"\033\[[0-9;:<=>?]*[ -/]*[@-~]|\033\][^\033\a]*(?:\033\\|\a)")
_SGR = re.compile(r"\033\[[0-9;:]*m\Z")
_DIGIT = re.compile(r"[0-9۰-۹]")

_CONTROLS = frozenset("\u200e\u200f\u061c\u202a\u202b\u202c\u202d\u202e"
                      "\u2066\u2067\u2068\u2069")
# What rides on the cell before it: marks, joiners, variation selectors
_RIDERS = frozenset(("Mn", "Me"))


def _rides(ch):
    return (unicodedata.category(ch) in _RIDERS
            or ch in "\u200c\u200d\ufe0e\ufe0f")


def display(text):
    """`text` -- one row, or a floating overlay of cursor-addressed
    pieces -- as it should be sent to the terminal."""
    if not text or not active():
        return text
    needs_order = _reorder and _RTL_OR_CONTROL.search(text) is not None
    needs_digits = (_digits is not None or _to_latin) and _DIGIT.search(text) is not None
    if not needs_order and not needs_digits:
        return text
    if "\n" in text:
        return "\n".join(display(line) for line in text.split("\n"))
    if not needs_order:
        return _digits_only(text)
    # Cut at the escapes that move the cursor: each piece is ordered on
    # its own, starting in the SGR state the piece before left.
    out = []
    tokens = []
    pos = 0
    state = ("", "")
    for m in _ESCAPE.finditer(text):
        if m.start() > pos:
            tokens.append(("t", text[pos:m.start()]))
        seq = m.group()
        if _SGR.match(seq) or seq.startswith("\033]8;"):
            tokens.append(("e", seq))
        else:
            piece, state = _order_piece(tokens, state)
            out.append(piece)
            out.append(seq)
            tokens = []
        pos = m.end()
    if pos < len(text):
        tokens.append(("t", text[pos:]))
    out.append(_order_piece(tokens, state)[0])
    return "".join(out)


def _next_state(state, seq):
    """The (SGR, hyperlink) state after the escape `seq`."""
    sgr, link = state
    if seq.startswith("\033]"):
        closing = seq.startswith("\033]8;;\033") or seq.startswith("\033]8;;\a")
        return sgr, ("" if closing else seq)
    params = seq[2:-1]
    if params in ("", "0"):
        return "", link
    if params.startswith("0;"):
        return seq, link
    return sgr + seq, link


def _set_state(have, want):
    """Escapes that take the terminal from state `have` to `want`."""
    out = ""
    if have[0] != want[0]:
        out += want[0] if want[0].startswith("\033[0;") else "\033[0m" + want[0]
    if have[1] != want[1]:
        out += want[1] or "\033]8;;\033\\"
    return out


def for_stream(text, stream=None):
    """`text` for `stream`: in display order on a terminal; in logical
    order to a pipe, for waybar or polybar, whose renderers reorder and
    shape by themselves, with only the digits changed."""
    import sys
    stream = sys.stdout if stream is None else stream
    try:
        tty = stream.isatty()
    except Exception:
        tty = False
    if tty:
        return display(text)
    if _digits is None and not _to_latin:
        return text
    return "\n".join(_digits_only(line) for line in text.split("\n"))


def _localise(ch):
    if _to_latin:
        o = ord(ch)
        if 0x06F0 <= o <= 0x06F9:
            return chr(o - 0x06F0 + 0x30)
        if 0x0660 <= o <= 0x0669:
            return chr(o - 0x0660 + 0x30)
        return {_DECIMAL_MARK: ".", _PERCENT_SIGN: "%"}.get(ch, ch)
    if "0" <= ch <= "9":
        return _digits[ord(ch) - 0x30]
    return ch


def _digits_only(text):
    """Digits in the reader's set, outside the escapes and identifiers."""
    parts = []
    pos = 0
    for m in _ESCAPE.finditer(text):
        parts.append(_digit_text(text[pos:m.start()]))
        parts.append(m.group())
        pos = m.end()
    parts.append(_digit_text(text[pos:]))
    return "".join(parts)


_POINT = re.compile(r"(?<=[0-9])\.(?=[0-9])")
_PERCENT_AFTER = re.compile(r"(?<=[0-9])%")
_TO_NATIVE = {}
_TO_LATIN = {**{0x06F0 + d: 0x30 + d for d in range(10)},
             **{0x0660 + d: 0x30 + d for d in range(10)},
             ord(_DECIMAL_MARK): ".", ord(_PERCENT_SIGN): "%"}


def _digit_text(s):
    if not s or not _DIGIT.search(s):
        return s
    if _to_latin:
        return s.translate(_TO_LATIN)
    table = _TO_NATIVE.get(_digits)
    if table is None:
        table = _TO_NATIVE[_digits] = {0x30 + d: _digits[d] for d in range(10)}
    if "." in s:
        s = _POINT.sub(_DECIMAL_MARK, s)
    if "%" in s:
        s = _PERCENT_AFTER.sub(_PERCENT_SIGN, s)
    return s.translate(table)


def _convert_digits(chars, protected):
    """Convert, in place, the digits of a logical sequence of cell texts,
    with a decimal point between two digits and a percent sign after one
    written the reader's way."""
    n = len(chars)
    for i in range(n):
        if protected[i]:
            continue
        c = chars[i]
        if not c:
            continue
        ch = c[0]
        if _to_latin:
            new = _localise(ch)
        elif "0" <= ch <= "9":
            new = _localise(ch)
        elif ch == "." and 0 < i < n - 1 and _is_digit(chars[i - 1]) and _is_digit(chars[i + 1]):
            new = _DECIMAL_MARK
        elif ch == "%" and i > 0 and _is_digit(chars[i - 1]):
            new = _PERCENT_SIGN
        else:
            continue
        chars[i] = new + c[1:]


def _is_digit(c):
    return bool(c) and ("0" <= c[0] <= "9" or "۰" <= c[0] <= "۹")


def _order_piece(tokens, state):
    """One piece of a row in display order, from ("t", text) and
    ("e", escape) tokens, starting in `state`.  Returns the piece and
    the state it leaves the terminal in."""
    if not any(kind == "t" and _RTL_OR_CONTROL.search(s) for kind, s in tokens):
        for kind, s in tokens:
            if kind == "e":
                state = _next_state(state, s)
        return ("".join(_digits_only(s) if kind == "t" else s
                        for kind, s in tokens), state)

    # Cells, each with the state it is drawn in and the escapes that
    # come before it
    start_state = state
    cells = []       # [text, state]
    lead = []
    pending = []
    for kind, s in tokens:
        if kind == "e":
            pending.append(s)
            state = _next_state(state, s)
            continue
        for ch in s:
            if cells and _rides(ch) and cells[-1][0][0] not in _CONTROLS:
                cells[-1][0] += ch
                continue
            cells.append([ch, state])
            lead.append(pending)
            pending = []
    tail = pending
    final_state = state
    n = len(cells)
    if not n:
        return "".join(s for _kind, s in tokens), final_state

    _shape(cells)
    classes = ["S" if _is_graphic(c[0][0]) else bidi_class(c[0][0]) for c in cells]

    if _digits is not None or _to_latin:
        # Identifiers, inside an LRI, keep their ASCII digits
        protected = []
        depth = []
        for cell in cells:
            ch = cell[0][0]
            if ch in (LRI, RLI, FSI):
                depth.append(ch)
            elif ch == PDI and depth:
                depth.pop()
            protected.append(LRI in depth)
        texts = [c[0] for c in cells]
        _convert_digits(texts, protected)
        for c, t in zip(cells, texts):
            c[0] = t

    # Segments: text between graphics and gaps of two spaces or more,
    # never cut inside an isolate.  A graphic or a gap is a segment of
    # its own, of one cell, which stays where it is.
    segments = []
    seg_start = None
    iso = 0
    for k in range(n):
        ch = cells[k][0][0]
        if ch in (LRI, RLI, FSI):
            iso += 1
        elif ch == PDI and iso:
            iso -= 1
        gap = not iso and (classes[k] == "S" or (ch == " " and (
            (k + 1 < n and cells[k + 1][0][0] == " ")
            or (k > 0 and cells[k - 1][0][0] == " "))))
        if gap:
            if seg_start is not None:
                segments.append((seg_start, k))
                seg_start = None
            segments.append((k, k + 1))
        elif seg_start is None:
            seg_start = k
    if seg_start is not None:
        segments.append((seg_start, n))
    # A segment's own leading and trailing spaces stay where they are,
    # as a gap's do
    trimmed = []
    for a, b in segments:
        while b - a > 1 and cells[a][0] == " ":
            trimmed.append((a, a + 1))
            a += 1
        tail_spaces = []
        while b - a > 1 and cells[b - 1][0] == " ":
            b -= 1
            tail_spaces.append((b, b + 1))
        trimmed.append((a, b))
        trimmed.extend(reversed(tail_spaces))
    segments = trimmed

    order = []
    mirrored = [False] * n
    for a, b in segments:
        types = classes[a:b]
        if b - a == 1 or not any(t in _MOVES for t in types):
            order.extend(range(a, b))
            continue
        base = 1 if _ui_rtl and any(t in _STRONG_R for t in types) else None
        brackets = [bracket_info(cells[i][0][0]) for i in range(a, b)]
        para, levels = resolve_levels(types, base, brackets)
        for j, lv in enumerate(levels):
            if lv is not None and lv % 2:
                mirrored[a + j] = True
        # The characters X9 removes are controls this pass drops; they
        # keep a place in the order so nothing is lost
        visual = visual_order([para if lv is None else lv for lv in levels])
        order.extend(a + j for j in visual)

    out = []
    have = start_state
    prev = -1
    for k in order:
        text, want = cells[k]
        ch = text[0]
        if ch in _CONTROLS:
            text = ""
        elif ch in _FORM_CHARS or joining_type(ch) in ("D", "R"):
            text = text.replace(_ZWNJ, "").replace(_ZWJ, "")
        if mirrored[k] and ch in _MIRROR:
            text = _MIRROR[ch] + text[1:]
        if k == prev + 1:
            out.extend(lead[k])      # the row's own escapes, in their order
        else:
            out.append(_set_state(have, want))
        have = want
        out.append(text)
        prev = k
    if prev == n - 1:
        out.extend(tail)
    else:
        out.append(_set_state(have, final_state))
    return "".join(out), final_state


_MOVES = frozenset(("R", "AL", "AN", "RLE", "RLO", "RLI", "FSI"))
_FORM_CHARS = frozenset(f for forms in _FORMS.values() for f in forms.values())
