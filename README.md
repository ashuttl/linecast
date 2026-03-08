# linecast

Terminal weather, solar arc, and tide visualizations. Pure Python, zero dependencies.

All data comes from free public APIs with no keys required.

![linecast](https://raw.githubusercontent.com/ashuttl/linecast/main/screenshots/triptych.png)

## Commands

**`weather`** — Current conditions, hourly braille temperature curve, 7-day forecast with color range bars, precipitation sparkline, natural language comparisons, and weather alerts for 36 countries. Available in 16 languages.

![weather](https://raw.githubusercontent.com/ashuttl/linecast/main/screenshots/weather.png)

**`sunshine`** — Solar arc inspired by the Apple Watch Solar Graph face. Shows the sun's position on its daily arc with sky color gradients, day length with daily delta, and moon phase.

<p align="center">
  <img src="https://raw.githubusercontent.com/ashuttl/linecast/main/screenshots/sunshine-day.png" width="49%" alt="sunshine — midday">
  <img src="https://raw.githubusercontent.com/ashuttl/linecast/main/screenshots/sunshine-dusk.png" width="49%" alt="sunshine — dusk">
</p>

**`tides`** — NOAA tide predictions rendered as a sunlight-shaded braille chart with current water level and high/low extremes.

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
weather --celsius                # celsius only (wind/precip stay imperial)
weather --metric --fahrenheit    # °F with km/h and mm
weather --lang fr                # UI in French (also covers alert text when available)
# other language codes: es, de, it, pt, nl, pl, no, sv, is, da, fi, ja, ko, zh
weather --live                   # full-screen, auto-refresh

sunshine                         # solar arc for today
sunshine --live                  # full-screen, scrubbable, auto-updating

tides                            # nearest NOAA station
tides --station 8413320          # specific station ID
tides --search "Bar Harbor"      # find stations by name
tides --live                     # full-screen, scrubbable, auto-updating
```

### Language support

Use `--lang` or set `LINECAST_LANG` to switch the full UI into another language. This covers weather descriptions, day names, natural language comparisons, precipitation forecasts, and alert timing. Non-English languages also use 24-hour time.

Supported: **English**, **French**, **Spanish**, **German**, **Italian**, **Portuguese**, **Dutch**, **Polish**, **Norwegian**, **Swedish**, **Icelandic**, **Danish**, **Finnish**, **Japanese**, **Korean**, **Chinese**

All commands are also available under the `linecast` namespace if the short names conflict with other tools on your system:

```
linecast weather --live
linecast sunshine
linecast tides --station 8413320
```

## Weather alerts

Alerts are sourced automatically based on location from eight providers covering 36 countries:

- **US** — National Weather Service
- **Canada** — Environment and Climate Change Canada
- **China** — China Meteorological Administration
- **Germany** — Deutscher Wetterdienst (via BrightSky)
- **Ireland** — Met Éireann
- **Japan** — Japan Meteorological Agency
- **Norway** — MET Norway
- **29 European countries** — MeteoAlarm (Austria, Belgium, Bulgaria, Croatia, Cyprus, Czechia, Denmark, Estonia, Finland, France, Greece, Hungary, Iceland, Italy, Latvia, Lithuania, Luxembourg, Malta, Netherlands, Poland, Portugal, Romania, Serbia, Slovakia, Slovenia, Spain, Sweden, Switzerland, UK)

Alert text comes from each national weather service in its native language. When available, alerts are served in your `--lang` preference.

## Environment variables

| Variable           | Description                                                                                                                                  |
| ------------------ | -------------------------------------------------------------------------------------------------------------------------------------------- |
| `WEATHER_LOCATION` | Default lat,lng for weather (e.g., `44.54,-68.42`)                                                                                           |
| `TIDE_STATION`     | Default NOAA station ID for tides (e.g., `8413320`)                                                                                          |
| `LINECAST_LANG`    | UI language, including alerts when available: `en`, `fr`, `es`, `de`, `it`, `pt`, `nl`, `pl`, `no`, `sv`, `is`, `da`, `fi`, `ja`, `ko`, `zh` |
| `WEATHER_UNITS`    | Set to `metric` for Celsius, km/h, and mm (same as `--metric`)                                                                               |
| `LINECAST_ICONS`   | Set to `emoji` to use standard emoji instead of Nerd Font icons                                                                              |
| `LINECAST_COLOR`   | Color mode: `auto` (default), `truecolor`, `256`, `16`, or `none`                                                                            |
| `NO_COLOR`         | Any non-empty value disables ANSI colors (standard convention)                                                                               |

## Requirements

- Python 3.10+
- A terminal with ANSI color support (`truecolor` looks best; weather remains usable in low/no color)
- A [Nerd Font](https://www.nerdfonts.com/) for best icon rendering (optional — use `--emoji` for standard emoji fallback)
- macOS or Linux (uses `termios` for live mode)

## License

MIT
