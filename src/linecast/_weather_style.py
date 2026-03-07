"""Shared weather rendering palette and low-level color/format helpers."""

from linecast._graphics import fg, interp_stops

# ---------------------------------------------------------------------------
# Palette
# ---------------------------------------------------------------------------
TEMP_COLORS = [
    ( 0, (100,  60, 180)),   # frigid — deep purple
    (32, ( 70, 130, 210)),   # freezing — blue
    (45, ( 50, 170, 180)),   # cold — teal
    (55, ( 60, 180, 120)),   # cool — green
    (65, (140, 200,  70)),   # mild — yellow-green
    (72, (220, 190,  50)),   # warm — gold
    (82, (240, 150,  40)),   # hot — orange
    (95, (220,  60,  50)),   # very hot — red
]

TEXT    = fg(200, 205, 215)
DIM     = fg(70, 80, 100)
MUTED   = fg(100, 110, 130)
PRECIP      = fg(80, 140, 220)    # blue (rain) — kept for daily text
PRECIP_RAIN = fg(80, 140, 220)
PRECIP_SNOW = fg(200, 210, 225)   # light gray-white
PRECIP_MIX  = fg(160, 140, 200)   # light purple
PRECIP_STORM = fg(220, 190, 50)   # amber
ALERT_RED    = fg(220, 60, 50)
ALERT_AMBER  = fg(220, 170, 50)
ALERT_YELLOW = fg(200, 200, 80)
WIND_COLOR   = fg(140, 150, 170)

# Wind direction arrows: indexed by compass sector (N=0, NE=1, E=2, ... NW=7)
# Arrow points in the direction the wind is blowing FROM (meteorological convention)
WIND_ARROWS = "↓↙←↖↑↗→↘"  # N wind blows south, NE blows southwest, etc.

SEP = f"{MUTED} \u00b7 "
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


def _precip_color(wmo_code):
    """ANSI color for precipitation type based on WMO code."""
    if wmo_code in (71, 73, 75, 77, 85, 86):
        return PRECIP_SNOW
    if wmo_code in (56, 57, 66, 67):
        return PRECIP_MIX
    if wmo_code in (95, 96, 99):
        return PRECIP_STORM
    return PRECIP_RAIN
