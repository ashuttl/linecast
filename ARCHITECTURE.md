# How linecast is put together

This is the map for someone who wants to change linecast without reading all of it first. The README says what the commands do; this says where the code for each part lives and how the parts talk to each other.

## The commands

Six commands, one module each at the top level of `src/linecast/`: `weather.py`, `sunshine.py`, `moon.py`, `tides.py`, `radar.py`, `maps.py`. Each has a `main()` that parses arguments (the parsers are built in `_runtime.py`, one function per command), resolves the location, fetches what it needs, and then either prints one frame (`--print`, or whenever stdout is not a terminal) or opens the live view. `__main__.py` is the `linecast` command itself; it hands off to the same six, plus `location.py`, `units.py`, `clock.py`, `icons.py` and `calendar_cmd.py` for the saved settings, `doctor.py` for the diagnostic report, and `_completion.py` for the shell completions.

The larger commands are split the same way: the top-level module renders one frame from data it is given; `_<command>_live.py` holds the live app (state and keys); the rest of `_<command>_*.py` fetches, decodes and paints. So `maps.py` draws, `_maps_live.py` runs, `_maps_views.py` fetches and caches, `_maps_paint.py` holds the inks, `_maps_streets.py` and `_maps_labels.py` build the street register, `_maps_ui.py` is the search and directions panels, and `_maps_style.py` is the cartography as plain data. Radar is the same: `_radar_live.py`, `_radar_frames.py` (the frame cache and prefetcher), `_radar_render.py` (the compositor), `_radar_basemap.py`, `_radar_layers.py`, `_radar_warnings.py` and `_radar_ui.py`. Weather's rendering is in `_weather_hourly.py`, `_weather_daily.py`, `_weather_sections.py` and `_weather_alerts.py`; tides' in `_tides_render.py`. `_ephemeris.py` is where the Sun and Moon actually are — positions, phases, and the rise and set times that follow — shared by the moon panel, the tides chart's moon labels and the phase icon in the one-line summaries. Each command's translated strings sit in its own `_<command>_i18n.py`, read through `_i18n.lookup`.

The moon's traditional calendars are one module each, and each answers the same question, what this civil date is in that calendar and what comes next: `_lunisolar.py` (Chinese, Japanese and Korean, from the ephemeris at each calendar's meridian), `_thai_lunar.py` (the Suriyayart arithmetic), `_pacific.py` (Hawaiʻi, American Samoa and the Marianas, from the first visible crescent), `_hijri.py` (the Umm al-Qura rule, from the ephemeris at Mecca) and `_hebrew.py` (the fixed arithmetic). `_lunisolar.resolve_calendar` picks which one the panel shows, from the flag, the saved setting or the language. `moon.py` lays the answer out beside the phase, `_moon_calendar.py` draws the month grid the `v` key opens, and `_moon_json.py` puts the same facts in the `--json` block. The almanac has no module of its own: its gardening counsel is strings in `_moon_i18n.py`, and its full-moon names come from `_seasons.py`, beside the equinoxes and solstices.

## The live loop

`_live.live_loop()` runs every live view. It puts the terminal on the alternate screen, turns on mouse reporting, calls a render function whenever something happens — a key, a wheel notch, a drag, a resize, a timer, a background fetch landing — and writes the frame. It decodes the escape sequences itself (`_read_key`); nothing else in the package reads stdin.

A live view with state subclasses `_live.LiveApp`. The loop's hooks are its methods — `render`, `on_action` for single keys, `on_wheel`, `on_drag`, `on_click`, `intercept` for a panel that wants every key, `text_mode` while a text field is open, `play_gate` for animations — and the loop's tuning is its class attributes (`interval`, `mouse`, `scroll_step`, `auto_play`, `play_interval`). `run()` puts the app on screen; `stop()` is called on the way out. A hook the subclass does not override is not handed to the loop, so the loop's defaults stand: without `on_wheel` the wheel scrubs time, without `on_drag` there are no clicks. `MapApp`, `RadarApp`, `WeatherApp` and `TidesApp` are the four; sunshine and moon are a single render function and call `live_loop` directly.

A frame is a string. Anything floating over it — a tooltip, a modal, the search field, the directions panel — is appended with `_live.overlay(body, floating, motion=...)`, which puts it on the channel the loop draws after the body, where clearing lines cannot touch it. `motion` switches any-motion mouse reporting with the frame; the search field turns it off, because a torn motion sequence reads as ESC.

Background work should not draw. It changes state and calls `_live.nudge()`, which wakes the loop for a repaint from any thread.

## What a view keeps

