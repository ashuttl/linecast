"""Live-mode state for maps: the `/` search prompt and directions.

Both are the same shape — a bit of state, one background worker, and a
generation counter that decides which reply is still wanted — so they
live together, away from the renderer.

The `/` prompt first.

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

from linecast import _maps_style as style
from linecast._color import RESET, bg, fg
from linecast._framebuffer import visible_len
from linecast._maps_i18n import ms
from linecast._maps_route import (
    NoRoute, PROFILES, RouteUnavailable, maneuver_glyph,
    route as route_client,
)
from linecast._maps_search import (
    SearchUnavailable, nominatim_search, photon_search,
)
from linecast._elevation import ATTRIBUTION as ELEV_ATTRIBUTION
from linecast._maps_route import ATTRIBUTION as ROUTE_ATTRIBUTION
from linecast import _theme
from linecast._theme import ensure_contrast, surface_bg
from linecast._vtiles import ATTRIBUTION as TILE_ATTRIBUTION
from linecast.radar import CROSSHAIR, DIM, MUTED

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
        self.purpose = "go"     # "go" | "route" (d) | "origin" (o)
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
    def start(self, purpose="go"):
        self.open = True
        self.purpose = purpose
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
            # live_loop's time-scrub names: 'back' is the down arrow,
            # and in a vertical list down must move down.
            self._move(1)
        elif action == 'fwd':
            self._move(-1)
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
    ink = ensure_contrast(_theme.theme_fg, surface, 4.0)
    width = max(PANEL_MIN, min(PANEL_MAX, cols - 2))
    caret = "\033[7m \033[27m"
    tail = "…" if state.status == "pending" else ""

    if state.query:
        field = f"{fg(*MUTED)}/ {fg(*ink)}{state.query}{caret}{tail}"
    else:
        prompt = {"route": 'search_dest_prompt',
                  "origin": 'search_origin_prompt'}.get(state.purpose,
                                                        'search_prompt')
        field = f"{fg(*MUTED)}/ {caret}{fg(*DIM)}{ms(prompt, lang)}"
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


# ---------------------------------------------------------------------------
# Directions
# ---------------------------------------------------------------------------
class RouteState:
    """Directions: the two endpoints, how we are travelling, the one
    request allowed to be in flight, and the directions panel.

    One mental model for the `d` key: *directions.*  It opens the
    panel, and the panel's own rows say the rest — `o` edits the
    origin, `d` the destination, `p` the way of travelling — so the
    keys are discovered by reading the thing they act on.  The origin
    defaults to the home marker; nothing has to be picked before the
    first route.
    """

    def __init__(self, refresh=None, fetch=None, profile="car", home=None):
        self.profile = profile
        self.home = home        # (lat, lon) — the marker, default origin
        self.origin = None      # (lat, lon, label) once o re-points it
        self.dest = None        # (lat, lon, label)
        self.route = None
        self.status = ""        # "" | "pending" | "none" | "error"
        self.panel = False      # the directions panel (the d key)
        self.step = None        # focused step index, or None
        self.panel_rows = None  # (width, {row: action}) of the last draw
        self.gen = 0
        self._lock = threading.Lock()
        self._refresh = refresh or _sigwinch
        self._fetch = fetch or route_client

    def select(self, lat, lon, label=""):
        self.dest = (lat, lon, label)

    def set_origin(self, lat, lon, label=""):
        self.origin = (lat, lon, label)

    def origin_point(self):
        """Where routing starts: the edited origin, else home."""
        return self.origin[:2] if self.origin is not None else self.home

    def clear(self):
        """`n` clears the route, both endpoints and the panel; esc
        never does."""
        self.origin = None
        self.dest = None
        self.route = None
        self.status = ""
        self.panel = False
        self.step = None
        self.gen += 1

    def press(self):
        """The `d` key, panel closed: open it, and supply whatever it
        is missing — a destination ("search"), or a route (request).
        Opening focuses nothing — the first arrow press does, so the
        map never moves on a key that only shows a panel."""
        self.panel = True
        self.step = None
        if self.dest is None:
            return "search"
        if self.route is None and self.status != "pending":
            self.request()
        return True

    def cycle_profile(self):
        """The `p` key: the next way of travelling, and go again."""
        i = PROFILES.index(self.profile) + 1
        self.profile = PROFILES[i % len(PROFILES)]
        if self.dest is not None:
            self.request()
        return True

    def close_panel(self):
        self.panel = False
        self.step = None
        return True

    def step_move(self, delta):
        """Move the focused step by delta and return it, clamped at
        both ends — arriving must not wrap around to departing."""
        steps = self.route.steps if self.route is not None else []
        if not steps:
            return None
        if self.step is None:
            self.step = 0 if delta > 0 else len(steps) - 1
        else:
            self.step = max(0, min(len(steps) - 1, self.step + delta))
        return steps[self.step]

    def request(self):
        """Fetch off the loop: the client's own throttle sleeps, and it
        must never sleep in the keyboard thread."""
        origin = self.origin_point()
        if self.dest is None or origin is None:
            return
        self.status = "pending"
        self.gen += 1
        gen = self.gen
        dest = self.dest[:2]
        profile = self.profile

        def body():
            try:
                found, status = self._fetch(profile, origin, dest), ""
            except NoRoute:
                found, status = None, "none"
            except RouteUnavailable:
                found, status = None, "error"
            except Exception:
                found, status = None, "error"
            with self._lock:
                if gen != self.gen:
                    return                  # superseded, or cleared
                self.route, self.status = found, status
                self.step = None            # a new route re-numbers its steps
            self._refresh()

        threading.Thread(target=body, daemon=True).start()


def _fmt_distance(metres, lang):
    """Distance in the reader's units, with one decimal where it helps."""
    if style.use_metric(lang):
        if metres < 1000:
            return f"{round(metres):,} m"
        return f"{metres / 1000:.1f} km"
    feet = metres * 3.28084
    if feet < 1000:
        return f"{round(feet):,} ft"
    return f"{feet / 5280:.1f} mi"


