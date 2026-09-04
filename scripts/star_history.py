#!/usr/bin/env python3
"""Draw the repository's GitHub star history as a bar per day.

    python3 scripts/star_history.py [owner/repo] [--days N] [--weeks N] [--width N]
                                    [--smooth] [--total]

Asks the stargazers API for the star media type, which adds a starred_at
timestamp to each entry, and draws the stars gained each day as a block
bar, the way the hourly forecast draws rain.  Days are local: a star at
nine in the evening counts toward the evening, not the UTC morning after.

--smooth draws each day as the average of the seven days ending there,
which flattens the spike a link somewhere makes and shows the pace
underneath.

--days and --weeks narrow the window to the most recent stretch.  --total
plots the running total as a braille curve instead, which is also what a
window too long to give every day a column of its own falls back to.  The
curve starts wherever the repository stood when the window opened rather
than at zero; the bars always stand on zero.

A narrow window is cheap: stargazers come back oldest first, so the fetch
walks the pages backwards from the newest and stops at the first one past
the cutoff.

The API lists the people who have a star today, so a star since taken away
was never there as far as this chart is concerned.
"""

import datetime as dt
import json
import math
import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from linecast import _theme  # noqa: E402
from linecast._braille import build_braille_curve  # noqa: E402
from linecast._color import RESET, fg  # noqa: E402
from linecast._theme import ensure_contrast, neutral_tone  # noqa: E402
from linecast._weather_style import SPARKLINE  # noqa: E402

DEFAULT_REPO = "ashuttl/linecast"
PER_PAGE = 100
ROWS = 8
SLOT_MAX = 7  # a few days shouldn't spread into slabs
SMOOTH_DAYS = 7
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def gh(path):
    """One `gh api` call against the star media type, decoded."""
    run = subprocess.run(
        ["gh", "api", "-H", "Accept: application/vnd.github.star+json", path],
        capture_output=True, text=True,
    )
    if run.returncode:
        sys.exit(run.stderr.strip() or f"gh api {path} failed")
    return json.loads(run.stdout)


def local_date(stamp):
    """The local calendar day an ISO-8601 UTC timestamp falls on."""
    return dt.datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone().date()


