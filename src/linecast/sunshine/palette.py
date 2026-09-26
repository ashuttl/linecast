"""Sunshine's inks and sky gradients, rebuilt when the theme changes.

The sky view, the moon view and the one-line summaries draw with the
same inks, so they take them from here rather than from the sunshine
command.
"""

from linecast.terminal import theme as _theme
from linecast.terminal.graphics import BG_PRIMARY, color_mode, lerp
from linecast.terminal.theme import (
    best_contrast,
    darken,
    ensure_contrast,
    is_light_theme,
    lerp_rgb,
    neutral_tone,
    theme_legacy_mode,
)

_theme.track_imports(globals(), "linecast.terminal.color")

# The sun is drawn, not typeset: a white dot in a gold halo on every
# theme. Theme-derived inks are contrast-checked against the page, which
# greys the dot and buries the glow in a light theme's day. Shared with
# the year view.
SUN_DOT_RGB = (255, 255, 255)
SUN_GLOW_RGB = (255, 214, 120)


def _rebuild():
    global HORIZON_COLOR, CURVE_COLOR, SUN_GLOW_TWILIGHT_RGB
    global INFO_AMBER_RGB, INFO_PURPLE_RGB, INFO_MUTED_RGB
    global INFO_DIM_RGB, INFO_TEXT_RGB, _SKY_BLUE, _SKY_CYAN, _SKY_MAGENTA
    global _SKY_RED, _SKY_YELLOW, _SKY_WHITE, SKY_NIGHT
    SKY_NIGHT = BG_PRIMARY
    if theme_legacy_mode:
        # Original pre-theme palette (classic mode).
        HORIZON_COLOR = (90, 98, 125)
        CURVE_COLOR = (160, 168, 195)
        SUN_GLOW_TWILIGHT_RGB = (180, 195, 225)
        INFO_AMBER_RGB = (251, 191, 36)
        INFO_PURPLE_RGB = (167, 139, 250)
        INFO_MUTED_RGB = (100, 110, 130)
        INFO_DIM_RGB = (70, 80, 100)
        INFO_TEXT_RGB = (200, 205, 215)
    else:
        _SKY_BLUE = best_contrast(
            (_theme.theme_ansi[4], _theme.theme_ansi[12], _theme.theme_ansi[6]), minimum=1.8)
        _SKY_CYAN = best_contrast(
            (_theme.theme_ansi[6], _theme.theme_ansi[14], _theme.theme_fg), minimum=1.8)
        _SKY_MAGENTA = best_contrast((_theme.theme_ansi[5], _theme.theme_ansi[13]), minimum=1.8)
        _SKY_RED = best_contrast((_theme.theme_ansi[1], _theme.theme_ansi[9]), minimum=1.8)
        _SKY_YELLOW = best_contrast((_theme.theme_ansi[3], _theme.theme_ansi[11]), minimum=1.8)
        _SKY_WHITE = best_contrast((_theme.theme_ansi[15], _theme.theme_fg), minimum=2.0)

        # Night is dark whatever the terminal. On a light theme the sky
        # sits on a navy from the theme's blue, not the page, and the
        # inks drawn over the sky contrast with that.
        if is_light_theme():
            SKY_NIGHT = darken(_SKY_BLUE, 0.80)
            _SKY_WHITE = (250, 252, 255)

        # hairline divider
        HORIZON_COLOR = ensure_contrast(neutral_tone(0.45), SKY_NIGHT, minimum=1.7)
        # neutral arc
        CURVE_COLOR = ensure_contrast(neutral_tone(0.74), SKY_NIGHT, minimum=2.4)
        SUN_GLOW_TWILIGHT_RGB = ensure_contrast(
            lerp_rgb(_SKY_BLUE, _SKY_WHITE, 0.45), SKY_NIGHT, minimum=1.6)
        INFO_AMBER_RGB = ensure_contrast(_SKY_YELLOW, _theme.theme_bg, minimum=2.3)
        INFO_PURPLE_RGB = ensure_contrast(_SKY_MAGENTA, _theme.theme_bg, minimum=2.3)
        INFO_MUTED_RGB = ensure_contrast(neutral_tone(0.48), _theme.theme_bg, minimum=2.4)
        INFO_DIM_RGB = ensure_contrast(neutral_tone(0.32), _theme.theme_bg, minimum=2.0)
        INFO_TEXT_RGB = ensure_contrast(_theme.theme_fg, _theme.theme_bg, minimum=4.5)


