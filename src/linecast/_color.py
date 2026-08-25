"""ANSI color helpers and color math.

Provides terminal color mode detection (truecolor → 256 → 16 → none),
RGB-to-escape-code conversion with LRU caching, and color interpolation
utilities.

Respects NO_COLOR (https://no-color.org/), CLICOLOR/CLICOLOR_FORCE
(http://bixense.com/clicolors/), and LINECAST_COLOR for manual override.
"""

import functools
import os
import sys
from linecast import _theme
from linecast._theme import _clamp_channel as _channel, ensure_theme_loaded

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


def _enable_windows_vt(stream):
    """Switch on ANSI processing for a Windows console.

    Windows Terminal enables it already; the classic conhost does not, and
    without it escape codes are printed literally.  Returns False when the
    stream is not a console at all (redirected to a file or pipe), which is
    the same "no colour" answer the TERM check gives elsewhere.
    """
    try:
        import ctypes
        import msvcrt
        from ctypes import wintypes
    except ImportError:
        return False
    ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
    try:
        handle = msvcrt.get_osfhandle(stream.fileno())
        kernel32 = ctypes.windll.kernel32
        mode = wintypes.DWORD()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False  # not a console
        if mode.value & ENABLE_VIRTUAL_TERMINAL_PROCESSING:
            return True
        return bool(kernel32.SetConsoleMode(
            handle, mode.value | ENABLE_VIRTUAL_TERMINAL_PROCESSING))
    except Exception:
        return False


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
    # Windows consoles do not set TERM, so an empty TERM says nothing about
    # capability there; the console itself is asked further down instead.
    windows = sys.platform == "win32"
    if term == "dumb" or (term == "" and not windows):
        return _COLOR_NONE

    if stream is None:
        stream = sys.stdout
    try:
        is_tty = bool(stream.isatty())
    except Exception:
        is_tty = False

    force = str(env.get("CLICOLOR_FORCE", "")).strip()
    forced = bool(force and force != "0")
    if forced:
        is_tty = True
    if not is_tty:
        return _COLOR_NONE

    if windows:
        # Windows Terminal and conhost from Windows 10 1703 on are all
        # 24-bit capable, so the only question is whether VT is switched on.
        if forced or _enable_windows_vt(stream):
            return _COLOR_TRUECOLOR
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

BG_PRIMARY = _theme.theme_bg


@_theme.on_reload
def _rebuild():
    global BG_PRIMARY
    BG_PRIMARY = _theme.theme_bg


def color_mode():
    """Current terminal color mode: truecolor, 256, 16, or none."""
    return _COLOR_MODE


# ---------------------------------------------------------------------------
# RGB → escape code conversion (cached for performance)
# ---------------------------------------------------------------------------
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
    # The gray ramp only competes for near-neutral colors: by raw
    # distance it wins whole families the 6-level cube serves badly
    # (desaturated forest greens, violet settlement), and turning a hue
    # into gray is a worse lie than snapping it to the nearest cube
    # hue.  The threshold sits between street mode's dark water fill
    # (spread 32, which *wants* the ramp so the dark fills keep their
    # value ladder) and terrain's urban violet (spread 36).
    if gray_dist < cube_dist and max(r, g, b) - min(r, g, b) < 34:
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


# fg and bg are the hot path of every compose, and most calls repeat a
# few hundred colours.  The caches above key on clamped ints, so each
# call still clamped three channels first — about 60% of compose time.
# These memos key on the raw arguments instead, plus the colour mode
# (tests swap it), so a repeated colour costs one dict probe.  Nothing
# here depends on the theme, so a reload leaves them alone; they are
# cleared when full.
_FG_MEMO = {}
_BG_MEMO = {}
_MEMO_LIMIT = 16384


def fg(r, g, b):
    key = (_COLOR_MODE, r, g, b)
    try:
        code = _FG_MEMO.get(key)
    except TypeError:    # an unhashable channel; _channel makes it 0
        return _fg_for_mode(_COLOR_MODE, _channel(r), _channel(g), _channel(b))
    if code is None:
        if len(_FG_MEMO) >= _MEMO_LIMIT:
            _FG_MEMO.clear()
        code = _FG_MEMO[key] = _fg_for_mode(
            _COLOR_MODE, _channel(r), _channel(g), _channel(b))
    return code


def bg(r, g, b):
    key = (_COLOR_MODE, r, g, b)
    try:
        code = _BG_MEMO.get(key)
    except TypeError:
        return _bg_for_mode(_COLOR_MODE, _channel(r), _channel(g), _channel(b))
    if code is None:
        if len(_BG_MEMO) >= _MEMO_LIMIT:
            _BG_MEMO.clear()
        code = _BG_MEMO[key] = _bg_for_mode(
            _COLOR_MODE, _channel(r), _channel(g), _channel(b))
    return code


# ---------------------------------------------------------------------------
# Color math
# ---------------------------------------------------------------------------
def lerp(c1, c2, t):
    """Linear interpolate between two RGB tuples, truncating each channel.

    Not interchangeable with _theme.lerp_rgb, which rounds and clamps:
    at t=0.5 between black and white this gives 127 and that gives 128.
    The framebuffer blends the same sub-pixel several times over (fill,
    then glow, then curve), and the one-unit difference compounds to as
    much as four in the sunshine sky, so swapping one for the other
    moves rendered pixels.  Inputs are trusted: channels are not clamped.
    """
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
