"""Terminal theme probing and derived color helpers.

Theme colors are queried once via OSC and cached at import time.
If the terminal does not answer quickly, a fallback dark palette is used.

The theme can change while a live view is open (the user switches their
terminal's colour scheme; on Omarchy, `omarchy-theme-set` pushes new
colours into every running terminal).  Modules that derive colours from
the theme at import time register a rebuild with `on_reload`, and the
live loop re-probes the terminal now and then; when the answer differs,
`_apply` swaps the theme, bumps `generation`, and runs every rebuild in
registration order — which is import order, so a module's own palette is
rebuilt before the modules that copied names out of it re-import them.
"""

from __future__ import annotations

import colorsys
import os
import re
import select
import sys
import time
from typing import Iterable

try:  # POSIX-only terminal control; absent on Windows
    import termios
    import tty
except ImportError:  # pragma: no cover - Windows only
    termios = tty = None

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

# Bumped on every applied theme change.  Render caches that bake theme
# colours into their buffers fold this into their keys, so a change
# simply misses instead of needing to be cleared under each cache's lock.
generation = 0

_reload_hooks = []


def _clamp_channel(v):
    try:
        n = int(round(v))
    except Exception:
        n = 0
    return max(0, min(255, n))


def clamp_rgb(color: RGB) -> RGB:
    return (_clamp_channel(color[0]), _clamp_channel(color[1]), _clamp_channel(color[2]))


def lerp_rgb(c1: RGB, c2: RGB, t: float) -> RGB:
    """Linear interpolate between two RGB tuples, rounding and clamping
    each channel.  _color.lerp truncates instead; the two are not
    interchangeable (see its docstring)."""
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


def best_contrast(candidates: Iterable[RGB], background: RGB | None = None,
                  minimum: float = 2.0) -> RGB:
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


# ---------------------------------------------------------------------------
# Hue transfer: re-inking a calibrated palette in the theme's own hues
# ---------------------------------------------------------------------------
# The ANSI slots standing at each canonical sixth of the hue wheel:
# red 0°, yellow 60°, green 120°, cyan 180°, blue 240°, magenta 300°.
_HUE_SLOTS = (1, 3, 2, 6, 4, 5)


def _with_luminance(color: RGB, target: float) -> RGB:
    """Nudge color toward black/white until its luminance matches target."""
    y = luminance(color)
    if abs(y - target) < 0.001:
        return color
    lighter = y < target
    pole = (255, 255, 255) if lighter else (0, 0, 0)
    lo, hi = 0.0, 1.0
    for _ in range(14):
        mid = (lo + hi) / 2.0
        if (luminance(lerp_rgb(color, pole, mid)) < target) == lighter:
            lo = mid
        else:
            hi = mid
    return lerp_rgb(color, pole, (lo + hi) / 2.0)


def themed(color: RGB) -> RGB:
    """Re-ink a calibrated color in the terminal theme's own hues.

    The maps palettes are luminance ladders first and hues second — the
    hillshade multiplies them, the coastline is derived from them — so
    adapting them to a theme cannot mean picking ANSI slots the way the
    weather palette does.  Instead the color keeps its luminance and
    its own saturation, and takes its hue from where the theme's ANSI
    colors sit at that point on the wheel: on a near-canonical theme
    that is close to the identity, and on a green-monochrome theme every
    hue collapses to the theme's green while the ladder stays readable.

    Saturation is scaled by the square root of the theme anchor's own
    saturation: the reference ANSI hues real themes are judged against
    are themselves only about half saturated, so a full ratio would
    double-count and wash a normal pastel theme out, while a truly grey
    theme still greys the map all the way.

    Identity when no theme answered, in legacy mode, or below 256
    colors (the 16-color tables are quantized against the terminal's
    real palette already).
    """
    color = clamp_rgb(color)
    if not theme_available or theme_legacy_mode:
        return color
    from linecast._color import color_mode
    if color_mode() not in ("truecolor", "256"):
        return color
    r, g, b = color
    h, lum, s = colorsys.rgb_to_hls(r / 255.0, g / 255.0, b / 255.0)
    if s <= 0.001 or lum <= 0.0 or lum >= 1.0:
        return color
    x = (h * 6.0) % 6.0
    i = int(x)
    t = x - i
    h0, s0 = _theme_hue_anchor(i)
    h1, s1 = _theme_hue_anchor((i + 1) % 6)
    d = ((h1 - h0 + 0.5) % 1.0) - 0.5          # shortest arc h0 -> h1
    nh = (h0 + d * t) % 1.0
    ns = min(1.0, s * ((s0 + (s1 - s0) * t) ** 0.5))
    nr, ng, nb = colorsys.hls_to_rgb(nh, lum, ns)
    cand = clamp_rgb((nr * 255.0, ng * 255.0, nb * 255.0))
    return _with_luminance(cand, luminance(color))


