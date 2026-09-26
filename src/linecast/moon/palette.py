"""The moon's inks: the disc, its halo, the stars, and the panel.

Rebuilt when the theme changes.  The month calendar and the sky view
draw the same Moon, so they take its inks from here.
"""

from linecast.terminal import theme as _theme
from linecast.terminal.theme import (
    best_contrast,
    darken,
    ensure_contrast,
    is_light_theme,
    lerp_rgb,
    neutral_tone,
    surface_bg,
    theme_legacy_mode,
)
from linecast.sunshine.palette import INFO_AMBER_RGB, INFO_DIM_RGB, INFO_PURPLE_RGB, INFO_TEXT_RGB

_theme.track_imports(globals(), "linecast.sunshine.palette")


def _rebuild():
    global MOON_LIT_RGB, MOON_SHADOW_RGB, MOON_NIGHT_RGB, MOON_GLOW_RGB, SKY_RGB
    global STAR_BRIGHT_RGB, STAR_RGB, STAR_DIM_RGB
    global PANEL_TEXT_RGB, PANEL_DIM_RGB, PANEL_AMBER_RGB, PANEL_PURPLE_RGB
    global PANEL_FAINT_RGB
    SKY_RGB = _theme.theme_bg
    if theme_legacy_mode:
        MOON_LIT_RGB = (228, 230, 238)
        MOON_SHADOW_RGB = (36, 40, 56)
        MOON_GLOW_RGB = (150, 160, 190)
        STAR_BRIGHT_RGB = (206, 214, 236)
        STAR_RGB = (150, 158, 180)
        STAR_DIM_RGB = (84, 92, 115)
    elif is_light_theme():
        # The night sky is dark whatever the terminal: a navy from the
        # theme's blue, with a white Moon and stars lifted from the sky.
        blue = best_contrast((_theme.theme_ansi[4], _theme.theme_ansi[12]),
                             minimum=1.8)
        SKY_RGB = darken(blue, 0.80)
        white = (250, 252, 255)
        MOON_LIT_RGB = white
        MOON_SHADOW_RGB = lerp_rgb(SKY_RGB, white, 0.10)
        MOON_GLOW_RGB = lerp_rgb(SKY_RGB, white, 0.55)
        STAR_BRIGHT_RGB = lerp_rgb(SKY_RGB, white, 0.85)
        STAR_RGB = lerp_rgb(SKY_RGB, white, 0.60)
        STAR_DIM_RGB = lerp_rgb(SKY_RGB, white, 0.38)
    else:
        MOON_LIT_RGB = best_contrast((_theme.theme_ansi[15], _theme.theme_fg), minimum=2.5)
        MOON_SHADOW_RGB = ensure_contrast(surface_bg(0.30), _theme.theme_bg, minimum=1.2)
        MOON_GLOW_RGB = ensure_contrast(neutral_tone(0.60), _theme.theme_bg, minimum=1.8)
        STAR_BRIGHT_RGB = ensure_contrast(neutral_tone(0.80), _theme.theme_bg, minimum=3.2)
        STAR_RGB = ensure_contrast(neutral_tone(0.58), _theme.theme_bg, minimum=2.2)
        STAR_DIM_RGB = ensure_contrast(neutral_tone(0.40), _theme.theme_bg, minimum=1.5)
    # The disc's night is darker than the sky around it, as it looks in
    # life, where the sky near the Moon is lit by the Moon and the night
    # side is lit by nothing but Earth; the halo outlines the disc. The
    # calendar's discs use the same night, so a day reads as the same
    # Moon at a smaller size.
    MOON_NIGHT_RGB = darken(SKY_RGB, 0.5)
    # The info sits in the sky in every layout, so its inks contrast
    # with the sky rather than the page.
    PANEL_TEXT_RGB = ensure_contrast(INFO_TEXT_RGB, SKY_RGB, minimum=4.5)
    PANEL_DIM_RGB = ensure_contrast(INFO_DIM_RGB, SKY_RGB, minimum=2.0)
    # A shade fainter than dim, for the counsel's source line.
    PANEL_FAINT_RGB = lerp_rgb(SKY_RGB, PANEL_DIM_RGB, 0.62)
    PANEL_AMBER_RGB = ensure_contrast(INFO_AMBER_RGB, SKY_RGB, minimum=2.3)
    PANEL_PURPLE_RGB = ensure_contrast(INFO_PURPLE_RGB, SKY_RGB, minimum=2.3)


_rebuild()
_theme.on_reload(_rebuild)
