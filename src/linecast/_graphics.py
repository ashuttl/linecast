"""Shared terminal graphics library for half-block rendering.

Provides ANSI color helpers, color interpolation, and a Framebuffer class
that renders at 2x vertical sub-pixel resolution using Unicode half-block
characters. Uses true color when available, with 256/16/none fallbacks.

Used by: weather, sunshine
"""

import functools
import math
import os
import re
import sys
import time as _time
import unicodedata

# ---------------------------------------------------------------------------
# ANSI helpers
# ---------------------------------------------------------------------------
_COLOR_TRUECOLOR = "truecolor"
_COLOR_256 = "256"
_COLOR_16 = "16"
_COLOR_NONE = "none"

_CUBE_LEVELS = (0, 95, 135, 175, 215, 255)
_ANSI16_RGB = (
    (0, 0, 0),
    (128, 0, 0),
    (0, 128, 0),
    (128, 128, 0),
    (0, 0, 128),
    (128, 0, 128),
    (0, 128, 128),
    (192, 192, 192),
    (128, 128, 128),
    (255, 0, 0),
    (0, 255, 0),
    (255, 255, 0),
    (92, 92, 255),
    (255, 0, 255),
    (0, 255, 255),
    (255, 255, 255),
)


def _normalize_color_mode(value):
    raw = str(value or "").strip().lower()
    aliases = {
        "": "auto",
        "auto": "auto",
        "truecolor": _COLOR_TRUECOLOR,
        "24bit": _COLOR_TRUECOLOR,
        "24-bit": _COLOR_TRUECOLOR,
        "full": _COLOR_TRUECOLOR,
        "256": _COLOR_256,
        "256color": _COLOR_256,
        "256-color": _COLOR_256,
        "8bit": _COLOR_256,
        "8-bit": _COLOR_256,
        "16": _COLOR_16,
        "ansi": _COLOR_16,
        "basic": _COLOR_16,
        "none": _COLOR_NONE,
        "off": _COLOR_NONE,
        "mono": _COLOR_NONE,
        "monochrome": _COLOR_NONE,
        "bw": _COLOR_NONE,
    }
    return aliases.get(raw)


def detect_color_mode(environ=None, stream=None):
    """Return one of: truecolor, 256, 16, none."""
    env = os.environ if environ is None else environ
    mode = _normalize_color_mode(env.get("LINECAST_COLOR", "auto"))
    if mode is None:
        mode = "auto"
    if mode != "auto":
        return mode

    if str(env.get("NO_COLOR", "")).strip():
        return _COLOR_NONE
    if str(env.get("CLICOLOR", "")).strip() == "0":
        return _COLOR_NONE

    term = str(env.get("TERM", "")).strip().lower()
    colorterm = str(env.get("COLORTERM", "")).strip().lower()
    if term in ("", "dumb"):
        return _COLOR_NONE

    if stream is None:
        stream = sys.stdout
    try:
        is_tty = bool(stream.isatty())
    except Exception:
        is_tty = False

    force = str(env.get("CLICOLOR_FORCE", "")).strip()
    if force and force != "0":
        is_tty = True
    if not is_tty:
        return _COLOR_NONE

    if "truecolor" in colorterm or "24bit" in colorterm:
        return _COLOR_TRUECOLOR
    if "truecolor" in term or "24bit" in term:
        return _COLOR_TRUECOLOR
    if "256color" in term:
        return _COLOR_256
    return _COLOR_16


_COLOR_MODE = detect_color_mode()
if _COLOR_MODE == _COLOR_NONE:
    RESET = ""
    BOLD = ""
else:
    RESET = "\033[0m"
    BOLD = "\033[1m"

HALF_BLOCK = "\u2584"          # ▄ lower half block

BG_PRIMARY = (15, 23, 42)     # #0f172a slate-900 — shared dark base


def color_mode():
    """Current terminal color mode: truecolor, 256, 16, or none."""
    return _COLOR_MODE


def _channel(v):
    try:
        n = int(round(v))
    except Exception:
        n = 0
    return max(0, min(255, n))


