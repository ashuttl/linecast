"""Moon calendar view — a month of phases, one small disc per day.

In live mode `v` flips the moon between the disc and this grid: the
civil month laid out week by week — the Gregorian month, or where the
dates are Solar Hijri (astro.calendars.civil) a Solar Hijri month such as
مهر ۱۴۰۵, each cell carrying its Gregorian day small in the corner.
Each day carries its phase drawn with the same shading as the big
disc, the principal phases and today called out, and — when a
traditional calendar is active — the calendar's own reading in the
cells: the 农历 day names, the lunar month starts, the festivals, the pō
mahina. The wheel or arrows page months; space returns
to this month. Hovering a day raises a chip with the day's phase,
moonrise and moonset, and the calendar's line for it, tides-style; a
click hands the day to the disc view (moon/view.py's `_on_click`, through
`clicked_day` below).

The discs are drawn icon-fashion — north up, the waxing moon lit on the
right (the southern hemisphere sees it mirrored) — rather than at the
parallactic tilt the big disc carries: a calendar is a table of days, and
the printed almanacs draw their tables this way.
"""

import calendar
from datetime import date, datetime, time, timedelta, timezone

from linecast.terminal import live as _live
from linecast.terminal import theme as _theme
from linecast.astro.ephemeris import _moon_events_for_local_date, next_moon_phase_utc
from linecast._timefmt import fmt_time_dt
from linecast.terminal.color import bg, fg
from linecast.terminal.textwidth import visible_len
from linecast.terminal.framebuffer import Framebuffer, cell_aspect, get_terminal_size
from linecast.terminal.live import overlay
from linecast._i18n import base_language, lang_of, table_for
from linecast.astro.calendars.lunisolar import (
    CALENDAR_MERIDIAN_HOURS, calendar_is_native, lunisolar_date,
)
from linecast.astro.calendars.hebrew import hebrew_date, holiday_key
from linecast.astro.calendars.hijri import hijri_date, observance_key
from linecast.astro.calendars.icelandic import lit_moon_key
from linecast.astro.calendars.icelandic import month_key as icelandic_month_key
from linecast.astro.calendars.icelandic import named_day_key
from linecast.astro.calendars.icelandic import (
    next_month_start as next_icelandic_month,
)
from linecast.astro.calendars import solar_hijri
from linecast.astro.calendars.civil import (
    SOLAR_HIJRI, civil_calendar, shift_month, solar_hijri_month_title,
)
from linecast.moon.i18n import (
    _day_abbrev, _fmt_month_day, _ms, _zh_day_name, festival_table, gregorian_date_label,
    hebrew_holiday_name, hebrew_month_name, hijri_era, hijri_month_name,
    hijri_observance_name, icelandic_day_name, icelandic_month_name, icelandic_moon_name,
    pacific_night_name, thai_festival_name, thai_month_label, vi_month_label, wan_phra_label,
    zh_month_label,
)
from linecast._i18n import MONTHS, moon_name
from linecast.astro.calendars.pacific import PACIFIC_CALENDARS, pacific_night
from linecast.astro.calendars.thai_lunar import (
    _festival_key as thai_festival_key, is_wan_phra, thai_lunar_date,
)
from linecast.astro.seasons import full_moon_name
from linecast.moon.phase import (
    SYNODIC_MONTH, moon_cycle_frac, moon_illumination, moon_phase,
)
from linecast.moon.readings import context, reading
from linecast.terminal.textwidth import char_width
from linecast.terminal.theme import darken, ensure_contrast, is_light_theme, surface_bg
from linecast.tides.i18n import _ts
from linecast._i18n import DAY_NAMES

_theme.track_imports(globals(), "linecast.terminal.color")


