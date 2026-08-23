"""Radar view helpers: the basemap cache, the drag preview, the panned-view
placename, and the overlays and footer pieces the live view draws.

These are the radar's screen-side helpers, shared with the maps view: a
_ShiftedBasemap stands in for a Basemap while a drag preview slides the
already-composed layers, _panned_place names a view centre from the
offline basemap data, and the theme picker, warning tooltip and timeline
scrubber are the chrome the live loop draws around the map.
"""

import datetime as _dt

from linecast._color import fg, bg, RESET
from linecast._framebuffer import fmt_time_dt
from linecast._theme import ensure_contrast
from linecast._weather_style import TOOLTIP_BG_RGB
from linecast._radar_basemap import (
    Basemap, _point_in_rings, marine_region, nearest_city,
)
from linecast._radar_i18n import rs
from linecast._radar_sources import THEMES, is_local
from linecast._runtime import use_metric
from linecast._graphics import visible_len

MUTED = (150, 155, 170)
DIM = (110, 114, 130)
FAINT = (70, 74, 88)
MARKER = (255, 240, 120)
CROSSHAIR = (215, 220, 232)

_basemap_cache = {}


def _get_basemap(bbox, graph_w, height_cells):
    key = (tuple(round(v, 3) for v in bbox), graph_w, height_cells)
    bm = _basemap_cache.get(key)
    if bm is None:
        bm = Basemap(bbox, graph_w, height_cells)
        _basemap_cache.clear()  # only need the current view
        _basemap_cache[key] = bm
    return bm


def _fmt_local(dt_utc, use_24h=False):
    return fmt_time_dt(dt_utc.astimezone(), use_24h=use_24h)


_place_cache = {}


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
        metric = use_metric(lang)
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

    if len(_place_cache) > 64:
        _place_cache.clear()
    _place_cache[key] = place
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


def _theme_menu_overlay(names, sel, current, lang, cols, rows):
    """Cursor-addressed theme list, drawn over the map via live_loop's \\x00
    overlay channel. `sel` is the highlighted row, `current` the active id.
    A rule separates the themes coloured here from the server's."""
    inner = min(cols - 4, max(len(n) for n in names) + 4)
    kinds = [is_local(THEMES.get(n)) for n in names]
    split = True in kinds and False in kinds
    top = max(1, (rows - (len(names) + 2 + split)) // 2)
    left = max(0, (cols - inner - 2) // 2)
    title = f" {rs('theme', lang)} "
    lines = [f"┌{title.center(inner, '─')}┐"]
    for i, name in enumerate(names):
        if i and kinds[i - 1] and not kinds[i]:
            lines.append(f"├{'─' * inner}┤")
        mark = "●" if THEMES.get(name) == current else " "
        body = f" {mark} {name}"[:inner].ljust(inner)
        if i == sel:
            body = f"\033[7m{body}\033[27m"  # reverse-video highlight
        lines.append(f"│{body}│")
    lines.append(f"└{'─' * inner}┘")
    return "".join(
        f"\033[{top + 1 + i};{left + 1}H{fg(*MUTED)}{line}{RESET}"
        for i, line in enumerate(lines))


def _fmt_expire(iso, use_24h):
    """"2026-07-17T05:00:00Z" → localised time-of-day, or None."""
    if not iso:
        return None
    try:
        exp = _dt.datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
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

    width = max(visible_len(ln) for ln in lines)
    padded = [f"{ln}{TBG}{' ' * (width - visible_len(ln))}{RESET}"
              for ln in lines]

    # anchor below-right of the pointer, pulled inward at the screen edges
    col = mcol + 1
    row = mrow + 1
    if col + width - 1 > cols:
        col = max(1, mcol - width)
    if row + len(padded) - 1 > rows:
        row = max(1, mrow - len(padded))
    return "".join(f"\033[{row + i};{col}H{ln}" for i, ln in enumerate(padded))


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


from linecast import _theme as _theme_mod
_theme_mod.reimport_on_reload(globals(), "linecast._weather_style",
                              "TOOLTIP_BG_RGB")
