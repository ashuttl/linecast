"""Names for places, and places for names: the geocoders every command uses.

Nominatim turns coordinates into a place's name, its country and its
address (reverse_geocode), in the display language or the country's
own, which is what the alert feeds' area names are matched against.
Open-Meteo's geocoder turns a name into coordinates (geocode), with
Photon standing in when it does not answer or finds nothing.  The maps' own search is
maps/search.py; it shares the Nominatim gate here, since both ask the
same server, which allows one request a second.
"""

import itertools
import time

from linecast._cache import location_cache_key, read_cache, read_stale, write_cache
from linecast._http import fetch_json, unanswered
from linecast._i18n import (
    GEOCODER_UNTRANSLATED, accept_language, base_language, geocoder_language,
)
from linecast._log import UserError, log_failure
from linecast._paths import cache_dir
from linecast._plaintext import plain_text
from linecast._rate_limit import RateLimit

PHOTON_URL = "https://photon.komoot.io/api"
# Photon translates place names into these three and nothing else;
# asking for anything more gets an error instead of English.
PHOTON_LANGS = ("en", "de", "fr")

# What Photon and Nominatim call a settlement or an area, as against a
# building, a business or a street: the kinds of thing a location is.
PLACE_KINDS = frozenset((
    "city", "town", "village", "hamlet", "municipality", "district",
    "locality", "suburb", "quarter", "neighbourhood", "borough", "county",
    "region", "province", "state", "country",
))


def places_first(results, kind):
    """*results* with the places in them (PLACE_KINDS) ahead of the rest,
    each in the geocoder's order.  Photon ranks "New York City Ballet"
    and six more ahead of New York for "New York City"."""
    results = list(results)
    return ([r for r in results if kind(r) in PLACE_KINDS]
            + [r for r in results if kind(r) not in PLACE_KINDS])

# Nominatim's usage policy allows one request a second from an
# application; reverse geocoding and the maps' search share this gate.
nominatim_throttle = RateLimit(1.0, "nominatim")

# After a reverse lookup goes unanswered, the next ones go straight to
# their fallback for a while.  On a stalled network each would wait out
# its own timeout, and a command asks more than once: a weather run
# asked three times, two of them one after the other.  An answer, even
# an error status or one that can't be read, holds nothing: it says
# nothing of the next place, and a tide station picked for a place
# with no country would skip the providers chosen by country.
_FAILURE_HOLD_S = 60.0
_failed_at = None   # time.monotonic() of the last failure


class GeocoderUnavailable(Exception):
    """Neither geocoder answered; the message is the first one's error."""


def country_code(addr):
    """The ISO country code of a Nominatim address, upper-cased.

    Hong Kong and Macau come back as China with the region in the
    ISO 3166-2 field ("CN-HK", "CN-MO"); each has its own weather
    service and tide stations, so they get their own codes, as the
    forward geocoder and the IP lookup already give them.
    """
    region = str(addr.get("ISO3166-2-lvl3", "")).upper()
    if region in ("CN-HK", "CN-MO"):
        return region[3:]
    return str(addr.get("country_code", "")).upper()


def reverse_geocode(lat, lng, lang=None):
    """Reverse geocode coordinates to a display name via Nominatim. Cached.

    Returns (display_name, country_code, address) tuple. `lang` localizes
    the returned names (Nominatim accept-language); without one they come
    in the country's own language, which is what the alert feeds' area
    names are matched against. Each place and language keeps its own
    cache file, so a command that asks both ways, or a reader who moves
    between two places, finds each the next time; offline, an answer
    older than a day is still given.
    """
    key = location_cache_key(lat, lng)
    cache_file = cache_dir("weather") / (f"place_{key}_{lang}.json" if lang
                                         else f"place_{key}.json")
    cached = read_cache(cache_file, 86400)  # 24h cache
    if _same_place(cached, lat, lng, lang):
        return _from_cache(cached)

    global _failed_at
    held = _failed_at is not None and time.monotonic() - _failed_at < _FAILURE_HOLD_S
    try:
        if held:
            raise OSError("not asked again so soon after a failure")
        url = (
            f"https://nominatim.openstreetmap.org/reverse"
            f"?lat={lat}&lon={lng}&format=json&zoom=10"
        )
        if lang:
            url += f"&accept-language={accept_language(lang)}"
        nominatim_throttle()
        data = fetch_json(url, timeout=10)
        addr = plain_values(data.get("address", {}))
        # Nominatim files small places under keys all the way down to
        # hamlet (Fayette, Maine is one); without them the name comes back
        # empty and the caller falls back to the timezone city (issue #50).
        name = (addr.get("city") or addr.get("town") or addr.get("village")
                or addr.get("hamlet") or addr.get("municipality") or "")
        state = addr.get("state", "")
        country = country_code(addr)
        if name and state:
            display = f"{name}, {state}"
        elif name:
            display = name
        else:
            display = ""
    except Exception as exc:
        if not held and unanswered(exc):
            _failed_at = time.monotonic()
        # Offline, a name from yesterday is still the place's name, and
        # its address still matches the alert feeds' areas.
        stale = read_stale(cache_file)
        if _same_place(stale, lat, lng, lang):
            log_failure("location/geocoder", "reverse geocode", exc,
                        url="nominatim.openstreetmap.org",
                        fallback=f"stale cache {cache_file.name}")
            return _from_cache(stale)
        log_failure("location/geocoder", "reverse geocode", exc,
                    url="nominatim.openstreetmap.org", fallback="unnamed location")
        return "", "", {}

    # the answer is in hand; keeping it is a separate, best-effort matter
    write_cache(cache_file, {
        "lat": round(lat, 4), "lng": round(lng, 4), "lang": lang,
        "name": display, "country_code": country,
        "address": addr,
    })
    return display, country, addr


