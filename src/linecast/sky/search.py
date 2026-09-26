"""The sky view's `/`: find a thing in the sky, and go to it.

No network: everything searchable is already in memory, the Sun, the
Moon, the planets, every named or designated star, the constellations
in Latin and in the display language and by the English names a few go
by, the asterisms from the Big Dipper to the False Cross, and extended
Messier objects by name or catalogue designation. Typing narrows
the list; Enter flies the camera to the chosen thing. When it is below
the horizon the panel says when it rises and where, and a second Enter
moves the clock to that moment, since "when can I see it" is the
question a search for something not up is really asking.
"""

import math
import re
import threading
import unicodedata
from datetime import timedelta, timezone

from linecast.terminal import theme as _theme
from linecast.terminal.graphics import RESET, bg, fg, visible_len
from linecast.terminal.live import nudge
from linecast.terminal.theme import ensure_contrast, surface_bg

PANEL_MIN, PANEL_MAX, MAX_ROWS = 28, 56, 8

_GREEK = {
    "alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ", "epsilon": "ε",
    "zeta": "ζ", "eta": "η", "theta": "θ", "iota": "ι", "kappa": "κ",
    "lambda": "λ", "mu": "μ", "nu": "ν", "xi": "ξ", "omicron": "ο", "pi": "π",
    "rho": "ρ", "sigma": "σ", "tau": "τ", "upsilon": "υ", "phi": "φ", "chi": "χ",
    "psi": "ψ", "omega": "ω",
}
_SUPERSCRIPTS = str.maketrans("", "", "¹²³⁴⁵⁶⁷⁸⁹")
_SUPER_TO_DIGIT = str.maketrans("¹²³⁴⁵⁶⁷⁸⁹", "123456789")

# The English names a few constellations go by, for the search; the label
# keeps the Latin. Keyed by IAU code, so a tradition that keeps the IAU's
# figure gets them too.
_ENGLISH = {
    "Cru": ("Southern Cross",), "UMa": ("Great Bear",), "UMi": ("Little Bear",),
    "CrB": ("Northern Crown",), "CrA": ("Southern Crown",),
    "TrA": ("Southern Triangle",), "PsA": ("Southern Fish",),
}


class Target:
    """Something the search can land on.

    `kind` is "sun", "moon", "planet", "star", "deep_sky", "asterism" or
    "constellation"; `label` is what the panel shows; `key` is the planet's
    name, the star's index, or the constellation, asterism or object
    record. `spread` is a constellation's or asterism's angular radius in
    degrees, for the zoom that frames it. `exact` names match only whole
    or as a prefix: a star's "alpha Centauri" answers to that and to
    "alpha cent", but not to "centauri", which is the constellation.
    """

    __slots__ = ("kind", "label", "key", "names", "folded", "exact", "rank", "spread")

    def __init__(self, kind, label, key, names, rank, spread=0.0, exact=()):
        self.kind, self.label, self.key = kind, label, key
        self.names = [n.lower() for n in names if n]
        # Each name without its accents too, so "thien lang" finds Sao
        # Thiên Lang and "etoile polaire" the Étoile polaire: a terminal
        # search is typed faster than an accent is.
        # A Persian name folds twice, its zero-width non-joiners once as
        # spaces and once as nothing, since a query may type either.
        self.folded = []
        for name in self.names:
            for f in (_fold(name), _fold(name.replace("\u200c", ""))):
                if f not in self.names and f not in self.folded:
                    self.folded.append(f)
        self.exact = [n.lower() for n in exact if n]
        self.rank = rank            # brighter or grander first, on ties
        self.spread = spread

    def place(self, scene):
        """(alt, az) in degrees at the scene's moment.

        A star, a constellation, an asterism and a Messier object all
        come from the J2000 catalogue, so they go through the scene's
        precessed frame; the Sun, the Moon and the planets are already
        placed for the moment.
        """
        from linecast.sky.catalogue import star_vectors
        from linecast.sky.view import alt_az_of, _mat_apply
        if self.kind == "sun":
            return scene.sun_alt, scene.sun_az
        if self.kind == "moon":
            return scene.moon_alt, scene.moon_az
        if self.kind == "planet":
            for key, _vec, alt, az, _mag in scene.planets:
                if key == self.key:
                    return alt, az
        at = star_vectors()[self.key] if self.kind == "star" else self.key["at"]
        return alt_az_of(_mat_apply(scene.catalogue, at))

    def fov(self, current):
        """A field that shows the thing: a constellation framed with air
        around it, the Moon close, a star or planet no wider than sixty."""
        if self.kind in ("constellation", "asterism"):
            return max(18.0, min(120.0, self.spread * 2.0 * 1.7))
        if self.kind == "deep_sky":
            return max(6.0, min(current, max(self.key['size']) / 60.0 * 2.5))
        if self.kind == "moon":
            return min(current, 40.0)
        return min(current, 60.0)


