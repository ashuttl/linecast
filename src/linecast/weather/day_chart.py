"""The daily temperature bar's midnight-to-midnight hover graph."""

from datetime import datetime, timedelta

from linecast._timefmt import fmt_hour
from linecast.terminal.braille import DOT_BITS, line_dots
from linecast.terminal.color import bg, fg
from linecast.terminal.textwidth import pad, visible_len
from linecast.weather.forecast import _at
from linecast.weather import style


def temperature_chip(hourly, date, low, high, cols, rows, runtime):
    """Styled curve rows and an hour axis, below the chip's day heading.

    Positions follow local clock times, including the next midnight when
    available. Missing hours stay blank; a short forecast is never stretched
    to fill the day. Return no graph when data or space is insufficient.
    """
    try:
        start = datetime.fromisoformat(date)
    except (TypeError, ValueError):
        return []
    end = start + timedelta(days=1)
    points = []
    temps = hourly.get("temperature_2m") or []
    for i, stamp in enumerate(hourly.get("time") or []):
        value = _at(temps, i)
        if value is None:
            continue
        try:
            dt = datetime.fromisoformat(stamp).replace(tzinfo=None)
        except (TypeError, ValueError):
            continue
        if start <= dt <= end:
            points.append(((dt - start).total_seconds() / 3600, value))
    if len(points) < 2:
        return []

    bounds = [value for _, value in points] + [v for v in (low, high) if v is not None]
    lo, hi = min(bounds), max(bounds)
    gutter = max(len(f"{round(v)}°") for v in (lo, hi)) + 1
    # A column for the shadow, one of padding at each side, and the scale.
    width = min(25, cols - gutter - 3)
    height = min(3, rows - 3)  # the heading, hour axis, and shadow
    if width < 13 or height < 2:
        return []

    dot_w, dot_h = width * 2, height * 4
    masks = [[0] * width for _ in range(height)]

    def position(hour, value):
        x = round(hour / 24 * (dot_w - 1))
        y = round((hi - value) / (hi - lo) * (dot_h - 1)) if hi != lo else dot_h // 2
        return x, y

    previous = None
    for hour, value in points:
        x, y = position(hour, value)
        dots = [(x, y)]
        if previous is not None:
            prev_hour, prev_value = previous
            if 0 <= hour - prev_hour <= 1:
                dots = line_dots(*position(prev_hour, prev_value), x, y)
        for dx, dy in dots:
            masks[dy // 4][dx // 2] |= DOT_BITS[dx % 2][dy % 4]
        previous = hour, value

    surface = bg(*style.TOOLTIP_BG_RGB)
    dim = fg(*style.TOOLTIP_DIM_RGB)
    labels = {0: hi, height - 1: lo} if hi != lo else {height // 2: lo}
    lines = []
    for row, masks_row in enumerate(masks):
        label = style._colored_temp(labels[row], runtime, "°") if row in labels else ""
        curve = []
        for mask in masks_row:
            if not mask:
                curve.append(" ")
                continue
            ys = [row * 4 + y for x in range(2) for y in range(4) if mask & DOT_BITS[x][y]]
            value = hi - sum(ys) / len(ys) / (dot_h - 1) * (hi - lo)
            curve.append(f"{fg(*style._temp_color(value, runtime))}{chr(0x2800 + mask)}")
        lines.append(f"{surface} {pad(label, gutter - 1, '>')} {''.join(curve)} ")

    axis = [" "] * width
    hours = (0, 6, 12, 18, 24) if width >= 21 else (0, 12, 24)
    for hour in hours:
        label = fmt_hour(hour, runtime.use_24h)
        x = round(hour / 24 * (width - 1)) - visible_len(label) // 2
        x = max(0, min(width - visible_len(label), x))
        axis[x:x + len(label)] = label
    lines.append(f"{surface}{dim} {' ' * gutter}{''.join(axis)} ")
    return lines
