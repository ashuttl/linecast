"""Shared CLI/runtime option helpers."""

import argparse
from dataclasses import dataclass
import os
import sys


# ---------------------------------------------------------------------------
# Debug logging
# ---------------------------------------------------------------------------
_DEBUG = False


def set_debug(value):
    global _DEBUG
    _DEBUG = bool(value)


def debug_enabled():
    """Whether --debug is on, for a caller whose message costs something
    to build."""
    return _DEBUG


def debug_log(msg):
    """Print a diagnostic message to stderr when --debug is active."""
    if _DEBUG:
        print(f"[linecast] {msg}", file=sys.stderr)


def redact_url(url: str) -> str:
    """The URL as a diagnostic may show it: scheme, host and path.

    Userinfo, query and fragment are removed.  The query is represented
    by ``?...`` so the reader can still tell that one was present.
    """
    from urllib.parse import urlsplit, urlunsplit
    try:
        parts = urlsplit(url)
    except ValueError:
        return "(unparseable URL)"
    host = parts.hostname or ""
    if ":" in host:
        host = f"[{host}]"  # an IPv6 literal, as it was written
    try:
        port = parts.port
    except ValueError:
        port = None
    if host and port is not None:
        host = f"{host}:{port}"
    query = "..." if parts.query else ""
    return urlunsplit((parts.scheme, host, parts.path, query, ""))


def _redact_urls_in_text(text: str) -> str:
    """Replace URL-like substrings with their diagnostic-safe form."""
    import re
    return re.sub(r"(?i)\b[a-z][a-z0-9+.-]*://[^\s<>\"']+",
                  lambda match: redact_url(match.group(0)), text)


def _host_of(where):
    """The host named by a URL, or the string itself when it is a bare
    host or a file name a caller passed instead of a URL."""
    from urllib.parse import urlsplit
    try:
        parts = urlsplit(where)
    except ValueError:
        return ""  # an unbalanced IPv6 bracket: name nothing, never raise
    if parts.hostname:
        return parts.hostname
    if parts.netloc or parts.scheme:
        return parts.scheme or ""
    # no scheme: a bare host, or a cache file's name
    return parts.path.split("/", 1)[0].rsplit("@", 1)[-1]


def log_failure(provider, operation, exc, url=None, fallback=None, trace=False):
    """One debug line for a failure the caller absorbed, in the house
    style:

        <provider>: <operation> failed (<host>) -- <ExcType>: <message>;
        <fallback>

    Only the URL's host is shown -- never its path, query, userinfo or
    any header. URL-like text in the exception and traceback is redacted,
    and the message is its first line cut at 120 characters, so a server's
    error page cannot spill the rest. Nothing is formatted, let alone
    printed, unless --debug is on: this runs inside the tile pools.

    `trace` follows the line with the traceback, still only with
    --debug on.  It is for a worker that died, not a request that
    failed: what a live view's WorkerWatch shows once the screen is
    back, so a --print run of the same command shows no less.
    """
    if not _DEBUG:
        return
    where = ""
    if url:
        host = _host_of(str(url))
        where = f" ({host})" if host else ""
    text = _redact_urls_in_text(str(exc))
    what = type(exc).__name__
    if text:
        what += ": " + text.splitlines()[0][:120]
    tail = f"; {fallback}" if fallback else ""
    debug_log(f"{provider}: {operation} failed{where} -- {what}{tail}")
    if trace and exc.__traceback__ is not None:
        import traceback
        rendered = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        sys.stderr.write(_redact_urls_in_text(rendered))


def log_skipped(provider, what, skipped, total, exc=None):
    """One debug line when parsing dropped records a provider sent, with
    the last exception standing in for the lot.  Nothing when nothing was
    dropped, so a loop can count skips and call this unconditionally:
    one bad record is a glitch, `40 of 40 skipped` is a schema change.
    """
    if not skipped or not _DEBUG:
        return
    tail = f"{skipped} of {total} skipped"
    if exc is None:
        debug_log(f"{provider}: parse of {what} failed -- {tail}")
    else:
        log_failure(provider, f"parse of {what}", exc, fallback=tail)