@functools.lru_cache(maxsize=4096)
def _rgb_to_xterm256(r, g, b):
    ri = min(range(6), key=lambda i: abs(_CUBE_LEVELS[i] - r))
    gi = min(range(6), key=lambda i: abs(_CUBE_LEVELS[i] - g))
    bi = min(range(6), key=lambda i: abs(_CUBE_LEVELS[i] - b))
    cube_idx = 16 + 36 * ri + 6 * gi + bi
    cube_rgb = (_CUBE_LEVELS[ri], _CUBE_LEVELS[gi], _CUBE_LEVELS[bi])

    gray_i = max(0, min(23, int(round((((r + g + b) / 3) - 8) / 10))))
    gray_level = 8 + 10 * gray_i
    gray_rgb = (gray_level, gray_level, gray_level)

    cube_dist = sum((a - b_) ** 2 for a, b_ in zip((r, g, b), cube_rgb))
    gray_dist = sum((a - b_) ** 2 for a, b_ in zip((r, g, b), gray_rgb))
    if gray_dist < cube_dist:
        return 232 + gray_i
    return cube_idx


@functools.lru_cache(maxsize=4096)
def _rgb_to_ansi16(r, g, b):
    return min(
        range(len(_ANSI16_RGB)),
        key=lambda i: (
            (_ANSI16_RGB[i][0] - r) ** 2
            + (_ANSI16_RGB[i][1] - g) ** 2
            + (_ANSI16_RGB[i][2] - b) ** 2
        ),
    )


@functools.lru_cache(maxsize=16384)
def _fg_for_mode(mode, r, g, b):
    if mode == _COLOR_NONE:
        return ""
    if mode == _COLOR_TRUECOLOR:
        return f"\033[38;2;{r};{g};{b}m"
    if mode == _COLOR_256:
        return f"\033[38;5;{_rgb_to_xterm256(r, g, b)}m"
    idx = _rgb_to_ansi16(r, g, b)
    return f"\033[{30 + idx if idx < 8 else 90 + (idx - 8)}m"


@functools.lru_cache(maxsize=16384)
def _bg_for_mode(mode, r, g, b):
    if mode == _COLOR_NONE:
        return ""
    if mode == _COLOR_TRUECOLOR:
        return f"\033[48;2;{r};{g};{b}m"
    if mode == _COLOR_256:
        return f"\033[48;5;{_rgb_to_xterm256(r, g, b)}m"
    idx = _rgb_to_ansi16(r, g, b)
    return f"\033[{40 + idx if idx < 8 else 100 + (idx - 8)}m"


def fg(r, g, b):
    return _fg_for_mode(_COLOR_MODE, _channel(r), _channel(g), _channel(b))


def bg(r, g, b):
    return _bg_for_mode(_COLOR_MODE, _channel(r), _channel(g), _channel(b))


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


# ---------------------------------------------------------------------------
# Live mode (alternate screen, auto-refresh, scroll-to-scrub)
# ---------------------------------------------------------------------------
def _read_key():
    """Read a keypress from stdin in cbreak mode. Returns action string or None.

    Fully consumes CSI/SS3 escape sequences so leftover bytes don't leak.
    Uses a longer timeout (150ms) to avoid splitting mouse escape sequences
    when the system is busy (e.g. after a re-render).
    """
    import select as _sel
    ch = sys.stdin.read(1)
    if ch == '\033':
        # Use 150ms timeout — 50ms is too short when the system is busy
        # rendering; mouse release sequences (\033[<0;x;ym) can arrive late
        # and the \033 gets read as a bare ESC.
        if _sel.select([sys.stdin], [], [], 0.15)[0]:
            ch2 = sys.stdin.read(1)
            if ch2 == '[':
                # CSI sequence: read params + final byte (letter or ~)
                seq = ''
                while _sel.select([sys.stdin], [], [], 0.15)[0]:
                    c = sys.stdin.read(1)
                    seq += c
                    if c.isalpha() or c == '~':
                        break
                # SGR mouse event: \033[<Cb;Cx;CyM or \033[<Cb;Cx;Cym
                if seq.startswith('<') and seq[-1:] in ('M', 'm'):
                    try:
                        parts = seq[1:-1].split(';')
                        cb, cx, cy = int(parts[0]), int(parts[1]), int(parts[2])
                        return ('mouse', cb, cx, cy, seq[-1] == 'm')
                    except (ValueError, IndexError):
                        return None
                final = seq[-1:] if seq else ''
                return {'A': 'fwd', 'B': 'back', 'C': 'fwd', 'D': 'back'}.get(final)
            elif ch2 == 'O':
                # SS3 sequence (some terminals use for arrows)
                if _sel.select([sys.stdin], [], [], 0.15)[0]:
                    ch3 = sys.stdin.read(1)
                    return {'A': 'fwd', 'B': 'back', 'C': 'fwd', 'D': 'back'}.get(ch3)
        return 'escape'
    elif ch in ('q', 'Q'):
        return 'quit'
    elif ch in ('o', 'O'):
        return 'open'
    elif ch in ('n', 'N', ' '):
        return 'reset'
    return None


