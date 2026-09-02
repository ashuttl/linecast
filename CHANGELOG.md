# Changelog

Notable changes, by release. Notes for the next release collect under **Unreleased** and get a final edit when `release.sh` runs.

## Unreleased

The moon follows traditional calendars: Chinese, Japanese, Korean, and Thai by language; Hebrew, Islamic, Hawaiian, Samoan, CHamoru, and the Old Farmer's Almanac by choice. It has a month view. Thai is the eighteenth language. Street maps get route shields, sunrise and sunset times are more accurate, and every European alert now applies to the ground it covers.

New this version:

- Moon: In Chinese, Japanese, and Korean the panel follows the traditional calendar: the lunar date beside the phase name (农历七月二十, 旧暦7月20日, 음력 7월 20일), the solar term in progress and the date of the next, and the coming festival (中秋节, 추석, 十五夜). In Japanese the headline names the night by the old calendar's day: 十六夜, 立待月, 居待月, 寝待月, 更待月.
- Moon: In Thai the panel follows the Thai lunar calendar: the waxing or waning day in Thai numerals (แรม ๔ ค่ำ เดือน ๙), the year's animal, the next วันพระ, and the coming festival, มาฆบูชา through ลอยกระทง.
- Moon: In Chinese, Japanese, Korean, or Thai (`--lang zh`, `ja`, `ko`, `th`) the matching calendar comes with the language. In any other language, `--calendar chinese`, `japanese`, `korean`, or `thai` shows one of them, with the customary English names ("Mid-Autumn Festival Sep 25"). The calendars below belong to no language and are chosen the same way. `--calendar none` turns any of them off, `linecast calendar` saves the choice, and `linecast doctor` shows it.
- Moon: `--calendar hawaiian` follows the Kaulana Mahina. Each night is named (Hilo, Hoaka, Māhealani, Muku) with its anahulu, and the month begins on the first night the crescent can be seen over Hawaiʻi, as in the Western Pacific Regional Fishery Management Council's calendars. The panel also gives the night's traditional fishing counsel, quoted from the Council's educational materials and credited on screen.
- Moon: `--calendar samoan` and `--calendar chamorro` follow the Council's American Samoa and Guam calendars: thirty named nights, counted from the first evening the crescent can be seen over Pago Pago or Hagåtña. `--calendar refaluwasch` is the CNMI calendar, which sets the Refaluwasch name beside the CHamoru one on the nights tradition names.
- Moon: `--calendar islamic` follows the Umm al-Qura calendar: the Hijri date beside the phase (23 Ramadan 1447 AH), turning at sunset, the coming month, and the next observance from Islamic New Year through Eid al-Adha, with "begins at sunset" the day before. Month starts follow Saudi Arabia's civil rule; a country's announced dates may differ by a day.
- Moon: `--calendar hebrew` follows the Hebrew calendar: the date beside the phase (20 Elul 5786), turning at sunset, the coming month, and the next holiday from Rosh Hashanah through Tisha B'Av, with "begins at sunset" the day before. A location in Israel keeps one day of Yom Tov, anywhere else two. `--json` carries the date in Hebrew letters too (כ׳ אלול תשפ״ו).
- Moon: `--calendar almanac` reads the moon the way the Old Farmer's Almanac does: the light or dark of the moon, gardening counsel for it, and the day's solunar periods. The almanac's full-moon names (Harvest, Blue, and the rest) show here and in the plain English view.
- Moon: `--json` reports the active calendar in a `calendar` block, or null when none is shown. `--oneline` adds the lunar date after the rise and set times (· 20 Elul 5786, · 旧暦7月22日), or the night's name in place of the phase where the calendar names nights.
- Moon: `v` in live mode flips between the disc and a month of phases. Each day is a small shaded disc, with today and the principal phases marked; a calendar in force sets its months in the title, its festivals on the days, and, for Hebrew and Islamic, its date in the corner of each cell. Scroll to page through months, hover a day for its phase, moonrise, and moonset, and click one to open it in the disc view. `linecast moon --grid` opens on the month.
- Sunshine: `v` switches between the day and year views, the same key as in maps and moon. `y` still works.
- Thai is the eighteenth language. `--lang th` puts the whole app in Thai.
- Maps: Route shields name their network (I-95, US-1, ME-128, M6, A38) and take the sign's color where there is one: interstates and motorways blue, US routes white, UK primary routes green. A shield appears at most twice per view.
- Maps: Exit numbers are bracketed and drawn in the ramp's dimmer ink, so they no longer pass for route numbers. A numbered road also shows its name at close zooms.
- Maps: Major cities are named in capitals, going by the city's own population rather than its metro area's, and national and state capitals get a star instead of a dot.
- Maps: Street maps shade built-up ground, so towns and cities read as settlement even where no one has mapped the land use.
- Maps: With daylight on, the header names what the sun is over ("sun over North Pacific Ocean") instead of the elevation at the centre of the view. Pointing at the terrain still reads the elevation there.
- Maps and radar: The header starts with the place name instead of the app's name.
- Weather: A line on the hourly chart marks the current time, so now stays visible after scrolling away from it (thanks [@ebrannin-bw](https://github.com/ebrannin-bw) for [#49](https://github.com/ashuttl/linecast/issues/49)).
- Sunshine: The year view fills the window with the sky, and the month labels sit on it. The sunrise/sunset line, which described only today, is gone; the pop-up gives those times for any day.
- Sunshine: The year view's daylight is hazier near sunrise and sunset, whiter low in the sky and bluer as the sun climbs.
- Radar: The marangai theme's top bands match MetService's legend more closely: heavy rain stays in the reds, and the possible-hail run of purple, white, green, and pink starts around 45 dBZ.

Fixes:

- Weather: The last MeteoAlarm feeds are matched by geometry: Bulgaria, Romania, France, Hungary, Belgium, North Macedonia, and Czechia. Every European alert now applies to the ground it covers.
- Weather: Alerts in Switzerland show again. The Swiss feed had grown past the size linecast would read, so the board showed a quiet day.
- Weather and tides: The live views no longer freeze on a slow network. Refreshes load in the background while the view keeps drawing what it has.
- Weather: The header names small towns correctly. It could show the timezone city ("New York") instead of the place itself.
- Sunshine: Sunrise and sunset times are more accurate. They could be ten or more minutes out in spring and autumn, most at high latitudes. The sky in both views and the globe's day/night edge sharpen with them.
- Sunshine: Languages with different words for morning and evening twilight now use the right one: świt and zmierzch in Polish, gryning and skymning in Swedish, aube and crépuscule in French. The evening word was used around the clock.
- Sunshine: The Polish and Finnish names for nautical twilight use the standard terms (żeglarski, nauttinen), and the Italian names for morning twilight are the customary short ones (alba astronomica, nautica, civile).
- Sunshine: The Swedish, Danish, and Norwegian "days ago" phrases begin with their preposition: för 3 dagar sedan, for 3 dage siden.
- Sunshine: The year view's month axis in French tells June from July (jun, jul). Both had truncated to "jui".
- Moon: The Korean phase names use the everyday words: 상현달, 보름달, 그믐달, with the gibbous phases as 차오르는 달 and 기우는 달.
- Tides: The Indonesian view names the wave and swell lines in Indonesian (gelombang, alun) instead of English.
- Radar: Frames that arrive incomplete are fetched again instead of drawn, since the missing parts looked like clear weather. A source that cannot serve its tiles falls back to the next.
- Chart and map labels in scripts with combining marks, Thai for one, keep those marks.
- Shell completions offer the `calendar` command and its choices.
- The hover pop-ups in weather, tides, radar, and the sunshine year view sit clear of the mouse pointer instead of underneath it (thanks [@ebrannin-bw](https://github.com/ebrannin-bw) for [#48](https://github.com/ashuttl/linecast/issues/48)).

## 2.2.2 — 2026-09-02

- Weather: Alerts across Europe now match the ground they cover. Most MeteoAlarm feeds name a warning's region by code rather than by outline, and linecast now carries the outline for every code, so a warning for a county reaches that county and nobody else. Matching by area name, which went wrong in Poland (issue #57), remains only where a feed carries neither.

## 2.2.1 — 2026-09-02

- Weather: Alerts in Poland no longer bury the forecast. Warsaw was getting every warning in the country, 419 of them, because the Polish word for province matched them all (issue #57). Words that name a tier rather than a place are now set aside in every MeteoAlarm language, along with any word that matches most of a country.
- Weather: A warning filed county by county, word for word the same across a province, now shows once, naming the reader's own county.
- Weather: The board keeps at most eight alerts, gravest first, whatever a feed sends.

## 2.2.0 — 2026-08-31

Sunshine has a year view. The Moon's phases and times are more accurate, and official weather alerts now reach India, New Zealand, and six more European countries.

New this version:

- Sunshine: `--year` draws a column of sky for each day of the year, with sunrise and sunset as the edge between night and day: blue by day, navy by night, a soft band of twilight between. A marker sits on the current day and time, and in live mode `y` switches between the day and the year.
- Sunshine: Pointing at a day in the year view shows its sunrise, sunset, and day length, and the sky at the time under the pointer: daylight, one of the twilights, night, or sunrise, sunset, and solar noon themselves when the pointer is near them. The times keep the clock that day will keep, named when it differs from today's (`06:36 EST`).
- Sunshine: The year is drawn in the location's current UTC offset, so the edge stays smooth. `--dst` plots each day in its own offset instead, and the clock changes show as steps.
- Sunshine: Where the sun does not rise or set, both views now say which it is, midnight sun or polar night, instead of a sunrise and sunset that were both solar noon. `--json` already reported this as `polar`.
- Sunshine: The info line names the sky at the moment shown: daylight, a twilight, night, or sunrise, sunset, and solar noon as they pass.
- Moon: Phases, illumination, and the Moon's age come from where the Moon actually is, not from an average month. New and full moons now land within a quarter of an hour of the published times, where they could be most of a day out, and the evening's phase is the one the almanac names. Moonrise and moonset improve with them.
- Moon: The lit edge now faces the Sun. It was drawn square to the Moon's poles, as much as a half turn out.
- Moon: The disc is drawn at the tilt you would see from your latitude and the Moon's place in your sky, and it turns through the night. It used to be flipped over south of the equator and left at that.
- Weather: Official alerts in India, from SACHET, the national warning system: IMD weather warnings, flood bulletins, and state nowcasts. They show in English; `--lang hi`, or another Indian language code, uses the alert's own text in that language where the source wrote one. The rest of the app stays in English.
- Weather: In India, air quality is the CPCB's National AQI, the number official bulletins report, with its category (Good to Severe), instead of the US index. `--json` adds `india_aqi` and its category.
- Text in scripts that stack marks on their letters, Devanagari, Thai, Arabic, now measures the width the terminal gives it, so an alert in one of them lines up instead of pushing the layout about. linecast asks the terminal once how it draws a conjunct and its vowel sign, since terminals disagree.
- Weather: Official alerts in New Zealand, from MetService, matched to your spot by each warning's own polygon.
- Weather: Alerts now also cover Ukraine, Israel, Bosnia and Herzegovina, Moldova, Montenegro, and North Macedonia, through MeteoAlarm.
- Maps: Near the poles, where the satellites cannot see, the clouds carry the satellite picture onward, matching its cloudiness, brightness, and grain, instead of switching to a forecast model. The globe looks more natural zoomed all the way out with clouds on.
- Maps: Street tiles fall back to the OpenStreetMap US Tileservice when OpenFreeMap doesn't answer. The credit line names whichever source drew the map.
- Maps: `LINECAST_ELEVATION_URL` accepts a full tile URL template, for elevation hosts with their own path shape.
- Location: IP geolocation and place-name search each have a second source, asked when the first doesn't answer.
- Radar: `--source` pins one frame source, `librewxr`, `rainviewer`, or `iem`, instead of choosing by location, for comparing what each shows over the same spot.

Fixes:

- Sunshine: On a light terminal theme the night sky is dark and the day light, in both views, and the sun keeps its white centre and warm glow. The night used to be the page, and the sun turned dark against the daytime sky.
- Moon: On a light terminal theme the sky is dark and the Moon is light, instead of a dark disc on the page.
- Maps: On a terminal taller than it is wide, zooming all the way out keeps the whole globe on screen. It used to fit the height and run the planet off both sides.
- Weather: The high and low inside a day's temperature bar turn white where the bar is dark, instead of vanishing into the cold end of the scale.
- Weather: The wind and UV readings under the hourly chart hold still while the chart scrolls, and no longer pick up a stray digit: a 22mph wind could read 220.
- Radar: The themes drawn in the terminal's own palette (terminal, dusk, ember, ink, marangai) survive a fallback to RainViewer instead of dropping to its blue scheme.
- Debug: A provider record that could not be parsed shows up in the `--debug` transcript, with a count, instead of being dropped in silence.

## 2.1.0 — 2026-08-28

New this version:

- Moon: The disc now shows the real lunar surface, from NASA's Lunar Reconnaissance Orbiter imagery, instead of a sketch of the maria.
- Moon: The star field mixes star shapes and brightnesses, so the sky reads as stars of different magnitudes rather than a scatter of identical blocks.
- Moon: Moonrise and moonset lead with how long until they happen, then the clock time: "Moonrise in 6h 29m (20:59)". A time on a later day names the day in the same parentheses.
- Moon: When the Moon is up, the altitude line also names the compass direction to look in. `--json` gains `azimuth_deg`.
- Maps: The globe draws inland water. The Great Lakes, the Caspian, Baikal, and every other lake big enough to see are water at planet zoom, in both the terrain and street views, with a shoreline.
- Maps: City lights belong to the terrain view. The street view no longer lights its cities, flat or on the globe; its fills stay a little brighter at night to make up for it.
- Maps: Better style consistency between street maps in flat mode and globe mode.
- Maps: With sunlight and shadows on, street map coastlines and roads dim on the night side.
- Maps: The tile cache no longer grows without limit. Tiles from a superseded edition of the map are dropped and the rest kept under 256 MB, least recently seen first. `LINECAST_MAPS_CACHE_MB` sets another size, and `linecast doctor` shows what the tiles are using.

Fixes:

- Maps: Near the poles, as you zoom out, the map switches to the globe sooner. Flat maps of Antarctica used to run off the edge of the world.
- Weather: A severe European alert now shows only where it applies. A MeteoAlarm feed covers a whole country, so a flood warning for a single river gauge was reaching everyone in it.
- Weather: The daily forecast keeps its rows on one line in Japanese, Chinese, and Korean. Double-width labels were measured by character count and pushed the last rows off the edge.
- Tides: The header names the place instead of its coordinates. Where only the global model covers, a tide table for the wrong hemisphere used to look like any other.
- Live views: Taking a screenshot with cmd-ctrl-shift-4 on a Mac no longer kills the view and leaves the shell echoing mouse movements. Ctrl-\ now quits cleanly as well.

## 2.0.0 — 2026-08-26

linecast 2.0 runs on Windows, installs a single `linecast` command, and picks its defaults from your location. Upgrading from 1.x, four things change unless you say otherwise; each has a one-line fix below.

Major changes this version:

- Windows: linecast now runs in Windows Terminal. Windows installs `tzdata` and `truststore`; macOS and Linux remain dependency-free.
- Install (breaking): The six short commands (`weather`, `sunshine`, `moon`, `tides`, `radar`, `maps`) are no longer installed, because their names collide with other programs. Use `linecast <command>`, or run `linecast link` once to put the six names back as links to the `linecast` binary (it skips any name something else owns; `--remove` undoes it). A shell alias works too.
- Units: Metric is now the default everywhere except the United States, going by the saved location or the machine's IP. `linecast units metric|imperial|auto` saves a choice, `LINECAST_UNITS` and `--metric`/`--imperial` override it per run, and radar and maps follow the same setting instead of guessing from the interface language.
- Clock: The default follows the country instead of the interface language: 12-hour in the United States, Canada, Australia and the other places that write 6:50 pm, 24-hour everywhere else. A French speaker in the US now gets 12-hour; an English speaker in France, 24-hour. `linecast clock 12|24|auto` saves a choice, `LINECAST_CLOCK` and `--12h`/`--24h` override it per run, and sunshine follows the same preference as the other views.
- Icons: linecast no longer assumes a Nerd Font. Terminals known to bundle its glyphs use them, other interactive terminals use emoji, and piped output uses plain Unicode. `linecast icons nerd` restores the full set for a terminal whose font linecast cannot see; `--icons nerd|emoji|plain` and `LINECAST_ICONS` choose per run, and `linecast doctor` previews all three.

Other changes:

- Settings: `linecast units`, `linecast clock` and `linecast icons` now say which setting is in force and where it came from.
- Cache and settings: JSON is read as UTF-8 on every platform. A saved location or cached response with a non-ASCII name no longer appears lost on Windows.
- Drawing: Emoji in alerts and map labels wrap at their real display width. Sunshine and moon no longer get colored rings on 256- or 16-color terminals, and sunrise and sunset use plain arrows in every icon set.
- Moon: The full-screen layout follows the terminal. A wide window floats the details beside a taller moon; a small one shortens or drops lines before they can wrap, and every size fills the screen while keeping stars out from under the text.
- Moon: The next full moon is given its traditional Almanac name — Harvest Moon, Wolf Moon, Blue Moon and the rest. The last line gives the day of the year and counts down to the next equinox or solstice; `--json` has the same fields.
- Tides: Queensland stations now show the future. Maritime Safety Queensland's predicted datasets cover the whole calendar year, replacing the monitoring feed that ended at the present and left the curve flat. Coverage grows from about two dozen sites to nearly eighty gauges; a saved station from before resolves to the nearest new gauge.
- Tides: The footer names the station's data source — NOAA, CHS, Queensland Open Data, Hong Kong Observatory, TideCheck, or Open-Meteo's tide model — and the location pill drops its "(model)" suffix. The header and marine line fit correctly with emoji, and an unfamiliar timezone shows its UTC offset instead of plain UTC.
- Tides: `--station` and `TIDE_STATION` accept a TideCheck station ID such as `fes2022-lisbon` without spending a search request. `linecast tides --nearby`, `--search`, and `linecast doctor` show how many of the day's 50 free-tier requests have been used; `LINECAST_TIDECHECK_PAID=1` hides the tally.

## 1.17.0 — 2026-08-25

- Tides: Hong Kong has its own tide stations now. Thirteen Hong Kong Observatory stations join the list, picked automatically for a location in Hong Kong or by code with `--station CCH`. Thanks to ErwinTATP.
- Weather: Alerts in Hong Kong come from the Hong Kong Observatory's warnings -- rainstorm, tropical cyclone signals, thunderstorm and the rest -- instead of the mainland service. Thanks to ErwinTATP.
- Doctor: `linecast doctor` shows which build is running, where the settings file and the cache live and whether the cache can be written, what the terminal supports, which preferences are in force and where each came from, and whether every provider answers. `--json` prints the same report for a bug report; `--offline` skips the probes.
- Debug: `--debug` now reports every fallback a command takes -- a provider that did not answer, a cache file that could not be read, a tile that would not decode -- as one line naming the provider, the host and what was shown instead. URLs in the debug output are reduced to scheme, host and path; the query string is never printed. The same redaction applies to URLs quoted by an exception or traceback.
- Live: A background task that crashes under a live view no longer scrawls a traceback across the screen. One line after the view closes says it happened; `--debug` prints the traceback in full. A failed request in `weather` or `tides` now shows what did arrive instead of ending the command with a traceback.
- Installer: The `curl | sh` quick start with no arguments works again on Debian and Ubuntu, where the script had been exiting without running anything.
- Installer: When nothing but `python3` is available, `get.sh` keeps its environment in a private per-user directory instead of a shared path under `/tmp`, and picks up new releases once a day.
- Cache: On macOS the cache now lives in `~/Library/Caches/linecast`; an existing `~/.cache/linecast` stays in use. `LINECAST_CACHE_DIR` and `LINECAST_CONFIG_DIR` put the cache and the settings file wherever you like, and `XDG_CACHE_HOME` is honored.
- Cache: A cache directory that cannot be written or read no longer stops a command; the data is fetched and shown without being kept. `linecast units` and `linecast location` say in one line when the settings file cannot be saved, instead of printing a traceback.
- Weather: In live mode, `o` opens the alert on screen. After the view refreshed its alerts it could open the wrong one, or none.
- Plumbing: A map of the code for contributors in ARCHITECTURE.md, a lint check in CI, and type annotations on the modules that talk to the network. The live views share one model now; nothing changes on screen. Python 3.14 is tested, and a release ships the exact wheel that CI installed and smoke-tested.

## 1.16.1 — 2026-08-24

- Plumbing: Fix for a failing macOS test

## 1.16.0 — 2026-08-24

- Security (also released as 1.15.2): every network response is read in chunks against a hard size cap (8 MiB for JSON, 16 MiB otherwise), refused early when the declared Content-Length is oversized, and gzipped vector tiles decompress against the same cap. A broken or hostile server can no longer balloon linecast's memory or its emitted output.

- Maps: Fixed a bug that could have caused rendering the globe to fail until the user interacted with it.
- Maps: The globe's first frame draws in about a second and a half instead of five or more.
- Maps: A fresh install draws its first globe without a network connection.
- Radar and maps launch faster.
- Maps: Terrain color accounts for climate as well as elevation, using the Köppen-Geiger classification, so deserts read as sand and dry plateaus as stone. Applies to the terrain view and the globe.
- Maps: `l` hides borders, coastlines, and rivers along with the labels, in the terrain view and on the globe.
- Maps: With the sun on, the globe's atmosphere glow fades into night along with the ground beside it.
- Weather: The climate archive behind the above-or-below-average note is downloaded once a week instead of once a day.
- Weather: In live mode, a failed air-quality or climate-average fetch no longer retries the network on every mouse movement.
- Completions: The tides, sunshine, and moon completions now offer `--location`, tides also `--emoji`, and sunshine `--lang`. The scripts are generated from the commands' own option definitions, so they can't fall behind again.
- Completions: fish's `linecast completion` now offers nu and nushell, and the unknown-shell message lists them.
- Maps: Dragging and spinning the globe is more than twice as fast, and hovering over it no longer re-places its city labels on every repaint.
- Maps: Panning and zooming the terrain view is about three times faster, and a view on a cold cache no longer waits for each tile source in turn.
- Tides: Opening the tide chart is much faster the first time each day, and the cache directory stops gaining new files every day. Old per-day cache files left by earlier versions are cleaned up on the next run.
- Radar: The frame on screen is fetched before the rest of the animation window, so a fresh view fills in sooner.
- Radar: Local color themes draw faster, and switching between them no longer waits on the network.
- Radar: Refreshing the frame list happens in the background, so a slow connection can't pause playback.
- Requests to the same server reuse one connection instead of opening a fresh one each time, so tile pyramids and the forecast's several calls arrive sooner.
- Every command starts a little faster.
- Radar: Quitting the live view no longer waits for the rest of the animation window to download, and a one-shot render fetches only the frame it shows.
- Radar and maps: Fixed a bug where a download finishing as the view closed could corrupt a cached tile.
- Maps: Fixed a bug where dragging the globe could leave the view blank until the next repaint.

## 1.15.1 — 2026-08-23

- Maps: the cloud layer now covers the poles. The satellite mosaic ends near the 72nd parallels; poleward, Open-Meteo model cloud cover fills in, fading in where the mosaic fades out, so a pole-centered globe no longer shows a ring of falsely clear sky.

## 1.15.0 — 2026-08-22

- Live views follow the terminal theme: switch your terminal's colors while weather, radar, maps, sunshine, moon or tides is open and the view re-inks itself in the new palette, no restart. On Omarchy the switch is picked up at once; elsewhere within a couple of seconds.

## 1.14.0 — 2026-08-22

- Radar: five color themes drawn in linecast itself rather than on the tile server — `terminal`, now the default, draws rain in your terminal's own palette; `dusk`, `ember` and `ink` are ramps that adapt to a light or dark background; `marangai` follows MetService New Zealand's stepped bands. They read reflectivity from LibreWXR's grayscale scheme, so snow is colored separately. The theme picker lists these above the server's schemes.
- Radar: the footer says when the frames come from a precipitation model rather than radar — everywhere outside North America, Europe and a few East Asian networks.

- Sunshine: the solar arc is drawn in braille, and the horizon is a dotted braille hairline that dissolves into daylight — it shows only where the sky is dark. The half-blocks now render only the sky.
- Sunshine: once the sun is up, the glow centers on its height in the plot rather than staying at the horizon.

- README: a Lineage section. A videotex terminal draws the weather, sometime in the 1980s.
- Screenshots: the sunshine pair and the hero desktop, reshot with the braille arc.

- Quick try with nothing but curl: `curl -sL .../get.sh | sh` is in the README.
- get.sh: without a terminal to reclaim, fall back to `--print` instead of failing.

## 1.13.0 — 2026-08-20

- Nushell completions: `linecast completion nu`. The project's first outside contribution — thank you, @kurokirasama.
- A changelog. Release notes now ship with each tag and GitHub Release.

## 1.12.0 — 2026-08-20

- Tides: subordinate stations work, drawn from NOAA's high/low predictions, and are matched correctly when picking the nearest station.
- Tides: `--print` output no longer contains escape codes.
- Sunshine, moon, and tides honor the location flag and its clock.
- Weather: the fetch spinner gives up instead of spinning forever.
- Radar: cached frames older than a day are deleted.
- Live mode: signals and exit codes pass through cleanup.
- The COLUMNS and LINES environment variables are respected.
- Cache files are written atomically.
- Packaging: screenshots are no longer shipped in the sdist.
- CI: tests also run on Python 3.11 and macOS.

## 1.11.0 — 2026-08-19

- Units: a preferred unit system can be saved in the config file.
- README: a screenshot of the globe and a table of keys.
