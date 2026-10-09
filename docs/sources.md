# Where the numbers come from

linecast draws on many providers, and where a country has its own scale or its own published figure, linecast prefers that to a global model. This page lists them by view: what is fetched, what is bundled, the formulas behind what linecast computes itself, and what each computation was checked against. Licenses and required credits are given with each entry.

Every request goes out with a User-Agent that names linecast and its version. Nothing here needs a key except TideCheck, which is optional; [configuration.md](configuration.md#the-tidecheck-key) says where the key goes.

## Location

A saved location was resolved to coordinates when it was saved, so reading it back never touches the network.

Fetched:

- **[ipinfo.io](https://ipinfo.io/)**, then **[ipwho.is](https://ipwho.is/)**, then **[GeoJS](https://www.geojs.io/)**. Where the machine is, from its address, when no location is saved or given. Only the coordinates and the country are taken. The accuracy is that of the service's database: usually the city, and sometimes the wrong one, which is why the README suggests saving a location.
- **[Open-Meteo geocoding API](https://open-meteo.com/en/docs/geocoding-api)**. A place name to coordinates, asked in the display language. The first result is taken, and `linecast location search` lists the rest. Open-Meteo also gives the time zone.
- **[Photon](https://photon.komoot.io/)**, on OpenStreetMap's data. Stands in when Open-Meteo's geocoder does not answer. It names places in English, German, and French only.
- **[Nominatim](https://nominatim.org/)**. Coordinates to a name, held to one request a second as its policy asks. Its country for the point decides the alert feed, the air quality scale, the tide service, the prayer convention, and the Hebrew calendar's diaspora days.

Checked against: nothing outside the services themselves; a location is what they say it is. A scheduled test suite asks each of them live.

## Weather

Fetched:

- **[Open-Meteo forecast API](https://open-meteo.com/en/docs)**. The forecast: the current conditions, seven days ahead and one behind by the hour, and each day's highs, lows, precipitation, snowfall, wind, sunrise, and sunset. Open-Meteo blends the national and global models and picks the best for the place; linecast names no model. The numbers are shown as sent, the felt temperature included. When the service cannot be reached, the last forecast fetched is shown with a line naming the day it was made, and `--json` sets `stale`.
- **[Open-Meteo historical weather API](https://open-meteo.com/en/docs/historical-weather-api)**. The last ten complete calendar years, for the line on how today compares with a normal day, the typical-year scale, and the month and year views. A normal day is the mean of that calendar day across the ten years. The archive is a reanalysis grid, and which reanalysis answers is Open-Meteo's choice. It is milder at the extremes than a thermometer at the airport, so these are not a station's readings, official normals, or records, and the year view names its bands by their years. [weather-month.md](weather-month.md) describes the month view's comparison.
- **[Aviation Weather Center](https://aviationweather.gov/data/api/)**. Airports' METAR reports. Where an airport within 25 km has reported in the last 90 minutes, its present weather and cloud take the place of the model's in the header, and the credit line names the station. An automated station sees cloud only to about 12,000 ft, so the model's high cloud still counts above a clear report from one. At a US automated station the prose gives what the rain gauge caught in the last 24 hours in place of the model's hours. Checked against the Portland Jetport's reports for 26 and 27 September 2026, whose hourly amounts add up to its six-hour total of 0.48″.

Computed from:

- **Environment Canada, [climate glossary](https://climate.weather.gc.ca/glossary_e.html)**. The humidex and wind chill formulas. In Canada, for a reader on Celsius in English or French, they take the felt temperature's place, as Environment Canada reports them, computed from Open-Meteo's temperature, dew point, and wind. The tests hold them to Wikipedia's worked examples: [the humidex](https://en.wikipedia.org/wiki/Humidex) at 30 °C with a dew point of 15 °C is 34, and [the wind chill](https://en.wikipedia.org/wiki/Wind_chill) at −20 °C in a 5 km/h wind is −24.
- **Australian Bureau of Meteorology, apparent temperature formula**. Inverted for the sentence that says whether humidity, wind, or the sun is behind the felt temperature. Its two terms were checked against Open-Meteo's values hour by hour and match to within a few tenths overnight.
- **Tufte, E., [New York City weather chart](https://www.edwardtufte.com/notebook/new-york-city-weather-chart/)**. The model for the year view.

Checked against: nothing outside Open-Meteo; the forecast and the archive are its numbers.

## Air quality

Fetched:

- **[Open-Meteo air quality API](https://open-meteo.com/en/docs/air-quality-api)**. Pollutant concentrations from the Copernicus CAMS global model at about 40 km, and CAMS Europe at 10 km over Europe, with the US EPA AQI the header shows by default. The source is a model, not a monitor: a number can differ from the one on a local station's page, and a plume over one town can be missed.
- **Environment Canada, [GeoMet API](https://api.weather.gc.ca/)**. In Canada the header shows the Air Quality Health Index, and the number is Environment Canada's own wherever it has one: the hourly observation from a community within 75 km, of about 120 that report, else the hourly forecast, which covers some 200. Quebec runs its own index and reports no observations here. `--json` says which the number came from.

Computed from:

- **Health Canada's AQHI formula**, as [summarized on Wikipedia](https://en.wikipedia.org/wiki/Air_Quality_Health_Index_(Canada)), with the AQHI-Plus rule from the [Fraser Basin Council's 2018 report](https://www.fraserbasin.bc.ca/_Library/TR_KAQR/aqhi-aqhi_plus_june_25_2018.pdf) and [British Columbia's AQHI page](https://www2.gov.bc.ca/gov/content/environment/air-land-water/air/air-quality/aqhi). The index beyond the reach of Environment Canada's communities, from Open-Meteo's pollutants. On 20 September 2026, a day of clean air, the computed index was compared with the reported one at 70 stations for the same hour. It matched at 36 and was within one point at 59, running about half a point high on average, with the model's ozone the main cause, and it missed a local smoke reading at Prince George, reported at 4 against a computed 1.6. That gap is why the reported value comes first.
- **CPCB National AQI (2014)**. In India the header shows this index in place of the US number, computed from the pollutants by the CPCB's averaging windows and breakpoints, with the categories its bulletins print.

## Alerts

The country of the place shown decides the feed. Ten countries have a feed of their own and thirty-five read MeteoAlarm; each has one feed, with no second behind it. A country with no feed shows no alerts. Iran is one, since its meteorological organization (IRIMO) publishes no warning feed that linecast has found. When a feed cannot be reached, the last copy fetched stands in with a line saying when it is from, and with no copy the view says the alerts could not be checked; `--json` reports this as `alerts_status`. linecast does not translate the text of an alert.

Fetched:

- **United States**. The [National Weather Service's](https://www.weather.gov/documentation/services-web-api) alerts for the point, in English. Only alerts whose status is Actual are shown, since the feed carries test messages.
- **Canada**. [Environment Canada's](https://api.weather.gc.ca/) alerts within about 50 km of the point, in English or French.
- **Germany**. The DWD's warnings for the point through [Bright Sky](https://brightsky.dev/), in German or English.
- **Norway**. [MET Norway's](https://api.met.no/weatherapi/metalerts/2.0/documentation) alerts for the point.
- **Ireland**. [Met Éireann's](https://www.met.ie/) warnings, shown in the counties each one lists. Marine and environmental warnings list no counties and are shown everywhere.
- **Japan**. The [JMA's](https://www.jma.go.jp/bosai/warning/) warnings from the nearest of its forecast offices in the prefecture, down to the municipality where the address names one. The event names are linecast's own table, in Japanese or English, with the JMA's headline as issued.
- **Hong Kong**. The [Observatory's](https://www.hko.gov.hk/en/wxinfo/dailywx/warnsum.htm) warning summary for the territory, in English, simplified Chinese, or traditional Chinese.
- **China**. The [CMA's](http://www.nmc.cn/) alarm list for the country, matched to the province. A Chinese reader gets the title as issued; otherwise an English name is put together from the type and the color.
- **India**. [SACHET](https://sachet.ndma.gov.in/), the national aggregator. An alert is kept when the point is within its area plus 25 km, and is shown in the display language where the issuer wrote one, else in English.
- **New Zealand**. [MetService's](https://alerts.metservice.com/) CAP feed (CC BY 4.0), placed by each alert's polygon.
- **MeteoAlarm**, the [country's feed](https://feeds.meteoalarm.org/), for Austria, Belgium, Bosnia and Herzegovina, Bulgaria, Croatia, Cyprus, Czechia, Denmark, Estonia, Finland, France, Greece, Hungary, Iceland, Israel, Italy, Latvia, Lithuania, Luxembourg, Malta, Moldova, Montenegro, the Netherlands, North Macedonia, Poland, Portugal, Romania, Serbia, Slovakia, Slovenia, Spain, Sweden, Switzerland, Ukraine, and the United Kingdom. Minor warnings are dropped. A warning is placed by its polygon, else by the region codes it carries, else by reading its area's description against the address; an Extreme warning is shown regardless. Switzerland, Estonia, the United Kingdom, Israel, Luxembourg, Sweden, and Ukraine have no bundled regions and rely on the polygons and the text. Germany, Norway, and Ireland are on MeteoAlarm too, but their own feeds say more.

Bundled, for placing MeteoAlarm's warnings:

- **MeteoAlarm's geocodes** of 31 July 2026 (© EUMETNET, CC BY 4.0). The warning regions.
- **[Eurostat GISCO](https://ec.europa.eu/eurostat/web/gisco)**, the 2013 NUTS boundaries, and 2021's for Croatia (© EuroGeographics for the administrative boundaries). The regions some feeds file by.
- **[ČÚZK RÚIAN](https://www.cuzk.gov.cz/)**, with the [Czech Statistical Office's](https://csu.gov.cz/) code list, both open data. Czechia's 206 ORP.

Checked against: real responses from every feed, saved as fixtures, and the bundled regions by looking up twelve places and a point in the Atlantic. No placed alert has been compared with a dated real one beyond these.

## Sunshine and the Moon

Everything here is computed on the device. Sunrise and sunset are the Sun's upper limb, refracted, at 0.833° below the horizon, and the twilights are the usual 6°, 12°, and 18°. The traditional hours and the calendars have their own pages, [hours.md](hours.md) and [calendars.md](calendars.md).

Computed from:

- **NOAA Solar Calculator**, the [simplified equations](https://gml.noaa.gov/grad/solcalc/solareqns.PDF), with Spencer's three-term equation of time. The `sunshine` day and year views, good to about a minute for sunrise and sunset and a third of a degree for the Sun's elevation.
- **Paul Schlyter's [low-precision ephemeris](https://stjarnhimlen.se/comp/ppcomp.html)**, itself a simplification of Meeus. The Moon, the sky, the traditional hours, and the calendars: the Sun to about a hundredth of a degree, the Moon to a couple of arcminutes, and the Moon's distance within a percent. There is no nutation, no aberration, no ΔT, and no observer height.
- **Meeus, J., *Astronomical Algorithms* (2nd ed.)**. The equinoxes and solstices (chapter 27), valid from 1000 to 3000 and good to a minute or so, with ΔT taken off so the instants are UTC, and the bright limb's angle on the Moon's disc (equation 48.5).
- **The Old Farmer's Almanac**. The full moons' names: the Harvest Moon nearest the September equinox, the Hunter's Moon after it, and a Blue Moon the second in a month.

Bundled:

- **NASA SVS, [CGI Moon Kit](https://svs.gsfc.nasa.gov/4720)** (Lunar Reconnaissance Orbiter, public domain). The Moon's face, reduced to a 512 by 256 grayscale. It is drawn from the mean sub-Earth point, so the libration of the month does not show.
- **[Yale Bright Star Catalogue](http://tdc-www.harvard.edu/catalogs/bsc5.html)** (Hoffleit & Warren, 1991). The stars behind the Moon, to magnitude 6.5. They are the real ones for the moment, each in its true direction, but the field is not to scale.
- **[Western Pacific Regional Fishery Management Council](https://www.wpcouncil.org/educational-resources/lunar-calendars/)**. The Pacific calendars are checked against its published calendars and quote its educational materials.

Checked against:

- **Published instants.** The eight principal phases of January to April 2026, within a quarter of an hour; the equinoxes and solstices of 2000 and 2024, within a quarter of an hour of the almanac; and the full-moon names of 2020, 2023, and 2026.
- **PyEphem's ELP2000.** The Moon's position at four moments of 2026, within a tenth of a degree, and its bright limb's bearing at four places, within 3°.
- **Hebcal.** The ephemeris's sunrise and sunset, within half a minute at four places on four dates of 2026 ([hours.md](hours.md)).
- The sunshine view's own rise and set, by the NOAA equations, are not in the tests. On 20 September 2026 they were compared with the ephemeris's at six places on the same four dates and agreed within two minutes, most within one.
- Moonrise and moonset are checked for shape, not against a table.

## The sky

The sky view uses the network for the location and its name and for nothing else. The stars, the figures, the names, the Milky Way, and the deep-sky objects are bundled; the Sun, the Moon, and the planets are computed. [STARS.md](../src/linecast/data/STARS.md) says where each data file is from and how it was built, and [cultures.md](cultures.md) credits the twenty-two other skies.

Bundled:

- **[Yale Bright Star Catalogue](http://tdc-www.harvard.edu/catalogs/bsc5.html)** (Hoffleit & Warren, 1991). The 8,404 stars to magnitude 6.5.
- **[HYG v4.1](https://github.com/astronexus/HYG-Database)** (David Nash, CC BY-SA 4.0). The 108,520 fainter stars, to magnitude 12, revealed as you zoom in.
- **[d3-celestial](https://github.com/ofrohn/d3-celestial)** (Olaf Frohn, BSD). The 107 Messier objects, the constellation figures, the IAU star names, and the star and constellation names in French, Spanish, German, Italian, Finnish, Japanese, Korean, and Chinese.
- **[Wikidata](https://www.wikidata.org/)** (CC0). The names in the other languages, a label kept only when it is a proper name and not a designation, with overrides reviewed against each language's Wikipedia. Hungarian constellations follow the Hungarian Astronomical Association's Meteor yearbook.
- **NASA SVS, [Deep Star Maps 2020](https://svs.gsfc.nasa.gov/4851)** (public domain). The Milky Way: the diffuse layer, the unresolved starlight from Gaia.
- **[Stellarium's sky cultures](https://github.com/Stellarium/stellarium-skycultures)**, placed from the Hipparcos catalogue. The other skies; [cultures.md](cultures.md) has the credits.

Computed from:

- **Paul Schlyter's elements and perturbations.** The planets from Mercury to Neptune, good to a couple of arcminutes for the inner planets and Jupiter and a few for Saturn and beyond, and their magnitudes. There is no light-time correction.
- **Meeus, *Astronomical Algorithms*.** The IAU 1976 precession that turns the catalogue's J2000 positions to the equinox of the date (chapter 21), and mean sidereal time (equation 12.4). The stars are not moved by proper motion or corrected for refraction or aberration.
- Two tables are linecast's own, with no source: the limiting magnitude by the Sun's altitude, which decides when a star comes out, and the fifteen asterisms the search offers.

Checked against:

- **PyEphem.** The precession of Sirius and Polaris to 2026, and of Meeus's worked example, θ Persei to 2028, within a hundredth of an arcsecond.
- **Published values.** Mars, Saturn, Uranus, and Neptune at their 2025 oppositions and Venus at its 2025 elongation, within a few arcminutes and a few tenths of a magnitude.
- Sidereal time and the stars' altitudes are checked for geometry, the pole at the latitude and the meridian due south, not against an almanac.

## Tides

The station is chosen by the country of the place shown: the country's own service first, then the bundled TICON-4 gauges, then NOAA, then TideCheck if a key is set, then Open-Meteo's model everywhere. In the United States and its territories NOAA goes before the gauges. The first with a station within 100 nautical miles wins, or 30 for the gauges, and the footer names it. Nothing is converted between datums; each provider's is passed through, except as the entries below say.

Fetched:

- **[NOAA CO-OPS](https://tidesandcurrents.noaa.gov/)**. Six-minute predictions above MLLW, with NOAA's own highs and lows. Subordinate stations publish highs and lows alone; they are reached by name, with a curve drawn between the extremes. The year view's measured water is the gauge's verified highs and lows, and its preliminary six-minute levels for the weeks since. The flood line is the National Weather Service's minor flood level for the station, or NOS's where the Weather Service has set none.
- **[Canadian Hydrographic Service](https://www.tides.gc.ca/)**, the IWLS API. Five-minute predictions and the turning points, on chart datum. The year view's measured water is the gauge's official water level, at fifteen-minute intervals. CHS publishes no flood stage, so a Canadian station's year has no flood line.
- **[Queensland open data](https://www.data.qld.gov.au/)**. Ten-minute heights above LAT. The datasets carry no coordinates, so linecast bundles 69 gauges' positions; ten beacon and reef gauges have none and are reached by name.
- **[Hong Kong Observatory](https://www.hko.gov.hk/en/tide/)**. Thirteen stations: hourly heights above chart datum and the day's highs and lows.
- **[Japan Meteorological Agency](https://www.data.jma.go.jp/kaiyou/db/tide/suisan/index.php)** (Public Data License 1.0; converted and redrawn by linecast). The 239 stations of its tide tables: hourly heights above each station's tide-table datum and the day's highs and lows, from 2011 to next year. At about seventy of them JMA runs the gauge itself, and the year view draws what it measured, moved onto the table's datum with JMA's hourly deviation files. JMA publishes no flood level for its tide stations.
- **[Kartverket](https://www.kartverket.no/en/at-sea/se-havniva)**, the Norwegian Mapping Authority's [water level API](https://vannstand.kartverket.no/tideapi_en.html) (CC BY 4.0). The tide predicted for any point on the coast of Norway, Svalbard, and Jan Mayen, above chart datum, so there is no station to pick. The year view draws measured water only where a gauge within 5 nautical miles has the very predictions Kartverket gives for the place, as at Bergen, Oslo, and Tromsø, and not at Kristiansand or Longyearbyen. Kartverket publishes no flooding threshold.
- **[TideCheck](https://tidecheck.com/)**, with a key. The nearest station within 185 km and its highs and lows for the next 30 days above MLLW, with a curve drawn between them. linecast counts its requests against the free tier's fifty a day and stops asking at fifty; `LINECAST_TIDECHECK_PAID` lifts the cap.
- **[Open-Meteo marine weather API](https://open-meteo.com/en/docs/marine-weather-api)**. Sea level above mean sea level from a model, at the nearest sea cell; the place itself is the station. linecast fits 33 constituents to last year's hourly heights and predicts from them. The year view draws the model's own heights, tide and weather together, marked as modeled rather than measured. The wave heights and periods beside the chart are from here too, whichever provider the tide is from.

Bundled:

- **TICON-4.** Hart-Davis, M., Dettmering, D., Seitz, F. (2025), *TICON-4: TIdal CONstants based on GESLA-4 sea-level records*, SEANOE, [doi:10.17882/109129](https://doi.org/10.17882/109129) (CC BY 4.0), by way of the [Slackwater database](https://github.com/openwatersio/slackwater-database), which names each gauge, finds its time zone, derives its datums, and re-fits some gauges. The harmonic constants of 1,215 tide gauges in 103 countries outside the United States and Canada, with the constituents trimmed and rounded. linecast keeps the stations whose license allows commercial use, which leaves out the gauges GESLA relayed from Copernicus Marine, and with them most of Norway's, Denmark's, and the Mediterranean's. The predictions are computed on the device from 43 constituents, above the chart datum Slackwater derives.

Computed from:

- **Schureman, P. (1958). *Manual of Harmonic Analysis and Prediction of Tides*.** U.S. Coast and Geodetic Survey Special Publication No. 98. [PDF from NOAA](https://tidesandcurrents.noaa.gov/publications/SpecialPubNo98.pdf). The astronomical arguments and the nodal corrections in linecast's harmonic code, taken at the middle of each year, as NOAA takes them.

Checked against:

- **NOAA's 2026 hourly predictions.** Fed NOAA's own published constants, the harmonic code reproduces them to 1 mm at Portland, Maine, Boston, Pensacola, and Honolulu, 3 mm at San Francisco, and 6 mm at Seattle, with the highs and lows within a minute or two. At Anchorage, where NOAA's prediction takes 120 constituents, many of them shallow-water terms the code does not have, it is 19 cm off.
- **The agencies' tables, for TICON-4's constants.** Andenes's and Ny-Ålesund's 2026 highs and lows are within a minute of Kartverket's for half of them and four minutes for nine in ten, and within 2 cm; Tokyo's hourly heights are within 2.7 cm of JMA's; and Portland's turns are within 2 minutes and 3 cm of NOAA's. The chart datums agree with the agencies' to 2 cm in Norway and 3.5 cm at Tokyo.
- **NOAA's tables, for Open-Meteo's fit.** At Portland its turns are 28 minutes early and its range 5% short, which is the model's cell out in Casco Bay; at Pensacola, inside its bay, they are two and a half hours early. What the fit leaves over, the weather, tracks the gauge's departures from the tables with a daily correlation of 0.95 at Portland, 0.87 at Pensacola, and 0.81 at San Francisco, though at Pensacola it reached only half the biggest surges.
- **JMA's own table pages**, for 1 October 2026. Tokyo's and Yokohama's highs and lows, to the minute and the centimeter. The datum tie held at a single value at every hour of each month checked, at Tokyo and four other stations, and in 2026 each value was within a centimeter of the offset JMA's station lists give.
- **Kartverket's printed tide table for 2026.** Bergen on 1 October (02:22 162 cm, 08:14 43, 14:50 155, 20:36 50) and on 25 October, the day the clocks go back. Bergen's measured daily lows and highs from January 2025 to August 2026 agree with Kartverket's own monthly statistics to within a millimeter.
- **Queensland's monitoring feed.** The gauge datasets matched its prediction column to within a centimeter on an overlapping day.
- No synthesized curve has been compared with a provider's own.

## Radar

Fetched:

- **[LibreWXR](https://librewxr.net/)**. Asked first everywhere: about two hours of past frames and an hour of nowcast. It composites real radar where it is published openly and fills the rest of the world with a precipitation model, and its index does not say which is which. linecast carries seven boxes drawn from LibreWXR's source list (the United States and Canada, Europe, Japan, Taiwan, Malaysia with Singapore and Brunei, the Philippines, and El Salvador), and the footer says "no radar here" outside them. The satellite layer is its hourly infrared cloud mosaic (CC BY 4.0), at about 8 km, reaching the 72nd parallels.
- **[Iowa Environmental Mesonet](https://mesonet.agron.iastate.edu/)**. NEXRAD's n0q base reflectivity composite, the fallback in the lower 48 states: five minutes a frame for the last three hours, with no forecast. Also the National Weather Service's storm-based warning polygons, drawn on past frames and only over the United States.
- **[RainViewer](https://www.rainviewer.com/)**. The fallback elsewhere. Its free tier publishes at zoom 7 in its Universal Blue colors, which linecast reads back to dBZ through a copy of RainViewer's published table.
- **Open-Meteo forecast API.** The temperature and wind layers, on a lattice of sixty points over the view, interpolated between them.

Bundled:

- **Natural Earth.** The basemap: land and lakes at 1:10m, borders at 1:50m, and populated places above 40,000 or a capital, with their names in each language Natural Earth has, simplified to about a kilometer.

The `dusk` palette was measured from LibreWXR's dark-sky tiles, and `marangai` follows MetService New Zealand's radar, matched by eye.

Checked against: RainViewer's published color for 20 dBZ. The tests run on hand-built indexes and synthetic tiles, and no decoded value has been compared with a radar product outside the app.

## Maps

Fetched:

- **[AWS Open Data Terrain Tiles](https://registry.opendata.aws/terrain-tiles/)**, in Mapzen's terrarium encoding. The terrain: SRTM, GMTED, and the national models the tiles composite, to zoom 13, where SRTM's 30 m grid runs out, and ETOPO1 for the sea floor, to zoom 10. No keyless mirror of them exists, so there is no second source; `LINECAST_ELEVATION_URL` names another. The globe is a whole-world mosaic of the same tiles, bundled.
- **[OpenFreeMap](https://openfreemap.org/)** vector tiles, in the OpenMapTiles schema (© OpenMapTiles © OpenStreetMap contributors). Streets, water, parks, land cover, buildings, and names. A name is the tile's own for the display language, then for its base language, then the Latin transliteration, then the local name; linecast translates nothing. The **[OpenStreetMap US Tileservice](https://tiles.openstreetmap.us/)** (Tiles by OSM US) stands in when OpenFreeMap does not answer. `LINECAST_VECTOR_TILES_URL` names another, with no fallback.
- **[Global Human Settlement Layer](https://human-settlement.emergency.copernicus.eu/)**, the built-up surface for 2020 (GHSL © European Commission JRC, CC BY 4.0). Built-up ground, tiled and served by linecast from its own bucket. An empty `LINECAST_BUILTUP_URL` turns it off.
- **[LibreWXR](https://librewxr.net/)**, the infrared mosaic (CC BY 4.0). The globe's clouds, an hour or two behind the clock, reaching the 72nd parallels. Poleward of that nothing sees, and the cap is filled with noise matched to the mosaic's last ring, not with observed cloud.
- **[Photon](https://photon.komoot.io/)** and **[Nominatim](https://nominatim.org/)**. Search: Photon while you type, in English, German, or French, and Nominatim when you press Enter and Photon found nothing.
- **[OSRM](http://project-osrm.org/)** at **[FOSSGIS](https://routing.openstreetmap.de/)** (© OpenStreetMap contributors). Directions for car, bicycle, and foot, with OSRM's own demo server standing in for the car alone. OSRM sends no instruction text and linecast writes none: a step is the road name, the distance, and a glyph for the maneuver.

Bundled:

- **[Köppen-Geiger grid](https://doi.org/10.6084/m9.figshare.21789074)**, Beck et al. (2023), for 1991 to 2020 at a tenth of a degree (CC BY 4.0). Picks the terrain's color ramp: humid, semi-arid, arid, or polar.
- **NASA [Black Marble 2016](https://science.nasa.gov/earth/earth-observatory/earth-at-night/maps/)** (Suomi NPP VIIRS). The globe's night lights. It is a historical composite, not live lighting and not a map of outages; [NIGHT_LIGHTS.md](../src/linecast/data/NIGHT_LIGHTS.md) has the credits and the format.
- **Natural Earth.** The borders, from the radar's basemap.

Checked against: the terrarium decoding round-trips Everest's 8,848 m, sea level, and a depth, and the globe's subsolar point is checked at the equinoxes and solstices. No fetched elevation, tile, or route is compared with a reference outside the app.
