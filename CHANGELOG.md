# Changelog

Notable changes, by release. Notes for the next release collect under
**Unreleased** and get a final edit when `release.sh` runs.

## Unreleased

- Debug: `--debug` now reports every fallback a command takes -- a
  provider that did not answer, a cache file that could not be read,
  a tile that would not decode -- as one line naming the provider,
  the host and what was shown instead. URLs in the debug output are
  reduced to scheme, host and path; the query string is never printed.
- Live: A background task that crashes under a live view no longer
  scrawls a traceback across the screen. One line after the view
  closes says it happened; `--debug` prints the traceback in full.
  A failed request in `weather` or `tides` now shows what did arrive
  instead of ending the command with a traceback.
- Installer: The `curl | sh` quick start with no arguments works again
  on Debian and Ubuntu, where the script had been exiting without running
  anything.
- Installer: When nothing but `python3` is available, `get.sh` keeps its
  environment in a private per-user directory instead of a shared path
  under `/tmp`, and picks up new releases once a day.
- Cache: On macOS the cache now lives in `~/Library/Caches/linecast`;
  an existing `~/.cache/linecast` stays in use. `LINECAST_CACHE_DIR`
  and `LINECAST_CONFIG_DIR` put the cache and the settings file
  wherever you like, and `XDG_CACHE_HOME` is honoured.
- Cache: A cache directory that cannot be written or read no longer
  stops a command; the data is fetched and shown without being kept.
  `linecast units` and `linecast location` say in one line when the
  settings file cannot be saved, instead of printing a traceback.
- Weather: In live mode, `o` opens the alert on screen. After the
  view refreshed its alerts it could open the wrong one, or none.
- Plumbing: A map of the code for contributors in ARCHITECTURE.md, a
  lint check in CI, and type annotations on the modules that talk to
  the network. The live views share one model now; nothing changes on
  screen. Python 3.14 is tested, and a release ships the exact wheel
  that CI installed and smoke-tested.

## 1.16.1 — 2026-08-24

- Plumbing: Fix for a failing macOS test

## 1.16.0 — 2026-08-24

- Security (also released as 1.15.2): every network response is read
  in chunks against a hard size cap (8 MiB for JSON, 16 MiB
  otherwise), refused early when the declared Content-Length is
  oversized, and gzipped vector tiles decompress against the same
  cap. A broken or hostile server can no longer balloon linecast's
  memory or its emitted output.

- Maps: Fixed a bug that could have caused rendering the globe to fail
  until the user interacted with it.
- Maps: The globe's first frame draws in about a second and a half
  instead of five or more.
- Maps: A fresh install draws its first globe without a network
  connection.
- Radar and maps launch faster.
- Maps: Terrain colour accounts for climate as well as elevation,
  using the Köppen-Geiger classification, so deserts read as sand and
  dry plateaus as stone. Applies to the terrain view and the globe.
- Maps: `l` hides borders, coastlines, and rivers along with the
  labels, in the terrain view and on the globe.
- Maps: With the sun on, the globe's atmosphere glow fades into night
  along with the ground beside it.
- Weather: The climate archive behind the above-or-below-average note
  is downloaded once a week instead of once a day.
- Weather: In live mode, a failed air-quality or climate-average fetch
  no longer retries the network on every mouse movement.
- Completions: The tides, sunshine, and moon completions now offer
  `--location`, tides also `--emoji`, and sunshine `--lang`. The
  scripts are generated from the commands' own option definitions, so
  they can't fall behind again.
- Completions: fish's `linecast completion` now offers nu and nushell,
  and the unknown-shell message lists them.
- Maps: Dragging and spinning the globe is more than twice as fast,
  and hovering over it no longer re-places its city labels on every
  repaint.
- Maps: Panning and zooming the terrain view is about three times
  faster, and a view on a cold cache no longer waits for each tile
  source in turn.
- Tides: Opening the tide chart is much faster the first time each
  day, and the cache directory stops gaining new files every day. Old
  per-day cache files left by earlier versions are cleaned up on the
  next run.
- Radar: The frame on screen is fetched before the rest of the
  animation window, so a fresh view fills in sooner.
- Radar: Local colour themes draw faster, and switching between them
  no longer waits on the network.
- Radar: Refreshing the frame list happens in the background, so a
  slow connection can't pause playback.
- Requests to the same server reuse one connection instead of opening
  a fresh one each time, so tile pyramids and the forecast's several
  calls arrive sooner.
- Every command starts a little faster.
- Radar: Quitting the live view no longer waits for the rest of the
  animation window to download, and a one-shot render fetches only the
  frame it shows.
- Radar and maps: Fixed a bug where a download finishing as the view
  closed could corrupt a cached tile.
- Maps: Fixed a bug where dragging the globe could leave the view
  blank until the next repaint.

## 1.15.1 — 2026-08-23

- Maps: the cloud layer now covers the poles. The satellite mosaic
  ends near the 72nd parallels; poleward, Open-Meteo model cloud
  cover fills in, fading in where the mosaic fades out, so a
  pole-centred globe no longer shows a ring of falsely clear sky.

## 1.15.0 — 2026-08-22

- Live views follow the terminal theme: switch your terminal's colours
  while weather, radar, maps, sunshine, moon or tides is open and the
  view re-inks itself in the new palette, no restart. On Omarchy the
  switch is picked up at once; elsewhere within a couple of seconds.

## 1.14.0 — 2026-08-22

- Radar: five colour themes drawn in linecast itself rather than on
  the tile server — `terminal`, now the default, draws rain in your
  terminal's own palette; `dusk`, `ember` and `ink` are ramps that
  adapt to a light or dark background; `marangai` follows MetService New
  Zealand's stepped bands. They read reflectivity from
  LibreWXR's grayscale scheme, so snow is coloured separately. The
  theme picker lists these above the server's schemes.
- Radar: the footer says when the frames come from a precipitation
  model rather than radar — everywhere outside North America, Europe
  and a few East Asian networks.

- Sunshine: the solar arc is drawn in braille, and the horizon is a
  dotted braille hairline that dissolves into daylight — it shows only
  where the sky is dark. The half-blocks now render only the sky.
- Sunshine: once the sun is up, the glow centers on its height in the
  plot rather than staying at the horizon.

- README: a Lineage section. A videotex terminal draws the weather,
  sometime in the 1980s.
- Screenshots: the sunshine pair and the hero desktop, reshot with
  the braille arc.

- Quick try with nothing but curl: `curl -sL .../get.sh | sh` is in
  the README.
- get.sh: without a terminal to reclaim, fall back to `--print`
  instead of failing.

## 1.13.0 — 2026-08-20

- Nushell completions: `linecast completion nu`. The project's first
  outside contribution — thank you, @kurokirasama.
- A changelog. Release notes now ship with each tag and GitHub
  Release.

## 1.12.0 — 2026-08-20

- Tides: subordinate stations work, drawn from NOAA's high/low
  predictions, and are matched correctly when picking the nearest
  station.
- Tides: `--print` output no longer carries escape codes.
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
