"""Framebuffer and rendering utilities for half-block terminal graphics.

Provides a Framebuffer class that renders at 2x vertical sub-pixel resolution
using Unicode half-block characters (▄), plus text measurement and time
formatting helpers used across the UI.
"""

import math
import os
import shutil
import sys

from linecast import _theme
from linecast._color import RESET, BOLD, BG_PRIMARY, fg, bg, lerp
from linecast._textwidth import char_width, visible_len  # noqa: F401
from linecast._i18n import base_language


# ---------------------------------------------------------------------------
# Rendering helpers
# ---------------------------------------------------------------------------
HALF_BLOCK = "\u2584"          # ▄ lower half block


def halfblock(top, bot):
    """One character cell: two sub-pixels via half-block with fg+bg."""
    if top == bot:
        return f"{bg(*top)} "
    return f"{bg(*top)}{fg(*bot)}{HALF_BLOCK}"


def fmt_time(hours, use_24h=False):
    """Format decimal hours as h:MMa/p, or HH:MM on a 24-hour clock."""
    h = int(hours) % 24
    m = int((hours % 1) * 60)
    if use_24h:
        return f"{h:02d}:{m:02d}"
    h12 = h % 12 or 12
    return f"{h12}:{m:02d}{'a' if h < 12 else 'p'}"


def fmt_hour(h, use_24h=False):
    """Format hour as compact label: 6a, 12p (12h) or 06, 14 (24h)."""
    h = h % 24
    if use_24h:
        return f"{h:02d}"
    if h == 0:
        return "12a"
    if h == 12:
        return "12p"
    if h < 12:
        return f"{h}a"
    return f"{h - 12}p"


# The 24-hour hour as each language writes it in running text: "around
# 15:00", "gegen 15 Uhr", "omkring kl. 15", "noin klo 15", "verso le 15",
# "15시경", "15时左右".  French, Portuguese and Vietnamese write "15h".
_HOUR_24 = {
    "en": "{h:02d}:00", "nl": "{h}\u00a0uur", "eo": "{h:02d}:00",
    "tr": "{h:02d}:00", "sw": "{h:02d}:00",
    # Without the leading zero in running text: "около 9:00", "kolem 9:00"
    "pl": "{h}:00", "cs": "{h}:00", "ru": "{h}:00", "uk": "{h}:00", "el": "{h}:00",
    "ro": "{h}:00",
    "de": "{h}\u00a0Uhr", "it": "{h}", "da": "kl.\u00a0{h}", "no": "kl.\u00a0{h}",
    "sv": "kl.\u00a0{h}", "is": "kl.\u00a0{h}", "fi": "klo\u00a0{h}", "id": "pukul\u00a0{h}.00",
    "ja": "{h}時", "ko": "{h}시", "zh": "{h}时", "zh-Hant": "{h}時", "th": "{h:02d}.00\u00a0น.",
    # French spaces the h, as Météo-France and Environment Canada write
    # it: "18 h".  The spaces are unbreakable, so a paragraph never parts
    # an hour from its word for it.
    "fr": "{h}\u00a0h",
    # Spanish and Portuguese drop the leading zero in running text: "hacia
    # las 9:00", "por volta das 9h".  One o'clock takes the singular
    # article ("hacia la 1:00", "por volta da 1h"), by the "_one" forms of
    # the templates.
    "es": "{h}:00", "pt": "{h}h",
    # Vietnamese writes the hour without a leading zero: "kho\u1ea3ng 9h".
    "vi": "{h}h",
}


def fmt_hour_phrase(hour, use_24h=False, lang="en"):
    """Conversational hour: '3pm' (12h), or the 24-hour form the language
    writes in a sentence: '15:00', '15 Uhr', 'kl. 15', '15時'."""
    hour = hour % 24
    if base_language(lang) == "sw":
        return _swahili_hour(hour)
    if lang == "zh-HK":
        return _hong_kong_hour(hour)
    if use_24h:
        form = _HOUR_24.get(lang, _HOUR_24.get(base_language(lang), "{h:02d}h"))
        return form.format(h=hour)
    h12 = hour % 12 or 12
    if lang == "el":
        # Words fit running prose and avoid a full stop after an am/pm
        # abbreviation colliding with the paragraph's sentence punctuation.
        if hour == 0:
            return "12 τα μεσάνυχτα"
        if hour == 12:
            return "12 το μεσημέρι"
        period = ("τη νύχτα" if hour < 5 else "το πρωί" if hour < 12
                  else "το μεσημέρι" if hour < 15 else "το απόγευμα" if hour < 19
                  else "το βράδυ")
        return f"{h12} {period}"
    return f"{h12}{'am' if hour < 12 else 'pm'}"


