# Changelog

Notable changes, by release. Notes for the next release collect under **Unreleased** and get a final edit when `release.sh` runs.

## Unreleased

- Sunshine: A year view (`--year`) draws a column of sky for each day of the year, sunrise and sunset appearing as the edge between night and day. A marker shows the current day and time; scrolling moves a cursor through the calendar, with that day's sunrise, sunset, and day length below.

## 2.1.0 — 2026-08-28

New this version:

- Moon: The disc now shows the real lunar surface, from NASA's Lunar Reconnaissance Orbiter imagery, instead of a sketch of the maria.
- Moon: The star field is drawn with a mix of star shapes at varied brightness, so the sky reads as stars of different magnitudes rather than a scatter of identical blocks.
- Moon: Moonrise and moonset lead with how long until they happen, with the clock time after — "Moonrise in 6h 29m (20:59)". A time on a later day is named inside the same parentheses.
- Moon: When the Moon is up, the line that gives its altitude now also names the compass direction to look in. `--json` gains `azimuth_deg` alongside `altitude_deg`.
- Maps: The globe draws inland water. The Great Lakes, the Caspian, Baikal and every other lake big enough to see are water at planet zoom, in the terrain view and the street one, with a shoreline to match.
- Maps: City lights were only ever intended for the terrain view. The street view no longer lights its cities, flat or on the globe; its fills stay a little brighter at night to make up for it.
- Maps: Better style consistency between street maps in flat mode and globe mode.
- Maps: With sunlight and shadows on, street map coastlines and roads dim on the night side.
- Maps: The map tile cache no longer grows without limit. Tiles left behind by a superseded edition of the map are dropped and the rest kept under 256 MB, the tiles you haven't looked at in longest going first; `LINECAST_MAPS_CACHE_MB` sets another size, and `linecast doctor` shows what the tiles are using.

Fixes:

- Maps: Near the poles, as you zoom out, the map switches to the globe sooner. Flat maps of Antarctica used to run off the edge of the world.
- Weather: A severe European alert now shows only where it applies. A MeteoAlarm feed covers a whole country, so a flood warning for a single river gauge was reaching everyone in it.
- Weather: The daily forecast keeps its rows on one line in Japanese, Chinese, and Korean. The rain and wind columns were measured by character count, so double-width labels pushed the last rows past the edge of the terminal.
- Tides: The header names the place instead of printing its coordinates. Somewhere the global tide model covers, with no station nearby, a tide table for the wrong hemisphere used to look like a tide table.
- Live views: Taking a screenshot with cmd-ctrl-shift-4 on a Mac no longer kills the view and leaves the shell echoing mouse movements. Ctrl-\ now quits cleanly as well.

## 2.0.0 — 2026-08-26

linecast 2.0 runs on Windows, installs a single `linecast` command, and picks its defaults from your location. Upgrading from 1.x, four things change unless you say otherwise; each has a one-line fix below.

Major changes this version:

- Windows: linecast now runs in Windows Terminal. Windows installs `tzdata` and `truststore`; macOS and Linux remain dependency-free.
- Install (breaking): The six short commands (`weather`, `sunshine`, `moon`, `tides`, `radar`, `maps`) are no longer installed, because their names collide with other programs. Use `linecast <command>`, or run `linecast link` once to put the six names back as links to the `linecast` binary (it skips any name something else owns; `--remove` undoes it). A shell alias works too.
- Units: Metric is now the default everywhere except the United States, going by the saved location or the machine's IP. `linecast units metric|imperial|auto` saves a choice, `LINECAST_UNITS` and `--metric`/`--imperial` override it per run, and radar and maps follow the same setting instead of guessing from the interface language.
- Clock: The default follows the country instead of the interface language: 12-hour in the United States, Canada, Australia and the other places that write 6:50 pm, 24-hour everywhere else. A French speaker in the US now gets 12-hour; an English speaker in France, 24-hour. `linecast clock 12|24|auto` saves a choice, `LINECAST_CLOCK` and `--12h`/`--24h` override it per run, and sunshine follows the same preference as the other views.
- Icons: linecast no longer assumes a Nerd Font. Terminals known to bundle its glyphs use them, other interactive terminals use emoji, and piped output uses plain Unicode. `linecast icons nerd` restores the full set for a terminal whose font linecast cannot see; `--icons nerd|emoji|plain` and `LINECAST_ICONS` choose per run, and `linecast doctor` previews all three.

Other changes:

