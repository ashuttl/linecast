"""Show where linecast keeps its files, what it sees of the terminal, and
which providers answer.

Usage: linecast doctor [--offline] [--json]

The report is the first thing to ask for in a bug report: it says which
build is running, where the settings and the cache are and whether the
cache can be written, what the terminal advertised, which preferences
are in force and where each came from, every linecast-related
environment variable (secrets and locations shown as "(set)", URLs
without their userinfo or query), and one line per provider host saying
whether it answered.  --offline skips the probes;
--json prints the same information as one object with stable keys.
"""

import json
import os
import platform
import re
import sys
from pathlib import Path

from linecast._runtime import doctor_parser, set_debug

PROBE_TIMEOUT = 4        # seconds per host; every probe runs at once
_PROBE_GRACE = 1         # seconds past that before a probe is given up on
_WALK_LIMIT = 50_000     # cache entries counted before the walk gives up
_SECRET_WORDS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "LOCATION")
_ENV_NAMES = re.compile(r"^(LINECAST_|WEATHER_|TIDES_|TIDE_STATION$|XDG_.*_HOME$"
                        r"|NO_COLOR$|CLICOLOR)")


# ---------------------------------------------------------------------------
# The providers, each with a URL that answers cheaply
# ---------------------------------------------------------------------------
def _root(url):
    """scheme://host/ of a URL, the port kept and any userinfo dropped:
    an override's credential never reaches the report."""
    from urllib.parse import urlsplit, urlunsplit
    from linecast._http import redact_url
    try:
        parts = urlsplit(url)
    except ValueError:
        return url  # the probe will say what is wrong with it
    return redact_url(urlunsplit((parts.scheme, parts.netloc, "/", "", "")))


def _hostname(url):
    from urllib.parse import urlsplit
    try:
        return urlsplit(url).hostname
    except ValueError:
        return None


def providers():
    """(name, url) for every host a command may talk to, honouring the
    URL overrides.  TideCheck's url is None until a key is configured.
    A 4xx from a host root is still a host that answers."""
    from linecast._builtup import DEFAULT_URL as BUILTUP_URL
    from linecast._elevation import tile_url as elevation_tile_url
    from linecast._maps_route import _FALLBACK as OSRM_FALLBACK, _PRIMARY as OSRM_PRIMARY
    from linecast._maps_search import NOMINATIM_URL, PHOTON_URL
    from linecast._radar_tiles import LIBREWXR_DEFAULT_URL
    from linecast._tides_chs import CHS_BASE
    from linecast._tides_hko import HKO_BASE
    from linecast._tides_qld import QLD_BASE
    from linecast._tides_tidecheck import TIDECHECK_BASE, is_available
    from linecast._vtiles import DEFAULT_TILEJSON_URL, FALLBACK_TILEJSON_URL
    env = os.environ
    return [
        ("Open-Meteo forecast", "https://api.open-meteo.com/"),
        ("Open-Meteo geocoder", "https://geocoding-api.open-meteo.com/"),
        ("Open-Meteo marine", "https://marine-api.open-meteo.com/"),
        ("Open-Meteo archive", "https://archive-api.open-meteo.com/"),
        ("Open-Meteo air quality", "https://air-quality-api.open-meteo.com/"),
        ("NWS alerts", "https://api.weather.gov/"),
        ("MetService alerts", "https://alerts.metservice.com/"),
        ("ipinfo geolocation", "https://ipinfo.io/"),
        ("ipwho geolocation (fallback)", "https://ipwho.is/"),
        ("GeoJS geolocation (fallback)", "https://get.geojs.io/"),
        ("NOAA CO-OPS tides", "https://api.tidesandcurrents.noaa.gov/"),
        ("CHS tides", _root(CHS_BASE)),
        ("Queensland tides", _root(QLD_BASE)),
        ("HKO tides and warnings", _root(HKO_BASE)),
        ("TideCheck tides", _root(TIDECHECK_BASE) if is_available() else None),
        ("IEM radar and warnings", "https://mesonet.agron.iastate.edu/"),
        ("RainViewer radar", "https://api.rainviewer.com/"),
        ("LibreWXR radar and clouds",
         _root(env.get("LINECAST_LIBREWXR_URL") or LIBREWXR_DEFAULT_URL)),
        ("OpenFreeMap streets",
         _root(env.get("LINECAST_VECTOR_TILES_URL") or DEFAULT_TILEJSON_URL)),
        # an override is the user's chosen source and gets no fallback
        ("OSM US streets (fallback)",
         None if env.get("LINECAST_VECTOR_TILES_URL")
         else _root(FALLBACK_TILEJSON_URL)),
        # the bucket root is a listing of every tile; z0 is one small tile
        ("AWS terrain tiles", elevation_tile_url(0, 0, 0)),
        ("built-up raster", _root(env.get("LINECAST_BUILTUP_URL") or BUILTUP_URL)),
        ("Photon search", _root(PHOTON_URL)),
        ("Nominatim search", _root(NOMINATIM_URL) + "status"),
        ("OSRM routing", _root(OSRM_PRIMARY)),
        ("OSRM routing (fallback)", _root(OSRM_FALLBACK)),
    ]


