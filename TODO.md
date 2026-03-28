# TideCheck Integration — TODO

## API Endpoint Verification

The TideCheck API endpoints were inferred from web search results and common
tide API patterns.  The following need verification against the live API once
a key is obtained:

- [ ] `GET /api/stations/nearest?lat=&lng=` — confirm response shape
      (`{"station": {"id", "name", ...}}` vs flat object)
- [ ] `GET /api/stations/search?q=` — confirm response shape
      (`{"stations": [...]}` vs bare list)
- [ ] `GET /api/station/:id/tides?days=N&datum=MLLW` — confirm:
  - `extremes` array field name and entry fields (`time`, `height`, `type`)
  - Whether a `heights` / `timeSeries` / `waterLevels` array is returned
    for minute-by-minute data, or only extremes
  - `station` metadata sub-object field names (`id`, `name`, `timezone`,
    `latitude`/`lat`, `longitude`/`lng`)
  - Unit of `height` values when `datum=MLLW` is requested (feet vs metres)
  - Whether the `unit` / `units` field is present in the response

## Rate Limiting Strategy (50 req/day)

The free tier is very tight.  Current mitigation:

- **Aggressive caching**: raw API responses cached 24 hours; station lookups
  cached 1 hour; metadata cached 30 days; y-range cached 7 days.
- **Single-request design**: one `/tides?days=N` call returns extremes AND
  time series for up to 30 days, so a single request can power the full UI.
- **Synthesized curves**: when the API returns only extremes (no time series),
  a cosine-interpolated curve is generated client-side, avoiding extra requests.

### Future improvements

- [ ] Track daily request count in a local file to warn users before hitting
      the limit
- [ ] Add `X-RateLimit-Remaining` header parsing to surface budget in the UI
- [ ] Consider a paid-tier flag for users who upgrade beyond 50 req/day

## Potential Future Tide Sources

- **WorldTides** (worldtides.info) — global coverage, paid API
- **Stormglass** (stormglass.io) — global tide + weather, freemium
- **UKHO Admiralty** (admiralty.co.uk) — UK tidal predictions API
- **BOM Australia** — Australian Bureau of Meteorology tide data
- **SHOM France** — French hydrographic service
- **BSH Germany** — German maritime agency tidal data

## Known Gaps & Improvements

- [ ] The `_iana_to_abbr` mapping in `_tides_tidecheck.py` covers ~40 common
      timezones but will show "UTC" for unmapped ones.  Consider falling back
      to the abbreviated offset (e.g. "UTC+9") instead.
- [ ] TideCheck station IDs may be string slugs (e.g. "london-tower-bridge")
      rather than numeric.  The `_is_chs_station_id` check in `tides.py` won't
      match these, but the text-query path handles them.  A dedicated
      `_is_tidecheck_station_id` helper could improve direct-ID overrides.
- [ ] The cosine interpolation fallback produces a reasonable visual curve but
      is not hydrodynamically accurate.  If TideCheck provides minute-by-minute
      data, prefer that.
- [ ] Integration testing with a real TideCheck API key is needed to validate
      the full flow end-to-end.