def _rebuild():
    # The hover chip, tides' recipe.
    global TIP_BG_RGB, TIP_TEXT_RGB, TIP_DIM_RGB
    TIP_BG_RGB = darken(surface_bg(0.10), 0.45 if not is_light_theme() else 0.10)
    TIP_TEXT_RGB = ensure_contrast(_theme.theme_fg, TIP_BG_RGB, minimum=4.5)
    TIP_DIM_RGB = ensure_contrast(surface_bg(0.55), TIP_BG_RGB, minimum=2.2)


_rebuild()
_theme.on_reload(_rebuild)

def _week_start(runtime):
    """The weekday() of the grid's first column: the resolved week start
    (`linecast week`, by default the country's custom), Monday without a
    runtime. DAY_NAMES is Monday-first, so this also rotates the header."""
    from linecast._runtime import WEEK_START_WEEKDAY
    return WEEK_START_WEEKDAY.get(getattr(runtime, "week_start", None), 0)


def _month_title(year, month, lang):
    """`Sep 2026`, `2026年9月` — the grid's headline, in the UI language."""
    if base_language(lang) in ("ja", "zh", "zh-Hant"):
        return f"{year}年{month}月"
    if lang == "ko":
        return f"{year}년 {month}월"
    if lang == "fi":
        return f"{month}/{year}"
    if lang == "hu":
        # Hungarian dates run from the year: "2026. szept."
        return f"{year}. {table_for(MONTHS, lang)[month - 1]}"
    if lang == "vi":
        return f"Tháng {month} năm {year}"
    months = table_for(MONTHS, lang)
    if lang == "th":
        # Thai calendars year themselves in the Buddhist Era.
        return f"{months[month - 1]} {year + 543}"
    return f"{months[month - 1]} {year}"


def _gregorian_span(first, last, lang):
    """The Gregorian months a Solar Hijri month runs through, for the
    title: `سپتامبر – اکتبر 2026`, or `دسامبر 2026 – ژانویه 2027`."""
    months = table_for(MONTHS, lang)
    n1, n2 = months[first.month - 1], months[last.month - 1]
    if first.year == last.year:
        return f"{n1} – {n2} {first.year}"
    return f"{n1} {first.year} – {n2} {last.year}"


def _calendar_span(cal, first, last, lang):
    """The Hebrew, Hijri, or Icelandic months a civil month runs
    through, for the title.

    `Elul 5786 – Tishrei 5787`, `Tishrei – Cheshvan 5787`, or a lone
    `Shevat 5787` for the February that fits inside one month. The
    printed wall calendars set this under the civil month; here it also
    covers the month starts the cells cannot show, since Tishrei and
    Muharram both open on a holiday that takes the cell, as Harpa,
    Heyannir, Gormánuður, Þorri, and Góa do. The Icelandic years have
    no numbers: `Tvímánuður – Haustmánuður`.
    """
    if cal == "icelandic":
        n1 = icelandic_month_name(icelandic_month_key(first))
        n2 = icelandic_month_name(icelandic_month_key(last))
        return n1 if n1 == n2 else f"{n1} – {n2}"
    if cal == "hebrew":
        y1, m1, _ = hebrew_date(first)
        y2, m2, _ = hebrew_date(last)
        n1, n2 = hebrew_month_name(y1, m1), hebrew_month_name(y2, m2)
        era = ""
    elif cal == "islamic":
        y1, m1, _ = hijri_date(first)
        y2, m2, _ = hijri_date(last)
        n1, n2 = hijri_month_name(m1, lang), hijri_month_name(m2, lang)
        era = f" {hijri_era(lang)}"
    else:
        return None
    if (y1, m1) == (y2, m2):
        return f"{n1} {y1}{era}"
    if y1 == y2:
        return f"{n1} – {n2} {y1}{era}"
    return f"{n1} {y1}{era} – {n2} {y2}{era}"


def principal_phase_days(year, month, tzinfo):
    """{date: (phase index, local datetime)} for the month's principal phases.

    Phase index follows moon_phase(): 0 new, 2 first quarter, 4 full,
    6 last quarter. A 31-day month can hold the same phase twice.
    """
    return _phase_days(date(year, month, 1), calendar.monthrange(year, month)[1],
                       tzinfo)


