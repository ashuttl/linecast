"""Terminal display width of text — the single source of truth.

One rule set for how many columns a character occupies: VS16 emoji
presentation, Private Use Area glyphs (Nerd Font icons), CJK wide/full
forms, and the emoji planes.  Stdlib only, so pure-data modules (like
_maps_style) can import it without dragging in the renderer.
"""

import re
import textwrap
import unicodedata

_OSC = re.compile(r'\033\][^\033]*\033\\')   # OSC sequences (hyperlinks)
_SGR = re.compile(r'\033\[[^m]*m')

_VS16 = '\ufe0f'                        # emoji presentation selector
# The emoji blocks proper.  Above them are the CJK extensions,
# which are wide because they are ideographs, not because the
# terminal draws emoji wide.
_EMOJI_PLANE = (0x1F000, 0x1FAFF)


def char_width(ch, next_ch=""):
    """Terminal columns a single character occupies.

    Pass the following character as ``next_ch``: a VS16 selector there
    promotes its base character to emoji presentation (width 2), and the
    selector itself is width 0.
    """
    if ch == _VS16:
        return 0
    if unicodedata.category(ch) == 'Co':
        # Private Use Area (Nerd Font icons) — single-width
        return _MEASURED.get("pua", 1)
    # Nonspacing marks ride their base's cell: a Devanagari matra above
    # or below, a virama, an anusvara, a Thai or Arabic vowel sign.
    # Spacing marks (Mc — ा, ि) keep their own cell, as wcwidth has it.
    if unicodedata.category(ch) in ('Mn', 'Me'):
        return 0
    if ch in '\u200b\u200c\u200d\u2060\ufeff':
        return 0        # zero-width space and joiners (ZWNJ/ZWJ in Indic text)
    if next_ch == _VS16:
        # base + VS16 → emoji presentation → double-width.  Asked before
        # the East Asian width: the selector is what settles how the
        # terminal draws the pair, whatever the base is on its own.
        if _EMOJI_PLANE[0] <= ord(ch) <= _EMOJI_PLANE[1]:
            return _MEASURED.get("smp_vs16", 2)
        return _MEASURED.get("bmp_vs16", 2)
    if _EMOJI_PLANE[0] <= ord(ch) <= _EMOJI_PLANE[1]:
        return _MEASURED.get("smp_bare", 2)
    if unicodedata.east_asian_width(ch) in ('W', 'F'):
        return 2
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


def wrap_display_width(text, width):
    """Wrap plain text to fit within a terminal display width.

    Handles CJK double-width and emoji characters correctly.  Falls back
    to ``textwrap.wrap`` when every character is a single cell.
    """
    if not text:
        return [""]
    # Fast path: every char is one cell → stdlib is fine
    if visible_len(text) == len(text):
        return textwrap.wrap(text, width) or [""]

    lines = []
    line = ""
    line_w = 0
    last_sp = -1

    widths = char_widths(text)
    for i, ch in enumerate(text):
        cw = widths[i]
        if line_w + cw > width:
            if ch == " ":
                lines.append(line)
                line, line_w, last_sp = "", 0, -1
                continue
            if last_sp >= 0:
                lines.append(line[:last_sp])
                rest = line[last_sp + 1:]
                line = rest + ch
                line_w = visible_len(line)
                last_sp = -1
            else:
                lines.append(line)
                line, line_w, last_sp = ch, cw, -1
            continue
        if ch == " ":
            last_sp = len(line)
        line += ch
        line_w += cw

    if line:
        lines.append(line)
    return lines or [""]


def truncate_display_width(text, width):
    """Truncate plain text to a terminal display width, adding \u2026 if needed.

    The ellipsis is counted, so the result is never wider than ``width``:
    a line built to the last column has no cell to spare, and one column
    over is a line the terminal wraps."""
    if width <= 0:
        return ""
    widths = char_widths(text)
    if sum(widths) <= width:
        return text
    w, cut = 0, 0
    for i, cw in enumerate(widths):
        if w + cw > width - 1:  # a column held back for the ellipsis
            break
        w += cw
        cut = i + 1
    return (text[:cut] + "\u2026") if cut else "\u2026"