def _theme_hue_anchor(sextant: int) -> tuple[float, float]:
    """(hue, saturation) of the theme color at canonical hue sextant/6."""
    r, g, b = theme_ansi[_HUE_SLOTS[sextant]]
    h, _l, s = colorsys.rgb_to_hls(r / 255.0, g / 255.0, b / 255.0)
    return h, s


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
    # (--theme now selects the radar colour palette; legacy palette mode is
    # reached via these flags or LINECAST_THEME)
    for token in sys.argv[1:]:
        if token.strip().lower() in ("--classic-colors", "--legacy-colors"):
            return True
    return False


def _legacy_mode_requested():
    raw = str(os.environ.get("LINECAST_THEME", "auto")).strip().lower()
    if raw in ("0", "false", "off", "none", "disabled", "classic", "legacy", "old"):
        return True
    return _argv_requests_legacy_mode()


def _query_theme_via_osc(timeout_s: float):
    # The probe needs raw mode and a select() on stdin, neither of which
    # Windows offers; fall back to the built-in palette there.
    if termios is None:
        return None

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
    global _theme_loaded, theme_fg, theme_bg, theme_ansi, theme_available
    global theme_legacy_mode
    if _theme_loaded:
        return theme_available
    _theme_loaded = True
    theme_fg, theme_bg, theme_ansi, theme_available, theme_legacy_mode = _load_theme()
    return theme_available



# ---------------------------------------------------------------------------
# Reloading: the theme can change under a live view
# ---------------------------------------------------------------------------
def on_reload(fn):
    """Register fn() to run after the theme changes.  Returns fn."""
    _reload_hooks.append(fn)
    return fn


def reimport_on_reload(namespace, module_name, *names):
    """After each theme change, re-bind `from module_name import names`
    into `namespace` (a module's globals()).  For modules that copied
    theme-derived constants out of another module at import time."""
    import importlib

    def _refresh():
        mod = importlib.import_module(module_name)
        for name in names:
            namespace[name] = getattr(mod, name)
    on_reload(_refresh)


def track_imports(namespace, module_name):
    """After each theme change, re-import into `namespace` (a module's
    globals()) every name it took from module_name.  The names are found
    once, now: those bound to the same object module_name binds them to,
    which is what `from module_name import ...` leaves behind.  One line
    at a module's tail, with no list to keep in step with its imports."""
    import importlib
    import types

    source = vars(importlib.import_module(module_name))
    names = [name for name, value in namespace.items()
             if not name.startswith("__")
             and not isinstance(value, types.ModuleType)
             and name in source and source[name] is value]
    reimport_on_reload(namespace, module_name, *names)


def _apply(fg_value, bg_value, ansi_value):
    """Install a new theme and run the rebuild hooks."""
    global theme_fg, theme_bg, theme_ansi, theme_available, generation
    theme_fg = clamp_rgb(fg_value)
    theme_bg = clamp_rgb(bg_value)
    theme_ansi = tuple(clamp_rgb(c) for c in ansi_value)
    theme_available = True
    generation += 1
    for hook in list(_reload_hooks):
        hook()


