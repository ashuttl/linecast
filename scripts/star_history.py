"""Draw the repository's GitHub star history as a braille curve.

    python3 scripts/star_history.py [owner/repo] [--days N] [--weeks N] [--width N]

Asks the stargazers API for the star media type, which adds a starred_at
timestamp to each entry, and plots the running total with the same braille
curve builder the weather and tide charts use.

--days and --weeks narrow the window to the most recent stretch.  The curve
still plots the true running total, so the axis starts wherever the
repository stood when the window opened rather than at zero.  A narrow
window is cheap: stargazers come back oldest first, so the fetch walks the
pages backwards from the newest and stops at the first one past the cutoff.

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

DEFAULT_REPO = "ashuttl/linecast"
PER_PAGE = 100
ROWS = 8
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
        stamps = [dt.date.fromisoformat(s["starred_at"][:10]) for s in batch]
        kept = [d for d in stamps if cutoff is None or d >= cutoff]
        dates = kept + dates
        if len(kept) < len(stamps):
            break
    return sorted(dates), max(0, total - len(dates))


def running_totals(dates, before, start, end):
    """The repository's total star count on each day from start to end."""
    per_day = [0] * ((end - start).days + 1)
    for d in dates:
        i = (d - start).days
        if 0 <= i < len(per_day):
            per_day[i] += 1
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


def y_labels(lo, hi, rows):
    """A label per character row, on the rows round values land in."""
    labels = [""] * rows
    if hi <= lo:
        labels[rows // 2] = str(int(hi))
        return labels
    dots = rows * 4
    step = nice_step(hi - lo)
    value = (int(lo) // step) * step
    while value <= hi:
        if value >= lo:
            row = round((1 - (value - lo) / (hi - lo)) * (dots - 1)) // 4
            if not labels[row]:
                labels[row] = str(int(value))
        value += step
    return labels


def date_label(day, with_day):
    month = MONTHS[day.month - 1]
    return f"{day.day} {month}" if with_day else month


def x_ticks(start, end, span):
    """(date, label) pairs to mark under the curve, at a spacing the span suits."""
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


def x_axis(start, end, span, width):
    """The tick row and the label row beneath the curve."""
    marks = [" "] * width
    names = [" "] * width
    for day, label in x_ticks(start, end, span):
        col = round((day - start).days / max(1, span - 1) * (width - 1))
        if not 0 <= col < width:
            continue
        marks[col] = "╷"
        at = min(col, width - len(label))  # flush left of the edge rather than dropped
        if at >= 0 and all(c == " " for c in names[max(0, at - 1):at + len(label) + 1]):
            names[at:at + len(label)] = label
    return "".join(marks), "".join(names)


def main():
    argv = sys.argv[1:]

    def option(name, default=None):
        return int(argv[argv.index(name) + 1]) if name in argv else default

    days = option("--days")
    weeks = option("--weeks")
    if weeks is not None:
        days = weeks * 7
    width = option("--width")
    repo = next((a for a in argv if "/" in a), DEFAULT_REPO)

    today = dt.datetime.now(dt.timezone.utc).date()  # stars are stamped UTC
    cutoff = today - dt.timedelta(days=days - 1) if days else None
    dates, before = star_dates(repo, cutoff)
    if not dates and not before:
        sys.exit(f"{repo} has no stars yet.")

    if not cutoff:
        start = dates[0]
    elif not before and dates and cutoff < dates[0]:
        start = dates[0]  # the window reaches back past the first star there ever was
    else:
        start = cutoff
    end = max(dates[-1], today) if dates else today
    series = running_totals(dates, before, start, end)
    span = len(series)
    total = series[-1]

    _theme.ensure_theme_loaded()
    muted = fg(*ensure_contrast(neutral_tone(0.48), _theme.theme_bg, minimum=2.5))
    dim = fg(*ensure_contrast(neutral_tone(0.32), _theme.theme_bg, minimum=2.0))

    lo = min(series) if cutoff else 0
    labels = y_labels(lo, total, ROWS)
    gutter = max(len(text) for text in labels)
    if width is None:
        width = max(20, shutil.get_terminal_size((80, 24)).columns - gutter - 2)
    curve = build_braille_curve(series, width, n_rows=ROWS, value_range=(lo, total))

    gained = len(dates)
    opened = date_label(start, True)
    if start.year != end.year:
        opened += f" {start.year}"
    window = f"{opened} to {date_label(end, True)} {end.year}"
    if cutoff:
        unit = "day" if days == 1 else "days"
        window = f"+{gained} in the last {days} {unit} \u00b7 {window}"
    print()
    print(f"  {repo} — {total} stars  {muted}{window}{RESET}")
    print()
    for label, row in zip(labels, curve):
        cells = "".join(char for char, _ in row)
        print(f"{dim}{label:>{gutter}}{RESET} {cells}")
    marks, names = x_axis(start, end, span, width)
    print(f"{' ' * gutter} {dim}{marks}{RESET}")
    print(f"{' ' * gutter} {muted}{names}{RESET}")
    print()


if __name__ == "__main__":
    main()
