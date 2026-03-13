"""Shared rendering helpers for tides chart layout."""

import math
from datetime import datetime, timedelta, timezone

from linecast._graphics import RESET, bg, fg, fmt_hour, fmt_time_dt, visible_len
from linecast._theme import (
    best_contrast,
    darken,
    ensure_contrast,
    is_light_theme,
    lerp_rgb,
    neutral_tone,
    surface_bg,
    theme_ansi,
    theme_bg,
    theme_fg,
)
from linecast._tides_i18n import FULL_DAY_NAMES
from linecast.sunshine import daylight_factor as solar_daylight_factor, moon_phase

DIM_RGB = ensure_contrast(neutral_tone(0.32), theme_bg, minimum=2.0)
MUTED_RGB = ensure_contrast(neutral_tone(0.48), theme_bg, minimum=2.5)
MOON_RISE_RGB = ensure_contrast(best_contrast((theme_ansi[5], theme_ansi[13]), minimum=2.0), theme_bg, minimum=2.0)
MOON_SET_RGB = ensure_contrast(
    lerp_rgb(best_contrast((theme_ansi[4], theme_ansi[12]), minimum=2.0), theme_ansi[5], 0.35),
    theme_bg,
    minimum=2.0,
)
TIP_BG_RGB = darken(surface_bg(0.10), 0.45 if not is_light_theme() else 0.10)
TIP_TEXT_RGB = ensure_contrast(theme_fg, TIP_BG_RGB, minimum=4.5)

DIM = fg(*DIM_RGB)


def interp_height(target_dt, predictions):
    """Linearly interpolate tide height at a given datetime."""
    if not predictions:
        return 0.0
    if target_dt <= predictions[0][0]:
        return predictions[0][1]
    if target_dt >= predictions[-1][0]:
        return predictions[-1][1]
    for i in range(len(predictions) - 1):
        if predictions[i][0] <= target_dt <= predictions[i + 1][0]:
            span = (predictions[i + 1][0] - predictions[i][0]).total_seconds()
            if span == 0:
                return predictions[i][1]
            frac = (target_dt - predictions[i][0]).total_seconds() / span
            return predictions[i][1] + (predictions[i + 1][1] - predictions[i][1]) * frac
    return predictions[-1][1]


def prepare_tide_window(predictions, hilo, start_dt, hours_shown=24):
    """Slice prediction data to a visible window starting at start_dt."""
    end_dt = start_dt + timedelta(hours=hours_shown)
    margin = timedelta(minutes=10)
    win_preds = [(dt, h) for dt, h in predictions if start_dt - margin <= dt <= end_dt + margin]
    win_hilo = [(dt, h, t) for dt, h, t in hilo if start_dt <= dt <= end_dt]
    return {
        "predictions": win_preds,
        "hilo": win_hilo,
        "start": start_dt,
        "end": end_dt,
        "total_hours": hours_shown,
    }


def _solar_daylight_at(hour, doy, lat, lng, tz_offset_h):
    """Compute daylight factor (0.0-1.0) at a local clock hour on a given day."""
    return solar_daylight_factor(hour, doy, lat, lng, tz_offset_h)


def compute_daylight_window(graph_w, window_start, total_hours, station_meta):
    """Compute per-column daylight factor for a datetime window."""
    if not station_meta:
        return [1.0] * graph_w

    try:
        lat = float(station_meta["lat"])
        tz_offset_h = float(station_meta["timezonecorr"])
    except (KeyError, TypeError, ValueError):
        return [1.0] * graph_w

    try:
        lng = float(station_meta["lng"])
    except (KeyError, TypeError, ValueError):
        lng = None

    col_daylight = []
    for x in range(graph_w):
        frac = (x + 0.5) / graph_w
        col_dt = window_start + timedelta(hours=frac * total_hours)
        doy = col_dt.timetuple().tm_yday
        hour = col_dt.hour + col_dt.minute / 60
        col_daylight.append(_solar_daylight_at(hour, doy, lat, lng, tz_offset_h))
    return col_daylight


def compute_time_markers(window_start, total_hours, graph_w, runtime):
    """Compute midnight column positions and day labels for the window."""
    lang = runtime.lang if runtime else "en"
    midnight_cols = set()
    midnight_day_names = {}

    first_midnight = window_start.replace(hour=0, minute=0, second=0, microsecond=0)
    if first_midnight <= window_start:
        first_midnight += timedelta(days=1)

    dt = first_midnight
    window_secs = total_hours * 3600
    while dt < window_start + timedelta(hours=total_hours):
        offset_secs = (dt - window_start).total_seconds()
        x = int(offset_secs / window_secs * (graph_w - 1))
        if 0 < x < graph_w - 1:
            midnight_cols.add(x)
            day_names = FULL_DAY_NAMES.get(lang, FULL_DAY_NAMES["en"])
            midnight_day_names[x] = day_names[dt.weekday()]
        dt += timedelta(days=1)

    return midnight_cols, midnight_day_names


