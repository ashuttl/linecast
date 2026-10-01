"""What the charts share.  Weather's hourly chart and the tides chart put
the same row of hour ticks under their curves: each finds its own hours,
from its samples or from the clock, and lays them out here.  Weather's
year and the tides' year lay the same days across the same columns, over
the same row of months.
"""

import calendar

from linecast.terminal import theme as _theme
from linecast.terminal.color import RESET, bg
from linecast.terminal.textwidth import char_width, visible_len


def tick_interval(graph_w):
    """The hours between labelled ticks on a chart *graph_w* columns wide."""
    if graph_w < 40:
        return 6
    if graph_w < 80:
        return 4
    if graph_w < 140:
        return 3
    return 2


def tick_canvas(items, graph_w, hover_col=None, now_col=None):
    """The tick row, as plain text *graph_w* columns wide.

    Each of *items*, (column, label, midnight), is a tick with its label
    after it: ╵ for an hour, │ for midnight.  They go left to right, and
    one that would run into the label before it, or off the edge, is
    left out.  Then a hairline marks the pointer's column, or else now's,
    where the row is empty there."""
    canvas = [" "] * graph_w
    last_end = 0
    for x, label, is_midnight in items:
        tick = "│" if is_midnight else "╵"
        tick_label = f"{tick}{label}"
        if x < last_end or x + len(tick_label) > graph_w:
            continue
        for j, c in enumerate(tick_label):
            if x + j < graph_w:
                canvas[x + j] = c
        last_end = x + len(tick_label) + 1
    if hover_col is not None and 0 <= hover_col < graph_w and canvas[hover_col] == " ":
        canvas[hover_col] = "│"
    elif now_col is not None and 0 <= now_col < graph_w and canvas[now_col] == " ":
        canvas[now_col] = "│"
    return "".join(canvas)


# ---------------------------------------------------------------------------
# A year across the chart
# ---------------------------------------------------------------------------
def month_starts(year):
    """Day index of each month's first day, and the year's length;
    `starts[1:] + [n]` are the months' ends."""
    starts, k = [], 0
    for m in range(1, 13):
        starts.append(k)
        k += calendar.monthrange(year, m)[1]
    return starts, k


def day_span(i, width, n):
    """The days, as a range, that column i of `width` covers."""
    a = int(i * n / width)
    return range(a, max(a + 1, int((i + 1) * n / width)))


def month_axis(labels, starts, n, width, ink, dim, this_month=None, whole=False):
    """The twelve *labels* at their months' starts, the current one in
    *ink* and the others in *dim*.  With *whole*, a month too narrow for
    its label goes without one; otherwise the label is cut at the edge."""
    cells = [" "] * width
    xs = [min(width - 1, int(s / n * width)) for s in starts] + [width]
    for m, label in enumerate(labels):
        x = xs[m]
        if whole and visible_len(label) + 1 > xs[m + 1] - x:
            continue
        color = ink if m == this_month else dim
        placed = []
        for ch in label:
            w = char_width(ch)
            if w == 0 and placed:
                cells[placed[-1]] += ch
                continue
            if x + w > width:
                break
            cells[x] = f"{color}{ch}"
            placed.append(x)
            for j in range(1, w):
                cells[x + j] = ""
            x += w
    return "".join(cells) + RESET


def on_the_page(lines, cols):
    """The view's lines, joined, and painted to the margin in the
    theme's background where that is not the terminal's own: in
    linecast's palette (--classic-colors, or a terminal that did not say
    what its colors are).  The panels paint every cell, and without this
    the header, the scale, the month axis and the footer would sit on
    the terminal's background beside them."""
    page = "" if _theme.theme_available else bg(*_theme.theme_bg)
    if not (page and RESET):
        return "\n".join(lines)
    return "\n".join(
        page + line.replace(RESET, RESET + page) + " " * max(0, cols - visible_len(line))
        + RESET for line in lines)
