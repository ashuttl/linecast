"""Radar view helpers: the basemap cache, the drag preview, the panned-view
placename, and the overlays and footer pieces the live view draws.

These are the radar's screen-side helpers, shared with the maps view: a
_ShiftedBasemap stands in for a Basemap while a drag preview slides the
already-composed layers, _panned_place names a view centre from the
offline basemap data, and the theme picker, warning tooltip and timeline
scrubber are the chrome the live loop draws around the map.  ThemePicker
is the picker's state; _radar_live routes the keys to it.
"""

import datetime as _dt
import threading

from linecast import _live, _theme
from linecast._color import fg, bg, RESET
from linecast._framebuffer import fmt_time_dt
from linecast._theme import ensure_contrast
from linecast._weather_style import TOOLTIP_BG_RGB
from linecast._radar_basemap import (
    Basemap, _point_in_rings, marine_region, nearest_city,
)
from linecast._radar_i18n import rs
from linecast._radar_render import _bbox_key
from linecast._radar_sources import THEMES, is_local
from linecast._runtime import log_failure, use_metric
from linecast._scenes import Memo

MUTED = _live.MUTED
DIM = (110, 114, 130)
FAINT = (70, 74, 88)
MARKER = (255, 240, 120)
CROSSHAIR = (215, 220, 232)

_basemap_cache = Memo(keep=1)  # only need the current view
_basemap_lock = threading.Lock()  # the render thread and the frame
                                  # prefetch workers both ask for it


def _get_basemap(bbox, graph_w, height_cells):
    key = (_bbox_key(bbox), graph_w, height_cells)
    with _basemap_lock:
        bm = _basemap_cache.get(key)
    if bm is None:
        bm = Basemap(bbox, graph_w, height_cells)
        with _basemap_lock:
            _basemap_cache.put(key, bm)
    return bm


def _fmt_local(dt_utc, use_24h=False):
    return fmt_time_dt(dt_utc.astimezone(), use_24h=use_24h)


_place_cache = Memo(keep=64)


def _panned_place(lat, lon, lang):
    """Friendly name for a panned view centre, from the offline basemap data.

    Layered: "23 km NE of Boston" while a city is close (localized); the
    water body ("Gulf of Maine") once offshore; a distant city again where
    the water is unnamed; bare coordinates in the middle of nowhere.
    """
    key = (round(lat, 3), round(lon, 3), lang)
    hit = _place_cache.get(key)
    if hit is not None:
        return hit

    def city_phrase(name, km, bearing):
        metric = use_metric()
        dist = km if metric else km * 0.621371
        if dist < 2:
            return name
        compass = rs("compass", lang).split()
        return rs("near", lang, dist=round(dist),
                  unit="km" if metric else "mi",
                  dir=compass[round(bearing / 45) % 8], name=name)

    city = nearest_city(lat, lon, lang)
    if city and city[1] < 100:  # coastal waters still read by the city
        place = city_phrase(*city)
    else:
        water = marine_region(lat, lon)
        if water:
            place = water
        elif city and city[1] <= 1000:
            place = city_phrase(*city)
        else:
            place = f"{lat:.2f}, {lon:.2f}"

    _place_cache.put(key, place)
    return place


class _ShiftedBasemap:
    """Duck-typed stand-in for Basemap during a drag preview."""
    __slots__ = ("dots", "color", "sea")

    def __init__(self, dots, color, sea=None):
        self.dots = dots
        self.color = color
        self.sea = sea


def _shift_grid(rows, dx, dy, fill):
    """Shift a 2D grid's content by (dx right, dy down), backfilling `fill`."""
    h = len(rows)
    w = len(rows[0]) if h else 0
    blank = [fill] * w
    out = []
    for y in range(h):
        sy = y - dy
        if 0 <= sy < h:
            src = rows[sy]
            if dx >= 0:
                out.append(([fill] * min(dx, w) + src[:max(0, w - dx)]))
            else:
                out.append((src[-dx:] + [fill] * min(-dx, w))[:w])
        else:
            out.append(blank[:])
    return out


class ThemePicker:
    """The theme picker's state: closed, or open on a highlighted row.

    `handle(action, themes, current)` consumes one key.  `themes` is the
    source's name -> id mapping (None or empty when it has none) and
    `current` its active theme id; both come fresh with each key, since
    a fallback can swap the source under an open picker.  Enter on a
    theme other than the current one leaves its id in `chosen` for the
    caller to drain with take_chosen() and apply.
    """

    def __init__(self):
        self.sel = None      # None = closed, else highlighted row
        self.chosen = None   # a picked theme id, drained by the caller

    @property
    def is_open(self):
        return self.sel is not None

    def open(self, themes, current):
        """Open on the current theme's row (the first, when unknown)."""
        ids = list(themes.values())
        self.sel = ids.index(current) if current in ids else 0

    def close(self):
        self.sel = None

    def take_chosen(self):
        """Hand the picked theme id to the caller, once."""
        hit, self.chosen = self.chosen, None
        return hit

    def handle(self, action, themes, current):
        """Route keys to the theme picker; everything else passes through."""
        names = list(themes) if themes else []
        if self.sel is None:
            if action == 'key:t' and names:
                self.open(themes, current)
                return True
            return False
        if not names:  # source lost its themes (fallback) — just close
            self.close()
            return True
        if action == 'fwd':
            self.sel = (self.sel - 1) % len(names)
        elif action == 'back':
            self.sel = (self.sel + 1) % len(names)
        elif action == 'key:enter':
            choice = themes[names[self.sel]]
            self.close()
            if choice != current:
                self.chosen = choice
        elif action in ('escape', 'key:t', 'quit'):
            self.close()
        return True  # while the menu is open, no key reaches the map


