"""Weather alert rendering."""

import textwrap
from datetime import datetime

from linecast._graphics import bg, fg, visible_len, RESET, BOLD
from linecast._weather_i18n import DAY_NAMES, _s
from linecast._weather_style import ALERT_AMBER, ALERT_RED, ALERT_YELLOW, MUTED, WIND_COLOR


def _parse_alert_time(iso_str, runtime=None):
    """Parse ISO time string to a short display string."""
    try:
        dt = datetime.fromisoformat(iso_str)
        use_24h = runtime.use_24h if runtime else False
        lang = getattr(runtime, "lang", "en") if runtime else "en"
        day_names = DAY_NAMES.get(lang, DAY_NAMES["en"])
        day = day_names[dt.weekday()]
        if use_24h:
            return f"{day} {dt.strftime('%H:%M')}"
        return f"{day} {dt.strftime('%-I%p').replace('AM', 'am').replace('PM', 'pm')}"
    except Exception:
        return ""


def _severity_color(severity):
    if severity in ("Extreme", "Severe"):
        return ALERT_RED
    if severity == "Moderate":
        return ALERT_AMBER
    return ALERT_YELLOW


def _severity_rgb(severity):
    if severity in ("Extreme", "Severe"):
        return (220, 60, 50)
    if severity == "Moderate":
        return (220, 170, 50)
    return (200, 200, 80)


def _render_single_alert(alert, width, max_lines=999, runtime=None):
    """Render one alert as a single compact line: pill + date range + truncated body."""
    dark_fg = fg(20, 20, 25)
    severity = alert.get("severity", "")
    r, g, b = _severity_rgb(severity)
    bg_color = bg(r, g, b)
    event = alert.get("event", "Unknown")
    effective = _parse_alert_time(alert.get("effective", ""), runtime)
    expires = _parse_alert_time(alert.get("expires", ""), runtime)
    timing = ""
    if effective and expires:
        timing = f"{effective} \u2013 {expires}"
    elif expires:
        until = _s("until", runtime) if runtime else "until"
        timing = f"{until} {expires}"

    pill = f"{bg_color}{dark_fg}{BOLD} \u26a0 {event} {RESET}"
    pill_vis = visible_len(pill)

    # Build the single line: pill + timing + truncated description
    parts = [f" {pill}"]
    used = 1 + pill_vis  # leading space + pill

    if timing:
        timing_str = f" {WIND_COLOR}{timing}{RESET}"
        used += 1 + len(timing)
        parts.append(timing_str)

    desc = alert.get("description", "").strip()
    if desc:
        flat = " ".join(desc.split())
        remaining = width - used - 2  # 2 for " " prefix and trailing space
        if remaining > 10:
            truncated = flat[:remaining]
            if len(flat) > remaining:
                truncated = truncated[:remaining - 1] + "\u2026"
            parts.append(f" {MUTED}{truncated}{RESET}")

    return ["".join(parts)]


def render_alerts(alerts, width=80, remaining_rows=None, runtime=None):
    """NWS/ECCC alert banners — compact one-line format."""
    if not alerts:
        return []
    lines = []
    for alert in alerts:
        lines.extend(_render_single_alert(alert, width, runtime=runtime))
    return lines


# ---------------------------------------------------------------------------
# Alert modal (full detail overlay for --live click)
# ---------------------------------------------------------------------------

_MODAL_BG = (10, 12, 18)


def _build_modal_content(alert, inner_w, runtime=None):
    """Build the full list of content lines for the alert modal.

    Returns a list of (text, is_blank) tuples. Each text string already
    contains ANSI color codes and will be padded by the caller.
    """
    MBG = bg(*_MODAL_BG)
    TFG = fg(200, 205, 215)
    dark_fg = fg(20, 20, 25)
    severity = alert.get("severity", "")
    r, g, b = _severity_rgb(severity)
    bg_color = bg(r, g, b)
    event = alert.get("event", "Unknown")

    lines = []

    # Title pill — pad remainder with modal bg
    pill = f"{bg_color}{dark_fg}{BOLD} \u26a0 {event} {RESET}"
    lines.append(pill)

    # Timing
    effective = _parse_alert_time(alert.get("effective", ""), runtime)
    expires = _parse_alert_time(alert.get("expires", ""), runtime)
    if effective and expires:
        lines.append(f"{MBG}{WIND_COLOR}{effective} \u2013 {expires}{RESET}")
    elif expires:
        until = _s("until", runtime) if runtime else "until"
        lines.append(f"{MBG}{WIND_COLOR}{until} {expires}{RESET}")

    lines.append("")  # blank line

    # Headline (if different from event name)
    headline = alert.get("headline", "")
    if headline and headline != event:
        for wrapped in textwrap.wrap(headline, inner_w):
            lines.append(f"{MBG}{TFG}{BOLD}{wrapped}{RESET}")
        lines.append("")

    # Description — preserve paragraph breaks from source
    desc = alert.get("description", "").strip()
    if desc:
        # Split on double newlines for paragraphs
        paragraphs = desc.split("\n\n")
        for pi, para in enumerate(paragraphs):
            if pi > 0:
                lines.append("")  # paragraph break
            # Collapse whitespace within each paragraph, then wrap
            flat = " ".join(para.split())
            for wrapped in textwrap.wrap(flat, inner_w):
                lines.append(f"{MBG}{TFG}{wrapped}{RESET}")

    # URL
    url = alert.get("url", "")
    if url:
        lines.append("")
        link_color = fg(80, 140, 220)
        display_url = url if len(url) <= inner_w else url[:inner_w - 1] + "\u2026"
        osc_link = f"\033]8;;{url}\033\\{link_color}{MBG}{display_url}\033]8;;\033\\{RESET}"
        lines.append(osc_link)

    return lines


def build_alert_modal(alert, cols, rows, runtime=None, scroll=0):
    """Build a centered modal overlay showing the full alert detail.

    Returns cursor-positioned ANSI escape sequences to draw the modal.
    scroll: number of content lines scrolled down (0 = top).
    """
    MBG = bg(*_MODAL_BG)
    TFG = fg(200, 205, 215)
    BORDER = fg(70, 80, 100)

    # Modal dimensions
    modal_w = min(cols - 4, 80)
    inner_w = modal_w - 4  # 2 border + 2 padding
    modal_max_h = rows - 4

    all_content = _build_modal_content(alert, inner_w, runtime=runtime)
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
        arrow = f" {MUTED}\u25b2 "
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
        result += f"\033[{r_pos};{left_col}H{MBG}{BORDER}\u2502{RESET}{MBG} {line}{MBG}{' ' * pad} {BORDER}\u2502{RESET}"

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
    hint_len = len(hint)
    if hint_len + 2 < modal_w - 2:
        left_bar = (modal_w - 2 - hint_len) // 2
        right_bar = modal_w - 2 - hint_len - left_bar
        bot_line = f"{BORDER}\u2570{bar_ch * left_bar}{MUTED}{hint}{BORDER}{bar_ch * right_bar}\u256f"
    else:
        bot_line = f"{BORDER}\u2570{horiz}\u256f"
    result += f"\033[{bot_row};{left_col}H{MBG}{bot_line}{RESET}"

    return result, max_scroll
