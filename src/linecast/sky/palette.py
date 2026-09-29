"""The sky's inks: the night and the ground, the stars, the Moon, the
Milky Way, the figures and their names, and the text over them.  Rebuilt
when the theme changes.  The view takes them from here, and so does the
one-line summary, without loading the view.
"""

from linecast.terminal import theme as _theme
from linecast.terminal.theme import (
    best_contrast, darken, ensure_contrast, is_light_theme, lerp_rgb, neutral_tone,
    theme_legacy_mode,
)
from linecast.sunshine.palette import INFO_AMBER_RGB, INFO_DIM_RGB, INFO_TEXT_RGB, SKY_NIGHT

_theme.track_imports(globals(), "linecast.sunshine.palette")


def _rebuild():
    global NIGHT_RGB, HAZE_RGB, GROUND_RGB, MILKY_RGB, FIGURE_RGB
    global STAR_BRIGHT_RGB, STAR_RGB, STAR_DIM_RGB, MOON_LIT_RGB, MOON_GLOW_RGB
    global TEXT_RGB, DIM_RGB, AMBER_RGB, LABEL_RGB, FIGURE_NAME_RGB
    global TIP_BG_RGB, TIP_TEXT_RGB, TIP_DIM_RGB
    NIGHT_RGB = SKY_NIGHT
    if theme_legacy_mode:
        STAR_BRIGHT_RGB = (206, 214, 236)
        STAR_RGB = (150, 158, 180)
        STAR_DIM_RGB = (84, 92, 115)
        MOON_LIT_RGB = (228, 230, 238)
        MOON_GLOW_RGB = (150, 160, 190)
    elif is_light_theme():
        white = (250, 252, 255)
        STAR_BRIGHT_RGB = lerp_rgb(NIGHT_RGB, white, 0.85)
        STAR_RGB = lerp_rgb(NIGHT_RGB, white, 0.60)
        STAR_DIM_RGB = lerp_rgb(NIGHT_RGB, white, 0.38)
        MOON_LIT_RGB = white
        MOON_GLOW_RGB = lerp_rgb(NIGHT_RGB, white, 0.55)
    else:
        STAR_BRIGHT_RGB = ensure_contrast(neutral_tone(0.80), NIGHT_RGB, minimum=3.2)
        STAR_RGB = ensure_contrast(neutral_tone(0.58), NIGHT_RGB, minimum=2.2)
        STAR_DIM_RGB = ensure_contrast(neutral_tone(0.40), NIGHT_RGB, minimum=1.5)
        MOON_LIT_RGB = best_contrast((_theme.theme_ansi[15], _theme.theme_fg), minimum=2.5)
        MOON_GLOW_RGB = ensure_contrast(neutral_tone(0.60), NIGHT_RGB, minimum=1.8)
    # The night sky is lifted a little toward the horizon, as it is in
    # life, and the ground below is darker than any sky.
    HAZE_RGB = lerp_rgb(NIGHT_RGB, STAR_DIM_RGB, 0.55)
    GROUND_RGB = darken(NIGHT_RGB, 0.45)
    # The Milky Way is milk: pale, a touch blue, never bright.
    MILKY_RGB = lerp_rgb(STAR_RGB, (200, 215, 255), 0.25)
    # The figures are drawn a shade above the sky, the names dimmer than
    # any star label, so both stay behind the stars.
    FIGURE_RGB = STAR_DIM_RGB
    TEXT_RGB = ensure_contrast(INFO_TEXT_RGB, NIGHT_RGB, minimum=4.5)
    DIM_RGB = ensure_contrast(INFO_DIM_RGB, NIGHT_RGB, minimum=2.0)
    AMBER_RGB = ensure_contrast(INFO_AMBER_RGB, NIGHT_RGB, minimum=2.3)
    LABEL_RGB = ensure_contrast(neutral_tone(0.62), NIGHT_RGB, minimum=2.4)
    FIGURE_NAME_RGB = lerp_rgb(NIGHT_RGB, LABEL_RGB, 0.62)
    TIP_BG_RGB, TIP_TEXT_RGB, TIP_DIM_RGB = _theme.chip_inks()


_rebuild()
_theme.on_reload(_rebuild)
