# How linecast is put together

This is the map for someone who wants to change linecast without reading all of it first. The README says what the commands do. This page says where the code for each part lives, how a run moves through it, and which rules hold everywhere.

It stops at the module. How a module does its work, and why, is in the docstring at the top of it. The long ones are worth reading before a change to what they describe: `maps/overscan.py`, `maps/labels.py`, `terminal/bidi.py`, `weather/narrative.py`.

linecast runs on Python's standard library alone, two small packages on Windows aside. That is why it carries its own PNG decoder, vector tile decoder and bidirectional text algorithm.

## The layers

The code is in `src/linecast/`, in five layers. A module imports only from its own layer or the ones below it, at the top of the file or inside a function alike.

| | Layer | What is in it |
| --- | --- | --- |
| 4 | Entry points | `__main__.py`, `settings/`, `link.py`, `doctor.py`, `_completion.py`, `prose.py` |
| 3 | Commands | `weather/`, `sunshine/`, `moon/`, `sky/`, `tides/`, `radar/`, `maps/` |
| 2 | Libraries | `terminal/`, `astro/`, `_xyz.py`, `_commands.py`, `_parsers.py`, `_runtime.py` |
| 1 | State and the network | `_cache.py`, `_http.py`, `_rate_limit.py`, `_config.py`, `_location.py`, `_geocode.py`, `_fanout.py` |
| 0 | The base | `_paths.py`, `_plaintext.py`, `_geo.py`, `_png.py`, `_log.py`, `_timefmt.py`, `_i18n.py`, `locales/` |

A command may borrow another command's small modules, such as `moon/phase.py` or `sunshine/solar.py`, but never its `view.py` or `live.py`, which would bring the whole command with it. Nothing imports an entry point.

`tests/test_layers.py` holds the package to this, and to having no import cycle at module level. The imports that still break the rule are listed there, each with the reason it stands, and the list can only shrink.

