"""tides --oneline: the next two high and low tides in one line."""

from linecast._i18n import fmt_decimal
from linecast._timefmt import fmt_time_dt


def tides_oneline(station_name, hilo_data, now_local, runtime):
    """Return a compact tide summary line.

    Example: ``Casco Bay ▲High 2:14p 9.2ft ▼Low 8:47p 1.1ft``

    *hilo_data* is a list of ``(datetime, height_ft, type_str)`` tuples where
    ``type_str`` is ``"H"`` or ``"L"``.
    """
    from linecast.terminal.color import fg, RESET
    from linecast.terminal.theme import theme_fg, ensure_contrast, theme_bg
    from linecast.tides.i18n import _ts

    text_rgb = ensure_contrast(theme_fg, theme_bg, minimum=4.5)
    TEXT = fg(*text_rgb)

    parts = []

    if station_name:
        short = station_name.split(",")[0].strip()
        parts.append(f"{TEXT}{short}")

    if not hilo_data:
        parts.append(f"{TEXT}{_ts('no_data', runtime)}")
        return " ".join(parts) + RESET

    # Find the next two tide events (from now onward), falling back to the
    # last two if we're past all events.
    upcoming = [(dt, h, t) for dt, h, t in hilo_data if dt >= now_local]
    if len(upcoming) >= 2:
        events = upcoming[:2]
    elif len(upcoming) == 1:
        # One upcoming + the most recent past event
        past = [(dt, h, t) for dt, h, t in hilo_data if dt < now_local]
        if past:
            events = [past[-1], upcoming[0]]
        else:
            events = upcoming[:1]
    else:
        # All past — show the last two
        events = hilo_data[-2:]

    use_24h = runtime.use_24h

    for dt, height_ft, typ in events:
        h_display = runtime.convert_height(height_ft)
        is_high = typ == "H"
        arrow = "\u25b2" if is_high else "\u25bc"
        label = _ts("high" if is_high else "low", runtime)
        time_str = fmt_time_dt(dt, use_24h=use_24h)
        height = fmt_decimal(h_display, 1, runtime)
        parts.append(f"{TEXT}{arrow}{label} {time_str} {height}{runtime.height_unit}")

    return " ".join(parts) + RESET
