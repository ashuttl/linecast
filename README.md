<div align="center">

# linecast

**Weather, tides, the sun, the moon, and maps, drawn for the terminal. The Old Farmer's Almanac meets Minitel.**

[![Tests](https://github.com/ashuttl/linecast/actions/workflows/test.yml/badge.svg)](https://github.com/ashuttl/linecast/actions/workflows/test.yml)
[![PyPI](https://img.shields.io/pypi/v/linecast)](https://pypi.org/project/linecast/)
[![Python](https://img.shields.io/pypi/pyversions/linecast)](https://pypi.org/project/linecast/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

<a href="https://terminaltrove.com/linecast/" title="linecast on Terminal Trove, the $HOME of all things in the terminal"><img src="https://cdn.terminaltrove.com/media/badges/tool_of_the_week/svg/terminal_trove_tool_of_the_week_green_on_dark_grey_bg.svg" alt="Terminal Trove Tool of The Week" height="36"></a>

</div>

![linecast weather, sunshine, tides, and radar tiled on an Omarchy desktop](https://raw.githubusercontent.com/ashuttl/linecast/main/screenshots/hero.png)

linecast turns free public data into six live, mouse-friendly terminal apps. It is pure Python, has no dependencies on macOS or Linux (and just two on Windows), tries to match your terminal theme (on macOS and Linux), and needs no account or API key.

| Command | What it shows |
| --- | --- |
| `linecast weather` | Current conditions, an hourly braille temperature curve, seven-day forecast, air quality, comparisons, and official alerts |
| `linecast sunshine` | The Sun moving across its daily arc, with sky gradients, day length, and moon phase |
| `linecast moon` | A shaded lunar disc, illumination, altitude, rise and set times, and the next full and new moons |
| `linecast tides` | A sunlight-shaded tide curve, current water level, and high and low times |
| `linecast radar` | Animated worldwide radar or satellite imagery, warning polygons, temperature, and wind |
| `linecast maps` | Detailed vector streets, terrain and bathymetry, a spinnable globe with live daylight and clouds, place search, and directions |

## Quick try

Try linecast without installing it, with [uv](https://docs.astral.sh/uv/):

```sh
uvx linecast weather
```

Any of the six commands above works in place of `weather`.

Or with nothing but curl — [`get.sh`](get.sh) uses whatever the machine has, down to plain `python3`:

```sh
curl -sL https://raw.githubusercontent.com/ashuttl/linecast/main/get.sh | sh
```

It opens `weather` in live mode; name another tool with `sh -s sunshine`, or pass flags with `sh -s -- --metric`. When nothing else is available, the script keeps a small private environment for linecast in your cache directory and checks for a newer release once a day.

## Install

With [uv](https://docs.astral.sh/uv/):

```sh
uv tool install linecast
```

Or use Homebrew:

```sh
brew tap ashuttl/linecast
brew install linecast
```

On Arch, there is a community-maintained [AUR package](https://aur.archlinux.org/packages/linecast):

```sh
yay -S linecast
```

`pipx install linecast` and `pip install linecast` work too. linecast requires Python 3.10+ on macOS, Linux or Windows (Windows Terminal; Git Bash and mintty see a pipe, not a terminal, so they get static output).

On Windows it also installs `tzdata` (Windows has no IANA time zone database) and `truststore` (TLS verification through the OS certificate store). Icons default to emoji in Windows Terminal; with a Nerd Font installed and selected, `linecast icons nerd` switches to the full set.

## Take it outside

```sh
linecast weather
linecast sunshine
linecast moon
linecast tides
linecast radar
linecast maps
```

Every command opens in live mode when run in a terminal, at the city your IP address suggests unless you have [saved a location](#location). Drag or scroll where it makes sense; each app shows its keyboard controls along the bottom.

Pass a place name or coordinates to go somewhere else:

```sh
linecast weather --location "Québec"
linecast radar --location 41.88,-87.63
linecast maps --view terrain --location "Innsbruck"
linecast maps --to "Portland Head Light" --profile bike
```

Use `--print` for one static frame. When output is piped, linecast does this automatically. Weather, sunshine, moon, and tides also have `--json` and a short `--oneline` for status bars.

Prefer the short spellings? The names are yours, not linecast's, so they never collide with anything else on your system. `linecast link` makes `weather`, `sunshine`, `moon`, `tides`, `radar` and `maps` as links beside the `linecast` binary, skipping any name something else already owns; `linecast link --remove` takes them away again. A shell alias does the same job:

```sh
alias weather='linecast weather' radar='linecast radar'
```

![the same desk in motion: the radar loop plays while weather, tides, and the solar arc keep watch](https://raw.githubusercontent.com/ashuttl/linecast/main/screenshots/hero.gif)

## A closer look

### Weather

The weather dashboard combines current conditions, daylight-shaded hourly temperatures, precipitation, daily ranges, air quality, and natural-language comparisons. Official alerts are available across 37 countries and open to their full detail in live mode. In India, air quality is shown on the CPCB's National AQI scale, the one official bulletins use.

![weather dashboard](https://raw.githubusercontent.com/ashuttl/linecast/main/screenshots/weather.png)

### Sunshine and Moon

`sunshine` is inspired by the Apple Watch Solar face. The arc and sky move through dawn, day, dusk, and night; day length includes its change from yesterday.

<p align="center">
  <img src="https://raw.githubusercontent.com/ashuttl/linecast/main/screenshots/sunshine-day.png" width="49%" alt="sunshine at midday">
  <img src="https://raw.githubusercontent.com/ashuttl/linecast/main/screenshots/sunshine-dusk.png" width="49%" alt="sunshine at dusk">
</p>

`moon` draws the current phase with its real terminator, mare shading, halo, and orientation for your hemisphere, then tells you what the Moon is doing next. Try `linecast moon --oneline` for a status bar.

![full Moon](https://raw.githubusercontent.com/ashuttl/linecast/main/screenshots/moon.png)

### Tides

The tide chart scrolls across several days and annotates exact highs, lows, and the current predicted water level. Coverage comes from NOAA in the US, the Canadian Hydrographic Service, Queensland Open Data, and the Hong Kong Observatory; anywhere else, the chart falls back to Open-Meteo's global tide model, so nearly any coastline works out of the box. An optional [TideCheck](https://tidecheck.com/) key adds more named stations. Run `linecast tides --nearby` to list the closest stations, or `linecast tides --station <id or name>` to pin one.

![tide chart](https://raw.githubusercontent.com/ashuttl/linecast/main/screenshots/tides.png)

### Radar

Radar animates recent observations and an hour of forecast over a braille basemap. Real radar is only available where a public network publishes an open composite — North America, Europe, and parts of East and Southeast Asia. Elsewhere LibreWXR fills in with a precipitation model, which looks smoother and blockier than radar; the footer says so when that is what you are seeing. On top of the frames, linecast draws US warning polygons that follow the timeline, optional temperature and wind layers, and hourly infrared satellite imagery.

The default theme uses colors from your terminal's color scheme to draw rain radar data on the map. If your theme is monochrome, the radar data will be too. In addition to the default theme, there are a handful of other local themes — `dusk`, `ember`, `ink`, and `marangai` — and you can also choose from LibreWXR's server-rendered themes. Press `t` to switch.

```sh
linecast radar --theme dusk
linecast radar --layers temp,wind
linecast radar --layer satellite
```

![animated radar forecast over Glasgow](https://raw.githubusercontent.com/ashuttl/linecast/main/screenshots/radar.gif)

### Maps

Street view renders OpenFreeMap vector tiles as solid water, land, parks, and buildings under a braille road network. Hover a feature to name and highlight it; search with `/`, ask for directions with `d`, or switch views with `v`. Directions open as a panel of turn-by-turn steps; arrow (or click) through them and the map flies along the route.

Terrain view turns global elevation into hillshade and a hypsometric ramp, from deep ocean trenches through lowland green to alpine white. Coastlines, borders, water, and cities are drawn over it in braille.

<p align="center">
  <img src="https://raw.githubusercontent.com/ashuttl/linecast/main/screenshots/maps-street.png" width="49%" alt="street map of Portland, Maine">
  <img src="https://raw.githubusercontent.com/ashuttl/linecast/main/screenshots/maps-terrain.png" width="49%" alt="terrain map of the Alps around Innsbruck">
</p>

Zoom all the way out and either view becomes an orthographic globe you can rotate by dragging — or set spinning with `r`. Two keys switch on the sky as it is right now: `s` shades the planet into actual daylight, with a creeping terminator and cities glowing on the night side, and `c` lays the current global cloud cover over it from live satellite imagery. `linecast maps --view now` opens straight to the full picture.

![the globe as it is right now: live daylight and the terminator](https://raw.githubusercontent.com/ashuttl/linecast/main/screenshots/maps-globe.png)

Everything is a single key — `?` shows this list in the app:

| Keys | |
|------|---|
| drag · wheel · hover | pan, zoom at the pointer, identify what's under the cursor |
| `+` `-` | zoom (a held key coasts; only the view you stop on fetches) |
| `n` | back to the start view |
| `v` `l` | street ↔ terrain · toggle labels & lines |
| `s` `c` | daylight and night city lights · live cloud cover |
| `r` | spin the globe |
| `/` | search places and addresses |
| `d` `o` `p` | directions · set the origin · cycle travel mode |
| `q` | quit |

```sh
linecast maps --location "Portland, Maine" --zoom 0.01
linecast maps --view terrain --location 60.4,5.3 --zoom 8
linecast maps --view now
linecast maps --from "Gorham, Maine" --to "Portland Head Light" --profile foot
```

## Make it yours

Settings live in `~/.config/linecast/config.json`. For any of them, a command-line flag beats an environment variable, which beats the saved setting.

### Location

Save one location for every command:

```sh
linecast location set "Portland, Maine"
linecast location set "westbrook, maine"
linecast location set 44.54,-68.42
linecast location
linecast location auto
linecast location search fayette
```

`set` takes a place name — it is looked up once, on the spot, and the first match is saved — or exact `lat,lng` coordinates; `search` lists the candidates when the first match might not be the right one. A command's `--location` flag or `WEATHER_LOCATION` wins. With no location saved or passed, linecast falls back to IP geolocation: a single anonymous request to [ipinfo.io](https://ipinfo.io/), which returns the rough position of your network connection — usually the right city, sometimes the wrong one, and off by a lot on a VPN or corporate network. The answer is cached for an hour; save a location, or set any override, and the request is not made at all. Times follow the location: point `linecast sunshine` or `linecast moon` somewhere across an ocean and sunrise, sunset, moonrise, and moonset come back in that place's local clock.

### Units

Metric is the default — imperial in the United States, going by the saved location or, failing that, the machine's IP — and either can be pinned for every command:

```sh
linecast units metric
linecast units imperial
linecast units
linecast units auto
```

Every view command takes `--metric` and `--imperial`; `weather` adds `--celsius` and `--fahrenheit` for the temperature alone. `LINECAST_UNITS` sets units for every command; `WEATHER_UNITS` and `TIDES_UNITS` override it for their one command.

### Clock

The clock tries to follow the country: 12-hour in the United States, Canada, Australia, and the other places that write 6:50 pm, 24-hour everywhere else. Pin either for every command:

```sh
linecast clock 12
linecast clock 24
linecast clock
linecast clock auto
```

The time-showing commands take `--12h` and `--24h` for one run, and `LINECAST_CLOCK` sets it in the environment.

### Language

Use `--lang` or `LINECAST_LANG` to pick the language. There are seventeen:

> English, French, Spanish, German, Italian, Portuguese, Dutch, Polish, Norwegian, Swedish, Icelandic, Danish, Finnish, Japanese, Korean, Chinese, and Indonesian

```sh
linecast weather --lang fr
linecast radar --lang zh
```

In India, alerts follow `--lang` further than the app itself: SACHET publishes many alerts in the state language, so `--lang hi`, `te`, `or`, `mr`, or another Indian language code shows an alert's own regional text where it exists, while the rest of the app stays in English.

### Color and icons

linecast asks the terminal for its palette so its colors belong in your theme. Set `LINECAST_COLOR` to `truecolor`, `256`, `16`, or `none` to choose the color mode yourself, or use the standard `NO_COLOR` variable.

Icons come in three sets. [Nerd Font](https://www.nerdfonts.com/) glyphs are used automatically in terminals that bundle them (WezTerm, kitty, Ghostty); other interactive terminals get emoji, and piped or redirected output falls back to plain Unicode, whose glyphs are one cell wide everywhere. Most terminals don't make their current font available programmatically, so if you have a Nerd Font in Alacritty, foot, or iTerm2, say so once:

```sh
linecast icons nerd
linecast icons emoji
linecast icons plain
linecast icons
linecast icons auto
```

`--icons` and `LINECAST_ICONS` pick a set for one run, and `linecast doctor` shows a glyph from each so you can see what your font renders.

### Shell completion

```sh
# Bash
source <(linecast completion bash)

# Zsh
source <(linecast completion zsh)

# Fish
linecast completion fish | source

# Nushell
linecast completion nu | save -f ~/.config/nushell/completions/linecast_completions.nu
# in config.nu:
use ~/.config/nushell/completions/linecast_completions.nu *
```

Completion covers `linecast <command>` and the short names, for anyone who aliased or symlinked them.

### When something looks wrong

```sh
linecast doctor
linecast doctor --offline
linecast doctor --json
```

`linecast doctor` reports the build, the settings and cache paths, what the terminal advertised, which settings are in force and where each came from, and whether each data provider answered. Secrets show as "(set)", never their value. `--offline` skips the probes; `--json` is the thing to paste into a bug report.

The six view commands and `linecast doctor` take `--debug`, which prints one line on stderr for each fallback taken along the way — a provider that did not answer, a tile that would not decode — and what was shown instead. URLs are reduced to scheme, host, and path.

<details>
<summary><strong>Environment variables</strong></summary>

| Variable | Description |
| --- | --- |
| `WEATHER_LOCATION` | Default location for location-aware commands, as `lat,lng` or a place name; overrides the saved location |
| `WEATHER_UNITS` | `metric` or `imperial` for the weather command; overrides `LINECAST_UNITS` and the saved units |
| `TIDE_STATION` | Default tide station ID |
| `TIDES_UNITS` | `metric` or `imperial` for tide heights; overrides `LINECAST_UNITS` and the saved units |
| `LINECAST_UNITS` | `metric` or `imperial` for every command; overrides the saved units |
| `LINECAST_CLOCK` | `12` or `24`; overrides the saved clock |
| `LINECAST_TIDECHECK_KEY` | Optional TideCheck API key for global tide coverage |
| `LINECAST_TIDECHECK_PAID` | Set to `1` on a paid TideCheck plan; the request tally then drops the 50-a-day free-tier cap |
| `LINECAST_LANG` | UI language code: `en`, `fr`, `es`, `de`, `it`, `pt`, `nl`, `pl`, `no`, `sv`, `is`, `da`, `fi`, `ja`, `ko`, `zh`, or `id` |
| `LINECAST_RADAR_THEME` | Default radar color theme |
| `LINECAST_LIBREWXR_URL` | Base URL of a self-hosted LibreWXR instance |
| `LINECAST_ICONS` | icon set: `nerd`, `emoji`, or `plain`; overrides the saved icons (default: `nerd` where the terminal bundles the glyphs, `emoji` on other interactive terminals, `plain` when piped) |
| `LINECAST_COLOR` | `auto`, `truecolor`, `256`, `16`, or `none` |
| `LINECAST_THEME` | `auto` (default), or `classic` / `legacy` / `off` for the fixed palette |
| `LINECAST_THEME_TIMEOUT_MS` | Terminal palette query timeout in milliseconds (default `100`) |
| `LINECAST_THEME_POLL` | Seconds between re-reading the terminal palette in live views, so a theme switch re-inks the view in place (default `2`; `0` disables) |
| `LINECAST_THEME_WATCH` | A file whose modification marks a desktop theme change, prompting an immediate re-read (default: Omarchy's current-theme marker; empty disables) |
| `LINECAST_CACHE_DIR` | Directory for cached data, used exactly as given |
| `LINECAST_MAPS_CACHE_MB` | Size the map tile cache is swept back to when `maps` starts (default `256`) |
| `LINECAST_CONFIG_DIR` | Directory for `config.json`, used exactly as given |
| `NO_COLOR` | Any non-empty value disables ANSI colors |
| `CLICOLOR` / `CLICOLOR_FORCE` | `CLICOLOR=0` disables color; a non-zero `CLICOLOR_FORCE` keeps it on when output is not a terminal |

Cached data lives in `~/Library/Caches/linecast` on macOS and `~/.cache/linecast` elsewhere; settings in `~/.config/linecast/config.json`. Both honor the `XDG_*` variables, and the `LINECAST_*_DIR` variables above override everything.

</details>

<details>
<summary><strong>Data sources and coverage</strong></summary>

- **Location** — [ipinfo.io](https://ipinfo.io/) for IP geolocation when no location is saved or passed; place names are geocoded by Open-Meteo.
- **Weather** — [Open-Meteo](https://open-meteo.com/) for forecasts, geocoding, and air quality. Alerts come from the US National Weather Service, Environment Canada, China Meteorological Administration, DWD via Bright Sky, Hong Kong Observatory, Met Éireann, Japan Meteorological Agency, MET Norway, MeteoAlarm, and SACHET (India's national alert aggregator).
- **Sunshine and Moon** — computed on your device from the astronomical equations; the Moon's face is a vendored grayscale of NASA SVS's [CGI Moon Kit](https://svs.gsfc.nasa.gov/4720) (Lunar Reconnaissance Orbiter, public domain).
- **Tides** — NOAA CO-OPS, Canadian Hydrographic Service, Queensland Open Data, Hong Kong Observatory, Open-Meteo's tide model as a global fallback, and optionally TideCheck.
- **Radar** — [LibreWXR](https://librewxr.net/), with NEXRAD via Iowa Environmental Mesonet and RainViewer as fallbacks; warning polygons come from the US National Weather Service via IEM. The basemap is derived from Natural Earth.
- **Maps** — terrain from AWS/Mapzen elevation tiles; streets and inland water from [OpenFreeMap](https://openfreemap.org/) (© OpenMapTiles © OpenStreetMap contributors); search from Photon and Nominatim; directions from FOSSGIS OSRM (© OpenStreetMap contributors); globe cloud cover from [LibreWXR](https://librewxr.net/) (CC BY 4.0) satellite imagery; terrain color picks its ramp from a vendored [Köppen-Geiger climate grid](https://doi.org/10.6084/m9.figshare.21789074) (Beck et al. 2023, CC BY 4.0).

</details>

## Contributing

Pull requests are welcome. [ARCHITECTURE.md](ARCHITECTURE.md) is the map of the code. The suite runs with `uv run --with pytest pytest tests -q` and the lint with `uvx ruff check src tests scripts`; both are meant to run without the network and without touching your home directory.

## Lineage

<p align="center">
  <img src="https://raw.githubusercontent.com/ashuttl/linecast/main/screenshots/minitel-terminatel-258.jpg" width="380" alt="3615 LINECAST">
</p>

<p align="center"><em>Prior art.</em></p>

A Telic-Alcatel videotex terminal draws the weather, circa 1990. Photograph from the collection at
[minitel-alcatel.fr](https://www.minitel-alcatel.fr/).

## License

[MIT](LICENSE)
