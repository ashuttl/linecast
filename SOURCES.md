# Where the numbers come from

linecast draws on many providers, and where a country has its own scale or its own published figure, linecast prefers that to a global model. This page says, for each kind of data, which source is asked first, what stands in when it does not answer, what linecast computes itself, and what that computation was checked against. It is a start: the air quality is written up here, and the README's [data sources](README.md#data-sources-and-coverage) list still covers the rest in a line each.

## Air quality

The pollutant concentrations come from [Open-Meteo's air quality API](https://open-meteo.com/en/docs/air-quality-api), which serves the Copernicus CAMS global model at about 40 km, and CAMS Europe at 10 km over Europe. Open-Meteo also computes the US EPA AQI and the European index from them, and the header shows the US number by default, colored on its scale. The hourly series of PM2.5, PM10, nitrogen dioxide, sulphur dioxide, carbon monoxide, and ozone for the past day come with it, so that a country's own index can be computed on the device.

Because the source is a model, not a monitor, a number can differ from the one on a local station's page, and a plume over one town can be missed. Where a country publishes the index it reports, linecast reads that first.

### India

In India the header shows the CPCB's National AQI (2014) instead of the US number, with the category the CPCB's bulletins print: Good, Satisfactory, Moderate, Poor, Very Poor, Severe. It is computed from the pollutants: each is averaged over its window (24 hours for the particulates, nitrogen dioxide, and sulphur dioxide; 8 hours for ozone and carbon monoxide), mapped onto the shared 0 to 500 index through its own breakpoints, and the index is the worst sub-index. As the CPCB does, linecast reports no index without particulate data, and does not average a window more than half empty. The colors follow the CPCB's wider bands.

### Canada

In Canada the header shows the Air Quality Health Index, on Health Canada's scale of 1 to 10+ with its risk level: Low risk to 3, Moderate to 6, High to 10, and Very high past that. The label reads AQHI in English and CAS, cote air santé, in French, with the risk level in French for a French reader.

The number is Environment Canada's own wherever it has one, read from the [GeoMet API](https://api.weather.gc.ca/):

- The **observations** feed carries the hourly AQHI for about 120 communities, as each province reports it. A place within 75 km of a community with a reading from the last two hours takes that reading. Quebec runs its own index and reports no observations here.
- Otherwise the **forecasts** feed, which carries hourly forecasts for some 200 communities, Montréal among them; the latest issue's value for the hour nearest now stands in.
- Beyond the reach of either, the index is **computed** from the pollutants. Health Canada's formula takes the three-hour trailing means of nitrogen dioxide and ozone in parts per billion and PM2.5 in µg/m³, sums an exponential term for each, and scales the sum so that 10 sits at the top of the range studied; the result is rounded and never below 1. Open-Meteo states the gases in µg/m³, and they are converted at 25 °C and one atmosphere. British Columbia's AQHI-Plus (2018), since taken up by the other provinces, publishes the greater of that and the current hour's PM2.5 divided by ten and rounded up, so that a smoke plume the slow means would understate is reported at once; linecast applies it everywhere in Canada.

The JSON output says which of the three the number came from.

**Checked against:** on 20 September 2026, a day of clean air, the computed index was compared with Environment Canada's reported value at 70 stations across the country for the same hour. It matched the rounded figure at 36 stations and was within one point at 59, running about half a point high on average, with the model's ozone the main cause. It missed a local smoke reading at Prince George, reported at 4 against a computed 1.6. That gap is why the reported value comes first and the computation is the fallback. The formula, its constants, and the categories are Health Canada's as [summarized on Wikipedia](https://en.wikipedia.org/wiki/Air_Quality_Health_Index_(Canada)); the AQHI-Plus rule is from the [Fraser Basin Council's 2018 report](https://www.fraserbasin.bc.ca/_Library/TR_KAQR/aqhi-aqhi_plus_june_25_2018.pdf) and [British Columbia's AQHI page](https://www2.gov.bc.ca/gov/content/environment/air-land-water/air/air-quality/aqhi).

## Still to write up

Each of these has a line in the README's data sources list; the fuller account of what is asked first, what stands in, and what was checked is to come.

- Location: IP geolocation and its fallbacks; geocoding and reverse geocoding, and which language each answers in.
- Weather forecasts and the climate averages the comparison is drawn against.
- Alerts, by country: the feeds, the region matching, and the languages each publishes in.
- Sunshine and the moon: the equations, the moon's face, the calendars ([CALENDARS.md](CALENDARS.md)) and hours ([HOURS.md](HOURS.md)).
- The sky: the catalogues, the names in each language, the cultures ([CULTURES.md](CULTURES.md)), the planets, and the satellites.
- Tides: the national services and the global model behind them.
- Radar: the mosaics, the warning polygons, and the basemap.
- Maps: terrain, streets, search, directions, cloud cover, and the climate grid that colors the land.
