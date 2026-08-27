"""Draft month-strip designs for the moon view — a parked exploration.

    uv run python scripts/moon_strip.py [width] [--at ISO_LOCAL_TIME]
    uv run python scripts/moon_strip.py --in-situ A

The first form prints every candidate inline, across all three icon
sets, so they can be read side by side.  The second renders the real
moon view at the real terminal size with the chosen strip along the
bottom, which is the only way to judge what it costs: a strip is paid
for out of the sky, and the disc shrinks by exactly the rows it takes.

Every strip spans the current lunation — the new moon just past on the
left, the next new moon on the right, tonight marked in between.  That
framing is what would let a strip *replace* the "Full ... / New ..."
lines rather than sit alongside them, since it carries both dates and
says where in the cycle tonight falls.

Nothing here is wired into the real view.  Kept because the question is
open, not because it is finished; see issue #26.  What the drafts
established so far:

  A  rule + principal phases + dates.  The most complete, and the only
     one whose today-marker gets its own row — which is why it costs
     three rows rather than two.
  B  phase ramp.  Redundant: the disc already shows the phase.
  C  illumination curve in braille.  Draws a cosine you can already read
     off "96% illuminated"; four rows for no new fact.
  D  illumination bars.  As C, fatter.
  E  spare: dates on a rule, two rows.  Cheapest, but the today marker
     collides with the full-moon glyph and hides it — visible on any day
     near full.

The open question is not which strip, but whether any of them beats the
text they would replace: those lines carry the almanac name ("Full
Sturgeon Moon") and the countdowns, and no strip here carries either.
"""
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, "src")

from linecast._color import RESET, fg
from linecast._moon_i18n import _fmt_month_day
from linecast._runtime import RuntimeConfig
from linecast._textwidth import char_width, visible_len
from linecast.sunshine import (
    INFO_AMBER_RGB, INFO_DIM_RGB, INFO_TEXT_RGB, SYNODIC_MONTH,
    _icon_set, moon_cycle_frac,
)

AMBER, DIM, TEXT = fg(*INFO_AMBER_RGB), fg(*INFO_DIM_RGB), fg(*INFO_TEXT_RGB)

# Eighth-of-a-cycle index for a position in the lunation, matching the
# eight icons in each set.
def _icon_at(t, icons):
    return icons[int((t % 1.0) * 8 + 0.5) % 8]


def _lunation(now):
    """(last new moon, next new moon, full moon, position 0-1) for *now*."""
    frac = moon_cycle_frac(now)
    last_new = now - timedelta(days=frac * SYNODIC_MONTH)
    return (last_new, last_new + timedelta(days=SYNODIC_MONTH),
            last_new + timedelta(days=SYNODIC_MONTH / 2), frac)


def _place(line, col, text):
    """Overwrite *line* (a list of cells) at *col* with *text*.

    A double-width glyph claims a second, empty cell so the row keeps its
    width when joined — the same trick the info column uses.
    """
    x = col
    for i, ch in enumerate(text):
        w = char_width(ch, text[i + 1:i + 2])
        if w == 0:                       # variation selector: ride along
            if col <= x - 1 < len(line):
                line[x - 1] += ch
            continue
        if 0 <= x < len(line):
            line[x] = ch
            if w == 2 and x + 1 < len(line):
                line[x + 1] = ""
        x += w
    return line


def _marker_row(width, pos, label):
    row = [" "] * width
    col = min(width - 1, max(0, round(pos * (width - 1))))
    col = max(0, min(col, width - visible_len(label) - 3))
    _place(row, col, "▲")
    _place(row, col + 2, label)
    return f"{AMBER}{''.join(row)}{RESET}"


