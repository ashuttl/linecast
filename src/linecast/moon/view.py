"""Moon phase, illumination, and rise/set times.

Usage: moon [--print] [--oneline] [--json] [--month] [--location PLACE] [--icons SET] [--emoji]
            [--lang CODE]

Renders the Moon itself — a shaded disc with the correct phase terminator,
mare shading, and a soft halo over a star field — in the middle of the sky,
with the info in its four corners: the current phase and illuminated
fraction, and a small table of what comes next for each of the Moon's
cycles. The day's opens with whether the Moon is up right now and lists the
next moonrise and moonset; the month's opens with the Moon's age and lists
the next new and full moons; the year's opens with the day of the year and
lists the next equinox or solstice. Each row gives the name, the time or
date, and how long until then. In English the full moon carries its
traditional almanac name (Harvest Moon and the rest), and a traditional
calendar adds its months and festivals to the tables.
The disc is drawn as the observer would see it. Its tilt in the sky is the
Moon's parallactic angle — near pole-up from the north, close to "upside
down" from the south, and turning steadily between moonrise and moonset —
and the terminator lies square to the bright limb, which points at the Sun.

Times and positions come from `astro/ephemeris.py`, which is good to a couple
of arcminutes: the principal phases land within a quarter of an hour of
the published ones, which is the accuracy an almanac is read at.

In live mode `v` flips to a month-calendar view of the phases (see
`moon/calendar.py`); the wheel or arrows page months there, space
returns to this month, and clicking a day opens it in the disc view.
In the disc view `t` puts the text away, leaving the Moon alone in its
sky, and brings it back.
"""

import calendar
import math
import textwrap
import threading
from datetime import datetime, timedelta, timezone
from typing import NamedTuple

from linecast._timefmt import fmt_time_dt
from linecast.terminal.textwidth import cells, pad, visible_len, wrap_display_width
from linecast.terminal.framebuffer import get_terminal_size, cell_aspect, Framebuffer
from linecast._i18n import GEOCODER_UNTRANSLATED, fmt_decimal, fmt_duration_parts, lang_of
from linecast._config import saved_location
from linecast._location import (
    location_is_pinned, location_overridden,
    location_tzinfo, machine_tzinfo,
)
from linecast.astro.calendars.lunisolar import resolve_calendar
from linecast.moon.i18n import (
    _day_abbrev, _fmt_month_day, _ms, _season_label, solar_hijri_observance_name,
    year_turn_label,
)
from linecast._i18n import moon_name
from linecast.astro.calendars.civil import (
    SOLAR_HIJRI, civil_calendar, solar_hijri_day_of_year,
)
from linecast.astro.seasons import full_moon_name, next_season_event
from linecast.tides.i18n import _ts  # shared "space to return to now" hint
from linecast._runtime import RuntimeConfig, install_banner, place_for, set_current
from linecast._parsers import moon_parser, refuse_view_flag
from linecast.terminal import theme as _theme
from linecast.radar.i18n import compass_point, rs
from linecast.astro.ephemeris import (
    _moon_altitude_deg, _moon_azimuth_deg, _moon_parallactic_deg, _moon_ra_dec,
    moon_age_days, moon_axis_deg, moon_bright_limb_deg, precess_to_j2000,
)
from linecast.moon.disc import _draw_moon_disc
from linecast.moon.stars import star_overlays
from linecast.moon.palette import (
    MOON_GLOW_RGB, MOON_NIGHT_RGB, PANEL_AMBER_RGB, PANEL_DIM_RGB, PANEL_MUTED_RGB,
    PANEL_PURPLE_RGB, PANEL_TEXT_RGB, SKY_RGB,
)
from linecast.moon.readings import Instant, Now, Panel, context, reading
from linecast.moon.phase import (
    HORIZON_THRESHOLD_DEG, SYNODIC_MONTH, moon_illumination, moon_phase,
    next_phase_local, upcoming_moon_events,
)

_theme.track_imports(globals(), "linecast.moon.palette")


