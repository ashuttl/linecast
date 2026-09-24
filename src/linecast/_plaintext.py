"""Text from outside stays text.

Place names, alert headlines, map labels and route steps come from
servers linecast does not control, and they are drawn straight into a
frame beside linecast's own escape sequences.  A name that carried an
ESC, a CSI or an OSC would reach the terminal as a command: set the
window title, move the cursor, open a hyperlink.  plain_text() is run
where provider data is read into linecast's own structures, never on a
finished frame, so the app's own colours and OSC 8 links are untouched.

What goes: C0 controls, DEL, C1 controls (U+0080-U+009F), and every
escape sequence whole, payload included, so "\\x1b]0;TITLE\\x07Park"
becomes "Park" and not "]0;TITLE Park".  What stays: every other
character, including the joiners Persian and the Indic scripts need
(ZWNJ, ZWJ), bidi marks, combining marks and emoji sequences.  Tab,
newline and carriage return become spaces, or with lines=True newlines
survive for text that is laid out in paragraphs.
"""

import re

# Any C0 control, DEL or C1 control: the fast path's test.
_CONTROL = re.compile(r'[\x00-\x1f\x7f-\x9f]')

# Whole escape sequences, 7-bit and 8-bit.  A string sequence (OSC,
# DCS, SOS, PM, APC) runs to its terminator, BEL or ST, or to the end
# of the text when it has none, as a terminal would read it.
_SEQUENCE = re.compile(
    r'(?:\x1b\]|\x9d)[^\x07\x1b\x9c]*(?:\x07|\x1b\\|\x9c)?'      # OSC
    r'|(?:\x1b[PX^_]|[\x90\x98\x9e\x9f])[^\x1b\x9c]*(?:\x1b\\|\x9c)?'
    r'|(?:\x1b\[|\x9b)[0-?]*[ -/]*[@-~]?'                         # CSI
    r'|\x1b[ -/]*[0-~]?'                    # any other ESC sequence
)

# What is left after the sequences: lone controls, and line breaks.
_STRAY = re.compile(r'[\x00-\x08\x0b-\x1f\x7f-\x9f]')
_BREAKS = re.compile(r'\r\n?|[\t\n]')
_TAB_CR = re.compile(r'\r\n?|\t')


def plain_text(text, lines=False):
    """``text`` with every terminal control removed.

    Tabs, newlines and carriage returns become single spaces; with
    ``lines=True`` a newline (or CRLF, or a lone CR) stays a newline.
    Anything that is not a string is handed back as it came.
    """
    if not isinstance(text, str) or not _CONTROL.search(text):
        return text
    text = _SEQUENCE.sub('', text)
    if lines:
        text = _TAB_CR.sub(lambda m: ' ' if m.group() == '\t' else '\n', text)
    else:
        text = _BREAKS.sub(' ', text)
    return _STRAY.sub('', text)
