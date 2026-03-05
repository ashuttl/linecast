# linecast

Terminal weather, solar arc, and tide visualizations. Pure Python, zero dependencies.

Three commands that turn your terminal into a living dashboard — temperature-colored braille curves, half-block pixel art, true color gradients, and Nerd Font icons. All data comes from free public APIs with no keys required.

## Commands

**`weather`** — Current conditions, hourly braille temperature curve, 7-day forecast with color range bars, precipitation sparkline, natural language comparisons, and NWS/Environment Canada weather alerts.

**`sunshine`** — Solar arc inspired by the Apple Watch Solar face. Shows the sun's position on its daily arc with sky color gradients, day length with daily delta, and moon phase.

**`tides`** — NOAA tide predictions rendered as an ocean-themed half-block chart with gradient fill, current water level, and high/low extremes.

All three support `--live` for a full-screen auto-refreshing display with arrow-key time scrubbing.

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
weather --location 35.43,-101.17 # specific coordinates
weather --search "Portland"      # find coordinates by city name
weather --live                   # full-screen, auto-refresh

sunshine                         # solar arc for today
sunshine --live                  # full-screen with time scrubbing

tides                            # nearest NOAA station
tides --station 8518750          # specific station ID
tides --search "San Francisco"   # find stations by name
tides --live                     # full-screen
```

## Weather alerts

Alerts are sourced automatically based on your location:

- **US** — National Weather Service (api.weather.gov)
- **Canada** — Environment and Climate Change Canada (api.weather.gc.ca)

Other regions get forecasts but no alerts yet.

## Environment variables

| Variable | Description |
|---|---|
| `WEATHER_LOCATION` | Default lat,lng for weather (e.g., `35.43,-101.17`) |
| `TIDE_STATION` | Default NOAA station ID for tides (e.g., `8518750`) |

## Requirements

- Python 3.10+
- A terminal with true color support (iTerm2, Ghostty, Kitty, WezTerm, etc.)
- A [Nerd Font](https://www.nerdfonts.com/) for weather/moon/tide icons
- macOS or Linux (uses `termios` for live mode)

## License

MIT
