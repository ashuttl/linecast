# Gallery

The README shows each app once or twice. This page shows them in more of their states: other languages, other traditions, other layers, smaller windows. Every frame is linecast's own output, captured by `scripts/capture_screenshots.sh`, which runs each app in a pseudo-terminal and draws what it writes the way foot would; the ones that depend on the weather or the hour are whatever the weather and the hour were.

## Desktops

The apps side by side, tiled on an Omarchy desktop: the weather in Westbrook, Maine, over its year; the radar over Portland; the Moon in Japanese; and a year of daylight in Reykjavík, in Icelandic.

![linecast tiled on an Omarchy desktop](../screenshots/hero.png)

A second desktop in other languages and traditions: Montréal's weather in Canadian French, October in Reykjavík by the Icelandic calendar with the pointer on the first day of winter, the Moon over Hilo by the Hawaiian calendar and over Okinawa in Japanese, and the January sky with Hawaiian star names and the star compass along the horizon.

![a second desktop, in Canadian French, Icelandic, Hawaiian, and Japanese](../screenshots/languages.png)

The first desktop again, through ten Omarchy themes. Each app redraws itself in the new colours as the theme changes.

![the same desktop through ten Omarchy themes](../screenshots/themes.gif)

## In motion

Two recordings driven by the mouse: the globe tipped up to Antarctica and rolled round to Africa, and the January sky lifted to the zenith and brought back down to the southwest.

<p>
  <img src="../screenshots/gallery/globe-spin.gif" width="49%" alt="the globe spun by dragging">
  <img src="../screenshots/gallery/sky-pan.gif" width="49%" alt="the sky panned by dragging">
</p>

## Weather

<p>
  <img src="../screenshots/weather.png" width="66%" alt="the weather in Dublin">
  <img src="../screenshots/gallery/weather-short.png" width="33%" alt="the same dashboard in a short window, with the rows that give way gone">
</p>

The dashboard gives up rows as the window shrinks: the cloud strip first, then the spacing, until only the chart and the days are left.

Hovering over a day's bar draws that day's hours.

<img src="../screenshots/gallery/weather-day.png" width="66%" alt="the dashboard for Dublin with the pointer on a day's temperature bar and the chip that graphs that day's hours">

<p>
  <img src="../screenshots/weather-reykjavik.png" width="49%" alt="the weather in Reykjavík, in Icelandic">
  <img src="../screenshots/weather-kyoto.png" width="49%" alt="the weather in Kyoto, in Japanese">
</p>

Press `v` to cycle forecast, month, and year. The month has a row for each day and the hours across it, with sunrise and sunset as dotted lines; arrows browse months. This is September 2026 in Westbrook, Maine: first the hourly temperatures, and then, after `c`, each hour's departure from its ten-year average, blue where it was cooler and red where it was warmer. The pointer is on the afternoon of the 10th, the warmest of the month: 82°F at an hour that averages 72°F. [The month view](weather-month.md) explains how to read it.

<p>
  <img src="../screenshots/gallery/weather-month.png" width="49%" alt="the hourly temperatures of September 2026 in Westbrook, Maine, a row for each day">
  <img src="../screenshots/gallery/weather-month-departure.png" width="49%" alt="the same month as departures from the 2016–2025 hourly average, with the chip for the afternoon of September 10">
</p>