def _phase_days(first, days_in, tzinfo):
    """principal_phase_days for the *days_in* days from *first*, which
    need not be a Gregorian month."""
    start_local = datetime(first.year, first.month, first.day, tzinfo=tzinfo)
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


def _cell_label(day, cal, native, fest, lang="en", israel=False,
                new_moon=None):
    """(text, is_festival) for the calendar's line in a day cell, or None.

    A festival names its day in every script. Beyond that only the
    labels that read at a glance appear: the 农历 day names, which are
    words, and each lunar month's opening day for Japanese and Korean.
    The Hijri and Hebrew calendars count their days in the cell's
    corner instead (render_calendar), and name the month there. The
    full lunar date lives in the hover chip. *new_moon* is the moment
    of a new moon that falls on *day*, for the calendars that name it.
    """
    if cal in PACIFIC_CALENDARS:
        night, nights = pacific_night(cal, day)
        return pacific_night_name(cal, night, nights), False
    if cal == "islamic":
        # The month starts ride in the corner with the Hijri day.
        key = observance_key(day)
        return (hijri_observance_name(key, lang), True) if key else None
    if cal == "hebrew":
        # A holiday names every day it runs, Sukkot's seven and
        # Hanukkah's eight included, the way a printed calendar does.
        # The month starts ride in the corner with the Hebrew day.
        key = holiday_key(day, israel)
        return (hebrew_holiday_name(key), True) if key else None
    if cal == "icelandic":
        # The named days on every day they run, the named moons on the
        # day they are lit, and each month's first day, as the almanac
        # marks them. A month that opens on a named day or moon gives
        # the cell to it; the title names the month.
        key = named_day_key(day)
        if key:
            return icelandic_day_name(key), True
        moon = lit_moon_key(new_moon) if new_moon else None
        if moon:
            return icelandic_moon_name(moon), False
        start, m_key = next_icelandic_month(day - timedelta(days=1))
        return (icelandic_month_name(m_key), False) if start == day else None
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
            return zh_month_label(m, leap, lang), False
        return _zh_day_name(d), False
    if d == 1:
        if cal == "japanese" and native:
            return f"{m}月", False
        if cal == "korean" and native:
            return f"{m}월", False
        if cal == "vietnamese" and native:
            return vi_month_label(m, leap, short=True), False
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
                    fullscreen=False, mouse_pos=None, calendar_name=None,
                    israel=False):
    """Build the calendar view: a month grid of shaded phase discs.

    *calendar_name* is the traditional calendar main() resolved, or
    None for none."""
    from linecast.moon import disc
    from linecast.moon import palette as moon_palette  # rebuilt on theme reload
    from linecast._runtime import install_banner

    lang = lang_of(runtime)
    cal = calendar_name
    native = cal is not None and calendar_is_native(cal, lang)
    fest = (festival_table(cal, lang if native else "en")
            if cal in CALENDAR_MERIDIAN_HOURS else {})
    tzinfo = now_local.tzinfo
    today = now_local.date()

    # The month is the civil calendar's: paging steps through Solar
    # Hijri months where the dates are Solar Hijri.
    civil = civil_calendar(lang)
    if civil == SOLAR_HIJRI:
        sh_year, sh_month, _day = solar_hijri.solar_hijri_date(today)
        year, month = shift_month(sh_year, sh_month, month_offset)
        first = solar_hijri.month_start(year, month)
        days_in = solar_hijri.days_in_month(year, month)
        title = solar_hijri_month_title(year, month, lang)
    else:
        month0 = now_local.year * 12 + (now_local.month - 1) + month_offset
        year, month = divmod(month0, 12)
        month += 1
        first = date(year, month, 1)
        days_in = calendar.monthrange(year, month)[1]
        title = _month_title(year, month, lang)
    last = first + timedelta(days=days_in - 1)
    start = _week_start(runtime)
    lead = (first.weekday() - start) % 7
    weeks = -(-(lead + days_in) // 7)

    cols, rows = get_terminal_size()
    hint = install_banner()
    chrome = 1 if hint else 0
    graph_w = max(16, cols)
    graph_h = max(9, rows - chrome - (0 if fullscreen else 2))

    # Two header rows (title, weekdays); the weeks split what remains,
    # and the leftover centres the grid vertically. A window too short
    # for two rows a week gets one, a glyph beside the day number,
    # rather than a last week drawn off the bottom of the frame.
    cell_h = max(1, (graph_h - 2) // weeks)
    cell_w = max(4, graph_w // 7)
    grid_w = cell_w * 7
    left = (graph_w - grid_w) // 2
    row0 = 2 + max(0, (graph_h - 2 - cell_h * weeks) // 2)
    aspect = cell_aspect() / 2.0   # a sub-pixel's height in cell widths
    radius = min((cell_h - 1.0) * aspect, (cell_w - 2) / 2)

    # The frame on screen is the one clicks and hovers land on, so its
    # geometry is kept for clicked_day() rather than recomputed.
    global _last_grid
    _last_grid = (left, row0, cell_w, cell_h, weeks, lead, days_in,
                  first, civil)

    phase_days = _phase_days(first, days_in, tzinfo)
    from linecast.terminal import bidi as _bidi
    mirrored = _bidi.mirrored()

    T, D, A, P = (moon_palette.PANEL_TEXT_RGB, moon_palette.PANEL_DIM_RGB,
                  moon_palette.PANEL_AMBER_RGB, moon_palette.PANEL_PURPLE_RGB)
    F = moon_palette.PANEL_FAINT_RGB

    fb = Framebuffer(graph_w, graph_h, bg_color=moon_palette.SKY_RGB)
    overlays = {}

    # Title, at the left, over the first weekday. A calendar with months
    # of its own sets them beside the civil month, as the wall calendars
    # do, in the text ink so they read as part of the title; paged away,
    # the way back rides at the end, dim. The span is the first to go
    # when the row runs short. A Solar Hijri month names the Gregorian
    # months its corner days belong to first, and keeps them longest.
    spans = [_gregorian_span(first, last, lang)] if civil == SOLAR_HIJRI else []
    spans.append(_calendar_span(cal, first, last, lang))
    spans = [sp for sp in spans if sp]
    aside = f" · {_ts('space_to_now', runtime)}" if month_offset else ""
    t_w = visible_len(title)
    a_w = visible_len(aside)
    while spans and t_w + visible_len(" · ".join(spans)) + 3 + a_w > grid_w - 1:
        spans.pop()
    span = "".join(f" · {sp}" for sp in spans)
    tx = _put(overlays, left + 1, 0, title, A if month_offset else T, bold=True,
              max_x=graph_w)
    if span:
        tx = _put(overlays, tx, 0, span, T, max_x=graph_w)
    if aside:
        _put(overlays, tx, 0, aside, D, max_x=graph_w)

    # Weekday header, dim, one label over each column of numbers.
    day_names = table_for(DAY_NAMES, lang)
    for c in range(7):
        label = _clip(day_names[(start + c) % 7], cell_w - 2)
        _put(overlays, left + c * cell_w + 1, 1, label, F, max_x=graph_w)

    # The days.
    for day in range(1, days_in + 1):
        d = first + timedelta(days=day - 1)
        slot = lead + day - 1
        wk, c = divmod(slot, 7)
        x0 = left + c * cell_w
        y0 = row0 + wk * cell_h
        noon = datetime.combine(d, time(12), tzinfo=tzinfo)
        illum = moon_illumination(noon)
        principal = phase_days.get(d)

        # Today's whole cell sits on a faintly moonlit field — the way a
        # printed calendar rings the day — since a glow behind a disc
        # this small has no room to show.
        if d == today:
            for spy in range(y0 * 2, (y0 + cell_h) * 2):
                for x in range(x0, x0 + cell_w):
                    fb.set_pixel(x, spy, moon_palette.MOON_GLOW_RGB, 0.16)

        # The disc: an icon of the day's phase, waxing lit on the right
        # (mirrored south of the equator).
        cx = x0 + cell_w // 2
        cy = y0 * 2 + cell_h
        if radius >= 2.0:
            waxing = moon_cycle_frac(noon) < 0.5
            limb = 90.0 if waxing else 270.0
            if lat is not None and lat < 0:
                limb = 360.0 - limb
            disc._draw_moon_disc(fb, cx, cy, radius, illum, limb, 0.0,
                                 night=moon_palette.MOON_NIGHT_RGB, aspect=aspect)
            if mirrored:
                # The grid reads from the right; the Moon is still the
                # Moon, so it is drawn flipped for the row's flip to undo
                fb.flip_columns(x0, x0 + cell_w, y0 * 2, (y0 + cell_h) * 2)
        elif cell_h > 1 or cell_w >= 6:
            # No room to draw: the phase glyph stands in for the disc.
            # On a one-row cell it sits a space after where a two-digit
            # day number ends, beside its own number rather than the
            # next day's, and a cell too narrow for both keeps the number.
            icon = moon_phase(noon, runtime)[2]
            gx = cx if cell_h > 1 else x0 + 4
            _put(overlays, gx, y0 + cell_h // 2, icon, T, max_x=graph_w)

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
            label = _cell_label(
                d, cal, native, fest, lang, israel,
                principal[1] if principal and principal[0] == 0 else None)
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

        # A calendar that counts its own days sets the day's number in
        # the far corner, faint, the way the dual wall calendars print
        # the other calendar's date small beside the civil one. A
        # month's opening day carries the month's name in front of its
        # 1, so the count and the name change together; the title says
        # which months the numbers belong to.
        right_w = 0
        if cal in ("hebrew", "islamic") and cell_h >= 3 and cell_w >= 6:
            if cal == "hebrew":
                oy, om, od = hebrew_date(d)
                name = hebrew_month_name(oy, om)
            else:
                _oy, om, od = hijri_date(d)
                name = hijri_month_name(om, lang)
            text = _corner_text(od, name, cell_w - 2)
            right_w = visible_len(text)
            _put(overlays, x0 + cell_w - 1 - right_w,
                 y0 + cell_h - 1, text, F, max_x=graph_w)

        # A Solar Hijri month sets the Gregorian day in the other
        # corner, the way Iran's wall calendars print it small beside
        # the solar one, the month's name with its 1. A calendar that
        # labels every day along the bottom edge keeps that edge, and
        # the Gregorian date waits in the hover.
        if (civil == SOLAR_HIJRI and cell_h >= 3 and cell_w >= 6
                and not (cal in PACIFIC_CALENDARS
                         or (cal == "chinese" and native))):
            room = cell_w - 2 - (right_w + 1 if right_w else 0)
            text = _corner_text(d.day, table_for(MONTHS, lang)[d.month - 1],
                                room)
            if visible_len(text) <= room:
                _put(overlays, x0 + 1, y0 + cell_h - 1, text, F, max_x=graph_w)

    if fullscreen:
        from linecast.terminal.help import paint_hint
        paint_hint(fb, overlays, lang)
    lines = fb.render(overlays=overlays)
    if hint:
        lines.append(hint)

    # Hover: the chip for the day under the pointer.
    chip = ""
    if mouse_pos:
        d = clicked_day(*mouse_pos)
        if d is not None:
            chip = _hover_chip(d, context(now_local, lat, lng, runtime, cal, israel),
                               reading(cal), phase_days, mouse_pos, cols, rows)
    return overlay("\n".join(lines), chip)


def _corner_text(day, month_name, room):
    """A corner's day number, with its month's name in front on the 1st
    when at least three letters of it fit in *room* cells."""
    text = str(day)
    if day == 1:
        name_room = room - len(text) - 1
        if name_room >= 3:
            text = f"{_clip(month_name, name_room)} {text}"
    return text


_last_grid = None   # geometry of the last rendered grid, for clicked_day


def clicked_day(col, row):
    """The date under a 1-based terminal cell, from the last rendered grid.

    None off the grid, or before any grid has been drawn. The same
    mapping serves the hover chip, so a click opens exactly the day the
    chip was reading.
    """
    if _last_grid is None:
        return None
    left, row0, cell_w, cell_h, weeks, lead, days_in, first, _civil = _last_grid
    gx, gy = col - 1 - left, row - 1 - row0
    if not (0 <= gx < cell_w * 7 and 0 <= gy < cell_h * weeks):
        return None
    day = (gy // cell_h) * 7 + gx // cell_w - lead + 1
    if 1 <= day <= days_in:
        return first + timedelta(days=day - 1)
    return None


def _hover_chip(d, ctx, found, phase_days, mouse_pos, cols, rows):
    """The hovered day, read in full: date, phase, rise and set, calendar.

    *found* is the calendar's reading (moon.readings), or None for none."""
    runtime, lang = ctx.runtime, ctx.lang
    tzinfo = ctx.now_local.tzinfo
    noon = datetime.combine(d, time(12), tzinfo=tzinfo)
    illum = moon_illumination(noon)
    principal = phase_days.get(d)
    night_name = found.night_name(d, ctx) if found else None

    tip_bg = bg(*TIP_BG_RGB)
    tip_fg = fg(*TIP_TEXT_RGB)
    tip_dim = fg(*TIP_DIM_RGB)

    head = f"{_day_abbrev(noon, runtime)} {_fmt_month_day(noon, runtime)}"
    ahead = (d - ctx.today).days
    if ahead > 0:
        head += f" · {_ms('in_days', runtime, days=str(ahead))}"
    # Solar Hijri dates keep the Gregorian date a line below, dim.
    gregorian = (gregorian_date_label(d, lang)
                 if civil_calendar(lang) == SOLAR_HIJRI else None)

    if principal:
        idx, at = principal
        name = night_name or moon_name(idx, runtime)
        if idx == 4 and lang == "en" and (found is None or found.full_moon_names):
            mn = full_moon_name(at, SYNODIC_MONTH)
            name = "Blue Moon" if mn == "Blue" else f"Full {mn} Moon"
        lit_moon = found.new_moon_name(at) if found and idx == 0 else None
        if lit_moon:
            name = lit_moon
        icon = moon_phase(at, runtime)[2]
        phase_line = (f"{icon} {name} · "
                      f"{fmt_time_dt(at, use_24h=runtime.use_24h)}")
    else:
        idx, _name, icon = moon_phase(noon, runtime)
        name = night_name or moon_name(idx, runtime)
        phase_line = (f"{icon} {name} · "
                      f"{_ms('illuminated', runtime, pct=f'{illum * 100:.0f}')}")

    rise, sset = _moon_events_for_local_date(d, ctx.lat, ctx.lng, tzinfo)

    def _t(dt):
        return fmt_time_dt(dt, use_24h=runtime.use_24h) if dt else "—"

    events = f"↑ {_t(rise)}  ↓ {_t(sset)}"
    cal_line = found.hover(d, ctx) if found else None

    tip_lines = [f"{tip_bg}{tip_fg} {head} "]
    if gregorian:
        tip_lines.append(f"{tip_bg}{tip_dim} {gregorian} ")
    tip_lines += [
        f"{tip_bg}{tip_fg} {phase_line} ",
        f"{tip_bg}{tip_dim} {events} ",
    ]
    if cal_line:
        tip_lines.append(f"{tip_bg}{tip_fg} {cal_line} ")
        note = found.hover_note(ctx)
        if note:
            tip_lines.append(f"{tip_bg}{tip_dim} {note} ")

    return _live.pointer_chip(tip_lines, mouse_pos[0] + 2, mouse_pos[1],
                              cols, rows, pad_bg=tip_bg)