def install_banner():
    """A one-line install hint shown when running from a temporary venv (get.sh)."""
    if not os.environ.get("LINECAST_TEMP"):
        return ""
    from linecast._color import fg, RESET
    from linecast._theme import ensure_contrast, neutral_tone, theme_bg, theme_fg
    text = fg(*ensure_contrast(theme_fg, theme_bg, minimum=4.5))
    muted = fg(*ensure_contrast(neutral_tone(0.48), theme_bg, minimum=2.5))
    sep = f"{muted} \u00b7 "
    return f" {text}linecast{sep}{muted}pip install linecast{sep}github.com/ashuttl/linecast{RESET}"


def _environ(environ=None):
    return os.environ if environ is None else environ


def env_truthy(value):
    return str(value).lower() in ("1", "true", "yes")


# ---------------------------------------------------------------------------
# Units and clock preferences
# ---------------------------------------------------------------------------
_UNSET = object()  # "look the country up yourself" default for the resolvers

# argv[0] as the process started, before dispatch renames it to
# "linecast <command>"; `linecast link` needs the binary's own path.
INVOKED_AS = None


def default_units(country):
    """The units for a user who has expressed no preference."""
    return "imperial" if country == "US" else "metric"


# Countries where the 12-hour clock is the everyday written form: a
# timetable, a shop sign or a weather report there says 6:50 pm, not
# 18:50.  Everywhere else the 24-hour clock is the default.
TWELVE_HOUR_COUNTRIES = frozenset((
    "US", "CA", "AU", "NZ", "PH", "IN", "PK", "BD", "MY", "EG", "SA",
))


def default_clock(country=None):
    """The clock style for a user who has expressed no preference."""
    return "12" if country in TWELVE_HOUR_COUNTRIES else "24"


def resolve_units(namespace=None, environ=None, legacy_env="WEATHER_UNITS",
                  country=_UNSET):
    """The units for this run, and where they came from.

    Returns ("metric" | "imperial", source); source is "flag", the
    winning env var's name, "config", or "auto".  Precedence:
    --metric/--imperial flags, the command's own env var (WEATHER_UNITS /
    TIDES_UNITS), LINECAST_UNITS, the `units` key in config.json, then
    the default for *country* -- the user's own, looked up offline via
    own_country() unless the caller already knows it.
    """
    env = _environ(environ)
    if namespace is not None:
        if getattr(namespace, "imperial", False):
            return "imperial", "flag"
        if getattr(namespace, "metric", False):
            return "metric", "flag"
    for name in (legacy_env, "LINECAST_UNITS"):
        value = env.get(name, "").strip().lower()
        if value in ("metric", "imperial"):
            return value, name
    from linecast._config import saved_units
    saved = saved_units()
    if saved is not None:
        return saved, "config"
    if country is _UNSET:
        from linecast._location import own_country
        country = own_country()
    return default_units(country), "auto"


def resolve_clock(namespace=None, environ=None, country=_UNSET):
    """The clock style for this run, and where it came from.

    Returns ("12" | "24", source); source is "flag", "LINECAST_CLOCK",
    "config", or "auto".  Precedence: --12h/--24h flags, LINECAST_CLOCK,
    the `clock` key in config.json (`linecast clock 12|24`), then the
    default for *country*, looked up as resolve_units does.
    """
    env = _environ(environ)
    if namespace is not None and getattr(namespace, "clock", None) in ("12", "24"):
        return namespace.clock, "flag"
    value = env.get("LINECAST_CLOCK", "").strip()
    if value in ("12", "24"):
        return value, "LINECAST_CLOCK"
    from linecast._config import saved_clock
    saved = saved_clock()
    if saved is not None:
        return saved, "config"
    if country is _UNSET:
        from linecast._location import own_country
        country = own_country()
    return default_clock(country), "auto"


def units_pref(env_var="WEATHER_UNITS", environ=None):
    """The user's explicit units preference, or None if they have none.

    Precedence: the command's env var (WEATHER_UNITS / TIDES_UNITS), then
    LINECAST_UNITS, then the `units` key in config.json
    (`linecast units metric|imperial`).
    """
    value, source = resolve_units(None, environ, env_var, country=None)
    return None if source == "auto" else value


def use_metric():
    """The resolved units of the running command, for render helpers
    called without a runtime (radar and maps)."""
    return current_runtime().metric


