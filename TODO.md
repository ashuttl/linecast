# TideCheck Integration — TODO

## API Endpoint Verification — DONE (2026-08-20, live key)

The endpoints were originally inferred; all of them have now been verified
against the live API and the code corrected to match:

- [x] `GET /api/stations/nearest?lat=&lng=` — returns a **bare JSON array**
      sorted by distance, entries carry `id`, `name`, `label`, `lat`, `lng`,
      `region`, `country`, `distanceKm`.
- [x] `GET /api/stations/search?q=` — bare JSON array, same entry shape
      (minus `distanceKm`).
- [x] `GET /api/station/:id/tides?days=N&datum=MLLW` — returns `extremes`
      **only** (no minute series; `time` UTC with fractional seconds,
      `localTime` with offset, `localDate`, `height`, `type` "high"/"low"),
      plus a rich `station` object (`id`, `name`, `region`, `country`,
      `lat`, `lng`, `type`, `timezone` as IANA). Heights are **meters**;
      there is no `unit` field. Free tier serves from yesterday forward.

## Rate Limiting Strategy (50 req/day)

The free tier is very tight.  Current mitigation:

- **Aggressive caching**: raw API responses cached 24 hours; station lookups
  cached 1 hour; metadata cached 30 days; y-range cached 7 days.
- **Shared fetches**: metadata is extracted from the same 30-day `/tides`
  response the y-range uses, so it never costs a request of its own.
- **Synthesized curves**: the API publishes extremes only, so the smooth
  curve is generated client-side (shared cosine model with subordinate
  NOAA stations) — no extra requests.

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
      to the abbreviated offset (e.g. "UTC+9") instead.  (Display-only: the
      chart's math uses the IANA `timeZoneCode` directly.)
- [ ] TideCheck station IDs may be string slugs (e.g. "fes2022-lisbon")
      rather than numeric.  The `_is_chs_station_id` check in `tides.py` won't
      match these, but the text-query path handles them.  A dedicated
      `_is_tidecheck_station_id` helper could improve direct-ID overrides.
- [ ] The cosine interpolation is a visual approximation, not hydrodynamics —
      fine for the chart; the labeled extremes are the API's own numbers.
- [x] Integration testing with a real TideCheck API key — done 2026-08-20
      (Cascais via `--station`, Lisbon via nearest-station fallback; both
      render with correct meters→feet conversion and local times).
