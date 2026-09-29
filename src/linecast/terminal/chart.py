"""What the time charts share: weather's hourly chart and the tides
chart put the same row of hour ticks under their curves.  Each finds its
own hours, from its samples or from the clock, and lays them out here."""


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
