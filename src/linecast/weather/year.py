"""Weather year view — this year's days against the ten before it,
après Tufte (https://www.edwardtufte.com/notebook/new-york-city-weather-chart/).

After the New York Times's yearly chart of the city's weather: a bar
for each day from its low to its high, standing in two bands that say
what the date usually brings -- the ten years' average high and low,
and around it, fainter, the highest high and the lowest low any of them
saw.  Under it, each month's precipitation as a running total against
the month's average, starting over on the 1st.

The bands are fields, drawn in half-block sub-pixels.  The days are
solid bars of quadrant blocks, two to a cell, in one plain ink, or with
`colored` each row in the dashboard's color for its temperature, so a
bar runs from its low's color to its high's as the daily forecast's do;
the running totals are braille lines.  The ten years are the
dashboard's own archive download (historical.fetch_history), so the
view costs one request more: this year so far.  Today and the days
after it come from the forecast, the days after it in a lighter ink.

Ten years of a reanalysis grid are not a station's thirty-year normals
or its records.  The averages are smoothed across a fortnight, since
ten samples of one date wander by several degrees from day to day, and
the outer band is named by its span, never called a record.
"""

import calendar
from dataclasses import dataclass
from datetime import date, timedelta

from linecast._i18n import fmt_decimal
from linecast.terminal import live as _live
from linecast.terminal import theme as _theme
from linecast.terminal.graphics import (
    RESET, Framebuffer, bg, fg, get_terminal_size, overlay, visible_len,
)
from linecast.terminal.textwidth import char_width
from linecast.terminal.theme import ensure_contrast, lerp_rgb, neutral_tone, surface_bg
from linecast.weather import style as _style
from linecast.weather.i18n import _s, _wmo_icons

# Days either side of a date that its average is taken over.
_SMOOTH_DAYS = 7
# A leap year, so every month and day has a slot.
_LEAP = 2000
# Braille dot bits by [column][row] within a cell.
_BITS = ((0x01, 0x02, 0x04, 0x40), (0x08, 0x10, 0x20, 0x80))
# Quadrant blocks by their filled quarters: 8 upper left, 4 upper right,
# 2 lower left, 1 lower right.
_QUADRANTS = " ▗▖▄▝▐▞▟▘▚▌▙▀▜▛█"
_QUARTER = ((8, 4), (2, 1))   # by [half row][column]
# The share of the chart's rows the precipitation panel takes.
_PRECIP_SHARE = 0.28
# How far a forecast day's bar fades toward the page.
_FORECAST_FADE = 0.5
# Open-Meteo's snowfall is seven times the snow's water: 7 cm of snow to
# 10 mm of water, 3.5 in to 0.5 in.
_SNOW_PER_WATER = 7


def _rebuild():
    global RANGE_RGB, NORMAL_RGB, RANGE_LABEL_RGB, NORMAL_LABEL_RGB, GRID_RGB
    global PRECIP_RGB, PRECIP_NORMAL_RGB, NEUTRAL_BAR_RGB, NEUTRAL_MARK_RGB, SNOW_RGB
    # The two bands: the span's extremes barely off the page, the
    # average range a step further, as the paper's two tans.
    RANGE_RGB = surface_bg(0.07)
    NORMAL_RGB = surface_bg(0.17)
    # Their names, a shade off the band each sits in.
    RANGE_LABEL_RGB = ensure_contrast(lerp_rgb(RANGE_RGB, _theme.theme_fg, 0.30),
                                      RANGE_RGB, minimum=2.0)
    NORMAL_LABEL_RGB = ensure_contrast(lerp_rgb(NORMAL_RGB, _theme.theme_fg, 0.35),
                                       NORMAL_RGB, minimum=2.2)
    GRID_RGB = surface_bg(0.14)
    # The plain inks, when the bars are not in the temperature colors.
    # Solid blocks take a grey off the text, clear of the average band
    # they cross; thin marks -- braille dots, the labels of the year's
    # hottest and coldest days -- take the text itself.
    NEUTRAL_BAR_RGB = ensure_contrast(neutral_tone(0.62), NORMAL_RGB, minimum=2.4)
    NEUTRAL_MARK_RGB = _style.TEXT_RGB
    PRECIP_RGB = _style.PRECIP_RAIN_RGB
    SNOW_RGB = _style.PRECIP_SNOW_RGB
    PRECIP_NORMAL_RGB = lerp_rgb(PRECIP_RGB, _theme.theme_bg, 0.55)


