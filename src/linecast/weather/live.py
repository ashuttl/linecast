"""The live weather: what runs when you type `weather`.

main() settles the arguments and the place, and gather() fetches what
the dashboard is built from side by side: the forecast, the airport's
report, the alerts, the air quality and the climate scale. --json,
--oneline and --prose print from that and exit, --print draws one frame,
and otherwise a WeatherApp puts the dashboard on screen and keeps it
fresh: a refresh every interval, the climate scale and the year's
archive fetched in the background, and the location menu. The month view
loads its hourly archive on demand; v cycles forecast, month, and year.
"""

import sys
import threading
import time as _t

from linecast.terminal import live as _live
from linecast.terminal.textwidth import visible_len
from linecast.terminal.framebuffer import get_terminal_size
from linecast._i18n import GEOCODER_UNTRANSLATED
from linecast._runtime import WeatherRuntime, install_banner, place_for, set_current
from linecast._parsers import refuse_view_flag, weather_parser
from linecast._log import log_failure
from linecast._geocode import reverse_geocode, print_search, without_country
from linecast.weather.hourly import _prepare_hourly_window
from linecast.weather.historical import fetch_historical
from linecast.weather.alert_feeds import ALERTS_UNAVAILABLE, AlertList, fetch_alerts
from linecast.weather.credits import (
    alert_attribution, forecast_attribution, observation_attribution,
)
from linecast.weather.forecast import local_now, fetch_forecast, forecast_is_todays
from linecast.weather.air import apply_national_index, fetch_canada_aqhi, fetch_aqi
from linecast.weather.location_menu import LocationMenu
from linecast.weather.humidex import apply_canadian_indices
from linecast.weather.observed import (
    apply_observation,
    fetch_observation,
    fetch_station_precipitation,
)
from linecast.weather.view import credit_row, forecast_notice, render_from_data

_FETCH_CEILING = 30  # shared wall-clock budget for the dashboard providers
# How long the live dashboard waits for the climate scale before showing
# the forecast without it. The archive answers in a few seconds when it
# answers; when it hangs, the view fills the scale in afterwards.
_CLIMATE_PATIENCE = 10
# The station's sky is a correction to the forecast, not worth holding
# the view for: once the forecast is in, it has this long to follow.
_OBSERVATION_PATIENCE = 2
# How long the live view waits before asking again for a climate scale
# that did not arrive with the forecast. Long enough for a request the
# dashboard stopped waiting for to finish and leave its answer in the
# cache, and to spare an archive that is refusing requests a second
# volley on its heels.
_CLIMATE_RETRY_DELAY = 20
# How often the year view asks the archive again: its latest days are
# revised as the reanalysis catches up, and a fetch from the cache
# costs nothing.
_YEAR_REFRESH = 3 * 3600


