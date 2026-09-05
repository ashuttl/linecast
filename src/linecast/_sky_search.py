"""The sky view's `/`: find a thing in the sky, and go to it.

No network: everything searchable is already in memory, the Sun, the
Moon, the planets, every named or designated star, and the
constellations in Latin and in the display language. Typing narrows
the list; Enter flies the camera to the chosen thing. When it is below
the horizon the panel says when it rises and where, and a second Enter
moves the clock to that moment, since "when can I see it" is the
question a search for something not up is really asking.
"""

import math
import threading
from datetime import timedelta, timezone

from linecast import _theme
from linecast._graphics import RESET, bg, fg, visible_len
from linecast._live import nudge
from linecast._theme import ensure_contrast, surface_bg

PANEL_MIN, PANEL_MAX, MAX_ROWS = 28, 56, 8

_GREEK = {
    "alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ", "epsilon": "ε",
    "zeta": "ζ", "eta": "η", "theta": "θ", "iota": "ι", "kappa": "κ",
    "lambda": "λ", "mu": "μ", "nu": "ν", "xi": "ξ", "omicron": "ο", "pi": "π",
    "rho": "ρ", "sigma": "σ", "tau": "τ", "upsilon": "υ", "phi": "φ", "chi": "χ",
    "psi": "ψ", "omega": "ω",
}


class Target:
    """Something the search can land on.

    `kind` is "sun", "moon", "planet", "star" or "constellation"; `label`
    is what the panel shows; `key` is the planet's name, the star's index,
    or the constellation record. `spread` is a constellation's angular
    radius in degrees, for the zoom that frames it.
    """

    __slots__ = ("kind", "label", "key", "names", "rank", "spread")

    def __init__(self, kind, label, key, names, rank, spread=0.0):
        self.kind, self.label, self.key = kind, label, key
        self.names = [n.lower() for n in names if n]
        self.rank = rank            # brighter or grander first, on ties
        self.spread = spread

    def place(self, scene):
        """(alt, az) in degrees at the scene's moment."""
        from linecast._ephemeris import _alt_az_deg
        from linecast._sky_catalogue import stars
        from linecast.sky import alt_az_of, _mat_apply
        if self.kind == "sun":
            return scene.sun_alt, scene.sun_az
        if self.kind == "moon":
            return scene.moon_alt, scene.moon_az
        if self.kind == "planet":
            for key, _vec, alt, az, _mag in scene.planets:
                if key == self.key:
                    return alt, az
        if self.kind == "star":
            ra, dec, _mag, _bv = stars()[self.key]
            return _alt_az_deg(math.degrees(ra), math.degrees(dec), scene.moment_utc,
                               scene.lat, scene.lng)
        return alt_az_of(_mat_apply(scene.horizontal, self.key["at"]))

    def fov(self, current):
        """A field that shows the thing: a constellation framed with air
        around it, the Moon close, a star or planet no wider than sixty."""
        if self.kind == "constellation":
            return max(18.0, min(120.0, self.spread * 2.0 * 1.7))
        if self.kind == "moon":
            return min(current, 40.0)
        return min(current, 60.0)