def _same_place(cached, lat, lng, lang):
    """Whether a cached answer is for this place in this language."""
    return (isinstance(cached, dict) and cached.get("lat") == round(lat, 4)
            and cached.get("lng") == round(lng, 4) and cached.get("lang", None) == lang)


def _from_cache(cached):
    return (plain_text(cached.get("name", "")), cached.get("country_code", ""),
            plain_values(cached.get("address", {})))


def place_label(lat, lng, label, lang):
    """The name a view shows for a place.

    *label* is the forward geocoder's name for a place typed with
    --location, which names what was asked for.  Without one, or in a
    language the forward geocoder has no names in (GEOCODER_UNTRANSLATED),
    Nominatim names the coordinates in *lang*, and *label* stands when
    it has no name.  "" when neither has one; the view says how to show
    that."""
    if label and lang not in GEOCODER_UNTRANSLATED:
        return label
    try:
        return reverse_geocode(lat, lng, lang=lang)[0] or label or ""
    except Exception as exc:
        log_failure("location/geocoder", "place name", exc, fallback="the typed label")
        return label or ""


def plain_values(mapping):
    """A geocoder's dict with the terminal controls out of its strings."""
    if not isinstance(mapping, dict):
        return mapping
    return {key: plain_text(value) for key, value in mapping.items()}


def photon_query(query, lang="en", timeout=10):
    """Photon's answer to a place name, reshaped to the Open-Meteo
    geocoder's result dicts, places first — the second source when
    Open-Meteo doesn't answer or knows nothing by the name. Photon
    speaks en/de/fr only; any other language asks in English rather
    than getting an error back."""
    import urllib.parse

    from linecast import user_agent

    params = [("q", query), ("limit", 10)]
    if base_language(lang) in PHOTON_LANGS:
        params.append(("lang", base_language(lang)))
    url = f"{PHOTON_URL}?{urllib.parse.urlencode(params)}"
    data = fetch_json(url, headers={"User-Agent": user_agent()}, timeout=timeout)
    results = []
    for feature in data.get("features") or []:
        props = feature.get("properties") or {}
        name = plain_text(props.get("name") or "").strip()
        coords = (feature.get("geometry") or {}).get("coordinates") or []
        if not name or len(coords) < 2:
            continue
        results.append({
            "name": name,
            "latitude": float(coords[1]),
            "longitude": float(coords[0]),
            "admin1": plain_text(props.get("state", "")),
            "country": plain_text(props.get("country", "")),
            "country_code": props.get("countrycode", ""),
            "kind": props.get("type", ""),
        })
    return places_first(results, lambda r: r["kind"])


# Open-Meteo reads a trailing ", XX" as a country when it is the ISO
# code or the country's name; these everyday forms are neither, and
# "London, UK" found nothing.
_COUNTRY_ALIASES = {"uk": "GB", "usa": "US", "us": "US"}


def _iso_country(query):
    """*query* with a trailing everyday country name ("UK", "U.S.A.")
    swapped for its ISO code, which the geocoder matches."""
    head, comma, tail = query.rpartition(",")
    code = _COUNTRY_ALIASES.get(tail.strip().replace(".", "").casefold()) if comma else None
    return f"{head.rstrip()}, {code}" if code and head.strip() else query


def _open_meteo(query, lang):
    """Open-Meteo's results for *query*; raises when it doesn't answer."""
    import urllib.parse

    url = (
        "https://geocoding-api.open-meteo.com/v1/search"
        f"?name={urllib.parse.quote(_iso_country(query))}&count=10"
        f"&language={geocoder_language(lang)}"
    )
    try:
        data = fetch_json(url, timeout=10)
    except Exception as exc:
        log_failure("location/geocoder", "geocode", exc, url=url, fallback="Photon")
        raise
    return [plain_values(r) for r in data.get("results") or []]