- Settings: `linecast units`, `linecast clock` and `linecast icons` now say which setting is in force and where it came from.
- Cache and settings: JSON is read as UTF-8 on every platform. A saved location or cached response with a non-ASCII name no longer appears lost on Windows.
- Drawing: Emoji in alerts and map labels wrap at their real display width. Sunshine and moon no longer get colored rings on 256- or 16-color terminals, and sunrise and sunset use plain arrows in every icon set.
- Moon: The full-screen layout follows the terminal. A wide window floats the details beside a taller moon; a small one shortens or drops lines before they can wrap, and every size fills the screen while keeping stars out from under the text.
- Moon: The next full moon is given its traditional Almanac name — Harvest Moon, Wolf Moon, Blue Moon and the rest. The last line gives the day of the year and counts down to the next equinox or solstice; `--json` has the same fields.
- Tides: Queensland stations now show the future. Maritime Safety Queensland's predicted datasets cover the whole calendar year, replacing the monitoring feed that ended at the present and left the curve flat. Coverage grows from about two dozen sites to nearly eighty gauges; a saved station from before resolves to the nearest new gauge.
- Tides: The footer names the station's data source — NOAA, CHS, Queensland Open Data, Hong Kong Observatory, TideCheck, or Open-Meteo's tide model — and the location pill drops its "(model)" suffix. The header and marine line fit correctly with emoji, and an unfamiliar timezone shows its UTC offset instead of plain UTC.
- Tides: `--station` and `TIDE_STATION` accept a TideCheck station ID such as `fes2022-lisbon` without spending a search request. `linecast tides --nearby`, `--search`, and `linecast doctor` show how many of the day's 50 free-tier requests have been used; `LINECAST_TIDECHECK_PAID=1` hides the tally.

## 1.17.0 — 2026-08-25

- Tides: Hong Kong has its own tide stations now. Thirteen Hong Kong Observatory stations join the list, picked automatically for a location in Hong Kong or by code with `--station CCH`. Thanks to ErwinTATP.
- Weather: Alerts in Hong Kong come from the Hong Kong Observatory's warnings -- rainstorm, tropical cyclone signals, thunderstorm and the rest -- instead of the mainland service. Thanks to ErwinTATP.
- Doctor: `linecast doctor` shows which build is running, where the settings file and the cache live and whether the cache can be written, what the terminal supports, which preferences are in force and where each came from, and whether every provider answers. `--json` prints the same report for a bug report; `--offline` skips the probes.
- Debug: `--debug` now reports every fallback a command takes -- a provider that did not answer, a cache file that could not be read, a tile that would not decode -- as one line naming the provider, the host and what was shown instead. URLs in the debug output are reduced to scheme, host and path; the query string is never printed. The same redaction applies to URLs quoted by an exception or traceback.
- Live: A background task that crashes under a live view no longer scrawls a traceback across the screen. One line after the view closes says it happened; `--debug` prints the traceback in full. A failed request in `weather` or `tides` now shows what did arrive instead of ending the command with a traceback.
- Installer: The `curl | sh` quick start with no arguments works again on Debian and Ubuntu, where the script had been exiting without running anything.
- Installer: When nothing but `python3` is available, `get.sh` keeps its environment in a private per-user directory instead of a shared path under `/tmp`, and picks up new releases once a day.
- Cache: On macOS the cache now lives in `~/Library/Caches/linecast`; an existing `~/.cache/linecast` stays in use. `LINECAST_CACHE_DIR` and `LINECAST_CONFIG_DIR` put the cache and the settings file wherever you like, and `XDG_CACHE_HOME` is honored.
- Cache: A cache directory that cannot be written or read no longer stops a command; the data is fetched and shown without being kept. `linecast units` and `linecast location` say in one line when the settings file cannot be saved, instead of printing a traceback.
- Weather: In live mode, `o` opens the alert on screen. After the view refreshed its alerts it could open the wrong one, or none.
- Plumbing: A map of the code for contributors in ARCHITECTURE.md, a lint check in CI, and type annotations on the modules that talk to the network. The live views share one model now; nothing changes on screen. Python 3.14 is tested, and a release ships the exact wheel that CI installed and smoke-tested.

## 1.16.1 — 2026-08-24

- Plumbing: Fix for a failing macOS test

## 1.16.0 — 2026-08-24

- Security (also released as 1.15.2): every network response is read in chunks against a hard size cap (8 MiB for JSON, 16 MiB otherwise), refused early when the declared Content-Length is oversized, and gzipped vector tiles decompress against the same cap. A broken or hostile server can no longer balloon linecast's memory or its emitted output.

