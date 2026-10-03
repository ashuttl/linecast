# Configuration

Settings are saved in `~/.config/linecast/config.json` by the settings commands (`linecast location`, `linecast units`, and the rest; `linecast --help` lists them). A flag on the command line beats an environment variable, which beats a saved setting.

Not every environment variable has a saved setting. The ones that do say what they override in the tables below; the rest are read from the environment alone. The [TideCheck key](#the-tidecheck-key) is the one setting written into `config.json` by hand.

Cached data lives in `~/Library/Caches/linecast` on macOS and `~/.cache/linecast` elsewhere. Both paths honor the `XDG_*` variables, and `LINECAST_CACHE_DIR` and `LINECAST_CONFIG_DIR` override everything.

## Print sizing

Every view accepts `--width` and `--height` for a static rendering at a chosen terminal viewport size. Either flag implies `--print`, including when `--live` is present. They work with alternate views such as `moon --month`, `weather --month`, `weather --month-departure`, and `weather --year`, but cannot be combined with `--json`, `--oneline`, or weather's `--prose`.

```sh
linecast moon --width 80 --height 20
linecast weather --width 100% --height 50%
linecast sunshine --width 80 --height 37.5%
```

Bare numbers are positive whole character columns or rows. Percentages may include decimals and must be above 0 and at most 100. Width percentages use the observed terminal width; height percentages use its height. Results round down to whole cells, with a minimum of one. An omitted dimension uses the terminal's corresponding dimension. `COLUMNS` and `LINES` override the observed size before percentages are applied; when a dimension cannot be detected, its fallback is 80 columns or 24 rows. The flags do not change these environment variables or resize the terminal window.

The dimensions describe the viewport offered to the renderer, rather than an exact output rectangle. Views keep their usual minimum sizes and space for the prompt. Very small dimensions can therefore produce a larger frame, and output wider than the physical terminal may be clipped when printed to it.

## Environment variables

### Settings

| Variable | Description |
| --- | --- |
| `WEATHER_LOCATION` | Default location, as `lat,lng` or a place name; overrides the saved location |
| `LINECAST_UNITS` | `metric` or `imperial` for every command; overrides the saved units |
| `WEATHER_UNITS` | Units for the weather command; overrides `LINECAST_UNITS` |
| `TIDES_UNITS` | Units for tide heights; overrides `LINECAST_UNITS` |
| `LINECAST_CLOCK` | `12` or `24`; overrides the saved clock |
| `LINECAST_WEEK_START` | `monday`, `sunday`, or `saturday`; overrides the saved week |
| `LINECAST_DATES` | `gregorian` or `solar-hijri`; overrides the saved dates |
| `LINECAST_DIGITS` | `latin` or `native`; overrides the saved digits |
| `LINECAST_LANG` | A language code from [languages.md](languages.md); overrides the saved language and the terminal's locale |
| `LINECAST_ICONS` | `nerd`, `emoji`, or `plain`; overrides the saved icons |
| `TIDE_STATION` | Default tide station ID |

### The terminal

| Variable | Description |
| --- | --- |
| `LINECAST_COLOR` | `auto`, `truecolor`, `256`, `16`, or `none` |
| `NO_COLOR` | Any non-empty value disables ANSI colors |
| `CLICOLOR` / `CLICOLOR_FORCE` | `CLICOLOR=0` disables color; a non-zero `CLICOLOR_FORCE` keeps it on when output is not a terminal |
| `LINECAST_THEME` | `auto` (default), or `classic` / `legacy` / `off` for the fixed palette |
| `LINECAST_THEME_TIMEOUT_MS` | How long, in milliseconds, to wait for the terminal to answer the palette query (default `500`, or `1000` over SSH) |
| `LINECAST_THEME_POLL` | Seconds between re-reading the terminal palette in live views, so a theme switch recolors the view in place (default `2`; `0` disables) |
| `LINECAST_THEME_WATCH` | A file whose modification marks a desktop theme change, prompting an immediate re-read (default: Omarchy's current-theme marker; empty disables) |
| `LINECAST_WIDTH_TIMEOUT_MS` | How long, in milliseconds, to wait for the terminal to say how wide it draws emoji and other glyphs (default `150`, or `600` over SSH) |
| `LINECAST_CELL_ASPECT` | The font's cell shape, as height over width (`2.1`) or `WxH` in pixels (`10x21`), when the terminal can't report it or reports it wrong |
| `LINECAST_BIDI` | `terminal` leaves the ordering of right-to-left text to the terminal; `linecast` orders it in linecast. See [languages.md](languages.md#persian-and-right-to-left-text) |
| `LINECAST_FRAME_SYNC` | `0` stops live views waiting for the terminal to finish drawing one frame before sending the next (default `1`) |

### Views and data sources

| Variable | Description |
| --- | --- |
| `LINECAST_TIDECHECK_KEY` | Optional [TideCheck](https://tidecheck.com/) API key, for more named tide stations; overrides the [saved key](#the-tidecheck-key) |
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

## The TideCheck key

[TideCheck](https://tidecheck.com/) adds named tide stations in places where linecast would otherwise fall back on the global tide model. It is optional, and it needs a key, which is free for 50 requests a day. linecast reads the key from `LINECAST_TIDECHECK_KEY`, or from `config.json`, where it is added by hand beside whatever settings the file already holds:

```json
{
  "tidecheck_key": "your-key"
}
```

No command saves the key, so that it stays out of the shell's history. The environment variable is the better place for it if `config.json` is kept in a public dotfiles repository. `linecast doctor` shows whether a key is set, never the key itself, and how many of the day's requests have been sent.