def _rebuild_sky():
    global SKY_NEAR_HORIZON, SKY_FAR_HORIZON, SKY_ZENITH
    # Sky palette: sun elevation → colors at horizon (near/far from sun) and zenith
    if theme_legacy_mode:
        SKY_NEAR_HORIZON = [   # warm side — sky color near the sun at the horizon
            (-18, BG_PRIMARY),
            (-12, (35, 18, 58)),
            ( -6, (115, 55, 75)),
            ( -3, (185, 80, 60)),
            (  0, (245, 135, 40)),
            (  3, (248, 175, 55)),
            (  8, (230, 195, 85)),
            ( 15, (195, 215, 242)),
            ( 30, (208, 228, 255)),
            ( 90, (218, 238, 255)),
        ]

        SKY_FAR_HORIZON = [    # cool side — sky color far from the sun at the horizon
            (-18, BG_PRIMARY),
            (-12, (28, 15, 52)),
            ( -6, (90, 40, 98)),
            ( -3, (160, 55, 108)),
            (  0, (205, 85, 110)),
            (  3, (190, 105, 125)),
            (  8, (168, 135, 160)),
            ( 15, (182, 208, 238)),
            ( 30, (202, 224, 252)),
            ( 90, (214, 234, 254)),
        ]

        SKY_ZENITH = [         # sky color at the top of the display
            (-18, BG_PRIMARY),
            (-12, (18, 14, 38)),
            ( -6, (30, 20, 55)),
            ( -3, (48, 28, 72)),
            (  0, (70, 38, 95)),
            (  3, (62, 55, 128)),
            (  8, (52, 82, 158)),
            ( 15, (78, 132, 208)),
            ( 30, (112, 170, 240)),
            ( 90, (132, 188, 250)),
        ]
    else:
        night = SKY_NIGHT
        SKY_NEAR_HORIZON = [   # warm side — sky color near the sun at the horizon
            (-18, night),
            (-12, darken(lerp_rgb(night, _SKY_MAGENTA, 0.18), 0.10)),
            ( -6, lerp_rgb(night, _SKY_RED, 0.35)),
            ( -3, lerp_rgb(_SKY_RED, _SKY_MAGENTA, 0.20)),
            (  0, lerp_rgb(_SKY_YELLOW, _SKY_RED, 0.28)),
            (  3, lerp_rgb(_SKY_YELLOW, _SKY_WHITE, 0.20)),
            (  8, lerp_rgb(_SKY_YELLOW, _SKY_CYAN, 0.35)),
            ( 15, lerp_rgb(_SKY_CYAN, _SKY_WHITE, 0.55)),
            ( 30, lerp_rgb(_SKY_CYAN, _SKY_WHITE, 0.72)),
            ( 90, lerp_rgb(_SKY_CYAN, _SKY_WHITE, 0.82)),
        ]

        SKY_FAR_HORIZON = [    # cool side — sky color far from the sun at the horizon
            (-18, night),
            (-12, darken(lerp_rgb(night, _SKY_MAGENTA, 0.14), 0.12)),
            ( -6, lerp_rgb(night, _SKY_MAGENTA, 0.30)),
            ( -3, lerp_rgb(_SKY_MAGENTA, _SKY_RED, 0.30)),
            (  0, lerp_rgb(_SKY_RED, _SKY_MAGENTA, 0.30)),
            (  3, lerp_rgb(_SKY_RED, _SKY_CYAN, 0.25)),
            (  8, lerp_rgb(_SKY_MAGENTA, _SKY_CYAN, 0.40)),
            ( 15, lerp_rgb(_SKY_BLUE, _SKY_WHITE, 0.52)),
            ( 30, lerp_rgb(_SKY_BLUE, _SKY_WHITE, 0.70)),
            ( 90, lerp_rgb(_SKY_BLUE, _SKY_WHITE, 0.80)),
        ]

        SKY_ZENITH = [         # sky color at the top of the display
            (-18, night),
            (-12, darken(lerp_rgb(night, _SKY_BLUE, 0.10), 0.14)),
            ( -6, darken(lerp_rgb(night, _SKY_BLUE, 0.18), 0.08)),
            ( -3, lerp_rgb(night, _SKY_MAGENTA, 0.22)),
            (  0, lerp_rgb(_SKY_MAGENTA, _SKY_BLUE, 0.32)),
            (  3, lerp_rgb(_SKY_MAGENTA, _SKY_BLUE, 0.48)),
            (  8, lerp_rgb(_SKY_BLUE, _SKY_CYAN, 0.22)),
            ( 15, lerp_rgb(_SKY_BLUE, _SKY_CYAN, 0.45)),
            ( 30, lerp_rgb(_SKY_BLUE, _SKY_WHITE, 0.48)),
            ( 90, lerp_rgb(_SKY_BLUE, _SKY_WHITE, 0.62)),
        ]


def _tame_for_mode():
    """Below truecolor, pull the sky toward gray.

    The 6-level xterm cube has no entry that keeps a muted blue-cyan's
    hue: adjacent gradient blends snap to purple, teal and lavender in
    turn, and the smooth sky renders as rainbow rings.  Near gray the
    quantizer uses the 24-step ramp instead, which stays smooth, so
    trade the chroma away.  Saturated stops (the sunset band) keep most
    of their colour; the muted mid-sky gives up the most.
    """
    global SKY_NEAR_HORIZON, SKY_FAR_HORIZON, SKY_ZENITH
    global SUN_GLOW_TWILIGHT_RGB
    if color_mode() not in ("256", "16"):
        return

    def tamed(rgb):
        r, g, b = rgb
        luma = int(0.30 * r + 0.59 * g + 0.11 * b)
        return lerp((r, g, b), (luma, luma, luma), 0.55)

    SKY_NEAR_HORIZON = [(e, tamed(c)) for e, c in SKY_NEAR_HORIZON]
    SKY_FAR_HORIZON = [(e, tamed(c)) for e, c in SKY_FAR_HORIZON]
    SKY_ZENITH = [(e, tamed(c)) for e, c in SKY_ZENITH]
    SUN_GLOW_TWILIGHT_RGB = tamed(SUN_GLOW_TWILIGHT_RGB)


def _rebuild_all():
    _rebuild()
    _rebuild_sky()
    _tame_for_mode()


_rebuild_all()
_theme.on_reload(_rebuild_all)
