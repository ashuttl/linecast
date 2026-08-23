# Changelog

Notable changes, by release. Notes for the next release collect under
**Unreleased** and get a final edit when `release.sh` runs.

## Unreleased

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
