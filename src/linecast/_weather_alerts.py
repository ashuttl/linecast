"""Weather alert rendering."""

from datetime import datetime

from linecast import _theme
from linecast._graphics import bg, fg, visible_len, RESET, BOLD
from linecast._i18n import lang_of
from linecast._runtime import log_failure
from linecast._textwidth import truncate_display_width, wrap_display_width
from linecast._weather_i18n import DAY_NAMES, _s
from linecast._weather_style import (
    ALERT_AMBER,
    ALERT_AMBER_RGB,
    ALERT_BLUE,
    ALERT_BLUE_RGB,
    ALERT_RED,
    ALERT_RED_RGB,
    ALERT_YELLOW,
    ALERT_YELLOW_RGB,
    DIM_RGB,
    LINK_RGB,
    MODAL_BG_RGB,
    MODAL_BORDER_RGB,
    MUTED,
    TEXT_RGB,
    WIND_COLOR,
    _knockout_ink,
)


def _parse_alert_time(iso_str, runtime=None, tz_name=""):
    """Parse ISO time string to a short display string in local time."""
    if not iso_str:
        return ""
    try:
        dt = datetime.fromisoformat(iso_str)
        if tz_name and dt.tzinfo is not None:
            from zoneinfo import ZoneInfo
            dt = dt.astimezone(ZoneInfo(tz_name))
        use_24h = runtime.use_24h if runtime else False
        day_names = DAY_NAMES.get(lang_of(runtime), DAY_NAMES["en"])
        day = day_names[dt.weekday()]
        if use_24h:
            return f"{day} {dt.strftime('%H:%M')}"
        from linecast._framebuffer import fmt_hour_phrase
        return f"{day} {fmt_hour_phrase(dt.hour)}"
    except Exception as exc:
        log_failure("weather/alerts", "alert time", exc, fallback="time omitted")
        return ""


def _severity_color(severity):
    if severity in ("Extreme", "Severe"):
        return ALERT_RED
    if severity == "Moderate":
        return ALERT_AMBER
    if severity == "Minor":
        return ALERT_BLUE
    return ALERT_YELLOW


def _severity_rgb(severity):
    if severity in ("Extreme", "Severe"):
        return ALERT_RED_RGB
    if severity == "Moderate":
        return ALERT_AMBER_RGB
    if severity == "Minor":
        return ALERT_BLUE_RGB
    return ALERT_YELLOW_RGB


def _alert_pill(alert, max_width=None):
    """The severity-coloured badge for one alert, trimmed to fit if need be."""
    severity = alert.get("severity", "")
    r, g, b = _severity_rgb(severity)
    dark_fg = fg(*_knockout_ink((r, g, b)))
    bg_color = bg(r, g, b)
    event = alert.get("event", "Unknown")

    def _pill(label):
        return f"{bg_color}{dark_fg}{BOLD} \u26a0 {label} {RESET}"

    pill = _pill(event)
    if max_width is not None and visible_len(pill) > max_width:
        chrome = visible_len(pill) - visible_len(event)
        pill = _pill(truncate_display_width(event, max(1, max_width - chrome)))
    return pill


def _pack_pills(pills, width):
    """Lay badges out over as many lines as they need, breaking between them.

    ``pills`` is a list of (alert index, rendered badge).  Returns
    ``(lines, spans)``, where ``spans[i]`` lists the (first column, last
    column, alert index) of each badge on ``lines[i]``, zero-based, so a
    click can find the badge under the pointer.
    """
    lines, spans = [], []
    row, row_spans, col = [], [], 1  # 1 for the leading space

    def flush():
        lines.append(" " + " ".join(row))
        spans.append(row_spans)

    for index, pill in pills:
        pill_w = visible_len(pill)
        gap = 1 if row else 0
        if row and col + gap + pill_w > width:
            flush()
            row, row_spans, col, gap = [], [], 1, 0
        row.append(pill)
        row_spans.append((col + gap, col + gap + pill_w - 1, index))
        col += gap + pill_w
    if row:
        flush()
    return lines, spans