def star_dates(repo, cutoff):
    """Star dates on or after *cutoff*, and the total standing before it.

    Walks pages newest first, so a short window reads a page or two.
    """
    total = gh(f"repos/{repo}")["stargazers_count"]
    if not total:
        return [], 0
    dates = []
    for page in range((total + PER_PAGE - 1) // PER_PAGE, 0, -1):
        batch = gh(f"repos/{repo}/stargazers?per_page={PER_PAGE}&page={page}")
        stamps = [local_date(s["starred_at"]) for s in batch]
        kept = [d for d in stamps if cutoff is None or d >= cutoff]
        dates = kept + dates
        if len(kept) < len(stamps):
            break
    return sorted(dates), max(0, total - len(dates))


def daily_counts(dates, start, end):
    """The stars gained on each day from start to end."""
    per_day = [0] * ((end - start).days + 1)
    for d in dates:
        i = (d - start).days
        if 0 <= i < len(per_day):
            per_day[i] += 1
    return per_day


def rolling_mean(values, window):
    """Each value averaged with the ones before it, *window* wide.

    The first few average over what stands before them, so the early days
    of a fresh repository read as zeros beforehand, which they were.
    """
    smoothed = []
    for i in range(len(values)):
        smoothed.append(sum(values[max(0, i - window + 1):i + 1]) / window)
    return smoothed


def running_totals(per_day, before):
    """The repository's total star count at the end of each day."""
    total = before
    series = []
    for gained in per_day:
        total += gained
        series.append(total)
    return series


def nice_step(span, ticks=5):
    """A round interval that puts about *ticks* labels across *span*."""
    if span <= 0:
        return 1
    rough = span / ticks
    magnitude = 10 ** math.floor(math.log10(rough))
    for step in (1, 2, 5, 10):
        if rough <= step * magnitude:
            return max(1, int(step * magnitude))
    return max(1, int(10 * magnitude))


def y_labels(lo, hi, rows, units=4):
    """A label per character row, on the rows round values land in.

    *units* is the vertical resolution of one row: four dots for a braille
    curve, eight steps for a block bar.
    """
    labels = [""] * rows
    if hi <= lo:
        labels[rows // 2] = str(int(hi))
        return labels
    steps = rows * units
    step = nice_step(hi - lo)
    value = (int(lo) // step) * step
    while value <= hi:
        if value >= lo:
            row = round((1 - (value - lo) / (hi - lo)) * (steps - 1)) // units
            if not labels[row]:
                labels[row] = str(int(value))
        value += step
    return labels


def bar_rows(values, peak, rows, bar, gap):
    """Block bars, one per value, standing on zero and grown in eighths."""
    heights = []
    for value in values:
        eighths = round(value / peak * rows * 8) if peak else 0
        heights.append(max(1, eighths) if value else 0)  # a day with a star shows one
    lines = []
    for r in range(rows):
        floor = (rows - 1 - r) * 8  # the eighths already filled below this row
        cells = []
        for height in heights:
            filled = min(8, max(0, height - floor))
            cells.append((SPARKLINE[filled - 1] if filled else " ") * bar + " " * gap)
        lines.append("".join(cells).rstrip())
    return lines


def date_label(day, with_day):
    month = MONTHS[day.month - 1]
    return f"{day.day} {month}" if with_day else month


def x_ticks(start, end, span):
    """(date, label) pairs to mark under the chart, at a spacing the span suits."""
    if span <= 21:
        every = 1 if span <= 8 else 3
        days = [start + dt.timedelta(days=i) for i in range(0, span, every)]
        return [(d, date_label(d, True)) for d in days]
    if span <= 130:
        day = start + dt.timedelta(days=-start.weekday() % 7)  # the first Monday
        ticks = []
        while day <= end:
            ticks.append((day, date_label(day, True)))
            day += dt.timedelta(days=7)
        return ticks
    month = start.replace(day=1)
    ticks = []
    while month <= end:
        if month >= start:
            ticks.append((month, date_label(month, False)))
        month = (month.replace(day=28) + dt.timedelta(days=7)).replace(day=1)
    return ticks


def x_axis(start, end, span, width, column):
    """The tick row and the label row beneath the chart.

    *column* gives the column a day's mark belongs over.
    """
    marks = [" "] * width
    names = [" "] * width
    for day, label in x_ticks(start, end, span):
        col = column((day - start).days)
        if not 0 <= col < width:
            continue
        marks[col] = "╷"
        at = min(col, width - len(label))  # flush left of the edge rather than dropped
        if at >= 0 and all(c == " " for c in names[max(0, at - 1):at + len(label) + 1]):
            names[at:at + len(label)] = label
    return "".join(marks).rstrip(), "".join(names).rstrip()


def main():
    argv = sys.argv[1:]

    def option(name, default=None):
        return int(argv[argv.index(name) + 1]) if name in argv else default

    days = option("--days")
    weeks = option("--weeks")
    if weeks is not None:
        days = weeks * 7
    width = option("--width")
    smooth = "--smooth" in argv
    as_total = "--total" in argv
    repo = next((a for a in argv if "/" in a), DEFAULT_REPO)

    today = dt.date.today()
    cutoff = today - dt.timedelta(days=days - 1) if days else None
    # A smoothed window needs the days before it to average the first bars over.
    warmup = SMOOTH_DAYS - 1 if smooth and cutoff else 0
    fetched, before = star_dates(repo, cutoff - dt.timedelta(days=warmup) if cutoff else None)
    if not fetched and not before:
        sys.exit(f"{repo} has no stars yet.")
    dates = [d for d in fetched if cutoff is None or d >= cutoff]
    before += len(fetched) - len(dates)

    if not cutoff:
        start = dates[0]
    elif not before and dates and cutoff < dates[0]:
        start = dates[0]  # the window reaches back past the first star there ever was
    else:
        start = cutoff
    end = max(dates[-1], today) if dates else today
    per_day = daily_counts(dates, start, end)
    series = running_totals(per_day, before)
    span = len(per_day)
    total = series[-1]
    if smooth:
        lead = start - dt.timedelta(days=warmup)
        bars = rolling_mean(daily_counts(fetched, lead, end), SMOOTH_DAYS)[warmup:]
    else:
        bars = per_day

    _theme.ensure_theme_loaded()
    muted = fg(*ensure_contrast(neutral_tone(0.48), _theme.theme_bg, minimum=2.5))
    dim = fg(*ensure_contrast(neutral_tone(0.32), _theme.theme_bg, minimum=2.0))

    peak = max(bars)
    lo = min(series) if cutoff else 0
    bar_labels = y_labels(0, peak, ROWS, units=8)
    curve_labels = y_labels(lo, total, ROWS)
    if width is None:
        gutter = max(len(text) for text in curve_labels)  # the wider of the two
        width = max(20, shutil.get_terminal_size((80, 24)).columns - gutter - 2)

    if not as_total and span <= width:  # a day too narrow for a bar wants the curve
        labels = bar_labels
        slot = min(width // span, SLOT_MAX)
        gap = 1 if slot >= 2 else 0
        bar = slot - gap
        rows = bar_rows(bars, peak, ROWS, bar, gap)
        def column(i):
            return i * slot + (bar - 1) // 2  # the middle of that day's bar
    else:
        labels = curve_labels
        curve = build_braille_curve(series, width, n_rows=ROWS, value_range=(lo, total))
        rows = ["".join(char for char, _ in row) for row in curve]
        def column(i):
            return round(i / max(1, span - 1) * (width - 1))
    gutter = max(len(text) for text in labels)

    gained = len(dates)
    opened = date_label(start, True)
    if start.year != end.year:
        opened += f" {start.year}"
    window = f"{opened} to {date_label(end, True)} {end.year}"
    if cutoff:
        unit = "day" if days == 1 else "days"
        window = f"+{gained} in the last {days} {unit} \u00b7 {window}"
    if smooth and not as_total and span <= width:
        window = f"{SMOOTH_DAYS}-day average \u00b7 {window}"
    print()
    print(f"  {repo} — {total} stars  {muted}{window}{RESET}")
    print()
    for label, row in zip(labels, rows):
        print(f"{dim}{label:>{gutter}}{RESET} {row}")
    marks, names = x_axis(start, end, span, width, column)
    print(f"{' ' * gutter} {dim}{marks}{RESET}")
    print(f"{' ' * gutter} {muted}{names}{RESET}")
    print()


if __name__ == "__main__":
    main()
