"""Recent places and the location menu, for weather and tides."""

import os

from linecast import _theme
from linecast._cache import read_stale, write_cache
from linecast._graphics import RESET, bg, fg, visible_len
from linecast._help import fit
from linecast._maps_i18n import ms
from linecast._maps_search import ATTRIBUTION, Result
from linecast._maps_ui import SearchState
from linecast._paths import config_root
from linecast._runtime import log_failure
from linecast._weather_locations_i18n import ls

LIMIT = 10


def place_key(place):
    return round(place.lat, 4), round(place.lon, 4)


class RecentLocations:
    def __init__(self):
        self.path = config_root() / 'locations.json'
        self.places = []
        saved = read_stale(self._migrate())
        for item in saved if isinstance(saved, list) else []:
            try:
                name, detail = item['name'], item.get('detail', '')
                lat, lon = float(item['lat']), float(item['lon'])
                if (not isinstance(name, str) or not name.strip()
                        or not isinstance(detail, str)
                        or not -90 <= lat <= 90 or not -180 <= lon <= 180):
                    continue
                place = Result(name, detail, lat, lon, 'point')
            except (TypeError, KeyError, ValueError, OverflowError):
                continue
            if place_key(place) not in {place_key(p) for p in self.places}:
                self.places.append(place)
            if len(self.places) == LIMIT:
                break

    def _migrate(self):
        """The list was weather's alone and named for it; tides shares it
        now. Move the old file to the new name, or read it where it is
        when it cannot be moved."""
        old = self.path.with_name('weather-locations.json')
        if self.path.exists() or not old.exists():
            return self.path
        try:
            os.replace(old, self.path)
        except OSError as exc:
            log_failure('locations', 'rename of weather-locations.json', exc,
                        fallback='read in place')
            return old
        return self.path

    def remember(self, place):
        self.places = [place] + [p for p in self.places if place_key(p) != place_key(place)]
        self.places = self.places[:LIMIT]
        self._save()

    def clear(self):
        self.places = []
        self._save()

    def _save(self):
        write_cache(self.path, [dict(name=p.name, detail=p.detail, lat=p.lat, lon=p.lon)
                               for p in self.places])


class LocationSearch(SearchState):
    """The map's geocoder, with an explicit choice after every query."""

    def submit(self, lang='en'):
        if self.status != 'pending':
            super().submit(lang)


