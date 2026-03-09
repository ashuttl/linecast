#!/usr/bin/env python3
"""Solar arc — terminal visualization of the sun's daily journey.

Renders a multi-line graphical display inspired by the Apple Watch Solar
face. Shows the sun's sinusoidal arc above and below the horizon with a
warm glow centered on the sun's current position, seasonal scaling, and day
length with daily delta.

Uses half-block characters with ANSI color for smooth rendering at 2x
vertical sub-pixel resolution (true color when available). Location is
cached from IP geolocation (~1 network call per week).

Usage: sunshine [--print] [--emoji] [--classic-colors]
"""

import math
import sys
from datetime import datetime, timezone

from linecast._graphics import (
    fg, RESET, BG_PRIMARY, lerp, interp_stops, visible_len, fmt_time,
    get_terminal_size, Framebuffer, live_loop,
)
from linecast._theme import (
    best_contrast,
    darken,
    ensure_contrast,
    lerp_rgb,
    lighten,
    neutral_tone,
    surface_bg,
    theme_ansi,
    theme_bg,
    theme_fg,
    theme_legacy_mode,
)
from linecast._location import get_location
from linecast._runtime import RuntimeConfig, has_flag

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
if theme_legacy_mode:
    # Original pre-theme palette (classic mode).
    HORIZON_COLOR = (40, 46, 65)
    CURVE_COLOR = (160, 168, 195)
    SUN_GLOW_DAY_RGB = (255, 250, 220)
    SUN_GLOW_TWILIGHT_RGB = (180, 195, 225)
    SUN_CORE_RGB = (255, 255, 255)
    INFO_AMBER_RGB = (251, 191, 36)
    INFO_PURPLE_RGB = (167, 139, 250)
    INFO_MUTED_RGB = (100, 110, 130)
    INFO_DIM_RGB = (70, 80, 100)
    INFO_TEXT_RGB = (200, 205, 215)
else:
    _SKY_BLUE = best_contrast((theme_ansi[4], theme_ansi[12], theme_ansi[6]), minimum=1.8)
    _SKY_CYAN = best_contrast((theme_ansi[6], theme_ansi[14], theme_fg), minimum=1.8)
    _SKY_MAGENTA = best_contrast((theme_ansi[5], theme_ansi[13]), minimum=1.8)
    _SKY_RED = best_contrast((theme_ansi[1], theme_ansi[9]), minimum=1.8)
    _SKY_YELLOW = best_contrast((theme_ansi[3], theme_ansi[11]), minimum=1.8)
    _SKY_WHITE = best_contrast((theme_ansi[15], theme_fg), minimum=2.0)

    HORIZON_COLOR = ensure_contrast(surface_bg(0.14), theme_bg, minimum=1.3)  # subtle divider
    CURVE_COLOR = ensure_contrast(neutral_tone(0.74), theme_bg, minimum=2.4)  # neutral arc
    SUN_GLOW_DAY_RGB = best_contrast((theme_ansi[15], lighten(theme_fg, 0.12)), minimum=1.8)
    SUN_GLOW_TWILIGHT_RGB = ensure_contrast(lerp_rgb(_SKY_BLUE, _SKY_WHITE, 0.45), theme_bg, minimum=1.6)
    SUN_CORE_RGB = best_contrast((theme_ansi[15], theme_fg), minimum=2.0)
    INFO_AMBER_RGB = ensure_contrast(_SKY_YELLOW, theme_bg, minimum=2.3)
    INFO_PURPLE_RGB = ensure_contrast(_SKY_MAGENTA, theme_bg, minimum=2.3)
    INFO_MUTED_RGB = ensure_contrast(neutral_tone(0.48), theme_bg, minimum=2.4)
    INFO_DIM_RGB = ensure_contrast(neutral_tone(0.32), theme_bg, minimum=2.0)
    INFO_TEXT_RGB = ensure_contrast(theme_fg, theme_bg, minimum=4.5)

_EMOJI_ICONS = {
    "sun_char": "\u25cf",         # ●
    "sun_icon": "\U0001f305",     # 🌅
    "sunset_icon": "\U0001f307",  # 🌇
    "moon_icons": [
        "\U0001f311",  # 🌑 New Moon
        "\U0001f312",  # 🌒 Waxing Crescent
        "\U0001f313",  # 🌓 First Quarter
        "\U0001f314",  # 🌔 Waxing Gibbous
        "\U0001f315",  # 🌕 Full Moon
        "\U0001f316",  # 🌖 Waning Gibbous
        "\U0001f317",  # 🌗 Last Quarter
        "\U0001f318",  # 🌘 Waning Crescent
    ],
}

