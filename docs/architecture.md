# How linecast is put together

linecast is seven commands over a shared library. It needs nothing beyond Python's standard library, two small packages on Windows aside, so it carries its own PNG decoder, vector tile decoder and bidirectional text algorithm.

The code is in `src/linecast/`. How a module works, and why, is in its docstring.

## The layers

A module imports only from its own layer or the ones below it, at the top of the file or inside a function alike.

| | Layer | What is in it |
| --- | --- | --- |
| 4 | Entry points | `__main__.py`, `settings/`, `link.py`, `doctor.py`, `_completion.py`, `prose.py` |
| 3 | Commands | `weather/`, `sunshine/`, `moon/`, `sky/`, `tides/`, `radar/`, `maps/` |
| 2 | Libraries | `terminal/`, `astro/`, `_xyz.py`, `_commands.py`, `_parsers.py`, `_runtime.py` |
| 1 | State and the network | `_cache.py`, `_http.py`, `_rate_limit.py`, `_config.py`, `_location.py`, `_geocode.py`, `_fanout.py` |
| 0 | The base | `_paths.py`, `_plaintext.py`, `_geo.py`, `_png.py`, `_log.py`, `_timefmt.py`, `_i18n.py`, `locales/` |

A command may borrow another command's small modules, such as `moon/phase.py` or `sunshine/solar.py`, but never its `view.py` or `live.py`, which would bring the whole command with it.

`tests/test_layers.py` holds the package to this, and to having no import cycle at module level. The imports that still break the rule are listed there, each with its reason, and the list can only shrink.

## A run

Take `linecast tides --location Portland`.

1. `__main__.py` finds the command, from the first argument or from the name the binary was run under, and imports `tides/view.py`.
2. `main()` parses the flags with its parser from `_parsers.py`. `_runtime.py` settles the units, the clock, the language and the icons from the flags, the environment and the saved settings. The result is a `RuntimeConfig`, handed down as `runtime`.
3. `_runtime.place_for` finds the place: the `--location` flag, the saved location, or a rough one from the network address.
4. The command fetches what it needs through `_http.py`, and `_cache.py` keeps most of the answers.
5. `--json` and `--oneline` print from `json.py` and `oneline.py`. `--print`, or a stdout that is not a terminal, prints one frame. Otherwise the command's `LiveApp` goes on screen.

## The rules

- A name with a leading underscore belongs to the package it is defined in. A name that more than one package uses is made public in its home module. The top-level `_*.py` modules are the exception: they are shared on purpose. `tests/test_layers.py` checks this.
- A command's `__init__.py` holds only its docstring, so borrowing one module does not load the command.
- Every request goes through `_http.py`.
- `_paths.py` decides where files go, and nothing else should. A module asks `_paths.data_path` for a bundled file.
- Only `terminal.keys.read_key` reads stdin.
- Text from outside passes through `_plaintext.plain_text` where it comes in, so a place name or an alert headline cannot reach the terminal as an escape sequence.
- Background work does not draw. It changes state and calls `terminal.live.nudge()`, which wakes the loop for a repaint from any thread.
- A provider that fails returns its fallback and logs one line. Nothing reaches stderr in normal use but a sentence for the user.
- Only a `main` ends the run. Anything below it raises `_log.UserError`. `tests/test_layers.py` checks this.
- The strings are in `locales/`, as data. A test keeps code out of those files.
- A view lays out text in logical order, first letter first. `terminal/bidi.py` puts right-to-left text in display order at the end.
- Fields are half-blocks and lines are braille. The sea, terrain and the Moon's glow are fields. Coastlines, borders and the tide curve are lines.
- The modules that fetch annotate their public signatures. The rest of the package mostly does not, by choice.

## Inside a command

Each command is a package, and the same file names mean the same thing in each.

| File | What it holds |
| --- | --- |
| `view.py` | `main()`, and the function that renders one frame from data it is given |
| `live.py` | The live app, its state and its keys |
| `i18n.py` | The command's strings, read from `locales/`, and the grammar around them |
| `json.py` | The `--json` payload |
| `oneline.py` | The `--oneline` summary |
| `palette.py` | The inks, built again when the terminal's theme changes |
| `__main__.py` | Lets `python -m linecast.weather` run the command from a checkout |

