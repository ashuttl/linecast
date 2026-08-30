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


# Two width models exist in the wild for a conjunct and its marks.
# Adding characters up, र्षा is three columns (र, ष, ा — the virama is
# zero); terminals that group text into grapheme clusters (Ghostty and
# other mode-2027 terminals) draw the whole cluster in two cells.  The
# probe below asks the terminal which it does; until it has answered,
# characters are added up, which is what most terminals do.
_CLUSTER_CAPPED = False

# Viramas: the linkers that join two consonants into one conjunct
# cluster, for Devanagari and its relatives.
_LINKERS = frozenset(map(chr, (
    0x094D, 0x09CD, 0x0A4D, 0x0ACD, 0x0B4D, 0x0BCD, 0x0C4D, 0x0CCD,
    0x0D4D, 0x0DCA, 0x1039, 0x17D2, 0xA9C0,
)))


def set_cluster_capped(on):
    """Choose the width model; see char_widths."""
    global _CLUSTER_CAPPED
    _CLUSTER_CAPPED = bool(on)


def char_widths(text):
    """Terminal columns for each character of `text`, in order.

    By default each character is measured alone (char_width).  In the
    cluster-capped model a character that extends a grapheme cluster —
    a mark, or a consonant joined by a virama — never grows the cluster
    past two columns.
    """
    widths = []
    cluster = 0
    prev = ""
    for i, ch in enumerate(text):
        w = char_width(ch, text[i + 1:i + 2])
        if _CLUSTER_CAPPED:
            extends = (prev in _LINKERS
                       or ch == _VS16
                       or unicodedata.category(ch) in ('Mn', 'Mc', 'Me'))
            if extends:
                w = min(w, max(0, 2 - cluster))
                cluster += w
            else:
                cluster = w
        widths.append(w)
        prev = ch
    return widths


def visible_len(s):
    """Length of a string ignoring ANSI escapes, counting wide/emoji chars as 2."""
    stripped = _OSC.sub('', s)
    stripped = _SGR.sub('', stripped)
    return sum(char_widths(stripped))


# ---------------------------------------------------------------------------
# Terminal probe
# ---------------------------------------------------------------------------

_PROBE_TEXT = "\u0930\u094d\u0937\u093e"    # र्षा
_CPR = re.compile(r'\033\[(\d+);(\d+)R')


def _cpr_width(buf):
    """The probe's rendered width from a cursor position report, or None."""
    match = _CPR.search(buf)
    if not match:
        return None
    return int(match.group(2)) - 1


def calibrate_from_terminal(timeout_s=0.1):
    """Ask the terminal how wide it draws a conjunct cluster.

    Writes र्षा at the start of the current line, reads the cursor
    position back (CPR), and erases the line again.  Two cells means
    the terminal groups clusters, so the cluster-capped model is
    chosen; three means it adds characters up.  A quiet no-op without
    a tty, on Windows, and when the terminal does not answer in time.
    """
    import os
    import sys
    import time
    try:
        import select
        import termios
        import tty
    except ImportError:
        return

    try:
        if not (sys.stdin.isatty() and sys.stdout.isatty()):
            return
        fd_in = sys.stdin.fileno()
        fd_out = sys.stdout.fileno()
        old_settings = termios.tcgetattr(fd_in)
    except Exception:
        return
    if str(os.environ.get("TERM", "")).strip().lower() in ("", "dumb"):
        return

    width = None
    buf = ""
    deadline = time.monotonic() + timeout_s
    try:
        tty.setraw(fd_in)
        os.write(fd_out, b"\r" + _PROBE_TEXT.encode() + b"\033[6n")
        while time.monotonic() < deadline:
            try:
                ready, _, _ = select.select([fd_in], [], [],
                                            deadline - time.monotonic())
            except (InterruptedError, OSError):
                continue
            if not ready:
                break
            try:
                chunk = os.read(fd_in, 512)
            except OSError:
                break
            if not chunk:
                break
            buf += chunk.decode("utf-8", errors="ignore")
            width = _cpr_width(buf)
            if width is not None:
                break
    finally:
        try:
            os.write(fd_out, b"\r\033[2K")
        except OSError:
            pass
        try:
            termios.tcsetattr(fd_in, termios.TCSADRAIN, old_settings)
        except Exception:
            pass

    if width in (2, 3):
        set_cluster_capped(width == 2)
        from linecast._runtime import debug_log
        debug_log(f"text width: probe drew {width} cells, "
                  f"{'cluster-capped' if width == 2 else 'per-character'} model")
