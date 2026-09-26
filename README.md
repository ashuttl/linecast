<div align="center">

# linecast

**Weather, tides, the sun, the moon, maps, and a planetarium, in your terminal. The Old Farmer's Almanac meets Minitel.**

[![Tests](https://github.com/ashuttl/linecast/actions/workflows/test.yml/badge.svg)](https://github.com/ashuttl/linecast/actions/workflows/test.yml)
[![PyPI](https://img.shields.io/pypi/v/linecast)](https://pypi.org/project/linecast/)
[![Python](https://img.shields.io/pypi/pyversions/linecast)](https://pypi.org/project/linecast/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](https://github.com/ashuttl/linecast/blob/main/LICENSE)

<a href="https://terminaltrove.com/linecast/" title="linecast on Terminal Trove, the $HOME of all things in the terminal"><img src="https://cdn.terminaltrove.com/media/badges/tool_of_the_week/svg/terminal_trove_tool_of_the_week_green_on_dark_grey_bg.svg" alt="Terminal Trove Tool of The Week" height="36"></a>

English | [日本語](https://github.com/ashuttl/linecast/blob/main/README.ja.md)

</div>

![linecast weather, radar, the moon, the year, and sunshine at dusk tiled on an Omarchy desktop](https://raw.githubusercontent.com/ashuttl/linecast/main/screenshots/hero.png)

Seven live terminal apps built on free public data. Pure Python, no dependencies, no accounts or API keys. Colors come from your terminal theme, and the mouse works. Runs on macOS, Linux, and Windows, over SSH, and in tmux.

| Command | Shows |
| --- | --- |
| `linecast weather` | Current conditions, hourly and seven-day forecasts, and official alerts for 45 countries |
| `linecast sunshine` | The sun's path today, and daylight through the year |
| `linecast moon` | The Moon's phase as you see it, with rise, set, and a month calendar |
| `linecast sky` | A planetarium: stars, constellations, planets, and the Milky Way over you |
| `linecast tides` | A tide curve for the nearest station |
| `linecast radar` | Animated weather radar for the whole world |
| `linecast maps` | Street maps, terrain, directions, and a globe with live daylight and clouds |

**[Install](#install) · [Using it](#using-it) · [The apps](#the-apps) · [Settings](#settings) · [Contributing](#contributing)**

## Install

```sh
brew install linecast        # Homebrew
uv tool install linecast     # uv
uvx linecast weather         # try it without installing
curl -sL https://raw.githubusercontent.com/ashuttl/linecast/main/get.sh | sh   # with nothing but curl
```

`pipx` and `pip` work too, and there are community packages in the [AUR](https://aur.archlinux.org/packages/linecast) and [nixpkgs](https://search.nixos.org/packages?channel=unstable&show=linecast). linecast needs Python 3.10 or newer. On Windows, use Windows Terminal.

## Using it

Every command opens live. Press `?` for the keys. Add `--print` for one static frame, `--json` for raw data, or `--oneline` for a status bar.

```sh
linecast weather --location "quebec"
linecast sky --culture hawaiian
linecast sunshine --year
linecast maps --from "portland, maine" --to "portland head light" --profile bike
linecast maps --view now
```

![an animated version of the hero screenshot, showing the weather radar moving](https://raw.githubusercontent.com/ashuttl/linecast/main/screenshots/hero.gif)

## The apps

The [gallery](https://github.com/ashuttl/linecast/blob/main/docs/gallery.md) shows each one in more of its states.

### Weather

An hourly chart on the scale of a typical year where you are, so a mild day looks mild, with a forecast in words. Click an alert to read it.

![weather dashboard](https://raw.githubusercontent.com/ashuttl/linecast/main/screenshots/weather.png)

Reykjavík in Icelandic, and Kyoto in Japanese:

<p>
  <img src="https://raw.githubusercontent.com/ashuttl/linecast/main/screenshots/weather-reykjavik.png" width="49%" alt="the weather in Reykjavík, in Icelandic">
  <img src="https://raw.githubusercontent.com/ashuttl/linecast/main/screenshots/weather-kyoto.png" width="49%" alt="the weather in Kyoto, in Japanese">
</p>

### Sunshine

The sun on its arc through dawn, day, and dusk. Press `v` for the whole year. `--hours` reads the day in [traditional hours](https://github.com/ashuttl/linecast/blob/main/docs/hours.md): halachic, Roman, Edo, Islamic, or Swahili.

Dawn and dusk on the June solstice:

<p align="center">
  <img src="https://raw.githubusercontent.com/ashuttl/linecast/main/screenshots/sunshine-dawn.png" width="49%" alt="sunshine at dawn on the June solstice">
  <img src="https://raw.githubusercontent.com/ashuttl/linecast/main/screenshots/sunshine-dusk.png" width="49%" alt="sunshine at dusk on the June solstice">
</p>

The year in Reykjavík, in Icelandic:

![the year view for Reykjavík, in Icelandic, with the pointer on the December solstice](https://raw.githubusercontent.com/ashuttl/linecast/main/screenshots/sunshine-year.png)

Polar night and midnight sun, at 78° north and 78° south:

<p align="center">
  <img src="https://raw.githubusercontent.com/ashuttl/linecast/main/screenshots/sunshine-year-arctic.png" width="49%" alt="the year view for Longyearbyen, Svalbard">
  <img src="https://raw.githubusercontent.com/ashuttl/linecast/main/screenshots/sunshine-year-antarctic.png" width="49%" alt="the year view for Vostok Station, Antarctica">
</p>

### Moon

The phase as you see it, with the real stars behind. Drag to see the far side; press `v` for the month. `--calendar` adds a [traditional calendar](https://github.com/ashuttl/linecast/blob/main/docs/calendars.md) and its festivals.

![full Moon](https://raw.githubusercontent.com/ashuttl/linecast/main/screenshots/moon.png)

Okinawa after the mid-autumn full moon, in Japanese, and the month around it:

<p align="center">
  <img src="https://raw.githubusercontent.com/ashuttl/linecast/main/screenshots/moon-okinawa.png" width="49%" alt="the moon over Okinawa in Japanese: 十六夜, the sixteenth night of the eighth month">
  <img src="https://raw.githubusercontent.com/ashuttl/linecast/main/screenshots/moon-calendar.png" width="49%" alt="the month calendar for September 2026 in Japanese, with 十五夜 on the 25th and the pointer on it">
</p>

### Sky

The sky over you, now or at any hour. Drag to look around, `/` to find a star or planet, `t` to choose among 22 [sky cultures](https://github.com/ashuttl/linecast/blob/main/docs/cultures.md).

![Orion on a January evening over Westbrook, Maine, with Jupiter in Gemini](https://raw.githubusercontent.com/ashuttl/linecast/main/screenshots/sky.png)

The whole August sky, and a January evening drawn the Hawaiian way:

<p>
  <img src="https://raw.githubusercontent.com/ashuttl/linecast/main/screenshots/sky-allsky.png" width="49%" alt="the whole August sky at once, the horizon closed into a circle, the Milky Way across it">
  <img src="https://raw.githubusercontent.com/ashuttl/linecast/main/screenshots/sky-hawaiian.png" width="49%" alt="the same January sky in the Hawaiian tradition, with the star compass along the horizon">
</p>

### Tides

National tide services in the US, Canada, Queensland, and Hong Kong, and a global model elsewhere. `--nearby` lists stations.

![tide chart](https://raw.githubusercontent.com/ashuttl/linecast/main/screenshots/tides.png)

### Radar

The last hour and the next, with US warnings on top. `S` switches to satellite, `t` changes the colors.

![animated radar forecast](https://raw.githubusercontent.com/ashuttl/linecast/main/screenshots/radar.gif)

### Maps

Streets or terrain; press `v` to switch, `/` to search, `D` for directions. Zoom out to the globe, and press `S` for daylight and `c` for clouds.

<p align="center">
  <img src="https://raw.githubusercontent.com/ashuttl/linecast/main/screenshots/maps-street.png" width="49%" alt="street map of Portland, Maine">
  <img src="https://raw.githubusercontent.com/ashuttl/linecast/main/screenshots/maps-terrain.png" width="49%" alt="terrain map of New Zealand, with the seafloor around it">
</p>

The labels change with the zoom:

<p>
  <img src="https://raw.githubusercontent.com/ashuttl/linecast/main/screenshots/maps-zoom-blocks.png" width="32%" alt="Portland, Maine, at block level">
  <img src="https://raw.githubusercontent.com/ashuttl/linecast/main/screenshots/maps-zoom-city.png" width="32%" alt="Portland, Maine, at city scale">
  <img src="https://raw.githubusercontent.com/ashuttl/linecast/main/screenshots/maps-zoom-state.png" width="32%" alt="southern Maine">
</p>

The globe in daylight, and with the hour's clouds:

<p>
  <img src="https://raw.githubusercontent.com/ashuttl/linecast/main/screenshots/maps-globe.png" width="49%" alt="the globe as it is right now: live daylight, the terminator, and the city lights beyond it">
  <img src="https://raw.githubusercontent.com/ashuttl/linecast/main/screenshots/maps-globe-clouds.png" width="49%" alt="the same globe with this hour's clouds">
</p>

## Settings

Run a setting alone to see it, with a value to save it, or with `auto` to reset it.

| Setting | Values | For one run |
| --- | --- | --- |
| `linecast location` | `set "Portland, Maine"`, `set 44.54,-68.42`, `search NAME` | `--location` |
| `linecast language` | one of [29 languages](https://github.com/ashuttl/linecast/blob/main/docs/languages.md) | `--lang` |
| `linecast units` | `metric`, `imperial` | `--metric`, `--imperial` |
| `linecast clock` | `12`, `24` | `--12h`, `--24h` |
| `linecast week` | `monday`, `sunday`, `saturday` | `--week-start` |
| `linecast calendar` | `chinese`, `hebrew`, `islamic`, … | `--calendar` |
| `linecast culture` | `chinese`, `hawaiian`, `norse`, … | `--culture` |
| `linecast hours` | `halachic`, `roman`, `japanese`, … | `--hours` |
| `linecast icons` | `nerd`, `emoji`, `plain` | `--icons` |
| `linecast dates` | `gregorian`, `solar-hijri` | |
| `linecast digits` | `latin`, `native` | |

Without a saved location, linecast guesses from your IP address, which can be far off on a VPN or over SSH.

Persian support is experimental. It works in Ghostty, Alacritty, and foot, but not well in the Mac's Terminal or iTerm2. See [docs/languages.md](https://github.com/ashuttl/linecast/blob/main/docs/languages.md#persian-and-right-to-left-text).

Environment variables are in [docs/configuration.md](https://github.com/ashuttl/linecast/blob/main/docs/configuration.md), and data sources and credits in [docs/sources.md](https://github.com/ashuttl/linecast/blob/main/docs/sources.md).

### Extras

```sh
linecast link                       # add weather, moon, … as short commands
source <(linecast completion zsh)   # shell completion: bash, zsh, fish, nu
linecast doctor                     # when something looks wrong
```

## Contributing

Questions and ideas are welcome in [Discussions](https://github.com/ashuttl/linecast/discussions), and pull requests too; see [CONTRIBUTING.md](https://github.com/ashuttl/linecast/blob/main/CONTRIBUTING.md).

## Lineage

<p align="center">
  <img src="https://raw.githubusercontent.com/ashuttl/linecast/main/screenshots/minitel-terminatel-258.jpg" width="380" alt="3615 LINECAST">
</p>

<p align="center"><em>Prior art.</em></p>

A Telic-Alcatel videotex terminal draws the weather, circa 1990. Photograph from the collection at [minitel-alcatel.fr](https://www.minitel-alcatel.fr/).

## License

[MIT](https://github.com/ashuttl/linecast/blob/main/LICENSE)
