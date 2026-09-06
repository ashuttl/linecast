"""The sky's tradition picker: `t` opens a panel listing the IAU sky and
the twenty-two cultures, and the sky draws whichever is highlighted, so
the figures and names change as the arrows move. Enter keeps the one
shown, Escape puts the sky back as it was.

The panel is the radar's theme picker: the same box, centred, drawn
by _live.menu_box. The list is longer than a short terminal, so it
scrolls, keeping the highlight in view.
"""

from linecast import _live
from linecast._config import CULTURE_CHOICES
from linecast._graphics import bg, fg
from linecast._theme import surface_bg

IAU = None   # the culture value for the IAU sky


def choices(lang):
    """The rows, as (culture, title): the IAU sky first, then the cultures
    in the order their titles sort in the display language."""
    from linecast._sky_catalogue import culture_title
    titled = [(culture_title(c, lang), c) for c in CULTURE_CHOICES if c != "none"]
    titled.sort(key=lambda row: row[0].casefold())
    return [(IAU, "IAU")] + [(c, t) for t, c in titled]


class CulturePicker:
    """The panel's state: closed, or open on a highlighted row.

    `handle(action, current)` consumes one key. It returns False for a
    key that is not the panel's — any key while closed but `t` — and
    True otherwise, after which `culture` is the culture the sky should
    draw: the highlighted one while the panel is open, the chosen one
    after Enter or `t`, and the one the panel opened on after Escape.
    """

    def __init__(self, lang):
        self.lang = lang
        self.rows = []        # (culture, title) while open
        self.sel = None       # None = closed, else the highlighted row
        self.kept = None      # the culture on opening, back with Escape
        self.culture = None   # what the sky should draw now

    @property
    def open(self):
        return self.sel is not None

    def start(self, current):
        self.rows = choices(self.lang)
        cultures = [c for c, _t in self.rows]
        self.sel = cultures.index(current) if current in cultures else 0
        self.kept = self.culture = current

    def close(self):
        self.sel = None

    def move(self, delta):
        """Move the highlight `delta` rows down (up when negative), wrapping;
        the sky follows."""
        if not self.open:
            return False
        self.sel = (self.sel + delta) % len(self.rows)
        self.culture = self.rows[self.sel][0]
        return True

    def handle(self, action, current):
        if not self.open:
            if action == "key:t":
                self.start(current)
                return True
            return False
        if action == "fwd":
            self.move(-1)
        elif action == "back":
            self.move(1)
        elif action in ("key:enter", "key:t"):
            self.culture = self.rows[self.sel][0]
            self.close()
        elif action in ("escape", "quit"):
            self.culture = self.kept
            self.close()
        return True   # while the panel is open, no key reaches the sky


def picker_overlay(state, cols, rows, runtime):
    """The panel, as cursor-addressed escapes for the floating channel:
    the list in a box with a rule after the IAU row. A list taller than
    the terminal scrolls about the highlight, with ▲ and ▼ in the
    borders where there is more."""
    from linecast._sky_i18n import _sk
    # The lines of the list: a row index, or None for the rule.
    entries = []
    for i, (culture, _title) in enumerate(state.rows):
        entries.append(i)
        if culture is IAU:
            entries.append(None)
    window = max(3, rows - 4)
    at = entries.index(state.sel)
    start = min(max(0, at - window // 2), max(0, len(entries) - window))
    shown = entries[start:start + window]
    lines = []
    for i in shown:
        if i is None:
            lines.append(None)
        else:
            culture, title = state.rows[i]
            mark = "●" if culture == state.kept else " "
            lines.append(f" {mark} {title}")
    return _live.menu_box(
        lines, cols, rows, title=_sk("tradition", runtime),
        sel=shown.index(state.sel), border=fg(*_live.MUTED),
        fill=bg(*surface_bg(0.10)),
        more=(start > 0, start + window < len(entries)))
