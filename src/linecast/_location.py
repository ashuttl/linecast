"""IP geolocation with caching and country detection."""

import math
import os
import sys
from datetime import tzinfo

from linecast._cache import location_cache_key, read_cache, read_stale, write_cache
from linecast._config import SETTING, saved_location
from linecast._http import fetch_json, fetch_json_cached
from linecast._paths import cache_dir
from linecast._plaintext import plain_text
from linecast._log import log_failure

_MAX_AGE = 3600  # 1 hour; implicit IP geolocation should refresh as users move.


def _parse_ipinfo(data):
    lat, lng = data.get("loc", "").split(",")
    return float(lat), float(lng), data.get("country", "")


def _parse_ipwhois(data):
    if data.get("success") is False:  # errors still arrive as HTTP 200
        raise ValueError(data.get("message") or "refused")
    return float(data["latitude"]), float(data["longitude"]), data.get("country_code", "")


def _parse_geojs(data):
    return float(data["latitude"]), float(data["longitude"]), data.get("country_code", "")


# Tried in order; each is keyless. ipinfo.io answers first; ipwho.is and
# GeoJS are the second opinions when it doesn't (issue #34).
PROVIDERS = (
    ("ipinfo", "https://ipinfo.io/json", _parse_ipinfo),
    ("ipwho.is", "https://ipwho.is/", _parse_ipwhois),
    ("GeoJS", "https://get.geojs.io/v1/ip/geo.json", _parse_geojs),
)
# A source that has kept us this long without an answer gets company:
# the next is asked beside it rather than after its timeout, so a
# network that has stalled costs about one timeout rather than three.
# ipinfo answers well inside it, so a working network asks it alone.
_HEDGE_S = 1.0


def _cache_file():
    return cache_dir("location.json")


def _cached_place(data):
    """(lat, lng, country) from the IP-geolocation cache, or None unless
    it holds a place on the planet.  Only linecast writes the file, but
    a crash or a hand edit can leave anything there, and `[]` or a
    latitude of "x" ended the command in a traceback."""
    if not isinstance(data, dict):
        return None
    lat, lng, country = data.get("lat"), data.get("lng"), data.get("country", "")
    if not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in (lat, lng)):
        return None
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        return None
    return float(lat), float(lng), country if isinstance(country, str) else ""


def get_location() -> tuple[float | None, float | None, str | None]:
    """Get (lat, lng, country_code) from cache or IP geolocation.

    Returns (lat, lng, country_code) on success, (None, None, None) on failure.
    country_code is ISO 3166-1 alpha-2 (e.g., "US", "CA", "GB").

    A location saved via `linecast location set` takes precedence over IP
    geolocation. (--location flags and WEATHER_LOCATION are handled by
    callers before reaching here, so overall precedence is flag > env >
    saved > IP.)
    """
    saved = saved_location()
    if saved is not None:
        return saved["lat"], saved["lng"], saved.get("country", "")

    cached = _cached_place(read_cache(_cache_file(), _MAX_AGE))
    if cached is not None:
        return cached

    found = _ask_sources()
    if found is None:
        # Offline, the place the machine was last found is a better
        # guess than none, and the moon, the sky and the sun need
        # nothing else from the network.
        stale = _cached_place(read_stale(_cache_file()))
        return stale if stale is not None else (None, None, None)

    lat, lng, country = found
    # the answer is in hand; keeping it is a separate, best-effort matter
    write_cache(_cache_file(), {"lat": lat, "lng": lng, "country": country})
    return lat, lng, country


def _ask_sources():
    """(lat, lng, country) from the first source to answer, or None.

    The sources are asked in PROVIDERS order, each started once the one
    before it has failed or has kept us waiting _HEDGE_S, and the first
    answer from any of those out is taken.  The rest are left to finish
    on their daemon threads, and say nothing more.
    """
    import queue
    import threading

    answers = queue.SimpleQueue()
    done = threading.Event()

    def ask(i, name, url, parse):
        try:
            data = fetch_json(url, headers={"Accept": "application/json"}, timeout=3)
            lat, lng, country = parse(data)
            answers.put((float(lat), float(lng), plain_text(country)))
        except Exception as exc:
            if not done.is_set():
                last = i == len(PROVIDERS) - 1
                log_failure(f"location/{name}", "geolocation", exc, url=url,
                            fallback="last location found, if any" if last
                            else PROVIDERS[i + 1][0])
            answers.put(None)

    asked = out = 0
    while True:
        if asked < len(PROVIDERS):
            threading.Thread(target=ask, args=(asked, *PROVIDERS[asked]), daemon=True).start()
            asked += 1
            out += 1
        try:
            found = answers.get(timeout=_HEDGE_S if asked < len(PROVIDERS) else None)
        except queue.Empty:
            continue   # the next source is asked beside the ones still out
        out -= 1
        if found is not None:
            done.set()
            return found
        if not out and asked == len(PROVIDERS):
            return None


