"""The location menu's part in a live view, for weather and tides.

The menu itself, with the recent places and the search, is
weather/locations.py; this is what a view does with it.  It is kept
apart so that the views need not load the menu, and the maps search
under it, until a live view starts.
"""

import threading

from linecast._log import log_failure
from linecast.terminal import live as _live
from linecast.weather.locations_i18n import ls


class LocationMenu:
    """The location menu of a live view, mixed in before LiveApp: `l` or
    a click on the place opens it, `/` opens it on the search, and a
    place chosen from it loads in the background while the view keeps
    painting the place it has.  Weather and tides both have it.

    The view sets `locations` (a LocationPicker), `_state_lock`,
    `_generation`, `_loading`, `_location_result`, `_location_worker`
    and `country`, and supplies:

      _here()                    the place shown, as (lat, lng)
      _label()                   its name as the menu shows it
      _load_place(place, stale)  what the view needs to show *place*,
                                 fetched on a worker thread; *stale*
                                 says the reader has moved on since
      _place_failed(place, result)  the note to show when *result* will
                                 not do, or None
      _commit_place(place, result)  take the loaded place in, on the UI
                                 thread
      _on_place(col, row)        whether a click there is on the place

    A `_load_place` that raises has "failed" as its result.
    """

    LOG_AREA = "weather"

    def _update_location_picker(self):
        from linecast._config import saved_location
        from linecast._location import same_place
        saved = saved_location()
        self.locations.location_name = self._label()
        self.locations.is_default = bool(
            saved and same_place((saved['lat'], saved['lng']), self._here()))
        self.locations.sel = 0

    def _save_default_location(self):
        """Persist the displayed place using the CLI's shared location setting."""
        from linecast._config import save_location
        lat, lng = self._here()
        label = self._label()
        try:
            save_location(lat, lng, label, self.country or "")
        except OSError as exc:
            log_failure(self.LOG_AREA, 'save default location', exc,
                        fallback='keep previous default')
            self.flash([ls('save_failed', self.runtime.lang)], seconds=5)
            return
        self._update_location_picker()
        self.flash([ls('saved', self.runtime.lang, name=label)])

    def _choose_location(self, place):
        if place is None:
            return
        if place == 'save':
            self._save_default_location()
            return
        with self._state_lock:
            self._generation += 1
            generation = self._generation
            self._location_result = None
            self._loading = place
            self.flash([ls('loading', self.runtime.lang, name=place.name)], busy=True)

        def stale():
            return generation != self._generation

        def fetch():
            try:
                result = self._load_place(place, stale)
            except Exception as exc:
                log_failure(self.LOG_AREA, "change location", exc,
                            fallback="keep current location")
                result = "failed"
            with self._state_lock:
                if not stale():
                    self._location_result = (place, result)
            _live.nudge()

        self._location_worker = threading.Thread(target=fetch, daemon=True)
        self._location_worker.start()

    def _finish_location(self):
        """Commit on the UI thread, so recents and the view never change
        mid-input.  Called with the state lock held."""
        from linecast._location import same_place
        from linecast.maps.search import Result
        if self._location_result is None:
            return
        place, result = self._location_result
        self._location_result = self._loading = None
        self.clear_flash()
        note = self._place_failed(place, result)
        if note:
            self.flash([note], seconds=5)
            return
        # Keep the departure point too, so the first trip has a way back.
        here = self._here()
        recent = self.locations.recent
        if self.lat is not None and not any(
                same_place((p.lat, p.lon), here) for p in recent.places):
            recent.remember(Result(self._label(), '', *here, 'point'))
        self._commit_place(place, result)
        recent.remember(place)
        self._update_location_picker()

    def menu_rows(self):
        """The menu's keys, for the top of the help panel."""
        lang = self.runtime.lang
        return [('l', ls('locations', lang)), ('/', ls('add', lang))]

    def menu_overlay(self, cols, rows):
        """The note, and the menu while it is open, for the floating channel."""
        floating = self.flash_overlay(cols, rows)
        if self.locations.active:
            here = tuple(round(v, 4) for v in self._here())
            floating += self.locations.overlay(cols, rows, here)
        return floating

    def text_mode(self):
        return self.locations.search.open

    def intercept(self, action):
        if self.locations.active:
            self._choose_location(self.locations.handle(action, *self._here()))
            return True
        return False

    def on_wheel(self, direction, col, row):
        if not self.locations.active:
            return NotImplemented  # the view's own scrolling
        self.locations.handle('fwd' if direction > 0 else 'back', *self._here())
        return True

    def on_drag(self, dcol, drow, done):
        # Opt in to live_loop's press/release tracking for clicks.
        return False

    def on_click(self, col, row):
        if self.locations.active:
            self._choose_location(self.locations.click(col, row))
            return True
        if self._on_place(col, row):
            self.locations.start()
            return True
        return False

    def on_action(self, key):
        if key == "l":
            self.locations.start()
            return True
        if key == "/":
            self.locations.choose('add')
            return True
        return False

    def stop(self):
        self.clear_flash()
        self.locations.close()
        with self._state_lock:
            self._generation += 1