# ---------------------------------------------------------------------------
# Terminal probe
# ---------------------------------------------------------------------------

# What the terminal is asked to draw, and what each answer governs.  Rows
# are laid out from these widths, so a glyph the terminal draws wider than
# the table above expects — a variation selector it gives a cell of its
# own, an icon its font draws double-width — makes the row too long for
# the screen, and the wrap pushes every row below it down one.  Rather
# than guess at which terminal does what, ask this one.
_PROBES = (
    ("ascii", "x"),                            # the canary: one cell everywhere
    ("cluster", "\u0930\u094d\u0937\u093e"),   # र्षा, a conjunct and its marks
    ("bmp_vs16", "\u2601\ufe0f"),              # ☁️, a text emoji VS16 promotes
    ("smp_vs16", "\U0001f327\ufe0f"),          # 🌧️, the weather icons' own class
    ("smp_bare", "\U0001f311"),                # 🌑, an emoji that needs no VS16
    ("pua", "\U000f0590"),                     # a Nerd Font weather glyph
)

# The columns this terminal drew each probe in.  Empty until the probe
# runs, and left empty when it is not asked or goes unanswered, so the
# table above stands as the default.
_MEASURED = {}

_CPR = re.compile(r'\033\[(\d+);(\d+)R')
_CALIBRATED = False


def measured_widths():
    """What the terminal answered, by probe name; empty before it is asked."""
    return dict(_MEASURED)


def probe_glyphs():
    """The glyphs the probe asks about, for a report that shows them."""
    return [(name, text) for name, text in _PROBES if name != "ascii"]


def _cpr_widths(buf):
    """The probes' rendered widths from the cursor position reports so far."""
    return [int(col) - 1 for _row, col in _CPR.findall(buf)]


def calibrate_from_terminal(timeout_s=None):
    """Ask the terminal how wide it draws the glyphs linecast draws.

    Writes each probe glyph at the start of the current line, reads the
    cursor position back (CPR), and erases the line again.  The answers
    settle the conjunct-cluster model — two cells means the terminal
    groups clusters, three that it adds characters up — and the width of
    an emoji, a variation-selected emoji and a Nerd Font glyph.  A quiet
    no-op without a tty, on Windows, when the answer disagrees with the
    terminal's own ``x``, and when it does not come in time.
    """
    global _CALIBRATED
    import os
    import sys
    import time
    try:
        import select
        import termios
        import tty
    except ImportError:
        return

    if _CALIBRATED:
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
    _CALIBRATED = True

    if timeout_s is None:
        from linecast._runtime import probe_timeout_s
        # A round trip is instant on this machine and a link away over SSH.
        timeout_s = probe_timeout_s("LINECAST_WIDTH_TIMEOUT_MS", 150, ssh_ms=600)

    payload = b"".join(b"\r" + text.encode() + b"\033[6n" for _name, text in _PROBES)
    widths = []
    buf = ""
    deadline = time.monotonic() + timeout_s
    try:
        tty.setraw(fd_in)
        os.write(fd_out, payload)
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
            widths = _cpr_widths(buf)
            if len(widths) >= len(_PROBES):
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

    from linecast._runtime import debug_log
    answers = dict(zip((name for name, _text in _PROBES), widths))
    if not answers:
        debug_log("text width: the terminal did not answer the probe")
        return
    # A terminal that cannot place its own cursor after an "x" is telling
    # us nothing about anything harder.
    if answers.get("ascii") != 1:
        debug_log(f"text width: probe canary drew {answers.get('ascii')} cells, "
                  "not 1 — the answers are ignored")
        return

    answers.pop("ascii", None)
    cluster = answers.pop("cluster", None)
    if cluster in (2, 3):
        set_cluster_capped(cluster == 2)
    for name, width in answers.items():
        if 1 <= width <= 3:
            _MEASURED[name] = width
    drawn = ", ".join(f"{name} {width}" for name, width in answers.items())
    model = "cluster-capped" if _CLUSTER_CAPPED else "per-character"
    debug_log(f"text width: probe drew {drawn}, cluster {cluster} ({model} model)")