def targets(runtime, culture=None):
    """Everything searchable, for the display language and the culture:
    the stars by the IAU's name, the language's own where it has one, and
    the designation; with a culture set its constellations replace the
    IAU's and its star names join theirs."""
    from linecast._i18n import lang_of
    from linecast.sky.planets import PLANETS
    from linecast.sky.catalogue import (
        constellation_name, constellations, figures_for, names_for, star_names, stars,
    )
    from linecast.sky.i18n import body_name
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
    local = star_names(lang)
    genitives = {c["id"]: c["gen"] for c in constellations()}
    for i, (proper, desig) in star_names().items():
        mag = catalogue[i][2]
        own = cultural.get(i, ("", ""))[0]
        mine = local[i][0]   # the language's own name, or the IAU's again
        label = own or mine or desig
        names = [proper, own, mine, *designation_names(desig)]
        out.append(Target("star", f"{label} · {desig}" if (proper or own) else label, i,
                          names, mag, exact=genitive_names(desig, genitives)))
    for i, (own, desig) in cultural.items():
        if i not in star_names() and own:
            out.append(Target("star", f"{own} · {desig}" if desig else own, i,
                              [own, *designation_names(desig)], catalogue[i][2],
                              exact=genitive_names(desig, genitives)))
    from linecast.sky.objects import object_name, objects
    for record in objects():
        name = object_name(record, lang)
        ident = record['id']
        aliases = [name, record['name'], ident, ident.replace('M', 'M '),
                   f"Messier {ident[1:]}", record['designation'],
                   record['designation'].replace(' ', ''), *record['aliases']]
        out.append(Target('deep_sky', f"{name} · {ident}" if name != ident else ident,
                          record, aliases, record['mag']))
    from linecast.sky.asterisms import asterism_name, asterisms
    for record in asterisms():
        name = asterism_name(record, lang)
        names = {record["name"], name, *record["aliases"], *record["names"].values()}
        label = name if name == record["name"] else f"{name} · {record['name']}"
        out.append(Target("asterism", label, record, names, -record["spread"],
                          record["spread"]))
    for record in (figures_for(culture, lang) if culture else constellations()):
        if not record["lines"]:
            continue
        name = record["name"] if culture else constellation_name(record, lang)
        names = {record["name"], record["gen"], record["id"], name,
                 record.get("detail", ""), *record["names"].values(),
                 *_ENGLISH.get(record.get("iau") or record["id"], ())}
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


def _letters(letter):
    """The ways a designation's letter is typed: "α¹" is also "α", "α1",
    "alpha¹", "alpha" and "alpha1", since the component superscript is
    not on a keyboard."""
    out = [letter]
    plain = letter.translate(_SUPERSCRIPTS)
    if plain != letter:
        out.append(plain)
        out.append(plain + letter[len(plain):].translate(_SUPER_TO_DIGIT))
    for word, greek in _GREEK.items():
        if letter.startswith(greek):
            out.extend(f"{word}{tail[len(greek):]}" for tail in list(out))
            break
    return out


def designation_names(desig):
    """"α¹ Cen" as it is typed: "α Cen", "alpha Cen", "alpha1 Cen"."""
    if not desig:
        return []
    letter, _, con = desig.partition(" ")
    return [f"{first} {con}" for first in _letters(letter)]


