"""Framebuffer and rendering utilities for half-block terminal graphics.

Provides a Framebuffer class that renders at 2x vertical sub-pixel resolution
using Unicode half-block characters (▄), plus text measurement and time
formatting helpers used across the UI.
"""

import math
import os
import re
import unicodedata

from linecast._color import RESET, BOLD, BG_PRIMARY, fg, bg, lerp


# ---------------------------------------------------------------------------
# Rendering helpers
# ---------------------------------------------------------------------------
HALF_BLOCK = "\u2584"          # ▄ lower half block


def halfblock(top, bot):
    """One character cell: two sub-pixels via half-block with fg+bg."""
    if top == bot:
        return f"{bg(*top)} "
    return f"{bg(*top)}{fg(*bot)}{HALF_BLOCK}"


def visible_len(s):
    """Length of a string ignoring ANSI escapes, counting wide/emoji chars as 2."""
    stripped = re.sub(r'\033\][^\033]*\033\\', '', s)  # strip OSC sequences (hyperlinks)
    stripped = re.sub(r'\033\[[^m]*m', '', stripped)
    chars = list(stripped)
    n = 0
    i = 0
    while i < len(chars):
        ch = chars[i]
        cp = ord(ch)
        # Check if next char is VS16 (emoji presentation selector)
        has_vs16 = (i + 1 < len(chars) and chars[i + 1] == '\ufe0f')
        if ch == '\ufe0f':
            # VS16 itself is zero-width (already accounted for on the base char)
            i += 1
            continue
        cat = unicodedata.category(ch)
        eaw = unicodedata.east_asian_width(ch)
        if cat == 'Co':
            # Private Use Area (Nerd Font icons) — single-width
            n += 1
        elif eaw in ('W', 'F'):
            n += 2
        elif has_vs16:
            # Base char + VS16 → emoji presentation → double-width
            n += 2
        elif cp >= 0x1F000:
            n += 2
        else:
            n += 1
        i += 1
    return n


def fmt_time(hours):
    """Format decimal hours as H:MM."""
    h = int(hours) % 24
    m = int((hours % 1) * 60)
    return f"{h}:{m:02d}"


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


def fmt_time_dt(dt, use_24h=False):
    """Format a datetime as a compact time string."""
    if use_24h:
        return dt.strftime("%H:%M")
    return dt.strftime("%-I:%M%p").lower().replace("am", "a").replace("pm", "p")


def get_terminal_size(fallback=(80, 24)):
    """Safe wrapper around os.get_terminal_size."""
    try:
        return os.get_terminal_size()
    except OSError:
        return fallback


# ---------------------------------------------------------------------------
# Framebuffer
# ---------------------------------------------------------------------------
class Framebuffer:
    """A width x (height_cells*2) sub-pixel buffer rendered via half-blocks.

    Sub-pixel row 0 = top of display, total_spy-1 = bottom.
    Each cell row spans two sub-pixel rows (top, bottom half-block).
    """

    def __init__(self, width, height_cells, bg_color=BG_PRIMARY):
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
                  drawn in fg_color over the appropriate background.
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
                    char, fg_color = overlays[key]
                    parts.append(f"{bg(*top)}{fg(*fg_color)}{BOLD}{char}{RESET}")
                else:
                    parts.append(halfblock(top, bot))
            parts.append(RESET)
            lines.append("".join(parts))
        return lines