# ---------------------------------------------------------------------------
# Argparse parser factories
# ---------------------------------------------------------------------------
class VersionAction(argparse.Action):
    """`--version` that looks the package version up only when asked.

    argparse's stock action wants the string at parser-build time, which
    would resolve importlib.metadata on every run of every command.
    """

    def __init__(self, option_strings, dest, **kwargs):
        super().__init__(option_strings, dest=argparse.SUPPRESS,
                         default=argparse.SUPPRESS, nargs=0,
                         help="show program's version number and exit")

    def __call__(self, parser, namespace, values, option_string=None):
        from linecast import __version__
        # `linecast weather --version` is linecast's version; a parser
        # under another name (a symlink's) says whose it is.
        if parser.prog.split()[0] == "linecast":
            sys.stdout.write(f"linecast {__version__}\n")
        else:
            sys.stdout.write(f"{parser.prog} (linecast {__version__})\n")
        parser.exit()


def _base_parser(prog, description):
    p = argparse.ArgumentParser(prog=prog, description=description)
    p.add_argument("--version", action=VersionAction)
    p.add_argument("--print", dest="print_mode", action="store_true",
                    help="single static snapshot (no live mode)")
    p.add_argument("--live", action="store_true",
                    help="force live mode (default when interactive)")
    p.add_argument("--oneline", action="store_true",
                    help="compact single-line output")
    p.add_argument("--icons", choices=("nerd", "emoji", "plain"), default=None,
                    help="icon set: Nerd Font glyphs, standard emoji, or "
                         "plain Unicode (default: nerd where the terminal "
                         "bundles the glyphs, emoji on other interactive "
                         "terminals, plain when piped or redirected)")
    p.add_argument("--emoji", action="store_true",
                    help="use standard emoji icons (same as --icons emoji)")
    p.add_argument("--lang", default=None,
                    help="UI language code (en, fr, es, de, it, pt, nl, pl, "
                         "no, sv, is, da, fi, id, ja, ko, zh)")
    p.add_argument("--classic-colors", action="store_true",
                    help="use pre-theme fixed color palette")
    p.add_argument("--legacy-colors", action="store_true",
                    help="alias for --classic-colors")
    p.add_argument("--debug", action="store_true",
                    help="show diagnostic info on stderr")
    return p


def _add_units_flags(p, metric_help, imperial_help):
    g = p.add_mutually_exclusive_group()
    g.add_argument("--metric", action="store_true", help=metric_help)
    g.add_argument("--imperial", action="store_true", help=imperial_help)


def _add_clock_flags(p):
    # explicit dest: "12h" is not a Python identifier
    g = p.add_mutually_exclusive_group()
    g.add_argument("--24h", dest="clock", action="store_const", const="24",
                    default=None, help="24-hour clock")
    g.add_argument("--12h", dest="clock", action="store_const", const="12",
                    help="12-hour clock")


def weather_parser():
    p = _base_parser("linecast weather",
                      "Terminal weather dashboard with braille temperature "
                      "curve and alerts")
    p.add_argument("--location", default=None,
                    help="location as 'lat,lng' or place name")
    p.add_argument("--search", default=None,
                    help="search for a location and exit")
    _add_units_flags(p, "metric units: celsius, km/h, mm",
                     "imperial units: fahrenheit, mph, inches")
    _add_clock_flags(p)
    p.add_argument("--celsius", action="store_true",
                    help="celsius temperatures only")
    p.add_argument("--fahrenheit", action="store_true",
                    help="fahrenheit temperatures")
    p.add_argument("--no-shading", action="store_true",
                    help="disable daylight shading on hourly chart")
    p.add_argument("--json", dest="json_mode", action="store_true",
                    help="machine-readable JSON output (implies --print)")
    return p


def tides_parser():
    p = _base_parser("linecast tides",
                      "Terminal tide chart with braille rendering")
    p.add_argument("--location", default=None,
                    help="find the nearest station to 'lat,lng' or a "
                         "place name instead of your location")
    p.add_argument("--station", default=None,
                    help="station ID or name (any provider)")
    p.add_argument("--search", nargs="?", const="", default=None,
                    help="search for a station and exit "
                         "(no query: list nearest stations)")
    p.add_argument("--nearby", action="store_true",
                    help="list the nearest tide stations and exit")
    _add_units_flags(p, "heights in meters",
                     "heights in feet")
    _add_clock_flags(p)
    p.add_argument("--json", dest="json_mode", action="store_true",
                    help="machine-readable JSON output (implies --print)")
    return p