def _fmt_duration(seconds):
    """`13m`, `1h 22m`.  The unit letters stay untranslated, matching
    the elevation readout."""
    minutes = int(round(seconds / 60.0))
    if minutes < 60:
        return f"{minutes}m"
    return f"{minutes // 60}h {minutes % 60:02d}m"


def route_summary(route, lang="en"):
    """`11.7 km · 13m · driving` for the header readout slot."""
    if route is None:
        return ""
    return (f"{_fmt_distance(route.distance_m, lang)}"
            f" · {_fmt_duration(route.duration_s)}"
            f" · {ms('profile_' + route.profile, lang)}")


def route_note(state, lang="en"):
    """What the header says while a route is being fetched, or failed."""
    return {"pending": ms('dir_wait', lang),
            "none": ms('dir_none', lang),
            "error": ms('dir_unavailable', lang)}.get(state.status, "")


def _point_label(point, fallback=""):
    """A (lat, lon, label) point's name for the panel; `fallback` names
    the unset point (the home origin).  Coordinates are the last resort
    — language-neutral, and always true."""
    if point is not None:
        if len(point) > 2 and point[2]:
            return point[2]
        return f"{point[0]:.3f}, {point[1]:.3f}"
    return fallback


def _step_text(step, lang, origin_label="", dest_label=""):
    """One step's name: the endpoints wear the labels of the points
    themselves, roads their names, ramps their ref when the name is
    blank upstream — and the hover vocabulary's word for a ramp when
    even the ref is missing, so no row goes nameless."""
    if step.get("type") == "depart" and origin_label:
        return origin_label
    if step.get("type") == "arrive" and dest_label:
        return dest_label
    name = step.get("name") or step.get("ref")
    if not name and "ramp" in (step.get("type") or ""):
        return ms('hov_ramp', lang)
    return name or ""


