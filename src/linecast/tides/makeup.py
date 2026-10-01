"""What a place's tide is made of: its two parts, over three spans of time.

Every tide is a twice-a-day tide and a once-a-day tide added together.
The twice-a-day part is the Moon's and the Sun's pull as the Earth turns
under them, and it swells when the two pull together, at the new and
full Moon, and when the Moon is near.  The once-a-day part comes from
the Moon and the Sun standing north or south of the equator: it is gone
when they cross it and comes back the other way up.  How much of each a
place has is the sea's doing more than the sky's, which is why Portland,
Maine has two even tides a day and Hong Kong, some days, has one.

The view is small multiples.  The two parts are the rows.  The columns
are the month, the year, and the nineteen years the Moon's orbit takes
to swing from its widest tilt to its narrowest and back.  In the month
and the year each part is drawn as its envelope, mirrored about a line
like a sound wave, and all four are on one scale, so the eye can weigh
one part against the other.  Over the nineteen years the change is a
few percent, less than a dot on that scale, so those two are lines on a
scale of their own with their least and their most written under them.

At the left, in the Moon view's manner, are the causes and the height
of each: half the swing from low water to high, and that height against
what the Moon or the Sun alone would raise at this latitude on an Earth
all ocean.  The sea builds some tides up and holds others down, so the
figure may be eleven or it may be less than one.

The constants are fitted to a year of the station's own high and low
waters (harmonic.fit_turns), the same year the year view draws, so the
view asks the source for nothing more.
"""

import calendar
import math
from datetime import date, datetime, timedelta, timezone

from linecast._i18n import DAY_NAMES, MONTHS, fmt_decimal, lang_of, table_for
from linecast.astro.calendars.civil import SOLAR_HIJRI, civil_calendar
from linecast.terminal import live as _live
from linecast.terminal.color import RESET, bg, fg
from linecast.terminal.framebuffer import get_terminal_size
from linecast.terminal.textwidth import cells as text_cells, visible_len, wrap_display_width
from linecast.tides import harmonic
from linecast.tides import palette as _palette
from linecast.tides.i18n import _ts

UTC = timezone.utc
M_PER_FT = 0.3048

# What the Moon and the Sun alone would raise, in metres, before the
# latitude's share: Kowalik and Luick, "Modern Theory and Practice of
# Tide Analysis and Tidal Power" (2019), Table I.5.  A twice-a-day
# constituent takes cos² of the latitude, a once-a-day one sin of twice
# the latitude (Pugh, "Tides, Surges and Mean Sea-Level", 1987, §3:2).
EQUILIBRIUM_M = {"M2": 0.2423, "S2": 0.1128, "N2": 0.0464, "O1": 0.1006, "P1": 0.0468}
# The Moon's share of K1, which the Moon and the Sun raise together
# (Pugh's Table 4:1: 0.3990 lunar, 0.1852 solar)
K1_LUNAR = 0.68
# Below this share of the full pull the latitude gives next to nothing
# to amplify, and the ratio means little: the once-a-day pull at the
# equator, either at the poles
LEAST_PULL = 0.15

# The nineteen years: ten before this one, and eight after
YEARS_BEFORE, YEARS_SPAN = 10, 19
LONG_STEP_DAYS = 30

# The table's rows: (string key, the constituent the row's height and
# its gain are read from).  The once-a-day rows share K1 between them.
TWICE = (("makeup_moon", "M2"), ("makeup_sun", "S2"), ("makeup_distance", "N2"))
ONCE = (("makeup_moon_tilt", "O1"), ("makeup_sun_tilt", "P1"))
# A strip narrower than this cannot carry its axis
LEAST_STRIP = 16

LEFT_COLUMN = (0x01, 0x02, 0x04, 0x40)
RIGHT_COLUMN = (0x08, 0x10, 0x20, 0x80)


def _species(name):
    """How many times a day a constituent comes: its first Doodson number."""
    return harmonic.CONSTITUENTS[name][0][0]


def _daily_amplitudes(tide, start, days, every=1):
    """Half the range of each day of *days* from *start*, a day in *every*."""
    out = []
    for k in range(0, days, every):
        t0 = start + timedelta(days=k)
        hs = [tide.height(t0 + timedelta(hours=h)) for h in range(25)]
        out.append((max(hs) - min(hs)) / 2)
    return out


