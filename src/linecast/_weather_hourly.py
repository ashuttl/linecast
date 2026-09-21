"""Hourly weather chart rendering."""

import math
from datetime import datetime, timedelta

from linecast import _theme
from linecast._braille import build_braille_curve, interpolate
from linecast._graphics import bg, color_mode, fg, fmt_hour, fmt_time_dt, RESET, visible_len
from linecast._runtime import WeatherRuntime, current_runtime, log_skipped
from linecast._i18n import lang_of, table_for
from linecast._weather_historical import temperature_scale
from linecast._weather_i18n import FULL_DAY_NAMES, _s
from linecast._weather_sources import _local_now_for_data
from linecast._weather_style import (
    CHART_BG_DAY_RGB,
    CHART_BG_NIGHT_RGB,
    CHART_HOVER_RGB,
    CHART_NOW_RGB,
    CLOUD_RGB,
    DIM,
    MUTED_RGB,
    DIM_RGB,
    SPARKLINE,
    SUNRISE_LABEL_RGB,
    SUNSET_LABEL_RGB,
    TEXT,
    UV_COLOR,
    WIND_ARROWS,
    WIND_COLOR,
    PRECIP_BAR_FULL,
    _colored_temp,
    _precip_rgb,
    _temp_color,
)

# The UV index from which the WHO says to protect skin: "moderate" starts
# at 3. The chart labels a reading once it rounds to this, so what is
# shown and what is judged agree.
UV_LABEL_MIN = 3


def _uv_label_value(uv):
    """The whole number a UV reading is labelled with."""
    return int(round(uv))


def _wind_threshold(runtime):
    """The wind speed, in the runtime's unit, above which the chart
    labels the wind: 25 km/h."""
    return 25 / runtime.wind_kmh(1)


def _daylight_factor(col_dt, sun_events):
    """Return a brightness factor (0.0-1.0) for a given datetime.

    1.0 = full daylight, 0.0 = full night.
    Transitions smoothly over ~40 minutes at dawn/dusk.
    sun_events is a list of (sunrise_dt, sunset_dt) tuples for each day.
    """
    TRANSITION_MINS = 40
    best = 0.0
    for rise, sset in sun_events:
        if rise is None or sset is None:
            continue
        # Minutes relative to sunrise/sunset
        mins_from_rise = (col_dt - rise).total_seconds() / 60
        mins_from_set = (col_dt - sset).total_seconds() / 60

        if mins_from_rise >= TRANSITION_MINS and mins_from_set <= -TRANSITION_MINS:
            # Full day
            return 1.0
        if mins_from_rise < 0 and mins_from_set > 0:
            # Full night (before sunrise, after sunset)
            pass
        else:
            # In transition zone
            dawn_f = max(0.0, min(1.0, mins_from_rise / TRANSITION_MINS))
            dusk_f = max(0.0, min(1.0, -mins_from_set / TRANSITION_MINS))
            f = min(dawn_f, dusk_f)
            best = max(best, f)
    return best


def _parse_sun_events(daily):
    """Parse sunrise/sunset ISO strings from daily data into datetime pairs."""
    events = []
    sunrises = daily.get("sunrise", [])
    sunsets = daily.get("sunset", [])
    total = max(len(sunrises), len(sunsets))
    dropped = 0
    bad = None
    for i in range(total):
        rise = sunset = None
        try:
            if i < len(sunrises) and sunrises[i]:
                rise = datetime.fromisoformat(sunrises[i])
        except (TypeError, ValueError) as exc:
            dropped += 1
            bad = exc
        try:
            if i < len(sunsets) and sunsets[i]:
                sunset = datetime.fromisoformat(sunsets[i])
        except (TypeError, ValueError) as exc:
            dropped += 1
            bad = exc
        events.append((rise, sunset))
    log_skipped("weather/open-meteo", "sun events", dropped, total * 2, bad)
    return events


# ---------------------------------------------------------------------------
# Braille temperature curve (multi-row, smooth line)
# ---------------------------------------------------------------------------
def _precip_bar_full(data, runtime):
    """Hourly amount that fills the precipitation bar, in the data's unit."""
    unit = (data.get("hourly_units") or {}).get("precipitation")
    if unit not in PRECIP_BAR_FULL:
        unit = "mm" if runtime.metric else "inch"
    return PRECIP_BAR_FULL[unit]


def _indicator_colors(graph_w, midnight_cols=None, hover_col=None, now_col=None):
    """Column -> RGB of the vertical time line through it.

    The hover line wins over the now line, which wins over a midnight
    divider, as in the temperature rows."""
    colors = {}
    for c in midnight_cols or ():
        if 0 <= c < graph_w:
            colors[c] = DIM_RGB
    if now_col is not None and 0 <= now_col < graph_w:
        colors[now_col] = CHART_NOW_RGB
    if hover_col is not None and 0 <= hover_col < graph_w:
        colors[hover_col] = CHART_HOVER_RGB
    return colors


def _as_indicators(indicator_cols):
    """Accept a column -> RGB map, or a bare set of columns in the divider color."""
    if not indicator_cols:
        return {}
    if isinstance(indicator_cols, dict):
        return indicator_cols
    return {c: DIM_RGB for c in indicator_cols}


def _indicator_row(graph_w, indicators):
    """A row holding nothing but the vertical time lines, or "" without any.

    Stands in for a wind, UV, or precipitation row that is reserved for
    the sake of a steady layout but has nothing to show in this window,
    so the lines run unbroken from the chart to the bottom of the section."""
    if not indicators:
        return ""
    cells = [f"{fg(*indicators[x])}\u2502" if x in indicators else " " for x in range(graph_w)]
    return f"{''.join(cells)}{RESET}"


def _through_line(rgb, indicators, x, through_col=None):
    """The color of a filled cell in column x.

    Only the hover line (through_col) tints the cell toward its own color,
    so it reads on through the bar; it moves with the mouse, so a tinted
    cell is hard to mistake for data.  The now line and the midnight
    dividers stop behind a filled cell: a darker cell in a fixed column
    looks like less cloud or a fainter chance of rain."""
    if through_col is None or x != through_col:
        return rgb
    ind = indicators.get(x)
    if ind is None:
        return rgb
    return _theme.lerp_rgb(rgb, ind, 0.5)


def _precip_columns(amounts, probs, weather_codes, graph_w, full):
    """Per-column (height fraction, RGB) for the precipitation bar.

    Height follows the forecast amount: the square root of its fraction of
    `full`, so drizzle registers and heavy rain tops out.  Color is the
    precipitation type faded toward the background by the probability, so a
    likely shower is solid and a long shot is a ghost of one.  Terminals
    with 16 colors or none cannot blend, so there the bar is always solid.
    A column with no forecast amount has height 0 whatever the probability.
    """
    col_amounts = interpolate(amounts, graph_w)
    col_probs = interpolate(probs, graph_w) if probs else [100] * graph_w
    blend = color_mode() in ("truecolor", "256")
    columns = []
    for x in range(graph_w):
        amount = col_amounts[x]
        if amount <= 0:
            columns.append((0.0, None))
            continue
        frac = math.sqrt(min(1.0, amount / full))
        code_t = x / max(1, graph_w - 1) * max(0, len(weather_codes) - 1)
        code_i = max(0, min(len(weather_codes) - 1, int(round(code_t))))
        rgb = _precip_rgb(weather_codes[code_i] if weather_codes else 0)
        if blend:
            alpha = max(0.0, min(1.0, col_probs[x] / 100))
            rgb = _theme.lerp_rgb(_theme.theme_bg, rgb, alpha)
        columns.append((frac, rgb))
    return columns