_SW_HOURS = ("moja", "mbili", "tatu", "nne", "tano", "sita", "saba", "nane",
             "tisa", "kumi", "kumi na moja", "kumi na mbili")


def _swahili_hour(hour):
    """The hour as Swahili tells it, counted from seven in the morning and
    seven at night, with the part of the day that says which: "saba
    mchana" for 13:00, "moja usiku" for 19:00.  The sentence supplies
    the "saa" before it."""
    count = _SW_HOURS[(hour - 7) % 12]
    part = ("usiku" if hour < 4 or hour >= 19 else "alfajiri" if hour < 6
            else "asubuhi" if hour < 12 else "mchana" if hour < 16 else "jioni")
    return f"{count} {part}"


def _hong_kong_hour(hour):
    """The hour as the Hong Kong Observatory writes it, on the 12-hour
    clock with the part of the day before it: "下午3時", "凌晨2時",
    "中午12時", "午夜12時"."""
    if hour == 0:
        return "午夜12時"
    if hour == 12:
        return "中午12時"
    part = ("凌晨" if hour < 6 else "上午" if hour < 12 else "下午" if hour < 18
            else "傍晚" if hour < 19 else "晚上")
    return f"{part}{hour % 12}時"


def fmt_time_dt(dt, use_24h=False):
    """Format a datetime as a compact time string."""
    if use_24h:
        return dt.strftime("%H:%M")
    # %-I is a glibc/BSD extension that Windows' CRT rejects, and %p is
    # locale-dependent; derive both by hand as fmt_time does just above.
    hour = dt.hour % 12 or 12
    return f"{hour}:{dt.minute:02d}{'a' if dt.hour < 12 else 'p'}"


def get_terminal_size(fallback=(80, 24)):
    """Terminal size, honouring $COLUMNS/$LINES overrides.

    shutil.get_terminal_size consults the env vars before the tty ioctl,
    which is what status-bar and tmux-pane captures expect; bare
    os.get_terminal_size ignores them.
    """
    try:
        return shutil.get_terminal_size(fallback)
    except (OSError, ValueError):
        return os.terminal_size(fallback)


def cell_aspect(fallback=2.0):
    """How many times taller than wide a cell of the terminal's font is.

    The same ioctl that reports the terminal's size in cells reports it
    in pixels, in two fields Python's get_terminal_size drops; the ratio
    of the two is the cell.  Half-block graphics take a cell for two
    square sub-pixels, which is only so when it is twice as tall as it
    is wide, and a real font is nearer 1.6 to 1.7: a disc drawn on the
    assumption comes out that much wider than it is tall.  The fallback
    is the assumption, for terminals that leave the pixel fields at
    zero, for pipes, and for Windows.  $LINECAST_CELL_ASPECT overrides
    the measurement, as a ratio (1.67) or a cell in pixels (9x15), for
    captures and for terminals that report a wrong size.
    """
    override = os.environ.get("LINECAST_CELL_ASPECT", "").strip().lower()
    if override:
        try:
            if "x" in override:
                w, h = override.split("x", 1)
                ratio = float(h) / float(w)
            else:
                ratio = float(override)
            if 1.0 <= ratio <= 4.0:
                return ratio
        except (ValueError, ZeroDivisionError):
            pass
        return fallback
    try:
        import fcntl
        import struct
        import termios
    except ImportError:
        return fallback
    for stream in (sys.__stdout__, sys.__stdin__, sys.__stderr__):
        try:
            packed = fcntl.ioctl(stream.fileno(), termios.TIOCGWINSZ, b"\0" * 8)
            rows, cols, xpx, ypx = struct.unpack("HHHH", packed)
        except (OSError, ValueError, AttributeError):
            continue
        if not (rows and cols and xpx and ypx):
            continue
        ratio = (ypx / rows) / (xpx / cols)
        if 1.0 <= ratio <= 4.0:
            return ratio
    return fallback