def _folded(text):
    """*text* as a keyboard without accents or full stops spells it:
    São Paulo as sao paulo, St. Gallen as st gallen."""
    import unicodedata
    text = unicodedata.normalize("NFKD", text.replace(".", " "))
    return " ".join("".join(ch for ch in text if not unicodedata.combining(ch))
                    .casefold().split())


def _names(results, name):
    """True when one of *results* is called *name*, and not merely
    spelled something like it."""
    return any(_folded(r.get("name", "")) == _folded(name) for r in results)


def _qualified(query):
    """*query*, typed without commas, read as a name and the state or
    country it is in, the longest name first: "Portland Oregon USA" as
    "Portland Oregon, USA", "Portland, Oregon USA", then "Portland,
    Oregon, USA".  The geocoder reads what follows a comma as where the
    place is, and the whole of a query without one as the name."""
    words = query.split()
    for i in range(len(words) - 1, 0, -1):
        name, where = " ".join(words[:i]), words[i:]
        yield name, f"{name}, {' '.join(where)}"
        if len(where) > 1:
            yield name, f"{name}, {' '.join(where[:-1])}, {where[-1]}"


# The readings _qualified offers past the query as typed, at most: a
# query of four words or fewer is read every way it has.
_QUALIFIED_TRIES = 5


def geocode(query, lang="en"):
    """Geocode a place name via Open-Meteo, falling back to Photon.
    Returns list of result dicts; raises GeocoderUnavailable when
    neither answers.

    Open-Meteo matches a query without a comma as one name, so
    "portland maine" found nothing and "Portland ME" found Portland
    Meadows, a park in Oregon.  When nothing it found is called what
    was typed, the query is asked again as a name and where it is
    (_qualified); a reading that finds a place by that name wins, and
    without one the query as typed stands, unless it found nothing.
    What no reading finds is asked of Photon, which reads a misspelling
    ("Pordland") and knows the café on the corner, as the location
    menu's search does.
    """
    try:
        results = _open_meteo(query, lang)
    except Exception as exc:
        try:
            return photon_query(query, lang=lang)
        except Exception as photon_exc:
            log_failure("location/photon", "geocode", photon_exc,
                        fallback="GeocoderUnavailable")
            raise GeocoderUnavailable(str(exc)) from photon_exc
    if "," not in query and not _names(results, query):
        for name, reading in itertools.islice(_qualified(query), _QUALIFIED_TRIES):
            try:
                found = _open_meteo(reading, lang)
            except Exception:
                break
            if _names(found, name):
                return found
            results = results or found
    if results:
        return results
    try:
        return photon_query(query, lang=lang)
    except Exception as exc:
        log_failure("location/photon", "geocode", exc, fallback="no match")
        return []


def geocode_first(query: str, lang: str = "en") -> tuple[float, float, str] | None:
    """Geocode a place name and return the top result as (lat, lng, label).

    Returns ``None`` if nothing matches.
    """
    results = geocode(query, lang=lang)
    if not results:
        return None
    r = results[0]
    return r.get("latitude", 0), r.get("longitude", 0), result_label(r)


def result_label(result) -> str:
    """A geocoder result as "name, admin1, country". A region named for
    its city is left out: "Busan, South Korea", not "Busan, Busan", and
    so is a country found as itself: "Poland", not "Poland, Poland"."""
    name = result.get("name", "")
    parts = [name]
    for part in (result.get("admin1", ""), result.get("country", "")):
        if part and part.casefold() not in {p.casefold() for p in parts}:
            parts.append(part)
    return ", ".join(parts)


def without_country(label: str) -> str:
    """A result_label without its country, for a header with less room
    than the tides pill: "Osaka, préfecture d'Osaka"."""
    parts = label.split(", ")
    return ", ".join(parts[:2]) if len(parts) == 3 else label


def print_search(query, lang="en"):
    """Search cities using Open-Meteo geocoding API and print results."""
    try:
        results = geocode(query, lang=lang)
    except GeocoderUnavailable as exc:
        raise UserError(f"Search failed: {exc}") from exc
    if not results:
        print(f'No locations matching "{query}".')
        return

    for result in results:
        lat = result.get("latitude", 0)
        lng = result.get("longitude", 0)
        print(f"  {lat:.4f},{lng:.4f}  {result_label(result)}")

    print("\nUsage: weather --location LAT,LNG")
    print("   or: linecast location set LAT,LNG")
    print("   or: export WEATHER_LOCATION=LAT,LNG")
