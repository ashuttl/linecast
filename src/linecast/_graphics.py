"""Shared terminal graphics library for half-block rendering.

Provides ANSI color helpers, color interpolation, and a Framebuffer class
that renders at 2x vertical sub-pixel resolution using Unicode half-block
characters with 24-bit true color.

Used by: weather, sunshine, tides
"""

import math, os, re, sys, time as _time

# ---------------------------------------------------------------------------
# ANSI helpers
# ---------------------------------------------------------------------------
RESET = "\033[0m"
BOLD  = "\033[1m"

HALF_BLOCK = "\u2584"          # ▄ lower half block

BG_PRIMARY = (15, 23, 42)     # #0f172a slate-900 — shared dark base


def fg(r, g, b):
    return f"\033[38;2;{r};{g};{b}m"


def bg(r, g, b):
    return f"\033[48;2;{r};{g};{b}m"


# ---------------------------------------------------------------------------
# Color math
# ---------------------------------------------------------------------------
def lerp(c1, c2, t):
    """Linear interpolate between two RGB tuples."""
    t = max(0.0, min(1.0, t))
    return tuple(int(a + (b - a) * t) for a, b in zip(c1, c2))


def interp_stops(stops, value):
    """Interpolate between a list of (value, color) stops."""
    if value <= stops[0][0]:
        return stops[0][1]
    if value >= stops[-1][0]:
        return stops[-1][1]
    for i in range(len(stops) - 1):
        v1, c1 = stops[i]
        v2, c2 = stops[i + 1]
        if v1 <= value <= v2:
            return lerp(c1, c2, (value - v1) / (v2 - v1))
    return stops[-1][1]


# ---------------------------------------------------------------------------
# Rendering helpers
# ---------------------------------------------------------------------------
def halfblock(top, bot):
    """One character cell: two sub-pixels via half-block with fg+bg."""
    if top == bot:
        return f"{bg(*top)} "
    return f"{bg(*top)}{fg(*bot)}{HALF_BLOCK}"


def visible_len(s):
    """Length of a string ignoring ANSI escape sequences."""
    return len(re.sub(r'\033\[[^m]*m', '', s))


def fmt_time(hours):
    """Format decimal hours as H:MM."""
    h = int(hours) % 24
    m = int((hours % 1) * 60)
    return f"{h}:{m:02d}"


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

    def draw_fill(self, curve_spy, fill_to_spy, color_func):
        """Fill between a curve and a boundary with a gradient.

        curve_spy: list of float y-positions per column (the curve edge).
        fill_to_spy: int sub-pixel row to fill toward (e.g. bottom of buffer).
        color_func: callable(t) -> RGB tuple, where t=0.0 at curve, t=1.0 at boundary.
        """
        for x in range(self.graph_w):
            cf = curve_spy[x]
            top_spy = int(round(cf))
            if fill_to_spy > top_spy:
                span = fill_to_spy - top_spy
                for spy in range(max(0, top_spy), min(self.total_spy, fill_to_spy)):
                    t = (spy - top_spy) / max(1, span)
                    color = color_func(t)
                    self.fb[spy][x] = lerp(self.fb[spy][x], color, 0.85)
            else:
                span = top_spy - fill_to_spy
                for spy in range(max(0, fill_to_spy), min(self.total_spy, top_spy)):
                    t = (top_spy - spy) / max(1, span)
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


# ---------------------------------------------------------------------------
# Live mode (alternate screen, auto-refresh, scroll-to-scrub)
# ---------------------------------------------------------------------------
def _read_key():
    """Read a keypress from stdin in cbreak mode. Returns action string or None.

    Fully consumes CSI/SS3 escape sequences so leftover bytes don't leak.
    """
    import select as _sel
    ch = sys.stdin.read(1)
    if ch == '\033':
        if _sel.select([sys.stdin], [], [], 0.05)[0]:
            ch2 = sys.stdin.read(1)
            if ch2 == '[':
                # CSI sequence: read params + final byte (letter or ~)
                seq = ''
                while _sel.select([sys.stdin], [], [], 0.05)[0]:
                    c = sys.stdin.read(1)
                    seq += c
                    if c.isalpha() or c == '~':
                        break
                final = seq[-1:] if seq else ''
                return {'A': 'fwd', 'B': 'back', 'C': 'fwd', 'D': 'back'}.get(final)
            elif ch2 == 'O':
                # SS3 sequence (some terminals use for arrows)
                if _sel.select([sys.stdin], [], [], 0.05)[0]:
                    ch3 = sys.stdin.read(1)
                    return {'A': 'fwd', 'B': 'back', 'C': 'fwd', 'D': 'back'}.get(ch3)
        return None  # bare ESC or unknown — ignore, don't reset
    elif ch in ('q', 'Q'):
        return 'quit'
    elif ch in ('n', 'N', ' '):
        return 'reset'
    return None


def live_loop(render_fn, interval=60):
    """Run render_fn() in a loop on the alternate screen buffer.

    render_fn: callable(offset_minutes=0) returning the display string.
               Scroll/arrow keys adjust offset_minutes to scrub through time.
    interval: seconds between refreshes.
    Re-renders immediately on terminal resize (SIGWINCH) or input.
    """
    import select, signal, termios, threading, tty

    wake = threading.Event()
    signal.signal(signal.SIGWINCH, lambda *_: wake.set())

    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    offset = 0

    sys.stdout.write("\033[?1049h\033[?25l")  # alt screen + hide cursor
    sys.stdout.flush()
    try:
        tty.setcbreak(fd)

        while True:
            output = render_fn(offset_minutes=offset)
            sys.stdout.write(f"\033[2J\033[H{output}\033[0m")
            sys.stdout.flush()
            wake.clear()

            # Wait for input, resize, or timeout
            deadline = _time.time() + interval
            while True:
                remaining = deadline - _time.time()
                if remaining <= 0 or wake.is_set():
                    break
                try:
                    ready, _, _ = select.select([sys.stdin], [], [], min(0.1, remaining))
                except (InterruptedError, OSError):
                    continue
                if ready:
                    action = _read_key()
                    if action == 'quit':
                        return
                    elif action == 'fwd':
                        offset += 15
                        break
                    elif action == 'back':
                        offset -= 15
                        break
                    elif action == 'reset':
                        offset = 0
                        break
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        sys.stdout.write("\033[?25h\033[?1049l")  # show cursor + restore screen
        sys.stdout.flush()