def _tidecheck_budget():
    """Where today's TideCheck requests stand, or None without a key."""
    from linecast._tides_tidecheck import budget_line
    return budget_line()


def probe(url, timeout=PROBE_TIMEOUT):
    """(ok, status) for one host: "ok", "ok (HTTP 404)", or the failure
    in a word or two."""
    import socket
    import ssl
    from linecast._http import HTTPError, fetch_bytes
    try:
        fetch_bytes(url, timeout=timeout, limit=1024 * 1024)
        return True, "ok"
    except HTTPError as exc:
        return True, f"ok (HTTP {exc.code})"
    except socket.gaierror:
        return False, "dns failed"
    except (socket.timeout, TimeoutError):
        return False, "timed out"
    except ConnectionRefusedError:
        return False, "refused"
    except ssl.SSLError:
        return False, "tls failed"
    except ValueError as exc:
        if "exceeds cap" in str(exc):
            return True, "ok (large response)"  # it answered, at length
        return False, f"bad url ({exc})"
    except OSError as exc:
        return False, f"unreachable ({type(exc).__name__})"
    except Exception as exc:
        return False, f"failed ({type(exc).__name__})"


def probe_all(hosts, timeout=PROBE_TIMEOUT):
    """[{name, host, url, ok, status}] with every probe in flight at once
    and one deadline over the lot, so the whole check takes one timeout,
    not one per host.  The probe gets the URL as configured; the record
    carries it redacted.

    The socket timeout bounds the connect and the read, not the name
    lookup before them: with the resolver unreachable, getaddrinfo
    blocks for as long as libc allows.  So the probes run on daemon
    threads that are joined against the deadline and left behind if
    still running -- a worker pool would be joined again at exit, and
    Ctrl-C along with the report would wait on the resolver.
    """
    import threading
    import time
    from linecast._http import redact_url

    def record(name, url, ok, status):
        return {"name": name, "host": _hostname(url), "url": redact_url(url),
                "ok": ok, "status": status}

    results = [None] * len(hosts)

    def one(i, name, url):
        results[i] = record(name, url, *probe(url, timeout))

    threads = []
    for i, (name, url) in enumerate(hosts):
        if url is None:
            results[i] = {"name": name, "host": None, "url": None, "ok": None,
                          "status": "not configured"}
            continue
        thread = threading.Thread(target=one, args=(i, name, url), daemon=True,
                                  name=f"probe-{i}")
        thread.start()
        threads.append(thread)
    deadline = time.monotonic() + timeout + _PROBE_GRACE
    for thread in threads:
        thread.join(max(0.0, deadline - time.monotonic()))
    for i, (name, url) in enumerate(hosts):
        if results[i] is None:
            results[i] = record(name, url, False, "timed out (dns)")
    return results


# ---------------------------------------------------------------------------
# The cache directory
# ---------------------------------------------------------------------------
def cache_writable(root):
    """(writable, reason) by creating and removing a file under root.

    A root that does not exist yet is created for the test and removed
    again, level by level, so nothing is left behind.
    """
    created = []
    path = Path(root)
    try:
        missing = []
        probe = path
        while not probe.exists():
            missing.append(probe)
            if probe.parent == probe:
                break
            probe = probe.parent
        for level in reversed(missing):
            level.mkdir()
            created.append(level)
        marker = path / f".doctor-{os.getpid()}.tmp"
        marker.write_bytes(b"")
        marker.unlink()
        return True, ""
    except OSError as exc:
        return False, exc.strerror or type(exc).__name__
    finally:
        for level in reversed(created):
            try:
                level.rmdir()
            except OSError:
                pass