def targets(runtime, culture=None):
    """Everything searchable, for the display language and the culture:
    with a culture set its constellations replace the IAU's and its star
    names join theirs."""
    from linecast._i18n import lang_of
    from linecast._planets import PLANETS
    from linecast._sky_catalogue import (
        constellation_name, constellations, figures_for, names_for, star_names, stars,
    )
    from linecast._sky_i18n import body_name
    lang = lang_of(runtime)
    out = [Target("sun", body_name("sun", runtime), None,
                  [body_name("sun", runtime), "sun", "sol"], -30.0),
           Target("moon", body_name("moon", runtime), None,
                  [body_name("moon", runtime), "moon", "luna"], -20.0)]
    for i, key in enumerate(PLANETS):
        out.append(Target("planet", body_name(key, runtime), key,
                          [body_name(key, runtime), key], -10.0 + i))
    catalogue = stars()
    cultural = names_for(culture, lang) if culture else {}
    for i, (proper, desig) in star_names().items():
        mag = catalogue[i][2]
        own = cultural.get(i, ("", ""))[0]
        label = own or proper or desig
        names = [proper, desig, own]
        if desig:
            # "alpha lyr" and "alpha lyrae" find α Lyr as well.
            letter, _, con = desig.partition(" ")
            for word, greek in _GREEK.items():
                if letter.startswith(greek):
                    names.append(f"{word}{letter[len(greek):]} {con}")
        out.append(Target("star", f"{label} · {desig}" if (proper or own) else label, i,
                          names, mag))
    for i, (own, desig) in cultural.items():
        if i not in star_names() and own:
            out.append(Target("star", f"{own} · {desig}" if desig else own, i,
                              [own, desig], catalogue[i][2]))
    for record in (figures_for(culture, lang) if culture else constellations()):
        if not record["lines"]:
            continue
        name = record["name"] if culture else constellation_name(record, lang)
        names = {record["name"], record["gen"], record["id"], name,
                 record.get("detail", ""), *record["names"].values()}
        # Angular radius of the figure about its label point.
        ax, ay, az = record["at"]
        spread = 0.0
        for line in record["lines"]:
            for x, y, z in line:
                dot = max(-1.0, min(1.0, ax * x + ay * y + az * z))
                spread = max(spread, math.degrees(math.acos(dot)))
        label = name if name == record["name"] else f"{name} · {record['name']}"
        out.append(Target("constellation", label, record, names, -spread, spread))
    return out


def search(query, pool, limit=MAX_ROWS):
    """The targets matching *query*: whole-name matches first, then those
    a name begins with, then those a word begins with, then any that
    contain it; the brightest or grandest first within each."""
    q = query.strip().lower()
    if not q:
        return []
    scored = []
    for t in pool:
        best = None
        for name in t.names:
            if name == q:
                score = 0
            elif name.startswith(q):
                score = 1
            elif any(word.startswith(q) for word in name.split()):
                score = 2
            elif q in name:
                score = 3
            else:
                continue
            best = score if best is None else min(best, score)
        if best is not None:
            scored.append((best, t.rank, t.label, t))
    scored.sort(key=lambda s: (s[0], s[1], s[2]))
    return [s[3] for s in scored[:limit]]


def next_rising(target, scene_at, now_local, hours=26):
    """When *target* next rises, as (local datetime, azimuth), or None if
    it never does. *scene_at(dt)* builds the Scene for a moment. Coarse
    quarter-hour steps find the crossing, bisection fixes it."""
    step = timedelta(minutes=15)
    prev_t = now_local
    prev_alt, _az = target.place(scene_at(prev_t))
    for i in range(1, int(hours * 4) + 1):
        t = now_local + step * i
        alt, az = target.place(scene_at(t))
        if prev_alt <= 0.0 < alt:
            lo, hi = prev_t, t
            for _ in range(10):
                mid = lo + (hi - lo) / 2
                if target.place(scene_at(mid))[0] > 0.0:
                    hi = mid
                else:
                    lo = mid
            return hi, target.place(scene_at(hi))[1]
        prev_t, prev_alt = t, alt
    return None


