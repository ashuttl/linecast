"""Names for places, and places for names: the geocoders every command uses.

Nominatim turns coordinates into a place's name, its country and its
address (reverse_geocode), in the display language or the country's
own, which is what the alert feeds' area names are matched against.
Open-Meteo's geocoder turns a name into coordinates (geocode), with
Photon standing in when it does not answer.  The maps' own search is
maps/search.py; it shares the Nominatim gate here, since both ask the
same server, which allows one request a second.
"""

import sys

from linecast._cache import read_cache, write_cache
from linecast._http import fetch_json
from linecast._i18n import (
    GEOCODER_UNTRANSLATED, accept_language, base_language, geocoder_language,
)
from linecast._log import log_failure
from linecast._paths import cache_dir
from linecast._plaintext import plain_text
from linecast._rate_limit import RateLimit

PHOTON_URL = "https://photon.komoot.io/api"
# Photon translates place names into these three and nothing else;
# asking for anything more gets an error instead of English.
PHOTON_LANGS = ("en", "de", "fr")

# Nominatim's usage policy allows one request a second from an
# application; reverse geocoding and the maps' search share this gate.
nominatim_throttle = RateLimit(1.0, "nominatim")


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
    names are matched against. Each language keeps its own cache file, so
    a command that asks both ways finds both the next time.
    """
    cache_file = cache_dir("weather") / (f"location_{lang}.json" if lang else "location.json")
    cached = read_cache(cache_file, 86400)  # 24h cache
    if (cached and cached.get("lat") == round(lat, 4)
            and cached.get("lng") == round(lng, 4)
            and cached.get("lang", None) == lang):
        return (plain_text(cached.get("name", "")), cached.get("country_code", ""),
                plain_values(cached.get("address", {})))

    try:
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
    geocoder's result dicts — the second source when Open-Meteo doesn't
    answer. Photon speaks en/de/fr only; any other language asks in
    English rather than getting an error back."""
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
        })
    return results


def geocode(query, lang="en"):
    """Geocode a place name via Open-Meteo, falling back to Photon.
    Returns list of result dicts; raises GeocoderUnavailable when
    neither answers."""
    import urllib.parse

    url = (
        "https://geocoding-api.open-meteo.com/v1/search"
        f"?name={urllib.parse.quote(query)}&count=10&language={geocoder_language(lang)}"
    )
    try:
        data = fetch_json(url, timeout=10)
    except Exception as exc:
        log_failure("location/geocoder", "geocode", exc, url=url, fallback="Photon")
        try:
            return photon_query(query, lang=lang)
        except Exception as photon_exc:
            log_failure("location/photon", "geocode", photon_exc,
                        fallback="GeocoderUnavailable")
            raise GeocoderUnavailable(str(exc)) from photon_exc
    return [plain_values(r) for r in data.get("results") or []]


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
    its city is left out: "Busan, South Korea", not "Busan, Busan"."""
    name = result.get("name", "")
    parts = [name]
    admin1 = result.get("admin1", "")
    if admin1 and admin1.casefold() != name.casefold():
        parts.append(admin1)
    if result.get("country"):
        parts.append(result["country"])
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
        sys.exit(f"Search failed: {exc}")
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
