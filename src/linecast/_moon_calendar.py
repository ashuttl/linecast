"""Moon calendar view — a month of phases, one small disc per day.

In live mode `v` flips the moon between the disc and this grid: the
Gregorian month laid out week by week, each day carrying its phase drawn
with the same shading as the big disc, the principal phases and today
called out, and — when a traditional calendar is active — the calendar's
own reading in the cells: the 农历 day names, the lunar month starts, the
festivals, the pō mahina. The wheel or arrows page months; space returns
to this month. Hovering a day raises a chip with the day's phase,
moonrise and moonset, and the calendar's line for it, tides-style; a
click hands the day to the disc view (moon.py's `_on_click`, through
`clicked_day` below).

The discs are drawn icon-fashion — north up, the waxing moon lit on the
right (the southern hemisphere sees it mirrored) — rather than at the
parallactic tilt the big disc carries: a calendar is a table of days, and
the printed almanacs draw their tables this way.
"""

import calendar
from datetime import date, datetime, time, timedelta, timezone

from linecast import _live, _theme
from linecast._ephemeris import _moon_events_for_local_date, next_moon_phase_utc
from linecast._framebuffer import fmt_time_dt
from linecast._graphics import (
    Framebuffer, bg, fg, get_terminal_size, overlay, visible_len,
)
from linecast._i18n import lang_of
from linecast._lunisolar import (
    CALENDAR_MERIDIAN_HOURS, CALENDAR_NATIVE_LANG, lunisolar_date,
    resolve_calendar,
)
from linecast._moon_i18n import (
    MONTHS_I18N, _day_abbrev, _fmt_month_day, _moon_name, _ms, _zh_day_name,
    _ZH_MONTHS, anahulu_name, festival_table, ja_night_name, lunar_date_label,
    pacific_night_label, pacific_night_name, thai_festival_name,
    thai_lunar_label, thai_month_label,
    wan_phra_label,
)
from linecast._pacific import PACIFIC_CALENDARS, pacific_night
from linecast._thai_lunar import (
    _festival_key as thai_festival_key, is_wan_phra, thai_lunar_date,
)
from linecast._seasons import full_moon_name
from linecast._textwidth import char_width
from linecast._theme import darken, ensure_contrast, is_light_theme, surface_bg
from linecast._tides_i18n import _ts
from linecast._weather_i18n import DAY_NAMES

_theme.track_imports(globals(), "linecast._color")


def _rebuild():
    # The hover chip, tides' recipe.
    global TIP_BG_RGB, TIP_TEXT_RGB, TIP_DIM_RGB
    TIP_BG_RGB = darken(surface_bg(0.10), 0.45 if not is_light_theme() else 0.10)
    TIP_TEXT_RGB = ensure_contrast(_theme.theme_fg, TIP_BG_RGB, minimum=4.5)
    TIP_DIM_RGB = ensure_contrast(surface_bg(0.55), TIP_BG_RGB, minimum=2.2)


_rebuild()
_theme.on_reload(_rebuild)

# Sunday opens the week where the printed calendars open it on Sunday;
# everywhere else Monday does. DAY_NAMES is Monday-first, so the value
# is the weekday() of the grid's first column.
_SUNDAY_FIRST = frozenset({"en", "ja", "ko"})


def _week_start(lang):
    return 6 if lang in _SUNDAY_FIRST else 0


def _month_title(year, month, lang):
    """`Sep 2026`, `2026年9月` — the grid's headline, in the UI language."""
    if lang in ("ja", "zh"):
        return f"{year}年{month}月"
    if lang == "ko":
        return f"{year}년 {month}월"
    if lang == "fi":
        return f"{month}/{year}"
    months = MONTHS_I18N.get(lang, MONTHS_I18N["en"])
    if lang == "th":
        # Thai calendars year themselves in the Buddhist Era.
        return f"{months[month - 1]} {year + 543}"
    return f"{months[month - 1]} {year}"


def principal_phase_days(year, month, tzinfo):
    """{date: (phase index, local datetime)} for the month's principal phases.

    Phase index follows moon_phase(): 0 new, 2 first quarter, 4 full,
    6 last quarter. A 31-day month can hold the same phase twice.
    """
    start_local = datetime(year, month, 1, tzinfo=tzinfo)
    days_in = calendar.monthrange(year, month)[1]
    end_local = start_local + timedelta(days=days_in)
    out = {}
    for target, idx in ((0.0, 0), (0.25, 2), (0.5, 4), (0.75, 6)):
        t = (start_local - timedelta(days=1)).astimezone(timezone.utc)
        while True:
            found = next_moon_phase_utc(t, target)
            if found is None:
                break
            local = found.astimezone(tzinfo)
            if local >= end_local:
                break
            if local >= start_local:
                out[local.date()] = (idx, local)
            t = found + timedelta(days=20)
    return out


