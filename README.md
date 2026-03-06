# linecast

Terminal weather, solar arc, and tide visualizations. Pure Python, zero dependencies.

All data comes from free public APIs with no keys required.

![linecast](https://raw.githubusercontent.com/ashuttl/linecast/main/screenshots/triptych.png)

## Commands

**`weather`** — Current conditions, hourly braille temperature curve, 7-day forecast with color range bars, precipitation sparkline, natural language comparisons, and NWS/Environment Canada weather alerts.

![weather](https://raw.githubusercontent.com/ashuttl/linecast/main/screenshots/weather.png)

**`sunshine`** — Solar arc inspired by the Apple Watch Solar Graph face. Shows the sun's position on its daily arc with sky color gradients, day length with daily delta, and moon phase.

<p align="center">
  <img src="https://raw.githubusercontent.com/ashuttl/linecast/main/screenshots/sunshine-day.png" width="49%" alt="sunshine — midday">
  <img src="https://raw.githubusercontent.com/ashuttl/linecast/main/screenshots/sunshine-dusk.png" width="49%" alt="sunshine — dusk">
</p>

**`tides`** — NOAA tide predictions rendered as an ocean-themed half-block chart with gradient fill, current water level, and high/low extremes.

![tides](https://raw.githubusercontent.com/ashuttl/linecast/main/screenshots/tides.png)

All three support `--live` for a full-screen auto-refreshing display. `sunshine` and `tides` also support arrow-key time scrubbing.

## Install

```
pip install linecast
```

Or with a Homebrew tap:

```
brew tap ashuttl/linecast
brew install linecast
```

## Usage

```
weather                          # current location via IP geolocation
weather --location 44.54,-68.42  # specific coordinates
weather --search québec          # find coordinates by city name
weather --metric                 # metric units (°C, km/h, mm)
weather --live                   # full-screen, auto-refresh
weather --lang fr                # descriptions et interface en français

sunshine                         # solar arc for today
sunshine --live                  # full-screen, scrubbable, auto-updating

tides                            # nearest NOAA station
tides --station 8413320          # specific station ID
tides --search "Bar Harbor"      # find stations by name
tides --live                     # full-screen, scrubbable, auto-updating
```

> **`weather --lang fr`** — Descriptions météorologiques, dates et interface en français. Utilise également la version française des alertes d'Environnement Canada, si disponible.

All commands are also available under the `linecast` namespace if the short names conflict with other tools on your system:

```
linecast weather --live
linecast sunshine
linecast tides --station 8413320
```

## Weather alerts

Alerts are sourced automatically based on location:

- **US** — National Weather Service (api.weather.gov)
- **Canada** — Environment and Climate Change Canada (api.weather.gc.ca)

Other regions get forecasts but no alerts yet.

## Environment variables

| Variable           | Description                                                       |
| ------------------ | ----------------------------------------------------------------- |
| `WEATHER_LOCATION` | Default lat,lng for weather (e.g., `44.54,-68.42`)                |
| `TIDE_STATION`     | Default NOAA station ID for tides (e.g., `8413320`)               |
| `WEATHER_UNITS`    | Set to `metric` for Celsius, km/h, and mm (same as `--celsius`)   |
| `LINECAST_ICONS`   | Set to `emoji` to use standard emoji instead of Nerd Font icons   |
| `LINECAST_COLOR`   | Color mode: `auto` (default), `truecolor`, `256`, `16`, or `none` |
| `NO_COLOR`         | Any non-empty value disables ANSI colors (standard convention)    |

## Requirements

- Python 3.10+
- A terminal with ANSI color support (`truecolor` looks best; weather remains usable in low/no color)
- A [Nerd Font](https://www.nerdfonts.com/) for best icon rendering (optional — use `--emoji` for standard emoji fallback)
- macOS or Linux (uses `termios` for live mode)

## License

MIT
