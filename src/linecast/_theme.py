"""Terminal theme probing and derived color helpers.

Theme colors are queried once via OSC and cached at import time.
If the terminal does not answer quickly, a fallback dark palette is used.
"""

from __future__ import annotations

import os
import re
import select
import sys
import termios
import time
import tty
from typing import Iterable

RGB = tuple[int, int, int]

# Fallback palette mirrors the pre-theme hardcoded dark styling.
_FALLBACK_BG: RGB = (15, 23, 42)
_FALLBACK_FG: RGB = (200, 205, 215)
_FALLBACK_ANSI: tuple[RGB, ...] = (
    (15, 23, 42),      # 0 black
    (220, 60, 50),     # 1 red
    (60, 180, 120),    # 2 green
    (220, 170, 50),    # 3 yellow/amber
    (80, 140, 220),    # 4 blue
    (160, 140, 200),   # 5 magenta
    (50, 170, 180),    # 6 cyan
    (200, 205, 215),   # 7 white
    (100, 110, 130),   # 8 bright black
    (220, 60, 50),     # 9 bright red
    (140, 200, 70),    # 10 bright green
    (200, 200, 80),    # 11 bright yellow
    (100, 120, 210),   # 12 bright blue
    (180, 140, 210),   # 13 bright magenta
    (80, 160, 220),    # 14 bright cyan
    (200, 210, 225),   # 15 bright white
)

_OSC_RESPONSE_RE = re.compile(
    r"\x1b\](?P<op>10|11|4;(?P<idx>\d{1,2}));"
    r"(?P<rgb>rgb:[0-9a-fA-F]+/[0-9a-fA-F]+/[0-9a-fA-F]+)"
    r"(?:\x07|\x1b\\)"
)

theme_fg: RGB = _FALLBACK_FG
theme_bg: RGB = _FALLBACK_BG
theme_ansi: tuple[RGB, ...] = _FALLBACK_ANSI
theme_available = False
theme_legacy_mode = False

_theme_loaded = False


def _clamp_channel(v):
    try:
        n = int(round(v))
    except Exception:
        n = 0
    return max(0, min(255, n))


def clamp_rgb(color: RGB) -> RGB:
    return (_clamp_channel(color[0]), _clamp_channel(color[1]), _clamp_channel(color[2]))


def lerp_rgb(c1: RGB, c2: RGB, t: float) -> RGB:
    t = max(0.0, min(1.0, float(t)))
    return (
        _clamp_channel(c1[0] + (c2[0] - c1[0]) * t),
        _clamp_channel(c1[1] + (c2[1] - c1[1]) * t),
        _clamp_channel(c1[2] + (c2[2] - c1[2]) * t),
    )


def _to_linear(channel):
    x = max(0.0, min(1.0, channel / 255.0))
    if x <= 0.04045:
        return x / 12.92
    return ((x + 0.055) / 1.055) ** 2.4


def luminance(color: RGB) -> float:
    r, g, b = color
    lr = _to_linear(r)
    lg = _to_linear(g)
    lb = _to_linear(b)
    return 0.2126 * lr + 0.7152 * lg + 0.0722 * lb


def contrast_ratio(c1: RGB, c2: RGB) -> float:
    l1 = luminance(c1)
    l2 = luminance(c2)
    hi = max(l1, l2)
    lo = min(l1, l2)
    return (hi + 0.05) / (lo + 0.05)


def is_light_theme(bg_color: RGB | None = None) -> bool:
    if bg_color is None:
        bg_color = theme_bg
    return luminance(bg_color) > 0.5


def neutral_tone(level: float, fg_color: RGB | None = None, bg_color: RGB | None = None) -> RGB:
    """Return a neutral color on the theme fg/bg axis.

    level: 0.0 is closest to background, 1.0 is closest to foreground.
    On light themes this axis is flipped so DIM/MUTED stay visually lighter
    than text while still anchored to fg/bg.
    """
    if fg_color is None:
        fg_color = theme_fg
    if bg_color is None:
        bg_color = theme_bg
    level = max(0.0, min(1.0, level))
    if is_light_theme(bg_color):
        return lerp_rgb(fg_color, bg_color, level)
    return lerp_rgb(bg_color, fg_color, level)


def shift_to_pole(color: RGB, amount: float, lighter: bool) -> RGB:
    target = (255, 255, 255) if lighter else (0, 0, 0)
    return lerp_rgb(color, target, amount)


def lighten(color: RGB, amount: float) -> RGB:
    return shift_to_pole(color, amount, lighter=True)


def darken(color: RGB, amount: float) -> RGB:
    return shift_to_pole(color, amount, lighter=False)


def ensure_contrast(color: RGB, background: RGB | None = None, minimum: float = 2.0) -> RGB:
    """Nudge color toward high-contrast pole until minimum contrast is met."""
    if background is None:
        background = theme_bg
    if contrast_ratio(color, background) >= minimum:
        return color
    bg_is_light = is_light_theme(background)
    target = (0, 0, 0) if bg_is_light else (255, 255, 255)
    for step in range(1, 11):
        candidate = lerp_rgb(color, target, step / 10.0)
        if contrast_ratio(candidate, background) >= minimum:
            return candidate
    return lerp_rgb(color, target, 1.0)