_NERD_ICONS = {
    "sun_char": "\U000F0F62",      # 󰽢
    "sun_icon": "\U000F059C",      # 󰖜
    "sunset_icon": "\U000F059B",   # 󰖛
    "moon_icons": [
        "\U000F0F64",  # New Moon
        "\U000F0F67",  # Waxing Crescent
        "\U000F0F61",  # First Quarter
        "\U000F0F68",  # Waxing Gibbous
        "\U000F0F62",  # Full Moon
        "\U000F0F66",  # Waning Gibbous
        "\U000F0F63",  # Last Quarter
        "\U000F0F65",  # Waning Crescent
    ],
}


def _icon_set(runtime):
    return _EMOJI_ICONS if runtime.emoji else _NERD_ICONS
MOON_NAMES = [
    "New Moon", "Waxing Crescent", "First Quarter", "Waxing Gibbous",
    "Full Moon", "Waning Gibbous", "Last Quarter", "Waning Crescent",
]

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
    SKY_NEAR_HORIZON = [   # warm side — sky color near the sun at the horizon
        (-18, BG_PRIMARY),
        (-12, darken(lerp_rgb(theme_bg, _SKY_MAGENTA, 0.18), 0.10)),
        ( -6, lerp_rgb(theme_bg, _SKY_RED, 0.35)),
        ( -3, lerp_rgb(_SKY_RED, _SKY_MAGENTA, 0.20)),
        (  0, lerp_rgb(_SKY_YELLOW, _SKY_RED, 0.28)),
        (  3, lerp_rgb(_SKY_YELLOW, _SKY_WHITE, 0.20)),
        (  8, lerp_rgb(_SKY_YELLOW, _SKY_CYAN, 0.35)),
        ( 15, lerp_rgb(_SKY_CYAN, _SKY_WHITE, 0.55)),
        ( 30, lerp_rgb(_SKY_CYAN, _SKY_WHITE, 0.72)),
        ( 90, lerp_rgb(_SKY_CYAN, _SKY_WHITE, 0.82)),
    ]

    SKY_FAR_HORIZON = [    # cool side — sky color far from the sun at the horizon
        (-18, BG_PRIMARY),
        (-12, darken(lerp_rgb(theme_bg, _SKY_MAGENTA, 0.14), 0.12)),
        ( -6, lerp_rgb(theme_bg, _SKY_MAGENTA, 0.30)),
        ( -3, lerp_rgb(_SKY_MAGENTA, _SKY_RED, 0.30)),
        (  0, lerp_rgb(_SKY_RED, _SKY_MAGENTA, 0.30)),
        (  3, lerp_rgb(_SKY_RED, _SKY_CYAN, 0.25)),
        (  8, lerp_rgb(_SKY_MAGENTA, _SKY_CYAN, 0.40)),
        ( 15, lerp_rgb(_SKY_BLUE, _SKY_WHITE, 0.52)),
        ( 30, lerp_rgb(_SKY_BLUE, _SKY_WHITE, 0.70)),
        ( 90, lerp_rgb(_SKY_BLUE, _SKY_WHITE, 0.80)),
    ]

    SKY_ZENITH = [         # sky color at the top of the display
        (-18, BG_PRIMARY),
        (-12, darken(lerp_rgb(theme_bg, _SKY_BLUE, 0.10), 0.14)),
        ( -6, darken(lerp_rgb(theme_bg, _SKY_BLUE, 0.18), 0.08)),
        ( -3, lerp_rgb(theme_bg, _SKY_MAGENTA, 0.22)),
        (  0, lerp_rgb(_SKY_MAGENTA, _SKY_BLUE, 0.32)),
        (  3, lerp_rgb(_SKY_MAGENTA, _SKY_BLUE, 0.48)),
        (  8, lerp_rgb(_SKY_BLUE, _SKY_CYAN, 0.22)),
        ( 15, lerp_rgb(_SKY_BLUE, _SKY_CYAN, 0.45)),
        ( 30, lerp_rgb(_SKY_BLUE, _SKY_WHITE, 0.48)),
        ( 90, lerp_rgb(_SKY_BLUE, _SKY_WHITE, 0.62)),
    ]

