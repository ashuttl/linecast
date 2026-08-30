"""Framebuffer and rendering utilities for half-block terminal graphics.

Provides a Framebuffer class that renders at 2x vertical sub-pixel resolution
using Unicode half-block characters (▄), plus text measurement and time
formatting helpers used across the UI.
"""

import math
import os
import shutil

from linecast import _theme
from linecast._color import RESET, BOLD, BG_PRIMARY, fg, bg, lerp
from linecast._textwidth import char_width, visible_len  # noqa: F401


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


def fmt_hour_phrase(hour, use_24h=False, lang="en"):
    """Conversational hour: '3pm' (12h), '15h' (24h), '15時' (Japanese)."""
    hour = hour % 24
    if use_24h:
        return f"{hour}時" if lang == "ja" else f"{hour:02d}h"
    h12 = hour % 12 or 12
    return f"{h12}{'am' if hour < 12 else 'pm'}"


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
            parts = [" "]  # left margin
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
