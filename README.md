<div align="center">

# linecast

**Weather, tides, the sun, the moon, maps, and a planetarium, in your terminal. The Old Farmer's Almanac meets Minitel.**

[![Tests](https://github.com/ashuttl/linecast/actions/workflows/test.yml/badge.svg)](https://github.com/ashuttl/linecast/actions/workflows/test.yml)
[![PyPI](https://img.shields.io/pypi/v/linecast)](https://pypi.org/project/linecast/)
[![Python](https://img.shields.io/pypi/pyversions/linecast)](https://pypi.org/project/linecast/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

<a href="https://terminaltrove.com/linecast/" title="linecast on Terminal Trove, the $HOME of all things in the terminal"><img src="https://cdn.terminaltrove.com/media/badges/tool_of_the_week/svg/terminal_trove_tool_of_the_week_green_on_dark_grey_bg.svg" alt="Terminal Trove Tool of The Week" height="36"></a>

English | [日本語](README.ja.md)

</div>

![linecast tiled on an Omarchy desktop: the weather in Westbrook, Maine, and its year so far, the radar over Portland, the Moon in Japanese, and a year of daylight in Reykjavík in Icelandic](screenshots/hero.png)

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

If you can't use a package manager, or would rather carry linecast around as a file, each [release](https://github.com/ashuttl/linecast/releases/latest) also has all of it in one file, `linecast.pyz`. A package manager is the better choice where you have one, because it keeps linecast up to date for you; the file only tells you, once a week, when there's a newer release. Make it executable with `chmod +x linecast.pyz` and run `./linecast.pyz weather`, or rename it `linecast` and put it on your PATH. It needs Python 3.10 or newer.

## Using it

Every command opens live. Press `?` for the keys. Add `--print` for one static frame, `--json` for raw data, or `--oneline` for a status bar.

```sh
linecast weather --location "quebec"
linecast sky --culture hawaiian
linecast sunshine --year
linecast maps --from "portland, maine" --to "portland head light" --profile bike
linecast maps --view now
```

Open the alternate views directly with `linecast weather --year`, `linecast sunshine --year`, `linecast moon --month`, or `linecast tides --month`, `--year`, or `--makeup`. These flags also work with `--print`; `--json` and `--oneline` describe the current conditions and cannot be combined with an alternate view.

linecast takes its colors from your terminal's color scheme. If you change the scheme while an app is open, the app redraws itself in the new colors. This is the same desktop through ten Omarchy themes:

![the same desktop through ten Omarchy themes, light and dark, each app taking up the new colors as the theme changes](screenshots/themes.gif)

Inside tmux, this needs tmux 3.6 or newer. Older versions don't pass the terminal's colors on, and linecast uses its own fixed palette instead. A change of scheme also comes through tmux only if the terminal reports it to tmux; if yours doesn't, detach and reattach to bring in the new colors. `linecast doctor` says which palette is in use.

## The apps

The [gallery](docs/gallery.md) shows each one in more of its states.

### Weather

An hourly chart on the scale of a typical year where you are, so a mild day looks mild, with a forecast in words. Click an alert to read it. Press `v` for the year so far, [après Tufte](https://www.edwardtufte.com/notebook/new-york-city-weather-chart/): each day's high and low against the last ten years, and each month's precipitation against its average. Press `c` to change the chart's colors. The first highlights where the temperature went above or below the average, the second uses the temperature colors from the main weather view, and the third is plain.

![weather dashboard](screenshots/weather.png)

Reykjavík in Icelandic, and Kyoto in Japanese:

<p>
  <img src="screenshots/weather-reykjavik.png" width="49%" alt="the weather in Reykjavík, in Icelandic">
  <img src="screenshots/weather-kyoto.png" width="49%" alt="the weather in Kyoto, in Japanese">
</p>

The year view for Westbrook, Maine, with the pointer on a week in May:

![the weather year view for Westbrook, Maine, with the chip for a week in May](screenshots/weather-year.png)

### Sunshine

The sun on its arc through dawn, day, and dusk. Press `v` for the whole year. In either view, `t` hides the text except the location and current time; `--no-text` starts that way. `--hours` reads the day in [traditional hours](docs/hours.md): halachic, Roman, Edo, Islamic, or Swahili.

Dawn and dusk on the June solstice:

<p align="center">
  <img src="screenshots/sunshine-dawn.png" width="49%" alt="sunshine at dawn on the June solstice">
  <img src="screenshots/sunshine-dusk.png" width="49%" alt="sunshine at dusk on the June solstice">
</p>

The year in Reykjavík, in Icelandic:

![the year view for Reykjavík, in Icelandic, with the pointer on the December solstice](screenshots/sunshine-year.png)

Polar night and midnight sun, at 78° north and 78° south:

<p align="center">
  <img src="screenshots/sunshine-year-arctic.png" width="49%" alt="the year view for Longyearbyen, Svalbard">
  <img src="screenshots/sunshine-year-antarctic.png" width="49%" alt="the year view for Vostok Station, Antarctica">
</p>

### Moon

The phase as you see it, with the real stars behind. Drag to see the far side; press `v` for the month, or open on it with `--month`. `--calendar` adds a [traditional calendar](docs/calendars.md) and its festivals.

![full Moon](screenshots/moon.png)

Okinawa after the mid-autumn full moon, in Japanese, and the month around it:

<p align="center">
  <img src="screenshots/moon-okinawa.png" width="49%" alt="the moon over Okinawa in Japanese: 十六夜, the sixteenth night of the eighth month">
  <img src="screenshots/moon-calendar.png" width="49%" alt="the month calendar for September 2026 in Japanese, with 十五夜 on the 25th and the pointer on it">
</p>

Press `t` to hide the text and show only the Moon, or launch with `--no-text`. You can drag the Moon to turn it, and when you let go, it turns back to how it looks from where you are:

![the Moon alone among the stars, dragged round by the pointer until it is nearly dark, then let go, rolling back to a waxing gibbous](screenshots/moon-spin.gif)

### Sky

The sky over you, now or at any hour: the 8,404 stars the naked eye can see, and nearly 117,000 as you zoom in. Drag to look around, `/` to find a star or planet, `t` to choose among 22 [sky cultures](docs/cultures.md).

![Orion on a January evening over Westbrook, Maine, with Jupiter in Gemini](screenshots/sky.png)

The whole August sky, and a January evening drawn the Hawaiian way:

<p>
  <img src="screenshots/sky-allsky.png" width="49%" alt="the whole August sky at once, the horizon closed into a circle, the Milky Way across it">
  <img src="screenshots/sky-hawaiian.png" width="49%" alt="the same January sky in the Hawaiian tradition, with the star compass along the horizon">
</p>

Press `-` a few times and the view lies back until the horizon closes into a circle overhead, with the whole sky inside it, the way the almanacs print it. Press `p` to play time forward. This is an August afternoon and night over Westbrook, Maine, at an hour a second:

![the whole sky from an August afternoon into the night: the Sun and a half Moon crossing, the sunset turning the sky pink, the stars and the Milky Way coming out, and the sky turning](screenshots/sky-time.gif)

### Tides

National tide services in the US, Canada, Queensland, Hong Kong, Japan, and Norway; 1,215 tide gauges elsewhere, predicted on your computer from their harmonic constants; and a global model beyond them. `--nearby` lists stations.

![tide chart](screenshots/tides.png)

Press `v` for the month, with a row for each day and the hours across, and again for the year, where what the gauge measured is drawn over what was predicted. Open directly with `linecast tides --month` or `linecast tides --year`:

<p align="center">
  <img src="screenshots/tides-month.png" width="49%" alt="October 2026 at Portland, Maine: the high water as two slanting bands a day, sunrise and sunset as dotted lines down the month, and each day's lowest low water in daylight at the right">
  <img src="screenshots/tides-year.png" width="49%" alt="2026 at Portland, Maine: each day's predicted range as a band, the gauge's highest and lowest water traced over it, and the pointer on the middle of June, where the water measured 12.4 feet and passed the flood stage">
</p>

Press `v` once more, or start with `linecast tides --makeup`, to see what moves the tide at that place: how much of it comes twice a day and how much once a day, what causes each part, and how each changes through the month, the year, and nineteen years of the Moon's long cycle. The year and makeup views require a source with year-round predictions. [About the tides](docs/tides.md) explains what it shows.

![what moves the tide at Portland, Maine: a table of five causes and the height of each, beside strips for the twice-a-day and once-a-day parts through October 2026, the year 2026, and 2016 to 2034](screenshots/tides-makeup.png)

### Radar

The last hour and the next, with US warnings on top. `S` switches to satellite, `t` changes the colors. Real radar comes from wherever it is published openly: North America, Europe, and parts of East and Southeast Asia. Everywhere else a precipitation model fills in, and it looks like one.

![animated radar forecast](screenshots/radar.gif)

### Maps

Streets or terrain; press `v` to switch, `/` to search, `D` for directions. Zoom out to the globe, and press `S` for daylight and `c` for clouds. Press `t` to hide the header and footer and fill the terminal with the map; `--no-text` starts that way. `l` toggles map labels independently.

`linecast maps --view now` opens a full-terminal globe with daylight and clouds, text and labels hidden, slowly rotating. Press `t` to restore the header and footer, `l` for labels, or `r` to stop or resume rotation.

<p align="center">
  <img src="screenshots/maps-street.png" width="49%" alt="street map of Portland, Maine">
  <img src="screenshots/maps-terrain.png" width="49%" alt="terrain map of New Zealand, with the seafloor around it">
</p>

The map decides what to say at every zoom. At block level it names the shops; at city scale, the cove and the bridge; at the state, only the highways and the towns:

<p>
  <img src="screenshots/maps-zoom-blocks.png" width="32%" alt="Portland, Maine, at block level">
  <img src="screenshots/maps-zoom-city.png" width="32%" alt="Portland, Maine, at city scale">
  <img src="screenshots/maps-zoom-state.png" width="32%" alt="southern Maine">
</p>

The globe in daylight, and with the hour's clouds:

<p>
  <img src="screenshots/maps-globe.png" width="49%" alt="the globe as it is right now: live daylight, the terminator, and the city lights beyond it">
  <img src="screenshots/maps-globe-clouds.png" width="49%" alt="the same globe with this hour's clouds">
</p>

## Settings

Run a setting alone to see it, with a value to save it, or with `auto` to reset it.

| Setting | Values | For one run |
| --- | --- | --- |
| `linecast location` | `set "Portland, Maine"`, `set 44.54,-68.42`, `search NAME` | `--location` |
| `linecast language` | one of [31 languages](docs/languages.md) | `--lang` |
| `linecast units` | `metric`, `imperial` | `--metric`, `--imperial` |
| `linecast clock` | `12`, `24` | `--12h`, `--24h` |
| `linecast week` | `monday`, `sunday`, `saturday` | `--week-start` |
| `linecast calendar` | `chinese`, `hebrew`, `islamic`, … | `--calendar` |
| `linecast culture` | `chinese`, `hawaiian`, `norse`, … | `--culture` |
| `linecast hours` | `halachic`, `roman`, `japanese`, … | `--hours` |
| `linecast icons` | `nerd`, `emoji`, `plain` | `--icons` |
| `linecast dates` | `gregorian`, `solar-hijri` | |
| `linecast digits` | `latin`, `native` | |

The same apps in other languages and traditions: the weather in Montréal in Canadian French, October in Reykjavík with the Icelandic calendar, the Moon over Hilo with the Hawaiian calendar and over Okinawa in Japanese, and the January sky with Hawaiian star names and the star compass along the horizon:

![a second desktop: the weather in Montréal in Canadian French, October 2026 in Icelandic with the pointer on Fyrsti vetrardagur, the Moon over Hilo on the night of Akua, the Moon over Okinawa on 十六夜, and the sky facing south with the Hawaiian star compass along the horizon](screenshots/languages.png)

Without a saved location, linecast guesses from your IP address, which can be far off on a VPN or over SSH.

Persian support is experimental. It works in Ghostty, Alacritty, and foot, but not well in the Mac's Terminal or iTerm2. See [docs/languages.md](docs/languages.md#persian-and-right-to-left-text).

Environment variables, and the optional TideCheck key for more tide stations, are in [docs/configuration.md](docs/configuration.md), and data sources and credits in [docs/sources.md](docs/sources.md).

### Extras

```sh
linecast link                       # add weather, moon, … as short commands
source <(linecast completion zsh)   # shell completion: bash, zsh, fish, nu
linecast doctor                     # when something looks wrong
```

## Contributing

Questions and ideas are welcome in [Discussions](https://github.com/ashuttl/linecast/discussions), and pull requests too; see [CONTRIBUTING.md](CONTRIBUTING.md).

## Lineage

<p align="center">
  <img src="screenshots/minitel-terminatel-258.jpg" width="380" alt="3615 LINECAST">
</p>

<p align="center"><em>Prior art.</em></p>

A Telic-Alcatel videotex terminal draws the weather, circa 1990. Photograph from the collection at [minitel-alcatel.fr](https://www.minitel-alcatel.fr/).

## License

[MIT](LICENSE)