def live_loop(render_fn, interval=60, mouse=False, on_open=None):
    """Run render_fn() in a loop on the alternate screen buffer.

    render_fn: callable(offset_minutes=0) returning (display_string, metadata)
               or just display_string.
               If mouse=True, also receives mouse_pos=(col, row) or None
               and active_alert=int_or_None.
               Scroll/arrow keys adjust offset_minutes to scrub through time.
    interval: seconds between refreshes.
    mouse: if True, enable SGR mouse tracking and pass mouse_pos to render_fn.
    on_open: optional callback(alert_index) called when user presses 'o' on a modal.
    Re-renders immediately on terminal resize (SIGWINCH) or input.
    """
    import select, signal, termios, threading, tty

    wake = threading.Event()
    signal.signal(signal.SIGWINCH, lambda *_: wake.set())

    # Terminal.app lacks SGR mouse support; disable gracefully
    if mouse and os.environ.get('TERM_PROGRAM') == 'Apple_Terminal':
        mouse = False

    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    offset = 0
    mouse_pos = None
    active_alert = None  # index of alert whose modal is open, or None
    modal_scroll = 0     # scroll offset within the modal
    alert_row_map = {}   # 0-based line index → alert index

    init = "\033[?1049h\033[?25l"
    if mouse:
        init += "\033[?1003h\033[?1006h"
    sys.stdout.write(init)
    sys.stdout.flush()
    try:
        tty.setcbreak(fd)

        while True:
            if mouse:
                result = render_fn(offset_minutes=offset, mouse_pos=mouse_pos, active_alert=active_alert, modal_scroll=modal_scroll)
            else:
                result = render_fn(offset_minutes=offset)
            # render_fn may return (output, metadata) or just output
            if isinstance(result, tuple):
                output, alert_row_map = result
            else:
                output = result
                alert_row_map = {}
            # Separate cursor-positioned overlay from main output (\x00 delimiter)
            parts = output.split('\x00', 1)
            main_out = parts[0]
            overlay = parts[1] if len(parts) > 1 else ""
            # \033[H homes cursor; \033[K clears line remainders;
            # \033[J clears below; overlay draws on top after clear
            padded = main_out.replace('\n', '\033[K\n')
            sys.stdout.write(f"\033[H{padded}\033[K\033[J\033[0m{overlay}\033[0m")
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
                        if active_alert is not None:
                            active_alert = None
                            modal_scroll = 0
                            break
                        return
                    elif action == 'escape':
                        # With mouse tracking, bare ESC is almost always a
                        # split mouse sequence (release bytes arriving late).
                        # Only honour ESC to dismiss when mouse is off.
                        if not mouse and active_alert is not None:
                            active_alert = None
                            break
                    elif action == 'open':
                        if active_alert is not None and on_open:
                            on_open(active_alert)
                            break
                    elif action == 'fwd':
                        offset += 15
                        break
                    elif action == 'back':
                        offset -= 15
                        break
                    elif action == 'reset':
                        offset = 0
                        break
                    elif mouse and isinstance(action, tuple) and action[0] == 'mouse':
                        _, cb, cx, cy, is_rel = action
                        if cb in (64, 65):
                            if active_alert is not None:
                                # Scroll the modal
                                modal_scroll += 3 if cb == 65 else -3
                                modal_scroll = max(0, modal_scroll)
                            else:
                                offset += 15 if cb == 64 else -15
                            break
                        if is_rel:
                            # Button release — ignore
                            continue
                        if cb == 0:
                            # Left button press (not release, not motion)
                            row_idx = cy - 1  # 1-based → 0-based
                            if active_alert is not None:
                                # Click while modal open — dismiss
                                active_alert = None
                                modal_scroll = 0
                                break
                            elif row_idx in alert_row_map:
                                active_alert = alert_row_map[row_idx]
                                modal_scroll = 0
                                break
                        if cb & 32:  # motion
                            mouse_pos = (cx, cy)
                            break
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        cleanup = ""
        if mouse:
            cleanup += "\033[?1003l\033[?1006l"
        cleanup += "\033[?25h\033[?1049l"
        sys.stdout.write(cleanup)
        sys.stdout.flush()