_rebuild()
_theme.on_reload(_rebuild)


def _slot(d):
    """The date's place in a leap year, 0-365: Feb 29 has its own."""
    return date(_LEAP, d.month, d.day).timetuple().tm_yday - 1


def _at(values, i):
    return values[i] if values is not None and i < len(values) else None


@dataclass(frozen=True)
class Climate:
    """Ten years of the date, by slot (see _slot)."""
    span: tuple          # (first year, last year)
    normal_high: tuple   # smoothed mean high; None where no year had one
    normal_low: tuple
    top: tuple           # the span's highest high on the date
    bottom: tuple        # and its lowest low
    month_precip: tuple  # mean total for each month, January first


def _smooth(sums, counts):
    n = len(sums)
    out = []
    for s in range(n):
        total = count = 0
        for k in range(s - _SMOOTH_DAYS, s + _SMOOTH_DAYS + 1):
            total += sums[k % n]
            count += counts[k % n]
        out.append(total / count if count else None)
    return tuple(out)


def climate_from_archive(data, span):
    """The Climate in an archive answer (historical.fetch_history), or
    None when it holds no temperatures."""
    daily = (data or {}).get("daily") or {}
    times = daily.get("time") or []
    highs = daily.get("temperature_2m_max")
    lows = daily.get("temperature_2m_min")
    precips = daily.get("precipitation_sum")
    sum_hi, n_hi = [0.0] * 366, [0] * 366
    sum_lo, n_lo = [0.0] * 366, [0] * 366
    top, bottom = [None] * 366, [None] * 366
    months = {}  # (year, month) -> [total, days with a value]
    for i, t in enumerate(times):
        try:
            d = date.fromisoformat(t)
        except (TypeError, ValueError):
            continue
        s = _slot(d)
        hi, lo, pr = _at(highs, i), _at(lows, i), _at(precips, i)
        if hi is not None:
            sum_hi[s] += hi
            n_hi[s] += 1
            top[s] = hi if top[s] is None else max(top[s], hi)
        if lo is not None:
            sum_lo[s] += lo
            n_lo[s] += 1
            bottom[s] = lo if bottom[s] is None else min(bottom[s], lo)
        if pr is not None:
            month = months.setdefault((d.year, d.month), [0.0, 0])
            month[0] += pr
            month[1] += 1
    if not any(n_hi) or not any(n_lo):
        return None
    # Feb 29 comes round two or three times in ten years: its extremes
    # take in the days either side, so the band does not pinch there.
    feb29 = _slot(date(_LEAP, 2, 29))
    for band, pick in ((top, max), (bottom, min)):
        near = [v for v in band[feb29 - 1:feb29 + 2] if v is not None]
        band[feb29] = pick(near) if near else None
    month_precip = []
    for m in range(1, 13):
        # A month the archive left more than a couple of days out of
        # would pull the average down.
        totals = [total for (y, mm), (total, k) in months.items()
                  if mm == m and k >= calendar.monthrange(y, m)[1] - 2]
        month_precip.append(sum(totals) / len(totals) if totals else None)
    return Climate(tuple(span), _smooth(sum_hi, n_hi), _smooth(sum_lo, n_lo),
                   tuple(top), tuple(bottom), tuple(month_precip))


@dataclass(frozen=True)
class YearDays:
    """This year, by day from 1 January (index 0)."""
    year: int
    today: int
    highs: tuple   # None where neither the archive nor the forecast has it
    lows: tuple
    precip: tuple  # the days before today only: the running totals' days
    codes: tuple   # WMO weather code, for the precipitation's ink
    snow: tuple = ()   # snowfall on the precipitation's days, cm or inches


def _daily_rows(data, jan1, n):
    daily = (data or {}).get("daily") or {}
    for i, t in enumerate(daily.get("time") or []):
        try:
            k = (date.fromisoformat(t) - jan1).days
        except (TypeError, ValueError):
            continue
        if 0 <= k < n:
            yield (k, _at(daily.get("temperature_2m_max"), i),
                   _at(daily.get("temperature_2m_min"), i),
                   _at(daily.get("precipitation_sum"), i),
                   _at(daily.get("weather_code"), i),
                   _at(daily.get("snowfall_sum"), i))


