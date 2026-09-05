"""The sky's tradition picker: `t` opens a panel listing the IAU sky and
the twenty-two cultures, and the sky draws whichever is highlighted, so
the figures and names change as the arrows move. Enter keeps the one
shown, Escape puts the sky back as it was.

The panel is the search panel's twin: the same surface at the top left,
the sky left in view beside it for the preview. The list is longer than
a short terminal, so it scrolls, keeping the highlight in view.
"""

from linecast import _theme
from linecast._config import CULTURE_CHOICES
from linecast._graphics import RESET, bg, fg, visible_len
from linecast._theme import ensure_contrast, surface_bg

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
    the title on the top row, the list under it, a rule after the IAU
    row. A list taller than the terminal scrolls about the highlight,
    with ▲ and ▼ where there is more."""
    from linecast._sky_i18n import _sk
    from linecast._sky_search import PANEL_MAX, PANEL_MIN, _fit
    surface = surface_bg(0.10)
    ink = ensure_contrast(_theme.theme_fg, surface, 4.0)
    dim = ensure_contrast(surface_bg(0.55), surface, 2.2)
    widest = max(visible_len(title) for _c, title in state.rows) + 6
    width = max(PANEL_MIN, min(PANEL_MAX, cols - 2, widest))

    def row(n, body):
        pad = " " * max(0, width - visible_len(body))
        return f"\033[{n};1H{bg(*surface)}{body}{pad}{RESET}"

    # The lines of the list: a row index, or None for the rule.
    entries = []
    for i, (culture, _title) in enumerate(state.rows):
        entries.append(i)
        if culture is IAU:
            entries.append(None)
    avail = max(3, rows - 2)
    scrolls = len(entries) > avail
    if scrolls:
        window = avail - 2   # a row each for ▲ and ▼
        at = entries.index(state.sel)
        start = min(max(0, at - window // 2), len(entries) - window)
    else:
        window, start = len(entries), 0
    shown = entries[start:start + window]

    out = [row(1, f"{fg(*dim)} {_sk('tradition', runtime)}")]
    line = 2
    if scrolls:
        out.append(row(line, f"{fg(*dim)} ▲" if start > 0 else ""))
        line += 1
    for i in shown:
        if i is None:
            out.append(row(line, f"{fg(*dim)} {'─' * (width - 2)}"))
        else:
            culture, title = state.rows[i]
            mark = "●" if culture == state.kept else " "
            body = f" {mark} {_fit(title, width - 4)}"
            body += " " * max(0, width - visible_len(body))
            if i == state.sel:
                body = f"\033[7m{body}\033[27m"
            out.append(row(line, f"{fg(*ink)}{body}"))
        line += 1
    if scrolls:
        more = start + window < len(entries)
        out.append(row(line, f"{fg(*dim)} ▼" if more else ""))
    return "".join(out)