Most of these modules come up again below. The ones that do not: `_geo.py` is the small geometry (wrapping a longitude, the distance between two points, a bearing's compass point), `_png.py` decodes PNGs, `_timefmt.py` writes clock times as text, `_commands.py` is the list of commands and the line the help pages say about each, `_completion.py` writes the shell completions from the parsers, and `link.py` makes the short-name links.

## A run, start to finish

Take `linecast tides --location Portland`.

1. `__main__.py` finds the command, from the first argument or from the name the binary was run under, and imports `tides/view.py`. A setting's command is its module in `settings/`. For a view command it first runs the day's cache sweep.
2. The command's `main()` parses its flags with its parser from `_parsers.py`. `_runtime.py` settles what the run uses from the flags, the environment, the saved settings and the language: the units, the clock, the language, the icons, and whether the run is live. The result is a `RuntimeConfig`, handed down as `runtime`.
3. `_runtime.place_for` finds the place: the `--location` flag, the saved location, or a rough one from the network address.
4. The command fetches what it needs. Every request goes through `_http.py`, and most answers are kept by `_cache.py`.
5. It writes its answer. `--json` and `--oneline` print from the command's `json.py` and `oneline.py`. `--print`, or a stdout that is not a terminal, prints one frame through `terminal.live.print_view`. Otherwise the command's `LiveApp` goes on screen and stays until `q`.

## The rules

Besides the layers, these hold across the package.

- A name with a leading underscore belongs to the package it is defined in. Another package imports only public names, so a name that more than one package uses is made public in its home module. The top-level `_*.py` modules are shared on purpose. `tests/test_layers.py` checks this, with its own shrinking list of the uses that remain.
- A command's `__init__.py` holds nothing but its docstring, so a module that borrows one part of a command does not load the rest.
- Every request goes through `_http.fetch_bytes` or its JSON and cached forms.
- `_paths.py` decides where files go, and nothing else should. A module asks `_paths.data_path` for a bundled file rather than looking beside its own.
- Nothing reads stdin but `terminal.keys.read_key`.
- Text from outside is cleaned where it comes in. Place names, alert headlines and map labels pass through `_plaintext.plain_text`, so none of them can reach the terminal as an escape sequence.
- Background work does not draw. It changes state and calls `terminal.live.nudge()`, which wakes the loop for a repaint from any thread.
- A failure is a fallback and a log line. Nothing reaches stderr in normal use but a sentence for the user. See [Diagnostics](#diagnostics).
- Only a `main` ends the run. Anything below it raises `_log.UserError`, and `tests/test_layers.py` checks that too.
- Words are data. The strings are in `locales/`, and a test keeps code out of those files.
- A view lays out text in logical order, first letter first. Right-to-left text is put in display order once, at the end.
- Fields are half-blocks and lines are braille. The sea, terrain and the Moon's glow are fields; coastlines, borders and the tide curve are lines.

## Inside a command

Each command is a package, and the same file names mean the same thing in each.

| File | What it holds |
| --- | --- |
| `view.py` | The command: `main()`, and the function that renders one frame from data it is given |
| `live.py` | The live app, its state and its keys |
| `i18n.py` | The command's strings, read from `locales/`, and the grammar around them |
| `json.py` | The `--json` payload |
| `oneline.py` | The `--oneline` summary |
| `palette.py` | The inks, built again when the terminal's theme changes |
| `__main__.py` | Lets `python -m linecast.weather` run the command from a checkout |

The modules beside these fetch, decode and paint. Radar and maps have no `--json` or `--oneline`. Weather keeps its inks in `style.py`, and maps in `paint.py` and `style.py`.

`live.py` draws through `view.py`, so `view.py` does not import it at the top. In weather, tides, radar and maps the `main()` in `view.py` hands off to the one in `live.py`.

## What the commands share

### The live loop

`terminal.live.live_loop()` runs every live view. It puts the terminal on the alternate screen, turns on mouse reporting, calls a render function whenever something happens (a key, a wheel notch, a drag, a resize, a timer, a nudge from a background thread), and writes the frame.

A view with state subclasses `terminal.live.LiveApp`, and there is one for each command: `WeatherApp`, `SunshineApp`, `MoonApp`, `SkyApp`, `TidesApp`, `RadarApp` and `MapApp`. The loop's hooks are its methods: `render`, `on_action` for single keys, `on_wheel`, `on_drag`, `on_click`, `intercept` for a panel that wants every key, `text_mode` while a text field is open, and `play_gate` for animations. The loop's tuning is its class attributes: `interval`, `mouse`, `scroll_step`, `auto_play`, `play_interval`. A hook the subclass does not override is not handed to the loop, so the loop's defaults stand: without `on_wheel` the wheel scrubs time, and without `on_drag` there are no clicks.

A frame is a string. Anything that floats over it, a tooltip or a modal or a search field, is appended with `terminal.live.overlay()`, which the loop draws after the body, where clearing lines cannot touch it. A toast in the corner says that something is on its way: `LiveApp.flash(..., busy=True)` keeps one up until `clear_flash()`, and `LiveApp.busy_toast` draws one for as long as each frame asks for it.

The loop paces itself to the terminal. Each frame goes out with a cursor position query after it, and the next is held until the reply comes back, so a slow terminal gets fewer frames rather than a backlog. `FramePainter` writes only the rows that changed. A view in motion starts a `terminal.live.Ticker`, a thread that wakes the loop thirty times a second while something moves and ends when it stops. The map's camera, the sky's, and the Moon's disc each run one.

Around the loop:

- `terminal/keys.py` — what the bytes a terminal sends mean. `KEYS` is every key a view answers to outside a text field, so a key a view handles and its help lists goes there too.
- `terminal/keylayouts.py` — keys typed under a non-Latin keyboard layout, read as the Latin keys they sit on.
- `terminal/term.py` — raw input, the wakeup and the resize notice, for POSIX and Windows.
- `terminal/help.py` — the shared `?` panel, with its descriptions in the locale files' `HELP` tables. A `LiveApp` names its `help_view`, and may add rows before the keys with `help_rows()` and credits after them with `help_credits()`.

### Drawing

- `terminal/framebuffer.py` — color fields at two sub-pixels per cell, with half-block characters.
- `terminal/braille.py` — curves and strokes at 2×4 dots per cell.
- `terminal/color.py` — RGB into escape codes for what the terminal supports: truecolor, 256, 16 or none.
- `terminal/theme.py` — asks the terminal for its own colors and builds every palette from them, with a stock palette when it does not answer. When the theme changes under a live view, the palettes are built again.
- `terminal/textwidth.py` — how many cells a string takes, and fitting and padding text by them.
- `terminal/box.py` — where a floating panel goes: help, the menus, the toasts, the search panels and the alert modal.
- `terminal/composition.py` — a hover chip's drop shadow, blended last with whatever the finished frame shows under it.
- `terminal/chart.py`, `terminal/heading.py`, `terminal/month_layout.py` — what weather's and tides' charts share: the hour ticks, the month axis, the headings and the spacing.
- `terminal/glyphs.py` — the sun and moon glyphs of each icon set.
- `terminal/oneline.py`, `terminal/spinner.py` — how a one-line summary is written, and the busy line while a run waits on the network.

### Right-to-left text

`terminal/bidi.py` turns each row of a frame, each piece of an overlay, `--print` and `--oneline` into display order just before it is written. It orders each stretch of text by the Unicode Bidirectional Algorithm (`terminal/uba.py`), joins Arabic-script letters into their presentation forms (`terminal/shaping.py`), and writes a language's own digits. It moves cells but never adds or removes one, so the layout the view measured holds. A row with no right-to-left text passes through untouched.

In a right-to-left language a view can ask to be laid out from the right with `terminal.bidi.set_mirror`. The pass then mirrors each row, and the live loop mirrors the pointer and the arrow keys to match, so no view needs a right-to-left layout of its own.

A few terminals order text themselves. linecast knows them by name, and there the pass hands right-to-left text over in logical order for the terminal to arrange. The docstring in `terminal/bidi.py` has the particulars.

### What a view keeps

Everything a live view paints from was fetched on some earlier repaint or in the background. `terminal/scenes.py` holds the two ways of keeping it.

- A `Memo` is a small bounded dictionary that answers or builds on the calling thread and forgets its oldest entries: basemaps, place names, shaded terrain buffers, route layers.
- A `SceneCache` holds a view's worth of fetched data: an elevation grid, a street layer, a radar field. Asked to block, it loads on the calling thread. Live, a miss starts one background load for that key, answers an empty value so the frame can say "loading", and nudges the loop when the data lands.

A `FetchHold` can gate a `SceneCache`, so a run of zoom taps repaints at once but only the view you stop on reaches the network. Radar's frames have a cache of their own in `radar/frames.py`, because they are fetched ahead in a set order.

### Strings

The strings are in `locales/`, one file per language. A regional variant's file, such as `pt_PT.py`, holds only the words that differ from its base. Each file is data alone, a name in capitals for each table (`WEATHER`, `MONTHS`, `SKY_CULTURES`) set to a literal, so a translator can edit it without reading the code.

A command reads its table through `_i18n.LocaleTable("WEATHER")`, which imports a language's file the first time it is asked for, so a run in French loads French and English alone. `_i18n.lookup` falls back from a variant to its base language, then to English.

Each file's `SETTINGS` says how the language writes numbers, percentages and durations, which plural rule it takes, whether it runs right to left, and which calendar, hours and sky follow it. `_i18n.setting(lang, name)` reads one.

What is logic rather than words stays in Python: the plural rules, French elision, the precipitation nouns' agreement, the calendars' numerals. CONTRIBUTING.md says how to add or correct a language.

### Settings

Each saved setting is declared once, as a record in `_config.SETTINGS`: its name, which is both its command and its key in `config.json`, its choices, the environment variable that overrides the saved value, its line on the help page, and how a value is spelled. The help page, the dispatch in `__main__.py`, the completions, the flags' choices, the resolvers and doctor all read it from there. A new setting is one more record and its module in `settings/`. `settings/_command.py` holds what those modules share.

Every resolver takes the same order: the flag, then the variable, then the saved setting, then the default. `_config.chosen` is the middle two. Most resolvers are in `_runtime.py`. The calendar's, the hours' and the sky culture's are beside their subjects: `astro.calendars.lunisolar.resolve_calendar`, `astro.hours.resolve_hours` and `sky.catalogue.resolve_culture`.

### Files on disk

`_paths.py` decides the two roots, and reads the environment each time it is asked, so a test or a wrapper can move them. The cache root is `LINECAST_CACHE_DIR`, else `$XDG_CACHE_HOME/linecast`, else `~/.cache/linecast`, or `~/Library/Caches/linecast` on macOS. The config root is `LINECAST_CONFIG_DIR`, else `$XDG_CONFIG_HOME/linecast`, else `~/.config/linecast` on every platform.

Under the config root are `config.json`, which `_config.py` reads and writes, and `locations.json`, the recent places in the weather and tides location menu.

`_cache.py` writes JSON and bytes under the cache root, with a maximum age per file. Within that age a file is read instead of the network. Past it, when the network fails, it is read as a stale copy, which is how the views keep working offline. `_http.fetch_json_cached` does both. A file for a place is named with `_cache.location_cache_key`, the coordinates to four decimal places.

The cache root holds:

- `weather/`, `tides/`, `radar/` and `maps/`, a folder for each command that fetches, and `marine/` for the sea forecast under the tide chart.
- `location.json`, the lookup of where you are by your address on the network.
- `timezone_{key}.json`, one for each place whose zone was looked up.
- `basemap_{python}_{mtime}.marshal`, the Natural Earth basemap parsed once for radar and maps.
- `prose/`, the developer bench's fixtures, which only `linecast prose rm` deletes.

`_cache.sweep` runs once a day, when a view command starts, and deletes what has gone unused for longer than its table allows that kind of file. `maps/` is kept under a size instead, 256 MB unless `LINECAST_MAPS_CACHE_MB` says otherwise, least recently used first (`maps/tile_cache.py`). Clearing the cache by hand is always safe: what is missing is fetched again.

### The network

`_http.py` keeps one connection per host per thread, attaches the user agent, and follows redirects. One thing goes around it: the Bureau of Meteorology's warnings are published only over FTP, and `weather/alert_feeds/bom.py` reads them with `ftplib`.

Every command uses these:

- `_location.py` — a rough location from the network address when none is saved or given: ipinfo.io, with ipwho.is and GeoJS as fallbacks.
- `_geocode.py` — Nominatim names a place from its coordinates, and the Open-Meteo geocoder turns a name into coordinates, with Photon as a fallback.
- `_rate_limit.py` — spaces the requests to a provider across threads.
- `_fanout.py` — fetches run side by side, on threads that never hold up the exit.

Each command's own providers are listed with the command below. The sky asks the network only for the location and its name; everything it draws is computed or bundled.

The public signatures of the modules that fetch carry type annotations. The rest of the package mostly does not, by choice.

### Diagnostics

A provider, cache or decoder that fails returns its documented fallback (a stale copy, an empty layer, None) and calls `_log.log_failure`. That prints one line naming the provider, the operation, the host, the exception and the fallback, and prints nothing unless `--debug` is on. A `--debug` transcript starts with the version, the Python, the platform and where the cache and settings live, then lists every fallback taken. URLs in it go through `_log.redact_url`, which drops the query string.

Failures are caught in two tiers. A provider absorbs what the network can be expected to do to it: a timeout, a refused connection, an error status, an answer it cannot parse, a missing key, a spent quota. Each comes back as the fallback. Anything else a provider raises is a bug, and whatever asked for it catches it, logs it with its traceback, and answers with the fallback, so the bug costs the view that one entry. `_fanout.Fanout.settle` does this for fetches run side by side, the tide stations' chain passes over a provider that raised to the next, and `fetch_alerts` answers an alert service that raised as alerts that could not be checked.

When a run cannot go on (a place no geocoder knows, a settings file that will not take a write), the code that finds the trouble raises `_log.UserError`. The command's `main`, wrapped in `_log.exits_on_user_error`, prints the message on stderr and exits with status 1. Nothing below the mains ends the process, since in a worker thread that would end only the thread.

One line prints without `--debug`: the notice after a live session in which a background thread crashed. `terminal.live.WorkerWatch` catches the crash and reports it once the terminal is restored.

`doctor.py` collects the same facts on demand and probes the provider hosts: every one a command asks, and, of the alert services, the one for the user's own country.

### Astronomy

`astro/ephemeris.py` computes where the Sun and Moon are: positions, phases, and the rise and set times that follow. Its `sunrise_sunset` is the app's one sunrise. The sunshine views, the weather's forecast, the tides' night shading, the month views and the traditional hours all read it, so no two views disagree about when the Sun comes up.

- `astro/seasons.py` — the equinoxes, the solstices and the traditional full-moon names.
- `astro/hours/` — the day read in a tradition's hours. The `__init__` is the model: a `DayHours` is one civil date read in one system, with the two edges the Sun sets, the count of equal hours between them and the named marks along the day, and `reading` says which hour a moment falls in. Each tradition is a module that fills the model in: `zmanim.py`, `roman.py`, `wadokei.py`, `swahili.py` and `prayer_times.py`.
- `astro/calendars/` — the traditional calendars, one module each, each answering what this civil date is in that calendar and what comes next: `lunisolar.py` (Chinese, Japanese, Korean and Vietnamese), `thai_lunar.py`, `pacific.py`, `hijri.py`, `hebrew.py` and `icelandic.py`. `civil.py` is the calendar the app writes its dates in: Gregorian, except in Persian, where it is Iran's Solar Hijri (`solar_hijri.py`).

[hours.md](hours.md) and [calendars.md](calendars.md) say how each is computed and what it was checked against.

## The commands

### Weather

Weather's data is the forecast as Open-Meteo sends it, a dict with its `current`, `hourly` and `daily` blocks. Nothing is copied out of it into a model of linecast's own, and the modules that add to it write into the same dict: `forecast.py` writes the app's sunrise and sunset into `daily`, `observed.py` writes a nearby airport's sky into `current`, and `humidex.py` adds Canada's humidex and wind chill. The dashboard, the year view and `--json` all read from it.

`gather` in `live.py` fetches everything the dashboard is drawn from, side by side, for the live view and a one-shot run alike.

What it draws:

- `view.py` — lays out the dashboard.
- `header.py` — the conditions line at the top.
- `hourly.py` — the hourly chart. `day_chart.py` is the hover graph on a daily bar.
- `narrative.py` — the prose under the graph.
- `daily.py` — the daily rows.
- `alerts.py` — the alerts and their modal.
- `credits.py` — the credit lines for the forecast, the sky and the alerts.
- `month.py`, `year.py` — the month and year views.
- `style.py` — the inks. `cover.py` names the sky's cover and the kinds of precipitation.

What it fetches:

- `forecast.py`, `air.py`, `historical.py`, `hourly_history.py` — Open-Meteo's forecast, air quality and archive. `air.py` also reads Environment Canada's air quality health index.
- `observed.py` — the Aviation Weather Center's airport reports, which correct the forecast's current sky and give the last day's precipitation.
- `alert_feeds/` — the alert services, a module each: the US National Weather Service, Environment Canada, MeteoAlarm for most of Europe, and other national services. `fetch_alerts` and `ALERT_FEEDS`, the table that routes a country to its service, are in the package's `__init__`.

The location menu is `locations.py`, the recent places and the search, and `location_menu.py`, what a live view does with them. Tides uses both.

`prose.py`, at the top level, is a bench for the forecast in words, hidden from the command list.

### Sunshine

- `view.py` — the day's arc. `year.py` is the year view, and `live.py` the keys between them.
- `solar.py` — the Sun's height and its rising and setting, from `astro.ephemeris`, in the decimal hours the views plot.
- `hours.py` — paints the traditional hours: the reading in the day view's corner and the marks on a line under the chart. `json.py` puts the same facts in an `hours` block.
- `palette.py` — the sky inks and gradients. Other commands that draw a sky borrow them.

### Moon

- `view.py` — the phase panel. `calendar.py` is the month grid you get by pressing `v`.
- `phase.py` — the Moon's facts: the phase and its name, how much is lit, its next rise and set, the next new and full moon. Other commands take these from here.
- `disc.py` — the Moon's disc, and the drag that turns it. `palette.py` holds its inks, and `stars.py` the stars about it.
- `readings/` — what the command says of a traditional calendar. The `__init__` holds `Reading`, the questions every part of the command asks a calendar (the headline, what the panel counts down to, the `--json` block, a day's cell in the month grid and its hover chip), and `Ctx`, the moment and place they are asked at. A module each answers them for one calendar, and `reading(cal)` finds it.

The calendars' arithmetic is in `astro/calendars/` and their words in `moon/i18n.py`. The almanac has no module in `astro/calendars/`: its advice is strings in the locale files' `MOON` tables, and its full-moon names come from `astro/seasons.py`.

### Sky

`view.py` draws the frame and `live.py` holds the camera and the keys. `scene.py` is the geometry both work from: `Scene`, where everything is at one moment, the projection both ways, and `point_up`, whether a star or a planet has risen. The `--json`, the one-line summary and the search read the scene without loading the renderer.

- `planets.py` — where the planets are.
- `catalogue.py` — the bundled stars, their names, the constellation figures and the Milky Way, all in J2000. `Scene.catalogue` folds in the precession to the equinox of date, so the stars land beside the planets. The sky cultures are here too: `culture()` prepares one, and `figures_for` and `names_for` give its constellations and star names in a display language.
- `deep.py` — the fainter stars, decoded a region at a time when the zoom needs them.
- `objects.py` — the Messier objects, painted behind the stars.
- `asterisms.py` — the asterisms, each a list of star designations placed from the catalogue.
- `search.py` — the `/` panel. `picker.py` is the tradition picker on `t`.
- `palette.py` — the sky view's own inks.

Sources and licenses are in `data/STARS.md`, and [cultures.md](cultures.md) has the credits the cultures' licenses require.

### Tides

`view.py` lays out the day chart from the parts in `chart.py`. The longer views are a module each: `month.py`, `year.py`, and `makeup.py`, what moves the tide at the place. `live.py` steps through them with `v`, fetches the one on screen on a worker, and keeps what it has fetched for the session.

- `stations.py` — picks the station for a place, the country's own service first and Open-Meteo's global model last, reads its name and time zone, fetches what the chart needs side by side, and searches every provider's stations for `--station`, `--search` and `--nearby`.
- `providers.py` — one `TideProvider` for each source, and the registry `stations.py` routes by.
- `noaa.py`, `chs.py`, `qld.py`, `hko.py`, `jma.py`, `kartverket.py`, `tidecheck.py`, `openmeteo.py` — NOAA CO-OPS, the Canadian Hydrographic Service, Queensland's open data, the Hong Kong Observatory, the Japan Meteorological Agency, Kartverket, TideCheck (which needs `LINECAST_TIDECHECK_KEY`) and Open-Meteo.
- `ticon.py` — the TICON-4 gauges bundled in `data/ticon.json.gz`, predicted here from their constants.
- `harmonic.py` — the tide machine that adds up harmonic constants, and fits them to a year of a model or of a station's highs and lows.
- `common.py` — what the providers share: the cache folder, the nearest-station search, the chart's height range.
- `marine.py` — Open-Meteo's marine forecast, for the sea under the chart.

### Radar

- `view.py`, `live.py` — the frame and the app.
- `sources.py` — picks the frame source by location: LibreWXR first, then IEM's NEXRAD composites over the continental US and RainViewer elsewhere. `iem.py` and `tiles.py` fetch the frames, and `ub.py` reads RainViewer's Universal Blue tiles back to reflectivity.
- `frames.py` — the frame cache and prefetcher. Frames are fetched ahead in a set order, the displayed one first, and the animation waits on a fraction of them.
- `render.py` — the compositor.
- `basemap.py` — the Natural Earth geography in braille: the borders, lakes and cities in `load_data`, and the `DotLayer` strokes are drawn into. Maps builds on it.
- `layers.py` — the temperature and wind lattice, from Open-Meteo. `warnings.py` is the warning polygons.
- `palettes.py` — the color ramps. `ui.py` holds the overlays and footer pieces the live view draws.

Radar and maps share `_xyz.py`, the slippy-map arithmetic: the window a view covers (`bbox_for`), the Web Mercator tile projection and zoom, the stitch of tiles into one canvas, and the thread pools that fetch them.

### Maps

Maps is the largest command and the one with the most moving parts. `view.py` draws, `live.py` runs the app and holds the camera, and `loaders.py` fetches, builds and keeps what a view is made of.

There are two registers, street and terrain, which `v` switches between. Close in, from `style.ROADS_BAND`, terrain carries the street register's lines and names over its own ground.

Both registers have one geometry at every zoom. `globe.py` inverts the same orthographic projection for a window a valley wide as for the whole planet. Close in, where the flat box rasterizer gives the same picture, it is the one that runs (`affine_ok`). Far out, past `local_tiles`, the tile sources cannot be asked at all, and the window is filled from `globe_texture.py`: the whole planet baked once into a texture, so a frame is a lookup per sample. The bake takes a second or two, so a live view runs it on a thread, and the texture is kept on disk.

The map's center and zoom are a camera. `maps.live.Camera` holds them and whatever motion they are in: a zoom easing, a coast after a flick, a keyed pan, a flight to a search result, the planet turning. `motion.py` is the arithmetic a motion follows, the easing and the flight path.

A globe frame is cheap and is drawn for real every time. A flat view takes a second or more to build, so four things stand between the camera and the build:

- The margin. A flat view is built an eighth of the window wider on each side, and a frame is a crop of it (`overscan.py`). A pan inside the margin is the real map at the new offset and asks for nothing. A built view hangs from an eye, the point its plane is projected about, so that every window on that plane is an exact crop. Where two views do not share an eye, the frame the camera comes to rest on is resampled (`overscan.Resample`).
- Stand-in frames. Past the margin a new window is a fetch, and the frames in between are the last real view moved and scaled (`reproject.py`). Labels and hover wait for the real thing.
- The destination first. Where the camera will stop is built as soon as it is known, a coast's at the release and a flight's from the descent, one at a time (`view.prefetch_view`, `loaders.fetch_destination`).
- A second interpreter. A build on the frame loop's interpreter takes the frames from thirty a second to three, so `worker.py` starts a child when the map runs and hands it every flat build. `loaders._build` is the one door, and builds in-process when there is no child: `--print`, a platform that cannot spawn, a child that has died. `LINECAST_MAPS_WORKER=0` keeps every build in-process, and the test suite sets it.

Names come from two places. `places.py` names the cities in both registers from the Natural Earth gazetteer, so the same names show either side of the hand-off to the globe. From `style.GAZETTEER_BAND` the street register takes its places from the vector tiles instead. `labels.py` places the street register's other labels, and carries what it placed from one build to the next, so a pan moves no name.

The rest, by what it does:

- `streets.py` — rasterizes the vector tiles into the street register. `style.py` is the cartography as plain data.
- `paint.py` — terrain's inks and the composers.
- `hover.py` — what the pointer is over. `ui.py` is the search and directions panels.
- `vtiles.py` — OpenFreeMap's vector tiles, with the OpenStreetMap US Tileservice as a fallback, decoded by `mvt.py`.
- `elevation.py` — the AWS terrain tiles. `builtup.py` is the optional built-up raster.
- `search.py` — Photon and Nominatim. `route.py` is OSRM.
- `globe_now.py` — daylight and the cloud mosaic. `night_lights.py` is the lights on the night side.
- `climate.py`, `glaciers.py` — the bundled grids that pick terrain's colors and paint its ice.
- `tile_cache.py` — keeps the tile cache under its size.

`scripts/bench_maps_live.py` drives the whole loop in a pty, and `scripts/bench_maps_frames.py` times a single frame.

## Bundled data

The data that ships with the package is under `data/`. Each file has a script in `scripts/` that bakes it and a module that reads it.

| File | Read by | Baked by |
| --- | --- | --- |
| `basemap.json.gz` | `radar/basemap.py` | `build_basemap_data.py` |
| `stars.bin`, `sky.json.gz`, `milkyway.bin.gz`, `cultures.json.gz` | `sky/catalogue.py` | `build_sky_catalogue.py` |
| `stars-deep.bin.gz` | `sky/deep.py` | `build_deep_stars.py` |
| `sky-objects.json.gz` | `sky/objects.py` | `build_sky_objects.py` |
| `moon_albedo.png` | `moon/disc.py` | `build_moon_albedo.py` |
| `ticon.json.gz` | `tides/ticon.py` | `build_ticon_stations.py` |
| `meteoalarm_regions.bin.gz` | `weather/alert_feeds/meteoalarm_regions.py` | `build_meteoalarm_regions.py` |
| `climate.png` | `maps/climate.py` | `build_climate_grid.py` |
| `glaciers.png` | `maps/glaciers.py` | `build_glacier_grid.py` |
| `night_lights.bin` | `maps/night_lights.py` | `build_night_lights.py` |
| `globe_canvas_1.bin`, `globe_canvas_2.bin` | `maps/globe.py` | `build_globe_canvas.py` |

## Names that look alike

- Location. `_location.py` resolves where a view is for. `_geocode.py` turns names into places and places into names. `settings/location.py` is the `linecast location` command. `weather/locations.py` is the recent places menu.
- Camera. `maps.live.Camera` is where the map looks and how it is moving. `maps.globe.Camera` is the projection of one window. `sky.live.Camera` is the sky's.
- Hours. `astro/hours/` is the model, `sunshine/hours.py` paints it, and `settings/hours.py` is the `linecast hours` command.
- Calendar. `astro/calendars/` is the arithmetic, `moon/readings/` is what the moon says of each, `moon/calendar.py` is the month grid, and `settings/calendar.py` is the `linecast calendar` command.
- Style. `maps/style.py` is cartography as data and `weather/style.py` is weather's inks. `radar/palettes.py` is the radar's color ramps, where another command's `palette.py` is its inks.

## Tests

The tests are in `tests/`, each file named for what it covers. `tests/conftest.py` gives the suite a private home and switches the network off. The render tests compare each view against a snapshot in `tests/snapshots`. CONTRIBUTING.md says how to run them.
