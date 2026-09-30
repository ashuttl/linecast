"""The live tides: what runs when you type `tides`.

main() settles the arguments and finds the station: the one --station
or TIDE_STATION names, else the one nearest the place.  --search and
--nearby list stations and exit, --json and --oneline print from the
predictions, and --print draws one frame; otherwise a TidesApp puts the
chart on screen, fetches more of the weeks either side as the view is
scrolled toward an edge, and moves to another station from the location
menu.  Everything drawn is in tides.view; the stations and what is
fetched for them are in tides.stations.
"""

import os
import sys
import threading
import time as _t
from datetime import date, datetime, timedelta

from linecast.terminal.textwidth import visible_len
from linecast.terminal.framebuffer import get_terminal_size
from linecast.terminal import live as _live
from linecast._location import country_for_defaults, resolve_location
from linecast._plaintext import plain_text
from linecast._runtime import TidesRuntime, set_current
from linecast._parsers import tides_parser
from linecast._log import log_failure
from linecast.terminal.spinner import Spinner
from linecast.tides.common import month_after, sweep_legacy_cache
from linecast.tides.i18n import _ts
from linecast.tides import palette as _palette
from linecast.terminal.color import RESET, fg
from linecast.weather.location_menu import LocationMenu
from linecast.tides.providers import NOAA, PROVIDERS, TIDECHECK, provider_for_id
from linecast.tides.stations import (
    _fetch_station, _find_matching_stations, _search_stations, _station_details,
    _station_for_location, _station_now,
)
from linecast.tides.view import (
    LIVE_WINDOW_HOURS, _live_window_start, _pill_label, _render_header_line, render,
)