def _theme_menu_overlay(names, sel, current, lang, cols, rows):
    """The theme list, drawn over the map via live_loop's \\x00 overlay
    channel. `sel` is the highlighted row, `current` the active id.
    A rule separates the themes coloured here from the server's."""
    kinds = [is_local(THEMES.get(n)) for n in names]
    lines, rows_of = [], []
    for i, name in enumerate(names):
        if i and kinds[i - 1] and not kinds[i]:
            lines.append(None)
        mark = "●" if THEMES.get(name) == current else " "
        rows_of.append(len(lines))
        lines.append(f" {mark} {name}")
    return _live.menu_box(lines, cols, rows, title=rs('theme', lang),
                          sel=rows_of[sel], border=fg(*MUTED))


def _fmt_expire(iso, use_24h):
    """"2026-07-17T05:00:00Z" → localised time-of-day, or None."""
    if not iso:
        return None
    try:
        exp = _dt.datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except (ValueError, AttributeError) as exc:
        log_failure("radar/warnings", "expiry time", exc, fallback="time omitted")
        return None
    return _fmt_local(exp, use_24h)


def _build_warning_tooltip(warns, mouse_pos, bbox, graph_w, height_cells,
                           cols, rows, use_24h):
    """A floating chip naming the warning(s) under the cursor, drawn over the
    map via live_loop's \\x00 overlay channel. Empty string when the pointer
    isn't over a warned area.

    The warned *area* is hoverable, not just its braille outline: we invert
    the cell → lon/lat projection and point-in-polygon test the raw rings, so
    the whole polygon interior surfaces its alert.
    """
    mcol, mrow = mouse_pos
    cx, cy = mcol - 1, mrow - 2  # 1-based terminal → 0-based cell (row 1 = header)
    if not (0 <= cx < graph_w and 0 <= cy < height_cells):
        return ""
    minlon, minlat, maxlon, maxlat = bbox
    lon = minlon + (cx + 0.5) / graph_w * (maxlon - minlon)
    lat = maxlat - (cy + 0.5) / height_cells * (maxlat - minlat)

    # most-severe-first (warns is least-severe-first), so the deadliest
    # overlapping warning heads the list
    hits = [(color, info) for _sev, color, rings, info in warns
            if _point_in_rings(lon, lat, rings)]
    if not hits:
        return ""
    hits.reverse()

    TBG = bg(*TOOLTIP_BG_RGB)
    lines = []
    for color, info in hits[:4]:
        name = info.get("name", "")
        if info.get("emergency"):
            name += " ‼"
        elif info.get("pds"):
            name += " (PDS)"
        until = _fmt_expire(info.get("expire"), use_24h)
        tail = f"  {fg(*MUTED)}→ {until}" if until else ""
        cfg = fg(*ensure_contrast(color, TOOLTIP_BG_RGB, 3.0))
        lines.append(f"{TBG} {cfg}{name}{tail} ")
    if len(hits) > 4:
        lines.append(f"{TBG} {fg(*MUTED)}+{len(hits) - 4} ")

    # right of the pointer, or ending just left of it at the screen edge
    return _live.pointer_chip(lines, mcol + 1, mrow, cols, rows,
                              pad_bg=TBG, flip_at=mcol)


def _timeline_bar(idx, n, width, present=None, loaded=None):
    """A compact scrubber: ─ track, ┼ notch at the present frame, ● playhead.

    With `loaded` (per-frame booleans), track cells whose frames haven't
    buffered yet draw faint, so the bar visibly fills in as fetches land.
    """
    if n <= 1 or width < 3:
        return ""
    pos = round(idx / (n - 1) * (width - 1))
    now = (round(present / (n - 1) * (width - 1))
           if present is not None else None)

    def cell(i):
        if i == pos:
            return f"{fg(*MARKER)}●"
        ch, color = ("┼", MUTED) if i == now else ("─", DIM)
        if loaded is not None and not loaded[round(i / (width - 1) * (n - 1))]:
            color = FAINT
        return f"{fg(*color)}{ch}"

    return "".join(cell(i) for i in range(width)) + RESET


_theme.track_imports(globals(), "linecast._weather_style")