def _cell_label(day, cal, native, fest):
    """(text, is_festival) for the calendar's line in a day cell, or None.

    A festival names its day in every script. Beyond that only the
    labels that read at a glance appear: the 农历 day names, which are
    words, and each lunar month's opening day for Japanese and Korean.
    The full lunar date lives in the hover chip.
    """
    if cal in PACIFIC_CALENDARS:
        night, nights = pacific_night(cal, day)
        return pacific_night_name(cal, night, nights), False
    if cal == "thai":
        # Festivals and month starts as the other calendars have them,
        # plus the วันพระ — the printed Thai calendars mark all four
        # holy days in every month's grid.
        label_lang = "th" if native else "en"
        key = thai_festival_key(day)
        if key:
            return thai_festival_name(key, label_lang), True
        m, d, doubled = thai_lunar_date(day)
        if d == 1:
            return thai_month_label(m, doubled, label_lang), False
        if native and is_wan_phra(day):
            return wan_phra_label(False, label_lang), False
        return None
    if cal not in CALENDAR_MERIDIAN_HOURS:
        return None
    lunar = lunisolar_date(day, CALENDAR_MERIDIAN_HOURS[cal])
    if lunar is None:
        return None
    m, d, leap = lunar
    if not leap and (m, d) in fest:
        return fest[(m, d)], True
    if cal == "chinese" and native:
        if d == 1:
            return ("闰" if leap else "") + _ZH_MONTHS[m - 1], False
        return _zh_day_name(d), False
    if d == 1:
        if cal == "japanese" and native:
            return f"{m}月", False
        if cal == "korean" and native:
            return f"{m}월", False
        return f"m{m}", False
    return None


def _put(overlays, x, row, text, rgb, bold=False, max_x=None):
    """Write *text* into the overlay dict, wide glyphs claiming two cells.

    A zero-width combining mark (a Thai vowel sign, say) joins its
    base's cell instead of claiming one of its own.
    """
    prev = None
    for j, ch in enumerate(text):
        w = char_width(ch, text[j + 1:j + 2])
        if w == 0 and prev is not None:
            kept, c, b = overlays[prev]
            overlays[prev] = (kept + ch, c, b)
            continue
        if max_x is not None and x + w > max_x:
            break
        overlays[(x, row)] = (ch, rgb, bold)
        prev = (x, row)
        if w == 2:
            overlays[(x + 1, row)] = ("", rgb, bold)
        x += max(w, 1)
    return x


def _clip(text, width):
    """The head of *text* that fits *width* terminal cells."""
    out, used = "", 0
    for j, ch in enumerate(text):
        w = char_width(ch, text[j + 1:j + 2])
        if used + w > width:
            break
        out += ch
        used += w
    return out