# --------------------------------------------------------------------
# The candidates
# --------------------------------------------------------------------
def rule(now, rt, width):
    """A: principal phases on a rule, dates beneath the ones that matter."""
    icons = _icon_set(rt)["moon_icons"]
    last_new, next_new, full, t = _lunation(now)
    line = ["─"] * width
    for frac_pos, idx in ((0.0, 0), (0.25, 2), (0.5, 4), (0.75, 6), (1.0, 0)):
        _place(line, round(frac_pos * (width - 1)), icons[idx])
    dates = [" "] * width
    _place(dates, 0, _fmt_month_day(last_new, rt))
    fl = _fmt_month_day(full, rt)
    _place(dates, round(0.5 * (width - 1)) - visible_len(fl) // 2, fl)
    nl = _fmt_month_day(next_new, rt)
    _place(dates, width - visible_len(nl), nl)
    return [f"{TEXT}{''.join(line)}{RESET}",
            f"{DIM}{''.join(dates)}{RESET}",
            _marker_row(width, t, "tonight")]


def ramp(now, rt, width):
    """B: the phase itself, sampled across the cycle."""
    icons = _icon_set(rt)["moon_icons"]
    _last_new, _next_new, _full, t = _lunation(now)
    step = visible_len(icons[0]) or 1
    n = max(4, width // step)
    line = "".join(_icon_at(i / (n - 1), icons) for i in range(n))
    return [f"{TEXT}{line}{RESET}", _marker_row(width, t, "tonight")]


def curve(now, rt, width):
    """C: illuminated fraction as a braille curve, the app's chart idiom."""
    from linecast._braille import build_braille_curve
    from linecast.moon import moon_illumination

    last_new, _next_new, _full, t = _lunation(now)
    vals = [moon_illumination(last_new + timedelta(days=SYNODIC_MONTH * i
                                                   / (width * 2 - 1)))
            for i in range(width * 2)]
    rows = build_braille_curve(vals, width, n_rows=2, value_range=(0.0, 1.0))
    out = [f"{TEXT}{''.join(ch for ch, _v in row)}{RESET}" for row in rows]
    icons = _icon_set(rt)["moon_icons"]
    base = [" "] * width
    _place(base, 0, icons[0])
    _place(base, round(0.5 * (width - 1)), icons[4])
    _place(base, width - visible_len(icons[0]), icons[0])
    return out + [f"{DIM}{''.join(base)}{RESET}", _marker_row(width, t, "tonight")]


def bars(now, rt, width):
    """D: illuminated fraction as a block ramp."""
    from linecast.moon import moon_illumination

    last_new, _next_new, _full, t = _lunation(now)
    blocks = " ▁▂▃▄▅▆▇█"
    line = ""
    for i in range(width):
        v = moon_illumination(last_new + timedelta(
            days=SYNODIC_MONTH * i / (width - 1)))
        line += blocks[min(8, int(v * 8 + 0.5))]
    return [f"{TEXT}{line}{RESET}", _marker_row(width, t, "tonight")]


def spare(now, rt, width):
    """E: just the two dates the text lines carried, placed on a rule."""
    icons = _icon_set(rt)["moon_icons"]
    last_new, next_new, full, t = _lunation(now)
    line = ["·"] * width
    mid = round(0.5 * (width - 1))
    _place(line, 0, icons[0])
    _place(line, mid, icons[4])
    _place(line, width - visible_len(icons[0]), icons[0])
    col = min(width - 1, max(0, round(t * (width - 1))))
    _place(line, col, "│")
    labels = [" "] * width
    _place(labels, 0, _fmt_month_day(last_new, rt))
    fl = _fmt_month_day(full, rt)
    _place(labels, mid - visible_len(fl) // 2, fl)
    nl = _fmt_month_day(next_new, rt)
    _place(labels, width - visible_len(nl), nl)
    return [f"{TEXT}{''.join(line)}{RESET}", f"{DIM}{''.join(labels)}{RESET}"]


CANDIDATES = [
    ("A  rule + principal phases", rule),
    ("B  phase ramp", ramp),
    ("C  illumination curve (braille)", curve),
    ("D  illumination bars", bars),
    ("E  spare: dates on a rule", spare),
]
CANDIDATES_BY_KEY = [(label.split()[0], fn) for label, fn in CANDIDATES]

LAT, LNG = 43.7, -79.4
STRIP_MAX = 58


def main():
    argv = sys.argv[1:]
    now = datetime.now().astimezone()
    if "--at" in argv:
        now = datetime.fromisoformat(argv[argv.index("--at") + 1]).astimezone()
    rt = RuntimeConfig(live=False, icons="emoji", lang="en", oneline=False)

    if "--in-situ" in argv:
        i = argv.index("--in-situ")
        which = argv[i + 1] if len(argv) > i + 1 else "A"
        print(in_situ(now, rt, which.upper(), LAT, LNG))
        return

    width = next((int(a) for a in argv if a.isdigit()), 56)
    for icons in ("emoji", "plain", "nerd"):
        r = RuntimeConfig(live=False, icons=icons, lang="en", oneline=False)
        print(f"\n\x1b[1m=== {icons} icons, width {width} ===\x1b[0m")
        for label, fn in CANDIDATES:
            print(f"\n  {DIM}{label}{RESET}")
            for line in fn(now, r, width):
                print("  " + line)
    print()


if __name__ == "__main__":
    main()