class Makeup:
    """A station's tide taken apart, from a year of its highs and lows."""

    def __init__(self, turns, lat):
        from linecast.tides.openmeteo import FIT_NAMES
        tide = harmonic.fit_turns([(t, h) for t, h, *_ in turns], FIT_NAMES)
        if tide is None:
            raise ValueError("the turns would not fit")
        constants = tide.constants()
        amp = {name: a for name, a, _phase in constants}
        self.semi = harmonic.Tide([c for c in constants if _species(c[0]) == 2])
        self.diur = harmonic.Tide([c for c in constants if _species(c[0]) == 1])
        k1 = amp.get("K1", 0.0)
        # (string key, amplitude in feet, the constituent its gain is read from)
        self.twice = [(key, amp.get(name, 0.0), name) for key, name in TWICE]
        self.once = [(key, amp.get(name, 0.0) + share * k1, name)
                     for (key, name), share in zip(ONCE, (K1_LUNAR, 1 - K1_LUNAR))]
        self.gain = {}
        if lat is not None:
            phi = math.radians(lat)
            share = {2: math.cos(phi) ** 2, 1: abs(math.sin(2 * phi))}
            for name, pull in EQUILIBRIUM_M.items():
                s = share[_species(name)]
                if s >= LEAST_PULL and amp.get(name):
                    self.gain[name] = amp[name] * M_PER_FT / (pull * s)
        self._years = {}
        self._long = {}

    def month(self, first, tz):
        """Each part's amplitude every six hours of the month from *first*."""
        ndays = calendar.monthrange(first.year, first.month)[1]
        start = datetime(first.year, first.month, first.day, tzinfo=tz) - timedelta(hours=12)
        out = []
        for tide in (self.semi, self.diur):
            row = []
            for k in range(ndays * 4 + 1):
                t0 = start + timedelta(hours=6 * k)
                hs = [tide.height(t0 + timedelta(minutes=30 * m)) for m in range(51)]
                row.append((max(hs) - min(hs)) / 2)
            out.append(row)
        return out

    def year(self, year):
        """Each part's amplitude on each day of *year*."""
        if year not in self._years:
            n = 366 if calendar.isleap(year) else 365
            start = datetime(year, 1, 1, tzinfo=UTC)
            self._years[year] = [_daily_amplitudes(t, start, n) for t in (self.semi, self.diur)]
        return self._years[year]

    def long(self, year):
        """Each part's mean amplitude over the year round each of a run of
        days, LONG_STEP_DAYS apart, across the nineteen years that begin
        YEARS_BEFORE before *year*."""
        if year not in self._long:
            every = 5
            start = datetime(year - YEARS_BEFORE, 1, 1, tzinfo=UTC) - timedelta(days=183)
            days = 365 * (YEARS_SPAN + 1) + 10
            window, step = 365 // every, LONG_STEP_DAYS // every
            rows = []
            for tide in (self.semi, self.diur):
                daily = _daily_amplitudes(tide, start, days, every=every)
                rows.append([sum(daily[k:k + window]) / window
                             for k in range(0, len(daily) - window, step)])
            self._long[year] = rows
        return self._long[year]


def sky_marks(first, tz):
    """Where the month's and the year's marks fall, as fractions of each:
    the Moon's turns in declination and its nearest approaches for the
    month, the Sun's turns in declination for the year; and the moments
    of the month's principal phases, whose icons the view draws."""
    from linecast.astro.ephemeris import _moon_distance_er, _moon_ra_dec, sun_declination
    from linecast.moon.calendar import principal_phase_days
    ndays = calendar.monthrange(first.year, first.month)[1]
    start = datetime(first.year, first.month, first.day, tzinfo=tz).astimezone(UTC)
    hours = ndays * 24
    times = [start + timedelta(hours=h) for h in range(-1, hours + 2)]
    moon = _turns([_moon_ra_dec(t)[1] for t in times], hours)
    dist = [_moon_distance_er(t) for t in times]
    near = [(k - 1) / hours for k in range(1, len(times) - 1)
            if dist[k] < dist[k - 1] and dist[k] <= dist[k + 1] and 0 <= k - 1 < hours]
    n = 366 if calendar.isleap(first.year) else 365
    jan1 = datetime(first.year, 1, 1, tzinfo=UTC)
    sun = _turns([sun_declination(jan1 + timedelta(days=k)) for k in range(-1, n + 2)], n)
    span = ndays * 86400
    phases = [((when - start).total_seconds() / span, when)
              for _index, when in principal_phase_days(first.year, first.month, tz).values()]
    return {"moon": moon, "near": near, "sun": sun, "phases": phases}


