"""A month of hourly temperatures and departures from the ten-year mean."""

import calendar
import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo

from linecast._i18n import DAY_NAMES, fmt_decimal, table_for
from linecast._timefmt import fmt_time_dt
from linecast.moon.calendar import _month_title
from linecast.terminal import live, theme
from linecast.terminal.braille import DOT_BITS
from linecast.terminal.color import RESET, bg, fg
from linecast.terminal.framebuffer import Framebuffer, get_terminal_size
from linecast.terminal.help import footer, wrap
from linecast.terminal.textwidth import clip_styled, fit, visible_len
from linecast.tides.chart import render_tide_ticks
from linecast.tides.month import _sun_times, sun_legend
from linecast.weather import style
from linecast.weather.header import location_chip, location_control
from linecast.weather.historical import history_span
from linecast.weather.i18n import _s


def _slot(day):
    return date(2000, day.month, day.day).timetuple().tm_yday - 1


@dataclass
class Temperatures:
    days: dict
    repeated: set
    normals: tuple
    span: tuple
    tz: object

    @classmethod
    def build(cls, payloads, span, tz=timezone.utc):
        """Index once, keeping missing hours empty and averaging repeated hours.

        A repeated autumn hour gets equal weight with each other date/hour in
        the baseline. The spring gap stays blank instead of inventing a value.
        """
        if payloads:
            tz = ZoneInfo(payloads[0]["timezone"])
        samples = {}
        for data in payloads:
            hourly = data.get("hourly") or {}
            for stamp, value in zip(hourly.get("time") or [],
                                   hourly.get("temperature_2m") or []):
                if not isinstance(value, (int, float)) or not math.isfinite(value):
                    continue
                try:
                    moment = datetime.fromtimestamp(stamp, timezone.utc).astimezone(tz)
                except (TypeError, ValueError, OverflowError, OSError):
                    continue
                # A timestamp can appear in overlapping payloads; count it once.
                samples.setdefault(moment.date(), {}).setdefault(moment.hour, {})[stamp] = value
        days, repeated = {}, set()
        sums = [[0.0] * 24 for _ in range(366)]
        counts = [[0] * 24 for _ in range(366)]
        for day, hours in samples.items():
            values = [None] * 24
            for hour, readings in hours.items():
                values[hour] = sum(readings.values()) / len(readings)
                if len(readings) > 1:
                    repeated.add((day, hour))
                if span[0] <= day.year <= span[1]:
                    sums[_slot(day)][hour] += values[hour]
                    counts[_slot(day)][hour] += 1
            days[day] = tuple(values)
        normals = []
        for slot in range(366):
            row = []
            for hour in range(24):
                near = [(slot + k) % 366 for k in range(-7, 8)]
                count = sum(counts[s][hour] for s in near)
                row.append(sum(sums[s][hour] for s in near) / count if count else None)
            normals.append(tuple(row))
        return cls(days, repeated, tuple(normals), span, tz)

    def at(self, day, hour, normal=False):
        """Interpolate consecutive clock-hour samples, never across a gap."""
        h = int(hour)
        if not 0 <= h < 24:
            return None
        values = self.normals[_slot(day)] if normal else self.days.get(day, ())
        a = values[h] if values else None
        fraction = hour - h
        if fraction < 1e-9:
            return a
        if h < 23:
            b = values[h + 1] if values else None
        else:
            tomorrow = day + timedelta(days=1)
            after = self.normals[_slot(tomorrow)] if normal else self.days.get(tomorrow, ())
            b = after[0] if after else None
        return None if a is None or b is None else a + (b - a) * fraction


def shown_temperature(value, runtime, difference=False):
    if runtime.celsius:
        return value
    return value * 9 / 5 + (0 if difference else 32)


def temperature_text(value, runtime, difference=False, precision=1):
    if value is None:
        return "—"
    shown = shown_temperature(value, runtime, difference)
    sign = "+" if difference and round(shown, precision) > 0 else ""
    return sign + fmt_decimal(shown, precision, runtime) + runtime.temp_unit


def field_color(value, runtime, difference=False):
    if value is None:
        return theme.surface_bg(0.025)
    if difference:
        ink = style.BLUE_RGB if value < 0 else style.RED_RGB
        return theme.lerp_rgb(theme.surface_bg(0.04), ink, min(1, abs(value) / 10) * 0.8)
    actual = shown_temperature(value, runtime)
    return theme.lerp_rgb(theme.theme_bg, style._temp_color(actual, runtime), 0.68)