def _build_precip_blocks(amounts, probs, weather_codes, graph_w, n_rows=1, indicator_cols=None,
                         full=PRECIP_BAR_FULL["mm"], through_col=None):
    """Build multi-row block bar graph for precipitation.

    Returns a list of rendered line strings (n_rows lines).
    Bars grow upward from the bottom using partial block characters (▁▂▃▄▅▆▇█),
    giving 8 levels of vertical resolution per character row.  See
    _precip_columns for what height and color mean.
    indicator_cols: columns of the vertical time lines (a column -> RGB
    map, or a set drawn in the divider color): │ where the cell is empty.
    through_col: the one line, the hover line, that also tints its way
    through the bar where the cell is filled; the others stop behind it.
    """
    total_eighths = n_rows * 8  # total vertical resolution units
    columns = _precip_columns(amounts, probs, weather_codes, graph_w, full)
    indicators = _as_indicators(indicator_cols)

    # Build rows top-down (row 0 = top, row n_rows-1 = bottom)
    result = []
    for r in range(n_rows):
        line = ""
        row_bottom = (n_rows - 1 - r) * 8  # eighths at bottom of this row
        row_top = row_bottom + 8             # eighths at top of this row
        for x in range(graph_w):
            frac, rgb = columns[x]
            is_empty = frac <= 0
            if not is_empty:
                bar_h = max(1, int(frac * total_eighths + 0.5))
                is_empty = bar_h <= row_bottom

            if is_empty:
                if x in indicators:
                    line += f"{fg(*indicators[x])}\u2502"
                else:
                    line += " "
            elif bar_h >= row_top:
                line += f"{fg(*_through_line(rgb, indicators, x, through_col))}\u2588"
            else:
                eighths_in_row = bar_h - row_bottom  # 1-7
                line += (f"{fg(*_through_line(rgb, indicators, x, through_col))}"
                         f"{SPARKLINE[eighths_in_row - 1]}")
        result.append(f"{line}{RESET}")

    return result


def _render_cloud_row(window_cloud, graph_w, indicator_cols=None, through_col=None):
    """One half-block strip of cloud cover, or None without data.

    Each column is the lower half of the cell, faded from the background
    toward CLOUD_RGB by the hour's cloud cover, so clear sky is nothing
    and overcast is a solid band.  It sits directly on the precipitation
    bar: cloud above, rain below.  The vertical time lines pass through a
    clear column as a hairline; only the hover line (through_col) tints
    the strip where there is cloud, the rest stop behind it.
    """
    if not window_cloud:
        return None
    indicators = _as_indicators(indicator_cols)
    col_cover = interpolate(window_cloud, graph_w)
    parts = []
    for x in range(graph_w):
        cover = max(0.0, min(100.0, col_cover[x])) / 100
        if cover < 0.05:
            parts.append(f"{fg(*indicators[x])}\u2502" if x in indicators else " ")
            continue
        rgb = _theme.lerp_rgb(_theme.theme_bg, CLOUD_RGB, cover)
        parts.append(f"{fg(*_through_line(rgb, indicators, x, through_col))}\u2584")
    return f"{''.join(parts)}{RESET}"


def _interpolate_columns(values, graph_w):
    """Linearly interpolate values to one sample per terminal column."""
    return interpolate(values, graph_w)


def _present(values):
    """The numbers in a series, with the nulls left out."""
    return [v for v in (values or ()) if v is not None]


def _filled(values, fill=None):
    """A series with each null replaced: by the nearest earlier value, or
    the nearest later one at the start, or `fill` when there is nothing
    else.  Open-Meteo writes null for an hour it has no value for, and a
    curve wants a number in every hour; carrying the neighbour across
    the gap keeps the line unbroken and the columns aligned with the
    clock.  `fill` is for the series where a missing hour honestly means
    nothing -- no rain, no cloud, no UV -- rather than "about the same".
    """
    if not values:
        return []
    if fill is not None:
        return [fill if v is None else v for v in values]
    out = list(values)
    last = next((v for v in out if v is not None), None)
    if last is None:
        return []
    for i, v in enumerate(out):
        if v is None:
            out[i] = last
        else:
            last = v
    return out