class SkySearch:
    """The `/` panel's state: the query, its matches, the choice, and the
    answer for a thing that is not up."""

    def __init__(self, runtime, refresh=None, culture=None):
        self.runtime = runtime
        self.culture = culture
        self.open = False
        self.query = ""
        self.results = []
        self.sel = 0
        self.note = ""           # "Orion rises at 02:14 in the E", or nothing
        self.jump = None         # (datetime, target) a second Enter goes to
        self._pool = None
        self._refresh = refresh or nudge
        self._lock = threading.Lock()

    def pool(self):
        if self._pool is None:
            self._pool = targets(self.runtime, self.culture)
        return self._pool

    def set_culture(self, culture):
        self.culture = culture
        self._pool = None

    def start(self):
        self.open = True
        self.query, self.results, self.sel, self.note, self.jump = "", [], 0, "", None

    def close(self):
        self.open = False
        self.query, self.results, self.note, self.jump = "", [], "", None

    def handle(self, action):
        """One key while open. Returns the chosen Target on Enter, the
        string "jump" when Enter takes the offered moment, else None."""
        if action == "escape":
            self.close()
        elif action == "key:enter":
            if self.jump is not None:
                return "jump"
            if self.results:
                return self.results[self.sel]
        elif action == "key:backspace":
            self.query = self.query[:-1]
            self._update()
        elif action == "key:kill":
            self.query = ""
            self._update()
        elif action == "back":
            self._move(1)
        elif action == "fwd":
            self._move(-1)
        elif isinstance(action, str) and action.startswith("char:"):
            self.query += action[5:]
            self._update()
        return None

    def _update(self):
        self.results = search(self.query, self.pool())
        self.sel = 0
        self.note, self.jump = "", None

    def _move(self, step):
        if self.results:
            self.sel = (self.sel + step) % len(self.results)


def search_overlay(state, cols, rows, runtime):
    """The panel, as cursor-addressed escapes for the floating channel:
    the field on the top row, the matches under it, then the note."""
    from linecast._sky_i18n import _sk
    surface = surface_bg(0.10)
    ink = ensure_contrast(_theme.theme_fg, surface, 4.0)
    dim = ensure_contrast(surface_bg(0.55), surface, 2.2)
    width = max(PANEL_MIN, min(PANEL_MAX, cols - 2))
    caret = "\033[7m \033[27m"

    def row(n, body):
        pad = " " * max(0, width - visible_len(body))
        return f"\033[{n};1H{bg(*surface)}{body}{pad}{RESET}"

    if state.query:
        field = f"{fg(*dim)}/ {fg(*ink)}{state.query}{caret}"
    else:
        field = f"{fg(*dim)}/ {caret} {_sk('search_prompt', runtime)}"
    out = [row(1, " " + field)]
    line = 2
    for i, target in enumerate(state.results[:max(0, rows - 4)]):
        body = " " + _fit(target.label, width - 2)
        body += " " * max(0, width - visible_len(body))
        if i == state.sel:
            body = f"\033[7m{body}\033[27m"
        out.append(row(line, f"{fg(*ink)}{body}"))
        line += 1
    if state.query and not state.results:
        out.append(row(line, f"{fg(*dim)} {_sk('search_none', runtime)}"))
        line += 1
    if state.note:
        for text in _wrap(state.note, width - 2):
            out.append(row(line, f"{fg(*ink)} {text}"))
            line += 1
        if state.jump is not None:
            out.append(row(line, f"{fg(*dim)} {_sk('search_jump', runtime)}"))
            line += 1
    return "".join(out)


def _fit(text, width):
    if visible_len(text) <= width:
        return text
    out = ""
    for ch in text:
        if visible_len(out + ch) > width - 1:
            break
        out += ch
    return out + "…"


def _wrap(text, width):
    words, lines, line = text.split(), [], ""
    for word in words:
        trial = f"{line} {word}".strip()
        if line and visible_len(trial) > width:
            lines.append(line)
            line = word
        else:
            line = trial
    if line:
        lines.append(line)
    return lines


def describe_rising(target, rising, runtime, culture=None):
    """'Orion rises at 02:14 in the E', or that it never rises here."""
    from linecast._framebuffer import fmt_time_dt
    from linecast._sky_i18n import _sk
    from linecast.sky import compass_point
    if rising is None:
        return _sk("never_rises", runtime, name=target.label.split(" · ")[0])
    when, az = rising
    return _sk("rises_at", runtime, name=target.label.split(" · ")[0],
               time=fmt_time_dt(when, use_24h=runtime.use_24h),
               dir=compass_point(az, runtime, culture))


def utc(dt):
    return dt.astimezone(timezone.utc)