Press `v` again for the year so far, [après Tufte](https://www.edwardtufte.com/notebook/new-york-city-weather-chart/). Each day's high and low is drawn against the last ten years' average and extremes, tinted warm or cool where it went past the average, and each month's precipitation is a running total against its average. The pointer here is on a week in May.

<img src="../screenshots/weather-year.png" alt="the weather year view for Westbrook, Maine, with the chip for a week in May">

## Sunshine

One June day over Westbrook, Maine: night, with the sun's dot below the horizon; dawn; midday; golden hour; dusk. Then a January noon, for what nine hours of daylight do to the arc.

<p>
  <img src="../screenshots/sunshine-night.png" width="32%" alt="sunshine at night">
  <img src="../screenshots/sunshine-dawn.png" width="32%" alt="sunshine at dawn">
  <img src="../screenshots/sunshine-day.png" width="32%" alt="sunshine at midday">
</p>
<p>
  <img src="../screenshots/sunshine-golden.png" width="32%" alt="sunshine in the golden hour">
  <img src="../screenshots/sunshine-dusk.png" width="32%" alt="sunshine at dusk">
  <img src="../screenshots/sunshine-winter.png" width="32%" alt="a January noon">
</p>

The year view for Reykjavík, in Icelandic, and for Longyearbyen and Vostok Station, 78° either side of the equator, each with the pointer on the December solstice.

<p>
  <img src="../screenshots/sunshine-year.png" width="32%" alt="the year view for Reykjavík">
  <img src="../screenshots/sunshine-year-arctic.png" width="32%" alt="the year view for Longyearbyen, Svalbard">
  <img src="../screenshots/sunshine-year-antarctic.png" width="32%" alt="the year view for Vostok Station, Antarctica">
</p>

## Moon

<p>
  <img src="../screenshots/moon.png" width="49%" alt="a waxing gibbous moon over Westbrook, Maine">
  <img src="../screenshots/gallery/moon-grid.png" width="49%" alt="the month grid for September 2026">
</p>

<p>
  <img src="../screenshots/moon-okinawa.png" width="49%" alt="the moon over Okinawa in Japanese: 十六夜, the sixteenth night of the eighth month">
  <img src="../screenshots/moon-calendar.png" width="49%" alt="the month calendar for September 2026 in Japanese, with 十五夜 on the 25th and the pointer on it">
</p>

The Moon alone, with the text put away by `t`, and the same Moon dragged round and let go:

<p>
  <img src="../screenshots/moon-alone.png" width="49%" alt="the waxing gibbous Moon alone among the stars">
  <img src="../screenshots/moon-spin.gif" width="49%" alt="the Moon dragged round by the pointer and let go, turning back">
</p>

## Sky

The same January evening over Westbrook, Maine, drawn six ways. The IAU figures first, then the Hawaiian sky with the navigators' star compass along the horizon, then the Chinese Three Enclosures and Twenty-Eight Mansions, the Norse sky, and H. A. Rey's stick figures.

<p>
  <img src="../screenshots/sky.png" width="49%" alt="Orion on a January evening, with Jupiter in Gemini">
  <img src="../screenshots/sky-hawaiian.png" width="49%" alt="the same sky in the Hawaiian tradition">
</p>

<p>
  <img src="../screenshots/gallery/sky-chinese.png" width="32%" alt="the same sky in the Chinese tradition">
  <img src="../screenshots/gallery/sky-norse.png" width="32%" alt="the same sky in the Norse tradition">
  <img src="../screenshots/gallery/sky-rey.png" width="32%" alt="the same sky with H. A. Rey's figures">
</p>

Zoomed all the way out while looking up, the horizon closes into a circle and the whole August sky is in the frame at once.

![the whole August sky at once, the Milky Way across it](../screenshots/sky-allsky.png)

The same view played forward with `p`, an hour a second, from an August afternoon into the night: the Sun and a half Moon cross and set, the sky turns pink and then dark, and the Milky Way comes out as the stars turn round the pole.

![the whole sky from an August afternoon into the night](../screenshots/sky-time.gif)

## Tides

The day's curve at Portland, Maine.

![the tide curve at Portland, Maine](../screenshots/tides.png)

Press `v` for the month and again for the year. The month has a row for each day, with the water drawn light where it is high, so Portland's two high waters a day are two slanting bands. The dotted lines are sunrise and sunset, and the times at the right are each day's lowest low water in daylight. The year draws each day's predicted range as a band and traces the gauge's highest and lowest measured water over it. The pointer is on the middle of June, where the water measured 12.4 feet and passed the flood stage.

<p>
  <img src="../screenshots/tides-month.png" width="49%" alt="October 2026 at Portland, Maine: the high water as two slanting bands a day, sunrise and sunset as dotted lines down the month, and each day's lowest low water in daylight at the right">
  <img src="../screenshots/tides-year.png" width="49%" alt="2026 at Portland, Maine: each day's predicted range as a band, the gauge's highest and lowest water traced over it, and the pointer on the middle of June">
</p>

The same October at Quarry Bay, Hong Kong, and at Tokyo. Neither draws Portland's picture: Hong Kong's broad bands break off around the 10th and the 24th, and Tokyo's two bands a day fade into one near the quarter moons. [About the tides](tides.md) explains why.

<p>
  <img src="../screenshots/tides-month-quarry-bay.png" width="49%" alt="the month view for Quarry Bay, Hong Kong in October 2026: broad bands that break off around the 10th and the 24th">
  <img src="../screenshots/tides-month-tokyo.png" width="49%" alt="the month view for Tokyo in October 2026: two bands a day that fade into one near the quarter moons">
</p>

Press `v` once more for what moves the tide: a table of the causes and the height of each, beside strips for the twice-a-day and once-a-day parts through the month, the year, and 2016 to 2034. Portland, where the Moon's part is more than six times the Sun's, and then Tokyo in Japanese, where it is only twice.

<p>
  <img src="../screenshots/tides-makeup.png" width="49%" alt="what moves the tide at Portland, Maine: a table of five causes and the height of each, beside strips for the twice-a-day and once-a-day parts through October 2026, the year 2026, and 2016 to 2034">
  <img src="../screenshots/tides-makeup-tokyo.png" width="49%" alt="what moves the tide at Tokyo, in Japanese">
</p>

## Radar

The radar wherever the most weather was when the gallery was refreshed, in the terminal's own colours, still and then running through its frames, and then in the four fixed themes: `dusk`, `ember`, `ink`, and `marangai`.

<p>
  <img src="../screenshots/radar.png" width="49%" alt="the radar in the terminal's own colours">
  <img src="../screenshots/radar.gif" width="49%" alt="the same radar, animated">
</p>

<p>
  <img src="../screenshots/gallery/radar-dusk.png" width="49%" alt="the radar in the dusk theme">
  <img src="../screenshots/gallery/radar-ember.png" width="49%" alt="the radar in the ember theme">
</p>
<p>
  <img src="../screenshots/gallery/radar-ink.png" width="49%" alt="the radar in the ink theme">
  <img src="../screenshots/gallery/radar-marangai.png" width="49%" alt="the radar in the marangai theme">
</p>

The satellite layer, an hourly cloud mosaic, and the condition layers, a temperature tint with wind arrows over it.

<p>
  <img src="../screenshots/gallery/radar-satellite.png" width="49%" alt="the satellite cloud layer">
  <img src="../screenshots/gallery/radar-layers.png" width="49%" alt="the radar with the temperature and wind layers">
</p>

## Maps

Portland, Maine, at five zooms. Each step out is a decision about what to leave off: shop names go first, then the small streets, then the neighbourhood names, until the state is highways and towns.

<p>
  <img src="../screenshots/maps-zoom-blocks.png" width="32%" alt="block level">
  <img src="../screenshots/maps-zoom-streets.png" width="32%" alt="the streets">
  <img src="../screenshots/maps-zoom-city.png" width="32%" alt="the city">
</p>
<p>
  <img src="../screenshots/maps-zoom-region.png" width="49%" alt="the region">
  <img src="../screenshots/maps-zoom-state.png" width="49%" alt="the state">
</p>

Terrain: New Zealand whole, then Cook Strait, then the Alps around Innsbruck.

![terrain map of New Zealand, with the seafloor around it](../screenshots/maps-terrain.png)

<p>
  <img src="../screenshots/gallery/maps-cook-strait.png" width="49%" alt="Cook Strait in terrain">
  <img src="../screenshots/gallery/maps-innsbruck.png" width="49%" alt="the Alps around Innsbruck in terrain">
</p>

A continent under the hour's clouds, at a zoom between the street map and the globe.

![a continent under this hour's clouds](../screenshots/gallery/maps-clouds-continent.png)

A walking route from Portland to South Portland, across the bridge.

![a walking route from Portland, Maine, to South Portland](../screenshots/gallery/maps-route.png)

The globe as it was when the gallery was refreshed, in daylight alone and with the hour's clouds.

<p>
  <img src="../screenshots/maps-globe.png" width="49%" alt="the globe with live daylight, the terminator, and city lights">
  <img src="../screenshots/maps-globe-clouds.png" width="49%" alt="the same globe with the hour's clouds">
</p>

The same two with the labels hidden by `l` and the text by `t`. The second is what `--view now` opens on, with the planet slowly turning.

<p>
  <img src="../screenshots/maps-globe-bare.png" width="49%" alt="the globe in daylight with no labels or text">
  <img src="../screenshots/maps-globe-clouds-bare.png" width="49%" alt="the globe under the hour's clouds with no labels or text, as --view now opens">
</p>