def year_days(archive, forecast, today):
    """This year's days: the archive's (historical.fetch_year_to_date)
    before today, and the forecast's from today on.  The forecast also
    fills a recent day the archive has not reached."""
    n = 366 if calendar.isleap(today.year) else 365
    jan1 = date(today.year, 1, 1)
    t = (today - jan1).days
    highs, lows = [None] * n, [None] * n
    precip, codes, snow = [None] * n, [None] * n, [None] * n
    for k, hi, lo, pr, code, sn in _daily_rows(archive, jan1, n):
        if k < t:
            highs[k], lows[k], precip[k], codes[k], snow[k] = hi, lo, pr, code, sn
    for k, hi, lo, pr, code, sn in _daily_rows(forecast, jan1, n):
        if k >= t:
            highs[k], lows[k], codes[k] = hi, lo, code
        elif highs[k] is None and lows[k] is None:
            highs[k], lows[k], precip[k], codes[k], snow[k] = hi, lo, pr, code, sn
    return YearDays(today.year, t, tuple(highs), tuple(lows), tuple(precip),
                    tuple(codes), tuple(snow))


def _snow_water(snow, metric):
    """The water in a snowfall, in the precipitation's unit (mm from cm)."""
    return (snow or 0) / _SNOW_PER_WATER * (10 if metric else 1)


def fetch_year(lat, lng, today, runtime, stale=None):
    """(Climate or None, this year's archive answer or None) for the
    place.  The ten years usually come from the dashboard's cache; each
    fetch falls back to None on its own, and the view draws the other."""
    from linecast.weather.historical import fetch_history, fetch_year_to_date, history_span
    celsius, metric = runtime.celsius, runtime.metric
    climate = climate_from_archive(
        fetch_history(lat, lng, today.year, celsius, metric, stale),
        history_span(today.year))
    archive = fetch_year_to_date(lat, lng, today, celsius, metric, stale)
    return climate, archive


def _span(i, width, n):
    """The days, as a range, that column i of `width` covers."""
    a = int(i * n / width)
    return range(a, max(a + 1, int((i + 1) * n / width)))


def _month_starts(year):
    """Day index of each month's first day, and the year's length;
    `starts[1:] + [n]` are the months' ends."""
    starts, k = [], 0
    for m in range(1, 13):
        starts.append(k)
        k += calendar.monthrange(year, m)[1]
    return starts, k