def _fmt_countdown(delta, lang="en"):
    """`48m`, `6h 56m`, `2d 4h` — how long until an event, in the
    language's own form (_i18n.fmt_duration_parts)."""
    minutes = max(0, int(delta.total_seconds() // 60))
    if minutes < 60:
        return fmt_duration_parts(lang, ("m", minutes))
    if minutes < 60 * 24:
        return fmt_duration_parts(lang, ("h", minutes // 60), ("m", minutes % 60))
    return fmt_duration_parts(lang, ("d", minutes // 1440), ("h", (minutes % 1440) // 60))


# How far ahead the turn of the Solar Hijri year is counted down: the
# month before Nowruz, when the preparations begin (خانه‌تکانی, the
# sabzeh set to sprout), and Chaharshanbe Suri falls.
YEAR_TURN_WINDOW = timedelta(days=30)


def next_year_turn(now_local):
    """(Solar Hijri year, UTC instant) of the next تحویل سال after
    *now_local*: the March equinox that begins the year."""
    from linecast.astro.calendars import solar_hijri
    now_utc = now_local.astimezone(timezone.utc)
    year = solar_hijri.solar_hijri_date(now_local.date())[0]
    for yy in (year, year + 1):
        moment = solar_hijri.nowruz_utc(yy)
        if moment > now_utc:
            return yy, moment
    return year + 2, solar_hijri.nowruz_utc(year + 2)


def _fmt_clock(delta):
    """`5:12:08` — hours, minutes, and seconds until an event."""
    seconds = max(0, int(delta.total_seconds()))
    return f"{seconds // 3600}:{seconds // 60 % 60:02d}:{seconds % 60:02d}"


class _Row(NamedTuple):
    """Something the panel counts down to: its name, when it falls, and
    how long until then, in the row's ink. *at* orders a table's rows;
    *mark* is a (glyph, rgb) hung just before the time."""
    at: datetime
    label: str
    when: str
    wait: str
    ink: tuple
    mark: tuple | None = None


def _in_order(rows):
    return sorted(rows, key=lambda row: row.at)


def _sentence(text):
    """*text* with its first letter capitalised, for a phrase that also
    runs mid-line in lower case ("day 16.9 of 29.5") set as a heading."""
    return text[:1].upper() + text[1:]


def _table(head, rows, wait=True):
    """Panel lines for one corner: its heading lines, then its rows as a
    table, all flush left, the name, the date or time, and the wait each
    in a column of its own. A row's mark (the rising and setting arrows)
    hangs just before its time, as the weather view writes ↑06:40, in a
    cell the unmarked rows leave empty so every date starts in the same
    column. *wait* False drops the waits, for a small terminal.
    """
    label_w = max((visible_len(r.label) for r in rows), default=0)
    when_w = max((visible_len(r.when) for r in rows), default=0)
    gutter = any(r.mark for r in rows)
    lines = list(head)
    for row in rows:
        line = [(pad(row.label, label_w), row.ink, False), ("  ", row.ink, False)]
        if gutter:
            glyph, color = row.mark or (" ", row.ink)
            line.append((glyph, color, False))
        line.append((pad(row.when, when_w), row.ink, False))
        if wait and row.wait:
            line.append((f"  {row.wait}", row.ink, False))
        last, color, bold = line[-1]
        line[-1] = (last.rstrip(), color, bold)
        lines.append(line)
    return lines


class _RowMaker:
    """The panel's _Rows, as counted from one moment.

    The ink says how near a row is: the day's rows, and anything else
    due within a day, in full; the rest muted. A wait is taken from the
    moment in UTC: two times in the one zone subtract as wall clocks, an
    hour out across a change of clock.
    """

    def __init__(self, now_local, moment_utc, runtime):
        self.now_local = now_local
        self.moment_utc = moment_utc
        self.runtime = runtime
        self.lang = lang_of(runtime)
        self.today = now_local.date()

    def _ink(self, at):
        return PANEL_TEXT_RGB if at - self.moment_utc < timedelta(days=1) else PANEL_MUTED_RGB

    def timed(self, label, dt, mark):
        """An instant within a day or two: the clock time, the weekday
        once it is not today's, and the wait to the minute."""
        runtime = self.runtime
        if dt is None:
            return _Row(self.now_local + timedelta(days=36500), label, "—", "",
                        PANEL_TEXT_RGB, mark)
        when = fmt_time_dt(dt, use_24h=runtime.use_24h)
        if dt.date() != self.today:
            when = f"{when} {_day_abbrev(dt, runtime)}"
        wait = _ms('in_time', runtime, dur=_fmt_countdown(dt - self.moment_utc, self.lang))
        return _Row(dt, label, when, wait, PANEL_TEXT_RGB, mark)

    def instant(self, label, dt):
        """An instant further off: the date, and the wait in days to a
        tenth, which says roughly when in the day.  Within the day the
        wait is to the minute, as the day's rows give it: the last hour
        before a full moon is not "in 0.0d"."""
        runtime = self.runtime
        wait = dt - self.moment_utc
        if wait < timedelta(days=1):
            wait_txt = _ms('in_time', runtime, dur=_fmt_countdown(wait, self.lang))
        else:
            wait_txt = _ms('in_days', runtime,
                           days=fmt_decimal(wait.total_seconds() / 86400.0, 1, runtime))
        return _Row(dt, label, _fmt_month_day(dt, runtime), wait_txt, self._ink(dt))

    def day(self, label, day, wait=None):
        """Something kept on a day — a festival, a month's first day:
        the date, and the wait in whole days."""
        at = datetime.combine(day, datetime.min.time(), self.now_local.tzinfo)
        gap = (day - self.today).days
        return _Row(at, label, _fmt_month_day(day, self.runtime),
                    wait or _ms('in_days', self.runtime, days=str(gap)),
                    self._ink(at))


def solar_hijri_rows(now_local, runtime):
    """(observance kept today, rows) for the panel where the dates are
    Solar Hijri; the first may be None.

    The rows are the next of the year's observances — Mehregan, Yalda,
    Sadeh, Chaharshanbe Suri, Sizdah Bedar, Tirgan — counted in days
    like the other calendars' festivals, and within YEAR_TURN_WINDOW of
    Nowruz the year's turn, counted down to the equinox itself, to the
    second on its last day, for which Nowruz's own row gives way. An
    observance on its day is named alone, as where the year stands.
    """
    from linecast.astro.calendars import solar_hijri
    lang = lang_of(runtime)
    today = now_local.date()
    rows = []
    turn_year, turn_utc = next_year_turn(now_local)
    left = turn_utc - now_local.astimezone(timezone.utc)
    if left <= YEAR_TURN_WINDOW:
        at = turn_utc.astimezone(now_local.tzinfo)
        clock = (at.strftime("%H:%M:%S") if runtime.use_24h
                 else fmt_time_dt(at, use_24h=False))
        when = clock if at.date() == today else f"{_fmt_month_day(at, runtime)} {clock}"
        if left < timedelta(days=1):
            wait = _ms('in_time', runtime, dur=_fmt_clock(left))
        else:
            wait = _ms('in_days', runtime, days=str((at.date() - today).days))
        rows.append(_Row(at, year_turn_label(turn_year, lang), when, wait,
                         PANEL_AMBER_RGB))

    day, key = solar_hijri.next_observance(today)
    if key == "nowruz" and rows:
        return None, rows
    name = solar_hijri_observance_name(key, lang)
    gap = (day - today).days
    if gap == 0:
        return name, rows
    rows.append(_Row(datetime.combine(day, datetime.min.time(), now_local.tzinfo),
                     name, _fmt_month_day(day, runtime),
                     _ms('in_days', runtime, days=str(gap)), PANEL_TEXT_RGB))
    return None, rows


def place_credit(lat, lng, place, runtime):
    """`Westbrook, Maine · 43.68° N, 70.37° W`: the place the sky is
    computed for, as the help panel credits it — its name where there
    is one, and always its coordinates, with the compass letters in the
    display language."""
    points = rs("compass", lang_of(runtime)).split()
    coords = (f"{fmt_decimal(abs(lat), 2, runtime)}° {points[0 if lat >= 0 else 4]}, "
              f"{fmt_decimal(abs(lng), 2, runtime)}° {points[2 if lng >= 0 else 6]}")
    return f"{place} · {coords}" if place else coords


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------
def _wrap(text, width, least=None):
    """textwrap.wrap without widows: no lone word on the last line.

    With *least*, the text takes as few lines as *width* allows but is
    set no wider than those lines need, and never narrower than *least*
    — so a counsel that fits beside the table keeps to its edge.  Text
    with a wide glyph in it is measured in cells, as it is drawn.
    """
    if visible_len(text) == len(text):
        wrap = textwrap.wrap
    else:
        wrap = wrap_display_width
    if least is not None and least < width:
        count = len(wrap(text, width))
        width = next(w for w in range(least, width + 1)
                     if len(wrap(text, w)) <= count)
    lines = wrap(text, width)
    if len(lines) > 1 and " " not in lines[-1]:
        head, last = lines[-2].rsplit(" ", 1)
        lines[-2:] = [head, f"{last} {lines[-1]}"]
    return lines


def _panel_overlays(panel, x0, row0, graph_w):
    """Character overlays for a block of the panel's lines.

    *panel* is a list of lines, each a list of (text, rgb, bold)
    segments, laid out by textwidth.cells to the screen's edge.  Each
    line also claims a clear cell at either end, so no star touches the
    text, and a blank line between two others keeps the sky clear as far
    as both reach, so no star lands among the text as if it were part
    of it.
    """
    overlays = {}
    for i, segments in enumerate(panel):
        if not segments and 0 < i < len(panel) - 1:
            reach = min(_seg_w(panel[i - 1]), _seg_w(panel[i + 1]))
            for x in range(max(0, x0 - 1), min(graph_w, x0 + reach + 1)):
                overlays[(x, row0 + i)] = (" ", PANEL_DIM_RGB, False)
            continue
        x = x0
        if segments and x0 > 0:
            overlays[(x0 - 1, row0 + i)] = (" ", segments[0][1], False)
        for text, color, bold in segments:
            laid, used = cells(text, graph_w - x)
            for col, glyph in laid:
                overlays[(x + col, row0 + i)] = (glyph, color, bold)
            x += used
        if segments and x < graph_w:
            overlays[(x, row0 + i)] = (" ", segments[-1][1], False)
    return overlays


def _seg_w(segments):
    """The cells a panel line's (text, rgb, bold) segments take."""
    return sum(visible_len(t) for t, _c, _b in segments)


def _block_w(block):
    return max(map(_seg_w, block), default=0)


def _place_corners(tl, tr, bl, br, graph_w, graph_h):
    """Overlays for the four corners, or None if they will not fit:
    each block against its corner, or, where a pair will not share
    its rows, the right-hand one beneath the left, flush left."""
    room = graph_w - 2
    if max(map(_block_w, (tl, tr, bl, br))) > room:
        return None
    spots = []
    if _block_w(tl) + 2 + _block_w(tr) <= room:
        spots += [(tl, 1, 0), (tr, graph_w - 1 - _block_w(tr), 0)]
        top_h = max(len(tl), len(tr))
    else:
        spots += [(tl, 1, 0), (tr, 1, len(tl))]
        top_h = len(tl) + len(tr)
    if _block_w(bl) + 2 + _block_w(br) <= room:
        spots += [(bl, 1, graph_h - len(bl)),
                  (br, graph_w - 1 - _block_w(br), graph_h - len(br))]
        bottom_h = max(len(bl), len(br))
    else:
        spots += [(bl, 1, graph_h - len(bl) - len(br)), (br, 1, graph_h - len(br))]
        bottom_h = len(bl) + len(br)
    if top_h + bottom_h > graph_h:
        return None
    overlays = {}
    for block, x, row in spots:
        if block:
            overlays.update(_panel_overlays(block, x, row, graph_w))
    return overlays


def _fit_corners(forms, graph_w, graph_h, aspect):
    """(radius, overlays): the disc's radius in cells across, and the
    corners' text, for the form the panel takes.

    *forms* runs from the most said to the least, each a (share, make)
    pair: *make* gives the four corners' blocks, and *share* is how much
    of its bare size that form must leave the Moon. *aspect* is a
    sub-pixel's height in cell widths.

    The radius is measured in cells across.  A sub-pixel is half a cell
    tall, which is a cell width only when the font's cell is twice as
    tall as it is wide; on the cell it really has, a sub-pixel stands
    *aspect* cell widths, and the disc's height in sub-pixels is its
    radius over that. Bare, it takes ~82% of the sky's height, or its
    width less a margin; the corners' text keeps two cells of sky
    between it and the limb.

    The first form that leaves the Moon its share wins; if none does,
    the one that leaves it the most. Then the fullest form that leaves
    it as much: where what stays (the counsel beside a long headline)
    is what holds the Moon in, shedding the rest would not enlarge it.
    """
    cx, cy = graph_w // 2, graph_h
    bare = min(graph_h * 2 * 0.41 * aspect, graph_w * 0.5 - 3.0)

    def disc_room(overlays):
        radius = bare
        for x, row in overlays:
            dy = min(abs(2 * row - cy), abs(2 * row + 1 - cy)) * aspect
            radius = min(radius, math.hypot(x - cx, dy) - 2.0)
        return radius

    best = None
    tried = []
    for share, form in forms:
        overlays = _place_corners(*form(), graph_w, graph_h)
        if overlays is None:
            continue
        radius = disc_room(overlays)
        tried.append((radius, overlays))
        if radius >= share * bare:
            best = (radius, overlays)
            break
        if best is None or radius > best[0]:
            best = (radius, overlays)
    if best:
        best = next(fit for fit in tried if fit[0] >= best[0])
    radius, overlays = best if best else (bare, {})
    return max(4.0, radius), overlays


def _place_help(overlays, graph_w, graph_h, lang):
    """Add the help hint to *overlays*: under the Moon, between the
    month and the year, or in a free corner when they leave no room
    there, in the dim ink: it points at the information, so it must not
    outrank it. It sits on the plain sky, which needs no lift for
    contrast."""
    from linecast.terminal.help import hint as help_label
    label = help_label(lang, graph_w - 2)
    width = visible_len(label)
    spots = [((graph_w - width) // 2, graph_h - 1, 3)] + [
        (x, row, 1) for row in (graph_h - 1, 0, graph_h - 2, 1)
        for x in (graph_w - width - 1, 1)]
    for x, row, air in spots:
        if x >= 1 and not any((c, row) in overlays
                              for c in range(x - air, x + width + air)):
            overlays.update(_panel_overlays([[(label, PANEL_DIM_RGB, False)]], x, row,
                                            graph_w))
            break


def keeps_israel_days(country, lat, lng):
    """Whether the viewed place keeps the Hebrew holidays as Israel does.

    The second day of Yom Tov is a rule about where the reader is, so
    the answer is the country of the location shown, not the user's
    own. resolve_location leaves the country blank for an override, so
    it is reverse geocoded then (cached); still blank, as offline with
    a cold cache, stays diaspora.
    """
    if not country:
        from linecast._geocode import reverse_geocode
        _name, country, _addr = reverse_geocode(lat, lng)
    return (country or "").upper() == "IL"


class _Facts(NamedTuple):
    """The Moon at one moment, seen from one place: what the sky says
    about it, before the panel puts any of it into words."""
    moment_utc: datetime
    phase: int              # moon_phase's index: 0 new, 2 first quarter, 4 full
    icon: str
    illum: float            # the lit fraction of the disc
    age: float              # days since the new moon
    alt: float              # degrees above the horizon
    up: bool
    bearing: str            # the compass point it stands over, in the display language
    limb: float             # where the bright limb and the Moon's north
    axis: float             # pole point on screen, in degrees
    sky: tuple              # (ra, dec, parallactic), placing it among the stars
    rise: datetime | None   # the next moonrise and moonset
    sset: datetime | None
    full: datetime          # the next full and new moons
    new: datetime
    season: str             # the next equinox or solstice, and when it falls
    season_at: datetime


def _moon_facts(now_local, lat, lng, runtime):
    """The Moon's _Facts at *now_local*, seen from *lat*, *lng*, its
    times in *now_local*'s zone."""
    idx, _name, icon = moon_phase(now_local, runtime)
    moment_utc = now_local.astimezone(timezone.utc)
    alt = _moon_altitude_deg(moment_utc, lat, lng)
    # Where the bright limb and the Moon's north pole fall on screen.
    # Position angles run from celestial north through east, which is
    # anticlockwise with north up; the parallactic angle then says how
    # far celestial north itself is turned from the observer's vertical.
    parallactic = _moon_parallactic_deg(moment_utc, lat, lng)
    rise, sset = upcoming_moon_events(now_local, lat, lng)
    season, season_utc = next_season_event(now_local)
    return _Facts(
        moment_utc=moment_utc, phase=idx, icon=icon,
        illum=moon_illumination(now_local),
        age=moon_age_days(moment_utc),
        alt=alt, up=alt > HORIZON_THRESHOLD_DEG,
        bearing=compass_point(_moon_azimuth_deg(moment_utc, lat, lng), lang_of(runtime)),
        limb=parallactic - moon_bright_limb_deg(moment_utc),
        axis=parallactic - moon_axis_deg(moment_utc),
        # The stars about the Moon, the Moon put in the catalogue's J2000 frame.
        sky=(*precess_to_j2000(*_moon_ra_dec(moment_utc), moment_utc), parallactic),
        rise=rise, sset=sset,
        full=next_phase_local(moment_utc, 0.5, now_local),
        new=next_phase_local(moment_utc, 0.0, now_local),
        season=season, season_at=season_utc.astimezone(now_local.tzinfo),
    )


class _Corners(NamedTuple):
    """What the panel says, before it is fitted round the Moon: what
    the Moon is (its headline, how much of it is lit, and a calendar's
    counsel), and a table each for the day, the month and the year,
    their heading lines over their _Rows (see _table)."""
    headline: list          # (text, rgb, bold): the phase, and an aside
    illum: str
    counsel: list           # the calendar's counsel, and the line that credits it
    source: str | None
    day_head: list
    day_rows: list
    month_head: list
    month_rows: list
    year_head: list
    year_rows: list
    back: str | None        # the way back to now, while scrubbed

    def what(self, short):
        """The phase line and the illumination, and the calendar's
        counsel beneath, which reads the night the headline names: in
        as few lines as a readable measure allows, and no wider than
        those lines need."""
        top = self.headline[:1] if short else self.headline
        block = [top, [(self.illum, PANEL_MUTED_RGB, False)]]
        if self.counsel:
            least = max(_seg_w(top), 28)
            block.append([])
            block += [[(seg, PANEL_MUTED_RGB, False)] for txt in self.counsel
                      for seg in _wrap(txt, max(int(least * 1.3), 48), least)]
            if self.source:
                # The source rides directly under the counsel it
                # credits, a shade fainter.
                block.append([(self.source, PANEL_DIM_RGB, False)])
        return block

    def day(self, wait):
        block = _table(self.day_head, _in_order(self.day_rows), wait)
        if self.back is not None:
            block.append([(self.back, PANEL_MUTED_RGB, False)])
        return block

    def month(self, wait):
        return _table(self.month_head, _in_order(self.month_rows), wait)

    def year(self, wait):
        return _table(self.year_head, _in_order(self.year_rows), wait)

    def forms(self):
        """From the most said to the least: each form is the four
        corners, and the share of its bare size it must leave the Moon
        (see _fit_corners). The rising and setting are the last to go:
        they may take the disc down to half its size, where the rest
        must leave it seven tenths."""
        return [
            (0.7, lambda: (self.what(False), self.day(True),
                           self.month(True), self.year(True))),
            (0.7, lambda: (self.what(False), self.day(False),
                           self.month(False), self.year(False))),
            (0.7, lambda: (self.what(False), self.day(False), self.month(False), [])),
            (0.5, lambda: (self.what(True), self.day(False), [], [])),
            (0.5, lambda: (self.what(True), self.day_head[:1], [], [])),
            (0.0, lambda: ([self.headline[:1]], [], [], [])),
        ]


def _corners(moon, found, ctx, offset_minutes):
    """The panel's _Corners for the Moon's _Facts *moon*, read through
    calendar *found* (moon.readings; None for none) at *ctx*, scrubbed
    *offset_minutes* from now."""
    now_local, lat, runtime, lang = ctx.now_local, ctx.lat, ctx.runtime, ctx.lang
    T, M = PANEL_TEXT_RGB, PANEL_MUTED_RGB
    A, P = PANEL_AMBER_RGB, PANEL_PURPLE_RGB

    # The headline is the calendar's: the night's name where the
    # calendar names nights, and the lunar date or the almanac's half
    # of the month as an aside. The one-line summary shows the same.
    cal_name, lunar_txt = found.headline(ctx) if found else (None, None)
    name = cal_name or moon_name(moon.phase, runtime)
    # The Old Farmer's Almanac names for the full moon are an English-
    # language tradition: they show in English by default and with the
    # almanac calendar, but a panel reading the moon through another
    # tradition's calendar keeps the plain phase name — Harvest Moon
    # is the almanac's name, not the Kaulana Mahina's or the 农历's.
    full_label = moon_name(4, runtime)
    if lang == "en" and (found is None or found.full_moon_names):
        folk_name = full_moon_name(moon.full, SYNODIC_MONTH)
        full_label = ("Blue Moon" if folk_name == "Blue"
                      else f"Full {folk_name} Moon")
    # The Icelandic almanac prints a named moon's name at the new moon
    # that lights it, as the English almanacs name the full moons.
    new_label = (found.new_moon_name(moon.new) if found else None) or moon_name(0, runtime)

    # Out of this month's own length, from the new moon before to the one
    # after: months run 29.3 to 29.8 days, and a mean 29.5 under an age
    # of 29.8 is a day past the end
    lunation = moon.age + (moon.new - moon.moment_utc).total_seconds() / 86400.0
    age_txt = _ms('age', runtime, age=fmt_decimal(moon.age, 1, runtime),
                  total=fmt_decimal(lunation, 1, runtime))
    year_n = now_local.timetuple().tm_yday
    year_len = 366 if calendar.isleap(now_local.year) else 365

    # Everything the panel counts down to has one shape: a name, when it
    # falls, and how long until then. Each is a _Row, and the rows are
    # set as small tables (see _table), one in a corner for each of the
    # Moon's cycles: the day (its rising and setting), the month (the
    # principal phases), and the year (the season and the calendar's
    # days). A table opens with where the present stands in its cycle;
    # something a calendar keeps today joins that line rather than
    # counting down to itself.
    make = _RowMaker(now_local, moon.moment_utc, runtime)
    day_rows = [make.timed(_ms('moonrise', runtime), moon.rise, ("↑", A)),
                make.timed(_ms('moonset', runtime), moon.sset, ("↓", P))]
    month_rows = [make.instant(full_label, moon.full), make.instant(new_label, moon.new)]
    year_rows = [make.instant(_season_label(moon.season, lat, runtime), moon.season_at)]
    month_now, year_now = [], []    # (text, rgb): what the calendar keeps today

    # Where the dates are Solar Hijri the day of the year is too, and the
    # year's own observances join the calendar's rows.
    if civil_calendar(lang) == SOLAR_HIJRI:
        year_n, year_len = solar_hijri_day_of_year(now_local)
        fest_now, rows = solar_hijri_rows(now_local, runtime)
        if fest_now:
            year_now.append((fest_now, T))
        year_rows += rows

    # The traditional calendar: on by default for the languages whose
    # readers know the moon through it, and available to anyone with
    # --calendar or `linecast calendar`. Each calendar's reading says
    # what it adds (moon/readings/): where the month and the year stand
    # in it, the days and instants it counts down to, and any counsel
    # under the phase, the Kaulana Mahina's for fishing or the Old
    # Farmer's for the garden.
    extra = found.panel(ctx) if found else Panel()
    if found and found.plain_age:
        age_txt = _ms('lunar_age', runtime, age=fmt_decimal(moon.age, 1, runtime))
    for items, stands, rows in ((extra.month, month_now, month_rows),
                                (extra.year, year_now, year_rows)):
        for item in items:
            if isinstance(item, Now):
                stands.append((item.text, T if item.today else M))
            elif isinstance(item, Instant):
                rows.append(make.instant(item.label, item.at))
            else:
                rows.append(make.day(item.label, item.day, item.wait))

    def heading(first, extras):
        segments = [first]
        for text, color in extras:
            segments += [(" · ", M, False), (text, color, False)]
        return segments

    below_txt = _ms('below_horizon', runtime)
    if offset_minutes:
        # Scrubbed away from the present: lead with the simulated moment
        # ("Up now" would lie), and show how to get back.
        when_txt = (f"{_day_abbrev(now_local, runtime)} "
                    f"{_fmt_month_day(now_local, runtime)} "
                    f"{fmt_time_dt(now_local, use_24h=runtime.use_24h)}")
        alt_txt = _ms('above_horizon', runtime, alt=f'{moon.alt:.0f}')
        day_head = [[(when_txt, A, False)],
                    [(f"{alt_txt} · {moon.bearing}", T, False)] if moon.up
                    else [(below_txt, M, False)]]
    elif moon.up:
        # After "Up now" the long phrase is redundant — being up is the
        # whole claim — so the altitude goes short and spends the room
        # on where to actually look.
        day_head = [[(_ms('up_now', runtime), A, False),
                     (f" · {moon.alt:.0f}° · {moon.bearing}", T, False)]]
    else:
        day_head = [[(below_txt, M, False)]]

    # The headline has room for one aside: the calendar's own — the
    # lunar date, the anahulu, or the almanac's half of the month.
    return _Corners(
        headline=[(f"{moon.icon} {name}", T, True)] + (
            [(f" · {lunar_txt}", T, False)] if lunar_txt else []),
        illum=_ms('illuminated', runtime, pct=f'{moon.illum * 100:.0f}'),
        counsel=[t for t in extra.counsel if t], source=extra.source,
        day_head=day_head, day_rows=day_rows,
        month_head=[heading((_sentence(age_txt), M, False), month_now)],
        month_rows=month_rows,
        year_head=[heading((_ms('year_day', runtime, n=year_n, total=year_len), M, False),
                           year_now)],
        year_rows=year_rows,
        back=_ts('space_to_now', runtime) if offset_minutes else None,
    )


def render(now_local, lat, lng, runtime, fullscreen=False, offset_minutes=0,
           calendar_name=None, israel=False, turn=None, show_text=True):
    """Build the full-screen moon display: disc plus info lines.

    One layout at every size: the Moon in the middle of the sky, and the
    info in its four corners, the disc as large as it can be without
    touching them; a small terminal sheds detail from the corners
    rather than letting lines wrap. *turn* is the live view's Turn,
    the way the user has dragged the disc round, or None. *show_text*
    False leaves the Moon alone in its sky, at its bare size.
    *calendar_name* is the traditional calendar main() resolved, or
    None for none.
    """
    moon = _moon_facts(now_local, lat, lng, runtime)
    rotation = turn.matrix() if turn is not None else None

    cols, rows = get_terminal_size()
    hint = install_banner()
    # Track even a very narrow terminal rather than overflow it; the
    # floor only guards against a degenerate reported size.
    graph_w = max(16, cols)
    # Fullscreen fills the terminal exactly (plus the install banner,
    # when present); the plain print leaves two rows for the prompt.
    reserve = (1 if hint else 0) + (0 if fullscreen else 2)
    graph_h = max(6, rows - reserve)

    # The Moon sits in the middle of the sky and what the panel says
    # sits in its four corners, one piece to each, read in that order:
    # what the Moon is, top left; the day, top right; the month, bottom
    # left; the year, bottom right. The disc is as large as it can be
    # without touching them. In a large terminal that costs it nothing;
    # in a small one the corners give up detail — the waits, then the
    # year, then the month — before the disc gives up much of its size.
    # With the text put away, no corner has anything in it.
    if show_text:
        ctx = context(now_local, lat, lng, runtime, calendar_name, israel)
        forms = _corners(moon, reading(calendar_name), ctx, offset_minutes).forms()
    else:
        forms = [(0.0, lambda: ([], [], [], []))]
    aspect = cell_aspect() / 2.0   # a sub-pixel's height in cell widths
    radius, overlays = _fit_corners(forms, graph_w, graph_h, aspect)
    cx, cy = graph_w // 2, graph_h   # the middle of the sky, in sub-pixels down

    fb = Framebuffer(graph_w, graph_h, bg_color=SKY_RGB)
    if turn is not None:
        turn.radius = radius   # so a drag knows how far a radian is
        turn.aspect = aspect
    fb.draw_radial(cx, cy, MOON_GLOW_RGB, int(radius * 1.7), aspect=aspect,
                   peak_alpha=0.10 + 0.20 * moon.illum)
    _draw_moon_disc(fb, cx, cy, radius, moon.illum, moon.limb, moon.axis, rotation,
                    night=MOON_NIGHT_RGB, aspect=aspect)
    if fullscreen and show_text:
        _place_help(overlays, graph_w, graph_h, lang_of(runtime))
    stars = star_overlays(fb, cx, cy, radius, moon.sky, taken=overlays.keys(),
                          turn=rotation, aspect=aspect)
    from linecast.terminal import bidi as _bidi
    if _bidi.mirrored():
        # The view reads from the right, the panel on the left; the Moon
        # and its stars are a picture, drawn flipped about the disc's
        # centre for the row's flip to undo.
        span = min(cx, graph_w - 1 - cx)
        fb.flip_columns(cx - span, cx + span + 1, 0, fb.total_spy)
        stars = {(2 * cx - x, row): star for (x, row), star in stars.items()
                 if 0 <= 2 * cx - x < graph_w and (2 * cx - x, row) not in overlays}
    lines = fb.render(overlays={**stars, **overlays})
    if hint:
        lines.append(hint)
    return "\n".join(lines)

def main():
    parser = moon_parser()
    args = parser.parse_args()
    runtime = RuntimeConfig.from_sources(args)
    set_current(runtime)

    if args.month:
        refuse_view_flag(parser, "--month", runtime, describes="now")
    lat, lng, country, label, runtime = place_for(args, runtime)

    # A pinned location may sit in another time zone; resolve it so times
    # match the location instead of the machine.
    tz = location_tzinfo(lat, lng) if location_is_pinned(args.location) else machine_tzinfo()

    def _now():
        return datetime.now(tz)

    # The calendar, from the flag, the saved setting, or the language,
    # resolved once here: the views draw every frame with its name.
    # The Hebrew holidays follow the place shown; the check costs a
    # reverse geocode for an override, so only that calendar pays it.
    cal, _source = resolve_calendar(args.calendar, lang_of(runtime))
    israel = cal == "hebrew" and keeps_israel_days(country, lat, lng)

    if runtime.json_mode:
        import json
        from linecast.moon.json import build_payload
        payload = build_payload(_now(), lat, lng, runtime,
                                calendar=args.calendar, israel=israel)
        print(json.dumps(payload, ensure_ascii=False))
        return

    if runtime.oneline:
        from linecast.terminal.oneline import emit
        from linecast.moon.oneline import moon_oneline
        emit(moon_oneline(_now(), lat, lng, runtime, calendar=args.calendar))
        return

    # Both views read from the right in a right-to-left language; the
    # Moon itself, on the disc and in the grid, is never flipped.
    from linecast.terminal import bidi as _bidi
    _bidi.set_mirror(True)

    from linecast.moon.live import MoonApp
    app = MoonApp(_now, lat, lng, runtime, calendar_name=cal, israel=israel,
                  month=args.month, show_text=not args.no_text)
    if not runtime.live:
        from linecast.terminal.live import print_view
        print_view(app.render)
        return

    # Help names the place the Moon is seen from, where the weather's
    # names its sources: a --location by the geocoder's label, a saved
    # location by its own, and an IP location by the (cached) reverse
    # geocoder, as is a typed place in a language the forward geocoder
    # has no names in (_geocode.place_label). It is asked off the loop,
    # so opening help never waits on the network; until it answers, the
    # label or the coordinates stand alone.
    app.place = label
    if not app.place and not location_overridden(args.location):
        app.place = (saved_location() or {}).get("label", "")
    if not app.place or runtime.lang in GEOCODER_UNTRANSLATED:
        threading.Thread(target=app.name_the_place, daemon=True).start()
    app.run()
