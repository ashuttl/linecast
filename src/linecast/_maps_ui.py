"""The `/` search prompt — its state machine, its worker, its chrome.

Chrome-light by design: no box rules, no spinner.  The panel is its own
ground, the field replaces the header, and a pending request shows as a
trailing ellipsis rather than an animation (the live loop repaints on
input and SIGWINCH, so nothing would turn a spinner anyway).

The threading rule is the interesting part.  Photon advertises
search-as-you-type, so every keystroke may ask — but one thread per
keystroke would be rude to a volunteer service and racy on the way
back.  Instead there is exactly one re-armed timer: a keystroke cancels
the pending one, bumps a generation counter and arms a fresh one.
In-flight urllib requests cannot be cancelled, so the generation check
on the way back is what guarantees only the newest query's results ever
reach the screen.  Nominatim is never asked per keystroke — only on
Enter, when Photon has come back empty.
"""

import os
import signal
import threading

from linecast._color import RESET, bg, fg
from linecast._framebuffer import visible_len
from linecast._maps_i18n import ms
from linecast._maps_search import (
    SearchUnavailable, nominatim_search, photon_search,
)
from linecast._theme import ensure_contrast, surface_bg, theme_fg
from linecast.radar import DIM, MUTED

MIN_CHARS = 2          # below this, asking is noise for both of us
DEBOUNCE = 0.28        # seconds of quiet before a keystroke becomes a query
MAX_ROWS = 8
PANEL_MIN = 30
PANEL_MAX = 56


def _sigwinch():
    """Wake the live loop the way the background fetchers already do."""
    os.kill(os.getpid(), signal.SIGWINCH)


class SearchState:
    """Everything the `/` prompt knows, and the one worker that feeds it.

    `fetch` and `one_shot` are injectable so the state machine can be
    tested without a network; `refresh` is the repaint poke.
    """

    def __init__(self, refresh=None, fetch=None, one_shot=None):
        self.open = False
        self.query = ""
        self.results = []
        self.sel = 0
        self.status = ""        # "" | "pending" | "none" | "error"
        self.chosen = None      # a committed Result, drained by the caller
        self.submitted = False  # Enter pressed while a request was in flight
        self.gen = 0
        self._timer = None
        self._lock = threading.Lock()
        self._refresh = refresh or _sigwinch
        self._fetch = fetch or photon_search
        self._one_shot = one_shot or nominatim_search

    # -- lifecycle ---------------------------------------------------------
    def start(self):
        self.open = True
        self.query = ""
        self.results = []
        self.sel = 0
        self.status = ""
        self.submitted = False
        self._cancel()

    def close(self):
        """Close and discard.  The typed query is the only thing esc
        costs, which is what makes esc safe to press."""
        self.open = False
        self.query = ""
        self.results = []
        self.status = ""
        self.submitted = False
        self._cancel()

    def take_chosen(self):
        """Hand the committed result to the caller, once."""
        hit, self.chosen = self.chosen, None
        return hit

    def _cancel(self):
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        self.gen += 1           # anything already in flight is now stale

    # -- input -------------------------------------------------------------
    def handle(self, action, lat, lon, zoom, lang="en"):
        """Consume one key.  Always returns True while the panel is open:
        nothing reaches the map behind it."""
        if action == 'escape':
            self.close()
        elif action == 'key:enter':
            self.submit(lang)
        elif action == 'key:backspace':
            self.query = self.query[:-1]
            self._arm(lat, lon, zoom, lang)
        elif action == 'key:kill':
            self.query = ""
            self._arm(lat, lon, zoom, lang)
        elif action == 'back':
            self._move(-1)
        elif action == 'fwd':
            self._move(1)
        elif isinstance(action, str) and action.startswith('char:'):
            self.query += action[5:]
            self._arm(lat, lon, zoom, lang)
        return True

    def _move(self, step):
        if self.results:
            self.sel = (self.sel + step) % len(self.results)

    def submit(self, lang="en"):
        """Enter: take the highlighted result, or go and find one."""
        if self.results:
            self.chosen = self.results[self.sel]
            self.close()
            return
        if self.status == "pending":
            # The intent ("go to the best match") outlives a slow Photon:
            # when the reply lands, its first result commits itself.
            self.submitted = True
            return
        if len(self.query.strip()) < MIN_CHARS:
            return
        self._ask_once(self.query, lang)

    # -- the worker --------------------------------------------------------
    def _arm(self, lat, lon, zoom, lang):
        self._cancel()
        if len(self.query.strip()) < MIN_CHARS:
            self.results, self.status, self.sel = [], "", 0
            return
        self.status = "pending"
        gen, query = self.gen, self.query
        self._timer = threading.Timer(
            DEBOUNCE, self._run, (gen, query, lat, lon, zoom, lang))
        self._timer.daemon = True
        self._timer.start()

    def _run(self, gen, query, lat, lon, zoom, lang):
        try:
            results = self._fetch(query, lat, lon, zoom, lang)
            status = "" if results else "none"
        except SearchUnavailable:
            results, status = [], "error"
        except Exception:                       # a fetcher must never crash
            results, status = [], "error"       # the live loop's worker
        self._publish(gen, results, status, auto=True)

    def _ask_once(self, query, lang):
        """The single Nominatim query, on Enter and nowhere else.

        It does not auto-commit: by the time it answers, the user has
        been waiting, and a list they can look at beats a jump they did
        not choose.
        """
        self.status = "pending"
        self._cancel()
        gen = self.gen

        def body():
            try:
                results = self._one_shot(query, lang)
                status = "" if results else "none"
            except SearchUnavailable:
                results, status = [], "error"
            except Exception:
                results, status = [], "error"
            self._publish(gen, results, status, auto=False)

        threading.Thread(target=body, daemon=True).start()

    def _publish(self, gen, results, status, auto):
        with self._lock:
            if gen != self.gen or not self.open:
                return                  # superseded, or the panel is gone
            self.results, self.status, self.sel = results, status, 0
            if auto and self.submitted:
                self.submitted = False
                if results:
                    self.chosen = results[0]
                    self.open = False
                elif status == "error":
                    self._ask_once(self.query, "en")
        self._refresh()


