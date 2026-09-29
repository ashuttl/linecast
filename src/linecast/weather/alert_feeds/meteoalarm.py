"""Alerts from MeteoAlarm, for the European countries without a
service of their own here."""

import re

from linecast._cache import location_cache_key
from linecast._http import fetch_json
from linecast._paths import cache_dir
from linecast.weather.alert_feeds.cap import cap_polygons, point_in_ring
from linecast.weather.alert_feeds import _cached_feed

# A feed is the whole country's, and one that draws every warning's
# outline runs big: Switzerland's was 9.4 MB on 2026-09-02, past the
# 8 MiB fetch_json allows, and the refusal read as a quiet day. The cap
# stays, since a runaway server is still the thing it is for, but high
# enough that a stormy day in a polygon-filing country gets through.
_METEOALARM_FEED_BYTES = 32 * 1024 * 1024


def fetch(lat, lng, lang="en", address=None, *, slug):
    """Fetch MeteoAlarm warnings for a European country, from the feed
    MeteoAlarm calls `slug`. Cached 15min.

    Filters by severity and area match against the user's Nominatim address.
    Prefers the user's language for alert text, falling back to English.
    """
    cache_file = cache_dir(
        "weather", f"alerts_eu_{slug}_{location_cache_key(lat, lng)}_{lang}.json")
    url = f"https://feeds.meteoalarm.org/api/v1/warnings/feeds-{slug}"
    return _cached_feed(
        cache_file, url, lambda data: _parse_meteoalarm(data, lat, lng, lang, address),
        timeout=15,
        fetch=lambda url, timeout: fetch_json(
            url, headers={"Accept": "application/json"}, timeout=timeout,
            limit=_METEOALARM_FEED_BYTES),
    )