# ---------------------------------------------------------------------------
class TidesApp(LocationMenu, _live.LiveApp):
    """The live tide view: a sliding window over predictions fetched a
    week to either side, widened as the user scrolls toward an edge."""

    interval = 60
    mouse = True
    # Larger step makes wheel/arrow scrubbing practical for multi-day browsing.
    scroll_step = 30

    LOG_AREA = 'tides'
    # v steps through them: the day's chart, a month of days, the year
    VIEWS = ("day", "month", "year")

    def __init__(self, provider, station_id, station_name, station_meta,
                 station_tz, runtime, predictions, hilo, fetched_start,
                 fetched_end, y_range=None, marine_data=None, place=None, country=""):
        self.provider = provider
        self.station_id = station_id
        self.station_name = station_name
        self.station_meta = station_meta
        self.station_tz = station_tz
        self.runtime = runtime
        self.predictions = predictions
        self.hilo = hilo
        self.fetched_start = fetched_start
        self.fetched_end = fetched_end
        self.y_range = y_range
        self.marine_data = marine_data
        self._worker = None
        self._retry_at = 0.0   # monotonic; no expansion before this
        # The place the reader asked for, which the station is nearest
        # to: (lat, lng, label). A named station stands for itself.
        if place is None:
            meta = station_meta or {}
            place = (meta.get("lat"), meta.get("lng"), "")
        self.lat, self.lng, self.place_label = place
        self.country = country
        from linecast.weather.locations import LocationPicker
        self.locations = LocationPicker(runtime.lang, align='left')
        self._update_location_picker()
        self._state_lock = threading.RLock()
        self._generation = 0
        self._loading = None
        self._location_result = None
        self._location_worker = None
        self.view = "day"
        self.months = 0              # the month view's offset from this month
        self.years = 0               # the year view's from this year
        # (view, station, month or year) -> what that view draws; a
        # worker fetches the one on screen, and a failure waits a while
        self._long = {}
        self._long_worker = None
        self._long_retry_at = 0.0

    @property
    def help_view(self):
        return {"day": "tides", "month": "tides_month", "year": "tides_year"}[self.view]

    # --- the location menu (LocationMenu) ---------------------------------
    def _here(self):
        try:
            return float(self.lat), float(self.lng)
        except (TypeError, ValueError):
            return 0.0, 0.0

    def _label(self):
        lat, lng = self._here()
        return self.place_label or self.station_name or f"{lat:.2f}, {lng:.2f}"

    def _load_place(self, place, stale):
        """The nearest station to *place* and its data, as main() finds
        them: None when nothing covers it, "failed" when it would not load."""
        from linecast._geocode import reverse_geocode
        try:
            country = reverse_geocode(place.lat, place.lon, lang=self.runtime.lang)[1]
        except Exception as exc:
            log_failure("tides", "place country", exc, fallback="no regional provider")
            country = ""
        provider, station_id, station_name = _station_for_location(
            place.lat, place.lon, country, label=place.name)
        if station_id is None:
            return None
        station_meta, station_name, station_tz = _station_details(
            provider, station_id, station_name)
        fetched = _fetch_station(provider, station_id, station_meta, station_tz, live=True)
        if not fetched[4]:
            return "failed"
        return dict(provider=provider, station_id=station_id, station_name=station_name,
                    station_meta=station_meta, station_tz=station_tz, country=country,
                    fetched=fetched)

    def _place_failed(self, place, result):
        if isinstance(result, dict):
            return None
        key = "no_tides" if result is None else "load_failed"
        return _ts(key, self.runtime, name=place.name)

    def _commit_place(self, place, result):
        (self.fetched_start, self.fetched_end, self.y_range, self.marine_data,
         self.predictions, self.hilo) = result["fetched"]
        self.provider = result["provider"]
        self.station_id = result["station_id"]
        self.station_name = result["station_name"]
        self.station_meta = result["station_meta"]
        self.station_tz = result["station_tz"]
        self.country = result["country"]
        self.lat, self.lng, self.place_label = place.lat, place.lon, place.name
        self._retry_at = 0.0

    def _on_place(self, col, row):
        name = _pill_label(self.station_name, location_menu=True)
        return row == 1 and bool(name) and col <= visible_len(name) + 4

    def expand_for(self, offset_minutes):
        """Widen the fetched range when the user scrolls near an edge.

        The fetch runs on a worker so a slow network never stalls the
        scroll: the view keeps painting the range it has, and the wider
        one nudges a repaint when it lands. The providers absorb network
        failures and answer empty, and an empty range is a failure, not
        a flat sea — the old range stays, and the next try waits out a
        short pause so a dead network is not asked on every repaint.
        """
        current_now = _station_now(self.station_meta, self.predictions)
        view_start = _live_window_start(
            current_now,
            offset_minutes=offset_minutes,
            hours_shown=LIVE_WINDOW_HOURS,
        )
        view_end = view_start + timedelta(hours=LIVE_WINDOW_HOURS)
        view_start_date = view_start.date()
        view_end_date = view_end.date()

        need_expand = False
        new_start, new_end = self.fetched_start, self.fetched_end

        if view_start_date - timedelta(days=2) < self.fetched_start:
            new_start = view_start_date - timedelta(days=7)
            need_expand = True
        if view_end_date + timedelta(days=2) > self.fetched_end:
            new_end = view_end_date + timedelta(days=7)
            need_expand = True

        if (not need_expand or _t.monotonic() < self._retry_at
                or (self._worker and self._worker.is_alive())):
            return

        provider, station_id, station_tz = self.provider, self.station_id, self.station_tz

        def worker():
            try:
                predictions = provider.tides_range(
                    station_id, new_start, new_end, station_tz)
                hilo = provider.hilo_range(
                    station_id, new_start, new_end, station_tz)
            except Exception as exc:
                log_failure("tides", "range expansion", exc,
                            fallback="edge stays put")
                predictions = None
            if station_id != self.station_id:
                return  # the reader has moved to another station
            if predictions:
                self.predictions = predictions
                self.hilo = hilo
                self.fetched_start = new_start
                self.fetched_end = new_end
                _live.nudge()
            else:
                self._retry_at = _t.monotonic() + 30

        self._worker = threading.Thread(target=worker, daemon=True)
        self._worker.start()

    # --- the month and year views -------------------------------------------
    def _today(self):
        return _station_now(self.station_meta, self.predictions).date()

    def _long_key(self):
        """What the month or year view on screen draws, as _long keys it."""
        from linecast.tides.month import month_of
        today = self._today()
        if self.view == "month":
            return ("month", self.station_id, month_of(today, self.months))
        return ("year", self.station_id, today.year + self.years)

    def _start_long(self):
        """Fetch the month or year on screen, off the loop.  A month is one
        of NOAA's requests; a year of high and low waters is twelve, and
        what the gauge measured two or three more."""
        key = self._long_key()
        if (key in self._long or self._loading is not None
                or _t.monotonic() < self._long_retry_at
                or (self._long_worker and self._long_worker.is_alive())):
            return
        provider, station_id, tz = self.provider, self.station_id, self.station_tz
        today = self._today()

        def worker():
            kind, _station, when = key
            try:
                if kind == "month":
                    last = month_after(when) - timedelta(days=1)
                    data = (provider.tides_range(station_id, when, last, tz),
                            provider.hilo_range(station_id, when - timedelta(days=1),
                                                last + timedelta(days=1), tz))
                else:
                    from linecast.tides.year import daily_ranges
                    hilo = provider.hilo_range(station_id, date(when, 1, 1),
                                               date(when, 12, 31), tz)
                    data = (daily_ranges(hilo),
                            provider.observed_extremes(station_id, when, today),
                            provider.flood_stage(station_id))
            except Exception as exc:
                log_failure("tides", f"{kind} view", exc, fallback="view left empty")
                data = None
            if data is None:
                self._long_retry_at = _t.monotonic() + 30
            else:
                self._long[key] = data
            _live.nudge()

        self._long_worker = threading.Thread(target=worker, daemon=True)
        self._long_worker.start()

    def _step(self, n):
        if self.view == "month":
            self.months += n
        else:
            self.years += n
        return True

    def _render_long(self, mouse_pos):
        from linecast.terminal import help as _help
        from linecast._i18n import lang_of
        self._start_long()
        cols, _rows = get_terminal_size()
        lang = lang_of(self.runtime)
        now_local = _station_now(self.station_meta, self.predictions)
        key = self._long_key()
        data = self._long.get(key)
        text, dim = fg(*_palette.TEXT_RGB), fg(*_palette.DIM_RGB)
        source = f"{dim}{self.provider.footer_label(self.runtime)}{RESET}"
        if self.view == "month":
            from linecast.moon.calendar import _month_title
            from linecast.tides.month import render_month
            first = key[2]
            header = _render_header_line(
                cols, self.station_name, self.runtime, offset_minutes=self.months,
                location_menu=True,
                right=f"{text}{_month_title(first.year, first.month, lang)}{RESET}")
            # The key to the braille over the field: the Sun's two lines
            from linecast.sunshine.i18n import _ss
            from linecast.tides import month as _month
            legend = (f"{source}   {fg(*_month.SUN_RGB)}⡇{RESET} {dim}"
                      f"{_ss('sunrise', self.runtime)} / {_ss('sunset', self.runtime)}{RESET}")
            footer = _help.footer(legend, cols, lang)
            return render_month(first, data[0] if data else None, data[1] if data else None,
                                self.runtime, header=header, footer=footer,
                                station_meta=self.station_meta, station_tz=self.station_tz,
                                now_local=now_local, mouse_pos=mouse_pos)
        from linecast.tides import year as _year
        year = key[2]
        predicted, observed, flood = data or ({}, {}, None)
        summary = _year.summary(year, predicted, observed, self.runtime, now_local.date())
        right = f"{text}{year}{RESET}" + (f"  {dim}{summary}{RESET}" if summary else "")
        header = _render_header_line(cols, self.station_name, self.runtime,
                                     offset_minutes=self.years, location_menu=True, right=right)
        legend = source
        if observed:
            pen, band = fg(*_year.PEN_RGB), fg(*_year.BAND_RGB)
            legend += (f"   {pen}⠤⠒⠉{RESET} {dim}{_ts('measured', self.runtime)}{RESET}"
                       f"   {band}██{RESET} {dim}{_ts('predicted', self.runtime)}{RESET}")
        footer = _help.footer(legend, cols, lang)
        return _year.render_year(year, predicted, observed, flood, self.runtime,
                                 header=header, footer=footer, today=now_local.date(),
                                 tzinfo=self.station_tz, mouse_pos=mouse_pos)

    # --- keys and the wheel -----------------------------------------------
    def intercept(self, action):
        if super().intercept(action):
            return True
        if self.view == "day":
            return False
        # The month and year views move by months and years; the day's
        # time scrub stays where it was left.
        if action in ("fwd", "back"):
            return self._step(1 if action == "fwd" else -1)
        if action == "reset":
            self.months = self.years = 0
            return True
        return False

    def on_wheel(self, direction, col, row):
        answer = super().on_wheel(direction, col, row)
        if answer is not NotImplemented or self.view == "day":
            return answer
        return self._step(direction)

    def on_action(self, key):
        if super().on_action(key):
            return True
        if key == "v":
            self.view = self.VIEWS[(self.VIEWS.index(self.view) + 1) % len(self.VIEWS)]
            return True
        return False

    def render(self, offset_minutes=0, mouse_pos=None, active_alert=None,
               modal_scroll=0):
        with self._state_lock:
            self._finish_location()
        panel = self.locations.active
        if self.view != "day":
            output = self._render_long(None if panel else mouse_pos)
            cols, rows = get_terminal_size()
            return _live.overlay(output, self.menu_overlay(cols, rows)), {}
        self.expand_for(offset_minutes)
        output = render(
            self.station_id,
            self.station_name,
            station_meta=self.station_meta,
            runtime=self.runtime,
            fullscreen=True,
            offset_minutes=offset_minutes,
            predictions=self.predictions,
            hilo=self.hilo,
            y_range=self.y_range,
            marine_data=self.marine_data,
            provider=self.provider,
            mouse_pos=None if panel else mouse_pos,
            location_menu=True,
        )
        cols, rows = get_terminal_size()
        floating = self.menu_overlay(cols, rows)
        output = _live.overlay(output, floating)
        return output, {}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    args = tides_parser().parse_args()
    runtime = TidesRuntime.from_sources(args)
    set_current(runtime)
    # The tide curve is time, so in a right-to-left language the whole
    # view reads from the right, the next tide at the right edge
    from linecast.terminal import bidi as _bidi
    _bidi.set_mirror(True)
    sweep_legacy_cache()

    # --search / --nearby: list stations and exit.  A bare `--search`
    # behaves like --nearby (empty query = nearest stations).
    if args.nearby or args.search is not None:
        query = args.search or ""
        _search_stations(query, metric=runtime.metric,
                         limit=15 if not query.strip() else 20,
                         cli_location=args.location)
        return

    # Ask the terminal how wide it draws things before the spinner has
    # the screen: the probe wants stdin and stdout to itself.
    if not runtime.json_mode:
        from linecast.terminal.textwidth import calibrate_from_terminal
        calibrate_from_terminal()

    # everything from here to the first paint may block on the network
    # (station lookup, metadata, two weeks of predictions) — spin
    # (suppressed for --json: stdout must carry nothing but the payload)
    spin = Spinner()
    if not runtime.json_mode:
        spin.start()
    try:
        # Station: --station flag > TIDE_STATION env var > geolocation
        override = args.station or os.environ.get("TIDE_STATION", "").strip()
        place, country = None, ""  # what the station was found for

        if override:
            provider = provider_for_id(override)
            if provider is not None:
                station_id = override
                station_name = plain_text(provider.name_for_id(override))
            else:
                # Text query — pick the closest matching station (first match
                # when the current location is unknown)
                matches = _find_matching_stations(override,
                                                  cli_location=args.location)
                if not matches:
                    print(f'No stations matching "{override}". '
                          "Try `linecast tides --nearby` to list the nearest stations.",
                          file=sys.stderr)
                    sys.exit(1)
                best = matches[0]
                provider = PROVIDERS[best["source"]]
                station_id = best["id"]
                station_name = best["name"] or f"Station {station_id[:8]}"
            # A named station says nothing about where the user is; the
            # units default still follows their own location, as it does
            # in the branch below.
            _lat, _lng, _cc = resolve_location(args.location, lang=runtime.lang)
            own = country_for_defaults(args.location, _cc, _lat, _lng)
            if own:
                runtime = TidesRuntime.from_sources(args, country=own)
                set_current(runtime)
        else:
            # need_country: provider routing (CHS for Canada, QLD for
            # Queensland) hinges on the country of the target location.
            # return_label: the forward geocoder already named the place
            # the user asked for. Keeping it spares a reverse-geocode
            # round trip and, more to the point, keeps the header able to
            # show that "Leith" was read as the one in Tasmania.
            lat, lng, country_code, resolved_label = resolve_location(
                args.location, lang=runtime.lang, need_country=True,
                return_label=True)
            if lat is None:
                print("Could not determine location for tide station lookup.", file=sys.stderr)
                sys.exit(1)
            if resolved_label:
                from linecast._geocode import place_label
                resolved_label = place_label(lat, lng, resolved_label, runtime.lang)

            # Re-resolve the runtime a cold cache made countryless.
            own = country_for_defaults(args.location, country_code, lat, lng)
            if own:
                runtime = TidesRuntime.from_sources(args, country=own)
                set_current(runtime)

            provider, station_id, station_name = _station_for_location(
                lat, lng, country_code, label=resolved_label)
            place, country = (lat, lng, resolved_label or ""), country_code or ""

            if station_id is None and runtime.json_mode:
                # No station in range: emit the payload shape anyway, with
                # station/events/series empty-or-null, and exit cleanly.
                import json as _json
                from linecast.sunshine.json import _location_label
                from linecast.tides.json import build_payload
                payload = build_payload(
                    None, runtime, datetime.now().astimezone(), [], [],
                    location=resolved_label or _location_label(lat, lng),
                )
                print(_json.dumps(payload, ensure_ascii=False))
                return

            if station_id is None:
                hint = ("No tide station within 100nm, and the global tide "
                        "model has no coverage here (inland?).\n"
                        "  Try `linecast tides --nearby` to list the nearest stations, "
                        "or `linecast tides --station <id or name>`.")
                if not TIDECHECK.available():
                    hint += ("\n  For more station coverage, set "
                             "LINECAST_TIDECHECK_KEY (free at tidecheck.com).")
                print(hint, file=sys.stderr)
                sys.exit(1)

        station_meta, station_name, station_tz = _station_details(
            provider, station_id, station_name)
        now_local = _station_now(station_meta)
        today = now_local.date()

        if runtime.json_mode:
            import json as _json
            from linecast.tides.json import build_payload
            preds = provider.tides_range(
                station_id, today - timedelta(days=1),
                today + timedelta(days=2), station_tz)
            hilo_data = provider.hilo_range(
                station_id, today - timedelta(days=1),
                today + timedelta(days=2), station_tz)
            now_local = _station_now(station_meta, preds or hilo_data)
            tz_name = (getattr(station_tz, "key", None)
                       or (now_local.tzname() if now_local.tzinfo else None))
            payload = build_payload(
                station_name, runtime, now_local, preds, hilo_data,
                station_id=station_id, source=provider.name, tz_name=tz_name,
            )
            print(_json.dumps(payload, ensure_ascii=False))
            return

        if runtime.oneline:
            from linecast.terminal.oneline import emit
            from linecast.tides.oneline import tides_oneline
            hilo_data = provider.hilo_range(
                station_id, today - timedelta(days=1),
                today + timedelta(days=1), station_tz)
            line = tides_oneline(station_name, hilo_data or [],
                                 _station_now(station_meta, hilo_data),
                                 runtime)
            spin.stop()
            emit(line)
            return

        fetch_start, fetch_end, y_range, marine_data, preds, hilo_data = _fetch_station(
            provider, station_id, station_meta, station_tz, runtime.live)

        if not preds:
            print(f"Could not fetch tide data for station {station_id}.", file=sys.stderr)
            sys.exit(1)

        if runtime.live:
            spin.stop()
            TidesApp(
                provider, station_id, station_name, station_meta,
                station_tz, runtime, preds, hilo_data, fetch_start, fetch_end,
                y_range=y_range, marine_data=marine_data, place=place, country=country,
            ).run()
        elif provider is NOAA:
            # NOAA's static view is the calendar day, which render fetches
            # itself from the month already cached above; every other
            # provider shows the same 24-hour window as the live view.
            out = render(
                station_id,
                station_name,
                station_meta=station_meta,
                runtime=runtime,
                y_range=y_range,
                marine_data=marine_data,
                provider=provider,
            )
            spin.stop()
            _live.print_frame(out)
        else:
            out = render(
                station_id,
                station_name,
                station_meta=station_meta,
                runtime=runtime,
                predictions=preds,
                hilo=hilo_data,
                y_range=y_range,
                marine_data=marine_data,
                provider=provider,
            )
            spin.stop()
            _live.print_frame(out)
    finally:
        spin.stop()
