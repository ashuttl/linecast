"""Shared weather rendering palette and low-level color/format helpers."""

from linecast._graphics import fg, interp_stops
from linecast import _theme
from linecast._theme import (
    best_contrast,
    darken,
    ensure_contrast,
    is_light_theme,
    lerp_rgb,
    lighten,
    neutral_tone,
    surface_bg,
)

# ---------------------------------------------------------------------------
# Palette
# ---------------------------------------------------------------------------
def _rebuild():
    global TEXT_RGB, DIM_RGB, MUTED_RGB, WIND_RGB, BLUE_RGB, CYAN_RGB
    global GREEN_RGB, YELLOW_RGB, RED_RGB, MAGENTA_RGB, BRIGHT_YELLOW_RGB
    global ALERT_BLUE_BASE_RGB, TEMP_COLORS, PRECIP_RAIN_RGB, PRECIP_SNOW_RGB
    global PRECIP_MIX_RGB, PRECIP_STORM_RGB, ALERT_RED_RGB, ALERT_AMBER_RGB
    global ALERT_YELLOW_RGB, ALERT_BLUE_RGB, CHART_BG_NIGHT_RGB
    global CHART_BG_DAY_RGB, CHART_HOVER_RGB, SUNRISE_LABEL_RGB
    global SUNSET_LABEL_RGB, TOOLTIP_BG_RGB, TOOLTIP_TEXT_RGB, MODAL_BG_RGB
    global MODAL_BORDER_RGB, LINK_RGB, TEXT, DIM, MUTED, PRECIP, PRECIP_RAIN
    global PRECIP_SNOW, PRECIP_MIX, PRECIP_STORM, ALERT_RED, ALERT_AMBER
    global ALERT_YELLOW, ALERT_BLUE, WIND_COLOR, WIND_ARROWS, SEP
    TEXT_RGB = ensure_contrast(_theme.theme_fg, _theme.theme_bg, minimum=4.5)
    DIM_RGB = ensure_contrast(neutral_tone(0.32), _theme.theme_bg, minimum=2.0)
    MUTED_RGB = ensure_contrast(neutral_tone(0.48), _theme.theme_bg, minimum=2.5)
    WIND_RGB = ensure_contrast(neutral_tone(0.68), _theme.theme_bg, minimum=3.0)

    BLUE_RGB = best_contrast((_theme.theme_ansi[4], _theme.theme_ansi[12]), minimum=2.1)
    CYAN_RGB = best_contrast((_theme.theme_ansi[6], _theme.theme_ansi[14]), minimum=2.1)
    GREEN_RGB = best_contrast((_theme.theme_ansi[2], _theme.theme_ansi[10]), minimum=2.1)
    YELLOW_RGB = best_contrast((_theme.theme_ansi[3], _theme.theme_ansi[11]), minimum=2.1)
    RED_RGB = best_contrast((_theme.theme_ansi[1], _theme.theme_ansi[9]), minimum=2.1)
    MAGENTA_RGB = best_contrast((_theme.theme_ansi[5], _theme.theme_ansi[13]), minimum=2.1)
    BRIGHT_YELLOW_RGB = ensure_contrast(_theme.theme_ansi[11], _theme.theme_bg, minimum=2.4)
    ALERT_BLUE_BASE_RGB = best_contrast((_theme.theme_ansi[12], _theme.theme_ansi[14], _theme.theme_ansi[6]), minimum=2.1)

    TEMP_COLORS = [
        (0, ensure_contrast(lerp_rgb(BLUE_RGB, CYAN_RGB, 0.15), _theme.theme_bg, minimum=2.1)),
        (32, BLUE_RGB),
        (45, CYAN_RGB),
        (55, GREEN_RGB),
        (65, ensure_contrast(lerp_rgb(GREEN_RGB, YELLOW_RGB, 0.45), _theme.theme_bg, minimum=2.1)),
        (72, YELLOW_RGB),
        (82, ensure_contrast(lerp_rgb(YELLOW_RGB, RED_RGB, 0.45), _theme.theme_bg, minimum=2.1)),
        (95, RED_RGB),
    ]

    PRECIP_RAIN_RGB = BLUE_RGB
    PRECIP_SNOW_RGB = best_contrast((_theme.theme_ansi[15], _theme.theme_ansi[8]), minimum=2.8)
    PRECIP_MIX_RGB = MAGENTA_RGB
    PRECIP_STORM_RGB = YELLOW_RGB
    ALERT_RED_RGB = RED_RGB
    ALERT_AMBER_RGB = YELLOW_RGB
    ALERT_YELLOW_RGB = BRIGHT_YELLOW_RGB
    ALERT_BLUE_RGB = ALERT_BLUE_BASE_RGB

    # Day/night chart tinting built from theme background + cool anchors.
    if is_light_theme():
        CHART_BG_NIGHT_RGB = darken(lerp_rgb(_theme.theme_bg, BLUE_RGB, 0.06), 0.12)
        CHART_BG_DAY_RGB = lighten(lerp_rgb(_theme.theme_bg, CYAN_RGB, 0.03), 0.03)
    else:
        CHART_BG_NIGHT_RGB = darken(lerp_rgb(_theme.theme_bg, BLUE_RGB, 0.12), 0.08)
        CHART_BG_DAY_RGB = lighten(lerp_rgb(_theme.theme_bg, CYAN_RGB, 0.06), 0.05)

    CHART_HOVER_RGB = ensure_contrast(surface_bg(0.36), CHART_BG_NIGHT_RGB, minimum=1.5)
    SUNRISE_LABEL_RGB = ensure_contrast(lerp_rgb(YELLOW_RGB, RED_RGB, 0.20), _theme.theme_bg, minimum=2.0)
    SUNSET_LABEL_RGB = ensure_contrast(lerp_rgb(RED_RGB, MAGENTA_RGB, 0.25), _theme.theme_bg, minimum=2.0)
    TOOLTIP_BG_RGB = darken(surface_bg(0.10), 0.45 if not is_light_theme() else 0.10)
    TOOLTIP_TEXT_RGB = ensure_contrast(TEXT_RGB, TOOLTIP_BG_RGB, minimum=4.5)
    MODAL_BG_RGB = darken(lerp_rgb(_theme.theme_bg, BLUE_RGB, 0.04), 0.10 if not is_light_theme() else 0.06)
    MODAL_BORDER_RGB = ensure_contrast(DIM_RGB, MODAL_BG_RGB, minimum=2.2)
    LINK_RGB = ensure_contrast(_theme.theme_ansi[4], MODAL_BG_RGB, minimum=3.0)

    TEXT = fg(*TEXT_RGB)
    DIM = fg(*DIM_RGB)
    MUTED = fg(*MUTED_RGB)
    PRECIP = fg(*PRECIP_RAIN_RGB)  # blue (rain) — kept for daily text
    PRECIP_RAIN = fg(*PRECIP_RAIN_RGB)
    PRECIP_SNOW = fg(*PRECIP_SNOW_RGB)
    PRECIP_MIX = fg(*PRECIP_MIX_RGB)
    PRECIP_STORM = fg(*PRECIP_STORM_RGB)
    ALERT_RED = fg(*ALERT_RED_RGB)
    ALERT_AMBER = fg(*ALERT_AMBER_RGB)
    ALERT_YELLOW = fg(*ALERT_YELLOW_RGB)
    ALERT_BLUE = fg(*ALERT_BLUE_RGB)
    WIND_COLOR = fg(*WIND_RGB)

    # Wind direction arrows: indexed by compass sector (N=0, NE=1, E=2, ... NW=7)
    # Arrow points in the direction the wind is blowing FROM (meteorological convention)
    WIND_ARROWS = "↓↙←↖↑↗→↘"  # N wind blows south, NE blows southwest, etc.

    SEP = f"{MUTED} \u00b7 "