def clear_ink(ink, background):
    """Keep the fine Sun and hover marks visible on either theme."""
    if theme.contrast_ratio(ink, background) >= 2.5:
        return ink
    return theme.best_contrast((theme.theme_bg, style.TEXT_RGB, (0, 0, 0), (255, 255, 255)),
                               background, minimum=2.5)


@lru_cache(maxsize=4096)
def sun_times(day, lat, lng, tz):
    return _sun_times(day, lat, lng, tz)


def day_label(day, runtime):
    number = _s("day_of_month", runtime, d=day.day)
    return f"{table_for(DAY_NAMES, runtime.lang)[day.weekday()]} {number:>2}"


def _legend(series, first, runtime, width, difference):
    if difference:
        values = [-10, -5, 0, 5, 10]  # Celsius differences; units change, colors do not
    else:
        month_values = [v for d, row in series.days.items()
                        if (d.year, d.month) == (first.year, first.month)
                        for v in row if v is not None]
        low, high = (min(month_values), max(month_values)) if month_values else (0, 30)
        values = [low + (high - low) * k / 4 for k in range(5)]
    parts = []
    for value in values:
        label = temperature_text(value, runtime, difference, precision=0)
        parts.append(f"{bg(*field_color(value, runtime, difference))}  {RESET} "
                     f"{fg(*style.MUTED_RGB)}{label}{RESET}")
    if sum(map(visible_len, parts)) + 3 * (len(parts) - 1) > width:
        parts = parts[::2]
    return clip_styled("   ".join(parts), width) + RESET