def own_country() -> str | None:
    """The user's own country (ISO alpha-2), for units and clock defaults.

    The saved location's country, else the IP-geolocation cache -- read
    with a 30-day tolerance, since a country changes far more slowly than
    a position -- else None.  Never fetches: the defaults must resolve
    offline, and before any command has touched the network.
    """
    saved = saved_location()
    if saved is not None and saved.get("country"):
        return saved["country"]
    cached = _cached_place(read_cache(_cache_file(), 30 * 86400))
    if cached is not None and cached[2]:
        return cached[2]
    return None


def country_for_defaults(
    cli_location: str | None, country_code: str | None,
    lat: float | None = None, lng: float | None = None,
) -> str | None:
    """The country whose conventions set the units and clock defaults.

    That is the user's own country: the resolved location's when nothing
    points the view elsewhere.  With a --location override the user's
    country comes from own_country() and this returns None, meaning the
    runtime already has it -- except on a first run, before a location is
    saved or an IP answer cached, when nothing is known.  Then the viewed
    place's country stands in: imperial for "Portland, Maine" is a better
    guess than metric-and-24-hour.  Reverse geocoding it is cached.
    """
    if not location_overridden(cli_location):
        return country_code or None
    if own_country() is not None:
        return None
    if country_code:
        return country_code
    if lat is None or lng is None:
        return None
    try:
        from linecast._geocode import reverse_geocode
        _name, country, _addr = reverse_geocode(lat, lng)
    except Exception as exc:
        log_failure("location/geocoder", "country lookup", exc, fallback="no country")
        return None
    return country or None


def location_overridden(cli_location: str | None = None) -> bool:
    """True when a --location flag or WEATHER_LOCATION points the view
    somewhere explicit -- a place that need not be the user's own, so
    its country must not feed the units default."""
    return bool((cli_location or os.environ.get(SETTING["location"].env, "")).strip())


def resolve_location(
    cli_location: str | None = None, lang: str = "en", need_country: bool = False,
    return_label: bool = False,
) -> (tuple[float | None, float | None, str | None]
      | tuple[float | None, float | None, str | None, str]):
    """Resolve the working location for a command.

    Precedence: --location flag (*cli_location*) > WEATHER_LOCATION env >
    saved location > IP geolocation. Returns (lat, lng, country_code), or
    (None, None, None) when no location can be determined. An explicit
    override that can't be geocoded exits with an error message instead.

    country_code is "" for overrides unless *need_country* is set, in which
    case it is filled in via the (cached) reverse geocoder.

    With *return_label*, a fourth element carries the geocoder's label for
    a place-name override ("" otherwise); radar and maps show it as the
    place name instead of reverse-geocoding the coordinates again.
    """
    override = (cli_location or os.environ.get(SETTING["location"].env, "")).strip()
    if not override:
        lat, lng, country = get_location()
        return (lat, lng, country, "") if return_label else (lat, lng, country)

    country = ""
    label = ""
    latlng = parse_latlng(override)
    if latlng is not None:
        lat, lng = latlng
    else:
        from linecast._geocode import GeocoderUnavailable, geocode_first
        try:
            hit = geocode_first(override, lang=lang)
        except GeocoderUnavailable as exc:
            sys.exit(f"Search failed: {exc}")
        if hit is None:
            # sys.exit with a message prints it to stderr with status 1,
            # after the caller's finally blocks have run -- so a spinner
            # on the same line is cleared before the message lands.
            sys.exit(f'No locations matching "{override}".')
        lat, lng, label = hit
    if need_country:
        from linecast._geocode import reverse_geocode
        _name, country, _addr = reverse_geocode(lat, lng)
    return (lat, lng, country, label) if return_label else (lat, lng, country)


def same_place(a, b) -> bool:
    """Whether two (lat, lng) pairs are the same place: equal to four
    decimal places, about ten metres."""
    return (round(a[0], 4), round(a[1], 4)) == (round(b[0], 4), round(b[1], 4))