def sunshine_parser():
    p = _base_parser("linecast sunshine",
                      "Solar arc inspired by the Apple Watch Solar face")
    p.add_argument("--location", default=None,
                    help="location as 'lat,lng' or place name")
    p.add_argument("--year", action="store_true",
                    help="year view: a column of sky for each day, with "
                         "sunrise and sunset as the day/night boundary")
    p.add_argument("--dst", action="store_true",
                    help="in the year view, plot each day in its own UTC "
                         "offset so clock changes show as steps (default: "
                         "the location's current offset all year)")
    _add_clock_flags(p)
    p.add_argument("--json", dest="json_mode", action="store_true",
                    help="machine-readable JSON output (implies --print)")
    return p


def moon_parser():
    p = _base_parser("linecast moon",
                      "Moon phase, illumination, and rise/set times")
    p.add_argument("--location", default=None,
                    help="location as 'lat,lng' or place name")
    _add_clock_flags(p)
    p.add_argument("--json", dest="json_mode", action="store_true",
                    help="machine-readable JSON output (implies --print)")
    return p


def radar_parser():
    p = _base_parser("linecast radar",
                      "Terminal weather radar over a braille basemap (US + global)")
    p.add_argument("--location", default=None,
                    help="location as 'lat,lng' or place name")
    p.add_argument("--search", default=None,
                    help="search for a location and exit")
    p.add_argument("--zoom", type=float, default=6.0,
                    help="degrees of latitude shown top-to-bottom (default 6)")
    p.add_argument("--theme", default=None,
                    help="radar colour theme. Drawn in the terminal: "
                         "terminal (default; your own palette), dusk, "
                         "ember, ink, marangai. Rendered by LibreWXR: dark-sky, "
                         "universal-blue, rainbow (classic radar look), "
                         "nexrad, original, titan, twc, meteored, "
                         "datameteo, viper, mrms, max-storm, black-white; "
                         "press t in live mode to pick interactively")
    p.add_argument("--layer", default=None,
                    help="display layer: radar (default) or satellite "
                         "(hourly cloud mosaic); press s in live mode "
                         "to toggle")
    p.add_argument("--layers", default=None,
                    help="condition layers to show, comma-separated: "
                         "temp (temperature tint), wind (speed/direction "
                         "arrows); press c/w in live mode to toggle")
    _add_units_flags(p, "metric units: celsius, kilometres",
                     "imperial units: fahrenheit, miles")
    _add_clock_flags(p)
    return p


def maps_parser():
    p = _base_parser("linecast maps",
                      "Street map and terrain map: vector streets, or "
                      "hillshaded elevation under braille coastlines")
    p.add_argument("--location", default=None,
                    help="location as 'lat,lng' or place name")
    p.add_argument("--search", default=None,
                    help="search for a location and exit")
    # the default is per view and resolved in maps.main(): a street map
    # opens on a neighbourhood, terrain on a region
    p.add_argument("--zoom", type=float, default=None,
                    help="degrees of latitude shown top-to-bottom "
                         "(default 0.05 in street view, 4 in terrain)")
    p.add_argument("--view", choices=("street", "terrain", "now"),
                    default="street",
                    help="vector street map or terrain relief (default "
                         "street); now opens the terrain planet with "
                         "daylight and clouds switched on")
    p.add_argument("--to", default=None,
                    help="route to a place or 'lat,lng' from the origin")
    p.add_argument("--from", dest="from_", metavar="FROM", default=None,
                    help="route from a place or 'lat,lng' "
                         "(default: your location)")
    p.add_argument("--profile", default="car",
                    help="how to travel: car, bike or foot (default car)")
    _add_units_flags(p, "metric units: kilometres and metres",
                     "imperial units: miles and feet")
    return p


