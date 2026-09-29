# Changelog

Notable changes, by release. Notes for the next release collect under **Unreleased** and get a final edit when `release.sh` runs.

## Unreleased

- Language: linecast speaks Hungarian and Slovak. `linecast language hu` or `sk`, or a terminal locale in either, puts every view in that language, and the sky names its constellations in each, with some of the brightest stars.
- Weather: Fixed the daily forecast's hover for a day of freezing rain, which read "40% chance of Mix"; it now reads "40% chance of mixed precipitation", in every language.
- Weather: More colors at the ends of the temperature scale: a deeper blue that pales toward ice down to -40°F (-40°C), and a crimson that deepens toward maroon up to 115°F (46°C).
- Weather: With --classic-colors, and in terminals that do not report their colors, the year view's background fills the whole window.
- Weather: In the daily forecast, the conditions for calm days are dimmed, so the days with rain, snow, or wind stand out.
- Moon: `--calendar icelandic` follows the old Icelandic calendar: the week of summer or winter beside the phase, the month, the next of the days the almanac names, such as the first day of winter and bóndadagur, and the moons it names, such as the jólatungl. In Icelandic it is the moon's calendar by default.
- Moon: The Moon stays in the middle of the view at every size, with the phase, the day's rising and setting, the month's new and full moons, and the year's days in the four corners, each laid out as a small table of dates and countdowns.
- Moon: The help panel names the place the Moon is seen from, with its coordinates.
- Moon: `t` hides the text and leaves the Moon alone in its sky; press it again to bring the text back.
- Help: The help pages list a flag's choices first and then say what it does, in a sentence or two.
- Radar: Fixed `radar --help`, which named the wrong keys for the satellite and wind layers.
- Moon: The month view's title sits at the left, over the first day of the week.
- Moon: `--month` opens on the month view, as `--year` does for weather and sunshine, and `moon --help` lists it. `--grid` still works.
- Language: Fixed a crash in the live views when Hebrew or Arabic text, such as a place name in a hover chip, was drawn beside numbers, in every language but Persian.
- Location: Fixed `--location`, `--to`, `--from`, and `linecast location set` refusing coordinates that start with a minus sign, such as `-33.87,151.21` for Sydney, with Python 3.13 and older.
- Sky: Fixed dawn and dusk being named the wrong way round south of the equator, in the languages that name the morning and evening twilight apart, such as Polish and Swedish.
- Tides: Fixed the chart's night shading, which began and ended an hour early during summer time. Tide times for Adak and the other western Aleutian stations are no longer an hour off in summer.
- Tides: `--oneline` names high and low tide in the display language.
- Sunshine: Fixed the day view's scale south of the equator, which drew a winter day's arc as high as a summer day's.
- Sunshine: Fixed `sunshine --json` giving tomorrow's sunrise and sunset an hour off on the evening before the clocks change.
- Sunshine: Fixed `--oneline` giving a sunrise and sunset through the polar night and the midnight sun; it now shows dashes and names the season, as the full view does. Fixed a sunrise just before midnight, in the far north in summer, showing as just after midnight.
- Moon, sunshine, sky, tides, radar, maps: Fixed Ctrl-C printing a Python traceback when pressed while the view was still loading, or during `--print`.
- Settings: Fixed a setting command, such as `linecast units imperial`, replacing a config.json that could not be read, and every setting in it, with the one setting. It now says what is wrong with the file and leaves it alone.
- Settings: A config.json that is a symbolic link, as from a dotfiles repository, stays one when a setting is saved; the setting is written to the file it points to.
- Radar, maps: `--help` no longer offers `--oneline`, which printed the whole frame; neither view has a single line to give.
- Weather: Fixed alert times on the 12-hour clock leaving out the minutes, so that a warning in force until 3:45pm read "until 3pm". In Greek they are written in words, as in the forecast.
- Weather: Fixed alerts in Canada showing no times with Python 3.10.
- Weather: Fixed blowing or drifting snow at a nearby weather station being shown as falling snow, in the conditions and in the forecast in words.
- Weather: Fixed temperatures just below zero showing as "-0°".
- Weather: Fixed a day of rain with a little snow in it giving its amount as the snow, such as "Snow 0.0″", in the daily forecast and its hover; it gives the rain's amount unless most of the day's precipitation is snow. The year view's hover does the same.
- Weather: Fixed the forecast in words saying "Below freezing overnight, down to 32°" for a low that rounds to freezing itself.
- Weather: Fixed the forecast in words leaving out the snow total when snow changes to rain and the rain lasts longer than the snow did.
- Weather: Fixed the last 24 hours' precipitation naming a kind too slight to mention, such as "0.4 cm of snow" after a dusting that was followed by 15 mm of rain.
- Moon, sky: Fixed times and dates past the next change of clock being an hour off where the location comes from the network rather than a setting, which could put a new or full moon on the wrong day.
- Moon: In the last day before a full or new moon, an equinox or a solstice, the wait is given in hours and minutes, as it is for moonrise and moonset. It read "in 0.0d" for the last hour.
- Moon: Fixed Blue Moons being missed, or named where there was none, when the two full moons of a month fell close to 29½ days apart, as in March 2029 in East Asia.
- Moon: The Moon's age is given out of the length of this month, from new moon to new moon, rather than the average of 29.5 days, which the age could pass: "Day 29.8 of 29.5".
- Moon: Fixed the Hebrew and Islamic dates turning at noon through the polar night, where the Sun does not set; they keep to the civil date, as they do under the midnight sun.
- Live views: Fixed Esc pressed while the mouse was moving turning the mouse's report into keypresses, which could swing the sky's view or fly it to the Moon.
- Live views: Fixed Ctrl-Z leaving the shell on the view's screen, with mouse reporting on and the cursor hidden. The terminal now goes back to the shell as it was, and `fg` returns to the view.
- Maps: Directions between two places with no road between them say "no route" rather than "directions unavailable", and are not asked for again.
- Radar, maps: `--zoom` with zero, a negative number, or anything not a number of degrees now says so rather than ending in a Python traceback.
- Maps: Fixed a search that found nothing as you typed, with Enter pressed before it answered, stopping at "no results" instead of looking the name up, as Enter pressed afterwards does.
- Maps: In Japanese, a place whose name is written in kana, such as さいたま市 or ファミリーマート, is labelled with that name rather than its romanization, as names in kanji already were.
- Maps: Fixed elevations in languages that write a decimal comma, where "5,094 m" read as five metres; they are grouped with a space, "5 094 m". A distance just short of a kilometre reads "1.0 km" rather than "1,000 m".
- Maps: Fixed one damaged map tile in the cache blanking the whole street view with "street tiles unavailable"; it now leaves a gap only where it was.
- Language: Fixed `LC_ALL=C` being passed over for the language in `LANG`, such as German with `LANG=de_DE.UTF-8`; linecast speaks English under it, as other programs do.
- Language: Fixed `linecast language` refusing `zh_Hant`, and a region given in numbers, such as `es-419` for Latin American Spanish, which `--lang` takes.
- Link: Fixed `linecast link` ending in a Python traceback where linecast is installed in a directory the user cannot write in, as with a system package; it says so and suggests `--dir`.
- Location: Fixed the moon, sunshine and sky views saying "Could not determine location" when offline, once an hour had passed since linecast last found where the machine is; with no location saved, they use the last place found.
- Language: A list of languages in `LANGUAGE`, as some Linux desktops set it, is read as other programs read it, down to the first language linecast speaks: `ca:es` is Spanish rather than English.
- Moon: Fixed the next moonrise or moonset in the far north on the few days a year when the Moon rises or sets twice on one date: the view, `--oneline`, and `--json` gave the next day's, or none at all, in place of the second.
- Moon: Fixed the wait for a moonrise or moonset after the clocks change being an hour out, such as "in 15h 00m" for a moonset sixteen hours off the night the clocks go back.
- Moon: In a window too short to draw the month view's discs, each day's phase sits beside its own date; it sat just before the next day's and read as that day's.
- Maps: Fixed a map tile that failed to load on a slow or dropped connection leaving a gap in the street or terrain view for as long as the view stayed put; the tile is asked for again a few seconds later.
- Maps: Names set in capitals follow Greek and Turkish spelling: Greek capitals drop their accents, "ΑΘΗΝΑ" rather than "ΑΘΉΝΑ", and in Turkish i becomes İ, "İZMİR" rather than "İZMIR".
- Maps: Fixed `--print` with `--from` and `--to` drawing your location's marker in the middle of the route and naming the map after your location. The marker stays where you are, and the header names the place the map is centred on, as the live view does.
- Maps: Fixed directions whose ends lie either side of the 180th meridian, as on Taveuni in Fiji, opening on the whole planet centred on Africa. On a street map that crosses the meridian, the route, your marker and the destination on its far side are drawn where they are.
- Maps: Fixed the saved street tiles being deleted when OpenFreeMap did not answer as the map opened and OSM US stood in for it, so that the next map downloaded them all again.
- Maps: Fixed `n` and space, which the help lists as "back to start", leaving the map where it was. They fly back to the place and zoom the map opened on, and still clear a route.
- Maps: Fixed the names of neighbourhoods, parks and water in Persian, and in other right-to-left scripts, being drawn letter by letter with their words in the wrong order. They are written as words, as street names are.
- Language: The Moon's phases are named in sentence case in Danish, Dutch, Finnish, Icelandic, Indonesian, Italian, Norwegian, Polish, Portuguese, Spanish, and Swedish, as they are in French: "Første kvarter", not "Første Kvarter".
- Tides: Fixed a low tide just below the datum, such as -0.01 ft, showing as "-0.0′" in the chart, its hover, and `--oneline`.
- Radar: Fixed the map in a view that crosses the 180th meridian, such as Fiji's or the Aleutians', leaving out the land and cities on the far side of it.
- Radar: Fixed the temperature and wind layers never loading in a view that crosses the 180th meridian.
- Tides: Fixed the line marking now, midnight, or the pointer cutting through the time of a high or low tide it passed, so that 11:10a read "11:1│a"; the time is written whole, as the height already was.
- Tides: Fixed most NOAA stations picked with `--station`, such as Back Cove in Portland, Maine, running an hour behind through summer time: the chart drew now an hour early, and `--json` gave a fixed offset for the time zone.
- Tides: Fixed the view failing with "Could not fetch tide data" in north Burnaby and around Vancouver's Second Narrows, where the nearest Canadian station predicts only the current; it now picks the nearest station with tides.
- Tides: Fixed tides from the global tide model, as for Sydney, Melbourne, and the coasts of Europe, being an hour off on the far side of a change of clock: the week before the clocks change, the tides after it were an hour early or late, and the week after, the tides before it.
- Maps: Fixed a search for a city, such as Paris, listing it twice.
- Weather: Fixed the daily forecast's rain hover saying "through the day" for a day with showers in the small hours and again at night but dry between; it gives the hours they fall between.
- Weather: Fixed the hover on the hourly chart giving an hour of snow the water it melts to, such as "0.12″" for an hour with nearly an inch of snow; it gives the snow, as the daily forecast does.
- Weather: Fixed the year view's header comparing one day's rain with the average for the whole year so far, such as "13mm · avg 824mm", when the year's past days could not be fetched. It leaves the comparison out until they come.
- Weather: Fixed the year view drawing each month's precipitation as none at all when the year's past days could not be fetched; a month with its days missing has no running total.
- Weather: `--oneline` no longer shows "Wind 0mph" when the air is all but still; it leaves the wind out, as it does when there is none.
- Weather: The last 24 hours' snow is given to the tenth of an inch, as the daily forecast gives it: "0.4 inches of snow", not "0.43 inches".
- Sunshine: Fixed `--oneline` in Persian giving the day's length in Latin letters, as "10h52m"; it is written in words, as the change beside it is.
- Tides: Fixed the waves and swell running past the edge of a narrow window, as they did in Thai, which names the points of the compass in words. Where both do not fit, the swell is left out.
- Weather: Fixed the year view's label for the average in Thai, "ค่าปกติ", losing its tone mark.