def _julian_day(dt_utc):
    """Convert a UTC datetime into Julian Day.

    Uses the Unix epoch offset: JD 2440587.5 = 1970-01-01T00:00:00Z.
    Reference: Meeus, "Astronomical Algorithms" (2nd ed.), ch. 7.
    """
    if dt_utc.tzinfo is None:
        dt_utc = dt_utc.replace(tzinfo=timezone.utc)
    else:
        dt_utc = dt_utc.astimezone(timezone.utc)
    return dt_utc.timestamp() / 86400.0 + 2440587.5


def _norm_deg(angle):
    """Normalize an angle to [0, 360) degrees."""
    return angle % 360.0


def _moon_ra_dec(dt_utc):
    """Approximate geocentric Moon right ascension/declination in degrees.

    Low-precision lunar ephemeris adapted from Paul Schlyter's algorithm,
    which itself is a simplification of the method in Meeus, "Astronomical
    Algorithms" (2nd ed.), ch. 47. Accuracy is ~0.5–1° in position, which
    is sufficient for moonrise/moonset timing to within a few minutes.

    Source: https://stjarnhimlen.se/comp/ppcomp.html#15
    Orbital elements epoch: 2000-Jan-0.0 (JD 2451543.5).

    Element key:
      N  — longitude of the ascending node (deg)
      i  — orbital inclination (deg)
      w  — argument of perigee (deg)
      a  — semi-major axis (Earth radii)
      e  — orbital eccentricity
      M  — mean anomaly (deg)
    """
    jd = _julian_day(dt_utc)
    # Days since the orbital elements epoch (2000-Jan-0.0 = JD 2451543.5)
    d = jd - 2451543.5

    # Lunar orbital elements (Schlyter, epoch 2000-Jan-0.0)
    n = math.radians(_norm_deg(125.1228 - 0.0529538083 * d))      # ascending node
    inc = math.radians(5.1454)                                      # inclination
    w = math.radians(_norm_deg(318.0634 + 0.1643573223 * d))       # argument of perigee
    a = 60.2666                                                     # semi-major axis (Earth radii)
    e = 0.0549                                                      # eccentricity
    m = math.radians(_norm_deg(115.3654 + 13.0649929509 * d))      # mean anomaly

    e_anom = m + e * math.sin(m) * (1.0 + e * math.cos(m))
    x_v = a * (math.cos(e_anom) - e)
    y_v = a * (math.sqrt(1.0 - e * e) * math.sin(e_anom))
    true_anom = math.atan2(y_v, x_v)
    radius = math.hypot(x_v, y_v)

    x_h = radius * (
        math.cos(n) * math.cos(true_anom + w)
        - math.sin(n) * math.sin(true_anom + w) * math.cos(inc)
    )
    y_h = radius * (
        math.sin(n) * math.cos(true_anom + w)
        + math.cos(n) * math.sin(true_anom + w) * math.cos(inc)
    )
    z_h = radius * (math.sin(true_anom + w) * math.sin(inc))

    # Mean obliquity of the ecliptic (Meeus, eq. 22.2, simplified)
    obliq = math.radians(23.4393 - 3.563e-7 * d)
    x_eq = x_h
    y_eq = y_h * math.cos(obliq) - z_h * math.sin(obliq)
    z_eq = y_h * math.sin(obliq) + z_h * math.cos(obliq)

    ra = _norm_deg(math.degrees(math.atan2(y_eq, x_eq)))
    dec = math.degrees(math.atan2(z_eq, math.hypot(x_eq, y_eq)))
    return ra, dec


def _gmst_deg(dt_utc):
    """Greenwich mean sidereal time in degrees.

    Uses the IAU 1982 expression for GMST as a function of Julian Date.
    Reference: Meeus, "Astronomical Algorithms" (2nd ed.), eq. 12.4.
    J2000.0 epoch = JD 2451545.0; Julian century = 36525 days.
    """
    jd = _julian_day(dt_utc)
    t = (jd - 2451545.0) / 36525.0
    gmst = (
        280.46061837
        + 360.98564736629 * (jd - 2451545.0)
        + 0.000387933 * t * t
        - (t * t * t) / 38710000.0
    )
    return _norm_deg(gmst)