def _parse_meteoalarm(data, lat, lng, lang, address):
    """A MeteoAlarm country feed's warnings for the place, normalized."""
    warnings = data.get("warnings", [])
    per_warning_descs = [
        [area.get("areaDesc") or ""
         for info in (w.get("alert") or {}).get("info") or []
         for area in info.get("area") or []]
        for w in warnings
    ]
    location_words = _drop_feed_wide_words(
        _extract_location_words(address), per_warning_descs)
    here = _regions_here(lat, lng, warnings)
    alerts = []
    seen = {}
    national = []
    national_seen = set()
    for w in warnings:
        alert_obj = w.get("alert") or {}
        infos = alert_obj.get("info") or []
        # Prefer user's language, fall back to English, then first available
        preferred_info = None
        en_info = None
        other_info = None
        area_descs = []
        areas = []
        for info in infos:
            # an info block with no language tag is one in the feed's own
            info_lang = info.get("language") or ""
            if info_lang.startswith(lang):
                preferred_info = info
            elif info_lang.startswith("en"):
                en_info = info
            elif other_info is None:
                other_info = info
            for area in info.get("area") or []:
                area_descs.append(area.get("areaDesc") or "")
                areas.append(area)
        info = preferred_info or en_info or other_info
        if not info:
            continue
        codes = _region_keys(areas)

        severity = info.get("severity") or ""
        if severity == "Minor":
            continue

        event = info.get("event") or ""
        if not event:
            continue
        # MeteoAlarm providers (e.g. DMI) often prefix the event name with
        # the English color level ("yellow Tåge", "orange Regn").  Strip it
        # since we already convey severity via the pill background colour.
        event = re.sub(r"^(?:yellow|orange|red|green)\s+", "", event, flags=re.IGNORECASE)

        # The feed is the whole country's, so every alert has to earn its
        # place. A CAP polygon settles it outright: it is the warning's
        # own account of the ground it covers, and it tells a gauge on one
        # brook apart from a red warning for half the country, which no
        # reading of an areaDesc can. Where the feed carries geometry,
        # nothing else is consulted -- not even severity, since being
        # outside an Extreme warning's polygon means being outside it.
        rings = [ring for area in areas for ring in cap_polygons(area)]
        if rings:
            matched = any(point_in_ring(lat, lng, ring) for ring in rings)
            geometric = True
        elif codes and here:
            # No polygon, but a geocode: an EMMA_ID, NUTS, or CISORP code
            # names a region whose ground we carry, so it is as
            # good as a polygon. Only where the point is in some region
            # of the data, though; off the coast, or in a country the
            # data lacks, the codes prove nothing and the areaDesc must do.
            matched = bool(codes & here)
            geometric = True
        else:
            geometric = False
            # No geometry: fall back to reading the areaDesc against the
            # user's address. Extreme is exempt -- at that level the
            # country should hear about it wherever it is -- and so is a
            # user we hold no address for, there being nothing to match.
            if severity == "Extreme" or not location_words:
                matched = True
            else:
                matched = any(_area_matches(ad, location_words)
                              for ad in area_descs)

        alert = {
            "event": event,
            "headline": info.get("headline") or event,
            "description": info.get("description") or "",
            "effective": info.get("onset") or info.get("effective") or "",
            "expires": info.get("expires") or "",
            "severity": severity,
            "url": info.get("web") or "",
        }

        if not matched:
            if geometric:
                continue  # the warning says where it applies; believe it
            # Read off an areaDesc, "no match" is a weaker finding. A
            # Severe warning for one river gauge 500km away is noise, but
            # a red warning for the whole country carries an areaDesc
            # that matches nobody's address either, and dropping that
            # would be the worse mistake. Hold the unmatched Severe ones
            # back and show them only if nothing local turned up: a
            # national warning still lands on an empty board, and a single
            # brook no longer outranks the local picture.
            key = (event, severity)
            if severity == "Severe" and key not in national_seen:
                national_seen.add(key)
                national.append(alert)
            continue

        # The text, not the ground, tells one warning from another.
        # Poland's service files a storm as one warning per county, word
        # for word the same across a province, and every county in the
        # province matched a Masovian address: 28 pills for one storm
        # (issue #57). Two warnings that read the same are one warning
        # to the reader. Where there is no text, the ground covered is
        # all that tells them apart, and it stays in the key: on
        # (event, severity) alone a country in flood collapses to one
        # arbitrary river's warning.
        dedup_key = (event, severity,
                     alert["description"] or " | ".join(area_descs))
        # Of the copies, keep the one whose ground reads most like the
        # user's address, so the headline names their own county.
        score = sum(1 for word in location_words
                    if any(word in ad.lower() for ad in area_descs))
        held = seen.get(dedup_key)
        if held is not None:
            if score > held[0]:
                alerts[held[1]] = alert
                seen[dedup_key] = (score, held[1])
            continue
        seen[dedup_key] = (score, len(alerts))
        alerts.append(alert)

    if not alerts:
        alerts = national
    return alerts


# Words that name an administrative tier rather than a place. Nominatim
# gives Edinburgh a county of "City of Edinburgh" and the Rhône one of
# "Auvergne-Rhône-Alpes Region"; left in, "city" and "region" match a good
# part of Europe's areaDescs and the filter stops filtering.
#
# Addresses come back in the country's own language, and so do the
# areaDescs, so every MeteoAlarm country's tier words belong here too.
# Warsaw's address is "Warszawa, województwo mazowieckie", and every
# Polish areaDesc begins "województwo ..."; that one word matched the
# whole country's warnings, 419 of them (issue #57).
_GENERIC_PLACE_WORDS = frozenset({
    # English, and the English names Nominatim gives foreign tiers
    "administrative", "area", "autonomous", "borough", "canton", "city",
    "community", "council", "county", "department", "district",
    "division", "metropolitan", "municipality", "oblast", "okrug",
    "prefecture", "province", "raion", "region", "regional", "state",
    "territory", "unitary", "voivodeship",
    # Polish
    "województwo", "powiat", "gmina", "miasto",
    # Czech, Slovak
    "kraj", "okres", "obec", "hlavní", "město", "mesto",
    # Hungarian
    "megye", "vármegye", "járás", "város", "kerület",
    # Romanian, Moldovan
    "județul", "județ", "municipiul", "comuna", "sectorul", "raionul",
    # Bulgarian, Serbian, Macedonian, Montenegrin
    "област", "община", "општина", "округ", "град", "opština", "grad",
    # Croatian, Slovenian, Bosnian
    "županija", "općina", "občina", "mestna", "kanton",
    # German (Austria, Switzerland, Luxembourg)
    "bezirk", "landkreis", "kreis", "gemeinde", "stadt", "regierungsbezirk",
    # Dutch, Flemish
    "provincie", "gemeente", "arrondissement", "gewest", "stad",
    # French (France, Belgium, Switzerland, Luxembourg)
    "département", "région", "commune", "métropole", "communauté", "ville",
    # Spanish, Catalan, Galician, Basque
    "provincia", "comunidad", "autónoma", "municipio", "comarca",
    "comunitat", "província", "autònoma", "concello", "probintzia",
    # Portuguese
    "distrito", "concelho", "freguesia", "município", "região",
    # Italian
    "regione", "comune", "città", "metropolitana",
    # Greek, Cypriot
    "περιφέρεια", "περιφερειακή", "ενότητα", "δήμος", "νομός", "επαρχία",
    # Danish, Swedish, Finnish, Icelandic
    "kommune", "län", "kommun", "maakunta", "kunta", "seutukunta",
    "sveitarfélag", "sýsla",
    # Estonian, Latvian, Lithuanian
    "maakond", "vald", "linn", "novads", "pagasts", "pilsēta",
    "apskritis", "rajonas", "savivaldybė", "miestas", "seniūnija",
    # Maltese, Irish, Hebrew
    "reġjun", "kunsill", "lokali", "contae", "מחוז", "נפת", "נפה",
})