def render_calendar(now_local, lat, lng, runtime, month_offset=0,
                    fullscreen=False, mouse_pos=None, calendar_name=None):
    """Build the calendar view: a month grid of shaded phase discs."""
    from linecast import moon as _moon  # palettes, rebuilt on theme reload
    from linecast.sunshine import moon_cycle_frac, moon_phase, SYNODIC_MONTH
    from linecast._runtime import install_banner

    lang = lang_of(runtime)
    cal = resolve_calendar(calendar_name, lang)
    native = cal is not None and CALENDAR_NATIVE_LANG.get(cal) == lang
    fest = (festival_table(cal, native)
            if cal in CALENDAR_MERIDIAN_HOURS else {})
    tzinfo = now_local.tzinfo
    today = now_local.date()

    month0 = now_local.year * 12 + (now_local.month - 1) + month_offset
    year, month = divmod(month0, 12)
    month += 1
    first = date(year, month, 1)
    days_in = calendar.monthrange(year, month)[1]
    start = _week_start(lang)
    lead = (first.weekday() - start) % 7
    weeks = -(-(lead + days_in) // 7)

    cols, rows = get_terminal_size()
    hint = install_banner()
    chrome = 1 if hint else 0
    graph_w = max(16, cols - 2)
    graph_h = max(9, rows - chrome - (0 if fullscreen else 2))

    # Two header rows (title, weekdays); the weeks split what remains,
    # and the leftover centres the grid vertically.
    cell_h = max(2, (graph_h - 2) // weeks)
    cell_w = max(4, graph_w // 7)
    grid_w = cell_w * 7
    left = (graph_w - grid_w) // 2
    row0 = 2 + max(0, (graph_h - 2 - cell_h * weeks) // 2)
    radius = min(cell_h - 1.0, (cell_w - 2) / 2)

    # The frame on screen is the one clicks and hovers land on, so its
    # geometry is kept for clicked_day() rather than recomputed.
    global _last_grid
    _last_grid = (left, row0, cell_w, cell_h, weeks, lead, days_in,
                  year, month)

    phase_days = principal_phase_days(year, month, tzinfo)

    T, D, A, P = (_moon.PANEL_TEXT_RGB, _moon.PANEL_DIM_RGB,
                  _moon.PANEL_AMBER_RGB, _moon.PANEL_PURPLE_RGB)
    F = _moon.PANEL_FAINT_RGB

    fb = Framebuffer(graph_w, graph_h, bg_color=_moon.SKY_RGB)
    overlays = {}

    # Title, centred over the grid; paged away, the way back rides beside it.
    title = _month_title(year, month, lang)
    aside = f" · {_ts('space_to_now', runtime)}" if month_offset else ""
    t_w = visible_len(title)
    a_w = visible_len(aside)
    tx = left + max(0, (grid_w - t_w - a_w) // 2)
    tx = _put(overlays, tx, 0, title, A if month_offset else T, bold=True,
              max_x=graph_w)
    if aside:
        _put(overlays, tx, 0, aside, D, max_x=graph_w)

    # Weekday header, dim, one label over each column of numbers.
    day_names = DAY_NAMES.get(lang, DAY_NAMES["en"])
    for c in range(7):
        label = _clip(day_names[(start + c) % 7], cell_w - 2)
        _put(overlays, left + c * cell_w + 1, 1, label, F, max_x=graph_w)

    # The days.
    for day in range(1, days_in + 1):
        d = date(year, month, day)
        slot = lead + day - 1
        wk, c = divmod(slot, 7)
        x0 = left + c * cell_w
        y0 = row0 + wk * cell_h
        noon = datetime.combine(d, time(12), tzinfo=tzinfo)
        illum = _moon.moon_illumination(noon)
        principal = phase_days.get(d)

        # Today's whole cell sits on a faintly moonlit field — the way a
        # printed calendar rings the day — since a glow behind a disc
        # this small has no room to show.
        if d == today:
            for spy in range(y0 * 2, (y0 + cell_h) * 2):
                for x in range(x0, x0 + cell_w):
                    fb.set_pixel(x, spy, _moon.MOON_GLOW_RGB, 0.16)

        # The disc: an icon of the day's phase, waxing lit on the right
        # (mirrored south of the equator).
        cx = x0 + cell_w // 2
        cy = y0 * 2 + cell_h
        if radius >= 2.0:
            waxing = moon_cycle_frac(noon) < 0.5
            limb = 90.0 if waxing else 270.0
            if lat is not None and lat < 0:
                limb = 360.0 - limb
            _moon._draw_moon_disc(fb, cx, cy, radius, illum, limb, 0.0)
        else:
            # No room to draw: the phase glyph stands in for the disc.
            icon = moon_phase(noon, runtime)[2]
            _put(overlays, cx, y0 + cell_h // 2, icon, T, max_x=graph_w)

        # The day number: today bold and bright, a full moon amber, the
        # other principal phases bright, ordinary days dim.
        if d == today:
            num_ink, num_bold = T, True
        elif principal and principal[0] == 4:
            num_ink, num_bold = A, False
        elif principal:
            num_ink, num_bold = T, False
        else:
            num_ink, num_bold = D, False
        _put(overlays, x0 + 1, y0, str(day), num_ink, bold=num_bold,
             max_x=graph_w)

        # The calendar's own line. A calendar that labels every day (the
        # 农历 day names, the pō mahina) writes along the cell's bottom
        # edge, where the every-cell rhythm says whose row it is; sparse
        # labels (month starts, festivals) ride just after the day
        # number instead, so they cannot read as another cell's.
        if cal and cell_h >= 3 and cell_w >= 6:
            label = _cell_label(d, cal, native, fest)
            if label:
                text, is_fest = label
                ink = P if is_fest else F
                dense = cal in PACIFIC_CALENDARS or (cal == "chinese" and native)
                if dense:
                    _put(overlays, x0 + 1, y0 + cell_h - 1,
                         _clip(text, cell_w - 2), ink, max_x=graph_w)
                else:
                    nx = x0 + 1 + len(str(day)) + 1
                    _put(overlays, nx, y0,
                         _clip(text, x0 + cell_w - 1 - nx), ink,
                         max_x=graph_w)

    lines = fb.render(overlays=overlays)
    if hint:
        lines.append(hint)

    # Hover: the chip for the day under the pointer.
    chip = ""
    if mouse_pos:
        d = clicked_day(*mouse_pos)
        if d is not None:
            chip = _hover_chip(
                d, now_local, lat, lng, runtime,
                cal, native, fest, phase_days, mouse_pos, cols, rows,
                moon_phase, moon_cycle_frac, SYNODIC_MONTH)
    return overlay("\n".join(lines), chip)


_last_grid = None   # geometry of the last rendered grid, for clicked_day


def clicked_day(col, row):
    """The date under a 1-based terminal cell, from the last rendered grid.

    None off the grid, or before any grid has been drawn. The same
    mapping serves the hover chip, so a click opens exactly the day the
    chip was reading.
    """
    if _last_grid is None:
        return None
    left, row0, cell_w, cell_h, weeks, lead, days_in, year, month = _last_grid
    gx, gy = col - 1 - left, row - 1 - row0
    if not (0 <= gx < cell_w * 7 and 0 <= gy < cell_h * weeks):
        return None
    day = (gy // cell_h) * 7 + gx // cell_w - lead + 1
    if 1 <= day <= days_in:
        return date(year, month, day)
    return None


def _hover_chip(d, now_local, lat, lng, runtime, cal, native, fest,
                phase_days, mouse_pos, cols, rows,
                moon_phase, moon_cycle_frac, SYNODIC_MONTH):
    """The hovered day, read in full: date, phase, rise and set, calendar."""
    from linecast import moon as _moon

    tzinfo = now_local.tzinfo
    noon = datetime.combine(d, time(12), tzinfo=tzinfo)
    illum = _moon.moon_illumination(noon)
    principal = phase_days.get(d)
    lang = lang_of(runtime)

    tip_bg = bg(*TIP_BG_RGB)
    tip_fg = fg(*TIP_TEXT_RGB)
    tip_dim = fg(*TIP_DIM_RGB)

    head = f"{_day_abbrev(noon, runtime)} {_fmt_month_day(noon, runtime)}"
    ahead = (d - now_local.date()).days
    if ahead > 0:
        head += f" · {_ms('in_days', runtime, days=str(ahead))}"

    if principal:
        idx, at = principal
        name = _moon_name(idx, runtime)
        if idx == 4 and lang == "en" and cal in (None, "almanac"):
            mn = full_moon_name(at, SYNODIC_MONTH)
            name = "Blue Moon" if mn == "Blue" else f"Full {mn} Moon"
        icon = moon_phase(at, runtime)[2]
        phase_line = (f"{icon} {name} · "
                      f"{fmt_time_dt(at, use_24h=runtime.use_24h)}")
    else:
        idx, _name, icon = moon_phase(noon, runtime)
        name = _moon_name(idx, runtime)
        phase_line = (f"{icon} {name} · "
                      f"{_ms('illuminated', runtime, pct=f'{illum * 100:.0f}')}")

    rise, sset = _moon_events_for_local_date(d, lat, lng, tzinfo)

    def _t(dt):
        return fmt_time_dt(dt, use_24h=runtime.use_24h) if dt else "—"

    events = f"↑ {_t(rise)}  ↓ {_t(sset)}"

    cal_line = None
    if cal in PACIFIC_CALENDARS:
        night, nights = pacific_night(cal, d)
        cal_line = pacific_night_label(cal, night, nights)
        if cal == "hawaiian":
            cal_line += f" · anahulu {anahulu_name(night)}"
    elif cal == "almanac":
        half = "light" if moon_cycle_frac(noon) < 0.5 else "dark"
        cal_line = _ms(f"{half}_of_moon", runtime)
    elif cal == "thai":
        m, day_n, doubled = thai_lunar_date(d)
        label_lang = "th" if native else "en"
        cal_line = thai_lunar_label(m, day_n, doubled, label_lang)
        key = thai_festival_key(d)
        if key:
            cal_line = f"{thai_festival_name(key, label_lang)} · {cal_line}"
        elif is_wan_phra(d):
            cal_line = f"{wan_phra_label(False, label_lang)} · {cal_line}"
    elif cal in CALENDAR_MERIDIAN_HOURS:
        lunar = lunisolar_date(d, CALENDAR_MERIDIAN_HOURS[cal])
        if lunar is not None:
            m, day_n, leap = lunar
            label_lang = lang if native else "en"
            cal_line = lunar_date_label(m, day_n, leap, label_lang)
            if cal == "japanese" and native:
                cal_line = f"{ja_night_name(day_n)} · {cal_line}"
            if not leap and (m, day_n) in fest:
                cal_line = f"{fest[(m, day_n)]} · {cal_line}"

    tip_lines = [
        f"{tip_bg}{tip_fg} {head} ",
        f"{tip_bg}{tip_fg} {phase_line} ",
        f"{tip_bg}{tip_dim} {events} ",
    ]
    if cal_line:
        tip_lines.append(f"{tip_bg}{tip_fg} {cal_line} ")

    return _live.pointer_chip(tip_lines, mouse_pos[0] + 2, mouse_pos[1],
                              cols, rows, pad_bg=tip_bg)