def best_contrast(candidates: Iterable[RGB], background: RGB | None = None, minimum: float = 2.0) -> RGB:
    if background is None:
        background = theme_bg
    colors = [clamp_rgb(c) for c in candidates]
    if not colors:
        return ensure_contrast(theme_fg, background, minimum=minimum)
    best = max(colors, key=lambda c: contrast_ratio(c, background))
    return ensure_contrast(best, background, minimum=minimum)


def surface_bg(level: float) -> RGB:
    """Theme-aware surface color that separates from the main background."""
    return lerp_rgb(theme_bg, theme_fg, max(0.0, min(1.0, level)))


def _hex_channel_to_8bit(text: str):
    if not text:
        return None
    try:
        value = int(text, 16)
    except ValueError:
        return None
    max_value = (1 << (len(text) * 4)) - 1
    if max_value <= 0:
        return None
    return _clamp_channel((value * 255) / max_value)


def _parse_rgb_value(rgb_value: str):
    if not rgb_value or not rgb_value.startswith("rgb:"):
        return None
    parts = rgb_value[4:].split("/")
    if len(parts) != 3:
        return None
    channels = [_hex_channel_to_8bit(part) for part in parts]
    if any(ch is None for ch in channels):
        return None
    return channels[0], channels[1], channels[2]


def _theme_query_timeout():
    raw = str(os.environ.get("LINECAST_THEME_TIMEOUT_MS", "100")).strip()
    try:
        ms = int(raw)
    except ValueError:
        ms = 100
    ms = max(10, min(1000, ms))
    return ms / 1000.0


def _argv_requests_legacy_mode():
    args = tuple(sys.argv[1:])
    for i, token in enumerate(args):
        low = token.strip().lower()
        if low in ("--classic-colors", "--legacy-colors"):
            return True
        if low.startswith("--theme="):
            value = low.split("=", 1)[1]
            if value in ("classic", "legacy", "old"):
                return True
        if low == "--theme" and i + 1 < len(args):
            value = str(args[i + 1]).strip().lower()
            if value in ("classic", "legacy", "old"):
                return True
    return False


def _legacy_mode_requested():
    raw = str(os.environ.get("LINECAST_THEME", "auto")).strip().lower()
    if raw in ("0", "false", "off", "none", "disabled", "classic", "legacy", "old"):
        return True
    return _argv_requests_legacy_mode()


def _query_theme_via_osc(timeout_s: float):
    stdin = sys.stdin
    stdout = sys.stdout

    try:
        if not (stdin.isatty() and stdout.isatty()):
            return None
    except Exception:
        return None

    term = str(os.environ.get("TERM", "")).strip().lower()
    if term in ("", "dumb"):
        return None

    try:
        fd_in = stdin.fileno()
        fd_out = stdout.fileno()
    except Exception:
        return None

    query = "".join(
        ["\033]10;?\007", "\033]11;?\007"]
        + [f"\033]4;{idx};?\007" for idx in range(16)]
    )
    fg_value = None
    bg_value = None
    ansi_values = {}

    try:
        old_settings = termios.tcgetattr(fd_in)
    except Exception:
        return None

    deadline = time.monotonic() + timeout_s
    buf = ""
    try:
        tty.setraw(fd_in)
        os.write(fd_out, query.encode("ascii", errors="ignore"))
        try:
            stdout.flush()
        except Exception:
            pass

        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                ready, _, _ = select.select([fd_in], [], [], remaining)
            except (InterruptedError, OSError):
                continue
            if not ready:
                break
            try:
                chunk = os.read(fd_in, 4096)
            except OSError:
                break
            if not chunk:
                break
            buf += chunk.decode("utf-8", errors="ignore")
            if len(buf) > 16384:
                buf = buf[-8192:]
            for match in _OSC_RESPONSE_RE.finditer(buf):
                rgb = _parse_rgb_value(match.group("rgb"))
                if rgb is None:
                    continue
                op = match.group("op")
                if op == "10":
                    fg_value = rgb
                elif op == "11":
                    bg_value = rgb
                else:
                    idx_text = match.group("idx")
                    if idx_text is None:
                        continue
                    try:
                        idx = int(idx_text)
                    except ValueError:
                        continue
                    if 0 <= idx <= 15:
                        ansi_values[idx] = rgb
            if fg_value is not None and bg_value is not None and len(ansi_values) == 16:
                break
    finally:
        try:
            termios.tcsetattr(fd_in, termios.TCSADRAIN, old_settings)
        except Exception:
            pass

    if fg_value is None or bg_value is None or len(ansi_values) < 16:
        return None
    ansi = tuple(ansi_values[i] for i in range(16))
    return fg_value, bg_value, ansi


def _load_theme():
    if _legacy_mode_requested():
        return _FALLBACK_FG, _FALLBACK_BG, _FALLBACK_ANSI, False, True
    queried = _query_theme_via_osc(_theme_query_timeout())
    if queried is None:
        return _FALLBACK_FG, _FALLBACK_BG, _FALLBACK_ANSI, False, False
    fg_value, bg_value, ansi_value = queried
    return (
        clamp_rgb(fg_value),
        clamp_rgb(bg_value),
        tuple(clamp_rgb(c) for c in ansi_value),
        True,
        False,
    )


def ensure_theme_loaded():
    """Load theme once and cache module-level values."""
    global _theme_loaded, theme_fg, theme_bg, theme_ansi, theme_available, theme_legacy_mode
    if _theme_loaded:
        return theme_available
    _theme_loaded = True
    theme_fg, theme_bg, theme_ansi, theme_available, theme_legacy_mode = _load_theme()
    return theme_available


ensure_theme_loaded()