# ---------------------------------------------------------------------------
# Framebuffer
# ---------------------------------------------------------------------------
class Framebuffer:
    """A width x (height_cells*2) sub-pixel buffer rendered via half-blocks.

    Sub-pixel row 0 = top of display, total_spy-1 = bottom.
    Each cell row spans two sub-pixel rows (top, bottom half-block).
    """

    def __init__(self, width, height_cells, bg_color=None):
        if bg_color is None:
            bg_color = BG_PRIMARY
        self.graph_w = width
        self.graph_h = height_cells
        self.total_spy = height_cells * 2
        self.bg = bg_color
        self.fb = [[bg_color] * width for _ in range(self.total_spy)]

    def fill_hline(self, spy, color):
        """Draw a horizontal line at sub-pixel row spy."""
        spy = max(0, min(self.total_spy - 1, int(round(spy))))
        for x in range(self.graph_w):
            self.fb[spy][x] = color

    def set_pixel(self, x, spy, color, alpha=1.0):
        """Blend a single sub-pixel."""
        if x < 0 or x >= self.graph_w or spy < 0 or spy >= self.total_spy:
            return
        self.fb[spy][x] = lerp(self.fb[spy][x], color, alpha)

    def draw_curve(self, curve_spy, color, sigma=0.8):
        """Draw a Gaussian-antialiased curve.

        curve_spy: list of float sub-pixel y-positions, one per column.
        """
        for x in range(self.graph_w):
            cf = curve_spy[x]
            lo = max(0, int(cf) - 3)
            hi = min(self.total_spy, int(cf) + 4)
            for spy in range(lo, hi):
                dist = abs(spy - cf)
                alpha = math.exp(-0.5 * (dist / sigma) ** 2)
                if alpha > 0.02:
                    self.fb[spy][x] = lerp(self.fb[spy][x], color, alpha)

    def draw_fill(self, curve_spy, fill_to_spy, color_func, aspect=1.0):
        """Fill between a curve and a boundary with a gradient.

        curve_spy: list of float y-positions per column (the curve edge).
        fill_to_spy: int sub-pixel row to fill toward (e.g. bottom of buffer).
        color_func: callable(t) -> RGB tuple, where t=0.0 at curve, t=1.0 at boundary.
        aspect: vertical stretch correction (>1 compresses gradient to compensate
                for sub-pixels being taller than wide on screen).
        """
        for x in range(self.graph_w):
            cf = curve_spy[x]
            top_spy = int(round(cf))
            if fill_to_spy > top_spy:
                span = fill_to_spy - top_spy
                for spy in range(max(0, top_spy), min(self.total_spy, fill_to_spy)):
                    t = min(1.0, (spy - top_spy) * aspect / max(1, span))
                    color = color_func(t)
                    self.fb[spy][x] = lerp(self.fb[spy][x], color, 0.85)
            else:
                span = top_spy - fill_to_spy
                for spy in range(max(0, fill_to_spy), min(self.total_spy, top_spy)):
                    t = min(1.0, (top_spy - spy) * aspect / max(1, span))
                    color = color_func(t)
                    self.fb[spy][x] = lerp(self.fb[spy][x], color, 0.85)

    def cell_bg(self, x, cell_row):
        """Blended color of a cell — its two sub-pixels averaged."""
        return lerp(self.fb[cell_row * 2][x], self.fb[cell_row * 2 + 1][x], 0.5)

    def draw_radial(self, cx, cy_spy, color, radius, aspect=1.8, peak_alpha=0.75):
        """Draw a radial glow blob centered at (cx, cy_spy).

        aspect: vertical stretch factor (cells are taller than wide in sub-pixels).
        """
        cy_i = int(round(cy_spy))
        scan = radius + 2
        for dy in range(-scan, scan + 1):
            for dx in range(-scan, scan + 1):
                sx = cx + dx
                sy = cy_i + dy
                if sx < 0 or sx >= self.graph_w or sy < 0 or sy >= self.total_spy:
                    continue
                dist = math.sqrt(dx * dx + (dy * aspect) ** 2)
                if dist > radius + 1:
                    continue
                intensity = math.exp(-0.5 * (dist / (radius * 0.35)) ** 2)
                self.fb[sy][sx] = lerp(self.fb[sy][sx], color, intensity * peak_alpha)

    def render(self, overlays=None):
        """Convert buffer to ANSI half-block strings.

        overlays: dict of {(col, cell_row): (char, fg_color)} for character overlays.
                  These replace the half-block at that position with a character
                  drawn in fg_color over the appropriate background.  A third
                  tuple element False drops the default bold weight.  An
                  empty char emits nothing for the cell: the slot a wide
                  glyph in the cell before it already covers.
        Returns a list of strings, one per cell row.
        """
        if overlays is None:
            overlays = {}

        lines = []
        for row in range(self.graph_h):
            parts = []
            for x in range(self.graph_w):
                top = self.fb[row * 2][x]
                bot = self.fb[row * 2 + 1][x]
                key = (x, row)
                if key in overlays:
                    entry = overlays[key]
                    char, fg_color = entry[0], entry[1]
                    if not char:
                        continue
                    weight = BOLD if len(entry) < 3 or entry[2] else ""
                    # An overlay char covers the whole cell; blend the two
                    # sub-pixels so its background matches the cell center.
                    parts.append(f"{bg(*self.cell_bg(x, row))}{fg(*fg_color)}{weight}{char}{RESET}")
                else:
                    parts.append(halfblock(top, bot))
            parts.append(RESET)
            lines.append("".join(parts))
        return lines

_theme.track_imports(globals(), "linecast._color")
