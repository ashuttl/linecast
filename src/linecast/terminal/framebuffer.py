"""Framebuffer and rendering utilities for half-block terminal graphics.

Provides a Framebuffer class that renders at 2x vertical sub-pixel resolution
using Unicode half-block characters (▄), plus text measurement and time
formatting helpers used across the UI.
"""

import math
import os
import shutil
import sys

from linecast.terminal import theme as _theme
from linecast.terminal.color import RESET, BOLD, BG_PRIMARY, fg, bg, lerp


# ---------------------------------------------------------------------------
# Rendering helpers
# ---------------------------------------------------------------------------
HALF_BLOCK = "\u2584"          # ▄ lower half block


def halfblock(top, bot):
    """One character cell: two sub-pixels via half-block with fg+bg."""
    if top == bot:
        return f"{bg(*top)} "
    return f"{bg(*top)}{fg(*bot)}{HALF_BLOCK}"


def get_terminal_size(fallback=(80, 24)):
    """Rendering size, honouring $COLUMNS/$LINES and print dimensions.

    shutil.get_terminal_size consults the env vars before the tty ioctl,
    which is what status-bar and tmux-pane captures expect; bare
    os.get_terminal_size ignores them.
    """
    from linecast._runtime import print_viewport
    try:
        size = shutil.get_terminal_size(fallback)
    except (OSError, ValueError):
        size = os.terminal_size(fallback)
    return print_viewport(size)


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

    def flip_columns(self, x0, x1, spy0, spy1):
        """Mirror the sub-pixels in columns x0..x1-1 of rows spy0..spy1-1
        left for right: a picture drawn ahead of a view that is laid
        out from the right (terminal.bidi), which flips it back."""
        x0, x1 = max(0, x0), min(self.graph_w, x1)
        for spy in range(max(0, spy0), min(self.total_spy, spy1)):
            row = self.fb[spy]
            row[x0:x1] = row[x0:x1][::-1]

    def set_pixel(self, x, spy, color, alpha=1.0):
        """Blend a single sub-pixel."""
        if x < 0 or x >= self.graph_w or spy < 0 or spy >= self.total_spy:
            return
        self.fb[spy][x] = lerp(self.fb[spy][x], color, alpha)

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

_theme.track_imports(globals(), "linecast.terminal.color")
