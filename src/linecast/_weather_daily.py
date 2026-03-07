"""Daily weather row rendering."""

from datetime import datetime

from linecast._graphics import bg, fg, visible_len, RESET, BOLD
from linecast._runtime import WeatherRuntime
from linecast._weather_i18n import DAY_NAMES, _s, _wmo_icons
from linecast._weather_style import DIM, TEXT, WIND_COLOR, _precip_color, _precip_type, _temp_color


def render_daily(data, width, runtime=None):
    """Daily forecast with temperature range bars."""
    if runtime is None:
        runtime = WeatherRuntime.from_sources()
    daily = data.get("daily", {})
    times = daily.get("time", [])
    hi_temps = daily.get("temperature_2m_max", [])
    lo_temps = daily.get("temperature_2m_min", [])
    precip_sum = daily.get("precipitation_sum", [])
    precip_prob = daily.get("precipitation_probability_max", [])
    wmo_codes = daily.get("weather_code", [])
    wind_max = daily.get("wind_speed_10m_max", [])

    lines = []

    # With past_days=1: 0=yesterday, 1=today, 2+=forecast
    # Show today (1) through end for scale, display 2+ as forecast rows
    display_end = min(len(times), 8)
    if display_end < 3:
        return lines

    # Common temperature scale across today + all forecast days
    all_lo = [lo_temps[i] for i in range(1, display_end) if i < len(lo_temps)]
    all_hi = [hi_temps[i] for i in range(1, display_end) if i < len(hi_temps)]
    if not all_lo or not all_hi:
        return lines

    scale_min = min(all_lo)
    scale_max = max(all_hi)

    # Measure widest right-side detail columns across all days for alignment
    lang = runtime.lang
    day_name_list = DAY_NAMES.get(lang, DAY_NAMES["en"])
    day_col_w = max(visible_len(n) for n in day_name_list + [_s("today_short", runtime)])
    left_prefix_w = 2 + day_col_w + 2 + 2 + 2  # "  day  ic  "
    # Compute per-day detail fields and find max width of each column
    day_details = []  # list of (precip_str, prob_str, wind_str) per day
    max_precip_w = 0
    max_prob_w = 0
    max_wind_w = 0
    for i in range(1, display_end):
        precip_i = precip_sum[i] if i < len(precip_sum) else 0
        prob_i = precip_prob[i] if i < len(precip_prob) else 0
        wind_i = wind_max[i] if i < len(wind_max) else 0
        wmo_i = wmo_codes[i] if i < len(wmo_codes) else 0
        precip_s = ""
        if precip_i >= (1 if runtime.metric else 0.05):
            ptype = _s(_precip_type(wmo_i), runtime)
            if runtime.metric:
                precip_s = f"{ptype} {precip_i:.0f}{runtime.precip_unit}"
            else:
                precip_s = f"{ptype} {precip_i:.1f}{runtime.precip_unit}"
        prob_s = f"{prob_i:.0f}%" if prob_i > 25 else ""
        wind_s = (
            f"{_s('wind', runtime)} {wind_i:.0f}{runtime.wind_unit}"
            if wind_i > (25 if runtime.metric else 15)
            else ""
        )
        day_details.append((precip_s, prob_s, wind_s))
        if precip_s:
            max_precip_w = max(max_precip_w, len(precip_s))
        if prob_s:
            max_prob_w = max(max_prob_w, len(prob_s))
        if wind_s:
            max_wind_w = max(max_wind_w, len(wind_s))

    max_right_w = 0
    if max_prob_w:
        max_right_w += 2 + max_prob_w
    if max_precip_w:
        max_right_w += 2 + max_precip_w
    if max_wind_w:
        max_right_w += 2 + max_wind_w

    # Bar gets all remaining width after left prefix, right details, and padding
    bar_w = max(10, width - left_prefix_w - max_right_w - 2)

    # Ensure outside labels always fit
    max_lo_label = max(
        len(f"{lo_temps[i]:.0f}\u00b0") for i in range(1, display_end) if i < len(lo_temps)
    )
    max_hi_label = max(
        len(f"{hi_temps[i]:.0f}\u00b0") for i in range(1, display_end) if i < len(hi_temps)
    )
    inner_w = bar_w - 1 - max_lo_label - max_hi_label
    if inner_w < 1:
        inner_w = 1
    actual_range = max(scale_max - scale_min, 1)
    deg_per_char = actual_range / max(inner_w, 1)
    scale_min = scale_min - max_lo_label * deg_per_char
    scale_max = scale_max + max_hi_label * deg_per_char
    scale_range = max(scale_max - scale_min, 1)

    dark_fg = fg(20, 20, 25)
    icons = _wmo_icons(runtime)

    for i in range(1, display_end):
        if i == 1:
            day_name = _s("today_short", runtime)
        else:
            try:
                dt = datetime.fromisoformat(times[i])
                day_name = day_name_list[dt.weekday()]
            except Exception:
                day_name = "???"
        day_name = day_name + " " * (day_col_w - visible_len(day_name))

        wmo = wmo_codes[i] if i < len(wmo_codes) else 0
        icon = icons.get(wmo, icons[0])
        hi = hi_temps[i] if i < len(hi_temps) else 0
        lo = lo_temps[i] if i < len(lo_temps) else 0
        precip = precip_sum[i] if i < len(precip_sum) else 0
        prob = precip_prob[i] if i < len(precip_prob) else 0
        wind = wind_max[i] if i < len(wind_max) else 0

        # Temperature range bar with integrated labels
        lo_pos = int((lo - scale_min) / scale_range * (bar_w - 1))
        hi_pos = int((hi - scale_min) / scale_range * (bar_w - 1))
        hi_pos = max(hi_pos, lo_pos + 1)  # at least 1 char wide

        lo_label = f"{lo:.0f}\u00b0"
        hi_label = f"{hi:.0f}\u00b0"
        lo_len = len(lo_label)
        hi_len = len(hi_label)
        filled_w = hi_pos - lo_pos + 1

        # Decide label placement: inside (knocked out) or outside
        both_inside = filled_w >= lo_len + hi_len + 2
        hi_inside = not both_inside and filled_w >= hi_len + 1
        lo_inside = both_inside

        lo_r, lo_g, lo_b = _temp_color(lo, runtime)
        hi_r, hi_g, hi_b = _temp_color(hi, runtime)

        cells = []
        for bx in range(bar_w):
            if lo_pos <= bx <= hi_pos:
                t_frac = (bx - lo_pos) / max(1, hi_pos - lo_pos)
                temp_at = lo + (hi - lo) * t_frac
                r, g, b = _temp_color(temp_at, runtime)
                rel = bx - lo_pos
                if lo_inside and rel < lo_len:
                    cells.append((lo_label[rel], f"{bg(r, g, b)}{dark_fg}{BOLD}"))
                elif both_inside and rel >= filled_w - hi_len:
                    hi_idx = rel - (filled_w - hi_len)
                    cells.append((hi_label[hi_idx], f"{bg(r, g, b)}{dark_fg}{BOLD}"))
                elif hi_inside and not both_inside and rel >= filled_w - hi_len:
                    hi_idx = rel - (filled_w - hi_len)
                    cells.append((hi_label[hi_idx], f"{bg(r, g, b)}{dark_fg}{BOLD}"))
                else:
                    cells.append(("\u2588", f"{fg(r, g, b)}"))
            else:
                cells.append(("\u2500", f"{DIM}"))

        # Overlay outside labels adjacent to filled region
        if not lo_inside:
            label_start = lo_pos - lo_len
            if label_start >= 0:
                for j, ch in enumerate(lo_label):
                    cells[label_start + j] = (ch, f"{fg(lo_r, lo_g, lo_b)}")
        if not (both_inside or hi_inside):
            label_start = hi_pos + 1
            if label_start + hi_len <= bar_w:
                for j, ch in enumerate(hi_label):
                    cells[label_start + j] = (ch, f"{fg(hi_r, hi_g, hi_b)}")

        bar = "".join(f"{prefix}{ch}{RESET}" for ch, prefix in cells)

        # Build the line with aligned right-side columns
        line = f"  {TEXT}{day_name}  {icon}  {bar}"

        precip_s, prob_s, wind_s = day_details[i - 1]
        pcolor = _precip_color(wmo)
        if max_prob_w:
            line += f"  {pcolor}{prob_s:>{max_prob_w}}" if prob_s else f"  {' ' * max_prob_w}"
        if max_precip_w:
            line += f"  {pcolor}{precip_s:<{max_precip_w}}" if precip_s else f"  {' ' * max_precip_w}"
        if max_wind_w:
            line += f"  {WIND_COLOR}{wind_s:<{max_wind_w}}" if wind_s else f"  {' ' * max_wind_w}"

        lines.append(f"{line}{RESET}")

    return lines