Radar and maps have no `--json` or `--oneline`. Weather keeps its inks in `style.py`, and maps in `paint.py` and `style.py`.

`live.py` draws through `view.py`, so `view.py` does not import it at the top. In weather, tides, radar and maps, `main()` in `view.py` hands off to the one in `live.py`.

## What the commands share

### The live loop

`terminal.live.live_loop()` runs every live view. It puts the terminal on the alternate screen, turns on mouse reporting, calls a render function whenever something happens (a key, a wheel notch, a drag, a resize, a timer, a nudge), and writes the frame.

A view with state subclasses `terminal.live.LiveApp`. The loop's hooks are its methods (`render`, `on_action`, `on_wheel`, `on_drag`, `on_click`), and the loop's tuning is its class attributes. A hook the subclass does not override is not handed to the loop, so the loop's default stands: without `on_wheel` the wheel scrubs time, and without `on_drag` there are no clicks.

A frame is a string. A tooltip, a modal or a search field is appended to it with `terminal.live.overlay()`, and the loop draws it after the body.

The loop paces itself to the terminal. Each frame goes out with a cursor position query after it, and the next waits for the reply, so a slow terminal gets fewer frames, not a backlog. `FramePainter` writes only the rows that changed. A view in motion starts a `terminal.live.Ticker`, a thread that wakes the loop thirty times a second while something moves.

- `terminal/keys.py` — what the bytes a terminal sends mean. `KEYS` is every key a view answers to outside a text field, so a new key goes there too.
- `terminal/keylayouts.py` — keys typed under a non-Latin layout, read as the Latin keys they sit on.
- `terminal/term.py` — raw input, the wakeup and the resize notice, for POSIX and Windows.
- `terminal/help.py` — the shared `?` panel.

### Drawing

- `terminal/framebuffer.py` — color fields, two sub-pixels to a cell, in half-blocks.
- `terminal/braille.py` — curves and strokes, 2×4 dots to a cell.
- `terminal/color.py` — RGB into escape codes for what the terminal supports: truecolor, 256, 16 or none.
- `terminal/theme.py` — asks the terminal for its colors and builds every palette from them, and builds them again when the theme changes under a live view.
- `terminal/textwidth.py` — how many cells a string takes.
- `terminal/box.py` — where a floating panel goes.
- `terminal/composition.py` — a hover chip's drop shadow, blended with the finished frame under it.
- `terminal/chart.py`, `terminal/heading.py`, `terminal/month_layout.py` — what weather's and tides' charts share.
- `terminal/glyphs.py` — the sun and moon glyphs of each icon set.
- `terminal/oneline.py`, `terminal/spinner.py` — the one-line summary's writer, and the busy line while a run waits on the network.

### Right-to-left text

`terminal/bidi.py` puts each row in display order just before it is written: every row of a frame, every piece of an overlay, `--print` and `--oneline`. It orders the text by the Unicode Bidirectional Algorithm (`terminal/uba.py`), joins Arabic-script letters (`terminal/shaping.py`), and writes a language's own digits. It moves cells but never adds or removes one, so the layout the view measured holds.

A view can ask to be laid out from the right with `terminal.bidi.set_mirror`. The pass then mirrors each row, and the live loop mirrors the pointer and the arrow keys, so no view needs a right-to-left layout of its own.

A few terminals order text themselves. linecast knows them by name and hands them right-to-left text in logical order.

### What a view keeps

`terminal/scenes.py` holds the two ways a live view keeps what it paints from.

- A `Memo` is a small bounded dictionary that answers or builds on the calling thread and forgets its oldest entries: basemaps, place names, shaded terrain, route layers.
- A `SceneCache` holds a view's worth of fetched data: an elevation grid, a street layer, a radar field. Live, a miss starts one background load for that key, answers an empty value so the frame can say "loading", and nudges the loop when the data lands. Asked to block, it loads on the calling thread.