_rebuild()
_theme.on_reload(_rebuild)
SPARKLINE = "\u2581\u2582\u2583\u2584\u2585\u2586\u2587\u2588"  # ▁▂▃▄▅▆▇█


def _temp_color(temp, runtime):
    temp_f = temp * 9 / 5 + 32 if runtime.celsius else temp
    return interp_stops(TEMP_COLORS, temp_f)


def _colored_temp(temp, runtime, suffix=""):
    r, g, b = _temp_color(temp, runtime)
    return f"{fg(r, g, b)}{temp:.0f}{suffix}"


def _precip_type(wmo_code):
    """Infer precipitation type from WMO weather code."""
    if wmo_code in (71, 73, 75, 77, 85, 86):
        return "Snow"
    if wmo_code in (56, 57, 66, 67):
        return "Mix"
    return "Rain"


def _rebuild_scales():
    global UV_COLORS, AQI_COLORS, UV_COLOR
    UV_COLORS = [
        (0, GREEN_RGB),
        (3, YELLOW_RGB),
        (6, ensure_contrast(lerp_rgb(YELLOW_RGB, RED_RGB, 0.45), _theme.theme_bg, minimum=2.1)),
        (8, RED_RGB),
        (11, MAGENTA_RGB),
    ]

    AQI_COLORS = [
        (0, GREEN_RGB),
        (51, YELLOW_RGB),
        (101, ensure_contrast(lerp_rgb(YELLOW_RGB, RED_RGB, 0.45), _theme.theme_bg, minimum=2.1)),
        (151, RED_RGB),
        (201, MAGENTA_RGB),
    ]
    UV_COLOR = fg(*ensure_contrast(lerp_rgb(YELLOW_RGB, RED_RGB, 0.30), _theme.theme_bg, minimum=2.5))


_rebuild_scales()
_theme.on_reload(_rebuild_scales)


def _uv_color(uv):
    """ANSI fg escape for a UV index value."""
    return fg(*interp_stops(UV_COLORS, uv))


def _aqi_color(aqi):
    """ANSI fg escape for a US AQI value."""
    return fg(*interp_stops(AQI_COLORS, aqi))


def _precip_color(wmo_code):
    """ANSI color for precipitation type based on WMO code."""
    if wmo_code in (71, 73, 75, 77, 85, 86):
        return PRECIP_SNOW
    if wmo_code in (56, 57, 66, 67):
        return PRECIP_MIX
    if wmo_code in (95, 96, 99):
        return PRECIP_STORM
    return PRECIP_RAIN