def _is_current(fg_value, bg_value, ansi_value):
    return (clamp_rgb(fg_value) == theme_fg and clamp_rgb(bg_value) == theme_bg
            and tuple(clamp_rgb(c) for c in ansi_value) == theme_ansi)


def reload(timeout_s=None):
    """Re-probe the terminal synchronously.  True if the theme changed.

    Only meaningful once a probe has succeeded: a terminal that never
    answered is not asked again, and legacy mode is never re-themed.
    """
    if theme_legacy_mode or not theme_available:
        return False
    queried = _query_theme_via_osc(_theme_query_timeout() if timeout_s is None else timeout_s)
    if queried is None or _is_current(*queried):
        return False
    _apply(*queried)
    return True


# The live loop's probe is asynchronous: the query goes out on stdout and
# the terminal's replies come back interleaved with keystrokes, where the
# key reader hands each OSC body to ingest_osc.  A probe is complete when
# fg, bg and all sixteen ANSI slots have answered.
_PROBE_QUERY = ("\033]10;?\007\033]11;?\007"
                + "".join(f"\033]4;{idx};?\007" for idx in range(16))).encode("ascii")
_probe = None        # {"fg": rgb, "bg": rgb, "ansi": {idx: rgb}, "started": monotonic}
_PROBE_STALE_S = 2.0


def can_reprobe():
    return theme_available and not theme_legacy_mode


def request_probe(fd_out):
    """Ask the terminal for its colours; replies arrive via ingest_osc."""
    global _probe
    if not can_reprobe():
        return False
    try:
        os.write(fd_out, _PROBE_QUERY)
    except OSError:
        return False
    _probe = {"fg": None, "bg": None, "ansi": {}, "started": time.monotonic()}
    return True


def probe_pending():
    global _probe
    if _probe is None:
        return False
    if time.monotonic() - _probe["started"] > _PROBE_STALE_S:
        _probe = None   # the terminal stopped answering; try again later
        return False
    return True


def ingest_osc(body):
    """Take one OSC reply body (bytes between ESC ] and its terminator).

    Returns True when this reply completed a probe whose answer differs
    from the current theme — the theme has just been swapped and the
    caller should re-render.
    """
    global _probe
    if _probe is None:
        return False
    text = body.decode("utf-8", errors="ignore") if isinstance(body, bytes) else body
    match = _OSC_RESPONSE_RE.match("\x1b]" + text + "\x07")
    if match is None:
        return False
    rgb = _parse_rgb_value(match.group("rgb"))
    if rgb is None:
        return False
    op = match.group("op")
    if op == "10":
        _probe["fg"] = rgb
    elif op == "11":
        _probe["bg"] = rgb
    else:
        idx = int(match.group("idx"))
        if 0 <= idx <= 15:
            _probe["ansi"][idx] = rgb
    if _probe["fg"] is None or _probe["bg"] is None or len(_probe["ansi"]) < 16:
        return False
    answer = (_probe["fg"], _probe["bg"], tuple(_probe["ansi"][i] for i in range(16)))
    _probe = None
    if _is_current(*answer):
        return False
    _apply(*answer)
    return True


def poll_interval():
    """Seconds between live re-probes; 0 disables.  LINECAST_THEME_POLL."""
    raw = str(os.environ.get("LINECAST_THEME_POLL", "2")).strip()
    try:
        value = float(raw)
    except ValueError:
        value = 2.0
    return max(0.0, value)


def watch_path():
    """A file whose mtime changes when the desktop theme does, so the live
    loop can re-probe at once instead of waiting for the next poll.
    Defaults to Omarchy's current-theme marker; LINECAST_THEME_WATCH
    overrides (empty disables)."""
    raw = os.environ.get("LINECAST_THEME_WATCH")
    if raw is None:
        raw = os.path.expanduser("~/.local/state/omarchy/current/theme.name")
    raw = raw.strip()
    return raw or None


ensure_theme_loaded()