## 2.9.2 — 2026-09-27

- Weather: Fixed the year view showing only the last week for places ahead of UTC, such as Sydney, for part of each day.

## 2.9.1 — 2026-09-27

- Weather: Fixed a bug that could leave the year view showing the previous place's year after changing location, most often after searching for a new place.

## 2.9.0 — 2026-09-27

Weather can show the year so far: each day's high and low against the last ten years, and each month's precipitation against its average. The forecast in words says when snow, ice, and rain change over, and takes what is falling now from a nearby station.

New this version:

- Weather:
  - `--year`, or `v` in the live view, shows the year so far, [après Tufte](https://www.edwardtufte.com/notebook/new-york-city-weather-chart/): each day's high and low against the average and the extremes of the last ten years, and each month's precipitation as a running total against its average. The chart highlights where the temperature went above or below the average, and `c` switches it to the temperature colors from the main weather view or to plain.
  - The forecast in words says when snow changes to rain, when rain or snow changes to freezing rain, and when freezing rain changes back, without calling an hour's flip between rain and snow a change. After snow changes to rain, the snow total is given for when the snow stops.
  - The forecast in words says what is falling now before what it turns into, and no longer leaves out heavy drizzle turning to rain: "Heavy drizzle now, becoming rain soon, ending around 11:00."
  - Where the current conditions come from a nearby weather station, the forecast in words takes what is falling now from the same report, so it agrees with the header.
  - In the US, where a nearby airport station measures precipitation, the forecast in words gives what its rain gauge caught in the last 24 hours in place of the model's estimate.
  - Where there is room, the daily forecast gives each day's date and names its weather beside the icon, and "Today" is spelled out.
  - The daily forecast gives a snowy day's snowfall rather than the water it melts to: "Snow 3.5″", not "Snow 0.50″".
  - In Canada, the humidex and the wind chill take the place of the feels-like temperature, in English and French, as Environment Canada reports them.
  - The credit line is shorter, and says when and where the current conditions were observed: "Observed at 7:51a from Portland Intl Jetport, 4 mi away." The help panel keeps the full credits.
  - An alert already in effect gives only its end time.
  - Conditions are named in sentence case in English and Indonesian: "Light showers", not "Light Showers".
  - `--json` adds `narrative`, the paragraph under the graph as the view reads it, and marks a forecast from an earlier day as `stale`. Each hour now carries humidity, dew point, gusts and snowfall.
- Language:
  - French sets the percent sign off with a space ("40 %"), names the Moon's phases in sentence case, and uses the standard term for snow grains, "neige en grains".
  - Canadian French calls the mouse wheel a "roulette", gives the chance of rain as a "probabilité", and names the Blackfoot sky culture "Pieds-Noirs". French for France keeps "Blackfoot", because there "pieds-noirs" means the European settlers of colonial Algeria and their descendants.
  - The maps give route distances in the language's own units in Persian, Russian, Ukrainian, and Thai: "۲۴۰ متر", not "۲۴۰ m".
  - The translations are now in one file per language, with notes on what each string is for, so a translation is easier to correct or add. CONTRIBUTING.md explains how.
- Install: For machines without a package manager, each release on GitHub has all of linecast in one file, `linecast.pyz`. It runs with Python 3.10 or newer and says when a newer release is out. Suggested by [@sobjey9](https://github.com/sobjey9) in [#89](https://github.com/ashuttl/linecast/issues/89).

Fixes:

- Weather: Fixed a unit-conversion bug that showed snow amounts in imperial units at about two-fifths of the real amount, both in the forecast and in the last 24 hours, and could leave light snow out of the forecast entirely.
- Weather: Fixed the word order of an alert's end time in Japanese, Korean, Finnish, and Turkish: "日 20:00まで", not "まで 日 20:00", and "Paz 20:00'ye kadar", with the dative ending that the time takes when it's read aloud.
- Weather: Fixed a bug that could drop the label from the week's lowest temperature in the daily forecast at some window widths.
- Tides, moon, maps, sky: Fixed a bug that showed tide and wave heights, the Moon's age and countdowns, route distances, and star magnitudes with a decimal point in languages that write a decimal comma, such as "9.8′" for "9,8′" in Czech.

## 2.8.0 — 2026-09-25

linecast speaks Persian, its first right-to-left language, as an experiment. It also speaks Hong Kong Chinese, and has regional forms of Portuguese, Spanish, and French. The maps curve into the globe as you zoom out and glide as you move them. The forecast in words says more, and reads more naturally.

New this version:

- Language:
  - **Experimental:** Persian (`fa`). Weather, tides, sunshine, and the Moon read from the right, dates are in the Solar Hijri calendar, and numbers are in Persian digits. It works in Ghostty, Alacritty, and foot, but not well in the Mac's Terminal or iTerm2, and a native reader has not checked it yet. [docs/languages.md](https://github.com/ashuttl/linecast/blob/main/docs/languages.md) has the details.
  - In Persian, the Moon counts down to Nowruz and the year's festivals, and sunshine lists the times Iranian prayer timetables print.
  - Hong Kong Chinese (`zh-HK`), with the Hong Kong Observatory's words for the weather.
  - Regional variants for Portugal, Spain, and Canada: `pt-PT`, `es-ES`, and `fr-CA`. Spanish is now Latin American throughout.
  - Keys work with a non-Latin keyboard layout switched on, such as Persian, Russian, Greek, Hebrew, or Korean.
- Weather:
  - The forecast in words says more about what is coming and what is unusual, and should read more naturally in every language. If it reads oddly in yours, please open an [issue](https://github.com/ashuttl/linecast/issues).
  - Current conditions come from the nearest airport's report when one is close and recent.
  - Cloud cover is described on the National Weather Service's five-step scale, or the local weather service's terms.
  - In Canada, air quality is on Environment Canada's AQHI scale.
  - Wind is in metres per second in the languages whose forecasts give it that way.
  - In Japan and Ireland, only the warnings for your own area are shown.
  - When the alert service can't be reached, a line says so.
- Maps:
  - The street and terrain maps curve into the globe as you zoom out, and city names stay the same all the way.
  - The view moves smoothly: zooms ease, drags coast, and `w a s d` pan.
  - Panning and turning the globe are faster, especially over ssh.
  - The previous street view stays on screen while the next loads. Contributed by [@N30Yang](https://github.com/N30Yang) in [#117](https://github.com/ashuttl/linecast/pull/117).
  - City lights on the night side, from NASA's Black Marble.
  - Where a place has no name in your language, a local name in your script comes before the Latin one.
- Radar: Press `A` to hide or show the US warning outlines.
- Tides: Click the station name or press `l` to change location, as in weather.
- Moon, sky, maps, radar: Circles look round in wide and narrow fonts alike.
- Help: `--help` fits the terminal and groups flags into sections.
- Docs: The README is shorter, with the details in `docs/`. Old GitHub links to the pages that moved there no longer work.

Fixes:

- Maps, weather, sky, radar: Names in Hebrew, Arabic, Persian, and Urdu read right to left, with Arabic letters joined, instead of backwards.
- Weather: An alert's times are when its weather begins and ends, not when the bulletin was issued.
- Weather: Warnings are matched more precisely in MeteoAlarm countries, near Japan's prefecture borders, and in Croatia.
- Weather: The 24-hour rain total no longer counts an extra hour.
- Sky, moon: The stars line up with the Moon and planets. They had been about a third of a degree off.
- Moon: Equinox and solstice times are no longer a minute late.
- Maps: Zooming the globe no longer flashes a blank disk.
- Tides: A free TideCheck key stays within its fifty requests a day.
- Radar: The NEXRAD cache no longer grows without limit.
- Install: The curl quick-start accepts `sky`.
- Security: A TideCheck key is never sent to another server, text from a service can't send control sequences to the terminal, and a malformed map tile can't use excess memory.

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