# ---------------------------------------------------------------------------
# Chrome
# ---------------------------------------------------------------------------
def _label(result):
    return f"{result.name}, {result.detail}" if result.detail else result.name


def _fit(text, width):
    """Truncate to `width` columns, keeping an ellipsis as the tell."""
    if visible_len(text) <= width:
        return text
    out = ""
    for ch in text:
        if visible_len(out + ch) > width - 1:
            break
        out += ch
    return out + "…"


def _row(n, body, width, surface):
    pad = " " * max(0, width - visible_len(body))
    return f"\033[{n};1H{bg(*surface)}{body}{pad}{RESET}"


def search_overlay(state, cols, rows, lang="en"):
    """The panel, as cursor-addressed escapes for the \\x00 channel."""
    surface = surface_bg(0.10)
    ink = ensure_contrast(theme_fg, surface, 4.0)
    width = max(PANEL_MIN, min(PANEL_MAX, cols - 2))
    caret = "\033[7m \033[27m"
    tail = "…" if state.status == "pending" else ""

    if state.query:
        field = f"{fg(*MUTED)}/ {fg(*ink)}{state.query}{caret}{tail}"
    else:
        field = (f"{fg(*MUTED)}/ {caret}{fg(*DIM)}"
                 f"{ms('search_prompt', lang)}")
    out = [_row(1, " " + field, cols, surface)]

    line = 2
    limit = min(MAX_ROWS, max(0, rows - 3))
    for i, result in enumerate(state.results[:limit]):
        body = " " + _fit(_label(result), width - 2)
        body += " " * max(0, width - visible_len(body))
        if i == state.sel:
            body = f"\033[7m{body}\033[27m"
        out.append(_row(line, f"{fg(*ink)}{body}", width, surface))
        line += 1
    if not state.results:
        note = {"none": "search_none", "error": "search_error"}.get(
            state.status)
        if note:
            out.append(_row(line, f"{fg(*DIM)} {ms(note, lang)}", width,
                            surface))
            line += 1

    out.append(_row(line, f"{fg(*DIM)} {ms('search_hint', lang)}", width,
                    surface))
    return "".join(out)
