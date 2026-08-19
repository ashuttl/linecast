<div align="center">

# linecast

**Weather, sunlight, tides, radar, the Moon, and maps — drawn for the terminal.**

[![PyPI](https://img.shields.io/pypi/v/linecast)](https://pypi.org/project/linecast/)
[![Python](https://img.shields.io/pypi/pyversions/linecast)](https://pypi.org/project/linecast/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

<a href="https://terminaltrove.com/linecast/" title="linecast on Terminal Trove, the $HOME of all things in the terminal"><img src="https://cdn.terminaltrove.com/media/badges/tool_of_the_week/svg/terminal_trove_tool_of_the_week_green_on_dark_grey_bg.svg" alt="Terminal Trove Tool of The Week" height="36"></a>

</div>

![linecast weather, sunshine, tides, and radar tiled on an Omarchy desktop](https://raw.githubusercontent.com/ashuttl/linecast/main/screenshots/hero.png)

linecast turns free public data into six live, mouse-friendly terminal apps. It is pure Python, has no dependencies, adapts to your terminal theme, and needs no account or API key for its core experience.

| Command | What it shows |
| --- | --- |
| `weather` | Current conditions, an hourly braille temperature curve, seven-day forecast, air quality, comparisons, and official alerts |
| `sunshine` | The Sun moving across its daily arc, with sky gradients, day length, and moon phase |
| `moon` | A shaded lunar disc, illumination, altitude, rise and set times, and the next full and new moons |
| `tides` | A sunlight-shaded tide curve, current water level, and high and low times |
| `radar` | Animated worldwide radar or satellite imagery, warning polygons, temperature, and wind |
| `maps` | Detailed vector streets, terrain and bathymetry, a spinnable globe with live daylight and clouds, place search, and directions |

## Quick try

Run linecast immediately with [uv](https://docs.astral.sh/uv/), without installing it:

```sh
uvx linecast weather
```

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

`pipx install linecast` and `pip install linecast` work too. linecast requires Python 3.10+ on macOS or Linux.

## Take it outside

```sh
weather
sunshine
moon
tides
radar
maps
```

Every command finds your approximate location from your IP address and opens in live mode when run in a terminal. Drag or scroll where it makes sense; each app shows its keyboard controls along the bottom.

Pass a place name or coordinates to go somewhere else:

```sh
weather --location "Québec"
radar --location 41.88,-87.63
maps --view terrain --location "Innsbruck"
maps --to "Portland Head Light" --profile bike
```

Use `--print` for one static frame. When output is piped, linecast does this automatically. Weather, sunshine, moon, and tides also offer `--json` and compact `--oneline` output for status bars.

If a short command name conflicts with something already on your system, everything also lives under the `linecast` namespace:

```sh
linecast weather --metric
linecast radar --theme rainbow
linecast maps --view terrain
```

## A closer look

### Weather

The weather dashboard combines current conditions, daylight-shaded hourly temperatures, precipitation, daily ranges, air quality, and natural-language comparisons. Official alerts are available across 36 countries and open to their full detail in live mode.

![weather dashboard](https://raw.githubusercontent.com/ashuttl/linecast/main/screenshots/weather.png)

### Sunshine and Moon

`sunshine` is inspired by the Apple Watch Solar face. The arc and sky move through dawn, day, dusk, and night; day length includes its change from yesterday.

<p align="center">
  <img src="https://raw.githubusercontent.com/ashuttl/linecast/main/screenshots/sunshine-day.png" width="49%" alt="sunshine at midday">
  <img src="https://raw.githubusercontent.com/ashuttl/linecast/main/screenshots/sunshine-dusk.png" width="49%" alt="sunshine at dusk">
</p>

`moon` draws the current phase with its real terminator, mare shading, halo, and orientation for your hemisphere, then tells you what the Moon is doing next. Try `moon --oneline` for a status bar.

![waxing gibbous Moon](https://raw.githubusercontent.com/ashuttl/linecast/main/screenshots/moon.png)

### Tides

The tide chart scrolls across several days and annotates exact highs, lows, and the current predicted water level. Coverage comes from NOAA in the US, the Canadian Hydrographic Service, and Queensland Open Data; anywhere else, the chart falls back to Open-Meteo's global tide model, so nearly any coastline works out of the box. An optional [TideCheck](https://tidecheck.com/) key adds more named stations. Run `tides --nearby` to list the closest stations, or `tides --station <id or name>` to pin one.

![tide chart](https://raw.githubusercontent.com/ashuttl/linecast/main/screenshots/tides.png)

### Radar

Radar animates recent observations and an hour of forecast over a braille basemap. LibreWXR supplies worldwide composites and fills gaps with model-derived precipitation; linecast adds time-synced US warning polygons, optional temperature and wind layers, 13 colour themes, and hourly infrared satellite imagery.

```sh
radar --theme rainbow
radar --layers temp,wind
radar --layer satellite
```

![animated radar forecast over Glasgow](https://raw.githubusercontent.com/ashuttl/linecast/main/screenshots/radar.gif)

### Maps

Street view renders OpenFreeMap vector tiles as solid water, land, parks, and buildings under a braille road network. Hover a feature to name and highlight it; search with `/`, ask for directions with `d`, or switch views with `v`. Directions open as a small panel: labelled from, to, and mode fields — each showing the key that edits it, and all clickable — above the turn-by-turn steps. Arrow (or click) through the maneuvers and the map flies along the route.

Terrain view turns global elevation into hillshade and a hypsometric ramp, from deep ocean trenches through lowland green to alpine white. Coastlines, borders, water, and cities are drawn over it in braille.

<p align="center">
  <img src="https://raw.githubusercontent.com/ashuttl/linecast/main/screenshots/maps-street.png" width="49%" alt="street map of Portland, Maine">
  <img src="https://raw.githubusercontent.com/ashuttl/linecast/main/screenshots/maps-terrain.png" width="49%" alt="terrain map of the Alps around Innsbruck">
</p>

Zoom all the way out and either view becomes an orthographic globe you can rotate by dragging — or set spinning with `r`. Two keys switch on the sky as it is right now: `s` shades the planet into actual daylight, with a creeping terminator and cities glowing on the night side, and `c` lays the current global cloud cover over it from live satellite imagery. `maps --view now` opens straight to the full picture.

![the globe as it is right now: live daylight and the terminator](https://raw.githubusercontent.com/ashuttl/linecast/main/screenshots/maps-globe.png)

Everything is a single key — `?` shows this list in the app:

| Keys | |
|------|---|
| drag · wheel · hover | pan, zoom at the pointer, identify what's under the cursor |
| `+` `-` | zoom (a held key coasts; only the view you stop on fetches) |
| `n` | back to the start view |
| `v` `l` | street ↔ terrain · toggle labels |
| `s` `c` | daylight and night city lights · live cloud cover |
| `r` | spin the globe |
| `/` | search places and addresses |
| `d` `o` `p` | directions · set the origin · cycle travel mode |
| `q` | quit |

```sh
maps --location "Portland, Maine" --zoom 0.01
maps --view terrain --location 60.4,5.3 --zoom 8
maps --view now
maps --from "Gorham, Maine" --to "Portland Head Light" --profile foot
```

## Make it yours

### Location

Save one location for every command:

```sh
linecast location set "Portland, Maine"
linecast location set 44.54,-68.42
linecast location
linecast location auto
linecast location search fayette
```

The setting lives in `~/.config/linecast/config.json`. A command's `--location` flag or `WEATHER_LOCATION` takes precedence.

### Language

Use `--lang` or `LINECAST_LANG` to localize the interface. Seventeen languages are supported:

> English, French, Spanish, German, Italian, Portuguese, Dutch, Polish, Norwegian, Swedish, Icelandic, Danish, Finnish, Japanese, Korean, Chinese, and Indonesian

```sh
weather --lang fr
radar --lang zh
```

### Colour and icons

linecast queries the terminal palette so its colours belong in your theme. Set `LINECAST_COLOR` to `truecolor`, `256`, `16`, or `none` to override colour detection, or use the standard `NO_COLOR` variable. A [Nerd Font](https://www.nerdfonts.com/) gives the best icon rendering; `--emoji` or `LINECAST_ICONS=emoji` uses standard emoji instead.

### Shell completion

```sh
# Bash
source <(linecast completion bash)

# Zsh
source <(linecast completion zsh)

# Fish
linecast completion fish | source
```

Completion covers both `linecast <command>` and the standalone commands.

<details>
<summary><strong>Environment variables</strong></summary>

| Variable | Description |
| --- | --- |
| `WEATHER_LOCATION` | Default `lat,lng` for location-aware commands; overrides the saved location |
| `WEATHER_UNITS` | `metric` for Celsius, km/h, and mm |
| `TIDE_STATION` | Default tide station ID |
| `TIDES_UNITS` | `metric` for tide heights in metres |
| `LINECAST_TIDECHECK_KEY` | Optional TideCheck API key for global tide coverage |
| `LINECAST_LANG` | UI language code: `en`, `fr`, `es`, `de`, `it`, `pt`, `nl`, `pl`, `no`, `sv`, `is`, `da`, `fi`, `ja`, `ko`, `zh`, or `id` |
| `LINECAST_RADAR_THEME` | Default radar colour theme |
| `LINECAST_LIBREWXR_URL` | Base URL of a self-hosted LibreWXR instance |
| `LINECAST_ICONS` | `emoji` to use standard emoji instead of Nerd Font icons |
| `LINECAST_COLOR` | `auto`, `truecolor`, `256`, `16`, or `none` |
| `LINECAST_THEME` | `auto` (default), or `classic` / `legacy` / `off` for the fixed palette |
| `LINECAST_THEME_TIMEOUT_MS` | Terminal palette query timeout in milliseconds (default `100`) |
| `NO_COLOR` | Any non-empty value disables ANSI colours |

</details>

<details>
<summary><strong>Data sources and coverage</strong></summary>

- **Weather** — [Open-Meteo](https://open-meteo.com/) for forecasts, geocoding, and air quality. Alerts come from the US National Weather Service, Environment Canada, China Meteorological Administration, DWD via Bright Sky, Met Éireann, Japan Meteorological Agency, MET Norway, and MeteoAlarm.
- **Sunshine and Moon** — computed locally from astronomical equations.
- **Tides** — NOAA CO-OPS, Canadian Hydrographic Service, Queensland Open Data, Open-Meteo's tide model as a global fallback, and optionally TideCheck.
- **Radar** — [LibreWXR](https://librewxr.net/), with NEXRAD via Iowa Environmental Mesonet and RainViewer as fallbacks; warning polygons come from the US National Weather Service via IEM. The basemap is derived from Natural Earth.
- **Maps** — terrain from AWS/Mapzen elevation tiles; streets and inland water from [OpenFreeMap](https://openfreemap.org/) (© OpenMapTiles © OpenStreetMap contributors); search from Photon and Nominatim; directions from FOSSGIS OSRM (© OpenStreetMap contributors); globe cloud cover from [LibreWXR](https://librewxr.net/) (CC BY 4.0) satellite imagery.

</details>

## License

[MIT](LICENSE)