- Maps: Fixed a bug that could have caused rendering the globe to fail until the user interacted with it.
- Maps: The globe's first frame draws in about a second and a half instead of five or more.
- Maps: A fresh install draws its first globe without a network connection.
- Radar and maps launch faster.
- Maps: Terrain color accounts for climate as well as elevation, using the Köppen-Geiger classification, so deserts read as sand and dry plateaus as stone. Applies to the terrain view and the globe.
- Maps: `l` hides borders, coastlines, and rivers along with the labels, in the terrain view and on the globe.
- Maps: With the sun on, the globe's atmosphere glow fades into night along with the ground beside it.
- Weather: The climate archive behind the above-or-below-average note is downloaded once a week instead of once a day.
- Weather: In live mode, a failed air-quality or climate-average fetch no longer retries the network on every mouse movement.
- Completions: The tides, sunshine, and moon completions now offer `--location`, tides also `--emoji`, and sunshine `--lang`. The scripts are generated from the commands' own option definitions, so they can't fall behind again.
- Completions: fish's `linecast completion` now offers nu and nushell, and the unknown-shell message lists them.
- Maps: Dragging and spinning the globe is more than twice as fast, and hovering over it no longer re-places its city labels on every repaint.
- Maps: Panning and zooming the terrain view is about three times faster, and a view on a cold cache no longer waits for each tile source in turn.
- Tides: Opening the tide chart is much faster the first time each day, and the cache directory stops gaining new files every day. Old per-day cache files left by earlier versions are cleaned up on the next run.
- Radar: The frame on screen is fetched before the rest of the animation window, so a fresh view fills in sooner.
- Radar: Local color themes draw faster, and switching between them no longer waits on the network.
- Radar: Refreshing the frame list happens in the background, so a slow connection can't pause playback.
- Requests to the same server reuse one connection instead of opening a fresh one each time, so tile pyramids and the forecast's several calls arrive sooner.
- Every command starts a little faster.
- Radar: Quitting the live view no longer waits for the rest of the animation window to download, and a one-shot render fetches only the frame it shows.
- Radar and maps: Fixed a bug where a download finishing as the view closed could corrupt a cached tile.
- Maps: Fixed a bug where dragging the globe could leave the view blank until the next repaint.

## 1.15.1 — 2026-08-23

- Maps: the cloud layer now covers the poles. The satellite mosaic ends near the 72nd parallels; poleward, Open-Meteo model cloud cover fills in, fading in where the mosaic fades out, so a pole-centered globe no longer shows a ring of falsely clear sky.

## 1.15.0 — 2026-08-22

- Live views follow the terminal theme: switch your terminal's colors while weather, radar, maps, sunshine, moon or tides is open and the view re-inks itself in the new palette, no restart. On Omarchy the switch is picked up at once; elsewhere within a couple of seconds.

## 1.14.0 — 2026-08-22

- Radar: five color themes drawn in linecast itself rather than on the tile server — `terminal`, now the default, draws rain in your terminal's own palette; `dusk`, `ember` and `ink` are ramps that adapt to a light or dark background; `marangai` follows MetService New Zealand's stepped bands. They read reflectivity from LibreWXR's grayscale scheme, so snow is colored separately. The theme picker lists these above the server's schemes.
- Radar: the footer says when the frames come from a precipitation model rather than radar — everywhere outside North America, Europe and a few East Asian networks.

- Sunshine: the solar arc is drawn in braille, and the horizon is a dotted braille hairline that dissolves into daylight — it shows only where the sky is dark. The half-blocks now render only the sky.
- Sunshine: once the sun is up, the glow centers on its height in the plot rather than staying at the horizon.

- README: a Lineage section. A videotex terminal draws the weather, sometime in the 1980s.
- Screenshots: the sunshine pair and the hero desktop, reshot with the braille arc.

- Quick try with nothing but curl: `curl -sL .../get.sh | sh` is in the README.
- get.sh: without a terminal to reclaim, fall back to `--print` instead of failing.

## 1.13.0 — 2026-08-20

- Nushell completions: `linecast completion nu`. The project's first outside contribution — thank you, @kurokirasama.
- A changelog. Release notes now ship with each tag and GitHub Release.

## 1.12.0 — 2026-08-20

- Tides: subordinate stations work, drawn from NOAA's high/low predictions, and are matched correctly when picking the nearest station.
- Tides: `--print` output no longer contains escape codes.
- Sunshine, moon, and tides honor the location flag and its clock.
- Weather: the fetch spinner gives up instead of spinning forever.
- Radar: cached frames older than a day are deleted.
- Live mode: signals and exit codes pass through cleanup.
- The COLUMNS and LINES environment variables are respected.
- Cache files are written atomically.
- Packaging: screenshots are no longer shipped in the sdist.
- CI: tests also run on Python 3.11 and macOS.

## 1.11.0 — 2026-08-19

- Units: a preferred unit system can be saved in the config file.
- README: a screenshot of the globe and a table of keys.