def _step_dist(step, lang):
    """The distance column: how far you follow this step, blank where
    there is nowhere further to follow (arrive)."""
    metres = step.get("distance_m") or 0.0
    return _fmt_distance(metres, lang) if metres else ""


def steps_text(route, lang="en", origin_label="", dest_label=""):
    """The maneuver list as plain printable lines, for --print."""
    lines = []
    for step in route.steps:
        line = (f" {maneuver_glyph(step)} {_step_dist(step, lang):>8}  "
                f"{_step_text(step, lang, origin_label, dest_label)}")
        lines.append(line.rstrip())
    return lines


def directions_overlay(state, cols, rows, lang="en", home_label=""):
    """The directions panel, on the same channel and ground as search.

    Three labelled field rows first — from, to, mode — each prefixed
    by the key that edits it, the way the help panel writes its keys:
    the panel is where your endpoints are seen, so it is also where
    the keys that change them are written.  Then one maneuver per row
    (or the router's status while there are none), the hint last.
    The focused step is reverse video with a counter in the hint, and
    a long list is a window that keeps the focus in view rather than
    a region to operate.

    Only the field rows sit on a surface, and they start under the
    header rather than over it; the steps are bare ink drawn straight
    onto the map — each row claims no more ground than its own text,
    so the route the steps describe stays visible beside them.

    As a side effect the panel records what each terminal row holds in
    state.panel_rows — that map is what lets a mouse click land on a
    field or a step.
    """
    state.panel_rows = None
    if rows < 6:
        return ""
    surface = surface_bg(0.10)
    ink = ensure_contrast(_theme.theme_fg, surface, 4.0)
    width = max(PANEL_MIN, min(PANEL_MAX, cols - 2))
    route, step = state.route, state.step

    labels = [ms(k, lang) for k in ('dir_from', 'dir_to', 'dir_mode')]
    lw = max(visible_len(label) for label in labels)

    def field(line, key, label, value, placeholder=False):
        pad = " " * (lw - visible_len(label))
        body = (f" {fg(*CROSSHAIR)}{key} {fg(*DIM)}{label}{pad}  "
                f"{fg(*DIM) if placeholder else fg(*ink)}"
                f"{_fit(value, width - lw - 6)}")
        return _row(line, body, width, surface)

    def loose(line, body):
        """A row with no ground of its own: the map stays visible
        wherever the text is not."""
        return f"\033[{line};1H{body}{RESET}"

    mode = ms('profile_' + state.profile, lang)
    if route is not None:
        mode += (f" · {_fmt_distance(route.distance_m, lang)}"
                 f" · {_fmt_duration(route.duration_s)}")
    out = [
        field(2, "o", labels[0], _point_label(state.origin, home_label)),
        field(3, "d", labels[1], _point_label(state.dest) or "…",
              placeholder=state.dest is None),
        field(4, "p", labels[2], mode),
    ]
    acts = {2: 'from', 3: 'to', 4: 'mode'}

    line = 5
    steps = route.steps if route is not None else []
    limit = min(len(steps), max(0, rows - 6))
    if steps and limit:
        start = 0
        if step is not None:
            start = max(0, min(step - limit // 2, len(steps) - limit))
        for i in range(start, start + limit):
            s = steps[i]
            plain = " " + _fit(f"  {maneuver_glyph(s)} "
                               f"{_step_dist(s, lang):>8}  "
                               f"{_step_text(s, lang)}", width - 2)
            body = (f"\033[7m{plain} \033[27m" if i == step
                    else plain)
            out.append(loose(line, f"{fg(*ink)}{body}"))
            acts[line] = ('step', i)
            line += 1
    else:
        note = route_note(state, lang)
        if note:
            out.append(loose(line, f"{fg(*DIM)}   {note}"))
            line += 1

    hint = ms('steps_hint', lang)
    if step is not None and steps:
        hint = f"{step + 1}/{len(steps)} · {hint}"
    out.append(loose(line, f"{fg(*DIM)} {_fit(hint, width - 2)}"))
    state.panel_rows = (width, acts)
    return "".join(out)


# ---------------------------------------------------------------------------
# The `?` panel
# ---------------------------------------------------------------------------
# Every key that does something, in the order you learn them. `esc` and
# `q` are in the frame rather than the list — the frame is where a
# reader looks for the way out.
HELP_KEYS = (
    ("drag", 'help_pan'),
    ("wheel", 'help_zoom_pointer'),
    ("hover", 'help_hover'),
    ("+ -", 'help_zoom'),
    ("n", 'help_reset'),
    None,
    ("v", 'help_view'),
    ("l", 'help_labels'),
    ("s c", 'help_sky'),
    ("r", 'help_spin'),
    ("/", 'help_search'),
    ("d", 'help_directions'),
    ("o", 'help_origin'),
    ("p", 'help_profile'),
    None,
    ("?", 'help_keys'),
    ("q", 'help_quit'),
)

# The legend is the glyph table read in order; hover reads the same one.
HELP_GLYPHS = tuple(style.GLYPH_LEGEND.items())

HELP_WIDTH = 47
_KEY_COL = 9


def _help_rows(lang, route, glyphs, terse=False):
    """(mark, text) content rows; None is a blank spacer."""
    rows = []
    for entry in HELP_KEYS:
        if terse and entry is not None and entry[0] in ("?", "hover"):
            # tightest rung: `?` names the panel being read, and hover
            # is the one key that teaches itself the moment the
            # pointer moves
            continue
        rows.append(None if entry is None
                    else (entry[0], ms(entry[1], lang)))
    if glyphs:
        rows.append(None)
        rows += [(g, ms(key, lang)) for g, key in HELP_GLYPHS]
    rows.append(None)
    # Attribution is a proper name and a data credit: imported from the
    # module that owns it, never retyped and never translated.
    rows.append(("", TILE_ATTRIBUTION))
    rows.append(("", ELEV_ATTRIBUTION))
    if route:
        rows.append(("", ROUTE_ATTRIBUTION))
    return rows


def help_overlay(cols, rows, lang="en", route=False):
    """The `?` panel, or "" when the terminal cannot hold it.

    Degradation is deterministic and never scrolls: drop the glyph
    legend, then the blank spacers, then the `?` row naming the panel
    itself, then give up entirely — a panel that scrolls is a panel you
    have to operate.
    """
    surface = surface_bg(0.10)
    ink = ensure_contrast(_theme.theme_fg, surface, 4.0)
    width = max(24, min(cols - 4, HELP_WIDTH))
    budget = rows - 2

    for glyphs, blanks, terse in ((True, True, False), (False, True, False),
                                  (False, False, False), (False, False, True)):
        content = _help_rows(lang, route, glyphs, terse)
        if not blanks:
            content = [r for r in content if r is not None]
        if len(content) + 2 <= budget:
            break
    else:
        return ""

    title = f" {ms('help_title', lang)} "
    close = f" {ms('help_close', lang)} "
    top = max(1, (rows - (len(content) + 2)) // 2)
    left = max(0, (cols - width - 2) // 2)

    lines = [f"{fg(*MUTED)}╭{title.center(width, '─')}╮{RESET}"]
    for row in content:
        if row is None:
            body = " " * width
        else:
            mark, text = row
            if mark:
                pad = " " * max(1, _KEY_COL - visible_len(mark))
                body = (f"  {fg(*CROSSHAIR)}{mark}{pad}"
                        f"{fg(*MUTED)}{_fit(text, width - _KEY_COL - 3)}")
            else:
                body = f"  {fg(*DIM)}{_fit(text, width - 3)}"
            body += " " * max(0, width - visible_len(body))
        lines.append(f"{fg(*MUTED)}│{bg(*surface)}{fg(*ink)}{body}"
                     f"{RESET}{fg(*MUTED)}│{RESET}")
    lines.append(f"{fg(*MUTED)}╰{close.center(width, '─')}╯{RESET}")

    return "".join(f"\033[{top + i};{left + 1}H{line}"
                   for i, line in enumerate(lines))