A `FetchHold` gates a `SceneCache`, so a run of zoom taps repaints at once but only the view you stop on reaches the network. Radar's frames have a cache of their own, `radar/frames.py`, because they are fetched ahead in a set order.

### Strings

The strings are in `locales/`, one file per language. A regional variant's file, such as `pt_PT.py`, holds only the words that differ from its base. Each file is data alone, a name in capitals for each table (`WEATHER`, `MONTHS`, `SKY_CULTURES`) set to a literal, so a translator can edit it without reading the code. Its `SETTINGS` says how the language writes numbers and durations, which plural rule it takes, whether it runs right to left, and which calendar, hours and sky follow it.

A command reads its table through `_i18n.LocaleTable("WEATHER")`, which imports a language's file the first time it is asked for, so a run in French loads French and English alone. A missing key falls back to the base language, then to English.

Logic stays in Python: the plural rules, French elision, the precipitation nouns' agreement, the calendars' numerals. CONTRIBUTING.md says how to add a language.

### Settings

Each saved setting is declared once, as a record in `_config.SETTINGS`: its name, which is both its command and its key in `config.json`, its choices, the environment variable that overrides it, and its line on the help page. The help page, the dispatch, the completions, the flags, the resolvers and doctor all read it from there. A new setting is one more record and its module in `settings/`.

Every resolver takes the same order: the flag, the variable, the saved setting, the default.

### Files on disk

`_paths.py` decides the cache root and the config root, and reads the environment each time it is asked, so a test or a wrapper can move them. [configuration.md](configuration.md) says where they are.

The config root holds `config.json` and `locations.json`, the recent places in the location menu.

`_cache.py` writes JSON and bytes under the cache root, with a maximum age per file. Within that age a file is read instead of the network. Past it, when the network fails, it is read as a stale copy, which is how the views keep working offline. `_http.fetch_json_cached` does both.

The cache root holds a folder for each command that fetches. `_cache.sweep` runs once a day, when a view command starts, and deletes what has gone unused for longer than its table allows. `maps/` is kept under a size instead, least recently used first (`maps/tile_cache.py`). Clearing the cache by hand is always safe: what is missing is fetched again.

`data/` holds what ships with the package: the stars, the basemap, the tide gauges. Each file has a `scripts/build_*.py` that bakes it.

### The network

`_http.py` keeps one connection per host per thread and attaches the user agent. The Bureau of Meteorology publishes its warnings only over FTP, so `weather/alert_feeds/bom.py` reads them with `ftplib`, the one request that does not go through it.

- `_location.py` — where a view is for. With no location saved or given, it asks ipinfo.io for a rough one.
- `_geocode.py` — names into places and places into names, from Nominatim and Open-Meteo's geocoder.
- `_rate_limit.py` — spaces the requests to a provider.
- `_fanout.py` — fetches run side by side, on threads that never hold up the exit.

Two more modules have "location" in their names: `settings/location.py` is the `linecast location` command, and `weather/locations.py` is the recent places menu.

The sky asks the network only for the location and its name.

### Diagnostics

A provider, cache or decoder that fails returns its documented fallback (a stale copy, an empty layer, None) and calls `_log.log_failure`, which prints one line, and nothing unless `--debug` is on.

Failures are caught in two tiers. A provider absorbs what the network can be expected to do to it: a timeout, a refused connection, an error status, an answer it cannot parse, a missing key, a spent quota. Anything else it raises is a bug, and whatever asked for it catches it, logs the traceback, and answers with the fallback, so the bug costs the view that one entry. `_fanout.Fanout.settle` does this for fetches run side by side.

When a run cannot go on (a place no geocoder knows, a settings file that will not take a write), the code that finds the trouble raises `_log.UserError`. The command's `main`, wrapped in `_log.exits_on_user_error`, prints the message on stderr and exits with status 1. Nothing below a `main` ends the process, since in a worker thread that would end only the thread.

`terminal.live.WorkerWatch` catches a background thread that crashes in a live session and reports it once the terminal is restored. `doctor.py` reports where the files are and what the terminal supports, and probes the provider hosts.

### Astronomy

