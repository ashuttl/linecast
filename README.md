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

linecast turns free public data into seven live, mouse-friendly terminal apps for macOS, Linux, and Windows. It is pure Python with no dependencies (two on Windows), takes its colors from your terminal theme, and needs no accounts or API keys.

| Command | What it shows |
| --- | --- |
| `linecast weather` | Current conditions, hourly temperatures, a seven-day forecast, air quality, how today compares with normal, and official alerts |
| `linecast sunshine` | The sun on its daily arc, with the color of the sky, day length, and moon phase |
| `linecast moon` | The moon as you see it from where you are, with rise and set times and the next full and new moons |
| `linecast sky` | The night sky from where you stand: the stars, the constellations, the planets, the Moon, and the Milky Way |
| `linecast tides` | A tide curve shaded by daylight, the water level now, and the times of high and low tide |
| `linecast radar` | Animated radar or satellite imagery for the whole world, with warnings, temperature, and wind |
| `linecast maps` | Street maps, terrain, and a globe you can spin, with live daylight and clouds, place search, and directions |

**[Install](#install) · [Using it](#using-it) · [A closer look](#a-closer-look) · [Settings](#settings) · [Contributing](#contributing)**

## Install

```sh
brew install linecast
```

Or with [uv](https://docs.astral.sh/uv/):

```sh
uv tool install linecast
```

`pipx install linecast` and `pip install linecast` work too, and there are community packages in the [AUR](https://aur.archlinux.org/packages/linecast) and in [nixpkgs](https://search.nixos.org/packages?channel=unstable&show=linecast) (unstable channel, for now). linecast needs Python 3.10 or newer.

To try it without installing anything:

```sh
uvx linecast weather
```

Or with nothing but curl. [`get.sh`](get.sh) runs linecast with whatever the machine has, down to plain `python3`:

```sh
curl -sL https://raw.githubusercontent.com/ashuttl/linecast/main/get.sh | sh
```

It opens `weather`. Name another tool with `sh -s sunshine`, or pass flags with `sh -s -- --metric`.

<details>
<summary><strong>On Windows</strong></summary>

Use Windows Terminal. Git Bash and mintty see a pipe rather than a terminal, so they get static output. The install adds two packages: `tzdata`, because Windows has no IANA time zone database, and `truststore`, for TLS verification through the OS certificate store. Icons default to emoji in Windows Terminal; with a Nerd Font installed and selected, `linecast icons nerd` switches to the full set.

</details>

## Using it

Run in a terminal, every command opens live, at the place your IP address suggests until you [save a location](#location).

```sh
linecast weather --location "Québec"
linecast radar --location 41.88,-87.63
linecast maps --view terrain --location "Innsbruck"
linecast maps --to "Portland Head Light" --profile bike
```

`--print` gives one static frame, and piped output gets one automatically. Weather, sunshine, moon, sky, and tides also have `--json`, and `--oneline` for a status bar.

![an animated version of the hero screenshot, showing the weather radar moving](https://raw.githubusercontent.com/ashuttl/linecast/main/screenshots/hero.gif)

## A closer look

### Weather

Current conditions, hourly temperatures shaded by daylight, precipitation, daily ranges, air quality, and a line on how today compares with a normal day. Official alerts cover 45 countries; click one to read it in full, or press `o` to open it in your browser. In India, air quality uses the CPCB's National AQI scale. If the forecast service cannot be reached, the last forecast stands in, and a line under the header says which day it is from; `r` asks for a newer one.

![weather dashboard](https://raw.githubusercontent.com/ashuttl/linecast/main/screenshots/weather.png)

### Sunshine

`sunshine` is modeled on the Apple Watch Solar face. The arc and sky move through dawn, day, dusk, and night, and the day length says how much longer or shorter it is than yesterday.

<p align="center">
  <img src="https://raw.githubusercontent.com/ashuttl/linecast/main/screenshots/sunshine-day.png" width="49%" alt="sunshine at midday">
  <img src="https://raw.githubusercontent.com/ashuttl/linecast/main/screenshots/sunshine-dusk.png" width="49%" alt="sunshine at dusk">
</p>

`--year` draws the whole year. Each column is a day, midnight to midnight, colored by the sky at each hour, so sunrise and sunset appear where night meets day. Hover a day for its sunrise, sunset, and day length. In live mode `v` switches between the day and the year, and `--dst` keeps each day on its own clock, so the clock changes show as steps.

![the year view for Westbrook, Maine, with the pointer on the December solstice](https://raw.githubusercontent.com/ashuttl/linecast/main/screenshots/sunshine-year.png)

Near the poles the same chart turns into polar night and midnight sun. These are Longyearbyen and Vostok Station, at 78° north and 78° south.

<p align="center">
  <img src="https://raw.githubusercontent.com/ashuttl/linecast/main/screenshots/sunshine-year-arctic.png" width="49%" alt="the year view for Longyearbyen, Svalbard">
  <img src="https://raw.githubusercontent.com/ashuttl/linecast/main/screenshots/sunshine-year-antarctic.png" width="49%" alt="the year view for Vostok Station, Antarctica">
</p>

### Moon

`moon` draws the phase as you see it from where you are, with the shadow falling where it really does, the maria shaded, earthshine on the night side, and a halo around it. Scroll to move through time. The stars around it are the real ones for the moment, so scrolling turns the sky with the night and walks the Moon through its constellations. Drag the disc to turn the Moon over and see the far side, with the stars wheeling past; let go and it settles back. Point it somewhere across an ocean and the rise and set times come back in that place's local clock.

![full Moon](https://raw.githubusercontent.com/ashuttl/linecast/main/screenshots/moon.png)

`v` flips to a calendar of the month (or open on it with `--grid`). Each day carries its phase as a small shaded disc, with today, the full and new moons, and the quarters marked. Scroll through the months, hover a day for its phase, moonrise, and moonset, and click one to open the disc view on it.

The moon can also follow a traditional calendar, with that calendar's date beside the phase and a countdown to its next festival or observance: the Chinese, Japanese, and Korean lunisolar calendars, the Thai lunar calendar, the Hawaiian Kaulana Mahina and the Samoan, Chamorro, and Refaluwasch calendars of the Pacific, the Islamic and Hebrew calendars, and the Old Farmer's Almanac. In Chinese, Japanese, Korean, and Thai the calendar follows the language; any language can ask for any of them with `--calendar`. Each is computed on your device and checked against the published calendars. [CALENDARS.md](CALENDARS.md) describes them one by one.

<p align="center">
  <img src="https://raw.githubusercontent.com/ashuttl/linecast/main/screenshots/moon-okinawa.png" width="49%" alt="the moon over Okinawa in Japanese: 十六夜, the sixteenth night of the eighth month">
  <img src="https://raw.githubusercontent.com/ashuttl/linecast/main/screenshots/moon-calendar.png" width="49%" alt="the month calendar for September 2026 in Japanese, with 十五夜 on the 25th and the pointer on it">
</p>

### Sky

`sky` is the night sky from where you stand. The horizon runs along the bottom with the compass points under it, and above it are the real stars for the moment, the constellation figures drawn faintly through them with their names, the planets marked and named, the Moon at its phase and tilt, and the Milky Way once the sky is dark enough. By day the sky is blue and holds only the Sun, and perhaps Venus. Scroll into the evening and the sky goes through its twilight colors while the stars come out one by one, brightest first.

Drag to look around, and let go while moving to coast. `+` and `-` zoom: as the view closes in, fainter stars and more names appear, and the Moon grows into the disc the moon view draws. Zoom all the way out while looking up and the horizon closes into a circle, the whole sky at once, the way the almanacs print it. `p` plays time at an hour a second, then a day, then a week, so you can watch the stars wheel and the Moon run through its phases; space returns to now. `c` cycles the constellation figures and names, `1` to `8` face the compass points, `9` looks straight up, and `m` faces the Moon. Point at anything for its name, and `--facing SW` or `--fov 40` open the view where you want it.

Press `/` and type a name, a star, a planet, or a constellation, and the view flies to it. If it is below the horizon the panel says when it rises and where, and Enter again moves the clock to that moment. `--at Jupiter` opens on it.

The sky has been drawn many ways. `t` steps through twenty-two traditions besides the IAU's, each with its own figures and star names: the Chinese Three Enclosures and Twenty-Eight Mansions, the Hawaiian star lines, the Boorong sky of Victoria, the Norse, Sami, Māori, Tongan, Mongolian, Romanian, Belarusian and Indian Vedic skies, H. A. Rey's stick figures, and more. `--culture hawaiian` opens on one, `linecast culture` saves one, and Chinese comes with the language. The Hawaiian sky also puts the navigators' star compass along the horizon, the thirty-two houses from Hikina round to Komohana, in place of the compass points. [CULTURES.md](CULTURES.md) lists them with their sources.

### Tides

The tide chart runs across several days and marks the highs, the lows, and the predicted water level now. Scroll to move through time.

Predictions come from national services where they exist (NOAA, the Canadian Hydrographic Service, Queensland Open Data, and the Hong Kong Observatory) and from Open-Meteo's global tide model everywhere else. An optional [TideCheck](https://tidecheck.com/) key adds more named stations. `--nearby` lists the closest stations and `--station <id or name>` pins one.

![tide chart](https://raw.githubusercontent.com/ashuttl/linecast/main/screenshots/tides.png)

### Radar

Radar animates the recent observations and an hour of forecast over a braille basemap.

Real radar exists only where open composites are published: North America, Europe, and parts of East and Southeast Asia. Elsewhere LibreWXR fills in with a precipitation model, and it looks like one. US warning polygons are drawn too, with optional temperature and wind layers and hourly infrared satellite imagery.

Rain takes its colors from your terminal theme; if the theme is monochrome, so is the rain. There are a few fixed themes as well, `dusk`, `ember`, `ink`, and `marangai`, plus LibreWXR's server-rendered ones. Press `t` to switch.

```sh
linecast radar --theme dusk
linecast radar --layers temp,wind
linecast radar --layer satellite
```

`--source librewxr`, `rainviewer`, or `iem` pins one frame source, for comparing what each shows over the same spot.

![animated radar forecast over Glasgow](https://raw.githubusercontent.com/ashuttl/linecast/main/screenshots/radar.gif)

### Maps

Streets are drawn in braille over water, land, parks, and buildings in solid color. In terrain view the land is shaded by height and lit from one side, like a relief map, with coastlines, borders, water, and cities in braille over it; `l` toggles them and the labels.

Search with `/` and ask for directions with `d`. Directions open as a panel of turn-by-turn steps; arrow or click through them and the map flies along the route.

<p align="center">
  <img src="https://raw.githubusercontent.com/ashuttl/linecast/main/screenshots/maps-street.png" width="49%" alt="street map of Portland, Maine">
  <img src="https://raw.githubusercontent.com/ashuttl/linecast/main/screenshots/maps-terrain.png" width="49%" alt="terrain map of the Alps around Innsbruck">
</p>

Zoom all the way out and either view becomes a globe. Drag to rotate it, or press `r` to set it spinning. `s` shades it into the daylight of this moment, with the terminator creeping and cities glowing on the night side, and `c` lays the current cloud cover over it from live satellite imagery. `--view now` opens straight to the full picture.

![the globe as it is right now: live daylight and the terminator](https://raw.githubusercontent.com/ashuttl/linecast/main/screenshots/maps-globe.png)

| Keys | |
|------|---|
| drag · wheel · hover | pan, zoom at the pointer, identify what's under the cursor |
| `+` `-` | zoom |
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

## Settings

Settings live in `~/.config/linecast/config.json`. A command-line flag beats an environment variable, which beats the saved setting. Each settings command below shows the current value when run with no argument, and `auto` returns it to the default.

### Location

Save one location for every command:

```sh
linecast location set "Portland, Maine"
linecast location set 44.54,-68.42
linecast location search fayette
linecast location auto
```

`set` takes a place name or `lat,lng`. A name is looked up once and the first match saved; `search` lists the candidates when the first match might be wrong. `--location` or `WEATHER_LOCATION` wins over the saved location.

With no location saved or passed, linecast asks [ipinfo.io](https://ipinfo.io/) (or ipwho.is or GeoJS if it doesn't answer) where your network connection is. That is usually the right city, sometimes the wrong one, and far off on a VPN or corporate network. The answer is cached for an hour. Save a location and the request is never made.

### Units and clock

Units follow the location, imperial in the United States and metric everywhere else. The clock follows the country, 12-hour where people write 6:50 pm and 24-hour everywhere else. Pin either:

```sh
linecast units metric
linecast clock 24
```

Every view command takes `--metric` and `--imperial` for one run, and the ones that show times take `--12h` and `--24h`. `weather` adds `--celsius` and `--fahrenheit` for the temperature alone.

### Language

linecast speaks the terminal's language when it is one it knows, read from `LANG` and the other locale variables the way most command-line tools read them, and English otherwise. `linecast language fr` saves a language instead, `--lang` or `LINECAST_LANG` picks one for a run, and `linecast language auto` goes back to following the terminal. There are eighteen:

> English, French, Spanish, German, Italian, Portuguese, Dutch, Polish, Norwegian, Swedish, Icelandic, Danish, Finnish, Japanese, Korean, Chinese, Thai, and Indonesian

```sh
linecast language fr
linecast radar --lang zh
```

In India, SACHET publishes many alerts in the state language. `--lang hi`, `te`, `or`, `mr`, or another Indian language code shows that text where it exists, while the rest of the app stays in English.

### Calendar

The moon's traditional calendar follows the language: Chinese, Japanese, Korean, and Thai get their own, and the rest get none. Pin any of them for every run, or none:

```sh
linecast calendar hebrew
linecast calendar none
linecast calendar auto
```

The names are `chinese`, `japanese`, `korean`, `thai`, `hawaiian`, `samoan`, `chamorro`, `refaluwasch`, `islamic`, `hebrew`, and `almanac`. `moon --calendar` takes one for a single run. [CALENDARS.md](CALENDARS.md) describes each.

### Culture

The sky draws the IAU constellations unless the language brings a tradition with it: Chinese gets the Chinese sky. Pin any of the twenty-two bundled traditions for every run, or none:

```sh
linecast culture hawaiian
linecast culture none
linecast culture auto
```

`sky --culture` takes one for a single run, and `t` steps through them live. [CULTURES.md](CULTURES.md) lists them with their credits.

### Color and icons

linecast asks the terminal for its palette so its colors belong in your theme. `LINECAST_COLOR` set to `truecolor`, `256`, `16`, or `none` chooses the color mode yourself, and the standard `NO_COLOR` is honored.

Icons come in three sets: [Nerd Font](https://www.nerdfonts.com/) glyphs in terminals that bundle them (WezTerm, kitty, Ghostty), emoji in other terminals, and plain Unicode when piped. If you have installed a Nerd Font in Alacritty, foot, or iTerm2, linecast cannot tell, so say so once:

```sh
linecast icons nerd
```

`--icons` and `LINECAST_ICONS` pick a set (`nerd`, `emoji`, or `plain`) for one run, and `linecast doctor` shows a glyph from each set so you can see what your font renders.

### Short names and shell completion

`linecast link` makes `weather`, `sunshine`, `moon`, `sky`, `tides`, `radar`, and `maps` links beside the `linecast` binary, skipping any name something else already owns; `linecast link --remove` takes them away. A shell alias does the same job.

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

Completion covers the short names too.

### When something looks wrong

```sh
linecast doctor
linecast doctor --offline
linecast doctor --json
```

`linecast doctor` reports the build, the settings and cache paths, what the terminal advertised, which settings are in force and where each came from, and whether each data provider answered. Secrets show as "(set)", never their value. `--offline` skips the probes; `--json` is the thing to paste into a bug report.

The six view commands and `linecast doctor` take `--debug`, which prints a line on stderr for each fallback taken along the way, such as a provider that did not answer or a tile that would not decode, and what was shown instead.

<details>
<summary><strong>Environment variables</strong></summary>

| Variable | Description |
| --- | --- |
| `WEATHER_LOCATION` | Default location, as `lat,lng` or a place name; overrides the saved location |
| `LINECAST_UNITS` | `metric` or `imperial` for every command; overrides the saved units |
| `WEATHER_UNITS` | Units for the weather command; overrides `LINECAST_UNITS` |
| `TIDES_UNITS` | Units for tide heights; overrides `LINECAST_UNITS` |
| `LINECAST_CLOCK` | `12` or `24`; overrides the saved clock |
| `LINECAST_LANG` | UI language code: `en`, `fr`, `es`, `de`, `it`, `pt`, `nl`, `pl`, `no`, `sv`, `is`, `da`, `fi`, `ja`, `ko`, `zh`, `th`, or `id`; overrides the saved language and the terminal's locale |
| `LINECAST_ICONS` | `nerd`, `emoji`, or `plain`; overrides the saved icons |
| `LINECAST_COLOR` | `auto`, `truecolor`, `256`, `16`, or `none` |
| `NO_COLOR` | Any non-empty value disables ANSI colors |
| `CLICOLOR` / `CLICOLOR_FORCE` | `CLICOLOR=0` disables color; a non-zero `CLICOLOR_FORCE` keeps it on when output is not a terminal |
| `LINECAST_THEME` | `auto` (default), or `classic` / `legacy` / `off` for the fixed palette |
| `LINECAST_THEME_TIMEOUT_MS` | Terminal palette query timeout in milliseconds (default `100`) |
| `LINECAST_THEME_POLL` | Seconds between re-reading the terminal palette in live views, so a theme switch re-inks the view in place (default `2`; `0` disables) |
| `LINECAST_THEME_WATCH` | A file whose modification marks a desktop theme change, prompting an immediate re-read (default: Omarchy's current-theme marker; empty disables) |
| `TIDE_STATION` | Default tide station ID |
| `LINECAST_TIDECHECK_KEY` | Optional TideCheck API key for global tide coverage |
| `LINECAST_TIDECHECK_PAID` | Set to `1` on a paid TideCheck plan; the request tally then drops the 50-a-day free-tier cap |
| `LINECAST_RADAR_THEME` | Default radar color theme |
| `LINECAST_RADAR_SOURCE` | Pin the radar frame source: `librewxr`, `rainviewer`, or `iem` |
| `LINECAST_RADAR_LAYER` | `radar` (default) or `satellite`, the imagery `radar` opens with |
| `LINECAST_RADAR_LAYERS` | Overlays `radar` opens with: `temp`, `wind`, or both comma-separated |
| `LINECAST_SUNSHINE_YEAR_PALETTE` | `dial` (default) for the Solar Dial colors in `sunshine --year`, or `graph` for the day view's own sky |
| `LINECAST_LIBREWXR_URL` | Base URL of a self-hosted LibreWXR instance |
| `LINECAST_VECTOR_TILES_URL` | TileJSON URL of a self-hosted street tile server, used instead of OpenFreeMap with no fallback |
| `LINECAST_ELEVATION_URL` | Elevation tile source for `maps`: a bucket root holding `terrarium/{z}/{x}/{y}.png`, or a full tile URL template containing `{z}`, `{x}`, and `{y}` |
| `LINECAST_MAPS_CACHE_MB` | Size the map tile cache is swept back to when `maps` starts (default `256`) |
| `LINECAST_CACHE_DIR` | Directory for cached data, used exactly as given |
| `LINECAST_CONFIG_DIR` | Directory for `config.json`, used exactly as given |

Cached data lives in `~/Library/Caches/linecast` on macOS and `~/.cache/linecast` elsewhere; settings in `~/.config/linecast/config.json`. Both honor the `XDG_*` variables, and the `LINECAST_*_DIR` variables above override everything.

</details>

<details>
<summary><strong>Data sources and coverage</strong></summary>

- **Location** — [ipinfo.io](https://ipinfo.io/) for IP geolocation when no location is saved or passed, with [ipwho.is](https://ipwho.is/) and [GeoJS](https://www.geojs.io/) as fallbacks; place names are geocoded by Open-Meteo, with Photon as a fallback.
- **Weather** — [Open-Meteo](https://open-meteo.com/) for forecasts, geocoding, and air quality. Alerts come from the US National Weather Service, Environment Canada, China Meteorological Administration, DWD via Bright Sky, Hong Kong Observatory, Met Éireann, Japan Meteorological Agency, MET Norway, MetService New Zealand, MeteoAlarm (with its warning-region geometry vendored, © EUMETNET, CC BY 4.0, the NUTS regions some feeds file from [Eurostat GISCO](https://ec.europa.eu/eurostat/web/gisco), © EuroGeographics for the administrative boundaries, and Czechia's ORP boundaries from [ČÚZK RÚIAN](https://www.cuzk.gov.cz/) with the [Czech Statistical Office](https://csu.gov.cz/)'s code list, both open data), and SACHET (India's national alert aggregator).
- **Sunshine and Moon** — computed on your device from the astronomical equations; the Moon's face is a vendored grayscale of NASA SVS's [CGI Moon Kit](https://svs.gsfc.nasa.gov/4720) (Lunar Reconnaissance Orbiter, public domain), and the stars around it are the [Yale Bright Star Catalogue](http://tdc-www.harvard.edu/catalogs/bsc5.html) (Hoffleit & Warren, 1991) to magnitude 6.5. The Pacific calendars are checked against the [Western Pacific Regional Fishery Management Council](https://www.wpcouncil.org/educational-resources/lunar-calendars/)'s published calendars and quote its educational materials.
- **Sky** — computed on your device: the stars are the same Yale Bright Star Catalogue, the constellation figures, their names, and the IAU star names are Olaf Frohn's [d3-celestial](https://github.com/ofrohn/d3-celestial) data (BSD), the names in the other languages linecast speaks are [Wikidata](https://www.wikidata.org/)'s labels (CC0), the planets follow Paul Schlyter's equations, and the Milky Way is the diffuse layer of NASA SVS's [Deep Star Maps 2020](https://svs.gsfc.nasa.gov/4851) (public domain). The sky cultures are [Stellarium's collection](https://github.com/Stellarium/stellarium-skycultures), placed from the Hipparcos catalogue; [CULTURES.md](CULTURES.md) has the credits.
- **Tides** — NOAA CO-OPS, Canadian Hydrographic Service, Queensland Open Data, Hong Kong Observatory, Open-Meteo's tide model as a global fallback, and optionally TideCheck.
- **Radar** — [LibreWXR](https://librewxr.net/), with NEXRAD via Iowa Environmental Mesonet and RainViewer as fallbacks; warning polygons come from the US National Weather Service via IEM. The basemap is derived from Natural Earth.
- **Maps** — terrain from AWS/Mapzen elevation tiles; streets and inland water from [OpenFreeMap](https://openfreemap.org/) vector tiles (© OpenMapTiles © OpenStreetMap contributors), with the [OpenStreetMap US Tileservice](https://tiles.openstreetmap.us/) as a fallback (Tiles by OSM US); search from Photon and Nominatim; directions from FOSSGIS OSRM (© OpenStreetMap contributors); globe cloud cover from [LibreWXR](https://librewxr.net/) (CC BY 4.0) satellite imagery; terrain color picks its ramp from a vendored [Köppen-Geiger climate grid](https://doi.org/10.6084/m9.figshare.21789074) (Beck et al. 2023, CC BY 4.0).

</details>

## Contributing

Pull requests are welcome. [ARCHITECTURE.md](ARCHITECTURE.md) is the map of the code. The suite runs with `uv run --with pytest pytest tests -q` and the lint with `uvx ruff check src tests scripts`; both are meant to run without the network and without touching your home directory.

## Lineage

<p align="center">
  <img src="https://raw.githubusercontent.com/ashuttl/linecast/main/screenshots/minitel-terminatel-258.jpg" width="380" alt="3615 LINECAST">
</p>

<p align="center"><em>Prior art.</em></p>

A Telic-Alcatel videotex terminal draws the weather, circa 1990. Photograph from the collection at [minitel-alcatel.fr](https://www.minitel-alcatel.fr/).

## License

[MIT](LICENSE)