def _log_startup():
    """The first line of a --debug transcript: which build, and where
    its files live."""
    import platform
    from linecast import __version__
    from linecast._config import config_file
    from linecast._paths import cache_root
    debug_log(f"linecast {__version__}, python {platform.python_version()}, "
              f"{sys.platform} {platform.machine()}; cache {cache_root()}; "
              f"settings {config_file()}")


def doctor_parser():
    """`linecast doctor` has none of the view flags, so it is not a
    _base_parser; --version is the same action."""
    p = argparse.ArgumentParser(
        prog="linecast doctor",
        description="Show where linecast keeps its files, what it sees of "
                    "the terminal, and which providers answer")
    p.add_argument("--version", action=VersionAction)
    p.add_argument("--offline", action="store_true",
                    help="skip the provider probes")
    p.add_argument("--json", dest="json_mode", action="store_true",
                    help="the same report as one JSON object, for bug reports")
    p.add_argument("--debug", action="store_true",
                    help="show diagnostic info on stderr")
    return p


# ---------------------------------------------------------------------------
# Live mode resolution
# ---------------------------------------------------------------------------
def _resolve_live(ns):
    """Live mode is on by default when stdout is a TTY.

    --print, --oneline and --json force static single-shot output.
    --live is accepted for backwards compatibility but is no longer needed.
    """
    # Not every command's parser defines --json (radar/maps), so getattr.
    if ns.print_mode or ns.oneline or getattr(ns, "json_mode", False):
        return False
    if ns.live:
        return True
    try:
        return sys.stdout.isatty() and sys.stdin.isatty()
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Runtime config dataclasses
# ---------------------------------------------------------------------------
ICON_SETS = ("nerd", "emoji", "plain")


def _interactive_utf8(stream):
    """Whether *stream* is an interactive UTF-8 terminal — the setting
    emoji are known to render in."""
    try:
        if not stream.isatty():
            return False
        return "utf" in (getattr(stream, "encoding", "") or "").lower()
    except Exception:
        return False


def default_icons(env, stream=None):
    """The icon set to assume when nothing was asked for.

    A terminal cannot be asked which font it renders with, so "does this
    user have a Nerd Font?" is unanswerable in general.  What is knowable:
    WezTerm, kitty (since 0.32) and Ghostty ship the Nerd Font symbols as
    a built-in fallback font, so the icons render there regardless of the
    configured font.

    Every other modern terminal draws emoji from a system fallback font,
    so an interactive UTF-8 stream gets the emoji set.  Plain Unicode is
    kept for the cases emoji cannot be trusted: output that is piped or
    redirected (stable single-cell widths, greppable), a stream whose
    encoding cannot carry emoji, TERM=dumb, and a console where no
    terminal identifies itself at all — TERM, TERM_PROGRAM and
    WT_SESSION all unset is the legacy Windows console, whose fonts
    have no emoji.
    """
    # A terminal's identity can remain in the environment after stdout is
    # redirected, so the stream wins first: automatic piped output is plain
    # regardless of which terminal launched the command.
    stream = sys.stdout if stream is None else stream
    if not _interactive_utf8(stream):
        return "plain"
    if env.get("TERM", "").lower() == "dumb":
        return "plain"

    # tmux and screen replace TERM_PROGRAM with their own name, so the
    # terminals' private variables, which the shell inherited before the
    # multiplexer started, are checked as well.
    if env.get("TERM_PROGRAM", "").lower() in ("wezterm", "ghostty"):
        return "nerd"
    if env.get("KITTY_WINDOW_ID") or env.get("WEZTERM_PANE") \
            or env.get("GHOSTTY_RESOURCES_DIR"):
        return "nerd"
    if not (env.get("TERM") or env.get("TERM_PROGRAM")
            or env.get("WT_SESSION")):
        return "plain"
    return "emoji"


def resolve_icons(namespace=None, environ=None):
    """The icon set for this run, and where it came from.

    Returns (set, source); source is "flag", "LINECAST_ICONS", "config"
    or "auto".  Precedence: --icons (and --emoji), LINECAST_ICONS, the
    `icons` key in config.json (`linecast icons nerd|emoji|plain`), then
    terminal detection.
    """
    env = _environ(environ)
    explicit = getattr(namespace, "icons", None)
    if explicit in ICON_SETS:
        return explicit, "flag"
    if getattr(namespace, "emoji", False):
        return "emoji", "flag"
    env_pref = env.get("LINECAST_ICONS", "").strip().lower()
    if env_pref in ICON_SETS:
        return env_pref, "LINECAST_ICONS"
    from linecast._config import saved_icons
    saved = saved_icons()
    if saved is not None:
        return saved, "config"
    return default_icons(env), "auto"


