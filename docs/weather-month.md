# The weather month view

Press `v` in weather to cycle forecast → month → year. The month opens on the previous calendar month. Open it directly with:

```sh
linecast weather --month
linecast weather --month-temperature
linecast weather --month-departure
linecast weather --month --print
```

`--month` and `--month-temperature` are the same. `--month-departure` starts with the comparison colors. All accept the usual location, language, units, clock, and print-sizing flags. The month has no `--json`, `--oneline`, or `--prose` output.

| Control | Action |
| --- | --- |
| `v` | Next view: forecast, month, year |
| `c` | Temperature or departure from the hourly average |
| ← / → or scroll | Previous or next month |
| Space / `n` | Previous calendar month |
| Hover | Temperature, baseline average, and difference at that time |
| `r` | Retry or refresh the hourly archive, using a fresh cache when available |
| `l` or click the place | Change location |
| `?` | Help |

Days run down the chart and local clock hours across it. In a short terminal, each row holds two days, with the first in the upper half and the second in the lower half; hovering reads both. The numbers at the right are the lowest and highest hourly temperatures in the row. They remain temperatures when the chart shows departures. The braille lines mark sunrise and sunset, and the diamond marks now when viewing the current month. Legend temperatures are rounded to whole degrees; hover keeps tenths.

Departure colors compare each hour with its average across the ten complete years before this year, using the same local clock hour and the seven dates either side. Blue is cooler than that average, red warmer. These are Open-Meteo's historical model estimates. The baseline is identified by its years and is not a station's official climate normal.

The archive loads in the background on the first visit, with the usual loading indicator if it takes a moment. The ten baseline years and this year so far are cached per location, so browsing months or switching colors needs no further download. The baseline cache lasts a week; the current year refreshes after three hours or on a new local day. A failed request uses the cached data when available. Missing hours stay blank, including recent hours the archive has not reached. No forecast is mixed into the chart. A spring clock-change gap stays empty; a repeated autumn hour is the average of both readings and is identified on hover.

The view needs at least 54 columns and 23 rows. More height gives each day its own row; more width leaves room for the temperature extremes and a single legend line. See [Where the numbers come from](sources.md#weather) for the archive and comparison details.