`astro/ephemeris.py` computes where the Sun and Moon are: positions, phases, and the rise and set times that follow. Its `sunrise_sunset` is the app's one sunrise. Sunshine, the weather's forecast, the tides' night shading, the month views and the traditional hours all read it.

- `astro/seasons.py` — the equinoxes, the solstices and the full-moon names.
- `astro/hours/` — the day read in a tradition's hours. The `__init__` is the model, a `DayHours`: the two edges the Sun sets, the count of equal hours between them, and the named marks along the day. Each tradition is a module that fills it in.
- `astro/calendars/` — the traditional calendars, one module each. Each answers what this civil date is in that calendar and what comes next. `civil.py` is the calendar the app writes its dates in: Gregorian, except in Persian, where it is Iran's Solar Hijri.

[hours.md](hours.md) and [calendars.md](calendars.md) say how each is computed and checked.

## The commands

### Weather

Weather's data is the forecast as Open-Meteo sends it, a dict with its `current`, `hourly` and `daily` blocks. linecast keeps no model of its own, and the modules that add to the forecast write into the same dict: `forecast.py` the app's sunrise and sunset, `observed.py` a nearby airport's sky, `humidex.py` Canada's humidex and wind chill. The dashboard, the year view and `--json` all read from it.

`gather` in `live.py` fetches everything the dashboard is drawn from, side by side.

- `view.py` — lays out the dashboard.
- `header.py` — the conditions line at the top.
- `hourly.py` — the hourly chart.
- `narrative.py` — the prose under the chart.
- `daily.py` — the daily rows. `day_chart.py` is the hover graph on one.
- `alerts.py` — the alerts and their modal.
- `month.py`, `year.py` — the month and year views.
- `cover.py`, `credits.py`, `style.py` — the sky's cover in words, the credit lines, the inks.
- `forecast.py`, `air.py`, `historical.py`, `hourly_history.py` — Open-Meteo's forecast, air quality and archive.
- `observed.py` — the Aviation Weather Center's airport reports.
- `alert_feeds/` — the alert services, a module each. `ALERT_FEEDS` in the `__init__` routes a country to its service.
- `locations.py`, `location_menu.py` — the recent places menu, which tides uses too.

`prose.py`, at the top level, is a bench for the forecast in words, hidden from the command list.

### Sunshine

- `view.py`, `year.py` — the day's arc and the year view.
- `solar.py` — the Sun's height and its rising and setting, in the decimal hours the views plot.
- `hours.py` — paints the traditional hours in the day view.
- `palette.py` — the sky's inks and gradients, which other commands borrow.

### Moon

- `view.py` — the phase panel. `calendar.py` is the month grid.
- `phase.py` — the Moon's facts: the phase and its name, how much is lit, the next rise and set, the next new and full moon. Other commands take them from here.
- `disc.py` — the Moon's disc, and the drag that turns it. `stars.py` is the stars about it.
- `readings/` — what the command says of a traditional calendar. `Reading` in the `__init__` is the questions every part of the command asks a calendar, and a module each answers them for one.

The calendars' arithmetic is in `astro/calendars/` and their words in `moon/i18n.py`. The almanac has no arithmetic of its own: its advice is strings in the locale files, and its full-moon names come from `astro/seasons.py`.

### Sky

`view.py` draws the frame, and `live.py` holds the camera and the keys. `scene.py` is the geometry: where everything is at one moment, and the projection both ways. The `--json`, the one-line summary and the search read it without loading the renderer.

- `planets.py` — where the planets are.
- `catalogue.py` — the bundled stars, their names, the constellation figures, the Milky Way and the sky cultures. The stars are in J2000, and the scene turns them to the equinox of date, so they land beside the planets.
- `deep.py` — the fainter stars, decoded a region at a time when the zoom needs them.
- `objects.py` — the Messier objects. `asterisms.py` is the asterisms.
- `search.py` — the `/` panel. `picker.py` is the tradition picker.

`data/STARS.md` has the sources and licenses, and [cultures.md](cultures.md) the credits the cultures' licenses require.

### Tides