def _moon_altitude_deg(dt_utc, lat_deg, lng_deg):
    """Approximate Moon altitude for a UTC datetime and observer lat/lng.

    Standard topocentric altitude formula (Meeus, ch. 13):
      sin(alt) = sin(lat)*sin(dec) + cos(lat)*cos(dec)*cos(ha)
    Parallax and refraction are not corrected here; the threshold_deg
    parameter in _moon_events_for_local_date compensates for this.
    """
    ra_deg, dec_deg = _moon_ra_dec(dt_utc)
    lst_deg = _norm_deg(_gmst_deg(dt_utc) + lng_deg)
    hour_angle = math.radians((lst_deg - ra_deg + 540.0) % 360.0 - 180.0)

    lat = math.radians(lat_deg)
    dec = math.radians(dec_deg)
    sin_alt = (
        math.sin(lat) * math.sin(dec)
        + math.cos(lat) * math.cos(dec) * math.cos(hour_angle)
    )
    sin_alt = max(-1.0, min(1.0, sin_alt))
    return math.degrees(math.asin(sin_alt))


def _refine_moon_crossing_utc(t0_utc, t1_utc, lat_deg, lng_deg, threshold_deg):
    """Refine a moonrise/moonset crossing between two UTC datetimes.

    Uses bisection (16 iterations → ~30 second precision) to locate the
    zero-crossing of (altitude - threshold) between the bracketing times.
    """
    f0 = _moon_altitude_deg(t0_utc, lat_deg, lng_deg) - threshold_deg
    f1 = _moon_altitude_deg(t1_utc, lat_deg, lng_deg) - threshold_deg
    if f0 == 0:
        return t0_utc
    if f1 == 0:
        return t1_utc

    lo, hi = t0_utc, t1_utc
    vlo = f0
    for _ in range(16):
        mid = lo + timedelta(seconds=(hi - lo).total_seconds() / 2.0)
        vmid = _moon_altitude_deg(mid, lat_deg, lng_deg) - threshold_deg
        if vlo == 0:
            return lo
        if vlo * vmid <= 0:
            hi = mid
        else:
            lo, vlo = mid, vmid
        if abs((hi - lo).total_seconds()) < 30:
            break
    return lo + timedelta(seconds=(hi - lo).total_seconds() / 2.0)


def _moon_events_for_local_date(local_date, lat_deg, lng_deg, tzinfo, threshold_deg=0.125):
    """Return (moonrise_local, moonset_local) for one local calendar date.

    The threshold_deg of 0.125° approximates the combined effect of
    atmospheric refraction (~0.57° at horizon) and lunar horizontal
    parallax (~0.95°), which partially cancel. The net geometric rise
    happens when the Moon's center is about 0.125° above the true
    horizon. (See Meeus, ch. 15, for the full derivation.)

    Events are found by stepping in 10-minute increments, detecting sign
    changes in (altitude - threshold), then refining via bisection.
    """
    start_local = datetime(local_date.year, local_date.month, local_date.day, tzinfo=tzinfo)
    end_local = start_local + timedelta(days=1)
    start_utc = start_local.astimezone(timezone.utc)
    end_utc = end_local.astimezone(timezone.utc)

    rise = None
    sset = None
    step = timedelta(minutes=10)
    t_prev = start_utc
    v_prev = _moon_altitude_deg(t_prev, lat_deg, lng_deg) - threshold_deg
    t_cur = t_prev + step

    while t_cur <= end_utc and (rise is None or sset is None):
        v_cur = _moon_altitude_deg(t_cur, lat_deg, lng_deg) - threshold_deg
        crossing = (
            v_prev == 0
            or v_cur == 0
            or (v_prev < 0 <= v_cur)
            or (v_prev > 0 >= v_cur)
        )
        if crossing:
            cross_utc = _refine_moon_crossing_utc(
                t_prev, t_cur, lat_deg, lng_deg, threshold_deg
            )
            before = _moon_altitude_deg(
                cross_utc - timedelta(minutes=1), lat_deg, lng_deg
            ) - threshold_deg
            after = _moon_altitude_deg(
                cross_utc + timedelta(minutes=1), lat_deg, lng_deg
            ) - threshold_deg
            is_rise = after > before
            cross_local = cross_utc.astimezone(tzinfo)
            if start_local <= cross_local < end_local:
                if is_rise and rise is None:
                    rise = cross_local
                elif not is_rise and sset is None:
                    sset = cross_local

        t_prev, v_prev = t_cur, v_cur
        t_cur += step

    return rise, sset


