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

linecast turns free public data into six live, mouse-friendly terminal apps for macOS, Linux, and Windows. It is pure Python with no third-party dependencies (two on Windows), tries to match your terminal theme, and needs no accounts or API keys.

| Command | What it shows |
| --- | --- |
| `linecast weather` | Current conditions, an hourly braille temperature curve, a seven-day forecast, air quality, how today compares with a normal day, and official alerts |
| `linecast sunshine` | The sun on its daily arc, with the color of the sky, day length, and moon phase |
| `linecast moon` | The moon as seen from where you are, with illumination, altitude, rise and set times, and the next full and new moons |
| `linecast tides` | A tide curve shaded by daylight, the current water level, and the times of high and low tide |
| `linecast radar` | Animated radar or satellite imagery for the whole world, warning polygons, temperature, and wind |
| `linecast maps` | Street maps, terrain, and a globe you can spin, with live daylight and clouds, place search, and directions |

## Install

```sh
brew install linecast
```

Or with [uv](https://docs.astral.sh/uv/):

```sh
uv tool install linecast
```

`pipx install linecast` and `pip install linecast` work too, and there are community-maintained packages in the [AUR](https://aur.archlinux.org/packages/linecast) and in [nixpkgs](https://search.nixos.org/packages?channel=unstable&show=linecast) (unstable channel, for now). linecast needs Python 3.10 or newer on macOS, Linux, or Windows.

To try it before installing anything:

```sh
uvx linecast weather
```

Or with nothing but curl — [`get.sh`](get.sh) runs linecast with whatever the machine has, down to plain `python3`:

```sh
curl -sL https://raw.githubusercontent.com/ashuttl/linecast/main/get.sh | sh
```

It opens `weather`; name another tool with `sh -s sunshine`, or pass flags with `sh -s -- --metric`.

<details>
<summary><strong>On Windows</strong></summary>

Use Windows Terminal; Git Bash and mintty see a pipe rather than a terminal, so they get static output. The install adds two packages: `tzdata`, because Windows has no IANA time zone database, and `truststore`, for TLS verification through the OS certificate store. Icons default to emoji in Windows Terminal; with a Nerd Font installed and selected, `linecast icons nerd` switches to the full set.

</details>

## Using it

Every command opens in live mode when run in a terminal, set to where your IP address says you are unless you have [saved a location](#location).

```sh
linecast weather --location "Québec"
linecast radar --location 41.88,-87.63
linecast maps --view terrain --location "Innsbruck"
linecast maps --to "Portland Head Light" --profile bike
```

`--print` gives one static frame, and piped output gets one automatically. Weather, sunshine, moon, and tides also have `--json`, and a short `--oneline` for status bars.

![an animated version of the hero screenshot, showing the weather radar moving](https://raw.githubusercontent.com/ashuttl/linecast/main/screenshots/hero.gif)

## A closer look

### Weather

The dashboard combines current conditions, hourly temperatures shaded by daylight, precipitation, daily ranges, air quality, and a line on how today compares with a normal day. Official alerts cover 45 countries; click one to read it in full, or press `o` to open it in your browser. In India, air quality is shown on the CPCB's National AQI scale.

![weather dashboard](https://raw.githubusercontent.com/ashuttl/linecast/main/screenshots/weather.png)

### Sunshine and Moon

`sunshine` is inspired by the Apple Watch Solar face. The arc and sky move through dawn, day, dusk, and night, and the day length comes with how much longer or shorter it is than yesterday.

<p align="center">
  <img src="https://raw.githubusercontent.com/ashuttl/linecast/main/screenshots/sunshine-day.png" width="49%" alt="sunshine at midday">
  <img src="https://raw.githubusercontent.com/ashuttl/linecast/main/screenshots/sunshine-dusk.png" width="49%" alt="sunshine at dusk">
</p>

`linecast sunshine --year` draws a whole year instead of one day. Each column is a day, running from midnight at the top to midnight at the bottom, and every point in it takes the color of the sky at that hour. Sunrise and sunset emerge where the night colors meet the day colors. Hover over a day to see its sunrise, sunset and day length, along with the time and the sky under the pointer. In live mode, `v` (or `y`) switches between the day view and the year view. `--dst` plots each day in its own clock, so the clock changes show as steps.

![the year view for Westbrook, Maine, with the pointer on the December solstice](https://raw.githubusercontent.com/ashuttl/linecast/main/screenshots/sunshine-year.png)

Near the poles the same chart turns into polar night and midnight sun. These are Longyearbyen and Vostok Station, at 78° north and 78° south.

<p align="center">
  <img src="https://raw.githubusercontent.com/ashuttl/linecast/main/screenshots/sunshine-year-arctic.png" width="49%" alt="the year view for Longyearbyen, Svalbard">
  <img src="https://raw.githubusercontent.com/ashuttl/linecast/main/screenshots/sunshine-year-antarctic.png" width="49%" alt="the year view for Vostok Station, Antarctica">
</p>

`moon` draws the current phase as you would see it from your location, with the shadow falling where it really does, the maria shaded, and a halo around it. Scroll to move through time. `linecast moon --oneline` fits a status bar.

In live mode, `v` flips to a calendar: the month laid out week by week, each day carrying its phase as a small shaded disc, with today, the full and new moons, and the quarters marked. Scroll to page through the months, and hover over a day for its phase, moonrise, and moonset. When a traditional calendar is active the grid carries its reading too — the 农历 day names, the lunar month starts, the festivals, the pō mahina — and the pop-up gives the full lunar date. Click a day and the disc view opens on it.

In Chinese, Japanese, and Korean the moon also follows the traditional calendar: the lunar date sits beside the phase name — and in Japanese the night is called by its own name, 十六夜, 居待月, 更待月 — with the solar term in progress and a countdown to the next festival, 中秋节, 추석, or 十五夜. Any language can ask for any of the three with `--calendar chinese`, `japanese`, or `korean`, written with the customary English names ("End of Heat · White Dew Sep 7", "Mid-Autumn Festival Sep 25"). The months, leap months, and solar terms are all computed from the ephemeris at each calendar's own meridian; nothing is looked up.

In Thai the moon follows the Thai lunar calendar, ปฏิทินจันทรคติไทย: the waxing or waning day sits beside the phase in Thai numerals, as the printed calendars have it — แรม ๔ ค่ำ เดือน ๙ — with the year's animal, a countdown to the next วันพระ (the four Buddhist holy days of each month), and the coming festival, มาฆบูชา through ลอยกระทง. This calendar is arithmetic rather than astronomical: the months run on the old Suriyayart reckoning, in which 800 solar years are exactly 292207 days — the same integer bookkeeping behind every printed Thai calendar, checked against the official holy days of 2023–2026. Any language can ask for it with `--calendar thai` ("month 9 · waning 4", "Loy Krathong Nov 24").

`--calendar hawaiian` follows the Kaulana Mahina, which names every night: Hilo, Hoaka, the Kū and ʻOle nights, through Māhealani, Kāne, and Muku, each in its ten-night anahulu — hoʻonui waxing, poepoe round, hōʻemi waning. The month begins at Hilo, the first night the young crescent can be seen, so it is computed as a visibility date — crescent geometry in the evening sky over Hawaiʻi, not a fixed step from the new moon — and checked against every month of the [Western Pacific Regional Fishery Management Council's published calendars](https://www.wpcouncil.org/educational-resources/lunar-calendars/). The panel carries the Council's counsel for the night — the four monthly kapu periods, the unproductive ʻOle nights, and each anahulu's fishing outlook — quoted from their educational materials, with a Source: wpcouncil.org line under it.

`--calendar samoan` and `--calendar chamorro` follow the Council's American Samoa and Guam calendars the same way. Each names thirty nights, Masina Fou through Masina Maunā and Sinahen Håcha through Sinahi, beginning the first evening the crescent can be seen over Pago Pago Harbor or Hagåtña, and each is checked against every month the Council has printed since 2021. `--calendar refaluwasch` shows the CNMI edition: the CHamoru night with its Refaluwasch name beside it on the eleven nights that tradition names, Sighauru through Arofú. In a few months of the 2021 to 2025 editions the printed start departs from the visibility data it otherwise follows; the tests list them, and every month of the 2026 calendars matches to the night.

`--calendar islamic` follows the Umm al-Qura calendar, Saudi Arabia's civil calendar, which is the one Islamic calendar a program can compute: since 1423 AH its rule is geometric — a month begins the day after the first sunset at Mecca that follows the new moon with the Moon still above the horizon — and linecast evaluates it from the same ephemeris the rest of the app draws with. Checked against the published calendar for 1423 through 1500 AH, it matches every month but one, in 2006, where the new moon fell five minutes before Mecca's sunset by one reckoning and after it by the other. The Hijri date sits beside the phase (23 Ramadan 1447 AH) and turns at your own sunset, since the Hijri day begins in the evening; the coming month and the next observance follow with their civil dates — Islamic New Year, Ashura, Mawlid, the start of Ramadan, Laylat al-Qadr, Eid al-Fitr, the Day of Arafah, and Eid al-Adha. The months are transliterated in every language (Indonesian gets its own spellings, Ramadan, Syawal, Zulhijah), and the month grid marks each month's first day and the observances. Most countries begin Ramadan and the Eids on a sighting of the crescent, so a country's announced dates may differ from these by a day; Saudi Arabia's own announcements sometimes do.

`--calendar hebrew` follows the Hebrew calendar, which has been pure arithmetic since the fourth century: the year begins at the mean new moon of Tishrei, moved by the four postponement rules, and a thirteenth month, Adar I, comes seven times in nineteen years. linecast computes it from those rules (Dershowitz and Reingold's *Calendrical Calculations* is the reference) and the tests pin every month of 5780 through 5790 and every holiday of 2023 through 2026 against Hebcal. The date sits beside the phase (20 Elul 5786) and turns at your own sunset, since the Hebrew day begins in the evening; the coming month and the next holiday follow with their civil dates — Rosh Hashanah, Yom Kippur, Sukkot, Shemini Atzeret, Simchat Torah, Hanukkah, Tu BiShvat, Purim, Pesach, Shavuot, and Tisha B'Av — and on the day before a holiday the countdown says it begins at sunset. The holidays are the diaspora observance, the second days included, since that is what a reader outside Israel keeps. Hebrew is not one of the app's languages, so the months and holidays are transliterated in every language; the month grid names each holiday's days and marks the month starts, and the hover chip notes each Rosh Chodesh. `--json` adds the date in Hebrew letters as well, כ׳ אלול תשפ״ו, for a consumer that can lay Hebrew out.

`--calendar almanac` reads the moon the way the Old Farmer's Almanac does — the same kind of tradition, from the English-language side: the light or dark of the moon beside the phase, what each half favors in the garden, and the day's solunar activity periods — the majors when the Moon crosses the meridian above or below, the minors at moonrise and moonset. The almanac's full-moon names (Harvest, Wolf, and the rest) belong to it too: they show there and in the plain English view, while a panel following another tradition's calendar keeps the plain phase name.

Point `sunshine` or `moon` somewhere across an ocean and the rise and set times come back in that place's local clock.

![full Moon](https://raw.githubusercontent.com/ashuttl/linecast/main/screenshots/moon.png)

### Tides

The tide chart runs across several days and marks the highs, the lows, and the current predicted water level. Scroll to move through time.

Predictions come from the national services where they exist — NOAA in the US, the Canadian Hydrographic Service, Queensland Open Data, and the Hong Kong Observatory — and from Open-Meteo's global tide model everywhere else. An optional [TideCheck](https://tidecheck.com/) key adds more named stations. `linecast tides --nearby` lists the closest stations; `linecast tides --station <id or name>` pins one.

![tide chart](https://raw.githubusercontent.com/ashuttl/linecast/main/screenshots/tides.png)

### Radar

Radar animates recent observations and an hour of forecast over a braille basemap.

Real radar exists only where open composites are published: North America, Europe, and parts of East and Southeast Asia. Elsewhere, LibreWXR fills in with a precipitation model, and it looks like one. US warning polygons are drawn too, along with optional temperature and wind layers and hourly infrared satellite imagery.

Rain is drawn in colors taken from your terminal theme; if the theme is monochrome, so is the rain. There are a few fixed themes as well — `dusk`, `ember`, `ink`, and `marangai` — plus LibreWXR's server-rendered ones. Press `t` to switch.

```sh
linecast radar --theme dusk
linecast radar --layers temp,wind
linecast radar --layer satellite
```

`--source librewxr`, `--source rainviewer`, or `--source iem` pins one frame source instead of routing by location, for comparing what each shows over the same spot.

![animated radar forecast over Glasgow](https://raw.githubusercontent.com/ashuttl/linecast/main/screenshots/radar.gif)

### Maps

Maps draws the streets in braille over water, land, parks, and buildings filled in solid color.

In terrain view, the land is shaded by height and lit from one side, like a relief map. Coastlines, borders, water, and cities are drawn over it in braille; `l` toggles them and the labels.

Search with `/` and ask for directions with `d`. Directions open as a panel of turn-by-turn steps; arrow or click through them and the map flies along the route.

<p align="center">
  <img src="https://raw.githubusercontent.com/ashuttl/linecast/main/screenshots/maps-street.png" width="49%" alt="street map of Portland, Maine">
  <img src="https://raw.githubusercontent.com/ashuttl/linecast/main/screenshots/maps-terrain.png" width="49%" alt="terrain map of the Alps around Innsbruck">
</p>

Zoom all the way out and either view becomes a globe you can rotate by dragging, or set spinning with `r`. Two keys switch on the sky as it is right now: `s` shades the planet into actual daylight, with a creeping terminator and cities glowing on the night side, and `c` lays the current global cloud cover over it from live satellite imagery. `linecast maps --view now` opens straight to the full picture.

![the globe as it is right now: live daylight and the terminator](https://raw.githubusercontent.com/ashuttl/linecast/main/screenshots/maps-globe.png)

Everything is a single key — `?` shows this list in the app:

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

`set` takes a place name or exact `lat,lng` coordinates. A name is looked up once, on the spot, and the first match is saved; `search` lists the candidates when the first match might not be the right one. A command's `--location` flag or `WEATHER_LOCATION` wins over the saved location.

With no location saved or passed, linecast falls back to IP geolocation: a single anonymous request to [ipinfo.io](https://ipinfo.io/) (or to ipwho.is or GeoJS if it doesn't answer), which returns the rough position of your network connection — usually the right city, sometimes the wrong one, and off by a lot on a VPN or corporate network. The answer is cached for an hour. Save a location, or set any override, and the request is not made at all.

### Units

Units follow the location: imperial in the United States, metric everywhere else. Either can be pinned for every command:

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

Use `--lang` or `LINECAST_LANG` to pick the language. There are eighteen:

> English, French, Spanish, German, Italian, Portuguese, Dutch, Polish, Norwegian, Swedish, Icelandic, Danish, Finnish, Japanese, Korean, Chinese, Thai, and Indonesian

```sh
linecast weather --lang fr
linecast radar --lang zh
```

In India, alerts go one step further: SACHET publishes many of them in the state language, and `--lang hi`, `te`, `or`, `mr`, or another Indian language code shows that regional text where it exists, while the rest of the app stays in English.

### Calendar

The moon's traditional calendar follows the language: Chinese with `--lang zh`, Japanese with `ja`, Korean with `ko`, Thai with `th`, none otherwise. Pin one — the Pacific calendars, the Islamic and Hebrew calendars, and the Old Farmer's Almanac included — or none, for every run:

```sh
linecast calendar chinese
linecast calendar thai
linecast calendar hawaiian
linecast calendar samoan
linecast calendar chamorro
linecast calendar refaluwasch
linecast calendar islamic
linecast calendar hebrew
linecast calendar almanac
linecast calendar none
linecast calendar
linecast calendar auto
```

`moon` takes `--calendar` for one run.

### Color and icons

linecast asks the terminal for its palette so its colors belong in your theme. Set `LINECAST_COLOR` to `truecolor`, `256`, `16`, or `none` to choose the color mode yourself, or use the standard `NO_COLOR` variable.

Icons come in three sets: [Nerd Font](https://www.nerdfonts.com/) glyphs in terminals that bundle them (WezTerm, kitty, Ghostty), emoji in other terminals, and plain Unicode when output is piped. If you have installed a Nerd Font in Alacritty, foot, or iTerm2, linecast cannot tell, so say so once:

```sh
linecast icons nerd
linecast icons emoji
linecast icons plain
linecast icons
linecast icons auto
```

`--icons` and `LINECAST_ICONS` pick a set for one run, and `linecast doctor` shows a glyph from each so you can see what your font renders.

### Short names

If you'd rather type `weather` than `linecast weather`, `linecast link` makes `weather`, `sunshine`, `moon`, `tides`, `radar`, and `maps` as links beside the `linecast` binary, skipping any name something else already owns; `linecast link --remove` takes them away. A shell alias does the same job.

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

Completion covers `linecast <command>` and the short names, for anyone who aliased or linked them.

### When something looks wrong

```sh
linecast doctor
linecast doctor --offline
linecast doctor --json
```

`linecast doctor` reports the build, the settings and cache paths, what the terminal advertised, which settings are in force and where each came from, and whether each data provider answered. Secrets show as "(set)", never their value. `--offline` skips the probes; `--json` is the thing to paste into a bug report.

The six view commands and `linecast doctor` take `--debug`, which prints a line on stderr for each fallback taken along the way — a provider that did not answer, a tile that would not decode — and what was shown instead.

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
| `LINECAST_LANG` | UI language code: `en`, `fr`, `es`, `de`, `it`, `pt`, `nl`, `pl`, `no`, `sv`, `is`, `da`, `fi`, `ja`, `ko`, `zh`, `th`, or `id` |
| `LINECAST_RADAR_THEME` | Default radar color theme |
| `LINECAST_RADAR_SOURCE` | Pin the radar frame source: `librewxr`, `rainviewer`, or `iem` |
| `LINECAST_RADAR_LAYER` | `radar` (default) or `satellite`, the imagery `radar` opens with |
| `LINECAST_RADAR_LAYERS` | Overlays `radar` opens with, `temp`, `wind`, or both comma-separated |
| `LINECAST_SUNSHINE_YEAR_PALETTE` | `dial` (default) for the Solar Dial colors in `sunshine --year`, or `graph` for the day view's own sky |
| `LINECAST_LIBREWXR_URL` | Base URL of a self-hosted LibreWXR instance |
| `LINECAST_VECTOR_TILES_URL` | TileJSON URL of a self-hosted street tile server, used instead of OpenFreeMap with no fallback |
| `LINECAST_ELEVATION_URL` | Elevation tile source for `maps`: a bucket root holding `terrarium/{z}/{x}/{y}.png`, or a full tile URL template containing `{z}`, `{x}`, and `{y}` |
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

- **Location** — [ipinfo.io](https://ipinfo.io/) for IP geolocation when no location is saved or passed, with [ipwho.is](https://ipwho.is/) and [GeoJS](https://www.geojs.io/) as fallbacks; place names are geocoded by Open-Meteo, with Photon as a fallback.
- **Weather** — [Open-Meteo](https://open-meteo.com/) for forecasts, geocoding, and air quality. Alerts come from the US National Weather Service, Environment Canada, China Meteorological Administration, DWD via Bright Sky, Hong Kong Observatory, Met Éireann, Japan Meteorological Agency, MET Norway, MetService New Zealand, MeteoAlarm (with its warning-region geometry vendored, © EUMETNET, CC BY 4.0, the NUTS regions some feeds file from [Eurostat GISCO](https://ec.europa.eu/eurostat/web/gisco), © EuroGeographics for the administrative boundaries, and Czechia's ORP boundaries from [ČÚZK RÚIAN](https://www.cuzk.gov.cz/) with the [Czech Statistical Office](https://csu.gov.cz/)'s code list, both open data), and SACHET (India's national alert aggregator).
- **Sunshine and Moon** — computed on your device from the astronomical equations; the Moon's face is a vendored grayscale of NASA SVS's [CGI Moon Kit](https://svs.gsfc.nasa.gov/4720) (Lunar Reconnaissance Orbiter, public domain).
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

A Telic-Alcatel videotex terminal draws the weather, circa 1990. Photograph from the collection at
[minitel-alcatel.fr](https://www.minitel-alcatel.fr/).

## License

[MIT](LICENSE)
