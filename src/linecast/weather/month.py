"""A month of hourly temperatures and departures from the ten-year mean."""

import calendar
import math
from dataclasses import dataclass, field, replace
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
from linecast.terminal.heading import render_heading
from linecast.terminal.help import footer, wrap
from linecast.terminal.month_layout import month_layout
from linecast.terminal.textwidth import clip_styled, fit, pad, visible_len
from linecast.tides.chart import render_tide_ticks
from linecast.tides.month import _sun_times, sun_legend
from linecast.weather import style
from linecast.weather.header import location_chip, location_control
from linecast.weather.historical import history_span
from linecast.weather.i18n import _s


def _slot(day):
    return date(2000, day.month, day.day).timetuple().tm_yday - 1


def _samples(payloads, tz, now=None):
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
            if now and stamp > now.timestamp():
                # Keep the next sample for interpolation up to now, but never
                # average an upcoming autumn fold into an hour already seen.
                if (stamp > now.timestamp() + 3600
                        or moment.replace(tzinfo=None) <= now.replace(tzinfo=None)):
                    continue
            # Overlapping payloads count a timestamp once, not as a clock fold.
            samples.setdefault(moment.date(), {}).setdefault(moment.hour, {})[stamp] = value
    return samples


@dataclass
class Temperatures:
    days: dict
    repeated: set
    normals: tuple
    span: tuple
    tz: object
    recent: dict = field(default_factory=dict)
    estimates: set = field(default_factory=set)
    until: datetime | None = None

    @classmethod
    def build(cls, payloads, span, tz=timezone.utc, *, recent=None):
        """Index once, keeping missing hours empty and averaging repeated hours.

        A repeated autumn hour gets equal weight with each other date/hour in
        the baseline. The spring gap stays blank instead of inventing a value.
        """
        if payloads:
            tz = ZoneInfo(payloads[0]["timezone"])
        elif recent:
            tz = ZoneInfo(recent["timezone"])
        samples = _samples(payloads, tz)
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
        return cls(days, repeated, tuple(normals), span, tz, recent=recent or {})

    def with_recent(self, now):
        """Fill missing archive hours for this frame, leaving the mean untouched."""
        now = now.replace(tzinfo=self.tz) if now.tzinfo is None else now.astimezone(self.tz)
        days, repeated, estimates = self.days.copy(), self.repeated.copy(), set()
        for day, hours in _samples([self.recent], self.tz, now).items():
            values = list(days.get(day, (None,) * 24))
            for hour, readings in hours.items():
                if values[hour] is not None:
                    continue
                values[hour] = sum(readings.values()) / len(readings)
                estimates.add((day, hour))
                if len(readings) > 1:
                    repeated.add((day, hour))
            days[day] = tuple(values)
        return replace(self, days=days, repeated=repeated, estimates=estimates, until=now)

    def _visible(self, day, hour):
        if self.until is None or day < self.until.date():
            return True
        now_hour = (self.until.hour + self.until.minute / 60
                    + self.until.second / 3600 + self.until.microsecond / 3_600_000_000)
        return day == self.until.date() and hour <= now_hour

    def values(self, day):
        """Visible hourly samples for the legend and row extremes."""
        return [v for h, v in enumerate(self.days.get(day, ()))
                if v is not None and self._visible(day, h)]

    def estimated(self, day, hour):
        """Whether either endpoint of a displayed temperature is provisional."""
        h = int(hour)
        after = (day, h + 1) if h < 23 else (day + timedelta(days=1), 0)
        return ((day, h) in self.estimates
                or (hour - h >= 1e-9 and after in self.estimates))

    def at(self, day, hour, normal=False):
        """Interpolate consecutive clock-hour samples, never across a gap."""
        h = int(hour)
        if not 0 <= h < 24 or (not normal and not self._visible(day, hour)):
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
        month_values = [v for d in series.days
                        if (d.year, d.month) == (first.year, first.month)
                        for v in series.values(d)]
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
    series = series.with_recent(now)
    now = series.until
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
    layout = month_layout(rows, ndays, heading_rows=2, legend_rows=len(legends))
    per_row = layout.days_per_row
    groups = [days[i:i + per_row] for i in range(0, len(days), per_row)]
    names = [day_label(now.date() if now.date() in group else group[0], runtime)
             for group in groups]
    extremes = []
    for group in groups:
        values = [v for day in group for v in series.values(day)]
        if not values:
            extremes.append(("", ""))
            continue
        labels = []
        for value in (min(values), max(values)):
            shown = shown_temperature(value, runtime)
            reading = (f"{fg(*style.MUTED_RGB)}{round(shown)}°" if difference
                       else style._colored_temp(shown, runtime, suffix="°"))
            labels.append(reading + RESET)
        extremes.append(tuple(labels))
    low_w, high_w = (max((visible_len(pair[i]) for pair in extremes if pair[i]), default=3)
                     for i in range(2))
    right_w = 2 + low_w + 1 + high_w if cols >= 74 else 0
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
        x, r = mouse_pos[0] - 1 - gutter, mouse_pos[1] - 1 - layout.field_top
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
    baseline = f"{series.span[0]}–{series.span[1]}"
    caption = (_s("month_departure", runtime, span=baseline) if difference
               else _s("month_temperature", runtime))
    lines = [place] + [""] * layout.header_gap
    lines += [" " * gutter + line for line in render_heading(
        caption, width, text_rgb=style.TEXT_RGB, dim_rgb=style.DIM_RGB,
        overline=title, unit=runtime.temp_unit, ruled=layout.ruled)]
    lines += [""] * layout.heading_gap
    for r, body in enumerate(field.render(overlays)):
        group = groups[r]
        ink = style.TEXT_RGB if now.date() in group else style.MUTED_RGB
        left = " " + names[r]
        left += " " * (gutter - visible_len(left))
        line = f"{fg(*ink)}{left}{RESET}" + body
        if right_w and extremes[r][0]:
            low, high = extremes[r]
            line += f"  {pad(low, low_w, '>')} {pad(high, high_w, '>')}"
        lines.append(line)
    midnight = datetime(first.year, first.month, first.day, tzinfo=series.tz)
    lines.append(" " * gutter + render_tide_ticks(midnight, 24, width, runtime))
    lines += [""] * layout.legend_gap
    lines += [" " * gutter + legend for legend in legends]
    lines += [""] * layout.footer_gap
    credit = fit(notice, cols - 10) if notice else "Open-Meteo"
    lines.append(footer(f"{fg(*style.DIM_RGB)}{credit}{RESET}", cols, runtime.lang,
                        controls=(("c", "hint_colors"), ("←→", "months"))))
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
            if value is not None and series.estimated(day, hour):
                tip.extend(f"{tip_bg}{tip_fg} {line} "
                           for line in wrap(_s("month_estimate", runtime), cols - 4))
            if value is not None and (day, int(hour)) in series.repeated:
                tip.extend(f"{tip_bg}{tip_fg} {line} "
                           for line in wrap(_s("month_repeat", runtime), cols - 4))
        chip = live.pointer_chip(tip, *mouse_pos, cols, rows, pad_bg=tip_bg)
        output = live.overlay(output, chip)
    return output


def month_location(label, cols, runtime, menu=True):
    """The left-hand place control, also used for the live click target."""
    name = location_control(label, cols, runtime) if menu else fit(label, cols // 2)
    return location_chip(name)