def cache_usage(root, limit=_WALK_LIMIT):
    """(files, bytes, complete): a bounded walk of the cache."""
    files = size = 0
    stack = [str(root)]
    while stack:
        try:
            with os.scandir(stack.pop()) as entries:
                for entry in entries:
                    if entry.is_dir(follow_symlinks=False):
                        stack.append(entry.path)
                        continue
                    try:
                        size += entry.stat(follow_symlinks=False).st_size
                    except OSError:
                        continue
                    files += 1
                    if files >= limit:
                        return files, size, False
        except OSError:
            continue
    return files, size, True


def _human(n):
    for unit in ("B", "kB", "MB", "GB"):
        if n < 1000 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1000
    return f"{n:.1f} GB"


# ---------------------------------------------------------------------------
# Collecting the report
# ---------------------------------------------------------------------------
def _collect_paths():
    from linecast._config import (
        config_file, read_config, saved_clock, saved_icons, saved_language,
        saved_location, saved_units,
    )
    from linecast._paths import cache_root
    settings = config_file()
    # os.path, not Path.exists/is_dir: before Python 3.14 those raise
    # on a parent this process cannot search, which is one of the
    # setups the report exists to describe
    settings_exists = os.path.exists(settings)
    keys = []
    if settings_exists:
        config = read_config()
        loc = saved_location()
        if loc is not None:
            keys.append("location")
        if saved_language() is not None:
            keys.append("language")
        if saved_units() is not None:
            keys.append("units")
        if saved_clock() is not None:
            keys.append("clock")
        if saved_icons() is not None:
            keys.append("icons")
        keys.extend(sorted(k for k in config
                           if k not in ("location", "language", "units",
                                        "clock", "icons")))
    root = cache_root()
    exists = os.path.isdir(root)
    writable, reason = cache_writable(root)
    files, size, complete = cache_usage(root) if exists else (0, 0, True)
    # Map tiles are the part that grows without being asked to, and the
    # only part under a cap, so doctor reports it separately.
    from linecast._maps_tile_cache import cache_limit_bytes
    maps_root = root / "maps"
    _mfiles, maps_size, _mcomplete = (
        cache_usage(maps_root) if os.path.isdir(maps_root) else (0, 0, True))
    legacy = (sys.platform == "darwin"
              and root == Path.home() / ".cache" / "linecast")
    return {
        "settings_file": str(settings),
        "settings_exists": settings_exists,
        "settings_keys": keys,
        "cache_dir": str(root),
        "cache_exists": exists,
        "cache_writable": writable,
        "cache_writable_reason": reason,
        "cache_files": files,
        "cache_bytes": size,
        "cache_count_complete": complete,
        "cache_legacy_location": legacy,
        "maps_cache_bytes": maps_size,
        "maps_cache_limit": cache_limit_bytes(),
    }


def _collect_terminal():
    import shutil
    from linecast import _color, _theme
    from linecast._runtime import RuntimeConfig, resolve_icons
    env = os.environ
    _theme.ensure_theme_loaded()  # no OSC probe unless stdout is a tty
    theme_env = env.get("LINECAST_THEME", "").strip()
    tty = _is_tty(sys.stdout)
    if theme_env:
        theme = f"{theme_env} (LINECAST_THEME)"
    elif _theme.theme_legacy_mode:
        theme = "fixed palette (--classic-colors)"
    elif _theme.theme_available:
        theme = "terminal palette (probed)"
    elif not tty:
        theme = "fixed palette (not probed: stdout is not a tty)"
    else:
        theme = "fixed palette (the terminal did not answer the probe)"
    size = shutil.get_terminal_size(fallback=(0, 0))
    runtime = RuntimeConfig.defaults()
    icon_set, icon_source = resolve_icons(None, env)
    if icon_source != "auto":
        icons = f"{icon_set} ({icon_source})"
    elif icon_set == "nerd":
        icons = "nerd font (this terminal bundles the glyphs)"
    elif icon_set == "emoji":
        icons = ("emoji (interactive terminal; run 'linecast icons nerd' "
                 "if your font is a Nerd Font)")
    elif not tty:
        icons = "plain (stdout is not a tty)"
    else:
        icons = ("plain (this console is not known to draw emoji; "
                 "'linecast icons' picks a set)")
    return {
        "term": env.get("TERM", ""),
        "colorterm": env.get("COLORTERM", ""),
        "color_mode": _color.color_mode(),
        "columns": size.columns,
        "lines": size.lines,
        "stdout_tty": _is_tty(sys.stdout),
        "icons": icons,
        "theme": theme,
        "lang": runtime.lang,
    }