def compute_moon_labels(window_start, total_hours, graph_w, station_meta, runtime):
    """Compute moonrise/moonset labels mapped to graph columns."""
    if total_hours <= 0 or graph_w < 3 or not station_meta:
        return {}

    try:
        lat = float(station_meta["lat"])
        lng = float(station_meta["lng"])
    except (KeyError, TypeError, ValueError):
        return {}

    tzinfo = window_start.tzinfo
    if tzinfo is None:
        try:
            tzinfo = timezone(timedelta(hours=float(station_meta.get("timezonecorr"))))
        except (TypeError, ValueError):
            return {}
        local_start = window_start.replace(tzinfo=tzinfo)
    else:
        local_start = window_start.astimezone(tzinfo)

    local_end = local_start + timedelta(hours=total_hours)
    labels = {}
    use_24h = bool(getattr(runtime, "use_24h", False))

    day = local_start.date() - timedelta(days=1)
    last_day = local_end.date() + timedelta(days=1)
    while day <= last_day:
        rise_dt, set_dt = _moon_events_for_local_date(day, lat, lng, tzinfo)
        for event_dt, is_rise in ((rise_dt, True), (set_dt, False)):
            if event_dt is None:
                continue
            off_h = (event_dt - local_start).total_seconds() / 3600.0
            if 0 < off_h < total_hours:
                col = int(off_h / total_hours * (graph_w - 1))
                if 0 < col < graph_w - 1:
                    _idx, _name, phase_icon = moon_phase(
                        event_dt.astimezone(timezone.utc),
                        runtime,
                    )
                    arrow = "\u2191" if is_rise else "\u2193"
                    labels[col] = (
                        f"{phase_icon}{arrow}{fmt_time_dt(event_dt, use_24h=use_24h)}",
                        is_rise,
                    )
        day += timedelta(days=1)

    return labels


def render_tide_ticks(window_start, total_hours, graph_w, runtime, now_col=None, hover_col=None):
    """Render time axis labels under the chart."""
    use_24h = runtime.use_24h
    if graph_w < 40:
        interval = 6
    elif graph_w < 80:
        interval = 4
    elif graph_w < 140:
        interval = 3
    else:
        interval = 2

    window_secs = total_hours * 3600
    label_items = []
    if window_secs > 0:
        interval_secs = interval * 3600
        elapsed_secs = (
            window_start.hour * 3600
            + window_start.minute * 60
            + window_start.second
            + window_start.microsecond / 1_000_000
        )
        first_offset_secs = (interval_secs - (elapsed_secs % interval_secs)) % interval_secs
        tick_dt = window_start + timedelta(seconds=first_offset_secs)
        window_end = window_start + timedelta(hours=total_hours)

        while tick_dt <= window_end:
            offset_secs = (tick_dt - window_start).total_seconds()
            x = int(offset_secs / window_secs * (graph_w - 1))
            if 0 <= x < graph_w:
                label_items.append(
                    (x, fmt_hour(tick_dt.hour, use_24h), tick_dt.hour == 0 and tick_dt.minute == 0)
                )
            tick_dt += timedelta(seconds=interval_secs)

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

    return f" {DIM}{''.join(canvas)}{RESET}"


def render_day_label_line(midnight_day_names, graph_w, moon_labels=None):
    """Render day and moon-event labels on their own row."""
    if moon_labels is None:
        moon_labels = {}

    muted = fg(*MUTED_RGB)
    rise_color = MOON_RISE_RGB
    set_color = MOON_SET_RGB
    canvas = [" "] * graph_w
    canvas_colors = [None] * graph_w

    def _draw_label(start, text, color=None, allow_overlap=False):
        width = visible_len(text)
        if start < 0 or start + width > graph_w:
            return False
        if not allow_overlap and any(canvas[start + i] != " " for i in range(width)):
            return False
        x = start
        for ch in text:
            if x >= graph_w:
                break
            canvas[x] = ch
            canvas_colors[x] = color
            ch_w = visible_len(ch)
            for k in range(1, ch_w):
                if x + k < graph_w:
                    canvas[x + k] = ""
                    canvas_colors[x + k] = color
            x += ch_w
        return True

    def _find_open_slot(
        preferred_start,
        text,
        prefer_forward=True,
        pad_mask=None,
        min_pad=0,
    ):
        """Find an open slot for text, preferring movement to the right."""
        width = visible_len(text)
        if width <= 0 or width > graph_w:
            return None

        lo = 0
        hi = graph_w - width
        start = max(lo, min(hi, preferred_start))

        def _open(slot):
            if not all(canvas[slot + i] == " " for i in range(width)):
                return False
            if pad_mask is None or min_pad <= 0:
                return True

            left = max(0, slot - min_pad)
            right = min(graph_w - 1, slot + width - 1 + min_pad)
            for i in range(left, right + 1):
                if slot <= i < slot + width:
                    continue
                if pad_mask[i]:
                    return False
            return True

        if _open(start):
            return start

        if prefer_forward:
            for slot in range(start + 1, hi + 1):
                if _open(slot):
                    return slot
            for slot in range(start - 1, lo - 1, -1):
                if _open(slot):
                    return slot
        else:
            for slot in range(start - 1, lo - 1, -1):
                if _open(slot):
                    return slot
            for slot in range(start + 1, hi + 1):
                if _open(slot):
                    return slot
        return None

    for col, day_name in sorted(midnight_day_names.items()):
        _draw_label(col + 1, day_name, color=None, allow_overlap=True)

    day_mask = [cell != " " for cell in canvas]

    for col, (label, is_rise) in sorted(moon_labels.items()):
        color = rise_color if is_rise else set_color
        preferred = max(0, col + 1)
        slot = _find_open_slot(
            preferred,
            label,
            prefer_forward=True,
            pad_mask=day_mask,
            min_pad=1,
        )
        if slot is not None:
            _draw_label(slot, label, color=color, allow_overlap=False)

    line = muted
    current_color = None
    for i in range(graph_w):
        color = canvas_colors[i]
        if color != current_color:
            line += muted if color is None else fg(*color)
            current_color = color
        line += canvas[i]
    if current_color is not None:
        line += muted
    return f" {line}{RESET}"