# ---------------------------------------------------------------------------
# Solar math (simplified NOAA algorithm)
# ---------------------------------------------------------------------------
import time as _time

def _tz_offset_hours():
    return _time.localtime().tm_gmtoff / 3600

def _equation_of_time(doy):
    B = math.radians(360 / 365 * (doy - 81))
    return 9.87 * math.sin(2*B) - 7.53 * math.cos(B) - 1.5 * math.sin(B)

def _declination(doy):
    return 23.45 * math.sin(math.radians(360 / 365 * (doy - 81)))

def solar_times(lat, lng, doy):
    """Sunrise/sunset as local decimal hours."""
    decl = _declination(doy)
    lat_r, dec_r = math.radians(lat), math.radians(decl)
    cos_ha = ((math.cos(math.radians(90.833)) -
               math.sin(lat_r) * math.sin(dec_r)) /
              (math.cos(lat_r) * math.cos(dec_r)))
    cos_ha = max(-1.0, min(1.0, cos_ha))
    ha = math.degrees(math.acos(cos_ha))
    eot = _equation_of_time(doy)
    noon_utc = 12 - lng / 15 - eot / 60
    tz = _tz_offset_hours()
    return noon_utc - ha/15 + tz, noon_utc + ha/15 + tz

def sun_elevation(lat, lng, local_hour, doy):
    """Sun elevation angle in degrees at a given local hour."""
    decl = _declination(doy)
    eot = _equation_of_time(doy)
    noon_utc = 12 - lng / 15 - eot / 60
    tz = _tz_offset_hours()
    ha = 15 * (local_hour - tz - noon_utc)
    lat_r = math.radians(lat)
    dec_r = math.radians(decl)
    ha_r  = math.radians(ha)
    sin_e = (math.sin(lat_r) * math.sin(dec_r) +
             math.cos(lat_r) * math.cos(dec_r) * math.cos(ha_r))
    return math.degrees(math.asin(max(-1.0, min(1.0, sin_e))))


def daylight_factor(local_hour, doy, lat, lng, tz_offset_h):
    """Compute a smooth day/night brightness factor for a local clock hour."""
    decl = -23.44 * math.cos(math.radians(360 / 365 * (doy + 10)))
    lat_rad = math.radians(lat)
    decl_rad = math.radians(decl)

    cos_ha = -math.tan(lat_rad) * math.tan(decl_rad)
    if cos_ha <= -1:
        return 1.0  # midnight sun
    if cos_ha >= 1:
        return 0.0  # polar night

    ha = math.degrees(math.acos(cos_ha))

    solar_noon = 12.0
    if lng is not None:
        tz_meridian = tz_offset_h * 15
        solar_noon += (tz_meridian - lng) / 15

    sunrise = solar_noon - ha / 15
    sunset = solar_noon + ha / 15
    transition = 40 / 60  # 40 minutes

    if local_hour < sunrise - transition or local_hour > sunset + transition:
        return 0.0
    if sunrise + transition <= local_hour <= sunset - transition:
        return 1.0
    if local_hour < sunrise + transition:
        return (local_hour - sunrise + transition) / (2 * transition)
    return (sunset + transition - local_hour) / (2 * transition)

# ---------------------------------------------------------------------------
# Moon phase
# ---------------------------------------------------------------------------
SYNODIC_MONTH = 29.53058867