def render_month(series, first, runtime, lat, lng, label, *, difference=False,
                 mouse_pos=None, now=None, location_menu=False, notice=""):
    cols, rows = get_terminal_size()
    if cols < 54 or rows < 23:
        return "\n".join(wrap(_s("month_small", runtime, cols=54, rows=23), cols))
    now = now or datetime.now(series.tz if series else timezone.utc)
    if series is None:
        series = Temperatures.build([], history_span(now.year), now.tzinfo or timezone.utc)
    ndays = calendar.monthrange(first.year, first.month)[1]
    days = [first + timedelta(days=k) for k in range(ndays)]
    gutter = max(visible_len(day_label(day, runtime)) for day in days) + 3
    legend_width = cols - gutter - 1
    chips = _legend(series, first, runtime, legend_width, difference)
    sun = sun_legend(runtime, legend_width, now=now.date() in days,
                     sun_rgb=style.YELLOW_RGB, now_rgb=style.TEXT_RGB,
                     text_rgb=style.DIM_RGB)
    legends = ([chips + "   " + sun] if visible_len(chips) + 3 + visible_len(sun) <= legend_width
               else [chips, sun])
    available = rows - 5 - len(legends)
    per_row = 1 if available >= len(days) else 2
    groups = [days[i:i + per_row] for i in range(0, len(days), per_row)]
    spare = available - len(groups)
    header_gap = int(spare > 0)
    spare -= header_gap
    rule_gap = int(spare > 0)
    spare -= rule_gap
    legend_gap = int(spare > 0)
    spare -= legend_gap
    above = spare // 2
    field_top = 3 + header_gap + above + rule_gap
    names = [day_label(now.date() if now.date() in group else group[0], runtime)
             for group in groups]
    right_w = 15 if cols >= 74 else 0
    width = cols - gutter - right_w - 1
    field = Framebuffer(width, len(groups), bg_color=field_color(None, runtime))
    bits = {}
    now_cell = None
    # Each row names one day, or two in a short terminal. Interpolation is
    # horizontal only: adjacent days retain their own weather.
    for r, group in enumerate(groups):
        for j, day in enumerate(group):
            subpixels = [r * 2, r * 2 + 1] if len(group) == 1 else [r * 2 + j]
            dot_rows = range(4) if len(group) == 1 else range(j * 2, j * 2 + 2)
            for x in range(width):
                hour = (x + 0.5) * 24 / width
                value = series.at(day, hour)
                if difference:
                    normal = series.at(day, hour, normal=True)
                    value = value - normal if value is not None and normal is not None else None
                for sy in subpixels:
                    field.set_pixel(x, sy, field_color(value, runtime, difference))
            for moment in sun_times(day, lat, lng, series.tz) if series.days else ():
                if moment is None or moment.date() != day:
                    continue
                hour = moment.hour + moment.minute / 60 + moment.second / 3600
                dot = min(width * 2 - 1, int(hour * width * 2 / 24))
                cell = (dot // 2, r)
                mask = sum(DOT_BITS[dot % 2][y] for y in dot_rows)
                bits[cell] = bits.get(cell, 0) | mask
            if day == now.date():
                now_cell = (min(width - 1, int((now.hour + now.minute / 60) * width / 24)), r)
    overlays = {cell: (chr(0x2800 + mask), clear_ink(style.YELLOW_RGB,
                                                   field.cell_bg(*cell)), False)
                for cell, mask in bits.items()}
    hover = None
    if mouse_pos:
        x, r = mouse_pos[0] - 1 - gutter, mouse_pos[1] - 1 - field_top
        if 0 <= x < width and 0 <= r < len(groups):
            hover = r, x
            for rr in range(len(groups)):
                cell = x, rr
                if cell not in overlays:
                    overlays[cell] = ("⠂", clear_ink(style.CHART_HOVER_RGB,
                                                    field.cell_bg(*cell)), False)
    if now_cell:
        overlays[now_cell] = ("◆", clear_ink(style.TEXT_RGB, field.cell_bg(*now_cell)), False)

    title = _month_title(first.year, first.month, runtime.lang, full=True)
    place = month_location(label, cols, runtime, location_menu)
    title = fit(title, max(0, cols - visible_len(place) - 2))
    head = place + " " * (cols - visible_len(place) - visible_len(title) - 1)
    head += f"{fg(*style.TEXT_RGB)}{title}{RESET}"
    baseline = f"{series.span[0]}–{series.span[1]}"
    caption = (_s("month_departure", runtime, span=baseline) if difference
               else _s("month_temperature", runtime))
    caption += "  " + runtime.temp_unit
    caption = fit(caption, width)
    lines = [head] + [""] * (header_gap + above)
    lines += [" " * gutter + f"{fg(*style.TEXT_RGB)}{caption}{RESET}",
              " " * gutter + f"{fg(*style.DIM_RGB)}{'─' * visible_len(caption)}{RESET}"]
    lines += [""] * rule_gap
    for r, body in enumerate(field.render(overlays)):
        group = groups[r]
        ink = style.TEXT_RGB if now.date() in group else style.MUTED_RGB
        left = " " + names[r]
        left += " " * (gutter - visible_len(left))
        line = f"{fg(*ink)}{left}{RESET}" + body
        if right_w:
            values = [v for day in group for v in series.days.get(day, ()) if v is not None]
            if values:
                low, high = (shown_temperature(v, runtime) for v in (min(values), max(values)))
                line += f"{fg(*style.MUTED_RGB)}  {round(low):4}°  {round(high):4}°{RESET}"
        lines.append(line)
    midnight = datetime(first.year, first.month, first.day, tzinfo=series.tz)
    lines.append(" " * gutter + render_tide_ticks(midnight, 24, width, runtime))
    lines += [""] * legend_gap
    lines += [" " * gutter + legend for legend in legends]
    lines += [""] * (spare - above)
    credit = fit(notice, cols - 10) if notice else "Open-Meteo"
    lines.append(footer(f"{fg(*style.DIM_RGB)}{credit}{RESET}", cols, runtime.lang,
                        controls=(("c", "hint_colors"),)))
    output = "\n".join(lines)
    if hover:
        r, x = hover
        hour = (x + 0.5) * 24 / width
        tip = []
        tip_bg, tip_fg = bg(*style.TOOLTIP_BG_RGB), fg(*style.TOOLTIP_TEXT_RGB)
        for day in groups[r]:
            moment = datetime(day.year, day.month, day.day) + timedelta(hours=hour)
            value, normal = series.at(day, hour), series.at(day, hour, normal=True)
            when = fmt_time_dt(moment, use_24h=runtime.use_24h)
            tip.append(f"{tip_bg}{tip_fg} {day_label(day, runtime)}  {when} "
                       f" {temperature_text(value, runtime)} ")
            if value is not None and normal is not None:
                tip.append(f"{tip_bg}{tip_fg} {baseline}: {temperature_text(normal, runtime)} "
                           f" ({temperature_text(value - normal, runtime, True)}) ")
            if (day, int(hour)) in series.repeated:
                tip.extend(f"{tip_bg}{tip_fg} {line} "
                           for line in wrap(_s("month_repeat", runtime), cols - 4))
        chip = live.pointer_chip(tip, *mouse_pos, cols, rows, pad_bg=tip_bg)
        output = live.overlay(output, chip)
    return output


def month_location(label, cols, runtime, menu=True):
    """The left-hand place control, also used for the live click target."""
    name = location_control(label, cols, runtime) if menu else fit(label, cols // 2)
    return location_chip(name)
