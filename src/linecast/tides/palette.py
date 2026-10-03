"""The tide view's inks: the curve, the lines for now and the pointer,
the station and time pills, the moon's rising and setting, and the
tooltips.  Rebuilt when the theme changes; the view and the chart
helpers both take them from here.
"""

from linecast.terminal import theme as _theme
from linecast.terminal.color import fg
from linecast.terminal.theme import (
    best_contrast,
    ensure_contrast,
    is_light_theme,
    lerp_rgb,
    neutral_tone,
    surface_bg,
)


def _rebuild():
    global CURVE_COLOR, NOW_LINE_COLOR, HOVER_COLOR, DIM_RGB, MUTED_RGB
    global TIP_DIM_RGB
    global TEXT_RGB, PILL_BG_RGB, PILL_FG_RGB, NOW_PILL_RGB, NOW_PILL_TEXT_RGB
    global DIM, NIGHT_DIM, MOON_RISE_RGB, MOON_SET_RGB, TIP_BG_RGB, TIP_TEXT_RGB
    CURVE_COLOR = ensure_contrast(
        best_contrast((_theme.theme_ansi[6], _theme.theme_ansi[14], _theme.theme_fg), minimum=2.0),
        _theme.theme_bg, minimum=2.0)
    NOW_LINE_COLOR = ensure_contrast(
        lerp_rgb(best_contrast((_theme.theme_ansi[4], _theme.theme_ansi[12]), minimum=2.0),
                 _theme.theme_bg, 0.30),
        minimum=1.8,
    )
    HOVER_COLOR = ensure_contrast(surface_bg(0.40), _theme.theme_bg, minimum=1.5)
    DIM_RGB = ensure_contrast(neutral_tone(0.32), _theme.theme_bg, minimum=2.0)
    MUTED_RGB = ensure_contrast(neutral_tone(0.48), _theme.theme_bg, minimum=2.5)
    TEXT_RGB = ensure_contrast(_theme.theme_fg, _theme.theme_bg, minimum=4.5)
    PILL_BG_RGB = surface_bg(0.08)
    PILL_FG_RGB = ensure_contrast(TEXT_RGB, PILL_BG_RGB, minimum=4.5)
    NOW_PILL_RGB = ensure_contrast(
        best_contrast((_theme.theme_ansi[6], _theme.theme_ansi[14]), minimum=2.0),
        _theme.theme_bg, minimum=2.0)
    NOW_PILL_TEXT_RGB = best_contrast(((12, 20, 30), _theme.theme_bg, _theme.theme_fg),
                                      background=NOW_PILL_RGB, minimum=4.5)
    MOON_RISE_RGB = ensure_contrast(
        best_contrast((_theme.theme_ansi[5], _theme.theme_ansi[13]), minimum=2.0),
        _theme.theme_bg, minimum=2.0)
    MOON_SET_RGB = ensure_contrast(
        lerp_rgb(best_contrast((_theme.theme_ansi[4], _theme.theme_ansi[12]), minimum=2.0),
                 _theme.theme_ansi[5], 0.35),
        minimum=2.0,
    )
    TIP_BG_RGB, TIP_TEXT_RGB, TIP_DIM_RGB = _theme.chip_inks()
    DIM = fg(*DIM_RGB)
    NIGHT_DIM = 0.6 if not is_light_theme() else 0.78


_rebuild()
_theme.on_reload(_rebuild)
