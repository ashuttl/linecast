"""Terminal display width of text — the single source of truth.

One rule set for how many columns a character occupies: VS16 emoji
presentation, Private Use Area glyphs (Nerd Font icons), CJK wide/full
forms, and the emoji planes.  Stdlib only, so pure-data modules (like
_maps_style) can import it without dragging in the renderer.
"""

import re
import unicodedata

_OSC = re.compile(r'\033\][^\033]*\033\\')   # OSC sequences (hyperlinks)
_SGR = re.compile(r'\033\[[^m]*m')

_VS16 = '\ufe0f'                        # emoji presentation selector


def char_width(ch, next_ch=""):
    """Terminal columns a single character occupies.

    Pass the following character as ``next_ch``: a VS16 selector there
    promotes its base character to emoji presentation (width 2), and the
    selector itself is width 0.
    """
    if ch == _VS16:
        return 0
    if unicodedata.category(ch) == 'Co':
        return 1        # Private Use Area (Nerd Font icons) — single-width
    # Nonspacing marks ride their base's cell: a Devanagari matra above
    # or below, a virama, an anusvara, a Thai or Arabic vowel sign.
    # Spacing marks (Mc — ा, ि) keep their own cell, as wcwidth has it.
    if unicodedata.category(ch) in ('Mn', 'Me'):
        return 0
    if ch in '\u200b\u200c\u200d\u2060\ufeff':
        return 0        # zero-width space and joiners (ZWNJ/ZWJ in Indic text)
    if unicodedata.east_asian_width(ch) in ('W', 'F'):
        return 2
    if next_ch == _VS16:
        return 2        # base + VS16 → emoji presentation → double-width
    if ord(ch) >= 0x1F000:
        return 2
    return 1


def visible_len(s):
    """Length of a string ignoring ANSI escapes, counting wide/emoji chars as 2."""
    stripped = _OSC.sub('', s)
    stripped = _SGR.sub('', stripped)
    return sum(char_width(ch, stripped[i + 1:i + 2])
               for i, ch in enumerate(stripped))