def moon_phase(dt, runtime=None):
    """Returns (index 0-7, name, nerd_font_icon).

    Uses narrow ~24h windows for principal phases (New, Full, Quarters)
    and wider bins for transitional phases, matching almanac conventions.
    """
    ref = datetime(2000, 1, 6, 18, 14, tzinfo=timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    diff = (dt - ref).total_seconds() / 86400.0
    frac = (diff % SYNODIC_MONTH) / SYNODIC_MONTH

    # ±0.017 of the cycle ≈ ±12 hours around each principal phase
    T = 0.017
    if frac < T or frac > 1 - T:
        idx = 0   # New Moon
    elif abs(frac - 0.25) < T:
        idx = 2   # First Quarter
    elif abs(frac - 0.5) < T:
        idx = 4   # Full Moon
    elif abs(frac - 0.75) < T:
        idx = 6   # Last Quarter
    elif frac < 0.25:
        idx = 1   # Waxing Crescent
    elif frac < 0.5:
        idx = 3   # Waxing Gibbous
    elif frac < 0.75:
        idx = 5   # Waning Gibbous
    else:
        idx = 7   # Waning Crescent
    if runtime is None:
        runtime = RuntimeConfig.from_sources()
    return idx, MOON_NAMES[idx], _icon_set(runtime)["moon_icons"][idx]

# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------
def render(lat, lng, doy, now_hour, fullscreen=False, offset_minutes=0, runtime=None):
    """Build the complete multi-line solar arc display."""
    if runtime is None:
        runtime = RuntimeConfig.from_sources()
    icons = _icon_set(runtime)
    cols, rows = get_terminal_size()

    # --- dimensions: fill the terminal ---
    graph_w = max(30, cols - 2)
    graph_h = max(6, rows - (1 if fullscreen else 6))
    total_spy = graph_h * 2

    # --- elevation curve for today ---
    elevations = []
    for x in range(graph_w):
        h = (x + 0.5) / graph_w * 24
        elevations.append(sun_elevation(lat, lng, h, doy))

    # --- seasonal vertical scale ---
    summer_peak = sun_elevation(lat, lng, 12, 172)
    winter_trough = sun_elevation(lat, lng, 0, 355)
    annual_max = max(summer_peak, max(elevations), 5)
    annual_min = min(winter_trough, min(elevations), -5)

    # Horizon placement — proportional to annual range
    horizon_frac = annual_max / (annual_max - annual_min)
    horizon_spy = int(total_spy * horizon_frac)
    horizon_spy = max(2, min(total_spy - 2, horizon_spy))

    def elev_to_spy(elev):
        """Elevation → sub-pixel row (float). 0=top, total_spy-1=bottom."""
        if elev >= 0:
            return horizon_spy * (1 - elev / annual_max)
        else:
            below = total_spy - horizon_spy
            return horizon_spy + abs(elev) / abs(annual_min) * below

    curve_f = [max(0.0, min(total_spy - 1.0, elev_to_spy(e))) for e in elevations]

    # Current sun position
    now_x = max(0, min(graph_w - 1, int(now_hour / 24 * graph_w)))
    now_elev = sun_elevation(lat, lng, now_hour, doy)
    now_spy = max(0.0, min(total_spy - 1.0, elev_to_spy(now_elev)))

    sunrise, sunset = solar_times(lat, lng, doy)

    # --- build framebuffer ---
    fb = Framebuffer(graph_w, graph_h)

    # 1. Horizon line
    fb.fill_hline(horizon_spy, HORIZON_COLOR)

    # 2. Sky glow — above horizon, centered on sun, irrespective of arc
    if now_elev > -18:
        sky_near_h = interp_stops(SKY_NEAR_HORIZON, now_elev)
        sky_far_h  = interp_stops(SKY_FAR_HORIZON, now_elev)
        sky_z      = interp_stops(SKY_ZENITH, now_elev)

        # Overall brightness: ramps from 0 at -18° to 1 around +2°
        brightness = max(0, min(1, (now_elev + 18) / 20))

        # Horizontal Gaussian spread: narrow twilight glow → wide daylight fill
        t_sigma = max(0, min(1, (now_elev + 6) / 30))
        glow_sigma = graph_w * (0.12 + 0.30 * t_sigma)

        # Ambient sky floor: even far from sun, some blue during day
        ambient = 0.15 * max(0, min(1, now_elev / 25))

        # Vertical extent: concentrated at horizon in twilight, fills sky midday
        height_power = 1.5 - 1.0 * max(0, min(1, (now_elev + 6) / 36))

        for x in range(graph_w):
            dx = x - now_x
            h_gauss = math.exp(-0.5 * (dx / max(glow_sigma, 1)) ** 2)
            h_intensity = max(ambient, h_gauss)

            # Horizon color blends near↔far based on proximity to sun
            horizon_color = lerp(sky_far_h, sky_near_h, h_gauss)

            for spy in range(0, horizon_spy):
                vert_frac = (horizon_spy - spy) / max(1, horizon_spy)

                # Vertical blend: horizon → zenith color
                sky_color = lerp(horizon_color, sky_z, vert_frac ** 0.65)

                # Vertical intensity falloff
                v_factor = max(0, (1 - vert_frac) ** height_power)

                intensity = brightness * h_intensity * v_factor
                if intensity > 0.01:
                    fb.set_pixel(x, spy, sky_color, intensity)

    # 3. Curve line
    fb.draw_curve(curve_f, CURVE_COLOR, sigma=0.8)

    # 4. Sun — radial glow
    sun_spy_i = int(round(now_spy))
    sun_spy_i = max(0, min(total_spy - 1, sun_spy_i))
    sun_r = max(5, int(min(graph_w, total_spy) * 0.04))
    sun_warm = SUN_GLOW_DAY_RGB if now_elev > -2 else SUN_GLOW_TWILIGHT_RGB

    fb.draw_radial(now_x, now_spy, sun_warm, sun_r)

    # Sun core — bright center
    for dy in range(-1, 2):
        for dx in range(-1, 2):
            sx, sy = now_x + dx, sun_spy_i + dy
            if 0 <= sx < graph_w and 0 <= sy < total_spy:
                d = math.sqrt(dx * dx + (dy * 1.5) ** 2)
                fb.set_pixel(sx, sy, SUN_CORE_RGB, max(0, 1 - d * 0.5))

    # --- render framebuffer with sun dot overlay ---
    sun_cell_row = sun_spy_i // 2
    overlays = {(now_x, sun_cell_row): (icons["sun_char"], SUN_CORE_RGB)}
    lines = fb.render(overlays)

    # --- info line ---
    lines.append(
        _info_line(
            lat,
            lng,
            doy,
            sunrise,
            sunset,
            cols,
            runtime,
            now_hour,
            offset_minutes,
        )
    )

    return "\n".join(lines)

def _info_line(lat, lng, doy, sunrise, sunset, width, runtime, now_hour=None, offset_minutes=0):
    """Sunrise — day length (delta) — sunset."""
    icons = _icon_set(runtime)
    day_len = sunset - sunrise
    dl_h = int(day_len)
    dl_m = int((day_len - dl_h) * 60)

    y_rise, y_set = solar_times(lat, lng, doy - 1)
    delta_sec = (day_len - (y_set - y_rise)) * 3600
    d_sign = "+" if delta_sec >= 0 else "\u2212"
    d_abs = abs(delta_sec)
    d_m = int(d_abs) // 60
    d_s = int(d_abs) % 60

    amber = fg(*INFO_AMBER_RGB)
    purple = fg(*INFO_PURPLE_RGB)
    muted = fg(*INFO_MUTED_RGB)
    dim = fg(*INFO_DIM_RGB)
    text = fg(*INFO_TEXT_RGB)

    delta_str = f"{d_sign}{d_m}m {d_s}s" if d_s > 0 else f"{d_sign}{d_m}m"

    left = f"{amber}{icons['sun_icon']} {text}{fmt_time(sunrise)}"
    if offset_minutes:
        center = f"{text}{fmt_time(now_hour)}"
    else:
        center = f"{text}{dl_h}h {dl_m:02d}m {dim}({delta_str})"
    right = f"{text}{fmt_time(sunset)} {purple}{icons['sunset_icon']}"

    lw = visible_len(left)
    cw = visible_len(center)
    rw = visible_len(right)

    total_gap = max(0, width - lw - cw - rw - 2)
    left_gap = max(1, total_gap // 2)
    right_gap = max(1, total_gap - left_gap)
    line = f" {left}{' ' * left_gap}{center}{' ' * right_gap}{right} "

    return f"{RESET}{line}{RESET}"

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    runtime = RuntimeConfig.from_sources()

    if has_flag("--help") or has_flag("-h"):
        print(__doc__.strip())
        return
    if has_flag("--version"):
        from linecast import __version__
        print(f"sunshine (linecast {__version__})")
        return

    lat, lng, _country = get_location()
    if lat is None:
        print("Could not determine location.", file=sys.stderr)
        sys.exit(1)

    live = runtime.live

    def _render(offset_minutes=0, mouse_pos=None, active_alert=None, modal_scroll=0):
        # mouse_pos/active_alert/modal_scroll are ignored; accepted so sunshine
        # can use shared live_loop mouse-wheel scrubbing support.
        now = datetime.now()
        if offset_minutes:
            from datetime import timedelta
            now = now + timedelta(minutes=offset_minutes)
        doy = now.timetuple().tm_yday
        now_hour = now.hour + now.minute / 60 + now.second / 3600
        return render(
            lat,
            lng,
            doy,
            now_hour,
            fullscreen=live,
            offset_minutes=offset_minutes,
            runtime=runtime,
        )

    if live:
        live_loop(_render, mouse=True)
    else:
        print(_render())

if __name__ == "__main__":
    main()