def _render_single_alert(alert, width, max_lines=999, runtime=None, tz_name=""):
    """Render one alert as a single compact line: pill + date range + truncated body."""
    effective = _parse_alert_time(alert.get("effective", ""), runtime, tz_name)
    expires = _parse_alert_time(alert.get("expires", ""), runtime, tz_name)
    timing = ""
    if effective and expires:
        timing = f"{effective} \u2013 {expires}"
    elif expires:
        until = _s("until", runtime) if runtime else "until"
        timing = f"{until} {expires}"

    pill = _alert_pill(alert, max_width=width - 1)

    # Build the single line: pill + timing + truncated description
    parts = [f" {pill}"]
    used = 1 + visible_len(pill)  # leading space + pill

    if timing:
        timing_str = f" {WIND_COLOR}{timing}{RESET}"
        if used + 1 + visible_len(timing_str) <= width:
            used += 1 + visible_len(timing_str)
            parts.append(timing_str)

    desc = alert.get("description", "").strip()
    if desc:
        flat = " ".join(desc.split())
        remaining = width - used - 2  # 2 for " " prefix and trailing space
        if remaining > 10:
            truncated = truncate_display_width(flat, remaining)
            parts.append(f" {MUTED}{truncated}{RESET}")

    return ["".join(parts)]


def render_alerts(alerts, width=80, remaining_rows=None, runtime=None, tz_name=""):
    """NWS/ECCC/JMA alert banners — compact format."""
    lines, _spans = render_alerts_mapped(alerts, width, remaining_rows, runtime, tz_name)
    return lines


def render_alerts_mapped(alerts, width=80, remaining_rows=None, runtime=None, tz_name=""):
    """Render the alert banners, with the columns each alert occupies.

    When several alerts share the same description, their pills are grouped
    onto one line, wrapping onto further lines when they run past the
    terminal's width, and the shared description follows underneath.

    Returns ``(lines, spans)``; ``spans[i]`` lists the (first column, last
    column, alert index) of each clickable region on ``lines[i]``.
    """
    if not alerts:
        return [], []

    # Group alerts by description text
    from collections import OrderedDict
    groups = OrderedDict()
    for index, alert in enumerate(alerts):
        desc = alert.get("description", "").strip()
        key = desc or id(alert)  # unique key for alerts without description
        groups.setdefault(key, []).append((index, alert))

    lines, spans = [], []
    for _key, group in groups.items():
        first_index = group[0][0]
        if len(group) == 1:
            # Single alert — render normally
            for line in _render_single_alert(group[0][1], width, runtime=runtime,
                                             tz_name=tz_name):
                lines.append(line)
                spans.append([(0, width - 1, first_index)])
        else:
            # Multiple alerts share a description — pills on one line or
            # more, shared description underneath
            pills = [(index, _alert_pill(alert, max_width=width - 1))
                     for index, alert in group]
            pill_lines, pill_spans = _pack_pills(pills, width)
            lines.extend(pill_lines)
            spans.extend(pill_spans)

            desc = group[0][1].get("description", "").strip()
            if desc:
                flat = " ".join(desc.split())
                remaining = width - 2  # leading space + margin
                if remaining > 10:
                    truncated = truncate_display_width(flat, remaining)
                    lines.append(f" {MUTED}{truncated}{RESET}")
                    spans.append([(0, width - 1, first_index)])

    return lines, spans


# ---------------------------------------------------------------------------
# Alert modal (full detail overlay for live mode click)
# ---------------------------------------------------------------------------

def _build_modal_content(alert, inner_w, runtime=None, tz_name=""):
    """Build the full list of content lines for the alert modal.

    Returns a list of (text, is_blank) tuples. Each text string already
    contains ANSI color codes and will be padded by the caller.
    """
    MBG = bg(*MODAL_BG_RGB)
    TFG = fg(*TEXT_RGB)
    severity = alert.get("severity", "")
    r, g, b = _severity_rgb(severity)
    dark_fg = fg(*_knockout_ink((r, g, b)))
    bg_color = bg(r, g, b)
    event = alert.get("event", "Unknown")

    lines = []

    # Title pill — pad remainder with modal bg
    pill = f"{bg_color}{dark_fg}{BOLD} \u26a0 {event} {RESET}"
    lines.append(pill)

    # Timing
    effective = _parse_alert_time(alert.get("effective", ""), runtime, tz_name)
    expires = _parse_alert_time(alert.get("expires", ""), runtime, tz_name)
    if effective and expires:
        lines.append(f"{MBG}{WIND_COLOR}{effective} \u2013 {expires}{RESET}")
    elif expires:
        until = _s("until", runtime) if runtime else "until"
        lines.append(f"{MBG}{WIND_COLOR}{until} {expires}{RESET}")

    lines.append("")  # blank line

    # Headline (if different from event name)
    headline = alert.get("headline", "")
    if headline and headline != event:
        for wrapped in wrap_display_width(headline, inner_w):
            lines.append(f"{MBG}{TFG}{BOLD}{wrapped}{RESET}")
        lines.append("")

    # Description — preserve paragraph breaks from source
    desc = alert.get("description", "").strip()
    if desc and desc != headline:
        # Split on double newlines for paragraphs
        paragraphs = desc.split("\n\n")
        for pi, para in enumerate(paragraphs):
            if pi > 0:
                lines.append("")  # paragraph break
            # Collapse whitespace within each paragraph, then wrap
            flat = " ".join(para.split())
            for wrapped in wrap_display_width(flat, inner_w):
                lines.append(f"{MBG}{TFG}{wrapped}{RESET}")

    # URL
    url = alert.get("url", "")
    if url:
        lines.append("")
        link_color = fg(*LINK_RGB)
        display_url = url if visible_len(url) <= inner_w else truncate_display_width(url, inner_w)
        osc_link = f"\033]8;;{url}\033\\{link_color}{MBG}{display_url}\033]8;;\033\\{RESET}"
        lines.append(osc_link)

    return lines


