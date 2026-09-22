# Changelog

Notable changes, by release. Notes for the next release collect under **Unreleased** and get a final edit when `release.sh` runs.

## Unreleased

- Weather: In Croatia, warnings filed by county are matched to your address by the county's boundary. They had been matched on the county's name.
- Weather: The current conditions come from the nearest airport's latest report, where one is close by and recent, instead of from the forecast model alone. A morning fog the model is slow to clear no longer lingers in the header after the sky has cleared. The credit line names the Aviation Weather Center when its report is used.
- Maps: The terrain map is drawn on the globe's geometry at every zoom. A regional view, a few degrees wide and up, now curves as the globe does instead of lying flat, with its borders, rivers and city dots curving with it, and zooming out no longer cuts from a flat map to a planet. Street mode is unchanged.
- Maps: The terrain map is drawn on the globe's geometry at every zoom. A regional view, a few degrees wide and up, now curves as the globe does instead of lying flat, with its borders, rivers and city dots curving with it, and zooming out no longer cuts from a flat map to a planet.
- Maps: The street map is drawn on the globe's geometry too. A view a few degrees wide and up curves as the globe does, with its roads, water, buildings and names curving with it, and zooming out to the planet eases through instead of cutting to it. A close street view is unchanged.
- Maps: Zooming out to the planet no longer changes the city names, in either the terrain or the street map: the same cities, spelled and drawn the same way, either side of it. A regional view names more of the towns around it, and the street map at road-atlas zooms names cities as well as countries. The capital's star stays with the closer views.
- Weather: The forecast paragraph mentions fog: when it closes in, and when it lifts. Fog already out there is said as when it clears, or as holding through the day or the night.
- Weather: The forecast paragraph leads with the rain worth planning for rather than an early chance of a few drops, names a turn to thunder or snow, agrees with the header about what is falling now, and names a wet day later in the week by its heaviest hour.
- Weather: A forecast read in the small hours calls the coming night "tonight" rather than "tomorrow night". Rain that turns to something else within one part of the day is said to do so later in it, instead of naming the same morning twice.
- Weather: The prose names the hour the sky clears or clouds over, after dark as well as by day, instead of the first morning hour that showed it. A felt temperature the header already shows is no longer promised for later.
- Weather: The felt-temperature sentence no longer blames dry air for cold, damp weather. Below-freezing readings on a humid day name the wind, or say nothing, instead.
- Language: Hong Kong Chinese (`zh-HK`) is a regional variant of Traditional Chinese, and a Hong Kong or Macau locale chooses it. It uses the Hong Kong Observatory's words for the weather (天晴, 大致多雲, 密雲, 驟雨, 雷暴, 警告) and Hong Kong's for everyday things (空格鍵, 公共交通, 駕車, 單車, 農曆新年); Traditional Chinese otherwise follows Taiwan, as before.
- Weather: In European Portuguese, European Spanish and Canadian French, the day chip and the stale-forecast notice name the day in the reader's language instead of English.
- Weather: The sky is named on the National Weather Service's five-step scale, which adds Mostly Cloudy between Partly Cloudy and Overcast. Each day in the daily list is named by its average cloud cover rather than its cloudiest hour, so a day with one grey hour no longer reads as overcast. In most languages, the steps now use the national weather service's own terms.
- Weather: The current conditions come from the nearest airport's latest report, where one is close by and recent, instead of from the forecast model alone. A morning fog the model is slow to clear no longer lingers in the header after the sky has cleared. When a report is used, the credit line names the Aviation Weather Center and the station, by its airport code.
- Maps: Dragging the street or terrain map now shows the real map at the new position, painted to every edge, instead of the last one slid across bare ground. A short pan needs nothing from the network at all, and neither does the frame it comes to rest on.
- Maps: Small ponds no longer get a shoreline of their own on the street and terrain maps. They are still drawn as water; a lake is given a shore once it is a few cells across, so a view of lake country is no longer a field of little rings.
- Tides: The live view has the location menu weather has. Click the station name, or press `l`, to choose a recent place or search for one, and the tides switch to the station nearest it. The recent places are shared with weather.
- Weather: The place name in the header sits in a chip, as it does in tides, and is the brightest thing on the line. The conditions, temperature, and feels-like read closer together, with the wider gaps kept for what follows.
- Maps: A flat map that has been flicked no longer waits until it stops to fill in. The place it will come to rest is fetched the moment the map is let go, and the new ground appears while it is still gliding.
- Weather: In Japanese, rain that turns heavy is said to strengthen (雨が強まり) instead of becoming heavy rain. A turn to another kind of precipitation reads as before.
- Weather: Wind speeds are in metres per second in Japanese, Korean, Danish, Norwegian, Swedish, Icelandic, Finnish, Russian, Ukrainian, and Czech, as the forecasts in those countries give them. Other languages keep km/h, and imperial units keep mph. `--json` names the unit as before.
- Weather: In Japan, the warnings shown are the ones for the reader's own city, town, or ward, not every one the prefecture has out. A reader in Shinagawa no longer sees a high-wave advisory for the Izu islands, which are Tokyo too.
- Maps: The view moves instead of jumping: a zoom eases to its new scale, a drag let go while moving coasts to a stop, `w a s d` slide the view along, and a searched place or a directions step is flown to. Terrain keeps the last map on screen while the next one loads, as the street map already did.
- Maps: Zooming the globe no longer flashes a blank disk. The planet stays on screen, scaled to where the zoom is going, until the sharper one arrives, and the sharper one starts loading at the keypress rather than after the zoom settles.
- Maps: The globe turns about twice as fast under a drag, since the planet is no longer rebuilt for every frame. Its shading is worked out once, in the background the first time a globe opens, and kept in the cache; that first globe draws the old way for a second or two while it happens.
- Help: `linecast --help` is laid out and coloured like the commands' own pages, and wraps to the terminal. Each command's `--help` opens with a short usage line and lists its flags in sections, its own first, instead of one long list under a usage line that named every flag.
- Maps: Each frame sent to the terminal is about half the size it was, since the map no longer repeats a colour the terminal is already using. Panning and rotating feel smoother on a slow terminal or over ssh.
- Maps: The lights on the night side of the globe, and on the shaded terrain map, now come from NASA's Black Marble picture of the Earth at night, bundled with linecast, instead of one glow per city. They fade out as you zoom in to where the terrain has the detail.
- Maps: While a street view loads after a pan or a zoom, the last view stays on screen, moved and scaled to where the new one will be, instead of bare ground. The tiles around the view, and one zoom step in the direction you last went, are fetched ahead while you read. Contributed by [@N30Yang](https://github.com/N30Yang) in [#117](https://github.com/ashuttl/linecast/pull/117).
- Sunshine: The help hint has moved to the top-left corner of the graph, where the year view keeps it, so the sunrise and sunset times sit at the two ends of the line below.
- Docs: The pages on sources, calendars, hours, cultures, the gallery, and the architecture have moved from the top of the repository into a `docs/` folder. Links to their old paths on GitHub no longer resolve.
- Sky, moon: The stars, the constellations, and the Milky Way now line up with the Moon and the planets. They were drawn about a third of a degree away from them, which showed at the closest zoom.
- Weather: Fixed a bug in the countries on MeteoAlarm where, after the live view's first refresh, every warning in the country without a map of its own was shown. They are matched to your address, as they are when the view opens.
- Tides: With a TideCheck key on the free plan, linecast now stops at the fifty requests a day the plan allows and shows cached tides until the day turns, as the README said it did.
- Radar: Cached NEXRAD frames are cleared after a day, as the other sources' tiles already were, so the cache stops growing.
- Weather: In Canada the air quality shows the AQHI, the number on Environment Canada's own scale, with its risk level. It is Environment Canada's reported value for the nearest community, and is computed from the pollutants, including the AQHI-Plus rule for smoke, where no community is near. The label reads CAS in French.
- Language: Portuguese, Spanish, and French each have a second regional form. `pt-PT`, `es-ES`, and `fr-CA` read the words that differ in Portugal, Spain, and Canada, and a terminal set to one of those countries picks it by itself. Spanish is Latin American throughout now; the maps had used Spain's words.
- Weather: The prose under the graph says more, in the order things will happen. It now mentions the sky clearing or clouding over, gusts, a freeze overnight, how much snow will be on the ground by morning, a felt temperature ahead that is extreme for the place, the next rain worth planning for later in the week, and a second bout of rain after a break. The comparison with yesterday or tomorrow gives the number of degrees, "likely" is only said of rain that is likely, and shades of the same rain are no longer called a change. Rain in the last day is mentioned from a tenth of an inch, and temperatures below zero carry a proper minus sign. In all twenty-eight languages.
- Moon, sky, maps, radar: Round things are drawn round, and square ground stays square, on wide and narrow terminal fonts alike. linecast reads the font's cell shape from the terminal where it can; `LINECAST_CELL_ASPECT` overrides it.

## 2.7.0 — 2026-09-19

linecast speaks Turkish, Esperanto, Russian, Romanian, Czech, Greek, Swahili, and Chinese in the traditional script, twenty-eight languages in all, and sunshine can read the day in the halachic, Roman, Edo, Islamic, or Swahili hours. Weather lets you change location from inside the view.

New this version:

- Language: linecast speaks Turkish, Esperanto, Russian, Romanian, Czech, Greek, and Swahili. `linecast language tr`, `eo`, `ru`, `ro`, `cs`, `el`, or `sw`, or a terminal locale in one of them, puts every view in that language, and the sky names its constellations in each and its brightest stars where the language has its own names. Turkish search takes a dotless ı or a dotted i alike, so `yildiz` finds Yıldız, and Esperanto search takes the x-system, so `gxemeloj` finds Ĝemeloj. (If your terminal is set to the `eo` locale, please [reach out](https://github.com/ashuttl/linecast/discussions). I want to hear about it.)
- Language: linecast speaks Chinese in the traditional script. `linecast language zh-Hant`, or a Taiwan, Hong Kong, or Macau terminal locale, puts every view in traditional characters, with the Chinese calendar and the Chinese sky as `zh` has them. `zh` is the simplified script, as before.
- Language: More of each view reads in the display language: place names in weather and sky, units written as the language writes them, the Moon's almanac counsel, the tides footer, and Hong Kong's weather warnings in Chinese.
- Sunshine: The day can be read in a tradition's hours beside the civil clock. `linecast hours` saves a choice and `sunshine --hours` sets it for one run. HOURS.md describes each system and what it is checked against. Suggested by [@ylub](https://github.com/ylub) in [#95](https://github.com/ashuttl/linecast/discussions/95).
  - `halachic` reads the sha'ot zmaniyot and the zmanim from alot hashachar to tzeit, and `halachic-mga` reads them by the Magen Avraham.
  - `roman` reads the twelve horae and four vigiliae of Rome.
  - `japanese` reads the six koku of the Edo day and night, 明六つ to 暮六つ.
  - `islamic` reads the prayer times, Fajr to Isha, by the convention of the country shown or a named one, and counts down the fast in Ramadan. In Turkish the prayers are named as the Diyanet prints them, İmsak to Yatsı.
  - `swahili` reads Swahili time, saa moja at seven in the morning and seven at night, and is on by default in Swahili.
- Weather: Change location from the top-right menu, with search suggestions and the ten most recent places. Recent places are kept between runs and can be cleared, and the displayed place can be saved as the default for every view.
- Weather: The hourly graph defaults to `--temp-range auto`: the typical-year climate scale when there is room for it, and the forecast's own range when that scale would exceed 5°C (9°F) per row. Resizing the terminal reconsiders; `climate`, `forecast`, and `world` behave as before.
- Weather: The UV index appears under the hourly chart from UV 3, where sun protection is advised, rather than from UV 6. Suggested by [@GigaHanBaoBao](https://github.com/GigaHanBaoBao) in [#115](https://github.com/ashuttl/linecast/issues/115).
- Weather: The wind and UV readings under the hourly chart share a line when they would not overlap, so the chart gets a row more. In a short window the UV labels go first, then the wind row, then the cloud strip.
- Weather: The rain sentence says when the rain turns heavier: "Light drizzle becoming heavy rain around 23h, ending overnight", not just "Light drizzle ending overnight".
- Location: A typed place is named as the geocoder found it, such as "Tobermory, Ontario", rather than by the district around the point, and a region named for its city is no longer repeated: "Busan, South Korea", not "Busan, Busan, South Korea".
- Sky: The Chinese sky names its brightest stars in Chinese, such as 北极二, and names 星宿, 龟, and 平 among the asterisms.
- Maps: Street maps open faster, and panning to a new area no longer reconnects to the tile server each time. Contributed by [@N30Yang](https://github.com/N30Yang) in [#117](https://github.com/ashuttl/linecast/pull/117).
- Live views: The hint that points to the `?` panel reads `? help` rather than `? keys`, in every language. A hover chip goes away once the mouse has been still for a few seconds.
- Docs: The README is available in [Japanese](README.ja.md), and CONTRIBUTING.md says how a change gets into a release.

Fixes:

- Weather: A forecast from an earlier day is no longer read as today's. The historical comparison in the header, and the JSON's today and upcoming forecasts, use the current date, and the comparison is left off when the cached forecast no longer covers today.
- Weather: The day after the clocks change reads by the clock there. Sunrise, sunset, the hours, and the day and night tint of the hourly chart all ran an hour off.
- Weather: Startup waits at most 30 seconds for data providers and keeps whatever has arrived, and Ctrl-C exits cleanly while loading. A gap in the forecast or an odd answer from a warning feed no longer ends the view in an error, and a missing current temperature is left off rather than shown as 0°.
- Weather: The hourly graph's climate scale arrives reliably after a change of location, and scrolling back from either end of the chart responds immediately, even after extra wheel or arrow-key input at the limit.
- Weather: The prose forecast wraps its lines more naturally.
- Live views: Input that arrives while the terminal is busy drawing is painted once it is free, rather than waiting for the next input. Quitting with Ctrl-C no longer leaves the shell without echo or with stray text on the command line.
- Sky, maps: On Windows, Ctrl-C closes an open search field, and a second quits. It did nothing before. Found by [@cygnostik](https://github.com/cygnostik) in [#114](https://github.com/ashuttl/linecast/issues/114).
- Maps: Editing a search clears the old suggestions and cancels a pending Enter, so a changed query cannot send the map to an unintended place, and a result without coordinates no longer makes the whole search unavailable. Search remembers the selected language when a provider fails.
- Maps: Overlapping search and directions requests keep their rate limits, including after the computer wakes from sleep.
- Downloads: An incomplete compressed response no longer replaces cached data, and a response in several gzip members is read in full.
- Radar, maps, tides: A stale or damaged cache file is fetched again rather than kept, a damaged street tile is skipped rather than failing the view, and a failed prefetch waits before trying again.
- Radar: A location near the poles no longer fails to open.
- Tides: The header shows the range only when the window holds both a high and a low; a station with one low a day printed a negative range. A Canadian or TideCheck station whose details could not be fetched no longer ends the view in an error, and a place name in the header keeps the capitals its language gives it, such as "préfecture d'Osaka".
- Moon: On a short window, the month grid is no longer cut off.
- Settings: A hand-edited config.json that is not valid is ignored rather than breaking every command, and `--location` and `linecast location set` refuse coordinates that are out of range, such as 91,0.
- Language: A Norwegian terminal locale, nb_NO or nn_NO, puts linecast in Norwegian.
- Units: `WEATHER_UNITS` applies to the weather command alone, as the README says.
- Completion: Fixes to completion in bash, zsh, and nushell.
- Print: Piping `--print` into `head` ends quietly.

## 2.6.1 — 2026-09-16

- Completion: The bash and zsh completion scripts load again. Both have been failing since 2.5.0 due to flags with hyphens.
- Weather: The ten-year climate archive behind the "warmer than usual" line and the hourly graph's scale downloads at a quarter of its former size, as do the forecast and air quality. Every download now asks the server to compress its answer.

## 2.6.0 — 2026-09-15

- Weather: The hourly graph now keeps one scale from day to day: the range of a typical year where you are, taken from the hottest and coldest day of each of the past ten years. A hot day reaches the top of the graph and a cold one the bottom, and the graph no longer rescales each time the forecast changes. Until now the forecast's own high and low always touched the edges, so a mild day looked like a heat wave. `--temp-range forecast` fits the graph to the forecast the old way, and `--temp-range world` uses one scale everywhere, -40 to 50°C. Contributed by [@db48x](https://github.com/db48x) in [#94](https://github.com/ashuttl/linecast/pull/94).
- Weather: The hourly graph labels the top and bottom of its temperature axis, in dim type at the edge where the curve leaves room.
- Weather: The now line and the midnight dividers no longer darken the cloud strip and the precipitation bar where they cross them. They pass behind, so a darker cell always means less cloud or a fainter chance of rain. The line under the mouse still shows through.
- Weather: In Japanese, drizzle is 霧雨 at every intensity, and the sentence about rain continuing or ending reads more naturally.

## 2.5.2 — 2026-09-14

- Live views: Quitting no longer leaves the terminal's colour replies on the shell's command line. linecast waits for the terminal to finish answering, at startup and on the way out, before it hands the terminal back.
- Live views: Scrolling or dragging faster than the terminal can draw no longer queues up frames that keep playing after you stop. Each frame waits until the terminal has drawn the one before it, and the input that arrives meanwhile goes into the next frame.

## 2.5.1 — 2026-09-14

- Live views: The last letter of the `? keys` hint is back. A row that reached the last column lost its final character to the clear that follows each frame, so the weather view's hint read "? key" since 2.5.0.
- Weather: A sunrise or sunset time in the hourly chart's header keeps a space between itself and the day name or the temperature range beside it, instead of running into them.

## 2.5.0 — 2026-09-14

linecast speaks Ukrainian and Vietnamese, twenty languages in all, and the Moon keeps a Vietnamese calendar. The weather chart shows how much rain to expect and how cloudy it will be, and every view fills the window.

New this version:

- Language: linecast speaks Ukrainian and Vietnamese. `linecast language uk` or `linecast language vi`, or a terminal locale in either, puts every view in that language, and the sky names its constellations and best-known stars in it.
- Moon: A Vietnamese calendar. `linecast calendar vietnamese` reads the lunar date, solar term, and festivals at Vietnam's own meridian, so Tết falls on the day Vietnam keeps it. It is the default in Vietnamese.
- Moon: The calendar opens the week on the day the country's printed calendars do, judged by your location rather than the display language: Monday in most of the world, Sunday in the United States, Canada, Japan, Korea, and others, Saturday in Egypt and the Gulf. `linecast week sunday` saves a choice, and `moon --week-start` sets it for one run.
- Moon: The sunlit ground fades toward the terminator, as it does in a photograph, instead of stopping at a hard edge, and the unlit limb no longer shows a faint rim. The new Moon is dark all the way round, a thin crescent tapers to nothing at its horns, and the full Moon runs bright to its edge.
- Weather: The precipitation bar below the hourly chart shows how much rain to expect, not how likely it is. Likelihood shows as opacity: a faint bar means rain is unlikely that hour. The bar is only as tall as the wettest hour can fill, so a week of drizzle takes one row and the temperature curve gets the rest.
- Weather: A strip of cloud cover sits above the precipitation bar.
- Weather: Hover over the hourly chart for the hour's rain and cloud cover, and over the daily chart for the day's detail.
- Weather: The live view says where its data comes from. The bottom row credits Open-Meteo for the forecast and names the service the alerts come from, such as Met Éireann in Ireland, and the `?` panel lists both. The credit is in the display language, and a service is named as it names itself: 気象庁 in Japanese, Deutscher Wetterdienst in German.
- Weather: `weather --json` names the sources in a `sources` field and gives each hour's cloud cover.
- Weather: In the morning the prose opens with how today compares to yesterday. From mid-afternoon it compares tomorrow to today, after the sentence about how the air feels now.
- Weather: The dashboard fits a short or narrow window better. The daily rows drop the words "Rain" and "Wind" sooner as the window narrows, and share one column when no day has both. A short window gives up its spacing rows before anything else, and a tall one gets a blank row above the credit.
- Weather: The prose under the chart is in the full text color, and the now and midnight lines run the full height of the hourly chart.
- Sky: Search finds a star by its designation as it is typed: "alpha cen", "alpha centauri", and "alpha crucis" all find the star, with or without the component number.
- Weather, tides, moon, sky, sunshine: The views use every column of the window. Text and graphs used to start one column in and stop one short of the right edge; now they run edge to edge, and the help hint sits in the last column.
- Help panel: The key column is in the display language too: wheel, space, hover, click, drag, and enter are translated, and the column widens to fit.

Fixes:

- Moon: The calendar shades the unlit side of each day's Moon as darkly as the main view does.
- Maps: With `--from` and `--to` and no `--location`, the map opens on the whole route instead of your own location.
- Weather: The prose explains why the air feels warmer or cooler than the thermometer only when the two are six degrees Fahrenheit or three Celsius apart. A smaller gap goes unremarked.

## 2.4.0 — 2026-09-10

A new view, `linecast sky`, draws the night sky from where you stand and knows the constellations of twenty-two traditions. Every live view now has a `?` help panel, and `w` `a` `s` `d` pan.

New this version:

- Sky: `linecast sky` shows the sky above you: the stars, the constellation figures and their names, the planets, the Moon at its phase, the Sun, and the Milky Way once the sky is dark. Drag to look around, zoom with `+` and `-`, scroll through time, and press `p` to watch the night pass. `--json` and `--oneline` say what is up. Use `linecast sky --location "auckland"` to see the sky from another location.
- Sky: `/` searches by name for a star, a planet, a constellation, or an asterism such as the Big Dipper or Orion's Belt, and the view flies to it. If it is below the horizon, the panel says when and where it rises, and Enter again moves the clock to that moment. `--at Orion` opens on one.
- Sky: `t` chooses among the constellations and star names of twenty-two traditions, from the Chinese lunar mansions to the Hawaiian star lines and H. A. Rey's figures. `--culture` and `linecast culture` pick one to open on, and Chinese comes with the language. CULTURES.md lists the sources.
- Sky: With the Hawaiian culture, the horizon carries the navigators' star compass, thirty-two houses from Hikina round to Komohana, and directions are given by house.
- Sky: Zooming in reveals fainter stars, from a catalog of nearly 117,000, and the galaxies, nebulae and clusters of the Messier list as faint glows. The pointer names them, and `/` finds them.
- Sky: `m` turns toward the Moon when it is up. The Sun and the Moon are cut by the skyline as they rise and set.
- Every live view has a `?` help panel that lists its controls in the display language, and a `? keys` hint points to it.
- Sky, maps and radar: `w` `a` `s` `d` pan the view. Maps moves daylight and directions to `S` and `D`; radar moves wind and satellite to `W` and `S`.

## 2.3.3 — 2026-09-07

- A line the terminal draws wider than linecast measured it no longer breaks the view. Views are painted a row at a time with the terminal's line wrapping off, so such a line is cut off at the right edge instead of wrapping and pushing the rest of the view, and the top line, off the screen.
- linecast asks the terminal how wide it draws emoji, Nerd Font icons and Indic conjuncts rather than assuming, and lays its rows out to the answer. `linecast doctor` shows what the terminal said. The question waits longer for an answer over SSH, as the question about the terminal's palette now does too.
- Weather: Warnings that share a line of badges now break between badges, instead of a badge splitting across two lines, and a click opens the warning under the pointer.
- Weather: The dashboard fits the window it is given. In a narrow terminal the prose wraps and the forecast rows give up their detail columns; in a short one the prose goes first and then the days furthest out, so the conditions line no longer scrolls off the top.
- Weather: The prose under the graph says why the air feels warmer or cooler than the thermometer reads, naming whichever of the humidity, the wind, the dry air or the sun accounts for most of it.
- Weather: The prose under the graph reads as prose. The sentences are punctuated and share a line where the terminal is wide enough for them, instead of taking one each.
- Weather: In Japanese, Chinese, Korean and Thai, the prose under the graph speaks of rain still to come as expected rather than certain, and the Japanese line comparing one day with the next reads as a forecast rather than a description.
- Weather: The rain in the last 24 hours, and the rain named beside a day in the forecast, now appear at the same amount of rain in millimetres as in inches. Small amounts in inches are given to a hundredth rather than a tenth.
- Sunshine: In the zones east of the date line that keep UTC+13 or +14 — Samoa, Tonga, Kiritimati — `--json` dated sunrise, sunset and solar noon a day late and named the wrong next event. The day and year views there now name sunrise, solar noon and sunset when the moment is one of them, rather than passing over it.

## 2.3.2 — 2026-09-05

The Moon sits among its real stars, shows earthshine on its night side, and turns when dragged. linecast speaks the terminal's language, and `linecast language` saves one. The help page is sorted by view, and a pinned sunshine location reads as a world clock.

New this version:

- Moon: The stars are the real sky around the Moon, from the Yale Bright Star Catalogue. Scrolling through time turns them with the night, and the Moon keeps its place among its constellations.
- Moon: The night side shows the maria faintly in earthshine, most at a thin crescent and not at all near full. It is darker than the sky around it now, as it looks in life, with the halo outlining the disc.
- Moon: Drag the disc to turn the Moon over, light and dark with it, and bring the far side round. The stars sweep past as it turns. Let go and it settles back to the face it really shows.
- Moon: In a terminal too narrow for the info column, the phase and the status sit in the top corners of the sky and the rest runs along the bottom, with the disc between. The day of the month comes before the illumination.
- Sunshine: The corner that names the place gives its time too, in both the day and year views, with the day of the week when it is not your own. A pinned location reads as a world clock.
- linecast speaks the terminal's language when it is one of the eighteen it knows, read from `LANG` the way other command-line tools read it. It spoke English until asked. `linecast language en` keeps English.
- `linecast language fr` saves the language for every run, the way `linecast units` and `linecast clock` save theirs. `--lang` still picks one for a single run.
- `linecast` on its own sorts the commands into the six views, the settings, and housekeeping, and ends with the moon's phase tonight.

Fixes:

- Weather: Alert details stay legible when a live view follows the terminal from a dark theme to a light one.
- Weather: An alert drops off the board once it expires. One kept from an earlier fetch could stay listed for as long as its provider was unreachable.
- Weather: MeteoAlarm warnings for Transnistria and Gagauzia in Moldova, and for five more Dutch coastal waters, reach the place they name. The region data is refreshed to MeteoAlarm's July 2026 list.
- Moon: A Japanese calendar chip names the evening by its lunar day instead of giving it a conflicting generic phase name.
- Cache files are now readable only by the user who owns them.

## 2.3.1 — 2026-09-03

- Weather: A forecast from an earlier day no longer passes as today's. When a newer one cannot be fetched, the view says which day the forecast is from and how to retry, the daily list names that day instead of calling it today, and `r` asks for a fresh one in live mode.

## 2.3.0 — 2026-09-02

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