def _is_tty(stream):
    try:
        return bool(stream.isatty())
    except Exception:
        return False


def _collect_preferences():
    from linecast._config import saved_location
    from linecast._location import own_country
    from linecast._runtime import resolve_clock, resolve_units
    env = os.environ
    country = own_country()

    def units(legacy_env):
        value, source = resolve_units(None, env, legacy_env, country)
        if source == "auto" and country:
            source = f"auto: {country}"
        return value, source

    weather, weather_source = units("WEATHER_UNITS")
    tides, tides_source = units("TIDES_UNITS")
    clock, clock_source = resolve_clock(None, env, country)
    override = env.get("WEATHER_LOCATION", "").strip()
    loc = saved_location()
    if override:
        location, location_source = "(set)", "WEATHER_LOCATION"
    elif loc is not None:
        location, location_source = "(set)", "config"
    else:
        location, location_source = "auto (IP geolocation)", "auto"
    from linecast._runtime import resolve_lang
    language, language_source = resolve_lang(None, env)
    from linecast._config import saved_calendar
    from linecast._lunisolar import CALENDAR_OF_LANG
    saved_cal = saved_calendar()
    if saved_cal is not None:
        calendar, calendar_source = saved_cal, "config"
    else:
        native = CALENDAR_OF_LANG.get(language)
        calendar = native or "none"
        calendar_source = f"auto: {language}" if native else "auto"
    from linecast._config import saved_culture
    from linecast._sky_catalogue import CULTURE_OF_LANG
    saved_culture_ = saved_culture()
    if saved_culture_ is not None:
        culture, culture_source = saved_culture_, "config"
    else:
        native = CULTURE_OF_LANG.get(language)
        culture = native or "none"
        culture_source = f"auto: {language}" if native else "auto"
    return {
        "units": weather,
        "units_source": weather_source,
        "tides_units": tides,
        "tides_units_source": tides_source,
        "clock": f"{clock}-hour",
        "clock_source": clock_source,
        "location": location,
        "location_source": location_source,
        "language": language,
        "language_source": language_source,
        "calendar": calendar,
        "calendar_source": calendar_source,
        "culture": culture,
        "culture_source": culture_source,
    }


def _collect_environment():
    """Every variable linecast reads that is set, secrets as "(set)" and
    any URL -- a proxy, an override, whatever else has a scheme --
    without its userinfo or query."""
    from linecast._http import redact_url
    shown = {}
    for name in sorted(os.environ):
        value = os.environ[name]
        low = name.lower()
        if not (_ENV_NAMES.match(name) or low.endswith("_proxy")):
            continue
        if any(word in name.upper() for word in _SECRET_WORDS):
            shown[name] = "(set)"
        elif (low.endswith(("_proxy", "_url")) and low != "no_proxy") or "://" in value:
            shown[name] = redact_url(value)
        else:
            shown[name] = value
    return shown


def collect(offline=False):
    """The whole report as one dict; the keys are the JSON contract."""
    from linecast import __version__
    report = {
        "linecast": {
            "version": __version__,
            "python": platform.python_version(),
            "platform": sys.platform,
            "machine": platform.machine(),
            "temporary_install": bool(os.environ.get("LINECAST_TEMP")),
        },
        "paths": _collect_paths(),
        "terminal": _collect_terminal(),
        "preferences": _collect_preferences(),
        "environment": _collect_environment(),
        "providers": None if offline else probe_all(providers()),
        "tidecheck_budget": _tidecheck_budget(),
    }
    return report


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------
def _section(title, rows):
    width = max((len(label) for label, _ in rows), default=0)
    lines = [title]
    for label, value in rows:
        lines.append(f"  {label:<{width}}  {value}")
    return lines