def build_alert_modal(alert, cols, rows, runtime=None, scroll=0, tz_name=""):
    """Build a centered modal overlay showing the full alert detail.

    Returns cursor-positioned ANSI escape sequences to draw the modal.
    scroll: number of content lines scrolled down (0 = top).
    """
    MBG = bg(*MODAL_BG_RGB)
    BORDER = fg(*MODAL_BORDER_RGB)

    # Modal dimensions
    modal_w = min(cols - 4, 80)
    inner_w = modal_w - 4  # 2 border + 2 padding
    modal_max_h = rows - 4

    all_content = _build_modal_content(alert, inner_w, runtime=runtime, tz_name=tz_name)
    total_content = len(all_content)

    # Visible content area height (excluding top/bottom border)
    visible_h = min(total_content, modal_max_h - 2)

    # Clamp scroll
    max_scroll = max(0, total_content - visible_h)
    scroll = max(0, min(scroll, max_scroll))

    # Slice visible window
    visible_lines = all_content[scroll:scroll + visible_h]

    # Scroll indicator
    can_scroll_up = scroll > 0
    can_scroll_down = scroll < max_scroll

    total_h = visible_h + 2  # content + top/bottom borders

    # Center the modal
    top_row = max(1, (rows - total_h) // 2 + 1)
    left_col = max(1, (cols - modal_w) // 2 + 1)

    result = ""
    horiz = "\u2500" * (modal_w - 2)

    # Top border (with scroll-up indicator)
    bar_ch = "\u2500"
    if can_scroll_up:
        arrow = f" {fg(*DIM_RGB)}\u25b2 "
        arrow_len = 3
        left_bar = (modal_w - 2 - arrow_len) // 2
        right_bar = modal_w - 2 - arrow_len - left_bar
        top_line = f"{BORDER}\u256d{bar_ch * left_bar}{arrow}{BORDER}{bar_ch * right_bar}\u256e"
    else:
        top_line = f"{BORDER}\u256d{horiz}\u256e"
    result += f"\033[{top_row};{left_col}H{MBG}{top_line}{RESET}"

    # Content lines — every cell gets the modal bg
    for i, line in enumerate(visible_lines):
        r_pos = top_row + 1 + i
        line_vis = visible_len(line)
        pad = max(0, inner_w - line_vis)
        result += (f"\033[{r_pos};{left_col}H{MBG}{BORDER}\u2502{RESET}{MBG} {line}"
                   f"{MBG}{' ' * pad} {BORDER}\u2502{RESET}")

    # Bottom border with hints
    bot_row = top_row + visible_h + 1
    url = alert.get("url", "")
    parts = [_s("q_to_close", runtime)]
    if url:
        parts.append(_s("o_to_open", runtime))
    if can_scroll_down:
        parts.append("\u25bc " + _s("scroll", runtime))
    sep = " \u00b7 "
    hint = f" {sep.join(parts)} "
    hint_len = visible_len(hint)
    if hint_len + 2 < modal_w - 2:
        left_bar = (modal_w - 2 - hint_len) // 2
        right_bar = modal_w - 2 - hint_len - left_bar
        bot_line = (f"{BORDER}\u2570{bar_ch * left_bar}{MUTED}{hint}"
                    f"{BORDER}{bar_ch * right_bar}\u256f")
    else:
        bot_line = f"{BORDER}\u2570{horiz}\u256f"
    result += f"\033[{bot_row};{left_col}H{MBG}{bot_line}{RESET}"

    return result, max_scroll

_theme.track_imports(globals(), "linecast._weather_style")
