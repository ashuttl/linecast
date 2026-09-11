<div align="center">

# linecast

**Weather, tides, the sun, the moon, the stars, and a globe, drawn for the terminal. The Old Farmer's Almanac meets Minitel.**

[![Tests](https://github.com/ashuttl/linecast/actions/workflows/test.yml/badge.svg)](https://github.com/ashuttl/linecast/actions/workflows/test.yml)
[![PyPI](https://img.shields.io/pypi/v/linecast)](https://pypi.org/project/linecast/)
[![Python](https://img.shields.io/pypi/pyversions/linecast)](https://pypi.org/project/linecast/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

<a href="https://terminaltrove.com/linecast/" title="linecast on Terminal Trove, the $HOME of all things in the terminal"><img src="https://cdn.terminaltrove.com/media/badges/tool_of_the_week/svg/terminal_trove_tool_of_the_week_green_on_dark_grey_bg.svg" alt="Terminal Trove Tool of The Week" height="36"></a>

</div>

![linecast weather, sunshine, tides, and radar tiled on an Omarchy desktop](https://raw.githubusercontent.com/ashuttl/linecast/main/screenshots/hero.png)

linecast turns free public data into seven live, mouse-friendly terminal apps for macOS, Linux, and Windows. It is pure Python with no dependencies, takes its colors from your terminal theme, and needs no accounts or API keys.

| Command | What it shows |
| --- | --- |
| `linecast weather` | A weather forecast with current conditions, an hourly and seven-day forecast, and official alerts for 45 countries |
| `linecast sunshine` | The sun's path across the sky today, and the hours of daylight through the year |
| `linecast moon` | The moon as seen from a given location, with rise and set times and the next full and new moons |
| `linecast sky` | The sky from where you stand: at night, a terminal planetarium shows you the stars, the constellations, the planets, the Moon, and the Milky Way |
| `linecast tides` | A scrollable tide curve shaded by daylight |
| `linecast radar` | Animated weather radar for the whole world, with warnings, temperature, and wind, drawn in the terminal grid |
| `linecast maps` | Street maps, terrain, and a globe you can spin, with live daylight and clouds, place search, and directions |

**[Install](#install) · [Using it](#using-it) · [A closer look](#a-closer-look) · [Settings](#settings) · [Contributing](#contributing)**

## Install

With [homebrew](https://brew.sh/):

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

Or with nothing but curl. [`get.sh`](get.sh) finds whatever Python the machine has and runs linecast with it:

```sh
curl -sL https://raw.githubusercontent.com/ashuttl/linecast/main/get.sh | sh
```

That opens `weather`. End the line with `sh -s sunshine` to open another tool, or `sh -s -- --metric` to pass flags.

<details>
<summary><strong>On Windows</strong></summary>

Use Windows Terminal. Git Bash and mintty look like a pipe rather than a terminal to linecast, so they get static output. On Windows the install adds two packages: `tzdata`, because Windows has no time zone database of its own, and `truststore`, so TLS uses the certificates Windows trusts. Icons are emoji unless you have a Nerd Font set up, in which case `linecast icons nerd` switches to the full set.

</details>

## Using it

Every command opens live, at the place your IP address suggests until you [save a location](#location). Press `?` for the keyboard controls.

Try the commands on their own, or with flags:

```sh
linecast weather --location "quebec"
linecast radar --location 44.35,-68.22
linecast sky --culture hawaiian --location molokai
linecast sunshine --year --location "vostok station"
linecast moon --lang zh
linecast tides --station "Burntcoat Head"
linecast maps --view terrain --location "new zealand"
linecast maps --from "477 congress street 04101" --to "portland head light" --profile bike
linecast maps --view now
```

Add `--print` for one static frame instead of a live view. Weather, sunshine, moon, sky, and tides also have `--json` for their raw data and `--oneline` for a status bar.

![an animated version of the hero screenshot, showing the weather radar moving](https://raw.githubusercontent.com/ashuttl/linecast/main/screenshots/hero.gif)

## A closer look

### Weather

`weather` shows current conditions, a scrollable chart of hourly temperatures shaded by daylight, precipitation, daily highs and lows, air quality, and a line on how today compares with a normal day. Official alerts cover 45 countries. Click one to read it in full, or press `o` to open it in your browser. If the forecast service can't be reached, you get the last forecast it fetched, with a line saying how old it is.

![weather dashboard](https://raw.githubusercontent.com/ashuttl/linecast/main/screenshots/weather.png)

### Sunshine

`sunshine`'s default view is inspired by the Apple Watch Solar Graph face. The sun moves along its arc and the sky changes through dawn, day, dusk, and night. The day length says how much longer or shorter today is than yesterday.

<p align="center">
  <img src="https://raw.githubusercontent.com/ashuttl/linecast/main/screenshots/sunshine-day.png" width="49%" alt="sunshine at midday">
  <img src="https://raw.githubusercontent.com/ashuttl/linecast/main/screenshots/sunshine-dusk.png" width="49%" alt="sunshine at dusk">
</p>

`sunshine --year` draws the whole year. Each column is a day, midnight to midnight, colored by the sky at each hour. Hover the graph for the sunrise, sunset, and day length of any day. Press `v` to switch between the day and the year. Add `--dst` to keep each day on its own clock, so the daylight saving changes show as a harsh step.

![the year view for Westbrook, Maine, with the pointer on the December solstice](https://raw.githubusercontent.com/ashuttl/linecast/main/screenshots/sunshine-year.png)

Near the poles the same chart turns into polar night and midnight sun. These are Longyearbyen and Vostok Station, at 78° north and 78° south.

<p align="center">
  <img src="https://raw.githubusercontent.com/ashuttl/linecast/main/screenshots/sunshine-year-arctic.png" width="49%" alt="the year view for Longyearbyen, Svalbard">
  <img src="https://raw.githubusercontent.com/ashuttl/linecast/main/screenshots/sunshine-year-antarctic.png" width="49%" alt="the year view for Vostok Station, Antarctica">
</p>

### Moon

`moon` draws the phase as you see it from where you are, with the shadow falling where it really does, the maria shaded, earthshine on the night side, and a halo around it. Scroll to move through time: the stars behind it are the real ones for the moment, so the sky turns with the night and the Moon walks through its constellations. Drag the disc to turn the Moon over and see the far side; let go and it settles back. Rise and set times for a place in another time zone are given in that place's local time.

![full Moon](https://raw.githubusercontent.com/ashuttl/linecast/main/screenshots/moon.png)

Press `v` for a calendar of the month, or open on it with `moon --grid`. Each day shows its phase as a small disc, with today, the full and new moons, and the quarters marked. Scroll through the months, hover a day for its phase, moonrise, and moonset, and click one to open the moon on that day.

The moon can also show the date in a traditional calendar beside the phase, with a countdown to its next festival or observance: the Chinese, Japanese, and Korean lunisolar calendars, the Thai lunar calendar, the Hawaiian Kaulana Mahina, the Samoan, Chamorro, and Refaluwasch calendars of the Pacific, the Islamic and Hebrew calendars, and the Old Farmer's Almanac. `moon --calendar hebrew` opens on one and `linecast calendar` saves one. [CALENDARS.md](CALENDARS.md) describes each of them and how it is checked.

<p align="center">
  <img src="https://raw.githubusercontent.com/ashuttl/linecast/main/screenshots/moon-okinawa.png" width="49%" alt="the moon over Okinawa in Japanese: 十六夜, the sixteenth night of the eighth month">
  <img src="https://raw.githubusercontent.com/ashuttl/linecast/main/screenshots/moon-calendar.png" width="49%" alt="the month calendar for September 2026 in Japanese, with 十五夜 on the 25th and the pointer on it">
</p>

### Sky

`sky` draws the sky from where you stand. The horizon runs along the bottom with the compass points under it, and above it are the real stars for the moment, the constellation figures drawn faintly through them with their names, the planets from Mercury to Neptune marked and named, the Moon at its phase and tilt, and the Milky Way once the sky is dark enough. By day the sky is blue and holds only the Sun, and perhaps Venus. Scroll into the evening and the sky goes through its twilight colors while the stars come out one by one, brightest first.

Drag to look around. The sky opens with the 8,404 stars the naked eye can see. Zoom in and nearly 117,000 fainter ones come out, with more names, and the 107 Messier galaxies, clusters, and nebulae appear as faint glows; the Moon grows into the disc the moon view draws. Zoom all the way out while looking up and the horizon closes into a circle, the whole sky at once, the way the almanacs print it. Press `p` to play time forward, an hour a second, then a day, then a week, so you can watch the stars wheel and the Moon run through its phases. Point at anything for its name. To open the view where you want it, add `--facing SW` or `--fov 40`.

Press `/` and type the name of a star, a planet, a constellation, or an asterism like the Big Dipper, and the view flies to it. If it is below the horizon the panel says when it rises and where, and you can press Enter to move the clock to that moment. `sky --at Jupiter` opens on it.

The sky has been drawn many ways. Press `t` for a list of twenty-two traditions besides the IAU's, each with its own figures and star names, and the sky redraws as you move through the list: the Chinese Three Enclosures and Twenty-Eight Mansions, the Hawaiian star lines, the Boorong sky of Victoria, the Norse, Sami, Māori, Tongan, Mongolian, Romanian, Belarusian, and Indian Vedic skies, H. A. Rey's stick figures, and more. `sky --culture hawaiian` opens on one and `linecast culture` saves one. The Hawaiian sky replaces the compass points with the navigators' star compass, thirty-two houses from Hikina round to Komohana. [CULTURES.md](CULTURES.md) lists them with their sources.

### Tides

`tides` draws the tide curve across several days and marks the highs, the lows, and the predicted water level now. Scroll to move through time.

Predictions come from the national tide services in the US, Canada, Queensland, and Hong Kong, and from Open-Meteo's global tide model everywhere else. A [TideCheck](https://tidecheck.com/) key adds more named stations. `tides --nearby` lists the closest stations, and `tides --station` picks one by name or id.

![tide chart](https://raw.githubusercontent.com/ashuttl/linecast/main/screenshots/tides.png)

### Radar

`radar` animates the recent observations and an hour of forecast over a braille map, with US weather warnings drawn on top. Temperature and wind layers are there if you want them, and you can press `S` for satellite imagery.

Real radar is only available where it is published openly: North America, Europe, and parts of East and Southeast Asia. Everywhere else, LibreWXR fills in with a precipitation model, and it looks like one.

Rain takes its colors from your terminal theme; if the theme is monochrome, so is the rain. There are a few fixed themes as well, `dusk`, `ember`, `ink`, and `marangai`, plus LibreWXR's own. Press `t` to switch.

```sh
linecast radar --theme dusk         # a fixed color theme
linecast radar --layers temp,wind   # add temperature and wind
linecast radar --layer satellite    # open on satellite imagery
```

Add `--source librewxr`, `--source rainviewer`, or `--source iem` to pin the radar to one source, if you want to compare what each shows over the same spot.

![animated radar forecast over Glasgow](https://raw.githubusercontent.com/ashuttl/linecast/main/screenshots/radar.gif)

### Maps

`maps` draws streets in braille over water, land, parks, and buildings in solid color. `maps --view terrain` shades the land by height and lights it from one side, like a relief map, with coastlines, borders, water, and cities in braille over it. Press `v` to switch between the two.

Press `/` to search for a place, or `D` to ask for directions, which open as a panel of turn-by-turn steps. Arrow or click through them and the map flies along the route.

<p align="center">
  <img src="https://raw.githubusercontent.com/ashuttl/linecast/main/screenshots/maps-street.png" width="49%" alt="street map of Portland, Maine">
  <img src="https://raw.githubusercontent.com/ashuttl/linecast/main/screenshots/maps-terrain.png" width="49%" alt="terrain map of the Alps around Innsbruck">
</p>

Zoom all the way out and either view becomes a globe. Drag to rotate it, or press `r` to set it spinning. Press `S` to shade it into the daylight of this moment, with the terminator creeping and cities glowing on the night side, and `c` to lay the current cloud cover over it from live satellite imagery. `maps --view now` opens straight to the full picture.

![the globe as it is right now: live daylight and the terminator](https://raw.githubusercontent.com/ashuttl/linecast/main/screenshots/maps-globe.png)

```sh
# a street map, zoomed in
linecast maps --location "Portland, Maine" --zoom 0.01
# the fjords around Bergen
linecast maps --view terrain --location 60.4,5.3 --zoom 8
# the globe as it is right now
linecast maps --view now
# walking directions
linecast maps --from "Gorham, Maine" --to "Portland Head Light" --profile foot
```

## Settings

Settings are saved in `~/.config/linecast/config.json`. A flag on the command line beats an environment variable, which beats a saved setting. Run any settings command below with no argument to see its current value, and with `auto` to go back to the default.

### Location

Save a location once and every command uses it, or pass one for a single run:

```sh
linecast location set "Portland, Maine"   # by name
linecast location set 44.54,-68.42        # or by lat,lng
linecast location search fayette          # list the places a name could mean
linecast location auto                    # back to guessing from your IP address
linecast weather --location "Bar Harbor"  # just this once
```

A name is looked up once and the first match is saved; `search` shows the other matches if that was the wrong place.

If you don't save a location or pass one in a flag, linecast asks [ipinfo.io](https://ipinfo.io/) where your network connection is. That is usually the right city, sometimes the wrong one, and far off on a VPN or corporate network. The answer is cached for an hour. Save a location and the request is never made.

### Units and clock

By default, linecast uses imperial units in the United States and metric everywhere else. Times use the 12-hour clock where people write 6:50 pm and the 24-hour clock everywhere else. Run these commands once to remember your preferences:

```sh
linecast units metric
linecast clock 24
```

Every view command also takes `--metric` and `--imperial` for one run, and the ones that show times take `--12h` and `--24h`. `weather` adds `--celsius` and `--fahrenheit` for the temperature alone, so you can have miles and Celsius, say.

### Language

linecast speaks your terminal's language if it is one of the eighteen it knows, and English otherwise. To choose one yourself, for every run or for one:

```sh
linecast language es        # use Spanish every time
linecast language auto      # follow the terminal again
linecast radar --lang zh    # just this once
```

The languages are English (`en`), French (`fr`), Spanish (`es`), German (`de`), Italian (`it`), Portuguese (`pt`), Dutch (`nl`), Polish (`pl`), Norwegian (`no`), Swedish (`sv`), Icelandic (`is`), Danish (`da`), Finnish (`fi`), Japanese (`ja`), Korean (`ko`), Chinese (`zh`), Thai (`th`), and Indonesian (`id`).

In India, many alerts are published in the state language. Add `--lang hi`, `--lang te`, `--lang mr`, or another Indian language code to `weather` to read them in that language where it exists; the rest of the app stays in English.

### Calendar

Run `moon` in Chinese, Japanese, Korean, or Thai and it uses that language's traditional calendar. To choose one yourself, for every run or for one:

```sh
linecast calendar hebrew            # use the Hebrew calendar every time
linecast calendar none              # no traditional calendar
linecast calendar auto              # follow the language again
linecast moon --calendar hawaiian   # just this once
```

The calendars are `chinese`, `japanese`, `korean`, `thai`, `hawaiian`, `samoan`, `chamorro`, `refaluwasch`, `islamic`, `hebrew`, and `almanac`. There's more about each in [CALENDARS.md](CALENDARS.md).

### Culture

Run `sky` in Chinese and it draws the Chinese sky; in any other language it draws the IAU constellations. To choose one of the twenty-two traditions yourself, for every run or for one:

```sh
linecast culture hawaiian           # use the Hawaiian sky every time
linecast culture none               # the IAU constellations
linecast culture auto               # follow the language again
linecast sky --culture hawaiian     # just this once
```

Use `t` in `sky` to choose one from a list. The names are in [CULTURES.md](CULTURES.md), with the credits for each.

### Color and icons

linecast asks the terminal for its palette so its colors match your theme. Set `LINECAST_COLOR` to `truecolor`, `256`, `16`, or `none` to choose the color mode yourself. `NO_COLOR` is honored.

Icons come in three sets: [Nerd Font](https://www.nerdfonts.com/) glyphs in terminals that bundle them (WezTerm, kitty, Ghostty), emoji in other terminals, and plain Unicode when piped. If you have installed a Nerd Font in another terminal, linecast can't tell, so say so once:

```sh
linecast icons nerd
```

Add `--icons nerd`, `--icons emoji`, or `--icons plain` to pick a set for one run. `linecast doctor` shows a glyph from each set, so you can see which ones your font can draw.

### Short names and shell completion

`linecast link` adds `weather`, `sunshine`, `moon`, `sky`, `tides`, `radar`, and `maps` as commands beside `linecast`, skipping any name that is already taken; `linecast link --remove` takes them away. A shell alias does the same job.

To turn on shell completion:

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

Start here:

```sh
linecast doctor             # what linecast sees
linecast doctor --offline   # the same, without the network checks
linecast doctor --json      # the thing to paste into a bug report
```

`linecast doctor` reports the version, the settings and cache paths, what the terminal said about itself, which settings are in force and where each came from, and whether each data provider answered. Secrets show as "(set)", never their value.

Every view command and `linecast doctor` take `--debug`, which prints a line on stderr for each fallback taken along the way, such as a provider that did not answer, and what was shown instead.

<details>
<summary><strong>Environment variables</strong></summary>

| Variable | Description |
| --- | --- |
| `WEATHER_LOCATION` | Default location, as `lat,lng` or a place name; overrides the saved location |
| `LINECAST_UNITS` | `metric` or `imperial` for every command; overrides the saved units |
| `WEATHER_UNITS` | Units for the weather command; overrides `LINECAST_UNITS` |
| `TIDES_UNITS` | Units for tide heights; overrides `LINECAST_UNITS` |
| `LINECAST_CLOCK` | `12` or `24`; overrides the saved clock |
| `LINECAST_LANG` | One of the language codes under [Language](#language); overrides the saved language and the terminal's locale |
| `LINECAST_ICONS` | `nerd`, `emoji`, or `plain`; overrides the saved icons |
| `LINECAST_COLOR` | `auto`, `truecolor`, `256`, `16`, or `none` |
| `NO_COLOR` | Any non-empty value disables ANSI colors |
| `CLICOLOR` / `CLICOLOR_FORCE` | `CLICOLOR=0` disables color; a non-zero `CLICOLOR_FORCE` keeps it on when output is not a terminal |
| `LINECAST_THEME` | `auto` (default), or `classic` / `legacy` / `off` for the fixed palette |
| `LINECAST_THEME_TIMEOUT_MS` | How long, in milliseconds, to wait for the terminal to answer the palette query (default `100`, or `500` over SSH) |
| `LINECAST_WIDTH_TIMEOUT_MS` | How long, in milliseconds, to wait for the terminal to say how wide it draws emoji and other glyphs (default `150`, or `600` over SSH) |
| `LINECAST_THEME_POLL` | Seconds between re-reading the terminal palette in live views, so a theme switch re-inks the view in place (default `2`; `0` disables) |
| `LINECAST_THEME_WATCH` | A file whose modification marks a desktop theme change, prompting an immediate re-read (default: Omarchy's current-theme marker; empty disables) |
| `TIDE_STATION` | Default tide station ID |
| `LINECAST_TIDECHECK_KEY` | Optional TideCheck API key for global tide coverage |
| `LINECAST_TIDECHECK_PAID` | Set to `1` on a paid TideCheck plan, and linecast stops holding itself to the free tier's 50 requests a day |
| `LINECAST_RADAR_THEME` | Default radar color theme |
| `LINECAST_RADAR_SOURCE` | Pin the radar frame source: `librewxr`, `rainviewer`, or `iem` |
| `LINECAST_RADAR_LAYER` | `radar` (default) or `satellite`, the imagery `radar` opens with |
| `LINECAST_RADAR_LAYERS` | Layers `radar` opens with: `temp`, `wind`, or `temp,wind` |
| `LINECAST_SUNSHINE_YEAR_PALETTE` | `dial` (default) for the Solar Dial colors in `sunshine --year`, or `graph` for the day view's own sky |
| `LINECAST_LIBREWXR_URL` | Base URL of a self-hosted LibreWXR instance |
| `LINECAST_VECTOR_TILES_URL` | TileJSON URL of a self-hosted street tile server, used instead of OpenFreeMap with no fallback |
| `LINECAST_ELEVATION_URL` | Elevation tile source for `maps`: a bucket root holding `terrarium/{z}/{x}/{y}.png`, or a full tile URL template containing `{z}`, `{x}`, and `{y}` |
| `LINECAST_MAPS_CACHE_MB` | Size, in megabytes, that `maps` trims its tile cache back to when it starts (default `256`) |
| `LINECAST_CACHE_DIR` | Directory for cached data, used exactly as given |
| `LINECAST_CONFIG_DIR` | Directory for `config.json`, used exactly as given |

Cached data lives in `~/Library/Caches/linecast` on macOS and `~/.cache/linecast` elsewhere; settings in `~/.config/linecast/config.json`. Both honor the `XDG_*` variables, and the `LINECAST_*_DIR` variables above override everything.

</details>

<details>
<summary><strong>Data sources and coverage</strong></summary>

- **Location** — [ipinfo.io](https://ipinfo.io/) for IP geolocation when no location is saved or passed, with [ipwho.is](https://ipwho.is/) and [GeoJS](https://www.geojs.io/) as fallbacks; place names are geocoded by Open-Meteo, with Photon as a fallback.
- **Weather** — [Open-Meteo](https://open-meteo.com/) for forecasts, geocoding, and air quality (in India on the CPCB's National AQI scale). Alerts come from the US National Weather Service, Environment Canada, China Meteorological Administration, DWD via Bright Sky, Hong Kong Observatory, Met Éireann, Japan Meteorological Agency, MET Norway, MetService New Zealand, MeteoAlarm (with its warning-region geometry vendored, © EUMETNET, CC BY 4.0, the NUTS regions some feeds file from [Eurostat GISCO](https://ec.europa.eu/eurostat/web/gisco), © EuroGeographics for the administrative boundaries, and Czechia's ORP boundaries from [ČÚZK RÚIAN](https://www.cuzk.gov.cz/) with the [Czech Statistical Office](https://csu.gov.cz/)'s code list, both open data), and SACHET (India's national alert aggregator).
- **Sunshine and Moon** — computed on your device from the astronomical equations; the Moon's face is a vendored grayscale of NASA SVS's [CGI Moon Kit](https://svs.gsfc.nasa.gov/4720) (Lunar Reconnaissance Orbiter, public domain), and the stars around it are the [Yale Bright Star Catalogue](http://tdc-www.harvard.edu/catalogs/bsc5.html) (Hoffleit & Warren, 1991) to magnitude 6.5. The Pacific calendars are checked against the [Western Pacific Regional Fishery Management Council](https://www.wpcouncil.org/educational-resources/lunar-calendars/)'s published calendars and quote its educational materials.
- **Sky** — computed on your device: the bright stars are the same Yale Bright Star Catalogue, with 108,520 fainter stars from David Nash's [HYG v4.1](https://github.com/astronexus/HYG-Database) (CC BY-SA 4.0) revealed as you zoom in; [star data credits](src/linecast/data/STARS.md) describe the bundled supplement. The 107 Messier galaxies, nebulae and clusters, the constellation figures, their names, and the IAU star names are Olaf Frohn's [d3-celestial](https://github.com/ofrohn/d3-celestial) data (BSD), the names in the other languages linecast speaks are [Wikidata](https://www.wikidata.org/)'s labels (CC0), the planets follow Paul Schlyter's equations, and the Milky Way is the diffuse layer of NASA SVS's [Deep Star Maps 2020](https://svs.gsfc.nasa.gov/4851) (public domain). The sky cultures are [Stellarium's collection](https://github.com/Stellarium/stellarium-skycultures), placed from the Hipparcos catalogue; [CULTURES.md](CULTURES.md) has the credits.
- **Tides** — NOAA CO-OPS, Canadian Hydrographic Service, Queensland Open Data, Hong Kong Observatory, Open-Meteo's tide model as a global fallback, and optionally TideCheck.
- **Radar** — [LibreWXR](https://librewxr.net/), with NEXRAD via Iowa Environmental Mesonet and RainViewer as fallbacks; warning polygons come from the US National Weather Service via IEM. The basemap is derived from Natural Earth.
- **Maps** — terrain from AWS/Mapzen elevation tiles; streets and inland water from [OpenFreeMap](https://openfreemap.org/) vector tiles (© OpenMapTiles © OpenStreetMap contributors), with the [OpenStreetMap US Tileservice](https://tiles.openstreetmap.us/) as a fallback (Tiles by OSM US); search from Photon and Nominatim; directions from FOSSGIS OSRM (© OpenStreetMap contributors); globe cloud cover from [LibreWXR](https://librewxr.net/) (CC BY 4.0) satellite imagery; terrain color picks its ramp from a vendored [Köppen-Geiger climate grid](https://doi.org/10.6084/m9.figshare.21789074) (Beck et al. 2023, CC BY 4.0).

</details>

## Contributing

Pull requests are welcome. [ARCHITECTURE.md](ARCHITECTURE.md) is the map of the code.

```sh
uv run --with pytest pytest tests -q   # tests
uvx ruff check src tests scripts       # lint
```

Both are meant to run without the network and without touching your home directory.

## Lineage

<p align="center">
  <img src="https://raw.githubusercontent.com/ashuttl/linecast/main/screenshots/minitel-terminatel-258.jpg" width="380" alt="3615 LINECAST">
</p>

<p align="center"><em>Prior art.</em></p>

A Telic-Alcatel videotex terminal draws the weather, circa 1990. Photograph from the collection at [minitel-alcatel.fr](https://www.minitel-alcatel.fr/).

## License

[MIT](LICENSE)