class WeatherApp(LocationMenu, _live.LiveApp):
    """The live weather view: the fetched data, refreshed every interval.

    Keep data in memory between renders: render_fn fires on every input
    event (hover motion, scroll), and re-reading disk caches — or worse,
    blocking on a network fetch when a TTL expires — on each mouse move
    makes the tooltip lag. Refresh at most once per interval, and off
    the render thread: the view keeps painting what it has while a
    worker fetches, so a slow network never freezes hover or scroll.
    """

    interval = 300
    scroll_step = 60
    mouse = True

    @property
    def help_view(self):
        if self.month_view:
            return 'weather_month'
        return 'weather_year' if self.year_view else 'weather'

    def __init__(self, data, alerts, aqi, lat, lng, runtime,
                 location_name="", historical=None, country="", year_view=False, month_view=None):
        self.data = data
        self.alerts = alerts
        self.aqi = aqi
        self.fetched = _t.monotonic()
        self.lat = lat
        self.lng = lng
        self.runtime = runtime
        self.location_name = location_name
        self.historical = historical
        self.country = country
        from linecast.weather.locations import LocationPicker
        self.locations = LocationPicker(runtime.lang)
        self._update_location_picker()
        self._state_lock = threading.RLock()
        self._generation = 0
        self._location_worker = None
        self._location_result = None
        self._loading = None
        self._location_hit = None
        self._worker = None
        self._climate_worker = None
        self.attempted = None   # local time the last refresh finished
        self.year_view = year_view
        self.month_view = bool(month_view)
        self.month_difference = month_view == "departure"
        from linecast.tides.month import month_of
        self.month_first = month_of(local_now(data).date(), -1)
        self._month = None
        self._month_asked = None
        self._month_worker = None
        self.year_colors = 0       # the year's bar coloring, an index into COLORS
        # The year view's ((lat, lng), day, climate, archive), and when
        # its fetch last started for a generation and day and whether it
        # came back whole.
        self._year = None
        self._year_asked = None
        self._year_worker = None
        self._start_climate(delay=_CLIMATE_RETRY_DELAY)
        self._start_year()
        self._start_month()

    def _refresh(self, generation, lat, lng, country):
        """Refresh a snapshot of the location; discard it if the user moved."""
        data, alerts, aqi = None, self.alerts, self.aqi
        # The address the alert matching needs, in the country's own
        # language, as the feeds' area names are; cached a day per
        # location, so only a place the reader has just moved to pays
        # for the call. Without it every text-only warning in the
        # country matches.
        try:
            _name, cc, addr = reverse_geocode(lat, lng)
        except Exception as exc:
            log_failure("weather", "live refresh address", exc,
                        fallback="alerts matched on geometry alone")
            cc, addr = "", {}
        try:
            forecast = fetch_forecast(lat, lng, self.runtime)
            observation = fetch_observation(lat, lng)
            data = apply_canadian_indices(
                apply_observation(forecast, observation,
                                  fetch_station_precipitation(observation)),
                cc or country, self.runtime)
            alerts = fetch_alerts(lat, lng, cc or country,
                                  lang=self.runtime.lang, address=addr)
            aqi = apply_national_index(fetch_aqi(lat, lng), country, lat, lng)
        except Exception as exc:
            log_failure("weather", "live refresh", exc, fallback="view stays stale")
        finally:
            with self._state_lock:
                if generation == self._generation:
                    if data:
                        self.data = data
                    self.alerts, self.aqi = alerts, aqi
                    self.fetched = _t.monotonic()
                    self.attempted = (None if forecast_is_todays(self.data)
                                      else local_now(self.data))
        _live.nudge()
        # The refresh is also the climate scale's next chance: a
        # location that arrived without one keeps asking every interval.
        with self._state_lock:
            if generation == self._generation:
                self._start_climate()

    def _fetch_climate(self, generation, lat, lng, delay=0):
        """Ask the archive for the climate scale a location arrived
        without, for the day it is there, and keep the answer unless the
        user has moved on.  The graph's scale falls in on the next paint."""
        if delay:
            _t.sleep(delay)
        with self._state_lock:
            if generation != self._generation or self.historical is not None:
                return
            data = self.data

        def stale():
            return generation != self._generation

        historical = None
        try:
            historical = fetch_historical(
                lat, lng, local_now(data).date(),
                celsius=getattr(self.runtime, "celsius", False),
                metric=getattr(self.runtime, "metric", False), stale=stale)
        except Exception as exc:
            log_failure("weather", "climate scale", exc, fallback="forecast's own range")
        if historical is None:
            return
        with self._state_lock:
            if generation != self._generation or self.historical is not None:
                return
            self.historical = historical
        _live.nudge()

    def _start_climate(self, delay=0):
        """Another try for a missing climate scale, in the background:
        a little after a location arrives without one, and at each
        refresh until it has one.  Called with the state lock held."""
        if self.historical is not None or not self.data:
            return
        worker = self._climate_worker
        if worker and worker.is_alive():
            return
        self._climate_worker = threading.Thread(
            target=self._fetch_climate,
            args=(self._generation, self.lat, self.lng, delay), daemon=True)
        self._climate_worker.start()

    def _fetch_year(self, generation, lat, lng, today):
        """The ten years and this year so far, for the year view; kept
        unless the user has moved on or a newer fetch has been asked for."""
        from linecast.weather.year import fetch_year

        def stale():
            return (generation != self._generation
                    or self._year_asked[:2] != (generation, today))

        climate, archive = fetch_year(lat, lng, today, self.runtime, stale=stale)
        with self._state_lock:
            if stale():
                return
            self._year = ((lat, lng), today, climate, archive)
            self._year_asked = (generation, today, self._year_asked[2],
                                climate is not None and archive is not None)
        _live.nudge()

    def _start_year(self):
        """Fetch the year view's data while the view is showing: when it
        opens, when the place or the day changes, again a little later
        when a fetch came back short, and every few hours for the
        archive's latest days.  Not while a new place loads: the
        generation is already the new place's, but the coordinates are
        still the old one's.  Called with the state lock held."""
        if not self.year_view or not self.data or self._loading is not None:
            return
        today = local_now(self.data).date()
        asked = self._year_asked
        if asked and asked[:2] == (self._generation, today):
            # A fetch still out for another place or day is left to
            # find itself stale; only this one's is waited for.
            worker = self._year_worker
            if worker and worker.is_alive():
                return
            wait = _YEAR_REFRESH if asked[3] else _CLIMATE_RETRY_DELAY
            if _t.monotonic() - asked[2] < wait:
                return
        self._year_asked = (self._generation, today, _t.monotonic(), False)
        self._year_worker = threading.Thread(
            target=self._fetch_year,
            args=(self._generation, self.lat, self.lng, today), daemon=True)
        self._year_worker.start()

    def _render_year(self, mouse_pos):
        from linecast.weather.year import COLORS, render_year, year_days
        today = local_now(self.data).date()
        # The place's own year; while a new place loads, the old one's
        # chart stays up, as the forecast does.
        year = self._year if self._year and self._year[0] == (self.lat, self.lng) else None
        climate = year[2] if year else None
        # Yesterday's archive answer is a day short; the forecast fills
        # that day until the new one comes.
        archive = year[3] if year and year[1].year == today.year else None
        cols, _ = get_terminal_size()
        return render_year(
            climate, year_days(archive, self.data, today), self.runtime,
            location_name=self.location_name, location_menu=True,
            mouse_pos=mouse_pos, live=True, hint=install_banner(),
            footer=credit_row(cols, self.runtime.lang, runtime=self.runtime,
                              controls=(("c", "hint_colors"),)),
            colors=COLORS[self.year_colors])

    def _fetch_month(self, generation, lat, lng, today):
        from linecast.weather.hourly_history import fetch_month

        def stale():
            return (generation != self._generation
                    or self._month_asked[:2] != (generation, today))

        series, complete = None, False
        try:
            series, complete = fetch_month(lat, lng, today, stale=stale)
        except Exception as exc:
            log_failure("weather", "hourly history", exc, fallback="keep previous month")
        with self._state_lock:
            if stale():
                return
            if series is not None:
                self._month = ((lat, lng), today, series)
            self._month_asked = (generation, today, self._month_asked[2], complete)
        _live.nudge()

    def _start_month(self):
        from linecast.weather.hourly_history import RECENT_AGE

        if not self.month_view or not self.data or self._loading is not None:
            return
        today = local_now(self.data).date()
        asked = self._month_asked
        if asked and asked[:2] == (self._generation, today):
            if self._month_worker and self._month_worker.is_alive():
                return
            wait = RECENT_AGE if asked[3] else _CLIMATE_RETRY_DELAY
            if _t.monotonic() - asked[2] < wait:
                return
        self._month_asked = (self._generation, today, _t.monotonic(), False)
        self._month_worker = threading.Thread(
            target=self._fetch_month,
            args=(self._generation, self.lat, self.lng, today), daemon=True)
        self._month_worker.start()

    def _month_busy(self):
        return bool(self._month_asked
                    and self._month_asked[:2] == (self._generation, local_now(self.data).date())
                    and self._month_worker and self._month_worker.is_alive())

    def _step_month(self, count):
        from datetime import date
        from linecast.tides.month import month_of
        from linecast.weather.historical import history_span
        today = local_now(self.data).date()
        self.month_first = max(date(history_span(today.year)[0], 1, 1),
                               min(today.replace(day=1), month_of(self.month_first, count)))
        return True

    def _render_month(self, mouse_pos):
        from linecast.weather.month import render_month
        from linecast.weather.i18n import _s
        self._step_month(0)
        cached = self._month
        now = local_now(self.data)
        series = (cached[2] if cached and cached[0] == (self.lat, self.lng)
                  and cached[1].year == now.year else None)
        notice = ""
        if not self._month_busy() and self._month_asked and not self._month_asked[3]:
            notice = _s("month_partial" if series else "month_unavailable", self.runtime)
            notice += " " + _s("retry_key", self.runtime)
        return render_month(series, self.month_first, self.runtime, self.lat, self.lng,
                            self.location_name, difference=self.month_difference,
                            mouse_pos=mouse_pos, now=now, location_menu=True, notice=notice)

    def _month_toast(self, cols, rows):
        if not self.month_view or self._flash is not None or not self._month_busy():
            return ""
        from linecast.weather.i18n import _s
        return self.busy_toast(_s("month_loading", self.runtime), cols, rows,
                               after=self._month_asked[2] + 0.2 - _t.monotonic())

    def _refreshing(self):
        return bool(self._worker and self._worker.is_alive())

    def _start_refresh(self):
        if not self._refreshing() and self._loading is None:
            self._worker = threading.Thread(
                target=self._refresh,
                args=(self._generation, self.lat, self.lng, self.country), daemon=True)
            self._worker.start()

    # --- the location menu (LocationMenu) ---------------------------------
    def _here(self):
        return self.lat, self.lng

    def _label(self):
        return self.location_name or f"{self.lat:.2f}, {self.lng:.2f}"

    def _load_place(self, place, stale):
        return gather(place.lat, place.lon, "", self.runtime, geo_label=place.name,
                      stale=stale)

    def _place_failed(self, place, result):
        from linecast.weather.locations_i18n import ls
        if not isinstance(result, dict) or not result.get('data'):
            return ls('failed', self.runtime.lang, name=place.name)
        return None

    def _commit_place(self, place, result):
        self.lat, self.lng = place.lat, place.lon
        self.data = result['data']
        self.alerts = result.get('alerts', [])
        self.aqi = result.get('aqi')
        self.historical = result.get('historical')
        self.country = result.get('country_code', '')
        self.location_name = result.get('name') or place.name
        self.aqi = apply_national_index(self.aqi, self.country, self.lat, self.lng,
                                        canada=result.get('aqhi'))
        self.fetched, self.attempted = _t.monotonic(), None
        self._start_climate(delay=_CLIMATE_RETRY_DELAY)
        self._start_year()
        self._start_month()

    def _on_place(self, col, row):
        hit = self._location_hit
        return row == 1 and hit is not None and hit[0] <= col <= hit[1]

    def _choose_location(self, place):
        if place not in (None, 'save'):
            with self._state_lock:
                # A refresh still out is for the place being left; it
                # finds itself stale, and need not hold up the next.
                self._worker = None
        super()._choose_location(place)

    def intercept(self, action):
        if super().intercept(action):
            return True
        if self.month_view:
            if action in ("fwd", "back"):
                return self._step_month(1 if action == "fwd" else -1)
            if action == "reset":
                from linecast.tides.month import month_of
                self.month_first = month_of(local_now(self.data).date(), -1)
                return True
        # The year view scrubs nothing; the arrows would move the
        # forecast behind it.
        return self.year_view and action in ("fwd", "back")

    def on_wheel(self, direction, col, row):
        if self.month_view and not self.locations.active:
            return self._step_month(-direction)
        if self.year_view and not self.locations.active:
            return True
        # else the menu's, or the forecast and alert modal's usual scrolling
        return super().on_wheel(direction, col, row)

    def clamp_offset(self, offset_minutes):
        with self._state_lock:
            cols, _ = get_terminal_size()
            window = _prepare_hourly_window(
                self.data.get("hourly", {}), local_now(self.data),
                max(10, cols), offset_minutes=offset_minutes)
            return window["offset_minutes"] if window else 0

    def on_action(self, key):
        """`r` asks for a newer forecast now rather than at the next
        interval -- the retry the stale-forecast line offers."""
        if super().on_action(key):
            return True
        if key == "r":
            with self._state_lock:
                if self.month_view:
                    if not self._month_busy():
                        if self._month_asked:
                            generation, today, _, complete = self._month_asked
                            self._month_asked = (generation, today, 0, complete)
                        self._start_month()
                else:
                    self._start_refresh()
            return True
        # v cycles forecast / month / year; y retains its direct year shortcut.
        if key in ("v", "y"):
            with self._state_lock:
                if key == "y":
                    self.year_view, self.month_view = not self.year_view, False
                elif self.month_view:
                    self.month_view, self.year_view = False, True
                elif self.year_view:
                    self.year_view = False
                else:
                    self.month_view = True
                self._start_year()
                self._start_month()
            return True
        if key == "c" and self.month_view:
            self.month_difference = not self.month_difference
            return True
        # c steps the year's bars through their colorings
        if key == "c" and self.year_view:
            from linecast.weather.year import COLORS
            self.year_colors = (self.year_colors + 1) % len(COLORS)
            return True
        return False

    def render(self, offset_minutes=0, mouse_pos=None, active_alert=None,
               modal_scroll=0):
        with self._state_lock:
            self._finish_location()
            return self._render(offset_minutes, mouse_pos, active_alert, modal_scroll)

    def _render(self, offset_minutes, mouse_pos, active_alert, modal_scroll):
        if _t.monotonic() - self.fetched >= 300:
            self._start_refresh()
        notice = forecast_notice(self.data, self.runtime, live=True,
                                 fetching=self._refreshing(), failed_at=self.attempted)
        panel = self.locations.active
        if self.month_view:
            self._start_month()
            output, alert_rows = self._render_month(None if panel else mouse_pos), {}
        elif self.year_view:
            self._start_year()
            output, alert_rows = self._render_year(None if panel else mouse_pos), {}
        else:
            output, alert_rows = render_from_data(
                self.data, self.alerts, self.runtime,
                location_name=self.location_name,
                offset_minutes=offset_minutes,
                mouse_pos=None if panel else mouse_pos,
                active_alert=None if panel else active_alert,
                modal_scroll=modal_scroll,
                aqi_data=self.aqi, historical=self.historical,
                notice=notice, country_code=self.country,
                location_menu=True,
            )
        cols, rows = get_terminal_size()
        # The live header always reserves space for its location control.
        from linecast.weather.header import location_chip, location_control
        label = location_chip(location_control(self.location_name, cols, self.runtime))
        self._location_hit = (cols - visible_len(label) + 1, cols)
        if self.month_view:
            from linecast.weather.month import month_location
            label = month_location(self.location_name, cols, self.runtime)
            self._location_hit = (1, visible_len(label)) if cols >= 54 and rows >= 23 else None
        floating = self.menu_overlay(cols, rows) + self._month_toast(cols, rows)
        if panel:
            alert_rows = {}  # a panel click must not open an alert beneath it
        output = _live.overlay(output, floating)
        return output, alert_rows

    def help_credits(self):
        from linecast.maps.search import ATTRIBUTION
        lang = self.runtime.lang
        if self.month_view:
            from linecast.weather.i18n import _s
            return ("Open-Meteo", *(_s(key, self.runtime) for key in (
                "month_average", "month_rows", "month_missing", "month_extremes")), ATTRIBUTION)
        observed = ((self.data or {}).get("current") or {}).get("observed")
        return (forecast_attribution(lang),
                observation_attribution(lang, observed["station"]) if observed else None,
                alert_attribution(self.country, lang),
                ATTRIBUTION)

    def on_open(self, idx):
        if 0 <= idx < len(self.alerts):
            url = self.alerts[idx].get("url", "")
            if url:
                import webbrowser
                webbrowser.open(url)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def gather(lat, lng, country_code, runtime, geo_label="", stale=None):
    """Everything the dashboard is built from, fetched side by side.

    Returns a dict with name, country_code, data, alerts, aqi and
    historical.  Each is taken from its own fetch on its own: a
    provider that raises -- an alert feed with a null where a string
    was expected, say -- costs only its own entry, logged under --debug,
    and never the air quality or the climate scale fetched beside it.
    All providers share one deadline; completed results survive a timeout.
    `stale` says whether the caller has stopped wanting the answer; the
    archive, which queues its requests, asks it before taking its turn."""
    from datetime import date

    from linecast._fanout import Fanout

    # A wedged provider must not hold up Ctrl-C: the fetches run on
    # daemon threads, and completed results survive the deadline.
    fanout = Fanout(_FETCH_CEILING)
    _submit, _settle = fanout.submit, fanout.settle

    result = {}
    fut_geocode = _submit(reverse_geocode, lat, lng)
    fut_forecast = _submit(fetch_forecast, lat, lng, runtime)
    fut_aqi = _submit(fetch_aqi, lat, lng)
    fut_observed = _submit(fetch_observation, lat, lng)
    # The station's gauge, once the station is known
    fut_gauge = _submit(lambda: fetch_station_precipitation(fut_observed.result()))
    today = date.today()
    fut_hist = _submit(fetch_historical, lat, lng, today,
                       celsius=runtime.celsius, metric=runtime.metric, stale=stale)

    # Alerts depend on geocode for country_code
    name, cc, addr = _settle(fut_geocode, "reverse geocode", ("", "", {}))
    # That address is in the country's own language, as the alert
    # feeds' area names are. A typed place is shown by the forward
    # geocoder's label, which names what was asked for; with only
    # coordinates, or a language that label cannot be in, Nominatim
    # is asked again for the name in the user's.
    fut_name = None
    if not geo_label or runtime.lang in GEOCODER_UNTRANSLATED:
        fut_name = _submit(reverse_geocode, lat, lng, lang=runtime.lang)
    fut_alerts = _submit(
        fetch_alerts, lat, lng, cc or country_code,
        lang=runtime.lang, address=addr,
    )
    # Canada publishes the air quality index it reports; fetched beside
    # the rest, and computed from the pollutants when it does not come.
    fut_aqhi = _submit(fetch_canada_aqhi, lat, lng) if (cc or country_code) == "CA" else None

    localized = _settle(fut_name, "place name", ("", "", {}))[0] if fut_name else ""
    result["name"] = localized or without_country(geo_label) or name
    result["country_code"] = cc or country_code
    forecast = _settle(fut_forecast, "forecast", None)
    observation = _settle(fut_observed, "station observation", None, _OBSERVATION_PATIENCE)
    gauge = (_settle(fut_gauge, "station precipitation", None, _OBSERVATION_PATIENCE)
             if observation else None)
    result["data"] = apply_canadian_indices(apply_observation(forecast, observation, gauge),
                                            result["country_code"], runtime)
    result["aqi"] = _settle(fut_aqi, "air quality", None)
    result["aqhi"] = _settle(fut_aqhi, "Canada's AQHI", None) if fut_aqhi else None
    # The live view can fill the climate scale in later, so it does not
    # keep the forecast waiting on a hung archive; a one-shot run has no
    # later, and waits out the deadline.
    patience = _CLIMATE_PATIENCE if getattr(runtime, "live", False) else None
    result["historical"] = _settle(fut_hist, "historical averages", None, patience)
    # The archive was asked for the machine's day, which is the
    # location's until the date line or a midnight comes between.
    # Then it is asked again for the day it is there: the download
    # covers the whole year, so the second answer comes from the
    # first's cache (issue #110).  Should that second ask miss the
    # deadline, the first answer stands: its year's extremes are the
    # same, and only the day's averages are a day off.
    if result["data"]:
        there = local_now(result["data"]).date()
        if there != today:
            again = _settle(
                _submit(fetch_historical, lat, lng, there,
                        celsius=runtime.celsius, metric=runtime.metric, stale=stale),
                "historical averages", None, patience)
            if again is not None:
                result["historical"] = again
    # A feed that raised or ran out the deadline was not heard from.
    result["alerts"] = _settle(fut_alerts, "alerts", AlertList(status=ALERTS_UNAVAILABLE))

    # A place no geocoder can name shows its coordinates, as radar and
    # maps do — never the timezone city, which can be a continent away
    # (issue #50).
    if not result["name"]:
        result["name"] = f"{lat:.2f}, {lng:.2f}"
    return result