def _temp_ticks(lo, hi, rows, celsius):
    """The degrees the temperature panel labels: at the finest step
    that leaves three rows between labels."""
    steps = (2, 5, 10, 20) if celsius else (5, 10, 20, 25, 50)
    for step in steps:
        if rows * step / max(1e-9, hi - lo) >= 3:
            break
    first = -(-lo // step) * step
    return list(range(int(first), int(hi) + 1, step))


def _fmt_amount(value, runtime):
    """A running total as the panel labels it: bare, like the paper's."""
    if runtime.metric:
        return fmt_decimal(value, 0, runtime)
    return fmt_decimal(value, 2 if value < 10 else 1, runtime)


class _Braille:
    """A panel's braille layer: dot bits and one ink per cell.  A cell
    holds data or a faint guide (a grid line, an average); a guide
    yields its cell to data and to labels."""

    def __init__(self, width, rows):
        self.width, self.rows = width, rows
        self.bits = [[0] * width for _ in range(rows)]
        self.ink = [[None] * width for _ in range(rows)]
        self.guide = [[False] * width for _ in range(rows)]

    def dot(self, i, y, ink, guide=False, wins=False):
        """Dot row y of dot column i.  Data meeting data of another ink
        keeps both dots, in the cell's ink unless this dot `wins` it."""
        cell, row = i // 2, y // 4
        if not (0 <= cell < self.width and 0 <= row < self.rows):
            return
        held = self.bits[row][cell]
        if held and self.ink[row][cell] != ink:
            if self.guide[row][cell]:
                held = 0            # a guide gives its cell up to anything
            elif guide:
                return              # and never takes one from data
            elif not wins:
                ink = self.ink[row][cell]
        self.bits[row][cell] = held | _BITS[i % 2][y % 4]
        self.ink[row][cell] = ink
        self.guide[row][cell] = guide

    def free(self, cell, row):
        """Whether the cell holds no data (a guide may be drawn over)."""
        return not self.bits[row][cell] or self.guide[row][cell]

    def overlays(self, out):
        for row in range(self.rows):
            for cell in range(self.width):
                if self.bits[row][cell] and (cell, row) not in out:
                    out[(cell, row)] = (chr(0x2800 + self.bits[row][cell]),
                                        self.ink[row][cell], False)


class _Bars:
    """A panel's bars, each cell two columns wide and `per` steps tall:
    quadrant blocks (2), solid quarters, or braille (4), dots.  A cell
    takes the ink of its row."""

    def __init__(self, width, rows, braille=False):
        self.width, self.rows = width, rows
        self.per = 4 if braille else 2
        self.bits = [[0] * width for _ in range(rows)]
        self.observed = [[False] * width for _ in range(rows)]

    def fill(self, i, q, observed):
        """Step q from the top of column i, a day gone by or one forecast."""
        cell, row = i // 2, q // self.per
        if 0 <= cell < self.width and 0 <= row < self.rows:
            self.bits[row][cell] |= (_BITS[i % 2][q % 4] if self.per == 4
                                     else _QUARTER[q % 2][i % 2])
            self.observed[row][cell] |= observed

    def free(self, cell, row):
        return not self.bits[row][cell]

    def overlays(self, out, ink):
        """The filled cells into `out`, inked by ink(row, observed).  A
        grid line gives a bar's cell up: drawn in the bar's ink, its dots
        would read as the bar's own."""
        for row in range(self.rows):
            for cell in range(self.width):
                bits = self.bits[row][cell]
                if not bits or (cell, row) in out:
                    continue
                glyph = chr(0x2800 + bits) if self.per == 4 else _QUADRANTS[bits]
                out[(cell, row)] = (glyph, ink(row, self.observed[row][cell]), False)


def _place(overlays, free, rows, text, x, row, ink, width):
    """Text into a panel's overlays at cell x, if every cell it needs is
    inside the panel and free of data (free(cell, row)), with a cell of
    air either side between it and another label."""
    cells = []
    for ch in text:
        w = char_width(ch)
        cells.append((x, ch))
        cells.extend((x + k, "") for k in range(1, w))
        x += w
    first = cells[0][0]
    if first < 0 or x > width or not 0 <= row < rows:
        return False
    if any(not free(c, row) for c, _ in cells):
        return False
    if any((c, row) in overlays for c in range(first - 1, x + 1)):
        return False
    for c, ch in cells:
        overlays[(c, row)] = (ch, ink, False)
    return True


def _header(climate, days, runtime, cols, location_name, location_menu):
    """The year, how warm it has been against the ten years, and the
    precipitation so far against theirs to the date; the place at the
    right, as the dashboard's header has it."""
    from linecast.weather.sections import location_chip, location_control
    from linecast.terminal.help import fit

    parts = [f"{_style.TEXT}{days.year if days else ''}"]
    if climate and days:
        felt, usual = [], []
        for k in range(days.today):
            s = _slot(date(days.year, 1, 1) + timedelta(days=k))
            nh, nl = climate.normal_high[s], climate.normal_low[s]
            if None not in (days.highs[k], days.lows[k], nh, nl):
                felt.append((days.highs[k] + days.lows[k]) / 2)
                usual.append((nh + nl) / 2)
        if felt:
            # The mean of every day's high and low, against the same
            # days' averages: a year's departure is a degree or two, so
            # it keeps its tenth where the dashboard's day rounds.
            diff = sum(felt) / len(felt) - sum(usual) / len(usual)
            if abs(diff) < (0.3 if runtime.celsius else 0.5):
                text = _s("hist_near_avg", runtime)
            else:
                key = "hist_above_avg" if diff > 0 else "hist_below_avg"
                text = _s(key, runtime, diff=f"{fmt_decimal(abs(diff), 1, runtime)}°")
            parts.append(f"{_style.MUTED}{text}")
        starts, n = _month_starts(days.year)
        observed = [p for p in days.precip[:days.today] if p is not None]
        normal = _normal_to_date(climate, days.today, starts, starts[1:] + [n])
        if observed and normal is not None:
            unit = runtime.precip_unit_label
            sep = _s("metric_unit_sep", runtime) if runtime.metric else ""
            parts.append(f"{_style.PRECIP_RAIN}{_fmt_amount(sum(observed), runtime)}{sep}{unit}"
                         f"{_style.MUTED} · {_s('avg', runtime)} "
                         f"{_fmt_amount(normal, runtime)}{sep}{unit}")
    if location_menu:
        right = location_chip(location_control(location_name, cols, runtime))
    elif location_name:
        right = location_chip(fit(location_name, max(0, min(cols - 4, cols // 2))))
    else:
        right = ""
    # Short of room, the precipitation goes, then the temperature.
    while parts:
        left = "  ".join(parts)
        pad = cols - visible_len(left) - visible_len(right)
        if pad >= 2 or not right:
            return f"{left}{' ' * max(0, pad)}{right}{RESET}"
        parts.pop()
    return f"{' ' * max(0, cols - visible_len(right))}{right}{RESET}"


def _normal_to_date(climate, today, starts, ends):
    """The ten years' average precipitation from 1 January to today,
    the current month's in proportion to the days gone."""
    if climate is None or None in climate.month_precip:
        return None
    total = 0.0
    for m in range(12):
        length = ends[m] - starts[m]
        done = max(0, min(length, today - starts[m]))
        total += climate.month_precip[m] * done / length
    return total


def render_year(climate, days, runtime, *, location_name="", location_menu=False,
                mouse_pos=None, live=False, footer="", hint="", colored=False,
                braille=False):
    """The year view, sized to the terminal: a header, the temperature
    panel, the month axis, the precipitation panel, and in live mode
    `footer` (the dashboard's credit row).  Either of `climate` and
    `days` may be None while it is fetched; the view draws what it has.
    `colored` draws the bars, and the labels of the year's hottest and
    coldest days, in the temperature colors instead of one plain ink.
    `braille` draws the bars in braille dots instead of quadrant blocks
    (a trial, for comparing the two).
    """
    cols, rows = get_terminal_size()
    year = days.year if days else date.today().year
    starts, n = _month_starts(year)
    ends = starts[1:] + [n]
    jan1 = date(year, 1, 1)
    slots = [_slot(jan1 + timedelta(days=k)) for k in range(n)]
    today = days.today if days else None

    # --- the rows ---
    fixed = 2 + bool(footer) + bool(hint) + (0 if live else 1)
    avail = max(5, rows - fixed)
    n_precip = max(2, round(avail * _PRECIP_SHARE))
    n_temp = max(3, avail - n_precip)

    # --- the temperature scale ---
    values = []
    if climate:
        values += [v for v in climate.top + climate.bottom if v is not None]
    if days:
        values += [v for v in days.highs + days.lows if v is not None]
    if not values:
        values = [-5, 35] if runtime.celsius else [20, 95]
    lo, hi = min(values), max(values)
    # A row to spare at either end, for the labels of the year's
    # hottest and coldest days when they are the scale's own ends.
    pad = (hi - lo + 1) / max(1, n_temp - 2)
    lo, hi = lo - pad, hi + pad
    ticks = _temp_ticks(lo, hi, n_temp, runtime.celsius)
    tick_labels = [f"{v}°" for v in ticks]
    gutter = max(visible_len(t) for t in tick_labels) + 1
    width = max(20, cols - gutter)
    dots = n_temp * 4

    def ty(v):
        return (hi - v) / (hi - lo) * dots

    def ydot(v):
        return max(0, min(dots - 1, int(ty(v))))

    def cell_of(k):
        return min(width - 1, int((k + 0.5) / n * width))

    # --- the bands: half-block fields ---
    # Each column's (outer top, outer bottom, average high, average low),
    # in dots from the top; None where the ten years have nothing.
    edges = [None] * width
    temp_fb = Framebuffer(width, n_temp)
    if climate:
        def values(series, span):
            return [series[slots[k]] for k in span if series[slots[k]] is not None]

        for x in range(width):
            span = _span(x, width, n)
            tops, bots = values(climate.top, span), values(climate.bottom, span)
            nhs = values(climate.normal_high, span)
            nls = values(climate.normal_low, span)
            bands = []
            if tops and bots and nhs and nls:
                edges[x] = (ty(max(tops)), ty(min(bots)),
                            ty(sum(nhs) / len(nhs)), ty(sum(nls) / len(nls)))
                bands = [(edges[x][0], edges[x][1], RANGE_RGB),
                         (edges[x][2], edges[x][3], NORMAL_RGB)]
            for spy in range(n_temp * 2):
                a, b = spy * 2, spy * 2 + 2   # the sub-pixel, in dots
                for y0, y1, ink in bands:
                    cover = max(0.0, min(b, y1) - max(a, y0)) / 2
                    if cover > 0:
                        temp_fb.set_pixel(x, spy, ink, cover)

    # --- the days: quadrant-block bars ---
    bars = _Bars(width, n_temp, braille=braille)
    steps = n_temp * bars.per

    def tq(v):
        """The bar step v falls in, from the top."""
        return max(0, min(steps - 1, int(ty(v) * bars.per / 4)))

    def bar_ink(row, observed):
        # The row's own temperature, in the dashboard's colors
        rgb = (_style._temp_color(hi - (row + 0.5) / n_temp * (hi - lo), runtime)
               if colored else NEUTRAL_MARK_RGB if braille else NEUTRAL_BAR_RGB)
        return rgb if observed else lerp_rgb(rgb, _theme.theme_bg, _FORECAST_FADE)

    def extreme_ink(v):
        return _style._temp_color(v, runtime) if colored else NEUTRAL_MARK_RGB

    temp_dots = _Braille(width, n_temp)   # the grid lines under the bars
    hottest = coldest = None   # (value, day) of the year's extremes so far
    if days:
        for i in range(width * 2):
            span = _span(i, width * 2, n)
            his = [days.highs[k] for k in span if days.highs[k] is not None]
            los = [days.lows[k] for k in span if days.lows[k] is not None]
            if not his or not los:
                continue
            for q in range(tq(max(his)), tq(min(los)) + 1):
                bars.fill(i, q, span.start <= days.today)
        for k in range(days.today + 1):
            if days.highs[k] is not None and (hottest is None or days.highs[k] > hottest[0]):
                hottest = (days.highs[k], k)
            if days.lows[k] is not None and (coldest is None or days.lows[k] < coldest[0]):
                coldest = (days.lows[k], k)

    # Grid lines at the labelled degrees and the month boundaries, dotted
    # and faint, yielding to the bars.
    for v in ticks:
        y = ydot(v)
        for i in range(0, width * 2, 2):
            temp_dots.dot(i, y, GRID_RGB, guide=True)
    month_dots = [min(width * 2 - 1, round(s / n * width * 2)) for s in starts[1:]]
    for i in month_dots:
        for y in range(0, dots, 2):
            temp_dots.dot(i, y, GRID_RGB, guide=True)

    # --- precipitation: braille running totals against the averages ---
    pdots_n = n_precip * 4
    # The top row is kept for the totals' labels while there are rows
    # enough to give one up.
    ptop = 4 if n_precip >= 3 else 0
    cum = [None] * n
    month_of = []
    for m in range(12):
        month_of += [m] * (ends[m] - starts[m])
        if not days:
            continue
        run = 0.0
        for k in range(starts[m], min(ends[m], days.today)):
            run += days.precip[k] or 0.0
            cum[k] = run
    normals = climate.month_precip if climate else (None,) * 12
    pvalues = [v for v in cum if v is not None] + [v for v in normals if v is not None]
    pmax = max(pvalues + [25.0 if runtime.metric else 1.0]) * 1.05

    def py(v):
        return max(0, min(pdots_n - 1,
                          int(ptop + (1 - v / pmax) * (pdots_n - 1 - ptop) + 0.5)))

    precip_dots = _Braille(width, n_precip)
    prev = None   # (dot row, month, day) of the last column's running total
    for i in range(width * 2):
        k = min(n - 1, _span(i, width * 2, n)[-1])
        if cum[k] is None:
            prev = None
            continue
        y = py(cum[k])
        same_month = prev is not None and prev[1] == month_of[k]
        # The days this column adds to the total; a step that is mostly
        # snow's water is drawn in the snow's ink, and takes its cell
        added = range(prev[2] + 1 if same_month else starts[month_of[k]], k + 1)
        water = sum(days.precip[d] or 0 for d in added)
        snowy = bool(water > 0 and days.snow and 2 * sum(
            _snow_water(days.snow[d], runtime.metric) for d in added) >= water)
        ink = SNOW_RGB if snowy else PRECIP_RGB
        precip_dots.dot(i, y, ink, wins=snowy)
        if same_month:
            for yy in range(min(prev[0], y), max(prev[0], y) + 1):
                precip_dots.dot(i, yy, ink, wins=snowy)
        prev = (y, month_of[k], k)
    for i in range(width * 2):
        span = _span(i, width * 2, n)
        normal = normals[month_of[min(n - 1, span[len(span) // 2])]]
        if normal is not None:
            precip_dots.dot(i, py(normal), PRECIP_NORMAL_RGB, guide=True)
    for i in month_dots:
        for y in range(0, pdots_n, 2):
            precip_dots.dot(i, y, GRID_RGB, guide=True)

    # --- hover ---
    hover_x = None
    x_today = cell_of(today) if today is not None else None
    if mouse_pos:
        gx, gy = mouse_pos[0] - 1 - gutter, mouse_pos[1] - 1
        if 0 <= gx < width and 1 <= gy <= n_temp + 1 + n_precip:
            hover_x = gx
            # A column is two or three days wide; within a cell of today's,
            # the hover is today.
            if x_today is not None and abs(gx - x_today) <= 1:
                hover_x = x_today

    # --- overlays: labels, then hairlines where nothing else is ---
    temp_over, precip_over = {}, {}
    if hottest:
        v, k = hottest
        text = f"{round(v)}°"
        _place(temp_over, bars.free, n_temp, text, cell_of(k) - len(text) // 2,
               tq(v) // bars.per - 1, extreme_ink(v), width)
    if coldest:
        v, k = coldest
        text = f"{round(v)}°"
        _place(temp_over, bars.free, n_temp, text, cell_of(k) - len(text) // 2,
               tq(v) // bars.per + 1, extreme_ink(v), width)
    # The bands' names where this year has not reached, at the chart's
    # right end as the paper's legend is: the average in its band, the
    # span in the outer band above it.  Hovering says the rest.
    reached = max((c for c in range(width) for r in range(n_temp)
                   if not bars.free(c, r)), default=-1)
    if climate:
        legend = ((_s("avg", runtime), 2, 3, NORMAL_LABEL_RGB),
                  (f"{climate.span[0]}–{climate.span[1]}", 0, 2, RANGE_LABEL_RGB))
        for text, upper, lower, ink in legend:
            x = width - 1 - visible_len(text)
            cols_under = [edges[c] for c in range(x, x + visible_len(text))]
            if x <= reached + 1 or None in cols_under:
                continue
            top = max(e[upper] for e in cols_under)
            bottom = min(e[lower] for e in cols_under)
            inside = [r for r in range(n_temp) if top <= r * 4 + 2 <= bottom]
            if inside:
                _place(temp_over, bars.free, n_temp, text, x,
                       inside[len(inside) // 2], ink, width)
    if ptop:
        for m in range(12):
            first, last = cell_of(starts[m]), cell_of(ends[m] - 1)
            if days and starts[m] < days.today:
                k_end = min(ends[m], days.today) - 1
                if cum[k_end] is not None:
                    text = _fmt_amount(cum[k_end], runtime)
                    end = cell_of(k_end)
                    x = max(first + 1, end - visible_len(text) + 1)
                    _place(precip_over, precip_dots.free, n_precip, text, x,
                           py(cum[k_end]) // 4 - 1, PRECIP_RGB, last + 1)
            if normals[m] is not None:
                text = _fmt_amount(normals[m], runtime)
                _place(precip_over, precip_dots.free, n_precip, text, first + 1,
                       py(normals[m]) // 4 - 1, PRECIP_NORMAL_RGB, last + 1)

    hairlines = [(x_today, _style.CHART_NOW_RGB)]
    if hover_x != x_today:
        hairlines.append((hover_x, _style.CHART_HOVER_RGB))
    for x, ink in hairlines:
        if x is None:
            continue
        for over, free, n_rows in ((temp_over, bars.free, n_temp),
                                   (precip_over, precip_dots.free, n_precip)):
            for row in range(n_rows):
                if free(x, row) and (x, row) not in over:
                    over[(x, row)] = ("│", ink, False)

    bars.overlays(temp_over, bar_ink)
    temp_dots.overlays(temp_over)
    precip_dots.overlays(precip_over)
    precip_fb = Framebuffer(width, n_precip)

    # --- assemble ---
    dim = _style.DIM
    label_at = {}
    for v, text in zip(ticks, tick_labels):
        label_at.setdefault(ydot(v) // 4, text)
    lines = [_header(climate, days, runtime, cols, location_name, location_menu)]
    for row, body in enumerate(temp_fb.render(temp_over)):
        text = label_at.get(row, "")
        lines.append(f"{dim}{' ' * (gutter - 1 - visible_len(text))}{text} {RESET}{body}")
    lines.append(" " * gutter + _month_axis(year, starts, n, width, runtime,
                                            this_month=month_of[today] if today is not None
                                            else None))
    for body in precip_fb.render(precip_over):
        lines.append(" " * gutter + body)
    if hint:
        lines.append(hint)
    if footer:
        lines.append(footer)

    tip = ""
    if hover_x is not None and mouse_pos:
        k = today if hover_x == x_today else min(n - 1, int((hover_x + 0.5) / width * n))
        tip = _tooltip(climate, days, k, jan1, slots, runtime, hover_x + gutter,
                       mouse_pos[1], cols, rows)
    return overlay("\n".join(lines), tip)


def _month_axis(year, starts, n, width, runtime, this_month=None):
    """The month labels at their months' starts, the current one brighter."""
    from linecast.sunshine.i18n import axis_month_labels
    labels = axis_month_labels(runtime, narrow=width < 72)
    cells = [" "] * width
    for m, label in enumerate(labels):
        x = min(width - 1, int(starts[m] / n * width))
        ink = _style.TEXT if m == this_month else _style.DIM
        placed = []
        for ch in label:
            w = char_width(ch)
            if w == 0 and placed:
                cells[placed[-1]] += ch
                continue
            if x + w > width:
                break
            cells[x] = f"{ink}{ch}"
            placed.append(x)
            for j in range(1, w):
                cells[x + j] = ""
            x += w
    return "".join(cells) + RESET


def _tooltip(climate, days, k, jan1, slots, runtime, col, mouse_row, cols, rows):
    """The chip for day k: its high and low, the ten years' average and
    extremes for the date, and its precipitation."""
    from linecast.sunshine.i18n import _fmt_month_day, relative_day
    from linecast.weather.daily import fmt_precip_amount, fmt_snow_amount
    from linecast.weather.sections import _PRECIP_CODES
    from linecast.weather.style import _colored_temp, _precip_rgb

    tbg = bg(*_style.TOOLTIP_BG_RGB)
    tfg = fg(*_style.TOOLTIP_TEXT_RGB)
    tdim = _style.DIM
    d = jan1 + timedelta(days=k)
    when = _fmt_month_day(d, runtime)
    if days:
        when += f" · {relative_day(k - days.today, runtime)}"
    lines = [f"{tbg}{tdim} {when} "]
    if days and days.highs[k] is not None and days.lows[k] is not None:
        lines.append(f"{tbg} {_colored_temp(days.highs[k], runtime, '°')}{tfg} / "
                     f"{_colored_temp(days.lows[k], runtime, '°')} ")
    if climate:
        s = slots[k]
        nh, nl = climate.normal_high[s], climate.normal_low[s]
        if nh is not None and nl is not None:
            lines.append(f"{tbg}{tdim} {_s('avg', runtime)} {tfg}{nh:.0f}° / {nl:.0f}° ")
        top, bottom = climate.top[s], climate.bottom[s]
        if top is not None and bottom is not None:
            first, last = climate.span
            lines.append(f"{tbg}{tdim} {first}–{last} {tfg}{top:.0f}° / {bottom:.0f}° ")
    snow = days.snow[k] if days and days.snow else None
    if snow and snow >= (0.3 if runtime.metric else 0.1):
        # A snowy day's snow as it lay, and under it the water it melted
        # to, which is what the running total adds
        lines.append(f"{tbg}{fg(*SNOW_RGB)} {_wmo_icons(runtime).get(73, '')} "
                     f"{_s('Snow', runtime)} {fmt_snow_amount(snow, runtime)} ")
        if days.precip[k]:
            water = fmt_precip_amount(days.precip[k], runtime)
            lines.append(f"{tbg}{tdim} {_s('of_water', runtime, amt=water)} ")
    elif days and days.precip[k]:
        code = days.codes[k] if days.codes[k] in _PRECIP_CODES else 61
        icon = _wmo_icons(runtime).get(code, "")
        ink = fg(*_precip_rgb(code))
        lines.append(f"{tbg}{ink} {icon} {fmt_precip_amount(days.precip[k], runtime)} ")
    return _live.pointer_chip(lines, col + 3, mouse_row, cols, rows,
                              pad_bg=tbg, flip_at=col + 2)
