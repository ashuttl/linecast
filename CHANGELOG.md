# Changelog

Notable changes, by release. Notes for the next release collect under
**Unreleased** and get a final edit when `release.sh` runs.

## Unreleased

- Maps: the globe no longer sticks on its loading frame. A background
  fetch that finished while the first frame was still being composed
  had its repaint nudge thrown away, so the finished globe sat in the
  cache until the next keypress. The nudge now survives.
- Maps: the first frame arrives in about a second and a half instead
  of five or more. The pure-Python PNG decoder gained C-speed paths
  for its hot loops, and the globe's stitched world canvas is baked to
  the cache directory after its first assembly, so later launches skip
  the tile decoding entirely.
- Radar and maps launch faster. The vendored geography parses through
  a marshal cache (0.3s → 0.08s), radar's rasterised land/sea grids
  are cached per view (0.6s → milliseconds on the second launch), a
  bounding-box test spares the water-name lookup its full ray-casting
  pass, and the version lookup no longer taxes every command's start.
  What remains of radar's launch is fetching the radar itself.
- Maps: the globe's two common world canvases now ship in the package
  (2.5 MB, baked at release time by scripts/build_globe_canvas.py), so
  a fresh install draws its first globe with no network at all. The
  largest size — very tall terminals only — still stitches once
  locally and is cached.
- Maps: terrain colour now knows the climate, not just the elevation.
  A vendored Köppen-Geiger grid (Beck et al. 2023, 67 KB in the
  package) picks between four hypsometric ramps — humid, steppe,
  desert, tundra — so the low Sahara reads as sand instead of meadow
  and the dry Tibetan Plateau as stone instead of snow. Works
  offline; applies to the terrain view and the globe.
- Maps: `l` now hides the linework along with the labels — national
  borders, coastlines, and rivers — in the terrain view and on the
  globe, leaving the bare planet. Street mode's lines are part of the
  map itself and stay.
- Maps: with the sun on, the globe's atmosphere glow now follows it.
  The blue rim is scattered sunlight, so it fades through the same
  twilight band as the ground beside it; the night limb keeps only a
  thin trace of airglow green.

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