def _prepare_hourly_window(hourly, now, graph_w, offset_minutes=0):
    """Slice hourly arrays to the visible window.

    offset_minutes shifts the window start forward (positive) or backward
    (negative) from the current hour, enabling keyboard/mouse scrolling.

    The nulls in the series are dealt with here, once, so that nothing
    downstream -- the curve, the bars, the labels, the hover chip -- meets
    one (see _filled).  A temperature series with no numbers at all is no
    graph, and returns None like an empty one.
    """
    times = hourly.get("time", [])
    temps = _filled(hourly.get("temperature_2m", []))
    precip_prob = _filled(hourly.get("precipitation_probability", []), fill=0)
    precip_amount = _filled(hourly.get("precipitation", []), fill=0)
    weather_codes = _filled(hourly.get("weather_code", []), fill=0)
    wind_speeds = _filled(hourly.get("wind_speed_10m", []), fill=0)
    wind_directions = _filled(hourly.get("wind_direction_10m", []))
    apparent_temps = _filled(hourly.get("apparent_temperature", []))
    humidity = _filled(hourly.get("relative_humidity_2m", []))
    dew_points = _filled(hourly.get("dew_point_2m", []))
    uv_indices = _filled(hourly.get("uv_index", []), fill=0)
    cloud_cover = _filled(hourly.get("cloud_cover", []), fill=0)
    if not times or not temps:
        return None

    parsed = []
    for i, t in enumerate(times):
        try:
            parsed.append((i, datetime.fromisoformat(t)))
        except Exception:
            continue

    current_hour_dt = now.replace(minute=0, second=0, microsecond=0)
    hours_shown = max(24, min(48, graph_w // 2))

    window_start_dt = current_hour_dt + timedelta(minutes=offset_minutes)

    # Clamp so the window fits within available data
    if parsed:
        first_dt = parsed[0][1]
        last_dt = parsed[-1][1]
        max_start = last_dt - timedelta(hours=hours_shown)
        if window_start_dt > max_start:
            window_start_dt = max_start
        if window_start_dt < first_dt:
            window_start_dt = first_dt

    start_idx = 0
    for i, dt in parsed:
        if dt >= window_start_dt:
            start_idx = i
            break

    end_time = window_start_dt + timedelta(hours=hours_shown)
    end_idx = start_idx
    for i, dt in parsed:
        if i >= start_idx and dt <= end_time:
            end_idx = i

    window_temps = temps[start_idx:end_idx + 1]
    if len(window_temps) < 2:
        return None

    window_precip = precip_prob[start_idx:end_idx + 1] if precip_prob else []
    window_amount = precip_amount[start_idx:end_idx + 1] if precip_amount else []
    window_codes = weather_codes[start_idx:end_idx + 1] if weather_codes else []
    window_winds = wind_speeds[start_idx:end_idx + 1] if wind_speeds else []
    window_wind_dirs = wind_directions[start_idx:end_idx + 1] if wind_directions else []
    window_apparent = apparent_temps[start_idx:end_idx + 1] if apparent_temps else []
    window_humidity = humidity[start_idx:end_idx + 1] if humidity else []
    window_dew = dew_points[start_idx:end_idx + 1] if dew_points else []
    window_uv = uv_indices[start_idx:end_idx + 1] if uv_indices else []
    window_cloud = cloud_cover[start_idx:end_idx + 1] if cloud_cover else []
    window_dts = [dt for i, dt in parsed if start_idx <= i <= end_idx]

    # Hours of real time across the window: the samples are an hour
    # apart, so one fewer than there are samples, whatever the wall
    # clock says between the first and the last.  The day the clocks
    # change has 23 or 25 of them, and each is as wide on the chart as
    # any other (issue #110).
    total_hours = len(window_dts) - 1 if len(window_dts) > 1 else 24

    # Global stats across all available data for stable layout while scrolling
    all_temp_lo = min(temps) if temps else 0
    all_temp_hi = max(temps) if temps else 0
    all_wind_max = max(wind_speeds) if wind_speeds else 0
    all_uv_max = max(uv_indices) if uv_indices else 0
    all_precip_max = max(precip_amount) if precip_amount else 0

    return {
        "temps": window_temps,
        "precip": window_precip,
        "precip_amount": window_amount,
        "codes": window_codes,
        "winds": window_winds,
        "wind_dirs": window_wind_dirs,
        "apparent_temps": window_apparent,
        "humidity": window_humidity,
        "dew_points": window_dew,
        "uv": window_uv,
        "cloud": window_cloud,
        "dts": window_dts,
        "total_hours": total_hours,
        "hours_shown": hours_shown,
        "offset_minutes": (window_start_dt - current_hour_dt).total_seconds() / 60,
        "all_temps": temps,
        "all_winds": wind_speeds,
        "all_wind_dirs": wind_directions,
        "all_uv": uv_indices,
        "start_idx": start_idx,
        "end_idx": end_idx,
        "all_temp_range": (all_temp_lo, all_temp_hi),
        "all_wind_max": all_wind_max,
        "all_uv_max": all_uv_max,
        "all_precip_max": all_precip_max,
    }


def _sample_col(i, n, graph_w):
    """The column the i-th of n samples is drawn at."""
    return int(i / max(1, n - 1) * (graph_w - 1))


def _column_of(dt, window_dts, graph_w):
    """The column a moment falls on, found among the window's samples
    rather than counted in clock hours from the first: the samples are
    an hour apart in real time whatever the wall clock says across a
    clock change, so this is where the curve draws that moment.  None
    outside the window."""
    n = len(window_dts)
    if n < 2 or dt < window_dts[0] or dt > window_dts[-1]:
        return None
    i = n - 2
    for k in range(n - 1):
        if window_dts[k + 1] > dt:
            i = k
            break
    span = (window_dts[i + 1] - window_dts[i]).total_seconds()
    frac = (dt - window_dts[i]).total_seconds() / span if span > 0 else 0.0
    return (i + min(1.0, max(0.0, frac))) / (n - 1) * (graph_w - 1)


def _compute_time_markers(window_dts, total_hours, graph_w, runtime=None):
    """Compute notable timeline columns (midnight, noon) and day labels.

    The samples are on the hour, so a midnight or a noon is one of them,
    and is drawn where the curve draws it."""
    lang = lang_of(runtime)
    midnight_cols = set()
    noon_cols = set()
    midnight_day_names = {}
    if window_dts:
        n = len(window_dts)
        for i, dt in enumerate(window_dts):
            x = _sample_col(i, n, graph_w)
            if not (0 < x < graph_w - 1):
                continue
            if dt.hour == 0:
                midnight_cols.add(x)
                midnight_day_names[x] = table_for(FULL_DAY_NAMES, lang)[dt.weekday()]
            elif dt.hour == 12:
                noon_cols.add(x)
    return midnight_cols, noon_cols, midnight_day_names


def _compute_sun_labels(window_dts, sun_events, total_hours, graph_w, runtime):
    """Compute sunrise/sunset labels mapped to graph columns."""
    sun_labels = {}
    use_24h = runtime.use_24h
    # Sunrise and sunset are marked with up and down arrows in every
    # icon set: they say rise and set more plainly than any sun glyph,
    # match the oneline view, and stay one cell wide.
    sunrise_icon = "\u2191"
    sunset_icon = "\u2193"
    if window_dts and sun_events:
        for rise, sset in sun_events:
            for moment, icon, is_rise in ((rise, sunrise_icon, True),
                                          (sset, sunset_icon, False)):
                if not moment:
                    continue
                col = _column_of(moment, window_dts, graph_w)
                if col is None:
                    continue
                x = int(col)
                if 0 < x < graph_w - 1:
                    lbl = fmt_time_dt(moment, use_24h)
                    sun_labels[x] = (f"{icon}{lbl}", is_rise)
    return sun_labels


def _compute_daylight_columns(window_dts, sun_events, graph_w):
    """Compute per-column daylight factor for day/night tinting."""
    if window_dts and sun_events:
        col_daylight = []
        for x in range(graph_w):
            t_frac = x / max(1, graph_w - 1) * max(0, len(window_dts) - 1)
            lo_i = int(t_frac)
            hi_i = min(lo_i + 1, len(window_dts) - 1)
            frac = t_frac - lo_i
            # Interpolated in place: a round trip through a timestamp
            # would read these naive local times in the machine's zone,
            # and on its own DST night shift an hour of columns.
            col_dt = window_dts[lo_i] + (window_dts[hi_i] - window_dts[lo_i]) * frac
            col_daylight.append(_daylight_factor(col_dt, sun_events))
        return col_daylight
    return [1.0] * graph_w


def _find_temperature_extrema(col_temps, graph_w):
    """Detect notable points for chart annotations: peaks, valleys, and bends.

    All candidate label points are scored and placed greedily from highest to
    lowest priority, respecting a minimum gap between labels.  This naturally
    adapts to terminal width — wider charts get more labels.

    Candidate types (unified scoring in comparable degree units):
      - Global max/min: score 1000 (always placed first)
      - Peaks/valleys:  score = topographic prominence (degrees)
      - Curvature bends: score = equivalent temperature displacement over the
        label-gap window, capturing elbows and plateaus

    Real peaks/valleys always outrank curvature bends during placement, so a
    decorative slope-bend can never elbow out the genuine extremum beside it.
    """
    extrema = []  # (x, temp, is_peak)
    if len(col_temps) < 5:
        return extrema

    min_gap = max(8, graph_w // 15)
    n = len(col_temps)

    def prominence(i, is_peak):
        """Topographic prominence: scan outward until the curve rises above
        (peak) or drops below (valley) this point, taking the min/max reached
        along the way.  Unlike a fixed-radius window this adapts to the terrain,
        so a broad flat top/bottom or an extremum near the chart edge still gets
        the drop to its true surrounding saddle rather than a near-zero value.
        Ties (plateaus of equal temperature) are scanned across, not stopped at.
        """
        v = col_temps[i]
        if is_peak:
            lo = v
            j = i - 1
            while j >= 0 and col_temps[j] <= v:
                lo = min(lo, col_temps[j])
                j -= 1
            hi = v
            j = i + 1
            while j < n and col_temps[j] <= v:
                hi = min(hi, col_temps[j])
                j += 1
            return v - max(lo, hi)
        lo = v
        j = i - 1
        while j >= 0 and col_temps[j] >= v:
            lo = max(lo, col_temps[j])
            j -= 1
        hi = v
        j = i + 1
        while j < n and col_temps[j] >= v:
            hi = max(hi, col_temps[j])
            j += 1
        return min(lo, hi) - v

    # All candidates: (x, temp, is_peak, score, is_curve)
    scored = []

    # --- Peaks and valleys (scored by topographic prominence in degrees) ---
    for i in range(2, n - 2):
        local = col_temps[max(0, i - 3):i + 4]
        is_peak = col_temps[i] >= max(local) and (
            col_temps[i] > col_temps[i - 1] or col_temps[i] > col_temps[i + 1]
        )
        is_valley = col_temps[i] <= min(local) and (
            col_temps[i] < col_temps[i - 1] or col_temps[i] < col_temps[i + 1]
        )
        if not is_peak and not is_valley:
            continue
        prom = prominence(i, is_peak)
        if prom >= 1:
            scored.append((i, col_temps[i], is_peak, prom, False))

    # --- Global max/min (always placed first) ---
    global_max_x = max(range(n), key=lambda i: col_temps[i])
    global_min_x = min(range(n), key=lambda i: col_temps[i])
    for gx, is_peak in [(global_max_x, True), (global_min_x, False)]:
        scored.append((gx, col_temps[gx], is_peak, 1000, False))

    # --- Curvature points: elbows and plateaus ---
    # Sagitta = how far the curve deviates from a straight chord.
    # Directly in degrees, comparable to peak/valley prominence.
    half_w = min_gap * 2
    detect_r = max(3, graph_w // 40)
    sagittas = [0.0] * n
    for i in range(detect_r, n - detect_r):
        hw = min(half_w, i, n - 1 - i)
        if hw < min_gap:
            continue
        sagittas[i] = col_temps[i] - (col_temps[i - hw] + col_temps[i + hw]) / 2

    for i in range(detect_r, n - detect_r):
        abs_sag = abs(sagittas[i])
        if abs_sag < 1:
            continue
        # Only label slope bends — skip near local temperature extrema
        local_slice = col_temps[max(0, i - min_gap):min(n, i + min_gap + 1)]
        local_hi, local_lo = max(local_slice), min(local_slice)
        band = (local_hi - local_lo) * 0.15
        if col_temps[i] > local_hi - band or col_temps[i] < local_lo + band:
            continue
        # Must be a local maximum of |sagitta|
        if any(abs(sagittas[j]) > abs_sag
               for j in range(i - detect_r, i + detect_r + 1)):
            continue
        # Concave up (sag<0, elbow) → label above; concave down (sag>0) → below
        is_peak = sagittas[i] < 0
        scored.append((i, col_temps[i], is_peak, abs_sag, True))

    # --- Greedily place: genuine peaks/valleys first (is_curve=False), then
    # curvature bends; within each tier, highest score wins. ---
    # Spacing is enforced only between labels of the SAME kind: peaks are drawn
    # above the curve and valleys below it, so a peak and a valley never
    # collide even when adjacent.  A day's morning valley and afternoon peak sit
    # closer than min_gap, and gating across kinds would let one silently evict
    # the other (topographic prominence makes the pair score almost equally).
    for x, temp, is_peak, _score, _is_curve in sorted(
        scored, key=lambda c: (c[4], -c[3])
    ):
        if any(abs(x - ex) < min_gap for ex, _, ep in extrema if ep == is_peak):
            continue
        # Skip if a nearby same-kind label already shows the same rounded temp.
        label_int = int(round(temp))
        if any(abs(x - ex) < min_gap * 3 and int(round(t)) == label_int
               for ex, t, ep in extrema if ep == is_peak):
            continue
        extrema.append((x, temp, is_peak))

    return extrema


def _render_today_line(width, chart_lo, chart_hi, midnight_day_names, sun_labels, runtime,
                       window_dts=None, now=None, offset_minutes=0):
    """Render the hourly section header with day and sun-event labels."""
    # Show "Today" only when the window starts on today's date;
    # otherwise show the actual day name so scrolled views make sense.
    lang = lang_of(runtime)
    if window_dts and now and window_dts[0].date() != now.date():
        day_name = table_for(FULL_DAY_NAMES, lang)[window_dts[0].weekday()]
        today_left = f"{TEXT}{day_name}"
    else:
        today_left = f"{TEXT}{_s('today', runtime)}"
    if offset_minutes:
        hint_text = _s("space_to_now", runtime)
        today_right = f"{DIM}{hint_text}"
    else:
        today_right = (
            f"{_colored_temp(chart_lo, runtime, '°')} "
            f"{TEXT}\u2192 {_colored_temp(chart_hi, runtime, runtime.temp_unit)}"
        )
    if not (midnight_day_names or sun_labels):
        pad = width - visible_len(today_left) - visible_len(today_right)
        return f"{today_left}{' ' * max(1, pad)}{today_right}{RESET}"

    label_start = visible_len(today_left)

    # Drop the "today" label if it would crowd out a midnight day name
    if midnight_day_names:
        first_col = min(midnight_day_names)
        if first_col <= label_start:
            today_left = ""
            label_start = 0
    right_len = visible_len(today_right)
    avail = width - right_len
    mid_w = max(0, avail - label_start)

    # A day name or a sun time never touches the label at either end:
    # "Today" keeps a column clear after it, the range one before it.
    left_gap = 1 if today_left else 0
    fit_w = mid_w - 1

    mid_canvas = [" "] * mid_w
    mid_colors = [None] * mid_w

    for col, name in sorted(midnight_day_names.items()):
        pos = col - label_start
        name_w = visible_len(name)
        if pos >= left_gap and pos + name_w <= fit_w:
            cx = pos
            base = None
            for c in name:
                cw = visible_len(c)
                if cw == 0:
                    # A combining mark (a Thai vowel sign, say) shares
                    # its base's cell rather than claiming the next one.
                    if base is not None:
                        mid_canvas[base] += c
                    continue
                mid_canvas[cx] = c
                base = cx
                for k in range(1, cw):
                    if cx + k < mid_w:
                        mid_canvas[cx + k] = ""
                cx += cw

    for col, (lbl, is_rise) in sorted(sun_labels.items()):
        pos = max(left_gap, col - label_start)
        lbl_w = visible_len(lbl)
        if pos + lbl_w > fit_w:
            continue
        if all(mid_canvas[pos + j] == " " for j in range(lbl_w)):
            color = SUNRISE_LABEL_RGB if is_rise else SUNSET_LABEL_RGB
            cx = pos
            base = None
            for c in lbl:
                cw = visible_len(c)
                if cw == 0:
                    if base is not None:
                        mid_canvas[base] += c
                    continue
                mid_canvas[cx] = c
                mid_colors[cx] = color
                base = cx
                for k in range(1, cw):
                    if cx + k < mid_w:
                        mid_canvas[cx + k] = ""
                        mid_colors[cx + k] = color
                cx += cw

    mid_str = ""
    cur_color = None
    for i in range(mid_w):
        color = mid_colors[i]
        if color != cur_color:
            if color is None:
                mid_str += f"{TEXT}"
            else:
                mid_str += f"{fg(*color)}"
            cur_color = color
        mid_str += mid_canvas[i]
    if cur_color is not None:
        mid_str += f"{TEXT}"

    pad = width - visible_len(today_left) - mid_w - visible_len(today_right)
    return f"{today_left}{mid_str}{' ' * max(0, pad)}{today_right}{RESET}"


def _render_extrema_line(extrema, graph_w, runtime, is_peak):
    """Render one extrema annotation line (peaks above or valleys below)."""
    points = sorted([(x, t) for x, t, peak in extrema if peak == is_peak])
    if not points:
        return None

    segments, cursor = [], 0
    for x, temp in points:
        label = f"{temp:.0f}\u00b0"
        pos = max(cursor, x - len(label) // 2)
        if pos + len(label) > graph_w:
            continue
        if pos > cursor:
            segments.append((" " * (pos - cursor), None))
        segments.append((label, temp))
        cursor = pos + len(label)
    if not segments:
        return None

    line = ""
    for text, temp in segments:
        if temp is None:
            line += text
            continue
        r, g, b = _temp_color(temp, runtime)
        line += f"{fg(r, g, b)}{text}"
    return f"{line}{RESET}"


def _compute_extrema_overlays(extrema, col_temps, n_rows, graph_w, runtime, value_range=None):
    """Map temperature extrema to overlay labels on specific braille rows."""
    if not extrema or n_rows < 1:
        return {}

    if value_range is not None:
        t_min, t_max = value_range
    else:
        t_min, t_max = min(col_temps), max(col_temps)
    total_dots = n_rows * 4
    overlays = {}  # row_idx -> [(start_col, label_text, (r, g, b)), ...]
    occupied_by_row = {}

    sorted_extrema = sorted(extrema, key=lambda e: -e[1] if e[2] else e[1])

    for x, temp, is_peak in sorted_extrema:
        if t_max == t_min:
            curve_row = n_rows // 2
        else:
            y = (total_dots - 1) * (1 - (temp - t_min) / (t_max - t_min))
            curve_row = max(0, min(n_rows - 1, int(round(y)) // 4))

        if is_peak:
            label_row = max(0, curve_row - 1)
        else:
            label_row = min(n_rows - 1, curve_row + 1)

        label = f"{temp:.0f}\u00b0"
        start = max(0, min(graph_w - len(label), x - len(label) // 2))

        if label_row not in occupied_by_row:
            occupied_by_row[label_row] = set()
        cols = set(range(start, start + len(label)))
        if cols & occupied_by_row[label_row]:
            continue
        occupied_by_row[label_row] |= cols

        color = _temp_color(temp, runtime)
        overlays.setdefault(label_row, []).append((start, label, color))

    return overlays


def _compute_axis_overlays(value_range, braille_rows, n_rows, graph_w, overlays, now_col=None):
    """Dim labels for the two ends of the chart's temperature axis: the
    top row's value on the top row, the bottom row's on the bottom,
    wherever the curve and the other labels leave the cells blank. The
    left edge first, just past the now line when that sits there, and
    the right edge when the left is taken. Adds to `overlays` in place."""
    lo, hi = value_range
    if n_rows < 1 or len(braille_rows) < n_rows or hi <= lo:
        return
    occupied = {}
    for row, items in overlays.items():
        for start, label, _color in items:
            occupied.setdefault(row, set()).update(range(start, start + len(label)))
    for row, value in ((0, hi), (n_rows - 1, lo)):
        label = f"{value:.0f}\u00b0"
        left = 1
        if now_col is not None and now_col < left + len(label):
            left = now_col + 1
        for start in (left, graph_w - len(label) - 1):
            cols = range(start, start + len(label))
            if start < 0 or cols[-1] >= len(braille_rows[row]):
                continue
            if occupied.get(row, set()).intersection(cols):
                continue
            if any(braille_rows[row][c][0] != "\u2800" for c in cols):
                continue
            occupied.setdefault(row, set()).update(cols)
            overlays.setdefault(row, []).append((start, label, MUTED_RGB))
            break


def _render_braille_rows(braille_rows, col_daylight, midnight_cols, runtime,
                         overlays=None, hover_col=None, now_col=None):
    """Render braille temperature rows with optional day/night shading."""
    if overlays is None:
        overlays = {}
    shading = runtime.shading
    night_dim = 0.6
    midnight_fg = DIM
    hover_fg = fg(*CHART_HOVER_RGB)
    now_fg = fg(*CHART_NOW_RGB)
    bg_night = CHART_BG_NIGHT_RGB
    bg_day = CHART_BG_DAY_RGB

    lines = []
    for row_idx, row in enumerate(braille_rows):
        # Build overlay char map for this row
        overlay_chars = {}
        for start_col, label, color in overlays.get(row_idx, []):
            for j, c in enumerate(label):
                col = start_col + j
                if 0 <= col < len(row):
                    overlay_chars[col] = (c, color)

        line = ""
        for ci, (ch, temp) in enumerate(row):
            dl = col_daylight[ci] if ci < len(col_daylight) else 1.0

            if ci in overlay_chars:
                oc, oc_color = overlay_chars[ci]
                if shading:
                    br = int(bg_night[0] + (bg_day[0] - bg_night[0]) * dl)
                    bg_g = int(bg_night[1] + (bg_day[1] - bg_night[1]) * dl)
                    bb = int(bg_night[2] + (bg_day[2] - bg_night[2]) * dl)
                    bg_str = bg(br, bg_g, bb)
                    line += f"{bg_str}{fg(*oc_color)}{oc}{RESET}"
                else:
                    line += f"{fg(*oc_color)}{oc}"
                continue

            # Pick indicator color for empty cells (hover > now > midnight)
            indicator = None
            if ch == '\u2800':
                if hover_col is not None and ci == hover_col:
                    indicator = hover_fg
                elif now_col is not None and ci == now_col:
                    indicator = now_fg
                elif ci in midnight_cols:
                    indicator = midnight_fg

            if shading:
                br = int(bg_night[0] + (bg_day[0] - bg_night[0]) * dl)
                bg_g = int(bg_night[1] + (bg_day[1] - bg_night[1]) * dl)
                bb = int(bg_night[2] + (bg_day[2] - bg_night[2]) * dl)
                bg_str = bg(br, bg_g, bb)

                if indicator:
                    line += f"{bg_str}{indicator}\u2502{RESET}"
                else:
                    r, g, b = _temp_color(temp, runtime)
                    line += f"{bg_str}{fg(r, g, b)}{ch}{RESET}"
            else:
                if indicator:
                    line += f"{indicator}\u2502"
                else:
                    r, g, b = _temp_color(temp, runtime)
                    brightness = night_dim + (1.0 - night_dim) * dl
                    line += fg(int(r * brightness), int(g * brightness), int(b * brightness))
                    line += ch
        lines.append(f"{line}{RESET}")
    return lines


def _render_tick_labels(window_dts, total_hours, graph_w, runtime=None, hover_col=None,
                        now_col=None):
    """Render compact timeline tick labels under the chart.

    Labels are anchored to clock-aligned hours so they scroll with the data
    rather than staying at fixed screen positions.
    """
    if not window_dts:
        return None
    use_24h = runtime.use_24h if runtime else False
    if graph_w < 40:
        interval = 6
    elif graph_w < 80:
        interval = 4
    elif graph_w < 140:
        interval = 3
    else:
        interval = 2

    # Each label is one of the samples, at the column the curve draws
    # it: the hour the clocks skip has no label, the hour they repeat
    # has two.
    n = len(window_dts)
    label_items = []
    for i, dt in enumerate(window_dts):
        if dt.hour % interval:
            continue
        x = _sample_col(i, n, graph_w)
        if 0 <= x < graph_w:
            label_items.append((x, fmt_hour(dt.hour, use_24h), dt.hour == 0))

    canvas = [" "] * graph_w
    last_end = 0
    for x, label, is_midnight in label_items:
        tick = "\u2502" if is_midnight else "\u2575"
        tick_label = f"{tick}{label}"
        if x < last_end or x + len(tick_label) > graph_w:
            continue
        for j, c in enumerate(tick_label):
            if x + j < graph_w:
                canvas[x + j] = c
        last_end = x + len(tick_label) + 1
    if hover_col is not None and 0 <= hover_col < graph_w and canvas[hover_col] == " ":
        canvas[hover_col] = "\u2502"
    elif now_col is not None and 0 <= now_col < graph_w and canvas[now_col] == " ":
        canvas[now_col] = "\u2502"
    return f"{DIM}{''.join(canvas)}{RESET}"


def _place_labels(items, graph_w):
    """Lay out (column, text) labels left to right, dropping any that collide.

    Each label is anchored on its column and kept whole; the return value is a
    list of (start_column, text) pairs.
    """
    placed = []
    occupied = [False] * graph_w
    for x, text in items:
        start = max(0, x - len(text) // 2)
        if start + len(text) > graph_w:
            start = graph_w - len(text)
        if start < 0:
            continue
        if any(occupied[start + j] for j in range(len(text))):
            continue
        for j in range(len(text)):
            occupied[start + j] = True
        placed.append((start, text))
    return placed


def _labels_to_canvas(placed, graph_w):
    """Draw placed labels onto a character array of the given width."""
    if not placed:
        return None
    canvas = [" "] * graph_w
    for start, text in placed:
        for j, ch in enumerate(text):
            if 0 <= start + j < graph_w:
                canvas[start + j] = ch
    return canvas


def _labels_in_window(placed, win_start_col, win_span, graph_w):
    """Map labels from the full-width canvas into the visible window.

    Each label moves as a unit. Resampling the character canvas column by
    column instead would drop or double the odd digit, since the two canvases
    are close to but not exactly the same scale.
    """
    scale = (graph_w - 1) / max(1, win_span)
    moved = []
    for start, text in placed:
        vis = int(round((start - win_start_col) * scale))
        # Labels that only partly fit are left out: a clipped one reads as a
        # different number rather than a truncated one.
        if vis < 0 or vis + len(text) > graph_w:
            continue
        moved.append((vis, text))
    moved.sort()
    kept = []
    last_end = -1
    for start, text in moved:
        if start <= last_end:
            continue
        kept.append((start, text))
        last_end = start + len(text) - 1
    return kept


def _sample_columns(graph_w, total_hours):
    """Columns to consider for a label, roughly one every three hours."""
    interval = max(1, int(3 / total_hours * (graph_w - 1))) if total_hours > 0 else 6
    return range(0, graph_w, max(1, interval))


def _place_wind_labels(winds, wind_dirs, total_hours, graph_w, runtime):
    """Place wind arrows and speeds at the windy parts of the chart.

    Placement is separate from rendering so it can run over the whole dataset,
    which keeps labels still while the chart scrolls under them.
    """
    wind_threshold = _wind_threshold(runtime)
    if not winds or max(winds, default=0) <= wind_threshold:
        return []

    candidates = []
    for x in _sample_columns(graph_w, total_hours):
        t = x / max(1, graph_w - 1) * max(0, len(winds) - 1)
        lo_i = int(t)
        hi_i = min(lo_i + 1, len(winds) - 1)
        frac = t - lo_i
        speed = winds[lo_i] + (winds[hi_i] - winds[lo_i]) * frac
        if speed <= wind_threshold:
            continue

        dir_i = max(0, min(len(wind_dirs) - 1, int(round(t)))) if wind_dirs else 0
        deg = wind_dirs[dir_i] if wind_dirs else 0
        sector = int((deg + 22.5) / 45) % 8
        candidates.append((x, f"{WIND_ARROWS[sector]}{speed:.0f}"))
    return _place_labels(candidates, graph_w)


def _place_uv_labels(uv_values, total_hours, graph_w, runtime):
    """Place UV index labels where protection is called for (UV_LABEL_MIN up)."""
    if not uv_values or _uv_label_value(max(uv_values, default=0)) < UV_LABEL_MIN:
        return []

    col_uv = _interpolate_columns(uv_values, graph_w)
    candidates = []
    for x in _sample_columns(graph_w, total_hours):
        uv = _uv_label_value(col_uv[x])
        if uv < UV_LABEL_MIN:
            continue
        candidates.append((x, f"{_s('uv', runtime)}{uv}"))
    return _place_labels(candidates, graph_w)


def _render_label_canvas(canvas, graph_w, color, midnight_cols=None, hover_col=None,
                         now_col=None, colors=None):
    """Render a pre-computed label canvas with styling and indicator lines.

    `colors`, when given, names an escape per column for the label cells
    there, so one row can carry labels of two kinds; `color` covers the
    rest."""
    if canvas is None or not any(c != " " for c in canvas):
        return None

    hover_fg = fg(*CHART_HOVER_RGB)
    now_fg = fg(*CHART_NOW_RGB)
    midnight_fg = DIM
    parts = []
    current = None
    for x in range(graph_w):
        ch = canvas[x] if x < len(canvas) else " "
        if ch != " ":
            want = (colors[x] if colors and x < len(colors) and colors[x] else color)
            if want != current:
                parts.append(want)
                current = want
            parts.append(ch)
        else:
            indicator = None
            if hover_col is not None and x == hover_col:
                indicator = hover_fg
            elif now_col is not None and x == now_col:
                indicator = now_fg
            elif midnight_cols and x in midnight_cols:
                indicator = midnight_fg
            if indicator:
                parts.append(f"{indicator}\u2502")
                current = None
            else:
                if current is None:
                    parts.append(color)
                    current = color
                parts.append(" ")
    parts.append(RESET)
    return "".join(parts)


def _labels_can_share(a, b, gap=2):
    """Whether two sets of placed labels fit on one row, keeping at least
    `gap` blank columns between a label of one kind and one of the other."""
    spans_b = [(start, start + len(text)) for start, text in b]
    for start, text in a:
        end = start + len(text)
        for b_start, b_end in spans_b:
            if start < b_end + gap and b_start < end + gap:
                return False
    return True


def _render_shared_row(wind, uv, graph_w, midnight_cols=None, hover_col=None, now_col=None):
    """One row carrying wind and UV labels together, each in its own color.

    The sets were checked apart before the window took them, so they should
    not meet; if the window's rounding brings two together, the one on the
    left stays, as it does within a kind."""
    labels = sorted([(start, text, WIND_COLOR) for start, text in wind]
                    + [(start, text, UV_COLOR) for start, text in uv])
    canvas = [" "] * graph_w
    colors = [None] * graph_w
    last_end = -1
    for start, text, color in labels:
        if start <= last_end:
            continue
        for j, ch in enumerate(text):
            if 0 <= start + j < graph_w:
                canvas[start + j] = ch
                colors[start + j] = color
        last_end = start + len(text) - 1
    return _render_label_canvas(canvas, graph_w, WIND_COLOR, midnight_cols=midnight_cols,
                                hover_col=hover_col, now_col=now_col, colors=colors)


def _render_wind_row(window_winds, window_wind_dirs, total_hours, graph_w, runtime,
                     midnight_cols=None, hover_col=None, now_col=None):
    """Render wind arrows/speed labels at high-wind positions."""
    placed = _place_wind_labels(window_winds, window_wind_dirs, total_hours, graph_w, runtime)
    return _render_label_canvas(_labels_to_canvas(placed, graph_w), graph_w, WIND_COLOR,
                                midnight_cols=midnight_cols, hover_col=hover_col,
                                now_col=now_col)


def _render_uv_row(window_uv, total_hours, graph_w, runtime,
                    midnight_cols=None, hover_col=None, now_col=None):
    """Render UV index labels where protection is called for (UV_LABEL_MIN up)."""
    placed = _place_uv_labels(window_uv, total_hours, graph_w, runtime)
    return _render_label_canvas(_labels_to_canvas(placed, graph_w), graph_w, UV_COLOR,
                                midnight_cols=midnight_cols, hover_col=hover_col,
                                now_col=now_col)


def _render_precip_rows(window_amount, window_precip, window_codes, graph_w, n_precip_rows,
                        indicator_cols=None, full=PRECIP_BAR_FULL["mm"], through_col=None):
    """Render precipitation graph rows: height is amount, color is probability."""
    if not window_amount or max(window_amount, default=0) <= 0:
        return []
    if n_precip_rows >= 1:
        return _build_precip_blocks(window_amount, window_precip, window_codes, graph_w,
                                    n_precip_rows, indicator_cols=indicator_cols, full=full,
                                    through_col=through_col)

    indicators = _as_indicators(indicator_cols)
    precip_chars = []
    for x, (frac, rgb) in enumerate(_precip_columns(window_amount, window_precip, window_codes,
                                                    graph_w, full)):
        if frac <= 0:
            if x in indicators:
                precip_chars.append(f"{fg(*indicators[x])}\u2502")
            else:
                precip_chars.append(" ")
            continue
        idx = max(0, min(7, int(frac * 7.99)))
        color = _through_line(rgb, indicators, x, through_col)
        precip_chars.append(f"{fg(*color)}{SPARKLINE[idx]}")
    return [f"{''.join(precip_chars)}{RESET}"]


def _full_canvas(window, graph_w):
    """The virtual canvas of the whole forecast that labels are placed on,
    so they hold still while the chart scrolls: (all_graph_w, win_start_col,
    win_span), or None when the window already shows the whole forecast."""
    all_temps = window.get("all_temps", window["temps"])
    start_idx = window.get("start_idx", 0)
    end_idx = window.get("end_idx", len(all_temps) - 1)
    n_window = end_idx - start_idx + 1
    n_all = len(all_temps)
    if not (n_all > n_window and n_window > 1):
        return None
    # Columns per hour, fixed by the terminal width alone. Deriving it from
    # the window's sample count instead would rescale the whole canvas
    # whenever the window happened to hold one hour more or less, and every
    # label on it would shift.
    cols_per_hour = (graph_w - 1) / max(1, window.get("hours_shown", 24))
    all_graph_w = max(graph_w, int(round(cols_per_hour * (n_all - 1))) + 1)
    win_start_col = start_idx * cols_per_hour
    win_end_col = end_idx * cols_per_hour
    return all_graph_w, win_start_col, win_end_col - win_start_col


def _place_week_labels(window, graph_w, runtime, show_wind=True, show_uv=True):
    """Place the wind and UV labels on the whole forecast, so they hold
    still while the chart scrolls, and decide whether they can share a row.

    Returns (wind, uv, shared, in_window): the two placed sets, whether
    they fit on one row, and a function that moves a placed set into the
    visible window.  With show_wind or show_uv off that kind has no labels."""
    window_winds = window["winds"] if show_wind else []
    window_wind_dirs = window["wind_dirs"]
    window_uv = window.get("uv", []) if show_uv else []
    canvas = _full_canvas(window, graph_w)
    if canvas:
        all_graph_w, win_start_col, win_span = canvas
        all_winds = window.get("all_winds", window_winds) if show_wind else []
        all_wind_dirs = window.get("all_wind_dirs", window_wind_dirs)
        all_uv = window.get("all_uv", window_uv) if show_uv else []
        placed_wind = (_place_wind_labels(all_winds, all_wind_dirs, max(1, len(all_winds) - 1),
                                          all_graph_w, runtime) if all_winds else [])
        placed_uv = (_place_uv_labels(all_uv, max(1, len(all_uv) - 1), all_graph_w, runtime)
                     if all_uv else [])

        def in_window(placed):
            return _labels_in_window(placed, win_start_col, win_span, graph_w)
    else:
        total_hours = window["total_hours"]
        placed_wind = _place_wind_labels(window_winds, window_wind_dirs, total_hours, graph_w,
                                         runtime)
        placed_uv = _place_uv_labels(window_uv, total_hours, graph_w, runtime)

        def in_window(placed):
            return placed

    # Wind and UV share one row when none of the week's labels would meet,
    # as rain and wind share a column in the daily table. The choice is
    # made on the whole forecast, not the window, so the chart keeps its
    # height while scrolling and a windy sunny afternoon never loses a
    # reading to save a line.
    shared = _labels_can_share(placed_wind, placed_uv)
    return placed_wind, placed_uv, shared, in_window


def _has_week_wind(window, runtime):
    return window.get("all_wind_max", 0) > _wind_threshold(runtime)


def _has_week_uv(window):
    return _uv_label_value(window.get("all_uv_max", 0)) >= UV_LABEL_MIN


def label_rows(window, graph_w, runtime):
    """How many rows the wind and UV labels take under the chart, as
    (wind, uv): the rows the wind reserves, and the rows UV adds beyond
    them.  UV adds none when its labels can share the wind's row, so
    leaving it off would save nothing."""
    has_wind = _has_week_wind(window, runtime)
    has_uv = _has_week_uv(window)
    if not has_uv:
        return int(has_wind), 0
    _wind, _uv, shared, _in_window = _place_week_labels(window, graph_w, runtime)
    return int(has_wind), int(not shared or not has_wind)


def render_hourly(data, width, n_braille_rows=2, n_precip_rows=0, now=None, runtime=None,
                  hover_col=None, offset_minutes=0, show_cloud=True, historical=None,
                  show_wind=True, show_uv=True):
    """Hourly forecast: braille temperature curve + precipitation graph.

    show_cloud, show_wind and show_uv: draw the cloud strip, the wind row
    and the UV labels when the data calls for them.  The dashboard turns
    them off in a window too short for their rows, UV first, then the
    wind, then the cloud strip.
    historical: the location's HistoricalAverages, which set the graph's
    scale under --temp-range climate or auto."""
    if runtime is None:
        runtime = current_runtime(WeatherRuntime)
    daily = data.get("daily", {})
    sun_events = _parse_sun_events(daily)
    if now is None:
        now = _local_now_for_data(data)

    graph_w = max(10, width)
    window = _prepare_hourly_window(data.get("hourly", {}), now, graph_w,
                                    offset_minutes=offset_minutes)
    if window is None:
        return []

    window_temps = window["temps"]
    window_precip = window["precip"]
    window_amount = window["precip_amount"]
    window_codes = window["codes"]
    window_dts = window["dts"]
    total_hours = window["total_hours"]
    chart_lo = min(window_temps)
    chart_hi = max(window_temps)
    # The curve is scaled to the whole forecast, so it holds still while
    # scrolling; --temp-range can widen that to the climate or the world.
    value_range = temperature_scale(runtime, historical, window.get("all_temp_range"),
                                     n_rows=n_braille_rows)

    midnight_cols, _noon_cols, midnight_day_names = _compute_time_markers(
        window_dts, total_hours, graph_w, runtime
    )

    # The current time, marked like a midnight divider but in its own
    # color: at launch it sits at the left edge, and it keeps saying
    # "you are here" once the chart has been scrolled (issue #49).
    now_col = None
    if window_dts:
        col = _column_of(now, window_dts, graph_w)
        if col is not None:
            now_col = int(col)
    sun_labels = _compute_sun_labels(window_dts, sun_events, total_hours, graph_w, runtime)
    col_daylight = _compute_daylight_columns(window_dts, sun_events, graph_w)
    col_temps = _interpolate_columns(window_temps, graph_w)

    # Full-data virtual canvas for stable label placement while scrolling.
    # Temperature extrema and wind labels are computed on this canvas, then
    # remapped into the visible window so they don't jump around.
    canvas = _full_canvas(window, graph_w)
    if canvas:
        all_graph_w, win_start_col, win_span = canvas
        all_temps = window.get("all_temps", window_temps)
        all_col_temps = _interpolate_columns(all_temps, all_graph_w)
        all_extrema = _find_temperature_extrema(all_col_temps, all_graph_w)
        extrema = []
        for x, temp, is_peak in all_extrema:
            vis_x = (x - win_start_col) / max(1, win_span) * (graph_w - 1)
            ix = int(round(vis_x))
            if 0 <= ix < graph_w:
                extrema.append((ix, temp, is_peak))
    else:
        extrema = _find_temperature_extrema(col_temps, graph_w)

    lines = [
        _render_today_line(
            width,
            chart_lo,
            chart_hi,
            midnight_day_names,
            sun_labels,
            runtime,
            window_dts=window_dts,
            now=now,
            offset_minutes=offset_minutes,
        )
    ]

    tick_line = _render_tick_labels(window_dts, total_hours, graph_w, runtime, hover_col=hover_col,
                                    now_col=now_col)
    if tick_line:
        lines.append(tick_line)

    braille_rows = build_braille_curve(window_temps, graph_w, n_braille_rows,
                                       value_range=value_range)
    overlays = _compute_extrema_overlays(extrema, col_temps, n_braille_rows, graph_w, runtime,
                                          value_range=value_range)
    _compute_axis_overlays(value_range, braille_rows, n_braille_rows, graph_w, overlays,
                           now_col=now_col)
    lines.extend(_render_braille_rows(braille_rows, col_daylight, midnight_cols, runtime, overlays,
                                       hover_col=hover_col, now_col=now_col))

    has_global_wind = show_wind and _has_week_wind(window, runtime)
    has_global_uv = show_uv and _has_week_uv(window)
    has_global_precip = window.get("all_precip_max", 0) > 0

    # Place wind and UV labels on the full dataset, then move the ones that
    # fall inside the window into it, so they hold still while scrolling.
    placed_wind, placed_uv, shared, in_window = _place_week_labels(
        window, graph_w, runtime, show_wind=show_wind, show_uv=show_uv)
    if shared:
        wind_line = _render_shared_row(in_window(placed_wind), in_window(placed_uv), graph_w,
                                       midnight_cols=midnight_cols, hover_col=hover_col,
                                       now_col=now_col)
        uv_line = None
    else:
        wind_line = _render_label_canvas(_labels_to_canvas(in_window(placed_wind), graph_w),
                                         graph_w, WIND_COLOR, midnight_cols=midnight_cols,
                                         hover_col=hover_col, now_col=now_col)
        uv_line = _render_label_canvas(_labels_to_canvas(in_window(placed_uv), graph_w),
                                       graph_w, UV_COLOR, midnight_cols=midnight_cols,
                                       hover_col=hover_col, now_col=now_col)

    # Always reserve rows for wind/UV/precip if they appear anywhere in the
    # full dataset, so the chart height stays stable while scrolling.  A
    # reserved row with nothing in it still carries the vertical time
    # lines, so they run unbroken down the whole section.
    indicators = _indicator_colors(graph_w, midnight_cols, hover_col, now_col)
    if wind_line:
        lines.append(wind_line)
    elif has_global_wind or (shared and has_global_uv):
        lines.append(_indicator_row(graph_w, indicators))
    if not shared:
        if uv_line:
            lines.append(uv_line)
        elif has_global_uv:
            lines.append(_indicator_row(graph_w, indicators))

    cloud_line = (_render_cloud_row(window.get("cloud", []), graph_w, indicator_cols=indicators,
                                    through_col=hover_col)
                  if show_cloud else None)
    if cloud_line:
        lines.append(cloud_line)

    precip_lines = _render_precip_rows(window_amount, window_precip, window_codes, graph_w,
                                       n_precip_rows, indicator_cols=indicators,
                                       full=_precip_bar_full(data, runtime),
                                       through_col=hover_col)
    if precip_lines:
        lines.extend(precip_lines)
    elif has_global_precip and n_precip_rows >= 1:
        lines.extend([_indicator_row(graph_w, indicators)] * n_precip_rows)
    return lines

_theme.track_imports(globals(), "linecast._weather_style")