Everything a live view paints from was fetched on some earlier repaint or in the background. `_scenes.py` holds the two ways of keeping it. A `Memo` is a small bounded dictionary that answers or builds on the calling thread and forgets its oldest entries: basemaps, place names, shaded terrain buffers, route layers. A `SceneCache` holds a view's worth of fetched data — an elevation grid, a street layer, a radar condition field. Asked to block, it loads on the caller. Live, a miss starts one background load for that key, answers an empty value so the frame can say "loading", and nudges the loop when the data lands. A `FetchHold` can gate it, so a run of zoom taps repaints at once but only the view you stop on reaches the network.

Radar frames have their own cache in `_radar_frames.py`, because they are fetched ahead in a set order (the displayed frame first, then the rest of the window) and the animation waits on a fraction of them.

On disk, `_paths.py` decides where files go, and nothing else should. The cache root is `LINECAST_CACHE_DIR` if set, else `$XDG_CACHE_HOME/linecast`, else `~/.cache/linecast` (on macOS, `~/Library/Caches/linecast`, unless an older `~/.cache/linecast` is there and the new directory is not). The config root is `LINECAST_CONFIG_DIR`, else `$XDG_CONFIG_HOME/linecast`, else `~/.config/linecast` on every platform. Both are read from the environment each time they are asked for, not fixed at import, so a test or a wrapper can move them. `_cache.py` writes JSON and bytes under the cache root, with a maximum age per file; `_config.py` reads and writes `config.json` under the config root (the saved location, units, clock, icons and calendar).

## Where the network is touched

Every request goes through `_http.fetch_bytes` and its JSON and cached forms, which keep one connection per host per thread and attach the user agent. The modules that call it, and who they call:

- `_location.py` — ipinfo.io for a rough location when none is saved or given, ipwho.is and GeoJS behind it; the Open-Meteo geocoder turns place names into coordinates, Photon behind it.
- `_weather_sources.py`, `_weather_historical.py`, `_marine.py` — Open-Meteo forecast, air quality, archive and marine APIs; alerts from the US National Weather Service, Environment Canada, MeteoAlarm and a few national services.
- `_tides_providers.py` and `_tides_noaa.py`, `_tides_chs.py`, `_tides_qld.py`, `_tides_hko.py`, `_tides_tidecheck.py`, `_tides_openmeteo.py` — NOAA CO-OPS, the Canadian Hydrographic Service, Queensland's open data, the Hong Kong Observatory, TideCheck (needs `LINECAST_TIDECHECK_KEY`) and Open-Meteo, one `TideProvider` each, picked by station.
- `_radar_sources.py`, `_radar_source.py`, `_radar_tiles.py` — IEM NEXRAD composites, RainViewer and LibreWXR, picked by location; `_radar_warnings.py` for the warning polygons; `_radar_layers.py` for the temperature and wind lattice from Open-Meteo.
- `_vtiles.py` — OpenFreeMap vector tiles, the OpenStreetMap US Tileservice behind them, decoded by `_mvt.py`; `_elevation.py` — the AWS terrain tiles; `_builtup.py` — the built-up raster; `_maps_search.py` — Photon and Nominatim; `_maps_route.py` — OSRM; `_globe_now.py` — the cloud mosaic.

The public signatures of these modules carry type annotations; the rest of the package mostly does not, by choice.

## Diagnostics

A provider, cache or decoder that fails returns its documented fallback -- a stale copy, an empty layer, None -- and calls `_runtime.log_failure`, which prints one line naming the provider, the operation, the host, the exception and the fallback, and prints nothing unless `--debug` is on. That is the whole contract: nothing should reach stderr in normal use but a sentence for the user, and a `--debug` transcript starts with the version, the Python, the platform and where the cache and settings live, then lists every fallback taken. URLs in the transcript go through `_http.redact_url`, which drops the query string. The one line that prints without `--debug` is the notice after a live session in which a background thread crashed; `_live.WorkerWatch` catches it with `threading.excepthook` and reports it once the terminal is restored. `doctor.py` collects the same facts on demand and probes every provider host.

## Drawing

`_framebuffer.py` paints color fields at two sub-pixels per cell with half-block characters; `_braille.py` draws curves and strokes at 2×4 dots per cell. As a rule, fields (the sea, terrain, the moon's glow) are half-blocks and lines (coastlines, borders, the tide curve) are braille. `_color.py` turns RGB into escape codes for what it can tell the terminal supports — truecolor, 256, 16 or none. `_theme.py` asks the terminal for its own colors and builds every palette from them, falling back to a stock palette when the terminal does not answer, and builds them again when the theme changes under a live view.