def main():
    try:
        _main()
    except KeyboardInterrupt:
        sys.exit(130)


def _main():
    parser = weather_parser()
    args = parser.parse_args()
    runtime = WeatherRuntime.from_sources(args)
    set_current(runtime)
    if args.year:
        refuse_view_flag(parser, "--year", runtime)
    if args.month:
        flag = next((arg for arg in sys.argv[1:] if arg.startswith("--month")), "--month")
        refuse_view_flag(parser, flag, runtime)
    # In a right-to-left language the whole dashboard reads from the
    # right, the hourly graph included: now is at the right edge
    from linecast.terminal import bidi as _bidi
    _bidi.set_mirror(True)

    # --search: geocode cities and exit
    if args.search:
        print_search(args.search, lang=runtime.lang)
        return

    # country_code is "" for an override; the reverse geocode fills it in
    lat, lng, country_code, geo_label, runtime = place_for(args, runtime)

    # JSON and prose stdout contain only the requested text; Spinner clears
    # its line on cancellation. gather bounds all providers with one deadline.
    from contextlib import nullcontext
    from linecast.terminal.spinner import Spinner
    with nullcontext() if runtime.json_mode or runtime.prose else Spinner():
        result = gather(lat, lng, country_code, runtime, geo_label)

    location_name = result.get("name", "")
    final_country = result.get("country_code", "")
    data = result.get("data")
    alerts = result.get("alerts", [])
    aqi_data = apply_national_index(result.get("aqi"), final_country, lat, lng,
                                    canada=result.get("aqhi"))
    historical = result.get("historical")

    if data is None:
        print("Could not fetch weather data.", file=sys.stderr)
        sys.exit(1)

    if runtime.json_mode:
        import json
        from linecast.weather.json import build_payload
        payload = build_payload(
            data, location_name, final_country, runtime,
            alerts=alerts, aqi_data=aqi_data, historical=historical,
        )
        print(json.dumps(payload, ensure_ascii=False))
        return

    if runtime.oneline or runtime.prose:
        from linecast.terminal.oneline import emit
        if runtime.oneline:
            from linecast.weather.oneline import weather_oneline
            emit(weather_oneline(data, location_name, runtime))
        if runtime.prose:
            from linecast.weather.narrative import narrative_text
            emit(narrative_text(data, local_now(data), runtime))
        return

    if runtime.live:
        WeatherApp(
            data, alerts, aqi_data, lat, lng, runtime,
            location_name=location_name, historical=historical,
            country=final_country, year_view=args.year, month_view=args.month,
        ).run()
    elif args.month:
        from linecast.terminal.textwidth import calibrate_from_terminal
        from linecast.tides.month import month_of
        from linecast.weather.hourly_history import fetch_month
        from linecast.weather.month import render_month
        from linecast.weather.i18n import _s
        now = local_now(data)
        with Spinner(_s("month_loading", runtime)):
            series, complete = fetch_month(lat, lng, now.date())
        calibrate_from_terminal()
        notice = "" if complete else _s("month_partial" if series else "month_unavailable", runtime)
        _live.print_frame(render_month(
            series, month_of(now.date(), -1), runtime, lat, lng, location_name,
            difference=args.month == "departure", now=now, notice=notice))
    elif args.year:
        from linecast.terminal.textwidth import calibrate_from_terminal
        from linecast.weather.year import fetch_year, render_year, year_days
        today = local_now(data).date()
        with Spinner():
            climate, archive = fetch_year(lat, lng, today, runtime)
        calibrate_from_terminal()
        _live.print_frame(render_year(
            climate, year_days(archive, data, today), runtime,
            location_name=location_name, hint=install_banner()))
    else:
        from linecast.terminal.textwidth import calibrate_from_terminal
        calibrate_from_terminal()
        output, _alert_map = render_from_data(
            data,
            alerts,
            runtime,
            location_name=location_name,
            aqi_data=aqi_data,
            historical=historical,
            notice=forecast_notice(data, runtime),
        )
        _live.print_frame(output)
