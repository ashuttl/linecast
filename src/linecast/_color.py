"""ANSI color helpers and color math.

Provides terminal color mode detection (truecolor → 256 → 16 → none),
RGB-to-escape-code conversion with LRU caching, and color interpolation
utilities.

Respects NO_COLOR (https://no-color.org/), CLICOLOR/CLICOLOR_FORCE
(http://bixense.com/clicolors/), and LINECAST_COLOR for manual override.
"""

import functools
import math
import os
import sys
from linecast._theme import ensure_theme_loaded, theme_bg

# ---------------------------------------------------------------------------
# Color mode constants
# ---------------------------------------------------------------------------
_COLOR_TRUECOLOR = "truecolor"
_COLOR_256 = "256"
_COLOR_16 = "16"
_COLOR_NONE = "none"

# xterm-256 6x6x6 color cube levels (indices 16–231)
_CUBE_LEVELS = (0, 95, 135, 175, 215, 255)

# Standard ANSI 16-color palette (indices 0–15) as approximate sRGB values
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
    # Theme probing is part of terminal capability setup and runs once.
    if environ is None and stream is None:
        ensure_theme_loaded()

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

BG_PRIMARY = theme_bg


def color_mode():
    """Current terminal color mode: truecolor, 256, 16, or none."""
    return _COLOR_MODE


# ---------------------------------------------------------------------------
# RGB → escape code conversion (cached for performance)
# ---------------------------------------------------------------------------
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