`view.py` lays out the day chart from the parts in `chart.py`. The longer views are a module each: `month.py`, `year.py`, and `makeup.py`, what moves the tide at the place. `live.py` steps through them with `v`.

- `stations.py` — picks the station for a place, the country's own service first and Open-Meteo's global model last, and fetches what the chart needs side by side.
- `providers.py` — a `TideProvider` for each source, and the registry `stations.py` routes by.
- `noaa.py`, `chs.py`, `qld.py`, `hko.py`, `jma.py`, `kartverket.py`, `tidecheck.py`, `openmeteo.py` — the sources: NOAA, the Canadian Hydrographic Service, Queensland, the Hong Kong Observatory, the Japan Meteorological Agency, Kartverket, TideCheck and Open-Meteo.
- `ticon.py` — the bundled TICON-4 gauges, predicted here from their constants.
- `harmonic.py` — the tide machine: a tide added up from its harmonic constants.
- `common.py` — what the providers share.
- `marine.py` — Open-Meteo's marine forecast, for the sea under the chart.

### Radar

- `sources.py` — picks the frame source for a place: LibreWXR first, then IEM's NEXRAD composites over the continental US and RainViewer elsewhere. `iem.py` and `tiles.py` fetch the frames.
- `frames.py` — the frame cache and prefetcher. It fetches the displayed frame first, then the rest, and the animation waits on a fraction of them.
- `render.py` — the compositor.
- `basemap.py` — the Natural Earth geography in braille. Maps builds on it.
- `layers.py` — the temperature and wind layers. `warnings.py` is the warning polygons.
- `palettes.py` — the color ramps.

Radar and maps share `_xyz.py`, the map tile arithmetic: the window a view covers, the tile projection and zoom, the stitch of tiles into one canvas, and the thread pools that fetch them.

### Maps

`view.py` draws, `live.py` runs the app, and `loaders.py` fetches, builds and keeps what a view is made of.

The map has two registers, street and terrain, and one geometry: `globe.py` inverts the same orthographic projection for a valley as for the planet. Close in, the flat rasterizer gives the same picture and runs instead. Far out, where no tile source can be asked, the frame is read from `globe_texture.py`, the whole planet baked once into a texture.

`maps.live.Camera` holds the center and zoom and whatever motion they are in: a zoom easing, a coast after a flick, a keyed pan, a flight to a search result, the planet turning. `motion.py` is the arithmetic a motion follows. `maps.globe.Camera` is something else, the projection of one window.

A globe frame is cheap, and every one is drawn for real. A flat view takes a second or more to build, and the frame loop does not wait for it.

- A flat view is built an eighth of the window wider on each side, and a frame is a crop of it (`overscan.py`). A pan inside the margin costs nothing.
- Past the margin, the frames until the new view lands are the last view moved and scaled (`reproject.py`). Labels and hover wait for the real thing.
- Where the camera will stop is built as soon as it is known: a coast's destination at the release, a flight's from the descent.
- Builds run in a second interpreter (`worker.py`), so they do not take the lock the frame loop needs. `LINECAST_MAPS_WORKER=0` keeps them in-process, and the test suite sets it.

`places.py` names the cities in both registers from the Natural Earth gazetteer. `labels.py` places the street register's other labels and carries them from one build to the next, so a pan moves no name.

- `streets.py` — rasterizes the vector tiles into the street register. `style.py` is the cartography as data.
- `paint.py` — terrain's inks and the composers.
- `hover.py` — what the pointer is over. `ui.py` is the search and directions panels.
- `vtiles.py`, `mvt.py` — OpenFreeMap's vector tiles and their decoder.
- `elevation.py` — the AWS terrain tiles. `builtup.py` is the optional built-up raster.
- `search.py`, `route.py` — Photon and Nominatim for search, OSRM for directions.
- `globe_now.py` — daylight and clouds. `night_lights.py` is the lights on the night side.
- `climate.py`, `glaciers.py` — the bundled grids that pick terrain's colors and paint its ice.
- `tile_cache.py` — keeps the tile cache under its size.

`scripts/bench_maps_live.py` drives the whole loop in a pty, and `scripts/bench_maps_frames.py` times a single frame.
