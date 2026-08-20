# Changelog

Notable changes, by release. Notes for the next release collect under
**Unreleased** and get a final edit when `release.sh` runs.

## Unreleased

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