def _turns(dec, n):
    """[(fraction, "N" | "S" | "0")] for a declination sampled at -1..n+1."""
    out = []
    for k in range(1, len(dec) - 1):
        if not 0 <= k - 1 < n:
            continue
        if (dec[k - 1] < 0) != (dec[k] < 0):
            out.append(((k - 1) / n, "0"))
        elif dec[k] > dec[k - 1] and dec[k] >= dec[k + 1]:
            out.append(((k - 1) / n, "N"))
        elif dec[k] < dec[k - 1] and dec[k] <= dec[k + 1]:
            out.append(((k - 1) / n, "S"))
    return out


# ---------------------------------------------------------------------------
# Drawing
# ---------------------------------------------------------------------------
class _Dots:
    """A small braille canvas: a strip's dots, then its lines."""

    def __init__(self, cells, rows):
        self.cells, self.rows = cells, rows
        self.bits = [[0] * cells for _ in range(rows)]

    def dot(self, x, y):
        if 0 <= x < self.cells * 2 and 0 <= y < self.rows * 4:
            self.bits[y // 4][x // 2] |= (LEFT_COLUMN, RIGHT_COLUMN)[x % 2][y % 4]

    def lines(self, ink, now_x=None):
        """The rows, inked; the dot column *now_x* is the line for now."""
        data, now = fg(*ink), fg(*_palette.NOW_LINE_COLOR)
        out = []
        for row in self.bits:
            line = [data]
            for c, b in enumerate(row):
                if now_x is not None and now_x // 2 == c:
                    column = sum((LEFT_COLUMN, RIGHT_COLUMN)[now_x % 2])
                    line.append(f"{now}{chr(0x2800 + column)}{data}")
                else:
                    line.append(chr(0x2800 + b))
            out.append("".join(line) + RESET)
        return out


def _sample(values, frac):
    """*values*, read at *frac* of the way along, between its points."""
    at = max(0.0, min(1.0, frac)) * (len(values) - 1)
    k = min(len(values) - 2, int(at))
    return values[k] + (values[k + 1] - values[k]) * (at - k)


def _wave(values, scale, cells, rows, now_frac, ink):
    """An envelope mirrored about its centre line, like a sound wave."""
    canvas = _Dots(cells, rows)
    half = rows * 2
    n = cells * 2
    for x in range(n):
        dots = round(2 * half * _sample(values, (x + 0.5) / n) / scale)
        top = half - dots // 2
        for y in range(top, top + dots):
            canvas.dot(x, y)
    return canvas.lines(ink, None if now_frac is None else int(now_frac * n))


def _line(values, cells, rows, now_frac, ink):
    """A line on its own scale, from the least of *values* to the most."""
    canvas = _Dots(cells, rows)
    lo, hi = min(values), max(values)
    top = rows * 4 - 1
    n = cells * 2
    before = None
    for x in range(n):
        y = round(top * (1 - (_sample(values, (x + 0.5) / n) - lo) / max(1e-9, hi - lo)))
        for yy in range(min(y, y if before is None else before),
                        max(y, y if before is None else before) + 1):
            canvas.dot(x, yy)
        before = y
    return canvas.lines(ink, None if now_frac is None else int(now_frac * n))


def _set(line, at, text):
    """*text* into *line* from column *at*, a column to each element: a
    wide glyph's second column is left empty and a combining mark rides
    with its base, so the columns after it stay where they were."""
    for col, glyph in text_cells(text)[0]:
        line[at + col] = glyph


def _placed(width, marks, beside=()):
    """A line *width* wide with each (fraction, text) centred at its
    place; a mark that would touch one already set is left out.  The
    marks in *beside* are set last, and one whose place is taken goes
    in the nearest free cell instead, touching what took it: the Moon's
    nearest approach on the day of a full Moon is worth both marks."""
    line = [" "] * width
    for frac, text in marks:
        w = visible_len(text)
        at = max(0, min(width - w, round(frac * width - w / 2)))
        if all(ch == " " for ch in line[max(0, at - 1):at + w + 1]):
            _set(line, at, text)
    for frac, text in beside:
        w = visible_len(text)
        at = max(0, min(width - w, round(frac * width - w / 2)))
        for shift in (0, 1, -1, 2, -2):
            to = at + shift
            if 0 <= to <= width - w and all(ch == " " for ch in line[to:to + w]):
                _set(line, to, text)
                break
    return "".join(line)


def _spread(width, marks):
    """A line *width* wide with each (fraction, text) as near its place
    as the others allow: two that would touch are moved apart to leave a
    space between them.  None where the line cannot hold them all."""
    marks = sorted(marks)
    widths = [visible_len(text) for _f, text in marks]
    if sum(widths) + len(marks) - 1 > width:
        return None
    at = [max(0, min(width - w, round(f * width - w / 2))) for (f, _t), w in zip(marks, widths)]
    for k in range(1, len(at)):                 # each clear of the one before
        at[k] = max(at[k], at[k - 1] + widths[k - 1] + 1)
    limit = width
    for k in reversed(range(len(at))):          # and all of them on the line
        at[k] = min(at[k], limit - widths[k])
        limit = at[k] - 1
    line = [" "] * width
    for x, (_f, text) in zip(at, marks):
        _set(line, x, text)
    return "".join(line)


def _flowed(items, width, between="   "):
    """*items* set on as few lines as hold them, none wider than *width*;
    an item wider than that is left out."""
    lines = []
    for item in items:
        if visible_len(item) > width:
            continue
        if lines and visible_len(lines[-1] + between + item) <= width:
            lines[-1] += between + item
        else:
            lines.append(item)
    return lines


def _fitted(room, key_rows):
    """What *room* rows hold: (the strips' height, the blank rows under
    the headline or None for no headline, how many of the key's lines,
    whether the key has its open line).

    The strips come first, at three rows; then as much of the key as
    still fits, since the marks cannot be read without it; then the
    strips grow, to six rows; then the key takes an open line between
    what it says of the figures and what it says of the marks.  The
    headline is set where the strips keep five rows and a blank row is
    left above it.  It closes up to the view first, with no blank row
    under its rule, since the row of the spans' titles is empty on its
    side; a window with more room opens that up, and then gives the
    strips their sixth row."""
    def needs(strip_rows, air, key, open_line=False):
        # the spans' titles, two parts of strips over an axis and its
        # marks with a blank between, the key under a blank, the
        # headline and its rule
        return (1 + 2 * (strip_rows + 2) + 1 + (key + 1 + open_line if key else 0)
                + (0 if air is None else 2 + air))
    key = next((k for k in range(key_rows, 0, -1) if needs(3, None, k) <= room), 0)
    whole = key > 0 and key == key_rows
    for strip_rows, air in ((6, 2), (6, 1), (5, 2), (5, 1), (5, 0)):
        if needs(strip_rows, air, key, whole) + 2 <= room:
            return strip_rows, air, key, whole
    if needs(5, 0, key, whole) + 1 <= room:
        return 5, 0, key, whole
    if whole and needs(6, None, key, True) <= room:
        return 6, None, key, True
    for strip_rows in (6, 5, 4, 3):
        if needs(strip_rows, None, key) <= room:
            return strip_rows, None, key, False
    return 2, None, 0, False


def _fortnightly(daily):
    """Each day's largest amplitude of the fortnight round it: the
    year's envelope, without the springs and neaps inside it."""
    return [max(daily[max(0, k - 7):k + 8]) for k in range(len(daily))]


def _height(value_ft, runtime):
    return (f"{fmt_decimal(runtime.convert_height(value_ft), 2 if runtime.metric else 1, runtime)}"
            f"{runtime.height_unit}")


def render_makeup(first, made, runtime, *, header, footer, station_tz, now_local,
                  mouse_pos=None):
    """The makeup view of the tides, sized to the terminal.

    *first* is the first day of the month on screen and *made* what was
    built for it: (Makeup, month, year, long, marks, the year the
    nineteen are counted from), or None while the tide is fetched and
    fitted, when the view draws the same frame without its figures.
    *header* and *footer* are the lines the live view puts above and
    below it.
    """
    from linecast.moon.calendar import _month_title
    from linecast.moon.phase import moon_phase
    from linecast.radar.i18n import rs
    from linecast.sunshine.i18n import axis_month_labels

    cols, rows = get_terminal_size()
    lang = lang_of(runtime)
    tz = station_tz or now_local.tzinfo
    text, muted, dim = (fg(*_palette.TEXT_RGB), fg(*_palette.MUTED_RGB),
                        fg(*_palette.DIM_RGB))
    ink = _palette.CURVE_COLOR
    ndays = calendar.monthrange(first.year, first.month)[1]
    year = first.year
    year_days = 366 if calendar.isleap(year) else 365

    # --- the left column: the causes, and the size of each -----------------
    makeup = made[0] if made else None

    def factor(gain):
        return "" if gain is None else f"×{fmt_decimal(gain, 0 if gain >= 3 else 1, runtime)}"
    if makeup:
        tables = [(title, [(_ts(key, runtime), _height(a, runtime), factor(makeup.gain.get(source)))
                           for key, a, source in rows_of])
                  for title, rows_of in (("makeup_twice", makeup.twice),
                                         ("makeup_once", makeup.once))]
    else:
        # Until the tide is fitted the table is its names alone, set in
        # the room the figures will want, so that nothing moves when
        # they come
        tables = [(title, [(_ts(key, runtime), "", "") for key, _name in rows_of])
                  for title, rows_of in (("makeup_twice", TWICE), ("makeup_once", ONCE))]
    # The two tables are one set of columns, so the eye runs down the
    # heights and the gains of both
    cells_of = [row for _t, table in tables for row in table]
    name_w = max(visible_len(n) for n, _h, _g in cells_of)
    size_w = max([visible_len(h) for _n, h, _g in cells_of] + [visible_len(_height(0, runtime))])
    gain_w = max(visible_len(g) for _n, _h, g in cells_of) if makeup else visible_len(factor(1.0))
    groups = []
    for title, table in tables:
        lines = [f"{text}{_ts(title, runtime)}{RESET}"]
        for name, size, gain in table:
            line = (f"{muted}{name}{' ' * (name_w - visible_len(name))}  "
                    f"{' ' * (size_w - visible_len(size))}{size}")
            lines.append(line + (f"  {gain}" if gain else "") + RESET)
        groups.append(lines)
    left_w = max([visible_len(g[0]) for g in groups]
                 + [name_w + 2 + size_w + (2 + gain_w if gain_w else 0), 12]) + 3

    # --- the strips: as many of the three spans as the width holds ---------
    gap = 3
    spans = ["month", "year", "long"]
    while (len(spans) > 1
           and (cols - 2 - left_w - gap * (len(spans) - 1)) // len(spans) < LEAST_STRIP):
        spans.pop()
    cell_w = max(8, min(60, (cols - 2 - left_w - gap * (len(spans) - 1)) // len(spans)))

    compass = rs("compass", lang).split()
    north, south = compass[0], compass[4]
    new_moon = moon_phase(datetime(2000, 1, 6, 18, 14, tzinfo=UTC), runtime)[2]
    full_moon = moon_phase(datetime(2000, 1, 21, 4, 40, tzinfo=UTC), runtime)[2]
    # What the table's figures are, then what the axes' marks are; a
    # short window keeps the marks' lines and lets the others go.  Each
    # sentence has a line to itself where the longest fits; where it
    # does not they are wrapped together as one paragraph, so that none
    # is left with a word on a line of its own.
    says = [_ts(k, runtime) for k in ("makeup_key_size", "makeup_key_gain", "makeup_key_sea")]
    if max(visible_len(line) for line in says) > cols - 2:
        says = wrap_display_width(" ".join(says), cols - 2)
    marks = _flowed([
        f"{new_moon} {full_moon} {_ts('makeup_key_phases', runtime)}",
        f"{_ts('makeup_mark_near', runtime)} {_ts('makeup_key_near', runtime)}",
        f"{north} {south} {_ts('makeup_key_far', runtime)}",
        f"0 {_ts('makeup_key_equator', runtime)}"], cols - 2)
    key_lines = [f" {dim}{line}{RESET}" for line in says + marks]
    # The headline is the one line set in full ink over a rule, which
    # is what puts it above the parts' own titles
    title = _ts("makeup_headline", runtime)
    headline = [f" {text}{title}{RESET}", f" {dim}{'─' * visible_len(title)}{RESET}"]
    n_footer = footer.count("\n") + 1
    room = rows - 1 - n_footer   # between the header and the footer
    strip_rows, air, kept, open_line = _fitted(room, len(key_lines))
    key_lines = key_lines[len(key_lines) - kept:]
    if open_line and says and marks:
        key_lines.insert(len(says), "")
    for lines in groups:
        del lines[strip_rows + 2:]

    # --- where now falls in each span -----------------------------------
    month_start = datetime(first.year, first.month, first.day, tzinfo=tz)
    now_month = (now_local - month_start).total_seconds() / (ndays * 86400)
    now_year = ((now_local - datetime(year, 1, 1, tzinfo=tz)).total_seconds()
                / (year_days * 86400))
    long_start = (made[5] if made else now_local.year) - YEARS_BEFORE
    now_long = (now_local.year + now_local.timetuple().tm_yday / 365.25 - long_start) / YEARS_SPAN
    now_at = {"month": now_month, "year": now_year, "long": now_long}
    now_at = {k: (v if 0 <= v < 1 else None) for k, v in now_at.items()}

    # --- the axes, the same under both parts --------------------------------
    month_labels = axis_month_labels(runtime, narrow=True)
    every = 1 if cell_w >= 24 else 2 if cell_w >= 18 else 3
    if civil_calendar(lang) == SOLAR_HIJRI:
        # A month's number would read as a Solar Hijri month, 7 as Mehr,
        # so the Gregorian months are named (weather.year._month_axis):
        # every month, or every second, third, fourth or sixth, the
        # first of those whose names stand clear of one another
        month_labels = table_for(MONTHS, lang)

        def clear(step):
            end = -1
            for m in range(0, 12, step):
                w = visible_len(month_labels[m])
                at = max(0, min(cell_w - w, round((m + 0.5) / 12 * cell_w - w / 2)))
                if at <= end:
                    return False
                end = at + w
            return True
        every = next((step for step in (1, 2, 3, 4, 6) if clear(step)), 12)
    axes = {
        "month": _placed(cell_w, [((d - 0.5) / ndays, str(d)) for d in range(1, ndays + 1, 7)]),
        "year": _placed(cell_w, [((m + 0.5) / 12, month_labels[m]) for m in range(0, 12, every)]),
        "long": _placed(cell_w, [((y + 0.5 - long_start) / YEARS_SPAN, str(y))
                                 for y in range(long_start + 1, long_start + YEARS_SPAN,
                                                4 if cell_w >= 26 else 8)]),
    }
    titles = {"month": _month_title(first.year, first.month, lang), "year": str(year),
              "long": f"{long_start}–{long_start + YEARS_SPAN - 1}"}

    def padded(s, width):
        return s + " " * max(0, width - visible_len(s))

    spacer = " " * gap
    out = []
    if air is not None:
        out += headline + [""] * air
    out.append(" " * (left_w + 1) + spacer.join(f"{dim}{padded(titles[s], cell_w)}{RESET}"
                                                for s in spans))
    tops = []     # each part's first strip line, counted from the body's top
    strips = {}   # (part, span) -> the values it draws, for the pointer
    for part, lines in enumerate(groups):
        cells, marks = [], []
        if made:
            _makeup, month, year_rows, long_rows, sky, _from = made
            scale = max(max(max(month[p]), max(year_rows[p])) for p in (0, 1)) or 1.0
            values = {"month": month[part], "year": _fortnightly(year_rows[part]),
                      "long": long_rows[part]}
            if part == 0:
                moon = [(f, moon_phase(when, runtime)[2]) for f, when in sky["phases"]]
                near = [(f, _ts("makeup_mark_near", runtime)) for f in sky["near"]]
            else:
                letters = {"N": north, "S": south, "0": "0"}
                moon, near = [(f, letters[m]) for f, m in sky["moon"]], []
            sun = [(f, {"N": north, "S": south, "0": "0"}[m]) for f, m in sky["sun"]]
            # The line is on a scale of its own, so its least and its
            # most are written under where they fall, as heights
            lo, hi = min(long_rows[part]), max(long_rows[part])
            last = len(long_rows[part]) - 1
            ends = sorted((long_rows[part].index(v) / last, f"{glyph} {_height(v, runtime)}")
                          for v, glyph in ((lo, "▼"), (hi, "▲")))
            mark_text = {"month": _placed(cell_w, sorted(moon), near),
                         "year": _placed(cell_w, sun),
                         "long": (_spread(cell_w, ends)
                                  or _spread(cell_w, [(f, t.replace(" ", "", 1)) for f, t in ends])
                                  or _placed(cell_w, ends))}
            for s in spans:
                strips[(part, s)] = values[s]
                cells.append(_line(values[s], cell_w, strip_rows, now_at[s], ink) if s == "long"
                             else _wave(values[s], scale, cell_w, strip_rows, now_at[s], ink))
                marks.append(mark_text[s])
        else:
            cells = [[" " * cell_w] * strip_rows for _s in spans]
            marks = ["" for _s in spans]
        under = [spacer.join(f"{dim}{padded(axes[s], cell_w)}{RESET}" for s in spans),
                 spacer.join(f"{dim}{padded(m, cell_w)}{RESET}" for m in marks)]
        tops.append(len(out))
        for r in range(strip_rows + 2):
            label = lines[r] if r < len(lines) else ""
            body = (spacer.join(c[r] for c in cells) if r < strip_rows
                    else under[r - strip_rows])
            out.append(" " + padded(label, left_w) + body)
        if part == 0:
            out.append("")
    if key_lines:
        out.append("")
        out.extend(key_lines)
    # The header keeps the top of the window and the footer the bottom;
    # what is between sits midway, and an odd row goes over the headline
    # to keep it off the station's name.
    spare = max(0, room - len(out))
    above = spare // 2 if air is None else (spare + 1) // 2
    output = "\n".join([header] + [""] * above + out + [""] * (spare - above) + [footer])

    # a part's strips open on the terminal row after the header, the
    # rows above the body, and the body's lines before them
    strip_tops = [2 + above + top for top in tops]
    chip = _hover_chip(mouse_pos, strips, spans, left_w, cell_w, gap, strip_rows, strip_tops,
                       first, ndays, year, year_days, long_start, runtime, cols, rows)
    return _live.overlay(output, chip) if chip else output


def _hover_chip(mouse_pos, strips, spans, left_w, cell_w, gap, strip_rows, strip_tops,
                first, ndays, year, year_days, long_start, runtime, cols, rows):
    """The chip for the strip under the pointer: the day, or the year,
    and that part's size then."""
    if not mouse_pos or not strips:
        return ""
    from linecast.moon.i18n import _fmt_month_day
    mcol, mrow = mouse_pos
    x = mcol - 1 - (left_w + 1)
    span_i, in_cell = divmod(x, cell_w + gap)
    if x < 0 or span_i >= len(spans) or in_cell >= cell_w:
        return ""
    part = next((p for p, top in enumerate(strip_tops)
                 if 0 <= mrow - top < strip_rows), None)
    if part is None:
        return ""
    span = spans[span_i]
    frac = (in_cell + 0.5) / cell_w
    values = strips[(part, span)]
    lang = lang_of(runtime)
    if span == "long":
        when = str(int(long_start + frac * YEARS_SPAN))
        value = _sample(values, frac)
    else:
        day = (first + timedelta(days=int(frac * ndays)) if span == "month"
               else date(year, 1, 1) + timedelta(days=int(frac * year_days)))
        when = f"{table_for(DAY_NAMES, lang)[day.weekday()]} {_fmt_month_day(day, runtime)}"
        value = _sample(values, frac)
    tip_bg, tip_fg, dim = (bg(*_palette.TIP_BG_RGB), fg(*_palette.TIP_TEXT_RGB),
                           fg(*_palette.DIM_RGB))
    name = _ts("makeup_twice" if part == 0 else "makeup_once", runtime)
    lines = [f"{tip_bg}{dim} {when} ",
             f"{tip_bg}{tip_fg} {name}  {_height(value, runtime)} "]
    return _live.pointer_chip(lines, mcol, mrow, cols, rows, pad_bg=tip_bg)