def _resolve_icons(namespace, env):
    return resolve_icons(namespace, env)[0]


@dataclass(frozen=True)
class RuntimeConfig:
    live: bool
    icons: str
    lang: str
    oneline: bool
    json_mode: bool = False  # machine-readable JSON output
    metric: bool = True      # resolved units, every command
    use_24h: bool = True     # resolved clock, every command

    # the parser whose defaults stand in before a main() has run
    _parser = staticmethod(lambda: _base_parser("linecast", ""))
    # the command's own units env var, before LINECAST_UNITS
    _legacy_units_env = "WEATHER_UNITS"

    @classmethod
    def from_sources(cls, namespace, environ=None, country=_UNSET):
        """Build the runtime from a parsed argparse namespace and the
        environment (os.environ unless *environ* is given).

        *country* feeds the units default; mains that have resolved the
        user's location call again with it (see resolve_units).
        """
        env = _environ(environ)
        if namespace.debug and not _DEBUG:
            set_debug(True)
            _log_startup()
        lang = (
            namespace.lang
            or env.get("LINECAST_LANG", "").strip()
            or "en"
        ).lower()[:2]
        units, _source = resolve_units(namespace, env, cls._legacy_units_env,
                                       country)
        clock, _source = resolve_clock(namespace, env, country)
        return cls(
            live=_resolve_live(namespace),
            icons=_resolve_icons(namespace, env),
            lang=lang if len(lang) == 2 and lang.isalpha() else "en",
            oneline=namespace.oneline,
            json_mode=getattr(namespace, "json_mode", False),
            metric=units == "metric",
            use_24h=clock == "24",
        )

    @classmethod
    def defaults(cls, environ=None):
        """The runtime with no flags given."""
        return cls.from_sources(cls._parser().parse_args([]), environ)


@dataclass(frozen=True)
class WeatherRuntime(RuntimeConfig):
    # Defaults required: the base class ends in defaulted fields.
    celsius: bool = True
    shading: bool = True

    _parser = staticmethod(weather_parser)

    @classmethod
    def from_sources(cls, namespace, environ=None, country=_UNSET):
        env = _environ(environ)
        base = RuntimeConfig.from_sources(namespace, env, country)
        # --celsius / --fahrenheit override temperature independently
        if namespace.fahrenheit:
            celsius = False
        else:
            celsius = namespace.celsius or base.metric
        return cls(
            live=base.live,
            icons=base.icons,
            lang=base.lang,
            oneline=base.oneline,
            celsius=celsius,
            metric=base.metric,
            use_24h=base.use_24h,
            shading=(not namespace.no_shading
                     and not env_truthy(env.get("WEATHER_NO_SHADING", ""))),
            json_mode=base.json_mode,
        )

    @property
    def temp_unit(self):
        return "\u00b0C" if self.celsius else "\u00b0F"

    @property
    def wind_unit(self):
        return "km/h" if self.metric else "mph"

    @property
    def precip_unit(self):
        return "mm" if self.metric else "\u2033"


@dataclass(frozen=True)
class TidesRuntime(RuntimeConfig):
    _parser = staticmethod(tides_parser)
    _legacy_units_env = "TIDES_UNITS"

    @property
    def height_unit(self):
        return "m" if self.metric else "\u2032"

    def convert_height(self, ft):
        return ft * 0.3048 if self.metric else ft


# ---------------------------------------------------------------------------
# The running command's runtime
# ---------------------------------------------------------------------------
_current = None


def set_current(runtime):
    """Record the runtime main() resolved, for current_runtime()."""
    global _current
    _current = runtime


def current_runtime(cls=RuntimeConfig):
    """The runtime the running command resolved in main(), for render
    helpers called without one.  Before a main() has run -- the tests, or
    a helper imported on its own -- it is *cls* with no flags given."""
    if isinstance(_current, cls):
        return _current
    return cls.defaults()
