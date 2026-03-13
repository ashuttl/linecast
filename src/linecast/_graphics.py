"""Shared terminal graphics library for half-block rendering.

This module is a backward-compatible facade. The implementation has been
split into focused modules for maintainability:

  _color.py        — ANSI color mode detection, escape code helpers, color math
  _framebuffer.py  — Framebuffer class, half-block rendering, text utilities
  _live.py         — Live mode loop, mouse/keyboard input handling

All public symbols are re-exported here so existing imports continue to work:

    from linecast._graphics import fg, bg, Framebuffer, live_loop  # still works
"""

# Color system
from linecast._color import (  # noqa: F401
    _COLOR_TRUECOLOR,
    _COLOR_256,
    _COLOR_16,
    _COLOR_NONE,
    _CUBE_LEVELS,
    _ANSI16_RGB,
    _normalize_color_mode,
    detect_color_mode,
    _COLOR_MODE,
    RESET,
    BOLD,
    BG_PRIMARY,
    color_mode,
    _channel,
    _rgb_to_xterm256,
    _rgb_to_ansi16,
    _fg_for_mode,
    _bg_for_mode,
    fg,
    bg,
    lerp,
    interp_stops,
)

# Rendering utilities and Framebuffer
from linecast._framebuffer import (  # noqa: F401
    HALF_BLOCK,
    halfblock,
    visible_len,
    fmt_time,
    fmt_hour,
    fmt_time_dt,
    get_terminal_size,
    Framebuffer,
)

# Live mode and input handling
from linecast._live import (  # noqa: F401
    _decode_sgr_mouse,
    _decode_legacy_mouse,
    _normalize_wheel_cb,
    _read_key,
    live_loop,
)