# A word the feed itself shows to be a tier word: one found in the areas
# of this share of a country's warnings names no single place, whatever
# language it is in. Judged only on a feed big enough to be telling; in
# a quiet country with three warnings, all in one province, the
# province's name matches all three and is not generic for it.
_FEED_WIDE_SHARE = 0.8
_FEED_WIDE_MIN_WARNINGS = 20


def _drop_feed_wide_words(location_words, per_warning_descs):
    """Location words minus any that match most of the feed.

    per_warning_descs holds one list of areaDesc strings per warning.
    The list of tier words above cannot know every language Nominatim
    speaks; this reads the tier words off the feed at hand instead.
    """
    if len(per_warning_descs) < _FEED_WIDE_MIN_WARNINGS:
        return location_words
    limit = _FEED_WIDE_SHARE * len(per_warning_descs)
    kept = set()
    for word in location_words:
        hits = sum(1 for descs in per_warning_descs
                   if any(word in d.lower() for d in descs))
        if hits < limit:
            kept.add(word)
    return kept


def _region_keys(areas):
    """The geocodes on a warning's areas that the data has ground for.

    Each is looked up by type and value: EMMA_IDs as themselves, a
    NUTS3, NUTS2, or CISORP code under its type. France's FR101 is both
    a NUTS3 code and an EMMA_ID; the type keeps them from crossing.
    """
    from linecast.weather.alert_feeds.meteoalarm_regions import key_for, known
    keys = set()
    for area in areas:
        for geocode in area.get("geocode") or []:
            key = key_for(geocode.get("valueName") or "", geocode.get("value") or "")
            if known(key):
                keys.add(key)
    return keys


def _regions_here(lat, lng, warnings):
    """The region keys covering the point, looked up only if a warning could use them."""
    from linecast.weather.alert_feeds.meteoalarm_regions import regions_at
    for w in warnings:
        for info in (w.get("alert") or {}).get("info") or []:
            if _region_keys(info.get("area") or []):
                return regions_at(lat, lng)
    return set()


def _extract_location_words(address):
    """Extract location words from a Nominatim address for area matching."""
    if not address:
        return set()
    words = set()
    for key in ("city", "town", "village", "county", "state", "municipality",
                "suburb", "district", "region"):
        val = address.get(key, "")
        if val:
            for word in val.split():
                word = word.strip("(),.").lower()
                if len(word) >= 3 and word not in _GENERIC_PLACE_WORDS:
                    words.add(word)
    return words


def _area_matches(area_desc, location_words):
    """Check if a MeteoAlarm areaDesc contains any of the user's location words."""
    if not area_desc or not location_words:
        return False
    desc_lower = area_desc.lower()
    return any(word in desc_lower for word in location_words)