def genitive_names(desig, genitives):
    """"α¹ Cen" as a chart prints it: "alpha Centauri", and without the
    accent where the genitive has one, "alpha Bootis". *genitives* maps
    the IAU code to the genitive."""
    if not desig:
        return []
    letter, _, con = desig.partition(" ")
    if not genitives.get(con):
        return []
    cons = [genitives[con]]
    folded = _fold(genitives[con])
    if folded != genitives[con]:
        cons.append(folded)
    return [f"{first} {second}" for first in _letters(letter) for second in cons]


# Letters no decomposition reduces: the Vietnamese đ, the Polish ł, the
# Norwegian and Danish ø, the Turkish dotless ı (its capital is a plain I).
# The Arabic kaf and yeh, which an Arabic keyboard types and some labels
# carry, read as the Persian ک and ی, and the zero-width non-joiner as a
# space, since a Persian query may leave it out (هفت اورنگ).
_BARRED = str.maketrans("đĐłŁøØıكيى\u200c", "dDlLoOiکیی ")


def _fold(text):
    """*text* without its accents."""
    return "".join(ch for ch in unicodedata.normalize("NFKD", text)
                   if not unicodedata.combining(ch)).translate(_BARRED)


_X_SYSTEM = re.compile(r"([cghjsu])x")


def _x_system(text):
    """*text* with the Esperanto x-system's digraphs reduced to their base
    letter, "gxemeloj" to "gemeloj", which is how the accent-stripped
    names read; typed without an Esperanto keyboard, ĝ is gx."""
    return _X_SYSTEM.sub(r"\1", text)


def _score(name, q):
    """How well *name* answers *q*: 0 whole, 1 from the start, 2 from a
    word's start, 3 anywhere inside; None if it does not."""
    if name == q:
        return 0
    if name.startswith(q):
        return 1
    if any(word.startswith(q) for word in name.split()):
        return 2
    if q in name:
        return 3
    return None


def search(query, pool, limit=MAX_ROWS):
    """The targets matching *query*: whole-name matches first, then those
    a name begins with, then those a word begins with, then any that
    contain it; the brightest or grandest first within each. A target's
    `exact` names take only the first two, and a match on a name
    stripped of its accents counts one step behind the same match on
    the name itself, and a query in the Esperanto x-system matches the
    accent-stripped names the same way."""
    q = query.strip().lower()
    if not q:
        return []
    queries = (q,) if _x_system(q) == q else (q, _x_system(q))
    # A query typed with the Arabic kaf and yeh finds the Persian names.
    if _fold(q) not in queries:
        queries += (_fold(q),)
    scored = []
    for t in pool:
        best = None
        for name in t.exact:
            if name == q:
                best = 0
            elif name.startswith(q) and best is None:
                best = 1
        for names, penalty in ((t.names, 0), (t.folded, 1)):
            for name in names:
                for text in queries:
                    score = _score(name, text)
                    if score is None:
                        continue
                    score = min(3, score + penalty)
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
        if action in ("escape", "quit"):
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
            selected = (self.sel + step) % len(self.results)
            if selected != self.sel:
                self.note, self.jump = "", None
            self.sel = selected


def search_overlay(state, cols, rows, runtime):
    """The panel, as cursor-addressed escapes for the floating channel:
    the field on the top row, the matches under it, then the note."""
    from linecast.sky.i18n import _sk
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
    from linecast.terminal.framebuffer import fmt_time_dt
    from linecast._i18n import sentence_24h
    from linecast.sky.i18n import _sk
    from linecast.sky.view import compass_point
    if rising is None:
        return _sk("never_rises", runtime, name=target.label.split(" · ")[0])
    when, az = rising
    return _sk("rises_at", runtime, name=target.label.split(" · ")[0],
               time=fmt_time_dt(when, use_24h=sentence_24h(runtime)),
               dir=compass_point(az, runtime, culture))


def utc(dt):
    return dt.astimezone(timezone.utc)