class LocationPicker:
    def __init__(self, lang, location_name="", align='right'):
        self.lang = lang
        self.align = align  # the side of the screen its control is on
        self.location_name = location_name
        self.is_default = False
        self.recent = RecentLocations()
        self.search = LocationSearch()
        self.open = False
        self.sel = 0
        self.hits = {}      # terminal rows → items, from the last paint
        self.bounds = None
        self.dividers = set()

    @property
    def active(self):
        return self.open or self.search.open

    def start(self):
        self.search.close()
        self.open, self.sel = True, 0

    def close(self):
        self.open = False
        self.search.close()
        self.hits, self.bounds = {}, None

    def items(self):
        items = [(p, p.name + (f', {p.detail}' if p.detail else ''))
                 for p in self.recent.places]
        items.append(('add', '+ ' + ls('add', self.lang)))
        if self.location_name and not self.is_default:
            items.append(('save', '★ ' + ls('save', self.lang, name=self.location_name)))
        if self.recent.places:
            items.append(('clear', '× ' + ls('clear', self.lang)))
        return items

    def choose(self, item):
        if item == 'add':
            self.open = False
            self.search.start()
        elif item == 'clear':
            self.recent.clear()
            self.sel = 0
        else:
            self.close()
            return item
        return None

    def handle(self, action, lat, lon):
        if self.search.open:
            self.search.handle(action, lat, lon, 7, self.lang)
            return self.search.take_chosen()
        if action in ('escape', 'quit', 'key:l'):
            self.close()
        elif action in ('fwd', 'back'):
            self.sel = (self.sel + (1 if action == 'back' else -1)) % len(self.items())
        elif action == 'key:enter':
            return self.choose(self.items()[self.sel][0])
        elif action == 'key:/':
            self.choose('add')
        return None

    def click(self, col, row):
        if (self.search.open and row == 1 and self.bounds
                and self.bounds[0] <= col <= self.bounds[1]):
            return None  # clicking the text field keeps its focus
        if self.bounds and self.bounds[0] <= col <= self.bounds[1]:
            if row in self.dividers:
                return None
            if row in self.hits:
                return self.choose(self.hits[row])
        self.close()
        return None

    def overlay(self, cols, rows, current):
        """A dropdown under its control; the search uses the same field/list shape as maps."""
        self.hits = {}
        self.dividers = set()
        if cols < 1 or rows < 2:
            self.bounds = None
            return ''
        searching = self.search.open
        width = min(cols, 56)
        if not searching:
            labels = [label for _item, label in self.items()]
            labels += ['● ' + label for item, label in self.items()
                       if isinstance(item, Result) and place_key(item) == current]
            labels.append(ms('search_hint', self.lang))
            width = min(width, max(visible_len(label) for label in labels) + 2)
        col = 1 if self.align == 'left' else cols - width + 1
        self.bounds = (col, col + width - 1)
        surface = _theme.surface_bg(0.10)
        ink = _theme.ensure_contrast(_theme.theme_fg, surface, 4.0)
        dim = _theme.ensure_contrast(_theme.surface_bg(0.55), surface, 2.2)
        rule_ink = _theme.ensure_contrast(_theme.surface_bg(0.25), surface, 1.3)
        out = []

        def row(n, text, selected=False, muted=False, color=None):
            body = fit(' ' + text, width)
            body += ' ' * max(0, width - visible_len(body))
            reverse = '\033[7m' if selected else ''
            normal = '\033[27m' if selected else ''
            color = color if color is not None else (dim if muted else ink)
            out.append(f'\033[{n};{col}H{bg(*surface)}{fg(*color)}'
                       f'{reverse}{body}{normal}{RESET}')

        if searching:
            search = self.search
            query = fit(search.query, max(0, width - 6))
            field = '/ ' + (query + '▏' if query else ms('search_prompt', self.lang))
            if search.status == 'pending':
                field += '…'
            row(1, field)
            items = [(p, p.name + (f', {p.detail}' if p.detail else ''))
                     for p in search.results]
            sel = search.sel
            available = max(1, rows - 3)
        else:
            items, sel = self.items(), self.sel
            available = max(0, rows - 2)
        # Selection indexes only actionable items. The rule has a display
        # row of its own, so arrows skip it and clicks leave the menu open.
        entries = list(range(len(items)))
        if not searching and self.recent.places:
            entries.insert(len(self.recent.places), None)
        at = entries.index(sel) if entries else 0
        start = min(max(0, at - available + 1), max(0, len(entries) - available))
        shown = entries[start:start + available]
        for n, index in enumerate(shown, 2):
            if index is None:
                row(n, '─' * max(0, width - 2), color=rule_ink)
                self.dividers.add(n)
                continue
            item, label = items[index]
            if item == 'save':
                # Keep "as default" visible when the place name is long.
                room = max(0, width - 4 - visible_len(ls('save', self.lang, name='')))
                label = '★ ' + ls('save', self.lang, name=fit(self.location_name, room))
            mark = '● ' if isinstance(item, Result) and place_key(item) == current else ''
            if n == 2 and start:
                mark = '▲ ' + mark
            if n == len(shown) + 1 and start + len(shown) < len(entries):
                label += ' ▼'
            row(n, mark + label, selected=index == sel)
            self.hits[n] = item
        n = len(shown) + 2
        if searching:
            note = {'none': 'search_none', 'error': 'search_error'}.get(self.search.status)
            if not items and note and n < rows:
                row(n, ms(note, self.lang), muted=True)
                n += 1
            if n < rows:
                row(n, ms('search_hint', self.lang), muted=True)
                n += 1
            if n <= rows:
                row(n, ATTRIBUTION, muted=True)
        elif n <= rows:
            row(n, ms('search_hint', self.lang), muted=True)
        return ''.join(out)