def render(report):
    """The report as aligned plain text."""
    lc = report["linecast"]
    paths = report["paths"]
    term = report["terminal"]
    prefs = report["preferences"]
    rows = [
        ("version", lc["version"]),
        ("python", lc["python"]),
        ("platform", f"{lc['platform']} {lc['machine']}"),
    ]
    if lc["temporary_install"]:
        rows.append(("install", "temporary (get.sh); `pip install linecast` to keep it"))
    out = _section("linecast", rows)

    if paths["settings_exists"]:
        keys = ", ".join(paths["settings_keys"]) or "no keys"
        settings = f"{paths['settings_file']}  (exists; {keys})"
    else:
        settings = f"{paths['settings_file']}  (not created yet)"
    if paths["cache_exists"]:
        count = f"{paths['cache_files']:,}"
        if not paths["cache_count_complete"]:
            count = "more than " + count
        state = f"exists; {count} files, {_human(paths['cache_bytes'])}"
    else:
        state = "not created yet"
    if paths["cache_writable"]:
        state += "; writable"
    else:
        state += f"; NOT writable ({paths['cache_writable_reason']})"
    cache = f"{paths['cache_dir']}  ({state})"
    rows = [("settings", settings), ("cache", cache)]
    if paths["cache_exists"] and paths["maps_cache_bytes"]:
        rows.append(("map tiles",
                     f"{_human(paths['maps_cache_bytes'])} of that "
                     f"(cap {_human(paths['maps_cache_limit'])}, swept "
                     "when maps starts)"))
    if paths["cache_legacy_location"]:
        rows.append(("", "the older location; ~/Library/Caches/linecast "
                         "takes over once this one is removed"))
    out += [""] + _section("paths", rows)

    size = (f"{term['columns']}x{term['lines']}" if term["columns"]
            else "unknown (not a terminal)")
    rows = [
        ("TERM", term["term"] or "(unset)"),
        ("COLORTERM", term["colorterm"] or "(unset)"),
        ("colour", term["color_mode"]
         + ("" if term["stdout_tty"] else " (stdout is not a tty)")),
        ("size", size),
        ("icons", term["icons"]),
        # one glyph from each set; whichever renders as a box is missing
        ("glyph check", "nerd \U000F0599  emoji ☀️  plain ☀"),
        ("theme", term["theme"]),
    ]
    out += [""] + _section("terminal", rows)

    units = f"{prefs['units']} ({prefs['units_source']})"
    if (prefs["tides_units"], prefs["tides_units_source"]) != (
            prefs["units"], prefs["units_source"]):
        units += f"; tides {prefs['tides_units']} ({prefs['tides_units_source']})"
    rows = [
        ("units", units),
        ("clock", f"{prefs['clock']} ({prefs['clock_source']})"),
        ("location", prefs["location"]
         + ("" if prefs["location_source"] == "auto"
            else f" ({prefs['location_source']})")),
        ("language", f"{prefs['language']} ({prefs['language_source']})"),
        ("calendar", f"{prefs['calendar']} ({prefs['calendar_source']})"),
        ("culture", f"{prefs['culture']} ({prefs['culture_source']})"),
    ]
    out += [""] + _section("preferences", rows)

    env = report["environment"]
    out += ["", "environment"]
    if env:
        out += [f"  {name}={value}" for name, value in env.items()]
    else:
        out.append("  (nothing set)")

    hosts = report["providers"]
    out += ["", "providers"]
    if hosts is None:
        out.append("  skipped (--offline)")
    else:
        width = max(len(h["name"]) for h in hosts)
        hwidth = max(len(h["host"] or "") for h in hosts)
        for h in hosts:
            out.append(f"  {h['name']:<{width}}  {h['host'] or '':<{hwidth}}  {h['status']}")
    if report.get("tidecheck_budget"):
        out.append(f"  {report['tidecheck_budget']}")
    return "\n".join(out)


def main():
    args = doctor_parser().parse_args()
    if args.debug:
        set_debug(True)
    report = collect(offline=args.offline)
    if args.json_mode:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(render(report))


if __name__ == "__main__":
    main()