def build_now_tooltip(now_col, now_info, chart_start, cols, graph_w):
    """Build cursor-positioned tooltip at the top of the now indicator line."""
    if now_col is None or now_info is None:
        return ""

    time_str, h_display, unit = now_info

    tip_bg = bg(*TIP_BG_RGB)
    tip_fg = fg(*TIP_TEXT_RGB)

    tip_lines = [
        f"{tip_bg}{tip_fg} {time_str} ",
        f"{tip_bg}{tip_fg} {h_display:.1f}{unit} ",
    ]

    max_w = max(visible_len(line) for line in tip_lines)
    padded = []
    for line in tip_lines:
        pad = max_w - visible_len(line)
        padded.append(f"{line}{' ' * pad}{RESET}")

    # Position: just to the right of the now column, at the top of the chart
    # +2 for the 1-char left margin and 1-based terminal coords
    snap_col = now_col + 2 + 1
    tooltip_col = snap_col
    tooltip_row = chart_start + 1  # 0-based line index -> 1-based terminal row
    tooltip_w = max_w
    if tooltip_col + tooltip_w - 1 > cols:
        tooltip_col = max(1, cols - tooltip_w + 1)

    result = ""
    for i, line in enumerate(padded):
        result += f"\033[{tooltip_row + i};{tooltip_col}H{line}"
    return result


def build_tide_hover_tooltip(window, graph_col, mouse_row, chart_start, chart_end, cols, rows, graph_w, runtime):
    """Build cursor-positioned tooltip overlay for mouse hover on the chart."""
    line_idx = mouse_row - 1
    if not (chart_start <= line_idx < chart_end):
        return ""
    if graph_col < 0 or graph_col >= graph_w:
        return ""

    predictions = window["predictions"]
    if not predictions:
        return ""

    total_hours = window["total_hours"]
    start_dt = window["start"]

    t_frac = graph_col / max(1, graph_w - 1)
    target_dt = start_dt + timedelta(hours=t_frac * total_hours)
    height = interp_height(target_dt, predictions)

    tip_bg = bg(*TIP_BG_RGB)
    tip_fg = fg(*TIP_TEXT_RGB)

    time_str = fmt_time_dt(target_dt, use_24h=runtime.use_24h)
    h_display = runtime.convert_height(height)

    tip_lines = [
        f"{tip_bg}{tip_fg} {time_str} ",
        f"{tip_bg}{tip_fg} {h_display:.1f}{runtime.height_unit} ",
    ]

    max_w = max(visible_len(line) for line in tip_lines)
    padded = []
    for line in tip_lines:
        pad = max_w - visible_len(line)
        padded.append(f"{line}{' ' * pad}{RESET}")

    snap_col = graph_col + 2
    tooltip_col = snap_col
    tooltip_row = mouse_row
    tooltip_w = max_w
    tooltip_h = len(padded)
    if tooltip_col + tooltip_w - 1 > cols:
        tooltip_col = max(1, cols - tooltip_w + 1)
    if tooltip_row + tooltip_h - 1 > rows:
        tooltip_row = max(1, rows - tooltip_h + 1)

    result = ""
    for i, line in enumerate(padded):
        result += f"\033[{tooltip_row + i};{tooltip_col}H{line}"
    return result
