"""The Unicode Bidirectional Algorithm (UAX #9), and the character data
it reads.

resolve_levels gives the embedding level of each character of a
paragraph, from the characters' bidi classes (bidi_class) and paired
brackets (bracket_info), and visual_order gives the order those levels
put the characters in.  MIRRORING_GLYPH is the glyph each mirrored
character is drawn as in a right-to-left run.  Nothing here knows about
terminals, escapes or cells: terminal/bidi.py cuts a row into
paragraphs, asks this module for their order, and draws them.  The
algorithm is checked against Unicode's BidiCharacterTest.txt
(tests/test_bidi.py).
"""

import unicodedata

# ---------------------------------------------------------------------------
# Character data
# ---------------------------------------------------------------------------

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
MIRRORING_GLYPH = {}
for _i in range(0, len(_MIRROR_PAIRS), 2):
    _a, _b = _MIRROR_PAIRS[_i], _MIRROR_PAIRS[_i + 1]
    MIRRORING_GLYPH[_a], MIRRORING_GLYPH[_b] = _b, _a
del _i, _a, _b

STRONG_R = frozenset(("R", "AL"))
_ISOLATE_INITIATORS = frozenset(("LRI", "RLI", "FSI"))
_EMBEDDINGS = frozenset(("LRE", "RLE", "LRO", "RLO"))
_REMOVED = frozenset(("LRE", "RLE", "LRO", "RLO", "PDF", "BN"))
_NEUTRAL_OR_ISOLATE = frozenset(("B", "S", "WS", "ON", "LRI", "RLI", "FSI", "PDI"))
_MAX_DEPTH = 125


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
# The algorithm
# ---------------------------------------------------------------------------
def _first_strong(types, start, end, matching_pdi):
    """P2/P3 over types[start:end]: 0 for L, 1 for R/AL, None for
    neither, skipping what lies inside isolates."""
    i = start
    while i < end:
        t = types[i]
        if t == "L":
            return 0
        if t in STRONG_R:
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
                          position, base, brackets)

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
                      base, brackets):
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