def parse_latlng(text: str) -> tuple[float, float] | None:
    """'lat,lng' as two floats, or None for anything else.

    Two parts, both finite and on the planet: "91,0" and "1,2,3" are
    not coordinates, and are left for the geocoder to refuse by name
    rather than sent on as a place that does not exist. A third part
    would be silently dropped otherwise, which is how "48,85,2,35" from
    a decimal-comma locale read as 48°N 85°E.
    """
    parts = text.split(",")
    if len(parts) != 2:
        return None
    try:
        lat, lng = float(parts[0]), float(parts[1])
    except ValueError:
        return None
    if not (math.isfinite(lat) and math.isfinite(lng)):
        return None
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        return None
    return lat, lng


def location_is_pinned(cli_location: str | None = None) -> bool:
    """True when the location comes from a flag, env var, or saved setting.

    A pinned location may be anywhere on Earth; an unpinned (IP-derived)
    one is where the machine is, so machine-local time already matches it.
    """
    return bool(cli_location
                or os.environ.get(SETTING["location"].env, "").strip()
                or saved_location() is not None)


def machine_tzinfo() -> tzinfo:
    """The machine's time zone, with its clock changes.

    datetime.now().astimezone() carries only today's offset, so a
    moonrise or a new moon a month off, read on it, lands an hour out
    across a change of clock, and near midnight on the wrong day.  The
    zone is found by name, from TZ or /etc/localtime, and kept only if
    it agrees with the machine's clock now; else the fixed offset.
    """
    from datetime import datetime
    now = datetime.now().astimezone()
    names = [os.environ.get("TZ", "").lstrip(":")]
    if sys.platform == "win32":
        names.append(_windows_zone_name())
    else:
        try:
            path = os.path.realpath("/etc/localtime")
            if "/zoneinfo/" in path:
                names.append(path.split("/zoneinfo/", 1)[1])
        except OSError:
            pass
    for name in names:
        if not name:
            continue
        try:
            from zoneinfo import ZoneInfo
            zone = ZoneInfo(name)
        except Exception:
            continue
        if now.astimezone(zone).utcoffset() == now.utcoffset():
            return zone
    return now.tzinfo


def _windows_zone_name() -> str | None:
    """The machine's zone by its IANA name on Windows, or None.

    Windows keeps zones under names of its own ("Eastern Standard Time")
    and sets neither TZ nor /etc/localtime, but the ICU it has shipped
    since Windows 10 1903 answers with the IANA name.  An older Windows,
    or anything unexpected, is None, and the fixed offset stands.
    """
    try:
        import ctypes
        # ICU exports cdecl functions (U_EXPORT2): CDLL, not WinDLL, or a
        # 32-bit Python unbalances the stack on every call
        icu = ctypes.CDLL("icu.dll")
        ask = icu.ucal_getDefaultTimeZone
        ask.restype = ctypes.c_int32
        ask.argtypes = (ctypes.c_wchar_p, ctypes.c_int32, ctypes.POINTER(ctypes.c_int))
        buf = ctypes.create_unicode_buffer(128)
        status = ctypes.c_int(0)
        length = ask(buf, len(buf), ctypes.byref(status))
    except Exception:
        return None
    # ICU's errors are positive; a name that filled the buffer has no end
    if status.value > 0 or not 0 < length < len(buf):
        return None
    return buf.value


# The zone name each place's lookup found this run (None for none), by
# its cache file's name.  place_for looks the zone up beside its own
# wait, and the view asks again when it needs the answer; the second ask
# takes this one rather than waiting out a failed lookup's timeout again.
_zones: dict = {}


def location_tzinfo(lat: float | None, lng: float | None) -> tzinfo | None:
    """tzinfo for a location, via a cached Open-Meteo timezone lookup.

    Falls back to the machine's local timezone when the lookup fails
    (offline with a cold cache) or the zone database lacks the name.
    Cached for 30 days per location, and looked up once a run.
    """
    machine_tz = machine_tzinfo()
    if lat is None or lng is None:
        return machine_tz

    cache_file = cache_dir(f"timezone_{location_cache_key(lat, lng)}.json")
    if cache_file.name not in _zones:
        url = (
            "https://api.open-meteo.com/v1/forecast"
            f"?latitude={lat}&longitude={lng}&timezone=auto"
        )
        data = fetch_json_cached(
            cache_file,
            30 * 86400,
            url,
            timeout=5,
            fallback=None,
        )
        _zones[cache_file.name] = data.get("timezone") if isinstance(data, dict) else None
    tz_name = _zones[cache_file.name]
    if tz_name and isinstance(tz_name, str):
        try:
            from zoneinfo import ZoneInfo
            return ZoneInfo(tz_name)
        except Exception as exc:
            log_failure("tz", f"lookup of {tz_name}", exc, fallback="machine timezone")
    return machine_tz
