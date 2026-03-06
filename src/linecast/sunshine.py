#!/usr/bin/env python3
"""Solar arc — terminal visualization of the sun's daily journey.

Renders a multi-line graphical display inspired by the Apple Watch Solar
face. Shows the sun's sinusoidal arc above and below the horizon with a
warm glow centered on the sun's current position, seasonal scaling, day
length with daily delta, and moon phase.

Uses half-block characters with ANSI color for smooth rendering at 2x
vertical sub-pixel resolution (true color when available). Location is
cached from IP geolocation (~1 network call per week).

Usage: sunshine [--live] [--emoji]
"""

import math
import sys
from datetime import datetime, timezone

from linecast._graphics import (
    fg, RESET, BG_PRIMARY, lerp, interp_stops, visible_len, fmt_time,
    get_terminal_size, Framebuffer, live_loop,
)
from linecast._location import get_location
from linecast._runtime import RuntimeConfig, has_flag

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
HORIZON_COLOR = (40, 46, 65)   # subtle divider
CURVE_COLOR   = (160, 168, 195) # neutral silver — the arc itself

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
    "sun_icon": "\U000F0599",      # 󰖙
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
SKY_NEAR_HORIZON = [   # warm side — sky color near the sun at the horizon
    (-18, BG_PRIMARY),
    (-12, (35, 18, 58)),            # faint warm purple
    ( -6, (115, 55, 75)),           # dusky rose
    ( -3, (185, 80, 60)),           # deep salmon
    (  0, (245, 135, 40)),          # rich amber
    (  3, (248, 175, 55)),          # golden
    (  8, (230, 195, 85)),          # warm gold
    ( 15, (195, 215, 242)),         # pale blue-white
    ( 30, (208, 228, 255)),         # bright blue-white
    ( 90, (218, 238, 255)),         # zenith blue-white
]

SKY_FAR_HORIZON = [    # cool side — sky color far from the sun at the horizon
    (-18, BG_PRIMARY),
    (-12, (28, 15, 52)),            # faint purple
    ( -6, (90, 40, 98)),            # purple
    ( -3, (160, 55, 108)),          # magenta-pink
    (  0, (205, 85, 110)),          # salmon-pink
    (  3, (190, 105, 125)),         # mauve-pink
    (  8, (168, 135, 160)),         # fading mauve
    ( 15, (182, 208, 238)),         # soft blue
    ( 30, (202, 224, 252)),         # blue-white
    ( 90, (214, 234, 254)),         # pale blue-white
]

SKY_ZENITH = [         # sky color at the top of the display
    (-18, BG_PRIMARY),
    (-12, (18, 14, 38)),            # barely visible indigo
    ( -6, (30, 20, 55)),            # dark purple
    ( -3, (48, 28, 72)),            # medium purple
    (  0, (70, 38, 95)),            # rich purple
    (  3, (62, 55, 128)),           # blue-purple
    (  8, (52, 82, 158)),           # blue
    ( 15, (78, 132, 208)),          # medium blue
    ( 30, (112, 170, 240)),         # bright blue
    ( 90, (132, 188, 250)),         # pale blue
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
    sun_warm = (255, 250, 220) if now_elev > -2 else (180, 195, 225)

    fb.draw_radial(now_x, now_spy, sun_warm, sun_r)

    # Sun core — bright center
    for dy in range(-1, 2):
        for dx in range(-1, 2):
            sx, sy = now_x + dx, sun_spy_i + dy
            if 0 <= sx < graph_w and 0 <= sy < total_spy:
                d = math.sqrt(dx * dx + (dy * 1.5) ** 2)
                fb.set_pixel(sx, sy, (255, 255, 255), max(0, 1 - d * 0.5))

    # --- render framebuffer with sun dot overlay ---
    sun_cell_row = sun_spy_i // 2
    overlays = {(now_x, sun_cell_row): (icons["sun_char"], (255, 255, 255))}
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
    """Sunrise — day length (delta) · moon phase — sunset."""
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

    _, phase_name, moon_icon = moon_phase(datetime.now(timezone.utc), runtime)

    amber = fg(251, 191, 36)
    purple = fg(167, 139, 250)
    muted = fg(100, 110, 130)
    dim = fg(70, 80, 100)
    text = fg(200, 205, 215)

    delta_str = f"{d_sign}{d_m}m {d_s}s" if d_s > 0 else f"{d_sign}{d_m}m"

    left = f"{amber}{icons['sun_icon']} {text}{fmt_time(sunrise)}"
    if offset_minutes:
        center = f"{text}{fmt_time(now_hour)}{muted}  \u00b7  {purple}{moon_icon} {dim}{phase_name}"
    else:
        center = f"{text}{dl_h}h {dl_m:02d}m {dim}({delta_str}){muted}  \u00b7  {purple}{moon_icon} {dim}{phase_name}"
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

    def _render(offset_minutes=0):
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
        live_loop(_render)
    else:
        print(_render())

if __name__ == "__main__":
    main()
