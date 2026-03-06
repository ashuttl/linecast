"""Weather alert rendering."""

from datetime import datetime

from linecast._graphics import bg, fg, RESET, BOLD
from linecast._weather_i18n import DAY_NAMES
from linecast._weather_style import ALERT_AMBER, ALERT_RED, ALERT_YELLOW, MUTED, WIND_COLOR


def _parse_alert_time(iso_str, runtime=None):
    """Parse ISO time string to a short display string."""
    try:
        dt = datetime.fromisoformat(iso_str)
        use_24h = runtime.metric if runtime else False
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
    """Render one alert (pill + wrapped description), up to max_lines."""
    dark_fg = fg(20, 20, 25)
    severity = alert.get("severity", "")
    r, g, b = _severity_rgb(severity)
    bg_color = bg(r, g, b)
    event = alert.get("event", "Unknown")
    effective = _parse_alert_time(alert.get("effective", ""), runtime)
    expires = _parse_alert_time(alert.get("expires", ""), runtime)
    timing = ""
    if effective and expires:
        timing = f" {effective} \u2013 {expires}"
    elif expires:
        until = "jusqu'\u00e0" if (runtime and runtime.lang == "fr") else "until"
        timing = f" {until} {expires}"

    pill = f"{bg_color}{dark_fg}{BOLD} \u26a0 {event} {RESET}"
    line1 = f" {pill} {MUTED}\u00b7{WIND_COLOR}{timing}{RESET}" if timing else f" {pill}{RESET}"
    lines = [line1]

    desc = alert.get("description", "").strip()
    if desc and max_lines > 1:
        desc = " ".join(desc.split())
        wrap_w = width - 2
        words = desc.split()
        current_line = ""
        desc_lines = 0
        max_desc = max_lines - 1  # 1 line for pill
        for word in words:
            if current_line and len(current_line) + 1 + len(word) > wrap_w:
                lines.append(f"  {MUTED}{current_line}{RESET}")
                desc_lines += 1
                if desc_lines >= max_desc:
                    break
                current_line = word
            else:
                current_line = f"{current_line} {word}" if current_line else word
        if current_line and desc_lines < max_desc:
            lines.append(f"  {MUTED}{current_line}{RESET}")

    return lines


def render_alerts(alerts, width=80, remaining_rows=None, runtime=None):
    """NWS/ECCC alert banners - severity-colored background pill + description."""
    if not alerts:
        return []
    n = len(alerts)

    if remaining_rows is not None:
        # Blank line between each alert, evenly distribute remaining space
        separator_lines = n - 1
        usable = max(n, remaining_rows - separator_lines)
        per_alert = usable // n
        # Distribute remainder to earlier alerts
        extras = usable - per_alert * n
    else:
        per_alert = 999
        extras = 0

    lines = []
    for idx, alert in enumerate(alerts):
        if idx > 0:
            lines.append("")  # blank separator between alerts
        budget = per_alert + (1 if idx < extras else 0)
        lines.extend(_render_single_alert(alert, width, max_lines=budget, runtime=runtime))

    return lines
